from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml

ROOT = Path(__file__).resolve().parents[1]


def main():
    sources = [p for name in ("src", "src_lbbd", "src_benders", "scripts", "tests")
               for p in (ROOT / name).rglob("*.py")]
    for path in sources:
        ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    configs = list((ROOT / "config").glob("*.json")) + [ROOT / "SOURCE_PROVENANCE.json"]
    configs.extend((ROOT / ".vscode").glob("*.json"))
    for path in configs:
        json.loads(path.read_text(encoding="utf-8"))
    documents = list(ROOT.glob("*.md"))
    for name in ("assets", "config", "src_benders"):
        documents.extend((ROOT / name).glob("*.md"))
    failures = []
    for path in documents:
        text = path.read_text(encoding="utf-8")
        references = re.findall(r'\[[^\]]*\]\(([^)]+)\)|<img\b[^>]*\bsrc="([^"]+)"', text)
        for markdown, html in references:
            target = (markdown or html).strip().split(' "', 1)[0]
            parsed = urlsplit(target)
            if not target or target.startswith("#") or parsed.scheme or parsed.netloc:
                continue
            destination = path.parent / unquote(parsed.path)
            if not destination.exists():
                failures.append(f"{path.relative_to(ROOT)}: missing link target {target}")
    repository = ROOT.parents[3]
    workflows = repository / ".github" / "workflows"
    for path in workflows.glob("*.y*ml"):
        document = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        if not isinstance(document, dict) or not {"on", "jobs"} <= document.keys():
            failures.append(f"Invalid workflow structure: {path.name}")
    if failures:
        raise SystemExit("\n".join(failures))
    print(f"Checked {len(sources)} Python sources, {len(configs)} JSON files, and {len(documents)} Markdown files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
