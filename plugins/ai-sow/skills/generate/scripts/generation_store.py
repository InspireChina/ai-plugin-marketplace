from __future__ import annotations

import json
import re
import secrets
import shutil
import stat
from collections.abc import Mapping
from pathlib import Path

from contracts import (
    canonical_json_bytes,
    load_registry,
    sha256_bytes,
    validate_contract,
)
from models import CurrentGeneration, PublicationResult
from runtime.project_io import ProjectFiles, ProjectIOError


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_REGISTRY = load_registry(SKILL_ROOT / "contracts")
SIX_DIGITS = re.compile(r"^[0-9]{6}$")


def replace_current(files: ProjectFiles, payload: bytes) -> None:
    """Atomically replace the sole mutable pointer after immutable publication."""
    files.write_atomic(".ai-sow/current.json", payload)


def _error(code: str, path: str, message: str) -> ProjectIOError:
    return ProjectIOError(code, path, message)


def _optional_json(files: ProjectFiles, relative_path: str) -> object | None:
    try:
        return files.read_json(relative_path)
    except ProjectIOError as error:
        if error.code == "PROJECT_PATH_MISSING":
            return None
        raise


def _validated_json(
    files: ProjectFiles,
    path: str,
    schema_name: str,
) -> Mapping[str, object]:
    value = files.read_json(path)
    if not isinstance(value, Mapping) or validate_contract(
        value, schema_name, SCHEMA_REGISTRY
    ):
        raise _error("PROJECT_CONTRACT_INVALID", path, "stored contract is invalid")
    return value


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


def _next_artifact_manifest(
    files: ProjectFiles,
    run_id: str,
    expected_sha256: str,
) -> tuple[str, Mapping[str, object]]:
    root_relative = f".ai-sow/work/runs/{run_id}/artifacts"
    root = files.resolve(root_relative, expect="dir")
    matches: list[tuple[str, Mapping[str, object]]] = []
    for version in sorted(root.iterdir(), key=lambda item: item.name):
        if not version.is_dir() or re.fullmatch(
            r"[0-9]{6}-[0-9a-f]{64}", version.name
        ) is None:
            continue
        relative = f"{root_relative}/{version.name}/artifact-manifest.json"
        try:
            payload = files.read_bytes(relative)
        except ProjectIOError as error:
            if error.code == "PROJECT_PATH_MISSING":
                continue
            raise
        if sha256_bytes(payload) != expected_sha256:
            continue
        value = files.read_json(relative)
        diagnostics = validate_contract(
            value,
            "artifact-approval.schema.json",
            SCHEMA_REGISTRY,
        )
        if diagnostics or not isinstance(value, Mapping):
            raise _error(
                "ARTIFACT_MANIFEST_INVALID",
                relative,
                "artifact manifest does not satisfy the frozen contract",
            )
        matches.append((relative, value))
    if len(matches) != 1:
        raise _error(
            "ARTIFACT_MANIFEST_NOT_UNIQUE",
            root_relative,
            "approval must resolve exactly one immutable artifact manifest",
        )
    return matches[0]


def _next_generation_id(files: ProjectFiles) -> str:
    values = _numeric_directories(files, ".ai-sow/generations")
    return f"{max(values, default=0) + 1:06d}"


