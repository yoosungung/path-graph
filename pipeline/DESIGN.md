# pipeline — 내부 설계

컴포넌트 *간* 계약은 [ARCHITECTURE.md](../ARCHITECTURE.md). 본 문서는 Argo step·agent 클라이언트·배치 처리 구현 방침만 다룬다.

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

1. **collect** → `batches/{tenant}/{batch_id}/manifest.jsonl` (한 줄 = `{content_hash, s3_raw_uri, source_id}`).
2. **ingest Workflow** entry: `withParam` manifest → sub-DAG (parse → chunk → fan-out).
3. 기본 **batch size 100**. 수집기가 버퍼 채우면 Workflow 1회 submit.
4. `parallelism: 10` (parse), `5` (embed) — semaphore와 함께 조정.

단건 재처리: `document_id` 또는 `content_hash` 단일 항목 manifest.

---

## Parse error boundary

| 포맷 | 이미지 | limits (memory) |
|---|---|---|
| hwp/hwpx | `rhwp-batch:0.7.15` | 2Gi |
| pdf/doc/ppt | `path-graph-parse` (markitdown) | 2Gi |
| txt/md | markitdown | 512Mi |

실패 시:

1. `dead_letter/{tenant}/{content_hash}/error.json` — `{stage, exit_code, stderr_snippet, at}`
2. PG `documents.ingest_state = dead_letter`
3. Argo `continueOn.failed: true` on parse map step

---

## GraphRAG (Hybrid, project별)

MS GraphRAG 사상을 Qdrant/Nebula project sharding과 정합되게 구현한다. **Community·Wiki는 project 경계를 넘지 않는다.**

### 흐름 (`steps/graphrag_pipeline.py`)

1. `partition_chunks_by_project` — batch chunks → `chunks/{tenant}/{project}/{batch_id}/chunks.jsonl`
2. `run_graph_pipeline` — project별 graph-extractor + Nebula upsert (`graph/nebula_store.py`)
3. `run_community_pipeline` — project별 hierarchical Leiden (`graph/community_detector.py`, `graspologic-native`)
4. `build_graph_context` — `graph_context/{tenant}/{project}/{batch_id}/{community_id}.json`
5. `run_wiki_pipeline` — project·community별 wiki-synthesizer

Argo: `deploy/k8s/base/workflow-templates/pipeline-graphrag.yaml` (권장). `pipeline-graph` / `pipeline-wiki`는 디버그용.

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
python -m path_graph.steps.ingest_sharepoint --tenant dev --folder 회사규정 --dry-run

# 수집 + ingest + RAG
python -m path_graph.steps.ingest_sharepoint \
  --tenant dev \
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

## 모듈 맵

```
src/path_graph/
  collectors/
    ms_graph_auth.py
    gdrive_auth.py
    gdrive.py
    onedrive.py
    sharepoint.py
  parsers/
  chunkers/
  contracts/community.py
  graph/
    nebula_store.py
    community_detector.py
    graph_context.py
    chunk_partition.py
  rag/qdrant_store.py
  steps/
    ingest_helpers.py
    ingest_sharepoint.py
    ingest_gdrive.py
    ingest_onedrive.py
    graph_pipeline.py
    community_pipeline.py
    graphrag_pipeline.py
    wiki_pipeline.py
    agent_invoke.py
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

# docker
docker build -f pipeline/Dockerfile -t path-graph-pipeline:latest .
```

Local env: [`scripts/wire-dev.sh`](../scripts/wire-dev.sh) `env` 또는 [`.env.dev.local.example`](../.env.dev.local.example)

VS Code: [`.vscode/launch.json`](../.vscode/launch.json) — `Wire: dev cluster` → `Debug: ingest_web` / `Debug: pytest`.
