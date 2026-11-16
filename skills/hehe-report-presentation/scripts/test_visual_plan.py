"""Regression checks for visual-plan enforcement and existing rendering paths."""
import json
import html
from pathlib import Path
import re
import tempfile
import unittest

from components import blocks_html, chart_html
from render_report import render
from visual_plan import validate_page

ASSETS = Path(__file__).resolve().parents[1] / 'assets'
NETWORK = '''<figure id="graphic" data-visual="network">
<div data-node="buyer">机器人公司支付采集费。</div>
<div data-node="supplier">采集企业交付数据。</div>
<svg viewBox="0 0 600 200"><path data-from="buyer" data-to="supplier" d="M10 20 H500" stroke="blue"/></svg>
<p>验收条件和付款时间按合同分别确认，完整解释保留。</p></figure>'''


def page(form='network', relation='flow'):
    return {'kind': 'content', 'title': '采集费与数据交付', 'lead': '采购方支付费用，采集企业按约定交付数据。',
            'body': NETWORK, 'visual_plan': {'relation': relation, 'message': '机器人公司付款，采集企业交付数据。',
            'form': form, 'target': 'graphic', 'explanation': '节点保留职责，图下保留验收说明。'}}


class VisualPlanTests(unittest.TestCase):
    def test_network(self):
        validate_page(page(), NETWORK, 1)

    def test_missing_plan(self):
        p = page(); del p['visual_plan']
        with self.assertRaisesRegex(ValueError, '缺少 visual_plan'):
            validate_page(p, NETWORK, 1)

    def test_table_and_icon_cannot_replace_network(self):
        alternatives = [
            '<figure id="graphic" data-visual="network"><table><tr><td>付款</td><td>交付</td></tr></table></figure>',
            '<div id="graphic" data-visual="network"><p>付款与交付。</p><svg><path d="M0 0 L3 3"/><circle r="2"/></svg></div>',
            '<div id="graphic" data-visual="network"><p>流程说明</p><svg></svg></div>',
            '<div id="graphic" data-visual="network"><div data-node="a">甲方</div><div data-node="b">乙方</div></div>',
        ]
        for body in alternatives:
            with self.subTest(body=body), self.assertRaisesRegex(ValueError, '未实现该图式'):
                validate_page(page(), body, 1)

    def test_broken_edge(self):
        with self.assertRaisesRegex(ValueError, '未实现该图式'):
            validate_page(page(), NETWORK.replace('data-to="supplier"', 'data-to="missing"'), 1)

    def test_empty_path_is_not_a_connector(self):
        with self.assertRaisesRegex(ValueError, '未实现该图式'):
            validate_page(page(), NETWORK.replace('M10 20 H500', ''), 1)

    def test_hidden_or_duplicate_target(self):
        for body in [NETWORK.replace('id="graphic"', 'id="graphic" hidden'), NETWORK + NETWORK]:
            with self.subTest(body=body), self.assertRaisesRegex(ValueError, '未唯一对应可见对象'):
                validate_page(page(), body, 1)

    def test_hidden_edges_and_defs_do_not_count(self):
        for body in [NETWORK.replace('<svg ', '<svg hidden '), NETWORK.replace('<path ', '<defs><path ').replace('</svg>', '</defs></svg>')]:
            with self.subTest(body=body), self.assertRaisesRegex(ValueError, '未实现该图式'):
                validate_page(page(), body, 1)

    def test_relation_form_mismatch(self):
        with self.assertRaisesRegex(ValueError, '不能由'):
            validate_page(page('table'), '<table id="graphic"><tr><td>文字</td></tr></table>', 1)

    def test_legitimate_prose_and_lookup(self):
        for form, relation, body in [('prose', 'narrative', '<p id="graphic">该结果适用于所述研究对象，理由如下。</p>'),
                                     ('table', 'lookup', '<table id="graphic"><tr><td>数量</td><td>价格</td></tr></table>')]:
            p = page(form, relation)
            with self.assertRaisesRegex(ValueError, 'reason'):
                validate_page(p, body, 1)
            p['visual_plan']['reason'] = '读者需要核对完整条件或逐项明细。'
            validate_page(p, body, 1)

    def test_decision_needs_visible_branch_conditions(self):
        body = NETWORK.replace('data-visual="network"', 'data-visual="decision"')
        body = body.replace('<p>', '<div data-node="third">反馈通过，继续交付。</div><p>', 1)
        body = body.replace('<p>', '<span data-connector="true" data-from="buyer" data-to="third" data-condition="反馈通过">反馈通过 →</span><p>', 1)
        body = body.replace('data-to="supplier"', 'data-to="supplier" data-condition="反馈失败"')
        with self.assertRaisesRegex(ValueError, '未实现该图式'):
            validate_page(page('decision', 'decision'), body, 1)
        validate_page(page('decision', 'decision'), body.replace('机器人公司支付采集费。', '反馈失败，进入适配。'), 1)

    def test_custom_numeric_marks(self):
        body = '<figure id="graphic" data-visual="waterfall" data-unit="万元"><svg><rect width="20" height="10" data-value="10"/><rect width="20" height="20" data-value="-20"/></svg><p>现金由10万元减至负10万元。</p></figure>'
        validate_page(page('waterfall', 'change'), body, 1)
        with self.assertRaisesRegex(ValueError, '未实现该图式'):
            validate_page(page('waterfall', 'change'), body.replace('data-value="10"', 'data-value="NaN"'), 1)

    def test_malformed_svg_nesting_is_not_visible_data(self):
        body = '<figure id="graphic" data-visual="waterfall" data-unit="万元"><svg><rect width="20" height="10"/ data-value="10"><text>10</text><rect width="20" height="20"/ data-value="-20"><text>-20</text></svg><p>完整解释。</p></figure>'
        with self.assertRaisesRegex(ValueError, '未实现该图式'):
            validate_page(page('waterfall', 'change'), body, 1)

    def test_bundled_examples_in_all_canvases(self):
        for file in ASSETS.glob('*.json'):
            data = json.loads(file.read_text(encoding='utf8'))
            for canvas in ['16:9', '9:16', 'A4', 'scroll']:
                for i, slide in enumerate(data.get('slides', []), 1):
                    with self.subTest(file=file.name, canvas=canvas, page=i):
                        body = blocks_html(slide['blocks'], canvas) if 'blocks' in slide else slide['body']
                        validate_page(slide, body, i)

    def test_render_gate_and_preserved_conversion(self):
        with tempfile.TemporaryDirectory(prefix='report-visual-plan-') as directory:
            root = Path(directory).resolve()
            self.assertTrue(root.is_relative_to(Path(tempfile.gettempdir()).resolve()))
            source, out = root/'source.json', root/'report.html'
            data = {'title': '测试', 'slides': [page()]}
            del data['slides'][0]['visual_plan']
            source.write_text(json.dumps(data, ensure_ascii=False), encoding='utf8')
            with self.assertRaisesRegex(ValueError, 'visual_plan'):
                render(source, out)
            self.assertFalse(out.exists())
            render(source, out, preserve_layout=True)
            self.assertIn('preserved-layout', out.read_text(encoding='utf8'))
            data['slides'] = [page()]
            source.write_text(json.dumps(data, ensure_ascii=False), encoding='utf8')
            render(source, out, replace=True)
            self.assertIn('visual-plan-checked', out.read_text(encoding='utf8'))
            original = out.read_bytes()
            del data['slides'][0]['visual_plan']
            source.write_text(json.dumps(data, ensure_ascii=False), encoding='utf8')
            with self.assertRaises(ValueError):
                render(source, out, replace=True)
            self.assertEqual(original, out.read_bytes())

    def test_markdown_sidebar_and_full_text(self):
        with tempfile.TemporaryDirectory(prefix='report-visual-md-') as directory:
            root = Path(directory).resolve()
            self.assertTrue(root.is_relative_to(Path(tempfile.gettempdir()).resolve()))
            source, out = root/'source.md', root/'report.html'
            source.write_text('# 采购研究\n\n## 采购条件\n\n这是完整条件说明，保留全部主语、条件和原因。\n\n[来源](https://example.com)\n', encoding='utf8')
            render(source, out)
            html = out.read_text(encoding='utf8')
            for text in ['report-sidebar', '这是完整条件说明，保留全部主语、条件和原因。', 'https://example.com', 'preserved-layout']:
                self.assertIn(text, html)
            self.assertNotIn('id="download"', html)


