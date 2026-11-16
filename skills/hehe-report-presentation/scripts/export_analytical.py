"""Export analytical charts as native editable PowerPoint objects.

The shared SVG defines geometry, labels and colours.  Slope, ECDF and equal-bin
histograms use native data charts when their plot geometry can be preserved.
Other charts use native shapes and text; they are deliberately not described as
workbook-editable charts.  No analytical chart is rasterized.
"""
import json
import math
import re

from lxml import etree
from pptx.chart.data import CategoryChartData, XyChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_MARKER_STYLE, XL_TICK_LABEL_POSITION
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_AUTO_SIZE, MSO_ANCHOR, PP_ALIGN
from pptx.oxml.xmlchemy import OxmlElement
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

from analytical_charts import TYPES, chart_model, render_svg, validate_spec


_SVG_TAGS = {'svg', 'rect', 'line', 'circle', 'polyline', 'polygon', 'text', 'tspan'}
_PALETTE = ['#27647f', '#208e91', '#b78647', '#8ba6b2']


def _pos(px):
    return Inches(px / 96)


def _number(value, default=0):
    if value is None:
        return default
    value = float(value)
    if not math.isfinite(value):
        raise ValueError('分析图表 SVG 坐标必须是有限数')
    return value


def _colour(value):
    """Return (RGBColor or None, opacity), retaining transparent paint."""
    value = (value or 'none').strip().lower()
    if value in {'none', 'transparent'}:
        return None, 0
    if value.startswith('#'):
        value = value[1:]
        if len(value) == 3:
            value = ''.join(ch * 2 for ch in value)
        return RGBColor.from_string(value.upper()), 1
    if value in {'white', 'black'}:
        return RGBColor.from_string('FFFFFF' if value == 'white' else '000000'), 1
    if value.startswith(('rgb(', 'rgba(')):
        parts = re.findall(r'[\d.]+', value)
        return RGBColor(*(round(float(x)) for x in parts[:3])), float(parts[3]) if len(parts) > 3 else 1
    raise ValueError(f'分析图表 SVG 颜色不支持：{value}')


def _alpha(solid_fill, opacity):
    colour = solid_fill.find(qn('a:srgbClr'))
    if colour is not None and opacity < 1:
        alpha = OxmlElement('a:alpha')
        alpha.set('val', str(round(max(0, opacity) * 100000)))
        colour.append(alpha)


def _paint(shape, node, scale):
    opacity = _number(node.get('opacity'), 1)
    colour, alpha = _colour(node.get('fill', 'none'))
    if colour is None:
        shape.fill.background()
    else:
        shape.fill.solid()
        shape.fill.fore_color.rgb = colour
        _alpha(shape._element.spPr.find(qn('a:solidFill')), alpha * opacity * _number(node.get('fill-opacity'), 1))
    colour, alpha = _colour(node.get('stroke', 'none'))
    if colour is None or _number(node.get('stroke-width'), 1) <= 0:
        shape.line.fill.background()
    else:
        shape.line.color.rgb = colour
        shape.line.width = Pt(_number(node.get('stroke-width'), 1) * scale * .75)
        line = shape._element.spPr.find(qn('a:ln'))
        _alpha(line.find(qn('a:solidFill')), alpha * opacity * _number(node.get('stroke-opacity'), 1))
        if node.get('stroke-dasharray') not in {None, 'none', ''}:
            shape.line.dash_style = MSO_LINE_DASH_STYLE.DASH
        if node.get('stroke-linecap') == 'round':
            line.set('cap', 'rnd')


