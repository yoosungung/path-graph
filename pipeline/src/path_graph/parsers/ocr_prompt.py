from __future__ import annotations

DEFAULT_OCR_PROMPT = """\
이 이미지는 문서 페이지입니다. 보이는 텍스트를 Markdown으로만 출력하세요.

규칙:
- 한국어·영문 혼용을 그대로 유지합니다.
- 표는 Markdown table로 구조를 유지합니다.
- 머리글·각주·본문을 구분합니다.
- 보이지 않는 내용을 추측하거나 보완하지 않습니다.
- 설명·코멘트 없이 Markdown 본문만 출력합니다.
"""
