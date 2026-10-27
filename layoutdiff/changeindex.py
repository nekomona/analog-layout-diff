"""Disposable, bounded-memory category index. Git snapshots remain authoritative."""
from collections import Counter
from pathlib import Path
import tempfile
from .categories import CategoryDiff, operation_category, status, operation_text, operation_excerpt, PAGE_SIZE
from .core import encoded
from .storage import spool, strict_json
from . import streaming


class ChangeIndex:
    overview = CategoryDiff.overview

    def __init__(self, before, after, *, backend="python"):
        self.temp = tempfile.TemporaryDirectory(prefix="ald_changes_")
        self.root = Path(self.temp.name)
        self.db = None
        try:
            self.operations_path = self.root / "operations.jsonl"
            self.backend = streaming.merge(before.wire(), after.wire(), self.operations_path,
                backend=backend, count=max(before.count, after.count))
            self._build()
        except BaseException:
            self.close()
            raise

    def operations(self):
        with self.operations_path.open("rb") as stream:
            for line in stream:
                yield strict_json(line)

    def _build(self):
        self.db = spool(self.root / "categories.sqlite")
        db = self.db
        db.execute("CREATE TABLE changes(key TEXT PRIMARY KEY, category TEXT, status TEXT, op BLOB) WITHOUT ROWID")
        db.execute("CREATE INDEX pending ON changes(status,key)")
        self.raw_operations, self.kinds = 0, Counter()
        for op in self.operations():
            self.raw_operations += 1
            record = op["after"] or op["before"]
            self.kinds[record["kind"]] += 1
            db.execute("INSERT INTO changes VALUES (?,?,?,?)", (op["key"], self.label(op), status(op), encoded(op)))
        from .matching import pairs
        def records(status, field):
            for key,raw in db.execute('SELECT key,op FROM changes WHERE status=? ORDER BY key', (status,)):
                yield key,strict_json(raw)[field]
        for key,old_key,evidence in pairs(records('deleted','before'), records('added','after')):
            op = strict_json(db.execute('SELECT op FROM changes WHERE key=?',(key,)).fetchone()[0])
            old = strict_json(db.execute('SELECT op FROM changes WHERE key=?',(old_key,)).fetchone()[0])
            op.update(before=old['before'], before_key=old_key, match=evidence)
            db.execute('DELETE FROM changes WHERE key=?',(old_key,))
            db.execute('UPDATE changes SET op=?,status=?,category=? WHERE key=?',(encoded(op),status(op),self.label(op),key))
        db.execute("CREATE INDEX pages ON changes(category,key)")
        db.commit()
        grouped = {}
        self.totals = Counter(added=0, modified=0, deleted=0, modified_net=0)
        for label, kind, n in db.execute("SELECT category,status,count(*) FROM changes GROUP BY category,status"):
            grouped.setdefault(label, Counter())[kind] = n
            self.totals[kind] += n
        self.rows = [[label, c["added"], c["modified"], c["deleted"], c["modified_net"]] for label, c in sorted(grouped.items())]

    @staticmethod
    def label(op):
        return operation_category(op)

    def page(self, index, page):
        label, *counts = self.rows[index]
        n = sum(counts)
        pages = max(1, (n + PAGE_SIZE - 1) // PAGE_SIZE)
        if page < 0 or page >= pages:
            raise ValueError("Category page is out of range")
        start = page * PAGE_SIZE
        text = f"{label}\nChanges {start + 1}-{min(start + PAGE_SIZE, n)} of {n} | Page {page + 1}/{pages}\n"
        for (raw,) in self.db.execute("SELECT op FROM changes WHERE category=? ORDER BY key LIMIT ? OFFSET ?", (label, PAGE_SIZE, start)):
            text += operation_excerpt(strict_json(raw))
        return {"title": label, "text": text, "page": page, "pages": pages, "count": n}

    def full(self, index=None):
        yield self.overview() + "\n"
        for label, *_ in self.rows if index is None else [self.rows[index]]:
            yield "\n### " + label + "\n"
            for (raw,) in self.db.execute("SELECT op FROM changes WHERE category=? ORDER BY key", (label,)):
                yield operation_text(strict_json(raw))

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None
        self.temp.cleanup()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
