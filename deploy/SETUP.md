# deploy/SETUP.md — apply / rollback

설계: [DESIGN.md](DESIGN.md) · 계약: [ARCHITECTURE.md](../ARCHITECTURE.md) · 진행: [ROADMAP.md](../ROADMAP.md)

## Prerequisites

| 항목 | 확인 |
|------|------|
| agents-runtime `runtime` NS | Garage, postgres, envoy |
| path-graph infra | Nebula — `make deploy-nebula` |
| runtime PG | **17 + pgvector** (`pgvector/pgvector:pg17` in agents-runtime) |
| Argo Workflows | **path-graph** — `make argo-install` (`deploy/k8s/argo/`) |
| pipeline 이미지 | **GHA** `make build-images` (로컬 docker 없음) |
| GHCR pull | `registry-creds` in `path-graph` NS (`make ensure-registry-secret`) |

## 이미지 빌드

**표준**: `:latest` 배포 금지. 이미지 태그 = **full git SHA** (`scripts/resolve-image-tag.sh`). `imagePullPolicy: IfNotPresent`.

### GitHub Actions

```bash
git push origin main
make build-images
gh run watch   # 또는: gh run list --workflow=build-images.yml --limit=1
```

Release publish 시 GHA가 `:<git-sha>`와 `:<release-tag>`를 함께 push한다:

```bash
gh release create v0.1.1 --title "v0.1.1" --target main
```

### 로컬 빌드 (docker)

```bash
make build-pipeline-image PUSH=1   # TAG=현재 HEAD SHA → GHCR push
```

## 배포

```bash
make bootstrap-k8s    # 최초: Argo + secrets + dev overlay
# 이미지 갱신 후 (SHA 태그 pin + apply):
make k8s-apply-dev    # set-dev-image-tag + secrets + dev overlay
```

`k8s-apply-dev`는 `deploy/k8s/overlays/dev/kustomization.yaml`의 `newTag`를 현재 `IMAGE_TAG`(기본 HEAD SHA)로 갱신하고 `deploy/k8s/pipeline-image-tag`에 기록한다. 다른 SHA를 배포할 때: `IMAGE_TAG=<sha> make k8s-apply-dev`.

## NebulaGraph

path-graph가 [`deploy/k8s/infra/`](k8s/infra/)에서 NebulaGraph를 설치·운영한다. 벡터(pgvector)는 agents-runtime **runtime Postgres** (`PATH_GRAPH_DSN`).

### 배포

```bash
make test-infra-config
make deploy-nebula
make verify-nebula
```

| 항목 | 값 |
|------|-----|
| Nebula graphd | `nebula-graphd-svc.nebula.svc.cluster.local:9669` — user `root` / `nebula` |
| Nebula Studio | `http://nebula-studio.k8s-test:7001/` |

로컬 디버그: `./scripts/wire-dev.sh up` → `:9669` port-forward.

### Teardown

```bash
make teardown-nebula
```

## Secrets

`create-path-graph-secrets.sh` — `path-graph-env`, `s3-creds` (runtime에서 복사). agent presigned URL 서명에 `S3_REGION` 필요. env로 넘기지 않으면 **기존 `path-graph-env`의 `PIPELINE_AGENT_ACCESS_TOKEN`·`S3_REGION`을 유지**한다(runtime `s3-creds`·`garage`는 Secret이 없을 때만). `make k8s-apply-dev`가 수동 설정을 지우지 않음.

```bash
PIPELINE_AGENT_ACCESS_TOKEN=... ./scripts/create-path-graph-secrets.sh   # 최초 설정·교체
S3_REGION=garage ./scripts/create-path-graph-secrets.sh                  # region 명시 override
./scripts/create-path-graph-secrets.sh                                   # 기존 token·S3_REGION 보존
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

## LangGraph agent bundles

graph-extractor·wiki-synthesizer는 agents-runtime `agent:compiled_graph` 풀에 zip 번들로 등록한다. pipeline은 artifact를 **presigned URL**로 전달 — agent pool에 Garage/S3 credential을 두지 않는다.

```bash
# agents-runtime admin 로그인 + bundle POST (AGENTS_HOST, ADMIN_PASSWORD)
./scripts/register-agent-bundles.sh all v2

