"""Deterministic review pairing; canonical snapshots and exact patches stay intact.

There are no persistent IDs on anonymous OA figures. Equal geometry is exact;
move/stretch pairing is an inference. Refuse ties and crowded neighborhoods.
SQLite indexes bound memory and candidate work for large layouts.
"""
from collections import Counter
import hashlib
import json
import math
import sqlite3
from itertools import chain
from layoutdiff.data.core import encoded
from layoutdiff.comparison.geometry_changes import POSITION, via_context

ATTRIBUTES = {'props', 'net', 'pin', 'group', 'groupOrder', 'routeStatus'}
ANNOTATIONS = {'mpp', 'mppOwner'}
KINDS = {'rect', 'polygon', 'path', 'pathSeg', 'label', 'ellipse', 'line', 'donut', 'arc',
         'stdVia', 'prBoundary', 'snapBoundary', 'layerBlockage', 'areaBlockage', 'textDisplay'}
LIMIT = 32


def bounds(r):
    points = []
    for field in POSITION:
        value = r.get(field)
        if not value: continue
        points.extend(value if isinstance(value[0], list) else [value])
    if not points or any(len(p) != 2 or any(type(x) not in (int, float) for x in p) for p in points):
        return None
    return min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)


def signature(r, *, translate=False):
    r = {k:v for k,v in r.items() if k not in ATTRIBUTES | ANNOTATIONS}
    box = bounds(r)
    if translate and box:
        def shift(v):
            return [shift(p) for p in v] if isinstance(v[0], list) else [v[0]-box[0], v[1]-box[1]]
        r = {k: shift(v) if k in POSITION and v else v for k,v in r.items()}
    return hashlib.sha256(encoded(r)).hexdigest()


def family(r):
    return encoded([r['kind'], r.get('layerName', r.get('layer')), r.get('purpose'),
                    r.get('viaDef'), r.get('theLabel'), r.get('text'), r.get('orient')])


def score(a, b):
    """Zero..one geometric evidence, with a small connectivity tie-breaker."""
    if family(a) != family(b): return 0
    # Do not pair unrelated MPP members or different named master paths.
    if a.get('mppOwner') and b.get('mppOwner') and a['mppOwner'] != b['mppOwner']: return 0
    if a.get('mpp') and b.get('mpp') and a['mpp']['name'] != b['mpp']['name']: return 0
    x, y = bounds(a), bounds(b)
    if not x or not y: return 0
    width = max(x[2]-x[0], y[2]-y[0], a.get('width') or 1, b.get('width') or 1, 1)
    height = max(x[3]-x[1], y[3]-y[1], a.get('width') or 1, b.get('width') or 1, 1)
    distance = math.hypot(((x[0]+x[2])-(y[0]+y[2]))/2, ((x[1]+x[3])-(y[1]+y[3]))/2)
    rigid = signature(a, translate=True) == signature(b, translate=True)
    if rigid:
        if distance > 8 * max(width, height): return 0
        value = .88 - .12 * min(1, distance / max(width, height))
    else:
        intersection = max(0, min(x[2], y[2])-max(x[0], y[0])) * max(0, min(x[3], y[3])-max(x[1], y[1]))
        area = max((x[2]-x[0])*(x[3]-x[1]), (y[2]-y[0])*(y[3]-y[1]), 1)
        overlap = intersection / area
        anchors = sum(x[i] == y[i] for i in range(4))
        # BBox overlap alone is insufficient for routed or polygonal figures.
        ap = a.get('points') or ([a['beginPt'], a['endPt']] if 'beginPt' in a else None)
        bp = b.get('points') or ([b['beginPt'], b['endPt']] if 'beginPt' in b else None)
        if ap and bp:
            if len(ap) != len(bp): return 0
            kept = sum(p == q for p,q in zip(ap,bp)) / len(ap)
            if kept < .5: return 0
        if anchors < 2 or (overlap < .2 and not ap): return 0
        value = .65 + .12 * min(1, anchors/3) + .10 * overlap
    if a.get('net') and a.get('net') == b.get('net'): value += .025
    if a.get('props') and a.get('props') == b.get('props'): value += .015
    return value


