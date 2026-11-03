"""Conservative three-way merging over logical objects, never serialized lines.

Anonymous correspondence is evidence, not persisted identity. Ambiguities are
explicit decisions. Snapshot keys and all supported native references are rebuilt
after choosing records. No database handles or source mutations are involved.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import copy
from graphlib import TopologicalSorter, CycleError

from layoutdiff.data.core import canonicalize, digest, encoded, validate, SCHEMA
from layoutdiff.data.storage import NAMED
from layoutdiff.comparison.matching import pairs
from layoutdiff.comparison.categories import category, operation_category
from layoutdiff.data.references import LINK_FIELDS, dependencies, alias_owner

SIDES = ('base', 'target', 'incoming')
GEOMETRY = frozenset(('bBox', 'points', 'xy', 'origin', 'orient', 'width', 'beginPt', 'endPt',
    'beginStyle', 'endStyle', 'beginExt', 'endExt', 'customExtensions', 'pathStyle',
    'layer', 'layerName', 'purpose', 'height', 'radius', 'innerRadius', 'outerRadius',
    'ellipseBBox', 'params', 'mpp', 'rows', 'columns', 'rowSpacing', 'columnSpacing',
    'numInst', 'master', 'libName', 'cellName', 'viewName', 'pcell', 'viaDef', 'entries'))
MISSING = object()


def references(record):
    refs = [record[f] for f in LINK_FIELDS.get(record['kind'], ()) if record.get(f)]
    refs += [m['target'] for m in record.get('members', [])] if record['kind'] == 'group' else []
    return refs


def remap(record, mapping):
    result = dict(record)
    for field in LINK_FIELDS.get(record['kind'], ()):
        if record.get(field):
            result[field] = mapping.get(record[field], record[field])
    if record['kind'] == 'group':
        result['members'] = [{**m, 'target': mapping.get(m['target'], m['target'])} for m in record['members']]
        if not record.get('isOrdered'):
            result['members'].sort(key=encoded)
    return result


def materialize(records):
    """Re-key anonymous records and links in dependency order, preserving counts."""
    graph = {key: {ref for ref in references(r) if not ref.startswith('@')}
             for key, r in records.items()}
    missing = set().union(*graph.values()) - records.keys() if graph else set()
    if missing:
        raise ValueError('Unresolved native references: ' + ', '.join(sorted(missing)[:8]))
    try:
        order = TopologicalSorter(graph).static_order()
        mapped, output, counts = {}, [], Counter()
        for handle in order:
            r = remap(records[handle], mapped)
            if r['kind'] in NAMED:
                key = r['kind'] + ':' + r.get('name', '')
            else:
                prefix = r['kind'] + ':' + digest(r)
                key = prefix + ':' + str(counts[prefix])
                counts[prefix] += 1
            mapped[handle] = key
            output.append(r)
    except CycleError as exc:
        raise ValueError('Cyclic merged references') from exc
    return canonicalize(output)


def _three(b, t, i):
    if t == i:
        return t
    if t == b:
        return i
    if i == b:
        return t
    return MISSING


def merge_record(b, t, i):
    value = _three(b, t, i)
    if value is not MISSING:
        return value, []
    if None in (b, t, i):
        return None, ['delete/modify' if b is not None else 'competing additions']
    if len({r['kind'] for r in (b, t, i)}) != 1:
        return None, ['object kind']
    result, conflicts = {}, []
    geometry = [{f: r[f] for f in GEOMETRY if f in r} for r in (b, t, i)]
    value = _three(*geometry)
    if value is MISSING:
        conflicts.append('coupled geometry / master / recipe')
    else:
        result.update(value)
    fields = (b.keys() | t.keys() | i.keys()) - GEOMETRY
    for field in sorted(fields):
        if field == 'props':
            props = [{p[0]: p for p in r.get('props', [])} for r in (b, t, i)]
            merged = []
            for name in sorted(set().union(*(p.keys() for p in props))):
                values = [p.get(name, MISSING) for p in props]
                value = _three(*values)
                if value is MISSING and values[1] != values[2] and values[1] != values[0] and values[2] != values[0]:
                    conflicts.append('property ' + name)
                elif value is not MISSING:
                    merged.append(value)
            if any('props' in r for r in (b, t, i)):
                result[field] = merged
            continue
        values = [r.get(field, MISSING) for r in (b, t, i)]
        value = _three(*values)
        if value is MISSING and values[1] != values[2] and values[1] != values[0] and values[2] != values[0]:
            conflicts.append(field)
        elif value is not MISSING:
            result[field] = value
    return (None if conflicts else result), conflicts


def _family(record):
    return encoded([record['kind'], record.get('layerName', record.get('layer')),
                    record.get('purpose'), record.get('viaDef')])


class MergePlan:
    """Immutable analysis and deterministic candidate generation.

    Units contain changed objects only. Unchanged records are shared, not copied
    into every conflict. Each side uses temporary logical handles until emission.
    """
    def __init__(self, base, target, incoming):
        self.inputs = dict(zip(SIDES, (base, target, incoming)))
        for state in self.inputs.values():
            validate(state)
        self.maps = {'base': {k: k for k in base['objects']}}
        self.evidence = defaultdict(list)
        self.warnings = []
        for side in SIDES[1:]:
            objects = self.inputs[side]['objects']
            mapping = {k: k for k in objects if k in base['objects'] or objects[k]['kind'] in NAMED}
            old = {k: r for k, r in base['objects'].items() if k not in objects and r['kind'] not in NAMED}
            new = {k: r for k, r in objects.items() if k not in mapping}
            for key, previous, evidence in pairs(old.items(), new.items()):
                mapping[key] = previous
                self.evidence[previous].append([side, evidence])
            # Unique logical group names are suggestions, never persistent IDs.
            group_old, group_new = defaultdict(list), defaultdict(list)
            for k, r in old.items():
                if r['kind'] == 'group':
                    group_old[(r.get('name'), r.get('defName'))].append(k)
            for k, r in new.items():
                if r['kind'] == 'group' and k not in mapping:
                    group_new[(r.get('name'), r.get('defName'))].append(k)
            for name in group_old.keys() & group_new.keys():
                if len(group_old[name]) == len(group_new[name]) == 1:
                    k, previous = group_new[name][0], group_old[name][0]
                    mapping[k] = previous
                    self.evidence[previous].append([side, 'unique group name/definition'])
            for k in objects:
                mapping.setdefault(k, side + '/' + k)
            self.maps[side] = mapping
        self.records = {side: {self.maps[side][k]: remap(r, self.maps[side])
                             for k, r in state['objects'].items()}
                        for side, state in self.inputs.items()}
        all_keys = sorted(set().union(*(r.keys() for r in self.records.values())))
        self.common = {}
        changed = {}
        for key in all_keys:
            records = [self.records[s].get(key) for s in SIDES]
            if records[0] == records[1] == records[2]:
                self.common[key] = records[0]
            else:
                changed[key] = records
        parent = {k: k for k in all_keys}
        def find(k):
            while parent[k] != k:
                parent[k] = parent[parent[k]]
                k = parent[k]
            return k
        def union(keys):
            keys = list(keys)
            for k in keys[1:]:
                parent[find(k)] = find(keys[0])
        ambiguous = set()
        buckets = defaultdict(list)
        for key, records in changed.items():
            r = next(r for r in records if r is not None)
            if r['kind'] not in NAMED and not self.evidence[key] and any(r is None for r in records):
                buckets[_family(r)].append(key)
        for keys in buckets.values():
            target_changes = any(changed[k][0] != changed[k][1] for k in keys)
            incoming_changes = any(changed[k][0] != changed[k][2] for k in keys)
            if target_changes and incoming_changes:
                union(keys)
                ambiguous.update(keys)
        # Keep MPP recipes and generated members atomic.
        mpps = defaultdict(set)
        for side in SIDES:
            for k, r in self.records[side].items():
                name = r.get('mppOwner') or (r.get('mpp') or {}).get('name')
                if name:
                    mpps[str(name)].add(k)
        for keys in mpps.values():
            if set(keys) & changed.keys():
                union(keys)
        # Ordered groups and multi-figure pins form compound decisions. A field
        # merge must not leave duplicate ordinals or two primary pin figures.
        compounds = defaultdict(set)
        for side in SIDES:
            objects = self.records[side]
            for k, r in objects.items():
                if r['kind'] == 'figGroup' and r.get('ordered'):
                    compounds['group/' + r['name']].add(k)
                if r.get('group') and objects.get('figGroup:' + r['group'], {}).get('ordered'):
                    compounds['group/' + r['group']].add(k)
                if r.get('pin'):
                    p = r['pin']
                    compounds['pin/' + p['term'] + '/' + p['name']].add(k)
        for keys in compounds.values():
            if keys & changed.keys():
                union(keys)
        # Deleting a referenced object couples the owner and target choices.
        for side in SIDES:
            for k, r in self.records[side].items():
                for target in dependencies(r):
                    ref = alias_owner(target)
                    if ref in changed and any(v is None for v in changed[ref]):
                        union((k, ref))
        # Technology and DBU changes cannot be mixed with another coordinate system.
        metadata = [self.records[s].get('cell:', {}) for s in SIDES]
        if (target != base and incoming != base and
                len({encoded({f: r.get(f) for f in ('dbu', 'units', 'technology')}) for r in metadata}) > 1):
            union(all_keys)
            ambiguous.update(changed)
        components = defaultdict(list)
        for key in all_keys:
            components[find(key)].append(key)
        self.units = {}
        for keys in components.values():
            if not changed.keys() & set(keys):
                continue
            alternatives = {s: {k: self.records[s][k] for k in keys if k in self.records[s]} for s in SIDES}
            combined, reasons = {}, []
            if any(set(keys) & members for members in mpps.values()):
                b, t, i = (alternatives[s] for s in SIDES)
                if t != b and i != b and t != i:
                    reasons.append('coupled MPP recipe and generated members')
            for k in keys:
                b, t, i = [self.records[s].get(k) for s in SIDES]
                record, issues = merge_record(b, t, i)
                if (b or t or i)['kind'] == 'dependency' and issues:
                    record, issues = t or i or b, []
                    self.warnings.append('Referenced master differs between branches: ' + k)
                if record is not None:
                    combined[k] = record
                reasons.extend(issues)
                if self.evidence[k] and t != b and i != b:
                    reasons.append('inferred correspondence needs confirmation')
            if set(keys) & ambiguous:
                reasons.append('ambiguous anonymous correspondence or coordinate-system change')
            for k, r in combined.items():
                if r['kind'] == 'figGroup' and r.get('ordered'):
                    members = [v for v in combined.values() if v.get('group') == r['name']]
                    ranks = [v.get('groupOrder') for v in members]
                    if r.get('memberCount') != len(members) or sorted(v for v in ranks if type(v) is int) != list(range(len(members))):
                        reasons.append('incompatible ordered-group membership')
            pinsets = defaultdict(list)
            for r in combined.values():
                if r.get('pin'):
                    p = r['pin']; pinsets[(p['term'], p['name'])].append(p)
            for pins in pinsets.values():
                if any('primary' in p for p in pins) and sum(bool(p.get('primary')) for p in pins) != 1:
                    reasons.append('incompatible primary pin figures')
            primary = next(k for k in keys if k in changed)
            b, t, i = [self.records[s].get(primary) for s in SIDES]
            record = t or i or b
            label = category(record)
            if b and (t or i):
                label = operation_category({'before': b, 'after': t if t != b and t else i or b})
            ident = 'C' + digest(keys)[:16]
            self.units[ident] = {'id': ident, 'keys': keys, 'category': label,
                'reasons': sorted(set(reasons)), 'evidence': {k: self.evidence[k] for k in keys if self.evidence[k]},
                'alternatives': alternatives, 'combined': combined if not any(
                    reason != 'inferred correspondence needs confirmation' for reason in reasons) else None}
            for k in keys:
                self.common.pop(k, None)

    def candidate(self, unit_id, choice):
        unit = self.units[unit_id]
        if choice in SIDES:
            return unit['alternatives'][choice]
        if choice == 'combined' and unit['combined'] is not None:
            return unit['combined']
        if choice == 'both':
            t, i = unit['alternatives']['target'], unit['alternatives']['incoming']
            if any(r['kind'] in NAMED or references(r) or r.get('mpp') or r.get('mppOwner') or r.get('pin')
                   for r in [*t.values(), *i.values()]):
                raise ValueError('Keep both requires independent anonymous figures without native relationships')
            result = dict(t)
            for key, r in i.items():
                if key not in result:
                    result[key] = r
                elif result[key] != r:
                    result['both/' + key] = r
            return result
        raise ValueError('Choice is unavailable for this conflict: ' + choice)

    def logical_result(self, decisions=None):
        decisions = decisions or {}
        result = dict(self.common)
        for ident, unit in self.units.items():
            choice = decisions.get(ident)
            if isinstance(choice, dict):
                selected = choice
            elif choice:
                selected = self.candidate(ident, choice)
            else:
                selected = unit['alternatives']['base'] if unit['reasons'] else unit['combined']
            result.update(selected)
        return result

    def result(self, decisions=None):
        return materialize(self.logical_result(decisions))

    def unresolved(self, decisions=None):
        return [k for k, u in self.units.items() if u['reasons'] and k not in (decisions or {})]

    def counts(self, decisions=None):
        counts = defaultdict(Counter)
        for k, unit in self.units.items():
            status = 'resolved' if k in (decisions or {}) else 'unresolved' if unit['reasons'] else 'automatic'
            counts[unit['category']][status] += 1
        return {k: dict(v) for k, v in sorted(counts.items())}
