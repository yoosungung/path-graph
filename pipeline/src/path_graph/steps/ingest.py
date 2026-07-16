from __future__ import annotations

import json
from typing import Any

from path_graph.chunkers.chunk import chunk_from_blocks, chunks_to_jsonl_lines
from path_graph.chunkers.pymupdf_json import chunk_from_pymupdf_json
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
from path_graph.parsers.blocks_extractors import get_blocks_extractor
from path_graph.parsers.image_caption import enrich_image_block_captions
from path_graph.parsers.parse import parse_non_pdf_to_blocks, parse_pdf_to_json
from path_graph.parsers.pymupdf_json import is_pymupdf_json_document
from path_graph.parsers.pdf_metrics import PdfKind, classify_pdf
from path_graph.parsers.route import route_parse
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


def _chunk_parsed_doc(
    parsed_doc: dict[str, Any],
    tenant: str,
    content_hash: str,
    project_id: str,
    *,
    max_chars: int,
) -> list:
    if is_pymupdf_json_document(parsed_doc):
        return chunk_from_pymupdf_json(
            parsed_doc,
            tenant,
            content_hash,
            project_id,
            max_chars=max_chars,
        )
    return chunk_from_blocks(
        parsed_doc,
        tenant,
        content_hash,
        project_id,
        max_chars=max_chars,
    )


def _chunk_from_blocks_doc(
    blocks_doc: dict[str, Any],
    tenant: str,
    content_hash: str,
    project_id: str,
    *,
    max_chars: int,
) -> list:
    return _chunk_parsed_doc(
        blocks_doc,
        tenant,
        content_hash,
        project_id,
        max_chars=max_chars,
    )


def _persist_parsed(
    store: BlobStore,
    tenant: str,
    doc_id: str,
    blocks_doc: dict[str, Any],
    *,
    markdown: str | None = None,
) -> str:
    parsed_key = s3_key_parsed_json(tenant, doc_id)
    store.put_bytes(
        parsed_key,
        json.dumps(blocks_doc, ensure_ascii=False).encode("utf-8"),
    )
    if markdown is not None:
        store.put_bytes(s3_key_parsed_md(tenant, doc_id), markdown.encode("utf-8"))
    return parsed_key


