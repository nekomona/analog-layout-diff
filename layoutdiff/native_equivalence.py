"""Narrow native readback equivalence; never changes stored snapshots or diffs."""
import copy
from collections import Counter, defaultdict
from .core import canonicalize, digest, encoded
from .storage import NAMED


def via_default_projection(snapshot, defaults):
    """Remove only proven redundant integer cut-array overrides for comparison.

    Re-key logical-group references after via keys change. Refuse an ambiguous
    collapse of distinct targets rather than assuming a group links either one.
    """
    records = {k: copy.deepcopy(r) for k, r in snapshot['objects'].items()
               if r['kind'] != 'dependency'}
    normalized = 0
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

    references = {m['target'] for r in records.values() if r['kind'] == 'group'
                  for m in r.get('members', [])}
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
        if r['kind'] == 'group':
            pending[key] = r
        else:
            assign(key, r)
    while pending:
        ready = [key for key, r in pending.items()
                 if all(m['target'] not in pending for m in r['members'])]
        if not ready:
            raise ValueError('Cyclic logical-group links during native comparison')
        for key in ready:
            r = pending.pop(key)
            for member in r['members']:
                target = member['target']
                if target in keys:
                    member['target'] = keys[target]
                elif not target.startswith(('@pin:', '@instTerm:')):
                    raise ValueError('Missing logical-group target during native comparison')
            if not r['isOrdered']:
                r['members'].sort(key=encoded)
            assign(key, r)
    for originals in raw_targets.values():
        if len(originals) > 1 and any(key in references for key in originals):
            raise ValueError('Ambiguous logical-group target after via-default normalization')
    return canonicalize(list(records.values())), normalized
