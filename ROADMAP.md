# ROADMAP.md

[ARCHITECTURE.md](ARCHITECTURE.md) 계약을 **어떤 순서로**, **어디까지** 구현할지 적는다. 불변 규칙·스키마 형태는 ARCHITECTURE / DESIGN에 두고, 여기서는 **진행 상태·갭·다음 작업**만 관리한다.

**상태 표기**: `[x]` 완료 · `[~]` 부분(코드만 / 미배포 / 미검증) · `[ ]` 미착수

---

## 현황 스냅샷

| 항목 | 상태 |
|---|---|
| pipeline 패키지 | v0.1.0, `make test` **102 tests** (2026-06) |
| 로컬 ingest | CLI로 **web / local file / SharePoint / GDrive / OneDrive** → parse → chunk → (선택) RAG |
| k8s dev 클러스터 | `runtime`·`qdrant`·`nebula` port-forward 가능 (`wire-dev.sh`) |
| Argo Workflows | `argo` NS — `make argo-install` |
| `path-graph` NS / WorkflowTemplate | **applied** — `make bootstrap-k8s` |
| agents | graph-extractor / wiki-synthesizer **스켈레ton** (invoke 연동 테스트는 pipeline mock 위주) |

---

## Phase 1 — MVP (ingest + RAG)

목표: 단일 tenant에서 **수집 → 파싱 → 청킹 → 벡터 인덱스**까지 end-to-end. 개발 경로는 **CLI 우선**, Argo는 템플릿까지.

### 1.1 계약·코어 pipeline

| # | 작업 | 상태 | 비고 |
|---|---|---|---|
| 1.1.1 | ARCHITECTURE §1 계약 문서화 | [x] | |
| 1.1.2 | `tenant` / `document_id` / `chunk_id` 멱등 식별자 | [x] | `ids.py`, 계약 테스트 |
| 1.1.3 | S3 key layout (`raw|parsed|chunks|batches|…`) | [x] | `contracts/s3_keys.py` |
| 1.1.4 | Blob store (local + S3/Garage) | [x] | `PIPELINE_STORAGE_BACKEND` |
| 1.1.5 | parse → chunk → meta 적재 | [x] | markitdown + rhwp-batch |
| 1.1.6 | `CHUNK_MAX_CHARS` (기본 1000) + 긴 문단 hard-split | [x] | embed context 안전 |
| 1.1.7 | dead-letter (parse 실패 격리) | [x] | S3 + PG `dead_letter` |
| 1.1.8 | PG `path_graph.*` 스키마·마이그레이션 | [x] | lifecycle 테이블·RLS POLICY 포함 |
| 1.1.9 | `pipeline_runs` / ingest_state **전 단계 기록** | [~] | 테이블 있음; **RAG·DLQ만 write**, graph/wiki 커서·run 미연동 |
| 1.1.10 | RLS 정책 (`tenant = current_setting('app.tenant')`) | [x] | `meta/pg.py` `RLS_POLICY_MIGRATION_SQL` |
| 1.1.11 | document **compensation** (재처리 시 Qdrant/Nebula 삭제) | [x] | `lifecycle/compensation.py` |
| 1.1.12 | **purge** · tombstone · reconcile | [x] | `lifecycle/purge.py`, `reconcile.py`, Argo WF |
| 1.1.13 | SharePoint **delta sync** | [~] | `SharePointClient.list_delta`, `collect_delta` |

### 1.2 RAG

| # | 작업 | 상태 | 비고 |
|---|---|---|---|
| 1.2.1 | TEI OpenAI-compatible embed (`bge-m3`, dim 1024) | [x] | `rag/embed.py` |
| 1.2.2 | Qdrant upsert (project Silo collection) | [x] | `path_graph_{tenant}_{project_slug}` |
| 1.2.3 | PG `chunks` + `document_ingest_state.rag_at` | [x] | |
| 1.2.4 | 로컬 RAG E2E (`ingest_web --rag`) | [~] | `EMBEDDING_BASE_URL` k8s 내부 주소 — 로컬은 port-forward 또는 URL override 필요 |
| 1.2.5 | embed 실패 재시도·배치 (`EMBEDDING_BATCH_SIZE`) | [x] | |

### 1.3 CLI · 개발 UX

| # | 작업 | 상태 | 비고 |
|---|---|---|---|
| 1.3.1 | `ingest_web` (url / file) | [x] | |
| 1.3.2 | `wire-dev.sh` (PG·Qdrant·Nebula·Envoy PF) | [x] | Argo 미포함 |
| 1.3.3 | VS Code launch (ingest, pytest, sharepoint dry-run) | [x] | |
| 1.3.4 | `make install` editable wheel (hatch `only-packages`) | [x] | |

