"""Reading-first business layouts. Source prose stays in ordinary visible paragraphs."""
import html
import json
import math


def esc(value):
    return html.escape(str(value), quote=True)


def paras(items):
    return ''.join('<p'+(f' data-source="{esc(x.get("source", ""))}"' if isinstance(x, dict) else '')+'>'+esc(x['text'] if isinstance(x, dict) else x)+'</p>' for x in items)


def business_block(b, canvas='16:9'):
    kind = b['type']
    if kind == 'briefing':
        return '<div class="business-brief"><div class="brief-main">'+''.join(f'<section class="brief-section"><h2>{esc(x["title"])}</h2>{paras(x["paragraphs"])}</section>' for x in b['main'])+'</div><aside class="brief-side"><h2>'+esc(b['aside']['title'])+'</h2>'+paras(b['aside']['paragraphs'])+'</aside></div>'
    if kind == 'branch_merge':
        return '<div class="branch-map"><div class="branch-list">'+''.join(f'<section class="branch-row"><h2>{esc(x["title"])}</h2><div>{paras(x["paragraphs"])}</div><span class="branch-arrow" aria-hidden="true">→</span></section>' for x in b['branches'])+'</div><aside class="merge-result"><div class="merge-label">'+esc(b.get('merge_label','综合分析'))+'</div><h2>'+esc(b['result']['title'])+'</h2>'+paras(b['result']['paragraphs'])+'</aside></div>'
    if kind == 'analysis_path':
        return '<div class="analysis-path">'+''.join(f'<section class="analysis-stage"><div class="stage-track"><span>{i+1:02d}</span><div class="track-line"></div></div><h2>{esc(x["title"])}</h2>{paras(x["paragraphs"])}</section>' for i,x in enumerate(b['steps']))+'</div>'
    if kind in {'swimlane','journey'}:
        stages=b['stages']; rows=b['rows']
        if any(len(x['cells']) != len(stages) for x in rows):
            raise ValueError('泳道/旅程每行须与阶段数一致')
        if canvas in {'9:16','A4'}:
            groups=[]
            for i,stage in enumerate(stages):
                cells=''.join('<tr><th>'+esc(row['label'])+'</th><td>'+paras(row['cells'][i] if isinstance(row['cells'][i],list) else [row['cells'][i]])+'</td></tr>' for row in rows)
                groups.append(f'<section class="portrait-phase"><h2><span>{i+1:02d}</span>{esc(stage)}</h2><table class="stage-table"><tbody>{cells}</tbody></table></section>')
            return '<div class="portrait-matrix">'+''.join(groups)+'</div>'
        return f'<table class="business-grid {kind}-grid"><thead><tr><th>{esc(b.get("axis",""))}</th>'+''.join(f'<th><span class="phase-order">{i+1:02d}</span>{esc(x)}</th>' for i,x in enumerate(stages))+'</tr></thead><tbody>'+''.join('<tr><th scope="row">'+esc(x['label'])+'</th>'+''.join(f'<td data-label="{esc(stages[i])}">{paras(c if isinstance(c,list) else [c])}</td>' for i,c in enumerate(x['cells']))+'</tr>' for x in rows)+'</tbody></table>'
    if kind == 'gantt':
        periods=b['periods']; n=len(periods)
        out='<div class="business-gantt"><div class="gantt-head"><span>'+esc(b.get('work_label','研究工作'))+'</span><div class="gantt-periods" style="grid-template-columns:repeat('+str(n)+',1fr)">'+''.join('<span>'+esc(x)+'</span>' for x in periods)+'</div><span>'+esc(b.get('result_label','交付与确认'))+'</span></div>'
        for x in b['items']:
            start,end=x['start'],x['end']
            if not (isinstance(start,int) and isinstance(end,int) and 1<=start<=end<=n):
                raise ValueError('甘特条起止须落在已给定的时间轴内')
            cells=''.join('<span></span>' for _ in periods)
            period_text=periods[start-1] if start==end else periods[start-1]+'—'+periods[end-1]
            heading=f'<h2>{esc(x["title"])}</h2>' if x.get("title") else ""
            out+=f'<div class="gantt-row"><div class="gantt-work">{heading}{paras(x.get("paragraphs",[]))}</div><div class="gantt-plot" style="--periods:{n}"><span class="gantt-period-note">{esc(period_text)}</span><div class="gantt-grid">{cells}</div><div class="gantt-bar" style="left:{(start-1)/n*100}%;width:{(end-start+1)/n*100}%"><span>{esc(x.get("bar_label", ""))}</span></div></div><div class="gantt-result">{paras(x["deliverables"])}</div></div>'
        return out+'</div>'
    return None


