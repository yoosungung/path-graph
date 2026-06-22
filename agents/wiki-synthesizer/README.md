# wiki-synthesizer agent bundle

## 등록

graph-extractor와 동일 절차. agent 이름: `wiki-synthesizer`.

## 입출력

- input: `{tenant, project, community_id, community_level, graph_context_s3, schema, idempotency_key}`
- output: `{pages: [{slug, title, markdown}]}`
