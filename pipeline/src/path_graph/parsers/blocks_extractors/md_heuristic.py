from __future__ import annotations

import re

from path_graph.parsers.blocks_contract import normalize_blocks_document

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
_BOLD_HEADING_RE = re.compile(r"^\*\*(.+)\*\*\s*$")
_SETEXT_H1_RE = re.compile(r"^=+\s*$")
_SETEXT_H2_RE = re.compile(r"^-+\s*$")


def _is_table_separator_row(line: str) -> bool:
    s = line.strip()
    if not s.startswith("|"):
        return False
    cells = [c.strip() for c in s.strip("|").split("|")]
    if not cells:
        return False
    return all(cell and set(cell) <= {"-", ":"} for cell in cells)


def _is_table_row(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if s.startswith("|"):
        return True
    if "|" in s and _is_table_separator_row(f"|{s}|" if not s.startswith("|") else s):
        return True
    return False


def _looks_like_table(lines: list[str]) -> bool:
    if len(lines) < 2:
        return False
    if any(_is_table_separator_row(row) for row in lines):
        return True
    return len(lines) >= 2 and all(row.strip().startswith("|") for row in lines)


class MdHeuristicBlocksExtractor:
    name = "md_heuristic"

    def extract(self, markdown: str) -> dict:
        blocks: list[dict] = []
        heading_stack: list[tuple[int, str]] = []
        lines = markdown.splitlines()
        i = 0

        def heading_path() -> list[str]:
            return [text for _, text in heading_stack]

        def push_heading(level: int, text: str) -> None:
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, text))
            blocks.append(
                {
                    "type": "heading",
                    "level": level,
                    "text": text,
                    "heading_path": heading_path(),
                }
            )

        while i < len(lines):
            line = lines[i]

            heading_match = _HEADING_RE.match(line)
            if heading_match:
                level = len(heading_match.group(1))
                text = heading_match.group(2).strip()
                push_heading(level, text)
                i += 1
                continue

            if i + 1 < len(lines) and line.strip() and not line.strip().startswith("|"):
                nxt = lines[i + 1].strip()
                if _SETEXT_H1_RE.match(nxt):
                    push_heading(1, line.strip())
                    i += 2
                    continue
                if _SETEXT_H2_RE.match(nxt):
                    push_heading(2, line.strip())
                    i += 2
                    continue

            bold_match = _BOLD_HEADING_RE.match(line.strip())
            if bold_match and bold_match.group(1).strip():
                push_heading(2, bold_match.group(1).strip())
                i += 1
                continue

            if _is_table_row(line):
                table_lines: list[str] = []
                while i < len(lines) and _is_table_row(lines[i]):
                    table_lines.append(lines[i])
                    i += 1
                if _looks_like_table(table_lines):
                    blocks.append(
                        {
                            "type": "table",
                            "markdown": "\n".join(table_lines),
                            "heading_path": heading_path(),
                        }
                    )
                else:
                    for row in table_lines:
                        blocks.append(
                            {
                                "type": "paragraph",
                                "text": row.strip(),
                                "heading_path": heading_path(),
                            }
                        )
                continue

            if line.strip():
                para_parts: list[str] = []
                blank_run = 0
                while i < len(lines):
                    cur = lines[i]
                    if not cur.strip():
                        blank_run += 1
                        if blank_run >= 2:
                            i += 1
                            break
                        i += 1
                        continue
                    if blank_run == 1 and para_parts:
                        para_parts.append("")
                    blank_run = 0
                    if _HEADING_RE.match(cur):
                        break
                    if i + 1 < len(lines) and cur.strip() and not cur.strip().startswith("|"):
                        nxt = lines[i + 1].strip()
                        if _SETEXT_H1_RE.match(nxt) or _SETEXT_H2_RE.match(nxt):
                            break
                    if _BOLD_HEADING_RE.match(cur.strip()):
                        break
                    if _is_table_row(cur):
                        break
                    para_parts.append(cur.rstrip())
                    i += 1
                text = "\n".join(para_parts).strip()
                if text:
                    blocks.append(
                        {
                            "type": "paragraph",
                            "text": text,
                            "heading_path": heading_path(),
                        }
                    )
                continue

            i += 1

        return normalize_blocks_document({"blocks": blocks}, extractor=self.name)
