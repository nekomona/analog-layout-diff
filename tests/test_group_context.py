import copy
from types import SimpleNamespace
import pytest
from layoutdiff.data.core import canonicalize
from layoutdiff.virtuoso.adapter import VirtuosoAdapter


def snapshot(definition='lxImplicitBus'):
    return canonicalize([
        dict(kind='cell', name='', dbu=1000, units='micron', cellType='maskLayout',
             technology='TECH', props=[]),
        dict(kind='group', name='G', defName=definition, isSet=True, isCollection=None,
             isOrdered=None, isUniqueName=None, deleteWhen='deleteNever', members=[], props=[]),
    ])


def result(output):
    return SimpleNamespace(status='success', output=output)


@pytest.mark.parametrize('definition,source', [('unrestricted', ['L', 'C', 'layout']),
                                               ('lxImplicitBus', None)])
def test_context_does_not_open_source_unnecessarily(tmp_path, definition, source):
    worker = VirtuosoAdapter(None, tmp_path)
    context = worker.prepare_group_context(snapshot(definition), source)
    assert not context['loaded']
    assert context['required'] == ([] if definition == 'unrestricted' else [definition])


@pytest.mark.parametrize('reply,loaded', [('(t ("unrestricted" "lxImplicitBus" "lxImplicitBus"))', True),
                                       ('(nil nil)', False)])
def test_context_read_is_balanced_readonly_and_preserves_snapshot(tmp_path, reply, loaded):
    calls = []
    class Client:
        def execute_skill(self, code, **kwargs):
            calls.append(code)
            return result(reply)
    adapter = VirtuosoAdapter(Client(), tmp_path)
    state = snapshot()
    original = copy.deepcopy(state)
    context = adapter.prepare_group_context(state, ['L', 'C', 'layout'])
    assert context['loaded'] == loaded and context['required'] == ['lxImplicitBus']
    assert context['source_definitions'] == (['lxImplicitBus', 'unrestricted'] if loaded else [])
    assert state == original
    assert len(calls) == 1
    assert 'dbOpenCellViewByType("L" "C" "layout" "maskLayout" "r")' in calls[0]
    assert 'unwindProtect' in calls[0] and 'dbClose(cv)' in calls[0]
    assert 'dbSave' not in calls[0] and 'dbReopen' not in calls[0]


@pytest.mark.parametrize('failure', ['("G" "lxImplicitBus")', 'nil'])
def test_native_group_failure_survives_generic_load_wrapper(tmp_path, failure):
    class Edit:
        def __enter__(self):
            self.commands = ['open()']
            return self
        def add(self, command): pass
        def __exit__(self, *args):
            raise RuntimeError('layout edit failed: load wrapper at line 5')
    class Client:
        library = SimpleNamespace(get=lambda lib: SimpleNamespace(technology_library='TECH'))
        layout = SimpleNamespace(create=lambda *a, **k: Edit())
        def load_il(self, *args, **kwargs): return result('t')
        def execute_skill(self, code, **kwargs):
            if code.startswith('ddGetObj'): return result('nil')
            if code.startswith("when(boundp('ALDReplayGroupFailure)"): return result(failure)
            return result('t')
    adapter = VirtuosoAdapter(Client(), tmp_path)
    if failure != 'nil':
        with pytest.raises(ValueError, match="logical group 'G'.*definition 'lxImplicitBus'"):
            adapter.reconstruct(snapshot(), adapter.writable_library, 'fresh')
    else:
        with pytest.raises(RuntimeError, match='load wrapper'):
            adapter.reconstruct(snapshot(), adapter.writable_library, 'fresh')
