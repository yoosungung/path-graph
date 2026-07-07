# wiki-synthesizer — 내부 설계

MS GraphRAG community report 프롬프트 사상으로 project·community 단위 위키를 합성한다.

## 현재 상태

| 항목 | 상태 |
|------|------|
| invoke payload 계약 | [x] `WikiSynthesizerInput` — `project_id`, `project_slug` |
| pipeline 연동 | [x] `wiki_pipeline.py` + `test_wiki.py` (agent mock) |
| LangGraph 본구현 | [x] `graph.py` — graph_context → LLM JSON → markdown page |
| agents-runtime 번들 배포 | [x] `./scripts/register-agent-bundles.sh` — `agent:compiled_graph` |

## 입출력

- **input**: `{tenant, project_id, project_slug, community_id, community_level, graph_context_s3, output_schema, idempotency_key}`
- **output**: `{pages: [{slug, title, markdown}], tenant, project_id}` — LLM structured output은 `executive_summary`·`key_entities` 등 bounded 필드이며 agent가 `markdown`을 조립한다.

`graph_context_s3`는 `graph_context/{tenant}/{project_id}/{batch_id}/{community_id}.json` artifact URI. wiki S3는 `wiki/{tenant}/{project_id}/{slug}.md`.

## 프롬프트

- `src/wiki_synthesizer/prompts/community_report.txt` — MS GraphRAG community report 템플릿 기반

## agents-runtime 번들 import

`__file__`은 번들 exec 시 정의되지 않는다. 프롬프트는 `paths.read_prompt()`(`__spec__.origin`)로 읽는다. graph-extractor와 동일 제약.

## LangGraph

1. `load_context` — `graph_context_s3` JSON
2. `synthesize` — `community_report.txt` + LLM(`response_format` `wiki_v1` JSON schema) → bounded sections → `assemble_wiki_markdown()` → `pages[]`
3. `project_slug` — invoke input 필수 (`WikiSynthesizerInput`)

## Commands

```bash
cd agents/wiki-synthesizer/src && zip -r ../bundle.zip wiki_synthesizer
# agent 이름: wiki-synthesizer, entrypoint=wiki_synthesizer.agent:factory
./scripts/register-agent-bundles.sh wiki-synthesizer v2

# pipeline 쪽 검증 (repo root)
make test   # test_agent_bundles.py, test_wiki.py
```
