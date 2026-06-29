# graph-extractor — 내부 설계

MS GraphRAG entity/relationship extraction 프롬프트 사상을 LangGraph로 이식한다. 컴포넌트 간 계약은 [ARCHITECTURE.md](../../ARCHITECTURE.md) §2.5.

## 현재 상태 (스켈레ton)

| 항목 | 상태 |
|------|------|
| invoke payload 계약 | [x] `GraphExtractorInput` — `project_id` (UUID) |
| pipeline 연동 테스트 | [x] mock 위주 — `pipeline/tests/test_graph.py` |
| LangGraph 본구현 | [ ] 아래 § LangGraph |
| agents-runtime 번들 배포 | 수동 zip + admin API |

## 입출력

- **input**: `{tenant, project_id, batch_id, chunks_s3, output_schema, idempotency_key}`
- **output**: `{entities: [{id, name, description?}], edges: [{type, source, target, confidence, description?}], tenant, project_id}`

`project_id`는 Knowledge Project UUID다. Nebula Space는 binding의 `nebula_space` (`path_graph_{tenant_slug}_{project_slug}`).

## 프롬프트

- `src/graph_extractor/prompts/extract_graph.txt` — MS GraphRAG `extract_graph` 템플릿 기반 (청크 텍스트 → entity/relation JSON)

## agents-runtime 번들 import

동적 import(`runtime_common.bundle_import`)는 모듈 `__file__`을 설정하지 않는다(`__spec__.origin`만 유효). 번들 코드에서 **모듈 최상단 `Path(__file__)` 금지** — 프롬프트 경로는 `paths.read_prompt()`(`__spec__.origin` 기준)로 읽는다.

## LangGraph (예정)

1. load chunks from `chunks_s3`
2. map: LLM extract per chunk batch
3. reduce: merge entities, dedupe edges
4. validate `graph_v1` schema

## Commands

```bash
# zip (루트 = graph_extractor 패키지)
cd agents/graph-extractor/src && zip -r ../bundle.zip graph_extractor

# admin POST /api/source-meta/bundle
#   name=graph-extractor, version=v2, runtime_pool=agent:compiled_graph
#   entrypoint=graph_extractor.agent:factory
./scripts/register-agent-bundles.sh graph-extractor v2

# pipeline 쪽 검증 (repo root)
make test   # test_agent_bundles.py, test_graph.py
```