def load_current(files: ProjectFiles) -> CurrentGeneration | None:
    current_value = _optional_json(files, ".ai-sow/current.json")
    if current_value is None:
        return None
    if not isinstance(current_value, Mapping) or validate_contract(
        current_value, "current.schema.json", SCHEMA_REGISTRY
    ):
        raise _error(
            "PROJECT_CURRENT_INVALID",
            ".ai-sow/current.json",
            "current pointer does not satisfy the v8 contract",
        )
    generation_id = str(current_value["generationId"])
    manifest_path = f".ai-sow/generations/{generation_id}/manifest.json"
    if current_value["generationManifestPath"] != manifest_path:
        raise _error(
            "PROJECT_CURRENT_PATH_MISMATCH",
            ".ai-sow/current.json",
            "current pointer does not name its generation manifest",
        )
    manifest_payload = files.read_bytes(manifest_path)
    if sha256_bytes(manifest_payload) != current_value["generationManifestSha256"]:
        raise _error(
            "PROJECT_HASH_MISMATCH",
            manifest_path,
            "generation manifest hash does not match current pointer",
        )
    manifest = _validated_json(
        files,
        manifest_path,
        "generation-manifest.schema.json",
    )
    if manifest["generationId"] != generation_id:
        raise _error(
            "PROJECT_GENERATION_ID_MISMATCH",
            manifest_path,
            "generation manifest ID does not match its directory",
        )
    for path_field, hash_field in (
        ("sowModelPath", "sowModelSha256"),
        ("workbookPath", "workbookSha256"),
        ("notesPath", "notesSha256"),
    ):
        path = str(manifest[path_field])
        if not path.startswith(f".ai-sow/generations/{generation_id}/") or sha256_bytes(
            files.read_bytes(path)
        ) != manifest[hash_field]:
            raise _error(
                "PROJECT_HASH_MISMATCH",
                path,
                "generation artifact path or hash is invalid",
            )
    proof_hashes = (
        ("proof/review-decision.json", manifest["reviewDecisionSha256"]),
        ("proof/artifact-manifest.json", manifest["artifactManifestSha256"]),
        ("proof/approval.json", manifest["approvalSha256"]),
        ("input/sow-template.xlsx", manifest["templateSha256"]),
        (
            "input/effective-policy-decision.json",
            manifest["effectivePolicyDecisionSha256"],
        ),
    )
    for relative, expected in proof_hashes:
        path = f".ai-sow/generations/{generation_id}/{relative}"
        if sha256_bytes(files.read_bytes(path)) != expected:
            raise _error(
                "PROJECT_HASH_MISMATCH",
                path,
                "generation proof hash does not match manifest",
            )
    checkpoint_paths = (
        "proof/scope-closure-checkpoint.json",
        "proof/story-ac-checkpoint.json",
        "proof/task-checkpoint.json",
    )
    actual_checkpoint_hashes = [
        sha256_bytes(files.read_bytes(f".ai-sow/generations/{generation_id}/{path}"))
        for path in checkpoint_paths
    ]
    if actual_checkpoint_hashes != list(manifest["stageCheckpointSha256s"]):
        raise _error(
            "PROJECT_HASH_MISMATCH",
            manifest_path,
            "generation checkpoint hashes do not match manifest",
        )
    return CurrentGeneration(
        generation_id=generation_id,
        manifest_path=manifest_path,
        workbook_path=str(manifest["workbookPath"]),
        notes_path=str(manifest["notesPath"]),
    )


