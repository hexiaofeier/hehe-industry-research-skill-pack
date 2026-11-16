"""Semantic and geometry regression for the independent analytical renderer."""
import copy
import json
import math
import re
from pathlib import Path
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET

from analytical_charts import (TYPES, box_summary, chart_html, chart_model,
                               render_svg, small_multiples_html,
                               validate_small_multiples, validate_spec)

ROOT = Path(__file__).resolve().parents[1]


def charts_from(blocks):
    for block in blocks:
        if block['type'] == 'chart':
            yield block
        elif block['type'] == 'split':
            for column in block['columns']:
                yield from charts_from(column)
        elif block['type'] == 'small_multiples':
            yield from block['charts']


EXAMPLE = json.loads((ROOT / 'assets/analytical_examples.json').read_text(encoding='utf-8'))
SPECS = {c['chart_type']: c for page in EXAMPLE['slides'] for c in charts_from(page.get('blocks', []))}
SMALL = next(b for p in EXAMPLE['slides'] for b in p.get('blocks', []) if b['type'] == 'small_multiples')


def elements(spec, kind=None, role=None):
    return [el for el in ET.fromstring(render_svg(spec)).iter()
            if (kind is None or el.tag.rsplit('}', 1)[-1] == kind)
            and (role is None or el.get('data-role') == role)]


