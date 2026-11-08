"""Crash-recoverable merge decisions, with optimistic generations and exact undo.

Only HEAD makes an event authoritative. An event written before a crash but not
referenced by HEAD is an orphan. Saved inputs and events are integrity checked.
Native database handles and temporary cells never enter this journal.
"""
from __future__ import annotations
import contextlib
import copy
import os
from pathlib import Path

from layoutdiff.data.core import digest, diff, apply_diff, validate
from layoutdiff.data.history import atomic_json, read_json
from layoutdiff.data.merge import MergePlan
from layoutdiff.data.storage import from_snapshot, Snapshot


class MergeSession:
    @classmethod
    def create(cls, path, base, target, incoming, *, metadata=None):
        path = Path(path)
        path.mkdir(parents=True, exist_ok=False)
        (path / 'events').mkdir()
        plan = MergePlan(base, target, incoming)
        for name, snapshot in plan.inputs.items():
            store = from_snapshot(snapshot, path / name)
            store.close()
        manifest = {'schema': 'layoutdiff-merge/1', 'inputs': {s: digest(v) for s, v in plan.inputs.items()},
                    'metadata': metadata or {}, 'analysis': digest(plan.units)}
        atomic_json(path / 'session.json', {**manifest, 'id': digest(manifest)})
        atomic_json(path / 'HEAD', None)
        return cls(path)

    def __init__(self, path):
        self.path = Path(path)
        manifest = read_json(self.path / 'session.json')
        if manifest.pop('id') != digest(manifest) or manifest['schema'] != 'layoutdiff-merge/1':
            raise ValueError('Corrupt merge manifest')
        self.metadata = manifest['metadata']
        inputs = []
        for side in ('base', 'target', 'incoming'):
            store = Snapshot(self.path / side)
            try:
                snapshot = store.materialize()
            finally:
                store.close()
            if digest(snapshot) != manifest['inputs'][side]:
                raise ValueError('Merge input changed: ' + side)
            inputs.append(snapshot)
        self.plan = MergePlan(*inputs)
        if digest(self.plan.units) != manifest['analysis']:
            raise ValueError('Merge analysis version changed; start a new session')
        self.initial = self.plan.result()
        self.snapshot = self.initial
        self.state = {'choices': {}, 'resolved': {}, 'undo': [], 'redo': []}
        self.head = read_json(self.path / 'HEAD')
        self.generation = 0
        chain, seen = [], set()
        current = self.head
        while current:
            if current in seen:
                raise ValueError('Cyclic merge journal')
            seen.add(current)
            event = self.event(current)
            chain.append(event)
            current = event['parent']
        for event in reversed(chain):
            if event['before'] != self.state:
                raise ValueError('Merge journal state mismatch')
            self.snapshot = apply_diff(self.snapshot, event['patch'])
            self.state = event['after']
            self.generation += 1

    def event(self, ident):
        if not isinstance(ident, str) or len(ident) != 64 or any(c not in '0123456789abcdef' for c in ident):
            raise ValueError('Invalid merge event ID')
        event = read_json(self.path / 'events' / (ident + '.json'))
        if digest(event) != ident:
            raise ValueError('Corrupt merge event')
        return event

    def check(self, generation):
        if generation != self.generation or read_json(self.path / 'HEAD') != self.head:
            raise ValueError('Stale merge request; refresh the session')

    @contextlib.contextmanager
    def lock(self, generation):
        lock = self.path / 'LOCK'
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise ValueError('Merge session is busy; inspect its lock if the worker exited') from None
        try:
            os.write(fd, str(os.getpid()).encode('ascii'))
            self.check(generation)
            yield
        finally:
            os.close(fd)
            lock.unlink()

    def _append(self, action, snapshot, state):
        validate(snapshot)
        event = {'parent': self.head, 'action': action, 'before': self.state,
                 'after': state, 'patch': diff(self.snapshot, snapshot)}
        ident = digest(event)
        atomic_json(self.path / 'events' / (ident + '.json'), event)
        atomic_json(self.path / 'HEAD', ident)
        self.head, self.snapshot, self.state = ident, snapshot, state
        self.generation += 1
        return ident

    def unresolved(self):
        return self.plan.unresolved(self.state['resolved'])

    def preview(self, unit_id, choice, generation):
        return self.preview_many({unit_id: choice}, generation)

    def preview_many(self, decisions, generation):
        self.check(generation)
        if not isinstance(decisions, dict) or set(decisions) - self.plan.units.keys():
            raise ValueError('Unknown merge decision')
        for ident, choice in decisions.items():
            self.plan.candidate(ident, choice)
        choices = {**self.state['choices'], **decisions}
        before = self.plan.result(self.state['choices'])
        after = self.plan.result(choices)
        # Retain custom edits outside the selected decision. Overlapping edits
        # require explicit manual reconciliation, never guessed correspondence.
        result = dict(self.snapshot['objects'])
        for op in diff(before, after)['operations']:
            if result.get(op['key']) != op['before']:
                raise ValueError('Choice overlaps custom edits; undo that edit or resolve this conflict in the editor')
            if op['after'] is None:
                result.pop(op['key'], None)
            else:
                result[op['key']] = op['after']
        candidate = {'schema': self.snapshot['schema'], 'objects': result}
        validate(candidate)
        return candidate

    def decide(self, unit_id, choice, generation, *, validated_digest=None):
        with self.lock(generation):
            snapshot = self.preview(unit_id, choice, generation)
            if validated_digest is not None and digest(snapshot) != validated_digest:
                raise ValueError('Preview changed before acceptance')
            state = copy.deepcopy(self.state)
            state['choices'][unit_id] = choice
            state['resolved'][unit_id] = choice
            return self._decision({'unit': unit_id, 'choice': choice}, snapshot, state)

    def decide_many(self, decisions, generation, *, validated_digest=None):
        """Accept a batch as one generation/undo step, preserving custom edits."""
        with self.lock(generation):
            snapshot = self.preview_many(decisions, generation)
            if validated_digest is not None and digest(snapshot) != validated_digest:
                raise ValueError('Preview changed before acceptance')
            state = copy.deepcopy(self.state)
            state['choices'].update(decisions)
            state['resolved'].update(decisions)
            return self._decision({'decisions': decisions}, snapshot, state)

    def _decision(self, action, snapshot, state):
        # Undo entries reference compact, immutable before/after state and patch.
        data = {'before': {k: v for k, v in self.state.items() if k not in {'undo', 'redo'}},
                'after': {k: v for k, v in state.items() if k not in {'undo', 'redo'}},
                'patch': diff(self.snapshot, snapshot)}
        ident = digest(data)
        atomic_json(self.path / 'events' / (ident + '.json'), data)
        state['undo'].append(ident)
        state['redo'] = []
        return self._append(action, snapshot, state)

    def accept_edits(self, snapshot, unit_id, generation, *, omissions=None):
        with self.lock(generation):
            if unit_id not in self.plan.units:
                raise ValueError('Select the decision resolved by these edits')
            validate(snapshot)
            state = copy.deepcopy(self.state)
            # Native editing can affect any prior decision. Reopen explicit
            # resolutions conservatively; the geometry stays visible for review.
            state['resolved'] = {unit_id: 'manual'}
            if omissions:
                state['omissions'] = omissions
            return self._decision({'unit': unit_id, 'choice': 'manual'}, snapshot, state)

    def undo(self, generation, *, redo=False):
        with self.lock(generation):
            source, dest = ('redo', 'undo') if redo else ('undo', 'redo')
            state = copy.deepcopy(self.state)
            if not state[source]:
                raise ValueError('No decision to ' + source)
            ident = state[source].pop()
            data = self.event(ident)
            snapshot = apply_diff(self.snapshot, data['patch'], reverse=not redo)
            state = {**copy.deepcopy(data['after' if redo else 'before']),
                     'undo': state['undo'], 'redo': state['redo']}
            state[dest].append(ident)
            return self._append({'action': source, 'decision': ident}, snapshot, state)
