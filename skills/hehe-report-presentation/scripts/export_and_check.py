"""Render every page, check geometry and navigation, export searchable PDF."""
import argparse,json,re
from pathlib import Path
from urllib.parse import quote
from playwright.sync_api import sync_playwright
import fitz
from analytical_charts import TYPES as ANALYTICAL_TYPES, render_svg

def normalize(text): return re.sub(r'\s+','',text)

def check_visuals(page, number, media):
    """Check computed browser visibility, including the print stylesheet."""
    # The fresh SVG supplies the expected real marks and legitimate degenerate
    # geometry. Computed browser paint/geometry below still checks the live DOM.
    analytical = {}
    for raw in page.locator('.slide').nth(number).locator('.native-chart').evaluate_all(
            '(nodes)=>nodes.map(node=>node.getAttribute("data-chart"))'):
        try:
            spec = json.loads(raw)
            if isinstance(spec, dict) and spec.get('chart_type') in ANALYTICAL_TYPES:
                try:
                    analytical[raw] = render_svg(spec)
                except (KeyError, TypeError, ValueError, OverflowError):
                    analytical[raw] = None
        except (TypeError, ValueError):
            pass
    return page.evaluate(r'''({number,media,analytical,analyticalTypes})=>{
        const slide=document.querySelectorAll('.slide')[number],issues=[];
        const issue=(target,el,reason)=>issues.push({page:Number(slide.dataset.page),media,target,
            object:el?(el.id||el.getAttribute('data-node')||el.getAttribute('data-point')||el.tagName.toLowerCase()):'target',reason});
        const transparent=c=>!c||c==='none'||c==='transparent'||/rgba\([^)]*,\s*0(?:\.0+)?\s*\)/.test(c);
        function styled(el){
            if(!el)return '对象不存在';
            for(let node=el;node&&node.nodeType===1;node=node.parentElement){
                const css=getComputedStyle(node);
                if(css.display==='none'||css.contentVisibility==='hidden')return 'display/content-visibility 隐藏';
                if(Number(css.opacity)<=0)return '对象或祖先 opacity 为 0';
                if(node.hasAttribute('hidden'))return '对象或祖先带 hidden';
            }
            const css=getComputedStyle(el);
            if(css.visibility==='hidden'||css.visibility==='collapse')return 'visibility 隐藏';
            return '';
        }
        function visible(el,zero=false,single=false){
            const hidden=styled(el);if(hidden)return hidden;
            const box=el.getBoundingClientRect(),tag=el.tagName.toLowerCase(),css=getComputedStyle(el);
            if(el instanceof SVGElement&&['path','line','polyline','polygon','rect','circle','ellipse'].includes(tag)){
                const fill=!transparent(css.fill)&&Number(css.fillOpacity)>0;
                const stroke=!transparent(css.stroke)&&Number(css.strokeOpacity)>0&&parseFloat(css.strokeWidth)>0;
                if(!fill&&!stroke)return '图元没有可见填色或描边';
                if(['line','polyline','path'].includes(tag)){
                    let length=0;try{length=el.getTotalLength();}catch(_){return '图元几何不可读';}
                    if(length<=0&&!single)return '线段长度为 0';
                    if(!stroke&&(tag!=='path'||el.matches('[data-from][data-to],[data-axis],[data-divider],[data-series]')||box.width<=0||box.height<=0))return '线段没有可见描边';
                    // Horizontal/vertical lines legitimately have a zero bbox dimension.
                    if(box.width<=0&&box.height<=0&&!single)return '图元的有效几何为 0';
                }else if(zero){
                    if(box.width<=0&&box.height<=0)return '零值柱的有效宽度为 0';
                }else if(box.width<=0||box.height<=0)return '图元的有效面积为 0';
            }else if(box.width<=0||box.height<=0)return '对象的有效面积为 0';
            if((el.dataset.connector==='true'||el.classList.contains('branch-arrow'))&&transparent(css.color))return '文字箭头颜色透明';
            return '';
        }
        function analyticalBounds(el){
            const number=key=>Number(el.getAttribute(key)||0),tag=el.tagName.toLowerCase();
            if(tag==='rect')return [number('x'),number('y'),number('width'),number('height')];
            if(tag==='circle')return [number('cx')-number('r'),number('cy')-number('r'),2*number('r'),2*number('r')];
            let points;
            if(tag==='line')points=[[number('x1'),number('y1')],[number('x2'),number('y2')]];
            else if(tag==='polyline'||tag==='polygon'){
                const values=(el.getAttribute('points')||'').trim().split(/[\s,]+/).map(Number);
                if(values.length<2||values.length%2)return null;
                points=values.reduce((out,v,i)=>{if(i%2===0)out.push([v,values[i+1]]);return out;},[]);
            }else return null;
            const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]);
            return [Math.min(...xs),Math.min(...ys),Math.max(...xs)-Math.min(...xs),Math.max(...ys)-Math.min(...ys)];
        }
        function analyticalChart(chart,svg,spec,target){
            const source=analytical[chart.dataset.chart];
            if(!source){issue(target,chart,'分析图数据合同无效，无法核对实际图元');return;}
            const expected=new DOMParser().parseFromString(source,'image/svg+xml').documentElement;
            const actual=[...svg.querySelectorAll('*')],wanted=[...expected.querySelectorAll('*')];
            if(actual.length!==wanted.length){issue(target,svg,'分析图实际图元或文字数量与数据不一致');return;}
            if(svg.getAttribute('viewBox')!==expected.getAttribute('viewBox'))issue(target,svg,'分析图实际画布尺度与数据不一致');
            for(let i=0;i<wanted.length;i++){
                const el=actual[i],reference=wanted[i],tag=el.tagName.toLowerCase();
                if(tag!==reference.tagName.toLowerCase()||['data-role','data-kind'].some(key=>el.getAttribute(key)!==reference.getAttribute(key))){
                    issue(target,el,'分析图实际数据图元、轴或标签与规范图形不对应');continue;
                }
                const bounds=analyticalBounds(reference),zero=bounds&&(bounds[2]===0||bounds[3]===0);
                const single=bounds&&bounds[2]===0&&bounds[3]===0;
                let why=visible(el,zero,single);
                if(why){issue(target,el,why);continue;}
                const matrix=el.getScreenCTM(),viewport=svg.getScreenCTM();
                if(!matrix||!viewport||Math.abs(matrix.a*matrix.d-matrix.b*matrix.c)<1e-12)
                    issue(target,el,'分析图的有效坐标变换退化');
                else if(['a','b','c','d','e','f'].some(key=>Math.abs(matrix[key]-viewport[key])>.05))
                    issue(target,el,'分析图图元的额外坐标变换改变了规范几何');
                if(tag==='text'||tag==='tspan'){
                    const css=getComputedStyle(el);
                    if(el.textContent!==reference.textContent)issue(target,el,'分析图可见数值、类别或说明与数据不一致');
                    if((transparent(css.fill)||Number(css.fillOpacity)<=0)&&
                       (transparent(css.stroke)||Number(css.strokeOpacity)<=0||parseFloat(css.strokeWidth)<=0))
                        issue(target,el,'分析图文字没有可见填色或描边');
                }else if(bounds){
                    const box=el.getBBox(),geometry=[box.x,box.y,box.width,box.height];
                    if(bounds.some((value,j)=>!Number.isFinite(value)||Math.abs(value-geometry[j])>.05))
                        issue(target,el,'分析图实际几何与数值尺度不一致');
                }
            }
            const panel=chart.closest('.report-chart');
            if(panel)for(const label of panel.querySelectorAll('.chart-heading,figcaption')){
                const why=visible(label);if(why)issue(target,label,why);
                else if(transparent(getComputedStyle(label).color))issue(target,label,'分析图标题或来源文字透明');
            }
        }
        let plans=[];
        try{plans=JSON.parse(slide.dataset.visualPlan||'[]');if(!Array.isArray(plans))plans=[plans];}
        catch(_){issue('',slide,'visual_plan 元数据无法解析');}
        let targets=plans.map(plan=>({form:plan.form,target:plan.target,
            nodes:[...document.querySelectorAll('[id]')].filter(el=>el.id===plan.target&&slide.contains(el))}));
        if(!targets.length){
            // Older generated HTML and faithful conversions do not carry a plan.
            targets=[...slide.querySelectorAll('.native-chart,[data-visual]')].map(el=>{
                let form=el.dataset.visual;
                if(!form)try{form=JSON.parse(el.dataset.chart).chart_type;}catch(_){}
                return {form,target:el.id||el.closest('[id]')?.id||'.native-chart',nodes:[el]};
            });
        }
        for(const {form,target,nodes} of targets){
            if(nodes.length!==1){issue(target,null,'方案目标未唯一对应本页对象');continue;}
            const root=nodes[0],hidden=visible(root);
            if(hidden){issue(target,root,hidden);continue;}
            if(form==='prose'||form==='table')continue;
            const charts=[...(root.matches('.native-chart')?[root]:root.querySelectorAll('.native-chart'))];
            if(analyticalTypes.includes(form)&&!charts.length){
                const owner=root.closest('.native-chart');
                if(owner)charts.push(owner);
                else{issue(target,root,'分析图缺少可核对的标准数据合同');continue;}
            }
            if(charts.length){
                for(const chart of charts){
                    let spec;try{spec=JSON.parse(chart.dataset.chart);}catch(_){issue(target,chart,'原生图表数据无法解析');continue;}
                    const svg=chart.querySelector('svg');let why=visible(svg);
                    if(why){issue(target,svg,why);continue;}
                    const type=spec.chart_type;
                    if(analyticalTypes.includes(type)){analyticalChart(chart,svg,spec,target);continue;}
                    const values=type==='waterfall'?spec.values:(spec.series||[]).flatMap(s=>s.values||[]);
                    const marks=[...svg.querySelectorAll(type==='line'?'circle,ellipse':'rect')];
                    if(!marks.length){issue(target,svg,'缺少实际数据图元');continue;}
                    let zeroes=0;
                    for(const mark of marks){
                        const zero=type!=='line'&&Number(mark.getAttribute(type==='hbar'?'width':'height'))===0;
                        if(zero)zeroes++;
                        why=visible(mark,zero);if(why)issue(target,mark,why);
                    }
                    if(type!=='line'&&zeroes!==values.filter(v=>v===0).length)issue(target,chart,'零面积柱与零值数据不一致');
                    if(type==='line'){
                        const lines=[...svg.querySelectorAll('polyline')];
                        if(!lines.length)issue(target,svg,'缺少连接折线');
                        for(const line of lines){why=visible(line,false,spec.labels?.length===1);if(why)issue(target,line,why);}
                    }else if(values.length&&values.every(v=>v===0)){
                        if(![...svg.querySelectorAll('line,path,polyline')].some(el=>!visible(el)))issue(target,svg,'全零图缺少可见基线');
                        const suffix=String(spec.value_suffix||'');
                        if(![...svg.querySelectorAll('text')].some(el=>{
                            let text=el.textContent.trim();if(suffix&&text.endsWith(suffix))text=text.slice(0,-suffix.length);
                            return !visible(el)&&/^[-+]?0+(?:\.0+)?$/.test(text);
                        }))issue(target,svg,'全零图缺少可见零值标签');
                    }
                }
                continue;
            }
            const marked=[...root.querySelectorAll('[data-node],[data-from][data-to],[data-value],[data-point],[data-region],[data-axis],[data-divider],[data-series]')];
            const component={flow:'.flow-step,.analysis-stage',timeline:'.timeline-row',gantt:'.gantt-bar',
                branch_merge:'.branch-row,.branch-arrow,.merge-result',swimlane:'.swimlane-grid>*,.portrait-phase',journey:'.journey-grid>*,.portrait-phase'}[form];
            const elements=marked.length?marked:(component?[...root.querySelectorAll(component)]:[]);
            if(!elements.length){issue(target,root,'未找到实际图形对象');continue;}
            for(const el of elements){const why=visible(el);if(why)issue(target,el,why);}
            for(const svg of root.querySelectorAll('svg')){const why=visible(svg);if(why)issue(target,svg,why);}
        }
        return issues;
    }''',{'number':number,'media':media,'analytical':analytical,'analyticalTypes':list(ANALYTICAL_TYPES)})


