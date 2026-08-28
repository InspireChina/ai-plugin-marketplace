from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from runtime.diagnostics import diagnostic
from runtime.handoff import sha256_bytes


NARRATIVE_FIELDS = {
    "description",
    "statement",
    "summary",
    "rationale",
    "impact",
    "question",
    "recommendedHandling",
    "decision",
    "purpose",
    "trigger",
    "responsibilityBoundary",
    "handling",
    "workModeRationale",
    "complexityRationale",
}
FACTUAL_PARENT_COLLECTIONS = {"evidence", "sourceDocuments"}


def _claim_id(owner: str, owner_field: str, text: str) -> str:
    digest = hashlib.sha256(f"{owner}\0{owner_field}\0{text}".encode()).hexdigest()[:16]
    return f"claim-{digest}"


def _anchor_sha(project_root: Path | None, path: str) -> str | None:
    if project_root is None or not path or Path(path).is_absolute() or ".." in Path(path).parts:
        return None
    resolved = (project_root / path).resolve()
    if not resolved.is_relative_to(project_root.resolve()) or not resolved.is_file():
        return None
    return sha256_bytes(resolved.read_bytes())


def build_claims(
    owner: str,
    documents: Sequence[tuple[str, Mapping[str, Any]]],
    *,
    project_root: Path | None = None,
    previous_verified: Sequence[Mapping[str, Any]] = (),
    previous_claims: Sequence[Mapping[str, Any]] = (),
    anchor_documents: Sequence[Mapping[str, Any]] = (),
) -> dict[str, object]:
    """Project narrative fields into deterministic, independently verifiable claims."""

    previous = {
        value.get("claimId"): value
        for value in previous_verified
        if isinstance(value.get("claimId"), str)
    }
    previous_projection = {
        value.get("claimId"): value
        for value in previous_claims
        if isinstance(value.get("claimId"), str)
    }
    claims: list[dict[str, object]] = []
    source_files: dict[str, str] = {}
    normalized_sources: dict[str, str] = {}
    evidence_anchors: dict[str, str] = {}
    supported_anchors: dict[str, list[str]] = {}
    repository_paths: dict[str, str] = {}
    prior_sow_paths: dict[str, str] = {}

    def index_sources(value: object) -> None:
        if isinstance(value, dict):
            source_id = value.get("sourceDocumentId")
            source_file = value.get("file")
            if isinstance(source_id, str) and isinstance(source_file, str):
                source_files[source_id] = source_file
            normalized_id = value.get("normalizedItemId")
            if isinstance(normalized_id, str) and isinstance(source_id, str):
                normalized_sources[normalized_id] = source_id
            evidence_id = value.get("evidenceId")
            reference = value.get("reference")
            if isinstance(evidence_id, str) and isinstance(reference, str):
                evidence_anchors[evidence_id] = reference
                supports = value.get("supportsIds", [])
                if isinstance(supports, list):
                    for supported in supports:
                        if isinstance(supported, str):
                            supported_anchors.setdefault(supported, []).append(reference)
            repo_id = value.get("repoId")
            repo_path = value.get("path")
            if isinstance(repo_id, str) and isinstance(repo_path, str):
                repository_paths[repo_id] = repo_path
            prior_sow_id = value.get("priorSowId")
            prior_sow_file = value.get("file")
            if isinstance(prior_sow_id, str) and isinstance(prior_sow_file, str):
                prior_sow_paths[prior_sow_id] = prior_sow_file
            for child in value.values():
                index_sources(child)
        elif isinstance(value, list):
            for child in value:
                index_sources(child)

    for _, document in documents:
        index_sources(document)
    for document in anchor_documents:
        index_sources(document)

    def anchor_file(anchor_path: str) -> str:
        logical = anchor_path.split("#", 1)[0]
        prior_match = re.fullmatch(r"prior-sow:([a-z][a-z0-9-]*)", logical)
        if prior_match and prior_match.group(1) in prior_sow_paths:
            return prior_sow_paths[prior_match.group(1)]
        repository_match = re.fullmatch(r"([a-z][a-z0-9-]*):(.+)", logical)
        if repository_match and repository_match.group(1) in repository_paths:
            base = repository_paths[repository_match.group(1)]
            anchor = repository_match.group(2)
            return anchor if base == "." else f"{base}/{anchor}"
        return logical

    def object_anchor_paths(value: Mapping[str, Any]) -> list[str]:
        result: list[str] = []
        for anchor_key in ("reference", "sourceReference", "file"):
            anchor_path = value.get(anchor_key)
            if isinstance(anchor_path, str):
                result.append(anchor_path)
        source_ids: list[str] = []
        source_id = value.get("sourceDocumentId")
        if isinstance(source_id, str):
            source_ids.append(source_id)
        direct_source_ids = value.get("sourceDocumentIds", [])
        if isinstance(direct_source_ids, list):
            source_ids.extend(item for item in direct_source_ids if isinstance(item, str))
        source = value.get("source")
        if isinstance(source, Mapping):
            nested_source_ids = source.get("sourceDocumentIds", [])
            if isinstance(nested_source_ids, list):
                source_ids.extend(item for item in nested_source_ids if isinstance(item, str))
            normalized_ids = source.get("normalizedItemIds", [])
            if isinstance(normalized_ids, list):
                source_ids.extend(
                    normalized_sources[item]
                    for item in normalized_ids
                    if isinstance(item, str) and item in normalized_sources
                )
        result.extend(source_files[item] for item in source_ids if item in source_files)
        evidence_ids = value.get("evidenceIds", [])
        if isinstance(evidence_ids, list):
            result.extend(
                evidence_anchors[item]
                for item in evidence_ids
                if isinstance(item, str) and item in evidence_anchors
            )
        for key, item in value.items():
            if key.endswith("Id") and isinstance(item, str):
                result.extend(supported_anchors.get(item, []))
        return list(dict.fromkeys(result))

    def walk(value: object, path: str, parents: tuple[str, ...]) -> None:
        if isinstance(value, dict):
            related_anchor_paths = object_anchor_paths(value)
            for key, child in value.items():
                child_path = f"{path}/{key}"
                if isinstance(child, str) and key in NARRATIVE_FIELDS:
                    anchors: list[dict[str, object]] = []
                    for anchor_path in related_anchor_paths:
                        anchor: dict[str, object] = {"path": anchor_path}
                        anchor_sha = _anchor_sha(project_root, anchor_file(anchor_path))
                        if anchor_sha:
                            anchor["anchorSha256"] = anchor_sha
                        anchors.append(anchor)
                    source_id = value.get("sourceDocumentId")
                    if not anchors and isinstance(source_id, str) and source_id in source_files:
                        anchor_path = source_files[source_id]
                        anchor = {"path": anchor_path}
                        anchor_sha = _anchor_sha(project_root, anchor_file(anchor_path))
                        if anchor_sha:
                            anchor["anchorSha256"] = anchor_sha
                        anchors.append(anchor)
                    kind = "FACTUAL" if anchors or any(parent in FACTUAL_PARENT_COLLECTIONS for parent in parents) else "JUDGMENT"
                    claim_id = _claim_id(owner, child_path, child)
                    claim: dict[str, object] = {
                        "claimId": claim_id,
                        "ownerField": child_path,
                        "text": child,
                        "anchors": anchors,
                        "kind": kind,
                        "confidence": "HIGH" if anchors else "LOW",
                    }
                    prior = previous_projection.get(claim_id)
                    if isinstance(prior, Mapping) and prior.get("text") == child:
                        prior_anchors = prior.get("anchors")
                        if isinstance(prior_anchors, list) and all(
                            isinstance(item, Mapping)
                            and isinstance(item.get("path"), str)
                            for item in prior_anchors
                        ):
                            refreshed: list[dict[str, object]] = []
                            for item in prior_anchors:
                                anchor = dict(item)
                                anchor_sha = _anchor_sha(
                                    project_root,
                                    anchor_file(str(anchor["path"])),
                                )
                                if anchor_sha:
                                    anchor["anchorSha256"] = anchor_sha
                                else:
                                    anchor.pop("anchorSha256", None)
                                refreshed.append(anchor)
                            claim["anchors"] = refreshed
                            anchors = refreshed
                        if prior.get("kind") in {"FACTUAL", "JUDGMENT", "COMPLETENESS"}:
                            claim["kind"] = prior["kind"]
                        if prior.get("confidence") in {"HIGH", "LOW"}:
                            claim["confidence"] = prior["confidence"]
                        if isinstance(prior.get("derivedFrom"), str):
                            claim["derivedFrom"] = prior["derivedFrom"]
                    cached = previous.get(claim_id)
                    current_anchor = anchors[0] if anchors else {}
                    if (
                        cached
                        and cached.get("textSha256") == sha256_bytes(child.encode("utf-8"))
                        and cached.get("anchorPath") == current_anchor.get("path")
                        and cached.get("anchorSha256") == current_anchor.get("anchorSha256")
                    ):
                        claim["verification"] = {
                            **cached,
                            "lineReference": f"cached:{cached.get('anchorPath', '')}",
                        }
                    claims.append(claim)
                elif isinstance(child, (dict, list)):
                    walk(child, child_path, parents + (key,))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}/{index}", parents)

    for name, document in documents:
        walk(document, f"/{name}", (name,))
    return {"algorithm": "ai-sow-review-claims-v1", "owner": owner, "claims": claims}


