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
  → [optional --rag] rag_index: embed → Qdrant (project collection, payload project_id)
```

| 모듈 | 역할 |
|------|------|
| `steps/ingest.py` | raw bytes → parse → chunk → artifact write |
| `steps/ingest_web.py` | URL / file CLI |
| `steps/ingest_helpers.py` | manifest line → `ingest_item` |
| `steps/rag_index.py` | document 단위 embed + Qdrant upsert |
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
| `lifecycle/compensation.py` | re-ingest 전 Qdrant/Nebula 정리 |
| `lifecycle/purge.py` | Document/Source/Project purge. **Project purge**는 미처리 문서를 `hard_raw`로 purge한 뒤 `raw/{tenant}/{project_id}/`·`wiki/{tenant}/{project_id}/` prefix 일괄 삭제(이미 `purged` 문서·미 ingest upload 포함). **`delete_project`**는 purge와 동일한 blob·인덱스 정리 + 프로젝트 `parsed`·`communities`·`graph_context` prefix + PG 행 hard delete |
| `lifecycle/reconcile.py` | PG↔Qdrant↔Nebula 3-way 고아 삭제 |
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
| `QDRANT_URL` / `QDRANT_API_KEY` | `http://127.0.0.1:6333` | 벡터 저장 |
| `EMBEDDING_BASE_URL` | cluster TEI URL | OpenAI `/v1/embeddings` |
| `EMBEDDING_MODEL` / `EMBEDDING_DIM` | `BAAI/bge-m3` / `1024` | |
| `EMBEDDING_BATCH_SIZE` | `8` | TEI 요청당 input 상한 |
| `CHUNK_MAX_CHARS` | `1000` | 청크 hard-split |
| `ENVOY_URL` / `PIPELINE_AGENT_ACCESS_TOKEN` | — | agent invoke |
| `NEBULA_HOST` / `NEBULA_PORT` / `NEBULA_USER` / `NEBULA_PASSWORD` | — | Graph upsert |

---

## Agent invoke (`steps/agent_invoke.py`)

### 문제

동기 `POST /v1/agents/invoke`를 수 분간 홀딩하면 Argo worker가 타임아웃·OOM·LLM rate limit에 취약하다.

### 패턴 (Phase 1)

1. **Submit**: `invoke` 1회 — `session_id = f"{workflow_uid}:{step}:{batch_idx}"` (멱등·추적).
2. **Poll**: agents-runtime이 동기 SSE/JSON 응답을 끝까지 반환하는 동안, **별도 lightweight poll loop**가 아니라 **단일 invoke with extended client timeout** + **Argo `activeDeadlineSeconds`** (기본 900s, graph/wiki step).
3. **Argo `suspend`**: Phase 2 — agents-runtime에 async job API가 생기면 `suspend` + callback resume으로 전환. ARCHITECTURE §1 계약은 유지.

### 타임아웃 (기본값)

| 계층 | 값 | 비고 |
|---|---|---|
| HTTP client read | 600s | graph-extractor / wiki-synthesizer |
| Argo step `activeDeadlineSeconds` | 900s | client + S3 I/O 여유 |
| Poll interval (Phase 2) | 5s | async job 도입 시 |
| Max wait | 1800s | 초과 시 `failed` + DLQ, retryable |

### 재시도

- **429 / 503**: exponential backoff, max 5회, jitter.
- **4xx (입력 오류)**: retry 금지 → `dead_letter`.
- invoke payload에 항상 `tenant`, `document_id` 또는 `batch_id`, `idempotency_key` (= content_hash 또는 batch manifest hash).

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
| `embed` | 16 | embed step (Qdrant write bound) |

tenant별 추가 제한: batch manifest에 `max_parallel` (기본 2). Hera에서 `parallelism` + semaphore 병용.

Rate limit (429) 시 Argo `retryStrategy` + step 내 backoff. 전역 semaphore가 1차 방어선.

---

## Mini-batch & Map

1. **collect** → `batches/{tenant}/{batch_id}/manifest.jsonl` (한 줄 = [ARCHITECTURE §2.6 `BatchManifestLine`](../ARCHITECTURE.md#26-공통-json-스키마)).
2. **ingest Workflow** entry: `withParam` manifest → sub-DAG (parse → chunk → fan-out).
3. 기본 **batch size 100**. 수집기가 버퍼 채우면 Workflow 1회 submit.
4. `parallelism: 10` (ingest map), `embed` semaphore 16 — `podGC` **OnPodCompletion** + `deleteDelayDuration: 60s`(Pod 완료 후 1분, WF 진행 중 누적 최소화·로그 확인용). 단일 노드 inotify: [SETUP.md](../deploy/SETUP.md).

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
| **blocks extractor** | Markdown → `content.json` | `md_heuristic`(기본), (미래) `docling`, `azure_di` |
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

### `md_heuristic` (기본)

markitdown md에서 `#` heading · `\|` table · paragraph를 휴리스틱 분리. `heading_path`는 heading 스택으로 계산.

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

---

## 수집 주기·동기화 (D5)

**결정 (ROADMAP D5)**:

| 항목 | 계약 |
|------|------|
| 주기 | Admin Console UI — source `schedule_cron` → CronWorkflow |
| 기본 | `config.sync_mode=delta` — SharePoint `collect_delta` |
| 전체 재수집 | Run now / `--sync-mode=full` override |
| 커서 | `config.delta_link` ← collect 출력; BFF persist (agents-runtime) |

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
3. `run_community_pipeline` — project별 hierarchical Leiden
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
| `EMBEDDING_DIM` | 1024 (Qdrant cosine) |
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
  rag/embed.py, qdrant_store.py
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
workflows/
```

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
```

Local env: [`scripts/wire-dev.sh`](../scripts/wire-dev.sh) `env` 또는 [`.env.dev.local.example`](../.env.dev.local.example)

VS Code: [`.vscode/launch.json`](../.vscode/launch.json) — `Wire: dev cluster` → `Debug: ingest_web` / `Debug: pytest`.
