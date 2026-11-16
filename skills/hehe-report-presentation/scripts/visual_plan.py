"""Check a page's declared relationship against its rendered objects (stdlib only)."""
from html.parser import HTMLParser
import json
import math
import re

from analytical_charts import TYPES as ANALYTICAL_TYPES, render_svg, validate_spec, validate_small_multiples


RELATIONS = {
    'flow': {'network', 'flow'},
    'sequence': {'flow', 'timeline', 'gantt'},
    'convergence': {'branch_merge'},
    'decision': {'decision'},
    'structure': {'structure'},
    'change': {'waterfall'},
    'comparison': {'bar', 'hbar', 'table', 'dumbbell', 'slope', 'heatmap', 'likert', 'tornado', 'small_multiples'},
    'trend': {'line', 'dual_axis', 'slope', 'band', 'small_multiples'},
    'composition': {'stacked', 'structure', 'donut', 'likert', 'heatmap'},
    'distribution': {'distribution', 'histogram', 'boxplot', 'ecdf', 'likert', 'heatmap', 'small_multiples'},
    'uncertainty': {'interval', 'band', 'small_multiples'},
    'correlation': {'scatter', 'quadrant'},
    'positioning': {'quadrant'},
    'geography': {'choropleth', 'bubble_map'},
    'calculation': {'calculation'},
    'coordination': {'swimlane', 'journey'},
    'lookup': {'table'},
    'narrative': {'prose'},
}
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}


class Node:
    def __init__(self, tag='', attrs=(), parent=None):
        self.tag, self.attrs, self.parent = tag, dict(attrs), parent
        self.children, self.data = [], []

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()

    def visible(self):
        node = self
        while node:
            style = re.sub(r'\s+', '', node.attrs.get('style', '')).lower()
            if (node.tag in {'defs', 'marker', 'clippath', 'symbol', 'script', 'style', 'title', 'desc'}
                    or 'hidden' in node.attrs or 'display:none' in style or 'visibility:hidden' in style):
                return False
            # SVG primitives do not render nested graphics or text as a group does.
            if node is not self and node.tag in {'rect', 'circle', 'ellipse', 'path', 'line', 'polyline', 'polygon'}:
                return False
            node = node.parent
        return True

    def text(self):
        return ' '.join(s for n in self.walk() if n.visible() for s in n.data).strip()

    def has_class(self, name):
        return name in self.attrs.get('class', '').split()


class Document(HTMLParser):
    def __init__(self, body):
        super().__init__(convert_charrefs=True)
        self.root = self.current = Node()
        self.feed(body)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.current)
        self.current.children.append(node)
        if tag not in VOID:
            self.current = node

    def handle_endtag(self, tag):
        node = self.current
        while node.parent:
            if node.tag == tag:
                self.current = node.parent
                return
            node = node.parent

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_data(self, data):
        self.current.data.append(data)


def _drawn_line(node):
    try:
        return any(any(point != segment[0] for point in segment[1:]) for segment in _line_segments(node))
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def _line_segments(node):
    """Read real segments, excluding moveto-only and zero-length SVG paths."""
    if node.tag == 'line':
        return [[(_number(node, 'x1', 0), _number(node, 'y1', 0)),
                 (_number(node, 'x2', 0), _number(node, 'y2', 0))]]
    if node.tag == 'polyline':
        values = _numbers(node.attrs.get('points', ''))
        if len(values) % 2:
            raise ValueError('incomplete polyline')
        points = list(zip(values[::2], values[1::2]))
        return [points[i:i + 2] for i in range(len(points) - 1)]
    if node.tag != 'path':
        return []
    token = r'[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d*\.?\d+)(?:[eE][-+]?\d+)?'
    data = node.attrs.get('d', '')
    if re.sub(token + r'|[\s,]', '', data):
        raise ValueError('invalid path')
    tokens = re.findall(token, data)
    if tokens and tokens[0].lower() != 'm':
        raise ValueError('path must start with moveto')
    arity = {'m': 2, 'l': 2, 'h': 1, 'v': 1, 'c': 6, 's': 4, 'q': 4, 't': 2, 'a': 7}
    segments, command, current, origin, control, previous, i = [], '', (0, 0), (0, 0), None, '', 0
    while i < len(tokens):
        if tokens[i].isalpha():
            command = tokens[i]; i += 1
            if command.lower() == 'z':
                segments.append([current, origin])
                current, command, control, previous = origin, '', None, 'z'
                continue
        if not command or i >= len(tokens):
            raise ValueError('incomplete path')
        kind, size = command.lower(), arity[command.lower()]
        values = [float(v) for v in tokens[i:i + size]]
        if len(values) != size or not all(math.isfinite(v) for v in values):
            raise ValueError('invalid path coordinates')
        i += size
        x, y = current
        coordinate = lambda a, b: (a + (x if command.islower() else 0), b + (y if command.islower() else 0))
        if kind == 'h':
            end = coordinate(values[0], 0)[0], y
        elif kind == 'v':
            end = x, coordinate(0, values[0])[1]
        else:
            end = coordinate(*values[-2:])
        points, next_control = [current], None
        if kind in {'c', 'q', 's'}:
            if kind == 's':
                points.append((2 * x - control[0], 2 * y - control[1]) if control and previous in {'c', 's'} else current)
            points.extend(coordinate(*values[j:j + 2]) for j in range(0, len(values) - 2, 2))
            next_control = points[-1]
        elif kind == 't':
            next_control = (2 * x - control[0], 2 * y - control[1]) if control and previous in {'q', 't'} else current
            points.append(next_control)
        elif kind == 'a' and (min(values[:2]) < 0 or any(v not in (0, 1) for v in values[3:5])):
            raise ValueError('invalid arc')
        if kind == 'm':
            origin = end
            command = 'l' if command.islower() else 'L'
        else:
            segments.append(points + [end])
        current, control, previous = end, next_control, kind
    return segments


