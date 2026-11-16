"""Real PPTX round-trip checks for analytical data, shapes and annotations."""
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from lxml import etree
from playwright.sync_api import sync_playwright
from pptx import Presentation
from pptx.chart.data import XyChartData
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.oxml.ns import qn

from analytical_charts import TYPES, chart_html, render_svg
from export_analytical import add_analytical_chart
from export_pptx import add_chart, convert


def example(kind):
    spec = {'type': 'chart', 'chart_type': kind, 'id': '分析_' + kind,
            'title': '可编辑分析图示例', 'unit': '分', 'source': '教学假设，非实际调研'}
    cases = {
        'dumbbell': {'labels': ['甲', '乙'], 'series': [{'name': '前期', 'values': [-10.25, 2]}, {'name': '后期', 'values': [8, -2]}]},
        'slope': {'labels': ['甲', '乙'], 'series': [{'name': '前期', 'values': [-10.25, 2]}, {'name': '后期', 'values': [8, -2]}]},
        'heatmap': {'rows': ['甲', '乙'], 'columns': ['能力', '意愿'], 'values': [[-4, None], [0, 10]], 'min': -4, 'max': 10},
        'likert': {'labels': ['使用体验', '购买意愿'], 'levels': ['很低', '较低', '中立', '较高', '很高'],
                   'values': [[10, 20, 30, 25, 15], [5, 10, 20, 30, 35]], 'input': 'count',
                   'bases': [100, 100], 'negative_count': 2, 'neutral_index': 2},
        'histogram': {'edges': [0, 1, 2, 3], 'counts': [2, 4, 1], 'sample_size': 7},
        'boxplot': {'groups': [{'label': '甲', 'values': [1, 2, 3, 4, 100]}, {'label': '乙', 'values': [-3, -2, 1, 4, 5]}]},
        'ecdf': {'series': [{'name': '甲', 'values': [-2, 1, 1, 3]}, {'name': '乙', 'values': [0, 2, 4, 5]}], 'min': -2, 'max': 5},
        'interval': {'labels': ['甲', '乙'], 'estimates': [-2, 4], 'lower': [-5, 2], 'upper': [1, 6],
                     'interval_label': '95%置信区间', 'sample_sizes': [40, 50]},
        'band': {'labels': ['一期', '二期', '三期', '四期', '五期'], 'values': [1, 2, None, 4, 5],
                 'lower': [0, 1, None, 3, 4], 'upper': [2, 3, None, 5, 6], 'interval_label': '模型情景上下界'},
        'tornado': {'labels': ['成本', '价格', '销量'], 'low': [110, -20, 75], 'high': [90, 150, 130],
                    'baseline': 100, 'scenario_labels': ['参数下界', '参数上界']},
    }
    spec.update(cases[kind])
    return spec


def description(shape):
    value = shape._element.find('.//' + qn('p:cNvPr')).get('descr')
    return json.loads(value) if value else {}


def save_reopen(prs):
    output = io.BytesIO()
    prs.save(output)
    output.seek(0)
    return Presentation(output), output


def native(kind, spec=None):
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    result = add_analytical_chart(slide, {'x': 20, 'y': 30, 'w': 900, 'h': 420, 'spec': spec or example(kind)})
    reopened, blob = save_reopen(prs)
    return reopened.slides[0], result, blob


