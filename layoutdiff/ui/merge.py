"""Versioned graphical merge actions; native views are disposable projections."""
import json
from pathlib import Path
import re
import uuid

from layoutdiff.data.core import digest, apply_diff
from layoutdiff.data.merge_session import MergeSession
from layoutdiff.data.history import atomic_json
from layoutdiff.eda.virtuoso.sexpr import dumps as sk
from layoutdiff.eda.virtuoso.merge_view import MergeView
from layoutdiff.comparison.matching import bounds


class MergeController:
    def __init__(self, worker):
        self.worker = worker
        self.root = worker.root / 'merges'
        self.root.mkdir(exist_ok=True)
        self.opened = {}

    def start(self, base, target, incoming, *, metadata=None):
        token = uuid.uuid4().hex
        session = MergeSession.create(self.root / token, base, target, incoming, metadata=metadata)
        return self.open(token, session)

    def open(self, token, session=None):
        if not re.fullmatch('[0-9a-f]{32}', token):
            raise ValueError('Invalid merge session ID')
        if token in self.opened:
            raise ValueError('Merge session is already open')
        session = session or MergeSession(self.root / token)
        view = MergeView(self.worker, token, session)
        state = {'session': session, 'view': view, 'selected': next(iter(session.plan.units), None),
                 'preview': None, 'page': 0, 'warnings': []}
        self.opened[token] = state
        try:
            view.show(session.snapshot)
            self.refresh(token)
        except BaseException:
            view.close()
            self.opened.pop(token)
            raise
        return {'token': token, 'generation': session.generation, 'unresolved': len(session.unresolved())}

    def refresh(self, token, *, graphics=True):
        state = self.opened[token]
        session, selected = state['session'], state['selected']
        rows = []
        units = list(session.plan.units.items())
        # Only a bounded page crosses the SKILL bridge.
        if selected:
            state['page'] = next(i for i, (k, _) in enumerate(units) if k == selected) // 50
        for ident, unit in units[state['page']*50:(state['page']+1)*50]:
            status = ('resolved' if ident in session.state['resolved'] else
                      'unresolved' if unit['reasons'] else 'automatic')
            rows.append([ident, unit['category'], status])
        label = session.metadata.get('label', 'Target versus Incoming')
        summary = (f'{label}\n{len(session.unresolved())} unresolved / {len(units)} decisions; '
                   f'page {state["page"]+1}\nBase gray; Target cyan; Incoming magenta. Result uses native layers.')
        explanation = 'No conflicting changes. Validate the result before finishing.'
        if selected:
            unit = session.plan.units[selected]
            explanation = (f'{selected}\n{unit["category"]}\n' +
                '\n'.join(unit['reasons'] or ['Automatically combined compatible changes']) +
                '\nPreview an alternative on the canvas, then Accept preview. '
                'Edit result uses native tools; Accept edits resolves this decision.')
            if state['preview']:
                explanation += '\nPREVIEW: ' + state['preview']['choice'] + ' (not accepted)'
            if graphics and not state['view'].editing:
                state['warnings'] = state['view'].highlight(selected)
        if state['warnings']:
            explanation += '\nSome alternative contours use bounding boxes.'
        explanation += '\n' + '\n'.join(session.plan.warnings)
        self.worker.execute(f'ALDMergeUpdate({sk(token)} {session.generation} {sk(rows)} '
                            f'{sk(summary)} {sk(explanation)})')

    def action(self, token, generation, action, value=''):
        state = self.opened.get(token)
        if state is None:
            raise ValueError('Merge session is closed; resume it first')
        session, view = state['session'], state['view']
        session.check(generation)
        self.worker.execute(f'ALDMergeBusy({sk(token)} {sk(action)})')
        try:
            if view.editing and action not in {'accept-edits', 'cancel-edits', 'details',
                                               'omit-continue', 'omit-confirm', 'omit-cancel'}:
                raise ValueError('Accept or cancel native edits before another merge action')
            if action in {'select', 'next', 'previous', 'pick'}:
                ids = list(session.plan.units)
                if not ids:
                    return {'unresolved': 0}
                if action == 'select':
                    if value not in session.plan.units:
                        raise ValueError('Unknown conflict')
                    selected = value
                elif action == 'pick':
                    selected = self.pick(session, value)
                else:
                    index = ids.index(state['selected']) if state['selected'] in ids else 0
                    selected = ids[(index + (1 if action == 'next' else -1)) % len(ids)]
                if state['preview']:
                    view.show(session.snapshot)
                state['selected'], state['preview'] = selected, None
            elif action == 'preview':
                candidate = session.preview(state['selected'], value, generation)
                view.show(candidate)  # Full native readback before showing a selectable result.
                state['preview'] = {'choice': value, 'digest': digest(candidate)}
            elif action == 'accept':
                preview = state['preview']
                if not preview:
                    raise ValueError('Preview an alternative before accepting it')
                session.decide(state['selected'], preview['choice'], generation,
                               validated_digest=preview['digest'])
                state['preview'] = None
            elif action == 'edit':
                view.edit()
            elif action == 'accept-edits':
                if not view.editing:
                    raise ValueError('Start Edit result first')
                candidate, audit, source_hash = view.capture_supported()
                if audit:
                    state['omission_pending'] = {'snapshot': candidate, 'audit': audit,
                                                 'source': source_hash, 'phase': 1}
                    self.omission_prompt(token, 1)
                    return {'omission_confirmation': 1}
                # Reconstruct separately before accepting edits into the journal.
                view.show(candidate)
                session.accept_edits(candidate, state['selected'], generation)
                state['preview'] = None
            elif action == 'omit-cancel':
                state.pop('omission_pending', None)
            elif action in {'omit-continue', 'omit-confirm'}:
                pending = state.get('omission_pending')
                phase = 1 if action == 'omit-continue' else 2
                if not pending or pending['phase'] != phase:
                    raise ValueError('Omission consent is missing or stale')
                if phase == 1:
                    pending['phase'] = 2
                    self.omission_prompt(token, 2)
                    return {'omission_confirmation': 2}
                candidate, audit, source_hash = view.capture_supported()
                state.pop('omission_pending')
                if source_hash != pending['source'] or audit != pending['audit'] or candidate != pending['snapshot']:
                    raise ValueError('Native content changed after omission preview; review it again')
                view.show(candidate)
                session.accept_edits(candidate, state['selected'], generation, omissions=audit)
                state['preview'] = None
            elif action == 'cancel-edits':
                state.pop('omission_pending', None)
                view.show(session.snapshot)
                state['preview'] = None
            elif action in {'undo', 'redo'}:
                stack = session.state[action]
                if not stack:
                    raise ValueError('No decision to ' + action)
                event = session.event(stack[-1])
                candidate = apply_diff(session.snapshot, event['patch'], reverse=action == 'undo')
                view.show(candidate)
                session.undo(generation, redo=action == 'redo')
                state['preview'] = None
            elif action == 'details':
                unit = session.plan.units.get(state['selected'], {})
                text = json.dumps(unit, indent=2, ensure_ascii=True)
                if len(text) > 60000:
                    destination = session.path / 'selected-details.json'
                    atomic_json(destination, unit)
                    text = text[:60000] + '\nFull details: ' + str(destination)
                self.worker.execute(f'ALDMergeDetails({sk(token)} {sk(text)})')
            elif action in {'validate', 'finish'}:
                if state['preview']:
                    raise ValueError('Accept or dismiss the current preview first')
                if action == 'finish' and session.unresolved():
                    raise ValueError('Resolve every conflict before finishing')
                view.show(session.snapshot)
                state['validated'] = digest(session.snapshot)
                if action == 'finish':
                    return self.finish(token)
            elif action == 'suspend':
                view.close()
                self.opened.pop(token)
                return {'suspended': token, 'generation': session.generation}
            else:
                raise ValueError('Unknown merge action: ' + action)
            self.refresh(token, graphics=action != 'details')
            return {'token': token, 'generation': session.generation, 'unresolved': len(session.unresolved())}
        finally:
            self.worker.execute(f'ALDMergeBusy({sk(token)} "")')

    def pick(self, session, point):
        if not isinstance(point, list) or len(point) != 2:
            raise ValueError('Expected a canvas point')
        candidates = []
        for ident, unit in session.plan.units.items():
            for side, records in unit['alternatives'].items():
                dbu = session.plan.inputs[side]['objects'].get('cell:', {}).get('dbu', 1000)
                x, y = point[0]*dbu, point[1]*dbu
                for r in records.values():
                    box = bounds(r)
                    if box and box[0]-1 <= x <= box[2]+1 and box[1]-1 <= y <= box[3]+1:
                        candidates.append(ident)
        choices = sorted(set(candidates))
        if not choices:
            raise ValueError('No conflict at that point; choose a row or another point')
        if len(choices) > 1:
            raise ValueError('Several conflicts overlap; select their category/row: ' + ', '.join(choices[:8]))
        return choices[0]

    def omission_prompt(self, token, phase):
        pending = self.opened[token]['omission_pending']
        audit = pending['audit']
        text = (f'{audit["omitted"]} unsupported elements will be omitted; '
                f'{audit["detached"]} group memberships will be detached.\n' +
                json.dumps(audit['counts'], indent=2))
        if phase == 2:
            text = 'Restoring or rolling back to this result WILL LOSE the omitted elements.\n' + text
        self.worker.execute(f'ALDMergeOmissionPrompt({sk(token)} {phase} {sk(text)})')

    def finish(self, token):
        # Repository integration installs a coordinator; file-only sessions retain
        # the validated snapshot and require an explicit destination transaction.
        state = self.opened[token]
        handler = getattr(self, 'repository_finish', None)
        if handler:
            return handler(token)
        session = state['session']
        atomic_json(session.path / 'validated-result.json', session.snapshot)
        self.worker.notice('Merge result validated and saved. This session has no Git transaction attached.')
        return {'validated': digest(session.snapshot), 'path': str(session.path / 'validated-result.json')}
