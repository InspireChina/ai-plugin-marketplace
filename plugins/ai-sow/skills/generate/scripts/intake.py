from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import stat
import sys
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[2]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from contracts import (
    canonical_json_bytes,
    load_registry,
    sha256_bytes,
    validate_contract,
)
from models import Diagnostic, InputRevisionResult
from questions import question_answer_anchors, validate_question_answers
from runtime.project_io import ProjectFiles, ProjectIOError
from source_readers import (
    SourceReadError,
    extract_source_blocks,
    inspect_source_header,
)


SKILL_ROOT = Path(__file__).resolve().parents[1]
NEXT_SCHEMA_REGISTRY = load_registry(SKILL_ROOT / "contracts")
TEMPLATE_ASSET = SKILL_ROOT / "assets/sow-template.xlsx"
PROJECT_TEMPLATE_PATH = ".ai-sow/templates/sow-template.xlsx"
DELIVERY_POLICY_ASSET = SKILL_ROOT / "contracts/delivery-policy-v1.json"
EXECUTION_POLICY_ASSET = SKILL_ROOT / "contracts/execution-policy-v1.json"
PARSER_VERSION = "2"


def _diagnostic(code: str, message: str, path: str = "") -> Diagnostic:
    return Diagnostic(code=code, message=message, path=path, details={})


def _sort_diagnostics(values: Sequence[Diagnostic]) -> tuple[Diagnostic, ...]:
    return tuple(sorted(values, key=lambda item: (item.path, item.code, item.message)))


def _is_unsafe(snapshot: os.stat_result) -> bool:
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(snapshot.st_mode) or bool(
        getattr(snapshot, "st_file_attributes", 0) & reparse
    )


def _revision_failure(diagnostics: Sequence[Diagnostic]) -> InputRevisionResult:
    return InputRevisionResult(
        value=None,
        path=None,
        sha256=None,
        diagnostics=_sort_diagnostics(diagnostics),
    )


def _selected_next_sources(value: Mapping[str, object]) -> list[Mapping[str, object]]:
    sources = value.get("sources")
    assert isinstance(sources, list)
    selected = [
        {**source, "_requestPath": f"/sources/{index}"}
        for index, source in enumerate(sources)
        if isinstance(source, Mapping)
    ]
    demo = value.get("demo")
    if isinstance(demo, Mapping):
        files = demo.get("files")
        if isinstance(files, list):
            selected.extend(
                {**source, "_requestPath": f"/demo/files/{index}"}
                for index, source in enumerate(files)
                if isinstance(source, Mapping)
            )
    return selected


def _template_table_names(path: Path) -> set[str]:
    try:
        with zipfile.ZipFile(path) as archive:
            table_paths = sorted(
                name
                for name in archive.namelist()
                if re.fullmatch(r"xl/tables/table[0-9]+\.xml", name)
            )
            return {
                str(ET.fromstring(archive.read(name)).attrib["name"])
                for name in table_paths
            }
    except (OSError, KeyError, ET.ParseError, zipfile.BadZipFile) as error:
        raise SourceReadError(
            "TEMPLATE_CONTRACT_INVALID", "SOW 模板无法读取 Table 合同。"
        ) from error


def _next_template_path(files: ProjectFiles) -> Path:
    try:
        return files.resolve(PROJECT_TEMPLATE_PATH)
    except ProjectIOError as error:
        if error.code != "PROJECT_PATH_MISSING":
            raise
    return TEMPLATE_ASSET


