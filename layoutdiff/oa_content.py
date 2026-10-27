"""Relationships and replay ordering for persistent OA layout annotations."""
from graphlib import TopologicalSorter

LINK_FIELDS = {'textDisplay': ('owner', 'associate', 'parent'),
               'layerBlockage': ('owner', 'parent'),
               'areaBlockage': ('owner', 'parent'), 'snapBoundary': ('parent',)}


def references(record):
    return [record[field] for field in LINK_FIELDS.get(record['kind'], ())
            if isinstance(record.get(field), str) and record[field]]


def replay_items(snapshot):
    """Stable base order, then dependency order for new annotation records."""
    from .core import encoded
    objects = snapshot['objects']
    order = {'net': 0, 'term': 1, 'figGroup': 2, 'group': 2, 'inst': 3, 'mosaic': 3}
    items = sorted(((k, r) for k, r in objects.items() if r['kind'] not in {'cell', 'dependency'}),
                   key=lambda item: (order.get(item[1]['kind'], 4),
                                     0 if (item[1].get('pin') or {}).get('primary') else 1,
                                     encoded(item[1]), item[0]))
    # JSON objects have no semantic iteration order. Use the same content order
    # as canonicalize(), including after v2/Git decoding. Native ROD callbacks
    # make an arbitrary input-order tie-breaker observably change metadata.
    ordinary = [(k, r) for k, r in items if r['kind'] not in LINK_FIELDS]
    linked = {k: r for k, r in items if r['kind'] in LINK_FIELDS}
    from .logical_groups import pin_key
    aliases = {pin_key(r['pin']['term'], r['pin']['name']): k for k,r in items
               if r.get('pin') and r['pin'].get('primary')}
    graph = {k: [aliases.get(ref, ref) for ref in references(r) if aliases.get(ref, ref) in linked]
             for k, r in linked.items()}
    return ordinary + [(k, linked[k]) for k in TopologicalSorter(graph).static_order()]


def issues(record):
    r, result = record, list(record.get('referenceIssues', []))
    kind = r['kind']
    for field in LINK_FIELDS.get(kind, ()):
        if field not in r or (r[field] is not None and not isinstance(r[field], str)):
            result.append('invalid or missing ' + kind + ' ' + field + ' reference')
        path = r.get(field + 'Property')
        if path is not None and (not isinstance(path, list) or not path or any(not isinstance(n, str) for n in path)):
            result.append('invalid ' + field + ' property path')
    if kind == 'textDisplay':
        if r.get('assocType') not in {'attrAssocType', 'paramAssocType', 'propAssocType'}:
            result.append('unsupported textDisplay association: ' + str(r.get('assocType')))
        if not r.get('owner') or not r.get('associate'):
            result.append('textDisplay requires captured owner and associate')
        if not isinstance(r.get('text'), str):
            result.append('textDisplay attribute/parameter name missing')
        path = r.get('associateProperty')
        if (r.get('assocType') == 'propAssocType') != bool(path) or (path is not None and
            (not isinstance(path, list) or any(not isinstance(n, str) for n in path))):
            result.append('invalid textDisplay property path')
    if kind in {'layerBlockage', 'areaBlockage'}:
        types = {'placement'} if kind == 'areaBlockage' else {
            'routing', 'viaRouting', 'wiring', 'fill', 'slot', 'pin', 'feedthru', 'screen', 'Screen'}
        if r.get('type') not in types:
            result.append('unsupported blockage type: ' + str(r.get('type')))
        if r.get('spacing') is not None and r.get('effectiveWidth') is not None:
            result.append('blockage spacing and effectiveWidth are mutually exclusive')
    if kind == 'sitePattern':
        entries = r.get('entries')
        if not isinstance(entries, list) or not entries:
            result.append('empty or invalid sitePattern')
        else:
            for entry in entries:
                if (not isinstance(entry, list) or len(entry) != 3 or
                    not isinstance(entry[0], str) or not isinstance(entry[1], list) or
                    len(entry[1]) != 2 or any(type(x) is not int for x in entry[1]) or
                    not isinstance(entry[2], str) or
                    entry[2] not in {'R0', 'R90', 'R180', 'R270', 'MX', 'MY', 'MXR90', 'MYR90'}):
                    result.append('invalid sitePattern entry')
    if kind == 'snapBoundary':
        if len(r.get('points') or []) != 4 or len(r.get('edgeNames') or []) != 4:
            result.append('snapBoundary requires four points and edge names')
    return result
