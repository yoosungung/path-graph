# pipeline — 내부 설계

컴포넌트 *간* 계약은 [ARCHITECTURE.md](../ARCHITECTURE.md). 본 문서는 Argo step·agent 클라이언트·배치 처리 구현 방침만 다룬다.

---

## Core ingest path

로컬 CLI·수집기 공통 경로 (`steps/ingest_helpers.ingest_item`):

```
collect / ingest_web
  → blob store: raw/{tenant}/{project_id}/{source_id}/{content_hash}/{filename}
  → parse (parsers/parse.py — markitdown / rhwp-batch)
  → chunk (chunkers/chunk.py — CHUNK_MAX_CHARS)
  → S3: parsed/{tenant}/{doc_id}/, chunks/{tenant}/{doc_id}/chunks.jsonl
  → PG: documents, chunks (project_id 포함, meta/pg.py)
  → [optional --rag] rag_index: embed → pgvector (`chunks.embedding`)
```

| 모듈 | 역할 |
|------|------|
| `steps/ingest.py` | raw bytes → parse → chunk → artifact write |
| `steps/ingest_web.py` | URL / file CLI |
| `steps/ingest_helpers.py` | manifest line → `ingest_item` |
| `steps/rag_index.py` | document 단위 embed + PG pgvector upsert |
| `storage/blob.py` | local / S3 backend |
| `ids.py` | `document_id`, `chunk_id` (UUIDv5) |
| `config.py` | env → `Settings` |

### ingest manifest (Argo WF)

