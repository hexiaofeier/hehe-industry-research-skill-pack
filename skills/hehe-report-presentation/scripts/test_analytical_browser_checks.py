"""Actual Chromium paint/geometry checks for analytical charts and small multiples."""
import html
import json
import os
from pathlib import Path
import unittest

from playwright.sync_api import sync_playwright

from analytical_charts import TYPES
from export_and_check import check_visuals
from test_analytical_visual_plan import body, fixture, page, small

BROWSER = os.environ.get('REPORT_BROWSER', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')


@unittest.skipUnless(Path(BROWSER).is_file(), 'Set REPORT_BROWSER to an installed Chromium browser')
class AnalyticalBrowserChecksTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True, executable_path=BROWSER)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.page = self.browser.new_page(viewport={'width': 1280, 'height': 800})
        self.page.context.set_offline(True)

    def tearDown(self):
        self.page.close()

    def open(self, spec, css='', no_plan=False):
        form = spec.get('chart_type', 'small_multiples')
        plan = page(form, 'uncertainty' if form == 'small_multiples' else None)['visual_plan']
        metadata = '' if no_plan else ' data-visual-plan="' + html.escape(json.dumps(plan), quote=True) + '"'
        self.page.emulate_media(media='screen')
        self.page.set_content('<!doctype html><meta charset="utf-8"><style>'
            'body{margin:0}.slide{width:1100px}.native-chart svg{width:900px;height:420px}'
            + css + '</style><section class="slide" data-page="1"' + metadata + '>' + body(spec) + '</section>')

    def assert_media(self, failure=False):
        for media in ['screen', 'print']:
            self.page.emulate_media(media=media)
            issues = check_visuals(self.page, 0, media)
            if failure:
                self.assertTrue(issues, (media, self.page.content()))
                self.assertTrue(all(issue['media'] == media and issue['page'] == 1 for issue in issues))
            else:
                self.assertFalse(issues, (media, issues))

    def test_ten_analytical_types_have_actual_visible_marks_and_text(self):
        for form in TYPES:
            with self.subTest(form=form):
                self.open(fixture(form))
                self.assert_media()

    def test_legitimate_zero_segments_tied_boxes_and_zero_length_intervals(self):
        cases = [fixture('dumbbell'), fixture('slope'), fixture('likert'), fixture('histogram'),
                 fixture('boxplot'), fixture('interval'), fixture('band'), fixture('tornado')]
        for spec in cases:
            form = spec['chart_type']
            if form in {'dumbbell', 'slope'}:
                for series in spec['series']:
                    series['values'] = [12, 12]
            elif form == 'likert':
                spec['values'] = [[0, 100, 0], [100, 0, 0]]
            elif form == 'histogram':
                spec['counts'] = [0, 10, 0]
            elif form == 'boxplot':
                spec['groups'] = [{'label': '全相同观测', 'values': [3, 3, 3, 3]}]
            elif form == 'interval':
                spec.update(lower=[12, 21], upper=[12, 21])
            elif form == 'band':
                spec.update(labels=['一期', '二期', '三期'], values=[12, None, 18],
                            lower=[12, None, 18], upper=[12, None, 18])
            elif form == 'tornado':
                spec['low'][0] = spec['baseline']
            with self.subTest(form=form):
                self.open(spec)
                self.assert_media()

    def test_css_hidden_key_data_marks_fail_in_both_media(self):
        roles = {'dumbbell': 'point', 'slope': 'data-mark', 'heatmap': 'cell', 'likert': 'segment',
                 'histogram': 'data-mark', 'boxplot': 'median', 'ecdf': 'data-mark',
                 'interval': 'interval', 'band': 'band', 'tornado': 'scenario'}
        for form, role in roles.items():
            with self.subTest(form=form):
                self.open(fixture(form), '[data-role="' + role + '"]{visibility:hidden}')
                self.assert_media(True)

    def test_print_only_hiding_axes_labels_and_band_is_reported(self):
        for selector in ['[data-role="band"]', '.native-chart line', '.native-chart text']:
            with self.subTest(selector=selector):
                self.open(fixture('band'), '@media print{' + selector + '{display:none}}')
                self.assertFalse(check_visuals(self.page, 0, 'screen'))
                self.page.emulate_media(media='print')
                issues = check_visuals(self.page, 0, 'print')
                self.assertTrue(issues)
                self.assertTrue(all(issue['media'] == 'print' for issue in issues))

    def test_missing_cell_and_missing_period_labels_must_remain_visible(self):
        self.open(fixture('heatmap'), '[data-role="cell"][data-value="null"]{opacity:0}')
        self.assert_media(True)
        self.open(fixture('band'))
        self.page.locator('svg text').evaluate_all(
            "nodes=>nodes.filter(node=>node.textContent==='缺失').forEach(node=>node.style.fill='transparent')")
        self.assert_media(True)

    def test_removed_data_mark_label_and_wrong_live_geometry_fail(self):
        for selector in ['[data-role="estimate"]', '.native-chart text', '.native-chart line']:
            with self.subTest(selector=selector):
                self.open(fixture('interval'))
                self.page.locator(selector).first.evaluate('node=>node.remove()')
                self.assert_media(True)
        self.open(fixture('histogram'), '[data-kind="bin"]{width:0px}')
        self.assert_media(True)
        self.open(fixture('band'), '[data-role="band"]{transform:scale(0)}')
        self.assert_media(True)
        self.open(fixture('band'), '[data-role="band"]{transform:translateX(10000px)}')
        self.assert_media(True)

    def test_transparent_marks_axes_and_text_fail(self):
        for css in ['[data-role="estimate"]{fill:none;stroke:none}',
                    '.native-chart line{stroke:transparent}',
                    '.native-chart text{fill:transparent;stroke:none}',
                    '.chart-heading,figcaption{color:transparent}']:
            with self.subTest(css=css):
                self.open(fixture('interval'), css)
                self.assert_media(True)

    def test_small_multiples_checks_the_second_panel(self):
        self.open(small())
        self.assert_media()
        self.page.add_style_tag(content='#panel-b [data-role="estimate"]{opacity:0}')
        self.assert_media(True)

    def test_preserved_html_fallback_still_checks_analytical_chart(self):
        spec = fixture('interval')
        spec.update(lower=[12, 21], upper=[12, 21])
        self.open(spec, no_plan=True)
        self.assert_media()
        self.page.add_style_tag(content='[data-role="estimate"]{opacity:0}')
        self.assert_media(True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