def _cheap_prepare_gate(
    value: object,
    *,
    files: ProjectFiles,
) -> tuple[
    Mapping[str, object] | None,
    tuple[Mapping[str, object], ...],
    Path | None,
    tuple[Diagnostic, ...],
]:
    diagnostics = list(
        validate_contract(value, "request.schema.json", NEXT_SCHEMA_REGISTRY)
    )
    if diagnostics or not isinstance(value, Mapping):
        return None, (), None, _sort_diagnostics(diagnostics)

    sources = _selected_next_sources(value)
    source_ids: set[str] = set()
    for index, source in enumerate(sources):
        request_path = str(source.get("_requestPath", f"/sources/{index}"))
        source_id = source.get("sourceId")
        if isinstance(source_id, str) and source_id in source_ids:
            diagnostics.append(
                _diagnostic(
                    "SOURCE_ID_DUPLICATE",
                    "sourceId 必须在当前请求中唯一。",
                    f"{request_path}/sourceId",
                )
            )
        if isinstance(source_id, str):
            source_ids.add(source_id)

    roles = [source.get("role") for source in sources]
    if value.get("mode") == "GREENFIELD" and "PRIOR_SOW" in roles:
        diagnostics.append(
            _diagnostic(
                "GREENFIELD_PRIOR_SOW_FORBIDDEN",
                "Greenfield 请求不得携带 PRIOR_SOW。",
                "/sources",
            )
        )
    if "PRD" not in roles:
        diagnostics.append(
            _diagnostic("PRD_REQUIRED", "必须提供已批准 PRD。", "/sources")
        )
    design_sources = [source for source in sources if source.get("role") in {"HLD", "ADR"}]
    if not design_sources:
        diagnostics.append(_diagnostic("APPROVED_DESIGN_REQUIRED", "必须提供至少一份 HLD 或 ADR。", "/sources"))
    if value.get("mode") == "BROWNFIELD" and value.get("declaredChangeContext") is None:
        diagnostics.append(
            _diagnostic(
                "BROWNFIELD_DECLARED_CHANGE_CONTEXT_REQUIRED",
                "Brownfield 必须声明当前状态变化。",
                "/declaredChangeContext",
            )
        )

    question_values = value.get("questions")
    answer_values = value.get("questionnaireAnswers")
    if isinstance(question_values, list) and isinstance(answer_values, list):
        diagnostics.extend(
            validate_question_answers(
                [item for item in question_values if isinstance(item, Mapping)],
                [item for item in answer_values if isinstance(item, Mapping)],
            )
        )

    resolved: list[Mapping[str, object]] = []
    if not diagnostics:
        for index, source in enumerate(sources):
            request_path = str(source.get("_requestPath", f"/sources/{index}"))
            relative_path = source.get("path")
            role = source.get("role")
            assert isinstance(relative_path, str) and isinstance(role, str)
            try:
                path = files.resolve(relative_path)
                if sha256_bytes(path.read_bytes()) != source.get("expectedSha256"):
                    raise SourceReadError("SOURCE_HASH_MISMATCH", "来源字节哈希与 expectedSha256 不一致。")
                inspect_source_header(path, source_role=role)
            except (ProjectIOError, SourceReadError) as error:
                code = error.code
                diagnostics.append(
                    _diagnostic(code, str(error), f"{request_path}/path")
                )
            else:
                resolved.append({**source, "_resolvedPath": path})

    if not diagnostics and isinstance(value.get("demo"), Mapping):
        from prototype_analysis import inventory_demo_bundle, PrototypeError

        try:
            inventory_demo_bundle(str(value["demo"]["entrypoint"]), [
                {"sourceId": source["sourceId"], "relativePath": source["path"],
                 "content": source["_resolvedPath"].read_bytes()}
                for source in resolved if source["role"] == "DEMO"
            ])
        except PrototypeError as error:
            diagnostics.append(_diagnostic(error.code, "Demo 静态 bundle 未通过边界校验。", "/demo"))

    template_path: Path | None = None
    if not diagnostics:
        try:
            template_path = _next_template_path(files)
            from workbook import FORMAL_TABLES

            table_names = _template_table_names(template_path)
            if table_names != FORMAL_TABLES:
                diagnostics.append(
                    _diagnostic(
                        "TEMPLATE_TABLES_INVALID",
                        "SOW 模板命名 Table 集合不符合合同。",
                        PROJECT_TEMPLATE_PATH,
                    )
                )
        except (ProjectIOError, SourceReadError, OSError) as error:
            code = getattr(error, "code", "TEMPLATE_CONTRACT_INVALID")
            diagnostics.append(
                _diagnostic(code, str(error), PROJECT_TEMPLATE_PATH)
            )

    if diagnostics:
        return value, (), None, _sort_diagnostics(diagnostics)
    return value, tuple(resolved), template_path, ()


