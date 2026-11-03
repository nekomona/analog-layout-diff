"""All pathSeg end-style pairs in eight directions; native readback and GDS XOR."""
import itertools
import json
from pathlib import Path
import sys
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from virtuoso_bridge import VirtuosoClient
from layoutdiff.eda.virtuoso.adapter import VirtuosoAdapter, checked, coverage, replay_source
from layoutdiff.eda.virtuoso.sexpr import dumps as sk
from layoutdiff.data.core import canonicalize, empty_snapshot, digest, diff, apply_diff, encoded
from layoutdiff.data.storage import from_snapshot
from layoutdiff.data.streampatch import create, apply
from layoutdiff.eda.virtuoso.geometry import export, compare_gds
from layoutdiff.data.history import atomic_json

project = Path(__file__).resolve().parents[1]
run = uuid.uuid4().hex[:8]
out = project / 'evidence' / ('pathseg_' + run)
out.mkdir(parents=True)
c = VirtuosoClient.from_env()
adapter = VirtuosoAdapter(c, out / 'capture')
lib, cell = 'LAYOUT_DIFF_TEST', 'pathseg_' + run
styles = ['truncate', 'extend', 'variable', 'chamfer', 'custom']
directions = [(4,0), (0,4), (-4,0), (0,-4), (4,4), (-4,4), (-4,-4), (4,-4)]
custom = [.15, .25, .2, .3, .35, .4]

def command(index, begin, end, direction):
    x, y = (index % 20) * 12 + 5, (index // 20) * 12 + 5
    dx, dy = direction
    ext = [.2 if begin in ('custom', 'variable') else 0.,
           .4 if end in ('custom', 'variable') else 0.] + ([custom] if 'custom' in (begin, end) else [])
    return (f'let((o) o=dbCreatePathSeg(cv list("MET1" "drawing") {sk([x,y])} {sk([x+dx,y+dy])} '
        f'0.6 {sk(begin)} {sk(end)} {sk(ext)}) unless(o error("pathSeg creation failed")) '
        f'dbReplaceProp(o "case_id" "int" {index}))')

specs = [(a, b, d) for a, b in itertools.product(styles, repeat=2) for d in directions]
commands = [command(i, a, b, d) for i, (a, b, d) in enumerate(specs)]
# An exact duplicate pair must survive capture, streamed replay and readback.
commands += [command(199, *specs[199]),
    'let((n o) n=dbCreateNet(cv "CUSTOM_NET") o=car(setof(s cv~>shapes dbGet(s "case_id")==192)) dbAddFigToNet(o n))']
function = 'ALDPathSegFixture_' + run
source, helpers = replay_source(['let((aldFixtureUnused)', *commands, 't)'], function, chunk_size=32)
path = out / 'fixture.il'; path.write_text(source)
checked(c.load_il(path))
try:
    with c.layout.create(lib, cell) as edit:
        edit.add(function + '(cv)')
finally:
    checked(c.execute_skill('progn(' + ' '.join(f"putd('{fn} nil)" for fn in helpers) + ' t)'))

report = {'run': run, 'source': [lib, cell, 'layout'], 'style_pairs': 25,
          'directions': 8, 'initial_segments': 201, 'cases': []}
previous = empty_snapshot()
prior = from_snapshot(previous, out / 'empty.layout')
for step in range(3):
    if step == 1:
        with c.layout.modify(lib, cell) as edit:
            edit.add('let((o) o=car(setof(s cv~>shapes dbGet(s "case_id")==192)) unless(dbSetPathSegStyle(o 0.6 "custom" "custom" list(0.3 0.5 list(0.2 0.3 0.25 0.4 0.45 0.35))) error("style update failed")))')
            edit.add('let((o) o=car(setof(s cv~>shapes dbGet(s "case_id")==148)) unless(dbSetPathSegStyle(o 0.6 "chamfer" "custom" list(0.0 0.4 list(0.0 0.0 0.0 0.3 0.35 0.3))) error("mixed style update failed")))')
            edit.add('let((o) o=car(setof(s cv~>shapes dbGet(s "case_id")==0)) dbReplaceProp(o "note" "string" "attribute edit"))')
    elif step == 2:
        with c.layout.modify(lib, cell) as edit:
            edit.add('dbDeleteObject(car(setof(s cv~>shapes dbGet(s "case_id")==199)))')
            edit.add(command(200, 'custom', 'chamfer', (-4,4)))
            edit.add(command(201, 'chamfer', 'custom', (0,-4)))
    snap = adapter.capture(lib, cell)
    assert not coverage(snap), coverage(snap)
    segments = [r for r in snap['objects'].values() if r['kind'] == 'pathSeg']
    assert all(('customExtensions' in r) == ('custom' in (r['beginStyle'], r['endStyle'])) for r in segments)
    assert all(len(r['customExtensions']) == 6 for r in segments if 'customExtensions' in r)
    delta = diff(previous, snap)
    assert encoded(apply_diff(previous, delta)) == encoded(snap)
    assert encoded(apply_diff(snap, delta, reverse=True)) == encoded(previous)
    store = adapter.capture_store(lib, cell)
    assert store.digest == digest(snap)
    create(prior, store, out / f'patch{step}', backend='python')
    replayed = apply(prior, out / f'patch{step}', out / f'replayed{step}.layout', backend='python')
    reversed_state = apply(store, out / f'patch{step}', out / f'reversed{step}.layout', reverse=True, backend='python')
    assert replayed.digest == store.digest and reversed_state.digest == prior.digest
    rebuilt_cell = f'pathseg_rebuilt_{run}_{step}'
    actual = adapter.reconstruct(replayed.materialize(), lib, rebuilt_cell)
    assert digest(actual) == digest(snap)
    case = {'step': step, 'segments': len(segments), 'custom_segments': sum('customExtensions' in r for r in segments),
            'reconstructed': rebuilt_cell, 'semantic_equal': True, 'v2_capture_equal': True,
            'forward_reverse_replay_equal': True, 'digest': digest(snap), 'operations': len(delta['operations'])}
    if step in (0, 2):
        mapping = out / 'stream.map'; mapping.write_bytes(b'MET1 drawing 81 0\n')
        a, b = out / f'source{step}.gds', out / f'reconstructed{step}.gds'
        export(c, lib, cell, a, mapping); export(c, lib, rebuilt_cell, b, mapping)
        case['gds'] = compare_gds(a, b, left_top=cell, right_top=rebuilt_cell)
        assert case['gds']['equal'] and case['gds']['has_geometry'], case
    atomic_json(out / f'snapshot{step}.json', snap)
    report['cases'].append(case)
    atomic_json(out / 'report.json', report)
    print(json.dumps(case), flush=True)
    previous = snap
    prior.close(); reversed_state.close(); replayed.close()
    prior = store
prior.close()
print(out, flush=True)