def _provenance(shape, spec, node=None, source=False):
    props = shape._element.find(qn('p:spPr'))
    if props is not None and props.find(qn('a:effectLst')) is None:
        # PowerPoint's theme otherwise gives newly added shapes/connectors a
        # shadow, even though the shared analytical SVG has flat paint.
        props.append(OxmlElement('a:effectLst'))
    tag = etree.QName(node).localname if node is not None else 'data-chart'
    metadata = {'chart_id': spec.get('id', ''), 'chart_type': spec['chart_type']}
    if node is not None:
        metadata.update({k: v for k, v in node.attrib.items() if k.startswith('data-')})
    if source:
        metadata['source_spec'] = spec
    shape.name = f"{spec.get('id', spec['chart_type'])}/{metadata.get('data-role', tag)}"
    shape._element.find('.//' + qn('p:cNvPr')).set('descr', json.dumps(metadata, ensure_ascii=False, separators=(',', ':')))


def _textbox(slide, node, point, scale, spec, inherited=None):
    """SVG uses an alphabetic baseline; PPT text uses a top-aligned frame."""
    attrs = dict(inherited or {})
    attrs.update(node.attrib)
    text = node.text or ''
    created = []
    if text:
        font_size = _number(attrs.get('font-size'), 14) * scale
        x, baseline = point(_number(attrs.get('x')), _number(attrs.get('y')))
        # An ample no-wrap frame keeps the complete text editable.  Alignment
        # around the SVG anchor does not depend on a guessed character width.
        width = max(font_size * 4, len(text) * font_size * 1.2)
        anchor = attrs.get('text-anchor', 'start')
        left = x - (width / 2 if anchor == 'middle' else width if anchor == 'end' else 0)
        shape = slide.shapes.add_textbox(_pos(left), _pos(baseline - font_size * 1.02), _pos(width), _pos(font_size * 1.8))
        frame = shape.text_frame
        frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
        frame.word_wrap = False
        frame.auto_size = MSO_AUTO_SIZE.NONE
        frame.vertical_anchor = MSO_ANCHOR.TOP
        para = frame.paragraphs[0]
        para.space_before = para.space_after = Pt(0)
        para.line_spacing = Pt(font_size * .75)
        para.alignment = {'middle': PP_ALIGN.CENTER, 'end': PP_ALIGN.RIGHT}.get(anchor, PP_ALIGN.LEFT)
        para._p.get_or_add_pPr().set('eaLnBrk', '1')
        run = para.add_run()
        run.text = text
        run.font.size = Pt(font_size * .75)
        run.font.name = attrs.get('font-family', 'Microsoft YaHei').split(',')[0].strip('"\' ')
        run.font.bold = attrs.get('font-weight', '400') in {'bold', '600', '700', '800', '900'}
        colour, opacity = _colour(attrs.get('fill', '#344c59'))
        if colour is not None:
            run.font.color.rgb = colour
        ea = OxmlElement('a:ea')
        ea.set('typeface', run.font.name)
        run._r.get_or_add_rPr().append(ea)
        _provenance(shape, spec, node)
        created.append(shape)
    for child in node:
        child_attrs = dict(attrs)
        child_attrs.update(child.attrib)
        # Shared renderer currently emits explicit tspan x/y, if present.
        # Reject implicit positioning rather than silently stacking runs.
        if child.get('x') is None or child.get('y') is None:
            raise ValueError('分析图表 PPT tspan 需要显式 x/y 坐标')
        created.extend(_textbox(slide, child, point, scale, spec, child_attrs))
    return created


def _points(node):
    values = [_number(v) for v in re.split(r'[\s,]+', node.get('points', '').strip()) if v]
    if len(values) < 4 or len(values) % 2:
        raise ValueError('分析图表 SVG 多边线坐标不完整')
    return list(zip(values[::2], values[1::2]))


