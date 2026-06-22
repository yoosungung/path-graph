# deploy — K8s 배포 설계

path-graph 파이프라인 **워크로드만** 배포한다. Qdrant·Nebula는 [test_infra](../../test_infra) 책임.

## 레이아웃

```
deploy/
  k8s/base/
    namespace.yaml
    serviceaccount.yaml
    configmap-limits.yaml      # Argo semaphore keys
    workflow-templates/
      pipeline-ingest-rag.yaml
      pipeline-graph.yaml
      pipeline-wiki.yaml
      pipeline-graphrag.yaml
```

## Namespace

- **`path-graph` 단독** — Argo WorkflowTemplate·pipeline SA·ConfigMap은 `runtime` NS와 co-locate하지 않는다.
- Workflow Pod는 cross-namespace egress(NetworkPolicy)로 `runtime`(Garage, PG, Envoy), `qdrant`, `nebula`에만 접근한다.

## Secrets (외부 참조)

| Secret | 소유 | 용도 |
|---|---|---|
| `path-graph-pg-dsn` | agents-runtime overlay 또는 수동 | `PATH_GRAPH_DSN` |
| `qdrant-api-key` | test_infra | Qdrant |
| `nebula-auth` | test_infra | Graph |
| `pipeline-jwt` | admin | agent invoke |
| `s3-creds` | agents-runtime `runtime` NS | Garage artifact |

## NetworkPolicy (요약)

pipeline SA egress:

- `garage-s3.runtime.svc:3900`
- `postgres.runtime.svc:5432`
- `qdrant.qdrant.svc:6333`
- `nebula-graphd-svc.nebula.svc:9669`
- Envoy `runtime` NS `:8084` (또는 Ingress)
- `bge-m3-tei.llm-serving.svc:8080` — embedding TEI (`/v1/embeddings`)

## Argo

- WorkflowTemplate은 `deploy/k8s/base/workflow-templates/`에 YAML 정본
- Hera 생성물은 `pipeline/workflows/` — drift 시 YAML 우선

## Commands

```bash
kubectl apply -k deploy/k8s/base
```

상세: [SETUP.md](SETUP.md)
