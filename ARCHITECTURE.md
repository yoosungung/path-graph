# ARCHITECTURE.md

path-graph 지식 파이프라인(RAG / Graph / Wiki)의 **컴포넌트 간 계약**. 내부 구현은 [`pipeline/DESIGN.md`](pipeline/DESIGN.md), K8s 배포는 [`deploy/DESIGN.md`](deploy/DESIGN.md).

인프라 소유: **Garage·runtime PG** → agents-runtime, **Qdrant·Nebula** → test_infra (path-graph는 소비만).

### 설계 원칙 (요약)

- **`tenant`** — 보안·격리의 1차 파티션 키. 생략·추론 금지.
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
- **Pipeline Console 권한** — `users.role = admin` 만 `/api/pipeline/*` 및 `/pipeline/*` UI 접근. `user_resource_access`에 `pipeline_source` kind **사용하지 않음**.
- **Pipeline credential** — refresh token 등 비밀값은 **Postgres 평문 저장 금지**. `path_graph.source_credentials`에 메타·`secret_keys`·`k8s_secret_name`만 두고, 값은 K8s Secret `path-graph-cred-{tenant}-{id}` (agents-runtime `infra_meta` reconciler 패턴). 로컬 dev는 backend `PIPELINE_CREDENTIAL_LOCAL_DIR` 파일 fallback.
- **Source ↔ credential** — `path_graph.sources.credential_id` FK. source마다 다른 OAuth 계정. OAuth 앱(client id/secret)은 backend `PIPELINE_*_CLIENT_*` env.
- **Pipeline Pod** — `users` 테이블 미사용. WF 파라미터 `tenant` + ServiceAccount만.

### Admin Console · 분리 경계 (MVP)

- **도메인** — `path_graph.admin.{sources,runner}` (path-graph 패키지). agents-runtime을 import 하지 않음.
- **BFF** — agents-runtime `backend/routers/pipeline.py` + `pipeline_argo.py` (HTTP·CSRF·Argo submit만).
- **UI** — agents-runtime `frontend/src/pipeline/` 디렉터리만. Agent/VFS 페이지에 pipeline 코드 삽입 금지.
- **기능 플래그** — `PIPELINE_CONSOLE_ENABLED=false` 시 `/api/pipeline/*` router 미등록.

### 테넌트 격리

