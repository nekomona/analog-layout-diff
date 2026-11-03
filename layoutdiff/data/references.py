"""Native relationship fields in the logical snapshot contract (no EDA imports)."""
import json

LINK_FIELDS = {'textDisplay': ('owner', 'associate', 'parent'),
               'layerBlockage': ('owner', 'parent'),
               'areaBlockage': ('owner', 'parent'), 'snapBoundary': ('parent',)}


def references(record):
    return [record[field] for field in LINK_FIELDS.get(record['kind'], ())
            if isinstance(record.get(field), str) and record[field]]


def dependencies(record):
    result = references(record)
    if record['kind'] == 'group':
        result += [m['target'] for m in record.get('members', [])]
    if record.get('net'):
        result.append('net:' + record['net'])
    if record.get('group'):
        result.append('figGroup:' + record['group'])
    if record.get('pin'):
        result.append('term:' + record['pin']['term'])
    if record['kind'] == 'inst':
        result += ['net:' + con[1] for con in record.get('connections', []) if con[1]]
    return result


def alias_owner(key):
    if key.startswith('@instTerm:'):
        return 'inst:' + json.loads(key[10:])[0]
    if key.startswith('@pin:'):
        return 'term:' + json.loads(key[5:])[0]
    return key
