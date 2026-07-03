# deploy — K8s 배포 설계

path-graph **Argo Workflows** + **파이프라인 워크로드** + **NebulaGraph 인프라**를 배포한다. 벡터(pgvector)는 agents-runtime **runtime Postgres 17**을 사용한다.

## 레이아웃

```
deploy/
  k8s/
    argo/
      values.yaml
    base/                             # WorkflowTemplate·SA·ConfigMap·Filestash
    infra/                            # NebulaGraph (test_infra에서 이전)
      helm/values/
      manifests/
    overlays/
      dev/                            # GHCR image + git SHA tag (kustomize newTag)
    pipeline-image-tag                # 현재 배포 중인 pipeline 이미지 SHA (set-dev-image-tag.sh)
```

## Argo Workflows (`k8s/argo/`)

**설치·운영 주체: path-graph** (ROADMAP D1 결정). `test_infra`는 ingress-nginx 등 클러스터 공유 컴포넌트만; Argo controller·server·Ingress는 path-graph가 관리한다.

| 리소스 | 용도 |
|--------|------|
| `argo/values.yaml` | Helm values — controller + server, Ingress `argo.k8s-test`, `workflowDefaults.spec.podGC.deleteDelayDuration` |
| `scripts/install-argo.sh` | `helm upgrade --install argo-workflows` (`argo` NS) |

`deleteDelayDuration`는 **WorkflowTemplate CR에 넣지 않는다** — `workflowDefaults`와 병합 시 Argo v4.0.6 `int64` 검증 오류. `podGC.strategy`·`parallelism: "{{workflow.parameters.max_parallel}}"`는 **base** 템플릿에 둔다. dev overlay는 JSON patch로 `parallelism`만 제거(v4.0.6 런타임; 동시성은 `ingest-map` semaphore).

```bash
make argo-install          # Helm upgrade + rollout wait
make bootstrap-k8s         # argo-install + k8s-apply-dev (최초 부트스트랩)
```

상세·UI URL: [SETUP.md](SETUP.md#argo-ui).

## NebulaGraph (`k8s/infra/`)

k8s-test 클러스터용 그래프 DB. Helm + raw manifest. 벡터(pgvector)는 agents-runtime runtime Postgres 17. 상세: [SETUP.md](SETUP.md#nebulagraph).

| 리소스 | 용도 |
|--------|------|
| `helm/values/nebula-operator.yaml` | NebulaGraph Operator 1.8.0 |
| `helm/values/nebula-cluster.yaml` | NebulaGraph v3.8.0 cluster (graphd/metad/storaged ×1) |
| `manifests/*-namespace.yaml` | `nebula`, `nebula-operator-system` |
| `manifests/nebula-studio.yaml` | Studio v3.8.0 (Ingress `nebula-studio.k8s-test:7001`) |
| `manifests/ingress-routes.yaml` | Ingress `nebula-studio.k8s-test:7001` |
| `helm/values/ingress-nginx-nebula.snippet.yaml` | 공유 ingress-nginx socat fragment |

배포·검증:

```bash
make test-infra-config
make deploy-nebula
make verify-nebula
```

로컬 디버그는 `wire-dev.sh` port-forward (`:9669`) — Ingress 불필요.

## Filestash (Garage S3 UI, dev)

클러스터 내부 Garage 버킷(`runtime-bundles` 등)을 브라우저로 탐색하는 **dev 전용** UI. `path-graph` NS에 배포, Ingress `filestash.k8s-test:8334`.

| 리소스 | 용도 |
|--------|------|
| `filestash.yaml` | Deployment + PVC + Service; init가 `s3-creds`로 `config.json` 생성 |
| `filestash-init` ConfigMap | `scripts/render-filestash-config.sh` — Garage key/secret/endpoint/region/버킷 path 주입 |
| `filestash-ingress.yaml` | nginx Ingress (HTTP, dev) |
| `filestash-networkpolicy.yaml` | egress → `runtime/garage-s3:3900` |

Secret `filestash-env`는 `scripts/bootstrap-filestash.sh`가 생성 (`ADMIN_PASSWORD` bcrypt, `APPLICATION_URL=filestash.k8s-test`). **`APPLICATION_URL`은 호스트명만** — `http://`·`https://` 접두사를 넣으면 Filestash가 `http://http//…` 형태로 잘못 리다이렉트한다([filestash#828](https://github.com/mickael-kerjean/filestash/issues/828)). Garage S3는 init가 `s3-creds`로 `config.json`을 렌더 — **passthrough `direct` middleware**로 로그인 화면 key/secret 입력 없이 바로 버킷 탐색(dev 전용).

## 컨테이너 이미지 (GitHub Actions → GHCR)

워크플로: [`.github/workflows/build-images.yml`](../.github/workflows/build-images.yml)

| 트리거 | 용도 |
|--------|------|
| `workflow_dispatch` | dev 배포용 — **push 후** `make build-images` |
| Release **published** | 태그 릴리스와 함께 빌드 |

태그: **`:latest` 사용 안 함.** `:<git-sha>`(full SHA, GHA·로컬 빌드 공통). Release published 시 추가로 `:<release-tag>`.

| 항목 | 표준 |
|------|------|
| 배포 참조 | `ghcr.io/yoosungung/path-graph/pipeline:<git-sha>` — `deploy/k8s/pipeline-image-tag` |
| base manifest | `path-graph/pipeline:0.0.0` placeholder → kustomize `images.newTag` |
| `imagePullPolicy` | `IfNotPresent` (pipeline WorkflowTemplate 전체) |

```bash
git push origin main
make build-images                    # GHA: push :<git-sha>
# 또는 로컬:
make build-pipeline-image PUSH=1     # TAG=현재 HEAD SHA
make k8s-apply-dev                   # set-dev-image-tag + kubectl apply -k dev
gh run list --workflow=build-images.yml --limit=3
```

## Commands

```bash
make test
make test-infra-config
make deploy-nebula
make verify-nebula
make kustomize-build
make workflow-validate
make argo-install
make build-images          # GHA workflow_dispatch
make k8s-apply-dev         # dev overlay + secrets + registry-creds
make bootstrap-k8s         # argo-install + k8s-apply-dev
```

상세: [SETUP.md](SETUP.md)
