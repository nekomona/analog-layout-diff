"""Native MPP sticky-net properties and property-linked text-display replay.

Uses only fresh cells in the dedicated test library. Requires a running plugin
for held-review handles. IC23.1 APIs verified in installed SKILL/ROD docs.
"""
import copy
from pathlib import Path
import uuid

from virtuoso_bridge import VirtuosoClient
from layoutdiff.data.core import canonicalize
from layoutdiff.data.history import atomic_json
from layoutdiff.eda.virtuoso.adapter import VirtuosoAdapter, checked
from layoutdiff.eda.virtuoso.dependencies import native_snapshot
from layoutdiff.eda.virtuoso.native_equivalence import via_default_projection
from layoutdiff.eda.virtuoso.sexpr import dumps as sk


def main():
    run = uuid.uuid4().hex[:8]
    out = Path(__file__).resolve().parents[1] / 'evidence' / ('mpp-properties-' + run)
    c = VirtuosoClient.from_env()
    adapter = VirtuosoAdapter(c, out)
    lib = adapter.writable_library
    source = 'mpp_props_' + run
    owned = [source]
    report = {'cases': []}
    try:
        with c.layout.create(lib, source) as edit:
            edit.add('''let((r p) dbCreateNet(cv "VSS")
              r=rodCreatePath(?cvId cv ?name "ring" ?layer list("ACT" "drawing")
                ?width 0.2 ?pts list(0:0 8:0) ?netName "VSS" ?choppable t
                ?subRect list(list(?layer list("CT" "drawing") ?width 0.09 ?length 0.09
                  ?space 0.11 ?netName "VSS" ?gap "distribute" ?choppable t)))
              unless(r error("MPP fixture creation failed"))
              dbReplaceProp(r~>dbId "lxStickyNet" "boolean" t)
              dbReplaceProp(r~>dbId "note" "string" "keep this association")
              foreach(name list("note" "lxStickyNet")
                p=dbGetPropByName(r~>dbId name)
                unless(dbCreateTextDisplay(p r~>dbId list("text" "drawing") t
                  list(0 2) "lowerLeft" "R0" "roman" 0.2 t nil t nil t)
                  error("MPP text display fixture failed"))))''')
        baseline = adapter.capture(lib, source, dependencies=False)
        assert sum(r['kind'] == 'textDisplay' for r in baseline['objects'].values()) == 2
        for value in (None, 'FALSE', 'TRUE'):
            rows = copy.deepcopy(list(baseline['objects'].values()))
            old_master = next(k for k, r in baseline['objects'].items() if r.get('mpp'))
            master = next(r for r in rows if r.get('mpp'))
            # Historical generated slot numbers are comparison-only aliases.
            # Force this path with zero vias to cover SKILL's nil defaults list.
            master['mpp']['parts'][0]['name'] = 'subpart17'
            new_master = next(iter(canonicalize([master])['objects']))
            for record in rows:
                for field in ('owner', 'associate', 'parent'):
                    if record.get(field) == old_master:
                        record[field] = new_master
                if record.get('mppOwner'):
                    record['props'] = [['note', 'string', 'member property']]
                    if value is not None:
                        record['props'].append(['lxStickyNet', 'boolean', value])
                    record['props'].sort()
            snapshot = canonicalize(rows)
            for held in (False, True):
                dest = source + '_' + str(len(report['cases']))
                owned.append(dest)
                token = uuid.uuid4().hex if held else None
                try:
                    actual = adapter.reconstruct(snapshot, lib, dest, review_token=token)
                    assert adapter.last_readback_normalization['via_defaults'] == {}
                    assert adapter.last_readback_normalization['equal']
                finally:
                    if token:
                        checked(c.execute_skill('ALDGUIDiscard(' + sk(token) + ')'))
                # Also verify persisted content after releasing the GUI-held cell.
                reopened = adapter.capture(lib, dest, dependencies=False)
                expected = via_default_projection(snapshot, {}, mpp_connectivity=True)[0]
                assert via_default_projection(actual, {}, mpp_connectivity=True)[0] == expected
                assert via_default_projection(reopened, {}, mpp_connectivity=True)[0] == expected
                report['cases'].append({'sticky': value, 'held': held,
                                        'records': len(native_snapshot(actual)['objects']),
                                        'saved_readback_equal': True, 'text_displays': 2})
                atomic_json(out / 'report.json', report)
                print('PASS', value, 'held' if held else 'closed', flush=True)
    finally:
        for cell in owned:
            args = sk(lib) + ' ' + sk(cell)
            checked(c.execute_skill('when(ddGetObj(' + args + ') ddDeleteObj(ddGetObj(' + args + ')))'))
            assert checked(c.execute_skill('ddGetObj(' + args + ')')).strip() == 'nil'
    report['cleanup'] = True
    atomic_json(out / 'report.json', report)
    print(out, flush=True)


if __name__ == '__main__':
    main()
