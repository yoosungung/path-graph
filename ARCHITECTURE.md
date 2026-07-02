# ARCHITECTURE.md

path-graph 지식 파이프라인(RAG / Graph / Wiki)의 **컴포넌트 간 계약**. 내부 구현은 [`pipeline/DESIGN.md`](pipeline/DESIGN.md), K8s 배포는 [`deploy/DESIGN.md`](deploy/DESIGN.md).

인프라 소유: **Garage·runtime PG** → agents-runtime, **Argo Workflows·Qdrant·Nebula** → path-graph [`deploy/k8s/`](deploy/k8s/) (설치·운영).

### 설계 원칙 (요약)

- **`tenant`** — 보안·격리의 1차 파티션 키. 생략·추론 금지.
- **`project`** — 사용자가 정의한 **관련 정보의 집합**(Knowledge Bundle). `project_id` (UUID)로 RAG·graph·wiki·수집 입력이 같은 경계에 닫힌다. 코드·문서에서 `project`는 이 의미만 쓴다. (과거 `project: int` hash 샤드는 **폐기**.)
- **S3 (Garage)** — artifact source of truth. PG·Qdrant·Nebula는 파생 인덱스.
- **멱등 Upsert** — Argo 재시도·부분 실패 재개 전제.
- **agents-runtime** — `POST /v1/agents/invoke`만. RAG/파이프라인 로직은 path-graph에 둔다.
- **Admin Console** — agents-runtime `backend/` + `frontend/`에 통합. path-graph 전용 UI·`users` 테이블 없음.

---

## 1. 계약사항 (불변 규칙)

### Admin Console · 인증 (agents-runtime 공유)

- **PostgreSQL** — runtime DB 단일 인스턴스. `public.users` + `path_graph.*` 스키마 공유. 별도 auth DB 없음.
- **`users.tenant`** — `NOT NULL`. bootstrap·사용자 생성 시 tenant 필수 (`INITIAL_ADMIN_TENANT`, 기본 `dev`).
- **멀티 tenant** — 한 사용자가 여러 tenant를 오가는 모델은 **계획 없음**. 1 user = 1 tenant.
- **Pipeline Console 권한** — `users.role = admin` 만 `/api/pipeline/*` 및 `/pipeline/*` UI 접근. `user_resource_access`에 `pipeline_source` kind **사용하지 않음**. General agent용 project 목록·binding 미리보기는 agents-runtime **`GET /api/me/knowledge-projects*`** (tenant read-only, role 무관).
- **Pipeline credential** — refresh token 등 비밀값은 **Postgres 평문 저장 금지**. `path_graph.source_credentials`에 메타·`secret_keys`·`k8s_secret_name`만 두고, 값은 K8s Secret `path-graph-cred-{tenant}-{id}` (agents-runtime `infra_meta` reconciler 패턴). 로컬 dev는 backend `PIPELINE_CREDENTIAL_LOCAL_DIR` 파일 fallback.
- **Source ↔ credential** — `path_graph.sources.credential_id` FK. source마다 다른 OAuth 계정. OAuth 앱(client id/secret)은 backend `PIPELINE_*_CLIENT_*` env.
- **Pipeline Pod** — `users` 테이블 미사용. WF 파라미터 `tenant` + ServiceAccount만.

### Admin Console · 분리 경계 (MVP)

- **도메인** — `path_graph.admin.{projects,sources,runner}` (path-graph 패키지). agents-runtime을 import 하지 않음.
- **BFF** — agents-runtime `backend/routers/pipeline.py` + `pipeline_argo.py` (HTTP·CSRF·Argo submit만).
- **UI** — agents-runtime `frontend/src/pipeline/` 디렉터리만. Agent/VFS 페이지에 pipeline 코드 삽입 금지.
- **기능 플래그** — `PIPELINE_CONSOLE_ENABLED=false` 시 `/api/pipeline/*` router 미등록.
- **BFF 감사** — admin actor mutation은 agents-runtime `public.audit_log` (`pipeline.*` action, `domain=pipeline`). WF 내부 단계는 `path_graph.purge_audit_log` — [agents-runtime `backend/DESIGN.md`](../agents-runtime/backend/DESIGN.md) Pipeline admin §감사.

