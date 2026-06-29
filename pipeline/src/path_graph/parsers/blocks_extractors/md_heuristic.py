from __future__ import annotations

import re

from path_graph.parsers.blocks_contract import normalize_blocks_document

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")


class MdHeuristicBlocksExtractor:
    name = "md_heuristic"

    def extract(self, markdown: str) -> dict:
        blocks: list[dict] = []
        heading_stack: list[tuple[int, str]] = []
        lines = markdown.splitlines()
        i = 0

        def heading_path() -> list[str]:
            return [text for _, text in heading_stack]

        while i < len(lines):
            line = lines[i]
            heading_match = _HEADING_RE.match(line)
            if heading_match:
                level = len(heading_match.group(1))
                text = heading_match.group(2).strip()
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
                i += 1
                continue

            if line.strip().startswith("|"):
                table_lines: list[str] = []
                while i < len(lines) and lines[i].strip().startswith("|"):
                    table_lines.append(lines[i])
                    i += 1
                blocks.append(
                    {
                        "type": "table",
                        "markdown": "\n".join(table_lines),
                        "heading_path": heading_path(),
                    }
                )
                continue

            if line.strip():
                para_lines: list[str] = []
                while i < len(lines):
                    cur = lines[i]
                    if not cur.strip():
                        break
                    if cur.strip().startswith("|") or _HEADING_RE.match(cur):
                        break
                    para_lines.append(cur)
                    i += 1
                blocks.append(
                    {
                        "type": "paragraph",
                        "text": "\n".join(para_lines),
                        "heading_path": heading_path(),
                    }
                )
                continue

            i += 1

        return normalize_blocks_document({"blocks": blocks}, extractor=self.name)
