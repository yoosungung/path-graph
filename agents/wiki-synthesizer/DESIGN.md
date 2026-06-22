# wiki-synthesizer — 내부 설계

MS GraphRAG community report 프롬프트 사상으로 project·community 단위 위키를 합성한다.

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
```
