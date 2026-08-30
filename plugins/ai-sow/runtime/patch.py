from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from runtime.diagnostics import diagnostic
from runtime.handoff import canonical_json_bytes, sha256_bytes
from runtime.project_io import ProjectFiles, ProjectIOError


STABLE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)+$")


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
    reverse: dict[str, set[str]] = defaultdict(set)
    for owner, targets in refs.items():
        for target in targets:
            reverse[target].add(owner)
    closure = set(changed)
    queue = deque(changed)
    while queue:
        current = queue.popleft()
        for related in refs.get(current, set()) | reverse.get(current, set()):
            if related not in closure:
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
            )
        )
    return diagnostics


def run_patch_cli(owner: str, default_candidate: str) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=f"Apply field patch for {owner}")
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--candidate", default=default_candidate)
    parser.add_argument("--patch", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--audit", required=True)
    args = parser.parse_args()
    files = ProjectFiles(args.project_root)
    diagnostics: list[dict[str, object]] = []
    try:
        before = json.loads(files.read_bytes(args.base).decode("utf-8"))
        patch = json.loads(files.read_bytes(args.patch).decode("utf-8"))
        operations = patch.get("operations", [])
        after = apply_operations(before, operations)
        diagnostics.extend(validate_patch_audit(before, after, patch))
        audit = patch_audit(before, after, patch)
        if not diagnostics:
            files.write_atomic(args.candidate, canonical_json_bytes(after))
            files.write_atomic(args.audit, canonical_json_bytes(audit))
    except (ProjectIOError, OSError, UnicodeError, json.JSONDecodeError, ValueError, KeyError, IndexError) as exc:
        diagnostics.append(diagnostic("PATCH_INVALID", str(exc)))
    outcome = "OK" if not diagnostics else "BLOCKED"
    print(json.dumps({"outcome": outcome, "owner": owner, "diagnostics": diagnostics}, ensure_ascii=False, sort_keys=True))
    return 0 if not diagnostics else 2
