"""Native logical-group capture/replay, duplicate names, nested groups and links."""
import json
from pathlib import Path
import sys
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from virtuoso_bridge import VirtuosoClient
from layoutdiff.eda.virtuoso.adapter import VirtuosoAdapter, checked, coverage
from layoutdiff.eda.virtuoso.sexpr import dumps as sk
from layoutdiff.data.core import empty_snapshot, digest, diff, apply_diff
from layoutdiff.data.storage import from_snapshot
from layoutdiff.data.streampatch import create, apply
from layoutdiff.eda.virtuoso.geometry import export, compare_gds
from layoutdiff.data.history import atomic_json

project=Path(__file__).resolve().parents[1]
run=uuid.uuid4().hex[:8]
out=project/'evidence'/('logical_groups_'+run); out.mkdir(parents=True)
c=VirtuosoClient.from_env(); adapter=VirtuosoAdapter(c,out/'capture')
lib='LAYOUT_DIFF_TEST'; cell='logical_groups_'+run; leaf=cell+'_leaf'
with c.layout.create(lib,leaf) as e:
    e.add('let((n o tm) n=dbCreateNet(cv "P") tm=dbCreateTerm(n "P" "inputOutput") '
          'o=dbCreateRect(cv list("MET1" "drawing") list(0:0 1:1)) dbCreatePin(n o "P" tm))')
with c.layout.create(lib,cell) as e:
    e.add('let((a b n tm pin i j it fg boundary ordered one two parent gm) '
        'a=dbCreateRect(cv list("MET1" "drawing") list(0:0 2:2)) '
        'b=dbCreateRect(cv list("MET1" "drawing") list(3:0 5:2)) '
        'n=dbCreateNet(cv "P") tm=dbCreateTerm(n "P" "inputOutput") pin=dbCreatePin(n b "P" tm) '
        f'i=dbCreateParamInstByMasterName(cv {sk(lib)} {sk(leaf)} "layout" "I0" list(0 4) "R0") '
        f'j=dbCreateParamInstByMasterName(cv {sk(lib)} {sk(leaf)} "layout" "I1" list(3 4) "R0") '
        'it=dbCreateInstTerm(n i dbFindTermByName(i~>master "P")) '
        'fg=dbCreateFigGroup(cv "fg" t 0:0 "R0") dbAddFigToFigGroup(fg a) '
        'boundary=dbCreatePRBoundary(cv list(0:0 10:0 10:10 0:10)) '
        'one=dbCreateGroup(cv "lxMTM" list("set" "unordered" "nonUniqueName" "deleteLast")) '
        'two=dbCreateGroup(cv "lxMTM" list("set" "unordered" "nonUniqueName" "deleteLast")) '
        'dbAddObjectToGroup(one i) dbAddObjectToGroup(two j) '
        'ordered=dbCreateGroup(cv "ordered" list("collection" "ordered" "uniqueName" "deleteNever")) '
        'foreach(o list(a n tm pin it a) gm=dbAddObjectToGroup(ordered o) '
        'unless(gm error("group member failed for %L" o~>objType)) dbReplaceProp(gm "role" "string" o~>objType)) '
        'parent=dbCreateGroup(cv "parent" list("set" "unordered" "uniqueName" "deleteNever")) '
        'foreach(o list(one two ordered fg) unless(dbAddObjectToGroup(parent o) error("nested group failed"))) '
        'one=dbCreateGroup(cv "geProtectedFiguresGroup" list("set" "unordered" "uniqueName" "deleteLast")) '
        'dbAddObjectToGroup(one boundary) '
        'unless(dbCreateGroup(cv "lxUngen" list("set" "unordered" "nonUniqueName" "deleteNever") "lxUngen") error("lxUngen creation")) '
        'unless(dbCreateGroup(cv "lxImplicitBus" list("set" "unordered" "nonUniqueName" "deleteNever") "lxImplicitBus") error("lxImplicitBus creation")))')
report={'source':[lib,cell,'layout'],'cases':[]}
previous=empty_snapshot(); prior=from_snapshot(previous,out/'empty.layout')
for step in range(3):
    if step==1:
        with c.layout.modify(lib,cell) as e:
            e.add('let((g saved members gm) g=dbGetGroupByName(cv "ordered") members=g~>members '
                'saved=foreach(mapcar m members list(m~>object dbGet(m "role"))) '
                'foreach(m members dbDeleteGroupMemberFromGroup(m)) '
                'foreach(pair reverse(saved) gm=dbAddObjectToGroup(g car(pair)) dbReplaceProp(gm "role" "string" cadr(pair))) '
                'dbReplaceProp(g "note" "string" "reordered"))')
    elif step==2:
        with c.layout.modify(lib,cell) as e:
            e.add('let((g o) g=dbGetGroupByName(cv "parent") '
                'o=dbCreateRect(cv list("MET1" "drawing") list(6:0 8:2)) '
                'dbAddObjectToGroup(g o) dbReplaceProp(g "annotation" "int" 7) '
                'dbDeleteObject(dbGetGroupByName(cv "lxImplicitBus")))')
    snap=adapter.capture(lib,cell)
    assert not coverage(snap), coverage(snap)
    patch=diff(previous,snap)
    assert apply_diff(previous,patch)==snap and apply_diff(snap,patch,reverse=True)==previous
    store=adapter.capture_store(lib,cell); assert store.digest==digest(snap)
    create(prior,store,out/f'patch{step}',backend='python')
    replayed=apply(prior,out/f'patch{step}',out/f'replayed{step}.layout',backend='python')
    undo=apply(store,out/f'patch{step}',out/f'undo{step}.layout',reverse=True,backend='python')
    assert replayed.digest==store.digest and undo.digest==prior.digest
    rebuilt=cell+'_rebuilt_'+str(step)
    actual=adapter.reconstruct(replayed.materialize(),lib,rebuilt)
    assert digest(actual)==digest(snap)
    groups=[r for r in snap['objects'].values() if r['kind']=='group']
    case={'step':step,'digest':digest(snap),'groups':len(groups),'group_members':sum(len(r['members']) for r in groups),
        'semantic_equal':True,'v2_capture_equal':True,'forward_reverse_replay_equal':True,'reconstructed':rebuilt}
    if step in (0,2):
        mapping=out/'stream.map'; mapping.write_bytes(b'MET1 drawing 81 0\n')
        a,b=out/f'source{step}.gds',out/f'reconstructed{step}.gds'
        export(c,lib,cell,a,mapping); export(c,lib,rebuilt,b,mapping)
        case['gds']=compare_gds(a,b,left_top=cell,right_top=rebuilt)
        assert case['gds']['equal'] and case['gds']['has_geometry']
    atomic_json(out/f'snapshot{step}.json',snap)
    report['cases'].append(case); atomic_json(out/'report.json',report)
    print(json.dumps(case),flush=True)
    previous=snap; prior.close(); replayed.close(); undo.close(); prior=store
prior.close(); print(out,flush=True)