def _ingest_pdf(
    data: bytes,
    filename: str,
    tenant: str,
    meta: dict[str, Any],
    *,
    settings: Settings,
    store: BlobStore,
) -> dict[str, Any]:
    doc_id = meta["document_id"]
    content_hash = meta["content_hash"]
    ocr_available = _ocr_available(settings, filename)
    try:
        pdf_kind = classify_pdf(
            data,
            min_text_chars=settings.ocr_min_text_chars,
        )
    except Exception as exc:
        _record_dead_letter(
            store,
            tenant,
            content_hash,
            {"stage": "parse", "error": str(exc)},
        )
        raise ParseError(str(exc)) from exc
    fallback_reason: str | None = None
    parse_error: str | None = None
    parsed_text = ""
    ocr_attempted = False
    parse_backend = ParseBackend.PYMUPDF4LLM
    parsed_doc: dict[str, Any] | None = None

    if settings.ocr_force:
        if not ocr_available:
            _record_dead_letter(
                store,
                tenant,
                content_hash,
                {
                    "stage": "parse_empty",
                    "prior_backend": ParseBackend.VL_OCR.value,
                    "error": "OCR_FORCE set but OCR_LLM_* not configured",
                },
            )
            raise ParseError("OCR_FORCE requires OCR_LLM_BASE_URL and OCR_LLM_MODEL")
        try:
            parsed_text, _ = _run_vl_ocr(
                data,
                settings=settings,
                store=store,
                tenant=tenant,
                doc_id=doc_id,
                parse_backend=ParseBackend.VL_OCR,
            )
            parse_backend = ParseBackend.VL_OCR
            ocr_attempted = True
            parsed_doc = _blocks_from_markdown(parsed_text, settings)
        except Exception as ocr_exc:
            _record_dead_letter(
                store,
                tenant,
                content_hash,
                {
                    "stage": "ocr_empty",
                    "prior_backend": ParseBackend.VL_OCR.value,
                    "ocr_error": str(ocr_exc),
                },
            )
            raise ParseError(str(ocr_exc)) from ocr_exc
    elif pdf_kind is PdfKind.SCAN:
        if not ocr_available:
            _record_dead_letter(
                store,
                tenant,
                content_hash,
                {
                    "stage": "parse_empty",
                    "prior_backend": ParseBackend.PYMUPDF4LLM.value,
                    "pdf_kind": PdfKind.SCAN.value,
                    "error": "scan PDF requires OCR_LLM_BASE_URL and OCR_LLM_MODEL",
                },
            )
            raise ParseError("scan PDF requires OCR configuration")
        try:
            parsed_text, _ = _run_vl_ocr(
                data,
                settings=settings,
                store=store,
                tenant=tenant,
                doc_id=doc_id,
                parse_backend=ParseBackend.VL_OCR,
            )
            parse_backend = ParseBackend.VL_OCR
            ocr_attempted = True
            fallback_reason = "scan"
            parsed_doc = _blocks_from_markdown(parsed_text, settings)
        except Exception as ocr_exc:
            _record_dead_letter(
                store,
                tenant,
                content_hash,
                {
                    "stage": "ocr_empty",
                    "prior_backend": ParseBackend.VL_OCR.value,
                    "pdf_kind": PdfKind.SCAN.value,
                    "ocr_error": str(ocr_exc),
                },
            )
            raise ParseError(str(ocr_exc)) from ocr_exc
    else:
        try:
            parsed_doc = parse_pdf_to_json(data)
            parse_backend = ParseBackend.PYMUPDF4LLM
            if ocr_available:
                parsed_doc = enrich_image_block_captions(
                    parsed_doc, data, settings=settings
                )
        except Exception as exc:
            parse_error = str(exc)
            parsed_doc = {"pages": [], "page_count": 0}
            if not ocr_available:
                _record_dead_letter(
                    store,
                    tenant,
                    content_hash,
                    {"stage": "parse", "error": parse_error},
                )
                raise ParseError(parse_error) from exc

        chunks = _chunk_parsed_doc(
            parsed_doc,
            tenant,
            content_hash,
            meta["project_id"],
            max_chars=settings.chunk_max_chars,
        )
        if not chunks and ocr_available and not ocr_attempted:
            backend = (
                ParseBackend.PYMUPDF4LLM_VL_OCR_FALLBACK
                if not parse_error
                else ParseBackend.VL_OCR
            )
            fallback_reason = "parse_error" if parse_error else "low_text"
            try:
                parsed_text, _ = _run_vl_ocr(
                    data,
                    settings=settings,
                    store=store,
                    tenant=tenant,
                    doc_id=doc_id,
                    parse_backend=backend,
                )
                parse_backend = backend
                ocr_attempted = True
                parsed_doc = _blocks_from_markdown(parsed_text, settings)
            except Exception as ocr_exc:
                err = {
                    "stage": "ocr_empty",
                    "prior_backend": ParseBackend.PYMUPDF4LLM.value,
                    "ocr_error": str(ocr_exc),
                }
                if parse_error:
                    err["parse_error"] = parse_error
                _record_dead_letter(store, tenant, content_hash, err)
                raise ParseError(str(ocr_exc)) from ocr_exc

    assert parsed_doc is not None
    chunks = _chunk_parsed_doc(
        parsed_doc,
        tenant,
        content_hash,
        meta["project_id"],
        max_chars=settings.chunk_max_chars,
    )
    if not chunks:
        stage = "ocr_empty" if ocr_attempted else "parse_empty"
        err: dict[str, Any] = {
            "stage": stage,
            "prior_backend": parse_backend.value,
            "pdf_kind": pdf_kind.value,
        }
        if parse_error:
            err["parse_error"] = parse_error
        _record_dead_letter(store, tenant, content_hash, err)
        raise ParseError(f"no chunks after parse ({stage})")

    parsed_key = _persist_parsed(
        store,
        tenant,
        doc_id,
        parsed_doc,
        markdown=parsed_text or None,
    )
    meta_payload: dict[str, Any] = {
        **meta,
        "parsed_key": parsed_key,
        "chunk_count": len(chunks),
        "parse_backend": parse_backend.value,
        "pdf_kind": pdf_kind.value,
    }
    if is_pymupdf_json_document(parsed_doc):
        meta_payload["content_format"] = "pymupdf4llm_json"
    else:
        meta_payload["blocks_extractor"] = parsed_doc.get("extractor")
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

    if not data:
        _record_dead_letter(
            store,
            tenant,
            content_hash,
            {"stage": "empty_raw", "error": "raw file is empty"},
        )
        raise ParseError("raw file is empty")

    if _is_pdf(filename):
        return _ingest_pdf(
            data,
            filename,
            tenant,
            meta,
            settings=settings,
            store=store,
        )

    try:
        route_backend = route_parse(filename)
        parse_backend_label = route_backend.value
        blocks_doc = parse_non_pdf_to_blocks(
            data, filename, rhwp_bin=settings.rhwp_batch_bin
        )
    except Exception as exc:
        _record_dead_letter(
            store,
            tenant,
            content_hash,
            {"stage": "parse", "error": str(exc)},
        )
        raise ParseError(str(exc)) from exc

    parsed_key = _persist_parsed(store, tenant, doc_id, blocks_doc)

    chunks = _chunk_from_blocks_doc(
        blocks_doc,
        tenant,
        content_hash,
        meta["project_id"],
        max_chars=settings.chunk_max_chars,
    )
    if not chunks:
        _record_dead_letter(
            store,
            tenant,
            content_hash,
            {"stage": "parse_empty", "prior_backend": parse_backend_label},
        )
        raise ParseError("no chunks after parse (parse_empty)")

    meta_payload: dict[str, Any] = {
        **meta,
        "parsed_key": parsed_key,
        "chunk_count": len(chunks),
        "parse_backend": parse_backend_label,
        "blocks_extractor": blocks_doc.get("extractor"),
    }
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
        "parse_backend": parse_backend_label,
    }
