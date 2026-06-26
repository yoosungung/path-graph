# deploy/SETUP.md — apply / rollback

설계: [DESIGN.md](DESIGN.md) · 계약: [ARCHITECTURE.md](../ARCHITECTURE.md) · 진행: [ROADMAP.md](../ROADMAP.md)

## Prerequisites

| 항목 | 확인 |
|------|------|
| agents-runtime `runtime` NS | Garage, postgres, envoy |
| path-graph infra | Qdrant, Nebula — `make deploy-qdrant-nebula` |
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

## Qdrant · NebulaGraph

path-graph가 [`deploy/k8s/infra/`](k8s/infra/)에서 Qdrant·NebulaGraph를 설치·운영한다.

### 배포

```bash
make test-infra-config       # pre-deploy (helm template + dry-run)
make deploy-qdrant-nebula    # namespaces + Helm + Studio + Ingress
make verify-qdrant-nebula    # post-deploy smoke
```

| 항목 | 값 |
|------|-----|
| Qdrant NS | `qdrant` — in-cluster `http://qdrant.qdrant.svc.cluster.local:6333` |
| Qdrant API key (dev) | `test-qdrant-api-key` (`QDRANT_API_KEY`로 override) |
| Qdrant external | `http://qdrant.k8s-test:6333/` (Ingress + ingress-nginx socat `:6333`) |
| Nebula graphd | `nebula-graphd-svc.nebula.svc.cluster.local:9669` — user `root` / `nebula` |
| Nebula Studio | `http://nebula-studio.k8s-test:7001/` |

로컬 디버그: `./scripts/wire-dev.sh up` → `:6333`, `:9669` port-forward (Ingress 불필요).

**Ingress (LAN)**: `make deploy-qdrant-nebula`가 Ingress route를 적용한다. 공유 ingress-nginx(`test_infra`의 `helm/values/ingress-nginx.yaml`)에 hostPort `:6333`/`:7001`/TCP `:6334`가 있어야 LAN URL이 동작한다.

### Teardown

```bash
make teardown-qdrant-nebula
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

## Filestash (Garage S3 UI)

dev 클러스터에서 Garage 객체를 브라우저로 확인할 때 사용한다. `make k8s-apply-dev`에 bootstrap이 포함된다.

| 항목 | 값 |
|------|-----|
| URL | http://filestash.k8s-test (`/etc/hosts` → ingress IP, Argo와 동일) |
| **원클릭 접속 (권장)** | http://filestash.k8s-test/api/session/auth/?action=redirect&label=Garage%20S3 — key/secret 입력 없이 바로 `runtime-bundles` |
| Admin | http://filestash.k8s-test/admin — 기본 비밀번호 `filestash-dev` (`FILESTASH_ADMIN_PASSWORD`로 override) |
| Garage 연결 | init + **passthrough `direct`** middleware. 로그인 화면에 **Garage S3**만 보이면 클릭만 하면 됨(구형 S3 key/secret 폼이 아님). `connections`만 넣으면 여전히 key/secret 폼이 뜸 |
| 주의 | `GARAGE_ADMIN_TOKEN`·`GARAGE_RPC_SECRET`은 S3 로그인에 쓰지 않음. credentials는 PVC `config.json`에 저장됨(dev 전용) |
| port-forward (대안) | `kubectl -n path-graph port-forward svc/filestash 8334:8334` |

```bash
FILESTASH_ADMIN_PASSWORD='...' ./scripts/bootstrap-filestash.sh   # secret만 재적용
kubectl -n path-graph rollout restart deploy/filestash
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
