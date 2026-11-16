"""Regression checks for native chart paint/labels and isolated SVG images.

Run with ``python -m unittest discover -s scripts -p test_pptx_export.py -v``.
SVG checks use Playwright's installed Chromium, or REPORT_PPTX_BROWSER.
"""
import base64
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright
from pptx import Presentation
from pptx.enum.chart import XL_LABEL_POSITION,XL_TICK_LABEL_POSITION
from pptx.oxml.ns import qn
from pptx.util import Pt

from export_pptx import add_chart, convert, rasterize_svg


class NativeChartTests(unittest.TestCase):
    def chart(self, kind, series=None):
        prs=Presentation();slide=prs.slides.add_slide(prs.slide_layouts[6])
        spec={'chart_type':kind,'labels':['甲','乙'],
              'series':series or [{'name':'一','values':[60.25,45]},
                                 {'name':'二','values':[25,35]},
                                 {'name':'三','values':[14.75,20]}]}
        if kind=='waterfall':spec.update(values=[100,120],totals=[0,1])
        chart=add_chart(slide,{'x':10,'y':10,'w':740,'h':330,'spec':spec})
        output=io.BytesIO();prs.save(output);output.seek(0)
        reopened=Presentation(output).slides[0].shapes[0].chart
        return reopened,output

    def test_line_has_continuous_colored_strokes_after_reopen(self):
        chart,_=self.chart('line')
        for series,expected in zip(chart.series,['27647F','208E91','B78647']):
            line=series._element.find(qn('c:spPr')).find(qn('a:ln'))
            self.assertIsNone(line.find(qn('a:noFill')))
            self.assertEqual(line.find(qn('a:solidFill')).find(qn('a:srgbClr')).get('val'),expected)
            self.assertEqual(series.format.line.width,Pt(2.25))
            self.assertEqual(str(series.marker.format.fill.fore_color.rgb),expected)
        self.assertEqual(chart.series[0].values,(60.25,45.0))

    def test_stacked_labels_show_exact_values_in_the_columns(self):
        chart,output=self.chart('stacked')
        labels=chart.plots[0].data_labels
        self.assertTrue(chart.plots[0].has_data_labels)
        self.assertTrue(labels.show_value)
        self.assertEqual(labels.position,XL_LABEL_POSITION.CENTER)
        self.assertEqual(labels.number_format,'General')
        self.assertTrue(labels.number_format_is_linked)
        self.assertEqual(str(labels.font.color.rgb),'FFFFFF')
        self.assertEqual([s.values for s in chart.series],[(60.25,45.0),(25.0,35.0),(14.75,20.0)])
        # The editable workbook, as well as the cached plot data, keeps decimals.
        with ZipFile(output) as archive:
            workbook=next(n for n in archive.namelist() if n.startswith('ppt/embeddings/'))
            with ZipFile(io.BytesIO(archive.read(workbook))) as embedded:
                sheet=embedded.read('xl/worksheets/sheet1.xml').decode('utf-8')
                self.assertIn('<v>60.25</v>',sheet)
                self.assertIn('<v>14.75</v>',sheet)

    def test_negative_bars_keep_the_series_fill_after_reopen(self):
        chart,_=self.chart('hbar',[{'name':'变化','values':[-10,-20]}])
        self.assertFalse(chart.series[0].invert_if_negative)
        self.assertEqual(str(chart.series[0].format.fill.fore_color.rgb),'27647F')
        self.assertEqual(chart.series[0].values,(-10.0,-20.0))

    def test_negative_hbar_categories_remain_left_of_the_plot_after_reopen(self):
        for values in [[-10,-20],[-14.7,39.4]]:
            with self.subTest(values=values):
                chart,_=self.chart('hbar',[{'name':'变化','values':values}])
                self.assertEqual(chart.category_axis.tick_label_position,XL_TICK_LABEL_POSITION.LOW)
                self.assertEqual(chart.series[0].values,tuple(map(float,values)))

    def test_positive_hbar_keeps_the_existing_category_position(self):
        chart,_=self.chart('hbar',[{'name':'水平','values':[10,20]}])
        self.assertEqual(chart.category_axis.tick_label_position,XL_TICK_LABEL_POSITION.NEXT_TO_AXIS)

    def test_other_chart_types_keep_their_label_and_fill_behavior(self):
        for kind in ['bar','hbar']:
            with self.subTest(kind=kind):
                chart,_=self.chart(kind)
                self.assertEqual(chart.plots[0].data_labels.position,XL_LABEL_POSITION.OUTSIDE_END)
                self.assertIsNotNone(chart.series[0]._element.find('.//'+qn('a:noFill')))
        chart,_=self.chart('waterfall')
        self.assertEqual(len(chart.series),4)
        self.assertEqual(chart.series[0].values,(0.0,0.0))
        self.assertIsNotNone(chart.series[0]._element.find(qn('c:spPr')).find(qn('a:noFill')))


