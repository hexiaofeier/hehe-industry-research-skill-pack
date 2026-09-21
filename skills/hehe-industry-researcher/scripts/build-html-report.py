#!/usr/bin/env python3
"""把定稿 Markdown 主报告转换为同内容、可离线阅读的 HTML 阅读版。"""

from __future__ import annotations

import argparse
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


def layout_summary(section: Tag, doc: BeautifulSoup) -> int:
    """只把并列结论排成卡片，保留引言、收尾及普通段落的原位通栏。"""
    count = 0
    grid: Tag | None = None
    for child in list(section.children):
        if isinstance(child, NavigableString) and not child.strip():
            continue
        if not isinstance(child, Tag):
            grid = None
            continue
        if child.name in {"ol", "ul"}:
            items = child.find_all("li", recursive=False)
            if items:
                child["class"] = [*child.get("class", []), "summary-grid"]
                ordinal = int(child.get("start", 1))
                for item in items:
                    ordinal = int(item.get("value", ordinal))
                    item["class"] = [*item.get("class", []), "summary-card"]
                    lead = next((x for x in item.contents if str(x).strip()), None)
                    if isinstance(lead, Tag) and lead.name == "p":
                        lead = next((x for x in lead.contents if str(x).strip()), None)
                    if isinstance(lead, Tag) and lead.name in {"strong", "b"}:
                        lead["class"] = [*lead.get("class", []), "summary-title"]
                    if child.name == "ol":
                        number = doc.new_tag("span", attrs={"class": "summary-number", "aria-hidden": "true"})
                        number.string = f"{ordinal}. "
                        if isinstance(lead, Tag) and "summary-title" in lead.get("class", []):
                            lead.insert(0, number)
                        else:
                            item.insert(0, number)
                    ordinal += 1
                    count += 1
            grid = None
            continue
        lead = next((x for x in child.contents if str(x).strip()), None)
        # 段落式摘要须有明确的编号结论，不能把整段加粗的引言误认成卡片。
        numbered = (
            child.name == "p" and isinstance(lead, Tag) and lead.name in {"strong", "b"}
            and re.match(r"^(?:\d+[.、．）)]|[一二三四五六七八九十]+[、.．）)])", lead.get_text(strip=True))
        )
        if numbered:
            if grid is None:
                grid = doc.new_tag("div", attrs={"class": "summary-grid"})
                child.insert_before(grid)
            child["class"] = [*child.get("class", []), "summary-card"]
            lead["class"] = [*lead.get("class", []), "summary-title"]
            grid.append(child.extract())
            count += 1
        else:
            grid = None
    return count


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

    doc = BeautifulSoup(template_path.read_text(encoding="utf-8-sig"), "html.parser")
    page = doc.select_one(".page")
    if page is None:
        raise ValueError("HTML 模板缺少 .page 正文容器")
    page.clear()
    page["class"] = ["page", "source-content"]

    current: Tag | None = None
    for node in list(source_soup.contents):
        if isinstance(node, NavigableString) and not node.strip():
            continue
        if isinstance(node, Tag) and node.name == "h2":
            heading_id = str(node.get("id", ""))
            current = doc.new_tag(
                "section", attrs={"class": "section", "aria-labelledby": heading_id}
            )
            current.append(node)
            page.append(current)
        elif current is not None:
            current.append(node)
        else:
            page.append(node)

    summary_section = page.find("section")
    if summary_section is None:
        raise ValueError("无法建立核心摘要区块")
    summary_lead = summary_section.find(["p", "li"])
    summary_text = summary_lead.get_text(" ", strip=True) if summary_lead else title
    summary_card_count = layout_summary(summary_section, doc)

    for table in list(page.find_all("table")):
        wrapper = doc.new_tag("div", attrs={"class": "table-wrap"})
        table.wrap(wrapper)

    for image in list(page.find_all("img")):
        if image.find_parent("figure") is None:
            wrapper = doc.new_tag("span", attrs={"class": "image-scroll"})
            image.wrap(wrapper)
    subtitle_match = re.match(r"(.+?[。！？])", summary_text)
    subtitle = subtitle_match.group(1) if subtitle_match else summary_text[:120]

    parity_soup = BeautifulSoup(str(page), "html.parser")
    for number in parity_soup.select(".summary-number"):
        number.decompose()
    delivered_text = text_key(parity_soup.get_text(" ", strip=True))
    if delivered_text != baseline_text:
        raise ValueError(
            "版式转换前后正文不一致："
            f"Markdown={len(baseline_text)}，HTML={len(delivered_text)}"
        )

    values = {"title": title, "report-type": args.report_type, "scope": args.scope,
              "data-cutoff": args.data_cutoff, "version": args.version, "subtitle": subtitle}
    for field, value in values.items():
        targets = doc.select(f'[data-field="{field}"]')
        if not targets:
            raise ValueError(f"HTML 模板缺少 data-field={field}")
        for target in targets:
            target.string = value
            del target["data-field"]
    doc.title.string = title + "｜HTML 阅读版"
    for nav in doc.select("nav.toc"):
        nav.clear()
        for heading in page.find_all("h2"):
            link = doc.new_tag("a", href="#" + str(heading["id"]))
            link.string = heading.get_text(" ", strip=True)
            nav.append(link)
    output_html = str(doc)

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
        "summary_cards": summary_card_count,
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
