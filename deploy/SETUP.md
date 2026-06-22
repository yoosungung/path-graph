# deploy/SETUP.md — apply / rollback

## Prerequisites

- K8s cluster with agents-runtime (`runtime` NS, Garage)
- test_infra: Qdrant, NebulaGraph
- Argo Workflows controller installed (test_infra 또는 별도 Helm)

## Apply

```bash
kubectl apply -k deploy/k8s/base
```

## Submit ingest-rag (예시)

```bash
argo submit -n path-graph deploy/k8s/base/workflow-templates/pipeline-ingest-rag.yaml \
  -p tenant=dev \
  -p batch_manifest=s3://path-graph/jobs/dev/manual/batch.jsonl
```

## Rollback

```bash
kubectl delete -k deploy/k8s/base
```

Running workflows는 Argo UI에서 중지. Qdrant/Nebula 데이터는 이 매니페스트로 삭제되지 않음.
