"""Read-only data for the native commit/file browser."""
from collections import Counter, OrderedDict
import html
from .core import empty_snapshot, diff
from .gitcommit import git
from .gitstore import GitSnapshots
from .gittools import textconv
from .categories import CategoryDiff


def field_text(text, limit=7600):
    data = text.encode("utf-8")
    if len(data) <= limit:
        return text
    return data[:limit].decode("utf-8", errors="ignore") + "\n[Shortened. Use Open full diff for all content.]"


def counts(commit):
    result = Counter(added=0, modified=0, deleted=0)
    kinds = Counter()
    for op in commit["operations"]:
        result["added" if op["before"] is None else "deleted" if op["after"] is None else "modified"] += 1
        kinds[(op["after"] or op["before"])["kind"]] += 1
    return dict(result), dict(sorted(kinds.items()))


def diff_html(text):
    """Escape every byte of layout/Git text: hypertext supports SKILL links."""
    lines = []
    for line in field_text(text).splitlines():
        color, background = "#263238", "#ffffff"
        if line.startswith(("+++", "---", "@@", "diff ")):
            color, background = "#245b88", "#edf3f8"
        elif line.startswith("+"):
            color, background = "#17613b", "#e5f4e9"
        elif line.startswith("-"):
            color, background = "#9d2525", "#fdeaea"
        lines.append(f'<span style="color:{color};background-color:{background}">{html.escape(line)}</span>')
    return '<a name="aldTop"></a><pre style="font-family:monospace;font-size:11px">' + "\n".join(lines) + "</pre>"


class HistoryBrowser:
    def __init__(self, history, identity, repo=None):
        self.history, self.identity, self.repo = history, identity, repo
        self.metadata = {}
        self.category_cache = OrderedDict()
        self.count_cache = {}
        self.prefix = None  # Always show repository-relative affected paths.
        self.store = GitSnapshots(repo, identity) if repo else None
        if self.store:
            self.commits = []
            for sha in self.store.revisions():
                meta = self.store.metadata(sha)
                self.metadata[sha] = meta
                self.commits.append({"id": sha, "parent": next(iter(meta["parents"]), None),
                                     "message": meta["message"]})
        else:
            self.commits = list(reversed(history.chain())) if history.path.exists() else []
            if self.commits:
                history.replay()
        self.by_id = {c["id"]: c for c in self.commits}

    def pair(self, commit_id):
        commit = self.by_id[commit_id]
        if self.store:
            return self.store.pair(commit_id)
        before = self.history.replay(commit["parent"]) if commit["parent"] else empty_snapshot()
        return before, self.history.replay(commit_id)

    def rows(self, *, lazy=False):
        rows = []
        for commit in self.commits:
            meta = self.metadata.get(commit["id"], {})
            stat = self.count_cache.get(commit["id"])
            if stat is None and not lazy:
                stat = self.categories(commit["id"]).totals
            values = [stat[k] for k in ("added", "modified", "deleted", "modified_net")] if stat is not None else ["..."] * 4
            rows.append([meta.get("sha", commit["id"])[:10], commit["message"].replace("\n", " ")[:250],
                         meta.get("author", "Local history"), meta.get("date", "Not recorded").replace("T", " ")[:19],
                         *values])
        return rows

    def categories(self, commit_id):
        if commit_id not in self.category_cache:
            if self.store:
                from .changeindex import ChangeIndex
                self.category_cache[commit_id] = ChangeIndex(*self.store.pair_stores(commit_id), backend="auto")
            else:
                self.category_cache[commit_id] = CategoryDiff(self.by_id[commit_id]["operations"])
            self.count_cache[commit_id] = dict(self.category_cache[commit_id].totals)
            while len(self.category_cache) > 2:
                _, old = self.category_cache.popitem(last=False)
                if hasattr(old, "close"):
                    old.close()
        self.category_cache.move_to_end(commit_id)
        return self.category_cache[commit_id]

    def close(self):
        for value in self.category_cache.values():
            if hasattr(value, "close"):
                value.close()
        self.category_cache.clear()
        if self.store:
            self.store.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def detail(self, commit_id):
        commit = self.by_id[commit_id]
        meta = self.metadata.get(commit_id, {})
        categories = self.categories(commit_id)
        patch = categories.overview()
        kinds = dict(categories.kinds) if self.store else counts(commit)[1]
        reviewable = self.store.open(commit_id).count > 0 if self.store else bool(self.pair(commit_id)[1]["objects"])
        stat = dict(categories.totals)
        files = []
        if meta:
            # --no-renames keeps each NUL-delimited entry one path, even if users
            # have enabled rename detection globally. Binary counts stay '-'.
            revisions = [*meta["parents"][:1], meta["sha"]]
            statuses = git(self.repo, "diff-tree", "--root", "--no-commit-id", "-r", "--no-renames",
                           "--name-status", "-z", *revisions).stdout.decode("utf-8", errors="replace").split("\0")
            status = dict(zip(statuses[1::2], statuses[::2]))
            nums = git(self.repo, "diff-tree", "--root", "--no-commit-id", "-r", "--no-renames",
                       "--numstat", "-z", *revisions).stdout.decode("utf-8", errors="replace")
            for entry in nums.split("\0"):
                if entry:
                    added, deleted, path = entry.split("\t", 2)
                    files.append({"status": status.get(path, "M"), "path": path, "added": added, "deleted": deleted})
        else:
            files = [{"status": "M", "path": "HEAD", "added": "-", "deleted": "-"},
                     {"status": "A", "path": "commits/" + commit_id + ".json", "added": "-", "deleted": "-"}]
        summary = (f"{commit['message']}\n"
                   f"Layout: {' / '.join(self.identity)}\n"
                   f"{'Git ' + meta['sha'] if meta else 'Local revision ' + commit_id}\n"
                   f"{meta.get('author', 'Author/date not recorded')}  {meta.get('date', '')}\n"
                   + (f"Processing backend: {categories.backend}\n" if self.store else "Legacy local archive (read only)\n") +
                   f"Layout changes: +{stat['added']} added   ~{stat['modified']} modified   -{stat['deleted']} deleted"
                   f"   {stat['modified_net']} modified net"
                   f"    |    {len(files)} affected files")
        return {"id": commit_id, "counts": stat, "kinds": kinds, "summary": summary,
                "patch": patch, "categories": categories.rows, "files": files, "git": meta,
                "reviewable": reviewable}

    def file_patch(self, detail, index):
        item = detail["files"][index]
        if detail["git"]:
            meta = detail["git"]
            if meta["parents"]:
                return git(self.repo, "diff", "--no-ext-diff", "--no-textconv", "--no-renames",
                           meta["parents"][0], meta["sha"], "--", item["path"]).stdout.decode("utf-8", errors="replace")
            return git(self.repo, "show", "--format=", "--no-ext-diff", "--no-textconv", "--no-renames",
                       detail["git"]["sha"], "--", item["path"]).stdout.decode("utf-8", errors="replace")
        if item["path"] == "HEAD":
            commit = self.by_id[detail["id"]]
            return f"--- HEAD\n+++ HEAD\n-{commit['parent'] or '(empty)'}\n+{commit['id']}\n"
        return textconv(self.by_id[detail["id"]])