class AnalyticalPptxTests(unittest.TestCase):
    def test_all_ten_types_roundtrip_without_pictures_and_keep_source_data(self):
        for kind in TYPES:
            with self.subTest(kind=kind):
                spec = example(kind)
                before = copy.deepcopy(spec)
                slide, result, _ = native(kind, spec)
                self.assertEqual(spec, before)
                self.assertTrue(slide.shapes)
                self.assertFalse(any(s.shape_type == MSO_SHAPE_TYPE.PICTURE for s in slide.shapes))
                for shape in slide.shapes:
                    if not shape.has_chart:
                        self.assertIsNotNone(shape._element.find(qn('p:spPr')).find(qn('a:effectLst')))
                sources = [description(s)['source_spec'] for s in slide.shapes if 'source_spec' in description(s)]
                self.assertEqual(sources, [spec])
                self.assertGreater(result['native_texts'], 0)
                self.assertEqual(result['images'], 0)
                expected = 'data_editable' if kind in {'slope', 'ecdf', 'histogram'} else 'shape_editable'
                self.assertEqual(result['editable'], expected)
                self.assertEqual(sum(s.has_chart for s in slide.shapes), int(expected == 'data_editable'))
                self.assertTrue(any(s.has_text_frame and '单位：分' in s.text for s in slide.shapes))

    def test_slope_preserves_exact_negative_values_series_binding_and_colours(self):
        slide, _, blob = native('slope')
        chart = next(s.chart for s in slide.shapes if s.has_chart)
        self.assertEqual([s.name for s in chart.series], ['甲', '乙'])
        self.assertEqual([s.values for s in chart.series], [(-10.25, 8), (2, -2)])
        self.assertEqual([str(s.format.line.color.rgb) for s in chart.series], ['27647F', '208E91'])
        self.assertEqual(chart.category_axis.minimum_scale, 0)
        self.assertEqual(chart.category_axis.maximum_scale, 1)
        self.assertIsNotNone(chart._chartSpace.find('.//' + qn('c:manualLayout')))
        with ZipFile(blob) as archive:
            embedded = next(name for name in archive.namelist() if name.startswith('ppt/embeddings/'))
            with ZipFile(io.BytesIO(archive.read(embedded))) as workbook:
                xml = workbook.read('xl/worksheets/sheet1.xml').decode('utf8')
                self.assertIn('<v>-10.25</v>', xml)
                self.assertIn('<v>8</v>', xml)

    def test_ecdf_has_exact_step_data_and_merged_duplicate_observations(self):
        slide, result, _ = native('ecdf')
        chart = next(s.chart for s in slide.shapes if s.has_chart)
        first = chart.series[0]
        self.assertEqual(first.values, (0, 0, 25, 25, 75, 75, 100, 100))
        x_values = [float(node.text) for node in first._element.findall('.//' + qn('c:xVal') + '//' + qn('c:v'))]
        self.assertEqual(x_values, [-2, -2, -2, 1, 1, 3, 3, 5])
        self.assertEqual(chart.value_axis.minimum_scale, 0)
        self.assertEqual(chart.value_axis.maximum_scale, 100)
        self.assertIn('实际阶梯点', result['data_note'])
        self.assertEqual(len(first._element.findall(qn('c:dPt'))), 5)

    def test_equal_bins_use_native_frequency_data_and_declared_height(self):
        spec = example('histogram')
        spec['frequency_max'] = 10
        slide, result, _ = native('histogram', spec)
        chart = next(s.chart for s in slide.shapes if s.has_chart)
        self.assertEqual(chart.series[0].values, (2, 4, 1))
        self.assertEqual([c.label for c in chart.plots[0].categories], ['[0, 1)', '[1, 2)', '[2, 3]'])
        self.assertEqual(chart.plots[0].gap_width, 0)
        self.assertEqual(chart.value_axis.maximum_scale, 10)
        self.assertEqual(result['editable'], 'data_editable')

    def test_unequal_bins_preserve_numeric_width_density_and_observation_counts(self):
        spec = example('histogram')
        spec.update(edges=[0, 1, 3, 6], counts=[2, 4, 6], sample_size=12)
        slide, result, _ = native('histogram', spec)
        self.assertEqual(result['editable'], 'shape_editable')
        bars = [s for s in slide.shapes if description(s).get('data-kind') == 'bin']
        self.assertEqual([float(description(s)['data-value']) for s in bars], [2, 4, 6])
        self.assertAlmostEqual(bars[1].width / bars[0].width, 2, places=4)
        self.assertAlmostEqual(bars[2].width / bars[0].width, 3, places=4)
        self.assertEqual([s.height for s in bars], [bars[0].height] * 3)

    def test_shape_scenario_category_value_and_fill_survive_sorting(self):
        slide, result, _ = native('tornado')
        bars = [s for s in slide.shapes if description(s).get('data-role') == 'scenario']
        actual = [(description(s)['data-category'], description(s)['data-scenario'], float(description(s)['data-value']), str(s.fill.fore_color.rgb)) for s in bars]
        self.assertEqual(actual, [('价格', '参数下界', -20, '27647F'), ('价格', '参数上界', 150, '208E91'),
                                  ('销量', '参数下界', 75, '27647F'), ('销量', '参数上界', 130, '208E91'),
                                  ('成本', '参数下界', 110, '27647F'), ('成本', '参数上界', 90, '208E91')])
        self.assertEqual(result['native_charts'], 0)

    def test_missing_band_period_stays_separate_editable_freeforms(self):
        slide, _, _ = native('band')
        polygons = [s for s in slide.shapes if description(s).get('data-role') == 'band']
        lines = [s for s in slide.shapes if description(s).get('data-role') == 'central-line']
        self.assertEqual(len(polygons), 2)
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(s.shape_type == MSO_SHAPE_TYPE.FREEFORM for s in polygons + lines))
        self.assertLess(polygons[0].left + polygons[0].width, polygons[1].left)
        self.assertTrue(any(s.has_text_frame and s.text == '缺失' for s in slide.shapes))

    def test_native_data_text_and_shape_edits_save_and_reopen(self):
        prs = Presentation()
        slope = prs.slides.add_slide(prs.slide_layouts[6])
        add_chart(slope, {'x': 20, 'y': 20, 'w': 900, 'h': 420, 'spec': example('slope')})
        heatmap = prs.slides.add_slide(prs.slide_layouts[6])
        add_chart(heatmap, {'x': 20, 'y': 20, 'w': 900, 'h': 420, 'spec': example('heatmap')})
        prs, _ = save_reopen(prs)
        chart = next(s.chart for s in prs.slides[0].shapes if s.has_chart)
        data = XyChartData()
        for index, old in enumerate(chart.series):
            new = data.add_series(old.name)
            new.add_data_point(.13846153846153847, 123.5 if index == 0 else 2)
            new.add_data_point(.8615384615384616, 8 if index == 0 else -2)
        chart.replace_data(data)
        text = next(s for s in prs.slides[1].shapes if s.has_text_frame and s.text)
        text.text = '验收文字修改'
        cell = next(s for s in prs.slides[1].shapes if description(s).get('data-role') == 'cell')
        cell.left += 95250
        changed_left = cell.left
        prs, _ = save_reopen(prs)
        chart = next(s.chart for s in prs.slides[0].shapes if s.has_chart)
        self.assertEqual(chart.series[0].values[0], 123.5)
        self.assertTrue(any(s.has_text_frame and s.text == '验收文字修改' for s in prs.slides[1].shapes))
        cell = next(s for s in prs.slides[1].shapes if description(s).get('data-role') == 'cell')
        self.assertEqual(cell.left, changed_left)

    def test_unsupported_geometry_fails_without_picture_fallback(self):
        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        svg = render_svg(example('heatmap')).replace('<rect ', '<rect transform="translate(2)" ', 1)
        with patch('export_analytical.render_svg', return_value=svg):
            with self.assertRaisesRegex(ValueError, 'transform'):
                add_analytical_chart(slide, {'x': 0, 'y': 0, 'w': 900, 'h': 420, 'spec': example('heatmap')})
        self.assertEqual(len(slide.shapes), 0)