def pairs(before, after):
    """Yield (new key, old key, evidence) from unmatched (key,record) streams."""
    before,after=iter(before),iter(after)
    first_old,first_new=next(before,None),next(after,None)
    if first_old is None or first_new is None:
        return
    before,after=chain([first_old],before),chain([first_new],after)
    db = sqlite3.connect('')
    db.executescript('''PRAGMA cache_size=-4096; PRAGMA temp_store=FILE;
      CREATE TABLE items(id INTEGER PRIMARY KEY, side INT,key TEXT,raw BLOB,sig TEXT,rigid TEXT,
                         family BLOB,x REAL,y REAL,active INT DEFAULT 1, name TEXT, context BLOB);
      CREATE VIRTUAL TABLE boxes USING rtree(id,x0,x1,y0,y1);
      CREATE TABLE anchors(side INT,token BLOB,id INT);
    ''')
    try:
        for side, records in enumerate((before, after)):
            for key, r in records:
                if r['kind'] not in KINDS: continue
                box = bounds(r)
                oid = db.execute('INSERT INTO items(side,key,raw,sig,rigid,family,x,y,name,context) VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (side,key,encoded(r),signature(r),signature(r,translate=True),family(r),
                     box[0] if box else None,box[1] if box else None,(r.get('mpp') or {}).get('name'),via_context(r))).lastrowid
        db.executescript('''CREATE INDEX exact ON items(side,active,sig,key);
          CREATE INDEX rigid ON items(side,active,rigid,x,y,key);
          CREATE INDEX named ON items(side,active,name,key);''')
        def consume(new, old, reason):
            db.executemany('UPDATE items SET active=0 WHERE id=?', [(new[0],),(old[0],)])
            return new[1],old[1],reason
        # ROD master names are real native identities. Never pair different names.
        for row in db.execute('SELECT id,key,name FROM items WHERE side=1 AND active=1 AND name IS NOT NULL ORDER BY key'):
            old = db.execute('SELECT id,key FROM items WHERE side=0 AND active=1 AND name=?', (row[2],)).fetchall()
            if len(old)==1 and db.execute('SELECT count(*) FROM items WHERE side=1 AND name=?',(row[2],)).fetchone()[0]==1:
                yield consume(row,old[0],'MPP name')
        for row in db.execute('SELECT id,key,sig FROM items WHERE side=1 AND active=1 ORDER BY key'):
            old = db.execute('SELECT id,key FROM items WHERE side=0 AND active=1 AND sig=? ORDER BY key LIMIT 1',(row[2],)).fetchone()
            if old: yield consume(row,old,'equal geometry')
        # Unique shape fingerprints establish translations without a nearest-
        # neighbor scan. Repeated shapes use a translation only with >=2 votes.
        votes = Counter()
        for row in db.execute('SELECT min(id),min(key),rigid,x,y,raw FROM items WHERE side=1 AND active=1 GROUP BY rigid HAVING count(*)=1'):
            old = db.execute('SELECT id,key,x,y,raw FROM items WHERE side=0 AND active=1 AND rigid=? LIMIT 2',(row[2],)).fetchall()
            if len(old)==1 and row[3] is not None and old[0][2] is not None and score(json.loads(old[0][4]),json.loads(row[5])) >= .75:
                votes[(row[3]-old[0][2],row[4]-old[0][3])] += 1
                yield consume(row,old[0],'translation')
        displacements = [v for v,n in votes.most_common(8) if n>=2]
        for row in db.execute('SELECT id,key,rigid,x,y FROM items WHERE side=1 AND active=1 ORDER BY key'):
            if row[3] is None: continue
            found = []
            for dx,dy in displacements:
                found.extend(db.execute('SELECT id,key FROM items WHERE side=0 AND active=1 AND rigid=? AND x=? AND y=? LIMIT 2',
                                        (row[2],row[3]-dx,row[4]-dy)).fetchall())
            if len(found)==1: yield consume(row,found[0],'common translation')
        # Bounded candidates; require reciprocal unique best matches. Ties and
        # crowded regions remain add/delete rather than inventing lineage.
        if not all(db.execute('SELECT 1 FROM items WHERE side=? AND active=1 LIMIT 1',(side,)).fetchone() for side in (0,1)):
            return
        for oid,side,raw in db.execute('SELECT id,side,raw FROM items WHERE active=1'):
            r=json.loads(raw);box=bounds(r)
            if box:
                db.execute('INSERT INTO boxes VALUES (?,?,?,?,?)',(oid,box[0],box[2],box[1],box[3]))
                for i,j in ((0,1),(0,3),(2,1),(2,3)):
                    db.execute('INSERT INTO anchors VALUES (?,?,?)',(side,encoded([family(r).decode(),i,j,box[i],box[j]]),oid))
        db.execute('CREATE INDEX anchor ON anchors(side,token,id)')
        db.execute('CREATE INDEX via_context ON items(side,active,context,rigid,x,y)')
        # Standard vias persist an origin and overrides, not a footprint. The
        # ordinary shape scorer's 1-DBU extent rejected almost every via move.
        # Compare compatible point objects, preferring identical via geometry,
        # then size/orientation edits. Require reciprocal nearest matches with
        # a 2x distance separation; freeze each pass before consuming anything.
        extent = db.execute('SELECT min(x),max(x),min(y),max(y) FROM items WHERE context IS NOT NULL').fetchone()
        span = max((extent[1]-extent[0]) if extent[0] is not None else 0,
                   (extent[3]-extent[2]) if extent[2] is not None else 0, 1) * 2
        def via_best(row, side, rigid_only):
            oid, key, context, rigid, x, y = row
            if x is None or y is None: return None
            clause = 'i.side=? AND i.active=1 AND i.context=?'
            args = [side, context]
            if rigid_only:
                clause += ' AND i.rigid=?'; args.append(rigid)
            candidates = db.execute('SELECT i.id,i.key,i.context,i.rigid,i.x,i.y FROM items i WHERE '+clause+' LIMIT ?', (*args,LIMIT+1)).fetchall()
            if len(candidates)>LIMIT:
                radius = 1
                while True:
                    candidates = db.execute('SELECT i.id,i.key,i.context,i.rigid,i.x,i.y FROM boxes b '
                        'CROSS JOIN items i ON i.id=b.id WHERE '+clause+
                        ' AND b.x0<=? AND b.x1>=? AND b.y0<=? AND b.y1>=? LIMIT ?',
                        (*args,x+radius,x-radius,y+radius,y-radius,LIMIT+1)).fetchall()
                    if len(candidates)>LIMIT: return None
                    if len(candidates)>=2 or radius>=span: break
                    if candidates and radius>=2*math.hypot(candidates[0][4]-x,candidates[0][5]-y): break
                    radius *= 4
            ranked = sorted((math.hypot(r[4]-x,r[5]-y),r) for r in candidates if r[4] is not None and r[5] is not None)
            if not ranked or (len(ranked)>1 and 2*ranked[0][0]>=ranked[1][0]): return None
            return ranked[0][1]
        for rigid_only in (True, False):
            db.execute('CREATE TEMP TABLE via_choices(new INT PRIMARY KEY,old INT UNIQUE)')
            for row in db.execute('SELECT id,key,context,rigid,x,y FROM items WHERE side=1 AND active=1 AND context IS NOT NULL ORDER BY key'):
                chosen = via_best(row,0,rigid_only)
                reverse = via_best(chosen,1,rigid_only) if chosen else None
                if reverse and reverse[0]==row[0]:
                    db.execute('INSERT INTO via_choices VALUES (?,?)',(row[0],chosen[0]))
            for new,old in db.execute('SELECT new,old FROM via_choices ORDER BY new'):
                nk=db.execute('SELECT key FROM items WHERE id=?',(new,)).fetchone()[0]
                ok=db.execute('SELECT key FROM items WHERE id=?',(old,)).fetchone()[0]
                yield consume((new,nk),(old,ok),'via translation' if rigid_only else 'via size/orientation')
            db.execute('DROP TABLE via_choices')
        def best(oid, side, raw):
            r = json.loads(raw); box = bounds(r)
            if not box: return None
            ids = set()
            for i,j in ((0,1),(0,3),(2,1),(2,3)):
                token = encoded([family(r).decode(),i,j,box[i],box[j]])
                found = list(db.execute('SELECT a.id FROM anchors a JOIN items i ON a.id=i.id WHERE a.side=? AND token=? AND i.active=1 LIMIT ?', (side,token,LIMIT+1)))
                if len(found)<=LIMIT: ids.update(x[0] for x in found)
            margin = max(box[2]-box[0], box[3]-box[1], r.get('width') or 1, 1)*2
            near = list(db.execute('SELECT b.id FROM boxes b CROSS JOIN items i ON i.id=b.id WHERE side=? AND active=1 AND family=? '
                'AND x0<=? AND x1>=? AND y0<=? AND y1>=? LIMIT ?',
                (side,family(r),box[2]+margin,box[0]-margin,box[3]+margin,box[1]-margin,LIMIT+1)))
            if len(near)<=LIMIT: ids.update(x[0] for x in near)
            if len(ids)>LIMIT*5: return None
            ranked=[]
            for candidate in ids:
                key,other = db.execute('SELECT key,raw FROM items WHERE id=?',(candidate,)).fetchone()
                value=score(r,json.loads(other))
                if value >= .75: ranked.append((value,candidate,key,other))
            ranked.sort(reverse=True)
            if not ranked or (len(ranked)>1 and ranked[0][0]-ranked[1][0]<.035): return None
            return ranked[0]
        # Freeze choices before consuming them, so deleting a candidate cannot
        # manufacture confidence in the next otherwise-ambiguous pair.
        db.execute('CREATE TABLE choices(new INT PRIMARY KEY,old INT UNIQUE)')
        for oid,key,raw in db.execute('SELECT id,key,raw FROM items WHERE side=1 AND active=1 ORDER BY key'):
            chosen=best(oid,0,raw)
            if chosen:
                reverse=best(chosen[1],1,chosen[3])
                if reverse and reverse[1]==oid:
                    db.execute('INSERT INTO choices VALUES (?,?)',(oid,chosen[1]))
        for new,old in db.execute('SELECT new,old FROM choices ORDER BY new'):
            nk=db.execute('SELECT key FROM items WHERE id=?',(new,)).fetchone()[0]
            ok=db.execute('SELECT key FROM items WHERE id=?',(old,)).fetchone()[0]
            yield consume((new,nk),(old,ok),'geometry similarity')
    finally:
        db.close()
