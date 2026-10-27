"""Narrow native readback equivalence; never changes stored snapshots or diffs."""
import copy
import re
from collections import Counter, defaultdict
from .core import canonicalize, digest, encoded
from .storage import NAMED


def via_default_projection(snapshot, defaults, *, mpp_connectivity=False):
    """Remove only proven redundant integer cut-array overrides for comparison.

    Re-key logical-group references after via keys change. Refuse an ambiguous
    collapse of distinct targets rather than assuming a group links either one.
    """
    records = {k: copy.deepcopy(r) for k, r in snapshot['objects'].items()
               if r['kind'] != 'dependency'}
    normalized = 0
    if mpp_connectivity:
        # IC23.1 promotes extracted subrectangle connectivity into the ROD
        # recipe when rebuilt. The ROD manual specifies this propagation on
        # the next MPP edit. Accept only one rectangle set on this LPP, all
        # member rectangles having exactly one nonempty net, with no pin.
        nets = defaultdict(set)
        pins = set()
        for r in records.values():
            if r.get('mppOwner') and r['kind'] == 'rect':
                k = (r['mppOwner'], r.get('layerName'), r.get('purpose'))
                nets[k].add(r.get('net'))
                if r.get('pin'): pins.add(k)
        for r in records.values():
            if not r.get('mpp'): continue
            m = r['mpp']
            # rodCreatePath numbers subparts by creation order. These generated
            # slot names are retained in Git; compare roles and full parameters
            # independently of numbering in a newly generated MPP.
            for p in m['parts']:
                if isinstance(p.get('name'),str) and re.fullmatch(r'subpart\d+',p['name']):
                    del p['name']; normalized += 1
            counts = Counter(tuple(p['lpp']) for p in m['parts'] if p['type'] == 'rectangle')
            for p in m['parts']:
                k = (m['name'], *p['lpp'])
                values = nets.get(k, set())
                if (p['type'] == 'rectangle' and counts[tuple(p['lpp'])] == 1
                        and p['netName'] is None and not p['termName']
                        and len(values) == 1 and None not in values and k not in pins):
                    p['netName'] = next(iter(values)); normalized += 1
            m['parts'].sort(key=encoded)
    for r in records.values():
        if r['kind'] != 'stdVia':
            continue
        known = defaults.get(r['viaDef'], {})
        params = []
        for name, value in r['params']:
            default = known.get(name)
            if (name in {'cutRows', 'cutColumns'} and type(value) is int
                    and type(default) is int and default > 0 and value == default):
                normalized += 1
            else:
                params.append([name, value])
        r['params'] = params
    if not normalized:
        return canonicalize(list(records.values())), 0

    from .oa_content import LINK_FIELDS, references as links
    references = {m['target'] for r in records.values() if r['kind'] == 'group'
                  for m in r.get('members', [])}
    references.update(ref for r in records.values() for ref in links(r))
    counts, keys, raw_targets = Counter(), {}, defaultdict(list)
    def assign(old, r):
        kind = r['kind']
        base = kind + ':' + (r.get('name', '') if kind in NAMED else digest(r))
        key = base if kind in NAMED else base + ':' + str(counts[base])
        counts[base] += 1
        raw_targets[base].append(old)
        keys[old] = key
    pending = {}
    for key, r in sorted(records.items()):
        if r['kind'] == 'group' or r['kind'] in LINK_FIELDS:
            pending[key] = r
        else:
            assign(key, r)
    while pending:
        ready = [key for key, r in pending.items()
                 if all(ref not in pending for ref in
                        ([m['target'] for m in r.get('members', [])] + links(r)))]
        if not ready:
            raise ValueError('Cyclic logical-group links during native comparison')
        for key in ready:
            r = pending.pop(key)
            for member in r.get('members', []):
                target = member['target']
                if target in keys:
                    member['target'] = keys[target]
                elif not target.startswith(('@pin:', '@instTerm:')):
                    raise ValueError('Missing logical-group target during native comparison')
            for field in LINK_FIELDS.get(r['kind'], ()):
                if r.get(field) in keys: r[field] = keys[r[field]]
            if r['kind'] == 'group' and not r['isOrdered']:
                r['members'].sort(key=encoded)
            assign(key, r)
    for originals in raw_targets.values():
        if len(originals) > 1 and any(key in references for key in originals):
            raise ValueError('Ambiguous logical-group target after via-default normalization')
    return canonicalize(list(records.values())), normalized
