"""Browser regressions for hidden graphics, offline images and JSON embedding."""
import base64
import builtins
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from playwright.sync_api import sync_playwright

from export_and_check import check_images, check_visuals
from render_report import ReportImageError, render

SCRIPTS = Path(__file__).resolve().parent
BROWSER = os.environ.get('REPORT_BROWSER', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jZQ0AAAAASUVORK5CYII=')


def chart_document(form='bar', values=None, css=''):
    values = [10, 20] if values is None else values
    spec = {'id': 'graphic', 'type': 'chart', 'chart_type': form,
            'title': '采购预算', 'unit': '万元', 'source': '教学数据',
            'labels': ['甲', '乙'][:len(values)], 'series': [{'name': '预算', 'values': values}]}
    if form == 'waterfall':
        spec['values'] = values
    relation = {'bar': 'comparison', 'hbar': 'comparison', 'stacked': 'composition',
                'line': 'trend', 'waterfall': 'change'}[form]
    return {'title': '浏览器检查', 'extra_css': css, 'slides': [{
        'kind': 'content', 'title': '两类客户采购预算', 'lead': '按同一口径比较客户采购预算。',
        'blocks': [spec], 'visual_plan': {'relation': relation, 'form': form, 'target': 'graphic',
            'message': '比较两类客户预算。', 'explanation': '图中保留数值和单位。'}}]}


def image_document(src):
    return {'title': '图片资料', 'slides': [{
        'kind': 'content', 'title': '设备实物资料', 'lead': '图片用于识别设备型号。',
        'body': f'<div id="evidence"><p>设备型号识别材料。</p><img src="{src}" width="20" height="20" alt="设备图片"></div>',
        'visual_plan': {'relation': 'narrative', 'form': 'prose', 'target': 'evidence',
            'message': '通过实物图片识别设备型号。', 'explanation': '图片上方段落说明用途。',
            'reason': '完整段落解释识别用途。'}}]}


class JsonImageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='report-browser-images-')
        self.root = Path(self.directory.name)
        self.source = self.root / 'source_CO.json'
        self.output = self.root / 'elsewhere' / 'report_CO.html'

    def tearDown(self):
        self.directory.cleanup()

    def write(self, data):
        self.source.write_text(json.dumps(data, ensure_ascii=False), encoding='utf8')

    def test_relative_local_image_is_embedded_without_bs4(self):
        (self.root / '设备 图片.png').write_bytes(PNG)
        self.write(image_document('设备%20图片.png'))
        original_import = builtins.__import__
        def no_bs4(name, *args, **kwargs):
            if name == 'bs4':
                raise ImportError('JSON must use only the standard library')
            return original_import(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=no_bs4):
            render(self.source, self.output)
        output = self.output.read_text(encoding='utf8')
        self.assertIn('data:image/png;base64,' + base64.b64encode(PNG).decode(), output)
        self.assertIn('data-visual-plan=', output)
        self.assertNotIn('设备%20图片.png', output)

    def test_data_uri_is_retained_verbatim(self):
        uri = 'data:image/png;base64,' + base64.b64encode(PNG).decode()
        self.write(image_document(uri))
        render(self.source, self.output)
        self.assertIn(f'src="{uri}"', self.output.read_text(encoding='utf8'))

    def test_src_replacement_retains_other_attributes_and_quoting(self):
        (self.root/'asset.png').write_bytes(PNG)
        for attributes in ["data-src='placeholder.png' src='asset.png'", 'data-src="placeholder.png" src=asset.png',
                           '''title=" src='placeholder.png' " src='asset.png' ''']:
            data = image_document('asset.png')
            data['slides'][0]['body'] = '<div id="evidence"><p>设备型号识别材料。</p><img ' + attributes + ' alt="设备图片"></div>'
            self.write(data)
            render(self.source, self.output, replace=True)
            output = self.output.read_text(encoding='utf8')
            self.assertIn('placeholder.png', output)
            self.assertIn('src="data:image/png;base64,', output)
            self.assertIn('alt="设备图片"', output)

    def test_missing_local_image_does_not_write_or_replace_output(self):
        self.write(image_document('missing.png'))
        with self.assertRaises(ReportImageError) as raised:
            render(self.source, self.output)
        self.assertEqual(raised.exception.issue['page'], 1)
        self.assertFalse(self.output.exists())
        self.output.parent.mkdir()
        self.output.write_text('original', encoding='utf8')
        with self.assertRaises(ReportImageError):
            render(self.source, self.output, replace=True, preserve_layout=True)
        self.assertEqual(self.output.read_text(), 'original')

    def test_renderer_cli_returns_structured_missing_image_failure(self):
        self.write(image_document('missing.png'))
        run = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(SCRIPTS/'render_report.py'),
                              str(self.source), str(self.output)], capture_output=True, text=True, encoding='utf8')
        self.assertEqual(run.returncode, 1)
        result = json.loads(run.stdout)
        self.assertFalse(result['passed'])
        self.assertEqual(result['image_issues'][0]['page'], 1)
        self.assertNotIn('Traceback', run.stderr)


