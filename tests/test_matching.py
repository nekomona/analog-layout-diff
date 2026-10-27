import copy
from layoutdiff.core import canonicalize, diff, apply_diff
from layoutdiff.review import classify
from layoutdiff.categories import CategoryDiff
from layoutdiff.changeindex import ChangeIndex
from layoutdiff.storage import write_records


def rect(x=0, y=0, w=10, h=20, layer='MET1', **attrs):
    return dict(kind='rect', bBox=[[x,y],[x+w,y+h]], layerName=layer, purpose='drawing', **attrs)


def check(tmp_path, a, b):
    a,b=canonicalize(a),canonicalize(b)
    patch=diff(a,b)
    assert apply_diff(a,patch)==b
    assert apply_diff(b,patch,reverse=True)==a
    summary=CategoryDiff(patch['operations'])
    old=write_records(a['objects'].values(),tmp_path/'before')
    new=write_records(b['objects'].values(),tmp_path/'after')
    index=ChangeIndex(old,new)
    try:
        assert index.rows==summary.rows
        assert list(index.full())==list(summary.full())
    finally:
        index.close();old.close();new.close()
    return classify(a,b),summary.totals


def test_moved_and_stretched_across_views(tmp_path):
    a=[rect(),rect(100,w=7),dict(kind='pathSeg',layerName='MET2',purpose='drawing',beginPt=[0,0],endPt=[0,100],width=4)]
    b=[rect(20,30),rect(100,w=11),{**a[2],'endPt':[0,130]}]
    r,c=check(tmp_path,a,b)
    assert c['modified']==3 and c['added']==c['deleted']==0
    assert r['counts']['changed']==3 and not r['removed']


def test_ambiguous_symmetric_candidates_stay_added_deleted(tmp_path):
    r,c=check(tmp_path,[rect(-20),rect(20)],[rect()])
    assert c['modified']==0 and c['added']==1 and c['deleted']==2


def test_distant_unrelated_shape_and_cross_layer(tmp_path):
    r,c=check(tmp_path,[rect(),rect(1,layer='MET2')],[rect(100000),rect(1,layer='MET3')])
    assert c['modified']==0


def test_common_translation_for_repeated_shapes(tmp_path):
    old=[rect(x*100,w=7) for x in range(100)] + [rect(0,500,w=11),rect(100,500,w=13)]
    new=[rect(x*100+20,30,w=7) for x in range(100)] + [rect(20,530,w=11),rect(120,530,w=13)]
    r,c=check(tmp_path,old,new)
    assert c['modified']==102 and c['added']==c['deleted']==0


def test_multiplicity_and_attribute_precedence(tmp_path):
    a=[rect(),rect(),rect(100)]
    b=[rect(),rect(net='VSS'),rect(120)]
    r,c=check(tmp_path,a,b)
    assert c['modified_net']==1 and c['modified']==1 and not r['removed']


def test_same_bbox_different_polygon_is_not_guessed(tmp_path):
    a=[dict(kind='polygon',layerName='M1',points=[[0,0],[10,1],[20,20],[0,19]])]
    b=[dict(kind='polygon',layerName='M1',points=[[1,0],[20,1],[19,20],[0,18]])]
    r,c=check(tmp_path,a,b)
    assert c['modified']==0
