# wiki-synthesizer — 내부 설계

MS GraphRAG community report 프롬프트 사상으로 project·community 단위 위키를 합성한다.

## 현재 상태 (스켈레ton)

| 항목 | 상태 |
|------|------|
| invoke payload 계약 | [x] `WikiSynthesizerInput` — ARCHITECTURE §2.5 |
| pipeline 연동 | [x] `wiki_pipeline.py` + `test_wiki.py` (mock) |
| LLM community report 본구현 | [ ] 프롬프트만 존재 |
| agents-runtime 번들 배포 | 수동 zip |

## 입출력

- **input**: `{tenant, project, community_id, community_level, graph_context_s3, output_schema, idempotency_key}`
- **output**: `{pages: [{slug, title, markdown}], tenant, project}`

`graph_context_s3`는 `graph_context/{tenant}/{project}/{batch_id}/{community_id}.json` artifact URI.

## 프롬프트

- `prompts/community_report.txt` — MS GraphRAG community report 템플릿 기반

## Commands

```bash
cd agents/wiki-synthesizer && zip -r bundle.zip src/
# agent 이름: wiki-synthesizer

# pipeline 쪽 검증 (repo root)
make test   # test_wiki.py
```