def _bind_source_blocks(
    source_id: str,
    blocks: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    replacements = {
        str(block["blockId"]): (
            "block-"
            + sha256_bytes(
                canonical_json_bytes([source_id, str(block["blockId"])])
            )[:20]
        )
        for block in blocks
    }
    bound: list[dict[str, object]] = []
    for block in blocks:
        block_id = replacements[str(block["blockId"])]
        primary = replacements.get(
            str(block["primaryCoverageBlockId"]),
            str(block["primaryCoverageBlockId"]),
        )
        parent_value = block.get("structuralParentId")
        bound.append(
            {
                **block,
                "blockId": block_id,
                "sourceId": source_id,
                "primaryCoverageBlockId": primary,
                "contextBlockIds": [
                    replacements.get(str(item), str(item))
                    for item in block.get("contextBlockIds", [])
                ],
                "structuralParentId": (
                    replacements.get(str(parent_value), str(parent_value))
                    if parent_value is not None
                    else None
                ),
            }
        )
    return tuple(bound)


def _manifest_block(block: Mapping[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in block.items()
        if key
        in {
            "blockId",
            "sourceId",
            "rawSha256",
            "contentSha256",
            "locator",
            "primaryCoverageBlockId",
            "contextBlockIds",
            "structuralParentId",
            "extractionDisposition",
            "droppedContentCategories",
        }
    }


def _tree_snapshot(path: Path) -> dict[str, bytes]:
    snapshot = path.lstat()
    if _is_unsafe(snapshot) or not stat.S_ISDIR(snapshot.st_mode):
        raise ProjectIOError(
            "PROJECT_PATH_UNSAFE",
            str(path),
            "Input Revision tree 必须是无链接的普通目录树。",
        )
    result: dict[str, bytes] = {}

    def visit(directory: Path) -> None:
        for child in sorted(directory.iterdir(), key=lambda item: item.name):
            child_snapshot = child.lstat()
            if _is_unsafe(child_snapshot):
                raise ProjectIOError(
                    "PROJECT_PATH_UNSAFE",
                    str(child),
                    "Input Revision tree 包含链接或 reparse point。",
                )
            if stat.S_ISDIR(child_snapshot.st_mode):
                visit(child)
            elif stat.S_ISREG(child_snapshot.st_mode):
                result[child.relative_to(path).as_posix()] = child.read_bytes()
            else:
                raise ProjectIOError(
                    "PROJECT_PATH_TYPE",
                    str(child),
                    "Input Revision tree 包含特殊文件。",
                )

    visit(path)
    return result


def _accept_revision_tree(
    files: ProjectFiles,
    built_root: Path,
    revision_id: str,
) -> str:
    files.ensure_dir(".ai-sow/inputs")
    pending_root = files.ensure_dir(".ai-sow/inputs/pending")
    revisions_root = files.ensure_dir(".ai-sow/inputs/revisions")
    final = revisions_root / revision_id
    relative_root = f".ai-sow/inputs/revisions/{revision_id}"
    if final.exists():
        if _tree_snapshot(final) == _tree_snapshot(built_root):
            return relative_root
        raise ProjectIOError(
            "PROJECT_CONTENT_CONFLICT",
            relative_root,
            "content-addressed Input Revision 已存在但内容不一致。",
        )

    staging = pending_root / f".stage-{secrets.token_hex(6)}"
    try:
        shutil.copytree(built_root, staging)
        try:
            os.replace(staging, final)
        except OSError:
            if final.exists() and _tree_snapshot(final) == _tree_snapshot(built_root):
                return relative_root
            raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return relative_root


def prepare(request_path: str, *, files: ProjectFiles) -> InputRevisionResult:
    """Rebuild a lossless snapshot solely from this explicit request and its sources."""
    try:
        request_payload = files.read_bytes(request_path)
        try:
            request_value = json.loads(request_payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _revision_failure(
                [_diagnostic("PROJECT_JSON_INVALID", "输入请求不是有效 JSON。", request_path)]
            )
        value, sources, template_path, diagnostics = _cheap_prepare_gate(
            request_value,
            files=files,
        )
        if diagnostics or value is None or template_path is None:
            return _revision_failure(diagnostics)

        source_results: list[dict[str, object]] = []
        bound_blocks: list[dict[str, object]] = []
        raw_sources: list[tuple[str, str, bytes]] = []
        for index, source in enumerate(sources):
            source_id = str(source["sourceId"])
            role = str(source["role"])
            path = source["_resolvedPath"]
            assert isinstance(path, Path)
            try:
                document = extract_source_blocks(
                    path,
                    source_role=role,
                    parser_version=PARSER_VERSION,
                )
            except SourceReadError as error:
                return _revision_failure(
                    [_diagnostic(error.code, str(error), f"/sources/{index}/path")]
                )
            blocks = _bind_source_blocks(source_id, document.blocks)
            bound_blocks.extend(blocks)
            extension = path.suffix.casefold()
            directory = "prior-sows" if role == "PRIOR_SOW" else "sources"
            source_relative = f"{directory}/{source_id}/source{extension}"
            if role == "DEMO":
                source_relative = f"demo/{source['path']}"
            source_payload = path.read_bytes()
            if (
                sha256_bytes(source_payload) != document.raw_sha256
                or document.raw_sha256 != source.get("expectedSha256")
            ):
                return _revision_failure(
                    [
                        _diagnostic(
                            "SOURCE_CHANGED_DURING_PREPARE",
                            "来源在解析期间发生变化，请重新准备输入。",
                            f"/sources/{index}/path",
                        )
                    ]
                )
            raw_sources.append((source_relative, source_id, source_payload))
            source_results.append(
                {
                    "sourceId": source_id,
                    "role": role,
                    "status": {
                        "PRD": "APPROVED", "HLD": "APPROVED", "ADR": "APPROVED",
                        "DEMO": "SELECTED", "PRIOR_SOW": "APPLICABLE",
                        "SUPPLEMENT": "REFERENCE_ONLY",
                    }[role],
                    "path": source_relative,
                    "rawSha256": document.raw_sha256,
                    "parserId": document.parser_id,
                    "parserVersion": document.parser_version,
                    "blockIds": [block["blockId"] for block in blocks],
                }
            )

        answer_anchors = question_answer_anchors(
            [item for item in value["questions"] if isinstance(item, Mapping)],
            [
                item
                for item in value["questionnaireAnswers"]
                if isinstance(item, Mapping)
            ],
        )
        for anchor in answer_anchors:
            content = anchor.normalized_text
            raw = content.encode("utf-8")
            block_id = f"block-{sha256_bytes(canonical_json_bytes([anchor.source_id, anchor.anchor_id]))[:20]}"
            block = {
                "blockId": block_id,
                "sourceId": anchor.source_id,
                "rawSha256": sha256_bytes(raw),
                "contentSha256": sha256_bytes(raw),
                "locator": anchor.locator,
                "primaryCoverageBlockId": block_id,
                "contextBlockIds": [],
                "structuralParentId": None,
                "extractionDisposition": "INCLUDED",
                "droppedContentCategories": [],
                "content": content,
            }
            bound_blocks.append(block)
            answer_path = f"sources/{anchor.source_id}/answer.txt"
            raw_sources.append((answer_path, anchor.source_id, raw))
            source_results.append(
                {
                    "sourceId": anchor.source_id,
                    "role": "QUESTION_ANSWER",
                    "status": "BOUND",
                    "path": answer_path,
                    "rawSha256": sha256_bytes(raw),
                    "parserId": "question-answer",
                    "parserVersion": PARSER_VERSION,
                    "blockIds": [block_id],
                }
            )

        template_payload = template_path.read_bytes()
        delivery_policy = DELIVERY_POLICY_ASSET.read_bytes()
        execution_policy = EXECUTION_POLICY_ASSET.read_bytes()
        prior_hashes = sorted({
            str(source["rawSha256"])
            for source in source_results
            if source["role"] == "PRIOR_SOW"
        })
        source_results.sort(key=lambda item: (str(item["role"]), str(item["sourceId"])))
        bound_blocks.sort(key=lambda item: (str(item["sourceId"]), str(item["locator"]), str(item["blockId"])))
        identity = {
            "requestSha256": sha256_bytes(request_payload),
            "templateSha256": sha256_bytes(template_payload),
            "deliveryPolicySha256": sha256_bytes(delivery_policy),
            "executionPolicySha256": sha256_bytes(execution_policy),
            "project": value["project"],
            "sources": source_results,
            "blocks": [_manifest_block(block) for block in bound_blocks],
        }
        revision_id = f"revision-{sha256_bytes(canonical_json_bytes(identity))[:16]}"
        revision_root = f".ai-sow/inputs/revisions/{revision_id}"
        for source in source_results:
            source["path"] = f"{revision_root}/{source['path']}"
        manifest = {
            "contract": "ai-sow-input-revision-v1",
            "revisionId": revision_id,
            "requestSha256": sha256_bytes(request_payload),
            "templateSha256": sha256_bytes(template_payload),
            "deliveryPolicySha256": sha256_bytes(delivery_policy),
            "executionPolicySha256": sha256_bytes(execution_policy),
            "project": value["project"],
            "priorSowState": "PROVIDED" if prior_hashes else "NOT_PROVIDED",
            "priorSowSha256s": prior_hashes,
            "sources": source_results,
            "blocks": [_manifest_block(block) for block in bound_blocks],
        }
        contract_diagnostics = validate_contract(
            manifest,
            "input-revision.schema.json",
            NEXT_SCHEMA_REGISTRY,
        )
        if contract_diagnostics:
            return _revision_failure(contract_diagnostics)
        manifest_payload = canonical_json_bytes(manifest)

        build_root = files.ensure_dir(".ai-sow/inputs/pending") / (
            f".build-{secrets.token_hex(6)}"
        )
        try:
            build_root.mkdir()
            built_root = build_root / revision_id
            built_root.mkdir()
            (built_root / "request.json").write_bytes(request_payload)
            (built_root / "sow-template.xlsx").write_bytes(template_payload)
            (built_root / "delivery-policy.json").write_bytes(delivery_policy)
            (built_root / "execution-policy.json").write_bytes(execution_policy)
            for relative, _, payload in raw_sources:
                destination = built_root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(payload)
            for block in bound_blocks:
                destination = built_root / "blocks" / f"{block['blockId']}.json"
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(canonical_json_bytes(block))
            (built_root / "manifest.json").write_bytes(manifest_payload)
            accepted_root = _accept_revision_tree(files, built_root, revision_id)
        finally:
            if build_root.exists():
                shutil.rmtree(build_root)

        manifest_path = f"{accepted_root}/manifest.json"
        return InputRevisionResult(
            value=manifest,
            path=manifest_path,
            sha256=sha256_bytes(manifest_payload),
            diagnostics=(),
        )
    except ProjectIOError as error:
        return _revision_failure(
            [_diagnostic(error.code, str(error), error.relative_path)]
        )
    except (OSError, ValueError) as error:
        return _revision_failure(
            [_diagnostic("INPUT_REVISION_PREPARATION_FAILED", str(error), request_path)]
        )