def _data_mark(node):
    try:
        if node.tag == 'rect':
            return float(node.attrs.get('width', '0')) > 0 and float(node.attrs.get('height', '0')) >= 0 and 'height' in node.attrs
        if node.tag == 'circle':
            return float(node.attrs.get('r', '0')) > 0
    except ValueError:
        return False
    return _drawn_line(node)



# New quantitative forms use a strict SVG contract. Existing component/custom
# graph paths below retain their original behavior.
def _number(node, key, default=None):
    value = float(node.attrs.get(key, default))
    if not math.isfinite(value):
        raise ValueError('non-finite data or geometry')
    return value


def _numbers(value):
    result = [float(v) for v in re.split(r'[\s,]+', value.strip()) if v]
    if not result or not all(math.isfinite(v) for v in result):
        raise ValueError('invalid coordinates')
    return result


def _close(a, b, tolerance=.05):
    return math.isclose(a, b, rel_tol=1e-6, abs_tol=tolerance)


def _property(node, key, default=''):
    while node:
        declarations = dict((k.strip().lower(), v.strip()) for k, v in (part.split(':', 1) for part in node.attrs.get('style', '').split(';') if ':' in part))
        value = declarations.get(key, node.attrs.get(key))
        if value is not None:
            value = value.strip().lower().removesuffix('!important').strip()
            if value not in {'inherit', 'unset'}:
                return default if value == 'initial' else value
        node = node.parent
    return default


def _primitive_box(node):
    if node.tag in {'circle', 'ellipse'}:
        cx, cy = _number(node, 'cx', 0), _number(node, 'cy', 0)
        rx = _number(node, 'r' if node.tag == 'circle' else 'rx')
        ry = _number(node, 'r' if node.tag == 'circle' else 'ry')
        return cx - rx, cy - ry, cx + rx, cy + ry
    if node.tag == 'rect':
        x, y = _number(node, 'x', 0), _number(node, 'y', 0)
        return x, y, x + _number(node, 'width'), y + _number(node, 'height')
    if node.tag == 'line':
        points = [(_number(node, 'x1', 0), _number(node, 'y1', 0)), (_number(node, 'x2', 0), _number(node, 'y2', 0))]
    elif node.tag == 'polyline':
        values = _numbers(node.attrs.get('points', ''))
        if len(values) % 2:
            raise ValueError('incomplete polyline')
        points = list(zip(values[::2], values[1::2]))
    elif node.tag == 'path':
        points = [point for segment in _line_segments(node) for point in segment]
    else:
        points = _region_points(node)
    if not points:
        raise ValueError('missing SVG geometry')
    return min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)


def _opacity(value):
    value = str(value).strip()
    result = float(value[:-1]) / 100 if value.endswith('%') else float(value)
    if not math.isfinite(result):
        raise ValueError('invalid opacity')
    return result


def _svg_painted(node, stroke=False, strict=True):
    """Require a rendered SVG primitive with effective paint, not a declaration."""
    bounds = _primitive_box(node)
    ancestor, svg = node, False
    while ancestor:
        if not ancestor.visible() or _opacity(_property_value(ancestor, 'opacity') or '1') <= 0:
            return False
        declarations = dict((k.strip().lower(), v.strip()) for k, v in (part.split(':', 1) for part in ancestor.attrs.get('style', '').split(';') if ':' in part))
        if (_property(node, 'visibility') in {'hidden', 'collapse'}
                or (strict and (ancestor.attrs.get('transform') or declarations.get('transform')
                    or any(ancestor.attrs.get(k) or declarations.get(k) for k in ('clip-path', 'mask', 'filter'))))):
            return False
        if ancestor.tag == 'foreignobject' and not svg:
            return False
        if ancestor.tag == 'svg':
            svg = True
            if any(re.fullmatch(r'[-+]?0+(?:\.0+)?(?:px|%)?', declarations.get(k, ancestor.attrs.get(k, '')).lower()) for k in ('width', 'height')):
                return False
            box = _numbers(ancestor.attrs.get('viewbox', '0 0 300 150'))
            if len(box) != 4 or min(box[2:]) <= 0:
                return False
            if strict and (bounds[2] < box[0] or bounds[0] > box[0] + box[2] or bounds[3] < box[1] or bounds[1] > box[1] + box[3]):
                return False
        ancestor = ancestor.parent
    if not svg:
        return False
    key = 'stroke' if stroke else 'fill'
    paint = _property(node, key, 'none' if stroke else 'black')
    if paint == 'currentcolor':
        paint = _property(node, 'color', 'black')
    transparent = (paint in {'', 'none', 'transparent'} or re.fullmatch(r'#(?:[0-9a-f]{3}0|[0-9a-f]{6}00)', paint)
                   or re.fullmatch(r'(?:rgba|hsla)\(.*,\s*0(?:\.0+)?\s*\)', paint)
                   or re.search(r'/\s*0(?:\.0+)?%?\s*\)$', paint))
    return (not transparent and _opacity(_property(node, key + '-opacity', '1')) > 0
            and (not stroke or float(_property(node, 'stroke-width', '1').removesuffix('px')) > 0))


