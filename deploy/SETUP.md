# deploy/SETUP.md — apply / rollback

설계: [DESIGN.md](DESIGN.md) · 계약: [ARCHITECTURE.md](../ARCHITECTURE.md) · 진행: [ROADMAP.md](../ROADMAP.md)

## Prerequisites

| 항목 | 확인 |
|------|------|
| agents-runtime `runtime` NS | Garage, postgres, envoy |
| test_infra | Qdrant (`qdrant` NS), Nebula (`nebula` NS) |
| Argo Workflows controller | CRD + controller Pod (**미설치 시 ROADMAP 1.4.7**) |
| pipeline 이미지 | `path-graph-pipeline:latest` (또는 overlay registry) |
| TEI `bge-m3` | `llm-serving` NS — WF embed step |

```bash
# apply 전 dry-run
make workflow-validate
```

## Secrets (수동 — ROADMAP 1.4.5)

Kustomize base에는 Secret이 없다. `path-graph` NS에 `path-graph-env` 등을 클러스터에 맞게 생성한다.

```bash
kubectl create namespace path-graph --dry-run=client -o yaml | kubectl apply -f -

kubectl -n path-graph create secret generic path-graph-env \
  --from-literal=PATH_GRAPH_DSN='postgresql://runtime:runtime@postgres.runtime.svc:5432/runtime' \
  --from-literal=QDRANT_URL='http://qdrant.qdrant.svc:6333' \
  --from-literal=QDRANT_API_KEY='...' \
  --from-literal=NEBULA_HOST='nebula-graphd-svc.nebula.svc' \
  --from-literal=NEBULA_PORT='9669' \
  --from-literal=NEBULA_USER='root' \
  --from-literal=NEBULA_PASSWORD='nebula' \
  --from-literal=ENVOY_URL='http://envoy.runtime.svc:8080' \
  --from-literal=PIPELINE_AGENT_ACCESS_TOKEN='...' \
  --from-literal=EMBEDDING_BASE_URL='http://bge-m3-tei.llm-serving.svc:8080' \
  --dry-run=client -o yaml | kubectl apply -f -
```

Garage S3 credential은 agents-runtime `runtime` NS Secret을 cross-ref하거나 동일 키를 `path-graph-env`에 포함한다.

## Apply

```bash
kubectl apply -k deploy/k8s/base
```

현재 base에 포함: `namespace.yaml`, WorkflowTemplate 4종. **미포함** (ROADMAP 1.4.3–1.4.4): `serviceaccount.yaml`, `configmap-limits.yaml` — WF가 `path-graph-limits` semaphore를 참조하면 apply 전 추가 필요.

## Submit ingest-rag (예시)

```bash
# manifest는 S3에 업로드된 JSONL URI 또는 Argo withParam용 JSON 배열
argo submit -n path-graph deploy/k8s/base/workflow-templates/pipeline-ingest-rag.yaml \
  -p tenant=dev \
  -p batch_manifest=s3://path-graph/jobs/dev/manual/batch.jsonl
```

**한계**: 현재 템플릿은 manifest line을 `ingest_web --file`로 넘기도록 되어 있어 [ROADMAP 2.4.1](../ROADMAP.md) 정합 전까지 E2E 실패 가능.

## Troubleshooting

| 증상 | 조치 |
|------|------|
| `configmap "path-graph-limits" not found` | `configmap-limits.yaml` 작성·kustomization 추가 (ROADMAP 1.4.4) |
| embed connection refused | `EMBEDDING_BASE_URL`·`llm-serving` TEI Pod 확인 |
| Qdrant 404 collection | tenant×project collection 자동 생성 — `QDRANT_URL`/API key 확인 |
| Workflow Pod ImagePullBackOff | pipeline 이미지 빌드·레지스트리 (ROADMAP 1.4.6) |
| agent invoke 401 | `PIPELINE_AGENT_ACCESS_TOKEN` — wire-dev와 동일 auth flow |

로컬 디버그: [README Quickstart](../README.md) · `./scripts/wire-dev.sh up`

## Rollback

```bash
kubectl delete -k deploy/k8s/base
```

Running workflows는 Argo UI에서 중지. Qdrant/Nebula/PG/S3 데이터는 이 매니페스트로 삭제되지 않음.