### 1.4 K8s · Argo (MVP 배포)

| # | 작업 | 상태 | 비고 |
|---|---|---|---|
| 1.4.1 | `namespace.yaml` | [x] | |
| 1.4.2 | WorkflowTemplate `pipeline-ingest-rag` | [~] | YAML + SA; **collect step·manifest 입력 형식 미정합** |
| 1.4.3 | ServiceAccount · NetworkPolicy | [x] | `serviceaccount.yaml`, `networkpolicy.yaml` |
| 1.4.4 | ConfigMap `path-graph-limits` (semaphore) | [x] | `configmap-limits.yaml` |
| 1.4.5 | Secret `path-graph-env` / PG·S3 참조 | [x] | `create-path-graph-secrets.sh` |
| 1.4.6 | pipeline **컨테이너 이미지** 빌드·푸시·CI | [x] | GHA `build-images.yml` + dev overlay GHCR |
| 1.4.7 | **Argo Workflows controller** 설치 | [x] | `install-argo.sh` + `deploy/k8s/argo/values.yaml` |
| 1.4.8 | `kubectl apply -k deploy/k8s/base` 검증 | [~] | `workflow-validate` + bootstrap; WF E2E는 2.4.1 |
| 1.4.9 | CronWorkflow / 이벤트 트리거 | [x] | Console `schedule_cron` → `pg-cron-{tenant}-{source}` |
| 1.4.10 | Filestash (Garage S3 dev UI) | [x] | `deploy/k8s/base/filestash*.yaml`, `bootstrap-filestash.sh` |

### 1.5 Agents (MVP 스켈레ton)

| # | 작업 | 상태 | 비고 |
|---|---|---|---|
| 1.5.1 | graph-extractor / wiki-synthesizer 패키지 | [x] | `agents/` |
| 1.5.2 | `POST /v1/agents/invoke` payload 계약 | [x] | ARCHITECTURE §2.5 |
| 1.5.3 | pipeline `agent_invoke.py` (동기 invoke + retry) | [x] | async suspend는 Phase 3 |

---

## Phase 2 — fan-out · 수집기 · Graph/Wiki

목표: **mini-batch manifest** → map ingest → Graph → Wiki. 수집기로 SharePoint 등 자동 유입.

### 2.1 수집기 (collectors)

| # | 작업 | 상태 | 비고 |
|---|---|---|---|
| 2.1.1 | web / local file | [x] | `collectors/web`, `ingest_web` |
| 2.1.2 | SharePoint (Graph: app/delegated/device) | [x] | `ingest_sharepoint` |
| 2.1.3 | Google Drive (OAuth refresh) | [x] | `ingest_gdrive` |
| 2.1.4 | OneDrive (`/me/drive`) | [x] | `ingest_onedrive` |
| 2.1.5 | agent-chat JSON export | [x] | `AgentChatCollector` |
| 2.1.6 | `batches/{tenant}/{batch_id}/manifest.jsonl` writer | [x] | collect CLI가 생성 |
| 2.1.7 | SharePoint **delta sync** / 변경 감지 | [~] | `list_delta` + `collect_delta`; source config `delta_link` |
| 2.1.8 | collect 전용 Argo step (Cron → manifest → submit) | [ ] | |

### 2.2 Graph pipeline

| # | 작업 | 상태 | 비고 |
|---|---|---|---|
| 2.2.1 | wikilink deterministic extract | [x] | `graph_pipeline.py` |
| 2.2.2 | graph-extractor agent invoke | [x] | |
| 2.2.3 | Nebula upsert (project Space) | [x] | `project_id` + `project_slug` |
| 2.2.4 | `copy_chunks_to_project_batch` | [x] | hash 샤드 `partition_chunks_by_project` **폐기** |
| 2.2.5 | WorkflowTemplate `pipeline-graph` | [x] | cluster E2E (`submit-downstream-e2e.sh`, `skip_agent=1`) |

### 2.3 Wiki pipeline

| # | 작업 | 상태 | 비고 |
|---|---|---|---|
| 2.3.1 | wiki-synthesizer invoke | [x] | |
| 2.3.2 | wiki page → S3 + PG | [x] | |
| 2.3.3 | WorkflowTemplate `pipeline-wiki` | [x] | cluster E2E (`submit-downstream-e2e.sh`, `skip_agent=1`) |

### 2.4 배치 오케스트레이션 갭