def _transformed_segments(node):
    """Keep ordinary SVG translations/curves valid while detecting collapsed lines."""
    segments = _line_segments(node)
    ancestor = node
    while ancestor:
        transform = _property_value(ancestor, 'transform')
        if transform.strip().lower() == 'none':
            transform = ''
        operations = re.findall(r'([a-zA-Z]+)\s*\(([^)]*)\)', transform)
        if re.sub(r'[a-zA-Z]+\s*\([^)]*\)|[\s,]', '', transform):
            raise ValueError('invalid transform')
        for kind, args in reversed(operations):
            values = _numbers(args)
            kind = kind.lower()
            if kind == 'matrix' and len(values) == 6:
                a, b, c, d, e, f = values
            elif kind == 'translate' and len(values) in (1, 2):
                a, b, c, d, e, f = 1, 0, 0, 1, values[0], values[-1] if len(values) == 2 else 0
            elif kind == 'scale' and len(values) in (1, 2):
                a, b, c, d, e, f = values[0], 0, 0, values[-1], 0, 0
            elif kind == 'rotate' and len(values) in (1, 3):
                angle = math.radians(values[0]); a, b = math.cos(angle), math.sin(angle)
                c, d = -b, a
                x, y = values[1:] if len(values) == 3 else (0, 0)
                e, f = x - a * x - c * y, y - b * x - d * y
            elif kind in {'skewx', 'skewy'} and len(values) == 1:
                shear = math.tan(math.radians(values[0]))
                a, b, c, d, e, f = 1, shear if kind == 'skewy' else 0, shear if kind == 'skewx' else 0, 1, 0, 0
            else:
                raise ValueError('unsupported transform')
            segments = [[(a * x + c * y + e, b * x + d * y + f) for x, y in segment] for segment in segments]
        ancestor = ancestor.parent
    return segments


def _property_value(node, key):
    """Read an element's own transform; transforms are not inherited properties."""
    declarations = dict((k.strip().lower(), v.strip()) for k, v in (part.split(':', 1) for part in node.attrs.get('style', '').split(';') if ':' in part))
    return declarations.get(key, node.attrs.get(key, '')).removesuffix('!important').strip()


def _visible_connector(node):
    try:
        if node.attrs.get('data-connector') == 'true' and node.tag not in {'line', 'path', 'polyline'}:
            return any(n.data and _visible_text(n) for n in node.walk())
        return (_svg_painted(node, stroke=True, strict=False)
                and any(any(not (_close(point[0], segment[0][0], 1e-9) and _close(point[1], segment[0][1], 1e-9))
                            for point in segment[1:]) for segment in _transformed_segments(node)))
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def _visible_text(node):
    """Exclude transparent text from the new quantitative forms' evidence."""
    if not node.visible():
        return False
    ancestor, svg = node, False
    try:
        while ancestor:
            opacity = float(_property(ancestor, 'opacity', '1').removesuffix('%'))
            if not math.isfinite(opacity) or opacity <= 0:
                return False
            svg = svg or ancestor.tag == 'svg'
            ancestor = ancestor.parent
        for key in (('fill', 'stroke') if svg else ('color',)):
            color = _property(node, key, 'none' if key == 'stroke' else 'black')
            if color == 'currentcolor':
                color = _property(node, 'color', 'black')
            transparent = (color in {'', 'none', 'transparent'}
                           or re.fullmatch(r'#(?:[0-9a-f]{3}0|[0-9a-f]{6}00)', color)
                           or re.fullmatch(r'(?:rgba|hsla)\(.*,\s*0(?:\.0+)?%?\s*\)', color)
                           or re.search(r'/\s*0(?:\.0+)?%?\s*\)$', color))
            if not transparent and (not svg or float(_property(node, key + '-opacity', '1').removesuffix('%')) > 0):
                if key != 'stroke' or float(_property(node, 'stroke-width', '1')) > 0:
                    return True
    except (TypeError, ValueError):
        return False
    return False


def _documented(target, *keys):
    text = ' '.join(part for node in target.walk() if node.data and _visible_text(node) for part in node.data).strip()
    return all(isinstance(target.attrs.get(k), str) and target.attrs[k].strip()
               and target.attrs[k].strip() in text for k in keys)


def _line_geometry(node):
    if node.tag != 'line' or not _svg_painted(node, stroke=True):
        raise ValueError('missing visible axis')
    values = tuple(_number(node, k, 0) for k in ('x1', 'y1', 'x2', 'y2'))
    if values[:2] == values[2:]:
        raise ValueError('zero-length axis')
    return values


def _one(nodes, key, value, tag=None):
    found = [n for n in nodes if n.attrs.get(key) == value and (tag is None or n.tag == tag)]
    if len(found) != 1:
        raise ValueError('missing or duplicate geometry')
    return found[0]


def _crossing(first, second, interior=False):
    x, y, endx, endy = first
    a, b, enda, endb = second
    dx, dy, da, db = endx - x, endy - y, enda - a, endb - b
    determinant = dx * db - dy * da
    if _close(determinant, 0, 1e-6):
        return False
    t, u = ((a - x) * db - (b - y) * da) / determinant, ((a - x) * dy - (b - y) * dx) / determinant
    return (0 < t < 1 and 0 < u < 1) if interior else (0 <= t <= 1 and 0 <= u <= 1)


def _plot(target, nodes, vertical='y', prefix='y'):
    x1, y1, x2, y2 = _line_geometry(_one(nodes, 'data-axis', 'x', 'line'))
    a, b, c, d = _line_geometry(_one(nodes, 'data-axis', vertical, 'line'))
    if not (_close(y1, y2) and x2 > x1 and _close(a, c) and b > d
            and _close(x1, a) and _close(y1, b)):
        raise ValueError('axes must share a Cartesian origin')
    xmin, xmax = ((_number(target, 'data-x-' + side) for side in ('min', 'max')) if vertical == 'y' else (0, 1))
    ymin, ymax = (_number(target, 'data-' + prefix + '-' + side) for side in ('min', 'max'))
    if not (xmin < xmax and ymin < ymax):
        raise ValueError('invalid scale')
    return x1, y1, x2 - x1, b - d, xmin, xmax, ymin, ymax


def _position(plot, x, y):
    left, bottom, width, height, xmin, xmax, ymin, ymax = plot
    if not (xmin <= x <= xmax and ymin <= y <= ymax):
        raise ValueError('data outside scale')
    return left + width * (x - xmin) / (xmax - xmin), bottom - height * (y - ymin) / (ymax - ymin)


def _point(node):
    if node.tag not in {'circle', 'ellipse'} or not (_svg_painted(node) or _svg_painted(node, stroke=True)):
        raise ValueError('missing point geometry')
    if node.tag == 'circle':
        if _number(node, 'r') <= 0:
            raise ValueError('zero-size point')
    elif min(_number(node, 'rx'), _number(node, 'ry')) <= 0:
        raise ValueError('zero-size point')
    return _number(node, 'cx', 0), _number(node, 'cy', 0)


