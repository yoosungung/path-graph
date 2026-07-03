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
)


def s3_key_raw(
    tenant: str, project_id: str, source_id: str, content_hash: str, filename: str
) -> str:
    return f"raw/{tenant}/{project_id}/{source_id}/{content_hash}/{filename}"


def s3_key_parsed_md(tenant: str, doc_id: str) -> str:
    return f"parsed/{tenant}/{doc_id}/content.md"


def s3_key_parsed_json(tenant: str, doc_id: str) -> str:
    return f"parsed/{tenant}/{doc_id}/content.json"


def s3_key_parsed_meta(tenant: str, doc_id: str) -> str:
    return f"parsed/{tenant}/{doc_id}/meta.json"


def s3_key_parsed_page_png(tenant: str, doc_id: str, page: int) -> str:
    return f"parsed/{tenant}/{doc_id}/pages/{page:04d}.png"


def s3_key_parsed_ocr_page_md(tenant: str, doc_id: str, page: int) -> str:
    return f"parsed/{tenant}/{doc_id}/ocr/{page:04d}.md"


def s3_key_chunks(tenant: str, doc_id: str) -> str:
    return f"chunks/{tenant}/{doc_id}/chunks.jsonl"


def s3_key_dead_letter(tenant: str, content_hash: str) -> str:
    return f"dead_letter/{tenant}/{content_hash}/error.json"


def s3_key_job_manifest(tenant: str, job_id: str) -> str:
    return f"jobs/{tenant}/{job_id}/manifest.json"


def s3_key_batch_manifest(tenant: str, batch_id: str) -> str:
    return f"batches/{tenant}/{batch_id}/manifest.jsonl"


def s3_key_batch_meta(tenant: str, batch_id: str) -> str:
    return f"batches/{tenant}/{batch_id}/manifest.meta.json"


def s3_key_chunks_project_batch(tenant: str, project_id: str, batch_id: str) -> str:
    return f"chunks/{tenant}/{project_id}/{batch_id}/chunks.jsonl"


def s3_key_communities(tenant: str, project_id: str, batch_id: str) -> str:
    return f"communities/{tenant}/{project_id}/{batch_id}/communities.jsonl"


def s3_key_graph_context(
    tenant: str, project_id: str, batch_id: str, community_id: str
) -> str:
    return f"graph_context/{tenant}/{project_id}/{batch_id}/{community_id}.json"


def s3_key_raw_prefix(tenant: str, project_id: str) -> str:
    return f"raw/{tenant}/{project_id}/"
