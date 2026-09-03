from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import stat
import sys
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[2]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from contracts import (
    canonical_json_bytes,
    load_schema_registry,
    sha256_bytes,
    validate_contract,
)
from models import (
    AnchorChange,
    Diagnostic,
    InputChangeSet,
    InputRequest,
    IntakeResult,
    SourceRequest,
)
from questions import question_answer_anchors, validate_question_answers
from runtime.project_io import ProjectFiles, ProjectIOError
from source_readers import SourceReadError, extract_document, source_media_type


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_REGISTRY = load_schema_registry(SKILL_ROOT)
class IntakeRequestError(ValueError):
    def __init__(self, diagnostics: tuple[Diagnostic, ...]):
        super().__init__("输入请求未通过校验。")
        self.diagnostics = diagnostics


def _diagnostic(code: str, message: str, path: str = "") -> Diagnostic:
    return Diagnostic(code=code, message=message, path=path, details={})


def _sort_diagnostics(values: Sequence[Diagnostic]) -> tuple[Diagnostic, ...]:
    return tuple(sorted(values, key=lambda item: (item.path, item.code, item.message)))


def _request_domain_diagnostics(value: object) -> tuple[Diagnostic, ...]:
    if not isinstance(value, Mapping):
        return ()
    mode = value.get("mode")
    sources = value.get("sources")
    roles = {
        source.get("role")
        for source in sources
        if isinstance(sources, list) and isinstance(source, Mapping)
    } if isinstance(sources, list) else set()
    diagnostics: list[Diagnostic] = []
    if isinstance(sources, list):
        for index, source in enumerate(sources):
            if not isinstance(source, Mapping):
                continue
            role = source.get("role")
            path = source.get("path")
            if role not in {"PRD", "HLD", "PRIOR_SOW", "SUPPLEMENT"} or not isinstance(
                path, str
            ):
                continue
            try:
                source_media_type(Path(path), str(role))
            except SourceReadError as error:
                diagnostics.append(
                    _diagnostic(error.code, str(error), f"/sources/{index}/path")
                )
    if mode == "BROWNFIELD":
        if "PRIOR_SOW" not in roles:
            diagnostics.append(
                _diagnostic(
                    "BROWNFIELD_PRIOR_SOW_REQUIRED",
                    "Brownfield 必须提供至少一份适用的往期 SOW。",
                    "/sources",
                )
            )
        if value.get("currentStateDelta") is None:
            diagnostics.append(
                _diagnostic(
                    "BROWNFIELD_CURRENT_STATE_DELTA_REQUIRED",
                    "Brownfield 必须提供现状增量声明。",
                    "/currentStateDelta",
                )
            )
    if mode == "GREENFIELD" and "PRIOR_SOW" in roles:
        diagnostics.append(
            _diagnostic(
                "GREENFIELD_PRIOR_SOW_FORBIDDEN",
                "Greenfield 不得把往期 SOW 作为输入来源。",
                "/sources",
            )
        )
    return tuple(diagnostics)


def load_request(files: ProjectFiles, request_path: str, registry) -> InputRequest:
    try:
        value = files.read_json(request_path)
    except ProjectIOError as error:
        raise IntakeRequestError(
            (_diagnostic(error.code, "输入请求文件无法读取。", request_path),)
        ) from error

    diagnostics = list(validate_contract(value, "request.schema.json", registry))
    diagnostics.extend(_request_domain_diagnostics(value))
    if diagnostics:
        raise IntakeRequestError(_sort_diagnostics(diagnostics))
    assert isinstance(value, Mapping)
    project = value["project"]
    assert isinstance(project, Mapping)
    source_values = value["sources"]
    assert isinstance(source_values, list)
    sources = tuple(
        SourceRequest(
            source_id=str(source["sourceId"]),
            role=source["role"],
            path=Path(str(source["path"])),
            version=str(source["version"]),
        )
        for source in source_values
        if isinstance(source, Mapping)
    )
    current_state_delta = value.get("currentStateDelta")
    return InputRequest(
        project_id=str(project["projectId"]),
        project_name=str(project["name"]),
        planned_effective_date=str(project["plannedEffectiveDate"]),
        mode=value["mode"],
        responsibility_boundaries=tuple(
            dict(item)
            for item in value["responsibilityBoundaries"]
            if isinstance(item, Mapping)
        ),
        sources=sources,
        questions=tuple(
            dict(item) for item in value["questions"] if isinstance(item, Mapping)
        ),
        questionnaire_answers=tuple(
            dict(item)
            for item in value["questionnaireAnswers"]
            if isinstance(item, Mapping)
        ),
        current_state_delta=(
            dict(current_state_delta)
            if isinstance(current_state_delta, Mapping)
            else None
        ),
    )