def claim_metrics(value: object) -> dict[str, object]:
    claims = value.get("claims", []) if isinstance(value, dict) else []
    if not isinstance(claims, list):
        claims = []
    verified: list[str] = []
    remaining: list[str] = []
    for claim in claims:
        if not isinstance(claim, dict) or not isinstance(claim.get("claimId"), str):
            continue
        verification = claim.get("verification")
        if isinstance(verification, dict) and verification.get("verdict") == "PASS":
            verified.append(claim["claimId"])
        else:
            remaining.append(claim["claimId"])
    return {
        "totalClaims": len(verified) + len(remaining),
        "verifiedClaims": len(verified),
        "unverifiedClaims": len(remaining),
        "remainingClaimIds": sorted(remaining),
    }


def _resolve_pointer(documents: Mapping[str, object], pointer: str) -> object:
    parts = [part.replace("~1", "/").replace("~0", "~") for part in pointer.strip("/").split("/")]
    if not parts or parts[0] not in documents:
        raise KeyError(pointer)
    current: object = documents[parts[0]]
    for part in parts[1:]:
        current = current[int(part)] if isinstance(current, list) else current[part]  # type: ignore[index]
    return current


def validate_claims(
    value: object,
    owner: str,
    documents: Mapping[str, object],
) -> list[dict[str, object]]:
    diagnostics: list[dict[str, object]] = []
    if not isinstance(value, dict) or value.get("algorithm") != "ai-sow-review-claims-v1" or value.get("owner") != owner:
        return [diagnostic("CLAIMS_INVALID", "claims use the wrong algorithm or owner")]
    claims = value.get("claims")
    if not isinstance(claims, list):
        return [diagnostic("CLAIMS_INVALID", "claims must be an array")]
    seen: set[str] = set()
    for index, claim in enumerate(claims):
        path = f"claims[{index}]"
        if not isinstance(claim, dict):
            diagnostics.append(diagnostic("CLAIMS_INVALID", "claim must be an object", path))
            continue
        claim_id = claim.get("claimId")
        owner_field = claim.get("ownerField")
        text = claim.get("text")
        if not isinstance(claim_id, str) or not re.fullmatch(r"claim-[0-9a-f]{16}", claim_id):
            diagnostics.append(diagnostic("CLAIMS_INVALID", "claimId is invalid", path))
        elif claim_id in seen:
            diagnostics.append(diagnostic("CLAIMS_INVALID", "claimId is duplicated", path))
        else:
            seen.add(claim_id)
        if not isinstance(owner_field, str) or not isinstance(text, str):
            diagnostics.append(diagnostic("CLAIMS_INVALID", "ownerField and text are required", path))
            continue
        try:
            if _resolve_pointer(documents, owner_field) != text:
                diagnostics.append(diagnostic("CLAIM_SOURCE_STALE", "claim text does not match its owner field", path))
        except (KeyError, IndexError, TypeError):
            diagnostics.append(diagnostic("CLAIM_SOURCE_STALE", "claim owner field cannot be resolved", path))
        if claim.get("kind") not in {"FACTUAL", "JUDGMENT", "COMPLETENESS"}:
            diagnostics.append(diagnostic("CLAIMS_INVALID", "claim kind is invalid", path))
        if claim.get("confidence") not in {"HIGH", "LOW"}:
            diagnostics.append(diagnostic("CLAIMS_INVALID", "claim confidence is invalid", path))
        anchors = claim.get("anchors")
        if not isinstance(anchors, list) or any(
            not isinstance(anchor, dict)
            or not isinstance(anchor.get("path"), str)
            or not anchor["path"]
            or not set(anchor).issubset(
                {"path", "glob", "expr", "expected", "anchorSha256"}
            )
            or (
                set(anchor) & {"glob", "expr", "expected"}
                and not {"glob", "expr", "expected"}.issubset(anchor)
            )
            or ("glob" in anchor and not isinstance(anchor["glob"], str))
            or ("expr" in anchor and not isinstance(anchor["expr"], str))
            or (
                "expected" in anchor
                and (
                    not isinstance(anchor["expected"], int)
                    or isinstance(anchor["expected"], bool)
                    or anchor["expected"] < 0
                )
            )
            or (
                "anchorSha256" in anchor
                and (
                    not isinstance(anchor["anchorSha256"], str)
                    or not re.fullmatch(r"[0-9a-f]{64}", anchor["anchorSha256"])
                )
            )
            for anchor in anchors
        ):
            diagnostics.append(diagnostic("CLAIMS_INVALID", "claim anchors are invalid", path))
        if claim.get("kind") == "FACTUAL" and not anchors:
            diagnostics.append(diagnostic("CLAIM_ANCHOR_MISSING", "factual claim requires an anchor", path))
        derived_from = claim.get("derivedFrom")
        if derived_from is not None and (
            not isinstance(derived_from, str)
            or not re.fullmatch(r"premise-[a-z0-9]+(?:-[a-z0-9]+)*", derived_from)
        ):
            diagnostics.append(diagnostic("CLAIMS_INVALID", "derivedFrom is invalid", path))
        verification = claim.get("verification")
        if (
            isinstance(verification, dict)
            and verification.get("verdict") == "PASS"
            and not isinstance(verification.get("lineReference"), str)
        ):
            diagnostics.append(
                diagnostic(
                    "CLAIM_PASS_LINE_MISSING",
                    "PASS verification requires an original line reference",
                    path,
                )
            )
    expected = build_claims(owner, list(documents.items()))
    expected_ids = {
        claim["claimId"]
        for claim in expected["claims"]
        if isinstance(claim, dict) and isinstance(claim.get("claimId"), str)
    }
    if seen != expected_ids:
        diagnostics.append(
            diagnostic(
                "CLAIMS_INCOMPLETE",
                "claims must cover every projected narrative field exactly once",
                missingClaimIds=sorted(expected_ids - seen),
                unexpectedClaimIds=sorted(seen - expected_ids),
            )
        )
    return diagnostics


