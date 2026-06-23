# deploy — K8s 배포 설계

path-graph 파이프라인 **워크로드만** 배포한다. Qdrant·Nebula는 [test_infra](../../test_infra) 책임.

## 레이아웃

```
deploy/
  k8s/
    argo/
      values.yaml
    base/                             # WorkflowTemplate·SA·ConfigMap
    overlays/
      dev/                            # GHCR image + :latest
```

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
make kustomize-build
make workflow-validate
make argo-install
make build-images          # GHA workflow_dispatch
make k8s-apply-dev         # dev overlay + secrets + registry-creds
make bootstrap-k8s         # argo-install + k8s-apply-dev
```

상세: [SETUP.md](SETUP.md)