def _is_unsafe(snapshot: os.stat_result) -> bool:
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(snapshot.st_mode) or bool(
        getattr(snapshot, "st_file_attributes", 0) & reparse
    )


def _ensure_privacy_ignore(files: ProjectFiles) -> Diagnostic | None:
    target = files.root / ".gitignore"
    try:
        snapshot = target.lstat()
    except FileNotFoundError:
        files.write_atomic(".gitignore", b"/.ai-sow/\n")
        return None
    if _is_unsafe(snapshot) or not stat.S_ISREG(snapshot.st_mode):
        return _diagnostic(
            "GITIGNORE_UNSAFE",
            "项目根目录 .gitignore 必须是普通文件。",
            ".gitignore",
        )
    payload = target.read_bytes()
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return _diagnostic(
            "GITIGNORE_INVALID_UTF8",
            "项目根目录 .gitignore 必须使用 UTF-8。",
            ".gitignore",
        )
    if any(line.strip().rstrip("/") == "/.ai-sow" for line in text.splitlines()):
        return None
    separator = b"" if not payload or payload.endswith((b"\n", b"\r")) else b"\n"
    files.write_atomic(".gitignore", payload + separator + b"/.ai-sow/\n")
    return None


def _optional_json(path: Path) -> object | None:
    try:
        snapshot = path.lstat()
    except FileNotFoundError:
        return None
    if _is_unsafe(snapshot) or not stat.S_ISREG(snapshot.st_mode):
        raise ValueError("unsafe managed JSON")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid managed JSON") from error


def _optional_project_json(files: ProjectFiles, relative_path: str) -> object | None:
    try:
        return files.read_json(relative_path)
    except ProjectIOError as error:
        if error.code == "PROJECT_PATH_MISSING":
            return None
        raise ValueError("invalid managed JSON") from error


def _existing_project_id(files: ProjectFiles) -> str | None:
    pending_manifest = _optional_project_json(
        files, ".ai-sow/inputs/pending/manifest.json"
    )
    if isinstance(pending_manifest, Mapping):
        project = pending_manifest.get("project")
        if isinstance(project, Mapping) and isinstance(project.get("projectId"), str):
            return project["projectId"]

    current = _optional_project_json(files, ".ai-sow/current.json")
    if not isinstance(current, Mapping):
        return None
    revision_id = current.get("revisionId")
    if not isinstance(revision_id, str):
        return None
    manifest = _optional_project_json(
        files, f".ai-sow/inputs/revisions/{revision_id}/manifest.json"
    )
    if isinstance(manifest, Mapping):
        project = manifest.get("project")
        if isinstance(project, Mapping) and isinstance(project.get("projectId"), str):
            return project["projectId"]
    return None


def _remove_work_request(files: ProjectFiles) -> None:
    path = files.root / ".ai-sow/work/request.json"
    try:
        snapshot = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISREG(snapshot.st_mode) or stat.S_ISLNK(snapshot.st_mode):
        path.unlink(missing_ok=True)


def _source_path(files: ProjectFiles, source: SourceRequest) -> Path:
    candidate = source.path if source.path.is_absolute() else files.root / source.path
    try:
        snapshot = candidate.lstat()
    except OSError as error:
        raise SourceReadError("SOURCE_UNREADABLE", "来源文件无法读取。") from error
    if _is_unsafe(snapshot) or not stat.S_ISREG(snapshot.st_mode):
        raise SourceReadError("SOURCE_UNREADABLE", "来源文件无法读取。")
    return candidate


def _anchor_value(anchor) -> dict[str, object]:
    return {
        "anchorId": anchor.anchor_id,
        "sourceId": anchor.source_id,
        "kind": anchor.kind,
        "locator": anchor.locator,
        "normalizedText": anchor.normalized_text,
        "sha256": anchor.sha256,
    }


def _read_baseline(files: ProjectFiles) -> tuple[object | None, list[Mapping[str, object]]]:
    current = _optional_project_json(files, ".ai-sow/current.json")
    if not isinstance(current, Mapping):
        return None, []
    revision_id = current.get("revisionId")
    if not isinstance(revision_id, str):
        return None, []
    manifest = _optional_project_json(
        files, f".ai-sow/inputs/revisions/{revision_id}/manifest.json"
    )
    anchors = _optional_project_json(
        files, f".ai-sow/inputs/revisions/{revision_id}/anchors.json"
    )
    return (
        manifest,
        [item for item in anchors if isinstance(item, Mapping)]
        if isinstance(anchors, list)
        else [],
    )


