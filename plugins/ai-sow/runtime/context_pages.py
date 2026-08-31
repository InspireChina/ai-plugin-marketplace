from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

from runtime.handoff import canonical_json_bytes, sha256_bytes
from runtime.project_io import ProjectFiles, ProjectIOError


CONTEXT_PAGE_ALGORITHM = "ai-sow-context-page-v1"
PAGE_BYTE_BUDGET = 32_768
PAGE_TOKEN_BUDGET = 8_192
TOKEN_ESTIMATOR = "utf8-bytes-upper-bound-v1"
TRUNCATED_PAGE_STATUS = "NOT_READ"
PENDING_CLAIM_METRICS = {"status": "PENDING_CANDIDATE"}


def context_budget() -> dict[str, object]:
    return {
        "pageByteBudget": PAGE_BYTE_BUDGET,
        "pageTokenBudget": PAGE_TOKEN_BUDGET,
        "tokenEstimator": TOKEN_ESTIMATOR,
    }


def read_protocol() -> dict[str, object]:
    return {
        "algorithm": "ai-sow-context-read-once-v1",
        "order": "manifest.fragments[].pages[].order",
        "readEachPageOnce": True,
        "truncatedPageStatus": TRUNCATED_PAGE_STATUS,
        "recovery": (
            "Resume at the first unread page in this exact manifest; a truncated page is "
            "NOT_READ, and previously completed pages must not be read again."
        ),
    }


def _page_path(source_path: str, order: int) -> str:
    stem = source_path.rsplit(".", 1)[0]
    return f"{stem}.pages/{order:04d}.json"


def _page_payload(
    fragment_name: str,
    order: int,
    page_count: int,
    content: str,
) -> bytes:
    return canonical_json_bytes(
        {
            "algorithm": CONTEXT_PAGE_ALGORITHM,
            "content": content,
            "fragment": fragment_name,
            "order": order,
            "pageCount": page_count,
        }
    )


def _content_pages(payload: bytes) -> list[str]:
    text = payload.decode("utf-8")
    if not text:
        return [""]
    pages: list[str] = []
    cursor = 0
    while cursor < len(text):
        end = min(cursor + PAGE_TOKEN_BUDGET, len(text))
        content = text[cursor:end]
        while (
            len(content.encode("utf-8")) > PAGE_TOKEN_BUDGET
            or len(_page_payload("fragment", 1, 1, content)) > PAGE_BYTE_BUDGET
        ):
            overflow = max(
                len(content.encode("utf-8")) - PAGE_TOKEN_BUDGET,
                len(_page_payload("fragment", 1, 1, content)) - PAGE_BYTE_BUDGET,
            )
            end -= max(1, math.ceil(overflow / 3))
            if end <= cursor:
                raise ValueError("context page budget cannot contain one UTF-8 character")
            content = text[cursor:end]
        pages.append(content)
        cursor = end
    return pages


def _page_entries(
    fragment_name: str,
    source_path: str,
    payload: bytes,
) -> list[tuple[str, bytes, dict[str, object]]]:
    contents = _content_pages(payload)
    page_count = len(contents)
    result: list[tuple[str, bytes, dict[str, object]]] = []
    for order, content in enumerate(contents, start=1):
        path = _page_path(source_path, order)
        page_payload = _page_payload(fragment_name, order, page_count, content)
        estimated_tokens = len(content.encode("utf-8"))
        if len(page_payload) > PAGE_BYTE_BUDGET or estimated_tokens > PAGE_TOKEN_BUDGET:
            raise ValueError("context page exceeds its deterministic budget")
        result.append(
            (
                path,
                page_payload,
                {
                    "bytes": len(page_payload),
                    "estimatedTokens": estimated_tokens,
                    "order": order,
                    "path": path,
                    "sha256": sha256_bytes(page_payload),
                },
            )
        )
    return result


def write_context_fragment(
    files: ProjectFiles,
    name: str,
    path: str,
    value: object,
) -> dict[str, object]:
    payload = canonical_json_bytes(value)
    files.write_atomic(path, payload)
    entries = _page_entries(name, path, payload)
    for page_path, page_payload, _ in entries:
        files.write_atomic(page_path, page_payload)
    return {
        "bytes": len(payload),
        "name": name,
        "pages": [entry for _, _, entry in entries],
        "path": path,
        "sha256": sha256_bytes(payload),
    }


def write_review_claims(
    files: ProjectFiles,
    path: str,
    claims: Mapping[str, Any],
) -> dict[str, object]:
    if claims.get("status") == "PENDING_CANDIDATE":
        return {"path": path, "status": "PENDING_CANDIDATE"}
    return {
        "fragment": write_context_fragment(files, "claims", path, claims),
        "status": "READY",
    }


def expected_review_claims(
    files: ProjectFiles,
    path: str,
) -> dict[str, object]:
    return {
        "fragment": expected_context_fragment(files, "claims", path),
        "status": "READY",
    }


def expected_context_fragment(
    files: ProjectFiles,
    name: str,
    path: str,
) -> dict[str, object]:
    payload = files.read_bytes(path)
    try:
        value = canonical_json_bytes(json.loads(payload.decode("utf-8")))
    except (UnicodeDecodeError, ValueError) as error:
        raise ProjectIOError(
            "CONTEXT_FRAGMENT_INVALID",
            path,
            f"context fragment is not canonical JSON: {path}",
        ) from error
    if value != payload:
        raise ProjectIOError(
            "CONTEXT_FRAGMENT_INVALID",
            path,
            f"context fragment is not canonical JSON: {path}",
        )
    entries = _page_entries(name, path, payload)
    for page_path, expected_payload, _ in entries:
        actual = files.read_bytes(page_path)
        if actual != expected_payload:
            raise ProjectIOError(
                "CONTEXT_PAGE_STALE",
                page_path,
                f"context page does not match its source fragment: {page_path}",
            )
    return {
        "bytes": len(payload),
        "name": name,
        "pages": [entry for _, _, entry in entries],
        "path": path,
        "sha256": sha256_bytes(payload),
    }


def write_context_fragments(
    files: ProjectFiles,
    specs: Sequence[tuple[str, str]],
    fragments: Mapping[str, Any],
) -> list[dict[str, object]]:
    return [
        write_context_fragment(files, name, path, fragments[name])
        for name, path in specs
    ]


def expected_context_fragments(
    files: ProjectFiles,
    specs: Sequence[tuple[str, str]],
) -> list[dict[str, object]]:
    return [expected_context_fragment(files, name, path) for name, path in specs]
