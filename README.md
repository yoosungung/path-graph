# path-graph

RAG · Graph · Wiki 지식 파이프라인. 오케스트레이션은 **Argo Workflows + Hera**, 계약은 [ARCHITECTURE.md](ARCHITECTURE.md).

## 의존 (외부)

| 컴포넌트 | 저장소 |
|---|---|
| Agent invoke, Garage, runtime PG | [agents-runtime](../agents-runtime) |
| Qdrant, NebulaGraph | [test_infra](../test_infra) |
| HWP 파서 | [rhwp_batch](../rhwp_batch) |

## Quickstart (로컬)

```bash
# k8s dev 클러스터에 path-graph 의존 infra가 떠 있어야 함
#   ../agents-runtime — make k8s-apply-dev
#   ../test_infra     — ./scripts/deploy.sh

make install
./scripts/wire-dev.sh up          # port-forward → 127.0.0.1
./scripts/wire-dev.sh env           # .env.dev.local 생성
make test
```

수동 env: [`.env.dev.local.example`](.env.dev.local.example). 포트 맵: [`scripts/wire-dev.env.example`](scripts/wire-dev.env.example).

## 파이프라인 CLI (개발)

```bash
source .venv/bin/activate
python -m path_graph.steps.ingest_web --tenant dev --url https://example.com
```

K8s 배포: [deploy/SETUP.md](deploy/SETUP.md)

## VS Code 디버그

`.vscode/launch.json` — `Wire: dev cluster`로 k8s port-forward 후 `Debug: ingest_web` / `Debug: pytest` 실행. 사전에 Python 확장(debugpy)과 `make install`(.venv) 필요.
