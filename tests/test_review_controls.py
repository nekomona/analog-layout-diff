import copy
from layoutdiff.core import canonicalize, diff
from layoutdiff.review import classify, modification
from layoutdiff.categories import CategoryDiff
from layoutdiff.changeindex import ChangeIndex
from layoutdiff.storage import from_snapshot
from layoutdiff.review_groups import boundary_targets
from layoutdiff.gui import display_resource, GuiWorker
from layoutdiff.history import atomic_json


def rect(x=0, **extra):
    return dict(kind='rect', layerName='MET1', purpose='drawing', bBox=[[x, 0], [x+1, 1]], props=[], **extra)


def test_net_only_mixed_changes_and_metadata_propagation():
    net = dict(kind='net', name='N', props=[])
    inst = dict(kind='inst', name='I', connections=[['A', 'N', []]])
    before = canonicalize([net, inst, rect(net='N'), rect(2, net='N'), rect(4, net='N')])
    after = canonicalize([{**net, 'props': [['x', 'int', 1]]}, inst,
        rect(net='P'), {**rect(2, net='N'), 'props': [['note', 'string', 'changed']]}, rect(4, net='N')])
    saved = copy.deepcopy([before, after])
    result = classify(before, after)
    assert result['counts'] == dict(untouched=0, changed=1, moved=0, netChanged=3, new=0)
    assert [before, after] == saved
    assert modification(inst, {**inst, 'connections': [['A', 'P', []]]}) == 'netChanged'
    assert modification(inst, {**inst, 'connections': [['A', 'P', []]], 'xy': [2, 3]}) == 'moved'


def test_pin_nonconnectivity_properties_remain_modified():
    a = rect(net='N', pin={'term': 'A', 'name': 'A', 'props': [], 'accessDir': ['left']})
    b = copy.deepcopy(a); b['pin']['term'] = b['pin']['name'] = 'B'
    assert modification(a, b) == 'netChanged'
    b['pin']['accessDir'] = ['right']
    assert modification(a, b) == 'changed'


def test_category_reference_and_streaming_separate_net_edits(tmp_path):
    before = canonicalize([rect(net='N'), rect(2), {'kind': 'net', 'name': 'N', 'props': []}])
    after = canonicalize([rect(net='P'), {**rect(2), 'props': [['x', 'int', 1]]},
                         {'kind': 'net', 'name': 'N', 'props': [['tag', 'int', 1]]}])
    reference = CategoryDiff(diff(before, after)['operations'])
    stores = [from_snapshot(s, tmp_path / str(i)) for i, s in enumerate((before, after))]
    index = ChangeIndex(*stores)
    try:
        assert index.rows == reference.rows
        assert dict(index.totals) == dict(reference.totals) == dict(added=0, modified=1, deleted=0, modified_net=2, moved=0)
        assert len([r for r in index.rows if r[0].startswith('Modified net /')]) == 2
        assert sum(r[2] for r in index.rows) == 1
        assert sum(r[4] for r in index.rows) == 2
        net_row = next(r for r in index.rows if r[0] == 'Modified net / MET1 shapes')
        assert net_row[1:] == [0, 0, 0, 1, 0]
        assert 'Modified net / MET1 shapes: 0A, 0M, 0D, 1MN' in index.overview()
        assert index.overview() == reference.overview()
        page = index.page(index.rows.index(net_row), 0)
        assert page['count'] == 1 and page['pages'] == 1
        assert 'MODIFIED_NET' in page['text']
        assert '"net"' in ''.join(index.full())
    finally:
        index.close()
        for s in stores: s.close()


def test_group_lifecycle_does_not_recolor_members_and_bounds_include_deleted():
    groups = [dict(kind='figGroup', name=n, props=[]) for n in ('modify', 'delete')]
    old = canonicalize([*groups, rect(group='modify'), rect(3, group='delete'), rect(5)])
    new = canonicalize([{**groups[0], 'props': [['edit', 'int', 1]]},
        dict(kind='figGroup', name='add', props=[]), rect(group='modify'), rect(3), rect(5, group='add')])
    result = classify(old, new)
    assert result['counts'] == dict(untouched=3, changed=0, moved=0, netChanged=0, new=0)
    assert {(g['name'], g['status'], g['side']) for g in result['group_changes']} == {
        ('modify', 'changed', 'after'), ('delete', 'deleted', 'before'), ('add', 'new', 'after')}
    for state, name in [(old, 'delete'), (new, 'add')]:
        targets = boundary_targets(state, ['figGroup:' + name])
        assert len(targets[0][1]) == 1 and targets[0][1][0].startswith('rect:')


