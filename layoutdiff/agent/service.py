"""Remote dispatcher. Requests/results live beside the runtime, never in Git."""
from collections import OrderedDict
from pathlib import Path
import os
import re
import uuid

from layoutdiff.agent import OPERATIONS, PROTOCOL
from layoutdiff.agent.analysis import change, matches, unit_summary
from layoutdiff.agent import repository as repos
from layoutdiff.comparison.changeindex import ChangeIndex
from layoutdiff.comparison.merge_index import MergeIndex
from layoutdiff.data.core import digest, encoded
from layoutdiff.data.history import atomic_json, read_json
from layoutdiff.data.merge_session import MergeSession
from layoutdiff.data.storage import from_snapshot, strict_json
from layoutdiff.git.active_merge import active_merge, cell_paths, index_entries, parsed_entries
from layoutdiff.git.commit import git
from layoutdiff.git.store import check_identity

ID = re.compile(r'[A-Za-z0-9_-]{1,64}\Z')
PAGE_BYTES = 2048  # ASCII pages remain bounded after SKILL/MCP escaping.
QUERY_KEYS = {'offset', 'limit', 'category', 'status', 'layer', 'region', 'records', 'unit_id'}


def identifier(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError('Invalid request/analysis identifier')
    return value


def keys(payload, allowed):
    if not isinstance(payload, dict) or set(payload) - allowed:
        raise ValueError('Unknown operation arguments: ' + ', '.join(sorted(set(payload) - allowed)))


def page_args(payload):
    offset, limit = payload.get('offset', 0), payload.get('limit', 10)
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError('offset must be nonnegative and limit between 1 and 50')
    region = payload.get('region')
    if region is not None and (not isinstance(region, list) or len(region) != 4 or
            any(type(v) not in (int, float) for v in region) or region[0] > region[2] or region[1] > region[3]):
        raise ValueError('region must be [x0,y0,x1,y1] in snapshot DBU')
    return offset, limit


class AgentService:
    def __init__(self, root, *, adapter=None, source_state=None, save_source=None, native_validate=None,
                 publish_capabilities=True):
        self.root = Path(root).resolve()
        self.requests = self.root / 'requests'
        self.requests.mkdir(parents=True, exist_ok=True)
        self.adapter, self.source_state = adapter, source_state
        self.save_source, self.native_validate = save_source, native_validate
        self.diffs = OrderedDict()
        self.plans = OrderedDict()
        self.capabilities = {
            'protocol': PROTOCOL, 'operations': list(OPERATIONS), 'runtime_root': str(self.root),
            'native_capture': adapter is not None, 'native_validation': native_validate is not None,
            'page_bytes': PAGE_BYTES, 'worker_pid': os.getpid(),
            'repository_paths': 'absolute paths on the Virtuoso host',
            'index_policy': 'writes leave Git index, commits and branch unchanged'}
        if publish_capabilities:
            atomic_json(self.root / 'capabilities.json', self.capabilities)

    def close(self):
        for index, _ in self.diffs.values():
            index.close()
        self.diffs.clear()
        for _, index in self.plans.values():
            if index is not None:
                index.close()
        self.plans.clear()

    def recover(self):
        """Call only after acquiring the existing runtime's exclusive worker lock."""
        for running in self.requests.glob('*.running'):
            ident = running.stem
            if not (self.requests / (ident + '.done')).exists():
                self.finish(ident, {'status': 'unknown', 'request_id': ident,
                    'error': 'Previous worker ended during this request. Inspect repository state and recovery journals before issuing a new write.'})

    def finish(self, ident, result):
        raw = encoded({'protocol': PROTOCOL, **result}).decode('ascii')
        atomic_json(self.requests / (ident + '.result.json'), {'protocol': PROTOCOL, **result})
        pages = [raw[i:i + PAGE_BYTES] for i in range(0, len(raw), PAGE_BYTES)]
        for i, chunk in enumerate(pages):
            (self.requests / f'{ident}.page.{i}').write_text(chunk, encoding='ascii')
        temp = self.requests / (ident + '.done.tmp')
        temp.write_text(str(len(pages)), encoding='ascii')
        os.replace(temp, self.requests / (ident + '.done'))

    def poll(self, *, limit=1, request_id=None):
        processed = 0
        requests = ([self.requests / (identifier(request_id) + '.request')] if request_id else
                    sorted(self.requests.glob('*.request')))
        for request in requests:
            ident = identifier(request.stem)
            if (self.requests / (ident + '.done')).exists():
                continue
            try:
                fd = os.open(self.requests / (ident + '.running'), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                continue
            os.write(fd, str(os.getpid()).encode()); os.close(fd)
            try:
                if request.stat().st_size > 60000:
                    raise ValueError('Request exceeds 60000 bytes')
                operation, raw = request.read_text(encoding='utf-8').split('\n', 1)
                result = self.dispatch(operation, strict_json(raw))
                response = {'status': 'complete', 'request_id': ident, 'result': result}
            except Exception as exc:
                response = {'status': 'error', 'request_id': ident,
                            'error': str(exc), 'error_type': type(exc).__name__}
            self.finish(ident, response)
            processed += 1
            if processed >= limit:
                break
        return processed

    def dispatch(self, operation, payload):
        if operation not in OPERATIONS or not isinstance(payload, dict):
            raise ValueError('Unknown operation or invalid payload')
        return getattr(self, operation)(payload)

    def _identity(self, payload):
        value = payload.get('cellview')
        if not isinstance(value, list):
            raise ValueError('cellview must be [library,cell,view]')
        check_identity(value)
        return value

    def _capture(self, identity, save=False):
        if self.adapter is None:
            raise ValueError('Native capture requires the connected Virtuoso worker')
        if save:
            if self.save_source is None:
                raise ValueError('Native save is unavailable')
            self.save_source(identity)
        before = self.source_state(identity) if self.source_state else None
        store = self.adapter.capture_store(*identity, temporary=True)
        try:
            value = store.materialize()
        finally:
            store.dispose()
        after = self.source_state(identity) if self.source_state else None
        if before != after:
            raise ValueError('Source layout changed during capture; capture again')
        warnings = []
        for r in value['objects'].values():
            if r['kind'] == 'dependency' and (r.get('dirty') or r.get('fingerprint', {}).get('status') != 'ok'):
                warnings.append({'master': r.get('name'), 'dirty': r.get('dirty'), 'fingerprint': r.get('fingerprint')})
        return value, {'source_state': after, 'dependency_warnings': warnings}

    def _read(self, repo, identity, source):
        if source == 'worktree':
            value, audit = repos.worktree_snapshot(repo, identity)
            return value, {'source': source, 'omissions': audit}
        if source == 'live':
            value, meta = self._capture(identity)
            return value, {'source': source, **meta}
        sha = repos.commit_id(repo, source)
        value, audit = repos.revision_snapshot(repo, identity, sha)
        return value, {'source': source, 'commit': sha, 'omissions': audit}

    def _diff(self, before, after, metadata):
        ident = uuid.uuid4().hex
        folder = self.root / 'diff-inputs' / ident
        a, b = from_snapshot(before, folder / 'before'), from_snapshot(after, folder / 'after')
        try:
            index = ChangeIndex(a, b, backend='auto')
        finally:
            a.close(); b.close()
        metadata = {**metadata, 'analysis_id': ident, 'digests': {'before': digest(before), 'after': digest(after)},
                    'inputs': str(folder), 'exact_operations': str(index.operations_path)}
        self.diffs[ident] = (index, metadata)
        while len(self.diffs) > 4:
            _, (old, _) = self.diffs.popitem(last=False)
            old.close()
        return ident

    def diff(self, p):
        keys(p, QUERY_KEYS | {'repository', 'cellview', 'left', 'right', 'analysis_id'})
        offset, limit = page_args(p)
        ident = p.get('analysis_id')
        if ident is None:
            repo, identity = repos.repository(p.get('repository', '')), self._identity(p)
            guard = repos.guard(repo, identity)
            before, left = self._read(repo, identity, p.get('left', 'HEAD'))
            after, right = self._read(repo, identity, p.get('right', 'worktree'))
            repos.check_guard(repo, identity, guard)
            ident = self._diff(before, after, {'repository': str(repo), 'cellview': identity,
                'left': left, 'right': right, 'worktree_digest': digest(guard)})
        identifier(ident)
        if ident not in self.diffs:
            raise ValueError('Analysis expired; request a new diff using its pinned inputs')
        index, metadata = self.diffs[ident]
        self.diffs.move_to_end(ident)
        items, total = [], 0
        for label, op in index.records(category=p.get('category'), status=p.get('status')):
            if not matches(op, layer=p.get('layer'), region=p.get('region')):
                continue
            if offset <= total < offset + limit:
                items.append({'category': label, **change(op, records=p.get('records', False))})
            total += 1
        return {**metadata, 'raw_operations': index.raw_operations, 'counts': dict(index.totals),
                'categories': index.rows, 'items': items, 'total': total, 'offset': offset,
                'next_offset': offset + len(items) if offset + len(items) < total else None}

    def _session(self, repo, identity, refs, *, active=None):
        guard = repos.guard(repo, identity)
        metadata = {'repository': str(repo), 'identity': identity, 'refs': refs, 'guard': guard, 'active_merge': active}
        ident = digest(metadata)
        path = self.root / 'plans' / ident
        if path.exists():
            session, _ = self._load_session(ident)
            repos.check_guard(repo, identity, guard)
            return ident, session
        values, audits = [], []
        for sha in refs.values():
            value, audit = repos.revision_snapshot(repo, identity, sha)
            values.append(value)
            if audit:
                audits.append(audit)
        metadata['omissions'] = audits
        session = MergeSession.create(path, *values, metadata=metadata)
        self.plans[ident] = (session, None)
        session, _ = self._load_session(ident)
        repos.check_guard(repo, identity, guard)
        return ident, session

    def _load_session(self, ident, *, indexed=False):
        identifier(ident)
        path = self.root / 'plans' / ident
        session, index = self.plans.pop(ident, (None, None))
        if session is None or read_json(path / 'HEAD') != session.head:
            if index is not None:
                index.close()
            session, index = MergeSession(path), None
        if indexed and index is None:
            index = MergeIndex(session.plan)
        self.plans[ident] = (session, index)
        while len(self.plans) > 4:
            _, (_, old) = self.plans.popitem(last=False)
            if old is not None:
                old.close()
        return session, index

    def _plan_page(self, ident, p):
        offset, limit = page_args(p)
        session, index = self._load_session(ident, indexed=True)
        unit_id = p.get('unit_id')
        ids = [unit_id] if unit_id else index.page(p.get('category'), offset, limit)
        items = []
        for key in ids:
            if key not in session.plan.units:
                raise ValueError('Unknown merge unit')
            row = unit_summary(session.plan, key, session.state['resolved'], details=bool(unit_id))
            row['spatial_interactions'] = {'units': index.interactions(key), 'limit': 8,
                                         'meaning': 'same-layer cross-branch bounding-box overlap; not DRC/LVS'}
            if unit_id:
                row['context'] = {}
                for side in ('base', 'target', 'incoming'):
                    selected, truncated = index.selection(side, key)
                    row['context'][side] = {'keys': selected[:50], 'total_selected': len(selected),
                                           'truncated': truncated or len(selected) > 50}
            items.append(row)
        total = sum(not p.get('category') or u['category'] == p['category'] for u in session.plan.units.values())
        return {'plan_id': ident, 'generation': session.generation, 'repository': session.metadata['repository'],
            'cellview': session.metadata['identity'], 'refs': session.metadata['refs'],
            'digests': {s: digest(v) for s, v in session.plan.inputs.items()},
            'counts': session.plan.counts(session.state['resolved']), 'unresolved': len(session.unresolved()),
            'warnings': session.plan.warnings, 'omissions': session.metadata['omissions'],
            'units': items, 'total': total, 'offset': offset,
            'next_offset': offset + len(items) if not unit_id and offset + len(items) < total else None}

    def merge_plan(self, p):
        keys(p, QUERY_KEYS | {'repository', 'cellview', 'base', 'ours', 'theirs', 'plan_id'})
        if p.get('plan_id'):
            ident = identifier(p['plan_id'])
            session, _ = self._load_session(ident)
        else:
            repo, identity = repos.repository(p.get('repository', '')), self._identity(p)
            ours = repos.commit_id(repo, p.get('ours', 'HEAD'))
            theirs = repos.commit_id(repo, p.get('theirs'))
            if not ours or not theirs:
                raise ValueError('Merge planning requires two existing commits')
            if p.get('base'):
                base = repos.commit_id(repo, p['base'])
            else:
                bases = git(repo, 'merge-base', '--all', ours, theirs, check=False).stdout.decode().split()
                if len(bases) != 1:
                    raise ValueError('Merge planning requires one common ancestor')
                base = bases[0]
            ident, session = self._session(repo, identity, {'base': base, 'target': ours, 'incoming': theirs})
        return self._plan_page(ident, p)

    def merge_explain(self, p):
        keys(p, QUERY_KEYS | {'repository', 'cellview'})
        offset, limit = page_args(p)
        repo = repos.repository(p.get('repository', ''))
        info = active_merge(repo)
        if info is None:
            return {'repository': str(repo), 'active_merge': False, 'cells': [],
                    'explanation': 'No MERGE_HEAD exists. This operation explains ordinary two-parent Git merges.'}
        all_entries = list(parsed_entries(git(repo, 'ls-files', '--unmerged', '-z').stdout))
        ordinary = [path for path in info['conflicts'] if not any(path in cell_paths(c) for c in info['conflicted'])]
        result = {'repository': str(repo), 'active_merge': True, 'supported': not bool(info['reason']),
                  'reason': info['reason'], 'head': info['head'], 'incoming': info['parents'], 'base': info['base'],
                  'ordinary_conflicts': ordinary[:50], 'ordinary_conflict_count': len(ordinary),
                  'resolved_cells': [c for c in info['cells'] if c not in info['conflicted']], 'cells': []}
        if info['reason']:
            return result
        selected = [self._identity(p)] if p.get('cellview') else info['conflicted'][offset:offset + limit]
        for identity in selected:
            if identity not in info['conflicted']:
                result['cells'].append({'cellview': identity, 'status': 'not_unmerged',
                    'explanation': 'This cell has no remaining index conflict; its staged resolution is preserved.'})
                continue
            refs = {'base': info['base'], 'target': info['head'], 'incoming': info['parents'][0]}
            ident, session = self._session(repo, identity, refs, active=refs)
            query = p if p.get('cellview') else {'limit': 3}
            row = self._plan_page(ident, query)
            names = cell_paths(identity)
            row['index_conflicts'] = [{'path': path, 'mode': mode, 'blob': oid, 'stage': stage}
                                      for path, mode, oid, stage in all_entries if path in names]
            row['explanation'] = ('Git reported serialized snapshot conflicts. Layout analysis found '
                                  f'{row["unresolved"]} decisions requiring resolution.')
            result['cells'].append(row)
        if active_merge(repo) != info or git(repo, 'ls-files', '--unmerged', '-z').stdout != b''.join(
                f'{mode} {oid} {stage}\t{path}\0'.encode() for path, mode, oid, stage in all_entries):
            raise ValueError('Active merge changed during analysis; explain it again')
        result['total_cells'] = len(info['conflicted'])
        result['next_offset'] = offset + len(selected) if not p.get('cellview') and offset + len(selected) < len(info['conflicted']) else None
        return result

    def merge_apply(self, p):
        keys(p, {'plan_id', 'generation', 'decisions', 'mode', 'native_validation'})
        ident = identifier(p.get('plan_id'))
        session, _ = self._load_session(ident)
        generation = p.get('generation')
        if type(generation) is not int:
            raise ValueError('generation is required')
        decisions, mode = p.get('decisions', {}), p.get('mode', 'preview')
        if mode not in {'preview', 'accept', 'write'}:
            raise ValueError('mode must be preview, accept or write')
        if type(p.get('native_validation', True)) is not bool:
            raise ValueError('native_validation must be a boolean')
        repo, identity = repos.repository(session.metadata['repository']), session.metadata['identity']
        repos.check_guard(repo, identity, session.metadata['guard'])
        candidate = session.preview_many(decisions, generation)
        unresolved = session.plan.unresolved({**session.state['resolved'], **decisions})
        result = {'plan_id': ident, 'generation': generation, 'mode': mode,
                  'snapshot_digest': digest(candidate), 'unresolved': len(unresolved), 'validation': 'logical'}
        if mode == 'write':
            if unresolved:
                raise ValueError('Resolve all merge decisions before writing')
            if session.metadata['omissions']:
                raise ValueError('Incomplete snapshots require the graphical omission-preservation workflow')
            if p.get('native_validation', True):
                if self.native_validate is None:
                    raise ValueError('Native validation requires Virtuoso; explicitly set native_validation=false for logical-only output')
                result['native'] = self.native_validate(candidate)
                result['validation'] = 'native_readback'
            # Keep the decision journal locked through validation of the final state and publication.
            with session.lock(generation):
                if digest(session.preview_many(decisions, generation)) != result['snapshot_digest']:
                    raise ValueError('Merge preview changed')
                result.update(repos.write_snapshot(repo, identity, candidate, session.metadata['guard'],
                    self.root / 'writes' / uuid.uuid4().hex))
                atomic_json(session.path / 'written.json', result)
        elif mode == 'accept':
            session.decide_many(decisions, generation, validated_digest=result['snapshot_digest'])
            result['generation'] = session.generation
        return result

    def export(self, p):
        keys(p, {'repository', 'cellview', 'save', 'expected_worktree'})
        if type(p.get('save', False)) is not bool:
            raise ValueError('save must be a boolean')
        repo, identity = repos.repository(p.get('repository', '')), self._identity(p)
        guard = repos.guard(repo, identity)
        if any(stage for _, _, _, stage in parsed_entries(index_entries(repo, cell_paths(identity)))):
            raise ValueError('This layout has an active index conflict; use merge_explain')
        dirty = git(repo, 'status', '--porcelain', '--untracked-files=all', '--', *repos.paths(identity)).stdout
        if dirty and p.get('expected_worktree') != digest(guard):
            raise ValueError('Managed paths have local changes; inspect layout_diff and supply its worktree_digest')
        before, audit = repos.worktree_snapshot(repo, identity)
        if audit:
            raise ValueError('An omission audit requires the graphical preservation workflow')
        value, native = self._capture(identity, p.get('save', False))
        ident = self._diff(before, value, {'repository': str(repo), 'cellview': identity})
        result = repos.write_snapshot(repo, identity, value, guard, self.root / 'writes' / uuid.uuid4().hex)
        return {**result, **native, 'analysis_id': ident, 'counts': dict(self.diffs[ident][0].totals),
                'worktree_digest': digest(repos.guard(repo, identity))}
