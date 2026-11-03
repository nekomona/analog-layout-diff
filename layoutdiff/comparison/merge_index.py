"""Disposable indexes for bounded merge navigation and native projections."""
from collections import defaultdict
import sqlite3

from layoutdiff.comparison.matching import bounds
from layoutdiff.comparison.review import VISUAL
from layoutdiff.data.merge import materialize, SIDES
from layoutdiff.data.references import dependencies, alias_owner


class MergeIndex:
    def __init__(self, plan):
        self.plan = plan
        self.db = sqlite3.connect('')
        self.db.executescript('''PRAGMA temp_store=FILE; PRAGMA cache_size=-4096;
            CREATE TABLE units(id TEXT PRIMARY KEY, category TEXT, rank INTEGER);
            CREATE TABLE regions(id INTEGER PRIMARY KEY, unit TEXT, side TEXT, layer TEXT);
            CREATE VIRTUAL TABLE boxes USING rtree(id,x0,x1,y0,y1);
            CREATE INDEX category ON units(category,rank);
            CREATE INDEX by_unit ON regions(unit,side);''')
        self.reverse, self.members, self.handles, self.companions = {}, {}, {}, {}
        self.unit_by_key = {k: ident for ident, u in plan.units.items() for k in u['keys']}
        for rank, (ident, unit) in enumerate(plan.units.items()):
            self.db.execute('INSERT INTO units VALUES (?,?,?)', (ident, unit['category'], rank))
        for side in SIDES:
            objects = plan.inputs[side]['objects']
            self.handles[side] = {v: k for k, v in plan.maps[side].items()}
            reverse, members, companions = defaultdict(set), defaultdict(set), defaultdict(list)
            compound = defaultdict(set)
            for key, r in objects.items():
                for ref in dependencies(r):
                    reverse[alias_owner(ref)].add(key)
                if r.get('group'):
                    members['figGroup:' + r['group']].add(key)
                if r['kind'] == 'group':
                    members[key].update(m['target'] for m in r['members'])
                if r.get('pin'):
                    p = r['pin']; compound[('pin', p['term'], p['name'])].add(key)
                name = r.get('mppOwner') or (r.get('mpp') or {}).get('name')
                if name:
                    compound[('mpp', name)].add(key)
            # Share each compound set; do not copy it once per member.
            for keys in compound.values():
                for key in keys:
                    companions[key].append(keys)
            self.reverse[side], self.members[side], self.companions[side] = reverse, members, companions
            dbu = objects.get('cell:', {}).get('dbu', 1000)
            for key, r in objects.items():
                ident = self.unit_by_key.get(plan.maps[side][key])
                box = bounds(r)
                if ident and box:
                    row = self.db.execute('INSERT INTO regions(unit,side,layer) VALUES (?,?,?)',
                        (ident, side, str(r.get('layerName', r.get('layer', ''))))).lastrowid
                    self.db.execute('INSERT INTO boxes VALUES (?,?,?,?,?)',
                        (row, box[0]/dbu, box[2]/dbu, box[1]/dbu, box[3]/dbu))
            # Metadata-only units still need a graphical picking target. These
            # context boxes are excluded from physical interaction warnings.
            for ident, unit in plan.units.items():
                special = [self.handles[side][k] for k in unit['keys'] if k in self.handles[side]
                           and objects[self.handles[side][k]]['kind'] in {'net', 'term', 'group', 'figGroup'}]
                if not special:
                    continue
                selected, _ = self.selection(side, ident)
                leaves, queue = set(selected), list(special)
                expanded = set()
                while queue:
                    key = queue.pop()
                    if key in expanded:
                        continue
                    expanded.add(key)
                    for ref in self.members[side].get(key, ()):
                        ref = alias_owner(ref)
                        leaves.add(ref)
                        if ref in self.members[side]:
                            queue.append(ref)
                boxes = [box for key in leaves if (box := bounds(objects.get(key, {})))]
                if boxes:
                    box = (min(b[0] for b in boxes), min(b[1] for b in boxes),
                           max(b[2] for b in boxes), max(b[3] for b in boxes))
                    row = self.db.execute('INSERT INTO regions(unit,side,layer) VALUES (?,?,?)',
                        (ident, 'context-' + side, '')).lastrowid
                    self.db.execute('INSERT INTO boxes VALUES (?,?,?,?,?)',
                        (row, box[0]/dbu, box[2]/dbu, box[1]/dbu, box[3]/dbu))
        self.db.commit()
        self.categories = [row[0] for row in self.db.execute('SELECT DISTINCT category FROM units ORDER BY category')]

    def close(self):
        self.db.close()

    def page(self, category=None, offset=0, limit=50):
        return [row[0] for row in self.db.execute(
            'SELECT id FROM units WHERE (? IS NULL OR category=?) ORDER BY rank LIMIT ? OFFSET ?',
            (category, category, limit, max(0, offset)))]

    def pick(self, point):
        x, y = point
        return [row[0] for row in self.db.execute('''SELECT DISTINCT r.unit FROM boxes b JOIN regions r USING(id)
            WHERE b.x0<=? AND b.x1>=? AND b.y0<=? AND b.y1>=? LIMIT 9''', (x+.001, x-.001, y+.001, y-.001))]

    def interactions(self, unit):
        return [row[0] for row in self.db.execute('''SELECT DISTINCT other.unit
            FROM regions own JOIN boxes a ON own.id=a.id JOIN boxes b
            ON b.x0<=a.x1 AND b.x1>=a.x0 AND b.y0<=a.y1 AND b.y1>=a.y0
            JOIN regions other ON other.id=b.id
            WHERE own.unit=? AND own.side IN ('target','incoming') AND other.side IN ('target','incoming')
              AND own.side!=other.side AND own.unit!=other.unit AND own.layer=other.layer LIMIT 8''', (unit,))]

    def selection(self, side, unit, limit=2000):
        """Net/terminal edits show connected geometry; groups show boundaries."""
        objects = self.plan.inputs[side]['objects']
        selected = {self.handles[side][k] for k in self.plan.units[unit]['keys'] if k in self.handles[side]}
        def changed(key):
            if objects[key]['kind'] not in VISUAL:
                return True
            handle = self.plan.maps[side][key]
            values = [self.plan.records[s].get(handle) for s in SIDES]
            values = [None if r is None else {k:v for k,v in r.items() if k not in {'group', 'groupOrder'}} for r in values]
            return not values[0] == values[1] == values[2]
        selected = {key for key in selected if changed(key)}
        queue = [k for k in selected if objects[k]['kind'] in {'net', 'term'}]
        seen = set(queue)
        while queue and len(selected) <= limit:
            key = queue.pop()
            for ref in sorted(self.reverse[side].get(key, ())):
                selected.add(ref)
                if ref not in seen and objects[ref]['kind'] in {'net', 'term'}:
                    queue.append(ref); seen.add(ref)
                if len(selected) > limit:
                    break
        return sorted(selected)[:limit], len(selected) > limit

    def projection(self, side, unit):
        objects = self.plan.inputs[side]['objects']
        selected, truncated = self.selection(side, unit)
        needed = set(selected)
        if 'cell:' in objects:
            needed.add('cell:')
        needed.update(k for k, r in objects.items() if r['kind'] == 'dependency')
        queue, expanded = list(needed), set()
        while queue:
            key = queue.pop()
            if key in expanded:
                continue
            expanded.add(key)
            record = objects.get(key)
            if record is None:
                continue
            deps = {alias_owner(k) for k in dependencies(record)}
            deps.update(alias_owner(k) for k in self.members[side].get(key, ()))
            for compound in self.companions[side].get(key, ()):
                deps.update(compound)
            # Pin/instTerm aliases need their figures when used by annotations.
            for ref in dependencies(record):
                if ref.startswith('@pin:'):
                    deps.update(self.reverse[side].get(alias_owner(ref), ()))
            for dep in deps:
                if dep in objects and dep not in needed:
                    needed.add(dep); queue.append(dep)
        snapshot, mapped = materialize({k: objects[k] for k in sorted(needed)}, with_mapping=True)
        return snapshot, [mapped[k] for k in selected], truncated
