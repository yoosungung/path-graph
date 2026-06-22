# ROADMAP.md

[ARCHITECTURE.md](ARCHITECTURE.md) 계약을 구현하는 순서. 미결정은 여기에만 둔다.

## Phase 1 — MVP

- [x] ARCHITECTURE.md §1 계약
- [x] pipeline 패키지·계약 테스트
- [x] ingest: web collect → parse → chunk → storage
- [x] RAG: embed → Qdrant + PG 메타
- [x] Hera `pipeline-ingest-rag` WorkflowTemplate
- [x] deploy/k8s 스켈레ton (NS, SA, limits, workflow templates)
- [x] agents/graph-extractor, wiki-synthesizer 스켈레ton

## Phase 2 — fan-out·수집기

- [x] Graph deterministic + agent + Nebula
- [x] Wiki synthesis workflow
- [x] GDrive / OneDrive / SharePoint / agent-chat collectors (OAuth + Graph/Drive API)

## Phase 3 — 하이브리드 GraphRAG 고도화

- [x] Graph-based Community Detection 모듈 구현 (NetworkX 등을 통한 Leiden Clustering)
- [x] Community Metadata & Report 구조 설계 (S3 및 PostgreSQL 적재)
- [ ] Graph-enhanced Wiki Synthesizer 에이전트 프롬프트 최적화 (MS GraphRAG 템플릿 이식)
- [x] Graph-to-Wiki synthesis 오케스트레이션 파이프라인 (Argo Workflow 및 pipeline steps 연계)
- [ ] agents-runtime VFS wiki mount
- [ ] Agent async suspend/resume (agents-runtime job API)
- [ ] RRF hybrid (PG BM25 + Qdrant)

## 미결정

_(없음)_
