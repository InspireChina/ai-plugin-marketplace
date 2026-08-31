from __future__ import annotations

import argparse
import copy
import json
import re
import secrets
import shutil
import sys
from collections import defaultdict, deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from runtime.authorization import plan_review_packet_rotation, publish_file_transaction
from runtime.diagnostics import diagnostic
from runtime.handoff import canonical_json_bytes, sha256_bytes
from runtime.project_io import ProjectFiles, ProjectIOError


STABLE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)+$")
DIFF_REVIEW_BYTE_BUDGET = 65_536
PatchPostCheck = Callable[[Path, str], list[dict[str, object]]]


def _tokens(pointer: str) -> list[str]:
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise ValueError("JSON pointer must start with /")
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]


def _parent(document: object, pointer: str) -> tuple[object, str]:
    tokens = _tokens(pointer)
    if not tokens:
        raise ValueError("the document root cannot be patched")
    current: object = document
    for token in tokens[:-1]:
        if isinstance(current, list):
            current = current[int(token)]
        elif isinstance(current, dict):
            current = current[token]
        else:
            raise ValueError(f"pointer does not resolve: {pointer}")
    return current, tokens[-1]


def apply_operations(document: object, operations: Sequence[Mapping[str, Any]]) -> object:
    """Apply a deterministic replace/add/remove JSON patch subset."""

    result = copy.deepcopy(document)
    for operation in operations:
        op = operation.get("op")
        pointer = operation.get("path")
        if op not in {"replace", "add", "remove"} or not isinstance(pointer, str):
            raise ValueError("patch operations require op replace/add/remove and a JSON pointer path")
        parent, token = _parent(result, pointer)
        if isinstance(parent, list):
            index = len(parent) if token == "-" else int(token)
            if op == "add":
                parent.insert(index, copy.deepcopy(operation.get("value")))
            elif op == "replace":
                parent[index] = copy.deepcopy(operation.get("value"))
            else:
                parent.pop(index)
        elif isinstance(parent, dict):
            if op in {"replace", "remove"} and token not in parent:
                raise ValueError(f"patch path does not exist: {pointer}")
            if op == "remove":
                del parent[token]
            else:
                parent[token] = copy.deepcopy(operation.get("value"))
        else:
            raise ValueError(f"patch parent is not a collection: {pointer}")
    return result


def changed_paths(before: object, after: object, path: str = "") -> set[str]:
    if type(before) is not type(after):
        return {path or "/"}
    if isinstance(before, dict) and isinstance(after, dict):
        result: set[str] = set()
        for key in before.keys() | after.keys():
            child = f"{path}/{key}"
            if key not in before or key not in after:
                result.add(child)
            else:
                result.update(changed_paths(before[key], after[key], child))
        return result
    if isinstance(before, list) and isinstance(after, list):
        result: set[str] = set()
        for index in range(max(len(before), len(after))):
            child = f"{path}/{index}"
            if index >= len(before) or index >= len(after):
                result.add(child)
            else:
                result.update(changed_paths(before[index], after[index], child))
        return result
    return set() if before == after else {path or "/"}


def _object_registry(value: object, path: str = "") -> tuple[dict[str, str], dict[str, set[str]]]:
    paths: dict[str, str] = {}
    refs: dict[str, set[str]] = defaultdict(set)
    if isinstance(value, dict):
        primary = next(
            (
                child
                for key, child in value.items()
                if key.endswith("Id")
                and not key.endswith("Ids")
                and isinstance(child, str)
                and STABLE_ID_PATTERN.fullmatch(child)
            ),
            None,
        )
        direct_refs: set[str] = set()
        for key, child in value.items():
            if key.endswith("Id") and isinstance(child, str) and child != primary:
                if STABLE_ID_PATTERN.fullmatch(child):
                    direct_refs.add(child)
            elif key.endswith("Ids") and isinstance(child, list):
                direct_refs.update(
                    item
                    for item in child
                    if isinstance(item, str) and STABLE_ID_PATTERN.fullmatch(item)
                )
        identity = primary or (f"@{path or '/'}" if direct_refs else None)
        if identity:
            paths[identity] = path or "/"
            refs[identity].update(direct_refs)
        for key, child in value.items():
            child_paths, child_refs = _object_registry(child, f"{path}/{key}")
            paths.update(child_paths)
            for owner, values in child_refs.items():
                refs[owner].update(values)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_paths, child_refs = _object_registry(child, f"{path}/{index}")
            paths.update(child_paths)
            for owner, values in child_refs.items():
                refs[owner].update(values)
    return paths, refs


