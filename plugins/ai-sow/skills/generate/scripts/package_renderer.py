from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path

from contracts import canonical_json_bytes, sha256_bytes
from models import RenderedPackage
from workbook import write_workbook


RENDERER_CONTRACT = "generation-renderer-v1"


class PackageRenderError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _mappings(value: object) -> list[Mapping[str, object]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _ids(value: object) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _line_values(values: Sequence[str]) -> list[str]:
    return [f"- {value}" for value in values] or ["- 无"]


def _review_notes(review: Mapping[str, object]) -> dict[str, list[str]]:
    sections = {
        "ASSUMPTION": "estimation",
        "ESTIMATE_BOUNDARY": "estimation",
        "DESIGN_TASK": "design",
        "RESPONSIBILITY": "responsibility",
        "EXCLUSION": "exclusion",
        "CHANGE_TRIGGER": "risk",
    }
    result: dict[str, list[str]] = {}
    seen: set[str] = set()
    for note in _mappings(review.get("notes")):
        note_id = note.get("noteId")
        text = note.get("sowNotesText")
        category = note.get("category")
        if not isinstance(note_id, str) or not isinstance(text, str) or not isinstance(category, str):
            continue
        if note_id in seen:
            raise PackageRenderError("WORKBOOK_RENDER_FAILED", "终审说明 ID 重复。")
        seen.add(note_id)
        result.setdefault(sections[category], []).append(f"[{note_id}] {text}")
    return result


def render_notes(
    *,
    generation_id: str,
    input_manifest: Mapping[str, object],
    scope: Mapping[str, object],
    delivery: Mapping[str, object],
    review: Mapping[str, object],
) -> str:
    notes = _review_notes(review)
    sources = [
        f"{item.get('role')} / {item.get('originalName')} / {item.get('version')}"
        for item in _mappings(input_manifest.get("sources"))
    ]
    effective_start = [
        f"{item.get('name')}：{item.get('summary')}"
        for item in _mappings(scope.get("effectiveStartItems"))
    ]
    interpretations = [
        f"{item.get('name')}：{item.get('rationale')}"
        for item in _mappings(scope.get("designDecisions"))
    ] + [
        f"{item.get('name')}：{item.get('scopeDecision', {}).get('rationale')}"
        for item in _mappings(scope.get("features"))
        if isinstance(item.get("scopeDecision"), Mapping)
    ]
    estimation = [
        f"{item.get('name')}：{item.get('estimateBoundary')}；变化触发：{item.get('changeTrigger')}"
        for collection in ("integrations", "nfrs", "assumptions")
        for item in _mappings(scope.get(collection))
        if item.get("estimateBoundary")
    ] + notes.get("estimation", [])
    design = [
        f"{item.get('name')}：{item.get('rationale')}"
        for item in _mappings(delivery.get("tasks"))
        if item.get("taskKind") == "DESIGN"
    ] + notes.get("design", [])
    responsibilities = [
        f"{item.get('name')}（{item.get('party')}）：{'；'.join(_ids(item.get('responsibilities')))}"
        for item in _mappings(scope.get("responsibilityBoundaries"))
    ] + notes.get("responsibility", [])
    exclusions = [
        f"Feature {item.get('name')}：{item.get('scopeDecision', {}).get('rationale')}"
        for item in _mappings(scope.get("features"))
        if isinstance(item.get("scopeDecision"), Mapping)
        and item["scopeDecision"].get("decision") != "IN_SCOPE"
    ] + [
        f"往期承诺 {item.get('name')}：已排除"
        for item in _mappings(scope.get("commitments"))
        if item.get("treatment") == "EXCLUDE"
    ] + notes.get("exclusion", [])
    conflicts = [
        f"{item.get('name')}：{item.get('treatment')}"
        for item in _mappings(scope.get("commitments"))
        if item.get("treatment") in {"SUPERSEDE", "EXCLUDE"}
    ]
    unresolved_nfr = [
        f"{item.get('name')}：{item.get('targetOrRationale')}"
        for item in _mappings(scope.get("nfrs"))
        if item.get("status") == "DESIGN_REQUIRED"
    ]
    risks = [
        f"{item.get('name')}：{item.get('trigger')}；变化触发：{item.get('changeTrigger')}"
        for item in _mappings(scope.get("assumptions"))
    ] + notes.get("risk", [])
    carry_forward = [
        f"{item.get('name')}：{item.get('treatment')}"
        for item in _mappings(scope.get("commitments"))
        if item.get("treatment") == "CARRY_FORWARD"
    ]
    conclusion = (
        "无重大未决事项"
        if review.get("decision") == "PASS" and not _mappings(review.get("notes"))
        else str(review.get("decision"))
    )
    sections = [
        (
            "生成与输入版本",
            [
                f"generation：{generation_id}",
                f"input revision：{input_manifest.get('revisionId')}",
                f"renderer：{RENDERER_CONTRACT}",
                f"终审：{conclusion}",
            ],
        ),
        ("来源版本与适用性", sources),
        ("As-Is 与 Effective Start 证据边界", effective_start),
        ("解释与推断", interpretations),
        ("估算假设与边界", estimation),
        ("Design Tasks 与待设计事项", design),
        ("参与方责任", responsibilities),
        ("外部排除项", exclusions),
        ("冲突与处置", conflicts),
        ("未决 NFR", unresolved_nfr),
        ("风险与变化触发", risks),
        ("往期 SOW 沿用", carry_forward),
    ]
    lines = ["# SOW 生成说明", ""]
    for heading, values in sections:
        lines.extend([f"## {heading}", "", *_line_values(values), ""])
    return "\n".join(lines).rstrip() + "\n"


def render_package(
    *,
    generation_id: str,
    template_path: Path,
    output_root: Path,
    input_manifest: Mapping[str, object],
    scope: Mapping[str, object],
    delivery: Mapping[str, object],
    review: Mapping[str, object],
) -> RenderedPackage:
    root = Path(output_root).absolute()
    root.parent.mkdir(parents=True, exist_ok=True)
    root_exists = root.exists()
    if root_exists and any(root.iterdir()):
        raise PackageRenderError("WORKBOOK_RENDER_FAILED", "渲染目标已存在。")
    temporary = Path(tempfile.mkdtemp(prefix=".render-", dir=root.parent))
    try:
        output = temporary / "output"
        output.mkdir()
        workbook_path = output / "sow.xlsx"
        notes_path = output / "sow-notes.md"
        manifest_sha = sha256_bytes(canonical_json_bytes(input_manifest))
        scope_sha = sha256_bytes(canonical_json_bytes(scope))
        delivery_sha = sha256_bytes(canonical_json_bytes(delivery))
        input_hashes = {
            "sourceRequirements": manifest_sha,
            "asis": scope_sha,
            "design": scope_sha,
            "derivedRequirements": scope_sha,
            "delivery": delivery_sha,
            "estimate": delivery_sha,
        }
        try:
            write_workbook(
                Path(template_path),
                dict(scope),
                dict(delivery),
                workbook_path,
                input_hashes,
            )
        except (OSError, KeyError, TypeError, ValueError, zipfile.BadZipFile) as error:
            raise PackageRenderError(
                "WORKBOOK_RENDER_FAILED", "工作簿渲染失败。"
            ) from error
        notes_text = render_notes(
            generation_id=generation_id,
            input_manifest=input_manifest,
            scope=scope,
            delivery=delivery,
            review=review,
        )
        notes_path.write_text(notes_text, encoding="utf-8", newline="\n")
        if notes_path.read_text(encoding="utf-8") != notes_text:
            raise PackageRenderError("WORKBOOK_VERIFY_FAILED", "说明文件复读失败。")
        if root_exists:
            os.replace(temporary / "output", root / "output")
            temporary.rmdir()
        else:
            os.replace(temporary, root)
        temporary = root
        workbook_final = root / "output/sow.xlsx"
        notes_final = root / "output/sow-notes.md"
        return RenderedPackage(
            root=str(root),
            workbook_path=str(workbook_final),
            notes_path=str(notes_final),
            workbook_sha256=sha256_bytes(workbook_final.read_bytes()),
            notes_sha256=sha256_bytes(notes_final.read_bytes()),
            files=("output/sow-notes.md", "output/sow.xlsx"),
        )
    except PackageRenderError:
        raise
    except (OSError, UnicodeError) as error:
        raise PackageRenderError("WORKBOOK_VERIFY_FAILED", "交付包复读失败。") from error
    finally:
        if temporary != root and temporary.exists():
            shutil.rmtree(temporary)