@unittest.skipUnless(Path(BROWSER).is_file(), 'Set REPORT_BROWSER to an installed Chromium browser')
class BrowserChecksTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True, executable_path=BROWSER)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='report-browser-checks-')
        self.root = Path(self.directory.name)
        self.source, self.output = self.root/'source_CO.json', self.root/'report_CO.html'
        self.page = self.browser.new_page(viewport={'width':1280, 'height':764})
        self.page.context.set_offline(True)

    def tearDown(self):
        self.page.close()
        self.directory.cleanup()

    def open(self, data, old_html=False):
        self.source.write_text(json.dumps(data, ensure_ascii=False), encoding='utf8')
        render(self.source, self.output, replace=True)
        if old_html:
            self.output.write_text(re.sub(r' data-visual-plan="[^"]*"', '', self.output.read_text(encoding='utf8')), encoding='utf8')
        self.page.goto(self.output.as_uri())
        self.page.wait_for_function("document.documentElement.dataset.ready==='true'")
        self.page.evaluate('show(0)')

    def test_css_hidden_svg_fails_in_screen_and_print(self):
        self.open(chart_document(css='#graphic .native-chart svg{visibility:hidden}'))
        for media in ['screen', 'print']:
            self.page.emulate_media(media=media)
            issues = check_visuals(self.page, 0, media)
            self.assertTrue(issues)
            self.assertEqual(issues[0]['target'], 'graphic')
            self.assertEqual(issues[0]['page'], 1)
            self.assertEqual(issues[0]['media'], media)

    def test_print_only_hidden_svg_is_separately_detected(self):
        self.open(chart_document(css='@media print{#graphic svg{display:none}}'))
        self.assertFalse(check_visuals(self.page, 0, 'screen'))
        self.page.emulate_media(media='print')
        self.assertTrue(check_visuals(self.page, 0, 'print'))

    def test_ancestor_opacity_and_zero_effective_geometry_fail(self):
        for css in ['#graphic{opacity:0}', '#graphic .native-chart{opacity:0}',
                    '#graphic svg{transform:scale(0)}', '#graphic rect{opacity:0}',
                    '#graphic rect{fill:transparent}']:
            with self.subTest(css=css):
                self.open(chart_document(css=css))
                self.assertTrue(check_visuals(self.page, 0, 'screen'))

    def test_old_html_falls_back_to_native_chart(self):
        self.open(chart_document(css='.native-chart svg{visibility:hidden}'), old_html=True)
        self.assertTrue(check_visuals(self.page, 0, 'screen'))

    def test_zero_bars_and_horizontal_lines_remain_valid(self):
        for form in ['bar', 'hbar', 'stacked', 'line', 'waterfall']:
            for values in [[0, 0], [0], [10, 10]]:
                with self.subTest(form=form, values=values):
                    self.open(chart_document(form, values))
                    for media in ['screen', 'print']:
                        self.page.emulate_media(media=media)
                        self.assertFalse(check_visuals(self.page, 0, media))
                    self.page.emulate_media(media='screen')

    def test_custom_horizontal_connector_and_old_html_fallback(self):
        data = image_document('data:image/png;base64,' + base64.b64encode(PNG).decode())
        slide = data['slides'][0]
        slide['body'] = '<figure id="network" data-visual="network"><div data-node="a">采购方</div><div data-node="b">服务方</div><svg viewBox="0 0 600 100"><path data-from="a" data-to="b" d="M10 20 H500" fill="none" stroke="blue"/></svg><p>支付与交付按合同执行。</p></figure>'
        slide['visual_plan'].update(relation='flow', form='network', target='network')
        self.open(data, old_html=True)
        self.assertFalse(check_visuals(self.page, 0, 'screen'))
        self.page.add_style_tag(content='[data-from]{opacity:0}')
        self.assertTrue(check_visuals(self.page, 0, 'screen'))
        self.page.add_style_tag(content='[data-from]{opacity:1;stroke:none}')
        self.assertTrue(check_visuals(self.page, 0, 'screen'))

    def test_zero_hbar_arbitrary_value_suffix_remains_valid(self):
        for suffix in ['元', '元/人', '(万元)', '%']:
            data = chart_document('hbar', [0, 0])
            data['slides'][0]['blocks'][0]['value_suffix'] = suffix
            self.open(data)
            self.assertFalse(check_visuals(self.page, 0, 'screen'))

    def test_embedded_image_loads_and_broken_image_is_reported(self):
        (self.root/'asset.png').write_bytes(PNG)
        self.open(image_document('asset.png'))
        self.assertFalse(check_images(self.page))
        self.page.locator('img').evaluate("img=>img.src='missing.png'")
        issues = check_images(self.page)
        self.assertTrue(issues)
        self.assertEqual(issues[0]['page'], 1)
        self.assertEqual(issues[0]['naturalWidth'], 0)
        self.assertFalse(issues[0]['decoded'])

    def test_export_cli_rejects_hidden_chart_with_structured_result(self):
        self.open(chart_document(css='#graphic .native-chart svg{visibility:hidden}'))
        out = self.root/'checks_CO'
        run = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(SCRIPTS/'export_and_check.py'),
                              str(self.output), '--browser', BROWSER, '--out', str(out)],
                             capture_output=True, text=True, encoding='utf8')
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        result = json.loads(run.stdout)
        self.assertFalse(result['passed'])
        self.assertEqual({issue['media'] for issue in result['visual_issues']}, {'screen', 'print'})
        self.assertNotIn('Traceback', run.stderr)

    def test_export_cli_rejects_missing_image_and_marks_offline_false(self):
        (self.root/'asset.png').write_bytes(PNG)
        self.open(image_document('asset.png'))
        output = re.sub(r'src="data:[^"]+"', 'src="missing.png"', self.output.read_text(encoding='utf8'))
        self.output.write_text(output, encoding='utf8')
        run = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(SCRIPTS/'export_and_check.py'),
                              str(self.output), '--browser', BROWSER, '--out', str(self.root/'checks_CO')],
                             capture_output=True, text=True, encoding='utf8')
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        result = json.loads(run.stdout)
        self.assertFalse(result['passed'])
        self.assertFalse(result['offline'])
        self.assertEqual(result['image_issues'][0]['page'], 1)
        self.assertTrue(result['request_failures'])
        self.assertNotIn('Traceback', run.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