def _shape(slide, node, point, scale, spec):
    tag = etree.QName(node).localname
    if tag == 'text':
        return _textbox(slide, node, point, scale, spec)
    if tag in {'line', 'polyline', 'polygon'}:
        points = [(_number(node.get('x1')), _number(node.get('y1'))), (_number(node.get('x2')), _number(node.get('y2')))] if tag == 'line' else _points(node)
        points = [point(x, y) for x, y in points]
        if tag == 'line':
            shape = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, *[_pos(v) for p in points for v in p])
            # Connectors have line paint only.
            colour, opacity = _colour(node.get('stroke', 'none'))
            if colour is None:
                shape.line.fill.background()
            else:
                shape.line.color.rgb = colour
                shape.line.width = Pt(_number(node.get('stroke-width'), 1) * scale * .75)
                line = shape._element.spPr.find(qn('a:ln'))
                _alpha(line.find(qn('a:solidFill')), opacity * _number(node.get('opacity'), 1) * _number(node.get('stroke-opacity'), 1))
                if node.get('stroke-dasharray') not in {None, 'none', ''}:
                    shape.line.dash_style = MSO_LINE_DASH_STYLE.DASH
        else:
            # Build in 1/1000 px local units to retain sub-pixel data positions.
            builder = slide.shapes.build_freeform(points[0][0] * 1000, points[0][1] * 1000, scale=9525 / 1000)
            builder.add_line_segments([(x * 1000, y * 1000) for x, y in points[1:]], close=tag == 'polygon')
            shape = builder.convert_to_shape()
            _paint(shape, node, scale)
    else:
        if tag == 'rect':
            x, y = point(_number(node.get('x')), _number(node.get('y')))
            width = _number(node.get('width')) * scale
            height = _number(node.get('height')) * scale
            kind = MSO_SHAPE.RECTANGLE
        elif tag == 'circle':
            radius = _number(node.get('r'))
            x, y = point(_number(node.get('cx')) - radius, _number(node.get('cy')) - radius)
            width = height = radius * 2 * scale
            kind = MSO_SHAPE.OVAL
        else:
            raise ValueError(f'分析图表 SVG 不支持图元：{tag}')
        shape = slide.shapes.add_shape(kind, _pos(x), _pos(y), _pos(max(.001, width)), _pos(max(.001, height)))
        _paint(shape, node, scale)
    _provenance(shape, spec, node)
    return [shape]


def _transparent_chart(chart):
    for parent in [chart._chartSpace, chart._chartSpace.chart.plotArea]:
        props = parent.find(qn('c:spPr'))
        if props is None:
            props = OxmlElement('c:spPr')
            following = next((child for child in parent if etree.QName(child).localname in {'txPr', 'externalData', 'printSettings', 'userShapes', 'extLst'}), None)
            if following is None:
                parent.append(props)
            else:
                following.addprevious(props)
        props.append(OxmlElement('a:noFill'))
        line = OxmlElement('a:ln')
        line.append(OxmlElement('a:noFill'))
        props.append(line)
    chart.has_legend = chart.has_title = False
    # python-pptx 1.0.2 lacks ScatterChart._remove_dLbls; remove the optional
    # label element directly, without changing its generated data-series XML.
    plot = chart.plots[0]._element
    labels = plot.find(qn('c:dLbls'))
    if labels is not None:
        plot.remove(labels)
    for axis in [chart.category_axis, chart.value_axis]:
        axis.visible = False
        axis.has_major_gridlines = False
        axis.tick_label_position = XL_TICK_LABEL_POSITION.NONE
    # With axes and labels supplied by SVG shapes, the inner plot fills exactly
    # the SVG data rectangle rather than using Office's automatic margins.
    area = chart._chartSpace.chart.plotArea
    layout = area.find(qn('c:layout'))
    if layout is None:
        layout = OxmlElement('c:layout')
        area.insert(0, layout)
    manual = OxmlElement('c:manualLayout')
    for tag, value in [('layoutTarget', 'inner'), ('xMode', 'factor'), ('yMode', 'factor'), ('wMode', 'factor'), ('hMode', 'factor'), ('x', '0'), ('y', '0'), ('w', '1'), ('h', '1')]:
        element = OxmlElement('c:' + tag)
        element.set('val', value)
        manual.append(element)
    layout.append(manual)