def native(form='bar', groups=None, **changes):
    spec = {'chart_type': form, 'labels': ['甲', '乙'], 'unit': '万元', 'source': '教学数据'}
    if form == 'waterfall':
        spec.update(labels=['期初', '增加', '减少', '期末'], values=[10, 5, -3, 12])
    else:
        spec['series'] = [{'name': '系列' + str(i + 1), 'values': values}
                          for i, values in enumerate(groups if groups is not None else [[10, 20]])]
    spec.update(changes)
    return spec, '<div id="graphic">' + chart_html(spec) + '</div>'


def replace_native_spec(body, spec):
    return re.sub(r'data-chart="[^"]*"', lambda _: 'data-chart="' + html.escape(json.dumps(spec), quote=True) + '"', body)


class ExistingGraphGateTests(unittest.TestCase):
    RELATION = {'bar': 'comparison', 'hbar': 'comparison', 'line': 'trend',
                'stacked': 'composition', 'waterfall': 'change'}

    def reject(self, form, body, relation=None):
        with self.assertRaisesRegex(ValueError, '未实现该图式'):
            validate_page(page(form, relation or self.RELATION.get(form, 'flow')), body, 1)

    def test_reviewed_empty_native_wrapper_and_invisible_edge_are_rejected(self):
        self.reject('bar', '<figure id="graphic"><div class="native-chart" data-chart=\'{"chart_type":"bar"}\'><svg></svg></div></figure>')
        self.reject('network', NETWORK.replace('stroke="blue"', 'stroke="none" opacity="0"'))

    def test_native_generated_single_multi_series_negative_and_zero_cases(self):
        for form, relation in self.RELATION.items():
            alternatives = [native(form)]
            if form != 'waterfall':
                alternatives.extend([native(form, [[5, 10], [10, 20]]),
                                     native(form, [[0, 20]]), native(form, [[0, 0]]),
                                     native(form, [[0, 0], [0, 0]]),
                                     native(form, [[4]], labels=['甲']),
                                     native(form, [[0]], labels=['甲'])])
            else:
                alternatives.extend([native(form, values=[0, 0, 0, 0]),
                                     native(form, values=[10, 0, -3, 7]),
                                     native(form, labels=['期初'], values=[10]),
                                     native(form, labels=['期初'], values=[0])])
            if form == 'hbar':
                alternatives.extend([native(form, [[-10, 20]]),
                                     native(form, [[-10, -20], [0, -15]]),
                                     native(form, [[0, 0]], value_suffix='%')])
            for spec, body in alternatives:
                with self.subTest(form=form, spec=spec):
                    self.assertNotIn('data-value=', body)
                    validate_page(page(form, relation), body, 1)

    def test_native_svg_must_contain_actual_marks(self):
        for form in self.RELATION:
            _, body = native(form)
            for svg in ['<svg></svg>', '<svg><text>只有图表标题</text></svg>',
                        '<svg><line x1="0" x2="100" stroke="black"/></svg>']:
                with self.subTest(form=form, svg=svg):
                    self.reject(form, re.sub(r'<svg\b.*?</svg>', svg, body, flags=re.S))

    def test_native_data_schema_and_finite_values_are_required(self):
        for form in self.RELATION:
            spec, body = native(form)
            invalid = [None, [], {'chart_type': form}, {**spec, 'labels': []},
                       {**spec, 'labels': '甲乙'}, {**spec, 'max': 0}, {**spec, 'max': float('nan')}]
            if form == 'waterfall':
                invalid.extend([{**spec, 'values': [10, 5, -3, 13]}, {**spec, 'totals': [1, 3]},
                                {**spec, 'totals': [0, 9]}, {**spec, 'values': [10]}])
                invalid.extend({**spec, 'values': [10, 5, bad, 12]} for bad in [True, None, '3', float('nan'), float('inf')])
            else:
                invalid.extend([{**spec, 'series': []}, {**spec, 'series': [{'values': [10, 20]}]},
                                {**spec, 'series': [{'name': '系列', 'values': [10]}]}])
                invalid.extend({**spec, 'series': [{'name': '系列', 'values': [10, bad]}]}
                               for bad in [True, None, '20', float('nan'), float('inf')])
            for data in invalid:
                with self.subTest(form=form, data=data):
                    self.reject(form, replace_native_spec(body, data))
            self.reject(form, re.sub(r'data-chart="[^"]*"', 'data-chart="invalid-json"', body))

    def test_native_hidden_transparent_and_degenerate_marks_are_rejected(self):
        for form in self.RELATION:
            _, body = native(form)
            alternatives = [body.replace('<svg ', '<svg opacity="0" ', 1),
                            body.replace('<svg ', '<svg style="opacity:0" ', 1),
                            body.replace('<svg ', '<svg visibility="hidden" ', 1),
                            body.replace('<svg ', '<svg width="0" ', 1)]
            if form == 'line':
                alternatives.extend([body.replace('r="4"', 'r="0"'),
                                     body.replace('<circle ', '<circle opacity="0" '),
                                     body.replace('<polyline ', '<polyline stroke-opacity="0" '),
                                     body.replace('<polyline ', '<polyline hidden ')])
            else:
                alternatives.extend([body.replace('<rect ', '<rect opacity="0" '),
                                     re.sub(r'(<rect\b[^>]*?)fill="[^"]*"', r'\1fill="none"', body),
                                     re.sub(r'(<rect\b[^>]*?)(width|height)="[^"]*"', r'\1\2="0"', body, count=1)])
            for alternative in alternatives:
                with self.subTest(form=form, body=alternative):
                    self.reject(form, alternative)

    def test_native_bar_dimensions_must_represent_data(self):
        for form in ['bar', 'hbar', 'stacked', 'waterfall']:
            _, body = native(form)
            dimension = 'width' if form == 'hbar' else 'height'
            altered = re.sub(r'(<rect\b[^>]*?\b' + dimension + r'=\")([^\"]+)',
                             lambda match: match[1] + str(float(match[2]) * 2), body, count=1)
            with self.subTest(form=form):
                self.reject(form, altered)

    def test_native_values_stay_bound_to_categories_and_series(self):
        for form in ['bar', 'hbar', 'stacked']:
            spec, body = native(form, [[10, 20], [30, 40]])
            body = re.sub(r' aria-label="[^"]*"', '', body)
            for groups in [[[20, 10], [30, 40]], [[30, 40], [10, 20]]]:
                changed = {**spec, 'series': [{'name': series['name'], 'values': values}
                                            for series, values in zip(spec['series'], groups)]}
                with self.subTest(form=form, groups=groups):
                    self.reject(form, replace_native_spec(body, changed))
        spec, body = native('waterfall', values=[10, 5, -3, 12])
        body = re.sub(r' aria-label="[^"]*"', '', body)
        self.reject('waterfall', replace_native_spec(body, {**spec, 'values': [10, -3, 5, 12]}))

    def test_native_existing_description_binds_category_and_series_names(self):
        for form, relation in self.RELATION.items():
            spec, body = native(form)
            changed = {**spec, 'labels': ['丙'] + spec['labels'][1:]}
            with self.subTest(form=form, changed='category name'):
                self.reject(form, replace_native_spec(body, changed))
            if form != 'waterfall':
                changed = {**spec, 'series': [{**spec['series'][0], 'name': '另一系列'}]}
                with self.subTest(form=form, changed='series name'):
                    self.reject(form, replace_native_spec(body, changed))
            validate_page(page(form, relation), re.sub(r' aria-label="[^"]*"', '', body), 1)

    def test_native_zero_baseline_direction_and_cumulative_positions(self):
        for form, groups in [('bar', None), ('hbar', [[-10, 20]]),
                             ('stacked', [[10, 20], [30, 40]]), ('waterfall', None)]:
            _, body = native(form, groups)
            axis = 'x' if form == 'hbar' else 'y'
            shifted = re.sub(r'(<rect\b[^>]*?\b' + axis + r'=\")([^\"]+)',
                             lambda match: match[1] + str(float(match[2]) + 15), body, count=1)
            with self.subTest(form=form):
                self.reject(form, shifted)

    def test_negative_only_hbar_accepts_zero_upper_limit_with_valid_range(self):
        spec, body = native('hbar', [[-10, -20]], max=0)
        validate_page(page('hbar', 'comparison'), body, 1)
        for maximum in [-30, -5, float('nan'), True]:
            with self.subTest(maximum=maximum):
                self.reject('hbar', replace_native_spec(body, {**spec, 'max': maximum}))
        _, zeros = native('hbar', [[0, 0]])
        zero_spec, _ = native('hbar', [[0, 0]])
        self.reject('hbar', replace_native_spec(zeros, {**zero_spec, 'max': 0}))

    def test_native_line_must_join_the_actual_points(self):
        _, body = native('line')
        self.reject('line', re.sub(r'<polyline\b[^>]*/>', '', body))
        self.reject('line', re.sub(r'(<polyline\b[^>]*\bpoints=")[^"]*', r'\g<1>0,0 5,5', body))
        self.reject('line', replace_native_spec(body, {**native('line')[0], 'series': [{'name': '反向数据', 'values': [20, 10]}]}))

    def test_existing_graph_render_gate_rejects_without_overwriting(self):
        with tempfile.TemporaryDirectory(prefix='report-existing-graph-gate-') as directory:
            source, out = Path(directory) / 'source.json', Path(directory) / 'report.html'
            _, valid = native('bar')
            slide = page('bar', 'comparison')
            slide['body'] = valid
            source.write_text(json.dumps({'title': '门禁回归', 'slides': [slide]}, ensure_ascii=False), encoding='utf8')
            render(source, out)
            original = out.read_bytes()
            alternatives = [('bar', 'comparison', re.sub(r'<svg\b.*?</svg>', '<svg></svg>', valid)),
                            ('network', 'flow', NETWORK.replace('stroke="blue"', 'stroke="none" opacity="0"'))]
            for form, relation, body in alternatives:
                slide = page(form, relation)
                slide['body'] = body
                source.write_text(json.dumps({'title': '门禁回归', 'slides': [slide]}, ensure_ascii=False), encoding='utf8')
                with self.subTest(form=form), self.assertRaisesRegex(ValueError, '未实现该图式'):
                    render(source, out, replace=True)
                self.assertEqual(original, out.read_bytes())

    def test_relationship_edges_need_visible_paint_and_nonzero_geometry(self):
        for form, relation in [('network', 'flow'), ('structure', 'structure'), ('flow', 'flow')]:
            original = NETWORK.replace('data-visual="network"', 'data-visual="' + form + '"')
            alternatives = [original.replace('stroke="blue"', attribute) for attribute in [
                'stroke="none"', 'stroke="transparent"', 'stroke="rgba(0,0,0,0)"',
                'stroke="#12345600"', 'stroke="blue" stroke-width="0"', 'stroke="blue" stroke-opacity="0"',
                'stroke="blue" opacity="0"', 'stroke="blue" style="opacity:0"',
                'stroke="currentColor" style="color:transparent"', 'stroke="blue" visibility="hidden"',
                'stroke="blue" style="stroke:none!important"', 'stroke="blue" style="stroke:inherit"']]
            alternatives.extend(original.replace('<svg ', '<svg ' + attr + ' ', 1)
                                for attr in ['opacity="0"', 'style="opacity:0"', 'visibility="hidden"', 'transform="scale(0)"'])
            alternatives.extend(original.replace('M10 20 H500', geometry) for geometry in [
                'M10 20 H10', 'M10 20 L10 20', 'M10 20 C10 20 10 20 10 20',
                'M10 20 M50 50', 'M10 20 LNaN 50', 'L10 20'])
            for alternative in alternatives:
                with self.subTest(form=form, body=alternative):
                    self.reject(form, alternative, relation)

    def test_legitimate_curved_inherited_and_transformed_connectors_remain_valid(self):
        alternatives = [NETWORK.replace('M10 20 H500', geometry) for geometry in [
            'M10 20 L500 20', 'M10 20 h490', 'M10 20 C80 5 200 80 500 20',
            'M10 20 Q80 5 500 20', 'M10 20 A20 20 0 0 1 500 20']]
        alternatives.extend([NETWORK.replace('<svg ', '<svg stroke="blue" opacity="0.5" ', 1).replace(' stroke="blue"/>', '/>'),
                             NETWORK.replace('<svg ', '<svg transform="translate(10 10)" ', 1),
                             NETWORK.replace('<svg ', '<svg style="opacity:50%" ', 1),
                             NETWORK.replace('stroke="blue"', 'stroke="blue" stroke-width="2px"'),
                             NETWORK.replace('stroke="blue"', 'stroke="blue" opacity="0" style="opacity:1"')])
        for body in alternatives:
            with self.subTest(body=body):
                validate_page(page(), body, 1)

    def test_html_connectors_preserve_visible_arrows_and_reject_transparency(self):
        arrow = '<span data-connector="true" data-from="buyer" data-to="supplier">付款 →</span>'
        body = re.sub(r'<svg\b.*?</svg>', arrow, NETWORK)
        validate_page(page(), body, 1)
        validate_page(page(), body.replace('<span ', '<span style="opacity:0.5;color:blue" ', 1), 1)
        for style in ['opacity:0', 'color:transparent', 'color:rgba(0,0,0,0)', 'display:none', 'visibility:hidden']:
            with self.subTest(style=style):
                self.reject('network', body.replace('<span ', '<span style="' + style + '" ', 1))
        self.reject('network', body.replace(arrow, '<div style="opacity:0">' + arrow + '</div>'))

    def test_decision_and_timeline_cannot_use_invisible_connectors(self):
        decision = NETWORK.replace('data-visual="network"', 'data-visual="decision"').replace(
            '<p>', '<div data-node="third">审核通过</div><span>通过，退回</span><p>', 1).replace(
            'data-to="supplier"', 'data-to="supplier" data-condition="退回"').replace(
            '</svg>', '<path data-from="buyer" data-to="third" data-condition="通过" d="M10 30 H500" stroke="blue"/></svg>')
        validate_page(page('decision', 'decision'), decision, 1)
        self.reject('decision', decision.replace('stroke="blue"', 'stroke="none"'), 'decision')
        timeline = NETWORK.replace('data-visual="network"', 'data-visual="timeline"').replace(
            'data-node="buyer"', 'data-node="buyer" data-order="1"').replace(
            'data-node="supplier"', 'data-node="supplier" data-order="2"')
        validate_page(page('timeline', 'sequence'), timeline, 1)
        self.reject('timeline', timeline.replace('stroke="blue"', 'stroke="none"'), 'sequence')

    def test_new_business_fixture_assets_in_all_canvases(self):
        expected = {'relationship_examples.json': 6, 'execution_examples.json': 5}
        for name, pages in expected.items():
            source = ASSETS / name
            self.assertTrue(source.is_file(), name)
            data = json.loads(source.read_text(encoding='utf8'))
            self.assertEqual(pages, len(data['slides']), name)
            for canvas in ['16:9', '9:16', 'A4', 'scroll']:
                for i, slide in enumerate(data['slides'], 1):
                    with self.subTest(asset=name, canvas=canvas, page=i):
                        body = blocks_html(slide['blocks'], canvas) if 'blocks' in slide else slide['body']
                        validate_page(slide, body, i)



