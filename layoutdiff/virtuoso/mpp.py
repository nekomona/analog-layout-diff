"""Editable ROD multipart paths plus exact generated-figure readback.

Only data is persisted; replay renders a fixed set of documented ROD keywords.
Generated figures are reused, not duplicated as flattened geometry.
"""
from layoutdiff.virtuoso.sexpr import dumps as sk
import re

PARTS = {'offsetPath': 'offsetSubPath', 'enclosurePath': 'encSubPath', 'rectangle': 'subRect'}
DIMS = {'width', 'length', 'space', 'separation', 'enclosure', 'beginOffset',
        'endOffset', 'beginSegOffset', 'endSegOffset'}
FIELDS = {'lpp': 'layer', 'separation': 'sep', **{f: f for f in DIMS - {'separation'}},
          **{f: f for f in ('choppable', 'netName', 'termName', 'justification', 'gap', 'diagonal')}}
STYLES = {'truncateExtend': 'flush', 'extendExtend': 'offset', 'variable': 'variable', 'octagon': 'octagon'}


def valid_hole(hole):
    return (isinstance(hole,list) and len(hole)>=2
            and all(isinstance(p,list) and len(p)==2
                    and all(type(v) is int for v in p) for p in hole))


def capture_chop_holes(m):
    """Decode the IC23.1 aggregate/cache representation, in integer DBU.

    Installed docs describe coordinate lists; native one/two-hole and moved
    fixtures reveal [all_holes, *cached_holes]. Only the aggregate is current.
    Preserve an unrecognized representation as explicit unsupported content.
    """
    if 'nativeChopHoles' not in m:
        return
    raw=m.pop('nativeChopHoles')
    if raw is None:
        m['chopHoles']=None
    elif (isinstance(raw,list) and raw and isinstance(raw[0],list)
          and raw[0] and all(valid_hole(h) for h in raw[0])
          and all(valid_hole(h) for h in raw[1:])):
        m['chopHoles']=sorted(raw[0])
    else:
        m['chopHoles']=raw
        m['unsupportedFeatures']=(m.get('unsupportedFeatures') or [])+['native chop-hole encoding']


def issues(r):
    m = r.get('mpp')
    if m is None:
        return []
    result = []
    if r['kind'] != 'path' or r.get('pathStyle') not in STYLES:
        result.append('unsupported MPP master path style')
    if not isinstance(m, dict) or not isinstance(m.get('name'), str):
        return result + ['invalid MPP definition']
    # SKILL nil is captured as JSON null, including an unchoppable master.
    if (not m['name'] or 'choppable' not in m
            or (m['choppable'] is not None and type(m['choppable']) is not bool)
            or not isinstance(m.get('parts'), list) or not m['parts']):
        result.append('invalid MPP definition')
    result += ['unsupported MPP ' + str(f) for f in m.get('unsupportedFeatures') or []]
    if m.get('chopHoles') is not None and (not isinstance(m['chopHoles'],list)
            or not all(valid_hole(h) for h in m['chopHoles'])):
        result.append('invalid MPP chop holes')
    for p in m.get('parts') or []:
        if not isinstance(p,dict):
            result.append('invalid MPP subpart'); continue
        if p.get('type') not in PARTS or set(p) - (set(FIELDS) | {'name', 'type'}):
            result.append('unsupported MPP subpart definition')
        if 'name' in p and (not isinstance(p['name'],str) or not re.fullmatch(r'subpart\d+',p['name'])):
            result.append('custom MPP subpart name')
        required = {'lpp','choppable','netName','termName','beginOffset','endOffset'}
        required |= ({'enclosure'} if p.get('type') == 'enclosurePath' else {'width','separation','justification'})
        if p.get('type') == 'rectangle':
            required |= {'length','space','gap','beginSegOffset','endSegOffset','diagonal'}
        if required - set(p) or any(type(v) is not int for f,v in p.items() if f in DIMS):
            result.append('missing or invalid MPP parameters')
        if not isinstance(p.get('lpp'),list) or len(p['lpp']) != 2 or not all(isinstance(v,str) for v in p['lpp']):
            result.append('invalid MPP layer-purpose pair')
        # Pin subpart semantics need a dedicated codec; fail explicitly.
        if p.get('termName'):
            result.append('MPP subpart terminal')
    return result