- **`tenant`는 모든 가변 데이터의 1차 파티션 키**다. S3 prefix, PG 행, Qdrant collection/payload, Nebula Space, Argo workflow parameter 어디에든 누락되면 안 된다.
- **PostgreSQL** (`path_graph` schema, runtime DB): 모든 테이블에 `tenant TEXT NOT NULL`. PK는 `(tenant, id)` 복합. 애플리케이션은 `tenant` 없는 쿼리를 발행하지 않는다. Phase 1부터 **RLS** (`tenant = current_setting('app.tenant')`) 적용.
- **Qdrant** (test_infra): **테넌트당 collection n개** — `path_graph_{tenant}_{project}` (project ∈ [0, n), n=`PATH_GRAPH_PROJECTS_PER_TENANT` 기본 4). point는 `chunk_id` 해시로 project 결정. 타 테넌트 collection에 쓰기/검색 금지.
- **NebulaGraph** (test_infra): **테넌트당 Space n개** — `path_graph_{tenant}_{project}` (동일 project 라우팅). 엣지 탐색은 Space 경계 밖으로 나가지 않는다. 단일 Space + 필터 방식은 채택하지 않는다.
- **Garage S3**: `raw|parsed|chunks|wiki/{tenant}/...` — [`§2.1`](#21-s3-garage) 유지.
- 파이프라인 Pod·agent invoke payload에 **`tenant` 필수**. 누락 시 step 실패(exit 1), 기본값 추론 금지.

### 식별자·멱등성

- **문서 단위**: `document_id = UUIDv5(namespace, f"{tenant}:{content_hash}")`. `content_hash`는 raw 바이트 SHA-256.
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
- **보상(Compensation)**: 특정 `document_id` 전체 재처리 시 PG soft-delete 플래그 → Qdrant `delete(filter document_id)` → Nebula 해당 document 서브그래프 삭제 후 재적재. 부분 보상은 chunk_id 단위 upsert로 우선 처리.

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

- test_infra에 Qdrant/Nebula **설치 매니페스트**를 path-graph에 두지 말 것.
- `tenant` 생략·빈 문자열·`default` 폴백으로 쓰기하지 말 것.
- agents-runtime에 RAG/파이프라인 로직을 넣지 말 것 — invoke만 사용.

---

## 2. 컴포넌트 간 형태

### 2.1 S3 (Garage)

```
s3://{bucket}/
  raw/{tenant}/{source_id}/{content_hash}/{filename}
  parsed/{tenant}/{doc_id}/content.md | content.json
  parsed/{tenant}/{doc_id}/meta.json
  chunks/{tenant}/{doc_id}/chunks.jsonl
  chunks/{tenant}/{project}/{batch_id}/chunks.jsonl   # GraphRAG project별 배치 청크
  dead_letter/{tenant}/{content_hash}/error.json
  jobs/{tenant}/{job_id}/manifest.json
  communities/{tenant}/{project}/{batch_id}/communities.jsonl
  graph_context/{tenant}/{project}/{batch_id}/{community_id}.json
  wiki/{tenant}/{project}/{page_slug}.md
```

### 2.2 runtime PostgreSQL (`path_graph` schema)

| 테이블 | 용도 |
|---|---|
| `documents` | `(tenant, id)`, `content_hash`, S3 URI, `ingest_state` |
| `sources` | Admin Console 수집 출처 — `(tenant, id)`, `driver`, `config`, `credential_id`, `last_*` run 메타 |
| `source_credentials` | OAuth 연동 메타 — `label`, `driver`, `secret_keys`, `k8s_secret_name`, `oauth_status` |
| `chunks` | `(tenant, id)`, `document_id`, `chunk_index`, text, `qdrant_point_id` |
| `pipeline_runs` | Argo uid, tenant, batch_id, status |
| `document_ingest_state` | per-store 커서: `rag_at`, `graph_at`, `wiki_at`, `error` |
| `communities` | `(tenant, project, id)`, `batch_id`, `level`, `title`, `s3_uri` |
| `wiki_pages` | `(tenant, project, slug)`, `community_id`, `batch_id`, `s3_uri` |

RLS: `tenant` = session `app.tenant`. 마이그레이션: `path_graph.migrations` → agents-runtime `db-migrate` Job.

**`documents.ingest_state` 전이** (구현: `meta/pg.py`):

| 상태 | 의미 | 기록 주체 |
|------|------|-----------|
| `pending` | raw·parsed 적재 전/중 | `upsert_document` 기본값 |
| `indexed_rag` | Qdrant upsert 완료 | `mark_rag_indexed` |
| `indexed_graph` | Nebula graph 단계 완료 | (예정 — ROADMAP 1.1.9) |
| `failed` | 재시도 가능 실패 | (예정) |
| `dead_letter` | parse 등 복구 불가 격리 | `record_dead_letter` |

**`document_ingest_state` 커서**: `rag_at`, `graph_at`, `wiki_at`, `error` — 저장소별 마지막 성공 시각·오류. 현재는 **RAG·DLQ만 write** (ROADMAP 1.1.9).

### 2.3 Qdrant (test_infra, 소비만)

- Collection: `path_graph_{tenant}_{project}` — tenant 슬러그 정규화, project = `stable_hash(chunk_id) % n`
- n: env `PATH_GRAPH_PROJECTS_PER_TENANT` (기본 4). Qdrant·Nebula 공통. 검색 시 해당 tenant의 n개 collection 모두 조회
- Point `id`: `chunk_id` (UUID string)
- Payload: `tenant`, `document_id`, `chunk_id`, `chunk_index`, `heading_path`, `s3_chunk_uri` — **본문 텍스트 없음**
- Vector: dim **1024**, distance **cosine** — embedding은 cluster 외부 TEI `BAAI/bge-m3` (`EMBEDDING_BASE_URL` + `/v1/embeddings`)
- URL/인증: test_infra Secret → pipeline env `QDRANT_URL`, `QDRANT_API_KEY`

### 2.4 NebulaGraph (test_infra, 소비만)

- Space: `path_graph_{tenant}_{project}` — Qdrant와 동일 project 라우팅
- Vertex id: deterministic (`entity:{uuid}`, `chunk:{chunk_id}`)
- Edge: `EXTRACTED`, `INFERRED`, `MENTIONS` — 양끝 vertex 동일 Space

### 2.5 Agent invoke (요약)

- **Graph Extractor**:
  ```json
  POST {ENVOY}/v1/agents/invoke
  { "agent": "graph-extractor", "input": { "tenant", "project", "batch_id", "chunks_s3" }, "session_id" }
  ```
- **Wiki Synthesizer (GraphRAG Community 기반)**:
  ```json
  POST {ENVOY}/v1/agents/invoke
  { "agent": "wiki-synthesizer", "input": { "tenant", "project", "community_id", "community_level", "graph_context_s3" }, "session_id" }
  ```

비동기·poll·semaphore 상세: [`pipeline/DESIGN.md`](pipeline/DESIGN.md).

### 2.6 공통 JSON 스키마

정본: `pipeline/src/path_graph/contracts/schemas.py`.

**`BatchManifestLine`** — `batches/{tenant}/{batch_id}/manifest.jsonl` 한 줄:

| 필드 | 타입 | 필수 |
|------|------|------|
| `tenant` | string | ✓ |
| `source_id` | string | ✓ |
| `content_hash` | string (SHA-256 hex) | ✓ |
| `s3_raw_uri` | string | ✓ |
| `filename` | string | ✓ |
| `mime` | string | 선택 |

수집기가 `document_id` 등을 함께 쓸 수 있으나 ingest step 계약 필드는 위 6개.

**`ChunkRecord`** — `chunks.jsonl` 한 줄: `chunk_id`, `document_id`, `tenant`, `chunk_index`, `text`, `text_hash`, `heading_path`, `source_block_type?`.

Agent I/O: §2.5 및 `GraphExtractorInput`, `WikiSynthesizerInput`.

---

## 3. 의존 저장소

| 저장소 | path-graph가 쓰는 것 |
|---|---|
| [agents-runtime](../agents-runtime) | Garage, runtime PG, `POST /v1/agents/invoke` |
| [test_infra](../test_infra) | Qdrant, NebulaGraph (설치·운영) |
| [rhwp_batch](../rhwp_batch) | HWP/HWPX `to-json` 컨테이너 이미지 |

**로컬 개발 연결**: [`scripts/wire-dev.sh`](scripts/wire-dev.sh) — PG `:5432`, Envoy `:8084`, Qdrant `:6333`, Nebula `:9669`, Garage `:3900`(profile s3). 포트 맵: [`scripts/wire-dev.env.example`](scripts/wire-dev.env.example). TEI(선택): `llm-serving/bge-m3-tei` → `:8085`.
