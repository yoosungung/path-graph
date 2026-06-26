# deploy — K8s 배포 설계

path-graph **파이프라인 워크로드** + **Qdrant·NebulaGraph 인프라**를 배포한다.

## 레이아웃

```
deploy/
  k8s/
    argo/
      values.yaml
    base/                             # WorkflowTemplate·SA·ConfigMap·Filestash
    infra/                            # Qdrant + NebulaGraph (test_infra에서 이전)
      helm/values/
      manifests/
    overlays/
      dev/                            # GHCR image + :latest
```

## Qdrant · NebulaGraph (`k8s/infra/`)

k8s-test 클러스터용 벡터·그래프 DB. Helm + raw manifest. 상세 런북: [SETUP.md](SETUP.md#qdrant--nebulagraph).

| 리소스 | 용도 |
|--------|------|
| `helm/values/qdrant.yaml` | Qdrant Helm (1 replica, `local-path` 8Gi) |
| `helm/values/nebula-operator.yaml` | NebulaGraph Operator 1.8.0 |
| `helm/values/nebula-cluster.yaml` | NebulaGraph v3.8.0 cluster (graphd/metad/storaged ×1) |
| `manifests/*-namespace.yaml` | `qdrant`, `nebula`, `nebula-operator-system` |
| `manifests/nebula-studio.yaml` | Studio v3.8.0 (Ingress `nebula-studio.k8s-test:7001`) |
| `manifests/ingress-routes.yaml` | Ingress `qdrant.k8s-test:6333` |
| `helm/values/ingress-nginx-qdrant-nebula.snippet.yaml` | 공유 ingress-nginx에 merge할 socat/TCP fragment |

배포·검증:

```bash
make test-infra-config      # TDD gate (helm template + kubectl dry-run)
make deploy-qdrant-nebula   # Helm + manifests
make verify-qdrant-nebula   # post-deploy smoke
```

로컬 디버그는 `wire-dev.sh` port-forward (`:6333`, `:9669`) — Ingress 불필요.

## Filestash (Garage S3 UI, dev)

클러스터 내부 Garage 버킷(`runtime-bundles` 등)을 브라우저로 탐색하는 **dev 전용** UI. `path-graph` NS에 배포, Ingress `filestash.k8s-test:8334`.

| 리소스 | 용도 |
|--------|------|
| `filestash.yaml` | Deployment + PVC + Service |
| `filestash-configmap.yaml` | S3 백엔드만 활성화한 seed `config.json` |
| `filestash-ingress.yaml` | nginx Ingress (HTTP, dev) |
| `filestash-networkpolicy.yaml` | egress → `runtime/garage-s3:3900` |

Secret `filestash-env`는 `scripts/bootstrap-filestash.sh`가 생성 (`ADMIN_PASSWORD` bcrypt, `APPLICATION_URL`). Garage 자격증명은 로그인 화면 또는 `/admin`에서 입력(S3 키는 `s3-creds`와 동일).

## 컨테이너 이미지 (GitHub Actions → GHCR)

워크플로: [`.github/workflows/build-images.yml`](../.github/workflows/build-images.yml)

| 트리거 | 용도 |
|--------|------|
| `workflow_dispatch` | dev 배포용 — **push 후** `make build-images` |
| Release **published** | 태그 릴리스와 함께 빌드 |

태그: `ghcr.io/yoosungung/path-graph/pipeline:latest` 및 `:<git-sha>`

```bash
git push origin main
make build-images
gh run list --workflow=build-images.yml --limit=3
make k8s-apply-dev
```

## Commands

```bash
make test
make test-infra-config
make deploy-qdrant-nebula
make verify-qdrant-nebula
make kustomize-build
make workflow-validate
make argo-install
make build-images          # GHA workflow_dispatch
make k8s-apply-dev         # dev overlay + secrets + registry-creds
make bootstrap-k8s         # argo-install + k8s-apply-dev
```

상세: [SETUP.md](SETUP.md)
