from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from runtime.claims import NARRATIVE_FIELDS, build_claims, validate_claims, verified_claims
from runtime.diagnostics import diagnostic
from runtime.fact_source import validate_unique_fact_sources
from runtime.handoff import canonical_json_bytes
from runtime.project_io import ProjectFiles, ProjectIOError
from runtime.text_gates import text_fields, validate_text_gates


def existing_claims(
    files: ProjectFiles,
    claims_path: str,
) -> list[Mapping[str, Any]]:
    try:
        value = files.read_json(claims_path)
    except ProjectIOError as error:
        if error.code == "PROJECT_PATH_MISSING":
            return []
        raise
    claims = value.get("claims", []) if isinstance(value, dict) else []
    return [claim for claim in claims if isinstance(claim, dict)] if isinstance(claims, list) else []


def cached_verified_claims(
    files: ProjectFiles,
    claims_path: str,
    validation_path: str | None = None,
) -> list[dict[str, object]]:
    cached: dict[str, dict[str, object]] = {}
    if validation_path is not None:
        try:
            report = files.read_json(validation_path)
        except ProjectIOError as error:
            if error.code not in {"PROJECT_PATH_MISSING", "PROJECT_JSON_INVALID"}:
                raise
        else:
            receipt = report.get("compilationReceipt", {}) if isinstance(report, dict) else {}
            values = receipt.get("verifiedClaims", []) if isinstance(receipt, dict) else []
            if isinstance(values, list):
                for value in values:
                    if isinstance(value, dict) and isinstance(value.get("claimId"), str):
                        cached[value["claimId"]] = dict(value)
    try:
        for value in verified_claims(files.read_json(claims_path)):
            if isinstance(value.get("claimId"), str):
                cached[value["claimId"]] = value
    except ProjectIOError as error:
        if error.code not in {"PROJECT_PATH_MISSING", "PROJECT_JSON_INVALID"}:
            raise
    return list(cached.values())


def prepare_claims(
    files: ProjectFiles,
    project_root: Path,
    owner: str,
    document_specs: Sequence[tuple[str, str]],
    output_path: str,
    *,
    required: bool = False,
    validation_path: str | None = None,
    anchor_documents: Sequence[Mapping[str, Any]] = (),
) -> dict[str, object]:
    """Write deterministic claims when all candidate documents are available."""

    documents: list[tuple[str, Mapping[str, Any]]] = []
    for name, path in document_specs:
        try:
            value = files.read_json(path)
        except ProjectIOError as error:
            if error.code == "PROJECT_PATH_MISSING" and not required:
                claims: dict[str, object] = {
                    "algorithm": "ai-sow-review-claims-v1",
                    "owner": owner,
                    "claims": [],
                }
                files.write_atomic(output_path, canonical_json_bytes(claims))
                return claims
            raise
        if not isinstance(value, dict):
            raise ValueError(f"claim source must be a JSON object: {path}")
        documents.append((name, value))
    previous_verified = cached_verified_claims(files, output_path, validation_path)
    previous_claims = existing_claims(files, output_path)
    claims = build_claims(
        owner,
        documents,
        project_root=project_root,
        previous_verified=previous_verified,
        previous_claims=previous_claims,
        anchor_documents=anchor_documents,
    )
    files.write_atomic(output_path, canonical_json_bytes(claims))
    return claims


def validate_review_artifacts(
    files: ProjectFiles,
    project_root: Path,
    owner: str,
    claims_path: str,
    documents: Mapping[str, object],
) -> list[dict[str, object]]:
    """Run the shared claim, path, absolute/count, and unique-fact gates."""

    try:
        payload = files.read_bytes(claims_path)
        claims = json.loads(payload.decode("utf-8"))
    except ProjectIOError as error:
        return [diagnostic(error.code, str(error), error.relative_path)]
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return [diagnostic("CLAIMS_INVALID", str(error), claims_path)]
    if canonical_json_bytes(claims) != payload:
        return [diagnostic("CLAIMS_INVALID", "claims JSON must use canonical bytes", claims_path)]

    diagnostics = validate_claims(claims, owner, documents)
    anchors: list[dict[str, object]] = []
    factual_paths: set[str] = set()
    if isinstance(claims, dict) and isinstance(claims.get("claims"), list):
        for claim in claims["claims"]:
            if not isinstance(claim, dict) or not isinstance(claim.get("ownerField"), str):
                continue
            if claim.get("kind") == "FACTUAL":
                factual_paths.add(claim["ownerField"])
            for anchor in claim.get("anchors", []):
                if (
                    isinstance(anchor, dict)
                    and isinstance(anchor.get("glob"), str)
                    and isinstance(anchor.get("expected"), int)
                ):
                    anchors.append({**anchor, "path": claim["ownerField"]})
    fields = text_fields(documents, fields=NARRATIVE_FIELDS)
    diagnostics.extend(
        validate_text_gates(
            project_root,
            fields,
            count_anchors=anchors,
            absolute_claim_paths=factual_paths,
        )
    )
    diagnostics.extend(validate_unique_fact_sources(fields))
    return diagnostics