def _key(value: Mapping[str, object], camel: str, snake: str) -> object:
    return value.get(camel, value.get(snake))


def _responsibility_map(value: object) -> dict[str, bytes]:
    if not isinstance(value, list):
        return {}
    return {
        str(item["responsibilityBoundaryId"]): canonical_json_bytes(item)
        for item in value
        if isinstance(item, Mapping) and "responsibilityBoundaryId" in item
    }


def compare_input_revisions(
    previous_manifest: Mapping[str, object] | None,
    previous_anchors: Sequence[Mapping[str, object]],
    pending_manifest: Mapping[str, object],
    pending_anchors: Sequence[Mapping[str, object]],
) -> InputChangeSet:
    previous_remaining = set(range(len(previous_anchors)))
    pending_remaining = set(range(len(pending_anchors)))
    changes: list[AnchorChange] = []

    previous_semantic: defaultdict[tuple[object, object], list[int]] = defaultdict(list)
    pending_semantic: defaultdict[tuple[object, object], list[int]] = defaultdict(list)
    for index, anchor in enumerate(previous_anchors):
        previous_semantic[
            (_key(anchor, "sourceId", "source_id"), anchor.get("sha256"))
        ].append(index)
    for index, anchor in enumerate(pending_anchors):
        pending_semantic[
            (_key(anchor, "sourceId", "source_id"), anchor.get("sha256"))
        ].append(index)

    for semantic_key in sorted(set(previous_semantic) & set(pending_semantic), key=str):
        old_indexes = previous_semantic[semantic_key]
        new_indexes = pending_semantic[semantic_key]
        if len(old_indexes) == len(new_indexes) == 1:
            old_index, new_index = old_indexes[0], new_indexes[0]
            previous_remaining.discard(old_index)
            pending_remaining.discard(new_index)
            old = previous_anchors[old_index]
            new = pending_anchors[new_index]
            if old.get("locator") != new.get("locator"):
                changes.append(
                    AnchorChange(
                        source_id=str(_key(new, "sourceId", "source_id")),
                        anchor_id=str(_key(new, "anchorId", "anchor_id")),
                        change="MOVED_UNCHANGED",
                        previous_sha256=str(old.get("sha256")),
                        current_sha256=str(new.get("sha256")),
                    )
                )
        elif len(old_indexes) == len(new_indexes):
            old_locators = [previous_anchors[index].get("locator") for index in old_indexes]
            new_locators = [pending_anchors[index].get("locator") for index in new_indexes]
            if old_locators == new_locators:
                previous_remaining.difference_update(old_indexes)
                pending_remaining.difference_update(new_indexes)

    previous_ids = {
        (_key(previous_anchors[index], "sourceId", "source_id"), _key(previous_anchors[index], "anchorId", "anchor_id")): index
        for index in previous_remaining
    }
    pending_ids = {
        (_key(pending_anchors[index], "sourceId", "source_id"), _key(pending_anchors[index], "anchorId", "anchor_id")): index
        for index in pending_remaining
    }
    for identity in sorted(set(previous_ids) & set(pending_ids), key=str):
        old_index, new_index = previous_ids[identity], pending_ids[identity]
        previous_remaining.discard(old_index)
        pending_remaining.discard(new_index)
        old = previous_anchors[old_index]
        new = pending_anchors[new_index]
        if old.get("sha256") != new.get("sha256"):
            changes.append(
                AnchorChange(
                    source_id=str(identity[0]),
                    anchor_id=str(identity[1]),
                    change="MODIFIED",
                    previous_sha256=str(old.get("sha256")),
                    current_sha256=str(new.get("sha256")),
                )
            )

    for index in sorted(previous_remaining):
        anchor = previous_anchors[index]
        changes.append(
            AnchorChange(
                source_id=str(_key(anchor, "sourceId", "source_id")),
                anchor_id=str(_key(anchor, "anchorId", "anchor_id")),
                change="REMOVED",
                previous_sha256=str(anchor.get("sha256")),
                current_sha256=None,
            )
        )
    for index in sorted(pending_remaining):
        anchor = pending_anchors[index]
        changes.append(
            AnchorChange(
                source_id=str(_key(anchor, "sourceId", "source_id")),
                anchor_id=str(_key(anchor, "anchorId", "anchor_id")),
                change="ADDED",
                previous_sha256=None,
                current_sha256=str(anchor.get("sha256")),
            )
        )

    previous_responsibilities = _responsibility_map(
        previous_manifest.get("responsibilityBoundaries", [])
        if previous_manifest is not None
        else []
    )
    pending_responsibilities = _responsibility_map(
        pending_manifest.get("responsibilityBoundaries", [])
    )
    responsibility_ids = tuple(
        sorted(
            key
            for key in set(previous_responsibilities) | set(pending_responsibilities)
            if previous_responsibilities.get(key) != pending_responsibilities.get(key)
        )
    )

    previous_sources = (
        previous_manifest.get("sources", []) if previous_manifest is not None else []
    )
    pending_sources = pending_manifest.get("sources", [])
    exact_match = (
        previous_manifest is not None
        and not changes
        and not responsibility_ids
        and canonical_json_bytes(previous_sources) == canonical_json_bytes(pending_sources)
    )
    return InputChangeSet(
        exact_match=exact_match,
        source_changes=tuple(
            sorted(changes, key=lambda item: (item.source_id, item.anchor_id, item.change))
        ),
        responsibility_ids=responsibility_ids,
    )


