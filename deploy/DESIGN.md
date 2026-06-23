# deploy — K8s 배포 설계

path-graph 파이프라인 **워크로드만** 배포한다. Qdrant·Nebula는 [test_infra](../../test_infra) 책임.

## 레이아웃

```
deploy/
  k8s/base/
    namespace.yaml                    # [x] kustomization 포함
    serviceaccount.yaml               # [ ] ROADMAP 1.4.3 — 미작성
    configmap-limits.yaml             # [ ] ROADMAP 1.4.4 — WF가 참조하나 미포함
    workflow-templates/
      pipeline-ingest-rag.yaml        # [x]
      pipeline-graph.yaml             # [x]
      pipeline-wiki.yaml              # [x]
      pipeline-graphrag.yaml          # [x]
```

## Namespace

- **`path-graph` 단독** — Argo WorkflowTemplate·pipeline SA·ConfigMap은 `runtime` NS와 co-locate하지 않는다.
- Workflow Pod는 cross-namespace egress(NetworkPolicy)로 `runtime`(Garage, PG, Envoy), `qdrant`, `nebula`에만 접근한다. NetworkPolicy 매니페스트는 ROADMAP 1.4.3.

## Secrets (외부 참조)

| Secret | 소유 | 용도 |
|---|---|---|
| `path-graph-env` (또는 분리) | 수동 / overlay | pipeline Pod env — [SETUP.md](SETUP.md) |
| `path-graph-pg-dsn` | agents-runtime overlay 또는 수동 | `PATH_GRAPH_DSN` |
| `qdrant-api-key` | test_infra | Qdrant |
| `nebula-auth` | test_infra | Graph |
| `pipeline-jwt` | admin | agent invoke |
| `s3-creds` | agents-runtime `runtime` NS | Garage artifact |

## NetworkPolicy (요약)

pipeline SA egress (ROADMAP 1.4.3 구현 시):

- `garage-s3.runtime.svc:3900`
- `postgres.runtime.svc:5432`
- `qdrant.qdrant.svc:6333`
- `nebula-graphd-svc.nebula.svc:9669`
- Envoy `runtime` NS `:8080` (로컬 wire-dev는 `:8084`)
- `bge-m3-tei.llm-serving.svc:8080` — embedding TEI (`/v1/embeddings`)

## Argo

- WorkflowTemplate은 `deploy/k8s/base/workflow-templates/`에 YAML 정본
- Hera 생성물은 `pipeline/workflows/` — drift 시 YAML 우선
- Controller 설치: test_infra Helm 또는 별도 — [SETUP.md](SETUP.md), ROADMAP 1.4.7

## Commands

```bash
make workflow-validate   # kubectl apply --dry-run=client
kubectl apply -k deploy/k8s/base
```

상세: [SETUP.md](SETUP.md)