def verified_claims(value: object) -> list[dict[str, object]]:
    if not isinstance(value, dict) or not isinstance(value.get("claims"), list):
        return []
    result: list[dict[str, object]] = []
    for claim in value["claims"]:
        if not isinstance(claim, dict) or not isinstance(claim.get("verification"), dict):
            continue
        verification = claim["verification"]
        if verification.get("verdict") != "PASS":
            continue
        anchor_path = ""
        anchor_sha = verification.get("anchorSha256", "")
        anchors = claim.get("anchors", [])
        if isinstance(anchors, list) and anchors and isinstance(anchors[0], dict):
            anchor_path = str(anchors[0].get("path", ""))
            anchor_sha = anchor_sha or anchors[0].get("anchorSha256", "")
        if (
            not anchor_path
            or not isinstance(anchor_sha, str)
            or not re.fullmatch(r"[0-9a-f]{64}", anchor_sha)
            or not verification.get("verifiedBy")
            or not verification.get("verifierModel")
        ):
            continue
        result.append(
            {
                "claimId": claim["claimId"],
                "textSha256": sha256_bytes(str(claim["text"]).encode("utf-8")),
                "anchorPath": anchor_path,
                "anchorSha256": anchor_sha,
                "verdict": "PASS",
                "verifiedBy": verification.get("verifiedBy", ""),
                "verifierModel": verification.get("verifierModel", ""),
            }
        )
    return result
