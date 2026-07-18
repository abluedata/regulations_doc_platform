"""Table grid utilities for high-fidelity dual-form (HTML + Markdown) tables.

All conversions are driven from a single 2D grid of plain cell strings.
No third-party parsers. Uses stdlib html.parser + html.unescape only.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from typing import List

__all__ = [
    "looks_like_html_table",
    "looks_like_markdown_table",
    "html_to_grid",
    "markdown_to_grid",
    "grid_to_html",
    "grid_to_markdown",
    "normalize_table_fields",
]


def looks_like_html_table(s: str) -> bool:
    """Heuristic: contains a table tag."""
    if not s or not isinstance(s, str):
        return False
    return bool(re.search(r"<\s*/?\s*table\b", s, flags=re.I))


def looks_like_markdown_table(s: str) -> bool:
    """Heuristic: >=3 lines, first two look like | ... | header + separator."""
    if not s or not isinstance(s, str):
        return False
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    if len(lines) < 3:
        return False
    # First line must look like a markdown table row
    if not (lines[0].startswith("|") and lines[0].endswith("|")):
        return False
    # Second line must be a separator (--- or :--- etc)
    sep = lines[1]
    if not (sep.startswith("|") and sep.endswith("|")):
        return False
    # Count dashes groups between pipes
    cells = [c.strip() for c in sep.split("|")[1:-1]]
    if not cells:
        return False
    return all(re.fullmatch(r":?-{3,}:?", c) or re.fullmatch(r"-{3,}", c) for c in cells)


class _TableHTMLParser(HTMLParser):
    """Collects table rows/cells as plain text.

    - Strips nested tags (p, span, etc.)
    - Converts <br> to space
    - Uses html.unescape for entities
    - Collapses internal whitespace
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._rows: List[List[str]] = []
        self._cur_row: List[str] = []
        self._cur_cell: List[str] = []
        self._in_cell = False
        self._skip_depth = 0  # inside tags we want to ignore entirely for structure (none yet)

    def handle_starttag(self, tag: str, attrs):
        tag = tag.lower()
        if tag == "tr":
            if self._cur_row:
                # flush previous row if we somehow missed </tr>
                self._flush_row()
            self._cur_row = []
        elif tag in ("td", "th"):
            self._in_cell = True
            self._cur_cell = []
        elif tag == "br" and self._in_cell:
            self._cur_cell.append(" ")

    def handle_endtag(self, tag: str):
        tag = tag.lower()
        if tag in ("td", "th"):
            if self._in_cell:
                text = "".join(self._cur_cell)
                text = html.unescape(text)
                # collapse whitespace
                text = re.sub(r"\s+", " ", text).strip()
                self._cur_row.append(text)
                self._cur_cell = []
            self._in_cell = False
        elif tag == "tr":
            self._flush_row()

    def handle_data(self, data: str):
        if self._in_cell:
            self._cur_cell.append(data)

    def _flush_row(self):
        if self._cur_row:
            self._rows.append(self._cur_row)
        self._cur_row = []

    def get_grid(self) -> List[List[str]]:
        # flush any unclosed row
        if self._cur_row or (self._in_cell and self._cur_cell):
            if self._in_cell and self._cur_cell:
                text = "".join(self._cur_cell)
                text = html.unescape(text)
                text = re.sub(r"\s+", " ", text).strip()
                self._cur_row.append(text)
            if self._cur_row:
                self._rows.append(self._cur_row)
        return self._rows


def html_to_grid(html_str: str) -> List[List[str]]:
    """Parse HTML table to 2D list of plain cell strings.

    Nested tags inside cells are stripped; only text content remains.
    Returns [] on failure / no table.
    """
    if not html_str or not isinstance(html_str, str):
        return []
    if not looks_like_html_table(html_str):
        return []

    parser = _TableHTMLParser()
    try:
        parser.feed(html_str)
        parser.close()
    except Exception:
        return []

    grid = parser.get_grid()
    if not grid or not any(any(cell for cell in row) for row in grid):
        return []
    return grid