def special(form, svg, attributes=''):
    return (f'<figure id="graphic" data-visual="{form}" data-source="教学台账" {attributes}>'
            f'<svg viewBox="0 0 140 140">{svg}</svg>'
            '<figcaption>教学台账。边界来自教学地图。收入亿元，增速%，数量个。'
            '甲、乙按相同口径比较；完整解释与有效条件保留。</figcaption></figure>')


AXES = ('<line data-axis="x" x1="10" y1="110" x2="110" y2="110" stroke="black"/>'
        '<line data-axis="y" x1="10" y1="110" x2="10" y2="10" stroke="black"/>')
SCATTER = special('scatter', AXES +
    '<circle data-point="甲" data-x="2" data-y="4" cx="30" cy="90" r="3"/>'
    '<ellipse data-point="乙" data-x="8" data-y="16" cx="90" cy="30" rx="3" ry="4"/>',
    'data-x-unit="亿元" data-y-unit="%" data-x-min="0" data-x-max="10" data-y-min="0" data-y-max="20"')
QUADRANT = SCATTER.replace('data-visual="scatter"', 'data-visual="quadrant" data-x-threshold="5" data-y-threshold="10"').replace(
    '</svg>', '<line data-divider="x" x1="60" y1="110" x2="60" y2="10" stroke="gray"/>'
              '<line data-divider="y" x1="10" y1="60" x2="110" y2="60" stroke="gray"/></svg>')
