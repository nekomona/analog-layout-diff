"""Virtuoso toolbar worker with explicit save/preview/Git and native review UI."""
from __future__ import annotations
import copy
import json
import os
import re
import struct
import time
import uuid
import zlib
import tempfile
import contextlib
import shlex
import shutil
from pathlib import Path
from layoutdiff.data.core import digest
from layoutdiff.data.history import History, read_json, atomic_json
from layoutdiff.comparison.review import classify, VISUAL
from layoutdiff.eda.virtuoso.sexpr import dumps as sk, loads
from layoutdiff.eda.virtuoso.adapter import VirtuosoAdapter, checked, coverage
from layoutdiff.eda.virtuoso.support import UnsupportedContentError
from layoutdiff.eda.virtuoso.paths import scratch
import layoutdiff.git.commit as gitcommit
import layoutdiff.git.store as gitstore
from layoutdiff.ui.browser import HistoryBrowser, RepositoryBrowser, field_text, diff_html
from layoutdiff.comparison.categories import CategoryDiff, snapshot_changes

COLORS = {"Gray": (150, 163, 180), "Orange": (255, 165, 0), "Green": (64, 235, 125),
          "Cyan": (0, 220, 255), "Magenta": (240, 90, 240), "Yellow": (255, 240, 40),
          "Blue": (90, 140, 255), "Red": (255, 70, 70)}
LINES = {"Solid": [1], "Dashed": [1, 1, 1, 1, 0, 0], "Dotted": [1, 0, 0],
         "Dash-dot": [1, 1, 1, 0, 0, 1, 0, 0]}
DEFAULTS = {"untouched": ["Gray", "Solid", "1", "Steady"], "changed": ["Orange", "Dashed", "3", "Steady"],
            "moved": ["Cyan", "Solid", "3", "Steady"],
            "netChanged": ["Blue", "Dotted", "3", "Steady"], "new": ["Green", "Solid", "3", "Steady"],
            "deleted": ["Red", "Dashed", "3", "Steady"],
            "groupNew": ["Green", "Dash-dot", "3", "Steady"],
            "groupChanged": ["Yellow", "Dash-dot", "3", "Steady"],
            "groupDeleted": ["Red", "Dashed", "3", "Steady"]}

TASK_LABELS = {
    'review': 'Preparing layout review...',
    'restore-prepare': 'Preparing and verifying checkpoint...',
    'restore-apply': 'Restoring layout checkpoint...',
    'quick-preview': 'Reading the saved layout and preparing the commit preview...',
    'git-setup': 'Configuring Git and preparing the commit preview...',
    'quick-commit': 'Verifying the preview and committing to Git...',
    'quick-omit-confirm': 'Verifying the preview and committing to Git...',
    'history': 'Loading cell history...', 'browser': 'Loading cell history...',
    'repository': 'Loading Git history...', 'repository-select': 'Loading changed cells...',
    'repository-cell': 'Computing layout changes...', 'browser-select': 'Computing layout changes...',
    'browser-full': 'Preparing the full diff...', 'quick-full': 'Preparing the full diff...',
    'browser-file': 'Loading the file diff...', 'browser-category': 'Loading change details...',
    'cleanup': 'Cleaning temporary reviews...',
}
POPUP_TASKS = {'quick-preview', 'quick-commit', 'quick-omit-confirm', 'git-setup'}


def style_settings(settings):
    settings = list(settings)
    if len(settings) == 3:
        settings.append('Steady')  # Migrate existing user styles without losing choices.
    if (len(settings) != 4 or settings[0] not in COLORS or settings[1] not in LINES
            or settings[2] not in {'1', '2', '3', '5'} or settings[3] not in {'Steady', 'Blink'}):
        raise ValueError('Invalid highlight style')
    return settings


