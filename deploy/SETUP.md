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

## Filestash (Garage S3 UI)

dev 클러스터에서 Garage 객체를 브라우저로 확인할 때 사용한다. `make k8s-apply-dev`에 bootstrap이 포함된다.

| 항목 | 값 |
|------|-----|
| URL | http://filestash.k8s-test (`/etc/hosts` → ingress IP, Argo와 동일) |
| Admin | http://filestash.k8s-test/admin — 기본 비밀번호 `filestash-dev` (`FILESTASH_ADMIN_PASSWORD`로 override) |
| Garage 연결 | **Access Key ID** = `GARAGE_DEFAULT_ACCESS_KEY` · **Secret Access Key** = `GARAGE_DEFAULT_SECRET_KEY` (`runtime/s3-creds`와 동일). **Advanced** → Endpoint `http://garage-s3.runtime.svc.cluster.local:3900`, Region `garage` (필수). 버킷 `GARAGE_DEFAULT_BUCKET`(`runtime-bundles`)은 로그인 후 선택 |
| 주의 | `GARAGE_ADMIN_TOKEN`·`GARAGE_RPC_SECRET`은 S3 로그인에 쓰지 않음. Region 미입력 시 `us-east-1`로 시도되어 **잘못된 계정** 오류 발생 |
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
