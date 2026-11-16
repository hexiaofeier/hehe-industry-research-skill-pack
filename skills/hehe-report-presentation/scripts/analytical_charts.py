"""Offline analytical charts: explicit data semantics and directly editable SVG.

Only the Python standard library is used. validate_spec never changes its input.
All SVG geometry uses absolute coordinates; the same SVG feeds HTML and PPTX.
"""
import html
import json
import math

TYPES = frozenset({'dumbbell', 'slope', 'heatmap', 'likert', 'histogram',
                   'boxplot', 'ecdf', 'interval', 'band', 'tornado'})
BLUE, TEAL, GOLD = '#27647f', '#208e91', '#b78647'
INK, MUTED, GRID = '#173f58', '#607681', '#d8e2e7'
COLORS = [BLUE, TEAL, GOLD, '#8ba6b2', '#775b83']
FONT = 'Microsoft YaHei, 微软雅黑, sans-serif'


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _labels(value, name):
    _require(isinstance(value, list) and value and all(_text(v) for v in value), name + '须为非空文字列表')
    _require(len(set(value)) == len(value), name + '不得重复')
    return len(value)


def _numbers(value, n, name, nonnegative=False, integer=False):
    _require(isinstance(value, list) and len(value) == n, name + '长度不匹配')
    _require(all(_num(v) and (not nonnegative or v >= 0) and
                 (not integer or int(v) == v) for v in value), name + '须为有限数值' + ('且非负' if nonnegative else ''))


def quantile(values, p):
    """R-7 / linear interpolation at (n - 1) * p, including singleton samples."""
    ordered = sorted(values)
    position = (len(ordered) - 1) * p
    low = int(position)
    return ordered[low] + (ordered[min(low + 1, len(ordered) - 1)] - ordered[low]) * (position - low)


def box_summary(group):
    if 'values' not in group:
        return dict(group, outliers=list(group.get('outliers', [])))
    values = sorted(group['values'])
    q1, median, q3 = (quantile(values, p) for p in (.25, .5, .75))
    iqr = q3 - q1
    inner = [v for v in values if q1 - 1.5 * iqr <= v <= q3 + 1.5 * iqr]
    return {'label': group['label'], 'n': len(values), 'low': min(inner),
            'q1': q1, 'median': median, 'q3': q3, 'high': max(inner),
            'outliers': [v for v in values if v < min(inner) or v > max(inner)]}


def _data_extent(s):
    t = s['chart_type']
    if t in {'dumbbell', 'slope'}:
        vals = [v for series in s['series'] for v in series['values']]
    elif t == 'heatmap':
        vals = [v for row in s['values'] for v in row if v is not None]
    elif t == 'likert':
        rows = _likert_rows(s)
        vals = [v for row in rows for segment in row for v in (segment['start'], segment['end'])]
    elif t == 'histogram':
        vals = s['edges']
    elif t == 'boxplot':
        vals = [v for g in s['groups'] for v in (g['values'] if 'values' in g else
                [g['low'], g['high']] + g.get('outliers', []))]
    elif t == 'ecdf':
        vals = [v for series in s['series'] for v in series['values']]
    elif t in {'interval', 'band'}:
        vals = [v for field in ('lower', 'upper') for v in s[field] if v is not None]
    else:
        vals = [s['baseline']] + s['low'] + s['high']
    return min(vals), max(vals)


def _likert_rows(s):
    result = []
    for i, row in enumerate(s['values']):
        pct = [v * 100 / s['bases'][i] for v in row] if s['input'] == 'count' else row
        negative = sum(pct[:s['negative_count']])
        neutral = 0 if s['neutral_index'] is None else pct[s['neutral_index']]
        current = -negative - neutral / 2
        segments = []
        for j, value in enumerate(pct):
            segments.append({'level': s['levels'][j], 'value': value, 'start': current, 'end': current + value})
            current += value
        result.append(segments)
    return result