### Admin Console · Manual raw upload

- **`manual` SourceDriver** — OAuth 없음. 운영자가 UI에서 파일을 `raw/{tenant}/{project_id}/{source_id}/{content_hash}/{filename}`에 적재. 원격 `collect_source`/`Run now` 대신 **upload + ingest** API 사용.
- **업로드 멱등** — 동일 `(tenant, source_id, content_hash)` raw 키가 이미 있으면 **overwrite 금지**(skip). PG `documents`는 신규 적재 시에만 `ingest_state=pending` upsert.
- **Ingest** — `ingest_state=pending` 문서만 mini-batch manifest → Argo `pipeline-ingest-rag`. **재 ingest·수정** 시 `compensate_document_index` 선행(구 chunk Qdrant/Nebula 삭제).
- **Lifecycle** — 정보삭제(`purge`)·temp삭제(`artifact_cleanup`)·IndexReconcile 분리. 도메인: `path_graph.lifecycle`, Admin: `path_graph.admin.lifecycle`. 상세: [`pipeline/DESIGN.md`](pipeline/DESIGN.md) §Lifecycle.
- **BFF** (admin + CSRF): `GET/POST /api/pipeline/projects`, `POST /api/pipeline/sources/{id}/upload` (multipart), `GET .../documents`, `POST .../ingest`. Source·upload는 `project_id` 필수. `driver=manual`만 upload/ingest 허용.

### Admin Console · Downstream (GraphRAG)

RAG ingest 이후 Graph(Nebula)·Wiki(S3) 적재. Console MVP는 **`pipeline-graphrag` 단일** WF.

| 항목 | 규칙 |
|------|------|
| **선행 조건** | manifest 문서 `ingest_state` ∈ `indexed_rag` (최초) · `indexed_graph` (재빌드) |
| **입력** | `tenant`, `project_id`, `project_slug`, `batch_id` — ingest와 **동일 batch_id** |
| **chunks_key** | submit 전 `chunks/{tenant}/{project_id}/{batch_id}/chunks.jsonl`로 manifest 문서 chunks **집계** |
| **API** | `POST /api/pipeline/projects/{project_id}/graphrag` → **202** `{batch_id, chunks_key, workflow_name, …}` |
| **멱등** | pipeline step Upsert/Merge. **동시 실행만 금지** — 동일 batch graphrag WF **Running/Pending/submitted** 시 **409**. Succeeded/Failed 후 **재빌드 허용** (run row 신규) |
| **도메인** | `path_graph.admin.downstream` — agents-runtime import 금지 |

### Knowledge Project · Agent Binding

- **`project`** = 사용자가 정의한 관련 정보 집합. 수집(`source` → `document` → `chunk`)과 산출물(RAG·graph·wiki)이 **동일 `project_id`** 안에 닫힌다.
- **`source`는 project 직속** — `path_graph.sources.project_id` FK. ingest 시 `documents`·`chunks`에 `project_id` 복사(denormalize).
- **에이전트 생성** — runtime은 `tenant` + `path_graph_project_id`만 받고, 나머지 백엔드는 **Knowledge Binding** 규약으로 resolve (`contracts/project.py` `resolve_knowledge_binding`).

| 채널 | MVP (Silo) | 소비 주체 |
|------|------------|-----------|
| **RAG** | Qdrant `path_graph_{tenant_slug}_{project_slug}` + payload `project_id` | retrieval tool |
| **Graph** | Nebula Space — Qdrant collection과 **동일 이름** | multi-hop 탐색 |
| **Wiki** | S3 `wiki/{tenant}/{project_id}/` (+ VFS mount `/wiki`) | 컴파일드 지식 |

```json
{
  "tenant": "acme",
  "project_id": "550e8400-e29b-41d4-a716-446655440000",
  "project_slug": "product-docs",
  "rag": {
    "qdrant_collection": "path_graph_acme_product-docs",
    "filter": { "project_id": "550e8400-..." }
  },
  "graph": { "nebula_space": "path_graph_acme_product-docs" },
  "wiki": { "s3_prefix": "wiki/acme/550e8400-.../", "vfs_mount": "/wiki/{project_slug}/" }
}
```

