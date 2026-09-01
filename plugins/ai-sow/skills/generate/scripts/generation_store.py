from __future__ import annotations

import json
import os
import re
import stat
from collections.abc import Mapping
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[2]
if str(PLUGIN_ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(PLUGIN_ROOT))

from contracts import (  # noqa: E402
    canonical_json_bytes,
    load_schema_registry,
    sha256_bytes,
    validate_contract,
    validate_generation_hash_closure,
)
from models import CurrentGeneration, PublicationResult  # noqa: E402
from runtime.project_io import ProjectFiles, ProjectIOError  # noqa: E402


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_REGISTRY = load_schema_registry(SKILL_ROOT)
SIX_DIGITS = re.compile(r"^[0-9]{6}$")
PUBLICATION_LEDGER = ".ai-sow/work/publication.json"


def _error(code: str, path: str, message: str) -> ProjectIOError:
    return ProjectIOError(code, path, message)


def _optional_json(files: ProjectFiles, relative_path: str) -> object | None:
    try:
        return files.read_json(relative_path)
    except ProjectIOError as error:
        if error.code == "PROJECT_PATH_MISSING":
            return None
        raise


def _require_valid(value: object, schema_name: str, path: str) -> Mapping[str, object]:
    diagnostics = validate_contract(value, schema_name, SCHEMA_REGISTRY)
    if diagnostics or not isinstance(value, Mapping):
        raise _error("PROJECT_CONTRACT_INVALID", path, "stored contract is invalid")
    return value


def _read_mapping(files: ProjectFiles, relative_path: str) -> Mapping[str, object]:
    return _require_valid(files.read_json(relative_path), Path(relative_path).name, relative_path)


def _verify_hash(files: ProjectFiles, path: object, expected: object) -> None:
    if not isinstance(path, str) or not isinstance(expected, str):
        raise _error("PROJECT_HASH_CLOSURE_INVALID", str(path), "artifact hash binding is invalid")
    if sha256_bytes(files.read_bytes(path)) != expected:
        raise _error("PROJECT_HASH_MISMATCH", path, "stored artifact hash does not match")


def _verify_input_revision(files: ProjectFiles, revision_id: str) -> Mapping[str, object]:
    manifest_path = f".ai-sow/inputs/revisions/{revision_id}/manifest.json"
    manifest = _require_valid(
        files.read_json(manifest_path),
        "input-manifest.schema.json",
        manifest_path,
    )
    if manifest.get("revisionId") != revision_id:
        raise _error(
            "PROJECT_REVISION_ID_MISMATCH",
            manifest_path,
            "input manifest revision ID does not match its directory",
        )
    revision_root = f".ai-sow/inputs/revisions/{revision_id}"
    anchors_path = manifest.get("anchorsPath")
    if not isinstance(anchors_path, str):
        raise _error("PROJECT_HASH_CLOSURE_INVALID", manifest_path, "anchors path is invalid")
    _verify_hash(
        files,
        f"{revision_root}/{anchors_path}",
        manifest.get("anchorsSha256"),
    )
    sources = manifest.get("sources")
    if isinstance(sources, list):
        for source in sources:
            if not isinstance(source, Mapping):
                continue
            source_path = source.get("path")
            if not isinstance(source_path, str):
                raise _error(
                    "PROJECT_HASH_CLOSURE_INVALID",
                    manifest_path,
                    "source path is invalid",
                )
            _verify_hash(
                files,
                f"{revision_root}/{source_path}",
                source.get("sha256"),
            )
    return manifest


def _verify_generation(
    files: ProjectFiles,
    generation_id: str,
    revision_id: str,
) -> Mapping[str, object]:
    manifest_path = f".ai-sow/generations/{generation_id}/manifest.json"
    manifest = files.read_json(manifest_path)
    diagnostics = validate_generation_hash_closure(manifest, SCHEMA_REGISTRY)
    if diagnostics or not isinstance(manifest, Mapping):
        raise _error(
            "PROJECT_GENERATION_INVALID",
            manifest_path,
            "generation manifest or hash closure is invalid",
        )
    if (
        manifest.get("generationId") != generation_id
        or manifest.get("revisionId") != revision_id
    ):
        raise _error(
            "PROJECT_GENERATION_ID_MISMATCH",
            manifest_path,
            "generation manifest IDs do not match their directories",
        )
    _verify_input_revision(files, revision_id)
    for path_field, hash_field in (
        ("inputManifestPath", "inputManifestSha256"),
        ("scopePath", "scopeSha256"),
        ("deliveryPath", "deliverySha256"),
        ("templatePath", "templateSha256"),
        ("workbookPath", "workbookSha256"),
        ("notesPath", "notesSha256"),
    ):
        _verify_hash(files, manifest.get(path_field), manifest.get(hash_field))
    return manifest