def reference_closure(document: object, changed: Iterable[str]) -> tuple[set[str], dict[str, str]]:
    paths, refs = _object_registry(document)
    owned_ids = set(paths)
    reverse: dict[str, set[str]] = defaultdict(set)
    for owner, targets in refs.items():
        for target in targets:
            reverse[target].add(owner)
    closure = set(changed)
    queue = deque(changed)
    while queue:
        current = queue.popleft()
        for related in refs.get(current, set()) | reverse.get(current, set()):
            if related in owned_ids and related not in closure:
                closure.add(related)
                queue.append(related)
    return closure, paths


def _ids_under_changed_paths(document: object, paths: Iterable[str]) -> set[str]:
    registry, _ = _object_registry(document)
    changed = set(paths)
    return {
        identifier
        for identifier, object_path in registry.items()
        if any(
            path == object_path
            or path.startswith(object_path.rstrip("/") + "/")
            or object_path.startswith(path.rstrip("/") + "/")
            for path in changed
        )
    }


def _direct_reference_closure(document: object, changed: Iterable[str]) -> set[str]:
    object_paths, refs = _object_registry(document)
    owned_ids = set(object_paths)
    reverse: dict[str, set[str]] = defaultdict(set)
    for owner, targets in refs.items():
        for target in targets:
            reverse[target].add(owner)
    result: set[str] = set()
    for identifier in changed:
        result.update(refs.get(identifier, set()))
        result.update(reverse.get(identifier, set()))
    return result & owned_ids


def _pointer_value(document: object, pointer: str) -> object:
    current = document
    try:
        for token in _tokens(pointer):
            current = current[int(token)] if isinstance(current, list) else current[token]  # type: ignore[index]
    except (IndexError, KeyError, TypeError, ValueError):
        return {"status": "ABSENT"}
    return current


def _acceptance_mappings(document: object, relevant_ids: set[str]) -> list[dict[str, str]]:
    story_features: dict[str, str] = {}
    criteria: list[tuple[str, str]] = []

    def walk(value: object) -> None:
        if isinstance(value, dict):
            story_id = value.get("storyId")
            feature_id = value.get("featureId")
            criterion_id = value.get("acceptanceCriterionId")
            if isinstance(story_id, str) and isinstance(feature_id, str):
                story_features[story_id] = feature_id
            if isinstance(criterion_id, str) and isinstance(story_id, str):
                criteria.append((criterion_id, story_id))
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(document)
    result: list[dict[str, str]] = []
    for criterion_id, story_id in criteria:
        feature_id = story_features.get(story_id, "")
        if relevant_ids & {criterion_id, story_id, feature_id}:
            result.append(
                {
                    "acceptanceCriterionId": criterion_id,
                    "featureId": feature_id,
                    "storyId": story_id,
                }
            )
    return sorted(result, key=lambda item: (item["storyId"], item["acceptanceCriterionId"]))


def _diff_review(
    before: object,
    after: object,
    paths: Sequence[str],
    changed_ids: set[str],
) -> dict[str, object]:
    direct_closure = _direct_reference_closure(after, changed_ids)
    relevant_ids = changed_ids | direct_closure
    content: dict[str, object] = {
        "acceptanceMappings": _acceptance_mappings(after, relevant_ids),
        "byteBudget": DIFF_REVIEW_BYTE_BUDGET,
        "changedFields": [
            {
                "after": _pointer_value(after, path),
                "before": _pointer_value(before, path),
                "path": path,
            }
            for path in paths
        ],
        "changedIds": sorted(changed_ids),
        "directClosureIds": sorted(direct_closure),
    }
    return {**content, "payloadBytes": len(canonical_json_bytes(content))}


def patch_audit(
    before: object,
    after: object,
    patch: Mapping[str, Any],
) -> dict[str, object]:
    operations = patch.get("operations", [])
    if not isinstance(operations, list):
        raise ValueError("patch operations must be an array")
    expected = apply_operations(before, operations)
    actual_paths = sorted(changed_paths(before, after))
    expected_paths = sorted(changed_paths(before, expected))
    changed_ids = _ids_under_changed_paths(after, actual_paths)
    closure, object_paths = reference_closure(after, changed_ids)
    acknowledged = {
        value
        for value in patch.get("acknowledgedClosureIds", [])
        if isinstance(value, str)
    }
    suspects = sorted(
        identifier
        for identifier in closure - changed_ids
        if identifier in object_paths and identifier not in acknowledged
    )
    diff_review = _diff_review(before, after, actual_paths, changed_ids)
    return {
        "algorithm": "ai-sow-field-patch-v1",
        "beforeSha256": sha256_bytes(canonical_json_bytes(before)),
        "afterSha256": sha256_bytes(canonical_json_bytes(after)),
        "expectedAfterSha256": sha256_bytes(canonical_json_bytes(expected)),
        "changedPaths": actual_paths,
        "expectedChangedPaths": expected_paths,
        "changedIds": sorted(changed_ids),
        "closureIds": sorted(closure),
        "syncSuspects": suspects,
        "diffReview": diff_review,
    }


