"""Virtuoso adapter: read-only capture, fresh-cell reconstruction only."""
from __future__ import annotations

import json
import uuid
from itertools import chain
from pathlib import Path

from .core import canonicalize, validate
from .sexpr import loads, dumps as sk
from .paths import scratch
from .support import SUPPORTED, coverage, checked_records
from .dependencies import (HierarchyReader, native_snapshot, dependency_records,
                           compare_dependencies, emit_warnings)

BOOKKEEPING = {"instance#", "pin#", "lastSavedExtractCounter"}


def checked(result):
    if str(getattr(result.status, "value", result.status)) != "success":
        raise RuntimeError(str(result.errors))
    return result.output


def untag(value):
    if isinstance(value, list):
        if len(value) == 2 and value[0] == "@float":
            return float(value[1])
        if len(value) == 2 and value[0] == "@list":
            return [untag(v) for v in value[1]]
        return [untag(v) for v in value]
    return value


def sorted_props(props):
    result = []
    for name, typ, value in props or []:
        result.append([name, typ, sorted_props(value) if typ == "hierProp" else value])
    return sorted(result, key=lambda p: p[0])


def normalized_records(records):
    for r in records:
        for key in list(r):
            r[key] = untag(r[key])
        r["props"] = sorted_props(r.get("props"))
        if r.get('mpp'):
            from .core import encoded
            r['mpp'] = dict(r['mpp'])
            r['mpp']['parts'] = sorted((dict(p) for p in r['mpp']['parts'] or []), key=encoded)
        if r["kind"] == "cell":
            r["props"] = [p for p in r["props"] if p[0] not in BOOKKEEPING]
        if r.get("pin"):
            r["pin"] = dict(r["pin"])
            r["pin"]["props"] = sorted_props(r["pin"].get("props"))
            if r["pin"].get("accessDir"):
                r["pin"]["accessDir"].sort()
        if r["kind"] in {"inst", "mosaic"}:
            r["params"] = sorted_props(r["params"])
        if r["kind"] == "inst":
            r["connections"] = sorted([[n, net, sorted_props(p), *ids] for n, net, p, *ids in r["connections"] or []])
        if r["kind"] == "group" and "_members" in r:
            r["_members"] = [[ref, kind, sorted_props(props)] for ref, kind, props in r["_members"] or []]
        if r["kind"] == "stdVia":
            r["params"] = sorted(r["params"] or [], key=lambda p: p[0])
        yield r


def capture_records(records):
    records = iter(normalized_records(records))
    first = next(records, None)
    if first is None:
        return
    records = chain([first], records)
    if '_captureId' in first:
        from .logical_groups import resolve_records
        yield from resolve_records(records)
    else:
        yield from records


def normalize(records):
    return canonicalize(list(capture_records(records)))


