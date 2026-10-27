import copy
from layoutdiff.core import canonicalize, diff, apply_diff, encoded
from layoutdiff.virtuoso import render
from layoutdiff.support import coverage
from layoutdiff.storage import from_snapshot
from layoutdiff.native_equivalence import via_default_projection
from layoutdiff.review import classify
from layoutdiff.omissions import project


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
    assert classify(old,new)['counts']['changed']==1


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