def chart_svg(b):
    kind=b['chart_type']; labels=b['labels']; colors=['#27647f','#208e91','#b78647','#8ba6b2']
    if not labels:raise ValueError('图表缺少类别')
    def valid(vals):
        return len(vals)==len(labels) and all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in vals)
    if kind=='hbar':
        series=b['series']
        if not series or any(not valid(s['values']) for s in series):raise ValueError('横向条形数据无效')
        vals=[v for s in series for v in s['values']];lo=min(0,min(vals));hi=max(0,max(vals));span=hi-lo or 1
        lo=lo-span*.08 if lo<0 else 0;hi=hi+span*.16
        if b.get("max") is not None:
            if b["max"]<max(vals):raise ValueError("横向条形最大值小于实际数据")
            hi=b["max"]
        left,right,top=190,710,22
        label_lines=[[str(label)[j:j+10] for j in range(0,len(str(label)),10)] or [''] for label in labels]
        row_min=max(70,max(len(lines) for lines in label_lines)*20+18,len(series)*24+14)
        w,h=760,max(300,len(labels)*row_min+40)
        scale=lambda v:left+(v-lo)/(hi-lo)*(right-left)
        svg=[f'<line x1="{scale(0)}" y1="{top}" x2="{scale(0)}" y2="{h-28}" stroke="#b5cbd4"/>']
        for i,label in enumerate(labels):
            row=(h-top-28)/len(labels);cy=top+(i+.5)*row;bh=min(22,(row-18-(len(series)-1)*4)/len(series))
            lines=label_lines[i];label_top=cy-(len(lines)-1)*10
            label_text=esc(lines[0]) if len(lines)==1 else ''.join(f'<tspan x="{left-14}" y="{label_top+k*20}">{esc(line)}</tspan>' for k,line in enumerate(lines))
            svg.append(f'<text x="{left-14}" y="{label_top}" text-anchor="end" dominant-baseline="central" fill="#243e4d" font-size="16">{label_text}</text>')
            group_height=len(series)*bh+(len(series)-1)*4
            for j,s in enumerate(series):
                v=s['values'][i];y=cy-group_height/2+j*(bh+4);x=min(scale(0),scale(v));width=abs(scale(v)-scale(0));fill=colors[j%4]
                svg.append(f'<rect x="{x}" y="{y}" width="{width}" height="{bh}" fill="{fill}"/>')
                svg.append(f'<text x="{scale(v)+(7 if v>=0 else -7)}" y="{y+bh/2}" text-anchor="{"start" if v>=0 else "end"}" dominant-baseline="central" fill="#243e4d" font-size="15">{v:g}{esc(b.get("value_suffix",""))}</text>')
        legend=[(s['name'],colors[j%4]) for j,s in enumerate(series)]
        alt='；'.join(f'{label}：'+ '、'.join(f'{s["name"]}{s["values"][i]}{b.get("unit","")}' for s in series) for i,label in enumerate(labels))
    elif kind=='waterfall':
        vals=b['values'];totals=set(b.get('totals',[0,len(vals)-1]))
        if not valid(vals) or 0 not in totals:raise ValueError('瀑布图须给定有限数及起点总额')
        current=0;steps=[]
        for i,v in enumerate(vals):
            if i in totals:
                if i and not math.isclose(current,v,rel_tol=1e-8,abs_tol=1e-8):raise ValueError('瀑布图合计与前序增减不一致')
                base=0;end=v;current=v
            else:base=current;end=current+v;current=end
            if min(base,end)<0:raise ValueError('当前瀑布组件支持累计值非负的利润/成本桥；跨零累计用专用图表')
            steps.append((base,end))
        w,h=760,350;left,top,pw,ph=45,24,690,245
        raw=(max(max(x) for x in steps)*1.15 or 1)/4;power=10**math.floor(math.log10(raw))
        tick=next(v for v in [1,2,2.5,3,4,5,10] if v>=raw/power)*power;ymax=tick*4
        sy=lambda v:top+ph-v/ymax*ph
        svg=[];stride=pw/len(labels)
        for k in range(5):
            v=ymax*k/4;y=sy(v);svg.append(f'<line x1="{left}" x2="{left+pw}" y1="{y}" y2="{y}" stroke="#dce6e9"/><text x="{left-8}" y="{y+4}" text-anchor="end" font-size="12" fill="#627682">{v:g}</text>')
        for i,(label,(a,z)) in enumerate(zip(labels,steps)):
            x=left+i*stride+stride*.15;bw=stride*.7;fill='#173f54' if i in totals else ('#238d88' if vals[i]>0 else '#a6674d')
            svg.append(f'<rect x="{x}" y="{sy(max(a,z))}" width="{bw}" height="{abs(z-a)/ymax*ph}" fill="{fill}"/>')
            value=f'{vals[i]:g}' if i in totals else f'{vals[i]:+g}'
            svg.append(f'<text x="{x+bw/2}" y="{sy(max(a,z))-7}" text-anchor="middle" font-size="15" fill="#243e4d">{value}</text>')
            if i<len(labels)-1:svg.append(f'<line x1="{x+bw}" x2="{x+stride}" y1="{sy(z)}" y2="{sy(z)}" stroke="#8ba4af" stroke-dasharray="3 3"/>')
            for j in range(0,len(label),7):svg.append(f'<text x="{x+bw/2}" y="{top+ph+24+j//7*18}" text-anchor="middle" font-size="14" fill="#243e4d">{esc(label[j:j+7])}</text>')
        legend=[('总额','#173f54'),('增加','#238d88'),('减少','#a6674d')]
        alt='；'.join(f'{label}{v:g}{b.get("unit","")}' for label,v in zip(labels,vals))
    else:raise ValueError(kind)
    legends=''.join(f'<span><i style="background:{color}"></i>{esc(name)}</span>' for name,color in legend)
    return f'<figure class="report-chart"><div class="chart-heading">{esc(b.get("title",""))}<span>{esc(b.get("unit",""))}</span></div><div class="chart-legend">{legends}</div><div class="native-chart" data-chart="{esc(json.dumps(b,ensure_ascii=False))}"><svg viewBox="0 0 {w} {h}" role="img" aria-label="{esc(alt)}">{"".join(svg)}</svg></div><figcaption>{esc(b.get("source",""))}</figcaption></figure>'