def validate_spec(s):
    """Validate meaning, lengths, missingness and declared common scales.

    Successful calls return the original object. Invalid input raises ValueError.
    Percent rows are exact by default; rounding_tolerance explicitly permits at
    most one percentage point. Counts, sample sizes and bases are integers.
    """
    _require(isinstance(s, dict), '图表须为对象')
    _require(s.get('type') == 'chart' and s.get('chart_type') in TYPES, '未知分析图表类型')
    for name in ('id', 'title', 'unit', 'source'):
        _require(_text(s.get(name)), name + '须明确填写')
    if 'svg_height' in s:
        _require(isinstance(s['svg_height'], int) and not isinstance(s['svg_height'], bool)
                 and 350 <= s['svg_height'] <= 420, 'svg_height须为350至420的整数，保留可读字体与行距')
    t = s['chart_type']
    if t in {'dumbbell', 'slope'}:
        n = _labels(s.get('labels'), 'labels')
        _require(isinstance(s.get('series'), list) and len(s['series']) == 2, '差值图须恰好两组同口径数值')
        for group in s['series']:
            _require(isinstance(group, dict) and _text(group.get('name')), 'series须有名称')
            _numbers(group.get('values'), n, 'series.values')
        _require(s['series'][0]['name'] != s['series'][1]['name'], '两个比较组须有不同名称')
    elif t == 'heatmap':
        nr, nc = _labels(s.get('rows'), 'rows'), _labels(s.get('columns'), 'columns')
        _require(isinstance(s.get('values'), list) and len(s['values']) == nr, '热力矩阵行数不匹配')
        for row in s['values']:
            _require(isinstance(row, list) and len(row) == nc and all(v is None or _num(v) for v in row), '热力矩阵须为同形有限数或null')
        _require(any(v is not None for row in s['values'] for v in row), '热力矩阵不能全部缺失')
        if 'bases' in s:
            _require(isinstance(s['bases'], list) and len(s['bases']) == nr, 'bases行数不匹配')
            for row, bases in zip(s['values'], s['bases']):
                _require(isinstance(bases, list) and len(bases) == nc, 'bases须与values同形')
                _require(all((b is None and v is None) or (_num(b) and int(b) == b and b > 0)
                             for v, b in zip(row, bases)), 'bases须为正整数，缺失单元可用null')
    elif t == 'likert':
        n, levels = _labels(s.get('labels'), 'labels'), _labels(s.get('levels'), 'levels')
        _require(s.get('input') in {'count', 'percent'}, 'input须为count或percent')
        _numbers(s.get('bases'), n, 'bases', True, True)
        _require(all(v > 0 for v in s['bases']), 'Likert基数须为正整数')
        negative, neutral = s.get('negative_count'), s.get('neutral_index')
        _require(isinstance(negative, int) and not isinstance(negative, bool) and 0 < negative < levels, 'negative_count须明确负向等级个数')
        _require('neutral_index' in s and (neutral is None or
                 (isinstance(neutral, int) and not isinstance(neutral, bool) and neutral == negative and neutral < levels - 1)),
                 '中立等级须紧接负向等级，且其后保留正向等级；无中立时填null')
        tolerance = s.get('rounding_tolerance', 1e-6)
        _require(_num(tolerance) and 0 <= tolerance <= 1, 'rounding_tolerance须为0至1个百分点')
        _require(isinstance(s.get('values'), list) and len(s['values']) == n, 'Likert行数不匹配')
        for i, row in enumerate(s['values']):
            _numbers(row, levels, 'Likert.values', True, s['input'] == 'count')
            target = s['bases'][i] if s['input'] == 'count' else 100
            _require(abs(sum(row) - target) <= (1e-9 if s['input'] == 'count' else tolerance), 'Likert每行合计须等于基数或100%')
    elif t == 'histogram':
        if 'count_unit' in s:
            _require(_text(s['count_unit']), 'count_unit须为明确的频数单位')
        edges = s.get('edges')
        _require(isinstance(edges, list) and len(edges) >= 2 and all(_num(v) for v in edges) and
                 all(a < b for a, b in zip(edges, edges[1:])), '分箱边界须严格递增')
        _numbers(s.get('counts'), len(edges) - 1, 'counts', True, True)
        _require(_num(s.get('sample_size')) and s['sample_size'] > 0 and int(s['sample_size']) == s['sample_size']
                 and sum(s['counts']) == s['sample_size'], 'sample_size须等于各箱频数合计且大于零')
        if 'frequency_max' in s:
            heights = _histogram_heights(s)[1]
            _require(_num(s['frequency_max']) and s['frequency_max'] >= max(heights) and s['frequency_max'] > 0,
                     'frequency_max须覆盖实际柱高')
    elif t == 'boxplot':
        _require(isinstance(s.get('groups'), list) and s['groups'], '箱线图缺少groups')
        _labels([g.get('label') if isinstance(g, dict) else None for g in s['groups']], 'groups.label')
        for g in s['groups']:
            if 'values' in g:
                _require(isinstance(g['values'], list) and g['values'] and all(_num(v) for v in g['values']), '原始观测须为非空有限数值')
                _require(not any(k in g for k in ('n', 'low', 'q1', 'median', 'q3', 'high', 'outliers')), '同组不能混用原始观测与汇总统计')
            else:
                _require(_text(s.get('summary_definition')), '汇总箱线图须说明summary_definition')
                _require(_num(g.get('n')) and g['n'] > 0 and int(g['n']) == g['n'], '汇总样本量须为正整数')
                v = [g.get(k) for k in ('low', 'q1', 'median', 'q3', 'high')]
                _require(all(_num(x) for x in v) and all(a <= b for a, b in zip(v, v[1:])), '箱线统计须满足low≤q1≤median≤q3≤high')
                outliers = g.get('outliers', [])
                _require(isinstance(outliers, list) and all(_num(x) and (x < v[0] or x > v[-1]) for x in outliers), '离群点须在须线外')
                _require(len(outliers) < g['n'], '离群点数须小于样本量')
    elif t == 'ecdf':
        _require(isinstance(s.get('series'), list) and s['series'], 'ECDF缺少series')
        _labels([g.get('name') if isinstance(g, dict) else None for g in s['series']], 'series.name')
        for g in s['series']:
            _require(isinstance(g.get('values'), list) and g['values'] and all(_num(v) for v in g['values']), 'ECDF须使用非空原始观测')
    elif t in {'interval', 'band'}:
        n = _labels(s.get('labels'), 'labels')
        _require(_text(s.get('interval_label')), '须说明区间含义interval_label')
        central = 'estimates' if t == 'interval' else 'values'
        for key in (central, 'lower', 'upper'):
            _require(isinstance(s.get(key), list) and len(s[key]) == n, key + '长度不匹配')
        present = 0
        for estimate, lower, upper in zip(s[central], s['lower'], s['upper']):
            if t == 'band' and estimate is lower is upper is None:
                continue
            _require(all(_num(v) for v in (estimate, lower, upper)) and lower <= estimate <= upper,
                     '区间须满足lower≤中心值≤upper；带状图三值同时缺失')
            present += 1
        _require(present > 0, '区间数据不能全部缺失')
        if 'sample_sizes' in s:
            _numbers(s['sample_sizes'], n, 'sample_sizes', True, True)
            _require(all(v > 0 for v in s['sample_sizes']), 'sample_sizes须为正整数')
    elif t == 'tornado':
        n = _labels(s.get('labels'), 'labels')
        for key in ('low', 'high'):
            _numbers(s.get(key), n, key)
        _require(_num(s.get('baseline')), 'baseline须为有限数')
        _require(_labels(s.get('scenario_labels'), 'scenario_labels') == 2, 'scenario_labels须恰好两个情景名称')
    for key in ('min', 'max'):
        if key in s:
            _require(_num(s[key]), key + '须为有限数')
    data_min, data_max = _data_extent(s)
    if 'min' in s:
        _require(s['min'] <= data_min, 'min大于实际数据，会裁切数值')
    if 'max' in s:
        _require(s['max'] >= data_max, 'max小于实际数据，会裁切数值')
    if 'min' in s and 'max' in s:
        _require(s['min'] < s['max'], 'min须小于max')
    return s


