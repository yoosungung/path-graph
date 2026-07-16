# ROADMAP.md

[ARCHITECTURE.md](ARCHITECTURE.md) 계약을 **어떤 순서로**, **어디까지** 구현할지 적는다. 불변 규칙·스키마 형태는 ARCHITECTURE / DESIGN에 두고, 여기서는 **진행 상태·갭·다음 작업**만 관리한다.

**상태 표기**: `[x]` 완료 · `[~]` 부분(코드만 / 미배포 / 미검증) · `[ ]` 미착수

---

## 현황 스냅샷

| 항목 | 상태 |
|---|---|
| pipeline 패키지 | v0.1.0, `make test` **218 tests** (2026-07) |
| 로컬 ingest | CLI — web / file / SharePoint / GDrive / OneDrive → parse → **blocks** → chunk → (선택) RAG |
| 파싱·청킹 | native parser → `content.json` `blocks[]` → `chunk_from_blocks` (D3 개정; 구현 parent #260 / #274→#278→#279→#280) |
| k8s dev 클러스터 | `runtime`·`nebula` port-forward (`wire-dev.sh`) |
| Argo Workflows | path-graph 소유 — `argo` NS, `make argo-install` (D1) |
| `path-graph` NS / WorkflowTemplate | **applied** — pipeline 이미지 **git SHA 태그** + `IfNotPresent` (D2) |
| Admin Console (agents-runtime) | ingest·GraphRAG downstream·파일관리·Sources `schedule_cron` |
| 외부 LLM·Embedding | llm-serving TEI·sglang — path-graph는 HTTP 클라이언트만 (D4) |
| 수집 동기화 | SharePoint 기본 **delta** · Run now `--sync-mode=full` (D5); BFF `delta_link` persist (reconciler) |

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
| 1.1.5 | parse → chunk → meta 적재 | [x] | HWP=`rhwp-batch`; 비-HWP는 blocks 경유 (3.3.2→3.3.5 native 전환) |
| 1.1.6 | `CHUNK_MAX_CHARS` (기본 1000) + 긴 문단 hard-split | [x] | embed context 안전 |
| 1.1.7 | dead-letter (parse 실패 격리) | [x] | S3 + PG `dead_letter` |
| 1.1.8 | PG `path_graph.*` 스키마·마이그레이션 | [x] | lifecycle 테이블·RLS POLICY 포함 |
| 1.1.9 | `pipeline_runs` / ingest_state **전 단계 기록** | [x] | RAG·DLQ·graph/wiki: `mark_rag_indexed` / `record_dead_letter` / `mark_graphrag_indexed`; graphrag WF 종료 시 pipeline step + BFF reconciler |
| 1.1.10 | RLS 정책 (`tenant = current_setting('app.tenant')`) | [x] | `meta/pg.py` `RLS_POLICY_MIGRATION_SQL` |
| 1.1.11 | document **compensation** (재처리 시 embedding·Nebula 삭제) | [x] | `lifecycle/compensation.py` |
| 1.1.12 | **purge** · tombstone · reconcile | [x] | `lifecycle/purge.py`, `reconcile.py`, Argo WF |
| 1.1.13 | SharePoint **delta sync** | [x] | `collect_delta` + `collect_source` 기본 delta; BFF reconciler `delta_link` persist · full 시 커서 제거 |

### 1.2 RAG

| # | 작업 | 상태 | 비고 |
|---|---|---|---|
| 1.2.1 | TEI OpenAI-compatible embed (`bge-m3`, dim 1024) | [x] | `rag/embed.py` |
| 1.2.2 | pgvector upsert (`chunks.embedding`) | [x] | runtime PG `path_graph_{tenant}_{project_slug}` scope via `project_id` |
| 1.2.3 | PG `chunks` + `document_ingest_state.rag_at` | [x] | |
| 1.2.4 | 로컬 RAG E2E (`ingest_web --rag`) | [~] | `wire-dev` TEI :8085 PF + `make e2e-local-rag`; 클러스터 TEI·PG 검증 잔여 |
| 1.2.5 | embed 실패 재시도·배치 (`EMBEDDING_BATCH_SIZE`) | [x] | |

### 1.3 CLI · 개발 UX

| # | 작업 | 상태 | 비고 |
|---|---|---|---|
| 1.3.1 | `ingest_web` (url / file) | [x] | |
| 1.3.2 | `wire-dev.sh` (PG·Nebula·Envoy PF) | [x] | Argo 미포함 |
| 1.3.3 | VS Code launch (ingest, pytest, sharepoint dry-run) | [x] | |
| 1.3.4 | `make install` editable wheel (hatch `only-packages`) | [x] | |

### 1.4 K8s · Argo (MVP 배포)

| # | 작업 | 상태 | 비고 |
|---|---|---|---|
| 1.4.1 | `namespace.yaml` | [x] | |
| 1.4.2 | WorkflowTemplate `pipeline-ingest-rag` | [x] | `resolve-manifest` + `batch_manifest_key` 우선; E2E `submit-ingest-rag-e2e.sh` |
| 1.4.3 | ServiceAccount · NetworkPolicy | [x] | `serviceaccount.yaml`, `networkpolicy.yaml` |
| 1.4.4 | ConfigMap `path-graph-limits` (semaphore) | [x] | `configmap-limits.yaml` |
| 1.4.5 | Secret `path-graph-env` / PG·S3 참조 | [x] | `create-path-graph-secrets.sh` |
| 1.4.6 | pipeline **컨테이너 이미지** 빌드·푸시·CI | [x] | GHA `build-images` → GHCR `:<git-sha>`; `make k8s-apply-dev` pin (D2) |
| 1.4.7 | **Argo Workflows controller** 설치 | [x] | `install-argo.sh` + `deploy/k8s/argo/values.yaml` |
| 1.4.8 | `kubectl apply -k deploy/k8s/base` 검증 | [x] | `make bootstrap-k8s` + ingest/downstream E2E scripts |
| 1.4.9 | CronWorkflow / 이벤트 트리거 | [x] | Console `schedule_cron` → `pg-cron-{tenant}-{source}` |
| 1.4.10 | Filestash (Garage S3 dev UI) | [x] | `deploy/k8s/base/filestash*.yaml`, `bootstrap-filestash.sh` |
| 1.4.11 | **Python wheel** → GitHub Release | [x] | GHA `publish-package.yml`; `make build-wheel`; release tag ↔ `pyproject.toml` version |
| 1.4.12 | **`path_graph.console` 공개 API** | [x] | 외부 소비자 stable facade; `admin`은 내부·Argo 전용 |

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
| 2.1.7 | SharePoint **delta sync** / 변경 감지 | [~] | pipeline + BFF persist [x]; Cron delta E2E — **관리자 일괄 검증으로 연기** (아래 §관리자 클러스터 검증) |
| 2.1.8 | collect 전용 Argo step (Cron → manifest → submit) | [x] | `pipeline-collect` WF · `submit_collect_only` |

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
| 2.4.2 | 단일 Workflow + `withParam` map (batch 100) | [x] | ingest E2E OK; pipeline NP egress K8s API·argo |
| 2.4.3 | tenant별 `parallelism` + semaphore | [x] | `manifest.meta.json` `max_parallel` · WF param · `ingest-map` semaphore |
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
| 3.1.5 | Graph-enhanced Wiki **프롬프트** (MS GraphRAG 템플릿) | [x] | `community_report.txt` |
| 3.1.6 | graph-extractor / wiki-synthesizer **LangGraph** 본구현 | [x] | `StateGraph` load→LLM JSON schema; artifact는 presigned HTTP(`agent_artifact_uri`) — agent pool S3 credential 불필요 |
| 3.1.7 | community export **semantic batch 스코핑** | [x] | `batch_entity_ids` from graph-extractor; MENTIONS-only scoping 폐기 (PDF/HWP GraphRAG) |

### 3.2 agents-runtime 연동

| # | 작업 | 상태 | 비고 |
|---|---|---|---|
| 3.2.0 | **Agent `knowledge_project_ids[]` + Knowledge Binding resolve** | [x] | runtime `config.general` 저장 · invoke마다 `api_get_binding` · MCP args scope · multi-project `search` RRF |
| 3.2.1 | VFS wiki mount | [x] | `wiki.vfs_mount` + PG `vfs_wiki_files` read-only backend; E2E [`test_wiki_vfs.sh`](../agents-runtime/deploy/examples/tests/e2e/test_wiki_vfs.sh) |
| 3.2.2 | async job API + Argo **suspend/resume** | [x] | `POST/GET /v1/agents/jobs` · pool `/jobs` · `async_poll` 기본 · `callback.argo` resume |

### 3.3 검색 · 파싱 고도화

| # | 작업 | 상태 | 비고 |
|---|---|---|---|
| 3.3.1 | **RRF hybrid** (PG FTS + pgvector) | [x] | `path_graph.rag.hybrid_search` |
| 3.3.2 | PDF/DOCX → **blocks JSON** (md 후처리) | [x] | **D3 개정으로 폐기 예정** — 당시 `md_heuristic`; 후속 3.3.5 |
| 3.3.3 | ingest 검색 API / retrieval CLI | [x] | `retrieval_search` CLI · `api_search_project` · BFF `GET …/search` |
| 3.3.4 | **스캔 PDF VL OCR fallback** (빈 parse → PNG→sglang→md) | [x] | ingest 동일 pass; native 전환 시 blocks 직행으로 재정렬 (3.3.5) |
| 3.3.5 | **Native blocks parser** (markitdown/md_heuristic 폐기) | [x] | parent #260 closeout; #274 문서, #278 routing, #293 adapter/chunk, #280 VLM·검증 완료. image `ghcr.io/yoosungung/path-graph/pipeline:c911fce66417ff27d967c2e255f1f8dc9fbc6d45` |

### 3.4 통합 Knowledge Search

| # | 작업 | 상태 | 비고 |
|---|---|---|---|
| 3.4.0 | `knowledge_search` 4-mode + `auto` 라우터 | [x] | `path_graph.retrieval` |
| 3.4.1 | wiki `wiki_pages` FTS+vector 인덱스 | [x] | wiki ingest 동기 |
| 3.4.2 | `entities` PG mirror + local graph retrieval | [x] | graph-extractor upsert hook |
| 3.4.3 | DRIFT-lite + `include_graph` community context | [x] | S3 `graph_context` 첨부 |
| 3.4.4 | agents-runtime MCP `search` tool `mode` 연동 | [x] | path-graph-rag-mcp + BFF |

---

## 권장 실행 순서 (다음 4 sprint)

D1–D5 결정 완료. Phase 4 Console·GraphRAG downstream **MVP 완료** — 병목은 **수집 운영화(BFF)** · **검색 품질** · **runtime binding**.

1. **검색·파싱 품질** — 3.3.1 RRF hybrid [x] · **3.3.5 native blocks** [x] (#260)
2. **오케스트레이션 잔여** — 2.4.2 Argo wait→API NP · 2.4.3 tenant `max_parallel`·semaphore · 2.1.8 collect-only WF [x]
3. **관리자 클러스터 검증 (일괄)** — 아래 §관리자 클러스터 검증 체크리스트 (SharePoint delta 등)

**D5 수집 동기화** — 코드·단위테스트 [x]. 클러스터 E2E만 §4로 연기.

### 관리자 클러스터 검증 체크리스트 (일괄 요청용)

운영 클러스터에서 한 번에 검증 요청할 항목. path-graph `deploy/SETUP.md`·agents-runtime `deploy/SETUP.md` 런북 전제.

**SharePoint delta sync (2.1.7)** — **보류** (ISMS 보안 심사, Eric 2026-07-09). 일괄 검증에서 제외. 재개 시 아래 체크리스트.

- [ ] SharePoint credential·source 연결 테스트 성공
- [ ] source `config.sync_mode=delta`, `schedule_cron` 설정 (예: `0 */6 * * *`)
- [ ] 1차 Cron WF Succeeded → source `config.delta_link` 비어 있지 않음
- [ ] SharePoint에 파일 1건 추가(또는 수정)
- [ ] 2차 Cron(delta) Succeeded → manifest에 변경분만 포함
- [ ] Console Run now `sync_mode=full` → 성공 후 `delta_link` 제거(또는 재수집 확인)

**Knowledge Binding · General agent (3.2.0)**

- [ ] Pipeline project ingest(RAG) 완료 문서 ≥1
- [ ] MCP 서버 `config.knowledge.requires_project=true` 등록
- [ ] General agent 생성 — `knowledge_project_ids`에 project 선택
- [ ] Chat invoke 1회 — agent-pool 로그에 `knowledge_binding_resolve` 성공(또는 MCP `collection`이 project binding과 일치)
- [ ] project 2개 연결 시 `search` tool — 양쪽 collection 병렬 호출 + RRF 병합 응답

**Wiki VFS (3.2.1)** — 자동: `agents-runtime/deploy/examples/tests/e2e/test_wiki_vfs.sh` (agent-pool `VFS_DSN` + general agent invoke). 수동 체크:

- [x] GraphRAG downstream 완료 → `vfs_wiki_files` 행 존재
- [x] agent-pool `VFS_DSN` 설정
- [x] General agent invoke 후 `/wiki/{project_slug}/` 경로 VFS read 성공

---

## 외부 의존 (path-graph가 설치하지 않음)

| 컴포넌트 | 소유 | path-graph 소비 |
|---|---|---|
| Garage, runtime PG, Envoy | agents-runtime | wire-dev / Secret |
| Nebula | path-graph `deploy/k8s/infra/` | `make deploy-nebula` |
| Argo Workflows controller | path-graph `deploy/k8s/argo/` | `make argo-install`, [SETUP.md](deploy/SETUP.md#argo-ui) |
| TEI `bge-m3` | llm-serving NS (외부) | `EMBEDDING_*` — HTTP only (D4) |
| sglang Gemma 4 12B | llm-serving NS (외부) | `OCR_LLM_*` · agents via Envoy (D4) |
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
| 4.1.3 | Run now → collect → Argo `pipeline-ingest-rag` | [x] | manifest submit + `sync_mode=full` default + reconciler `delta_link` persist |
| 4.1.7 | Source **schedule_cron** + **sync_mode** UI | [x] | PG `schedule_cron` [x]; Console cron [x]; delta/full·delta_link UI [x] (D5) |
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
| 4.4.4 | CronWorkflow `pipeline-reconcile-index` per project | [x] | 일 1회; agents-runtime BFF reconcile (PG-5) |

### 4.5 Downstream (GraphRAG) — Console

| # | 작업 | 상태 | 비고 |
|---|---|---|---|
| 4.5.1 | BFF `POST …/projects/{id}/graphrag` | [x] | `pipeline-graphrag` 단일 |
| 4.5.2 | ingest batch → `chunks_key` aggregate | [x] | `admin/downstream.py` |
| 4.5.3 | UI Runs 「Graph & Wiki 빌드」+ 재빌드 | [x] | active graphrag만 disabled |
| 4.5.4 | `pipeline_runs` run_kind + graph_at/wiki_at | [x] | reconciler on Succeeded |

---

## 결정 사항 (D1–D5, 2026-06)

| ID | 주제 | 결정 |
|---|---|---|
| D1 | Argo controller 설치 주체 | **path-graph** — `deploy/k8s/argo/` + `make argo-install` |
| D2 | pipeline 이미지 레지스트리·태그 | **GHCR** + **git SHA** (`:latest` 배포 안 함), `IfNotPresent` |
| D3 | 문서 구조화 | **native parser → `content.json` `blocks[]` 정본** — Office=`unstructured[docx,pptx,xlsx]`, PDF=PyMuPDF(/4LLM) router+blocks, HWP=`rhwp-batch`; `content.md` optional debug; markitdown/`md_heuristic` 폐기. Office embedded image VLM은 후속. |
| D4 | LLM·Embedding 서빙 | **path-graph 외부** — OpenAI-compatible HTTP (`EMBEDDING_*`, `OCR_LLM_*`, Envoy); in-process 모델 없음 |
| D5 | 수집 주기·동기화 | Console **`schedule_cron`** · 기본 **`sync_mode=delta`** · Run now **`full`** 전체 재수집 |

계약 정본: [ARCHITECTURE.md](ARCHITECTURE.md) · [pipeline/DESIGN.md](pipeline/DESIGN.md) · [deploy/DESIGN.md](deploy/DESIGN.md)

---

## 완료 시 갱신 규칙

- Phase 항목 상태 변경 시 이 파일만 수정 (ARCHITECTURE 계약 변경은 ARCHITECTURE 먼저).
- 테스트 수·주요 CLI 변경 시 [AGENTS.md](AGENTS.md) §3 Status 한 줄 동기화.
- 새 컴포넌트 코드 디렉터리 추가 시 [AGENTS.md](AGENTS.md) §1 표 검토.
