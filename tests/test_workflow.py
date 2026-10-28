import json
from pathlib import Path
import pytest
import layoutdiff.git.commit as gc
from layoutdiff.ui.browser import RepositoryBrowser
from layoutdiff.data.core import canonicalize
from layoutdiff.runtime.workspace import allocate, reap


def test_repository_graph_cells_refs_and_no_checkout(tmp_path):
    repo = tmp_path / 'repo'; repo.mkdir()
    gc.git(repo, 'init')
    gc.git(repo, 'config', 'user.name', 'Workflow Test')
    gc.git(repo, 'config', 'user.email', 'workflow@example.invalid')
    first = ['TEST', 'a', 'layout']; second = ['TEST', 'b', 'layout']
    snapshot = canonicalize([{'kind': 'cell', 'name': '', 'props': []}])
    a = gc.commit(gc.prepare(repo, first, snapshot), 'Add cell a')['git_commit']
    b = gc.commit(gc.prepare(repo, second, snapshot), 'Add cell b')['git_commit']
    gc.git(repo, 'tag', '-a', 'checkpoint', '-m', 'checkpoint', a)
    (repo / 'notes.txt').write_text('non-layout change')
    gc.git(repo, 'add', 'notes.txt'); gc.git(repo, 'commit', '-m', 'Documentation')
    head = gc.git(repo, 'rev-parse', 'HEAD').stdout
    index = (repo / '.git/index').read_bytes()
    browser = RepositoryBrowser(repo)
    rows, ids = browser.history()
    assert len(rows) == 3 and '*' in rows[0][0]
    assert browser.cells(ids[0]) == []
    assert browser.cells(b) == [second]
    assert browser.cells(a) == [first]
    model = browser.cell_model(a, first)
    assert model.pair(a)[1] == snapshot
    assert model.detail(a)['counts']['added'] == 1
    model.close()
    tag_index = next(i for i, r in enumerate(browser.refs) if r[0] == 'refs/tags/checkpoint')
    assert browser.history(tag_index)[1] == [a]
    with pytest.raises(ValueError, match='not modified'):
        browser.cell_model(b, first)
    assert gc.git(repo, 'rev-parse', 'HEAD').stdout == head
    assert (repo / '.git/index').read_bytes() == index


def test_repository_groups_v2_components_and_deleted_cells(tmp_path):
    from layoutdiff.data.storage import from_snapshot
    repo = tmp_path / 'repo'; repo.mkdir()
    gc.git(repo, 'init')
    gc.git(repo, 'config', 'user.name', 'Workflow Test')
    gc.git(repo, 'config', 'user.email', 'workflow@example.invalid')
    identity = ['TEST', 'v2', 'layout']
    store = from_snapshot(canonicalize([{'kind': 'cell', 'name': '', 'props': []}]), tmp_path/'snapshot')
    first = gc.commit(gc.prepare(repo, identity, store), 'V2 cell')['git_commit']
    gc.git(repo, 'rm', '-r', 'layouts'); gc.git(repo, 'commit', '-m', 'Delete cell')
    browser = RepositoryBrowser(repo)
    _, ids = browser.history()
    assert browser.cells(first) == [identity]
    assert browser.cells(ids[0]) == [identity]
    model = browser.cell_model(ids[0], identity)
    assert model.detail(ids[0])['reviewable'] is False
    model.close(); store.close()


def test_reap_waits_for_release_or_parent_exit(tmp_path):
    session = tmp_path / 'ald-session-unit'; session.mkdir()
    a, first = allocate(session); b, second = allocate(session)
    for folder in (first, second):
        record = json.loads((folder/'lease.json').read_text()); record['armed'] = True
        (folder/'lease.json').write_text(json.dumps(record))
    (first / 'RELEASED').touch()
    assert reap(session) == [str(second)]
    assert not first.exists() and second.exists()
    assert reap(session, parent_dead=True) == []
    assert not second.exists()


def test_reap_unarmed_allocation_after_startup_failure(tmp_path):
    session = tmp_path/'ald-session-unit'; session.mkdir()
    _, folder = allocate(session)
    assert reap(session) == [] and not folder.exists()


def test_parent_exit_reaps_interrupted_manifest_write(tmp_path):
    session = tmp_path/'ald-session-unit'; session.mkdir()
    folder = session/'work'/'interrupted'; folder.mkdir(parents=True)
    assert reap(session) == [str(folder)]
    assert reap(session, parent_dead=True) == [] and not folder.exists()


def test_reap_refuses_unowned_paths_and_tampered_manifest(tmp_path):
    with pytest.raises(ValueError):
        reap(tmp_path)
    session = tmp_path/'ald-session-unit'; session.mkdir()
    _, folder = allocate(session)
    (folder/'lease.json').write_text(json.dumps({'token': folder.name, 'path': str(tmp_path)}))
    (folder/'RELEASED').touch()
    with pytest.raises(ValueError):
        reap(session)
    assert folder.exists()


def test_native_workflow_definitions_are_complete_top_level_forms():
    # Cadence load() can return success after an incomplete trailing procedure;
    # a delimiter check catches that before runtime callbacks go undefined.
    source = Path(__file__).resolve().parents[1]/'layoutdiff/ui/skill'
    for name in ('workflow.il', 'browser.il', 'gui.il'):
        depth = 0; quoted = False; escaped = False
        for line in (source/name).read_text().splitlines():
            if line.startswith('procedure('):
                assert depth == 0, (name, line, depth)
            for char in line:
                if char == ';' and not quoted:
                    break
                if char == '"' and not escaped:
                    quoted = not quoted
                if not quoted:
                    depth += (char == '(') - (char == ')')
                    assert depth >= 0, (name, line)
                escaped = char == '\\' and not escaped
        assert depth == 0 and not quoted, name
