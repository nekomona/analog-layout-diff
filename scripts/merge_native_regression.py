"""Exercise native graphical preview/accept/edit/undo/resume on synthetic data."""
import argparse
import copy
from pathlib import Path
import sys
import tempfile
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from virtuoso_bridge import SSHClient, VirtuosoClient
from layoutdiff.data.core import canonicalize
from layoutdiff.eda.virtuoso.adapter import VirtuosoAdapter, checked
from layoutdiff.eda.virtuoso.sexpr import dumps as sk, loads
from layoutdiff.ui.worker import GuiWorker
from layoutdiff.ui.merge import MergeController


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--profile')
    p.add_argument('--technology', required=True)
    p.add_argument('--layer', required=True)
    p.add_argument('--complex', action='store_true', help='Include pins, ordered groups, MPP and associated text')
    p.add_argument('--repository', action='store_true', help='Also verify an isolated synthetic Git merge')
    args = p.parse_args()
    tunnel = SSHClient.from_env(profile=args.profile); tunnel.warm()
    c = VirtuosoClient.from_tunnel(tunnel)
    root = Path(__file__).resolve().parents[1]
    run = uuid.uuid4().hex
    lib = 'ALD_MERGE_TEST_' + run[:12]
    out = root / 'evidence/merge' / run
    out.mkdir(parents=True)
    c.library.create(lib, '/tmp/ald-merge-fixture-' + run, technology_library=args.technology)
    controller = None
    try:
        with c.layout.create(lib, 'base') as edit:
            edit.add(f'dbCreateRect(cv {sk([args.layer,"drawing"])} list(0:0 2:1))')
            if args.complex:
                edit.add(f'''let((n term a b group rod prop)
                  n=dbCreateNet(cv "SIGNAL") term=dbCreateTerm(n "SIGNAL" "inputOutput")
                  a=dbCreateRect(cv {sk([args.layer, 'drawing'])} list(4:0 5:1))
                  b=dbCreateRect(cv {sk([args.layer, 'drawing'])} list(6:0 7:1))
                  dbCreatePin(n a "P0" term)
                  group=dbCreateFigGroup(cv "ordered" t 0:0 "R0")
                  dbAddFigToFigGroup(group a) dbAddFigToFigGroup(group b)
                  rod=rodCreatePath(?cvId cv ?name "ring" ?layer {sk([args.layer, 'drawing'])}
                    ?width 0.2 ?pts list(0:4 8:4) ?netName "SIGNAL" ?choppable t
                    ?subRect list(list(?layer {sk([args.layer, 'drawing'])} ?width 0.09 ?length 0.09
                      ?space 0.11 ?netName "SIGNAL" ?gap "distribute" ?choppable t)))
                  unless(rod error("MPP creation failed"))
                  prop=dbReplaceProp(rod~>dbId "note" "string" "synthetic annotation")
                  dbCreateTextDisplay(prop rod~>dbId {sk([args.layer, 'drawing'])} t
                    0:6 "lowerLeft" "R0" "roman" 0.2 t nil t nil t))''')
        adapter = VirtuosoAdapter(c, out / 'capture', writable_library=lib)
        base = adapter.capture(lib, 'base')
        def moved(x):
            records = copy.deepcopy(list(base['objects'].values()))
            r = next(r for r in records if r['kind'] == 'rect' and not r.get('mppOwner')
                     and (not args.complex or r.get('group')))
            r['bBox'] = [[v[0]+x, v[1]] for v in r['bBox']]
            return canonicalize(records)
        target, incoming = moved(100), moved(200)
        checked(c.load_il(root / 'layoutdiff/eda/virtuoso/skill/merge.il'))
        checked(c.load_il(root / 'layoutdiff/eda/virtuoso/skill/merge_repository.il'))
        worker = GuiWorker(c, out / 'worker')
        controller = MergeController(worker)
        opened = controller.start(base, target, incoming, metadata={'identity': [lib, 'base', 'layout']})
        print('Workspace opened', flush=True)
        token = opened['token']
        state = controller.opened[token]; session = state['session']
        assert len(session.unresolved()) == 1
        worker.execute(f'ALDMergeToggle({sk(token)} 0)')
        state['view'].highlight(state['selected'])
        assert loads(worker.execute(f'car(ALDMergeSessions[{sk(token)}][\'highlights])->enable')) is None
        worker.execute(f'ALDMergeBlink({sk(token)})')
        phase = worker.execute(f'ALDMergeSessions[{sk(token)}][\'phase]')
        time.sleep(.65)
        assert worker.execute(f'ALDMergeSessions[{sk(token)}][\'phase]') != phase
        worker.execute(f'ALDMergeBlink({sk(token)}) ALDMergeToggle({sk(token)} 0)')
        print('Highlight toggles and native blinking passed', flush=True)
        controller.action(token, 0, 'preview', 'incoming')
        assert session.snapshot == base and session.unresolved()
        controller.action(token, 0, 'accept')
        print('Preview and acceptance passed', flush=True)
        assert session.snapshot == incoming and not session.unresolved()
        controller.action(token, 1, 'undo')
        assert session.snapshot == base
        controller.action(token, 2, 'redo')
        print('Undo/redo passed', flush=True)
        assert session.snapshot == incoming
        controller.action(token, 3, 'edit')
        native = state['view'].current
        with c.layout.modify(native['library'], native['cell']) as edit:
            edit.add(f'dbCreateRect(cv {sk([args.layer,"drawing"])} list(20:0 21:1))')
        controller.action(token, 3, 'accept-edits')
        print('Native custom edit passed', flush=True)
        assert not session.unresolved()
        controller.action(token, 4, 'validate')
        saved = session.snapshot
        controller.action(token, 4, 'suspend')
        assert worker.execute(f'ALDMergeLeases[{sk(token)}]') == 'nil'
        controller.open(token)
        assert controller.opened[token]['session'].snapshot == saved
        controller.action(token, 4, 'suspend')
        if args.repository:
            from layoutdiff.git.commit import git
            from layoutdiff.git.store import snapshot_path
            from layoutdiff.git.merge import resolve
            from layoutdiff.data.history import atomic_json
            repo = out / 'repository'; repo.mkdir()
            git(repo, 'init', '-b', 'target')
            git(repo, 'config', 'user.name', 'Synthetic Merge Test')
            git(repo, 'config', 'user.email', 'test@example.invalid')
            path = repo / snapshot_path(['MERGE_SYNTH', 'example', 'layout'])
            path.parent.mkdir(parents=True)
            def save(snapshot):
                atomic_json(path, snapshot)
                git(repo, 'add', '--all'); git(repo, 'commit', '-m', 'Synthetic fixture')
                return resolve(repo, 'HEAD')
            save(base); git(repo, 'branch', 'incoming')
            before = save(target)
            git(repo, 'switch', 'incoming'); other = save(incoming)
            git(repo, 'switch', 'target')
            worker.git_repository = lambda: repo
            worker.merge_controller = controller
            opened = worker.dispatch(['merge-repository', 'start', '', 'incoming'])
            repo_token = opened['token']; tx = controller.repository(repo_token)
            key, = tx.state['cells']
            opened = worker.dispatch(['merge-repository', 'open-cell', repo_token, key])
            token = opened['token']; s = controller.opened[token]['session']
            for ident in s.unresolved():
                worker.dispatch(['merge-action', token, s.generation, 'select', ident])
                worker.dispatch(['merge-action', token, s.generation, 'preview', 'incoming'])
                worker.dispatch(['merge-action', token, s.generation, 'accept', ''])
            worker.dispatch(['merge-action', token, s.generation, 'finish', ''])
            worker.dispatch(['merge-repository', 'commit', repo_token, 'Merge synthetic layouts'])
            assert resolve(repo, 'HEAD') == before
            worker.dispatch(['merge-repository', 'publish', repo_token, ''])
            assert git(repo, 'show', '-s', '--format=%P', 'HEAD').stdout.decode().split() == [before, other]
            checked(c.execute_skill('hiFormCancel(ALDMergeRepositoryForm)'))
            print('PASS: native validation, nested runtime dispatch, two-parent Git commit and explicit publication', flush=True)
        print('PASS: native graphical alternatives, preview/accept, undo/redo, custom edit, validation and resume')
        print('Evidence:', out)
    finally:
        if controller:
            for state in list(controller.opened.values()):
                state['view'].close()
        c.library.delete(lib)


if __name__ == '__main__':
    main()