REGIONS = ('<polygon data-region="甲区" points="0,0 100,0 0,100" fill="#ddd" data-value="4"/>'
           '<path data-region="乙区" d="M100 0 L100 100 L0 100 Z" fill="#55a" data-value="16"/>')
CHOROPLETH = special('choropleth', REGIONS, 'data-map-source="教学地图" data-unit="个"')
BUBBLE_MAP = special('bubble_map', REGIONS +
    '<circle data-point="甲" data-lon="2" data-lat="3" data-value="4" cx="20" cy="70" r="4" fill="blue"/>'
    '<circle data-point="乙" data-lon="8" data-lat="7" data-value="16" cx="80" cy="30" r="8" fill="blue"/>',
    'data-map-source="教学地图" data-unit="个" data-projection="equirectangular" '
    'data-lon-min="0" data-lon-max="10" data-lat-min="0" data-lat-max="10" data-map-box="0 0 100 100"')
DONUT = special('donut',
    '<circle data-category="甲" data-value="25" cx="60" cy="60" r="30" fill="none" stroke="blue" stroke-width="10" '
    'stroke-dasharray="47.1238898 141.3716694" stroke-dashoffset="0"/>'
    '<circle data-category="乙" data-value="75" cx="60" cy="60" r="30" fill="none" stroke="red" stroke-width="10" '
    'stroke-dasharray="141.3716694 47.1238898" stroke-dashoffset="-47.1238898"/>',
    'data-total="100" data-unit="%"')
