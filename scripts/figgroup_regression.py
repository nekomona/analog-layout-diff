"""Ordered/nested groups, membership edits, native replay and complete blockers."""
import json
from pathlib import Path
import sys
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from virtuoso_bridge import VirtuosoClient
from layoutdiff.virtuoso.adapter import VirtuosoAdapter, checked, coverage
from layoutdiff.virtuoso.sexpr import dumps as sk
from layoutdiff.data.core import empty_snapshot, digest, diff, apply_diff
from layoutdiff.data.storage import from_snapshot
from layoutdiff.data.streampatch import create, apply
from layoutdiff.virtuoso.geometry import export, compare_gds
from layoutdiff.data.history import atomic_json
from layoutdiff.virtuoso.support import UnsupportedContentError

project = Path(__file__).resolve().parents[1]
run = uuid.uuid4().hex[:8]
out = project / 'evidence' / ('figgroup_' + run)
out.mkdir(parents=True)
c = VirtuosoClient.from_env()
adapter = VirtuosoAdapter(c, out / 'capture')
lib, cell = 'LAYOUT_DIFF_TEST', 'figgroup_' + run
leaf = cell + '_leaf'
with c.layout.create(lib, leaf) as edit:
    edit.add('dbCreateRect(cv list("MET1" "drawing") list(0:0 1:1))')
with c.layout.create(lib, cell) as edit:
    edit.add('let((outer inner plain empty a b d i v n p mo) '
        'outer=dbCreateFigGroup(cv "outer" t 2:3 "R90") '
        'inner=dbCreateFigGroup(cv "inner" t 1:1 "MX") '
        'plain=dbCreateFigGroup(cv "plain" nil 0:0 "R0") '
        'empty=dbCreateFigGroup(cv "empty" t 0:0 "R0") '
        'a=dbCreateRect(cv list("MET1" "drawing") list(0:0 2:2)) '
        'b=dbCreateRect(cv list("MET1" "drawing") list(0:0 2:2)) '
        'd=dbCreateRect(cv list("MET2" "drawing") list(6:0 8:2)) '
        f'i=dbCreateParamInstByMasterName(cv {sk(lib)} {sk(leaf)} "layout" "I0" list(3 4) "R0") '
        f'mo=dbCreateParamSimpleMosaicByMasterName(cv {sk(lib)} {sk(leaf)} "layout" "ARRAY0" list(14 5) "R0" 2 3 2.0 3.0 nil) '
        'v=dbCreateVia(cv techFindViaDefByName(techGetTechFile(cv) "MET2_MET1") list(5 5) "R0") '
        'n=dbCreateNet(cv "P") dbCreateTerm(n "P" "inputOutput") '
        'p=dbCreatePin(n d "P") dbReplaceProp(p "pin_note" "string" "grouped pin") '
        'dbReplaceProp(outer "group_note" "string" "initial") '
        'foreach(obj list(b i inner v a plain mo) unless(dbAddFigToFigGroup(outer obj) error("outer membership"))) '
        'unless(dbAddFigToFigGroup(inner d) error("inner membership")) '
        'unless(dbAddFigToFigGroup(plain empty) error("nested empty membership")))')

report = {'run': run, 'source': [lib, cell, 'layout'], 'cases': []}
previous = empty_snapshot()
prior = from_snapshot(previous, out / 'empty.layout')
for step in range(3):
    if step == 1:
        with c.layout.modify(lib, cell) as edit:
            # Pure order edit, independent of geometry/property changes.
            edit.add('let((g members) g=dbGetFigGroupByName(cv "outer") members=g~>figs '
                'foreach(o members dbRemoveFigFromFigGroup(g o)) '
                'foreach(o reverse(members) dbAddFigToFigGroup(g o)))')
    elif step == 2:
        with c.layout.modify(lib, cell) as edit:
            edit.add('let((g inner o) g=dbGetFigGroupByName(cv "outer") inner=dbGetFigGroupByName(cv "inner") '
                'o=car(setof(s g~>figs s~>objType=="rect")) dbRemoveFigFromFigGroup(g o) dbDeleteObject(o) '
                'o=car(inner~>figs) dbRemoveFigFromFigGroup(inner o) dbAddFigToFigGroup(g o) '
                'o=dbCreateRect(cv list("MET1" "drawing") list(10:0 12:2)) dbAddFigToFigGroup(inner o) '
                'dbReplaceProp(g "group_note" "string" "membership changed") '
                'dbGetFigGroupByName(cv "plain")~>ordered=t)')
    snapshot = adapter.capture(lib, cell)
    assert not coverage(snapshot), coverage(snapshot)
    if step == 1:
        assert digest(snapshot) != digest(previous), 'Order-only edits must be visible'
    delta = diff(previous, snapshot)
    assert apply_diff(previous, delta) == snapshot
    assert apply_diff(snapshot, delta, reverse=True) == previous
    store = adapter.capture_store(lib, cell)
    assert store.digest == digest(snapshot)
    create(prior, store, out / f'patch{step}', backend='python')
    replayed = apply(prior, out / f'patch{step}', out / f'replayed{step}.layout', backend='python')
    reversed_state = apply(store, out / f'patch{step}', out / f'reversed{step}.layout', reverse=True, backend='python')
    assert replayed.digest == store.digest and reversed_state.digest == prior.digest
    rebuilt = cell + '_rebuilt_' + str(step)
    actual = adapter.reconstruct(replayed.materialize(), lib, rebuilt)
    assert digest(actual) == digest(snapshot)
    case = {'step': step, 'digest': digest(snapshot), 'operations': len(delta['operations']),
        'semantic_equal': True, 'v2_capture_equal': True, 'forward_reverse_replay_equal': True,
        'reconstructed': rebuilt, 'groups': [r for r in snapshot['objects'].values() if r['kind'] == 'figGroup']}
    if step in (0, 2):
        mapping = out / 'stream.map'
        mapping.write_bytes(b'MET1 drawing 81 0\nMET2 drawing 82 0\nVIA1 drawing 51 0\n')
        a, b = out / f'source{step}.gds', out / f'reconstructed{step}.gds'
        export(c, lib, cell, a, mapping); export(c, lib, rebuilt, b, mapping)
        case['gds'] = compare_gds(a, b, left_top=cell, right_top=rebuilt)
        assert case['gds']['equal'] and case['gds']['has_geometry'], case
    atomic_json(out / f'snapshot{step}.json', snapshot)
    report['cases'].append(case)
    atomic_json(out / 'report.json', report)
    print(json.dumps(case), flush=True)
    previous = snapshot
    prior.close(); reversed_state.close(); replayed.close()
    prior = store
prior.close()

bad = cell + '_unsupported'
with c.layout.create(lib, bad) as edit:
    edit.add('dbCreateRect(cv list("MET1" "drawing") list(0:0 1:1))')
    edit.add('dbCreateGuide(cv 0:0 1:1 "MET1" "MET1")')
    edit.add('dbCreateGuide(cv 2:0 3:1 "MET1" "MET1")')
    edit.add('dbCreateGuide(cv 4:0 5:1 "MET1" "MET1")')
try:
    adapter.capture_store(lib, bad, temporary=True)
    raise AssertionError('Unsupported content was allowed')
except UnsupportedContentError as exc:
    assert exc.counts == {'unsupported collection: guides': 3}, exc.counts
    details = [json.loads(line) for line in exc.report.read_text().splitlines()]
    assert len(details) == 3
    report['unsupported'] = {'source': [lib, bad, 'layout'], 'counts': exc.counts,
        'report': str(exc.report), 'details': len(details)}
atomic_json(out / 'report.json', report)
print(out, flush=True)
