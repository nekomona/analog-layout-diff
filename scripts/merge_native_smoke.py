"""Verify docked native merge controls in a new disposable library only."""
import argparse
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from virtuoso_bridge import SSHClient, VirtuosoClient
from layoutdiff.eda.virtuoso.adapter import checked
from layoutdiff.eda.virtuoso.sexpr import dumps as sk, loads


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile')
    parser.add_argument('--technology', required=True)
    parser.add_argument('--layer', required=True)
    parser.add_argument('--keep-open', action='store_true')
    args = parser.parse_args()
    tunnel = SSHClient.from_env(profile=args.profile)
    tunnel.warm()
    c = VirtuosoClient.from_tunnel(tunnel)
    token = uuid.uuid4().hex
    lib = 'ALD_MERGE_TEST_' + token[:12]
    assert args.technology in c.library.list()
    c.library.create(lib, '/tmp/ald-merge-smoke-' + token, technology_library=args.technology)
    with c.layout.create(lib, 'result') as edit:
        edit.add(f'dbCreateRect(cv {sk([args.layer, "drawing"])} list(0:0 2:1))')
    root = Path(__file__).resolve().parents[1]
    # Existing runtime helpers are required; do not reload/stop another worker.
    assert checked(c.execute_skill("boundp('ALDGUIWindows)")) == 't', 'Load the Layout Diff runtime first'
    checked(c.load_il(root / 'layoutdiff/eda/virtuoso/skill/merge.il'))
    def call(expr):
        result = c.execute_skill(expr, timeout=60)
        if result.warnings:
            raise RuntimeError(result.warnings)
        return checked(result)
    try:
        call(f'ALDMergeOpen({sk(token)} {sk(lib)} "result" 0 "Native merge shell test")')
        call(f'ALDMergeUpdate({sk(token)} 1 {sk([["C001", args.layer + " shapes", "unresolved"]])} '
             '"1 unresolved" "Both branches moved this rectangle. Preview a branch, then accept.")')
        call(f'ALDMergeDetails({sk(token)} "Optional serialized preview")')
        call(f'ALDMergeBusy({sk(token)} "Preparing preview")')
        call(f'ALDMergeBusy({sk(token)} "")')
        state = loads(call(f'let((s) s=ALDMergeSessions[{sk(token)}] '
                          'list(length(s[\'docks]) s[\'generation] s[\'window]->displayCellView~>mode))'))
        assert state == [3, 1, 'r'], state
        print('PASS: native docked forms, toolbar, inline loading, details and read-only result')
    finally:
        if not args.keep_open:
            call(f'ALDMergeClose({sk(token)} t)')
            c.library.delete(lib)
    print('Test library:', lib)


if __name__ == '__main__':
    main()
