"""Forensic + guardrail inventory for the renderer i18n layer.

Parses the locale tables out of the TypeScript sources textually (no bundler, no
network) so it can run in CI and in restricted sandboxes:

  * key parity across zh-CN / en-US / ja-JP, merged exactly like index.ts does
    (`messages` -> second ja block -> jaOverrides)
  * values that are still Chinese in en-US / ja-JP
  * hardcoded CJK in renderer components (the parts that never reach `t()`)

Usage:
  python scripts/i18n_inventory.py                 # summary
  python scripts/i18n_inventory.py --json PATH     # machine-readable report
  python scripts/i18n_inventory.py --max-cjk N     # fail if hardcoded CJK lines > N
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "electron" / "src"
# `shared/` is imported by both the renderer and the main process; its text is
# scanned too so a label cannot hide there (the main process has no i18n layer, so
# the few strings it needs on purpose are reported rather than silently ignored).
SCAN_ROOTS = (SRC / "renderer", SRC / "shared")
I18N = SRC / "renderer" / "i18n"

CJK = re.compile("[\u3400-\u4dbf\u4e00-\u9fff]")
# Characters that are simplified-only: no Japanese shinjitai form uses them.
# A ja-JP string containing one of these is Chinese left behind, not Japanese.
SIMPLIFIED_ONLY = set(
    "这说们个时对门问题让还关闭删设证据页显视图标记录载网络误连确认启动储忆语乐频档"
    "继续暂统项务处从后边为员变单选应该读级别类层组织间开无夹缓调试运弹输态权块"
    "库备归换删编"
)
# Modules pack several `'key': 'value',` pairs onto one line, so pairs are matched
# inside a line instead of assuming one entry per line.
KV_ANY = re.compile(r"'([^']+)'\s*:\s*'((?:[^'\\]|\\.)*)'")
LOCALE_HEADER = re.compile(r"^'?(zh-CN|en-US|ja-JP)'?\s*:\s*\{\s*$")
KEY_TEMPLATE_START = re.compile(r"'([^']+)'\s*:\s*`(.*)$")
FLAT_HEADER = re.compile(r"^export const \w+\s*=\s*\{\s*$")


def _collect_block(lines, start_index):
    """Yield key/value pairs from the object literal starting at start_index.

    Values may be multi-line template literals (the built-in prompts), so a
    backtick that opens without closing on the same line consumes the following
    lines until the closing backtick.
    """
    depth = 0
    started = False
    pending_key = None
    pending_lines: list[str] = []
    for line in lines[start_index:]:
        if pending_key is not None:
            pending_lines.append(line)
            joined = "\n".join(pending_lines)
            if "`" in joined:
                yield pending_key, joined.split("`", 1)[0]
                pending_key = None
                pending_lines = []
            continue
        if not started:
            depth = line.count("{") - line.count("}")
            started = True
            continue
        depth += line.count("{") - line.count("}")
        if depth <= 0:
            return
        if depth != 1:
            continue
        template = KEY_TEMPLATE_START.search(line)
        if template and "`" not in template.group(2):
            pending_key = template.group(1)
            pending_lines = [template.group(2)]
            continue
        for match in KV_ANY.finditer(line):
            yield match.group(1), match.group(2)


def parse_message_modules():
    """{module: {locale: {key: value}}} for every i18n module file."""
    out = {}
    for path in sorted(I18N.glob("*.ts")):
        if path.name.endswith(".test.ts") or path.name in {"index.ts", "definePanelMessages.ts"}:
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        tables = {}
        for index, line in enumerate(lines):
            header = LOCALE_HEADER.match(line.strip())
            if header:
                tables.setdefault(header.group(1), {}).update(dict(_collect_block(lines, index)))
        if tables:
            out[path.stem] = tables
    return out


def parse_index_tables():
    """zh-CN / en-US / ja-JP as merged by index.ts (later blocks win)."""
    lines = (I18N / "index.ts").read_text(encoding="utf-8").splitlines()
    tables = {}
    for index, line in enumerate(lines):
        header = LOCALE_HEADER.match(line.strip())
        if header:
            tables.setdefault(header.group(1), {}).update(dict(_collect_block(lines, index)))
    return tables


def parse_flat(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if FLAT_HEADER.match(line.strip()):
            return dict(_collect_block(lines, index))
    return {}


def resolved_tables():
    index = parse_index_tables()
    modules = parse_message_modules()
    tables = {"zh-CN": {}, "en-US": {}, "ja-JP": {}}
    for locale in tables:
        for module in modules.values():
            tables[locale].update(module.get(locale, {}))
        tables[locale].update(index.get(locale, {}))
    tables["ja-JP"].update(parse_flat(I18N / "jaOverrides.ts"))
    # index.ts resolves modules first, then its own literal, then jaOverrides;
    # mirrors `messages` spread order closely enough for an inventory.
    return tables


PLACEHOLDER = re.compile(r"\{([A-Za-z0-9_]+)\}")


def scan_hardcoded():
    rows = []
    for root in SCAN_ROOTS:
        for path in sorted(list(root.rglob("*.vue")) + list(root.rglob("*.ts"))):
            rel = path.relative_to(SRC).as_posix()
            if rel.startswith("renderer/i18n/"):
                continue
            if rel.endswith((".test.ts", ".spec.ts")):
                # Tests legitimately assert Chinese fixtures; they never reach a user.
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            hits = []
            for number, line in enumerate(lines, 1):
                if not CJK.search(line):
                    continue
                stripped = line.strip()
                if stripped.startswith(("//", "*", "/*", "<!--")):
                    continue
                hits.append(number)
            if hits:
                rows.append({"file": rel, "cjk_lines": len(hits), "total_lines": len(lines)})
    rows.sort(key=lambda row: -row["cjk_lines"])
    return rows


def build_report():
    tables = resolved_tables()
    zh, en, ja = tables["zh-CN"], tables["en-US"], tables["ja-JP"]
    missing_en = sorted(set(zh) - set(en))
    missing_ja = sorted(set(zh) - set(ja))
    orphan_en = sorted(set(en) - set(zh))
    orphan_ja = sorted(set(ja) - set(zh))
    placeholder_mismatch = []
    empty_values = []
    for key in sorted(set(zh) & set(en) & set(ja)):
        expected = sorted(PLACEHOLDER.findall(zh[key]))
        for locale, table in (("en-US", en), ("ja-JP", ja)):
            if sorted(PLACEHOLDER.findall(table[key])) != expected:
                placeholder_mismatch.append(f"{locale}:{key}")
        for locale, table in (("zh-CN", zh), ("en-US", en), ("ja-JP", ja)):
            if not table[key].strip():
                empty_values.append(f"{locale}:{key}")
    cjk_in_en = sorted(key for key, value in en.items() if CJK.search(value))
    chinese_in_ja = sorted(
        key for key, value in ja.items() if any(char in SIMPLIFIED_ONLY for char in value)
    )
    return {
        "sizes": {"zh-CN": len(zh), "en-US": len(en), "ja-JP": len(ja)},
        "missing_en": missing_en,
        "missing_ja": missing_ja,
        "orphan_en": orphan_en,
        "orphan_ja": orphan_ja,
        "placeholder_mismatch": placeholder_mismatch,
        "empty_values": empty_values,
        "cjk_in_en": cjk_in_en,
        "chinese_in_ja": chinese_in_ja,
        "hardcoded": scan_hardcoded(),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json")
    parser.add_argument("--max-cjk", type=int, default=None)
    args = parser.parse_args(argv)

    report = build_report()
    hardcoded = report["hardcoded"]
    print(f"locale keys: {report['sizes']}")
    print(f"missing en-US: {len(report['missing_en'])}  missing ja-JP: {len(report['missing_ja'])}")
    print(f"placeholder mismatches: {len(report['placeholder_mismatch'])}"
          f"  empty values: {len(report['empty_values'])}")
    print(f"CJK left in en-US: {len(report['cjk_in_en'])}"
          f"  Chinese left in ja-JP: {len(report['chinese_in_ja'])}")
    print(f"\nhardcoded CJK: {len(hardcoded)} files, "
          f"{sum(row['cjk_lines'] for row in hardcoded)} lines")
    for row in hardcoded[:15]:
        print(f"  {row['cjk_lines']:5d}  {row['file']}")
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nwrote {args.json}")
    if args.max_cjk is not None:
        total = sum(row["cjk_lines"] for row in hardcoded)
        if total > args.max_cjk:
            print(f"\nFAIL: {total} hardcoded CJK lines exceeds budget {args.max_cjk}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