class SemanticTests(unittest.TestCase):
    def spec(self, kind, **changes):
        out = copy.deepcopy(SPECS[kind])
        out.update(changes)
        return out

    def test_teaching_pages_have_all_types_and_complete_explanations(self):
        self.assertEqual(set(SPECS), TYPES)
        pages = [p for p in EXAMPLE['slides'] if p['kind'] == 'content']
        self.assertEqual(len(pages), 11)
        for page in pages:
            self.assertNotEqual(page['title'], page['lead'])
            self.assertIn('。', page['lead'])
            self.assertTrue(page['visual_plan']['explanation'])
        for spec in SPECS.values():
            before = copy.deepcopy(spec)
            self.assertIs(validate_spec(spec), spec)
            render_svg(spec)
            self.assertEqual(spec, before)

    def test_nonfinite_and_boolean_rejected(self):
        for value in (True, False, float('nan'), float('inf'), -float('inf'), None):
            spec = self.spec('dumbbell')
            spec['series'][0]['values'][0] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_spec(spec)
        for value in (True, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                validate_spec(self.spec('interval', min=value))

    def test_scale_cannot_crop_or_reverse(self):
        for changes in ({'min': 50}, {'max': 60}, {'min': 90, 'max': 30}):
            with self.assertRaises(ValueError):
                validate_spec(self.spec('dumbbell', **changes))

    def test_negative_pair_values_use_real_scale(self):
        spec = self.spec('dumbbell', labels=['净变化'], min=-20, max=20,
                         series=[{'name': '甲', 'values': [-10]}, {'name': '乙', 'values': [10]}])
        points = elements(spec, 'circle', 'point')
        self.assertEqual([float(el.get('cx')) for el in points], [164 + 650 / 4, 164 + 650 * .75])

    def test_pair_lengths_and_distinct_series(self):
        spec = self.spec('slope')
        spec['series'][1]['values'].pop()
        with self.assertRaises(ValueError):
            validate_spec(spec)
        spec = self.spec('slope')
        spec['series'][1]['name'] = spec['series'][0]['name']
        with self.assertRaises(ValueError):
            validate_spec(spec)

    def test_heatmap_null_is_not_zero(self):
        spec = self.spec('heatmap')
        cells = elements(spec, 'rect', 'cell')
        missing = [c for c in cells if c.get('data-value') == 'null']
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0].get('fill'), '#edf1f3')
        self.assertIn('缺失', render_svg(spec))
        spec['values'][0][0] = 0
        zero = [c for c in elements(spec, 'rect', 'cell') if c.get('data-value') == '0'][0]
        self.assertNotEqual(zero.get('fill'), missing[0].get('fill'))
        spec['bases'][0][0] = None
        with self.assertRaises(ValueError):
            validate_spec(spec)

    def test_heatmap_requires_shape_and_at_least_one_observation(self):
        with self.assertRaises(ValueError):
            validate_spec(self.spec('heatmap', values=[[None] * 4] * 3))
        with self.assertRaises(ValueError):
            validate_spec(self.spec('heatmap', values=[[1, 2], [3, 4], [5, 6]]))

    def test_likert_counts_and_neutral_center(self):
        spec = self.spec('likert')
        middle = chart_model(spec)['rows'][0][2]
        self.assertEqual((middle['start'], middle['end'], middle['value']), (-10, 10, 20))
        row = chart_model(spec)['rows'][0]
        self.assertEqual(sum(v['value'] for v in row), 100)
        neutral = [el for el in elements(spec, 'rect', 'segment') if el.get('data-level') == '一般'][0]
        center = float(neutral.get('x')) + float(neutral.get('width')) / 2
        self.assertAlmostEqual(center, 164 + 650 / 2)
        spec['bases'][0] = 101
        with self.assertRaises(ValueError):
            validate_spec(spec)

    def test_likert_percent_rounding_is_explicit(self):
        spec = self.spec('likert', input='percent')
        spec['values'][0][0] = 10.2
        with self.assertRaises(ValueError):
            validate_spec(spec)
        spec['rounding_tolerance'] = .21
        validate_spec(spec)
        for value in (-1, 2, True):
            with self.assertRaises(ValueError):
                validate_spec(dict(spec, rounding_tolerance=value))

    def test_likert_no_neutral_and_order(self):
        spec = self.spec('likert', labels=['体验'], levels=['负向', '正向'], values=[[40, 60]],
                         bases=[100], negative_count=1, neutral_index=None)
        row = chart_model(spec)['rows'][0]
        self.assertEqual([(v['start'], v['end']) for v in row], [(-40, 0), (0, 60)])
        spec['neutral_index'] = True
        with self.assertRaises(ValueError):
            validate_spec(spec)

    def test_histogram_density_uses_area_for_unequal_bins(self):
        spec = self.spec('histogram')
        model = chart_model(spec)
        self.assertTrue(model['density'])
        self.assertEqual(model['heights'], [9, 21, 9, 6])
        bars = [el for el in elements(spec, 'rect', 'data-mark') if el.get('data-kind') == 'bin']
        areas = [float(el.get('width')) * float(el.get('height')) for el in bars]
        ratios = [area / count for area, count in zip(areas, spec['counts'])]
        for ratio in ratios:
            self.assertAlmostEqual(ratio, ratios[0])
        self.assertEqual(float(bars[2].get('width')), 2 * float(bars[0].get('width')))
        self.assertIn('频数密度', render_svg(spec))

    def test_histogram_count_labels_are_distinct_from_density_units(self):
        spec = self.spec('histogram', count_unit='笔')
        svg = render_svg(spec)
        self.assertIn('频数密度（笔/小时）', svg)
        for value in spec['counts']:
            self.assertIn('>' + str(value) + '笔</text>', svg)
        with self.assertRaises(ValueError):
            validate_spec(self.spec('histogram', count_unit=''))

    def test_equal_bins_use_frequencies_and_counts_reconcile(self):
        spec = self.spec('histogram', edges=[0, 2, 4, 6], counts=[2, 4, 3], sample_size=9, max=6)
        self.assertFalse(chart_model(spec)['density'])
        self.assertEqual(chart_model(spec)['heights'], [2, 4, 3])
        for changes in ({'sample_size': 8}, {'edges': [0, 2, 2, 6]}, {'counts': [1, -1, 9]}, {'counts': [1, True, 7]}):
            with self.assertRaises(ValueError):
                validate_spec(dict(spec, **changes))

    def test_boxplot_linear_quantiles_and_outlier_retention(self):
        summary = box_summary({'label': '甲', 'values': [0, 1, 2, 3, 4, 100]})
        self.assertEqual([summary[k] for k in ('q1', 'median', 'q3', 'low', 'high')], [1.25, 2.5, 3.75, 0, 4])
        self.assertEqual(summary['n'], 6)
        self.assertEqual(summary['outliers'], [100])
        singleton = box_summary({'label': '甲', 'values': [7]})
        self.assertEqual([singleton[k] for k in ('low', 'q1', 'median', 'q3', 'high')], [7] * 5)

    def test_boxplot_summary_requires_definition_and_valid_order(self):
        group = dict(label='甲', n=10, low=1, q1=2, median=3, q3=4, high=5, outliers=[9])
        spec = self.spec('boxplot', groups=[group], min=0, max=10)
        with self.assertRaises(ValueError):
            validate_spec(spec)
        spec['summary_definition'] = '上游按线性插值和1.5倍IQR生成的汇总值。'
        validate_spec(spec)
        group['median'] = 6
        with self.assertRaises(ValueError):
            validate_spec(spec)

    def test_ecdf_merges_ties_and_is_right_continuous(self):
        spec = self.spec('ecdf', series=[{'name': '甲', 'values': [4, 2, 2, 1]}], min=0, max=5)
        group = chart_model(spec)['series'][0]
        self.assertEqual(group['n'], 4)
        self.assertEqual([(p['value'], p['cumulative'], p['count']) for p in group['points']],
                         [(1, .25, 1), (2, .75, 2), (4, 1, 1)])
        line = [el for el in elements(spec, 'polyline', 'data-mark')][0]
        coords = [tuple(map(float, v.split(','))) for v in line.get('points').split()]
        self.assertEqual(coords[0], (164, 334))
        for a, b in zip(coords, coords[1:]):
            self.assertTrue(a[0] == b[0] or a[1] == b[1])
        self.assertEqual(coords[-1], (814, 62))
        self.assertIn('横轴：观测值（小时）', render_svg(spec))

    def test_interval_order_and_sample_sizes(self):
        for changes in ({'lower': [73, 54, 57]}, {'upper': [71, 74, 81]}, {'sample_sizes': [150, 0, 80]}, {'estimates': [None, 64, 69]}):
            with self.assertRaises(ValueError):
                validate_spec(self.spec('interval', **changes))
        validate_spec(self.spec('interval', estimates=[0, 5, -5], lower=[-1, 2, -9], upper=[1, 8, -1], min=-10, max=10))

    def test_band_breaks_at_missing_observations(self):
        spec = self.spec('band')
        self.assertEqual(chart_model(spec)['segments'], [[0, 1, 2], [4, 5]])
        polygons = elements(spec, 'polygon', 'band')
        self.assertEqual(len(polygons), 2)
        self.assertEqual([(p.get('data-start-index'), p.get('data-end-index')) for p in polygons], [('0', '2'), ('4', '5')])
        spec['lower'][3] = 3
        with self.assertRaises(ValueError):
            validate_spec(spec)

    def test_band_single_observation_keeps_interval(self):
        spec = self.spec('band', labels=['甲', '乙', '丙'], values=[None, 4, None], lower=[None, 2, None], upper=[None, 7, None])
        self.assertEqual(chart_model(spec)['segments'], [[1]])
        self.assertEqual(len(elements(spec, 'line', 'single-interval')), 1)
        self.assertEqual(len(elements(spec, 'polygon', 'band')), 0)

    def test_tornado_sorts_bound_names_and_preserves_reversal(self):
        model = chart_model(self.spec('tornado'))
        self.assertEqual([r['label'] for r in model['rows']], ['续约率', '维修单价', '人员利用率', '备件成本'])
        self.assertEqual((model['rows'][-1]['low'], model['rows'][-1]['high']), (13, 10))
        self.assertEqual([r['span'] for r in model['rows']], [8, 6, 4.5, 3])
        spec = self.spec('tornado', labels=['同侧'], low=[13], high=[16])
        marks = elements(spec, 'rect', 'scenario')
        self.assertEqual(len(marks), 2)
        self.assertNotEqual(marks[0].get('y'), marks[1].get('y'))

    def test_common_scale_and_category_order(self):
        validate_small_multiples(SMALL)
        for field, value in (('min', 20), ('unit', '小时'), ('labels', ['远程诊断', '驻场维护', '年度维护'])):
            spec = copy.deepcopy(SMALL)
            spec['charts'][1][field] = value
            with self.assertRaises(ValueError):
                validate_small_multiples(spec)
        spec = copy.deepcopy(SMALL)
        del spec['charts'][0]['min']
        with self.assertRaises(ValueError):
            validate_small_multiples(spec)
        self.assertIn('repeat(1,', small_multiples_html(SMALL, '9:16'))
        self.assertIn('repeat(1,', small_multiples_html(SMALL, 'A4'))

    def test_small_histograms_share_both_axes(self):
        a = self.spec('histogram', frequency_max=30)
        b = self.spec('histogram', id='second', counts=[24, 36, 36, 24], frequency_max=30)
        group = dict(type='small_multiples', id='small-hist', title='共同尺度', charts=[a, b], shared_scale=True)
        validate_small_multiples(group)
        del b['frequency_max']
        with self.assertRaises(ValueError):
            validate_small_multiples(group)

    def test_a4_small_multiples_keep_fonts_scales_and_source_data(self):
        before = copy.deepcopy(SMALL)
        ordinary = [ET.fromstring(raw) for raw in re.findall(r'<svg\b.*?</svg>', small_multiples_html(SMALL), re.S)]
        compact = [ET.fromstring(raw) for raw in re.findall(r'<svg\b.*?</svg>', small_multiples_html(SMALL, 'A4'), re.S)]
        self.assertEqual(SMALL, before)
        for original, shortened in zip(ordinary, compact):
            self.assertEqual(original.get('viewBox'), '0 0 900 420')
            self.assertEqual(shortened.get('viewBox'), '0 0 900 350')
            for key in ('data-x-min', 'data-x-max', 'data-unit'):
                self.assertEqual(original.get(key), shortened.get(key))
            original_labels = [(el.text, el.get('font-size')) for el in original.iter() if el.tag.endswith('text')]
            compact_labels = [(el.text, el.get('font-size')) for el in shortened.iter() if el.tag.endswith('text')]
            self.assertEqual(original_labels, compact_labels)
        for height in (True, 349, 421, float('nan')):
            with self.assertRaises(ValueError):
                validate_spec(self.spec('dumbbell', svg_height=height))

    def test_svg_is_direct_finite_geometry_with_visible_metadata(self):
        allowed = {'svg', 'rect', 'line', 'circle', 'polyline', 'polygon', 'text', 'tspan'}
        for spec in SPECS.values():
            for el in elements(spec):
                self.assertIn(el.tag.rsplit('}', 1)[-1], allowed)
                self.assertNotIn('transform', el.attrib)
                for key in ('x', 'y', 'x1', 'y1', 'x2', 'y2', 'cx', 'cy', 'r', 'width', 'height'):
                    if key in el.attrib:
                        self.assertTrue(math.isfinite(float(el.get(key))))
            markup = chart_html(spec)
            self.assertIn('native-chart analytical-chart', markup)
            self.assertIn(spec['source'], markup)
            self.assertIn('data-chart=', markup)

    def test_no_third_party_packages_are_needed(self):
        code = ("import sys,json;from pathlib import Path;sys.path.insert(0,sys.argv[1]);"
                "import analytical_charts as a;data=json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'));"
                "defwalk=None\n"
                "def walk(bs):\n"
                " for b in bs:\n"
                "  if b['type']=='chart': a.render_svg(b)\n"
                "  elif b['type']=='split':\n"
                "   for col in b['columns']: walk(col)\n"
                "  elif b['type']=='small_multiples': a.small_multiples_html(b)\n"
                "for p in data['slides']: walk(p.get('blocks',[]))\n")
        result = subprocess.run([sys.executable, '-I', '-S', '-B', '-X', 'utf8', '-c', code,
                                 str(ROOT / 'scripts'), str(ROOT / 'assets/analytical_examples.json')],
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
