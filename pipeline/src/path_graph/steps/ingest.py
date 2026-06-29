from __future__ import annotations

import json
from typing import Any

from path_graph.chunkers.chunk import chunk_from_blocks, chunks_to_jsonl_lines
from path_graph.config import Settings, get_settings
from path_graph.contracts.s3_keys import (
    s3_key_chunks,
    s3_key_dead_letter,
    s3_key_parsed_json,
    s3_key_parsed_md,
    s3_key_parsed_meta,
    s3_key_parsed_ocr_page_md,
    s3_key_parsed_page_png,
)
from path_graph.parsers.blocks_contract import normalize_blocks_document
from path_graph.parsers.blocks_extractors import get_blocks_extractor
from path_graph.parsers.parse import parse_document
from path_graph.parsers.vl_ocr import ParseBackend, vl_ocr_pdf_to_markdown
from path_graph.storage.blob import BlobStore, make_blob_store, write_jsonl


class ParseError(Exception):
    pass


def _is_pdf(filename: str) -> bool:
    return filename.lower().endswith(".pdf")


def _ocr_available(settings: Settings, filename: str) -> bool:
    return _is_pdf(filename) and bool(
        settings.ocr_llm_base_url.strip() and settings.ocr_llm_model.strip()
    )


def _record_dead_letter(
    store: BlobStore,
    tenant: str,
    content_hash: str,
    error: dict[str, Any],
) -> None:
    dl_key = s3_key_dead_letter(tenant, content_hash)
    store.put_bytes(dl_key, json.dumps(error, ensure_ascii=False).encode("utf-8"))


def _should_fallback_to_ocr(
    *,
    parsed_text: str,
    chunk_count: int,
    ocr_available: bool,
    ocr_attempted: bool,
    settings: Settings,
) -> bool:
    if not ocr_available or ocr_attempted:
        return False
    if chunk_count == 0:
        return True
    return len(parsed_text.strip()) < settings.ocr_min_text_chars


def _persist_ocr_artifacts(
    store: BlobStore,
    tenant: str,
    doc_id: str,
    ocr_meta: dict[str, Any],
    *,
    keep_page_images: bool,
) -> None:
    page_mds = ocr_meta.get("page_mds") or []
    for idx, page_md in enumerate(page_mds, start=1):
        store.put_bytes(
            s3_key_parsed_ocr_page_md(tenant, doc_id, idx),
            page_md.encode("utf-8"),
        )
    if keep_page_images:
        page_pngs = ocr_meta.get("page_pngs") or []
        for idx, png in enumerate(page_pngs, start=1):
            store.put_bytes(s3_key_parsed_page_png(tenant, doc_id, idx), png)


def _run_vl_ocr(
    data: bytes,
    *,
    settings: Settings,
    store: BlobStore,
    tenant: str,
    doc_id: str,
    parse_backend: ParseBackend,
) -> tuple[str, dict[str, Any]]:
    parsed_text, ocr_meta = vl_ocr_pdf_to_markdown(
        data,
        settings=settings,
        parse_backend=parse_backend,
    )
    _persist_ocr_artifacts(
        store,
        tenant,
        doc_id,
        ocr_meta,
        keep_page_images=settings.ocr_keep_page_images,
    )
    return parsed_text, ocr_meta


def _blocks_from_markdown(parsed_text: str, settings: Settings) -> dict[str, Any]:
    return get_blocks_extractor(settings.blocks_extractor).extract(parsed_text)


def _blocks_from_rhwp(rhwp_doc: dict[str, Any]) -> dict[str, Any]:
    return normalize_blocks_document(rhwp_doc, extractor="rhwp_batch")


def _chunk_from_blocks_doc(
    blocks_doc: dict[str, Any],
    tenant: str,
    content_hash: str,
    project_id: str,
    *,
    max_chars: int,
) -> list:
    return chunk_from_blocks(
        blocks_doc,
        tenant,
        content_hash,
        project_id,
        max_chars=max_chars,
    )


