#!/usr/bin/env python3
"""Validate the public Hehe industry research Skill pack using stdlib only."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote


TEXT_SUFFIXES = {
    ".md", ".json", ".py", ".ps1", ".txt", ".html", ".css", ".js",
    ".mmd", ".svg", ".yml", ".yaml", ".toml",
}
FORBIDDEN_PATH_PARTS = {"_本地维护", "90_历史备份", "__pycache__"}
PRIVATE_PATTERNS = {
    "local Windows user path": re.compile(r"[A-Za-z]:\\Users\\", re.I),
    "local Git workspace path": re.compile(r"D:\\LenovoSoftstore\\", re.I),
    "private tanzi-pro capability": re.compile(r"(?<![A-Za-z0-9-])tanzi-pro(?![A-Za-z0-9-])", re.I),
    "private AgentKey capability": re.compile(r"(?<![A-Za-z0-9-])agentkey(?![A-Za-z0-9-])", re.I),
}
LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
NAME_RE = re.compile(r"(?m)^name:\s*([^\s]+)\s*$")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def check_markdown_links(skill_dir: Path, errors: list[str]) -> None:
    root = skill_dir.resolve()
    for md in skill_dir.rglob("*.md"):
        text = read_text(md)
        for raw in LINK_RE.findall(text):
            target = raw.strip().strip("<>").split(maxsplit=1)[0]
            if not target or target.startswith("#"):
                continue
            if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
                continue
            target = unquote(target.split("#", 1)[0])
            if not target:
                continue
            resolved = (md.parent / target).resolve()
            try:
                resolved.relative_to(root)
            except ValueError:
                errors.append(f"cross-package link: {md.relative_to(skill_dir)} -> {raw}")
                continue
            if not resolved.exists():
                errors.append(f"broken link: {md.relative_to(skill_dir)} -> {raw}")


def main() -> int:
    repo = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
    manifest_path = repo / "release-manifest.json"
    errors: list[str] = []

    for required in (repo / "README.md", repo / "LICENSE", manifest_path, repo / "skills"):
        if not required.exists():
            errors.append(f"missing required path: {required.relative_to(repo)}")
    if errors:
        print("\n".join(f"ERROR: {item}" for item in errors))
        return 1

    manifest = json.loads(read_text(manifest_path))
    skills = manifest.get("skills", [])
    names = [item.get("name") for item in skills]
    if manifest.get("display_name") != "盒盒行业研究技能包":
        errors.append("release display_name is not 盒盒行业研究技能包")
    if len(names) != 14 or len(set(names)) != 14:
        errors.append(f"release manifest must contain 14 unique skills, found {len(names)}")
    if any(not isinstance(name, str) or not name.startswith("hehe-") for name in names):
        errors.append("every released skill name must start with hehe-")

    skills_root = repo / "skills"
    actual_dirs = sorted(p.name for p in skills_root.iterdir() if p.is_dir())
    if sorted(names) != actual_dirs:
        errors.append(f"skills directory mismatch: expected {sorted(names)}, found {actual_dirs}")

    for name in names:
        skill_dir = skills_root / name
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.is_file():
            errors.append(f"missing SKILL.md: skills/{name}")
            continue
        match = NAME_RE.search(read_text(skill_file))
        actual_name = match.group(1) if match else None
        if actual_name != name:
            errors.append(f"frontmatter name mismatch: {name} -> {actual_name}")
        check_markdown_links(skill_dir, errors)

    for path in repo.rglob("*"):
        rel = path.relative_to(repo)
        if any(part in FORBIDDEN_PATH_PARTS for part in rel.parts):
            errors.append(f"forbidden path: {rel}")
        if path.is_file() and (path.suffix.lower() == ".pyc" or "_CO" in path.name):
            errors.append(f"forbidden generated file: {rel}")
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES and path.resolve() != Path(__file__).resolve():
            text = read_text(path)
            for label, pattern in PRIVATE_PATTERNS.items():
                if pattern.search(text):
                    errors.append(f"{label}: {rel}")

    entry = manifest.get("entry_skill")
    if entry != "hehe-industry-researcher":
        errors.append(f"unexpected entry_skill: {entry}")
    router_manifest_path = skills_root / entry / "package-manifest.json"
    if not router_manifest_path.is_file():
        errors.append("missing router package-manifest.json")
    else:
        router_manifest = json.loads(read_text(router_manifest_path))
        required = router_manifest.get("required_specialty_skills", [])
        required_names = [item.get("name") for item in required]
        expected_specialty = [name for name in names if name != entry]
        if router_manifest.get("install_policy") != "full-bundle":
            errors.append("router install_policy must be full-bundle")
        if router_manifest.get("entry_skill") != entry:
            errors.append("router entry_skill does not use public name")
        if sorted(required_names) != sorted(expected_specialty):
            errors.append("router required_specialty_skills does not match the 13 public specialty skills")

    for name in names:
        if name == entry:
            continue
        templates = list((skills_root / name).rglob("*交付模板.md"))
        if len(templates) != 1:
            errors.append(f"{name} must contain exactly one delivery template, found {len(templates)}")
            continue
        text = read_text(templates[0])
        headings = ["## 一、交付载体", "## 二、Markdown 主报告", "## 三、其他交付物", "## 四、保存与命名", "## 五、信息缺口", "## 六、交付条件与交付前检查"]
        positions = [text.find(heading) for heading in headings]
        if -1 in positions or positions != sorted(positions):
            errors.append(f"delivery template section order invalid: {name}")
        summary = text.find("核心摘要")
        scope = text.find("研究范围", summary + 1) if summary >= 0 else -1
        if summary < 0 or scope < 0 or summary >= scope:
            errors.append(f"delivery template is not summary-first: {name}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"Validation failed with {len(errors)} issue(s).")
        return 1

    print(f"Validated {len(names)} public Skills for {manifest['display_name']}.")
    print("Names, bundle contract, links, delivery templates, and public-package hygiene passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
