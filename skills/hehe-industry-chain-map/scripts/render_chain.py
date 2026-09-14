#!/usr/bin/env python3
"""Render a positioned industry-chain JSON into SVG, Mermaid source and offline HTML.

Python standard library only. SVG uses the supplied orthogonal geometry; Mermaid
preserves nodes and relationships, not the manually arranged SVG coordinates.
"""

import argparse
import html
import json
import math
import re
import sys
from pathlib import Path


NODE_STYLES = {
    "normal": ("#ffffff", "#b7d0df", "#194861", "#58788e", ""),
    "core": ("#e7f2f7", "#276580", "#123f59", "#58788e", ""),
    "terminal": ("#194861", "#194861", "#ffffff", "#d2e5ef", ""),
    "support": ("#fbfdff", "#9fbaca", "#194861", "#58788e", "7 6"),
    "policy": ("#fff4f2", "#d79a98", "#a14e4b", "#58788e", ""),
}
EDGE_STYLES = {
    "main": ("#277598", ""),
    "support": ("#7895a7", "7 6"),
    "policy": ("#b15a56", "8 6"),
}
EPS = 0.01


def number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field}: expected a finite number")
    return value


def required_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}: expected non-empty text")
    return value


def boundary(point, node):
    x, y = point
    left, top, right, bottom = node["x"], node["y"], node["x"] + node["w"], node["y"] + node["h"]
    return ((abs(x-left) < EPS or abs(x-right) < EPS) and top-EPS <= y <= bottom+EPS
            or (abs(y-top) < EPS or abs(y-bottom) < EPS) and left-EPS <= x <= right+EPS)


def crosses_interior(a, b, node):
    left, top, right, bottom = node["x"], node["y"], node["x"] + node["w"], node["y"] + node["h"]
    if abs(a[0]-b[0]) < EPS:
        return left+EPS < a[0] < right-EPS and max(min(a[1], b[1]), top+EPS) < min(max(a[1], b[1]), bottom-EPS)
    return top+EPS < a[1] < bottom-EPS and max(min(a[0], b[0]), left+EPS) < min(max(a[0], b[0]), right-EPS)


