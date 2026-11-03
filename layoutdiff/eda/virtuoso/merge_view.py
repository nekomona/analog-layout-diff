"""Disposable native merge views and independently drawn alternative geometry."""
from pathlib import Path
import shutil
import uuid

from layoutdiff.data.core import canonicalize, digest
from layoutdiff.eda.virtuoso.adapter import VirtuosoAdapter, checked
from layoutdiff.eda.virtuoso.sexpr import dumps as sk, loads
from layoutdiff.comparison.review import VISUAL
from layoutdiff.comparison.review_groups import boundary_targets


class MergeView:
    def __init__(self, worker, token, session):
        self.worker, self.token, self.session = worker, token, session
        self.current = None
        self.alternatives = {}
        self.packets = {}
        self.editing = False
        self.index = None

    def display_snapshot(self, snapshot):
        if snapshot['objects']:
            return snapshot
        meta = next(s['objects']['cell:'] for s in self.session.plan.inputs.values() if 'cell:' in s['objects'])
        return canonicalize([meta])  # Empty canvas for a deleted cell, never persisted as its result.

    def build(self, snapshot):
        w = self.worker
        snapshot = self.display_snapshot(snapshot)
        with w.work_area(independent=True) as area:
            lib = w.temporary_library(snapshot['objects']['cell:']['technology'])
            adapter = VirtuosoAdapter(w.client, area['path'], writable_library=lib)
            token = uuid.uuid4().hex
            cell = 'ALD_MERGE_' + token[:16]
            actual = adapter.reconstruct(snapshot, lib, cell, review_token=token,
                                         group_definition_source=self.session.metadata.get('identity'))
            # Helper cells have no editor windows. Hold their leases until their
            # merge workspace releases them, including after the worker stops.
            w.execute(f'ALDMergeHold({sk(self.token)} {sk(area["token"])})')
            return {'library': lib, 'cell': cell, 'token': token, 'lease': area['token'],
                    'actual': actual, 'digest': digest(snapshot), 'warnings': adapter.last_dependency_warnings}

    def release(self, native):
        if native:
            self.worker.execute(f'ALDMergeRelease({sk(self.token)} {sk(native["lease"])})')

    def show(self, snapshot):
        native = self.build(snapshot)
        old = self.current
        try:
            self.worker.execute(f'ALDMergeOpen({sk(self.token)} {sk(native["library"])} {sk(native["cell"])} '
                                f'{self.session.generation} "Preparing merge decisions...")')
        except BaseException:
            self.release(native)
            raise
        self.current = native
        self.release(old)
        self.editing = False

    def install_styles(self):
        from layoutdiff.ui.worker import display_resource
        styles = {'base': ['Gray', 'Dotted', '1', 'Steady'],
                  'target': ['Cyan', 'Dashed', '3', 'Steady'],
                  'incoming': ['Magenta', 'Dash-dot', '3', 'Steady']}
        w = self.worker
        with w.work_area() as area:
            source = area['path'] / 'merge.drf'
            for side in styles:
                self.packets[side] = 'aldMerge' + self.token[:12] + side
            source.write_text(''.join(display_resource(self.packets[k], v) for k, v in styles.items()), encoding='ascii')
            remote = area['remote'] + '/merge.drf'
            checked(w.client.upload_file(str(source), remote))
            w.execute(f'drLoadDrf({sk(remote)})')

    def highlight(self, unit_id):
        if not self.packets:
            self.install_styles()
        unit = self.session.plan.units[unit_id]
        entries, boxes, warnings = [], [], []
        for side in ('base', 'target', 'incoming'):
            snapshot, selected, truncated = self.index.projection(side, unit_id)
            if truncated:
                warnings.append('Alternative geometry limited to 2000 elements; full result validation remains required')
            if not snapshot['objects']:
                entries.append([self.packets[side], []])
                continue
            if side not in self.alternatives or self.alternatives[side]['unit'] != unit_id:
                self.release(self.alternatives.pop(side, None))
                self.alternatives[side] = {**self.build(snapshot), 'unit': unit_id}
            native = self.alternatives[side]
            groups = [k for k in selected if snapshot['objects'][k]['kind'] in {'group', 'figGroup'}]
            figures = [k for k in selected if snapshot['objects'][k]['kind'] in VISUAL]
            shadow = uuid.uuid4().hex
            # Only helpers receive the transient boolean-conversion figures.
            if figures:
                info = loads(self.worker.execute(f'ALDGUIPrepareShadows({sk(native["token"])} {sk(shadow)} {sk(figures)})'))
                warnings.extend(info[2] or [])
                data = loads(self.worker.execute(f'ALDGUIShadowData[{sk(shadow)}]'))
                primitives = data[1] or []
                if data[0]:
                    boxes.append(data[0])
                self.worker.execute(f'ALDGUIShadowData[{sk(shadow)}]=nil')
            else:
                primitives = []
            if groups:
                bounds = loads(self.worker.execute(f'ALDGUIGroupBounds({sk(native["token"])} '
                                                   f'{sk(boundary_targets(snapshot, groups))})'))
                for _key, box in bounds or []:
                    if box:
                        primitives.append(['rect', box]); boxes.append(box)
            entries.append([self.packets[side], primitives])
        self.worker.execute(f'ALDMergeDraw({sk(self.token)} {sk(entries)})')
        if boxes:
            box = [[min(b[0][j] for b in boxes) for j in (0, 1)],
                   [max(b[1][j] for b in boxes) for j in (0, 1)]]
            self.worker.execute(f'ALDMergeZoom({sk(self.token)} {sk(box)})')
        return warnings

    def edit(self):
        self.worker.execute(f'ALDMergeEdit({sk(self.token)} t)')
        self.editing = True

    def capture(self):
        with self.worker.work_area():
            native = self.current
            actual = self.worker.adapter.capture(native['library'], native['cell'])
            return actual

    def capture_supported(self):
        """Retain complete omission diagnostics; caller must obtain two consents."""
        with self.worker.work_area():
            native = self.current
            store = self.worker.adapter.capture_store(native['library'], native['cell'],
                allow_unsupported=True, temporary=True)
            try:
                audit = store.omissions
                if audit:
                    destination = self.session.path / 'omissions' / (audit['reportSha256'] + '.jsonl')
                    destination.parent.mkdir(exist_ok=True)
                    if not destination.exists():
                        shutil.copyfile(store.omission_report, destination)
                return store.materialize(), audit, store.source_digest
            finally:
                store.dispose()

    def close(self):
        self.worker.execute(f'ALDMergeClose({sk(self.token)} t)')
        self.release(self.current)
        for native in self.alternatives.values():
            self.release(native)
        self.current = None
        self.alternatives.clear()