- **`steps/ingest_manifest.py`** — `BatchManifestLine` JSON 한 줄 → `ingest_item` ([ARCHITECTURE §2.6](../ARCHITECTURE.md#26-공통-json-스키마))
- **`ingest_helpers.parse_manifest_line`** — `document_id` 보강
- **WF**: `pipeline-ingest-rag` — `batch_manifest_key`(S3, **우선**) 또는 `batch_manifest` inline JSON → `load_batch_manifest` → `withParam` map ingest. 둘 다 있으면 **key만** 사용(inline 무시).
- **`steps/load_batch_manifest.py`** — S3 manifest jsonl → JSON 배열 (Argo output parameter)
- **`admin.runner.read_manifest_lines`** — S3 manifest jsonl → `BatchManifestLine` 필드(`project_id` 포함) 유지
- **`steps/collect_source_step.py`** — PG source + credential env → collect → Argo output `manifest_key`
- **WF**: `pipeline-collect-ingest-rag` — collect step → `pipeline-ingest-rag` (`batch_manifest_key`)

---

## Lifecycle (raw 생명주기)

관리 계층: `tenant → project → source → document → chunk`. Agent: `tenant → project → (rag, graph, wiki)` ([`contracts/project.py`](src/path_graph/contracts/project.py)).

**Project slug**: `slug` 미지정 시 `name`에서 `[a-z0-9_-]`만 남겨 derive. 라틴 문자가 없으면(예: 한글 전용 name) `p_{sha256(name)[:8]}` fallback. 명시 `slug`가 규칙 위반이면 API 422.

| 모듈 | 역할 |
|------|------|
| `lifecycle/tombstone.py` | `(tenant, project_id, content_hash)` 차단 |
| `lifecycle/compensation.py` | re-ingest·purge 전 embedding clear·Nebula 정리 |
| `lifecycle/purge.py` | Document/Source/Project purge. **Project purge**는 미처리 문서를 `hard_raw`로 purge한 뒤 `raw/{tenant}/{project_id}/` prefix 일괄 삭제 + `vfs_wiki_files` project 트리 삭제(이미 `purged` 문서·미 ingest upload 포함). **`delete_project`**는 purge와 동일한 blob·인덱스 정리 + 프로젝트 `parsed`·`communities`·`graph_context` prefix + PG 행 hard delete |
| `lifecycle/reconcile.py` | PG truth 기준 Nebula 고아 삭제 |
| `lifecycle/artifact_cleanup.py` | temp S3 정리 (indexed 미접촉) |
| `lifecycle/wiki_stale.py` | purge 후 stale_communities 기록 |
| `admin/lifecycle.py` | BFF용 `api_*` (agents-runtime 래핑) |
| `admin/projects.py` | `ensure_default_project`, `backfill_orphan_project_ids` — legacy `project_id IS NULL` 행 복구 |
| `steps/purge_step.py` | Argo/CLI purge·delete (`--scope project` \| `delete`) |
| `steps/reconcile_step.py` | Argo/CLI reconcile |
| `steps/cleanup_step.py` | Argo/CLI artifact cleanup |

**정보삭제**: `python -m path_graph.steps.purge_step --tenant … --project-id … --scope project|delete`

**Project lifecycle WF**: `pipeline-purge-project` · `pipeline-delete-project` — BFF `POST …/purge|delete` → 202 + Argo submit (동기 실행 없음)

**IndexReconcile**: `python -m path_graph.steps.reconcile_step` — Cron WF `pipeline-reconcile-index`

**SharePoint delta**: `SharePointCollector.collect_delta` — `config.delta_link` 갱신은 source update(agents-runtime).

---

## 공통 환경 변수

로컬은 `./scripts/wire-dev.sh env`가 [`.env.dev.local.example`](../.env.dev.local.example) 형태로 생성. 수집기 전용 env는 아래 collector 절 참고.

| env | 기본값 | 용도 |
|---|---|---|
| `PATH_GRAPH_TENANT` | — | CLI `--tenant` 미지정 시 (비어 있으면 오류) |
| `PATH_GRAPH_DSN` | — | runtime PG (`path_graph` schema) |
| `PIPELINE_STORAGE_BACKEND` | `local` | `local` \| `s3` |
| `PIPELINE_STORAGE_DIR` | `.data/pipeline` | local blob root |
| `PATH_GRAPH_DSN` | — | runtime PG (pgvector) |
| `EMBEDDING_BASE_URL` | cluster TEI URL | OpenAI `/v1/embeddings` |
| `EMBEDDING_MODEL` / `EMBEDDING_DIM` | `BAAI/bge-m3` / `1024` | |
| `EMBEDDING_BATCH_SIZE` | `8` | TEI 요청당 input 상한 |
| `CHUNK_MAX_CHARS` | `1000` | 청크 hard-split |
| `ENVOY_URL` / `PIPELINE_AGENT_ACCESS_TOKEN` | — | agent invoke |
| `NEBULA_HOST` / `NEBULA_PORT` / `NEBULA_USER` / `NEBULA_PASSWORD` | — | Graph upsert |
| `NEBULA_SCHEMA_WAIT_SEC` / `NEBULA_SCHEMA_POLL_INTERVAL_SEC` | 20 / 1 | Nebula DDL 전파 폴링 |

---

## Agent invoke (`steps/agent_invoke.py`)

### 문제

동기 `POST /v1/agents/invoke`를 수 분간 홀딩하면 Argo worker가 타임아웃·OOM·LLM rate limit에 취약하다.

### 패턴 (Phase 2 — 기본)

1. **Submit**: `POST {ENVOY}/v1/agents/jobs` — 동기 `/v1/agents/invoke` 대신 `job_id` 즉시 수신. `session_id = f"{workflow_uid}:{step}:{batch_idx}"` (멱등·추적).
2. **Poll**: `GET {ENVOY}/v1/agents/jobs/{job_id}?agent=…` — 5s 간격, max **7200s (2h)**. Argo worker는 agent pool HTTP 연결을 홀딩하지 않는다.
3. **Argo `suspend` + resume** (`PIPELINE_AGENT_INVOKE_MODE=async_suspend`): submit body `callback.argo`에 WF name/namespace/`node_field_selector` 전달 → job 완료 시 agents-runtime이 Argo `PUT …/resume`(또는 실패 시 `…/stop`) 호출. WF 템플릿에 `suspend: {}` step이 선행해야 한다.

동기 `/v1/agents/invoke`는 `PIPELINE_AGENT_INVOKE_MODE=sync`로만 유지(디버그·로컬).

**Argo suspend 템플릿 (split step)** — graphrag 단일 container 대신:

```yaml
steps:
  - - name: submit-agent
      template: pipeline-submit-agent-job   # POST /v1/agents/jobs + callback.argo
  - - name: wait-agent
      template: suspend                     # agents-runtime job 완료 시 PUT …/resume
  - - name: fetch-agent
      template: pipeline-poll-agent-job     # GET /v1/agents/jobs/{id}
```

`suspend` 노드는 `inputs.parameters.job-id`를 `node_field_selector`로 resume 타깃에 넘긴다. monolithic `pipeline-graphrag` step은 **`async_poll`**(기본)을 사용한다.

### 타임아웃 (기본값)

| 계층 | 값 | 비고 |
|---|---|---|
| Job poll interval | 5s | `PIPELINE_AGENT_JOB_POLL_INTERVAL_S` |
| Job max wait | 7200s (2h) | `PIPELINE_AGENT_JOB_MAX_WAIT_S` — 초과 시 `failed`, retryable |
| Argo step `activeDeadlineSeconds` | 7200s | graphrag step (poll + graph-extractor job) |
| Sync invoke (legacy) | 600s | `PIPELINE_AGENT_INVOKE_MODE=sync` only |

### 재시도

- **429 / 503**: exponential backoff, max 5회, jitter.
- **4xx (입력 오류)**: retry 금지 → `dead_letter`.
- invoke payload에 항상 `tenant`, `document_id` 또는 `batch_id`, `idempotency_key` (= content_hash 또는 batch manifest hash).

### LangGraph agents (3.1.6)

`agents/graph-extractor`, `agents/wiki-synthesizer` — `StateGraph` 2-node workflow, `agent:compiled_graph` 풀.

| agent | nodes | structured output |
|---|---|---|
| graph-extractor | `load` → `extract` | `graph_v1` JSON schema (`entities[]`, `edges[]`) |
| wiki-synthesizer | `load` → `synthesize` | `wiki_v1` JSON schema (`slug`, `title`, `markdown`) |

- **artifact I/O**: pipeline이 `BlobStore.agent_artifact_uri(key)`로 **presigned HTTPS**(S3) 또는 `file://`(local) URI를 invoke input에 넣는다. agent pool은 `httpx` GET만 사용 — **S3 credential env 불필요**.
- **LLM**: `runtime_common.providers.langgraph.prepare_langgraph_llm(cfg)` + `llm.bind(response_format=...)`.
- **번들 등록**: `./scripts/register-agent-bundles.sh {graph-extractor|wiki-synthesizer|all} v2` — [deploy/SETUP.md](../deploy/SETUP.md#langgraph-agent-bundles).
- **테스트**: `test_graph_extractor_langgraph.py`, `test_wiki_synthesizer_langgraph.py`, `test_agent_artifact_io.py`, `test_agent_bundles.py`.

클러스터 downstream E2E는 LLM·번들 등록 전제 — `submit-downstream-e2e.sh` 기본 `skip_agent=1`; live agent 검증은 번들 등록 후 `skip_agent=0`.

---

## LLM·Agent 동시성 (Argo Semaphore)

WorkflowTemplate에 **ClusterWorkflowTemplate** 수준 semaphore:

```yaml
# 예: workflow-level
synchronization:
  semaphore:
    configMapKeyRef:
      name: path-graph-limits
      key: agent-invoke
```

| 키 | 기본값 | 의미 |
|---|---|---|
| `agent-invoke` | 8 | cluster 전체 graph+wiki agent step 동시 실행 |
| `parse-hwp` | 4 | rhwp-batch CPU bound |
| `embed` | 16 | embed step (PG vector write bound) |
| `ingest-map` | 10 | ingest map step 동시 실행 (WF `max_parallel`과 병용) |

tenant별 추가 제한: `batches/{tenant}/{batch_id}/manifest.meta.json`의 `max_parallel`(기본 10, source `config.max_parallel`로 override). Workflow submit 시 `max_parallel` 파라미터 → `spec.parallelism`. `ingest-map` semaphore(ConfigMap)과 병용.

Rate limit (429) 시 Argo `retryStrategy` + step 내 backoff. 전역 semaphore가 1차 방어선.

---

## Mini-batch & Map

1. **collect** → `batches/{tenant}/{batch_id}/manifest.jsonl` (한 줄 = [ARCHITECTURE §2.6 `BatchManifestLine`](../ARCHITECTURE.md#26-공통-json-스키마)).
2. **ingest Workflow** entry: `withParam` manifest → sub-DAG (parse → chunk → fan-out).
3. 기본 **batch size 100**. 수집기가 버퍼 채우면 Workflow 1회 submit.
4. `parallelism: 10` (ingest map, WF param `max_parallel`), `embed` semaphore 16 — `podGC` **OnPodCompletion**(템플릿) + `deleteDelayDuration: 60s`(`workflowDefaults`만). 단일 노드 inotify: [SETUP.md](../deploy/SETUP.md).

단건 재처리: `document_id` 또는 `content_hash` 단일 항목 manifest.

---

## Blocks 구조화 (D3)

**결정 (ROADMAP D3)**: PDF/DOCX 등은 **md→blocks 후처리**. 파싱 모듈(markitdown·Docling·Azure DI 등)은 바뀔 수 있으므로 **md 생성**과 **blocks 추출**을 분리하고, 청킹은 항상 `content.json` `blocks[]`만 본다.

### 파이프라인

```
bytes → parse (markitdown | rhwp-batch | VL OCR → md)
      → blocks extractor (BLOCKS_EXTRACTOR)
      → content.json + content.md (md는 디버그·재추출용)
      → chunk_from_blocks
```

| 레이어 | 책임 | 교체 |
|--------|------|------|
| **parse** | 바이너리 → Markdown(또는 HWP JSON) | markitdown, VL OCR, (미래) Docling pre-md |
| **blocks extractor** | Markdown → `content.json` | `md_heuristic`(기본·정본) |
| **chunk** | `blocks[]` → `chunks.jsonl` | `chunk_from_blocks` 고정 |

### Registry

- 패키지: `path_graph.parsers.blocks_extractors`
- `BlocksExtractor` protocol: `name: str`, `extract(markdown: str) -> dict`
- `get_blocks_extractor(name)` — 미등록 이름은 `ValueError`
- 신규 구현: 모듈 추가 + `register_blocks_extractor()` (또는 `@register` 데코레이터)

### 환경 변수

| 변수 | 기본 | 설명 |
|------|------|------|
| `BLOCKS_EXTRACTOR` | `md_heuristic` | registry 키 |

### `md_heuristic` (기본·정본)

markitdown md → `content.json` `blocks[]`. 외부 파서(Docling 등)는 성능 병목 시 별도 검토.

| 규칙 | 동작 |
|------|------|
| ATX heading | `#` … `######` — 스택 기반 `heading_path` |
| Setext heading | 다음 줄 `===` / `---` — level 1 / 2 |
| Bold line | 단독 `**title**` — level 2 (markitdown 관행) |
| Table | `\|` 시작 행 연속 + separator(`\|---\|`) 인식; 2행 미만·separator 없으면 paragraph |
| Paragraph | 빈 줄 **1개**는 같은 문단(soft break); **2개 이상**이면 문단 분리 |

### HWP

`rhwp-batch` JSON이 이미 `blocks[]`를 포함 — extractor 생략, `extractor=rhwp_batch` 메타만 보강.

---

## 외부 LLM·Embedding (D4)

**결정 (ROADMAP D4)**: LLM·Embedding **서빙은 path-graph 외부**. 구현체(TEI·sglang·상용 API)는 바뀔 수 있으므로 pipeline은 **OpenAI-compatible HTTP + env**만 유지한다. in-process 모델 로드 금지.

| 용도 | env (대표) | 프로토콜 |
|------|------------|----------|
| RAG embed | `EMBEDDING_BASE_URL`, `EMBEDDING_MODEL`, `EMBEDDING_DIM` | `POST /v1/embeddings` |
| VL OCR | `OCR_LLM_BASE_URL`, `OCR_LLM_MODEL` | `POST /v1/chat/completions` |
| Graph/Wiki agent | `ENVOY_URL`, `PIPELINE_AGENT_ACCESS_TOKEN` | `POST /v1/agents/invoke` |

로컬: `wire-dev` port-forward 후 URL override.

### Hybrid search (3.3.1)

project **내부** PG FTS + pgvector 두 채널을 RRF로 병합한다. multi-project RRF(PG-4)는 agents-runtime `runtime_common.knowledge`가 담당.

| 모듈 | 역할 |
|------|------|
| `path_graph.meta.pg` | `chunks.text_tsv` GIN + `search_fts()` |
| `path_graph.meta.pg.PgMetaStore` | `search_vector()` — cosine ANN |
| `path_graph.rag.rrf` | `reciprocal_rank_fusion()` |
| `path_graph.rag.hybrid_search` | `hybrid_search(tenant, project_id, project_slug, query, top_k=…)` |

소비: agents-runtime **Container MCP** — path-graph·pgvector·embedding 의존성은 **이미지에 포함**

FTS: PostgreSQL `simple` config + `plainto_tsquery`. ingest `upsert_chunks` 시 `text_tsv` 동기 갱신.

### Retrieval CLI · Admin search (3.3.3)

로컬·E2E에서 hybrid search를 agent/MCP 없이 검증한다.

| 진입점 | 용도 |
|--------|------|
| `python -m path_graph.steps.retrieval_search` | CLI — `--tenant` `--project-id` `--query` `--top-k` `--json` |
| `path_graph.admin.retrieval.api_search_project` | domain API — BFF가 `asyncio.to_thread`로 호출 |
| agents-runtime `GET /api/pipeline/projects/{id}/search` | Admin Console — `q`, `top_k` query params |

응답: `{query, project_id, project_slug, results[]}` — `results`는 `hybrid_search`와 동일(`chunk_id`, `text`, `rrf_score`, 채널 score).

---

## 수집 주기·동기화 (D5)

**결정 (ROADMAP D5)**:

| 항목 | 계약 |
|------|------|
| 주기 | Admin Console UI — source `schedule_cron` → CronWorkflow |
| 기본 | `config.sync_mode=delta` — SharePoint `collect_delta` |
| 전체 재수집 | Run now / `--sync-mode=full` override |
| 커서 | `config.delta_link` ← collect 출력; BFF reconciler persist (`SourceStore.patch_source_config`). full 성공 시 `delta_link` 제거 |
| Argo | `pipeline-collect-ingest-rag` — WF param `sync_mode`; collect step output `delta_link` |

`CollectSyncMode`: `delta` \| `full` — `contracts/source.py`. GDrive/OneDrive는 현재 `full`만.

---

## Parse error boundary

| 포맷 | 이미지 | limits (memory) |
|---|---|---|
| hwp/hwpx | `rhwp-batch` v0.7.15 (GH release `x86_64-unknown-linux-gnu` tarball) | 2Gi |
| pdf/docx/xls/xlsx/txt/md | markitdown `[pdf,docx,xlsx,xls]` | 2Gi |
| legacy `.doc` | 미지원 — 업로드 허용 시 ingest `dead_letter` (docx 변환 권장) | — |

실패 시:

1. `dead_letter/{tenant}/{content_hash}/error.json` — `{stage, exit_code, stderr_snippet, at}`
2. PG `documents.ingest_state = dead_letter`
3. Argo `continueOn.failed: true` on parse map step

---

## VL OCR ingest — 빈 parse fallback

**상태: 구현됨** — `parsers/pdf_render.py`, `parsers/vl_ocr.py`, `steps/ingest.py` fallback. 계약 변경 시 [ARCHITECTURE.md](../ARCHITECTURE.md) §1을 먼저 갱신한다.

### 배경·목표

- **문제**: `markitdown`은 텍스트 레이어가 없는 **이미지 스캔 PDF**에서 빈 Markdown → chunk 0 → `ingest_state`가 `pending`에 머무름(`indexed_rag` 미도달). `ParseError`가 아니므로 **dead_letter도 아님** — ingest WF는 `continueOn.failed: true`로 **Succeeded**일 수 있어 Console GraphRAG가 실패한다.
- **설계 방향**: 별도 「전처리 단계」가 아니라 **동일 ingest pass 안의 fallback** — 1차 markitdown 후 **저텍스트·zero-chunk**이면 VL OCR 재시도, 그래도 실패하면 그때 `dead_letter`. `markitdown-ocr` 패키지는 쓰지 않고 클러스터 **sglang + Gemma 4 12B**(`llm-serving/sglang-gemma4-12b:30000`) Vision API만 사용.
- **범위**: parse 단계만 확장. chunk · RAG embed(TEI) · GraphRAG 이후는 기존 경로 재사용.
- **비범위**: DOCX/PPTX embedded image OCR, raw **0 byte** 파일( VL OCR 불가 ), markitdown-ocr 도입.

### 트리거 — dead letter fallback vs 동일 pass fallback

| 방식 | 설명 | 채택 |
|------|------|------|
| **동일 pass fallback** (권장) | `ingest_item` 한 번: markitdown → (빈 결과) → VL OCR → chunk/RAG | **예** — 스캔 PDF 실패 모드와 정합 |
| dead_letter → Reingest만 | 1차 ingest가 `pending`/빈 성공 후 운영자가 UI Reingest | 보조 — OCR 설정 추가 **이후** 이미 쌓인 문서용 |
| dead_letter → 자동 2차 WF | `stage: parse_empty` dead letter 전용 Argo | **아니오** — 지연·복잡도만 증가 |

**「0 byte 문서」 구분**

| 케이스 | raw | 1차 markitdown | fallback |
|--------|-----|----------------|----------|
| 스캔 PDF | bytes > 0 | 텍스트 ≈ 0, chunk 0 | VL OCR |
| 진짜 빈 파일 | 0 byte | (업로드 단계에서 거부 권장) | 불가 → `dead_letter` `stage: empty_raw` |
| 손상 PDF | bytes > 0 | `ParseError` | VL OCR **시도 가능**(PyMuPDF 렌더 성공 시); 렌더 실패 시 `dead_letter` `stage: parse` |
| 디지털 PDF | bytes > 0 | 텍스트 충분 | fallback **스킵** |

현행 버그 수정(구현 시 필수): chunk 0이면 `ingest_item`이 **성공(True)으로 끝나지 않도록** — fallback 시도 후에도 chunk 0이면 `record_dead_letter(..., stage: ocr_empty)` 및 `return False`.

### 흐름 (ingest_item 내부)

```
ingest_item
  → parse_document (markitdown)     # 항상 1차
  → blocks extractor (BLOCKS_EXTRACTOR) → content.json
  → chunk_from_blocks
  → if chunk_count == 0 AND pdf AND OCR_LLM_BASE_URL configured:
       vl_ocr_pdf_to_markdown
         1. PDF → PNG (pymupdf, OCR_RENDER_DPI)
         2. 페이지별 sglang chat/completions (image_url)
         3. 페이지 md 합침 → 재-extract blocks → 재-chunk
  → if chunk_count == 0:
       dead_letter stage: parse_empty | ocr_empty
       return False
  → [rag] index_rag_for_document → indexed_rag
```

`parse_backend` 메타: `markitdown` | `markitdown+vl_ocr_fallback` | `vl_ocr` (`OCR_FORCE` 시만 markitdown 생략).

### 산출물 (S3)

| 단계 | 키 | 비고 |
|------|-----|------|
| 페이지 PNG | `parsed/{tenant}/{doc_id}/pages/{page:04d}.png` | fallback 사용 시만 |
| VL OCR 페이지 md | `parsed/{tenant}/{doc_id}/ocr/{page:04d}.md` | |
| 최종 md | `parsed/{tenant}/{doc_id}/content.md` | chunk 입력 |
| meta | `parsed/{tenant}/{doc_id}/meta.json` | `parse_backend`, `fallback_reason: low_text` |

`dead_letter/{tenant}/{content_hash}/error.json` — fallback 후에도 실패 시 `{stage, prior_backend, ocr_error?}`.

### sglang / Gemma 4 Vision 클라이언트

- **프로토콜**: OpenAI-compatible `POST {OCR_LLM_BASE_URL}/v1/chat/completions`
- **dev 클러스터 기준** (검증됨):
  - `OCR_LLM_BASE_URL=http://sglang-gemma4-12b.llm-serving.svc.cluster.local:30000`
  - `OCR_LLM_MODEL=nmilosev/gemma-4-12B-it-quantized.w4a16` (`GET /v1/models`의 `id`와 일치)
  - `OCR_LLM_API_KEY=EMPTY` (sglang dev)
- **요청 형식** (markitdown-ocr와 동일 패턴):

```json
{
  "model": "<OCR_LLM_MODEL>",
  "messages": [{
    "role": "user",
    "content": [
      {"type": "text", "text": "<OCR_PROMPT>"},
      {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
    ]
  }],
  "max_tokens": 2048,
  "temperature": 0
}
```

- **기본 프롬프트** (`OCR_PROMPT`): 한국어·영문 혼용 문서용 — 표 구조 유지, 머리글/각주 구분, 추측 금지, Markdown만 출력.
- **페이지 상한** (`OCR_MAX_PAGES`, 기본 30): 렌더 후 초과 시 API 호출 없이 `ValueError` → `dead_letter` `stage: ocr_empty`. 페이지 수별 Argo 정책 분기는 하지 않는다.
- **ingest-rag deadline**: `ingest-one` `activeDeadlineSeconds: 3600` — VL OCR(페이지 순차) + RAG embed를 15분(900s) 안에 끝내기 어려움. 디지털 PDF는 여전히 수 분 내 완료.
- **응답 처리**: `choices[0].message.content`만 사용. Gemma 4 `reasoning_content`는 무시.
- **재시도**: HTTP 429/5xx, 빈 content → 지수 backoff 최대 `OCR_MAX_RETRIES`(기본 2). 페이지 단위 실패 시 해당 페이지만 재시도; 전 페이지 실패 시 document `dead_letter`.
- **동시성**: 문서 내 페이지는 **순차**(GPU 메모리·context 16k). 문서 간 병렬은 기존 ingest map `parallelism`에 맡김. cluster 전역 제한용 semaphore 키 `ocr-vision`(기본 2) — `path-graph-limits` ConfigMap.

sglang Gemma 4 cookbook: 이미지 품질이 중요하면 서버 측 `--attention-backend triton` 검토(B200 등). pipeline 코드 변경 범위 밖 — llm-serving 배포 정책.

### 모듈 배치 (구현 예정)

| 모듈 | 역할 |
|------|------|
| `parsers/pdf_render.py` | PDF → `list[bytes]` PNG (`OCR_RENDER_DPI`, 기본 200) |
| `parsers/vl_ocr.py` | 페이지 PNG → Markdown; httpx Vision client |
| `parsers/ocr_prompt.py` | 기본·커스텀 프롬프트 상수 |
| `parsers/parse.py` | markitdown/HWP parse (`vl_ocr`는 `ingest.py`에서 호출) |
| `tests/test_vl_ocr.py` | mock HTTP; pdf_render·fallback·dead_letter |

`ingest.py` / `ingest_helpers.py` 시그니처 변경 없음 — `parse_document` 내부만 확장.

### 환경 변수 (신규)

| env | 기본값 | 용도 |
|-----|--------|------|
| `OCR_LLM_BASE_URL` | — | 설정 시 빈 parse fallback 활성 (미설정 = 현행) |
| `OCR_FORCE` | `false` | PDF markitdown 생략·VL OCR만 (디버그) |
| `OCR_LLM_MODEL` | — | `/v1/models` id |
| `OCR_LLM_API_KEY` | `EMPTY` | |
| `OCR_LLM_TIMEOUT_S` | `120` | 페이지당 |
| `OCR_RENDER_DPI` | `200` | PNG 렌더 |
| `OCR_MIN_TEXT_CHARS` | `32` | (선택) markitdown 직후 조기 fallback; 기본은 **chunk_count==0** |
| `OCR_MAX_RETRIES` | `2` | 페이지 API 재시도 |
| `OCR_MAX_PAGES` | `30` | 렌더 페이지 상한; `0` = 무제한 |
| `OCR_MAX_TOKENS` | `2048` | 페이지당 chat/completions `max_tokens` |
| `OCR_KEEP_PAGE_IMAGES` | `true` | S3 page PNG 보존 |
| `OCR_PROMPT` | (내장 기본) | override 가능 |

`config.py` `Settings`에 등록. Secret `path-graph-env` / dev overlay에 OCR_* 추가(구현 시).

### K8s·네트워크

- Pipeline Pod egress: `llm-serving` **:30000** (sglang) — TEI `:8080`과 별도. [deploy/k8s/base/networkpolicy.yaml](../deploy/k8s/base/networkpolicy.yaml) `path-graph-pipeline-egress`에 TCP 30000 명시(구현 시).
- ingest-rag Pod memory: VL OCR 시 페이지 PNG·base64 버퍼 — limits **2Gi → 4Gi** 검토(`pipeline-ingest-rag.yaml`).
- **의존 패키지**: `pymupdf`(PDF 렌더), `openai`(HTTP client). pipeline 이미지 빌드·`test_parse_deps` 갱신.

### TDD · 구현 순서

| # | 작업 | 검증 |
|---|------|------|
| 1 | `pdf_render` — fixture PDF → N PNG | pytest, 페이지 수·크기 |
| 2 | `vl_ocr` — mock completions → md | 프롬프트·base64·재시도 |
| 3 | `ingest_item` — chunk 0 → fallback → dead_letter | mock; `pending` 잔류 금지 |
| 4 | `ingest_item` 통합 — mock OCR → chunks > 0 → `indexed_rag` | 기존 ingest 테스트 확장 |
| 5 | k8s dev E2E — 스캔 PDF 3건 manual upload → ingest → GraphRAG | Console Runs |

### 운영·비용

- **비용**: 페이지당 1회 Vision forward (3페이지 PDF ≈ 3 GPU 호출). embed(TEI)와 **별도 큐**.
- **지연**: 12B quant + 순차 페이지 — 문서당 수 분 가능. ingest map `activeDeadlineSeconds`(900s) 초과 시 WF 템플릿 조정.
- **품질**: w4a16 양자화·낮은 DPI는 OCR 품질 저하 — DPI·프롬프트·(필요 시) non-quant 모델은 llm-serving 측 튜닝.

### ROADMAP

[ROADMAP.md §3.3.4](../ROADMAP.md) — 구현 착수 시 상태 갱신.

---

## GraphRAG (Hybrid, project_id 단위)

MS GraphRAG 사상을 **Knowledge Project** 경계와 정합되게 구현한다. Community·Wiki는 **project_id** 경계를 넘지 않는다.

### 흐름 (`steps/graphrag_pipeline.py`)

1. `copy_chunks_to_project_batch` — batch chunks → `chunks/{tenant}/{project_id}/{batch_id}/chunks.jsonl`
2. `run_graph_pipeline` — project별 graph-extractor + Nebula upsert (`graph/nebula_store.py`)
   - **순서**: `ensure_space` → wikilink `MENTIONS` upsert → graph-extractor (또는 캐시) → semantic upsert. downstream 실패 시 agent 재호출을 피한다.
   - **Agent 캐시** (`steps/agent_cache.py`): graph-extractor·wiki-synthesizer 출력을 S3에 저장. 키 `graph_extract/{tenant}/{project_id}/{batch_id}/graph_v1.json` + `meta.json` (`chunks_sha256` 검증). wiki는 `wiki_agent/.../{community_id}.json`. hit 시 `invoke_agent` 생략. WF 파라미터 `force_agent=1`이면 캐시 무시.
   - **정본**: `graph-extractor` semantic `entities`/`edges` → `EXTRACTED`/`INFERRED`
   - **보조**: chunk `[[wikilink]]` → `MENTIONS` (일반 PDF/HWP ingest에는 없음)
   - agent job `output`은 runtime이 `{"output": <LangGraph state>}`로 한 겹 감쌀 수 있다. `unwrap_agent_graph_output()`으로 `entities`/`edges`가 있는 dict까지 벗긴 뒤 Nebula upsert한다 (fixture: `tests/fixtures/graph_extractor/opik_span_019f2579-93b7.json`).
   - 반환: `batch_entity_ids` — semantic `entities[].id` 집합 (community batch 스코프)
   - **Nebula space bootstrap** (`NebulaGraphStore.ensure_space`): `CREATE SPACE` → `USE` 성공까지 폴링(graphd 캐시 전파; `SHOW SPACES`만으로는 부족) → `CREATE TAG`/`CREATE EDGE` DDL → schema 전파 대기. 태그 `Entity`, `Chunk`; 엣지 `EXTRACTED`, `INFERRED`, `MENTIONS`. DDL은 비동기 반영이므로 `SHOW TAGS`/`SHOW EDGES` 폴링 후 **Entity probe INSERT/DELETE**로 DML 준비까지 확인(`NEBULA_SCHEMA_WAIT_SEC`, 기본 20s).
   - **Entity VID** (`graph/entity_vid.py`): Nebula `FIXED_STRING(64)`는 **UTF-8 바이트** 상한. `entity:{name}` 형태는 한글·긴 조문명에서 64B를 초과할 수 있다. ingest 시 `entity_vid(name)` = `uuid5(PATH_GRAPH_NAMESPACE, "entity:{name}")`(36자)로 정규화하고, 원문은 `Entity.name` property에 저장한다. graph-extractor·wikilink의 legacy `entity:…` ref는 upsert 직전 `resolve_entity_vid()`로 canonical VID에 매핑한다. **기존 space의 legacy VID vertex와 공존하지 않음** — graphrag 재실행 전 space drop 또는 project purge 권장.
   - upsert 실패 시 `RuntimeError` — silent ignore 금지.
3. `run_community_pipeline` — `batch_entity_ids`로 `export_project_graph` 스코프 후 project별 hierarchical Leiden
4. `build_graph_context` — `graph_context/{tenant}/{project_id}/{batch_id}/{community_id}.json`
5. `run_wiki_pipeline` — project·community별 wiki-synthesizer

Argo: `pipeline-graphrag.yaml` — WF 파라미터 `tenant`, `project_id`, `project_slug`, `batch_id`.

### Community detection 설정

| env | 기본값 |
|---|---|
| `COMMUNITY_MAX_CLUSTER_SIZE` | 10 |
| `COMMUNITY_USE_LCC` | true |
| `COMMUNITY_SEED` | 0xDEADBEEF |
| `GRAPH_CONTEXT_MAX_ENTITIES` | 50 |

### Embedding (외부 TEI)

| env | 기본값 |
|---|---|
| `EMBEDDING_MODEL` | `BAAI/bge-m3` |
| `EMBEDDING_DIM` | 1024 (pgvector cosine) |
| `EMBEDDING_BASE_URL` | `http://bge-m3-tei.llm-serving.svc.cluster.local:8080` |
| `EMBEDDING_BATCH_SIZE` | 8 (TEI CPU backend 내부 배치 상한; 요청당 `input` ≤8) |
| `EMBEDDING_API_KEY` | (optional) |

`POST {EMBEDDING_BASE_URL}/v1/embeddings` — OpenAI-compatible. pipeline Pod는 in-process 모델을 로드하지 않는다.

---

## SharePoint collector (`collectors/sharepoint.py`, `steps/ingest_sharepoint.py`)

사내 SharePoint 문서 라이브러리 폴더를 Microsoft Graph로 수집 → `raw/` 적재 → `batches/{tenant}/{batch_id}/manifest.jsonl` → parse/chunk/(optional) RAG.

### Azure 앱 등록 (사전)

Entra ID 앱 등록 후 API 권한: `Sites.Read.All`, `Files.Read.All` (Application 또는 Delegated + 관리자 동의).

### env

| env | 기본값 | 용도 |
|---|---|---|
| `MS_TENANT_ID` | — | Azure tenant |
| `MS_CLIENT_ID` | — | 앱 client id |
| `MS_CLIENT_SECRET` | — | Application auth (`MS_AUTH_MODE=app`) |
| `MS_REFRESH_TOKEN` | — | Delegated auth (`MS_AUTH_MODE=delegated`) |
| `MS_AUTH_MODE` | `app` | `app` \| `delegated` \| `device` |
| `SHAREPOINT_SITE` | `tripodoffice.sharepoint.com:/sites/kms` | Graph site path |
| `SHAREPOINT_DRIVE_NAME` | `Documents` | 문서 라이브러리 drive name |
| `SHAREPOINT_FOLDER` | `회사규정` | 수집 폴더 |
| `SHAREPOINT_FILE_EXTENSIONS` | `.pdf,.doc,...` | 허용 확장자 |

- **Application**: `MS_AUTH_MODE=app` + `MS_CLIENT_SECRET`
- **Delegated**: 최초 `MS_AUTH_MODE=device`로 Device Code 로그인 → stderr에 출력된 `MS_REFRESH_TOKEN` 저장 → `MS_AUTH_MODE=delegated`

### CLI

```bash
# 목록만 (다운로드·ingest 없음)
python -m path_graph.steps.ingest_sharepoint --tenant dev --project-id UUID --folder 회사규정 --dry-run

# 수집 + ingest + RAG
python -m path_graph.steps.ingest_sharepoint \
  --tenant dev \
  --project-id UUID \
  --source-id sharepoint:kms \
  --folder 회사규정 \
  --batch-id 20250622 \
  --rag

# 수집만 (manifest + raw)
python -m path_graph.steps.ingest_sharepoint --tenant dev --collect-only
```

---

## Google Drive collector (`collectors/gdrive.py`, `steps/ingest_gdrive.py`)

Google Drive API v3 + OAuth refresh token. Google Docs/Sheets/Slides는 export 후 수집(docx/xlsx/pptx).

### env

| env | 용도 |
|---|---|
| `GDRIVE_CLIENT_ID` | Google Cloud OAuth client id |
| `GDRIVE_CLIENT_SECRET` | client secret |
| `GDRIVE_REFRESH_TOKEN` | refresh token (로컬 OAuth 후 발급) |
| `GDRIVE_FOLDER_ID` | 폴더 ID (우선) |
| `GDRIVE_FOLDER_PATH` | 루트 기준 경로 (`Reports/2024`) |
| `GDRIVE_FILE_EXTENSIONS` | 허용 확장자 |

### CLI

```bash
python -m path_graph.steps.ingest_gdrive --tenant dev --folder-id FOLDER_ID --dry-run
python -m path_graph.steps.ingest_gdrive --tenant dev --folder-path Reports/2024 --rag
python -m path_graph.steps.ingest_gdrive --tenant dev --file-id FILE_ID
```

---

## OneDrive collector (`collectors/onedrive.py`, `steps/ingest_onedrive.py`)

개인/업무 OneDrive — Graph `/me/drive`. SharePoint와 동일 Entra 앱·위임 토큰 사용 가능.

### env

| env | 용도 |
|---|---|
| `MS_TENANT_ID`, `MS_CLIENT_ID` | Entra 앱 (SharePoint와 공유 가능) |
| `ONEDRIVE_REFRESH_TOKEN` | OneDrive 전용 refresh token |
| `MS_REFRESH_TOKEN` | `ONEDRIVE_REFRESH_TOKEN` 없을 때 폴백 |
| `ONEDRIVE_FOLDER` | 드라이브 루트 기준 경로 |
| `ONEDRIVE_FILE_EXTENSIONS` | 허용 확장자 |

### CLI

```bash
python -m path_graph.steps.ingest_onedrive --tenant dev --folder Documents --dry-run
python -m path_graph.steps.ingest_onedrive --tenant dev --folder Docs --batch-id od1 --rag
python -m path_graph.steps.ingest_onedrive --tenant dev --item-id ITEM_ID
```

---

## Downstream (GraphRAG · Console)

RAG ingest batch → `path_graph.admin.downstream`:

1. `aggregate_batch_chunks` — manifest jsonl → per-doc `chunks/{tenant}/{doc_id}/chunks.jsonl` merge → `chunks/{tenant}/{project_id}/{batch_id}/chunks.jsonl`
2. `prepare_graphrag_submission` — project slug + Argo parameters
3. `assert_project_graphrag_idle` — 동일 batch active graphrag run → 409

BFF: `POST /api/pipeline/projects/{id}/graphrag` `{batch_id}`. agents-runtime `pipeline_argo.submit_graphrag`.

### ingest_state · pipeline_runs (ROADMAP 1.1.9)

| 단계 | `documents.ingest_state` | `document_ingest_state` | `pipeline_runs` |
|---|---|---|---|
| ingest upsert | `pending` | — | BFF submit `run_kind=ingest` |
| RAG index | `indexed_rag` | `rag_at` | terminal: BFF reconciler |
| parse dead-letter | `dead_letter` | `error` | — |
| GraphRAG success | `indexed_graph` | `graph_at`, `wiki_at` | BFF submit `run_kind=graphrag`; terminal + cursors: **graphrag step** (`apply_graphrag_success`) + BFF reconciler (멱등) |

---

## 모듈 맵

```
src/path_graph/
  config.py
  ids.py
  collectors/
    web.py, remote.py
    ms_graph_auth.py, sharepoint.py, onedrive.py
    gdrive_auth.py, gdrive.py
  parsers/parse.py
  parsers/pdf_render.py   # (계획) VL OCR
  parsers/vl_ocr.py
  parsers/ocr_prompt.py
  chunkers/chunk.py
  contracts/
    schemas.py, s3_keys.py, community.py, project.py, source.py
  admin/
    projects.py, sources.py, runner.py, uploads.py, downstream.py
  storage/blob.py
  meta/pg.py
  rag/embed.py
  graph/
    nebula_store.py, community_detector.py
    graph_context.py, chunk_partition.py
  steps/
    ingest.py, ingest_web.py, ingest_helpers.py, rag_index.py
    ingest_sharepoint.py, ingest_gdrive.py, ingest_onedrive.py
    graph_pipeline.py, community_pipeline.py
    graphrag_pipeline.py, wiki_pipeline.py
    agent_invoke.py
  migrations/
```

Argo `WorkflowTemplate` YAML: [`deploy/k8s/base/workflow-templates/`](../deploy/k8s/base/workflow-templates/) (Kustomize base).

## Commands

```bash
# from repo root
make install
./scripts/wire-dev.sh up && ./scripts/wire-dev.sh env   # k8s → localhost
make test
make workflow-validate   # kubectl dry-run

# local ingest
source .venv/bin/activate
python -m path_graph.steps.ingest_web --tenant dev --file ./sample.txt

# SharePoint (MS Graph credentials in .env.dev.local)
python -m path_graph.steps.ingest_sharepoint --tenant dev --folder 회사규정 --dry-run

# Google Drive / OneDrive
python -m path_graph.steps.ingest_gdrive --tenant dev --folder-path MyFolder --dry-run
python -m path_graph.steps.ingest_onedrive --tenant dev --folder Documents --dry-run

# 컨테이너 이미지 — GitHub Actions → GHCR (로컬 docker 빌드 없음)
#   git push && make build-images

# Python wheel — GitHub Release asset (agents-runtime 등 소비자용)
make build-wheel                    # pipeline/dist/*.whl
# Release published 또는 workflow_dispatch → GHA publish-package.yml
#   gh release upload vX.Y.Z dist/*.whl
# 소비: path-graph==X.Y.Z + releases/download/vX.Y.Z/*.whl URL (GitHub Packages PyPI 미지원)
# 버전: release tag vX.Y.Z ↔ pipeline/pyproject.toml version (불일치 시 publish fail)
```

**Wheel publish 계약**: 패키지명 `path-graph`, hatch `only-packages` wheel. agents-runtime은 editable path 복사 대신 release wheel URL pin. 로컬 sibling 개발은 agents-runtime `uv.override.toml`로 editable override.

**Console API**: 외부 import는 `path_graph.console`만 (`ProjectStore`, `api_get_binding`, `hybrid_search` 등). `path_graph.admin`은 Argo step·내부 구현.

Local env: [`scripts/wire-dev.sh`](../scripts/wire-dev.sh) `env` 또는 [`.env.dev.local.example`](../.env.dev.local.example)

VS Code: [`.vscode/launch.json`](../.vscode/launch.json) — `Wire: dev cluster` → `Debug: ingest_web` / `Debug: pytest`.
