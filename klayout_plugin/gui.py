"""KLayout desktop menu and history dialog (embedded pya Python only).

The source LayoutView is read only. Reviews open a separate temporary OASIS tab;
they never replace, recolor, save, or edit the designer's current layout.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from layoutdiff.data.core import empty_snapshot
from layoutdiff.data.history import History, read_json
from .codec import capture_layout, write_layout
from .review import build_review, configure_view, load_style, review_counts

_controller = None


def _get(obj, name):
    value = getattr(obj, name)
    return value() if callable(value) else value


class Controller:
    def __init__(self, pya):
        self.pya = pya
        self.window = pya.Application.instance().main_window()
        self.actions, self.dialogs, self.temps = [], [], []
        self.style = load_style()
        self.history_path = ""

    def _guard(self, function):
        def run(*_):
            try:
                function()
            except Exception as exc:
                self.pya.MessageBox.warning("Analog Layout Diff", str(exc), self.pya.MessageBox.Ok)
        return run

    def install(self):
        menu = self.window.menu()
        menu.insert_menu("tools_menu.end", "analog_layout_diff", "Analog Layout Diff")
        for name, title, callback in [
            ("capture", "Capture selected cell to JSON...", self.capture),
            ("history", "Commit / history / review...", self.history_dialog),
            ("style", "Load review colors and styles...", self.choose_style),
        ]:
            action = self.pya.Action()
            action.title = title
            action.on_triggered = self._guard(callback)
            self.actions.append(action)  # Keep Python actions alive.
            menu.insert_item("tools_menu.analog_layout_diff.end", name, action)

    def current(self):
        view = self.window.current_view()
        if view is None:
            raise ValueError("Open a GDS/OAS layout and select a cell first")
        cv = view.active_cellview()
        if not cv.is_valid() or cv.cell is None:
            raise ValueError("Select a cell in the active layout")
        layout = cv.layout()
        if layout.property("layoutdiff.review"):
            raise ValueError("This is a generated review. Select the source layout tab to capture/commit.")
        return layout, cv.cell

    def capture(self):
        # Capture first, so a bad/unsupported source fails before prompting for a path.
        layout, cell = self.current()
        snapshot = capture_layout(layout, cell.name)
        path = self.pya.QFileDialog.getSaveFileName(self.window, "New canonical snapshot", "", "JSON (*.json)")
        if path:
            from .__main__ import _new_json
            _new_json(path, snapshot)

    def choose_style(self):
        path = self.pya.QFileDialog.getOpenFileName(self.window, "Review style JSON", "", "JSON (*.json)")
        if path:
            self.style = load_style(path)

    def open_review(self, before, after, *, pair_changes=True):
        layout, _, report = build_review(before, after, pair_changes=pair_changes)
        # Retain temporary directories until KLayout exits; a loaded tab can still
        # need its backing file. This is a generated layout, never the source.
        temp = tempfile.TemporaryDirectory(prefix="analog-layout-diff-")
        self.temps.append(temp)
        path = Path(temp.name) / "review.oas"
        layout.write(str(path))
        self.window.load_layout(str(path), 1)  # mode 1 = new view/tab; returns CellView
        view = self.window.current_view()
        configure_view(view, report, self.style, cellview=_get(view, "active_cellview_index"))
        view.zoom_fit()
        return report

    def history_dialog(self):
        pya = self.pya
        dialog = pya.QDialog(self.window)
        dialog.windowTitle = "Analog Layout Diff — commit and history"
        dialog.resize(900, 540)
        box = pya.QVBoxLayout(dialog)
        box.addWidget(pya.QLabel("Capture reads the selected cell and reachable static hierarchy, including unsaved edits."))
        row = pya.QHBoxLayout()
        history = pya.QLineEdit(self.history_path)
        browse = pya.QPushButton("Choose history...")
        create = pya.QPushButton("Initialize new history...")
        row.addWidget(history); row.addWidget(browse); row.addWidget(create)
        box.addLayout(row)
        revisions = pya.QListWidget()
        box.addWidget(revisions)
        message = pya.QLineEdit()
        message.placeholderText = "Commit message"
        box.addWidget(message)
        pair = pya.QCheckBox("Infer a changed pair only for one compatible unmatched before/after object")
        pair.checked = True
        box.addWidget(pair)
        box.addWidget(pya.QLabel("Review opens AFTER geometry; red hollow ghosts show removals and old changed positions."))
        buttons = pya.QHBoxLayout()
        refresh = pya.QPushButton("Refresh")
        commit = pya.QPushButton("Commit selected source cell")
        working = pya.QPushButton("Review source vs HEAD")
        selected = pya.QPushButton("Review revision vs parent")
        restore = pya.QPushButton("Export revision to NEW OAS...")
        for button in [refresh, commit, working, selected, restore]:
            buttons.addWidget(button)
        box.addLayout(buttons)
        status = pya.QLabel("Choose or initialize a history.")
        status.wordWrap = True
        box.addWidget(status)
        state = {"chain": []}

        def get_history():
            path = str(_get(history, "text")).strip()
            if not path:
                raise ValueError("Choose a history directory")
            self.history_path = path
            return History(path)

        def reload_history():
            h = get_history()
            h.replay()  # Verify stored history before showing revisions.
            state["chain"] = list(reversed(h.chain()))
            revisions.clear()
            for item in state["chain"]:
                revisions.addItem(item["id"][:16] + "  " + item["message"])
            if state["chain"]:
                revisions.setCurrentRow(0)
            status.text = f"{len(state['chain'])} verified revisions. Full IDs are stored in commits/<SHA256>.json."

        def choose_history():
            path = pya.QFileDialog.getExistingDirectory(dialog, "Existing history", self.history_path)
            if path:
                history.text = path
                reload_history()

        def init_history():
            # Select a parent, then create a named NEW child; never initialize an
            # arbitrary populated design directory by accident.
            parent = pya.QFileDialog.getExistingDirectory(dialog, "Parent for new history", "")
            if not parent:
                return
            name = pya.QInputDialog.getText(dialog, "New history", "New directory name:")
            if not name:
                return
            if Path(name).name != name or name in {".", ".."}:
                raise ValueError("Use one new directory name")
            path = Path(parent) / name
            if path.exists():
                raise FileExistsError("New history directory already exists")
            History(path).init()
            history.text = str(path)
            reload_history()

        def do_commit():
            h = get_history()
            expected = read_json(h.path / "HEAD")
            msg = str(_get(message, "text")).strip()
            if not msg:
                raise ValueError("Enter a commit message")
            layout, cell = self.current()
            result = h.commit(capture_layout(layout, cell.name), msg, expected_head=expected)
            reload_history()
            status.text = "Committed " + result["id"] if result else "No changes; no commit written."

        def working_review():
            h = get_history()
            before = h.replay()
            layout, cell = self.current()
            report = self.open_review(before, capture_layout(layout, cell.name), pair_changes=bool(_get(pair, "checked")))
            status.text = str(review_counts(report)) + " | Changed = unique-pair inference."

        def revision():
            row = int(_get(revisions, "currentRow"))
            if not 0 <= row < len(state["chain"]):
                raise ValueError("Select a revision")
            return state["chain"][row]

        def selected_review():
            h, rev = get_history(), revision()
            after = h.replay(rev["id"])
            before = h.replay(rev["parent"]) if rev["parent"] else empty_snapshot()
            report = self.open_review(before, after, pair_changes=bool(_get(pair, "checked")))
            status.text = rev["id"] + " | " + str(review_counts(report))

        def export_revision():
            h, rev = get_history(), revision()
            path = pya.QFileDialog.getSaveFileName(dialog, "NEW static layout (existing files refused)", "", "OASIS (*.oas)")
            if path:
                write_layout(h.replay(rev["id"]), path)
                status.text = "Exported static revision to " + path

        for button, callback in [(browse, choose_history), (create, init_history),
                                 (refresh, reload_history), (commit, do_commit),
                                 (working, working_review), (selected, selected_review),
                                 (restore, export_revision)]:
            button.clicked.connect(self._guard(callback))
        # Keep callbacks and widgets alive for the nonmodal dialog lifetime.
        self.dialogs.append((dialog, state, [get_history, reload_history, choose_history,
                                           init_history, do_commit, working_review,
                                           revision, selected_review, export_revision]))
        if self.history_path:
            self._guard(reload_history)()
        dialog.show()


def install():
    """Idempotent for repeated runs of the autorun macro in one Python session."""
    global _controller
    if _controller is None:
        import pya
        if not hasattr(pya, "Application"):
            raise RuntimeError("GUI macro requires desktop KLayout with Python support")
        _controller = Controller(pya)
        _controller.install()
    return _controller