def _native_plot(slide, spec, root, point, scale):
    """Return native frame when the declared SVG plot has compatible geometry."""
    kind = spec['chart_type']
    required = ['data-plot-left', 'data-plot-top', 'data-plot-width', 'data-plot-height', 'data-x-min', 'data-x-max', 'data-y-min', 'data-y-max']
    if kind not in {'slope', 'ecdf', 'histogram'} or any(root.get(k) is None for k in required):
        return None
    left, top, width, height, xmin, xmax, ymin, ymax = [_number(root.get(k)) for k in required]
    if not width > 0 or not height > 0 or not xmax > xmin or not ymax > ymin:
        return None
    marks = [node for node in root if node.get('data-role') == 'data-mark']
    if not marks:
        return None
    x, y = point(left, top)
    colours = []
    if kind == 'histogram':
        edges = spec['edges']
        stride = edges[1] - edges[0]
        if any(not math.isclose(b - a, stride, rel_tol=1e-9, abs_tol=1e-9) for a, b in zip(edges, edges[1:])) or not math.isclose(xmin, edges[0]) or not math.isclose(xmax, edges[-1]):
            return None
        data = CategoryChartData()
        data.categories = [f'[{a:g}, {b:g}{"]" if i == len(edges) - 2 else ")"}' for i, (a, b) in enumerate(zip(edges, edges[1:]))]
        data.add_series('频数', spec['counts'])
        chart_type = XL_CHART_TYPE.COLUMN_CLUSTERED
        colours.append(marks[0].get('fill', _PALETTE[0]))
    else:
        data = XyChartData()
        chart_type = XL_CHART_TYPE.XY_SCATTER_LINES
        lines = [node for node in marks if etree.QName(node).localname in {'line', 'polyline'}]
        if not lines:
            return None
        expected = len(spec['labels']) if kind == 'slope' else len(spec['series'])
        if len(lines) != expected:
            return None
        for index, node in enumerate(lines):
            coords = _points(node) if etree.QName(node).localname == 'polyline' else [(_number(node.get('x1')), _number(node.get('y1'))), (_number(node.get('x2')), _number(node.get('y2')))]
            name = spec['labels'][index] if kind == 'slope' else spec['series'][index]['name']
            series = data.add_series(name)
            if kind == 'slope':
                for endpoint, (px, py) in enumerate(coords):
                    # The native workbook keeps the exact source values;
                    # synthetic x positions retain the SVG endpoint inset.
                    series.add_data_point(xmin + (px - left) / width * (xmax - xmin), spec['series'][endpoint]['values'][index])
            else:
                cumulative = 0
                series.add_data_point(xmin, 0)
                for item in chart_model(spec)['series'][index]['points']:
                    series.add_data_point(item['value'], cumulative * 100)
                    cumulative = item['cumulative']
                    series.add_data_point(item['value'], cumulative * 100)
                series.add_data_point(xmax, 100)
            colours.append(node.get('stroke', _PALETTE[index % len(_PALETTE)]))
    frame = slide.shapes.add_chart(chart_type, _pos(x), _pos(y), _pos(width * scale), _pos(height * scale), data)
    chart = frame.chart
    _transparent_chart(chart)
    chart.value_axis.minimum_scale = ymin
    chart.value_axis.maximum_scale = ymax
    if kind == 'histogram':
        chart.plots[0].gap_width = 0
    else:
        chart.category_axis.minimum_scale = xmin
        chart.category_axis.maximum_scale = xmax
    for index, series in enumerate(chart.series):
        rgb, _ = _colour(colours[index])
        series.format.fill.solid()
        series.format.fill.fore_color.rgb = rgb
        if kind == 'histogram':
            series.format.line.fill.background()
            series.invert_if_negative = False
        else:
            line_nodes = [node for node in marks if etree.QName(node).localname in {'line', 'polyline'}]
            series.format.line.color.rgb = rgb
            series.format.line.width = Pt(_number(line_nodes[index].get('stroke-width'), 2) * scale * .75)
            series.marker.style = XL_MARKER_STYLE.NONE
            circles = [node for node in marks if etree.QName(node).localname == 'circle']
            if circles:
                series.marker.style = XL_MARKER_STYLE.CIRCLE
                series.marker.size = max(2, min(72, round(_number(circles[0].get('r'), 4) * scale * 1.5)))
                series.marker.format.fill.solid()
                series.marker.format.fill.fore_color.rgb = rgb
                series.marker.format.line.color.rgb = rgb
                if kind == 'ecdf':
                    # Only jump endpoints are observed values; intermediate
                    # step corners and range endpoints have no point marker.
                    for point_index, data_point in enumerate(series.points):
                        if point_index == 0 or point_index % 2 or point_index == len(series.points) - 1:
                            data_point.marker.style = XL_MARKER_STYLE.NONE
    _provenance(frame, spec, source=True)
    return frame


