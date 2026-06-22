# graph-extractor agent bundle (agents-runtime 등록용)

LangGraph agent skeleton. `factory(cfg, secrets)` 엔트리포인트는 agents-runtime 번들 규약을 따른다.

## 등록 (agents-runtime admin)

1. 이 디렉터리를 zip 번들로 패키징 (`graph_extractor:factory` 엔트리포인트)
2. admin `POST /api/source-meta/bundle` — `runtime_pool=agent:compiled_graph`
3. `config` 예: `{"langgraph": {"model": "provider:openai:gpt-4o-mini"}}`
4. pipeline `invoke_agent("graph-extractor", ...)` 호출

## 입출력

- input: `{tenant, project, batch_id, chunks_s3, schema, idempotency_key}`
- output: `{edges: [{type, source, target, confidence}]}`

구현: `src/graph_extractor/agent.py`
