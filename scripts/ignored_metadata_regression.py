"""Native regression for the user-approved route/marker/Steiner exclusion."""
import json
from pathlib import Path
import sys
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from virtuoso_bridge import VirtuosoClient
from layoutdiff.virtuoso.adapter import VirtuosoAdapter, checked, coverage
from layoutdiff.virtuoso.sexpr import dumps as sk, loads
from layoutdiff.data.core import diff, digest, apply_diff
from layoutdiff.virtuoso.geometry import export, compare_gds
from layoutdiff.data.history import atomic_json
from layoutdiff.data.streampatch import create, apply

project = Path(__file__).resolve().parents[1]
cell = 'ignored_metadata_' + uuid.uuid4().hex[:8]
lib = 'LAYOUT_DIFF_TEST'
out = project/'evidence'/cell; out.mkdir(parents=True)
c = VirtuosoClient.from_env(); adapter = VirtuosoAdapter(c, out/'capture')
with c.layout.create(lib, cell) as e:
    e.add('let((n a p r m s fg lg) '
        'n=dbCreateNet(cv "A") dbCreateNet(cv "B") '
        'a=dbCreateRect(cv list("MET1" "drawing") list(0:2 1:3)) a~>net=n '
        'p=dbCreatePathSeg(cv list("MET1" "drawing") 0:0 5:0 0.2 "truncate" "truncate") p~>net=n '
        'r=dbCreateRoute(cv n) r~>objects=list(p) '
        'm=dbCreateMarker(cv "initial" "LayoutDiffRegression" list(0:0 5:0 5:5 0:5)) '
        's=dbCreateSteiner(cv list(5:0 5:0) "MET1") dbAddFigToNet(s n) r~>endConn=s '
        'fg=dbCreateFigGroup(cv "ordered" t 0:0 "R0") '
        'foreach(o list(m a r s) unless(dbAddFigToFigGroup(fg o) error("figGroup attach failed: %L" o~>objType))) '
        'lg=dbCreateGroup(cv "ordered logical" list("collection" "ordered" "uniqueName" "deleteNever")) '
        'foreach(o list(m a r s p) unless(dbAddObjectToGroup(lg o) error("logical group attach failed"))))')
report = {'source':[lib,cell,'layout'], 'cases':[]}
initial = prior = None
for step in range(4):
    if step == 1:
        with c.layout.modify(lib, cell) as e:
            e.add('let((m s fg lg) '
                'dbReplaceProp(car(cv~>routes) "ignored note" "string" "changed") '
                'car(cv~>markers)~>msg="changed message" car(cv~>steiners)~>bBox=list(6:0 6:0) '
                'm=dbCreateMarker(cv "additional" "LayoutDiffRegression" list(0:0 1:0 1:1 0:1)) '
                's=dbCreateTapSteiner(cv list(7:0 7:0) "MET1") '
                'fg=car(cv~>figGroups) lg=car(cv~>groups) '
                'foreach(o list(m s) dbAddFigToFigGroup(fg o) dbAddObjectToGroup(lg o)))')
    elif step == 2:
        with c.layout.modify(lib, cell) as e:
            e.add('foreach(attr list("routes" "markers" "steiners") foreach(o dbGet(cv attr) dbDeleteObject(o)))')
    elif step == 3:
        with c.layout.modify(lib, cell) as e:
            e.add('let((p r) p=car(setof(o cv~>shapes o~>objType=="pathSeg")) '
                'p~>width=0.4 r=dbCreateRoute(cv) r~>objects=list(p) r~>net=dbFindNetByName(cv "B"))')
    native_counts = loads(checked(c.execute_skill(
        f'let((cv) cv=dbOpenCellViewByType({sk(lib)} {sk(cell)} "layout" "maskLayout" "r") '
        'unwindProtect(list(length(cv~>routes) length(cv~>markers) length(cv~>steiners)) dbClose(cv)))')))
    snap = adapter.capture(lib,cell,dependencies=False)
    assert not coverage(snap), coverage(snap)
    assert all(r['kind'] not in {'route','marker','steiner','steinerPin','unsupported'} for r in snap['objects'].values())
    groups = [r for r in snap['objects'].values() if r['kind']=='group']
    assert len(groups)==1 and len(groups[0]['members'])==2
    fg = snap['objects']['figGroup:ordered']
    assert fg['memberCount']==1
    assert sorted(r['groupOrder'] for r in snap['objects'].values() if r.get('group')=='ordered')==[0]
    if initial is None: initial = snap
    if step in (1,2):
        assert snap==initial, diff(initial,snap)
    if step==3:
        assert snap!=initial
        p = next(r for r in snap['objects'].values() if r['kind']=='pathSeg')
        assert p['width']==400 and p['net']=='B'
    store=adapter.capture_store(lib,cell,dependencies=False)
    assert store.digest==digest(snap)
    if prior is not None:
        patch=diff(previous,snap)
        assert apply_diff(previous,patch)==snap and apply_diff(snap,patch,reverse=True)==previous
        create(prior,store,out/f'patch{step}',backend='python')
        replay=apply(prior,out/f'patch{step}',out/f'applied{step}.layout',backend='python')
        assert replay.digest==store.digest; replay.close(); prior.close()
    case={'step':step,'native_excluded_counts':native_counts,'digest':digest(snap),
          'same_as_initial':snap==initial,'supported_records':len(snap['objects'])}
    if step in (0,3):
        rebuilt=cell+'_rebuilt_'+str(step)
        actual=adapter.reconstruct(snap,lib,rebuilt)
        assert digest(actual)==digest(snap)
        case['native_reconstruction_equal']=True
        mapping=out/'stream.map'; mapping.write_bytes(b'MET1 drawing 81 0\n')
        a,b=out/f'source{step}.gds',out/f'rebuilt{step}.gds'
        export(c,lib,cell,a,mapping); export(c,lib,rebuilt,b,mapping)
        case['gds']=compare_gds(a,b,left_top=cell,right_top=rebuilt)
        assert case['gds']['equal'] and case['gds']['has_geometry']
    atomic_json(out/f'snapshot{step}.json',snap)
    report['cases'].append(case); atomic_json(out/'report.json',report)
    print(json.dumps(case),flush=True)
    previous=snap; prior=store
prior.close(); print(out,flush=True)