def validate_patch_audit(
    before: object,
    candidate: object,
    patch: Mapping[str, Any],
) -> list[dict[str, object]]:
    audit = patch_audit(before, candidate, patch)
    diagnostics: list[dict[str, object]] = []
    if audit["afterSha256"] != audit["expectedAfterSha256"]:
        diagnostics.append(
            diagnostic(
                "PATCH_FREEFORM_EDIT_DETECTED",
                "candidate contains changes that are not explained by the declared patch",
            )
        )
    if audit["syncSuspects"]:
        diagnostics.append(
            diagnostic(
                "PATCH_CLOSURE_UNSYNCED",
                "referencing objects require explicit patch or acknowledgement; anonymous objects use @<JSON Pointer>",
                syncSuspects=audit["syncSuspects"],
                acknowledgementField="acknowledgedClosureIds",
                candidateUpdated=False,
                retryAllowed=True,
                consumesPatchRound=False,
            )
        )
    diff_review = audit["diffReview"]
    if (
        isinstance(diff_review, dict)
        and isinstance(diff_review.get("payloadBytes"), int)
        and diff_review["payloadBytes"] > DIFF_REVIEW_BYTE_BUDGET
    ):
        diagnostics.append(
            diagnostic(
                "PATCH_DIFF_BUDGET_EXCEEDED",
                "diff-review payload exceeds the hard byte budget; split the finding-bound patch",
                payloadBytes=diff_review["payloadBytes"],
                byteBudget=DIFF_REVIEW_BYTE_BUDGET,
                candidateUpdated=False,
                retryAllowed=True,
                consumesPatchRound=False,
            )
        )
    return diagnostics


def _stage_stale_authorization(
    files: ProjectFiles,
    view: object,
    *,
    packet_path: str,
    reviewer_path: str,
    approval_path: str,
) -> tuple[list[str], str | None]:
    read_bytes = getattr(view, "read_bytes")
    write_atomic = getattr(view, "write_atomic")
    new_packet = read_bytes(packet_path)
    writes, deletes, archive_root = plan_review_packet_rotation(
        files,
        packet_path=packet_path,
        packet_payload=new_packet,
        reviewer_path=reviewer_path,
        approval_path=approval_path,
    )
    for archive_path, payload in writes.items():
        if archive_path == packet_path:
            continue
        write_atomic(archive_path, payload)
    return deletes, archive_root


def _staged_writes(staging_directory: Path) -> dict[str, bytes]:
    writes: dict[str, bytes] = {}
    for path in sorted(staging_directory.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"staging output must not be a symlink: {path.name}")
        if not path.is_file():
            continue
        relative = path.relative_to(staging_directory).as_posix()
        if relative == ".project-io" or relative.startswith(".project-io/"):
            raise ValueError("patch transaction does not support staged tombstones")
        writes[f".ai-sow/{relative}"] = path.read_bytes()
    return writes