def _scatter(target, form, nodes):
    if not _documented(target, 'data-x-unit', 'data-y-unit'):
        return False
    axes = [_line_geometry(_one(nodes, 'data-axis', k, 'line')) for k in ('x', 'y')]
    if not _crossing(*axes):
        return False
    scale_keys = ('data-x-min', 'data-x-max', 'data-y-min', 'data-y-max')
    plot = _plot(target, nodes) if any(k in target.attrs for k in scale_keys) else None
    marks = [n for n in nodes if n.attrs.get('data-point')]
    names = [n.attrs['data-point'] for n in marks]
    if len(marks) < 2 or len(names) != len(set(names)):
        return False
    for mark in marks:
        actual = _point(mark)
        x, y = _number(mark, 'data-x'), _number(mark, 'data-y')
        if plot is not None:
            expected = _position(plot, x, y)
            if not all(_close(a, b) for a, b in zip(actual, expected)):
                return False
    if form == 'scatter':
        return True
    xcut, ycut = _number(target, 'data-x-threshold'), _number(target, 'data-y-threshold')
    if plot is None:
        cuts = [_line_geometry(_one(nodes, 'data-divider', k, 'line')) for k in ('x', 'y')]
        return _crossing(*cuts, interior=True)
    left, bottom, width, height, xmin, xmax, ymin, ymax = plot
    if not (xmin < xcut < xmax and ymin < ycut < ymax):
        return False
    x, y = _position(plot, xcut, ycut)
    for axis, expected in [('x', (x, bottom, x, bottom - height)), ('y', (left, y, left + width, y))]:
        actual = _line_geometry(_one(nodes, 'data-divider', axis, 'line'))
        if not (all(_close(a, b) for a, b in zip(actual, expected))
                or all(_close(a, b) for a, b in zip(actual, expected[2:] + expected[:2]))):
            return False
    return True


def _region_points(node):
    if node.tag == 'polygon':
        values = _numbers(node.attrs.get('points', ''))
        if len(values) % 2:
            raise ValueError('incomplete polygon')
        return list(zip(values[::2], values[1::2]))
    if node.tag != 'path':
        return []
    data = node.attrs.get('d', '')
    token = r'[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d*\.?\d+)(?:[eE][-+]?\d+)?'
    tokens = re.findall(token, data)
    if re.sub(token + r'|[\s,]', '', data) or not re.search(r'[Zz]', data):
        return []
    arity = {'m': 2, 'l': 2, 'h': 1, 'v': 1, 'c': 6, 's': 4, 'q': 4, 't': 2, 'a': 7}
    points, command, x, y, origin, i = [], '', 0, 0, (0, 0), 0
    while i < len(tokens):
        if tokens[i].isalpha():
            command = tokens[i]; i += 1
            if command.lower() == 'z':
                x, y = origin
                command = ''
                continue
        if not command:
            raise ValueError('invalid path')
        size = arity[command.lower()]
        values = [float(v) for v in tokens[i:i + size]]
        if len(values) != size or not all(math.isfinite(v) for v in values):
            raise ValueError('invalid path coordinates')
        i += size
        if command.lower() == 'h':
            x = values[0] + (x if command.islower() else 0)
        elif command.lower() == 'v':
            y = values[0] + (y if command.islower() else 0)
        else:
            x, y = values[-2] + (x if command.islower() else 0), values[-1] + (y if command.islower() else 0)
        points.append((x, y))
        if command.lower() == 'm':
            origin = x, y
            command = 'l' if command.islower() else 'L'
    return points


def _region(node):
    if not node.attrs.get('data-region') or not (_svg_painted(node) or _svg_painted(node, stroke=True)):
        return False
    points = _region_points(node)
    distinct = list(dict.fromkeys(points))
    if len(distinct) < 3:
        return False
    a, b = distinct[:2]
    return any(abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) > 1e-6 for c in distinct[2:])


def _geography(target, form, nodes):
    if not _documented(target, 'data-unit', 'data-map-source'):
        return False
    regions = [n for n in nodes if n.attrs.get('data-region')]
    if not regions or not all(_region(n) for n in regions):
        return False
    ids = [n.attrs['data-region'] for n in regions]
    if len(ids) != len(set(ids)):
        return False
    if form == 'choropleth':
        values = [_number(n, 'data-value') for n in regions]
        fills = [_property(n, 'fill', 'black') for n in regions]
        return (len(regions) >= 2 and all(_svg_painted(n) for n in regions)
                and (len(set(values)) == 1 or len(set(fills)) >= 2))
    projected = target.attrs.get('data-projection') == 'equirectangular' and 'data-map-box' in target.attrs
    lonmin, lonmax = _number(target, 'data-lon-min', -180), _number(target, 'data-lon-max', 180)
    latmin, latmax = _number(target, 'data-lat-min', -90), _number(target, 'data-lat-max', 90)
    left, top, width, height = _numbers(target.attrs.get('data-map-box', '0 0 1 1'))
    if not (-180 <= lonmin < lonmax <= 180 and -90 <= latmin < latmax <= 90 and min(width, height) > 0):
        return False
    marks = [n for n in nodes if n.attrs.get('data-point')]
    ids = [n.attrs['data-point'] for n in marks]
    if len(marks) < 2 or len(ids) != len(set(ids)):
        return False
    scales = []
    for mark in marks:
        if mark.tag != 'circle':
            return False
        actual = _point(mark)
        lon, lat, value = (_number(mark, k) for k in ('data-lon', 'data-lat', 'data-value'))
        if not (lonmin <= lon <= lonmax and latmin <= lat <= latmax and value > 0):
            return False
        if projected:
            expected = left + width * (lon - lonmin) / (lonmax - lonmin), top + height * (latmax - lat) / (latmax - latmin)
            if not all(_close(a, b) for a, b in zip(actual, expected)):
                return False
        scales.append(_number(mark, 'r') ** 2 / value)
    return all(_close(v, scales[0], 1e-6) for v in scales)


