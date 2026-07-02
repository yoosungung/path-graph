# graph-extractor — 내부 설계

MS GraphRAG entity/relationship extraction 프롬프트 사상을 LangGraph로 이식한다. 컴포넌트 간 계약은 [ARCHITECTURE.md](../../ARCHITECTURE.md) §2.5.

## 현재 상태

| 항목 | 상태 |
|------|------|
| invoke payload 계약 | [x] `GraphExtractorInput` — `project_id` (UUID) |
| pipeline 연동 | [x] `graph_pipeline.py` + `test_graph.py` (agent mock) |
| LangGraph 본구현 | [x] `graph.py` — load chunks → LLM extract → entities/edges |
| agents-runtime 번들 배포 | [x] `./scripts/register-agent-bundles.sh` — `agent:compiled_graph` |

## 입출력

- **input**: `{tenant, project_id, batch_id, chunks_s3, output_schema, idempotency_key}`
- **output**: `{entities: [{id, name, description?}], edges: [{type, source, target, confidence, description?}], tenant, project_id}`

`project_id`는 Knowledge Project UUID다. Nebula Space는 binding의 `nebula_space` (`path_graph_{tenant_slug}_{project_slug}`).

## 프롬프트

- `src/graph_extractor/prompts/extract_graph.txt` — MS GraphRAG `extract_graph` 템플릿 기반 (청크 텍스트 → entity/relation JSON)

## agents-runtime 번들 import

동적 import(`runtime_common.bundle_import`)는 모듈 `__file__`을 설정하지 않는다(`__spec__.origin`만 유효). 번들 코드에서 **모듈 최상단 `Path(__file__)` 금지** — 프롬프트 경로는 `paths.read_prompt()`(`__spec__.origin` 기준)로 읽는다.

## LangGraph

1. `load_chunks` — `chunks_s3` URI → JSONL (`artifact_io.fetch_bytes`) → **문자 예산 단위 배치** (`chunk_batches`)
2. `extract_graph` — 배치마다 `extract_graph.txt` + LLM(`response_format` `graph_v1`) → `merge_graph_parts`로 entities/edges 합침
3. `factory` — `StateGraph` compile → `CompiledStateGraph.ainvoke` (agents-runtime `agent:compiled_graph` 풀)

### 컨텍스트 예산 (Preset → 번들 → user-meta)

역할 분리:

| 계층 | 책임 | 예 |
|------|------|-----|
| **LLM Preset** (`llm_presets`) | 서버가 허용하는 상한 | sglang-gemma4 → `context_window_tokens=16384` |
| **Agent 번들** (`cfg.graph_extractor`) | preset 안에서 prompt/output 예산 전략 | `max_batch_chars`, `max_completion_tokens` |
| **user-meta** | 테넌트별 미세 조정 | (향후) 동일 키 override |

`langgraph.model`이 `preset:NAME`이면 factory 시 `LLM_PRESET_{NAME}_CONTEXT_WINDOW`·`LLM_PRESET_{NAME}_MAX_OUTPUT_TOKENS`(agents-runtime reconciler 주입)로 **물리 상한**을 읽고, `compute_graph_extractor_budgets()`가 `max_batch_chars`·`max_completion_tokens` 기본값을 계산한다. env가 없으면 보수적 fallback(`4000`자 / `4096` 토큰). 번들 cfg에 명시된 값이 있으면 그 전략이 우선한다.

운영 LLM(sglang-gemma4)은 **총 16K 토큰**이다. 단일 호출에 prompt+completion이 16K에 닿으면 structured output 파싱이 실패한다(`LengthFinishReasonError`).

| 설정 (`cfg.graph_extractor`) | 기본값 | 용도 |
|------------------------------|--------|------|
| `max_batch_chars` | preset 계산 또는 `4000` | LLM 1회당 청크 텍스트 상한(문자) |
| `max_completion_tokens` | preset 계산 또는 `4096` | `llm.bind(max_tokens=…)` |

출력이 `max_completion_tokens`에 닿으면 해당 배치 텍스트를 **반으로 쪼개 재귀 호출**한다(`min_split_chars` 미만이면 실패).

전체 chunks.jsonl은 배치 루프로 **모두** 처리한다(이전 `16_000` 문자에서 조기 중단하던 동작 제거).

S3: pipeline이 invoke 시 **presigned HTTP URL**을 전달한다(`BlobStore.agent_artifact_uri`). agent pool은 `httpx` GET만 사용(boto3 없음). 로컬은 `file://`.

응답은 runtime runner가 `{"output": state}`로 감싼다 — pipeline `agent_invoke.py`가 unwrap.

## Commands

```bash
# zip (루트 = graph_extractor 패키지)
cd agents/graph-extractor/src && zip -r ../bundle.zip graph_extractor

# admin POST /api/source-meta/bundle
#   name=graph-extractor, version=v4, runtime_pool=agent:compiled_graph
#   entrypoint=graph_extractor.agent:factory
./scripts/register-agent-bundles.sh graph-extractor v4

# pipeline 쪽 검증 (repo root)
make test   # test_agent_bundles.py, test_graph.py
```