DUAL_AXIS = special('dual_axis', AXES.replace('data-axis="y"', 'data-axis="left"') +
    '<line data-axis="right" x1="110" y1="110" x2="110" y2="10" stroke="black"/>'
    '<rect data-series="收入" data-category="甲" data-value="40" x="20" y="70" width="20" height="40"/>'
    '<rect data-series="收入" data-category="乙" data-value="80" x="70" y="30" width="20" height="80"/>'
    '<circle data-series="增速" data-category="甲" data-value="4" cx="30" cy="90" r="3"/>'
    '<circle data-series="增速" data-category="乙" data-value="16" cx="80" cy="30" r="3"/>'
    '<polyline data-series="增速" points="30,90 80,30" fill="none" stroke="red"/>',
    'data-left-unit="亿元" data-right-unit="%" data-left-series="收入" data-right-series="增速" '
    'data-left-min="0" data-left-max="100" data-right-min="0" data-right-max="20"')
SPECIALS = [
    ('scatter', 'correlation', SCATTER), ('quadrant', 'correlation', QUADRANT),
    ('quadrant', 'positioning', QUADRANT), ('choropleth', 'geography', CHOROPLETH),
    ('bubble_map', 'geography', BUBBLE_MAP), ('donut', 'composition', DONUT),
    ('dual_axis', 'trend', DUAL_AXIS),
]


