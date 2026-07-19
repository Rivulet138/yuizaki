"""Local desktop automation tools.

Initial minimal set for MCP-style tool calling:

- open_app(name)
- open_url(url)
- read_file(path)
- write_file(path, content)

These are intentionally conservative and avoid arbitrary shell execution.
"""

from __future__ import annotations

import os
import json
import re
import subprocess
import sys
import webbrowser
from html import unescape
from pathlib import Path
from typing import Any, Dict
from urllib.parse import quote_plus, unquote
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LOCAL_TOOL_ROOTS_ENV = "YUIZAKI_LOCAL_TOOL_ROOTS"


class LocalToolError(Exception):
    """Custom error type for local tool failures."""


def _is_path_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _allowed_file_roots() -> list[Path]:
    raw_roots = os.getenv(LOCAL_TOOL_ROOTS_ENV, "")
    roots: list[Path] = [] if raw_roots.strip() else [PROJECT_ROOT]
    for raw_root in raw_roots.split(os.pathsep):
        value = raw_root.strip()
        if not value:
            continue
        roots.append(Path(value).expanduser())

    resolved_roots: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        try:
            resolved = root.resolve()
        except OSError:
            continue
        key = os.path.normcase(str(resolved))
        if key not in seen:
            seen.add(key)
            resolved_roots.append(resolved)
    return resolved_roots


def _resolve_local_file_path(path: str) -> Path:
    raw_path = (path or "").strip()
    if not raw_path:
        raise LocalToolError("File path is required")

    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    try:
        resolved = candidate.resolve()
    except OSError as exc:
        raise LocalToolError(str(exc)) from exc

    roots = _allowed_file_roots()
    if not any(_is_path_inside(resolved, root) for root in roots):
        root_text = ", ".join(str(root) for root in roots)
        raise LocalToolError(
            f"File path is outside allowed local tool roots. Configure {LOCAL_TOOL_ROOTS_ENV} to set roots. "
            f"Allowed roots: {root_text}"
        )
    return resolved


def open_app(name: str) -> str:
    """Open a desktop application by name.

    NOTE: Implementation is OS-specific and intentionally minimal.
    """

    if os.name == "nt":  # Windows
        try:
            # Use 'start' via cmd to let Windows resolve the app
            subprocess.Popen(["cmd", "/c", "start", "", name], shell=False)
            return f"Launched application: {name}"
        except OSError as exc:
            raise LocalToolError(str(exc))
    else:
        # On non-Windows platforms, fall back to 'open' / 'xdg-open'
        try:
            if sys.platform == "darwin":  # type: ignore[name-defined]
                subprocess.Popen(["open", "-a", name])
            else:
                subprocess.Popen(["xdg-open", name])
            return f"Launched application: {name}"
        except OSError as exc:  # pragma: no cover - platform dependent
            raise LocalToolError(str(exc))


def open_url(url: str) -> str:
    """Open a URL in the default browser."""

    try:
        webbrowser.open(url)
        return f"Opened URL: {url}"
    except Exception as exc:  # pragma: no cover - system dependent
        raise LocalToolError(str(exc))


def _strip_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_duckduckgo_results(html: str, limit: int) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    pattern = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?'
        r'<a[^>]+class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(html):
        href = unescape(match.group("href"))
        redirect_match = re.search(r"[?&]uddg=([^&]+)", href)
        url = unquote(redirect_match.group(1)) if redirect_match else href
        title = _strip_html(match.group("title"))
        snippet = _strip_html(match.group("snippet"))
        if title and url:
            results.append({"title": title, "url": url, "snippet": snippet})
        if len(results) >= limit:
            break
    return results


def web_search(query: str, limit: int = 5) -> str:
    """Search public web results without requiring an API key."""

    clean_query = query.strip()
    if not clean_query:
        raise LocalToolError("Search query is required")

    safe_limit = max(1, min(int(limit or 5), 8))
    url = f"https://duckduckgo.com/html/?q={quote_plus(clean_query)}"
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 YuizakiLocalAgent/1.0",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    try:
        with urlopen(request, timeout=8) as response:
            html = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        raise LocalToolError(f"Web search failed: {exc}") from exc

    results = _extract_duckduckgo_results(html, safe_limit)
    return json.dumps(
        {
            "query": clean_query,
            "results": results,
            "source": "duckduckgo_html",
        },
        ensure_ascii=False,
    )


def read_file(path: str) -> str:
    """Read a text file from disk.

    The path is resolved relative to the current working directory.
    """

    p = _resolve_local_file_path(path)
    if not p.exists() or not p.is_file():
        raise LocalToolError(f"File not found: {p}")
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise LocalToolError(str(exc))


def write_file(path: str, content: str) -> str:
    """Write text content to a file.

    Creates parent directories if needed.
    """

    p = _resolve_local_file_path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} characters to {p}"
    except OSError as exc:
        raise LocalToolError(str(exc))


def dispatch_tool(name: str, args: Dict[str, Any]) -> str:
    """Dispatch a tool call by name.

    Returns a string output or raises LocalToolError.
    """

    if name == "open_app":
        return open_app(str(args.get("name", "")))
    if name == "open_url":
        return open_url(str(args.get("url", "")))
    if name == "read_file":
        return read_file(str(args.get("path", "")))
    if name == "write_file":
        return write_file(str(args.get("path", "")), str(args.get("content", "")))
    if name == "web_search":
        return web_search(str(args.get("query", "")), int(args.get("limit", 5) or 5))

    raise LocalToolError(f"Unknown tool: {name}")
