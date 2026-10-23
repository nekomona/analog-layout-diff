"""Derived group boundaries/status, independent of stored layout records."""
import json
from collections import defaultdict
from .core import encoded
from .review import GROUP_KINDS, VISUAL


def group_members(snapshot):
    objects = snapshot['objects']
    result = {k: [] for k, r in objects.items() if r['kind'] in GROUP_KINDS}
    for key, r in objects.items():
        if r.get('group'):
            result.get('figGroup:' + r['group'], []).append((r.get('groupOrder', 0), key))
    for key in result:
        r = objects[key]
        if r['kind'] == 'group':
            result[key] = [m['target'] for m in r['members']]
        else:
            result[key] = [k for _, k in sorted(result[key])]
    return result


def group_changes(before, after, pairs):
    old, new = before['objects'], after['objects']
    a, b = group_members(before), group_members(after)
    match = {key: key for key in a.keys() & b.keys()}
    # Logical groups have content IDs. Pair only unambiguous name/definition
    # identities, never guess among duplicate names.
    names = [defaultdict(list), defaultdict(list)]
    for table, members, objects in [(names[0], a, old), (names[1], b, new)]:
        for key in members:
            r = objects[key]
            if r['kind'] == 'group':
                table[(r['name'], r['defName'])].append(key)
    for name in names[0].keys() & names[1].keys():
        if len(names[0][name]) == len(names[1][name]) == 1:
            match[names[1][name][0]] = names[0][name][0]
    remap = {v: k for k, v in {**pairs, **match}.items()}
    def signature(key, objects, members, mapping):
        r = dict(objects[key])
        if r['kind'] == 'group':
            r['members'] = [{**m, 'target': mapping.get(m['target'], m['target'])} for m in r['members']]
            if not r['isOrdered']:
                r['members'].sort(key=encoded)
        targets = [mapping.get(k, k) for k in members[key]]
        if not r.get('ordered') and not r.get('isOrdered'):
            targets.sort()
        return encoded([r, targets])
    result = []
    for key in sorted(b):
        previous = match.get(key)
        if previous is None:
            status = 'new'
        elif signature(previous, old, a, remap) != signature(key, new, b, {}):
            status = 'changed'
        else:
            continue
        result.append({'key': key, 'status': status, 'side': 'after', 'name': new[key]['name'], 'kind': new[key]['kind']})
    for key in sorted(a.keys() - set(match.values())):
        result.append({'key': key, 'status': 'deleted', 'side': 'before', 'name': old[key]['name'], 'kind': old[key]['kind']})
    return result


def boundary_targets(snapshot, keys):
    """Resolve geometric leaves, including nested groups, pins and instTerms."""
    objects = snapshot['objects']
    members = group_members(snapshot)
    pins = defaultdict(list)
    for key, r in objects.items():
        if r.get('pin'):
            p = r['pin']
            pins[(p['term'], p['name'])].append(key)
    cache = {}
    def leaves(key, visiting):
        if key in cache:
            return cache[key]
        if key in visiting:
            raise ValueError('Cyclic group boundary membership')
        if key in members:
            result = set()
            for target in members[key]:
                result.update(leaves(target, visiting | {key}))
        elif key.startswith('@pin:'):
            result = set(pins[tuple(json.loads(key[5:]))])
        elif key.startswith('@instTerm:'):
            result = {'inst:' + json.loads(key[10:])[0]}
        else:
            result = {key} if objects.get(key, {}).get('kind') in VISUAL else set()
        cache[key] = result
        return result
    return [[key, sorted(leaves(key, set()))] for key in keys]
