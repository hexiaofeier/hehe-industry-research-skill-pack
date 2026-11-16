"""Semantic report components. Text stays complete; pagination stays with the author."""
import html,json,math,re
from business_components import business_block,chart_svg
from analytical_charts import TYPES as ANALYTICAL_TYPES, chart_html as analytical_chart_html, small_multiples_html

def e(x): return html.escape(str(x),quote=True)
def paragraphs(items):
    return ''.join(f'<p data-source="{e(x.get("source",""))}">{e(x["text"])}</p>' if isinstance(x,dict) else f'<p>{e(x)}</p>' for x in items)

def chart_html(b):
    if b['chart_type'] in ANALYTICAL_TYPES:return analytical_chart_html(b)
    if b['chart_type'] in {'hbar','waterfall'}:return chart_svg(b)
    labels,series=b['labels'],b['series']
    if b['chart_type'] not in {'bar','line','stacked'}: raise ValueError('图表支持 bar、line、stacked')
    if not labels or not series:raise ValueError('图表缺少数据')
    for s in series:
        if len(s['values'])!=len(labels) or any(not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 for v in s['values']):raise ValueError('图表数值需为非负有限数，且与类别等长')
    colors=['#27647f','#208e91','#b78647','#8ba6b2']
    w,h=740,330; left,top,pw,ph=60,25,650,245
    maxv=max(sum(s['values'][i] for s in series) for i in range(len(labels))) if b['chart_type']=='stacked' else max(v for s in series for v in s['values'])
    ymax=b.get('max',maxv*1.2 or 1)
    if ymax<maxv:raise ValueError('纵轴最大值小于实际数据')
    svg=[]
    for k in range(5):
        v=ymax*k/4;y=top+ph-ph*k/4
        svg.append(f'<line x1="{left}" y1="{y}" x2="{left+pw}" y2="{y}" stroke="#d8e2e7"/><text x="{left-10}" y="{y+5}" text-anchor="end" fill="#627682" font-size="14">{v:g}</text>')
    stride=pw/len(labels)
    for i,label in enumerate(labels):svg.append(f'<text x="{left+stride*(i+.5)}" y="{top+ph+27}" text-anchor="middle" fill="#344c59" font-size="15">{e(label)}</text>')
    for j,s in enumerate(series):
        color=colors[j%len(colors)];points=[]
        for i,v in enumerate(s['values']):
            x=left+stride*(i+.5); y=top+ph-ph*v/ymax
            if b['chart_type']=='line':
                points.append(f'{x},{y}');svg.append(f'<circle cx="{x}" cy="{y}" r="4" fill="{color}"/>')
            else:
                bw=stride*.62/(1 if b['chart_type']=='stacked' else len(series))
                x=left+stride*(i+.19)+(j*bw if b['chart_type']=='bar' else 0)
                if b['chart_type']=='stacked':y-=ph*sum(series[k]['values'][i] for k in range(j))/ymax
                svg.append(f'<rect x="{x}" y="{y}" width="{bw}" height="{ph*v/ymax}" fill="{color}"/>')
                if len(labels)*len(series)<=18:svg.append(f'<text x="{x+bw/2}" y="{y-5 if b["chart_type"]=="bar" else y+ph*v/ymax/2+5}" text-anchor="middle" font-size="14" fill="{color if b["chart_type"]=="bar" else "white"}">{v:g}</text>')
        if points:svg.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="3"/>')
    legend=''.join(f'<span><i style="background:{colors[j%4]}"></i>{e(s["name"])}</span>' for j,s in enumerate(series))
    alt='；'.join(f'{lab}：'+ '、'.join(f'{s["name"]}{s["values"][i]}{b.get("unit","")}' for s in series) for i,lab in enumerate(labels))
    return f'<figure class="report-chart"><div class="chart-heading">{e(b.get("title",""))}<span>{e(b.get("unit",""))}</span></div><div class="chart-legend">{legend}</div><div class="native-chart" data-chart="{e(json.dumps(b,ensure_ascii=False))}"><svg viewBox="0 0 {w} {h}" role="img" aria-label="{e(alt)}">{"".join(svg)}</svg></div><figcaption>{e(b.get("source",""))}</figcaption></figure>'

def _block_html(b,canvas='16:9'):
    t=b['type']
    if t=='small_multiples':return small_multiples_html(b,canvas)
    result=business_block(b,canvas)
    if result is not None:return result
    if t=='prose':return f'<div class="prose">'+(f'<h2>{e(b["title"])}</h2>' if b.get('title') else '')+paragraphs(b['paragraphs'])+'</div>'
    if t=='split':
        ratio=b.get('ratio','1.5fr 1fr')
        if ratio not in {'1fr 1fr','1.5fr 1fr','1fr 1.5fr','2fr 1fr'}:raise ValueError('不支持的栏宽')
        return f'<div class="report-split" style="grid-template-columns:{ratio}">'+''.join('<div>'+blocks_html(col,canvas)+'</div>' for col in b['columns'])+'</div>'
    if t=='table':
        cols=b['columns'];rows=b['rows']
        if any(len(r)!=len(cols) for r in rows):raise ValueError('表格行列数不匹配')
        widths=b.get('widths',[1]*len(cols));den=sum(widths)
        return '<table class="research-table semantic-table"><colgroup>'+''.join(f'<col style="width:{v/den*100}%">' for v in widths)+'</colgroup><thead><tr>'+''.join(f'<th>{e(x)}</th>' for x in cols)+'</tr></thead><tbody>'+''.join('<tr>'+''.join(f'<td data-label="{e(cols[i])}">{e(x)}</td>' for i,x in enumerate(row))+'</tr>' for row in rows)+'</tbody></table>'
    if t=='flow':return '<div class="report-flow">'+''.join(f'<div class="flow-step"><span class="step-number">{i+1:02}</span><div><h2>{e(x["title"])}</h2>{paragraphs(x["paragraphs"])}</div></div>' for i,x in enumerate(b['steps']))+'</div>'
    if t=='timeline':return '<div class="report-timeline">'+''.join(f'<div class="timeline-row"><div class="period">{e(x["period"])}</div><div><h2>{e(x["title"])}</h2>{paragraphs(x["paragraphs"])}</div></div>' for x in b['items'])+'</div>'
    if t=='finding':return f'<aside class="report-finding"><h2>{e(b["title"])}</h2>{paragraphs(b["paragraphs"])}</aside>'
    if t=='chart':return chart_html(b)
    if t=='metrics':return '<div class="report-metrics">'+''.join(f'<div><span class="metric-value">{e(x["value"])}</span><h2>{e(x["title"])}</h2>{paragraphs(x["paragraphs"])}</div>' for x in b['items'])+'</div>'
    if t=='source':return f'<p class="source-brief">{e(b["text"])}</p>'
    raise ValueError(f'未知组件：{t}')

def block_html(b,canvas='16:9'):
    result = _block_html(b,canvas)
    if b.get('id'):
        result = re.sub(r'^(<[a-z][a-z0-9-]*)', lambda m: m[1]+' id="'+e(b['id'])+'"', result, count=1)
    return result

def blocks_html(blocks,canvas='16:9'):return ''.join(block_html(b,canvas) for b in blocks)
