"""Standalone local MCP proxy and its bounded, non-replaying Bridge transport."""
import importlib.util
import json
import os
import shlex
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import pytest

from layoutdiff.agent import PROTOCOL
from layoutdiff.agent.service import AgentService
from layoutdiff.eda.virtuoso.sexpr import loads
from test_repository_merge import branches

SERVER = Path(__file__).resolve().parents[1] / 'mcp/layoutdiff_server.py'
spec = importlib.util.spec_from_file_location('layoutdiff_mcp_test', SERVER)
mcp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcp)


class Proxy(mcp.BridgeProxy):
    def __init__(self, service):
        super().__init__()
        self.service, self.submitted, self.lose_reply = service, 0, False
    def execute(self, expr):
        if 'ALDAgentDescribe' in expr:
            return [PROTOCOL, True, (self.service.root / 'capabilities.json').read_text()]
        name, args = expr.split('(', 1)
        args = loads('(' + args)
        if name == 'ALDAgentSubmit':
            ident, op, payload = args
            raw = op + '\n' + payload
            path = self.service.requests / (ident + '.request')
            if path.exists():
                if path.read_text() != raw:
                    raise ValueError('Request ID already has a different payload')
            else:
                path.write_text(raw)
                self.submitted += 1
            self.service.poll()
            if self.lose_reply:
                self.lose_reply = False
                raise mcp.BridgeFailure({'metadata': {'outcome': 'unknown'}})
            return ['accepted', ident]
        ident, page = args
        done = self.service.requests / (ident + '.done')
        if not done.exists():
            return ['not_found', ident]
        return ['complete', int(done.read_text()), (self.service.requests / f'{ident}.page.{page}').read_text()]


def test_local_proxy_roundtrip_and_lost_submission_receipt(tmp_path):
    repo, _, _ = branches(tmp_path)
    service = AgentService(tmp_path / 'remote-state')
    proxy = Proxy(service)
    try:
        args = {'repository': str(repo), 'cellview': ['TEST','a','layout'], 'theirs': 'incoming', 'request_id': 'stable'}
        proxy.lose_reply = True
        response = proxy.call('layout_merge_plan', args)
        assert response['status'] == 'transport_unknown' and response['request_id'] == 'stable'
        result = proxy.call('layout_result', {'request_id': 'stable'})
        assert result['status'] == 'complete' and result['result']['unresolved'] == 1
        assert proxy.submitted == 1
        assert proxy.call('layout_merge_plan', args)['result'] == result['result']
        assert proxy.submitted == 1
    finally:
        service.close()


def test_stdio_catalog_needs_neither_layoutdiff_nor_bridge_import(tmp_path):
    requests = [
        {'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25'}},
        {'jsonrpc':'2.0','method':'notifications/initialized'},
        {'jsonrpc':'2.0','id':2,'method':'tools/list'},
    ]
    run = subprocess.run([sys.executable, '-I', '-S', str(SERVER)], cwd=tmp_path,
        input=''.join(json.dumps(r) + '\n' for r in requests), text=True, capture_output=True, timeout=15)
    assert run.returncode == 0, run.stderr
    responses = [json.loads(line) for line in run.stdout.splitlines()]
    assert len(responses) == 2
    tools = {t['name']: t for t in responses[1]['result']['tools']}
    assert 'layout_merge_explain' in tools
    assert tools['layout_merge_explain']['annotations']['readOnlyHint']
    assert not tools['layout_export']['annotations']['readOnlyHint']


def test_skill_string_preserves_json_and_cannot_escape_string():
    value = json.dumps({'text': 'quote " parens ) and slash \\ newline\n \u4e2d'})
    assert loads(mcp.skill_string(value)) == value


def test_transport_exception_retains_original_request_id():
    class Client:
        def execute_skill(self, expression, **kwargs):
            assert kwargs['retry_connect'] is False
            raise TimeoutError('reply lost')
    proxy = mcp.BridgeProxy(Client())
    proxy.describe = lambda: {'running': True, 'operations': ['merge_apply']}
    result = proxy.call('layout_merge_apply', {'request_id': 'write_once', 'plan_id': 'plan', 'generation': 0})
    assert result['status'] == 'transport_unknown'
    assert result['request_id'] == 'write_once' and result['next_tool'] == 'layout_result'


def test_invalid_request_ids_are_rejected_before_transport():
    proxy = mcp.BridgeProxy()
    for ident in ('', '../escape', 123, 'x' * 65):
        with pytest.raises(ValueError, match='request ID'):
            proxy.call('layout_result', {'request_id': ident})
    with pytest.raises(ValueError, match='required'):
        proxy.call('layout_result', {})


def test_partial_transport_pages_resume_without_submission():
    proxy = mcp.BridgeProxy()
    raw = json.dumps({'status': 'complete', 'request_id': 'paged', 'text': '\u4e2d' * 600})
    pages = [raw[i:i+2048] for i in range(0, len(raw), 2048)]
    calls = []
    def execute(expression):
        args = loads('(' + expression.split('(', 1)[1])
        ident, cursor = args
        calls.append(cursor)
        return ['complete', len(pages), pages[cursor]]
    proxy.execute = execute
    result = proxy.call('layout_result', {'request_id': 'paged', 'wait_seconds': 0})
    assert result['status'] == 'retrieving' and calls == [0]
    result = proxy.call('layout_result', {'request_id': 'paged'})
    assert result == json.loads(raw) and calls == list(range(len(pages)))


def test_ssh_transport_uses_host_runner_and_reconciles_lost_submission(tmp_path):
    """Run the real headless CLI through a local substitute for Bridge's SSH."""
    repo = tmp_path / 'repository with spaces'; repo.mkdir()
    from layoutdiff.git.commit import git
    git(repo, 'init')
    class Runner:
        submissions = 0
        def run_command(self, command, timeout=None):
            args = shlex.split(command)
            assert args[0] == '/remote/python'
            args[0] = sys.executable
            args[args.index('--root') + 1] = str(tmp_path / 'state')
            completed = subprocess.run(args, text=True, capture_output=True, timeout=timeout,
                env={**os.environ, 'GIT_CEILING_DIRECTORIES': str(tmp_path)})
            if '--submit' in args:
                self.submissions += 1
                raise TimeoutError('Accepted request; SSH receipt lost')
            return SimpleNamespace(returncode=completed.returncode, stdout=completed.stdout, stderr=completed.stderr)
    runner = Runner()
    proxy = mcp.SSHProxy(python='/remote/python', root='/remote/state', runner=runner)
    caps = proxy.call('layout_capabilities', {})
    assert caps['native_capture'] is False and caps['native_backend'] == 'none'
    response = proxy.call('layout_merge_explain', {'repository': str(repo), 'request_id': 'once'})
    assert response['status'] == 'transport_unknown' and runner.submissions == 1
    result = proxy.call('layout_result', {'request_id': 'once'})
    assert result['status'] == 'complete' and result['result']['active_merge'] is False
    assert runner.submissions == 1