def geometry(r, dim):
    # Native-generated objects are matched within one MPP only. Include full
    # geometry, not just a bounding box; identical occurrences use queues.
    return [r['kind'], [r.get('layerName'), r.get('purpose')],
            dim(r.get('bBox')) if r['kind'] == 'rect' else dim(r.get('points')),
            dim(r.get('width'))]


def prepare_replay(records, dim):
    masters = [r for r in records if r.get('mpp')]
    if not masters:
        return []
    commands = ["aldMPPs=makeTable('aldMPPs nil) aldMPPShapes=makeTable('aldMPPShapes nil)"]
    for r in sorted(masters, key=lambda r: r['mpp']['name']):
        m = r['mpp']
        args = f'?cvId cv ?name {sk(m["name"])} ?layer {sk([r["layerName"], r["purpose"]])} '
        args += f'?pts {sk(dim(r["points"]))} ?width {sk(dim(r["width"]))} ?endType {sk(STYLES[r["pathStyle"]])} '
        args += f'?choppable {sk(m["choppable"])} ?beginExt {sk(dim(r["beginExt"]))} ?endExt {sk(dim(r["endExt"]))}'
        for typ, keyword in PARTS.items():
            parts = []
            for p in m['parts']:
                if p['type'] != typ:
                    continue
                fields = ['?' + key + ' ' + sk(dim(p[f]) if f in DIMS else p[f])
                          for f, key in sorted(FIELDS.items()) if f in p and (p[f] is not None or f in {'choppable', 'diagonal'})]
                parts.append('list(' + ' '.join(fields) + ')')
            if parts:
                args += ' ?' + keyword + ' list(' + ' '.join(parts) + ')'
        commands.append(f'aldRod=rodCreatePath({args}) unless(aldRod error("MPP creation failed")) aldMPPs[{sk(m["name"])}]=aldRod')
        for hole in m.get('chopHoles') or []:
            commands.append(f'unless(rodAddMPPChopHole(aldRod {sk(dim(hole))}) error("MPP chop replay failed"))')
        commands.append(f'''foreach(fig aldRod~>subShapes
          aldShapeKey=list({sk(m['name'])} fig~>objType fig~>lpp
            ALDScale(if(fig~>objType=="rect" then fig~>bBox else fig~>points) cv~>DBUPerUU)
            ALDScale(fig~>width cv~>DBUPerUU))
          aldMPPShapes[aldShapeKey]=cons(fig aldMPPShapes[aldShapeKey]))''')
    return commands


def figure_expression(r, dim):
    if r.get('mpp'):
        return f'aldMPPs[{sk(r["mpp"]["name"])}]~>dbId'
    key = [r['mppOwner'], *geometry(r, lambda v: v)]
    return (f'progn(aldShapeKey={sk(key)} aldMatches=aldMPPShapes[aldShapeKey] '
            'unless(aldMatches error("MPP generated geometry differs from checkpoint")) '
            'aldMPPShapes[aldShapeKey]=cdr(aldMatches) car(aldMatches))')


def cleanup_replay(records):
    """Remove only empty nets created from dangling native recipe names.

    A source MPP recipe can retain a name whose OA net was deleted. rodCreatePath
    creates that net again; exact figure connectivity has already been restored.
    Never delete checkpoint nets, or detach any remaining native references.
    """
    names={r['name'] for r in records if r['kind']=='net'}
    dangling={p['netName'] for r in records if r.get('mpp')
              for p in r['mpp']['parts'] if p.get('netName')} - names
    result=[]
    for name in sorted(dangling):
        result.append(f'''n=car(setof(net cv~>nets net~>name=={sk(name)}))
          when(n
            when(n~>figs || n~>allInstTerms || n~>pins || n~>terms || n~>groupMembers ||
                 n~>textDisplays || n~>assocTextDisplays || n~>subnets || n~>routes
              error("Unexpected connected MPP recipe net: %s" {sk(name)}))
            unless(dbDeleteObject(n) error("Cannot remove empty MPP recipe net")))''')
    return result