| # | 작업 | 상태 | 비고 |
|---|---|---|---|
| 2.4.1 | manifest 한 줄 스키마 ↔ ingest step 입력 정합 | [x] | `ingest_manifest.py` + WF `MANIFEST_LINE` |
| 2.4.2 | 단일 Workflow + `withParam` map (batch 100) | [~] | ingest E2E OK (`submit-ingest-rag-e2e.sh`); Argo wait→API NP 잔여 |
| 2.4.3 | tenant별 `parallelism` + semaphore | [~] | ingest-rag WF `parallelism:10`·`podGC`·`ttlStrategy`; tenant `max_parallel`·ConfigMap 연동 잔여 |
| 2.4.4 | parse 실패 `continueOn` 배치 격리 | [x] | ingest-rag WF |

---

## Phase 3 — 하이브리드 GraphRAG 고도화

목표: Community 기반 GraphRAG + 검색 품질·운영성.

### 3.1 Community · GraphRAG

| # | 작업 | 상태 | 비고 |
|---|---|---|---|
| 3.1.1 | Leiden community detection | [x] | `community_detector.py` |
| 3.1.2 | community metadata → S3/PG | [x] | |
| 3.1.3 | graph_context artifact | [x] | |
| 3.1.4 | `graphrag_pipeline` / WF `pipeline-graphrag` | [x] | cluster E2E (`submit-downstream-e2e.sh`, `skip_agent=1`) |
| 3.1.5 | Graph-enhanced Wiki **프롬프트** (MS GraphRAG 템플릿) | [ ] | |

### 3.2 agents-runtime 연동

| # | 작업 | 상태 | 비고 |
|---|---|---|---|
| 3.2.0 | **Agent `path_graph_project_id` + Knowledge Binding resolve** | [~] | path-graph `resolve_knowledge_binding`; runtime 저장·retrieval/VFS는 [ ] |
| 3.2.1 | VFS wiki mount | [ ] | agents-runtime 측 — binding `wiki.s3_prefix` |
| 3.2.2 | async job API + Argo **suspend/resume** | [ ] | Phase 1은 extended sync poll |

### 3.3 검색 · 파싱 고도화

| # | 작업 | 상태 | 비고 |
|---|---|---|---|
| 3.3.1 | **RRF hybrid** (PG BM25 + Qdrant) | [ ] | |
| 3.3.2 | PDF/DOCX → **blocks JSON** (md 후처리 또는 Docling) | [ ] | HWP만 `content.json` |
| 3.3.3 | ingest 검색 API / retrieval CLI | [ ] | |

---

## 권장 실행 순서 (다음 4 sprint)

아래는 **의존성·리스크** 기준 권장 순서. 번호는 ROADMAP # 참조.

1. **운영 기반** — 1.4.7 Argo 설치 → 1.4.3–1.4.5 → 1.4.8 → 1.4.6 이미지
2. **배치 ingest 실동** — 2.4.1 manifest→ingest step → 2.4.2 WF E2E → 2.1.8 SharePoint cron (회사규정)
3. **PG 완성** — 1.1.10 RLS policy → 1.1.9 pipeline_runs 연동 → 1.1.11 compensation
4. **품질** — 3.3.2 blocks JSON (표 많은 PDF) → 3.3.1 RRF → 3.1.5 wiki 프롬프트

---

## 외부 의존 (path-graph가 설치하지 않음)

| 컴포넌트 | 소유 | path-graph 소비 |
|---|---|---|
| Garage, runtime PG, Envoy | agents-runtime | wire-dev / Secret |
| Qdrant, Nebula | path-graph `deploy/k8s/infra/` | `make deploy-qdrant-nebula` |
| Argo Workflows controller | test_infra 또는 별도 Helm | SETUP.md |
| TEI `bge-m3` | llm-serving NS | `EMBEDDING_BASE_URL` |
| rhwp-batch 이미지 | rhwp_batch | HWP parse |

---

## Phase 4 — Admin Console (agents-runtime 통합)

목표: 운영자가 **로그인 한 번**으로 수집·ingest·상태 확인. path-graph repo에는 UI 없음 — agents-runtime `backend` + `frontend` 확장.

### 4.0 계약 (ARCHITECTURE §1 Admin Console · Knowledge Project)

| 항목 | 결정 |
|------|------|
| DB | runtime Postgres 단일 — `public.users` + `path_graph.*` |
| `users.tenant` | NOT NULL (agents-runtime `0009_users_tenant_not_null.sql`) |
| 멀티 tenant | **없음** — 1 user = 1 tenant |
| **Knowledge Project** | `path_graph.projects` — 사용자 정의 정보 집합; source·RAG·graph·wiki·에이전트 binding 스코프 |
| Pipeline UI/API | **`role = admin` 만** — `pipeline_source` ACL 없음 |
| Pipeline Pod | `users` 미사용 (WF `tenant` + `project_id` 파라미터) |

### 4.1 Backend (`/api/pipeline/*`)