SVG_FIXTURE='''<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;background:#ffd500}
.slide{position:relative;width:200px;height:100px;background:#ffd500;overflow:hidden;opacity:.5}
.clip{position:absolute;left:120px;top:20px;width:60px;height:80px;overflow:hidden;opacity:.5;
      color:rgb(0,128,0);font:20px "Courier New",monospace}
.art{position:relative;left:10px;width:120px;height:80px;fill:currentColor}
h1{position:absolute;left:130px;top:20px;width:200px;color:red;font-size:28px;margin:0;z-index:2}
.other{position:absolute;left:130px;top:20px;width:70px;height:80px}
</style></head><body data-canvas="16:9"><section class="slide active">
<div class="clip"><svg class="art" viewBox="0 0 120 80" xmlns="http://www.w3.org/2000/svg">
<rect width="120" height="20"/><text x="0" y="50">WWW</text>
<rect y="60" width="120" height="20" fill="magenta" style="visibility:hidden"/>
</svg></div><h1>旧标题重叠</h1>
<svg class="other"><rect width="70" height="80" fill="red"/></svg>
</section><script>document.documentElement.dataset.ready='true';function show(){}</script></body></html>'''


class IsolatedSvgTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright=sync_playwright().start()
        cls.browser_path=os.environ.get('REPORT_PPTX_BROWSER',cls.playwright.chromium.executable_path)
        if not Path(cls.browser_path).is_file():
            cls.playwright.stop()
            raise unittest.SkipTest('Chromium unavailable; set REPORT_PPTX_BROWSER')
        cls.browser=cls.playwright.chromium.launch(executable_path=cls.browser_path,headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close();cls.playwright.stop()

    def setUp(self):
        self.page=self.browser.new_page(viewport={'width':300,'height':200})
        self.page.set_content(SVG_FIXTURE)
        self.page.evaluate('()=>document.fonts.ready')

    def tearDown(self):
        self.page.close()

    def test_svg_pixels_keep_inheritance_opacity_transparency_and_clipping(self):
        before=self.page.content();clip={'x':130,'y':20,'width':70,'height':80}
        isolated=Image.open(io.BytesIO(rasterize_svg(self.page,self.page.locator('.art'),clip))).convert('RGBA')
        self.assertEqual(self.page.content(),before)
        # An unobstructed original-DOM render is an independent pixel reference.
        self.page.locator('h1,.other').evaluate_all('nodes=>nodes.forEach(e=>e.remove())')
        self.page.add_style_tag(content='html,body,.slide{background:transparent!important}')
        reference=Image.open(io.BytesIO(self.page.screenshot(clip=clip,omit_background=True))).convert('RGBA')
        self.assertIsNone(ImageChops.difference(isolated,reference).getbbox())
        self.assertEqual(isolated.size,(70,80))
        self.assertIn(isolated.getpixel((5,5))[3],[63,64])  # .5 * .5 ancestor opacity
        self.assertEqual(isolated.getpixel((55,5))[3],0)    # ancestor overflow
        self.assertEqual(isolated.getpixel((5,70))[3],0)    # hidden SVG child
        red,green,blue,alpha=isolated.split()
        self.assertIsNotNone(ImageChops.multiply(ImageChops.subtract(green,red),alpha).getbbox())
        self.assertIsNone(ImageChops.multiply(ImageChops.subtract(red,green),alpha).getbbox())

    def test_page_styles_restore_when_screenshot_fails(self):
        before=self.page.content()
        with patch.object(self.page,'screenshot',side_effect=RuntimeError('capture failed')):
            with self.assertRaisesRegex(RuntimeError,'capture failed'):
                rasterize_svg(self.page,self.page.locator('.art'),{'x':130,'y':20,'width':70,'height':80})
        self.assertEqual(self.page.content(),before)

    def test_bitmap_keeps_fit_clipping_and_opacity_without_overlapping_text(self):
        raw=io.BytesIO();image=Image.new('RGB',(200,100),'blue')
        image.paste('green',(100,0,200,100));image.save(raw,format='PNG')
        src='data:image/png;base64,'+base64.b64encode(raw.getvalue()).decode('ascii')
        self.page.set_content('''<style>html,body{margin:0;background:yellow}
.clip{position:relative;width:60px;height:70px;overflow:hidden;opacity:.5}
img{position:absolute;left:10px;top:10px;width:80px;height:80px;object-fit:cover}
h1{position:absolute;left:10px;top:10px;color:red;margin:0}</style>
<div class="clip"><img src="'''+src+'''"></div><h1>原标题</h1>''')
        self.page.locator('img').evaluate('e=>e.decode()')
        before=self.page.content();clip={'x':10,'y':10,'width':80,'height':80}
        isolated=Image.open(io.BytesIO(rasterize_svg(self.page,self.page.locator('img'),clip))).convert('RGBA')
        self.assertEqual(self.page.content(),before)
        self.page.locator('h1').evaluate('e=>e.remove()')
        self.page.add_style_tag(content='html,body{background:transparent!important}')
        reference=Image.open(io.BytesIO(self.page.screenshot(clip=clip,omit_background=True))).convert('RGBA')
        self.assertIsNone(ImageChops.difference(isolated,reference).getbbox())
        self.assertIn(isolated.getpixel((5,5))[3],[127,128])
        self.assertEqual(isolated.getpixel((55,5))[3],0)
        self.assertEqual(isolated.getpixel((5,65))[3],0)

class EndToEndPptxTests(unittest.TestCase):
    def test_convert_keeps_overlapping_title_as_native_text_only(self):
        with sync_playwright() as playwright:
            browser_path=os.environ.get('REPORT_PPTX_BROWSER',playwright.chromium.executable_path)
        if not Path(browser_path).is_file():self.skipTest('Chromium unavailable; set REPORT_PPTX_BROWSER')
        # Exclude the deliberately occluding second SVG from this one-picture test.
        source=SVG_FIXTURE.replace('<svg class="other"><rect width="70" height="80" fill="red"/></svg>','')
        with tempfile.TemporaryDirectory() as directory:
            html=Path(directory)/'重叠标题_CO.html';output=Path(directory)/'可编辑_CO.pptx'
            html.write_text(source,encoding='utf-8')
            convert(html,output,browser_path)
            slide=Presentation(output).slides[0]
            self.assertTrue(any(s.has_text_frame and s.text=='旧标题重叠' for s in slide.shapes))
            pictures=[s for s in slide.shapes if s.shape_type==13]
            self.assertEqual(len(pictures),1)
            image=Image.open(io.BytesIO(pictures[0].image.blob)).convert('RGBA')
            self.assertEqual(image.size,(70,80))  # slide crops the 120px SVG
            red,green,blue,alpha=image.split()
            self.assertIsNone(ImageChops.multiply(ImageChops.subtract(red,green),alpha).getbbox())
            self.assertEqual(alpha.getextrema()[0],0)

    def test_png_and_jpeg_local_and_data_uri_survive_as_separate_pictures(self):
        with sync_playwright() as playwright:
            browser_path=os.environ.get('REPORT_PPTX_BROWSER',playwright.chromium.executable_path)
        if not Path(browser_path).is_file():self.skipTest('Chromium unavailable; set REPORT_PPTX_BROWSER')
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            for fmt,mime in [('PNG','image/png'),('JPEG','image/jpeg')]:
                data=io.BytesIO();Image.new('RGB',(100,50),(32,142,145)).save(data,format=fmt)
                image=folder/('产品_CO.'+('png' if fmt=='PNG' else 'jpg'));image.write_bytes(data.getvalue())
                for source_type in ['local','data']:
                    with self.subTest(format=fmt,source=source_type):
                        src=image.name if source_type=='local' else 'data:'+mime+';base64,'+base64.b64encode(data.getvalue()).decode('ascii')
                        html=folder/(fmt+source_type+'_CO.html');output=html.with_suffix('.pptx')
                        html.write_text(image_fixture(src),encoding='utf8')
                        convert(html,output,browser_path)
                        slide=Presentation(output).slides[0]
                        pictures=[s for s in slide.shapes if s.shape_type==13]
                        self.assertEqual(len(pictures),1)
                        self.assertTrue(any(s.has_text_frame and s.text=='独立标题' for s in slide.shapes))
                        pic=pictures[0]
                        self.assertAlmostEqual(pic.left/9525,40,places=2)
                        self.assertAlmostEqual(pic.top/9525,70,places=2)
                        self.assertAlmostEqual(pic.width/9525,200,places=2)
                        self.assertAlmostEqual(pic.height/9525,100,places=2)
                        bitmap=Image.open(io.BytesIO(pic.image.blob)).convert('RGB')
                        self.assertEqual(bitmap.size,(200,100))
                        # The red overlapping HTML title must remain outside the picture.
                        self.assertLessEqual(ImageChops.subtract(bitmap.getchannel('R'),bitmap.getchannel('G')).getextrema()[1],3)
                        self.assertTrue(all(abs(a-b)<=3 for a,b in zip(bitmap.getpixel((100,50)),(32,142,145))))
                        manifest=json_load(output.with_name(output.stem+'_对象核验_CO.json'))
                        self.assertEqual(manifest['image_elements'][0]['element'],'HTML图片')

    def test_missing_or_invalid_image_fails_before_writing_ppt(self):
        with sync_playwright() as playwright:
            browser_path=os.environ.get('REPORT_PPTX_BROWSER',playwright.chromium.executable_path)
        if not Path(browser_path).is_file():self.skipTest('Chromium unavailable; set REPORT_PPTX_BROWSER')
        with tempfile.TemporaryDirectory() as directory:
            for name,src in [('missing','missing-product.png'),('broken','data:image/png;base64,broken')]:
                with self.subTest(source=name):
                    html=Path(directory)/(name+'_CO.html');output=html.with_suffix('.pptx')
                    html.write_text(image_fixture(src),encoding='utf8')
                    with self.assertRaisesRegex(ValueError,'第1页图片未成功加载'):
                        convert(html,output,browser_path)
                    self.assertFalse(output.exists())

    def test_nested_svg_is_one_picture_without_double_opacity(self):
        with sync_playwright() as playwright:
            browser_path=os.environ.get('REPORT_PPTX_BROWSER',playwright.chromium.executable_path)
        if not Path(browser_path).is_file():self.skipTest('Chromium unavailable; set REPORT_PPTX_BROWSER')
        source=image_fixture('').replace('<img src="" alt="产品图片">','''<svg xmlns="http://www.w3.org/2000/svg" style="position:absolute;left:40px;top:70px;width:200px;height:100px" viewBox="0 0 200 100"><rect width="200" height="100" fill="white"/><svg x="80" y="20" width="80" height="60" viewBox="0 0 80 60"><rect width="80" height="60" fill="red" fill-opacity=".5"/></svg></svg>''')
        with tempfile.TemporaryDirectory() as directory:
            html=Path(directory)/'嵌套_CO.html';output=html.with_suffix('.pptx')
            html.write_text(source,encoding='utf8');convert(html,output,browser_path)
            pictures=[s for s in Presentation(output).slides[0].shapes if s.shape_type==13]
            self.assertEqual(len(pictures),1)
            pixel=Image.open(io.BytesIO(pictures[0].image.blob)).convert('RGB').getpixel((120,50))
            self.assertEqual(pixel[0],255)
            self.assertIn(pixel[1],[127,128]);self.assertIn(pixel[2],[127,128])


def image_fixture(src):
    return '''<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;background:white}.slide{position:relative;width:400px;height:240px;overflow:hidden;background:white}
img{position:absolute;left:40px;top:70px;width:200px;height:100px;object-fit:cover}
h1{position:absolute;left:80px;top:90px;margin:0;color:red;font:24px Arial;z-index:2}
</style></head><body data-canvas="16:9"><section class="slide active"><img src="'''+src+'''" alt="产品图片"><h1>独立标题</h1></section>
<script>document.documentElement.dataset.ready='true';function show(){}</script></body></html>'''


def json_load(path):
    import json
    return json.loads(path.read_text(encoding='utf8'))


if __name__=='__main__':
    unittest.main(verbosity=2)