def _donut(target, nodes):
    if not _documented(target, 'data-unit'):
        return False
    marks = [n for n in nodes if n.attrs.get('data-category')]
    ids = [n.attrs['data-category'] for n in marks]
    if len(marks) < 2 or len(ids) != len(set(ids)) or any(name not in target.text() for name in ids):
        return False
    values = [_number(n, 'data-value') for n in marks]
    total = _number(target, 'data-total')
    if min(values) <= 0 or not _close(sum(values), total, 1e-6):
        return False
    geometry, consumed = None, 0
    for mark, value in zip(marks, values):
        if mark.tag != 'circle' or _property(mark, 'fill', 'black') != 'none' or not _svg_painted(mark, stroke=True):
            return False
        current = _point(mark) + (_number(mark, 'r'), float(_property(mark, 'stroke-width', '1')), mark.attrs.get('transform', ''))
        if not (0 < current[3] < 2 * current[2]) or (geometry is not None and current != geometry):
            return False
        geometry = current
        circumference = 2 * math.pi * current[2]
        dash, gap = _numbers(_property(mark, 'stroke-dasharray'))
        if not (_close(dash + gap, circumference) and _close(dash, circumference * value / total)
                and _close(float(_property(mark, 'stroke-dashoffset', '0')), -circumference * consumed / total)):
            return False
        consumed += value
    return True


def _dual_axis(target, nodes):
    if not _documented(target, 'data-left-unit', 'data-right-unit', 'data-left-series', 'data-right-series'):
        return False
    plot = _plot(target, nodes, 'left', 'left')
    left, bottom, width, height, xmin, xmax, ymin, ymax = plot
    rightmin, rightmax = _number(target, 'data-right-min'), _number(target, 'data-right-max')
    if not (ymin <= 0 <= ymax and rightmin < rightmax):
        return False
    expected = left + width, bottom, left + width, bottom - height
    if not all(_close(a, b) for a, b in zip(_line_geometry(_one(nodes, 'data-axis', 'right', 'line')), expected)):
        return False
    bars = [n for n in nodes if n.tag == 'rect' and n.attrs.get('data-series') == target.attrs['data-left-series']]
    points = [n for n in nodes if n.tag in {'circle', 'ellipse'} and n.attrs.get('data-series') == target.attrs['data-right-series']]
    categories = [n.attrs['data-category'] for n in bars]
    if (len(bars) < 2 or len(categories) != len(set(categories)) or len(points) != len(bars)
            or set(categories) != {n.attrs['data-category'] for n in points}
            or any(category not in target.text() for category in categories)):
        return False
    by_category, positive = {}, False
    baseline = bottom + height * ymin / (ymax - ymin)
    for bar in bars:
        if not _svg_painted(bar):
            return False
        x, y, w, h = (_number(bar, k) for k in ('x', 'y', 'width', 'height'))
        value = _number(bar, 'data-value')
        if not (w > 0 and h >= 0 and ymin <= value <= ymax and left <= x < x + w <= left + width):
            return False
        endpoint = bottom - height * (value - ymin) / (ymax - ymin)
        if not (_close(y, min(baseline, endpoint)) and _close(h, abs(baseline - endpoint))):
            return False
        by_category[bar.attrs['data-category']] = x + w / 2
        positive = positive or h > 0
    if not positive or len(set(by_category.values())) != len(bars):
        return False
    positions = []
    for point in points:
        x, y = _point(point)
        value = _number(point, 'data-value')
        if not (rightmin <= value <= rightmax and _close(x, by_category[point.attrs['data-category']])
                and _close(y, bottom - height * (value - rightmin) / (rightmax - rightmin))):
            return False
        positions.append((x, y))
    line = _one(nodes, 'data-series', target.attrs['data-right-series'], 'polyline')
    values = _numbers(line.attrs.get('points', ''))
    drawn = list(zip(values[::2], values[1::2]))
    expected = sorted(positions)
    return (len(values) == 2 * len(expected) and _svg_painted(line, stroke=True)
            and all(_close(a, b) for actual, wanted in zip(drawn, expected) for a, b in zip(actual, wanted)))


def _quantitative_graph(target, form, nodes):
    if target.attrs.get('data-visual') != form or not _documented(target, 'data-source'):
        return False
    try:
        if form in {'scatter', 'quadrant'}:
            return _scatter(target, form, nodes)
        if form in {'choropleth', 'bubble_map'}:
            return _geography(target, form, nodes)
        if form == 'donut':
            return _donut(target, nodes)
        if form == 'dual_axis':
            return _dual_axis(target, nodes)
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
    return False


