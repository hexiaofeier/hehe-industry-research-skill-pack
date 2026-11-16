"""Check category/bar alignment and preserve the native hbar data contract."""
import json
import unittest
import xml.etree.ElementTree as ET

from business_components import chart_svg


class HbarAlignmentTests(unittest.TestCase):
    def check_chart(self, spec):
        figure = ET.fromstring(chart_svg(spec))
        native = figure.find(".//div[@class='native-chart']")
        self.assertEqual(json.loads(native.get('data-chart')), spec)
        svg = native.find('svg')
        labels = [text for text in svg.findall('text') if text.get('font-size') == '16']
        values = [text for text in svg.findall('text') if text.get('font-size') == '15']
        bars = svg.findall('rect')
        self.assertEqual(len(labels), len(spec['labels']))
        self.assertEqual(len(bars), len(spec['labels']) * len(spec['series']))
        self.assertEqual(len(values), len(bars))
        zero = float(svg.find('line').get('x1'))
        previous_bottom = 0
        count = len(spec['series'])
        for i, label in enumerate(labels):
            self.assertEqual(''.join(label.itertext()), spec['labels'][i])
            self.assertEqual(label.get('dominant-baseline'), 'central')
            text_lines = label.findall('tspan') or [label]
            text_center = sum(float(line.get('y')) for line in text_lines) / len(text_lines)
            group = bars[i * count:(i + 1) * count]
            top = min(float(bar.get('y')) for bar in group)
            bottom = max(float(bar.get('y')) + float(bar.get('height')) for bar in group)
            self.assertAlmostEqual(text_center, (top + bottom) / 2)
            self.assertGreater(top, previous_bottom)
            previous_bottom = bottom
            for j, bar in enumerate(group):
                value = spec['series'][j]['values'][i]
                x, width = float(bar.get('x')), float(bar.get('width'))
                self.assertGreater(float(bar.get('height')), 0)
                self.assertGreaterEqual(width, 0)
                self.assertAlmostEqual(x if value >= 0 else x + width, zero)
                if value == 0:
                    self.assertEqual(width, 0)
                self.assertEqual(bar.get('fill'), ['#27647f', '#208e91', '#b78647', '#8ba6b2'][j % 4])
                text = values[i * count + j]
                self.assertEqual(''.join(text.itertext()), f'{value:g}%')
                self.assertEqual(text.get('dominant-baseline'), 'central')
                self.assertAlmostEqual(float(text.get('y')), float(bar.get('y')) + float(bar.get('height')) / 2)
        self.assertLess(previous_bottom, float(svg.get('viewBox').split()[3]))
        return labels

    def test_single_series_positive_negative_and_zero(self):
        for values in [[45, 0, -20], [0, 0, 0]]:
            with self.subTest(values=values):
                self.check_chart({'chart_type': 'hbar', 'labels': ['甲组', '乙组', '丙组'],
                                  'series': [{'name': '本期', 'values': values}], 'value_suffix': '%'})

    def test_multiple_series_stay_in_their_category_rows(self):
        for count in [2, 3, 4, 8]:
            with self.subTest(count=count):
                self.check_chart({'chart_type': 'hbar', 'labels': ['甲组', '乙组', '丙组'],
                                  'series': [{'name': f'系列{j + 1}', 'values': [40 + j, -10 - j, 0]}
                                             for j in range(count)], 'value_suffix': '%'})

    def test_long_category_keeps_complete_text_and_font_size(self):
        labels = self.check_chart({'chart_type': 'hbar', 'labels': ['负责设备部署和后续维护的合作伙伴',
                                  '负责区域内全部设备部署和后续维护并反馈实际使用情况的合作伙伴'],
                                  'series': [{'name': '本期', 'values': [60, 45]}], 'value_suffix': '%'})
        self.assertTrue(all(label.findall('tspan') for label in labels))
        self.assertTrue(all(label.get('font-size') == '16' for label in labels))


if __name__ == '__main__':
    unittest.main()