class VirtuosoAdapter:
    def __init__(self, client, artifacts, *, writable_library="LAYOUT_DIFF_TEST"):
        self.client = client
        self.artifacts = Path(artifacts)
        self.artifacts.mkdir(parents=True, exist_ok=True)
        self.writable_library = writable_library
        self.loaded = False
        self.hierarchy = HierarchyReader(client, self.artifacts, checked)
        self.last_dependency_warnings = []
        self.last_readback_normalization = None
        self.last_group_context = None

    def capture(self, lib, cell, view="layout", *, dependencies=True):
        if not self.loaded:
            checked(self.client.load_il(Path(__file__).with_name("reader.il")))
            self.loaded = True
        token = uuid.uuid4().hex
        remote = scratch(self.client, "ald_" + token + ".sexpr")
        local = self.artifacts / (token + ".sexpr")
        checked(self.client.execute_skill(f"ALDRead({sk(lib)} {sk(cell)} {sk(view)} {sk(remote)})", timeout=120))
        self.client.download_file(remote, str(local))
        records = [dict(loads(line)) for line in local.read_text(encoding="utf-8").splitlines() if line.strip()]
        snapshot = normalize(records)
        if dependencies:
            snapshot = canonicalize(list(snapshot["objects"].values()) +
                                    self.hierarchy.read(root=(lib, cell, view)))
        return snapshot

    def capture_store(self, lib, cell, view="layout", *, dependencies=True, temporary=False,
                      allow_unsupported=False):
        """Stream native transport through bounded sorting into a v2 snapshot."""
        from .storage import write_records
        import tempfile
        if not self.loaded:
            checked(self.client.load_il(Path(__file__).with_name("reader.il")))
            self.loaded = True
        token = uuid.uuid4().hex
        remote = scratch(self.client, "ald_" + token + ".sexpr")
        owner = tempfile.TemporaryDirectory(prefix="ald_capture_") if temporary else None
        folder = Path(owner.name) if owner else self.artifacts
        local = folder / (token + ".sexpr")
        checked(self.client.execute_skill(f"ALDRead({sk(lib)} {sk(cell)} {sk(view)} {sk(remote)})", timeout=120))
        checked(self.client.download_file(remote, str(local)))
        def records():
            with local.open(encoding="utf-8") as stream:
                captured = capture_records(dict(loads(line)) for line in stream if line.strip())
                yield from (captured if allow_unsupported else checked_records(
                    captured, self.artifacts / (token + ".unsupported.jsonl")))
            if dependencies:
                yield from self.hierarchy.read(root=(lib, cell, view))
        try:
            store = write_records(records(), folder / (token + ".layout"))
            if allow_unsupported:
                from .omissions import project
                import shutil
                full = store
                try:
                    store = project(full, folder / (token + ".supported.layout"),
                                    folder / (token + ".omissions.jsonl"))
                finally:
                    full.close()
                    shutil.rmtree(full.path)
        except BaseException as exc:
            from .support import UnsupportedContentError
            if owner and isinstance(exc, UnsupportedContentError) and exc.report.is_relative_to(folder):
                import shutil
                retained = self.artifacts / (token + '.unsupported.jsonl')
                shutil.copyfile(exc.report, retained)
                owner.cleanup()
                raise UnsupportedContentError(exc.counts, retained) from exc
            if owner:
                owner.cleanup()
            raise
        store._capture_owner = owner
        return store

    def check_dependencies(self, snapshot, *, emit=True):
        validate(snapshot)
        records = list(dependency_records(snapshot).values())
        if not records:
            return []  # Legacy snapshots contain no dependency claims.
        identities = [[r[k] for k in ("libName", "cellName", "viewName")] for r in records]
        try:
            current = canonicalize(self.hierarchy.read(identities=identities))
            issues = compare_dependencies(snapshot, current)
        except Exception as exc:
            issues = [{"key": "hierarchy", "reason": "dependency check unavailable: " + str(exc)}]
        if emit:
            emit_warnings(issues)
        return issues

    def prepare_group_context(self, snapshot, source=None):
        """Import persisted OA group definitions by reading their source view.

        These definitions are session state: dbCreateGroup requires them even
        when an empty group is being restored. Reading the source registers
        its persisted definitions; loading Layout XL alone is insufficient.
        No source geometry, properties or edit mode are changed.
        """
        required = sorted({r['defName'] for r in snapshot['objects'].values()
                           if r['kind'] == 'group' and r['defName'] != 'unrestricted'})
        context = dict(required=required, source=list(source) if source else None,
                       loaded=False, source_definitions=[])
        if not required or source is None:
            return context
        if len(source) != 3 or not all(isinstance(part, str) and part for part in source):
            raise ValueError('Group-definition source must be a library/cell/view identity')
        args = ' '.join(sk(part) for part in source)
        result = loads(checked(self.client.execute_skill(
            f'let((cv names) cv=when(ddGetObj({args}) '
            f'dbOpenCellViewByType({args} "maskLayout" "r")) '
            'if(cv then unwindProtect(progn(names=foreach(mapcar g cv~>groups g~>defName) '
            'list(t names)) dbClose(cv)) else list(nil nil)))', timeout=120)))
        context.update(loaded=bool(result[0]), source_definitions=sorted(set(result[1] or [])))
        return context

    def reconstruct(self, snapshot, lib, cell, view="layout", *, review_token=None,
                    group_definition_source=None):
        self.last_readback_normalization = None
        validate(snapshot)
        issues = coverage(snapshot)
        if issues:
            raise ValueError("Snapshot cannot be faithfully reconstructed:\n" + "\n".join(issues))
        if not self.loaded:
            checked(self.client.load_il(Path(__file__).with_name('reader.il')))
            self.loaded = True
        if lib != self.writable_library:
            raise ValueError("Destination is outside the configured test library")
        meta = snapshot["objects"].get("cell:")
        if meta and self.client.library.get(lib).technology_library != meta["technology"]:
            raise ValueError("Destination technology differs from snapshot")
        exists = checked(self.client.execute_skill(f"ddGetObj({sk(lib)} {sk(cell)} {sk(view)})"))
        if exists.strip() != "nil":
            raise ValueError("Destination already exists; reconstruction only creates fresh cells")
        self.last_group_context = self.prepare_group_context(snapshot, group_definition_source)
        self.last_dependency_warnings = self.check_dependencies(snapshot)
        commands = render(snapshot, review_token=review_token)
        build_id = uuid.uuid4().hex
        function = "ALDBuild_" + build_id
        source = self.artifacts / ("build_" + build_id + ".il")
        from .history import atomic_json
        warning_path = self.artifacts / ("dependency_warnings_" + build_id + ".json")
        atomic_json(warning_path, self.last_dependency_warnings)
        source_text, helpers = replay_source(commands, function)
        source.write_text(source_text, encoding="utf-8")
        try:
            checked(self.client.load_il(source))
            checked(self.client.execute_skill('ALDReplayGroupFailure=nil'))
            # The explicit bridge create context balances the owned open and save.
            try:
                with self.client.layout.create(lib, cell, view=view, timeout=120) as edit:
                    edit.commands[0] = f"when(ddGetObj({sk(lib)} {sk(cell)} {sk(view)}) error(\"Destination already exists\")) " + edit.commands[0]
                    edit.add(function + "(cv)")
            except RuntimeError as exc:
                try:
                    failure = loads(checked(self.client.execute_skill(
                        "when(boundp('ALDReplayGroupFailure) ALDReplayGroupFailure)")))
                except Exception:
                    failure = None
                if isinstance(failure, list) and len(failure) == 2:
                    raise ValueError(f'Cannot reconstruct logical group {failure[0]!r} '
                                     f'with definition {failure[1]!r}. Read a source layout '
                                     'containing that definition in this Virtuoso session '
                                     'before replay; custom definitions must be available.') from exc
                raise
        finally:
            # Release generated bodies on both success and partial load failure.
            for offset in range(0, len(helpers), 64):
                checked(self.client.execute_skill("progn(" + " ".join(
                    f"putd('{name} nil)" for name in helpers[offset:offset+64]) + " t)"))
        actual = self.capture(lib, cell, view, dependencies=False)
        equal = native_snapshot(actual) == native_snapshot(snapshot)
        if not equal and any(r['kind'] == 'stdVia' or r.get('mpp') for r in snapshot['objects'].values()):
            # IC23.1 dbCreateVia omits redundant defaults. Compare only row/column
            # overrides proven equal to this destination's viaDef defaults.
            from .native_equivalence import via_default_projection
            names = sorted({r['viaDef'] for state in (snapshot, actual)
                            for r in state['objects'].values() if r['kind'] == 'stdVia'})
            values = loads(checked(self.client.execute_skill(
                f'let((tf vd) tf=techGetTechFile(ddGetObj({sk(lib)})) '
                f'foreach(mapcar name {sk(names)} vd=techFindViaDefByName(tf name) '
                'list(name when(vd nth(3 vd~>params)) when(vd nth(4 vd~>params)))))')))
            defaults = {name: {'cutRows': rows, 'cutColumns': columns} for name, rows, columns in values}
            expected_comparison, expected_count = via_default_projection(snapshot, defaults, mpp_connectivity=True)
            actual_comparison, actual_count = via_default_projection(actual, defaults, mpp_connectivity=True)
            equal = expected_comparison == actual_comparison
            self.last_readback_normalization = {
                'method': 'technology-defaults-and-mpp-effective-connectivity', 'equal': equal,
                'expected_redundant_parameters': expected_count,
                'actual_redundant_parameters': actual_count, 'via_defaults': defaults}
            atomic_json(self.artifacts / ('readback_normalization_' + build_id + '.json'),
                        self.last_readback_normalization)
        if not equal:
            from .core import diff
            from .history import atomic_json
            mismatch = self.artifacts / ("mismatch_" + build_id + ".json")
            atomic_json(mismatch, diff(native_snapshot(snapshot), native_snapshot(actual)))
            raise ValueError("Reconstruction readback mismatch: " + str(mismatch))
        if dependency_records(snapshot):
            try:
                actual = canonicalize(list(actual["objects"].values()) +
                                      self.hierarchy.read(root=(lib, cell, view)))
                issues = compare_dependencies(snapshot, actual)
            except Exception as exc:
                issues = [{"key": "hierarchy", "reason": "readback dependency check unavailable: " + str(exc)}]
            additions = [i for i in issues if i not in self.last_dependency_warnings]
            emit_warnings(additions)
            self.last_dependency_warnings += additions
            atomic_json(warning_path, self.last_dependency_warnings)
        return actual


