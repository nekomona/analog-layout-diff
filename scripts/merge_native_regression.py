"""Exercise native graphical preview/accept/edit/undo/resume on synthetic data."""
import argparse
import copy
from pathlib import Path
import sys
import tempfile
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
        adapter = VirtuosoAdapter(c, out / 'capture', writable_library=lib)
        base = adapter.capture(lib, 'base')
        def moved(x):
            records = copy.deepcopy(list(base['objects'].values()))
            r = next(r for r in records if r['kind'] == 'rect')
            r['bBox'] = [[v[0]+x, v[1]] for v in r['bBox']]
            return canonicalize(records)
        target, incoming = moved(100), moved(200)
        checked(c.load_il(root / 'layoutdiff/eda/virtuoso/skill/merge.il'))
        worker = GuiWorker(c, out / 'worker')
        controller = MergeController(worker)
        opened = controller.start(base, target, incoming, metadata={'identity': [lib, 'base', 'layout']})
        print('Workspace opened', flush=True)
        token = opened['token']
        state = controller.opened[token]; session = state['session']
        assert len(session.unresolved()) == 1
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
            edit.add('car(cv~>shapes)~>bBox=list(0.3:0 2.3:1)')
        controller.action(token, 3, 'accept-edits')
        print('Native custom edit passed', flush=True)
        assert not session.unresolved()
        controller.action(token, 4, 'validate')
        saved = session.snapshot
        controller.action(token, 4, 'suspend')
        controller.open(token)
        assert controller.opened[token]['session'].snapshot == saved
        controller.action(token, 4, 'suspend')
        print('PASS: native graphical alternatives, preview/accept, undo/redo, custom edit, validation and resume')
        print('Evidence:', out)
    finally:
        if controller:
            for state in list(controller.opened.values()):
                state['view'].close()
        c.library.delete(lib)


if __name__ == '__main__':
    main()