def ingest_raw_bytes(
    data: bytes,
    filename: str,
    tenant: str,
    source_id: str,
    meta: dict[str, Any],
) -> dict[str, Any]:
    settings = get_settings()
    store = make_blob_store(settings)
    doc_id = meta["document_id"]
    content_hash = meta["content_hash"]
    ocr_available = _ocr_available(settings, filename)

    if not data:
        _record_dead_letter(
            store,
            tenant,
            content_hash,
            {"stage": "empty_raw", "error": "raw file is empty"},
        )
        raise ParseError("raw file is empty")

    parse_backend = ParseBackend.MARKITDOWN
    fallback_reason: str | None = None
    markitdown_error: str | None = None
    rhwp_doc: dict | None = None
    parsed_text = ""
    ocr_attempted = False

    if settings.ocr_force and ocr_available:
        parsed_text, _ocr_meta = _run_vl_ocr(
            data,
            settings=settings,
            store=store,
            tenant=tenant,
            doc_id=doc_id,
            parse_backend=ParseBackend.VL_OCR,
        )
        parse_backend = ParseBackend.VL_OCR
        ocr_attempted = True
    else:
        try:
            parsed_text, rhwp_doc = parse_document(
                data, filename, rhwp_bin=settings.rhwp_batch_bin
            )
        except Exception as exc:
            markitdown_error = str(exc)
            if not ocr_available:
                _record_dead_letter(
                    store,
                    tenant,
                    content_hash,
                    {"stage": "parse", "error": markitdown_error},
                )
                raise ParseError(markitdown_error) from exc
            parsed_text = ""

    if rhwp_doc is not None:
        blocks_doc = _blocks_from_rhwp(rhwp_doc)
        parsed_key = s3_key_parsed_json(tenant, doc_id)
        store.put_bytes(
            parsed_key,
            json.dumps(blocks_doc, ensure_ascii=False).encode("utf-8"),
        )
        chunks = _chunk_from_blocks_doc(
            blocks_doc,
            tenant,
            content_hash,
            meta["project_id"],
            max_chars=settings.chunk_max_chars,
        )
    else:
        blocks_doc = _blocks_from_markdown(parsed_text, settings)
        chunks = _chunk_from_blocks_doc(
            blocks_doc,
            tenant,
            content_hash,
            meta["project_id"],
            max_chars=settings.chunk_max_chars,
        )

        if _should_fallback_to_ocr(
            parsed_text=parsed_text,
            chunk_count=len(chunks),
            ocr_available=ocr_available,
            ocr_attempted=ocr_attempted,
            settings=settings,
        ):
            backend = (
                ParseBackend.MARKITDOWN_VL_OCR_FALLBACK
                if not markitdown_error
                else ParseBackend.VL_OCR
            )
            fallback_reason = "parse_error" if markitdown_error else "low_text"
            try:
                parsed_text, _ocr_meta = _run_vl_ocr(
                    data,
                    settings=settings,
                    store=store,
                    tenant=tenant,
                    doc_id=doc_id,
                    parse_backend=backend,
                )
                parse_backend = backend
                ocr_attempted = True
                blocks_doc = _blocks_from_markdown(parsed_text, settings)
                chunks = _chunk_from_blocks_doc(
                    blocks_doc,
                    tenant,
                    content_hash,
                    meta["project_id"],
                    max_chars=settings.chunk_max_chars,
                )
            except Exception as ocr_exc:
                err = {
                    "stage": "ocr_empty",
                    "prior_backend": parse_backend.value,
                    "ocr_error": str(ocr_exc),
                }
                if markitdown_error:
                    err["parse_error"] = markitdown_error
                _record_dead_letter(store, tenant, content_hash, err)
                raise ParseError(str(ocr_exc)) from ocr_exc

        if not chunks:
            stage = "ocr_empty" if ocr_attempted else "parse_empty"
            err: dict[str, Any] = {"stage": stage, "prior_backend": parse_backend.value}
            if markitdown_error:
                err["parse_error"] = markitdown_error
            _record_dead_letter(store, tenant, content_hash, err)
            raise ParseError(f"no chunks after parse ({stage})")

        parsed_key = s3_key_parsed_json(tenant, doc_id)
        store.put_bytes(
            parsed_key,
            json.dumps(blocks_doc, ensure_ascii=False).encode("utf-8"),
        )
        md_key = s3_key_parsed_md(tenant, doc_id)
        store.put_bytes(md_key, parsed_text.encode("utf-8"))

    meta_payload: dict[str, Any] = {
        **meta,
        "parsed_key": parsed_key,
        "chunk_count": len(chunks),
        "parse_backend": parse_backend.value,
        "blocks_extractor": blocks_doc.get("extractor"),
    }
    if fallback_reason:
        meta_payload["fallback_reason"] = fallback_reason

    meta_key = s3_key_parsed_meta(tenant, doc_id)
    store.put_bytes(
        meta_key,
        json.dumps(meta_payload, ensure_ascii=False).encode("utf-8"),
    )

    chunks_key = s3_key_chunks(tenant, doc_id)
    chunks_uri = write_jsonl(chunks_key, chunks_to_jsonl_lines(chunks), store)

    return {
        **meta,
        "parsed_uri": store.uri_for(parsed_key),
        "chunks_uri": chunks_uri,
        "chunks_key": chunks_key,
        "chunks": chunks,
        "parse_backend": parse_backend.value,
    }