def load_current(files: ProjectFiles) -> CurrentGeneration | None:
    current_value = _optional_json(files, ".ai-sow/current.json")
    if current_value is None:
        return None
    current = _require_valid(
        current_value,
        "current.schema.json",
        ".ai-sow/current.json",
    )
    generation_id = str(current["generationId"])
    revision_id = str(current["revisionId"])
    expected_manifest_path = f".ai-sow/generations/{generation_id}/manifest.json"
    if current.get("generationManifestPath") != expected_manifest_path:
        raise _error(
            "PROJECT_CURRENT_PATH_MISMATCH",
            ".ai-sow/current.json",
            "current pointer does not name its generation manifest",
        )
    _verify_hash(
        files,
        expected_manifest_path,
        current.get("generationManifestSha256"),
    )
    manifest = _verify_generation(files, generation_id, revision_id)
    return CurrentGeneration(
        generation_id=generation_id,
        revision_id=revision_id,
        manifest_path=expected_manifest_path,
        scope_path=str(manifest["scopePath"]),
        delivery_path=str(manifest["deliveryPath"]),
        workbook_path=str(manifest["workbookPath"]),
        notes_path=str(manifest["notesPath"]),
    )


def _numeric_directories(files: ProjectFiles, relative_root: str) -> set[int]:
    try:
        root = files.resolve(relative_root, expect="dir")
    except ProjectIOError as error:
        if error.code == "PROJECT_PATH_MISSING":
            return set()
        raise
    values: set[int] = set()
    for child in sorted(root.iterdir(), key=lambda item: item.name):
        if SIX_DIGITS.fullmatch(child.name) is None:
            continue
        snapshot = child.lstat()
        if stat.S_ISLNK(snapshot.st_mode) or not stat.S_ISDIR(snapshot.st_mode):
            raise _error(
                "IMMUTABLE_DIRECTORY_CONFLICT",
                f"{relative_root}/{child.name}",
                "six-digit immutable entry is not a regular directory",
            )
        values.add(int(child.name))
    return values


def _reserved_ids(files: ProjectFiles) -> tuple[str | None, str | None]:
    ledger = _optional_json(files, PUBLICATION_LEDGER)
    if not isinstance(ledger, Mapping) or ledger.get("publicationComplete") is not False:
        return None, None
    revision_id = ledger.get("revisionId")
    generation_id = ledger.get("generationId")
    return (
        revision_id if isinstance(revision_id, str) and SIX_DIGITS.fullmatch(revision_id) else None,
        generation_id
        if isinstance(generation_id, str) and SIX_DIGITS.fullmatch(generation_id)
        else None,
    )


def allocate_next_ids(
    files: ProjectFiles,
    current: CurrentGeneration | None,
) -> tuple[str, str]:
    revision_values = _numeric_directories(files, ".ai-sow/inputs/revisions")
    generation_values = _numeric_directories(files, ".ai-sow/generations")
    if current is not None:
        revision_values.add(int(current.revision_id))
        generation_values.add(int(current.generation_id))
    reserved_revision, reserved_generation = _reserved_ids(files)

    pending = _optional_json(files, ".ai-sow/inputs/pending/manifest.json")
    pending_revision = (
        pending.get("revisionId")
        if isinstance(pending, Mapping)
        and isinstance(pending.get("revisionId"), str)
        and SIX_DIGITS.fullmatch(str(pending.get("revisionId")))
        else None
    )
    if pending_revision is not None:
        next_revision = str(pending_revision)
    elif reserved_revision is not None:
        next_revision = reserved_revision
    else:
        next_revision = f"{max(revision_values, default=0) + 1:06d}"

    if reserved_generation is not None:
        next_generation = reserved_generation
    else:
        next_generation = f"{max(generation_values, default=0) + 1:06d}"
    return next_revision, next_generation


def replace_current(files: ProjectFiles, payload: bytes) -> None:
    files.write_atomic(".ai-sow/current.json", payload)


