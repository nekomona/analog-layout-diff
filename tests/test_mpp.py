import copy
import json
import pytest
from layoutdiff.data.core import canonicalize, diff, apply_diff, encoded
from layoutdiff.eda.virtuoso.adapter import render
from layoutdiff.eda.virtuoso.support import coverage
from layoutdiff.data.storage import from_snapshot
from layoutdiff.eda.virtuoso.native_equivalence import via_default_projection
from layoutdiff.comparison.review import classify
from layoutdiff.eda.virtuoso.omissions import project


def records():
    return [dict(kind='cell',name='',dbu=1000,units='micron',cellType='maskLayout',technology='test',props=[]),
      dict(kind='net',name='VSS',props=[],sigType='signal',isGlobal=None,connStatus=None,criticality=None,routePattern=None,source=None),
      dict(kind='path',points=[[0,0],[10000,0]],width=200,pathStyle='truncateExtend',beginExt=0,endExt=0,
        layerName='ACT',purpose='drawing',props=[],mpp=dict(name='ring',choppable=True,chopHoles=None,
          unsupportedFeatures=None,parts=[dict(type='rectangle',lpp=['CT','drawing'],choppable=True,
            netName=None,termName=None,width=100,length=100,separation=0,justification='center',space=100,
            beginOffset=0,endOffset=0,beginSegOffset=0,endSegOffset=0,gap='distribute',diagonal=None)])),
      dict(kind='rect',bBox=[[0,0],[100,100]],layerName='CT',purpose='drawing',props=[],net='VSS',mppOwner='ring')]


def test_recipe_replay_uses_native_rod_and_reuses_members():
    s=canonicalize(records())
    assert not coverage(s)
    text='\n'.join(render(s))
    assert text.count('rodCreatePath(')==1
    assert 'MPP generated geometry differs' in text
    assert 'dbCreateRect(' not in text and 'dbCreatePath(' not in text
    assert text.index('dbCreateNet(')<text.index('rodCreatePath(')


def test_exact_patch_preserves_recipe_and_generated_members(tmp_path):
    old=canonicalize(records())
    records2=records(); records2[2]['mpp']['parts'][0]['space']=300
    new=canonicalize(records2)
    assert apply_diff(old,diff(old,new))==new
    a=from_snapshot(new,tmp_path/'v2')
    try: assert a.materialize()==new
    finally: a.close()
    assert classify(old,new)['counts']['moved']==1


def test_replay_is_invariant_to_json_and_git_store_record_order(tmp_path):
    snapshot=canonicalize(records())
    source=from_snapshot(snapshot,tmp_path/'stored')
    try:
        variants=[json.loads(json.dumps(snapshot,sort_keys=True)),source.materialize(),
                  {**snapshot,'objects':dict(reversed(list(snapshot['objects'].items())))}]
        expected=render(snapshot)
        for variant in variants:
            assert variant==snapshot
            assert render(variant)==expected
    finally:
        source.close()


@pytest.mark.parametrize('value', [None, 'FALSE', 'TRUE'])
def test_mpp_sticky_property_restored_after_connectivity_without_losing_other_properties(value):
    raw = records()
    raw[2]['props'] = [['lxStickyNet', 'boolean', 'TRUE']]
    raw[3]['props'] = [['note', 'string', 'keep']]
    if value is not None:
        raw[3]['props'].append(['lxStickyNet', 'boolean', value])
    snapshot = canonicalize(raw)
    master = next(k for k, r in snapshot['objects'].items() if r.get('mpp'))
    raw.append(dict(kind='textDisplay', owner=master, associate=master, parent=None,
                    associateProperty=['lxStickyNet'], assocType='propAssocType',
                    xy=[0, 2000], height=200, justify='lowerLeft', orient='R0', font='roman',
                    isDrafted=True, isOverbar=None, isVisible=True, isNameVisible=None,
                    isValueVisible=True, layerName='text', purpose='drawing', props=[]))
    snapshot = canonicalize(raw)
    original = copy.deepcopy(snapshot)
    code = '\n'.join(render(snapshot))
    # The final pass must follow *all* net assignments, even assignments on
    # other figures; native ROD updates can affect previously visited members.
    tail = code[code.rindex('o~>net='):code.index('o=dbCreateTextDisplay')]
    assert tail.count('foreach(prop o~>prop dbDeleteObject(prop))') == 2
    assert tail.index('dbReplaceProp(o "lxStickyNet" "boolean" t)') < tail.index('dbReplaceProp(o "note"')
    if value is not None:
        expected = 't' if value == 'TRUE' else 'nil'
        assert f'dbReplaceProp(o "lxStickyNet" "boolean" {expected})' in tail
    else:
        assert tail.count('dbReplaceProp(o "lxStickyNet"') == 1
    assert 'dbReplaceProp(o "note" "string" "keep")' in tail
    assert 'dbDeleteObject(prop)' not in code[code.index('o=dbCreateTextDisplay'):]
    assert snapshot == original


def test_unchoppable_master_keeps_nil_and_replays_chopped_subparts():
    raw=records()
    raw[2]['mpp']['choppable']=None
    raw[2]['mpp']['chopHoles']=[[[2000,0],[3000,0]]]
    snapshot=canonicalize(raw)
    assert not coverage(snapshot)
    text='\n'.join(render(snapshot))
    assert '?choppable nil' in text and 'rodAddMPPChopHole(' in text
    del raw[2]['mpp']['choppable']
    assert any('invalid MPP definition' in issue for issue in coverage(canonicalize(raw)))