def chart_model(s):
    """Return a fresh normalized model, retaining all observations in the source."""
    validate_spec(s)
    lo, hi = _data_extent(s)
    if lo == hi:
        pad = abs(lo) * .1 or 1
        lo, hi = lo - pad, hi + pad
    elif s['chart_type'] not in {'heatmap', 'histogram', 'likert', 'ecdf'}:
        pad = (hi - lo) * .08
        lo, hi = lo - pad, hi + pad
    if s['chart_type'] == 'likert':
        lo, hi = -100, 100
    model = {'type': s['chart_type'], 'min': s.get('min', lo), 'max': s.get('max', hi)}
    if s['chart_type'] == 'boxplot':
        model['groups'] = [box_summary(g) for g in s['groups']]
    elif s['chart_type'] == 'likert':
        model['rows'] = _likert_rows(s)
    elif s['chart_type'] == 'histogram':
        model['density'], model['heights'] = _histogram_heights(s)
        model['frequency_max'] = s.get('frequency_max', max(model['heights']) or 1)
    elif s['chart_type'] == 'ecdf':
        model['series'] = []
        for group in s['series']:
            values = sorted(group['values'])
            unique = sorted(set(values))
            counts = {v: 0 for v in unique}
            for value in values:
                counts[value] += 1
            total = 0
            points = []
            for value in unique:
                total += counts[value]
                points.append({'value': value, 'cumulative': total / len(values), 'count': counts[value]})
            model['series'].append({'name': group['name'], 'n': len(values), 'points': points})
    elif s['chart_type'] == 'band':
        segments, current = [], []
        for i, v in enumerate(s['values']):
            if v is None:
                if current:
                    segments.append(current)
                current = []
            else:
                current.append(i)
        if current:
            segments.append(current)
        model['segments'] = segments
    elif s['chart_type'] == 'tornado':
        model['rows'] = sorted([{'label': name, 'low': low, 'high': high, 'index': i,
                                'span': abs(high - low)} for i, (name, low, high) in
                               enumerate(zip(s['labels'], s['low'], s['high']))],
                              key=lambda row: -row['span'])
    return model