def run_patch_cli(
    owner: str,
    default_candidate: str,
    *,
    additional_candidates: Sequence[str] = (),
    post_check: PatchPostCheck | None = None,
    packet_path: str | None = None,
    reviewer_path: str | None = None,
    approval_path: str | None = None,
) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=f"Apply field patch for {owner}")
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--candidate", default=default_candidate)
    parser.add_argument("--patch", required=True)
    parser.add_argument("--base")
    parser.add_argument("--audit", required=True)
    args = parser.parse_args()
    files = ProjectFiles.open(args.project_root)
    diagnostics: list[dict[str, object]] = []
    committed = False
    post_check_passed = post_check is None
    archive_root: str | None = None
    staging_root: str | None = None
    staging_directory: Path | None = None
    try:
        if post_check is not None:
            if None in {packet_path, reviewer_path, approval_path}:
                raise ValueError("transactional patch requires packet, reviewer, and approval paths")
            staging_root = f".ai-sow/.stage-{secrets.token_hex(6)}"
            staging_directory = files.ensure_dir(staging_root)
            transaction_files = ProjectFiles.open_view(args.project_root, staging_root)
        else:
            transaction_files = files
        patch = json.loads(files.read_bytes(args.patch).decode("utf-8"))
        document_patches = patch.get("documents")
        writes: list[tuple[str, object]] = []
        if document_patches is not None:
            if not isinstance(document_patches, list) or not document_patches:
                raise ValueError("multi-document patch requires a non-empty documents array")
            if set(patch) != {"documents"}:
                raise ValueError("multi-document patch cannot mix top-level patch fields")
            allowed_candidates = {default_candidate, *additional_candidates}
            audits: list[dict[str, object]] = []
            seen_paths: set[str] = set()
            for document_patch in document_patches:
                if not isinstance(document_patch, dict):
                    raise ValueError("multi-document patch entries must be objects")
                path = document_patch.get("path")
                if not isinstance(path, str) or path not in allowed_candidates:
                    raise ValueError("multi-document patch path is not owned by this Owner")
                if path in seen_paths:
                    raise ValueError("multi-document patch path is duplicated")
                seen_paths.add(path)
                local_patch = {
                    "operations": document_patch.get("operations", []),
                    "acknowledgedClosureIds": document_patch.get(
                        "acknowledgedClosureIds", []
                    ),
                }
                before = json.loads(files.read_bytes(path).decode("utf-8"))
                after = apply_operations(before, local_patch["operations"])
                diagnostics.extend(validate_patch_audit(before, after, local_patch))
                audits.append(
                    {
                        "audit": patch_audit(before, after, local_patch),
                        "path": path,
                    }
                )
                writes.append((path, after))
            diff_documents = [
                {
                    "diffReview": entry["audit"]["diffReview"],
                    "path": entry["path"],
                }
                for entry in audits
            ]
            diff_content: dict[str, object] = {
                "byteBudget": DIFF_REVIEW_BYTE_BUDGET,
                "documents": diff_documents,
            }
            diff_review = {
                **diff_content,
                "payloadBytes": len(canonical_json_bytes(diff_content)),
            }
            if diff_review["payloadBytes"] > DIFF_REVIEW_BYTE_BUDGET:
                diagnostics.append(
                    diagnostic(
                        "PATCH_DIFF_BUDGET_EXCEEDED",
                        "multi-document diff-review payload exceeds the hard byte budget",
                        payloadBytes=diff_review["payloadBytes"],
                        byteBudget=DIFF_REVIEW_BYTE_BUDGET,
                        candidateUpdated=False,
                        retryAllowed=True,
                        consumesPatchRound=False,
                    )
                )
            audit = {
                "algorithm": "ai-sow-multi-field-patch-v1",
                "diffReview": diff_review,
                "documents": audits,
            }
        else:
            if not isinstance(args.base, str):
                raise ValueError("single-document patch requires --base")
            before = json.loads(files.read_bytes(args.base).decode("utf-8"))
            operations = patch.get("operations", [])
            after = apply_operations(before, operations)
            diagnostics.extend(validate_patch_audit(before, after, patch))
            audit = patch_audit(before, after, patch)
            writes.append((args.candidate, after))
        if not diagnostics:
            for path, after in writes:
                transaction_files.write_atomic(path, canonical_json_bytes(after))
            transaction_files.write_atomic(args.audit, canonical_json_bytes(audit))
        if not diagnostics and post_check is not None and staging_root is not None:
            diagnostics.extend(post_check(args.project_root, staging_root))
            post_check_passed = not diagnostics
        if not diagnostics and post_check is not None and staging_directory is not None:
            deletes, archive_root = _stage_stale_authorization(
                files,
                transaction_files,
                packet_path=str(packet_path),
                reviewer_path=str(reviewer_path),
                approval_path=str(approval_path),
            )
            publish_file_transaction(
                files,
                _staged_writes(staging_directory),
                deletes,
            )
            committed = True
        elif not diagnostics:
            committed = True
    except (ProjectIOError, OSError, UnicodeError, json.JSONDecodeError, ValueError, KeyError, IndexError) as exc:
        diagnostics.append(diagnostic("PATCH_INVALID", str(exc)))
    finally:
        if staging_directory is not None and staging_directory.exists():
            shutil.rmtree(staging_directory)
    outcome = "OK" if not diagnostics else "BLOCKED"
    print(
        json.dumps(
            {
                "outcome": outcome,
                "owner": owner,
                "candidateUpdated": committed,
                "auditUpdated": committed,
                "postCheckPassed": post_check_passed,
                "patchRoundConsumed": committed,
                "authorizationArchive": archive_root,
                "diagnostics": diagnostics,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if not diagnostics else 2