def test_nested_logical_groups_pins_and_empty_groups():
    shape = rect(pin={'term': 'P', 'name': 'P'})
    inst = dict(kind='inst', name='I')
    child = dict(kind='group', name='child', defName='unrestricted', isOrdered=False,
                 members=[{'target': '@pin:["P","P"]', 'props': []}, {'target': '@instTerm:["I","A"]', 'props': []}])
    snapshot = canonicalize([shape, inst, child])
    child_key = next(k for k, r in snapshot['objects'].items() if r['kind'] == 'group')
    parent = {**child, 'name': 'parent', 'members': [{'target': child_key, 'props': []}]}
    empty = {**child, 'name': 'empty', 'members': []}
    snapshot = canonicalize([shape, inst, child, parent, empty])
    keys = {r['name']: k for k, r in snapshot['objects'].items() if r['kind'] == 'group'}
    targets = dict(boundary_targets(snapshot, keys.values()))
    assert targets[keys['empty']] == []
    assert targets[keys['child']] == targets[keys['parent']]
    assert len(targets[keys['child']]) == 2 and 'inst:I' in targets[keys['child']]
    updated = canonicalize([shape, inst, {**child, 'props': [['x', 'int', 1]]}, empty])
    assert any(g['name'] == 'child' and g['status'] == 'changed' for g in classify(snapshot, updated)['group_changes'])


def test_legacy_styles_migrate_and_blink_is_driven_by_window_timer(tmp_path):
    atomic_json(tmp_path / 'styles.json', {'changed': ['Blue', 'Dotted', '5']})
    worker = GuiWorker(None, tmp_path)
    assert worker.styles['changed'] == ['Blue', 'Dotted', '5', 'Steady']
    assert 'netChanged' in worker.styles and 'groupDeleted' in worker.styles
    assert worker.styles['netChanged'][0] != worker.styles['changed'][0]
    assert worker.styles['moved'][0] not in {worker.styles[k][0] for k in ('changed','netChanged','new','deleted','untouched')}
    assert worker.styles['deleted'] == ['Red', 'Dashed', '3', 'Steady']
    assert ' 0 220 255 nil)' in display_resource('packet', ['Cyan', 'Solid', '3', 'Blink'])
    assert ' 0 220 255 nil)' in display_resource('packet', ['Cyan', 'Solid', '3', 'Steady'])


def test_geometry_changes_separate_from_mixed_edits_and_net_only():
    a=rect(net='N')
    assert modification(a,rect(5,net='N'))=='moved'
    assert modification(a,rect(5,net='P'))=='moved'
    assert modification(a,rect(net='P'))=='netChanged'
    assert modification(a,{**rect(5,net='N'),'props':[['x','int',1]]})=='changed'
    assert modification(a,{**rect(5,net='N'),'layerName':'MET2'})=='changed'
    inst=dict(kind='inst',name='I',xy=[0,0],orient='R0',params=[['w','float',1]])
    assert modification(inst,{**inst,'xy':[100,0]})=='moved'
    assert modification(inst,{**inst,'xy':[100,0],'params':[['w','float',2]]})=='changed'
    assert modification(inst,{**inst,'xy':[100,0],'orient':'R90'})=='changed'


def test_style_matrix_validates_all_rows_before_applying(tmp_path):
    import pytest
    worker = GuiWorker(None, tmp_path)
    worker.reviews['test'] = {}
    original = copy.deepcopy(worker.styles)
    for rows in ([['deleted', 'Red', 'Solid', '3', 'Blink'], ['new', 'invalid', 'Solid', '3']],
                 [['deleted', 'Red', 'Solid', '3']] * 2):
        with pytest.raises(ValueError):
            worker.styles_batch('test', rows)
        assert worker.styles == original
        assert not (tmp_path / 'styles.json').exists()


def test_deleted_overlays_exclude_matched_edits_and_metadata(tmp_path):
    old = canonicalize([rect(), rect(4), {'kind': 'net', 'name': 'old', 'props': []}])
    new = canonicalize([{**rect(), 'props': [['note', 'string', 'edit']]}])
    result = classify(old, new)
    from layoutdiff.review import VISUAL
    deleted = [old['objects'][k] for k in result['removed'] if old['objects'][k]['kind'] in VISUAL]
    assert deleted == [rect(4)]


def test_shadow_helper_is_shared_and_released(tmp_path, monkeypatch):
    import layoutdiff.gui as gui
    worker = GuiWorker(None, tmp_path)
    calls, builds = [], []
    class Adapter:
        last_dependency_warnings = []
        def __init__(self, *a, **kw): pass
        def reconstruct(self, *a, **kw): builds.append((a, kw))
    monkeypatch.setattr(gui, 'VirtuosoAdapter', Adapter)
    def execute(code):
        calls.append(code)
        if code.startswith('ALDGUIGroupBounds'): return '(("figGroup:g" ((0 0) (1 1))))'
        if code.startswith('ALDGUIPrepareShadows'): return '(1 1 nil)'
        return 't'
    worker.execute = execute
    old = canonicalize([rect(group='g'), dict(kind='figGroup', name='g', props=[])])
    new = canonicalize([])
    bounds, warnings, shadows = worker.group_boundaries(old, new, classify(old, new), 'review')
    assert len(builds) == 1 and bounds[0]['bBox'] == [[0, 0], [1, 1]]
    assert shadows == dict(count=1, primitives=1, fallbacks=[])
    assert any(c.startswith('ALDGUIDiscard') for c in calls)
    assert not warnings