def _histogram_heights(s):
    widths = [b - a for a, b in zip(s['edges'], s['edges'][1:])]
    density = any(not math.isclose(v, widths[0], rel_tol=1e-9, abs_tol=1e-12) for v in widths[1:])
    return density, [count / width if density else count for count, width in zip(s['counts'], widths)]


def _category_key(s):
    t = s['chart_type']
    if t == 'heatmap':
        return s['rows'], s['columns']
    if t == 'likert':
        return s['labels'], s['levels'], s['negative_count'], s['neutral_index']
    if t == 'histogram':
        return s['edges']
    if t == 'boxplot':
        return [g['label'] for g in s['groups']]
    if t == 'ecdf':
        return [g['name'] for g in s['series']]
    if t == 'tornado':
        return [g['label'] for g in chart_model(s)['rows']]
    return s['labels']


def validate_small_multiples(s):
    _require(isinstance(s, dict) and s.get('type') == 'small_multiples', '小多图类型错误')
    _require(_text(s.get('id')) and _text(s.get('title')), '小多图须有id和title')
    _require(s.get('shared_scale') is True, '小多图须使用shared_scale:true')
    columns = s.get('columns', 2)
    _require(isinstance(columns, int) and not isinstance(columns, bool) and 1 <= columns <= 3, 'columns须为1至3')
    charts = s.get('charts')
    _require(isinstance(charts, list) and len(charts) >= 2, '小多图须至少两个子图')
    ids = []
    for chart in charts:
        validate_spec(chart)
        _require('min' in chart and 'max' in chart, '小多图各子图须显式提供min/max')
        ids.append(chart['id'])
    _require(len(set(ids + [s['id']])) == len(ids) + 1, '小多图及子图id不得重复')
    first = charts[0]
    key = _category_key(first)
    for chart in charts[1:]:
        _require(all(chart[k] == first[k] for k in ('chart_type', 'unit', 'min', 'max')), '小多图须同图式、同单位及同min/max')
        _require(_category_key(chart) == key, '小多图须保持相同类别与顺序')
        if chart['chart_type'] in {'dumbbell', 'slope'}:
            _require([v['name'] for v in chart['series']] == [v['name'] for v in first['series']], '小多图须保持比较组名称与顺序')
        if chart['chart_type'] == 'histogram':
            _require(chart_model(chart)['frequency_max'] == chart_model(first)['frequency_max'],
                     '直方小多图须以frequency_max明确统一纵轴上限')
    return s


class _SVG:
    def __init__(self):
        self.parts = []

    def element(self, tag, attrs, text=None):
        encoded = ' '.join(f'{key.replace("_", "-")}="{html.escape(str(value), quote=True)}"' for key, value in attrs.items())
        self.parts.append(f'<{tag} {encoded}/>' if text is None else f'<{tag} {encoded}>{html.escape(str(text))}</{tag}>')

    def text(self, x, y, value, size=16, color=INK, anchor='start', **extra):
        self.element('text', dict(x=x, y=y, fill=color, stroke='none', font_size=size,
                                 font_family=FONT, text_anchor=anchor, **extra), value)

    def line(self, x1, y1, x2, y2, color=GRID, width=1, **extra):
        self.element('line', dict(x1=x1, y1=y1, x2=x2, y2=y2, fill='none', stroke=color, stroke_width=width, **extra))

    def circle(self, x, y, color=BLUE, radius=5, **extra):
        self.element('circle', dict(cx=x, cy=y, r=radius, fill=color, stroke=color, stroke_width=1, **extra))

    def rect(self, x, y, width, height, color, **extra):
        self.element('rect', dict(x=x, y=y, width=max(width, 0), height=max(height, 0),
                                  fill=color, stroke='white', stroke_width=1, **extra))

    def poly(self, tag, points, color, fill='none', **extra):
        self.element(tag, dict(points=' '.join(f'{x:g},{y:g}' for x, y in points),
                               fill=fill, stroke=color, stroke_width=2, **extra))


