"""Adversarial checks of real analytical marks, scales, text and panel binding."""
from copy import deepcopy
import html
import json
from pathlib import Path
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET

from analytical_charts import TYPES
from components import blocks_html
from render_report import render
from visual_plan import validate_page


def fixture(form):
    spec = {'type': 'chart', 'id': 'graphic', 'chart_type': form,
            'title': '可核对的分析图', 'unit': '分', 'source': '合成教学数据'}
    if form in {'dumbbell', 'slope'}:
        spec.update(labels=['对象甲', '对象乙'], series=[
            {'name': '之前', 'values': [12, 21]}, {'name': '之后', 'values': [19, 15]}])
    elif form == 'heatmap':
        spec.update(rows=['对象甲', '对象乙'], columns=['服务', '体验'],
                    values=[[12, None], [21, 15]], bases=[[20, None], [30, 25]])
    elif form == 'likert':
        spec.update(labels=['服务', '体验'], levels=['不满意', '中立', '满意'],
                    values=[[20, 30, 50], [40, 10, 50]], input='count', bases=[100, 100],
                    neutral_index=1, negative_count=1)
    elif form == 'histogram':
        spec.update(edges=[0, 2, 5, 10], counts=[2, 5, 3], sample_size=10)
    elif form == 'boxplot':
        spec.update(groups=[{'label': '对象甲', 'values': [1, 2, 2, 3, 4, 20]},
                            {'label': '对象乙', 'values': [2, 3, 5, 6, 8]}])
    elif form == 'ecdf':
        spec.update(series=[{'name': '对象甲', 'values': [1, 2, 2, 4]},
                            {'name': '对象乙', 'values': [1, 3, 5]}])
    elif form == 'interval':
        spec.update(labels=['对象甲', '对象乙'], estimates=[12, 21], lower=[8, 17],
                    upper=[17, 25], interval_label='95%置信区间', sample_sizes=[100, 80])
    elif form == 'band':
        spec.update(labels=['一期', '二期', '三期', '四期', '五期'],
                    values=[12, 18, None, 17, 20], lower=[8, 14, None, 13, 16],
                    upper=[16, 22, None, 21, 24], interval_label='95%预测区间')
    elif form == 'tornado':
        spec.update(labels=['销量', '价格', '成本'], low=[80, 90, 110], high=[130, 115, 85],
                    baseline=100, scenario_labels=['参数下界', '参数上界'])
    return spec


RELATION = {'dumbbell': 'comparison', 'slope': 'trend', 'heatmap': 'comparison',
            'likert': 'composition', 'histogram': 'distribution', 'boxplot': 'distribution',
            'ecdf': 'distribution', 'interval': 'uncertainty', 'band': 'uncertainty',
            'tornado': 'comparison'}


def page(form, relation=None):
    return {'kind': 'content', 'title': '分析图校验', 'lead': '图形须准确表达已确认的数值与类别。', 'visual_plan': {
        'relation': relation or RELATION[form], 'message': '比较所列对象及其已确认数值。',
        'form': form, 'target': 'graphic', 'explanation': '图后可见正文保留解释和条件。'}}


def body(spec, canvas='16:9'):
    return blocks_html([spec], canvas)


def replace_spec(markup, spec, index=0):
    matches = list(re.finditer(r'data-chart="[^"]*"', markup))
    match = matches[index]
    replacement = 'data-chart="' + html.escape(json.dumps(spec, ensure_ascii=False), quote=True) + '"'
    return markup[:match.start()] + replacement + markup[match.end():]


def change_svg(markup, tag, change, index=0, predicate=lambda node: True):
    matches = list(re.finditer(r'<svg\b.*?</svg>', markup, re.S))
    match = matches[index]
    root = ET.fromstring(match[0])
    ET.register_namespace('', 'http://www.w3.org/2000/svg')
    node = next(node for node in root.iter() if node.tag.split('}')[-1] == tag and predicate(node))
    change(node)
    updated = ET.tostring(root, encoding='unicode')
    return markup[:match.start()] + updated + markup[match.end():]


