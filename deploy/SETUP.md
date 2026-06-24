# deploy/SETUP.md — apply / rollback

설계: [DESIGN.md](DESIGN.md) · 계약: [ARCHITECTURE.md](../ARCHITECTURE.md) · 진행: [ROADMAP.md](../ROADMAP.md)

## Prerequisites

| 항목 | 확인 |
|------|------|
| agents-runtime `runtime` NS | Garage, postgres, envoy |
| test_infra | Qdrant, Nebula |
| Argo Workflows | `make argo-install` |
| pipeline 이미지 | **GHA** `make build-images` (로컬 docker 없음) |
| GHCR pull | `registry-creds` in `path-graph` NS (`make ensure-registry-secret`) |

## 이미지 빌드 (GitHub Actions)

```bash
git push origin main
make build-images
gh run watch   # 또는: gh run list --workflow=build-images.yml --limit=1
```

Release publish:

```bash
gh release create v0.1.1 --title "v0.1.1" --target main
```

## 배포

```bash
make bootstrap-k8s    # 최초: Argo + secrets + dev overlay
# 이후 이미지 갱신 후:
make k8s-apply-dev    # secrets + dev overlay + runtime NP patch
./scripts/patch-runtime-ingress-for-path-graph.sh   # k8s-apply-dev에 포함
```

## Secrets

`create-path-graph-secrets.sh` — `path-graph-env`, `s3-creds` (runtime에서 복사)

```bash
PIPELINE_AGENT_ACCESS_TOKEN=... ./scripts/create-path-graph-secrets.sh
```

## Submit ingest-rag

```bash
./scripts/submit-ingest-rag-e2e.sh   # S3 fixture + Argo withParam E2E
```

## Submit graph / wiki / graphrag

```bash
./scripts/submit-downstream-e2e.sh                    # all three (skip_agent=1)
TEMPLATE=pipeline-graph ./scripts/submit-downstream-e2e.sh
```

## Argo UI

| 항목 | 값 |
|------|-----|
| URL | http://argo.k8s-test (`/etc/hosts` → ingress IP `10.43.115.145`) |
| auth | `server` 모드 — UI 로그인 없음 (dev 전용) |
| port-forward (대안) | `kubectl -n argo port-forward svc/argo-workflows-server 2746:2746` |

```bash
make argo-install   # Ingress 포함 Helm upgrade
```

## Troubleshooting

| 증상 | 조치 |
|------|------|
| ImagePullBackOff | `make build-images` 완료 후 `make ensure-registry-secret` |
| embed connection refused | TEI Pod·`EMBEDDING_BASE_URL` 확인 |
| agent invoke 401 | `PIPELINE_AGENT_ACCESS_TOKEN` 설정 |

## Rollback

```bash
kubectl delete -k deploy/k8s/overlays/dev
```
