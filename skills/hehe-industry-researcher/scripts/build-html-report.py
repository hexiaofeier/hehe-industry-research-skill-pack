#!/usr/bin/env python3
"""把定稿 Markdown 主报告转换为同内容、可离线阅读的 HTML 阅读版。"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

try:
    import markdown
    from bs4 import BeautifulSoup, NavigableString, Tag
except ImportError as exc:  # pragma: no cover - 只在缺少运行依赖时触发
    raise SystemExit(
        "缺少公开 Python 依赖。请先运行："
        "python -m pip install Markdown beautifulsoup4"
    ) from exc


def normalize_old_tables(text: str) -> str:
    """删除旧报告中插在同一 Markdown 管道表相邻行之间的空行。"""
    lines = text.splitlines()
    normalized: list[str] = []
    for index, line in enumerate(lines):
        if not line.strip():
            previous = next(
                (lines[pos].strip() for pos in range(index - 1, -1, -1) if lines[pos].strip()),
                "",
            )
            following = next(
                (lines[pos].strip() for pos in range(index + 1, len(lines)) if lines[pos].strip()),
                "",
            )
            if previous.startswith("|") and following.startswith("|"):
                continue
        normalized.append(line)
    return "\n".join(normalized)


def extract_template_part(template: str, tag: str) -> str:
    match = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", template, re.S | re.I)
    if not match:
        raise ValueError(f"HTML 模板缺少 <{tag}> 区块")
    return match.group(1).strip()


def text_key(value: str) -> str:
    return re.sub(r"\s+", "", value)


def parse_args() -> argparse.Namespace:
    skill_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="把定稿 Markdown 主报告转换为同内容、可离线阅读的 HTML 阅读版。"
    )
    parser.add_argument("input", type=Path, help="输入 Markdown 主报告")
    parser.add_argument("output", type=Path, help="输出 HTML 文件")
    parser.add_argument("--report-type", required=True, help="报告类型，如：行业＋企业研究报告")
    parser.add_argument("--scope", required=True, help="封面显示的研究范围")
    parser.add_argument("--data-cutoff", required=True, help="数据截止日，建议 YYYY-MM-DD")
    parser.add_argument("--version", default="V1.0", help="报告版本，默认 V1.0")
    parser.add_argument(
        "--template",
        type=Path,
        default=skill_root / "assets" / "研究报告HTML模板.html",
        help="HTML 模板路径",
    )
    parser.add_argument("--overwrite", action="store_true", help="允许覆盖已存在的输出文件")
    return parser.parse_args()


def validate_links(soup: BeautifulSoup) -> tuple[int, int]:
    ids = [str(tag["id"]) for tag in soup.select("[id]")]
    duplicate_ids = sorted({item for item in ids if ids.count(item) > 1})
    if duplicate_ids:
        raise ValueError("HTML 存在重复锚点：" + "、".join(duplicate_ids[:8]))

    id_set = set(ids)
    broken = sorted(
        {
            str(link.get("href"))[1:]
            for link in soup.select('a[href^="#"]')
            if str(link.get("href")) != "#" and str(link.get("href"))[1:] not in id_set
        }
    )
    if broken:
        raise ValueError("HTML 存在失效目录锚点：" + "、".join(broken[:8]))

    remote_images = [
        str(image.get("src"))
        for image in soup.find_all("img")
        if re.match(r"^https?://", str(image.get("src", "")), re.I)
    ]
    if remote_images:
        raise ValueError(
            "发现远程图片。请先嵌入 data URI 或改成随报告交付的相对路径："
            + "、".join(remote_images[:3])
        )
    return len(ids), len(soup.select('a[href^="#"]'))


def build(args: argparse.Namespace) -> dict[str, object]:
    source = args.input.resolve()
    output = args.output.resolve()
    template_path = args.template.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"找不到 Markdown 主报告：{source}")
    if not template_path.is_file():
        raise FileNotFoundError(f"找不到 HTML 模板：{template_path}")
    if output.exists() and not args.overwrite:
        raise FileExistsError(f"输出文件已存在；如确认覆盖，请增加 --overwrite：{output}")
    if source == output:
        raise ValueError("输入和输出不能是同一文件")

    source_text = source.read_text(encoding="utf-8-sig")
    fragment = markdown.markdown(
        normalize_old_tables(source_text),
        extensions=["tables", "fenced_code", "toc", "sane_lists"],
        output_format="html5",
    )
    source_soup = BeautifulSoup(fragment, "html.parser")
    h1s = source_soup.find_all("h1")
    if len(h1s) != 1:
        raise ValueError(f"Markdown 主报告必须且只能有一个一级标题；当前为 {len(h1s)} 个")
    title = h1s[0].get_text(" ", strip=True)
    h1s[0].extract()
    h2s = source_soup.find_all("h2")
    if not h2s:
        raise ValueError("Markdown 主报告没有二级章节")
    if "核心摘要" not in h2s[0].get_text(" ", strip=True):
        raise ValueError("Markdown 主报告的首个正文章节必须是“核心摘要”")

    baseline_text = text_key(source_soup.get_text(" ", strip=True))
    source_h2_count = len(h2s)
    source_h3_count = len(source_soup.find_all("h3"))
    source_table_count = len(source_soup.find_all("table"))

    template = template_path.read_text(encoding="utf-8-sig")
    style = extract_template_part(template, "style")
    script = extract_template_part(template, "script")
    style += """
    .page p{margin:0 0 18px}.page ul,.page ol{margin:12px 0 22px;padding-left:1.5em}
    .page li{margin:7px 0}.section h4,.section h5,.section h6{margin:28px 0 10px;color:var(--muted)}
    .section code{padding:.1em .35em;border-radius:4px;background:#eef3f7;font-family:Consolas,monospace}
    .section strong{color:#263b49}.source-content{overflow-wrap:anywhere}
    .summary-card>p:last-child{margin-bottom:0}
    """

    doc = BeautifulSoup("", "html.parser")
    page = doc.new_tag("div", attrs={"class": "page source-content"})
    mobile_toc = doc.new_tag("details", attrs={"class": "mobile-toc"})
    mobile_summary = doc.new_tag("summary")
    mobile_summary.string = "展开目录"
    mobile_nav = doc.new_tag("nav", attrs={"class": "toc", "aria-label": "移动端章节目录"})
    mobile_toc.extend([mobile_summary, mobile_nav])
    page.append(mobile_toc)

    current: Tag | None = None
    section_number = 0
    for node in list(source_soup.contents):
        if isinstance(node, NavigableString) and not node.strip():
            continue
        if isinstance(node, Tag) and node.name == "h2":
            heading_id = str(node.get("id", ""))
            current = doc.new_tag(
                "section", attrs={"class": "section", "aria-labelledby": heading_id}
            )
            heading = doc.new_tag("div", attrs={"class": "section-head"})
            number = doc.new_tag("div", attrs={"class": "section-no"})
            number.string = f"{section_number:02d}"
            section_number += 1
            heading.extend([number, node])
            current.append(heading)
            page.append(current)
        elif current is not None:
            current.append(node)

    summary_section = page.find("section")
    if summary_section is None:
        raise ValueError("无法建立核心摘要区块")
    summary_paragraphs = summary_section.find_all("p", recursive=False)
    if summary_paragraphs:
        summary_grid = doc.new_tag("div", attrs={"class": "summary-grid"})
        for paragraph in summary_paragraphs:
            card = doc.new_tag("article", attrs={"class": "summary-card"})
            paragraph.extract()
            card.append(paragraph)
            summary_grid.append(card)
        summary_section.find("div", class_="section-head").insert_after(summary_grid)

    for table in list(page.find_all("table")):
        wrapper = doc.new_tag("div", attrs={"class": "table-wrap"})
        table.wrap(wrapper)

    summary_text = summary_section.get_text(" ", strip=True)
    summary_text = re.sub(r"^00\s*核心摘要\s*", "", summary_text)
    subtitle_match = re.match(r"(.+?[。！？])", summary_text)
    subtitle = subtitle_match.group(1) if subtitle_match else summary_text[:120]

    parity_soup = BeautifulSoup(str(page), "html.parser")
    for number in parity_soup.select(".section-no"):
        number.decompose()
    for navigation in parity_soup.select(".mobile-toc"):
        navigation.decompose()
    delivered_text = text_key(parity_soup.get_text(" ", strip=True))
    if delivered_text != baseline_text:
        raise ValueError(
            "版式转换前后正文不一致："
            f"Markdown={len(baseline_text)}，HTML={len(delivered_text)}"
        )

    output_html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{html.escape(title)}｜HTML 阅读版</title>
  <style>{style}</style>
</head>
<body>
  <a class="skip" href="#report">跳到正文</a>
  <aside class="rail" aria-label="报告目录">
    <div class="brand"><small>RESEARCH REPORT</small><strong>{html.escape(args.report_type)}</strong></div>
    <nav class="toc" aria-label="章节目录"></nav>
    <div class="rail-actions"><button type="button" onclick="window.print()">打印 / 导出 PDF</button></div>
  </aside>
  <main id="report">
    <header class="cover">
      <div class="eyebrow">{html.escape(args.report_type)} · HTML 阅读版</div>
      <h1>{html.escape(title)}</h1>
      <p class="dek">{html.escape(subtitle)}</p>
      <div class="meta"><span>研究范围：{html.escape(args.scope)}</span><span>数据截止：{html.escape(args.data_cutoff)}</span><span>版本：{html.escape(args.version)}</span></div>
    </header>
    {page}
    <footer class="footer">{html.escape(args.report_type)} · HTML 阅读版 · 数据截止 {html.escape(args.data_cutoff)}</footer>
  </main>
  <script>{script}</script>
</body>
</html>
"""

    final_soup = BeautifulSoup(output_html, "html.parser")
    anchor_ids, internal_links = validate_links(final_soup)
    if len(final_soup.find_all("h1")) != 1:
        raise ValueError("生成后的 HTML 必须且只能有一个一级标题")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(output_html, encoding="utf-8", newline="\n")
    return {
        "input": str(source),
        "output": str(output),
        "source_characters": len(source_text),
        "h2": source_h2_count,
        "h3": source_h3_count,
        "tables": source_table_count,
        "summary_cards": len(summary_paragraphs),
        "anchor_ids": anchor_ids,
        "internal_links_in_static_html": internal_links,
        "content_match": True,
    }


def main() -> int:
    try:
        result = build(parse_args())
    except (FileNotFoundError, FileExistsError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