def check_images(page):
    return page.evaluate(r'''async()=>{
        const images=[...document.images];
        return (await Promise.all(images.map(async(img,index)=>{
            img.loading='eager';let decoded=true;
            try{await Promise.race([img.decode(),new Promise((_,reject)=>setTimeout(()=>reject(new Error('timeout')),5000))]);}catch(_){decoded=false;}
            if(img.complete&&decoded&&img.naturalWidth>0&&img.naturalHeight>0)return null;
            return {page:Number(img.closest('.slide')?.dataset.page||0),object:img.id||img.alt||`img[${index+1}]`,
                src:(img.currentSrc||img.src||'').slice(0,200),complete:img.complete,decoded,naturalWidth:img.naturalWidth,
                reason:'图片未成功加载或解码'};
        }))).filter(Boolean);
    }''')


def main():
    ap=argparse.ArgumentParser();ap.add_argument('html');ap.add_argument('--browser',required=True);ap.add_argument('--out',required=True);ap.add_argument('--replace',action='store_true')
    args=ap.parse_args();source=Path(args.html).resolve();out=Path(args.out).resolve()
    out.mkdir(parents=True,exist_ok=True)
    pdf=source.with_suffix('.pdf')
    if pdf.exists() and not args.replace:raise FileExistsError(pdf)
    result={'html':str(source),'pages':[],'browser_errors':[],'pdf_text_missing':[],
            'visual_issues':[],'image_issues':[],'request_failures':[]}
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path=args.browser)
        page=browser.new_page(viewport={'width':1280,'height':764},device_scale_factor=1)
        page.context.set_offline(True)
        page.on('pageerror',lambda error:result['browser_errors'].append(str(error)))
        page.on('requestfailed',lambda request:result['request_failures'].append(
            {'url':request.url,'object':request.resource_type,'reason':request.failure})
            if request.resource_type in {'image','stylesheet','script','font','document'} else None)
        page.goto(source.as_uri());page.wait_for_function("document.documentElement.dataset.ready==='true'")
        result['image_issues']=check_images(page)
        for failure in result['request_failures']:
            failure['page']=page.evaluate('''url=>Number([...document.images].find(img=>img.src===url||img.currentSrc===url)?.closest('.slide')?.dataset.page||0)''',failure['url'])
        canvas=page.locator('body').get_attribute('data-canvas') or '16:9'; scroll=canvas=='scroll'; result['canvas']=canvas
        width,height=page.evaluate("[parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--page-w')),parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--page-h'))]")
        page.set_viewport_size({'width':int(width),'height':int(height+44) if height else 900})
        count=page.locator('.slide').count()
        pdf_units=[]
        def navigation_reached(target):
            if not scroll:
                return page.locator('#pages').input_value()==str(target)
            page.wait_for_timeout(90)
            return page.evaluate('''n=>{const s=document.querySelectorAll('.slide')[n];if(!s)return false;const r=s.getBoundingClientRect(),h=s.querySelector('h1').getBoundingClientRect();return Math.abs(r.top)<150||(h.top>=0&&h.bottom<=innerHeight&&scrollY+innerHeight>=document.documentElement.scrollHeight-3)}''',target)
        for n in range(count):
            page.evaluate('(n)=>show(n)',n)
            result['visual_issues'].extend(check_visuals(page,n,'screen'))
            row=page.evaluate('''n=>{const s=document.querySelectorAll('.slide')[n],box=s.getBoundingClientRect(),footer=s.querySelector('footer').getBoundingClientRect(),content=s.querySelector('.content');const nodes=[...s.querySelectorAll('h1,.lead,h2,p,td,th,.qty,.name,.work,.output,.role h2,.chapter-route>span,.toc-link')].filter(e=>e.getBoundingClientRect().height>0);const issues=[];let maxBottom=0;for(const el of nodes){const b=el.getBoundingClientRect();if(b.top<box.top-1||b.right>box.right-4||b.left<box.left-1||b.bottom>footer.top-8)issues.push({type:'page_boundary',text:el.textContent.slice(0,55),bottom:b.bottom,footer:footer.top});if(el.scrollWidth>el.clientWidth+2)issues.push({type:'horizontal_overflow',text:el.textContent.slice(0,55)});if(content.contains(el))maxBottom=Math.max(maxBottom,b.bottom);const r=document.createRange();r.selectNodeContents(el);const rects=[...r.getClientRects()];if(rects.some(x=>x.right>b.right+3||x.bottom>b.bottom+3))issues.push({type:'text_container',text:el.textContent.slice(0,55)});}return {number:Number(s.dataset.page),title:s.querySelector('h1').textContent,layout:s.dataset.layout,kind:s.className,issues,body_bottom:maxBottom,blank_before_footer:footer.top-maxBottom,font:getComputedStyle(content).fontFamily,units:[...s.querySelectorAll('h1,.lead,h2,p,td,th,.interview-row>.name,.interview-row>.qty,.interview-row>div:last-child,.week>.work,.week>.output')].map(e=>e.textContent.trim())}}''',n)
            pdf_units.append(row.pop('units'));result['pages'].append(row)
            page.locator('.slide').nth(n).screenshot(path=str(out/f'P{n+1:02}_CO.png'))
        page.evaluate('show(0)')
        if count>1:page.locator('#next').click()
        result['next_button']=navigation_reached(min(1,count-1))
        keyboard_target=min(int(page.locator('#pages').input_value())+1,count-1)
        page.keyboard.press('ArrowRight');result['keyboard']=navigation_reached(keyboard_target)
        if scroll:
            page.set_viewport_size({'width':1440,'height':960});page.evaluate('show(0)')
            result['sidebar_links']=[]
            result['sidebar_active_targets']=[]
            links=page.locator('#report-toc a')
            for i in range(links.count()):
                link=links.nth(i);target=link.evaluate('a=>decodeURIComponent(a.hash.slice(1))')
                link.click();page.wait_for_timeout(90)
                result['sidebar_links'].append(page.evaluate('id=>{const h=document.getElementById(id);if(!h)return false;const r=h.getBoundingClientRect();return Math.abs(r.top)<150||(r.top>=0&&r.bottom<=innerHeight&&scrollY+innerHeight>=document.documentElement.scrollHeight-3)}',target))
                at_bottom=page.evaluate('scrollY+innerHeight>=document.documentElement.scrollHeight-3')
                last_highlighted=links.last.get_attribute('aria-current')=='location'
                # At the document end several short sections can be visible together.
                result['sidebar_active_targets'].append(link.get_attribute('aria-current')=='location' or
                    (at_bottom and last_highlighted and result['sidebar_links'][-1]))
            page.locator('#report-toc a').first.click();page.wait_for_timeout(90)
            result['sidebar_highlight']=page.locator('#report-toc a[aria-current="location"]').count()==1
            page.evaluate("window.scrollTo(0,0);document.getElementById('report-sidebar').scrollTop=0")
            page.screenshot(path=str(out/'桌面侧栏预览_CO.png'))
            page.emulate_media(media='print')
            result['print_sidebar_hidden']=page.locator('#report-sidebar').evaluate('e=>getComputedStyle(e).display')=='none'
            page.emulate_media(media='screen')
        result['toc']=[]
        page.evaluate('show(0)')
        for i in range(page.locator('.toc-link').count()):
            a=page.locator('.toc-link').nth(i);parent=a.evaluate("el=>Number(el.closest('.slide').dataset.page)-1");page.evaluate('(n)=>show(n)',parent);target=int(re.search(r'show\((\d+)\)',a.get_attribute('onclick')).group(1));a.click();result['toc'].append(page.locator('#pages').input_value()==str(target))
        page.set_viewport_size({'width':390,'height':844});page.evaluate('(n)=>show(n)',min(2,count-1));box=page.locator('.slide.active').bounding_box();result['phone_ratio']=box['width']/box['height'];result['offline']=not(result['image_issues'] or result['request_failures']);result['phone_overflow']=page.evaluate('document.documentElement.scrollWidth>innerWidth+2');page.screenshot(path=str(out/'手机预览_CO.png'))
        if scroll:
            result['phone_toc_collapsed']=not page.locator('#report-sidebar').is_visible()
            page.locator('#toc-toggle').click();result['phone_toc_open']=page.locator('#report-sidebar').is_visible()
            page.screenshot(path=str(out/'手机目录预览_CO.png'))
            page.locator('#report-toc a').nth(min(1,page.locator('#report-toc a').count()-1)).click()
            result['phone_toc_closes_after_click']=not page.locator('#report-sidebar').is_visible()
        page.set_viewport_size({'width':int(width),'height':int(height+44) if height else 900});page.evaluate('show(0)')
        page.emulate_media(media='print')
        for n in range(count):result['visual_issues'].extend(check_visuals(page,n,'print'))
        page.pdf(path=str(pdf),print_background=True,display_header_footer=False,prefer_css_page_size=True)
        browser.close()
    doc=fitz.open(pdf);result['pdf_pages']=len(doc);result['pdf_sizes']=[list(p.rect)[2:] for p in doc]
    for i,units in enumerate(pdf_units):
        text=normalize(''.join(p.get_text() for p in doc)) if scroll else (normalize(doc[i].get_text()) if i<len(doc) else '')
        for unit in units:
            if normalize(unit) not in text:result['pdf_text_missing'].append({'page':i+1,'text':unit[:90]})
    ratio=210/297 if canvas in {'scroll','A4'} else width/height
    result['pdf_ratio_correct']=all(abs(p.rect.width/p.rect.height-ratio)<.003 for p in doc)
    result['pdf_browser_header_absent']=not any('file:///' in p.get_text() for p in doc)
    result['pdf_colored_text']=any(span['color'] not in [0,0xffffff] for p in doc for block in p.get_text('dict')['blocks'] if 'lines' in block for line in block['lines'] for span in line['spans'])
    for n in [0,min(6,len(doc)-1),min(15,len(doc)-1),min(28,len(doc)-1)]:doc[n].get_pixmap(matrix=fitz.Matrix(1,1)).save(str(out/f'PDF_P{n+1:02}_CO.png'))
    result['passed']=not(result['browser_errors'] or result['pdf_text_missing'] or result['visual_issues'] or result['image_issues'] or result['request_failures'] or any(r['issues'] for r in result['pages']) or result['phone_overflow']) and result['pdf_ratio_correct'] and result['pdf_browser_header_absent'] and result['next_button'] and result['keyboard'] and all(result['toc']) and (scroll or len(doc)==count)
    if scroll:result['passed']=result['passed'] and all(result['sidebar_links']) and all(result['sidebar_active_targets']) and result['sidebar_highlight'] and result['print_sidebar_hidden'] and result['phone_toc_collapsed'] and result['phone_toc_open'] and result['phone_toc_closes_after_click']
    if result['passed']:
        # Expose the download only after the PDF has been created and checked.
        text=source.read_text(encoding='utf8')
        link=f'<a id="download" href="{quote(pdf.name)}" download>下载 PDF</a>'
        text,updated=re.subn(r'<a id="download"[^>]*>.*?</a>|<!--PDF_DOWNLOAD-->',lambda _:link,text,count=1)
        if updated:source.write_text(text,encoding='utf8')
        result['pdf_download_link_updated']=bool(updated)
    (out/'技术核验_CO.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'canvas':canvas,'passed':result['passed'],'pages':count,'geometry_issues':[(r['number'],r['issues']) for r in result['pages'] if r['issues']], 'visual_issues':result['visual_issues'],'image_issues':result['image_issues'],'request_failures':result['request_failures'],'offline':result['offline'], 'pdf_pages':len(doc),'pdf_ratio_correct':result['pdf_ratio_correct'],'pdf_text_missing':result['pdf_text_missing'],'navigation':result['next_button'] and result['keyboard'] and all(result['toc'])},ensure_ascii=False))

    if not result['passed']:raise SystemExit(1)

if __name__=='__main__':
    try:main()
    except Exception as error:
        result={'passed':False,'error':str(error),'error_type':type(error).__name__}
        # Operational failures use the same machine-readable failure contract.
        import sys
        try:
            destination=Path(sys.argv[sys.argv.index('--out')+1]);destination.mkdir(parents=True,exist_ok=True)
            (destination/'技术核验_CO.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        except (ValueError,IndexError,OSError):pass
        print(json.dumps(result,ensure_ascii=False));raise SystemExit(1)