class QuantitativeVisualPlanTests(unittest.TestCase):
    def assert_rejected(self, form, relation, body):
        with self.assertRaisesRegex(ValueError, '未实现该图式'):
            validate_page(page(form, relation), body, 1)

    def test_new_relation_forms_have_real_svg_routes(self):
        for form, relation, body in SPECIALS:
            with self.subTest(form=form, relation=relation):
                validate_page(page(form, relation), body, 1)

    def test_text_images_tables_and_empty_svg_do_not_count(self):
        for form, relation, original in SPECIALS:
            start, _, remainder = original.partition('<svg ')
            _, _, finish = remainder.partition('</svg>')
            for replacement in ['<svg></svg>', '<img src="plot.png" alt="图表"/>',
                                '<table><tr><td data-value="4">4</td><td data-value="16">16</td></tr></table>',
                                '<div data-point="甲" data-x="2" data-y="4">甲</div>']:
                with self.subTest(form=form, replacement=replacement):
                    self.assert_rejected(form, relation, start + replacement + finish)

    def test_hidden_defs_opacity_and_no_paint_do_not_count(self):
        for form, relation, body in SPECIALS:
            alternatives = [
                body.replace('<svg ', '<svg hidden ', 1),
                body.replace('<svg ', '<svg style="opacity:0" ', 1),
                body.replace('<svg viewBox="0 0 140 140">', '<svg viewBox="0 0 140 140"><defs>').replace('</svg>', '</defs></svg>'),
                body.replace('<svg ', '<svg fill="none" stroke="none" ', 1).replace('fill="blue"', 'fill="none"').replace(
                    'fill="#ddd"', 'fill="none"').replace('fill="#55a"', 'fill="none"').replace(
                    'stroke="black"', 'stroke="none"').replace('stroke="gray"', 'stroke="none"').replace(
                    'stroke="red"', 'stroke="none"').replace('stroke="blue"', 'stroke="none"'),
            ]
            for i, alternative in enumerate(alternatives):
                with self.subTest(form=form, variant=i):
                    self.assert_rejected(form, relation, alternative)

    def test_non_svg_offscreen_and_unresolved_effects_do_not_count(self):
        for form, relation, body in SPECIALS:
            alternatives = [
                body.replace('<svg ', '<div ', 1).replace('</svg>', '</div>'),
                body.replace('viewBox="0 0 140 140"', 'viewBox="1000 1000 10 10"'),
                body.replace('<svg ', '<svg width="0.00" ', 1),
                body.replace('<svg ', '<svg transform="scale(0)" ', 1),
                body.replace('<svg ', '<svg style="clip-path:url(#hidden)" ', 1),
                body.replace('<svg ', '<svg><foreignObject><svg-not-real ', 1).replace('</svg>', '</svg-not-real></foreignObject></svg>'),
            ]
            for i, alternative in enumerate(alternatives):
                with self.subTest(form=form, variant=i):
                    self.assert_rejected(form, relation, alternative)

    def test_transparent_data_marks_do_not_count(self):
        for form, relation, body in [
            ('scatter', 'correlation', SCATTER.replace('<svg ', '<svg fill="rgba(0,0,0,0)" ', 1)),
            ('choropleth', 'geography', CHOROPLETH.replace('fill="#55a"', 'fill="#12345600"')),
            ('bubble_map', 'geography', BUBBLE_MAP.replace('fill="blue"', 'fill="rgb(0 0 0 / 0)"')),
            ('donut', 'composition', DONUT.replace('stroke="red"', 'stroke="#1230"')),
        ]:
            with self.subTest(form=form):
                self.assert_rejected(form, relation, body)

    def test_source_and_units_must_be_present_and_visible(self):
        for form, relation, body in SPECIALS:
            for alternative in [body.replace('data-source="教学台账"', 'data-source="未展示的来源"'),
                                body.replace('data-source="教学台账"', '')]:
                with self.subTest(form=form):
                    self.assert_rejected(form, relation, alternative)
        for form, relation, body, key in [
            ('scatter', 'correlation', SCATTER, 'data-x-unit'),
            ('donut', 'composition', DONUT, 'data-unit'),
            ('choropleth', 'geography', CHOROPLETH, 'data-map-source'),
            ('dual_axis', 'trend', DUAL_AXIS, 'data-right-unit'),
        ]:
            self.assert_rejected(form, relation, body.replace(key + '="', key + '="不存在的'))

    def test_transparent_source_text_or_ancestors_do_not_count(self):
        for form, relation, body in SPECIALS:
            for replacement in [
                '<figcaption style="opacity:0">',
                '<figcaption><span style="opacity:0">',
                '<figcaption style="opacity:0"><span style="opacity:1">',
                '<figcaption style="color:transparent">',
                '<figcaption><span style="color:rgba(0,0,0,0)">',
            ]:
                hidden = body.replace('<figcaption>', replacement)
                if '<span' in replacement:
                    hidden = hidden.replace('</figcaption>', '</span></figcaption>')
                with self.subTest(form=form, replacement=replacement):
                    self.assert_rejected(form, relation, hidden)

    def test_transparent_svg_source_text_and_group_do_not_count(self):
        source = SCATTER.replace('教学台账。', '').replace('</svg>', '<text x="10" y="130">教学台账</text></svg>')
        validate_page(page('scatter', 'correlation'), source, 1)
        for old, new in [
            ('<text ', '<text opacity="0" '),
            ('<text ', '<text style="fill:transparent" '),
            ('<text ', '<text fill-opacity="0" '),
            ('<text ', '<text fill="currentColor" style="color:transparent" '),
            ('<text ', '<g opacity="0"><text '),
            ('<text ', '<g style="opacity:0"><text style="opacity:1" '),
        ]:
            hidden = source.replace(old, new)
            if '<g ' in new:
                hidden = hidden.replace('</text>', '</text></g>')
            with self.subTest(replacement=new):
                self.assert_rejected('scatter', 'correlation', hidden)

    def test_partly_transparent_text_still_counts_as_visible_evidence(self):
        for form, relation, body in SPECIALS:
            visible = body.replace('<figcaption>', '<figcaption style="opacity:0.5; color:rgba(0,0,0,0.5)">')
            validate_page(page(form, relation), visible, 1)
        colored = SCATTER.replace('<figcaption>', '<figcaption style="color:transparent"><span style="color:black">').replace('</figcaption>', '</span></figcaption>')
        validate_page(page('scatter', 'correlation'), colored, 1)

    def test_scatter_requires_axes_finite_data_and_scaled_points(self):
        for old, new in [
            ('data-axis="y"', 'data-axis="missing"'), ('data-y="4"', 'data-y="NaN"'),
            ('data-x="2"', 'data-x="11"'), ('cx="30"', 'cx="35"'),
            ('r="3"', 'r="0"'), ('rx="3"', 'rx="0"'),
            ('data-point="乙"', 'data-point="甲"'), ('data-x-max="10"', 'data-x-max="0"'),
        ]:
            with self.subTest(change=(old, new)):
                self.assert_rejected('scatter', 'correlation', SCATTER.replace(old, new))

    def test_quadrant_requires_real_correct_threshold_lines(self):
        for old, new in [
            ('data-divider="x"', 'data-divider="missing"'),
            ('data-x-threshold="5"', 'data-x-threshold="10"'),
            ('data-y-threshold="10"', 'data-y-threshold="NaN"'),
            ('x1="60"', 'x1="65"'),
        ]:
            with self.subTest(change=(old, new)):
                self.assert_rejected('quadrant', 'positioning', QUADRANT.replace(old, new))

    def test_map_requires_closed_non_degenerate_region_geometry(self):
        for old, new in [
            ('points="0,0 100,0 0,100"', 'points="0,0 50,50 100,100"'),
            ('d="M100 0 L100 100 L0 100 Z"', 'd="M100 0 L100 100 L0 100"'),
            ('d="M100 0 L100 100 L0 100 Z"', 'd=""'),
            ('data-region="乙区"', 'data-region="甲区"'),
        ]:
            with self.subTest(change=(old, new)):
                self.assert_rejected('choropleth', 'geography', CHOROPLETH.replace(old, new))
        body = special('choropleth',
            '<rect data-region="甲区" x="0" y="0" width="20" height="20" data-value="4" fill="red"/>'
            '<rect data-region="乙区" x="30" y="30" width="20" height="20" data-value="16" fill="blue"/>',
            'data-map-source="教学地图" data-unit="个"')
        self.assert_rejected('choropleth', 'geography', body)

    def test_choropleth_requires_numeric_values_and_visible_encoding(self):
        for old, new in [('data-value="4"', 'data-value="Infinity"'), ('fill="#55a"', 'fill="#ddd"'),
                         ('fill="#55a"', 'fill="none"')]:
            with self.subTest(change=(old, new)):
                self.assert_rejected('choropleth', 'geography', CHOROPLETH.replace(old, new))

    def test_bubbles_require_geographic_positions_and_proportional_area(self):
        for old, new in [
            ('data-lon="2"', 'data-lon="NaN"'), ('data-lat="3"', 'data-lat="30"'),
            ('data-value="16" cx="80"', 'data-value="0" cx="80"'),
            ('cx="20"', 'cx="30"'), ('r="8"', 'r="6"'),
            ('data-map-box="0 0 100 100"', 'data-map-box="0 0 0 100"'),
        ]:
            with self.subTest(change=(old, new)):
                self.assert_rejected('bubble_map', 'geography', BUBBLE_MAP.replace(old, new))

    def test_donut_requires_actual_ring_segments_matching_values(self):
        for old, new in [
            ('data-value="25"', 'data-value="-25"'), ('data-total="100"', 'data-total="120"'),
            ('stroke-dasharray="47.1238898 141.3716694"', 'stroke-dasharray="1 187.4955592"'),
            ('stroke-dashoffset="-47.1238898"', 'stroke-dashoffset="0"'),
            ('stroke-width="10"', 'stroke-width="70"'),
            ('fill="none"', 'fill="black"'),
        ]:
            with self.subTest(change=(old, new)):
                self.assert_rejected('donut', 'composition', DONUT.replace(old, new))

    def test_dual_axis_requires_both_series_scales_and_actual_line(self):
        for old, new in [
            ('data-axis="right"', 'data-axis="missing"'),
            ('data-right-max="20"', 'data-right-max="10"'),
            ('data-value="40"', 'data-value="NaN"'),
            ('height="80"', 'height="60"'), ('points="30,90 80,30"', 'points="30,90 80,50"'),
            ('points="30,90 80,30"', 'points=""'), ('data-category="乙" data-value="16"', 'data-category="甲" data-value="16"'),
        ]:
            with self.subTest(change=(old, new)):
                self.assert_rejected('dual_axis', 'trend', DUAL_AXIS.replace(old, new))

    def test_uniform_values_and_alternative_projection_are_valid(self):
        cases = [
            ('choropleth', 'geography', CHOROPLETH.replace('data-value="16"', 'data-value="4"').replace('fill="#55a"', 'fill="#ddd"')),
            ('bubble_map', 'geography', BUBBLE_MAP.replace('data-value="16"', 'data-value="4"').replace('r="8"', 'r="4"')),
            ('bubble_map', 'geography', BUBBLE_MAP.replace('data-projection="equirectangular"', 'data-projection="Mercator"')),
            ('donut', 'composition', DONUT.replace('stroke="red"', 'stroke="blue"')),
        ]
        for form, relation, body in cases:
            with self.subTest(form=form, body=body):
                validate_page(page(form, relation), body, 1)

    def test_scatter_and_quadrant_can_record_data_without_numeric_scale(self):
        for form, body in [('scatter', SCATTER), ('quadrant', QUADRANT)]:
            for attr in [' data-x-min="0"', ' data-x-max="10"', ' data-y-min="0"', ' data-y-max="20"']:
                body = body.replace(attr, '')
            validate_page(page(form, 'correlation'), body, 1)
            if form == 'quadrant':
                self.assert_rejected(form, 'correlation', body.replace('x1="60" y1="110"', 'x1="60" y1="50"'))

    def test_new_forms_retain_render_gate(self):
        with tempfile.TemporaryDirectory(prefix='report-new-visuals-') as directory:
            source, out = Path(directory) / 'source.json', Path(directory) / 'report.html'
            slides = []
            for form, relation, body in SPECIALS:
                slide = page(form, relation)
                slide['body'] = body
                slides.append(slide)
            source.write_text(json.dumps({'title': '新图式回归', 'slides': slides}, ensure_ascii=False), encoding='utf8')
            render(source, out)
            original = out.read_bytes()
            slides[0]['body'] = SCATTER.replace('data-y="4"', 'data-y="NaN"')
            source.write_text(json.dumps({'title': '新图式回归', 'slides': slides}, ensure_ascii=False), encoding='utf8')
            with self.assertRaisesRegex(ValueError, '未实现该图式'):
                render(source, out, replace=True)
            self.assertEqual(original, out.read_bytes())

if __name__ == '__main__':
    unittest.main(verbosity=2)
