from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.exceptions import NoSuchResource

from models import Diagnostic


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def load_schema_registry(skill_root: Path) -> Registry:
    registry = Registry()
    for path in sorted((skill_root / "contracts").glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        schema_id = schema.get("$id")
        if not isinstance(schema_id, str) or not schema_id:
            raise ValueError(f"Schema 缺少非空 $id：{path.name}")
        registry = registry.with_resource(schema_id, Resource.from_contents(schema))
    return registry


def _schema_id(schema_name: str) -> str:
    suffix = ".schema.json"
    if not schema_name.endswith(suffix):
        raise ValueError(f"Schema 名称必须以 {suffix} 结尾")
    return f"urn:ai-sow:generate:{schema_name.removesuffix(suffix)}:1"


def _json_pointer(parts: object) -> str:
    escaped = [
        str(part).replace("~", "~0").replace("/", "~1") for part in parts  # type: ignore[arg-type]
    ]
    return "/" + "/".join(escaped) if escaped else ""


def _diagnostic(
    code: str,
    path: str,
    message: str,
    **details: object,
) -> Diagnostic:
    return Diagnostic(code=code, message=message, path=path, details=details)


def _sort_diagnostics(diagnostics: list[Diagnostic]) -> tuple[Diagnostic, ...]:
    return tuple(sorted(diagnostics, key=lambda item: (item.path, item.code, item.message)))


def validate_contract(
    value: object,
    schema_name: str,
    registry: Registry,
) -> tuple[Diagnostic, ...]:
    try:
        schema = registry.get(_schema_id(schema_name)).contents
        errors = tuple(Draft202012Validator(schema, registry=registry).iter_errors(value))
    except (NoSuchResource, LookupError, ValueError) as error:
        return (
            _diagnostic(
                "CONTRACT_REFERENCE_INVALID",
                "",
                "合同引用无法解析。",
                schema=schema_name,
                errorType=type(error).__name__,
            ),
        )

    diagnostics: list[Diagnostic] = []
    for error in errors:
        code = {
            "required": "CONTRACT_REQUIRED",
            "additionalProperties": "CONTRACT_UNEXPECTED_PROPERTY",
        }.get(error.validator, "CONTRACT_INVALID")
        message = {
            "CONTRACT_REQUIRED": "合同缺少必填字段。",
            "CONTRACT_UNEXPECTED_PROPERTY": "合同包含未声明字段。",
            "CONTRACT_INVALID": "合同值不符合 Schema。",
        }[code]
        diagnostics.append(
            _diagnostic(
                code,
                _json_pointer(error.absolute_path),
                message,
                schema=schema_name,
                validator=str(error.validator),
                schemaPath=_json_pointer(error.absolute_schema_path),
            )
        )
    return _sort_diagnostics(diagnostics)


def validate_id_decisions(
    value: object,
    registry: Registry,
) -> tuple[Diagnostic, ...]:
    diagnostics = list(validate_contract(value, "id-decisions.schema.json", registry))
    if not isinstance(value, Mapping):
        return _sort_diagnostics(diagnostics)
    decisions = value.get("decisions")
    if not isinstance(decisions, list):
        return _sort_diagnostics(diagnostics)

    seen: set[tuple[object, object]] = set()
    for index, decision in enumerate(decisions):
        if not isinstance(decision, Mapping):
            continue
        path = f"/decisions/{index}"
        identity = (decision.get("objectType"), decision.get("objectId"))
        if identity in seen:
            diagnostics.append(
                _diagnostic(
                    "ID_DECISION_DUPLICATE",
                    path,
                    "同一对象只能有一条 ID 决定。",
                )
            )
        seen.add(identity)

        disposition = decision.get("disposition")
        object_id = decision.get("objectId")
        previous_id = decision.get("previousId")
        if disposition in {"UNCHANGED", "CLARIFIED"} and previous_id != object_id:
            diagnostics.append(
                _diagnostic(
                    "ID_PRESERVED_USES_DIFFERENT_ID",
                    path,
                    "含义保留的对象必须继续使用原 ID。",
                )
            )
        if disposition == "CHANGED" and previous_id == object_id:
            diagnostics.append(
                _diagnostic(
                    "ID_CHANGED_REUSES_PREVIOUS",
                    path,
                    "实质含义变化的对象不得复用原 ID。",
                )
            )
    return _sort_diagnostics(diagnostics)


def validate_final_review(
    value: object,
    registry: Registry,
    *,
    expected_packet_sha256: str | None = None,
) -> tuple[Diagnostic, ...]:
    diagnostics = list(validate_contract(value, "final-review.schema.json", registry))
    if not isinstance(value, Mapping):
        return _sort_diagnostics(diagnostics)

    decision = value.get("decision")
    notes = value.get("notes")
    questions = value.get("questions")
    if decision == "BLOCKED" and isinstance(questions, list) and not questions:
        diagnostics.append(
            _diagnostic(
                "FINAL_REVIEW_BLOCKED_QUESTIONS_REQUIRED",
                "/questions",
                "BLOCKED 终审必须给出至少一个最小问题。",
            )
        )
    if decision == "PASS_WITH_NOTES" and isinstance(notes, list) and not notes:
        diagnostics.append(
            _diagnostic(
                "FINAL_REVIEW_NOTES_REQUIRED",
                "/notes",
                "PASS_WITH_NOTES 终审必须给出至少一条说明。",
            )
        )
    if decision == "PASS" and (
        (isinstance(notes, list) and notes)
        or (isinstance(questions, list) and questions)
    ):
        diagnostics.append(
            _diagnostic(
                "FINAL_REVIEW_PASS_MUST_BE_EMPTY",
                "",
                "PASS 终审不得包含说明或问题。",
            )
        )

    if (
        expected_packet_sha256 is not None
        and value.get("packetSha256") != expected_packet_sha256
    ):
        diagnostics.append(
            _diagnostic(
                "FINAL_REVIEW_PACKET_HASH_MISMATCH",
                "/packetSha256",
                "终审结果未绑定预期 review packet。",
            )
        )

    for field, identifier in (
        ("notes", "noteId"),
        ("questions", "questionId"),
    ):
        items = value.get(field)
        if not isinstance(items, list):
            continue
        ids = [item.get(identifier) for item in items if isinstance(item, Mapping)]
        if len(ids) != len(set(ids)):
            diagnostics.append(
                _diagnostic(
                    "FINAL_REVIEW_DUPLICATE_ITEM",
                    f"/{field}",
                    "终审说明或问题不得重复。",
                )
            )
    return _sort_diagnostics(diagnostics)


def validate_generation_hash_closure(
    value: object,
    registry: Registry,
) -> tuple[Diagnostic, ...]:
    diagnostics = list(
        validate_contract(value, "generation-manifest.schema.json", registry)
    )
    if not isinstance(value, Mapping):
        return _sort_diagnostics(diagnostics)

    generation_id = value.get("generationId")
    revision_id = value.get("revisionId")
    generation_prefix = f".ai-sow/generations/{generation_id}/"
    revision_prefix = f".ai-sow/inputs/revisions/{revision_id}/"
    path_mismatch = False
    for field in ("scopePath", "deliveryPath", "workbookPath", "notesPath"):
        path = value.get(field)
        if not isinstance(path, str) or not path.startswith(generation_prefix):
            path_mismatch = True
    input_path = value.get("inputManifestPath")
    if not isinstance(input_path, str) or not input_path.startswith(revision_prefix):
        path_mismatch = True
    if path_mismatch:
        diagnostics.append(
            _diagnostic(
                "GENERATION_PATH_ID_MISMATCH",
                "",
                "generation 或 revision 路径与其 ID 不一致。",
            )
        )

    review = value.get("finalReview")
    if isinstance(review, Mapping):
        expected = sha256_bytes(canonical_json_bytes(review))
        if value.get("finalReviewSha256") != expected:
            diagnostics.append(
                _diagnostic(
                    "GENERATION_REVIEW_HASH_MISMATCH",
                    "/finalReviewSha256",
                    "generation 未绑定终审对象的 canonical SHA-256。",
                )
            )
        if (
            review.get("inputRevisionId") != revision_id
            or review.get("scopeSha256") != value.get("scopeSha256")
            or review.get("deliverySha256") != value.get("deliverySha256")
        ):
            diagnostics.append(
                _diagnostic(
                    "GENERATION_REVIEW_INPUT_MISMATCH",
                    "/finalReview",
                    "终审对象未绑定 generation 使用的 revision、Scope 或 Delivery。",
                )
            )
        if review.get("decision") not in {"PASS", "PASS_WITH_NOTES"}:
            diagnostics.append(
                _diagnostic(
                    "GENERATION_REVIEW_NOT_ACCEPTED",
                    "/finalReview/decision",
                    "只有通过或带说明通过的终审才能进入 generation。",
                )
            )
        if value.get("decision") != review.get("decision"):
            diagnostics.append(
                _diagnostic(
                    "GENERATION_DECISION_MISMATCH",
                    "/decision",
                    "generation decision 与内嵌终审不一致。",
                )
            )
    return _sort_diagnostics(diagnostics)