def promote(
    draft_manifest_sha256: str,
    approval: Mapping[str, object],
    *,
    files: ProjectFiles,
) -> PublicationResult:
    """Promote approved draft bytes without invoking renderer or Office."""
    approval_diagnostics = validate_contract(
        approval,
        "artifact-approval.schema.json",
        SCHEMA_REGISTRY,
    )
    if approval_diagnostics or approval.get("decision") != "APPROVE":
        raise _error(
            "APPROVAL_INVALID",
            "approval.json",
            "promote requires a contract-valid APPROVE decision",
        )
    if approval.get("artifactManifestSha256") != draft_manifest_sha256:
        raise _error(
            "APPROVAL_BINDING_MISMATCH",
            "approval.json",
            "approval does not bind the requested artifact manifest",
        )
    manifest_path, artifact = _next_artifact_manifest(
        files,
        str(approval["runId"]),
        draft_manifest_sha256,
    )
    for field in (
        "runId",
        "candidateSha256",
        "sourceManifestSha256",
        "reviewDecisionSha256",
        "templateSha256",
        "effectivePolicyDecisionSha256",
    ):
        if approval.get(field) != artifact.get(field):
            raise _error(
                "APPROVAL_BINDING_MISMATCH",
                "approval.json",
                f"approval field does not bind artifact: {field}",
            )
    approval_payload = canonical_json_bytes(approval)
    approval_sha256 = sha256_bytes(approval_payload)
    current = _optional_json(files, ".ai-sow/current.json")
    if isinstance(current, Mapping) and current.get("contract") == "ai-sow-current-v2":
        current_manifest = _optional_json(
            files, str(current.get("generationManifestPath"))
        )
        if (
            isinstance(current_manifest, Mapping)
            and current_manifest.get("artifactManifestSha256")
            == draft_manifest_sha256
            and current_manifest.get("approvalSha256") == approval_sha256
        ):
            return PublicationResult(
                outcome="REUSED",
                decision="PASS",
                generation_id=str(current["generationId"]),
                revision_id=None,
                workbook_path=str(current_manifest["workbookPath"]),
                notes_path=str(current_manifest["notesPath"]),
                change_counts={},
                questions=(),
            )
    artifact_root = str(Path(manifest_path).parent.as_posix())

    def artifact_bytes(name: str) -> bytes:
        return files.read_bytes(f"{artifact_root}/{name}")

    for field, name in (("workbook", "sow.xlsx"), ("notes", "sow-notes.md")):
        binding = artifact.get(field)
        if not isinstance(binding, Mapping) or sha256_bytes(
            artifact_bytes(name)
        ) != binding.get("sha256"):
            raise _error(
                "ARTIFACT_HASH_MISMATCH",
                f"{artifact_root}/{name}",
                "approved artifact bytes do not match the manifest",
            )
    model_payload = artifact_bytes("sow-model.json")
    model = json.loads(model_payload.decode("utf-8"))
    if not isinstance(model, Mapping) or sha256_bytes(model_payload) != artifact.get(
        "candidateSha256"
    ):
        raise _error(
            "ARTIFACT_HASH_MISMATCH",
            f"{artifact_root}/sow-model.json",
            "approved sow-model bytes do not match the manifest",
        )
    project = model.get("project")
    if not isinstance(project, Mapping):
        raise _error(
            "ARTIFACT_MODEL_INVALID",
            f"{artifact_root}/sow-model.json",
            "approved sow-model lacks project bindings",
        )
    generation_id = _next_generation_id(files)
    generation_root = f".ai-sow/generations/{generation_id}"
    workbook_payload = artifact_bytes("sow.xlsx")
    notes_payload = artifact_bytes("sow-notes.md")
    project_meta_root = files.ensure_dir(".ai-sow")
    stage_root = project_meta_root / f".generation-stage-{secrets.token_hex(6)}"
    stage_root.mkdir()
    try:
        stage_files = ProjectFiles.open(stage_root)
        copied = (
            ("data/sow-model.json", model_payload),
            ("input/sow-template.xlsx", artifact_bytes("sow-template.xlsx")),
            (
                "input/effective-policy-decision.json",
                artifact_bytes("effective-policy-decision.json"),
            ),
            ("proof/review-decision.json", artifact_bytes("review-decision.json")),
            (
                "proof/scope-closure-checkpoint.json",
                artifact_bytes("scope-closure-checkpoint.json"),
            ),
            (
                "proof/story-ac-checkpoint.json",
                artifact_bytes("story-ac-checkpoint.json"),
            ),
            ("proof/task-checkpoint.json", artifact_bytes("task-checkpoint.json")),
            ("proof/artifact-manifest.json", files.read_bytes(manifest_path)),
            ("proof/approval.json", approval_payload),
            ("output/sow.xlsx", workbook_payload),
            ("output/sow-notes.md", notes_payload),
        )
        for relative, payload in copied:
            stage_files.write_atomic(relative, payload)
        generation_manifest = {
            "contract": "ai-sow-generation-manifest-v2",
            "generationId": generation_id,
            "runId": artifact["runId"],
            "inputRevisionSha256": project["inputRevisionSha256"],
            "sowModelPath": f"{generation_root}/data/sow-model.json",
            "sowModelSha256": artifact["candidateSha256"],
            "stageCheckpointSha256s": artifact["stageCheckpointSha256s"],
            "reviewDecisionSha256": artifact["reviewDecisionSha256"],
            "artifactManifestSha256": draft_manifest_sha256,
            "approvalSha256": approval_sha256,
            "templateSha256": artifact["templateSha256"],
            "effectivePolicyDecisionSha256": artifact[
                "effectivePolicyDecisionSha256"
            ],
            "rendererContract": artifact["rendererContract"],
            "rendererSha256": artifact["rendererSha256"],
            "workbookPath": f"{generation_root}/output/sow.xlsx",
            "workbookSha256": artifact["workbook"]["sha256"],
            "notesPath": f"{generation_root}/output/sow-notes.md",
            "notesSha256": artifact["notes"]["sha256"],
            "publicationComplete": True,
        }
        manifest_diagnostics = validate_contract(
            generation_manifest,
            "generation-manifest.schema.json",
            SCHEMA_REGISTRY,
        )
        if manifest_diagnostics:
            raise _error(
                "GENERATION_MANIFEST_INVALID",
                "manifest.json",
                "generation manifest does not satisfy the frozen contract",
            )
        manifest_payload = canonical_json_bytes(generation_manifest)
        stage_files.write_atomic("manifest.json", manifest_payload)
        files.publish_tree_new(stage_root, generation_root)
        final_manifest_path = f"{generation_root}/manifest.json"
        if files.read_bytes(final_manifest_path) != manifest_payload:
            raise _error(
                "GENERATION_HASH_MISMATCH",
                final_manifest_path,
                "published generation manifest changed",
            )
        current_value = {
            "contract": "ai-sow-current-v2",
            "generationId": generation_id,
            "generationManifestPath": final_manifest_path,
            "generationManifestSha256": sha256_bytes(manifest_payload),
        }
        current_diagnostics = validate_contract(
            current_value,
            "current.schema.json",
            SCHEMA_REGISTRY,
        )
        if current_diagnostics:
            raise _error(
                "CURRENT_INVALID",
                ".ai-sow/current.json",
                "current pointer does not satisfy the frozen contract",
            )
        replace_current(files, canonical_json_bytes(current_value))
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)
    return PublicationResult(
        outcome="PUBLISHED",
        decision="PASS",
        generation_id=generation_id,
        revision_id=None,
        workbook_path=f"{generation_root}/output/sow.xlsx",
        notes_path=f"{generation_root}/output/sow-notes.md",
        change_counts={},
        questions=(),
    )