def validate(data):
    if not isinstance(data, dict):
        raise ValueError("Root must be a JSON object")
    required_text(data.get("title"), "title")
    if not isinstance(data.get("subtitle", ""), str):
        raise ValueError("subtitle must be text")
    if data.get("direction", "TB") not in ("TB", "TD", "BT", "LR", "RL"):
        raise ValueError("direction must be TB, TD, BT, LR or RL")
    width, height = number(data.get("width"), "width"), number(data.get("height"), "height")
    if width <= 0 or height <= 0:
        raise ValueError("Canvas width and height must be positive")
    if not isinstance(data.get("nodes"), list) or not data["nodes"]:
        raise ValueError("nodes must be a non-empty list")
    if not isinstance(data.get("edges"), list):
        raise ValueError("edges must be a list")
    nodes = {}
    for node in data["nodes"]:
        if not isinstance(node, dict):
            raise ValueError("Each node must be an object")
        key = required_text(node.get("id"), "node.id")
        if key in nodes:
            raise ValueError(f"Duplicate node id: {key}")
        required_text(node.get("title"), f"{key}.title")
        if not isinstance(node.get("lines", []), list) or not all(isinstance(s, str) for s in node.get("lines", [])):
            raise ValueError(f"{key}.lines must be a list of strings")
        if node.get("kind", "normal") not in NODE_STYLES:
            raise ValueError(f"{key}: unknown node kind")
        for field in ("x", "y", "w", "h"):
            number(node.get(field), f"{key}.{field}")
        if node["w"] <= 0 or node["h"] <= 0:
            raise ValueError(f"{key}: node size must be positive")
        if node["x"] < 0 or node["y"] < 0 or node["x"]+node["w"] > width or node["y"]+node["h"] > height:
            raise ValueError(f"{key}: node outside canvas")
        for other in nodes.values():
            if (max(node["x"], other["x"]) < min(node["x"]+node["w"], other["x"]+other["w"]) - EPS
                    and max(node["y"], other["y"]) < min(node["y"]+node["h"], other["y"]+other["h"]) - EPS):
                raise ValueError(f"Overlapping nodes: {key}, {other['id']}")
        nodes[key] = node
    for index, edge in enumerate(data["edges"]):
        if not isinstance(edge, dict):
            raise ValueError(f"Edge {index} must be an object")
        if edge.get("source") not in nodes or edge.get("target") not in nodes:
            raise ValueError(f"Edge {index}: unknown source or target")
        required_text(edge.get("label"), f"edge {index}.label")
        if edge.get("type", "main") not in EDGE_STYLES:
            raise ValueError(f"Edge {index}: unknown relationship type")
        points = edge.get("points")
        if not isinstance(points, list) or len(points) < 2:
            raise ValueError(f"Edge {index}: provide at least two orthogonal points")
        for point in points:
            if not isinstance(point, list) or len(point) != 2:
                raise ValueError(f"Edge {index}: each point must be [x, y]")
            x, y = number(point[0], "point.x"), number(point[1], "point.y")
            if not (0 <= x <= width and 0 <= y <= height):
                raise ValueError(f"Edge {index}: point outside canvas")
        if not boundary(points[0], nodes[edge["source"]]) or not boundary(points[-1], nodes[edge["target"]]):
            raise ValueError(f"Edge {index}: endpoints must touch source/target boundaries")
        if edge["source"] == edge["target"] and all(abs(a-b) < EPS for a, b in zip(points[0], points[-1])):
            raise ValueError(f"Edge {index}: a self loop needs distinct exit and entry points")
        for a, b in zip(points, points[1:]):
            if abs(a[0]-b[0]) >= EPS and abs(a[1]-b[1]) >= EPS:
                raise ValueError(f"Edge {index}: diagonal segment; use orthogonal points")
            if abs(a[0]-b[0]) < EPS and abs(a[1]-b[1]) < EPS:
                raise ValueError(f"Edge {index}: repeated adjacent point")
            for node in nodes.values():
                if crosses_interior(a, b, node):
                    raise ValueError(f"Edge {index}: segment crosses node {node['id']}")
        for field, limit in (("label_x", width), ("label_y", height)):
            value = number(edge.get(field), f"Edge {index}.{field}")
            if not 0 <= value <= limit:
                raise ValueError(f"Edge {index}: {field} outside canvas")
        left, top, box_width, box_height = label_box(edge)
        if left < 0 or top < 0 or left+box_width > width or top+box_height > height:
            raise ValueError(f"Edge {index}: label box outside canvas; move or shorten label")
        for node in nodes.values():
            if (max(left, node["x"]) < min(left+box_width, node["x"]+node["w"]) - EPS
                    and max(top, node["y"]) < min(top+box_height, node["y"]+node["h"]) - EPS):
                raise ValueError(f"Edge {index}: label covers node {node['id']}; move or shorten label")
    return data


def char_units(text):
    return sum(1 if ord(c) > 127 else 0.56 for c in text)


def label_box(edge):
    """Estimated text backing box; final font metrics still require visual review."""
    lines = edge["label"].split("\n")
    width = max(char_units(line) for line in lines)*15+16
    height = len(lines)*21+4
    return edge["label_x"]-width/2, edge["label_y"]-16, width, height


def wrap(text, units):
    result, line = [], ""
    for char in text:
        if char == "\n" or (line and char_units(line+char) > units):
            result.append(line)
            line = "" if char == "\n" else char
        else:
            line += char
    if line:
        result.append(line)
    return result or [""]


def esc(text):
    return html.escape(str(text), quote=True)


def text_element(x, y, text, size, color, weight="400"):
    return f'<text x="{x:g}" y="{y:g}" text-anchor="middle" font-size="{size}" font-weight="{weight}" fill="{color}">{esc(text)}</text>'