def _staged_json(path: Path) -> Mapping[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _error("PROJECT_JSON_INVALID", path.name, "staged JSON is invalid") from error
    if not isinstance(value, Mapping):
        raise _error("PROJECT_CONTRACT_INVALID", path.name, "staged JSON must be an object")
    return value


def publish_success(
    files: ProjectFiles,
    *,
    target_revision_id: str,
    target_generation_id: str,
    pending_root: Path | None,
    staged_generation_root: Path,
) -> PublicationResult:
    if SIX_DIGITS.fullmatch(target_revision_id) is None or SIX_DIGITS.fullmatch(
        target_generation_id
    ) is None:
        raise _error("PROJECT_ID_INVALID", ".ai-sow", "publication IDs must be six digits")

    generation_manifest = _staged_json(Path(staged_generation_root) / "manifest.json")
    if (
        generation_manifest.get("generationId") != target_generation_id
        or generation_manifest.get("revisionId") != target_revision_id
    ):
        raise _error(
            "PROJECT_GENERATION_ID_MISMATCH",
            "manifest.json",
            "staged generation IDs do not match publication targets",
        )

    if pending_root is not None:
        pending_manifest = _staged_json(Path(pending_root) / "manifest.json")
        if pending_manifest.get("revisionId") != target_revision_id:
            raise _error(
                "PROJECT_REVISION_ID_MISMATCH",
                "manifest.json",
                "pending revision ID does not match publication target",
            )
        files.publish_tree_new(
            Path(pending_root),
            f".ai-sow/inputs/revisions/{target_revision_id}",
        )
    else:
        _verify_input_revision(files, target_revision_id)

    files.publish_tree_new(
        Path(staged_generation_root),
        f".ai-sow/generations/{target_generation_id}",
    )
    manifest = _verify_generation(files, target_generation_id, target_revision_id)
    manifest_path = f".ai-sow/generations/{target_generation_id}/manifest.json"
    current = {
        "contract": "ai-sow-current-v1",
        "generationId": target_generation_id,
        "revisionId": target_revision_id,
        "generationManifestPath": manifest_path,
        "generationManifestSha256": sha256_bytes(files.read_bytes(manifest_path)),
    }
    replace_current(files, canonical_json_bytes(current))

    files.remove_managed_tree(
        ".ai-sow/inputs/pending",
        allowed_roots=(".ai-sow/inputs/pending",),
    )
    files.remove_managed_tree(
        ".ai-sow/work",
        allowed_roots=(".ai-sow/work",),
    )
    review = manifest.get("finalReview")
    decision = review.get("decision") if isinstance(review, Mapping) else None
    change_counts = manifest.get("changeCounts")
    counts = dict(change_counts) if isinstance(change_counts, Mapping) else {}
    return PublicationResult(
        outcome="PUBLISHED",
        decision=decision if decision in {"PASS", "PASS_WITH_NOTES", "BLOCKED"} else None,
        generation_id=target_generation_id,
        revision_id=target_revision_id,
        workbook_path=str(manifest["workbookPath"]),
        notes_path=str(manifest["notesPath"]),
        feature_counts={"changed": int(counts.get("features", 0))},
        recomputed_story_count=int(counts.get("stories", 0)),
        recomputed_task_count=int(counts.get("tasks", 0)),
        questions=(),
    )


def cleanup_interrupted_publication(
    files: ProjectFiles,
    current: CurrentGeneration | None,
) -> None:
    ai_sow = files.root / ".ai-sow"
    if ai_sow.is_dir():
        for candidate in sorted(ai_sow.glob(".candidate-*"), key=lambda item: item.name):
            if re.fullmatch(r"\.candidate-[0-9a-f]{12}", candidate.name):
                relative = f".ai-sow/{candidate.name}"
                files.remove_managed_tree(relative, allowed_roots=(relative,))

    reserved_revision, reserved_generation = _reserved_ids(files)
    referenced_revision = current.revision_id if current is not None else None
    referenced_generation = current.generation_id if current is not None else None
    for kind, identifier, referenced, relative in (
        (
            "revision",
            reserved_revision,
            referenced_revision,
            f".ai-sow/inputs/revisions/{reserved_revision}" if reserved_revision else "",
        ),
        (
            "generation",
            reserved_generation,
            referenced_generation,
            f".ai-sow/generations/{reserved_generation}" if reserved_generation else "",
        ),
    ):
        if identifier is None or identifier == referenced:
            continue
        try:
            files.resolve(relative, expect="dir")
        except ProjectIOError as error:
            if error.code == "PROJECT_PATH_MISSING":
                continue
            raise
        files.remove_managed_tree(relative, allowed_roots=(relative,))
