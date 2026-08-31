from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from runtime.claims import NARRATIVE_FIELDS, build_claims, validate_claims, verified_claims
from runtime.diagnostics import diagnostic
from runtime.fact_source import validate_unique_fact_sources
from runtime.handoff import canonical_json_bytes, sha256_bytes
from runtime.project_io import ProjectFiles, ProjectIOError
from runtime.text_gates import text_fields, validate_text_gates


REVIEW_JUDGMENT_ALGORITHM = "ai-sow-owner-review-judgment-v1"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def artifact_metrics(documents: Mapping[str, object]) -> dict[str, object]:
    """Return deterministic candidate counts for user-visible stage summaries."""

    projected: dict[str, object] = {}
    for name in sorted(documents):
        document = documents[name]
        if not isinstance(document, Mapping):
            continue
        projected[name] = {
            "canonicalSha256": sha256_bytes(canonical_json_bytes(document)),
            "collections": {
                key: len(value)
                for key, value in sorted(document.items())
                if isinstance(value, list)
            },
        }
    return {
        "algorithm": "ai-sow-artifact-metrics-v1",
        "documents": projected,
    }


def record_reviewer_judgment(
    files: ProjectFiles,
    *,
    owner: str,
    packet_sha256: str,
    decision: str,
    finding_ids: Sequence[str],
    journal_directory: str,
    reviewer_path: str,
    reviewer_algorithm: str,
) -> tuple[list[dict[str, object]], list[str], str]:
    """Freeze the first judgment for a packet and optionally bind a PASS sidecar."""

    diagnostics: list[dict[str, object]] = []
    normalized_findings = sorted(set(finding_ids))
    if SHA256_PATTERN.fullmatch(packet_sha256) is None:
        diagnostics.append(
            diagnostic(
                "PACKET_SHA256_INVALID",
                "--packet-sha256 must be exactly 64 lowercase hexadecimal characters",
            )
        )
    if decision not in {"PASS", "BLOCKED"}:
        diagnostics.append(
            diagnostic(
                "REVIEW_DECISION_INVALID",
                "--review-decision must be PASS or BLOCKED",
            )
        )
    if any(not isinstance(value, str) or not value.strip() for value in finding_ids):
        diagnostics.append(
            diagnostic(
                "REVIEW_FINDING_IDS_INVALID",
                "--finding-id values must be non-empty strings",
            )
        )
    if len(normalized_findings) != len(finding_ids):
        diagnostics.append(
            diagnostic(
                "REVIEW_FINDING_IDS_INVALID",
                "--finding-id values must be unique",
            )
        )
    if decision == "PASS" and normalized_findings:
        diagnostics.append(
            diagnostic(
                "REVIEW_FINDING_IDS_INVALID",
                "PASS cannot include finding IDs",
            )
        )
    if decision == "BLOCKED" and not normalized_findings:
        diagnostics.append(
            diagnostic(
                "REVIEW_FINDING_IDS_REQUIRED",
                "BLOCKED requires at least one --finding-id",
            )
        )

    judgment_path = f"{journal_directory.rstrip('/')}/{packet_sha256}.json"
    if diagnostics:
        return diagnostics, [], judgment_path

    judgment = {
        "algorithm": REVIEW_JUDGMENT_ALGORITHM,
        "decision": decision,
        "findingIds": normalized_findings,
        "owner": owner,
        "packetSha256": packet_sha256,
    }
    payload = canonical_json_bytes(judgment)
    try:
        current = files.read_bytes(judgment_path)
    except ProjectIOError as error:
        if error.code != "PROJECT_PATH_MISSING":
            return [diagnostic(error.code, str(error), error.relative_path)], [], judgment_path
        files.write_atomic(judgment_path, payload)
    else:
        if current != payload:
            try:
                previous = json.loads(current.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                previous = {}
            return [
                diagnostic(
                    "REVIEW_JUDGMENT_CONFLICT",
                    "the first judgment for this packet is immutable; new evidence must produce a new packet hash",
                    judgmentPath=judgment_path,
                    previousDecision=previous.get("decision"),
                    attemptedDecision=decision,
                )
            ], [], judgment_path

    outputs = [judgment_path]
    if decision == "PASS":
        files.write_atomic(
            reviewer_path,
            canonical_json_bytes(
                {
                    "algorithm": reviewer_algorithm,
                    "decision": "PASS",
                    "owner": owner,
                    "packetSha256": packet_sha256,
                }
            ),
        )
        outputs.append(reviewer_path)
    return [], outputs, judgment_path


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
                return {
                    "algorithm": "ai-sow-review-claims-v1",
                    "owner": owner,
                    "status": "PENDING_CANDIDATE",
                }
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
    evidence_anchor_paths: set[str] = set()
    if isinstance(claims, dict) and isinstance(claims.get("claims"), list):
        for claim in claims["claims"]:
            if not isinstance(claim, dict) or not isinstance(claim.get("ownerField"), str):
                continue
            if claim.get("kind") == "FACTUAL":
                factual_paths.add(claim["ownerField"])
                if claim.get("anchors"):
                    evidence_anchor_paths.add(claim["ownerField"])
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
            evidence_anchor_paths=evidence_anchor_paths,
        )
    )
    diagnostics.extend(validate_unique_fact_sources(fields))
    return diagnostics