def _fmt(v):
    return f'{v:.4g}'


def _axis(svg, left, top, width, height, lo, hi, vertical=False, percentage=False):
    for i in range(5):
        value = lo + (hi - lo) * i / 4
        if vertical:
            y = top + height * (1 - i / 4)
            svg.line(left, y, left + width, y)
            svg.text(left - 10, y + 5, _fmt(value) + ('%' if percentage else ''), 14, MUTED, 'end')
        else:
            x = left + width * i / 4
            svg.line(x, top, x, top + height)
            svg.text(x, top + height + 24, _fmt(value) + ('%' if percentage else ''), 14, MUTED, 'middle')
    svg.line(left, top + height, left + width, top + height, MUTED)


def render_svg(s):
    model = chart_model(s)
    t, lo, hi = s['chart_type'], model['min'], model['max']
    svg = _SVG()
    svg_height = s.get('svg_height', 420)
    bottom_offset = 420 - svg_height
    left, top, width, height = 164, 62, 650, svg_height - 148
    horizontal = t in {'dumbbell', 'boxplot', 'interval', 'tornado', 'likert'}
    x_min, x_max, y_min, y_max = (lo, hi, 0, 1) if horizontal or t in {'heatmap', 'histogram', 'ecdf'} else (0, 1, lo, hi)
    if t == 'histogram':
        y_max = model['frequency_max']
    if t == 'ecdf':
        y_max = 100
    x = lambda v: left + width * (v - lo) / (hi - lo)
    y = lambda v: top + height * (hi - v) / (hi - lo)
    svg.text(10, 24, '单位：' + s['unit'], 16)
    notes = []
    if t in {'dumbbell', 'slope'}:
        for j, group in enumerate(s['series']):
            svg.circle(535 + j * 165, 18, COLORS[j], 4)
            svg.text(546 + j * 165, 24, group['name'], 15)
    if horizontal:
        _axis(svg, left, top, width, height, lo, hi, percentage=t == 'likert')
    if t == 'dumbbell':
        stride = height / len(s['labels'])
        for i, label in enumerate(s['labels']):
            yy = top + stride * (i + .5)
            a, b = (group['values'][i] for group in s['series'])
            svg.text(left - 14, yy + 5, label, 16, INK, 'end')
            svg.line(x(a), yy, x(b), yy, '#8ba6b2', 4, data_role='difference', data_category=label)
            for j, value in enumerate((a, b)):
                svg.circle(x(value), yy, COLORS[j], 5, data_role='point', data_value=value, data_category=label, data_series=s['series'][j]['name'])
                svg.text(x(value), yy - 11 if j == 0 else yy + 23, _fmt(value), 15, COLORS[j], 'middle')
    elif t == 'slope':
        _axis(svg, left, top, width, height, lo, hi, True)
        xa, xb = left + 90, left + width - 90
        for j, xx in enumerate((xa, xb)):
            svg.line(xx, top, xx, top + height, MUTED)
            svg.text(xx, top + height + 27, s['series'][j]['name'], 16, INK, 'middle')
        for i, label in enumerate(s['labels']):
            a, b = (group['values'][i] for group in s['series'])
            color = COLORS[i % len(COLORS)]
            svg.line(xa, y(a), xb, y(b), color, 2.5, data_role='data-mark', data_kind='slope', data_category=label, data_start=a, data_end=b)
            for xx, value in ((xa, a), (xb, b)):
                svg.circle(xx, y(value), color, 4, data_role='data-mark', data_kind='point', data_value=value, data_category=label)
            svg.text(xa - 10, y(a) + 5, label + ' ' + _fmt(a), 15, color, 'end')
            svg.text(xb + 10, y(b) + 5, _fmt(b), 15, color)
    elif t == 'heatmap':
        nr, nc = len(s['rows']), len(s['columns'])
        cw, rh = width / nc, height / nr
        for j, label in enumerate(s['columns']):
            svg.text(left + cw * (j + .5), top - 12, label, 15, INK, 'middle')
        for i, row in enumerate(s['values']):
            svg.text(left - 12, top + rh * (i + .5) + 5, s['rows'][i], 16, INK, 'end')
            for j, value in enumerate(row):
                color = '#edf1f3' if value is None else _heat_color((value - lo) / (hi - lo))
                svg.rect(left + cw * j, top + rh * i, cw, rh, color, data_role='cell',
                         data_row=s['rows'][i], data_column=s['columns'][j], data_value='null' if value is None else value)
                label = '缺失' if value is None else _fmt(value)
                svg.text(left + cw * (j + .5), top + rh * (i + .5) + (1 if 'bases' in s else 5), label, 18,
                         'white' if value is not None and (value - lo) / (hi - lo) > .56 else INK, 'middle')
                if 'bases' in s and value is not None:
                    svg.text(left + cw * (j + .5), top + rh * (i + .5) + 21, 'n=' + str(s['bases'][i][j]), 12,
                             'white' if (value - lo) / (hi - lo) > .56 else MUTED, 'middle')
        for i in range(10):
            svg.rect(left + i * 17, top + height + 22, 17, 11, _heat_color(i / 9))
        svg.text(left + 182, top + height + 33, f'统一色阶：{_fmt(lo)} 至 {_fmt(hi)}；灰色表示缺失', 14, MUTED)
    elif t == 'likert':
        palette = ['#945b4d', '#c69079', '#c6d0d5', '#76abae', BLUE] if len(s['levels']) == 5 else [_heat_color(i / max(len(s['levels']) - 1, 1)) for i in range(len(s['levels']))]
        step = height / len(s['labels'])
        for i, row in enumerate(model['rows']):
            yy, bar = top + step * (i + .2), step * .55
            svg.text(left - 14, yy + bar * .55, s['labels'][i], 15, INK, 'end')
            for j, seg in enumerate(row):
                svg.rect(x(seg['start']), yy, x(seg['end']) - x(seg['start']), bar, palette[j], data_role='segment',
                         data_category=s['labels'][i], data_level=seg['level'], data_value=seg['value'], data_start=seg['start'], data_end=seg['end'])
                if seg['value'] >= 6:
                    svg.text((x(seg['start']) + x(seg['end'])) / 2, yy + bar * .55 + 4, _fmt(seg['value']) + '%', 13,
                             INK if j == s['neutral_index'] else 'white', 'middle')
            svg.text(824, yy + bar * .55, 'n=' + str(s['bases'][i]), 13, MUTED)
        svg.line(x(0), top, x(0), top + height, MUTED, 1.5)
        for j, level in enumerate(s['levels']):
            xx = 15 + j * (870 / len(s['levels']))
            svg.rect(xx, 376 - bottom_offset, 12, 12, palette[j])
            svg.text(xx + 18, 387 - bottom_offset, level, 13)
        notes.append('负向向左、正向向右；中立等级完整跨零居中，各占一半。' if s['neutral_index'] is not None else '负向向左、正向向右；零线分隔两种倾向。')
    elif t == 'histogram':
        edges, counts = s['edges'], s['counts']
        ymax = model['frequency_max']
        _axis(svg, left, top, width, height, 0, ymax, True)
        for i, count in enumerate(counts):
            xx, end = x(edges[i]), x(edges[i + 1])
            hh = height * model['heights'][i] / ymax
            svg.rect(xx, top + height - hh, end - xx, hh, BLUE, data_role='data-mark', data_kind='bin',
                     data_lower=edges[i], data_upper=edges[i + 1], data_value=count)
            svg.text((xx + end) / 2, top + height - hh - 9, str(count) + s.get('count_unit', '个'), 16, INK, 'middle')
        for edge in edges:
            svg.text(x(edge), top + height + 24, _fmt(edge), 14, MUTED, 'middle')
        count_unit = s.get('count_unit', '个')
        svg.text(10, 48, '纵轴：频数密度（' + count_unit + '/' + s['unit'] + '）' if model['density'] else '纵轴：频数（' + count_unit + '）', 14, MUTED)
        notes.append(f'n={s["sample_size"]}；分箱左闭右开，最后一箱含右端点；' + ('不等宽分箱以面积表达频数。' if model['density'] else '等宽分箱以高度表达频数。'))
    elif t == 'boxplot':
        step = height / len(model['groups'])
        for i, group in enumerate(model['groups']):
            yy, hh = top + step * (i + .5), min(step * .45, 40)
            svg.text(left - 12, yy + 5, group['label'], 15, INK, 'end')
            svg.line(x(group['low']), yy, x(group['high']), yy, BLUE, 2, data_role='whisker', data_category=group['label'])
            for key in ('low', 'high'):
                svg.line(x(group[key]), yy - hh * .35, x(group[key]), yy + hh * .35, BLUE, 2, data_role=key, data_value=group[key])
            svg.rect(x(group['q1']), yy - hh / 2, x(group['q3']) - x(group['q1']), hh, '#b9d8e1',
                     data_role='box', data_q1=group['q1'], data_q3=group['q3'])
            svg.line(x(group['median']), yy - hh / 2, x(group['median']), yy + hh / 2, BLUE, 3, data_role='median', data_value=group['median'])
            for j, outlier in enumerate(group['outliers']):
                svg.circle(x(outlier), yy + ((j % 3) - 1) * 5, GOLD, 4, data_role='outlier', data_value=outlier)
            svg.text(826, yy + 5, 'n=' + str(group['n']), 13, MUTED)
            svg.text(x(group['median']), yy - hh / 2 - 8, '中位 ' + _fmt(group['median']), 13, BLUE, 'middle')
        notes.append(s.get('summary_definition') or '分位数采用线性插值；须线止于1.5×四分位距内最远观测，金色点为保留的离群值。')
    elif t == 'ecdf':
        _axis(svg, left, top, width, height, 0, 100, True, True)
        for i in range(5):
            xx = left + width * i / 4
            svg.text(xx, top + height + 24, _fmt(lo + (hi - lo) * i / 4), 14, MUTED, 'middle')
        for j, group in enumerate(model['series']):
            color, cumulative = COLORS[j % len(COLORS)], 0
            points = [(x(lo), top + height)]
            for point in group['points']:
                xx = x(point['value'])
                points.extend([(xx, top + height * (1 - cumulative)), (xx, top + height * (1 - point['cumulative']))])
                cumulative = point['cumulative']
                svg.circle(xx, top + height * (1 - cumulative), color, 3, data_role='data-mark', data_kind='ecdf-point', data_value=point['value'], data_cumulative=cumulative, data_count=point['count'], data_series=group['name'])
            points.append((x(hi), top))
            svg.poly('polyline', points, color, data_role='data-mark', data_kind='ecdf-step', data_series=group['name'])
            svg.line(180 + j * 270, 19, 203 + j * 270, 19, color, 3)
            svg.text(212 + j * 270, 24, f'{group["name"]}（n={group["n"]}）', 14)
        svg.text(left + width / 2, top + height + 47, '横轴：观测值（' + s['unit'] + '）', 14, MUTED, 'middle')
        notes.append('纵轴为不超过横轴取值的观测比例；重复值在同一取值合并跳升，不连接为平滑曲线。')
    elif t == 'interval':
        step = height / len(s['labels'])
        for i, label in enumerate(s['labels']):
            yy = top + step * (i + .5)
            estimate, lower, upper = s['estimates'][i], s['lower'][i], s['upper'][i]
            svg.text(left - 12, yy + 5, label, 15, INK, 'end')
            svg.line(x(lower), yy, x(upper), yy, BLUE, 3, data_role='interval', data_category=label, data_lower=lower, data_upper=upper)
            for bound in (lower, upper):
                svg.line(x(bound), yy - 7, x(bound), yy + 7, BLUE, 2)
            svg.circle(x(estimate), yy, TEAL, 5, data_role='estimate', data_value=estimate, data_category=label)
            svg.text(x(estimate), yy - 13, f'{_fmt(estimate)} [{_fmt(lower)}, {_fmt(upper)}]', 13, INK, 'middle')
            if 'sample_sizes' in s:
                svg.text(826, yy + 5, 'n=' + str(s['sample_sizes'][i]), 13, MUTED)
        notes.append(s['interval_label'])
    elif t == 'band':
        _axis(svg, left, top, width, height, lo, hi, True)
        xp = lambda i: left + width * i / max(len(s['labels']) - 1, 1)
        for i, label in enumerate(s['labels']):
            svg.text(xp(i), top + height + 25, label, 14, MUTED, 'middle')
            if s['values'][i] is None:
                svg.text(xp(i), top + height * .55, '缺失', 14, MUTED, 'middle')
        for segment in model['segments']:
            if len(segment) > 1:
                polygon = [(xp(i), y(s['upper'][i])) for i in segment] + [(xp(i), y(s['lower'][i])) for i in reversed(segment)]
                svg.poly('polygon', polygon, '#b9d8e1', '#dcebef', data_role='band', data_start_index=segment[0], data_end_index=segment[-1])
                svg.poly('polyline', [(xp(i), y(s['values'][i])) for i in segment], BLUE, data_role='central-line')
            else:
                i = segment[0]
                svg.line(xp(i), y(s['lower'][i]), xp(i), y(s['upper'][i]), '#8ba6b2', 4, data_role='single-interval')
            for i in segment:
                svg.circle(xp(i), y(s['values'][i]), BLUE, 4, data_role='estimate', data_value=s['values'][i], data_lower=s['lower'][i], data_upper=s['upper'][i], data_category=s['labels'][i])
                svg.text(xp(i), y(s['values'][i]) - 10, _fmt(s['values'][i]), 14, BLUE, 'middle')
        notes.append(s['interval_label'] + '；缺失时期断开，带宽表示给定上下界。')
    elif t == 'tornado':
        step, baseline = height / len(model['rows']), s['baseline']
        svg.line(x(baseline), top, x(baseline), top + height, INK, 2, data_role='baseline', data_value=baseline)
        svg.text(x(baseline), top - 12, '基准 ' + _fmt(baseline), 14, INK, 'middle')
        for i, row in enumerate(model['rows']):
            yy, hh = top + step * (i + .2), min(step * .6, 36)
            svg.text(left - 12, yy + hh * .6, row['label'], 15, INK, 'end')
            # Parallel half-height bars keep reversed and same-side scenarios visible.
            for j, field in enumerate(('low', 'high')):
                value = row[field]
                svg.rect(min(x(baseline), x(value)), yy + j * hh / 2, abs(x(value) - x(baseline)), hh / 2,
                         COLORS[j], data_role='scenario', data_category=row['label'], data_scenario=s['scenario_labels'][j], data_value=value, data_baseline=baseline)
                svg.text(x(value) + (-6 if value < baseline else 6), yy + j * hh / 2 + hh / 2 - 1,
                         _fmt(value), 13, COLORS[j], 'end' if value < baseline else 'start')
        for j, label in enumerate(s['scenario_labels']):
            svg.rect(170 + j * 300, 375 - bottom_offset, 14, 12, COLORS[j])
            svg.text(192 + j * 300, 386 - bottom_offset, label, 14)
        notes.append('按两情景输出的绝对跨度降序排列；基准线为模型输出，参数名称与对应情景值保持绑定。')
    for i, note in enumerate(notes):
        svg.text(12, (411 if len(notes) == 1 else 395 + i * 18) - bottom_offset, note, 12, MUTED)
    attrs = {'xmlns': 'http://www.w3.org/2000/svg', 'viewBox': f'0 0 900 {svg_height}', 'role': 'img',
             'aria-label': s['title'], 'data-visual': t, 'data-chart-type': t, 'data-unit': s['unit'],
             'data-source': s['source'], 'data-x-min': x_min, 'data-x-max': x_max,
             'data-y-min': y_min, 'data-y-max': y_max, 'data-plot-left': left, 'data-plot-top': top,
             'data-plot-width': width, 'data-plot-height': height}
    attr_string = ' '.join(f'{k}="{html.escape(str(v), quote=True)}"' for k, v in attrs.items())
    return f'<svg {attr_string}>' + ''.join(svg.parts) + '</svg>'


