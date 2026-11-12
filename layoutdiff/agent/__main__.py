"""Headless semantic operations. Git staging and commits remain with the caller."""
import argparse
import base64
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

from layoutdiff.agent import OPERATIONS, PROTOCOL
from layoutdiff.agent.service import AgentService, identifier
from layoutdiff.data.storage import strict_json
from layoutdiff.git.commit import discover


@contextmanager
def runner_lock(root):
    """Kernel-owned lock; never unlink its inode, even after a crash."""
    with (root / 'runner.lock').open('a+b') as lock:
        if os.name == 'nt':
            import msvcrt
            lock.write(b'0'); lock.flush(); lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == 'nt':
                lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)


def submit(root, ident, operation, payload):
    raw = operation + '\n' + json.dumps(payload, ensure_ascii=True, separators=(',', ':'), allow_nan=False)
    if len(raw.encode()) > 60000:
        raise ValueError('Request exceeds 60000 bytes')
    path = root / 'requests' / (ident + '.request')
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex)
    temp.write_text(raw, encoding='utf-8')
    created = False
    try:
        try:
            os.link(temp, path)
            created = True
        except FileExistsError:
            if path.read_text(encoding='utf-8') != raw:
                raise ValueError('Request ID already has a different payload')
    finally:
        temp.unlink()
    return created


def result(root, ident):
    requests = root / 'requests'
    if (requests / (ident + '.done')).exists():
        return strict_json((requests / (ident + '.result.json')).read_bytes())
    state = ('running' if (requests / (ident + '.running')).exists() else
             'pending' if (requests / (ident + '.request')).exists() else 'not-found')
    return {'protocol': PROTOCOL, 'request_id': ident, 'status': state}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, help='Dedicated state directory outside Git; separate from GUI state')
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--operation', choices=OPERATIONS)
    action.add_argument('--describe', action='store_true')
    action.add_argument('--result', action='store_true', help='Retrieve only; never submit or replay')
    action.add_argument('--execute', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--request-id')
    payload = parser.add_mutually_exclusive_group()
    payload.add_argument('--payload', help='JSON file, or - for stdin')
    payload.add_argument('--payload-base64', help=argparse.SUPPRESS)
    parser.add_argument('--submit', action='store_true', help='Submit asynchronously; retrieve using --result')
    parser.add_argument('--native-backend', choices=('none', 'batch'), default='none')
    parser.add_argument('--virtuoso', default='virtuoso', help='Batch Virtuoso executable')
    parser.add_argument('--virtuoso-cwd', help='Project working directory containing cds.lib and site setup')
    parser.add_argument('--validation-library', help='Dedicated existing writable native-validation library')
    parser.add_argument('--group-definition-source', nargs=3, metavar=('LIB', 'CELL', 'VIEW'))
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if discover(root) is not None:
        parser.error('--root must be outside any Git worktree')
    if not args.describe and not args.request_id:
        parser.error('--request-id is required')
    ident = identifier(args.request_id) if not args.describe else None
    if args.result:
        print(json.dumps(result(root, ident)))
        return 0
    if args.operation:
        if args.payload is None and args.payload_base64 is None:
            parser.error('--operation requires --payload')
        data = (base64.b64decode(args.payload_base64, validate=True) if args.payload_base64 is not None else
                sys.stdin.buffer.read(60001) if args.payload == '-' else Path(args.payload).read_bytes())
        if len(data) > 60000:
            raise ValueError('Request exceeds 60000 bytes')
        value = strict_json(data)
        if not isinstance(value, dict):
            raise ValueError('Expected a JSON request object')
        created = submit(root, ident, args.operation, value)
        if args.submit:
            if created:
                command = [sys.executable, '-m', 'layoutdiff.agent', '--root', str(root), '--request-id', ident,
                           '--execute', '--native-backend', args.native_backend, '--virtuoso', args.virtuoso]
                for option, value in (('--virtuoso-cwd', args.virtuoso_cwd),
                                      ('--validation-library', args.validation_library)):
                    if value:
                        command.extend([option, value])
                if args.group_definition_source:
                    command.extend(['--group-definition-source', *args.group_definition_source])
                with (root / 'requests' / (ident + '.log')).open('ab') as log:
                    subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                        start_new_session=os.name != 'nt',
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            print(json.dumps(result(root, ident)))
            return 0
    adapter = None
    if args.native_backend == 'batch':
        from layoutdiff.eda.virtuoso.batch import BatchAdapter
        adapter = BatchAdapter(args.virtuoso, args.virtuoso_cwd, root / 'native',
                               writable_library=args.validation_library,
                               group_definition_source=args.group_definition_source)
    service = AgentService(root, adapter=adapter, native_validate=adapter.validate if adapter and args.validation_library else None,
                           publish_capabilities=False, durable_diffs=True)
    try:
        if args.describe:
            print(json.dumps({**service.capabilities, 'running': True, 'transport': 'host',
                              'native_backend': args.native_backend, 'capture_state': 'saved_oa' if adapter else None}))
        else:
            with runner_lock(root):
                service.recover()
                service.poll(request_id=ident)
            print(json.dumps(result(root, ident)))
    finally:
        service.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