def _native_values(chart, form):
    """Validate the existing native-chart data schema, without new mark attributes."""
    if not isinstance(chart, dict) or chart.get('chart_type') != form:
        raise ValueError('missing chart type')
    labels = chart.get('labels')
    if (not isinstance(labels, list) or not labels
            or any(not isinstance(label, (str, int, float)) or isinstance(label, bool)
                   or not str(label).strip() or (isinstance(label, (int, float)) and not math.isfinite(label)) for label in labels)):
        raise ValueError('missing categories')
    if form == 'waterfall':
        groups = [chart.get('values')]
    else:
        series = chart.get('series')
        if (not isinstance(series, list) or not series
                or any(not isinstance(s, dict) or not isinstance(s.get('name'), str) or not s['name'].strip() for s in series)):
            raise ValueError('missing series')
        groups = [s.get('values') for s in series]
    if any(not isinstance(values, list) or len(values) != len(labels)
           or any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) for v in values) for values in groups):
        raise ValueError('invalid series values')
    values = [v for group in groups for v in group]
    if form in {'bar', 'line', 'stacked'} and min(values) < 0:
        raise ValueError('negative values unsupported by native chart')
    if 'max' in chart:
        maximum = chart['max']
        required = max(sum(group[i] for group in groups) for i in range(len(labels))) if form == 'stacked' else max(values)
        if not isinstance(maximum, (int, float)) or isinstance(maximum, bool) or not math.isfinite(maximum) or maximum < required:
            raise ValueError('invalid chart scale')
        if form == 'hbar':
            lower = min(0, min(values))
            span = max(0, max(values)) - lower or 1
            lower = lower - span * .08 if lower < 0 else 0
            if maximum < 0 or maximum <= lower:
                raise ValueError('invalid chart scale')
        elif maximum <= 0:
            raise ValueError('invalid chart scale')
    if form == 'waterfall':
        totals = chart.get('totals', [0, len(labels) - 1])
        if (not isinstance(totals, list) or 0 not in totals
                or any(not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < len(labels) for i in totals)):
            raise ValueError('invalid waterfall totals')
        current = 0
        for i, value in enumerate(values):
            if i in totals:
                if i and not math.isclose(current, value, rel_tol=1e-8, abs_tol=1e-8):
                    raise ValueError('inconsistent waterfall total')
                current = value
            else:
                current += value
            if current < 0:
                raise ValueError('negative cumulative native waterfall')
    return groups