def add_analytical_chart(slide, a):
    """Add one analytical chart and return a truthful editability manifest."""
    spec = a['spec']
    if spec.get('chart_type') not in TYPES:
        raise ValueError(f"未知分析图表：{spec.get('chart_type')}")
    validate_spec(spec)
    root = etree.fromstring(render_svg(spec).encode('utf-8'), parser=etree.XMLParser(resolve_entities=False, no_network=True))
    for node in root.iter():
        if etree.QName(node).localname not in _SVG_TAGS or node.get('transform') is not None:
            raise ValueError('分析图表 PPT 仅支持无 transform 的直接坐标图元')
    viewbox = [_number(v) for v in root.get('viewBox', '').split()]
    if len(viewbox) != 4 or viewbox[2] <= 0 or viewbox[3] <= 0:
        raise ValueError('分析图表 SVG 需要有效 viewBox')
    vx, vy, vw, vh = viewbox
    scale = min(a['w'] / vw, a['h'] / vh)
    ox = a['x'] + (a['w'] - vw * scale) / 2
    oy = a['y'] + (a['h'] - vh * scale) / 2
    point = lambda x, y: (ox + (x - vx) * scale, oy + (y - vy) * scale)
    start = len(slide.shapes)
    native = _native_plot(slide, spec, root, point, scale)
    text_count = shape_count = 0
    plot_layered = False
    for node in root:
        if native is not None and node.get('data-role') == 'data-mark':
            if not plot_layered:
                # Preserve SVG paint order: the data plot sits above its grid,
                # while later annotations remain above the native chart.
                tree = slide.shapes._spTree
                tree.remove(native._element)
                tree.insert_element_before(native._element, 'p:extLst')
                plot_layered = True
            continue
        objects = _shape(slide, node, point, scale, spec)
        text_count += sum(obj.has_text_frame and bool(obj.text) for obj in objects)
        shape_count += sum(not obj.has_text_frame or not obj.text for obj in objects)
    if native is None and len(slide.shapes) > start:
        # Complete source data remains recoverable even for shape-only output.
        _provenance(slide.shapes[start], spec, root, source=True)
    result = {
        'id': spec.get('id', ''), 'chart_type': spec['chart_type'],
        'editable': 'data_editable' if native is not None else 'shape_editable',
        'native_charts': int(native is not None), 'native_shapes': shape_count,
        'native_texts': text_count, 'images': 0,
        'source_data': '完整数据保留在源JSON及PPT对象说明',
    }
    if native is not None:
        result['editable_scope'] = '数据工作簿中的绘图系列可编辑；坐标、图例、类别和注释为可编辑形状/文本'
        result['update_note'] = '修改PPT系列数据后，外置数值注释和尺度不自动更新；修改源JSON并重新生成可完整同步'
        if spec['chart_type'] == 'ecdf':
            result['data_note'] = '工作簿保存实际阶梯点；原始观测保留在源JSON及PPT对象说明'
    else:
        result['editable_scope'] = '逐个形状和文本可编辑；无关联数据工作簿'
        result['update_note'] = '数值修改需同步调整形状位置，或修改源JSON并重新生成'
        result['reason'] = '原生形状保持区间宽度、排序、分段或组合图形与HTML一致'
    return result