def markdown_to_grid(md: str) -> List[List[str]]:
    """Parse GFM-ish markdown table to 2D list of plain cell strings.

    - Skips separator lines (containing mostly ---)
    - Splits cells on unescaped |
    - Strips outer pipes and whitespace
    - Returns [] on failure / insufficient rows
    """
    if not md or not isinstance(md, str):
        return []
    lines = [ln.rstrip() for ln in md.splitlines()]
    # Keep only lines that look like table rows
    table_lines = [ln for ln in lines if ln.strip().startswith("|") and ln.strip().endswith("|")]
    if len(table_lines) < 2:
        return []

    grid: List[List[str]] = []
    for ln in table_lines:
        # strip outer pipes
        inner = ln.strip()[1:-1]
        # split on |
        cells = inner.split("|")
        cells = [c.strip() for c in cells]
        # skip separator row
        if all(re.fullmatch(r":?-{3,}:?", c) or re.fullmatch(r"-{3,}", c) or c == "" for c in cells):
            continue
        grid.append(cells)

    if len(grid) < 2:
        return []
    # normalize column count (pad short rows)
    width = max(len(r) for r in grid)
    norm = [r + [""] * (width - len(r)) for r in grid]
    return norm


def grid_to_html(grid: List[List[str]]) -> str:
    """Render 2D grid to canonical HTML table.

    First row -> <thead><tr><th>...</th></tr></thead>
    Remaining rows -> <tbody><tr><td>...</td></tr></tbody>
    All cells are plain text (escaped).
    """
    if not grid or not any(grid):
        return ""
    # normalize width
    width = max(len(r) for r in grid)
    norm = [r + [""] * (width - len(r)) for r in grid]

    parts: List[str] = ["<table>"]
    # thead
    header = norm[0]
    parts.append("<thead>")
    parts.append("<tr>")
    for cell in header:
        safe = html.escape(str(cell or ""))
        parts.append(f"<th>{safe}</th>")
    parts.append("</tr>")
    parts.append("</thead>")
    # tbody
    if len(norm) > 1:
        parts.append("<tbody>")
        for row in norm[1:]:
            parts.append("<tr>")
            for cell in row:
                safe = html.escape(str(cell or ""))
                parts.append(f"<td>{safe}</td>")
            parts.append("</tr>")
        parts.append("</tbody>")
    parts.append("</table>")
    return "".join(parts)


def grid_to_markdown(grid: List[List[str]]) -> str:
    r"""Render 2D grid to GFM markdown table.

    Header row
    Separator (---)
    Data rows
    | is escaped as \|
    """
    if not grid or not any(grid):
        return ""
    width = max(len(r) for r in grid)
    norm = [r + [""] * (width - len(r)) for r in grid]

    def esc(c: str) -> str:
        return str(c or "").replace("|", "\\|").replace("\n", " ").strip()

    header = norm[0]
    lines: List[str] = []
    lines.append("| " + " | ".join(esc(c) for c in header) + " |")
    lines.append("| " + " | ".join("---" for _ in header) + " |")
    for row in norm[1:]:
        lines.append("| " + " | ".join(esc(c) for c in row) + " |")
    return "\n".join(lines)


def normalize_table_fields(*, html: str | None = None, markdown: str | None = None, text: str | None = None) -> dict:
    """Return canonical {"html", "markdown", "text"} from any one source form.

    Strategy:
    - Prefer html if present and convertible.
    - Else markdown.
    - Else text (treated as markdown).
    - Always produce dual form from the SAME grid.
    - On failure: return empty strings for all three.
    - text always equals markdown (or "")
    """
    grid: List[List[str]] = []

    if html:
        grid = html_to_grid(html)
    if not grid and markdown:
        grid = markdown_to_grid(markdown)
    if not grid and text:
        grid = markdown_to_grid(text)

    if not grid:
        return {"html": "", "markdown": "", "text": ""}

    out_html = grid_to_html(grid)
    out_md = grid_to_markdown(grid)
    return {"html": out_html, "markdown": out_md, "text": out_md}