def small(form='interval'):
    first, second = fixture(form), fixture(form)
    first.update(id='panel-a', title='人群甲', min=0, max=30)
    second.update(id='panel-b', title='人群乙', min=0, max=30)
    return {'type': 'small_multiples', 'id': 'graphic', 'title': '两组使用同一尺度',
            'charts': [first, second], 'columns': 2, 'shared_scale': True}


class AnalyticalVisualPlanTests(unittest.TestCase):
    def reject(self, form, markup, relation=None):
        with self.assertRaisesRegex(ValueError, '未实现该图式'):
            validate_page(page(form, relation), markup, 1)

    def test_all_ten_types_and_four_canvases(self):
        self.assertEqual(set(RELATION), set(TYPES))
        for form in TYPES:
            for canvas in ['16:9', '9:16', 'A4', 'scroll']:
                with self.subTest(form=form, canvas=canvas):
                    validate_page(page(form), body(fixture(form), canvas), 1)

    def test_extended_relation_routes(self):
        routes = {'comparison': ['dumbbell', 'slope', 'heatmap', 'likert', 'tornado'],
                  'distribution': ['histogram', 'boxplot', 'ecdf', 'likert', 'heatmap'],
                  'trend': ['slope', 'band'], 'uncertainty': ['interval', 'band'],
                  'composition': ['likert', 'heatmap']}
        for relation, forms in routes.items():
            for form in forms:
                with self.subTest(form=form, relation=relation):
                    validate_page(page(form, relation), body(fixture(form)), 1)
        with self.assertRaisesRegex(ValueError, '不能由'):
            validate_page(page('histogram', 'uncertainty'), body(fixture('histogram')), 1)

    def test_data_drift_is_rejected_even_when_svg_metadata_is_unchanged(self):
        for form in TYPES:
            original = fixture(form)
            updated = deepcopy(original)
            if form in {'dumbbell', 'slope', 'ecdf'}:
                updated['series'][0]['values'][0] += 1
            elif form in {'heatmap', 'likert'}:
                updated['values'][0][0] += 1
                if form == 'likert':
                    updated['values'][0][-1] -= 1
            elif form == 'histogram':
                updated['counts'][0] += 1
                updated['counts'][1] -= 1
            elif form == 'boxplot':
                updated['groups'][0]['values'][2] += .5
            elif form == 'interval':
                updated['estimates'][0] += 1
            elif form == 'band':
                updated['values'][0] += 1
            else:
                updated['low'][0] += 1
            with self.subTest(form=form):
                self.reject(form, replace_spec(body(original), updated))

    def test_endpoint_bin_width_proportion_box_and_band_geometry(self):
        operations = {
            'dumbbell': ('circle', lambda node: node.set('cx', str(float(node.get('cx')) + 15))),
            'slope': ('line', lambda node: node.set('y2', str(float(node.get('y2')) + 15))),
            'heatmap': ('rect', lambda node: node.set('fill', '#ff0000')),
            'likert': ('rect', lambda node: node.set('width', str(float(node.get('width')) * .7))),
            'histogram': ('rect', lambda node: node.set('width', str(float(node.get('width')) * .7))),
            'boxplot': ('rect', lambda node: node.set('width', str(float(node.get('width')) + 15))),
            'ecdf': ('polyline', lambda node: node.set('points', node.get('points') + ' 400,50')),
            'interval': ('line', lambda node: node.set('x2', str(float(node.get('x2')) + 15))),
            'band': ('polygon', lambda node: node.set('points', node.get('points') + ' 400,50')),
            'tornado': ('rect', lambda node: node.set('width', str(float(node.get('width')) * .7))),
        }
        for form, (tag, operation) in operations.items():
            wanted_kind = {'slope': 'slope', 'interval': 'interval'}.get(form)
            with self.subTest(form=form):
                self.reject(form, change_svg(body(fixture(form)), tag, operation,
                    predicate=lambda node: wanted_kind is None or wanted_kind in
                    {node.get('data-kind'), node.get('data-role')}))

    def test_median_outlier_and_missing_band_segment_are_real_geometry(self):
        markup = body(fixture('boxplot'))
        self.reject('boxplot', change_svg(markup, 'line', lambda node: node.set('x1', '1'),
                                         predicate=lambda node: node.get('data-role') == 'median'))
        self.reject('boxplot', change_svg(markup, 'circle', lambda node: node.set('r', '0'),
                                         predicate=lambda node: node.get('data-role') == 'outlier'))
        self.reject('band', change_svg(body(fixture('band')), 'polyline',
                    lambda node: node.set('points', node.get('points') + ' 800,120'),
                    predicate=lambda node: node.get('data-role') == 'central-line'))

    def test_categories_numeric_labels_scales_and_interval_definition(self):
        form = 'interval'
        markup = body(fixture(form))
        # Visible text, even with the hidden spec and mark attributes unchanged.
        for text in ['对象甲', '95%置信区间']:
            with self.subTest(text=text):
                self.reject(form, change_svg(markup, 'text', lambda node: setattr(node, 'text', '错误标签'),
                                             predicate=lambda node: text in ''.join(node.itertext())))
        self.reject(form, change_svg(markup, 'text', lambda node: setattr(node, 'text', '999'),
                                     predicate=lambda node: bool(re.fullmatch(r'-?\d+(?:\.\d+)?', node.text or ''))))
        self.reject(form, change_svg(markup, 'svg', lambda node: node.set('viewBox', '0 0 400 200')))

    def test_hidden_removed_or_extra_real_graphics_cannot_pass(self):
        for form in TYPES:
            markup = body(fixture(form))
            bad = [re.sub(r'<svg\b.*?</svg>', '<svg viewBox="0 0 800 400"></svg>', markup, flags=re.S),
                   markup.replace('<svg ', '<svg opacity="0" ', 1),
                   markup.replace('<svg ', '<svg visibility="hidden" ', 1),
                   markup.replace('<svg ', '<svg style="display:none" ', 1),
                   markup.replace('<svg ', '<svg width="0" ', 1),
                   markup.replace('<svg ', '<svg transform="scale(0)" ', 1),
                   markup.replace('</svg>', '<circle cx="200" cy="100" r="30" fill="red"/></svg>', 1)]
            for candidate in bad:
                with self.subTest(form=form, candidate=candidate[-120:]):
                    self.reject(form, candidate)

    def test_mark_and_label_hiding_is_rejected(self):
        markup = body(fixture('interval'))
        for tag, attributes in [('circle', {'fill': 'none', 'stroke': 'none'}),
                                ('circle', {'style': 'opacity:0'}),
                                ('text', {'fill': 'transparent'}),
                                ('text', {'visibility': 'collapse'})]:
            with self.subTest(tag=tag, attributes=attributes):
                self.reject('interval', change_svg(markup, tag, lambda node: node.attrib.update(attributes)))

    def test_custom_new_chart_requires_standard_spec_and_geometry(self):
        for form in TYPES:
            markup = ('<figure id="graphic" data-visual="' + form + '" data-unit="分">'
                      '<svg viewBox="0 0 200 100"><rect x="10" y="10" width="20" height="30" '
                      'fill="blue" data-value="30"/><rect x="50" y="10" width="20" height="50" '
                      'fill="blue" data-value="50"/></svg><p>只有标签，缺少标准数据合同。</p></figure>')
            with self.subTest(form=form), self.assertRaisesRegex(ValueError, '专用自绘分析图当前不支持'):
                validate_page(page(form), markup, 1)

    def test_invalid_spec_cannot_use_old_distribution_fallback(self):
        spec = fixture('histogram')
        for changes in [{'edges': [0, 5, 2, 10]}, {'sample_size': 999}, {'counts': [2, True, 3]},
                        {'counts': [2, float('nan'), 3]}, {'counts': [2, float('inf'), 3]}]:
            with self.subTest(changes=changes):
                self.reject('histogram', replace_spec(body(spec), {**spec, **changes}))
        generic = body(spec).replace('data-visual="histogram"', 'data-visual="distribution"')
        self.reject('distribution', generic, 'distribution')

    def test_zero_values_ties_summary_boxplot_and_missing_segments(self):
        alternatives = [fixture('band'), fixture('ecdf'),
                        {**fixture('histogram'), 'counts': [0, 10, 0]},
                        {**fixture('interval'), 'lower': [12, 21], 'upper': [12, 21]},
                        {**fixture('boxplot'), 'summary_definition': '提供方给出的线性分位数及须线',
                         'groups': [{'label': '汇总组', 'n': 20, 'low': 1, 'q1': 2, 'median': 3,
                                     'q3': 5, 'high': 8, 'outliers': [11]}]}]
        for spec in alternatives:
            with self.subTest(form=spec['chart_type']):
                validate_page(page(spec['chart_type']), body(spec), 1)

    def test_small_multiples_each_child_and_four_canvases(self):
        spec = small()
        for canvas in ['16:9', '9:16', 'A4', 'scroll']:
            with self.subTest(canvas=canvas):
                validate_page(page('small_multiples', 'uncertainty'), body(spec, canvas), 1)
        markup = body(spec)
        self.reject('small_multiples', change_svg(markup, 'circle', lambda n: n.set('cx', '1'), index=1), 'uncertainty')
        second = deepcopy(spec['charts'][1]); second['max'] = 40
        self.reject('small_multiples', replace_spec(markup, second, index=1), 'uncertainty')
        second = deepcopy(spec['charts'][1]); second['labels'].reverse()
        self.reject('small_multiples', replace_spec(markup, second, index=1), 'uncertainty')
        second = deepcopy(spec['charts'][1]); del second['min']
        self.reject('small_multiples', replace_spec(markup, second, index=1), 'uncertainty')
        second = deepcopy(spec['charts'][1]); second['unit'] = '元'
        self.reject('small_multiples', replace_spec(markup, second, index=1), 'uncertainty')
        self.reject('small_multiples', markup.replace('data-shared-scale="true"', 'data-shared-scale="false"'), 'uncertainty')
        self.reject('small_multiples', markup.replace('id="panel-b"', 'id="panel-b" hidden'), 'uncertainty')

    def test_small_multiples_relation_must_match_all_children(self):
        self.reject('small_multiples', body(small()), 'comparison')
        spec = small('slope')
        validate_page(page('small_multiples', 'trend'), body(spec), 1)
        spec = small('heatmap')
        validate_page(page('small_multiples', 'distribution'), body(spec), 1)

    def test_gate_preserves_existing_file_after_wrong_visible_graph(self):
        with tempfile.TemporaryDirectory(prefix='analytical-visual-plan-') as directory:
            source, output = Path(directory) / 'source.json', Path(directory) / 'report.html'
            slide = page('interval')
            slide['body'] = body(fixture('interval'))
            data = {'title': '分析图', 'slides': [slide]}
            source.write_text(json.dumps(data, ensure_ascii=False), encoding='utf8')
            render(source, output)
            original = output.read_bytes()
            slide['body'] = change_svg(slide['body'], 'circle', lambda node: node.set('cx', '1'))
            source.write_text(json.dumps(data, ensure_ascii=False), encoding='utf8')
            with self.assertRaisesRegex(ValueError, '未实现该图式'):
                render(source, output, replace=True)
            self.assertEqual(original, output.read_bytes())


if __name__ == '__main__':
    unittest.main(verbosity=2)
