#!/usr/bin/env python3
"""Local stdio MCP proxy. Only stdlib and virtuoso-bridge are required locally.

All Layout Diff imports, Git access and semantic analysis run in the remote
host. Select CIW or SSH transport explicitly; uncertain writes are never replayed.
"""
from __future__ import annotations
import argparse
import base64
from contextlib import redirect_stdout
import json
import re
import shlex
import sys
import time
import uuid

PROTOCOL = 'layoutdiff-agent/1'


def string(description=''):
    return {'type': 'string', 'description': description}


COMMON = {'request_id': string('Optional stable ID. Reuse only with identical arguments; retain it after a timeout.'),
          'wait_seconds': {'type': 'number', 'minimum': 0, 'maximum': 30, 'default': 10}}
CELL = {'type': 'array', 'items': {'type': 'string', 'minLength': 1}, 'minItems': 3, 'maxItems': 3,
        'description': '[library, cell, view]'}
REPO = string('Absolute Git worktree root on the remote Virtuoso host; never a local desktop path.')
PAGE = {'offset': {'type': 'integer', 'minimum': 0, 'default': 0},
        'limit': {'type': 'integer', 'minimum': 1, 'maximum': 50, 'default': 10},
        'category': string('Exact category label returned by the analysis.')}


def tool(name, description, properties, required=(), *, write=False):
    return {'name': name, 'description': description,
        'inputSchema': {'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False},
        'annotations': {'readOnlyHint': not write, 'destructiveHint': write, 'idempotentHint': not write,
                        'openWorldHint': False}}


TOOLS = [
    tool('layout_capabilities', 'Inspect the selected remote Layout Diff backend and protocol.', {}),
    tool('layout_diff', 'Semantic layout diff on the remote host. Pairs moves/stretches, reports connectivity and all changed fields. Supply repository/cellview initially, or analysis_id for another page.',
         {**COMMON, **PAGE, 'repository': REPO, 'cellview': CELL,
          'left': string('Git revision, worktree, live, or saved_oa (batch); default HEAD'),
          'right': string('Git revision, worktree, live, or saved_oa (batch); default worktree'),
          'analysis_id': string(), 'status': {'type': 'string', 'enum': ['added','modified','deleted','modified_net','moved']},
          'layer': string(), 'region': {'type': 'array', 'items': {'type': 'number'}, 'minItems': 4, 'maxItems': 4,
                                      'description': '[x0,y0,x1,y1] in integer snapshot DBU'}, 'records': {'type': 'boolean'}}),
    tool('layout_merge_plan', 'Analyze three Git revisions using the native merge editor decision model. Returns compound choices, reasons and evidence. Existing plan_id supports paging without rereading changing refs.',
         {**COMMON, **PAGE, 'repository': REPO, 'cellview': CELL, 'base': string(), 'ours': string('Default HEAD'),
          'theirs': string(), 'plan_id': string(), 'unit_id': string('Retrieve detailed changes and connected context for one decision.')}),
    tool('layout_merge_explain', 'Explain an ongoing Git merge initiated outside Layout Diff. Reads MERGE_HEAD, the merge base and index conflict stages. Preserves files, staged resolutions and the index. Ordinary-file conflicts are listed; layout conflicts receive semantic decisions and descriptions.',
         {**COMMON, **PAGE, 'repository': REPO, 'cellview': CELL, 'unit_id': string()}, ('repository',)),
    tool('layout_merge_apply', 'Preview, accept, or write a batch of merge decisions. write requires no unresolved decisions and checks pinned inputs. Updates only remote layout snapshot files; leaves Git staging and commits to the caller. Native readback validation is default for write.',
         {**COMMON, 'plan_id': string(), 'generation': {'type': 'integer', 'minimum': 0},
          'decisions': {'type': 'object', 'additionalProperties': {'type': 'string', 'enum': ['base','target','incoming','combined','both']}},
          'mode': {'type': 'string', 'enum': ['preview','accept','write'], 'default': 'preview'},
          'native_validation': {'type': 'boolean', 'default': True},
          'omission_consent': string('Token returned by an inspected incomplete-output preview; bound to the candidate and Git inputs.')}, ('plan_id','generation'), write=True),
    tool('layout_export', 'Capture a selected cellview into its remote project worktree. Batch capture reads saved OA; an attached session can read unsaved state. Returns semantic counts and paths for normal git add/commit. save=true requires an attached session. Dirty managed files require worktree_digest from layout_diff. allow_incomplete=true previews audited omissions before digest-bound consent.',
         {**COMMON, 'repository': REPO, 'cellview': CELL, 'save': {'type': 'boolean', 'default': False},
          'expected_worktree': string(), 'allow_incomplete': {'type': 'boolean', 'default': False},
          'omission_consent': string('Token returned by the incomplete-output preview; acknowledges omitted native content.')}, ('repository','cellview'), write=True),
    tool('layout_result', 'Retrieve a submitted request by its original ID after pending/timeout/unknown transport response. Never resubmits it.',
         COMMON, ('request_id',)),
]


def skill_string(value):
    # JSON is already ASCII; SKILL string escaping must preserve its backslashes.
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r') + '"'


class BridgeProxy:
    def __init__(self, client=None, *, profile=None):
        self.client, self.profile, self.buffers = client, profile, {}

    def execute(self, expression):
        if self.client is None:
            from virtuoso_bridge import VirtuosoClient
            self.client = VirtuosoClient.from_env(profile=self.profile)
        try:
            result = self.client.execute_skill(expression, timeout=15, retry_connect=False)
        except Exception as exc:
            # An exception after transmission is no proof that submission failed.
            raise BridgeFailure({'error': str(exc), 'error_type': type(exc).__name__}) from exc
        if str(getattr(result.status, 'value', result.status)) != 'success':
            raise BridgeFailure(result.model_dump(mode='json'))
        from virtuoso_bridge.virtuoso.skill_output import parse_sexpr
        return parse_sexpr(result.output)

    def describe(self):
        value = self.execute("if(getd('ALDAgentDescribe) then ALDAgentDescribe() else list(\"unavailable\"))")
        if not isinstance(value, list) or len(value) != 3 or value[0] != PROTOCOL:
            raise ValueError('Load the updated remote Layout Diff startup.il in the selected CIW')
        caps = json.loads(value[2])
        if caps.get('protocol') != PROTOCOL:
            raise ValueError('Remote Layout Diff protocol is incompatible')
        return {**caps, 'running': bool(value[1])}

    def submit(self, ident, operation, payload):
        expression = f'ALDAgentSubmit({skill_string(ident)} {skill_string(operation)} {skill_string(payload)})'
        if len(expression) > 60000:
            raise ValueError('Request is too large; use smaller decision batches')
        self.execute(expression)

    def result(self, ident, wait_seconds=10):
        if not isinstance(ident, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', ident):
            raise ValueError('Invalid request ID')
        deadline = time.monotonic() + wait_seconds
        chunks = self.buffers.setdefault(ident, [])
        while True:
            state = self.execute(f'ALDAgentResult({skill_string(ident)} {len(chunks)})')
            if not isinstance(state, list) or not state:
                raise ValueError('Invalid remote result envelope')
            if state[0] == 'complete':
                count = int(state[1])
                chunks.append(state[2])
                if len(chunks) == count:
                    result = json.loads(''.join(chunks))
                    self.buffers.pop(ident, None)
                    return result
                if count > 8192:
                    raise ValueError('Result exceeds transport limit; request a smaller semantic page')
                # Completed data is fetched immediately; no polling delay per chunk.
            elif state[0] not in {'pending', 'running'}:
                return {'request_id': ident, 'status': state[0]}
            if time.monotonic() >= deadline:
                return {'request_id': ident, 'status': state[0] if state[0] != 'complete' else 'retrieving',
                        'retrieved_pages': len(chunks), 'next_tool': 'layout_result'}
            if state[0] != 'complete':
                time.sleep(min(.5, max(0, deadline - time.monotonic())))

    def call(self, name, arguments):
        arguments = dict(arguments)
        wait = arguments.pop('wait_seconds', 10)
        if type(wait) not in (int, float) or not 0 <= wait <= 30:
            raise ValueError('wait_seconds must be between 0 and 30')
        ident = arguments.pop('request_id', None)
        if ident is None:
            if name == 'layout_result':
                raise ValueError('request_id is required')
            ident = uuid.uuid4().hex
        if not isinstance(ident, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', ident):
            raise ValueError('Invalid request ID')
        try:
            if name == 'layout_capabilities':
                return self.describe()
            if name == 'layout_result':
                return self.result(ident, wait)
            operation = name.removeprefix('layout_')
            caps = self.describe()
            if not caps['running'] or operation not in caps['operations']:
                raise ValueError('Remote worker is stopped or does not provide this operation')
            payload = json.dumps(arguments, ensure_ascii=True, separators=(',', ':'), allow_nan=False)
            self.submit(ident, operation, payload)
            return self.result(ident, wait)
        except BridgeFailure as exc:
            return {'request_id': ident, 'status': 'transport_unknown', 'bridge': exc.result,
                    'next_tool': 'layout_result', 'message': 'Retain this request ID. Reconcile its result before a new write.'}


class BridgeFailure(RuntimeError):
    def __init__(self, result):
        self.result = result
        super().__init__('Bridge request failed or its outcome is unknown')


class SSHProxy(BridgeProxy):
    """Use Bridge's SSH connection without connecting to or loading a CIW."""
    def __init__(self, *, python, root, profile=None, runner=None, native_backend='none',
                 virtuoso='virtuoso', virtuoso_cwd=None, validation_library=None, group_definition_source=None):
        super().__init__(profile=profile)
        if not python.startswith('/') or not root.startswith('/'):
            raise ValueError('SSH Python and state root must be absolute remote paths')
        self.runner = runner
        self.command = [python, '-m', 'layoutdiff.agent', '--root', root,
                        '--native-backend', native_backend, '--virtuoso', virtuoso]
        for option, value in (('--virtuoso-cwd', virtuoso_cwd), ('--validation-library', validation_library)):
            if value:
                self.command.extend([option, value])
        if group_definition_source:
            self.command.extend(['--group-definition-source', *group_definition_source])

    def invoke(self, *args):
        if self.runner is None:
            from virtuoso_bridge import SSHClient
            self.client = SSHClient.from_env(profile=self.profile)
            self.runner = self.client.ssh_runner
        try:
            result = self.runner.run_command(' '.join(shlex.quote(s) for s in [*self.command, *args]), timeout=30)
            if result.returncode:
                raise RuntimeError(result.stderr.strip() or 'Remote agent runner failed')
            value = json.loads(result.stdout)
            if value.get('protocol') != PROTOCOL:
                raise ValueError('Remote agent protocol is incompatible')
            return value
        except Exception as exc:
            raise BridgeFailure({'error': str(exc), 'error_type': type(exc).__name__}) from exc

    def describe(self):
        return self.invoke('--describe')

    def submit(self, ident, operation, payload):
        if len(payload.encode()) > 59000:
            raise ValueError('Request is too large; use smaller decision batches')
        value = self.invoke('--operation', operation, '--request-id', ident, '--submit',
                            '--payload-base64', base64.b64encode(payload.encode()).decode())
        if value.get('status') == 'error':
            raise ValueError(value.get('error', 'Remote request rejected'))

    def result(self, ident, wait_seconds=10):
        if not isinstance(ident, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', ident):
            raise ValueError('Invalid request ID')
        deadline = time.monotonic() + wait_seconds
        while True:
            value = self.invoke('--result', '--request-id', ident)
            if value.get('status') not in {'pending', 'running'} or time.monotonic() >= deadline:
                return value
            time.sleep(min(.5, max(0, deadline - time.monotonic())))


def dispatch(message, proxy):
    method, params = message.get('method'), message.get('params') or {}
    if method == 'initialize':
        requested = params.get('protocolVersion')
        version = requested if requested in ('2025-11-25', '2024-11-05') else '2025-11-25'
        return {'protocolVersion': version, 'capabilities': {'tools': {}},
                'serverInfo': {'name': 'layoutdiff-bridge-proxy', 'version': '1.0.0'}}
    if method == 'ping':
        return {}
    if method == 'tools/list':
        return {'tools': TOOLS}
    if method == 'tools/call':
        name, arguments = params.get('name'), params.get('arguments', {})
        definition = next((t for t in TOOLS if t['name'] == name), None)
        if definition is None or not isinstance(arguments, dict):
            raise ValueError('Unknown tool or invalid arguments')
        schema = definition['inputSchema']
        if set(arguments) - schema['properties'].keys() or set(schema['required']) - arguments.keys():
            raise ValueError('Unknown or missing tool arguments')
        try:
            result = proxy.call(name, arguments)
        except Exception as exc:
            result = {'status': 'error', 'error': str(exc)}
        return {'content': [{'type': 'text', 'text': json.dumps(result, ensure_ascii=True)}],
                'structuredContent': result,
                'isError': result.get('status') in {'error', 'unknown', 'transport_unknown'}}
    raise ValueError('Unsupported method: ' + str(method))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile')
    parser.add_argument('--env', help='Absolute local Bridge configuration file')
    parser.add_argument('--transport', choices=('ciw', 'ssh'), default='ciw')
    parser.add_argument('--remote-python', help='Absolute remote interpreter with Layout Diff installed')
    parser.add_argument('--remote-root', help='Dedicated remote headless state root outside Git')
    parser.add_argument('--native-backend', choices=('none', 'batch'), default='none')
    parser.add_argument('--virtuoso', default='virtuoso')
    parser.add_argument('--virtuoso-cwd')
    parser.add_argument('--validation-library')
    parser.add_argument('--group-definition-source', nargs=3, metavar=('LIB', 'CELL', 'VIEW'))
    args = parser.parse_args()
    if args.env:
        from virtuoso_bridge.env import set_runtime_env_file
        set_runtime_env_file(args.env)
    if args.transport == 'ssh':
        if not args.remote_python or not args.remote_root:
            parser.error('SSH transport requires --remote-python and --remote-root')
        proxy = SSHProxy(python=args.remote_python, root=args.remote_root, profile=args.profile,
            native_backend=args.native_backend, virtuoso=args.virtuoso, virtuoso_cwd=args.virtuoso_cwd,
            validation_library=args.validation_library, group_definition_source=args.group_definition_source)
    else:
        proxy = BridgeProxy(profile=args.profile)
    for line in sys.stdin:
        message = None
        try:
            message = json.loads(line)
            if 'id' not in message:
                continue
            # Bridge/dependency diagnostics must never corrupt MCP stdout.
            with redirect_stdout(sys.stderr):
                result = dispatch(message, proxy)
            response = {'jsonrpc': '2.0', 'id': message['id'], 'result': result}
        except Exception as exc:
            response = {'jsonrpc': '2.0', 'id': message.get('id') if isinstance(message, dict) else None,
                        'error': {'code': -32602, 'message': str(exc)}}
        print(json.dumps(response, ensure_ascii=True), flush=True)


if __name__ == '__main__':
    main()
