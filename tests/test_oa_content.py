import copy
from contextlib import closing
import random

import pytest

from layoutdiff.data.core import canonicalize, diff, apply_diff, empty_snapshot
from layoutdiff.eda.virtuoso.adapter import normalize, render
from layoutdiff.eda.virtuoso.support import coverage, checked_records, UnsupportedContentError
from layoutdiff.data.storage import from_snapshot
from layoutdiff.data.streampatch import create, apply
from layoutdiff.comparison.categories import CategoryDiff, category
from layoutdiff.comparison.changeindex import ChangeIndex
from layoutdiff.comparison.review import classify


def records():
    return [
        dict(kind='cell', name='', _captureId=1, dbu=1000, units='micron', cellType='none',
             props=[['metadata', 'hierProp', [['note', 'string', 'nested']]]]),
        dict(kind='rect', _captureId=2, layerName='MET1', purpose='drawing',
             bBox=[[0, 0], [1000, 1000]], props=[]),
        dict(kind='layerBlockage', _captureId=3, _refs=[['owner', None], ['parent', [2, 'rect']]],
             layer='MET1', type='routing', points=[[0, 0], [0, 2000], [2000, 2000], [2000, 0]],
             density=0.0, isPushedDown=None, effectiveWidth=100, spacing=None, allowPGNet=True,
             maskColor='grayColor', props=[]),
        dict(kind='snapBoundary', _captureId=4, _refs=[['parent', None]],
             points=[[0, 0], [0, 3000], [3000, 3000], [3000, 0]], edgeNames=['L','T','R','B'], props=[]),
        dict(kind='sitePattern', entries=[['IOSite', [0, 0], 'R0'], ['IOSite', [10, 20], 'MY']], props=[]),
        dict(kind='textDisplay', _captureId=5, _refs=[['owner', [1,'cellView']], ['associate', [1,'cellView']], ['parent',None]],
             associateProperty=['metadata','note'], ownerProperty=['metadata'], assocType='propAssocType',
             xy=[100,200], text='note', height=0, orient='R0', justify='lowerLeft', font='roman',
             isDrafted=True, isOverbar=None, isVisible=True, isNameVisible=None, isValueVisible=True,
             layerName='text', purpose='drawing', props=[]),
        dict(kind='group', _captureId=6, _members=[[3,'layerBlockage',[]],[5,'textDisplay',[]]],
             name='annotations', defName='unrestricted', isSet=True, isCollection=None, isOrdered=None,
             isUniqueName=True, deleteWhen='deleteNever', props=[])]


def test_reference_resolution_is_order_independent_and_roundtrips_v2(tmp_path):
    original = records()
    snapshot = normalize(copy.deepcopy(original))
    assert not coverage(snapshot)
    rng = random.Random(26)
    for _ in range(8):
        rest = copy.deepcopy(original[1:]); rng.shuffle(rest)
        assert normalize([copy.deepcopy(original[0]), *rest]) == snapshot
    with closing(from_snapshot(snapshot, tmp_path/'layout')) as store:
        assert store.materialize() == snapshot
    assert '_captureId' not in str(snapshot) and '_refs' not in str(snapshot)
    code = '\n'.join(render(snapshot))
    assert code.index('dbCreateRect') < code.index('dbCreateLayerBlockage')
    assert code.index('dbCreateTextDisplay') < code.index('dbAddObjectToGroup')
    assert 'dbGetPropByName(dbGetPropByName(figures["cell:"] "metadata") "note")' in code
    assert 'o~>density=' not in code
    assert 'dbCreateLayerBlockage(cv "MET1" "routing"' in code
    assert 'cv~>sitePattern=list(list("IOSite" list(0.0 0.0)' in code


def test_add_edit_delete_chain_compact_patches_and_category_parity(tmp_path):
    source = records()
    states = [empty_snapshot(), normalize(copy.deepcopy(source))]
    source[2]['props'] = [['note', 'string', 'changed']]
    source[4]['entries'].reverse()
    source[5]['isOverbar'] = True
    states.append(normalize(copy.deepcopy(source)))
    source = [r for r in source if r['kind'] not in {'textDisplay', 'sitePattern', 'snapBoundary', 'group'}]
    states.append(normalize(source))
    stores = [from_snapshot(s, tmp_path/str(i)) for i,s in enumerate(states)]
    try:
        for i, (a,b) in enumerate(zip(states,states[1:])):
            patch = diff(a,b)
            assert apply_diff(a,patch) == b and apply_diff(b,patch,reverse=True) == a
            create(stores[i],stores[i+1],tmp_path/f'patch{i}',backend='python')
            with closing(apply(stores[i],tmp_path/f'patch{i}',tmp_path/f'applied{i}',backend='python')) as result:
                assert result.materialize() == b
            with closing(apply(stores[i+1],tmp_path/f'patch{i}',tmp_path/f'undo{i}',backend='python',reverse=True)) as result:
                assert result.materialize() == a
            idx = ChangeIndex(stores[i], stores[i+1])
            try:
                assert idx.rows == CategoryDiff(patch['operations']).rows
            finally:
                idx.close()
        assert category(source[2]) == 'MET1 blockages'
        assert category(records()[3]) == 'Snap boundary'
        assert category(records()[4]) == 'Placement site pattern'
        assert category(records()[5]) == 'text text displays'
        removed = classify(states[2],states[3])['removed']
        assert any(states[2]['objects'][k]['kind']=='textDisplay' for k in removed)
    finally:
        for store in stores: store.close()


@pytest.mark.parametrize('problem', ['missing','ambiguous','cycle','cross_cell','label','property'])
def test_unsupported_references_are_complete_scan_errors(tmp_path, problem):
    source = records()
    if problem in {'missing','cross_cell'}:
        source[5]['_refs'][1][1] = [999,'term']
    elif problem == 'ambiguous':
        source.insert(2,{**copy.deepcopy(source[1]), '_captureId':99})
    elif problem == 'cycle':
        source[2]['_refs'][1][1]=[3,'layerBlockage']
    elif problem == 'label':
        source[5]['assocType']='labelAssocType'
    elif problem == 'property':
        source[5]['associateProperty']=['missing']
    snap = normalize(source)
    assert coverage(snap)
    if problem != 'property':
        with pytest.raises(UnsupportedContentError) as err:
            list(checked_records(snap['objects'].values(),tmp_path/'unsupported.jsonl'))
        assert err.value.report.exists()


def test_boundary_and_site_validation():
    snapshot = normalize(records())
    duplicated = list(snapshot['objects'].values())
    duplicated.append({**next(r for r in duplicated if r['kind']=='sitePattern'), 'entries':[['IOSite',[5,0],'R0']]})
    assert 'multiple sitePattern' in ' '.join(coverage(canonicalize(duplicated)))
    bad = records(); bad[4]['entries']=[['IOSite',[0,1],'R0','discarded?']]
    assert 'invalid sitePattern entry' in ' '.join(coverage(normalize(bad)))


def test_terminal_changes_propagate_to_dynamic_display_as_modified_net():
    term = dict(kind='term', name='P', net='P', direction='input', props=[])
    td = dict(kind='textDisplay', owner='term:P', associate='term:P', text='name', xy=[0,0])
    before = canonicalize([term, td])
    after = canonicalize([{**term, 'direction':'output'}, td])
    assert classify(before,after)['counts']['netChanged'] == 1


def test_transport_pin_ids_are_removed_from_linked_figures():
    source = records()
    source[5]['pin'] = dict(_captureId=100, term='P', name='P', primary=True, props=[])
    snap = normalize(source)
    assert '_captureId' not in str(snap)