def render_svg(data):
    width, height = data["width"], data["height"]
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:g}" height="{height:g}" viewBox="0 0 {width:g} {height:g}" role="img" aria-labelledby="chart-title chart-desc" data-node-count="{len(data["nodes"])}" data-edge-count="{len(data["edges"])}">',
           f'<title id="chart-title">{esc(data["title"])}</title>',
           f'<desc id="chart-desc">{esc(data.get("subtitle", ""))}</desc>',
           '<defs><linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#f8fbfe"/><stop offset="1" stop-color="#f0f7fb"/></linearGradient>']
    for kind, (color, _) in EDGE_STYLES.items():
        out.append(f'<marker id="arrow-{kind}" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto" markerUnits="userSpaceOnUse"><path d="M 0 0 L 10 4 L 0 8 Z" fill="{color}"/></marker>')
    out += ['</defs>', f'<rect width="{width:g}" height="{height:g}" fill="url(#bg)" rx="20"/>',
            '<g font-family="Microsoft YaHei, Noto Sans CJK SC, PingFang SC, Arial, sans-serif">',
            text_element(width/2, 42, data["title"], 26, "#194861", "700"),
            text_element(width/2, 72, data.get("subtitle", ""), 14, "#67869a")]
    # Draw connectors below cards, then their labels last so labels remain readable.
    for index, edge in enumerate(data["edges"]):
        kind = edge.get("type", "main")
        color, dash = EDGE_STYLES[kind]
        points = " ".join(f"{x:g},{y:g}" for x, y in edge["points"])
        out.append(f'<polyline data-edge-index="{index}" data-source="{esc(edge["source"])}" data-target="{esc(edge["target"])}" points="{points}" fill="none" stroke="{color}" stroke-width="2.4" stroke-dasharray="{dash}" marker-end="url(#arrow-{kind})" stroke-linejoin="round"/>')
    for node in data["nodes"]:
        kind = node.get("kind", "normal")
        fill, stroke, title_color, body_color, dash = NODE_STYLES[kind]
        x, y, w, h = [node[k] for k in ("x", "y", "w", "h")]
        out.append(f'<g data-node-id="{esc(node["id"])}"><rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="16" fill="{fill}" stroke="{stroke}" stroke-width="{2.6 if kind == "core" else 1.6}" stroke-dasharray="{dash}"/>')
        title_lines = wrap(node["title"], (w-30)/21)
        body_lines = [line for value in node.get("lines", []) for line in wrap(value, (w-32)/16)]
        text_height = len(title_lines)*27 + (12 if body_lines else 0) + len(body_lines)*24
        if text_height > h-22:
            raise ValueError(f"{node['id']}: text exceeds card height; shorten labels or enlarge card")
        baseline = y+(h-text_height)/2+21
        for line in title_lines:
            out.append(text_element(x+w/2, baseline, line, 21, title_color, "700"))
            baseline += 27
        baseline += 8
        for line in body_lines:
            out.append(text_element(x+w/2, baseline, line, 16, body_color))
            baseline += 24
        out.append('</g>')
    for edge in data["edges"]:
        lines = edge["label"].split("\n")
        left, top, label_width, label_height = label_box(edge)
        x, y = edge["label_x"], edge["label_y"]
        out.append(f'<rect x="{left:g}" y="{top:g}" width="{label_width:g}" height="{label_height:g}" rx="4" fill="#f5f9fc" fill-opacity="0.96"/>')
        for offset, line in enumerate(lines):
            out.append(text_element(x, y+offset*21, line, 15, EDGE_STYLES[edge.get("type", "main")][0], "600"))
    legend = data.get("legend", {"main": "生产、服务与交易关系", "support": "配套与支持关系", "policy": "政策与公共收益关系"})
    active = [kind for kind in EDGE_STYLES if any(e.get("type", "main") == kind for e in data["edges"])]
    start = width/2 - (len(active)-1)*175
    for index, kind in enumerate(active):
        x = start+index*350
        color, dash = EDGE_STYLES[kind]
        out.append(f'<line x1="{x-150:g}" x2="{x-105:g}" y1="{height-33:g}" y2="{height-33:g}" stroke="{color}" stroke-width="2.6" stroke-dasharray="{dash}"/>')
        out.append(text_element(x+20, height-28, legend.get(kind, kind), 14, "#58788e"))
    out += ['</g>', '</svg>']
    return "\n".join(out)+"\n"


def mermaid_text(value):
    # Mermaid's documented decimal entity notation keeps syntax punctuation inert.
    return "".join(f"#{ord(c)};" if c in '#&<>"[]{}|`\\' else c for c in value).replace("\n", "<br/>")


def mermaid_id(value):
    # Stable across reordered/subset diagrams; prefixes avoid reserved words.
    return "n_" + value if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value) else "u_" + value.encode("utf-8").hex()