def swatch(rgb):
    """Small PNG toolbar icon; no graphics package required."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    rows = b"".join(b"\0" + bytes(rgb) * 18 for _ in range(18))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 18, 18, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


def display_resource(packet, settings):
    color, line, width, _mode = style_settings(settings)
    # Names are generated internally, not interpreted user input.
    r, g, b = COLORS[color]
    pattern = " ".join(map(str, LINES[line]))
    # Window highlight sets ignore the DRF blink bit on some displays. The UI
    # timer animates set visibility, independently of line pattern and color.
    return (f'drDefineColor((display {packet}Color {r} {g} {b} nil))\n'
            f'drDefineStipple((display {packet}Blank ((0))))\n'
            f'drDefineLineStyle((display {packet}Line {width} ({pattern})))\n'
            f'drDefinePacket((display {packet} {packet}Blank {packet}Line {packet}Color {packet}Color))\n')


class GuiWorker:
    def __init__(self, client, root, *, review_library="LAYOUT_DIFF_TEST"):
        self.client = client
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.token = uuid.uuid4().hex
        self.adapter = VirtuosoAdapter(client, self.root / "artifacts", writable_library=review_library)
        self.review_library = review_library
        self.styles = copy.deepcopy(DEFAULTS)
        if (self.root / 'styles.json').exists():
            saved_styles = read_json(self.root / 'styles.json')
            self.styles.update({k: style_settings(v) for k, v in saved_styles.items() if k in DEFAULTS})
            if 'netChanged' not in saved_styles:
                used = {self.styles[k][0] for k in ('untouched', 'changed', 'new')}
                self.styles['netChanged'][0] = next(c for c in ('Blue', 'Cyan', 'Magenta', 'Yellow') if c not in used)
            if 'moved' not in saved_styles:
                used = {self.styles[k][0] for k in ('untouched', 'changed', 'netChanged', 'new', 'deleted')}
                self.styles['moved'][0] = next(c for c in ('Cyan', 'Magenta', 'Yellow', 'Blue', 'Orange', 'Green') if c not in used)
        self.reviews = {}
        self.previews = {}
        self.lock_registry = None
        self.git_scratch = None
        self.browser_state = None
        self.repository_browser = None
        self.restore_plans = {}
        self.merge_controller = None
        self.active_work = None
        self.temp_session = None
        self.legacy_cleanup_at = 0
        if (self.root / "performance.json").exists():
            mode = read_json(self.root / "performance.json").get("mode", "auto")
            if mode not in {"auto", "python", "native"}:
                raise ValueError("Invalid saved performance backend")
            os.environ["ALD_BACKEND"] = mode

    def execute(self, expression):
        if len(expression.encode("utf-8")) > 12000:
            # Large review maps must not pass through the inline SKILL reader.
            # Wrap only whitespace outside strings, keeping source lines short.
            pieces, quoted, escaped, column = [], False, False, 0
            for char in expression:
                if char == '"' and not escaped:
                    quoted = not quoted
                if char == " " and not quoted and column > 120:
                    char = "\n"
                pieces.append(char)
                column = 0 if char == "\n" else column + 1
                escaped = char == "\\" and not escaped
            with tempfile.TemporaryDirectory(prefix="ald_skill_") as temp:
                source = Path(temp) / "bulk.il"
                source.write_text("procedure(ALDGUIBulkCall()\nprogn(" + "".join(pieces) + "))\n", encoding="utf-8")
                checked(self.client.load_il(source, timeout=120))
            expression = "ALDGUIBulkCall()"
        return checked(self.client.execute_skill("progn(" + expression + ")", timeout=120))

    def install(self):
        checked(self.client.load_il((Path(__file__).parent / "skill" / "workflow.il")))
        checked(self.client.load_il((Path(__file__).parent / "skill" / "gui.il")))
        checked(self.client.load_il((Path(__file__).parent / "skill" / "browser.il")))
        checked(self.client.load_il((Path(__file__).parents[1] / "eda" / "virtuoso" / "skill" / "merge.il")))
        checked(self.client.load_il((Path(__file__).parents[1] / "eda" / "virtuoso" / "skill" / "merge_repository.il")))
        self.execute("when(ALDGUIOwner ALDGUIStop(ALDGUIOwner))")
        self.execute(f"ALDGUIOwner={sk(self.token)} ALDGUIQueue=nil ALDGUIInstallQuickKey() ALDGUIAttachAll()")
        atomic_json(self.root / "worker.json", {"pid": os.getpid(), "session": self.token,
                    "root": str(self.root), "review_library": self.review_library})

    def git_repository(self):
        working = loads(self.execute("getWorkingDir()"))
        config = self.root / "git.json"
        if config.exists():
            settings = read_json(config)
            if settings.get("working_directory", working) != working:
                return gitcommit.discover(working)
            repo = Path(settings["repository"])
            if gitcommit.discover(repo) != repo.resolve():
                raise ValueError("Configured Git repository is unavailable: " + str(repo))
            return repo.resolve()
        return gitcommit.discover(working)

    def history(self, identity, *, local=False, create=False):
        """Read-only access to pre-Git local archives; GUI never appends to them."""
        gitstore.check_identity(identity)
        folder = self.root / "histories" / digest(identity)
        history = History(folder)
        if folder.exists() and read_json(folder / "source.json") != identity:
            raise ValueError("History source identity mismatch")
        return history

    def history_model(self, identity):
        repo = self.git_repository()
        if repo:
            model = HistoryBrowser(None, identity, repo)
            if model.commits or not self.history(identity).path.exists():
                return model
            model.close()
        return HistoryBrowser(self.history(identity), identity)

    def notice(self, message):
        self.execute(f"ALDGUINotice({sk(field_text(message, limit=6000))})")

    @contextlib.contextmanager
    def work_area(self, *, independent=False):
        from layoutdiff.runtime.workspace import allocate, new_session
        if self.active_work and independent:
            outer = self.active_work
            self.active_work = None
            try:
                with self.work_area() as area:
                    yield area
            finally:
                self.active_work = outer
                self.execute(f'ALDGUIActiveLease={sk(outer["token"])}')
            return
        if self.active_work:
            yield self.active_work
            return
        if self.temp_session is None:
            self.temp_session = new_session()
        token, path = allocate(self.temp_session)
        (path / 'transport').mkdir()
        remote = str(path)
        if not getattr(self.client, 'layoutdiff_local_files', False):
            remote = '/tmp/' + self.temp_session.name + '/work/' + token
            result = self.client.ssh_runner.run_command('mkdir -p ' + shlex.quote(remote + '/transport'))
            if result.returncode:
                raise RuntimeError(result.stderr)
        old_scratch = getattr(self.client, 'layoutdiff_scratch', None)
        old_artifacts, old_lib = self.adapter.artifacts, self.review_library
        self.active_work = {'token': token, 'path': path, 'remote': remote}
        self.client.layoutdiff_scratch = lambda name: remote + '/transport/' + name
        self.adapter.artifacts = self.adapter.hierarchy.artifacts = path
        try:
            self.execute(f'ALDGUILeaseBegin({sk(token)} {sk(remote)})')
            atomic_json(path / 'lease.json', {'token': token, 'path': str(path), 'armed': True})
            yield self.active_work
        finally:
            try:
                self.execute(f'ALDGUILeaseSeal({sk(token)})')
            finally:
                self.adapter.artifacts = self.adapter.hierarchy.artifacts = old_artifacts
                self.review_library = self.adapter.writable_library = old_lib
                if old_scratch is None:
                    del self.client.layoutdiff_scratch
                else:
                    self.client.layoutdiff_scratch = old_scratch
                self.active_work = None

    def temporary_library(self, technology):
        work = self.active_work
        if not work:
            raise ValueError('A temporary work area is required')
        lib = 'ALD_TMP_' + work['token'][:16]
        self.execute(f'ALDGUILeaseLibrary({sk(work["token"])} {sk(lib)})')
        self.client.library.create(lib, work['remote'] + '/oa', technology_library=technology)
        return lib

    def close(self):
        if self.merge_controller:
            for state in self.merge_controller.opened.values():
                state['view'].close()
                state['index'].close()
            self.merge_controller.opened.clear()
        for preview in self.previews.values():
            preview.close()
        self.previews.clear()
        if self.browser_state and self.browser_state["model"]:
            self.browser_state["model"].close()
        self.browser_state = None

    def commit(self, identity, message):
        raise ValueError("Local checkpoints are read only. Use Save & Commit to preview a Git commit.")

    def quick_preview(self, identity):
        for old in self.previews.values():
            old.close()
        self.previews.clear()
        if self.execute(f"ALDGUIRequireSaved({sk(identity)})") != "t":
            raise ValueError("Layout has unsaved edits. Run Save & Commit again.")
        self.execute('when(boundp(\'ALDGUIOmissionForm) && ALDGUIOmissionForm '
                     'ALDGUIOmissionForm->aldToken=nil hiFormCancel(ALDGUIOmissionForm))')
        snapshot = self.adapter.capture_store(*identity, temporary=True, allow_unsupported=True)
        try:
            return self._quick_preview(identity, snapshot)
        except BaseException:
            snapshot.dispose()
            raise

    def _quick_preview(self, identity, snapshot):
        if self.execute(f"ALDGUIRequireSaved({sk(identity)})") != "t":
            raise ValueError("Layout changed during capture. Run Save & Commit again.")
        repo = self.git_repository()
        if repo is None:
            working = Path(loads(self.execute("getWorkingDir()")))
            self.execute(f"ALDGUIShowGitSetup({sk(identity)} {sk(str(working.parent))} \"\" \"\")")
            snapshot.dispose()
            return {"needs_repository": True, "suggested": str(working.parent)}
        try:
            preview = gitcommit.prepare(repo, identity, snapshot)
        except RuntimeError as exc:
            if "identity" in str(exc).lower() or "email" in str(exc).lower():
                self.execute(f"ALDGUIShowGitSetup({sk(identity)} {sk(str(repo))} \"\" \"\")")
                snapshot.dispose()
                return {"needs_git_identity": True}
            raise
        if not preview["write_required"]:
            warning = preview['omission_warning']
            preview.close()
            self.notice((warning + '\n\n' if warning else '') + "Layout saved. No changes relative to its current Git revision.")
            self.execute('ALDGUIStatus("Saved; no changes")')
            return {"no_changes": True}
        token = uuid.uuid4().hex
        preview['phase'] = 'preview'
        self.previews[token] = preview
        categories = preview["changes"]
        display_summary = "\n".join(line for line in preview["summary"].splitlines() if not line.startswith("Kinds:"))
        display_summary = re.sub(r"Objects:.*", f"Changes: {categories.totals['added']}A, "
                                f"{categories.totals['modified']}M, {categories.totals['deleted']}D, "
                                f"{categories.totals['modified_net']} modified net, "
                                f"{categories.totals['moved']} moved / stretched", display_summary)
        if preview['omissions']:
            display_summary = (preview['omission_warning'] + '\nTwo additional confirmations are required.\n\n' + display_summary)
        self.execute(f"ALDGUIShowQuickPreview({sk(token)} {sk(field_text(display_summary))} "
                     f"{sk(field_text(categories.overview(interactive=False)))} nil)")
        self.execute('ALDGUIStatus("Saved; awaiting commit message")')
        return {"token": token, "repo": str(repo), "operations": preview["operations"], "backend": categories.backend}

    def quick_full(self, token):
        preview = self.previews.get(token)
        if preview is None:
            return {"stale": True}
        path = self.browser_patch(preview["changes"].full())
        self.execute(f"ALDGUIQuickOpenFull({sk(token)} {sk(path)})")
        return {"full_diff": path}

    def quick_commit(self, token, message):
        preview = self._take_preview(token, 'preview')
        try:
            if not isinstance(message, str) or not message.strip():
                raise ValueError('Enter a nonempty commit message')
            preview['message'] = message
            if preview['omissions']:
                return self._omission_prompt(preview, 'omit-choice')
            return self._finish_commit(preview)
        except BaseException:
            preview.close()
            raise

    def _take_preview(self, token, phase):
        preview = self.previews.get(token)
        if preview is None or preview.get('phase') != phase:
            raise ValueError('Preview or confirmation expired. Run Save & Commit again.')
        del self.previews[token]
        return preview

    def _omission_prompt(self, preview, phase):
        # Each step gets a new one-use token. A duplicate callback cannot count
        # as the next confirmation, nor replace the already-entered message.
        token = uuid.uuid4().hex
        preview['phase'] = phase
        final = phase == 'omit-loss'
        audit = preview['omissions']
        text = ('CONFIRMATION 2 OF 2 - ROLLBACK DATA LOSS\n\n' if final else
                'CONFIRMATION 1 OF 2 - UNSUPPORTED ELEMENTS\n\n')
        text += preview['omission_warning'] + '\n\n'
        text += ('Confirm and commit only if you accept that these elements WILL BE LOST '
                 'when rolling back or restoring this checkpoint. They cannot be reconstructed from it.\n\n'
                 if final else 'Reject cancels this commit. Continue ignores the listed elements and opens a final data-loss warning.\n\n')
        text += f"Layout: {' / '.join(preview['identity'])}\nCommit message: {preview['message']}\n\n"
        text += '\n'.join(f'- {reason}: {count}' for reason, count in audit['counts'].items())
        if len(text.encode('utf-8')) > 7300:
            text = text.encode('utf-8')[:7000].decode('utf-8', errors='ignore') + '\n[Use View all omissions for every element and reason.]'
        self.previews[token] = preview
        try:
            self.execute(f'ALDGUIOmissionConfirm({sk(token)} {sk(text)} {sk(final)})')
        except BaseException:
            self.previews.pop(token, None)
            preview.close()
            raise
        return dict(token=token, confirmation=2 if final else 1, omitted=audit['omitted'], detached=audit['detached'])

    def quick_omit_continue(self, token):
        return self._omission_prompt(self._take_preview(token, 'omit-choice'), 'omit-loss')

    def quick_omit_confirm(self, token):
        return self._finish_commit(self._take_preview(token, 'omit-loss'))

    def quick_omission_report(self, token):
        preview = self.previews.get(token)
        if preview is None or not preview['omissions']:
            raise ValueError('Omission preview expired. Run Save & Commit again.')
        local = preview['snapshot'].omission_report
        remote = scratch(self.client, local.name)
        checked(self.client.upload_file(str(local), remote))
        self.execute(f'ALDGUIViewFile({sk(remote)} "Layout Diff - All omitted elements and memberships")')
        return {'report': remote}

    def _finish_commit(self, preview):
        try:
            if self.execute(f"ALDGUIRequireSaved({sk(preview['identity'])})") != "t":
                raise ValueError("Layout changed after preview. Run Save & Commit again.")
            current = self.adapter.capture_store(*preview["identity"], temporary=True, allow_unsupported=True)
            try:
                equal = (current.digest == preview['snapshot'].digest and
                         current.source_digest == preview['snapshot'].source_digest and
                         current.omissions == preview['omissions'])
            finally:
                current.dispose()
            if not equal:
                raise ValueError("Layout, ignored elements or hierarchy changed after preview. Run Save & Commit again.")
            if self.execute(f"ALDGUIRequireSaved({sk(preview['identity'])})") != "t":
                raise ValueError("Layout changed while validating preview. Run Save & Commit again.")
            message = preview['message']
            if preview['omissions']:
                message += '\n\nLayout Diff: ' + preview['omission_warning'] + '\nOmissions explicitly confirmed twice.'
            result = gitcommit.commit(preview, message, scratch=self.git_scratch, registry=self.lock_registry)
        finally:
            preview.close()
        self.execute(f"ALDGUIStatus({sk('Git committed ' + result['git_commit'][:12])})")
        self.execute(f"ALDGUIBrowserRefreshIfOpen({sk(preview['identity'])})")
        return result

    def git_setup(self, identity, directory, name, email):
        directory = Path(directory)
        if not directory.is_absolute():
            raise ValueError("Enter an absolute repository directory on the Virtuoso host")
        directory = directory.resolve()
        directory.mkdir(parents=True, exist_ok=True)
        repo = gitcommit.discover(directory)
        if repo is None:
            gitcommit.git(directory, "init")
            repo = directory
        if name.strip():
            gitcommit.git(repo, "config", "--local", "user.name", name.strip())
        if email.strip():
            gitcommit.git(repo, "config", "--local", "user.email", email.strip())
        atomic_json(self.root / "git.json", {"repository": str(repo),
                    "working_directory": loads(self.execute("getWorkingDir()"))})
        return self.quick_preview(identity)

    def sources(self):
        identities = [read_json(p) for p in sorted((self.root / "histories").glob("*/source.json"))]
        repo = self.git_repository()
        if repo:
            identities += gitstore.sources(repo)
        return [list(x) for x in sorted(set(tuple(x) for x in identities))]

    def show_history(self, identity):
        if self.browser_state and self.browser_state["model"]:
            self.browser_state["model"].close()
        sources = self.sources()
        identity = identity or (sources[0] if sources else None)
        if identity and identity not in sources:
            sources.insert(0, identity)
        repo = self.git_repository()
        model = None
        if identity:
            model = self.history_model(identity)
        token = uuid.uuid4().hex
        self.browser_state = {"token": token, "model": model, "detail": None}
        branch = gitcommit.git(repo, "symbolic-ref", "--short", "--quiet", "HEAD", check=False).stdout.decode().strip() if repo else ""
        header = f"Repository: {repo}     |     Branch: {branch or 'detached HEAD'}" if repo else "No Git repository selected. Save & Commit opens repository setup."
        if model and not model.store:
            header += "     |     Legacy local archive (read only)"
        commits = model.commits if model else []
        self.execute(f"ALDGUIBrowserLoad({sk(token)} {sk(identity)} {sk(sources)} "
                     f"{sources.index(identity) if identity else 0} {sk(header)} "
                     f"{sk(self.history_rows(model) if model else [])} {sk([c['id'] for c in commits])})")
        if commits:
            self.browser_select(token, commits[0]["id"])
        self.execute('ALDGUIStatus("History loaded")')
        return [{k: c[k] for k in ("id", "parent", "message")} for c in commits]

    def show_repository(self, ref_index=0, limit=500):
        repo = self.git_repository()
        if not repo:
            raise ValueError('No Git repository selected. Use Save & Commit to configure one.')
        self.repository_browser = RepositoryBrowser(repo)
        rows, ids = self.repository_browser.history(ref_index, limit)
        if self.browser_state and self.browser_state['model']:
            self.browser_state['model'].close()
        token = uuid.uuid4().hex
        self.browser_state = {'token': token, 'model': None, 'detail': None, 'git': True}
        self.execute(f'ALDGUIRepositoryLoad({sk(token)} {sk(str(repo))} '
                     f'{sk([r[0] for r in self.repository_browser.refs])} {int(ref_index)} '
                     f'{sk(rows)} {sk(ids)} {int(limit)})')
        if ids:
            self.repository_select(token, ids[0])
        return {'commits': len(ids), 'refs': len(self.repository_browser.refs)}

    def repository_select(self, token, revision):
        state = self.browser_state
        if not state or state['token'] != token or not state.get('git'):
            return {'stale': True}
        cells = self.repository_browser.cells(revision)
        if state['model']:
            state['model'].close()
        state.update(model=None, detail=None, revision=revision, cells=cells)
        self.execute(f'ALDGUIRepositoryCells({sk(token)} {sk(revision)} {sk(cells)})')
        if cells:
            return self.repository_cell(token, revision, 0)
        return {'cells': []}

    def repository_cell(self, token, revision, index):
        state = self.browser_state
        if not state or state['token'] != token or state.get('revision') != revision:
            return {'stale': True}
        identity = state['cells'][int(index)]
        if state['model']:
            state['model'].close()
        state['model'] = self.repository_browser.cell_model(revision, identity)
        self.execute(f'ALDGUIHistoryForm->aldSource={sk(identity)}')
        return self.browser_select(token, revision)

    @staticmethod
    def history_rows(model):
        return [[*r[:4], *[str(v) for v in r[4:]]] for r in model.rows(lazy=True)]

    def browser_patch(self, text):
        name = "browser-" + uuid.uuid4().hex + ".diff"
        path = self.adapter.artifacts / name
        with path.open("w", encoding="utf-8", newline="\n") as stream:
            if isinstance(text, str):
                stream.write(text)
            else:
                stream.writelines(text)
        remote = scratch(self.client, name)
        checked(self.client.upload_file(str(path), remote))
        return remote

    def browser_select(self, token, commit_id):
        state = self.browser_state
        if not state or state["token"] != token:
            return {"stale": True}
        detail = state["model"].detail(commit_id)
        state["detail"] = detail
        rows = []
        for item in detail["files"]:
            identity = gitstore.path_identity(item["path"])
            label = f"{identity[1]} / {identity[2]} ({identity[0]})" if identity else item["path"]
            if identity and len(item["path"].split("/")) == 5:
                # Keep the distinguishing filename visible in a narrow pane.
                label = item["path"].split("/")[-1] + " / " + label
            rows.append([item["status"], label, item["added"], item["deleted"]])
        self.execute(f"ALDGUIBrowserDetail({sk(token)} {sk(commit_id)} {sk(field_text(detail['summary']))} "
                     f"{sk(rows)} {sk(detail['categories'])} {sk(diff_html(detail['patch']))})")
        if not state.get('git'):
            self.execute(f"ALDGUIBrowserCounts({sk(token)} {sk(commit_id)} {sk(self.history_rows(state['model']))})")
        if not detail["reviewable"]:
            self.execute('ALDGUIHistoryForm->aldReview->enabled=nil ALDGUIHistoryForm->aldRestore->enabled=nil')
        return {key: detail[key] for key in ("id", "counts", "kinds", "files", "git", "categories")}

    def browser_file(self, token, commit_id, index):
        state = self.browser_state
        if not state or state["token"] != token or not state["detail"] or state["detail"]["id"] != commit_id:
            return {"stale": True}
        detail = state["detail"]
        index = int(index)
        text = detail["patch"] if index == -1 else state["model"].file_patch(detail, index)
        title = "All change categories" if index == -1 else detail["files"][index]["path"]
        title = title.removeprefix((state["model"].prefix or "") + "/")
        path = self.browser_patch(text)
        self.execute(f"ALDGUIBrowserPatch({sk(token)} {sk(commit_id)} {index} {sk(title)} {sk(diff_html(text))} {sk(path)})")
        return {"path": title, "full_diff": path}

    def browser_category(self, token, commit_id, index, page):
        state = self.browser_state
        if not state or state["token"] != token or not state["detail"] or state["detail"]["id"] != commit_id:
            return {"stale": True}
        index, page = int(index), int(page)
        if index < 0:
            raise ValueError("Select a category")
        result = state["model"].categories(commit_id).page(index, page)
        self.execute(f"ALDGUIBrowserCategoryData({sk(token)} {sk(commit_id)} {index} {page} "
                     f"{sk(result['title'])} {sk(diff_html(result['text']))} {result['pages']})")
        return {k: result[k] for k in ("title", "page", "pages", "count")}

    def browser_full(self, token, commit_id, file_index, category_index):
        state = self.browser_state
        if not state or state["token"] != token or not state["detail"] or state["detail"]["id"] != commit_id:
            return {"stale": True}
        file_index, category_index = int(file_index), int(category_index)
        if file_index >= 0:
            text = state["model"].file_patch(state["detail"], file_index)
        else:
            text = state["model"].categories(commit_id).full(category_index if category_index >= 0 else None)
        path = self.browser_patch(text)
        self.execute(f"ALDGUIBrowserOpenFull({sk(token)} {sk(commit_id)} {file_index} {category_index} {sk(path)})")
        return {"full_diff": path}

    def style(self, token, group, settings):
        result = self.styles_batch(token, [[group, *settings]])
        return tuple(result['packets'][0])

    def styles_batch(self, token, rows):
        if token not in self.reviews:
            raise ValueError("Review session is no longer available")
        # Validate every row before writing any files or applying any setting.
        validated = {}
        for group, *settings in rows:
            if group not in DEFAULTS or group in validated:
                raise ValueError('Invalid or duplicate highlight category')
            validated[group] = style_settings(settings)
        if not validated:
            raise ValueError('No highlight styles supplied')
        packets, updates, content = [], [], []
        remote = scratch(self.client, 'ALD' + token + 'styles')
        local = self.adapter.artifacts / ('ALD' + token + 'styles.drf')
        for group, settings in validated.items():
            packet = 'ALD' + token + group
            content.append(display_resource(packet, settings))
            icon_tag = digest(settings)[:12]
            icon = local.with_name(packet + '_' + icon_tag + '.png')
            icon.write_bytes(swatch(COLORS[settings[0]]))
            remote_icon = remote + '_' + group + '_' + icon_tag + '.png'
            self.client.upload_file(str(icon), remote_icon)
            packets.append([packet, remote_icon])
            updates.append([group, settings, remote_icon])
        local.write_text(''.join(content), encoding='ascii')
        self.client.upload_file(str(local), remote + ".drf")
        self.execute(f'drLoadDrf({sk(remote + ".drf")} nil) ALDGUIUpdateStyles({sk(token)} {sk(updates)})')
        self.styles.update(validated)
        atomic_json(self.root / "styles.json", self.styles)
        self.execute('ALDGUIStatus("Style updated")')
        return {'packets': packets, 'categories': list(validated)}

    def group_boundaries(self, before, after, classification, token, *, definition_source=None):
        from layoutdiff.comparison.review_groups import boundary_targets
        changes = classification['group_changes']
        deleted = [k for k in classification['removed'] if before['objects'][k]['kind'] in VISUAL]
        records, issues = [], []
        shadows = {'count': 0, 'primitives': 0, 'fallbacks': []}
        def collect(snapshot, side, native_token):
            selected = [r for r in changes if r['side'] == side]
            if not selected:
                return
            requests = boundary_targets(snapshot, [r['key'] for r in selected])
            boxes = dict(loads(self.execute(f'ALDGUIGroupBounds({sk(native_token)} {sk(requests)})')) or [])
            records.extend({**r, 'bBox': boxes.get(r['key'])} for r in selected)
        collect(after, 'after', token)
        if deleted or any(r['side'] == 'before' for r in changes):
            # Share one previous-state build for deleted figures and groups.
            old_token = uuid.uuid4().hex
            cell = 'ALD_REVIEW_' + old_token[:16]
            folder = self.adapter.artifacts / 'reviews' / old_token
            atomic_json(folder / 'review.json', {'token': old_token, 'cell': cell,
                        'library': self.review_library, 'purpose': 'deleted-review-overlays'})
            adapter = VirtuosoAdapter(self.client, self.adapter.artifacts, writable_library=self.review_library)
            try:
                self.execute('ALDGUIStatus("Building deleted-object shadows")')
                adapter.reconstruct(before, self.review_library, cell, review_token=old_token,
                                    group_definition_source=definition_source)
                collect(before, 'before', old_token)
                if deleted:
                    result = loads(self.execute(f'ALDGUIPrepareShadows({sk(old_token)} {sk(token)} {sk(deleted)})'))
                    shadows = dict(zip(('count', 'primitives', 'fallbacks'), result))
                    shadows['fallbacks'] = shadows['fallbacks'] or []
                issues.extend(adapter.last_dependency_warnings)
            except Exception as exc:
                if deleted:
                    # Never report a successful review with silently missing shadows.
                    raise ValueError('Cannot build deleted-object shadows: ' + str(exc)) from exc
                issues.append({'reason': 'Previous group boundaries unavailable: ' + str(exc)})
                records.extend({**r, 'bBox': None} for r in changes if r['side'] == 'before')
            finally:
                self.execute(f'ALDGUIDiscard({sk(old_token)})')
                # Only this registered helper cell is eligible, and only closed.
                self.execute(f'''let((dd) unless(setof(cv dbGetOpenCellViews()
                    cv~>libName=={sk(self.review_library)} && cv~>cellName=={sk(cell)})
                    dd=ddGetObj({sk(self.review_library)} {sk(cell)} "layout") when(dd ddDeleteObj(dd))) t)''')
        return records, issues, shadows

    def review(self, identity, commit_id):
        if not self.active_work:
            with self.work_area():
                return self.review(identity, commit_id)
        state = self.browser_state
        model = state["model"] if state and state["model"] and state["model"].identity == identity else self.history_model(identity)
        before, after = model.pair(commit_id)
        from layoutdiff.eda.virtuoso.omissions import warning
        omission_warning = warning(model.store.omissions(commit_id)) if model.store else ''
        if not after["objects"]:
            self.notice("This revision deletes the layout snapshot. Select an earlier revision to review its layout.")
            return {"deleted": True, "commit": commit_id}
        classification = classify(before, after)
        self.review_library = self.temporary_library(after['objects']['cell:']['technology'])
        self.adapter.writable_library = self.review_library
        token = uuid.uuid4().hex
        cell = "ALD_REVIEW_" + token[:16]
        self.reviews[token] = {"source": identity, "commit": commit_id, "cell": cell}
        artifacts = self.adapter.artifacts / "reviews" / token
        artifacts.mkdir(parents=True)
        # Register the destination before creation so interrupted/failed builds
        # can be reclaimed later using the same strict ownership checks.
        atomic_json(artifacts / "review.json", {**self.reviews[token], "library": self.review_library,
                    "token": token, "state": "building"})
        atomic_json(artifacts / "requested.layout.json", after)
        atomic_json(artifacts / "classification.json", classification)
        self.execute(f"ALDGUIStyleData[{sk(token)}]=makeTable('aldStyleData nil)")
        packets, icons = [], []
        installed = self.styles_batch(token, [[g, *s] for g, s in self.styles.items()])
        for group, (packet, icon) in zip(self.styles, installed['packets']):
            packets.append([group, packet])
            icons.append([group, icon])
        try:
            actual = self.adapter.reconstruct(after, self.review_library, cell, review_token=token,
                                              group_definition_source=identity)
            boundaries, boundary_warnings, shadows = self.group_boundaries(
                before, after, classification, token, definition_source=identity)
            boundary_counts = {s: sum(r['status'] == s for r in boundaries) for s in ('new', 'changed', 'deleted')}
            counts = classification["counts"]
            summary = (f"Commit {commit_id[:12]}\n{'/'.join(identity)}\n"
                f"Untouched: {counts['untouched']}   Modified: {counts['changed']}   Moved / stretched: {counts['moved']}   Modified net: {counts['netChanged']}   New: {counts['new']}\n"
                f"Group boundaries: {boundary_counts['new']} new, {boundary_counts['changed']} modified, {boundary_counts['deleted']} deleted\n"
                f"Groups without drawable bounds: {sum(r['bBox'] is None for r in boundaries)}; boundary warnings: {len(boundary_warnings)}\n"
                f"Deleted shadows: {shadows['count']} ({len(shadows['fallbacks'])} bounding-box fallbacks)\n"
                f"Metadata changes: {len(classification['metadata_changes'])}\n"
                f"Hierarchy warnings: {len(self.adapter.last_dependency_warnings)}\n"
                "Moves/stretches use conservative geometric matching; ambiguous pairs remain A/D.\n"
                "Instance, array, and via highlights show their bounds.")
            if omission_warning:
                summary = omission_warning + '\n\n' + summary
            assignments = [[key, group] for key, group in sorted(classification["groups"].items())]
            outline_styles = {'new': 'groupNew', 'changed': 'groupChanged', 'deleted': 'groupDeleted'}
            outlines = [[outline_styles[r['status']], r['bBox']] for r in boundaries if r['bBox'] is not None]
            window = int(self.execute(f"ALDGUIOpenReview({sk(token)} {sk(self.review_library)} {sk(cell)} {sk(identity)} {sk(assignments)} {sk(packets)} {sk(icons)} {sk(summary)} {sk(outlines)})"))
            self.reviews[token]["window"] = window
            self.execute(f"ALDGUIFit(window({window}))")
            self.execute('ALDGUIStatus("Review ready")')
            atomic_json(artifacts / "actual.layout.json", actual)
            atomic_json(artifacts / "review.json", {**self.reviews[token], "library": self.review_library,
                        "token": token, "warnings": self.adapter.last_dependency_warnings,
                        "readback_normalization": self.adapter.last_readback_normalization,
                        "group_definition_context": self.adapter.last_group_context,
                        "group_boundaries": boundaries, "boundary_warnings": boundary_warnings,
                        "deleted_shadows": shadows,
                        "counts": counts, "summary": summary})
            return read_json(artifacts / "review.json")
        except Exception:
            self.execute(f"ALDGUIDiscard({sk(token)})")
            raise

    def dispatch(self, request):
        with self.work_area():
            label = TASK_LABELS.get(request[0])
            if label:
                self.execute(f'ALDGUIBusyStart({sk(label)} {sk(request[0] in POPUP_TASKS)})')
            try:
                return self._dispatch(request)
            finally:
                if label:
                    self.execute('ALDGUIBusyDone()')

    def _dispatch(self, request):
        command, *args = request
        if command.startswith('merge-'):
            if self.merge_controller is None:
                from layoutdiff.ui.merge import MergeController
                self.merge_controller = MergeController(self)
            if command == 'merge-action' and len(args) == 4:
                return self.merge_controller.action(*args)
            if command == 'merge-resume' and len(args) == 1:
                return self.merge_controller.open(args[0])
            if command == 'merge-setup' and not args:
                return self.merge_controller.setup()
            if command == 'merge-repository' and len(args) in (3, 4):
                return self.merge_controller.repository_action(*args)
            raise ValueError('Unknown merge request')
        if command in {"backend-info", "backend-config"}:
            from layoutdiff.data.acceleration import info
            if command == "backend-config":
                if len(args) != 1 or args[0] not in {"auto", "python", "native"}:
                    raise ValueError("Choose auto, python or native")
                os.environ["ALD_BACKEND"] = args[0]
                atomic_json(self.root / "performance.json", {"mode": args[0]})
            data = info()
            text = ("Auto uses C++ for 50,000+ objects or 32 MiB+ canonical streams.\n"
                "Python is the reference and automatic fallback. Native mode requires a verified tool.\n\n"
                f"Tool: {data['tool']}\nAvailability: {data['availability']}\n"
                f"Last kernel: {data['last']['selected']}\nReason: {data['last']['reason']}\n"
                "This setting affects subsequent operations.")
            if command == "backend-info":
                self.execute(f"ALDGUIPerformance({sk(data['mode'])} {sk(field_text(text))})")
            else:
                self.execute(f"ALDGUIPerformanceForm->aldInfo->value={sk(field_text(text))}")
                self.execute(f"ALDGUIStatus({sk('Performance backend: ' + data['mode'])})")
            return data
        if command == "quick-preview" and len(args) == 3:
            return self.quick_preview(args)
        if command == "quick-commit" and len(args) == 2:
            return self.quick_commit(*args)
        if command == 'quick-omit-continue' and len(args) == 1:
            return self.quick_omit_continue(args[0])
        if command == 'quick-omit-confirm' and len(args) == 1:
            return self.quick_omit_confirm(args[0])
        if command == 'quick-omission-report' and len(args) == 1:
            return self.quick_omission_report(args[0])
        if command == "quick-cancel" and len(args) == 1:
            old = self.previews.pop(args[0], None)
            if old:
                old.close()
            self.execute('ALDGUIStatus("Saved; commit cancelled")')
            return {"cancelled": True}
        if command == "quick-full" and len(args) == 1:
            return self.quick_full(args[0])
        if command == "git-setup" and len(args) == 6:
            return self.git_setup(args[:3], *args[3:])
        if command == "commit" and len(args) == 4:
            return self.commit(args[:3], args[3])
        if command == "history" and len(args) == 3:
            return self.show_history(args)
        if command == "browser" and len(args) in (0, 3):
            return self.show_history(args)
        if command == 'repository' and len(args) == 2:
            return self.show_repository(*args)
        if command == 'repository-select' and len(args) == 2:
            return self.repository_select(*args)
        if command == 'repository-cell' and len(args) == 3:
            return self.repository_cell(*args)
        if command == 'browser-close' and len(args) == 1:
            if self.browser_state and self.browser_state['token'] == args[0]:
                if self.browser_state['model']:
                    self.browser_state['model'].close()
                self.browser_state = None
                self.repository_browser = None
            return {'closed': True}
        if command == 'restore-prepare' and len(args) == 4:
            return self.restore_prepare(args[:3], args[3])
        if command == 'restore-apply' and len(args) == 1:
            return self.restore_apply(args[0])
        if command == 'restore-cancel' and len(args) == 1:
            return self.restore_cancel(args[0])
        if command == "browser-select" and len(args) == 2:
            return self.browser_select(*args)
        if command == "browser-file" and len(args) == 3:
            return self.browser_file(*args)
        if command == "browser-category" and len(args) == 4:
            return self.browser_category(*args)
        if command == "browser-full" and len(args) == 4:
            return self.browser_full(*args)
        if command == "review" and len(args) == 4:
            return self.review(args[:3], args[3])
        if command == "style" and len(args) in (5, 6):
            self.execute(f'ALDGUILeaseWatchReview({sk(args[0])})')
            return self.style(args[0], args[1], args[2:])
        if command == "styles" and len(args) == 2:
            self.execute(f'ALDGUILeaseWatchReview({sk(args[0])})')
            return self.styles_batch(*args)
        if command == "cleanup" and not args:
            result = self.clean_reviews()
            self.notice("Temporary review cleanup:\n" + json.dumps(result, indent=2))
            self.execute('ALDGUIStatus("Cleanup complete")')
            return result
        if command == "sources" and not args:
            identities = self.sources()
            self.execute(f"ALDRuntimeSources({sk(identities)})")
            self.execute('ALDGUIStatus("Layouts refreshed")')
            return identities
        if command == "logs" and not args:
            path = self.root / "runtime.log"
            text = path.read_text(encoding="utf-8", errors="replace")[-12000:] if path.exists() else "No runtime log yet"
            self.notice(text)
            return {"log": str(path)}
        raise ValueError("Unknown GUI request")

    def restore_prepare(self, identity, revision):
        from layoutdiff.ui.restore import prepare
        return prepare(self, identity, revision)

    def restore_apply(self, token):
        from layoutdiff.ui.restore import apply
        return apply(self, token)

    def restore_cancel(self, token):
        from layoutdiff.ui.restore import cancel
        return cancel(self, token)

    def clean_reviews(self):
        """Remove only recorded, closed temporary review views in the allowed lib."""
        results = []
        for manifest in sorted((self.root / "reviews").glob("*/review.json")):
            record = read_json(manifest)
            token, cell, lib = record.get("token", ""), record.get("cell"), record.get("library")
            if (not re.fullmatch(r"[0-9a-f]{32}", token) or cell != "ALD_REVIEW_" + token[:16]
                    or lib != self.review_library or manifest.parent.name != token):
                raise ValueError("Refusing unrecognized review manifest: " + str(manifest))
            status = loads(self.execute(f'''let((dd)
                if(setof(cv dbGetOpenCellViews() cv~>libName=={sk(lib)} && cv~>cellName=={sk(cell)})
                  then "open-skipped"
                  else dd=ddGetObj({sk(lib)} {sk(cell)} "layout")
                    if(dd then ddDeleteObj(dd)
                      if(ddGetObj({sk(lib)} {sk(cell)} "layout") then "delete-failed" else "deleted")
                    else "absent")))'''))
            results.append({"cell": cell, "status": status})
            if status in {'deleted', 'absent'}:
                # The manifest identity and strict token/path check above are
                # required before deleting any pre-temp-directory artifacts.
                shutil.rmtree(manifest.parent)
        atomic_json(self.root / "cleanup.json", results)
        return results

    def poll(self):
        if time.monotonic() >= self.legacy_cleanup_at:
            self.clean_reviews()
            self.legacy_cleanup_at = time.monotonic() + 15
            if self.merge_controller is None:
                from layoutdiff.ui.merge import MergeController
                self.merge_controller = MergeController(self)
            try:
                self.merge_controller.refresh_hint()
            except (ValueError, RuntimeError, OSError) as exc:
                # Discovery must not spam CIW or block queued actions.
                atomic_json(self.root / 'merge-discovery.json', {'error': str(exc)})
        requests = loads(self.execute(f"ALDGUIPoll({sk(self.token)})")) or []
        for request in requests:
            with self.work_area():
                entry = {"request": request, "time": time.time()}
                try:
                    entry["result"] = self.dispatch(request)
                except Exception as exc:
                    entry["error"] = str(exc)
                    try:
                        self.execute('ALDGUIStatus("Operation failed")')
                        if isinstance(exc, UnsupportedContentError):
                            entry["unsupported_counts"] = exc.counts
                            entry["unsupported_report"] = str(exc.report)
                            # No field_text truncation: show every unsupported category
                            # in the scrollable result form, even beyond 6000 bytes.
                            remote_report = scratch(self.client, exc.report.name)
                            checked(self.client.upload_file(str(exc.report), remote_report))
                            message = 'Operation failed: ' + str(exc)
                            summary_remote = None
                            # IC23.1 MLTextField accepts at most 8191 bytes. An
                            # oversized summary opens in the native file viewer in
                            # full; no categories are dropped from either report.
                            if len(message.encode("utf-8")) > 7600:
                                summary = exc.report.with_suffix(".summary.txt")
                                summary.write_text(message, encoding="utf-8")
                                summary_remote = scratch(self.client, summary.name)
                                checked(self.client.upload_file(str(summary), summary_remote))
                                message = (f"Cannot commit unsupported layout content: {len(exc.counts)} categories.\n"
                                           "The complete category summary has opened in a text viewer.\n"
                                           "Use View all unsupported elements for individual records.")
                            self.execute(f"ALDGUIUnsupported({sk(message)} {sk(remote_report)} {sk(summary_remote)})")
                        else:
                            self.notice("Operation failed: " + str(exc))
                    except Exception as notification:
                        entry["notification_error"] = str(notification)[:2000]
                atomic_json(self.root / "requests" / (uuid.uuid4().hex + ".json"), entry)
        return len(requests)

    def serve(self):
        lock = self.root / "worker.lock"
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        stop = self.root / "STOP"
        stop.unlink(missing_ok=True)
        try:
            self.install()
            print("Virtuoso Layout Diff toolbar installed. Worker:", os.getpid(), flush=True)
            while not stop.exists():
                self.poll()
                time.sleep(.8)
        finally:
            try:
                self.execute(f"ALDGUIStop({sk(self.token)})")
            finally:
                self.close()
                lock.unlink(missing_ok=True)
                stop.unlink(missing_ok=True)
