"""Presentation geometry fields; exact stored records are never rewritten."""
from .core import encoded

POSITION = {'points', 'bBox', 'ellipseBBox', 'xy', 'origin', 'beginPt', 'endPt'}
SIZE = {'width', 'height', 'beginExt', 'endExt', 'customExtensions',
        'innerRadius', 'outerRadius', 'rows', 'columns', 'uX', 'uY'}
VIA_SIZE = {'cutRows', 'cutColumns', 'cutWidth', 'cutHeight', 'cutSpacing',
            'layer1Enc', 'layer2Enc', 'layer1Offset', 'layer2Offset',
            'originOffset', 'implant1Enc', 'implant2Enc'}
MPP_SIZE = {'width', 'length', 'space', 'separation', 'enclosure', 'beginOffset',
            'endOffset', 'beginSegOffset', 'endSegOffset'}


def without_geometry(record):
    result = {k: v for k, v in record.items() if k not in POSITION | SIZE}
    if record['kind'] == 'stdVia':
        result['params'] = [p for p in record.get('params', []) if p[0] not in VIA_SIZE]
    if record.get('mpp'):
        result['mpp'] = {k: v for k, v in record['mpp'].items() if k not in {'parts', 'chopHoles'}}
        result['mpp']['parts'] = sorted(
            ({k: v for k, v in p.items() if k not in MPP_SIZE} for p in record['mpp']['parts']), key=encoded)
    return result


def via_context(record):
    """Keep definition/net and non-dimensional overrides as pairing evidence."""
    if record['kind'] != 'stdVia': return None
    return encoded([record.get('viaDef'), record.get('purpose'), record.get('net'),
                    [p for p in record.get('params', []) if p[0] not in VIA_SIZE]])