def render_mermaid(data):
    # Official frontmatter config: mermaid.js.org/config/theming.html and
    # mermaid.js.org/syntax/flowchart.html (Styling line curves).
    out = ["---", "config:", "  theme: base", "  themeVariables:",
           "    fontFamily: 'Microsoft YaHei, Noto Sans CJK SC, PingFang SC, Arial, sans-serif'",
           "    fontSize: '16px'", "    background: '#f5f9fc'",
           "    primaryColor: '#ffffff'", "    primaryTextColor: '#194861'",
           "    primaryBorderColor: '#b7d0df'", "    lineColor: '#277598'",
           "    edgeLabelBackground: '#f5f9fc'",
           "  flowchart:", "    curve: stepAfter", "---",
           "%% Generated from the same nodes and edges as the SVG.",
           "%% Layout is automatic here; manual SVG coordinates are not Mermaid coordinates.",
           f"flowchart {data.get('direction', 'TB')}"]
    names = {node["id"]: mermaid_id(node["id"]) for node in data["nodes"]}
    for node in data["nodes"]:
        out.append(f'    %% {names[node["id"]]} = {json.dumps(node["id"], ensure_ascii=True)}')
        label = "<br/>".join(mermaid_text(line) for line in [node["title"], *node.get("lines", [])])
        out.append(f'    {names[node["id"]]}("{label}"):::{node.get("kind", "normal")}')
    for edge in data["edges"]:
        arrow = "-->" if edge.get("type", "main") == "main" else "-.->"
        out.append(f'    {names[edge["source"]]} {arrow}|"{mermaid_text(edge["label"])}"| {names[edge["target"]]}')
    for kind, (fill, stroke, text, _, dash) in NODE_STYLES.items():
        suffix = f",stroke-dasharray:{dash}" if dash else ""
        out.append(f"    classDef {kind} fill:{fill},stroke:{stroke},color:{text},stroke-width:2px{suffix}")
    for index, edge in enumerate(data["edges"]):
        color, dash = EDGE_STYLES[edge.get("type", "main")]
        suffix = f",stroke-dasharray:{dash}" if dash else ""
        out.append(f"    linkStyle {index} stroke:{color},stroke-width:2px{suffix}")
    return "\n".join(out)+"\n"


def render_html(data, svg, mermaid):
    return (f'<!doctype html>\n<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{esc(data["title"])}</title><style>body{{margin:0;padding:24px;background:#eaf1f6;color:#194861;font-family:"Microsoft YaHei",sans-serif}}'
            'main{max-width:1600px;margin:auto}svg{display:block;width:100%;height:auto}details{margin-top:18px;padding:18px;border-radius:12px;background:white}'
            'pre{white-space:pre-wrap;overflow-wrap:anywhere;color:#33566c;font:14px/1.6 Consolas,monospace}p{font-size:14px;line-height:1.7}</style><main>'
            f'{svg}<p>图示为 SVG；下方是同源 Mermaid 可编辑源码，并非 Mermaid 的实际渲染结果。手工布局保存在输入 JSON 中。</p>'
            f'<details><summary>查看 Mermaid 源码</summary><pre>{esc(mermaid)}</pre></details></main></html>\n')


def write_outputs(data, output_dir, basename, overwrite=False):
    if not basename or basename in (".", "..") or any(c in basename for c in '/\\:*?"<>|'):
        raise ValueError("basename must be a filename without directory separators")
    validate(data)
    svg, mermaid = render_svg(data), render_mermaid(data)
    contents = {".svg": svg, ".mmd": mermaid, ".html": render_html(data, svg, mermaid)}
    output_dir = Path(output_dir)
    paths = [output_dir/(basename+suffix) for suffix in contents]
    existing = [path for path in paths if path.exists()]
    if existing and not overwrite:
        raise FileExistsError("Output already exists; use --overwrite explicitly: "+", ".join(str(p) for p in existing))
    output_dir.mkdir(parents=True, exist_ok=True)
    for path, content in zip(paths, contents.values()):
        with path.open("w" if overwrite else "x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
    return paths


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Positioned nodes/edges JSON (UTF-8)")
    parser.add_argument("--output-dir", required=True, type=Path, help="Write only the named SVG, MMD and HTML files here")
    parser.add_argument("--basename", default="产业链图", help="Output name without extension")
    parser.add_argument("--overwrite", action="store_true", help="Explicitly allow replacing the three output files")
    args = parser.parse_args(argv)
    try:
        with args.input.open(encoding="utf-8-sig") as handle:
            data = json.load(handle)
        paths = write_outputs(data, args.output_dir, args.basename, args.overwrite)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Error: {exc}\n")
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