def _blocked_result(
    diagnostics: Sequence[Diagnostic],
    questions: Sequence[str] = (),
    *,
    pending_manifest_path: str = ".ai-sow/inputs/pending/manifest.json",
    anchors_path: str = ".ai-sow/inputs/pending/anchors.json",
) -> IntakeResult:
    return IntakeResult(
        outcome="BLOCKED",
        pending_manifest_path=pending_manifest_path,
        anchors_path=anchors_path,
        changes=InputChangeSet(False, (), ()),
        diagnostics=_sort_diagnostics(diagnostics),
        questions=tuple(sorted(set(questions))),
    )


def prepare_pending(
    files: ProjectFiles,
    request: InputRequest,
    *,
    revision_id: str,
    now: Callable[[], datetime],
) -> IntakeResult:
    try:
        if not revision_id.isdigit() or len(revision_id) != 6:
            return _blocked_result(
                [_diagnostic("REVISION_ID_INVALID", "revision ID 必须是六位数字。")]
            )
        try:
            existing_project_id = _existing_project_id(files)
        except ValueError:
            return _blocked_result(
                [_diagnostic("PROJECT_IDENTITY_INVALID", "既有项目身份无法安全读取。")]
            )
        if existing_project_id is not None and existing_project_id != request.project_id:
            return _blocked_result(
                [_diagnostic("PROJECT_IDENTITY_CONFLICT", "请求项目与既有项目身份不一致。")]
            )

        answer_diagnostics = validate_question_answers(
            request.questions, request.questionnaire_answers
        )
        if answer_diagnostics:
            return _blocked_result(answer_diagnostics)

        answer_anchors = question_answer_anchors(
            request.questions, request.questionnaire_answers
        )
        answer_source_ids = {anchor.source_id for anchor in answer_anchors}
        source_id_conflicts = tuple(
            _diagnostic(
                "QUESTION_ANSWER_SOURCE_ID_CONFLICT",
                "文档 sourceId 与问答证据保留的 sourceId 冲突。",
                f"/sources/{index}/sourceId",
            )
            for index, source in enumerate(request.sources)
            if source.source_id in answer_source_ids
        )
        if source_id_conflicts:
            return _blocked_result(source_id_conflicts)

        privacy_error = _ensure_privacy_ignore(files)
        if privacy_error is not None:
            return _blocked_result([privacy_error])

        ai_sow = files.ensure_dir(".ai-sow")
        inputs_root = files.ensure_dir(".ai-sow/inputs")
        pending = inputs_root / "pending"
        temp = ai_sow / f".pending-{secrets.token_hex(6)}"
        temp.mkdir()
        diagnostics: list[Diagnostic] = []
        questions: tuple[str, ...] = ()
        try:
            existing_manifest = _optional_json(pending / "manifest.json")
            effective_revision_id = revision_id
            if isinstance(existing_manifest, Mapping):
                previous_id = existing_manifest.get("revisionId")
                if isinstance(previous_id, str):
                    effective_revision_id = previous_id

            answers = [dict(item) for item in request.questionnaire_answers]

            source_entries: list[dict[str, object]] = []
            anchor_values: list[dict[str, object]] = []
            for source in request.sources:
                original = _source_path(files, source)
                original_name = original.name
                relative = (
                    f"sources/{source.role.lower()}/{source.source_id}/{original_name}"
                )
                destination = temp / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                payload = original.read_bytes()
                destination.write_bytes(payload)
                try:
                    anchors = extract_document(
                        destination,
                        source_id=source.source_id,
                        role=source.role,
                    )
                except SourceReadError as error:
                    diagnostics.append(_diagnostic(error.code, str(error), f"/sources/{source.source_id}"))
                    continue
                serialized = [_anchor_value(anchor) for anchor in anchors]
                anchor_values.extend(serialized)
                source_entries.append(
                    {
                        "sourceId": source.source_id,
                        "role": source.role,
                        "version": source.version,
                        "originalName": original_name,
                        "mediaType": source_media_type(destination, source.role),
                        "path": relative,
                        "sha256": hashlib.sha256(payload).hexdigest(),
                        "semanticSha256": sha256_bytes(canonical_json_bytes(serialized)),
                        "anchorCount": len(serialized),
                    }
                )

            anchor_values.extend(
                _anchor_value(anchor)
                for anchor in answer_anchors
            )

            source_entries.sort(key=lambda item: (str(item["role"]), str(item["sourceId"]), str(item["version"])))
            anchor_values.sort(key=lambda item: (str(item["sourceId"]), str(item["anchorId"])))
            recorded_at = now().isoformat().replace("+00:00", "Z")
            manifest: dict[str, object] = {
                "contract": "ai-sow-input-manifest-v1",
                "revisionId": effective_revision_id,
                "project": {
                    "projectId": request.project_id,
                    "name": request.project_name,
                    "plannedEffectiveDate": request.planned_effective_date,
                },
                "mode": request.mode,
                "responsibilityBoundaries": [
                    dict(item) for item in request.responsibility_boundaries
                ],
                "sources": source_entries,
                "questions": [dict(item) for item in request.questions],
                "questionnaireAnswers": answers,
                "anchorsPath": "anchors.json",
                "anchorsSha256": sha256_bytes(canonical_json_bytes(anchor_values)),
                "recordedAt": recorded_at,
            }
            (temp / "manifest.json").write_bytes(canonical_json_bytes(manifest))
            (temp / "answers.json").write_bytes(canonical_json_bytes(answers))
            (temp / "anchors.json").write_bytes(canonical_json_bytes(anchor_values))
            if diagnostics:
                (temp / "diagnostics.json").write_bytes(
                    canonical_json_bytes(
                        [
                            {"code": item.code, "message": item.message, "path": item.path}
                            for item in diagnostics
                        ]
                    )
                )
            else:
                contract_diagnostics = validate_contract(
                    manifest,
                    "input-manifest.schema.json",
                    SCHEMA_REGISTRY,
                )
                diagnostics.extend(contract_diagnostics)

            backup = inputs_root / f".pending-backup-{secrets.token_hex(6)}"
            had_pending = pending.exists()
            try:
                if had_pending:
                    os.replace(pending, backup)
                os.replace(temp, pending)
            except OSError:
                if had_pending and backup.exists() and not pending.exists():
                    os.replace(backup, pending)
                return _blocked_result(
                    [_diagnostic("PENDING_PUBLISH_FAILED", "pending 输入未能原子发布。")]
                )
            finally:
                if temp.exists():
                    shutil.rmtree(temp)
            if backup.exists():
                shutil.rmtree(backup)

            baseline_manifest, baseline_anchors = _read_baseline(files)
            changes = compare_input_revisions(
                baseline_manifest if isinstance(baseline_manifest, Mapping) else None,
                baseline_anchors,
                manifest,
                anchor_values,
            )
            outcome = "BLOCKED" if diagnostics else "READY"
            return IntakeResult(
                outcome=outcome,
                pending_manifest_path=".ai-sow/inputs/pending/manifest.json",
                anchors_path=".ai-sow/inputs/pending/anchors.json",
                changes=changes,
                diagnostics=_sort_diagnostics(diagnostics),
                questions=questions,
            )
        except SourceReadError as error:
            if temp.exists():
                shutil.rmtree(temp)
            return _blocked_result([_diagnostic(error.code, str(error))])
        except (OSError, ValueError, ProjectIOError):
            if temp.exists():
                shutil.rmtree(temp)
            return _blocked_result(
                [_diagnostic("PENDING_PREPARATION_FAILED", "pending 输入准备失败。")]
            )
    finally:
        _remove_work_request(files)