def test_native_chop_coordinates_are_dbu_and_cache_is_not_replayed():
    from layoutdiff.eda.virtuoso.mpp import capture_chop_holes
    first=[[3000,0],[2000,0]]; second=[[6000,2000],[6000,1000]]
    recipe={'nativeChopHoles':[[second,first],first]}
    capture_chop_holes(recipe)
    assert recipe=={'chopHoles':sorted([first,second])}
    recipe={'nativeChopHoles':[first]}
    capture_chop_holes(recipe)
    assert recipe['unsupportedFeatures']==['native chop-hole encoding']


def test_only_dangling_recipe_nets_are_cleanup_candidates():
    from layoutdiff.eda.virtuoso.mpp import cleanup_replay
    raw=records(); raw[2]['mpp']['parts'][0]['netName']='VSS'
    assert cleanup_replay(raw)==[]  # Retain even empty checkpoint nets.
    raw[2]['mpp']['parts'][0]['netName']='deleted_net'
    commands=cleanup_replay(raw)
    assert len(commands)==1 and 'deleted_net' in commands[0]
    assert 'allInstTerms' in commands[0] and 'Unexpected connected MPP recipe net' in commands[0]


def test_projection_preserves_dangling_recipe_net_and_legacy_diff(tmp_path):
    raw=records(); raw[2]['mpp']['parts'][0]['netName']='deleted_net'
    expected=canonicalize(raw)
    legacy=copy.deepcopy(raw)
    for r in legacy:
        r.pop('mpp',None); r.pop('mppOwner',None)
    legacy=canonicalize(legacy)
    source=from_snapshot(expected,tmp_path/'source')
    out=project(source,tmp_path/'supported',tmp_path/'report.jsonl')
    try:
        assert out.omissions is None
        assert out.materialize()==expected
        assert out.omission_report.read_bytes()==b''
        assert apply_diff(legacy,diff(legacy,out.materialize()))==expected
    finally:
        source.close(); out.close()


def test_projection_existing_recipe_net_remains_a_dependency(tmp_path):
    raw=records(); raw[2]['mpp']['parts'][0]['netName']='RECIPE_ONLY'
    raw.append(dict(raw[1],name='RECIPE_ONLY',props=[['unsupported','future',1]]))
    source=from_snapshot(canonicalize(raw),tmp_path/'source')
    out=project(source,tmp_path/'supported',tmp_path/'report.jsonl')
    try:
        assert out.omissions['omitted']==3  # net, master, generated member
        assert not any(r.get('mpp') or r.get('mppOwner') for _,r in out.records())
        assert 'net:VSS' in out.materialize()['objects']
    finally:
        source.close(); out.close()


def test_projection_missing_figure_net_still_omits_complete_mpp(tmp_path):
    raw=records(); raw[-1]['net']='MISSING_ACTUAL_CONNECTION'
    source=from_snapshot(canonicalize(raw),tmp_path/'source')
    out=project(source,tmp_path/'supported',tmp_path/'report.jsonl')
    try:
        assert out.omissions['omitted']==2
        assert 'missing referenced object' in out.omissions['counts']
        assert not any(r.get('mpp') or r.get('mppOwner') for _,r in out.records())
    finally:
        source.close(); out.close()


def test_native_equivalence_only_infers_uniform_rectangle_net():
    a=canonicalize(records()); raw=records();raw[2]['mpp']['parts'][0]['netName']='VSS';b=canonicalize(raw)
    assert via_default_projection(a,{},mpp_connectivity=True)[0]==via_default_projection(b,{},mpp_connectivity=True)[0]
    raw[-1]['net']='DIFFERENT'
    assert via_default_projection(a,{},mpp_connectivity=True)[0]!=via_default_projection(canonicalize(raw),{},mpp_connectivity=True)[0]


def test_subpart_slot_names_remain_in_snapshot_and_compare_by_role():
    a=records();a[2]['mpp']['parts'][0]['name']='subpart2'
    b=copy.deepcopy(a);b[2]['mpp']['parts'][0]['name']='subpart0'
    left,right=canonicalize(a),canonicalize(b)
    assert left!=right
    assert via_default_projection(left,{},mpp_connectivity=True)[0]==via_default_projection(right,{},mpp_connectivity=True)[0]
    assert a[2]['mpp']['parts'][0]['name']=='subpart2'


def test_omission_of_master_or_member_omits_complete_mpp(tmp_path):
    for i in [2,3]:
        r=records();r[i]['props']=[['unsupported','future',4]]
        source=from_snapshot(canonicalize(r),tmp_path/f'source{i}')
        out=project(source,tmp_path/f'project{i}',tmp_path/f'report{i}.jsonl')
        try:
            assert out.omissions['omitted']==2
            assert not any(r.get('mpp') or r.get('mppOwner') for _,r in out.records())
        finally: source.close();out.close()


def test_missing_master_fails_coverage():
    r=records();del r[2]
    assert any('missing or duplicate MPP master' in s for s in coverage(canonicalize(r)))


def test_recipe_connectivity_uses_modified_net_category():
    a=records();b=copy.deepcopy(a);b[2]['mpp']['parts'][0]['netName']='VSS'
    result=classify(canonicalize(a),canonicalize(b))
    assert result['counts']['netChanged']==1 and result['counts']['changed']==0