def _native_chart(node, form):
    """Require the declared data to have actual painted bars or connected points."""
    try:
        chart = json.loads(node.attrs['data-chart'])
        groups = _native_values(chart, form)
        nodes = [n for n in node.walk() if n.visible()]
        # Existing generated SVGs already name categories and series here.
        # Check that binding when present, while retaining older unlabeled SVGs.
        if form == 'waterfall':
            description = '；'.join(f'{label}{value:g}{chart.get("unit", "")}'
                                   for label, value in zip(chart['labels'], groups[0]))
        else:
            description = '；'.join(f'{label}：' + '、'.join(
                f'{series["name"]}{series["values"][i]}{chart.get("unit", "")}'
                for series in chart['series']) for i, label in enumerate(chart['labels']))
        if any(n.tag == 'svg' and 'aria-label' in n.attrs and n.attrs['aria-label'] != description for n in nodes):
            return False
        if form == 'line':
            points = [n for n in nodes if n.tag in {'circle', 'ellipse'}]
            actual = [_point(n) for n in points]
            if len(points) != sum(len(group) for group in groups):
                return False
            lines = [n for n in nodes if n.tag == 'polyline']
            if len(lines) != len(groups):
                return False
            joined, plotted = [], []
            for line, group in zip(lines, groups):
                values = _numbers(line.attrs.get('points', ''))
                if len(values) != 2 * len(group) or not _svg_painted(line, stroke=True):
                    return False
                if len(group) > 1 and not _drawn_line(line):
                    return False
                coordinates = list(zip(values[::2], values[1::2]))
                if len({x for x, _ in coordinates}) != len(group):
                    return False
                joined.extend(coordinates)
                plotted.extend((value, y) for value, (_, y) in zip(group, coordinates))
            first_value, first_y = plotted[0]
            different = next(((value, y) for value, y in plotted if value != first_value), None)
            if different is None:
                consistent = all(_close(y, first_y) for _, y in plotted)
            else:
                value, y = different
                scale = (y - first_y) / (value - first_value)
                consistent = scale < 0 and all(_close(y, first_y + scale * (value - first_value)) for value, y in plotted)
            return consistent and all(_close(a, b) for p, q in zip(sorted(actual), sorted(joined)) for a, b in zip(p, q))
        marks = [n for n in nodes if n.tag == 'rect']
        # Native categories run left-to-right (top-to-bottom for hbar).
        # Stable sorting keeps the existing drawing order of stacked series.
        marks.sort(key=lambda mark: _number(mark, 'y' if form == 'hbar' else 'x'))
        values = [group[i] for i in range(len(chart['labels'])) for group in groups]
        if len(marks) != len(values):
            return False
        geometry, ratios = [], []
        for mark, value in zip(marks, values):
            if not _svg_painted(mark):
                return False
            x, y = _number(mark, 'x'), _number(mark, 'y')
            width, height = _number(mark, 'width'), _number(mark, 'height')
            length, breadth = (width, height) if form == 'hbar' else (height, width)
            if length < 0 or breadth <= 0 or (value == 0) != (length == 0):
                return False
            geometry.append((x, y, width, height))
            if value:
                ratios.append(length / abs(value))
        if ratios and not all(math.isclose(ratio, ratios[0], rel_tol=1e-6, abs_tol=1e-8) for ratio in ratios):
            return False
        scale = ratios[0] if ratios else 1
        axes = [_line_segments(n)[0] for n in nodes if n.tag == 'line'
                and _svg_painted(n, stroke=True) and _drawn_line(n)]
        if form == 'hbar':
            baselines = [a[0] for a, b in axes if _close(a[0], b[0])
                         and min(a[1], b[1]) <= min(y for _, y, _, _ in geometry)
                         and max(a[1], b[1]) >= max(y + h for _, y, _, h in geometry)]
            if not any(all(_close(x, baseline + scale * min(0, value))
                           for (x, _, _, _), value in zip(geometry, values)) for baseline in baselines):
                return False
        else:
            baselines = [a[1] for a, b in axes if _close(a[1], b[1])
                         and min(a[0], b[0]) <= min(x for x, _, _, _ in geometry)
                         and max(a[0], b[0]) >= max(x + w for x, _, w, _ in geometry)]
            if not baselines:
                return False
            baseline, current, size = max(baselines), 0, len(groups)
            totals = chart.get('totals', [0, len(values) - 1])
            for k, ((_, y, _, _), value) in enumerate(zip(geometry, values)):
                if form == 'waterfall':
                    start = 0 if k in totals else current
                    end = value if k in totals else current + value
                    current = end
                elif form == 'stacked':
                    start = sum(group[k // size] for group in groups[:k % size])
                    end = start + value
                else:
                    start, end = 0, value
                if not _close(y, baseline - scale * max(start, end)):
                    return False
        if ratios:
            return True
        # A true zero has no area. Retain native zero-only charts when their
        # baseline and numeric zero labels remain visible, rather than inventing bars.
        return (any(n.tag in {'line', 'path', 'polyline'} and _visible_connector(n) for n in nodes)
                and any(n.data and _visible_text(n) and re.fullmatch(r'[+\-]?0+(?:\.0+)?' + re.escape(str(chart.get('value_suffix', ''))), ' '.join(n.data).strip()) for n in nodes))
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def _analytical_visible(node):
    """Check local/ancestor hiding; stylesheet layout is checked in the browser."""
    if not node.visible() or _property(node, 'visibility') in {'hidden', 'collapse'}:
        return False
    ancestor = node
    while ancestor:
        if (_property_value(ancestor, 'display').lower() == 'none'
                or _opacity(_property_value(ancestor, 'opacity') or '1') <= 0):
            return False
        # Analytical SVG uses direct coordinates. A later transform, crop or
        # filter can change the pictured values even when the metadata agrees.
        if any(_property_value(ancestor, key).lower() not in {'', 'none'}
               for key in ('transform', 'clip-path', 'mask', 'filter')):
            return False
        if ancestor.tag == 'svg' and any(
                re.fullmatch(r'[-+]?0+(?:\.0+)?(?:px|%)?', _property_value(ancestor, key).lower())
                for key in ('width', 'height')):
            return False
        ancestor = ancestor.parent
    return True


def _analytical_svg(actual, expected):
    """Compare actual painted geometry/text with a fresh render of validated data.

    This deliberately accepts the standard direct-coordinate SVG contract, not
    arbitrary hand-drawn analytical charts. Data attributes alone never suffice:
    every bar, endpoint, interval, quantile, category and axis label is compared.
    """
    allowed = {'svg', 'rect', 'line', 'circle', 'polyline', 'polygon', 'text', 'tspan'}
    actual_nodes, expected_nodes = list(actual.walk()), list(expected.walk())
    if len(actual_nodes) != len(expected_nodes):
        return False
    scalar = {'x', 'y', 'cx', 'cy', 'x1', 'x2', 'y1', 'y2', 'r', 'rx', 'ry',
              'width', 'height', 'font-size', 'stroke-width', 'opacity',
              'fill-opacity', 'stroke-opacity', 'letter-spacing'}
    vector = {'viewbox', 'points', 'stroke-dasharray'}
    ignored = {'id', 'class', 'xmlns', 'role', 'aria-label', 'aria-labelledby', 'aria-describedby'}
    for node, wanted in zip(actual_nodes, expected_nodes):
        if node.tag != wanted.tag or node.tag not in allowed or not _analytical_visible(node):
            return False
        actual_attrs = {key: value for key, value in node.attrs.items() if key not in ignored}
        wanted_attrs = {key: value for key, value in wanted.attrs.items() if key not in ignored}
        if actual_attrs.keys() != wanted_attrs.keys():
            return False
        for key, value in wanted_attrs.items():
            if key in scalar:
                if not _close(float(actual_attrs[key]), float(value), .02):
                    return False
            elif key in vector:
                observed, required = _numbers(actual_attrs[key]), _numbers(value)
                if len(observed) != len(required) or not all(_close(a, b, .02) for a, b in zip(observed, required)):
                    return False
            elif actual_attrs[key].strip() != value.strip():
                return False
        if ' '.join(node.data).strip() != ' '.join(wanted.data).strip():
            return False
        if node.tag in {'text', 'tspan'}:
            if node.data and not _visible_text(node):
                return False
        elif node.tag != 'svg':
            # Preserve legitimate zero-height bars/zero-length intervals. Their
            # coordinates and visible labels still must match the canonical SVG.
            if not (_svg_painted(node) or _svg_painted(node, stroke=True)):
                return False
    return True


def _analytical_chart(node, form, target):
    try:
        spec = json.loads(node.attrs['data-chart'])
        if not isinstance(spec, dict) or spec.get('chart_type') != form:
            return False
        validate_spec(spec)
        actual = [n for n in node.walk() if n.tag == 'svg']
        expected = [n for n in Document(render_svg(spec)).root.walk() if n.tag == 'svg']
        if len(actual) != 1 or len(expected) != 1 or not _analytical_svg(actual[0], expected[0]):
            return False
        text = ' '.join(part for n in target.walk() if n.data and _analytical_visible(n)
                        and _visible_text(n) for part in n.data)
        return all(str(spec[key]).strip() in text for key in ('title', 'unit', 'source'))
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def _small_multiples(target, relation):
    try:
        containers = [n for n in target.walk() if n.has_class('small-multiples')
                      and n.attrs.get('data-visual') == 'small_multiples']
        if len(containers) != 1:
            return False
        container = containers[0]
        if container.attrs.get('data-shared-scale') != 'true' or not _analytical_visible(container):
            return False
        charts = [n for n in container.walk() if n.has_class('native-chart')]
        if len(charts) < 2 or any('data-chart' not in n.attrs for n in charts):
            return False
        headings = [n for n in container.children if n.tag == 'h2' and _analytical_visible(n)]
        if len(headings) != 1 or not headings[0].text():
            return False
        specs = [json.loads(node.attrs['data-chart']) for node in charts]
        validate_small_multiples({'type': 'small_multiples', 'id': target.attrs.get('id'),
                                  'title': headings[0].text(), 'shared_scale': True, 'charts': specs})
        if sum(n.tag == 'svg' for n in container.walk()) != len(charts):
            return False
        for node, spec in zip(charts, specs):
            form = spec['chart_type']
            if form not in RELATIONS[relation] - {'small_multiples', 'table', 'prose'}:
                return False
            panel = node.parent
            while panel is not container and not panel.has_class('report-chart'):
                panel = panel.parent
            if panel is container or panel.attrs.get('id') != spec['id'] or not _analytical_visible(node):
                return False
            if not _analytical_chart(node, form, panel):
                return False
        return True
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def _custom_graph(target, form, nodes):
    if target.attrs.get('data-visual') != form:
        return False
    if form in {'bar', 'hbar', 'line', 'stacked', 'waterfall', 'distribution'}:
        marks = [n for n in nodes if 'data-value' in n.attrs and _data_mark(n)]
        try:
            return (bool(target.attrs.get('data-unit')) and len(marks) >= 2
                    and all(math.isfinite(float(n.attrs['data-value'])) for n in marks)
                    and bool(target.text()))
        except (TypeError, ValueError):
            return False
    points = [n for n in nodes if n.attrs.get('data-node') and n.text()]
    ids = [n.attrs['data-node'] for n in points]
    if len(ids) < 2 or len(ids) != len(set(ids)):
        return False
    if form == 'timeline':
        try:
            order = [float(n.attrs['data-order']) for n in points]
            return (all(math.isfinite(v) for v in order) and len(order) == len(set(order))
                    and any(_visible_connector(n) for n in nodes))
        except (KeyError, TypeError, ValueError):
            return False
    edges = [n for n in nodes if n.attrs.get('data-from') and n.attrs.get('data-to')
             and _visible_connector(n)]
    if not edges or any(n.attrs['data-from'] not in ids or n.attrs['data-to'] not in ids for n in edges):
        return False
    if set(ids) != {n.attrs[k] for n in edges for k in ('data-from', 'data-to')}:
        return False
    if form == 'decision':
        return any(len({n.attrs['data-to'] for n in edges if n.attrs['data-from'] == key
                        and n.attrs.get('data-condition') and n.attrs['data-condition'] in target.text()}) >= 2 for key in ids)
    return True


def _implemented(target, form, relation=None):
    nodes = [n for n in target.walk() if n.visible()]
    count = lambda cls: sum(n.has_class(cls) for n in nodes)
    # Keep the historical custom distribution path, while preventing a new
    # standard chart from evading its spec/geometry check by relabeling its plan.
    if form == 'distribution' and any(n.has_class('native-chart') or n.has_class('analytical-chart')
                                      or n.attrs.get('data-chart-type') in ANALYTICAL_TYPES for n in target.walk()):
        return False
    if form == 'small_multiples':
        return _small_multiples(target, relation)
    if form in ANALYTICAL_TYPES:
        charts = [n for n in target.walk() if n.has_class('native-chart') and n.attrs.get('data-chart')]
        return len(charts) == 1 and _analytical_chart(charts[0], form, target)
    if form in {'scatter', 'quadrant', 'choropleth', 'bubble_map', 'donut', 'dual_axis'}:
        return _quantitative_graph(target, form, nodes)
    if form == 'table':
        return any(n.tag == 'table' and n.text() for n in nodes)
    if form == 'prose':
        return any(n.tag == 'p' and n.text() for n in nodes)
    if form in {'bar', 'hbar', 'line', 'stacked', 'waterfall'}:
        for node in nodes:
            if node.has_class('native-chart') and node.attrs.get('data-chart'):
                if _native_chart(node, form):
                    return True
    native = {
        'flow': (count('report-flow') and count('flow-step') >= 2) or (count('analysis-path') and count('analysis-stage') >= 2),
        'timeline': count('report-timeline') and count('timeline-row') >= 2,
        'gantt': count('business-gantt') and count('gantt-bar') >= 1,
        'branch_merge': count('branch-map') and count('branch-row') >= 2 and count('merge-result'),
        'swimlane': count('swimlane-grid') or (count('portrait-matrix') and count('portrait-phase') >= 2),
        'journey': count('journey-grid') or (count('portrait-matrix') and count('portrait-phase') >= 2),
    }
    return bool(native.get(form)) or _custom_graph(target, form, nodes)


def validate_page(slide, body, index):
    """Raise before output is written. Covers/navigation are not analytical pages."""
    if slide.get('kind') != 'content':
        return
    plans = slide.get('visual_plan')
    if isinstance(plans, dict):
        plans = [plans]
    prefix = f'第{index}页「{slide.get("title", "")}」'
    if not isinstance(plans, list) or not plans:
        raise ValueError(prefix + '缺少 visual_plan：先确定关系、图式及完整解释位置。')
    nodes = list(Document(body).root.walk())
    for plan in plans:
        if not isinstance(plan, dict):
            raise ValueError(prefix + '的 visual_plan 须为对象或对象列表。')
        for key in ('relation', 'message', 'form', 'target', 'explanation'):
            if not isinstance(plan.get(key), str) or not plan[key].strip():
                raise ValueError(prefix + f'的图形方案缺少 {key}。')
        relation, form = plan['relation'], plan['form']
        if relation not in RELATIONS or form not in RELATIONS[relation]:
            raise ValueError(prefix + f'的 {relation} 关系不能由 {form} 承担；按关系选图。')
        if form in {'table', 'prose'} and not str(plan.get('reason', '')).strip():
            raise ValueError(prefix + '选表格或正文时，需写明其查阅、比较或论证作用 reason。')
        targets = [n for n in nodes if n.attrs.get('id') == plan['target']]
        if len(targets) != 1 or not targets[0].visible():
            raise ValueError(prefix + f'的 target={plan["target"]} 未唯一对应可见对象。')
        if not _implemented(targets[0], form, relation):
            if form in ANALYTICAL_TYPES or form == 'small_multiples':
                raise ValueError(prefix + f'计划使用 {form}，但对应对象未实现该图式：需使用含完整 data-chart 的标准组件，'
                                 '并保留与数据一致的可见数值、类别、尺度和 SVG 几何；小多图须逐图使用相同尺度和类别顺序。'
                                 '仅有 data-visual 的专用自绘分析图当前不支持此校验路径。')
            raise ValueError(prefix + f'计划使用 {form}，但对应对象未实现该图式；文字框、普通表格、图标和空 SVG 不计。')
