# graph-extractor — 내부 설계

MS GraphRAG entity/relationship extraction 프롬프트 사상을 LangGraph로 이식한다. 컴포넌트 간 계약은 [ARCHITECTURE.md](../../ARCHITECTURE.md) §2.5.

## 현재 상태 (스켈레ton)

| 항목 | 상태 |
|------|------|
| invoke payload 계약 | [x] `GraphExtractorInput` — pipeline `agent_invoke.py` |
| pipeline 연동 테스트 | [x] mock 위주 — `pipeline/tests/test_graph.py` |
| LangGraph 본구현 | [ ] 아래 § LangGraph |
| agents-runtime 번들 배포 | 수동 zip + admin API |

## 입출력

- **input**: `{tenant, project, batch_id, chunks_s3, output_schema, idempotency_key}`
- **output**: `{entities: [{id, name, description?}], edges: [{type, source, target, confidence, description?}], tenant, project}`

`project`는 Qdrant/Nebula와 동일한 `stable_hash(chunk_id) % n` 라우팅 인덱스다.

## 프롬프트

- `prompts/extract_graph.txt` — MS GraphRAG `extract_graph` 템플릿 기반 (청크 텍스트 → entity/relation JSON)

## LangGraph (예정)

1. load chunks from `chunks_s3`
2. map: LLM extract per chunk batch
3. reduce: merge entities, dedupe edges
4. validate `graph_v1` schema

## Commands

```bash
# agents-runtime 번들 등록 (수동)
cd agents/graph-extractor && zip -r bundle.zip src/
# admin POST /api/source-meta/bundle — entry: graph_extractor:factory

# pipeline 쪽 검증 (repo root)
make test   # test_graph.py
```
