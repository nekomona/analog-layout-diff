import pytest
from layoutdiff.ui.merge import MergeController
from layoutdiff.data.core import canonicalize


def state(x):
    return canonicalize([{'kind': 'cell', 'name': '', 'dbu': 1000, 'technology': 'TEST'},
        {'kind': 'rect', 'layerName': 'MET1', 'bBox': [[x, 0], [x+100, 100]]}])


class View:
    fail = False
    def __init__(self, worker, token, session):
        self.editing = False
        self.snapshot = None
    def show(self, snapshot):
        if self.fail:
            raise ValueError('Native readback mismatch')
        self.snapshot = snapshot
        self.editing = False
    def highlight(self, selected):
        return []
    def edit(self):
        self.editing = True
    def capture(self):
        return state(30)
    def close(self):
        pass


class Worker:
    def __init__(self, root):
        self.root = root
        self.calls = []
    def execute(self, expression):
        self.calls.append(expression)
    def notice(self, text):
        pass


def controller(monkeypatch, tmp_path):
    monkeypatch.setattr('layoutdiff.ui.merge.MergeView', View)
    c = MergeController(Worker(tmp_path))
    token = c.start(state(0), state(10), state(20))['token']
    return c, token


def test_graphical_preview_is_separate_from_acceptance(monkeypatch, tmp_path):
    c, token = controller(monkeypatch, tmp_path)
    s = c.opened[token]['session']
    c.action(token, 0, 'preview', 'incoming')
    assert s.snapshot == state(0) and s.unresolved()
    assert c.opened[token]['view'].snapshot == state(20)
    c.action(token, 0, 'accept')
    assert s.snapshot == state(20) and not s.unresolved()
    c.action(token, 1, 'undo')
    assert s.snapshot == state(0)
    c.action(token, 2, 'redo')
    assert s.snapshot == state(20)


def test_failed_native_preview_does_not_accept_or_change_result(monkeypatch, tmp_path):
    c, token = controller(monkeypatch, tmp_path)
    c.opened[token]['view'].fail = True
    with pytest.raises(ValueError, match='readback'):
        c.action(token, 0, 'preview', 'target')
    assert c.opened[token]['session'].snapshot == state(0)
    assert c.opened[token]['preview'] is None


def test_custom_edit_boundaries_and_restart(monkeypatch, tmp_path):
    c, token = controller(monkeypatch, tmp_path)
    c.action(token, 0, 'edit')
    with pytest.raises(ValueError, match='Accept or cancel'):
        c.action(token, 0, 'next')
    c.action(token, 0, 'accept-edits')
    assert c.opened[token]['session'].snapshot == state(30)
    c.action(token, 1, 'suspend')
    reopened = MergeController(Worker(tmp_path))
    reopened.open(token)
    assert reopened.opened[token]['session'].snapshot == state(30)


def test_finish_rejects_pending_preview_or_unresolved_decisions(monkeypatch, tmp_path):
    c, token = controller(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match='every conflict'):
        c.action(token, 0, 'finish')
    c.action(token, 0, 'preview', 'target')
    with pytest.raises(ValueError, match='current preview'):
        c.action(token, 0, 'finish')