class AnalyticalConvertTests(unittest.TestCase):
    def test_conversion_manifest_distinguishes_data_shapes_and_original_svg_picture(self):
        with sync_playwright() as playwright:
            browser = os.environ.get('REPORT_PPTX_BROWSER', playwright.chromium.executable_path)
        if not Path(browser).is_file():
            self.skipTest('Chromium unavailable; set REPORT_PPTX_BROWSER')
        from components import chart_html as old_chart
        bar = {'chart_type': 'bar', 'title': '原柱形', 'unit': '分', 'source': '假设', 'labels': ['甲'], 'series': [{'name': '组', 'values': [5]}]}
        slides = [chart_html(example('slope')), chart_html(example('heatmap')), old_chart(bar), '<svg width="160" height="80" viewBox="0 0 160 80"><rect width="160" height="80" fill="blue"/></svg>']
        html = '''<!doctype html><meta charset="utf8"><style>body{margin:0}.slide{display:none;position:relative;width:1000px;height:600px;background:white}.slide.active{display:block}.native-chart{width:900px;height:420px}.native-chart svg{width:100%;height:100%}figure{margin:20px}.chart-heading,figcaption{font:16px "Microsoft YaHei"}</style><body data-canvas="16:9">'''
        html += ''.join('<section class="slide' + (' active' if i == 0 else '') + '">' + body + '</section>' for i, body in enumerate(slides))
        html += '''<script>function show(n){document.querySelectorAll('.slide').forEach((e,i)=>e.classList.toggle('active',i===n))}document.documentElement.dataset.ready='true';</script>'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / '分析导出_CO.html'
            output = source.with_suffix('.pptx')
            source.write_text(html, encoding='utf8')
            convert(source, output, browser)
            prs = Presentation(output)
            self.assertEqual(len(prs.slides), 4)
            self.assertEqual([sum(s.has_chart for s in slide.shapes) for slide in prs.slides], [1, 0, 1, 0])
            self.assertEqual([sum(s.shape_type == MSO_SHAPE_TYPE.PICTURE for s in slide.shapes) for slide in prs.slides], [0, 0, 0, 1])
            manifest = json.loads(output.with_name(output.stem + '_对象核验_CO.json').read_text(encoding='utf8'))
            self.assertEqual([c['editable'] for c in manifest['analytical_charts']], ['data_editable', 'shape_editable'])
            self.assertEqual(len(manifest['image_elements']), 1)
            self.assertEqual([p['native_data_charts'] for p in manifest['pages']], [1, 0, 1, 0])
            self.assertEqual([p['analytical_shape_charts'] for p in manifest['pages']], [0, 1, 0, 0])


if __name__ == '__main__':
    unittest.main(verbosity=2)