| # | 작업 | 상태 | 비고 |
|---|---|---|---|
| 4.1.0 | **`projects` 테이블·CRUD·`resolve_binding`** | [x] | path-graph `admin/projects.py`; BFF `/api/pipeline/projects`는 agents-runtime |
| 4.1.1 | `path_graph.sources` + **`project_id` FK** | [x] | Source 생성 시 project 필수 |
| 4.1.2 | Sources CRUD + 연결 테스트 | [x] | SharePoint/GDrive/OneDrive dry-run (`probe_source`) |
| 4.1.3 | Run now → collect → Argo `pipeline-ingest-rag` | [x] | BFF가 manifest jsonl → JSON 배열 submit (MVP) |
| 4.1.4 | Runs / dead-letter 조회 | [x] | `pipeline_runs`, `documents.ingest_state=dead_letter` |
| 4.1.5 | `require_admin` 가드 전 API | [x] | agents-runtime `UserRole.ADMIN` |
| 4.1.6 | Manual raw upload / ingest / documents API | [x] | `driver=manual`, multipart upload, pending ingest |

### 4.2 Frontend (`/pipeline/*` + `/files/*`)

| # | 작업 | 상태 | 비고 |
|---|---|---|---|
| 4.2.0 | **Project-first IA** | [x] | Nav Pipeline + **파일관리**; `/pipeline/projects/:id/*`; `knowledge/` 공유 context |
| 4.2.1 | Pipeline Sources·Runs·Credentials | [x] | project nested 라우트; flat `/pipeline/sources` 제거 |
| 4.2.2 | OAuth 마법사 (SharePoint/GDrive) | [x] | `source_credentials` + K8s Secret |
| 4.2.3 | Run now + Runs (WF만) | [x] | dead-letter 탭 → 파일관리 |
| 4.2.4 | `<RequireAdmin />` 라우트 가드 | [x] | `RequireRole min="admin"` |
| 4.2.5 | Manual upload + ingest (Pipeline source) | [x] | 상세 문서 테이블 → 파일관리 링크 |
| 4.2.6 | **파일관리** (`frontend/src/files/`) | [x] | documents·lifecycle·purge UI |

### 4.3 오케스트레이션

| # | 작업 | 상태 | 비고 |
|---|---|---|---|
| 4.3.1 | WF `batch_manifest_key` (S3 manifest 경로) | [x] | `load_batch_manifest` step; key 우선, inline은 key 없을 때만 |
| 4.3.2 | `pipeline-collect-ingest-rag` WorkflowTemplate | [x] | BFF Run now 202 + collect→ingest chain |
| 4.3.3 | CronWorkflow per source (Console에서 스케줄) | [x] | BFF reconcile on create/update/delete |
| 4.3.4 | WF `pipeline-purge-document` / `pipeline-reconcile-index` / `pipeline-artifact-cleanup` | [x] | `deploy/k8s/base/workflow-templates/` |

### 4.4 Lifecycle (agents-runtime BFF 연동)

| # | 작업 | 상태 | 비고 |
|---|---|---|---|
| 4.4.1 | path-graph `admin.lifecycle` 도메인 API | [x] | purge/restore/reingest/cleanup/reconcile/tombstones |
| 4.4.2 | BFF `/api/pipeline/documents/{id}/purge` 등 | [x] | agents-runtime `pipeline.py` 래핑 |
| 4.4.3 | UI purge·tombstones·reconcile 리포트 | [x] | `/files/projects/:id/*` |
| 4.4.4 | CronWorkflow `pipeline-reconcile-index` per project | [ ] | 일 1회 |

---

## 미결정

| ID | 주제 | 선택지 / 메모 |
|---|---|---|
| D1 | Argo controller **설치 주체** | test_infra Helm vs path-graph deploy 문서만 |
| D2 | pipeline 이미지 **레지스트리** | **GHCR** — GHA `workflow_dispatch` + release (`make build-images`) |
| D3 | PDF 구조화 | md→blocks 후처리 vs Docling vs Azure DI |
| D4 | 로컬 embed | TEI port-forward vs 로컬 mock vs cluster-only RAG |
| D5 | 회사규정 ingest **주기** | SharePoint cron 주기·delta vs full scan |

---

## 완료 시 갱신 규칙

- Phase 항목 상태 변경 시 이 파일만 수정 (ARCHITECTURE 계약 변경은 ARCHITECTURE 먼저).
- 테스트 수·주요 CLI 변경 시 [AGENTS.md](AGENTS.md) §3 Status 한 줄 동기화.
- 새 컴포넌트 코드 디렉터리 추가 시 [AGENTS.md](AGENTS.md) §1 표 검토.
