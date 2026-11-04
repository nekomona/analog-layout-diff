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
    def capture_supported(self):
        return self.capture(), None, 'source'
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


def test_omissions_require_two_consents_and_survive_undo(monkeypatch, tmp_path):
    c, token = controller(monkeypatch, tmp_path)
    s = c.opened[token]['session']
    v = c.opened[token]['view']
    audit = {'omitted': 1, 'detached': 0, 'counts': {'unknown': 1}, 'reportSha256': 'test'}
    v.capture_supported = lambda: (state(30), audit, 'source')
    c.action(token, 0, 'edit')
    assert c.action(token, 0, 'accept-edits')['omission_confirmation'] == 1
    assert s.generation == 0 and v.editing
    with pytest.raises(ValueError, match='missing or stale'):
        c.action(token, 0, 'omit-confirm')
    c.action(token, 0, 'omit-cancel')
    assert s.snapshot == state(0) and v.editing
    c.action(token, 0, 'accept-edits')
    assert c.action(token, 0, 'omit-continue')['omission_confirmation'] == 2
    assert s.generation == 0
    c.action(token, 0, 'omit-confirm')
    assert s.snapshot == state(30) and s.state['omissions'] == audit
    c.action(token, 1, 'undo')
    assert 'omissions' not in s.state
    c.action(token, 2, 'redo')
    assert s.state['omissions'] == audit
    c.action(token, 3, 'suspend')
    c.open(token)
    assert c.opened[token]['session'].state['omissions'] == audit


def test_edit_after_omission_preview_invalidates_consent(monkeypatch, tmp_path):
    c, token = controller(monkeypatch, tmp_path)
    v = c.opened[token]['view']
    audit = {'omitted': 1, 'detached': 0, 'counts': {}}
    v.capture_supported = lambda: (state(30), audit, 'source')
    c.action(token, 0, 'edit')
    c.action(token, 0, 'accept-edits')
    c.action(token, 0, 'omit-continue')
    v.capture_supported = lambda: (state(30), audit, 'changed-unknown-content')
    with pytest.raises(ValueError, match='changed after omission'):
        c.action(token, 0, 'omit-confirm')
    assert c.opened[token]['session'].generation == 0 and v.editing


def test_repository_flow_routes_native_validation_before_git_commit(monkeypatch, tmp_path):
    from test_repository_merge import branches
    from layoutdiff.git.merge import resolve
    repo, target, incoming = branches(tmp_path)
    monkeypatch.setattr('layoutdiff.ui.merge.MergeView', View)
    worker = Worker(tmp_path)
    worker.git_repository = lambda: repo
    c = MergeController(worker)
    result = c.repository_action('start', value='incoming')
    token = result['token']
    tx = c.repository(token)
    for key in tx.state['cells']:
        opened = c.repository_action('open-cell', token, key)
        native = opened['token']
        session = c.opened[native]['session']
        for ident in session.unresolved():
            c.action(native, session.generation, 'select', ident)
            c.action(native, session.generation, 'preview', 'incoming')
            c.action(native, session.generation, 'accept')
        c.action(native, session.generation, 'finish')
    c.repository_action('file', token, ['notes.txt', 'incoming'])
    c.repository_action('commit', token, 'Merge graphical decisions')
    assert resolve(repo, 'HEAD') == target
    assert not c.opened
    c.repository_action('publish', token)
    assert resolve(repo, 'HEAD') != target


def test_active_merge_discovery_and_graphical_stage(monkeypatch, tmp_path):
    from test_active_merge import conflicted
    from layoutdiff.data.core import digest
    from layoutdiff.git.merge import resolve
    repo, target, incoming = conflicted(tmp_path)
    monkeypatch.setattr('layoutdiff.ui.merge.MergeView', View)
    worker = Worker(tmp_path); worker.git_repository = lambda: repo
    c = MergeController(worker)
    info = c.setup()['active']
    assert 'ACTIVE GIT MERGE' in worker.calls[-1]
    c.refresh_hint()
    assert 'Merge: active (1)' in worker.calls[-1]
    token = c.repository_action('active', value=digest(info))['token']
    try:
        tx = c.repository(token)
        for key in tx.state['cells']:
            native = c.repository_action('open-cell', token, key)['token']
            session = c.opened[native]['session']
            for ident in session.unresolved():
                c.action(native, session.generation, 'select', ident)
                c.action(native, session.generation, 'preview', 'incoming')
                c.action(native, session.generation, 'accept')
            c.action(native, session.generation, 'finish')
        result = c.repository_action('commit', token)
        assert result['phase'] == 'staged' and not c.opened
        assert resolve(repo, 'HEAD') == target and resolve(repo, 'MERGE_HEAD') == incoming
    finally:
        tx = c.repository(token)
        if tx.work.exists(): c.repository_action('cancel', token)