def replay_source(commands, function, chunk_size=200):
    """Bound each compiled SKILL body without breaking cross-command bindings.

    .il uses dynamic scope (IC23.1 sklanguser/chap13); helpers deliberately
    inherit the main let locals, including the last object and reference tables.
    Each render command is a complete expression sequence, so it is safe to
    split between commands even between object creation and property assignment.
    """
    helpers, bodies = [], []
    interior = commands[1:-1]
    for offset in range(0, len(interior), chunk_size):
        name = function + "_" + str(offset // chunk_size)
        helpers.append(name)
        bodies.append(f"procedure({name}()\n" + "\n".join(interior[offset:offset+chunk_size]) + "\nt)\n")
    bodies.append(f"procedure({function}(cv)\n" + commands[0] + "\n" +
                  "\n".join(name + "()" for name in helpers) + "\n" + commands[-1] + ")\n")
    return "\n".join(bodies), helpers + [function]


def render(snapshot, *, review_token=None):
    from .logical_groups import pin_key, inst_term_key
    from .oa_content import LINK_FIELDS, replay_items
    records = list(snapshot["objects"].values())
    has_logical_groups = any(record['kind'] == 'group' or record['kind'] in LINK_FIELDS for record in records)
    meta = next(r for r in records if r["kind"] == "cell")
    dbu = meta["dbu"]

    def dim(v):
        return [dim(x) for x in v] if isinstance(v, list) else (v / dbu if v is not None else None)

    def prop_cmds(var, props, depth=0):
        cmds = []
        for n, t, v in props:
            if t == "hierProp":
                hp = "hp" + str(depth)
                cmds.append(f"let(({hp}) {hp}=dbCreateHierProp(" + var + " " + sk(n) + f") unless({hp} error(\"HierProp creation failed\")) " + " ".join(prop_cmds(hp, v, depth+1)) + ")")
            else:
                # dbGet exposes OA Boolean property values as "TRUE"/"FALSE";
                # the writer takes SKILL booleans, not nonempty string truthiness.
                if t == "boolean" and isinstance(v, str):
                    if v not in {"TRUE", "FALSE"}:
                        raise ValueError("Invalid Boolean property value")
                    v = v == "TRUE"
                cmds.append(f"unless(dbReplaceProp({var} {sk(n)} {sk(t)} {sk(v)}) error(\"Property creation failed\"))")
        return cmds

    commands = ["let((o n p m it g gm nets terms insts groups pins figures aldMPPs aldMPPShapes aldRod aldShapeKey aldMatches)",
                "nets=makeTable('aldN nil) terms=makeTable('aldT nil) insts=makeTable('aldI nil) groups=makeTable('aldG nil) pins=makeTable('aldP nil)",
                "figures=makeTable('aldFigures nil)",
                'figures["cell:"]=cv',
                f"cv~>DBUPerUU={float(dbu)!r} cv~>userUnits={sk(meta['units'])} cv~>cellType={sk(meta['cellType'])}"]
    commands += prop_cmds("cv", meta["props"])
    from .mpp import prepare_replay, figure_expression
    mpp_commands = prepare_replay(records, dim)
    if review_token:
        commands.append(f"ALDGUIBeginReview({sk(review_token)} cv)")
    for key, r in replay_items(snapshot):
        kind = r["kind"]
        if kind not in {'net', 'term'} and mpp_commands:
            commands += mpp_commands
            mpp_commands = []
        lpp = sk([r.get("layerName"), r.get("purpose")])
        def reference(field):
            return f'figures[{sk(r[field])}]' if r.get(field) else 'nil'
        if kind == 'sitePattern':
            entries = [[name, dim(xy), orient] for name, xy, orient in r['entries']]
            commands.append(f'cv~>sitePattern={sk(entries)}')
            continue
        if kind == "net":
            expr = f"dbCreateNet(cv {sk(r['name'])})"
        elif kind == "term":
            expr = f"dbCreateTerm(nets[{sk(r['net'])}] {sk(r['name'])} {sk(r['direction'])})"
        elif kind == "figGroup":
            expr = f"dbCreateFigGroup(cv {sk(r['name'])} {sk(r.get('ordered'))} {sk(dim(r['origin']))} {sk(r['orient'])})"
        elif kind == "group":
            attributes = ['set' if r['isSet'] else 'collection',
                          'ordered' if r['isOrdered'] else 'unordered',
                          'uniqueName' if r['isUniqueName'] else 'nonUniqueName', r['deleteWhen']]
            expr = f"dbCreateGroup(cv {sk(r['name'])} {sk(attributes)} {sk(r['defName'])})"
        elif kind == "inst":
            expr = f"dbCreateParamInstByMasterName(cv {sk(r['libName'])} {sk(r['cellName'])} {sk(r['viewName'])} {sk(r['name'])} {sk(dim(r['xy']))} {sk(r['orient'])} {sk(r['numInst'])} {sk(r['params'])} {sk(r['physOnly'])})"
        elif kind == "mosaic":
            expr = f"dbCreateParamSimpleMosaicByMasterName(cv {sk(r['libName'])} {sk(r['cellName'])} {sk(r['viewName'])} {sk(r['name'])} {sk(dim(r['xy']))} {sk(r['tileArray'][0])} {sk(r['rows'])} {sk(r['columns'])} {sk(dim(r['uY']))} {sk(dim(r['uX']))} {sk(r['params'])})"
        elif kind == "prBoundary":
            expr = f"dbCreatePRBoundary(cv {sk(dim(r['points']))})"
        elif kind == 'snapBoundary':
            expr = f"dbCreateSnapBoundary(cv {sk(dim(r['points']))} {sk(r['edgeNames'])})"
        elif kind == 'areaBlockage':
            owner = ' ' + reference('owner') if r.get('owner') else ''
            expr = f"dbCreateAreaBlockage(cv {sk(dim(r['points']))}{owner})"
        elif kind == 'layerBlockage':
            owner = ' ' + reference('owner') if r.get('owner') else ''
            expr = f"dbCreateLayerBlockage(cv {sk(r['layer'])} {sk(r['type'])} {sk(dim(r['points']))}{owner})"
        elif kind == 'textDisplay':
            associate = reference('associate')
            for name in r.get('associateProperty', []):
                associate = f'dbGetPropByName({associate} {sk(name)})'
            args = [dim(r['xy']), r['justify'], r['orient'], r['font'], dim(r['height']),
                    r['isDrafted'], r['isOverbar'], r['isVisible'], r['isNameVisible'],
                    r['isValueVisible']]
            if not r.get('associateProperty'):
                args += [r['text'], r['assocType'] == 'paramAssocType']
            expr = f"dbCreateTextDisplay({associate} {reference('owner')} {lpp} t " + ' '.join(sk(x) for x in args) + ')'
        elif kind == "stdVia":
            expr = f"dbCreateVia(cv techFindViaDefByName(techGetTechFile(cv) {sk(r['viaDef'])}) {sk(dim(r['origin']))} {sk(r['orient'])} {sk(r['params'])})"
        elif kind in {"rect", "ellipse"}:
            fn = "dbCreateRect" if kind == "rect" else "dbCreateEllipse"
            expr = f"{fn}(cv {lpp} {sk(dim(r['bBox']))})"
        elif kind == "donut":
            expr = f"dbCreateDonut(cv {lpp} {sk(dim(r['xy']))} {sk(dim(r['outerRadius']))} {sk(dim(r['innerRadius']))})"
        elif kind == "arc":
            expr = f"dbCreateArc(cv {lpp} {sk(dim(r['ellipseBBox']))} {sk(dim(r['bBox']))})"
        elif kind in {"polygon", "line"}:
            fn = "dbCreatePolygon" if kind == "polygon" else "dbCreateLine"
            expr = f"{fn}(cv {lpp} {sk(dim(r['points']))})"
        elif kind == "path":
            expr = f"dbCreatePath(cv {lpp} {sk(dim(r['points']))} {sk(dim(r['width']))} {sk(r['pathStyle'])})"
        elif kind == "pathSeg":
            # Fixed styles derive their extension from width. IC23.1 rejects
            # arbitrary extension arguments for truncate/extend/chamfer; zero
            # requests the documented default and preserves their readback.
            extensions = [dim(r[side + 'Ext']) if r[side + 'Style'] in {'custom', 'variable'} else 0.0
                          for side in ('begin', 'end')]
            if "custom" in {r['beginStyle'], r['endStyle']}:
                extensions.append(dim(r['customExtensions']))
            expr = f"dbCreatePathSeg(cv {lpp} {sk(dim(r['beginPt']))} {sk(dim(r['endPt']))} {sk(dim(r['width']))} {sk(r['beginStyle'])} {sk(r['endStyle'])} {sk(extensions)})"
        elif kind == "label":
            expr = f"dbCreateLabel(cv {lpp} {sk(dim(r['xy']))} {sk(r['theLabel'])} {sk(r['justify'])} {sk(r['orient'])} {sk(r['font'])} {sk(dim(r['height']))})"
        else:
            raise ValueError("Unsupported kind " + kind)
        if r.get('mpp') or r.get('mppOwner'):
            expr = figure_expression(r, dim)
        if kind == 'group':
            commands.append(f'o={expr} unless(o ALDReplayGroupFailure={sk([r["name"], r["defName"]])} '
                            f'error("Creation failed: group %s (definition %s)" {sk(r["name"])} {sk(r["defName"])}))')
        else:
            commands.append(f"o={expr} unless(o error(\"Creation failed: {kind}\"))")
        if has_logical_groups:
            commands.append(f"figures[{sk(key)}]=o")
        if review_token:
            commands.append(f"ALDGUIRemember({sk(review_token)} {sk(key)} o)")
        if r.get('mpp') or r.get('mppOwner'):
            commands.append('foreach(prop o~>prop dbDeleteObject(prop))')
        commands += prop_cmds("o", r.get("props", []))
        if kind in LINK_FIELDS and r.get('parent'):
            commands.append(f"o~>parent={reference('parent')}")
        if kind in {'areaBlockage', 'layerBlockage'}:
            for field in ('density', 'isPushedDown', 'isSoft', 'allowPGNet'):
                # OA exposes zero for ordinary routing blockages but rejects
                # setting density on that type. Only nondefault values need a write.
                if field in r and (field != 'density' or r[field] not in {None, 0}):
                    commands.append(f'o~>{field}={sk(r[field])}')
            for field in ('effectiveWidth', 'spacing'):
                if r.get(field) is not None:
                    commands.append(f'o~>{field}={sk(dim(r[field]))}')
            if r.get('maskColor') not in {None, 'grayColor'}:
                commands.append(f'unless(dbSetBlockageColor(o {sk(r["maskColor"])}) error("Blockage color assignment failed"))')
        if kind == "net":
            commands.append(f"nets[{sk(r['name'])}]=o o~>sigType={sk(r['sigType'])}")
            for field in ("isGlobal", "connStatus", "criticality", "routePattern", "source"):
                if r[field] is not None or field == "isGlobal":
                    commands.append(f"o~>{field}={sk(r[field])}")
        if kind == "term":
            commands.append(f"terms[{sk(r['name'])}]=o")
        if kind == "figGroup":
            commands.append(f"groups[{sk(r['name'])}]=o")
        if kind == "inst":
            commands.append(f"insts[{sk(r['name'])}]=o")
            for field in ("status", "source"):
                if r[field] is not None:
                    commands.append(f"o~>{field}={sk(r[field])}")
            for name, net, props in r["connections"]:
                commands.append(f"it=dbCreateInstTerm(nets[{sk(net)}] o car(setof(tm o~>master~>terminals tm~>name=={sk(name)}))) unless(it error(\"InstTerm creation failed\"))")
                commands += prop_cmds("it", props)
                commands.append(f"figures[{sk(inst_term_key(r['name'], name))}]=it")
        if r.get("routeStatus"):
            commands.append(f"o~>routeStatus={sk(r['routeStatus'])}")
        if kind == "path":
            for field in ("beginExt", "endExt"):
                if r.get(field) is not None:
                    commands.append(f"o~>{field}={sk(dim(r[field]))}")
        if kind == "label":
            for field in ("isDrafted", "isOverbar", "isVisible", "labelType"):
                commands.append(f"o~>{field}={sk(r[field])}")
        if kind == "pathSeg":
            commands.append(f"o~>topology={sk(r['topology'])}")
        if kind == "arc":
            commands.append(f"o~>startAngle={sk(r['startAngle'])} o~>stopAngle={sk(r['stopAngle'])}")
        if (r.get('mpp') or r.get('mppOwner')) and not r.get('pin'):
            net = f'nets[{sk(r["net"])}]' if r.get('net') else 'nil'
            commands.append(f'o~>net={net}')
        elif r.get("net") and kind != "term" and not r.get("pin"):
            commands.append(f"unless(dbAddFigToNet(o nets[{sk(r['net'])}]) error(\"Net assignment failed\"))")
        if r.get("group"):
            commands.append(f"figures[{sk(key)}]=o")
        if r.get("pin"):
            p = r["pin"]
            pin_table_key = sk(json.dumps([p['term'], p['name']]))
            commands.append(f"p=pins[{pin_table_key}] if(p then unless(dbAddFigToPin(p o) error(\"Pin figure attachment failed\")) else p=dbCreatePin(nets[{sk(r['net'])}] o {sk(p['name'])} terms[{sk(p['term'])}]) unless(p error(\"Pin creation failed\")) pins[{pin_table_key}]=p) p~>accessDir={sk(p['accessDir'])} p~>type={sk(p['type'])}")
            commands += prop_cmds("p", p["props"])
            commands.append(f"figures[{sk(pin_key(p['term'], p['name']))}]=p")
    # All members (including nested groups) must exist before attachment. Native
    # ordered groups append members, independent of geometry creation order.
    for key, r in sorted(((k, r) for k, r in snapshot["objects"].items() if r.get("group")),
                         key=lambda item: (item[1]["group"], item[1].get("groupOrder", 0), item[0])):
        commands.append(f"unless(dbAddFigToFigGroup(groups[{sk(r['group'])}] figures[{sk(key)}]) error(\"Group assignment failed\"))")
    for key, r in snapshot['objects'].items():
        if r['kind'] == 'group':
            for member in r['members']:
                commands.append(f"gm=dbAddObjectToGroup(figures[{sk(key)}] figures[{sk(member['target'])}]) unless(gm error(\"Logical group membership failed\"))")
                commands += prop_cmds('gm', member['props'])
    commands.append("t)")
    return commands
