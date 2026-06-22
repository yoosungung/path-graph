from __future__ import annotations

S3_PREFIXES = (
    "raw",
    "parsed",
    "chunks",
    "dead_letter",
    "jobs",
    "batches",
    "communities",
    "graph_context",
    "wiki",
)


def s3_key_raw(tenant: str, source_id: str, content_hash: str, filename: str) -> str:
    return f"raw/{tenant}/{source_id}/{content_hash}/{filename}"


def s3_key_parsed_md(tenant: str, doc_id: str) -> str:
    return f"parsed/{tenant}/{doc_id}/content.md"


def s3_key_parsed_json(tenant: str, doc_id: str) -> str:
    return f"parsed/{tenant}/{doc_id}/content.json"


def s3_key_parsed_meta(tenant: str, doc_id: str) -> str:
    return f"parsed/{tenant}/{doc_id}/meta.json"


def s3_key_chunks(tenant: str, doc_id: str) -> str:
    return f"chunks/{tenant}/{doc_id}/chunks.jsonl"


def s3_key_dead_letter(tenant: str, content_hash: str) -> str:
    return f"dead_letter/{tenant}/{content_hash}/error.json"


def s3_key_job_manifest(tenant: str, job_id: str) -> str:
    return f"jobs/{tenant}/{job_id}/manifest.json"


def s3_key_batch_manifest(tenant: str, batch_id: str) -> str:
    return f"batches/{tenant}/{batch_id}/manifest.jsonl"


def s3_key_chunks_project_batch(tenant: str, project: int, batch_id: str) -> str:
    return f"chunks/{tenant}/{project}/{batch_id}/chunks.jsonl"


def s3_key_communities(tenant: str, project: int, batch_id: str) -> str:
    return f"communities/{tenant}/{project}/{batch_id}/communities.jsonl"


def s3_key_graph_context(
    tenant: str, project: int, batch_id: str, community_id: str
) -> str:
    return f"graph_context/{tenant}/{project}/{batch_id}/{community_id}.json"


def s3_key_wiki(tenant: str, project: int, page_slug: str) -> str:
    return f"wiki/{tenant}/{project}/{page_slug}.md"