def _heat_color(fraction):
    f = max(0, min(1, fraction))
    light, dark = (237, 244, 246), (39, 100, 127)
    return '#' + ''.join(f'{round(a + (b - a) * f):02x}' for a, b in zip(light, dark))


def chart_html(s):
    svg = render_svg(s)
    esc = lambda value: html.escape(str(value), quote=True)
    return (f'<figure class="report-chart" data-visual="{s["chart_type"]}" data-unit="{esc(s["unit"])}" data-source="{esc(s["source"])}">'
            f'<div class="chart-heading">{esc(s["title"])}<span>{esc(s["unit"])}</span></div>'
            f'<div class="native-chart analytical-chart" data-chart="{esc(json.dumps(s, ensure_ascii=False))}">{svg}</div>'
            f'<figcaption>{esc(s["source"])}</figcaption></figure>')


def small_multiples_html(s, canvas='16:9'):
    validate_small_multiples(s)
    columns = 1 if canvas in {'9:16', 'A4'} else s.get('columns', 2)
    esc = lambda value: html.escape(str(value), quote=True)
    # A4 stacks panels in one column. Shorten their plot spacing while keeping
    # the font sizes, horizontal numeric scale and complete explanations intact.
    charts = [dict(c, svg_height=min(c.get('svg_height', 420), 350)) for c in s['charts']] if canvas == 'A4' else s['charts']
    figures = ''.join(chart_html(c).replace('<figure ', '<figure id="' + esc(c['id']) + '" ', 1) for c in charts)
    return (f'<div class="small-multiples" data-visual="small_multiples" data-shared-scale="true">'
            f'<h2>{esc(s["title"])}</h2><div style="display:grid;grid-template-columns:repeat({columns},minmax(0,1fr));gap:20px">'
            f'{figures}</div></div>')