- **path-graph** — pipeline이 위 규약 경로에만 쓴다. `ProjectStore.resolve_binding(tenant, project_id)` 헬퍼 제공.
- **agents-runtime** — 에이전트 리소스에 `path_graph_project_id` 저장 → invoke/retrieval/VFS mount 시 binding resolve (ROADMAP 3.2.1).
- **확장 (Pool)** — tenant당 Qdrant collection 1개 + payload `project_id` 필터. binding API는 동일; `qdrant_collection`만 `path_graph_{tenant_slug}`로 바뀐다.

### 테넌트 격리

- **`tenant`는 모든 가변 데이터의 1차 파티션 키**다. S3 prefix, PG 행, Qdrant collection/payload, Nebula Space, Argo workflow parameter 어디에든 누락되면 안 된다.
- **PostgreSQL** (`path_graph` schema, runtime DB): 모든 테이블에 `tenant TEXT NOT NULL`. PK는 `(tenant, id)` 복합. 애플리케이션은 `tenant` 없는 쿼리를 발행하지 않는다. Phase 1부터 **RLS** (`tenant = current_setting('app.tenant')`) 적용.
- **Qdrant** (path-graph infra): **project당 collection 1개 (Silo MVP)** — `path_graph_{tenant_slug}_{project_slug}`. point payload에 `tenant`, `project_id` 필수. 검색은 에이전트 binding의 collection 1개 + `filter.project_id`. (과거 `stable_hash(chunk_id) % n` 샤딩 **폐기**.)
- **NebulaGraph** (path-graph infra): **project당 Space 1개** — Qdrant collection과 동일 이름. 엣지 탐색은 Space 경계 밖으로 나가지 않는다.
- **Garage S3**: `raw|parsed|chunks|wiki/{tenant}/...` — [`§2.1`](#21-s3-garage) 유지.
- 파이프라인 Pod·agent invoke payload에 **`tenant` 필수**. 누락 시 step 실패(exit 1), 기본값 추론 금지.

### 식별자·멱등성

- **문서 단위**: `document_id = UUIDv5(namespace, f"{tenant}:{project_id}:{content_hash}")`. `content_hash`는 raw 바이트 SHA-256.
- **청크 단위**: `chunk_id = UUIDv5(namespace, f"{tenant}:{document_id}:{chunk_index}:{chunk_text_hash}")`.
- **모든 ingest·index step은 멱등**이어야 한다. 동일 `(tenant, content_hash)` 또는 `(tenant, chunk_id)` 재실행 시 **Upsert/Merge**만 허용. Append-only 중복 insert 금지.
- **S3 raw**는 content_hash prefix로 **overwrite 금지** (이미 존재하면 skip 또는 동일 해시 검증 후 no-op).

### 다중 저장소 쓰기·장애 복구

쓰기 순서(권장):

1. Garage (raw → parsed → chunks) — artifact source of truth
2. runtime PG `path_graph.*` — 메타·상태
3. Qdrant — vector point (`id` = `chunk_id` 문자열)
4. Nebula — graph upsert (Graph/Wiki downstream만)

- **부분 실패 시**: `path_graph.pipeline_runs` / `path_graph.document_ingest_state`에 `pending|indexed_rag|indexed_graph|failed|dead_letter` 기록. 재시도는 **마지막 성공 단계부터** 재개.
- **Overwrite 규칙**: 재시도 시 PG·Qdrant·Nebula는 동일 `chunk_id`로 upsert. Qdrant point id = `chunk_id`. Nebula vertex id = 계약된 deterministic id. 이전 실패 run의 고아 point는 **동일 id upsert로 자연 치환**.
- **보상(Compensation)**: 재 ingest·문서 수정 시 **선행** `compensate_document_index` → Qdrant `delete(filter document_id)` → Nebula chunk·MENTIONS 삭제 → entity orphan prune → 재적재.
- **정보삭제(Purge)**: `ingest_state=purged` + tombstone `(tenant, project_id, content_hash)`. upload·upsert·manifest 차단.
- **IndexReconcile**: PG `chunks`를 truth로 Qdrant/Nebula 고아 주기 삭제(Cron `pipeline-reconcile-index`).
- **RLS**: `path_graph.*` 전 테이블 `tenant_isolation` POLICY — `set_config('app.tenant')` 필수.

### Agent 호출 (agents-runtime)

- Graph/Wiki step은 **동기 HTTP 홀딩을 기본으로 하지 않는다**. Submit → `job_id`/`session_id` 수신 → **poll 또는 Argo `suspend` + resume**(callback은 Phase 2).
- Poll 간격·최대 대기는 [`pipeline/DESIGN.md`](pipeline/DESIGN.md) § Agent invoke. Argo step `activeDeadlineSeconds`는 poll 루프 전체를 포함해 설정.
- **LLM/ agent 동시성**은 WorkflowTemplate **semaphore** + pool별 `parallelism`으로 상한. 기본: tenant당 graph/wiki agent step 동시 2, cluster 전체 8 (overlay에서 조정).

### 대량 ingest·Argo 오버헤드

- **문서 1건 = Workflow 1개** 금지(소량 수동 제외). 수집기는 **mini-batch**(기본 100건)로 `batch_manifest.jsonl` 생성 후 **단일 Workflow + `withParam`/`parallelism`** 으로 map 처리.
- Cron·이벤트 트리거는 batch 단위. 단건 API는 개발·재처리용.

### 파싱 격리·Dead-letter

- parse step Pod: **requests** cpu 500m / memory 512Mi, **limits** cpu 2 / memory 2Gi (HWP·PDF). OOM·timeout은 **해당 파일만** `dead_letter/{tenant}/{content_hash}/` + PG `dead_letter` 상태. 배치 나머지는 `on-error: continue`.
- 손상 파일·미지원 포맷은 전체 workflow 실패로 승격하지 않는다.

### 이것만은 하지 말 것

- Qdrant/Nebula **설치 매니페스트**를 `deploy/k8s/infra/` 밖(예: pipeline 패키지)에 두지 말 것.
- `tenant` 생략·빈 문자열·`default` 폴백으로 쓰기하지 말 것.
- agents-runtime에 RAG/파이프라인 로직을 넣지 말 것 — invoke만 사용.
- **LLM·Embedding 모델을 path-graph 패키지/이미지에 내장하지 말 것** — 외부 HTTP 서빙만 (`EMBEDDING_*`, `OCR_LLM_*`, Envoy agent). 교체는 env/Secret만 바꾼다 ([pipeline/DESIGN.md](pipeline/DESIGN.md#외부-llmembedding-d4)).

### 수집 주기·동기화 (Admin Console)

- **`schedule_cron`**: Console UI에서 source별 cron 입력 → BFF가 CronWorkflow 생성(기존).
- **`sync_mode`**: source `config` — `delta`(기본) | `full`. Scheduled run은 **delta**; Console 「Run now」에서 **full** 전체 재수집 override 가능.
- SharePoint **delta**: `config.delta_link` 커서 — collect 후 BFF가 source config에 persist.

---

## 2. 컴포넌트 간 형태

### 2.1 S3 (Garage)

```
s3://{bucket}/
  raw/{tenant}/{project_id}/{source_id}/{content_hash}/{filename}
  parsed/{tenant}/{doc_id}/content.md | content.json
  parsed/{tenant}/{doc_id}/meta.json
  chunks/{tenant}/{doc_id}/chunks.jsonl
  chunks/{tenant}/{project_id}/{batch_id}/chunks.jsonl   # GraphRAG project별 배치 청크
  dead_letter/{tenant}/{content_hash}/error.json
  jobs/{tenant}/{job_id}/manifest.json
  batches/{tenant}/{batch_id}/manifest.jsonl
  communities/{tenant}/{project_id}/{batch_id}/communities.jsonl
  graph_context/{tenant}/{project_id}/{batch_id}/{community_id}.json
  wiki/{tenant}/{project_id}/{page_slug}.md
```

**`content.json` (blocks, 청킹 정본)** — PDF/DOCX(markitdown·VL OCR)와 HWP(rhwp-batch) 공통:

| 필드 | 필수 | 설명 |
|------|------|------|
| `schema_version` | ✓ | `"1"` |
| `extractor` | ✓ | 구현 식별자 — 예: `md_heuristic`, `rhwp_batch` |
| `blocks` | ✓ | 배열; block마다 `type`, `heading_path`, 본문(`text` \| `markdown` \| `rows`) |

**blocks 추출기**: ingest는 `BLOCKS_EXTRACTOR=md_heuristic`(기본·정본). md 생성(markitdown/VL OCR)과 blocks 추출은 분리. 상세: [`pipeline/DESIGN.md`](pipeline/DESIGN.md#blocks-구조화-d3).

### 2.2 runtime PostgreSQL (`path_graph` schema)

| 테이블 | 용도 |
|---|---|
| `projects` | Knowledge Bundle — `(tenant, id UUID)`, `slug`, `name`. tenant당 `slug` unique |
| `documents` | `(tenant, id)`, `project_id`, `content_hash`, S3 URI, `ingest_state` |
| `sources` | Admin Console 수집 출처 — `(tenant, id)`, **`project_id` FK**, `driver`, `config`, `credential_id`, `last_*` run 메타 |
| `source_credentials` | OAuth 연동 메타 — `label`, `driver`, `secret_keys`, `k8s_secret_name`, `oauth_status` |
| `chunks` | `(tenant, id)`, `project_id`, `document_id`, `chunk_index`, text, `qdrant_point_id` |
| `pipeline_runs` | Argo uid, tenant, batch_id, status |
| `document_ingest_state` | per-store 커서: `rag_at`, `graph_at`, `wiki_at`, `error` |
| `communities` | `(tenant, project_id, id)`, `batch_id`, `level`, `title`, `s3_uri` |
| `wiki_pages` | `(tenant, project_id, slug)`, `community_id`, `batch_id`, `s3_uri` |
| `document_tombstones` | `(tenant, project_id, content_hash)` PK — 재ingest 차단 |
| `purge_audit_log` | purge·compensation 단계별 감사 |
| `reconcile_reports` | IndexReconcile 결과 |
| `stale_communities` | document purge 후 wiki/graph 재생성 큐 |

RLS: `tenant` = session `app.tenant`. 마이그레이션: `path_graph.migrations` → agents-runtime `db-migrate` Job.

**`documents.ingest_state` 전이** (구현: `meta/pg.py`):

| 상태 | 의미 | 기록 주체 |
|------|------|-----------|
| `pending` | raw·parsed 적재 전/중 | `upsert_document` 기본값 |
| `indexed_rag` | Qdrant upsert 완료 | `mark_rag_indexed` |
| `indexed_graph` | GraphRAG(graph+wiki) 완료 | `mark_graphrag_indexed` — graphrag WF step + BFF reconciler |
| `failed` | 재시도 가능 실패 | (미구현) |
| `dead_letter` | parse 등 복구 불가 격리 | `record_dead_letter` |
| `purging` | purge WF 실행 중 | `purge_document` |
| `purged` | tombstone·인덱스 제거 완료 | `purge_document` |
| `purge_failed` | compensation 일부 실패 | reconcile·재시도 |

**`document_ingest_state` 커서**: `rag_at`, `graph_at`, `wiki_at`, `error` — RAG는 ingest step, graph/wiki는 graphrag WF 성공 시 `mark_graphrag_indexed` (pipeline step + BFF reconciler, 멱등).

### 2.3 Qdrant (path-graph infra)

- Collection: `path_graph_{tenant_slug}_{project_slug}` — project당 1개 (Silo MVP). `ids.qdrant_collection_name(tenant, project_slug)`
- Point `id`: `chunk_id` (UUID string)
- Payload: `tenant`, **`project_id`**, `document_id`, `chunk_id`, `chunk_index`, `heading_path`, `s3_chunk_uri` — **본문 텍스트 없음**
- Vector: dim **1024**, distance **cosine** — embedding은 **cluster 외부** OpenAI-compatible HTTP (`EMBEDDING_BASE_URL` + `/v1/embeddings`, `EMBEDDING_MODEL`, `EMBEDDING_DIM`). path-graph는 TEI 등 구현체를 소유하지 않는다 (D4).
- URL/인증: K8s Secret 또는 dev 기본값 → pipeline env `QDRANT_URL`, `QDRANT_API_KEY` ([`deploy/SETUP.md`](deploy/SETUP.md#qdrant--nebulagraph))
- **Pool 전환 시** (ROADMAP): tenant당 collection 1 + `project_id` payload index. binding의 `filter.project_id`는 **항상** 유지.

### 2.4 NebulaGraph (path-graph infra)

- Space: `path_graph_{tenant_slug}_{project_slug}` — Qdrant collection과 동일 (`ids.nebula_space_name`)
- Vertex id: deterministic (`entity:{uuid}`, `chunk:{chunk_id}`)
- Edge: `EXTRACTED`, `INFERRED`, `MENTIONS` — 양끝 vertex 동일 Space

### 2.5 Agent invoke (요약)

**Async job (기본)** — pool HTTP 홀딩 없음:

```json
POST {ENVOY}/v1/agents/jobs
{
  "agent": "graph-extractor | wiki-synthesizer",
  "input": { … },
  "session_id": "…",
  "callback": {
    "argo": {
      "namespace": "path-graph",
      "workflow": "{workflow.name}",
      "node_field_selector": "inputs.parameters.job-id.value={job_id}"
    }
  }
}
→ { "job_id", "status": "pending", "session_id" }

GET {ENVOY}/v1/agents/jobs/{job_id}?agent={agent}
→ { "job_id", "status": "pending|running|succeeded|failed", "output"?, "error"? }
```

성공 시 `output`은 동기 invoke와 동일 envelope. pipeline은 `jobs/{tenant}/{job_id}/manifest.json`(S3)에도 결과를 기록할 수 있다.

**Graph Extractor input**: `{ "tenant", "project_id", "batch_id", "chunks_s3" }`  
**Wiki Synthesizer input**: `{ "tenant", "project_id", "project_slug", "community_id", "community_level", "graph_context_s3" }`

정본 스키마: `pipeline/src/path_graph/contracts/schemas.py`, Knowledge Binding: `contracts/project.py`.

비동기·poll·Argo suspend 상세: [`pipeline/DESIGN.md`](pipeline/DESIGN.md).

### 2.6 공통 JSON 스키마

정본: `pipeline/src/path_graph/contracts/schemas.py`.

**`BatchManifestLine`** — `batches/{tenant}/{batch_id}/manifest.jsonl` 한 줄:

| 필드 | 타입 | 필수 |
|------|------|------|
| `tenant` | string | ✓ |
| `project_id` | string (UUID) | ✓ |
| `source_id` | string | ✓ |
| `content_hash` | string (SHA-256 hex) | ✓ |
| `s3_raw_uri` | string | ✓ |
| `filename` | string | ✓ |
| `mime` | string | 선택 |

수집기가 `document_id` 등을 함께 쓸 수 있으나 ingest step 계약 필드는 위 7개.

**`BatchManifestMeta`** — `batches/{tenant}/{batch_id}/manifest.meta.json`:

| 필드 | 타입 | 필수 |
|------|------|------|
| `max_parallel` | int (1–100) | 선택 — ingest map 동시성; 미설정 시 WF 기본 10 |

**`ChunkRecord`** — `chunks.jsonl` 한 줄: `chunk_id`, `document_id`, `tenant`, **`project_id`**, `chunk_index`, `text`, `text_hash`, `heading_path`, `source_block_type?`.

Agent I/O: §2.5 및 `GraphExtractorInput`, `WikiSynthesizerInput`.

---

## 3. 의존 저장소

| 저장소 | path-graph가 쓰는 것 |
|---|---|
| [agents-runtime](../agents-runtime) | Garage, runtime PG, `POST /v1/agents/invoke` |
| path-graph [`deploy/k8s/`](deploy/k8s/) | Argo Workflows controller, Qdrant, NebulaGraph (설치·운영) |
| [rhwp_batch](../rhwp_batch) | HWP/HWPX `to-json` 컨테이너 이미지 |

**로컬 개발 연결**: [`scripts/wire-dev.sh`](scripts/wire-dev.sh) — PG `:5432`, Envoy `:8084`, Qdrant `:6333`, Nebula `:9669`, Garage `:3900`(profile s3). 포트 맵: [`scripts/wire-dev.env.example`](scripts/wire-dev.env.example). TEI(선택): `llm-serving/bge-m3-tei` → `:8085`. **Garage 브라우저 UI**(k8s dev): Filestash → [`deploy/SETUP.md`](deploy/SETUP.md#filestash-garage-s3-ui).
