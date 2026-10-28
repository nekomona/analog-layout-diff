import copy
import pytest
from layoutdiff.virtuoso.adapter import normalize, coverage, render
from layoutdiff.data.core import canonicalize, diff, apply_diff, empty_snapshot
from layoutdiff.data.storage import from_snapshot
from layoutdiff.virtuoso.logical_groups import resolve_records


def group(token, name='same', members=(), **fields):
    return {'kind': 'group', '_captureId': token, 'name': name, 'defName': 'unrestricted',
        'isSet': True, 'isCollection': None, 'isOrdered': None, 'isUniqueName': None,
        'deleteWhen': 'deleteNever', 'props': [], '_members': list(members), **fields}


def meta():
    return {'kind': 'cell', '_captureId': 1, 'name': '', 'dbu': 1000, 'units': 'micron',
            'cellType': 'maskLayout', 'props': []}


def shape(token, x=0):
    return {'kind': 'rect', '_captureId': token, 'layerName': 'MET1', 'purpose': 'drawing',
            'bBox': [[x, 0], [x+100, 100]], 'props': []}


def test_duplicate_group_names_nested_members_and_order_are_canonical(tmp_path):
    records = [meta(), shape(2), shape(3, 1000), group(4, members=[(2, 'rect', [])]),
        group(5, members=[(3, 'rect', [])]), group(6, 'parent', [(5, 'group', []), (4, 'group', [['role', 'string', 'second']])], isOrdered=True)]
    snap = normalize(copy.deepcopy(records))
    assert not coverage(snap)
    assert len([r for r in snap['objects'].values() if r['kind'] == 'group']) == 3
    assert snap == normalize(copy.deepcopy([records[0], *reversed(records[1:])]))
    assert from_snapshot(snap, tmp_path / 'v2').materialize() == snap
    patch = diff(empty_snapshot(), snap)
    assert apply_diff(empty_snapshot(), patch) == snap
    assert apply_diff(snap, patch, reverse=True) == empty_snapshot()
    code = '\n'.join(render(snap))
    assert code.count('dbCreateGroup(') == 3 and code.count('dbAddObjectToGroup(') == 4
    assert code.rindex('dbCreateRect(') < code.index('dbAddObjectToGroup(')
    assert 'dbReplaceProp(gm "role" "string" "second")' in code
    assert '_captureId' not in str(snap) and '_members' not in str(snap)


def test_unordered_group_members_sort_and_collections_keep_multiplicity():
    records = [meta(), shape(2), shape(3, 1000), group(4, members=[(3,'rect',[]),(2,'rect',[]),(2,'rect',[])], isSet=None, isCollection=True)]
    snap = normalize(copy.deepcopy(records))
    records[-1]['_members'].reverse()
    assert normalize(records) == snap
    g = next(r for r in snap['objects'].values() if r['kind'] == 'group')
    assert len(g['members']) == 3


def test_pin_and_instterm_aliases_do_not_leak_transport_ids():
    pinshape = shape(2)
    pinshape['pin'] = {'_captureId': 3, 'term': 'P', 'name': 'P', 'props': []}
    inst = {'kind':'inst','_captureId':4,'name':'I0','props':[], 'params':[], 'connections':[['A','P',[],5]]}
    snap = normalize([meta(), pinshape, inst, group(6, members=[(3,'pin',[]),(5,'instTerm',[])])])
    assert not coverage(snap)
    targets = next(r for r in snap['objects'].values() if r['kind']=='group')['members']
    assert {m['target'] for m in targets} == {'@pin:["P","P"]','@instTerm:["I0","A"]'}
    assert len(snap['objects']['inst:I0']['connections'][0]) == 3


@pytest.mark.parametrize('case', ['cycle','missing','ambiguous'])
def test_unrepresentable_links_are_explicit_coverage_errors(case):
    records = [meta(), shape(2), group(3, members=[(2,'rect',[])])]
    if case == 'cycle': records[-1]['_members']=[(3,'group',[])]
    elif case == 'missing': records[-1]['_members']=[(99,'route',[])]
    else: records.insert(2, shape(4))
    assert coverage(normalize(records))


def test_missing_persisted_group_reference_is_rejected_before_native_creation():
    g=group(2); g.pop('_captureId'); g.pop('_members'); g['members']=[{'target':'rect:missing:0','props':[]}]
    assert 'missing logical group member' in ' '.join(coverage(canonicalize([g])))


def test_cellview_membership_is_rejected_before_native_creation():
    snap = normalize([meta(), group(2, members=[(1, 'cellView', [])])])
    assert 'cellView cannot be a logical group member' in ' '.join(coverage(snap))