# live agent downstream (LLM port-forward + 번들 등록 후)
SKIP_AGENT=0 ./scripts/submit-downstream-e2e.sh
```

## Filestash (Garage S3 UI)

dev 클러스터에서 Garage 객체를 브라우저로 확인할 때 사용한다. `make k8s-apply-dev`에 bootstrap이 포함된다.

| 항목 | 값 |
|------|-----|
| URL | http://filestash.k8s-test (`/etc/hosts` → ingress IP, Argo와 동일) |
| **원클릭 접속 (권장)** | http://filestash.k8s-test/api/session/auth/?action=redirect&label=Garage%20S3 — key/secret 입력 없이 바로 `runtime-bundles` |
| Admin | http://filestash.k8s-test/admin — 기본 비밀번호 `filestash-dev` (`FILESTASH_ADMIN_PASSWORD`로 override). env 없이 `bootstrap-filestash.sh`/`make k8s-apply-dev` 재실행 시 **기존 `filestash-env` bcrypt hash 유지** |
| Garage 연결 | init + **passthrough `direct`** middleware. 로그인 화면에 **Garage S3**만 보이면 클릭만 하면 됨(구형 S3 key/secret 폼이 아님). `connections`만 넣으면 여전히 key/secret 폼이 뜸 |
| 주의 | `GARAGE_ADMIN_TOKEN`·`GARAGE_RPC_SECRET`은 S3 로그인에 쓰지 않음. credentials는 PVC `config.json`에 저장됨(dev 전용) |
| redirect 오류 | `http://http//filestash.k8s-test/` 등이면 `APPLICATION_URL`에 scheme이 들어간 상태 — secret을 `filestash.k8s-test`(호스트명만)로 재적용 후 pod 재시작 |
| port-forward (대안) | `kubectl -n path-graph port-forward svc/filestash 8334:8334` |

```bash
FILESTASH_ADMIN_PASSWORD='...' ./scripts/bootstrap-filestash.sh   # secret만 재적용
kubectl -n path-graph rollout restart deploy/filestash
```

## Argo UI

**소유**: path-graph — controller·server Helm (`deploy/k8s/argo/values.yaml`), `make argo-install`. `test_infra` Argo 설치에 의존하지 않는다.

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
| ImagePullBackOff | `make build-images`(또는 `make build-pipeline-image PUSH=1`) 완료 후 `IMAGE_TAG`가 GHCR에 있는 SHA인지 확인 · `make ensure-registry-secret` |
| embed connection refused | TEI Pod·`EMBEDDING_BASE_URL` 확인 |
| agent invoke 401 / `PIPELINE_AGENT_ACCESS_TOKEN not set` | Secret에 토큰 설정 — `PIPELINE_AGENT_ACCESS_TOKEN=ak_... ./scripts/create-path-graph-secrets.sh`. `make k8s-apply-dev` 후에도 기존 토큰은 보존되나, 최초 1회는 API key 발급 필요 |
| graphrag agent 500 / Garage presigned 400 | `path-graph-env`에 `S3_REGION=garage` — `./scripts/create-path-graph-secrets.sh` 재실행 |
| `fsnotify watcher: too many open files` | ingest map burst 시 노드 inotify 한도. `./scripts/tune-node-inotify.sh` (기본 `max_user_instances=512`). 오래된 Completed WF Pod 정리: `kubectl delete pods -n path-graph --field-selector=status.phase=Succeeded` |

## Rollback

```bash
kubectl delete -k deploy/k8s/overlays/dev
```
