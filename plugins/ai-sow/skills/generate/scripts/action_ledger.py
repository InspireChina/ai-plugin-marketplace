from __future__ import annotations
from collections.abc import Callable

from dataclasses import dataclass, field, replace
from functools import lru_cache
import json
from pathlib import Path
from types import MappingProxyType
from typing import Mapping
from jsonschema import Draft202012Validator

from contracts import (
    canonical_json_bytes,
    normalize_action_result,
    sha256_bytes,
    InvalidActionResult,
    usage_value,
    validate_action_usage,
    validate_attempt_timing,
    validate_usage,
    action_contract_binding,
    load_schema_registry,
)
from models import (
    ActionEnvelope,
    AttemptCompletion,
    AttemptDiagnostic,
    AttemptRecord,
    AttemptTiming,
    ContextRefDescriptor,
    Usage,
)

SKILL_ROOT = Path(__file__).parents[1]


@dataclass(frozen=True)
class ActionLedger:
    envelopes_by_sha256: Mapping[str, ActionEnvelope] = field(default_factory=dict)
    attempt_records: Mapping[str, AttemptRecord] = field(default_factory=dict)
    raw_outputs: Mapping[str, bytes] = field(default_factory=dict)
    normalized_results: Mapping[str, bytes] = field(default_factory=dict)

    def __post_init__(self):
        for name in (
            "envelopes_by_sha256",
            "attempt_records",
            "raw_outputs",
            "normalized_results",
        ):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))
        seen = set()
        for digest, record in self.attempt_records.items():
            if (
                digest
                != sha256_bytes(canonical_json_bytes(attempt_record_value(record)))
                or record.envelope_sha256 in seen
            ):
                raise ValueError("AttemptRecord hash 无效或同 Envelope 存在重复终态。")
            seen.add(record.envelope_sha256)
            _record_envelope(record, self.envelopes_by_sha256)
            for content_hash, collection in (
                (record.raw_sha256, self.raw_outputs),
                (record.normalized_result_sha256, self.normalized_results),
            ):
                if content_hash is not None and (
                    content_hash not in collection
                    or sha256_bytes(collection[content_hash]) != content_hash
                ):
                    raise ValueError("AttemptRecord 内容 hash 无效。")


def attempt_record_value(record: AttemptRecord) -> dict[str, object]:
    diagnostic = record.diagnostic
    return {
        "logicalWorkId": record.logical_work_id,
        "revision": record.revision,
        "attempt": record.attempt,
        "envelopeSha256": record.envelope_sha256,
        "outcome": record.outcome,
        "failureKind": record.failure_kind,
        "diagnostic": (
            None
            if diagnostic is None
            else {
                "code": diagnostic.code,
                "path": diagnostic.path,
                "subjectIds": list(diagnostic.subject_ids),
            }
        ),
        "rawSha256": record.raw_sha256,
        "normalizedResultSha256": record.normalized_result_sha256,
        "usage": usage_value(record.usage),
        "timing": {
            "startedAtUtc": record.timing.started_at_utc,
            "endedAtUtc": record.timing.ended_at_utc,
        },
    }


def issue(ledger: ActionLedger, prepared_envelope: ActionEnvelope) -> ActionLedger:
    if (
        sha256_bytes(canonical_json_bytes(prepared_envelope.value))
        != prepared_envelope.sha256
    ):
        raise ValueError("Envelope canonical hash 不匹配。")
    if prepared_envelope.sha256 in ledger.envelopes_by_sha256:
        return ledger
    for envelope in ledger.envelopes_by_sha256.values():
        if envelope.value["actionId"] == prepared_envelope.value["actionId"]:
            raise ValueError("retry 必须使用新的 actionId。")
    value = prepared_envelope.value
    contract, digest = action_contract_binding(
        SKILL_ROOT, str(value["actionContractId"])
    )
    if digest != value["actionContractSha256"]:
        raise ValueError("Envelope Action contract hash 无效。")
    revision, attempt = value["revision"], value["attempt"]
    if (
        type(revision) is not int
        or type(attempt) is not int
        or revision not in (1, 2)
        or attempt not in (1, 2)
        or (contract["executionKind"] == "HOST_BROWSER" and revision != 1)
    ):
        raise ValueError("Attempt 超出 execution/revision 上限。")
    prior = [
        item
        for item in ledger.envelopes_by_sha256.values()
        if item.value["logicalWorkId"] == value["logicalWorkId"]
    ]
    if not prior:
        if (revision, attempt) != (1, 1):
            raise ValueError("Logical Work 必须从 revision 1 attempt 1 开始。")
    else:
        previous = max(
            prior, key=lambda item: (item.value["revision"], item.value["attempt"])
        )
        if any(
            value.get(key) != previous.value.get(key)
            for key in (
                "runId",
                "groupId",
                "actionContractId",
                "actionContractSha256",
                "stageKind",
                "inputRevisionSha256",
                "baseCandidateSha256",
                "upstreamCheckpointSha256s",
            )
        ):
            raise ValueError("retry 不得改变 Logical Work 的冻结身份。")
        records = [
            record
            for record in ledger.attempt_records.values()
            if record.logical_work_id == value["logicalWorkId"]
        ]
        diagnostics = [
            sha256_bytes(
                canonical_json_bytes(attempt_record_value(record)["diagnostic"])
            )
            for record in records
            if record.diagnostic is not None
        ]
        if len(diagnostics) != len(set(diagnostics)):
            raise ValueError("重复 canonical diagnostic，停止 retry。")
        failure = next(
            (record for record in records if record.envelope_sha256 == previous.sha256),
            None,
        )
        if (
            revision == previous.value["revision"]
            and attempt == previous.value["attempt"] + 1
        ):
            if failure is not None and failure.failure_kind != "EXECUTION":
                raise ValueError("只有 EXECUTION 可增加同 revision attempt。")
        elif revision == previous.value["revision"] + 1 and attempt == 1:
            if (
                failure is None
                or failure.outcome != "FAILED"
                or failure.failure_kind not in ("INVALID_JSON", "INVALID_IR")
            ):
                raise ValueError("只有已封存 JSON/IR failure 可增加 revision。")
        else:
            raise ValueError("Attempt 必须按有效 retry 路由连续发放。")
    return replace(
        ledger,
        envelopes_by_sha256={
            **ledger.envelopes_by_sha256,
            prepared_envelope.sha256: prepared_envelope,
        },
    )


def is_group_ready(ledger: ActionLedger, required_logical_work_ids) -> bool:
    for logical_work_id in required_logical_work_ids:
        envelopes = [
            item
            for item in ledger.envelopes_by_sha256.values()
            if item.value["logicalWorkId"] == logical_work_id
        ]
        if not envelopes:
            return False
        active = max(
            envelopes, key=lambda item: (item.value["revision"], item.value["attempt"])
        )
        if not any(
            record.envelope_sha256 == active.sha256 and record.outcome == "SUCCEEDED"
            for record in ledger.attempt_records.values()
        ):
            return False
    return True


def finish(
    ledger: ActionLedger, envelope: ActionEnvelope, completion: AttemptCompletion,
    *, bound_result_validator: Callable[[bytes], None] | None = None,
) -> tuple[ActionLedger, AttemptRecord]:
    if ledger.envelopes_by_sha256.get(envelope.sha256) != envelope:
        raise ValueError("Attempt 必须绑定已签发的 Envelope。")
    kind, diagnostic = completion.failure_kind, completion.diagnostic
    if completion.raw_output is not None:
        if kind is not None or diagnostic is not None:
            raise ValueError("raw output 与 caller failure 互斥。")
    elif kind not in (
        "EXECUTION",
        "INPUT_REQUIRED",
        "CONTRACT_GAP",
        "OWNER_BUG",
        "SYSTEM",
    ) or not isinstance(diagnostic, AttemptDiagnostic):
        raise ValueError("失败 completion 必须有合法 failureKind 与 diagnostic。")
    if diagnostic is not None and (
        not isinstance(diagnostic.code, str)
        or not diagnostic.code
        or not isinstance(diagnostic.path, str)
        or not isinstance(diagnostic.subject_ids, tuple)
        or any(not isinstance(item, str) or not item for item in diagnostic.subject_ids)
    ):
        raise ValueError("AttemptDiagnostic 字段无效。")
    skill_root = SKILL_ROOT
    validate_action_usage(envelope.value, completion.usage, skill_root=skill_root)
    normalized = None
    if completion.raw_output is not None:
        try:
            normalized = normalize_action_result(
                envelope.value, completion.raw_output, skill_root=skill_root
            )
            if bound_result_validator is not None:
                bound_result_validator(normalized)
        except json.JSONDecodeError:
            kind, diagnostic = "INVALID_JSON", AttemptDiagnostic("INVALID_JSON", "", ())
        except InvalidActionResult as error:
            normalized = None
            kind, diagnostic = "INVALID_IR", error.diagnostic
        except UnicodeDecodeError:
            kind, diagnostic = "SYSTEM", AttemptDiagnostic("OUTPUT_NOT_UTF8", "", ())
        contract, _ = action_contract_binding(
            skill_root, envelope.value["actionContractId"]
        )
        if contract["executionKind"] == "HOST_BROWSER" and kind in (
            "INVALID_JSON",
            "INVALID_IR",
        ):
            kind, diagnostic = "SYSTEM", AttemptDiagnostic(
                "HOST_BROWSER_INVALID_TRACE", "", ()
            )
    # Any returned raw output proves execution started, even if parsing failed.
    validate_attempt_timing(
        completion.timing,
        failed=kind is not None and completion.raw_output is None,
    )
    validate_usage(
        completion.usage, provider_started=completion.timing.started_at_utc is not None
    )
    digest = sha256_bytes(normalized) if normalized is not None else None
    raw_digest = (
        sha256_bytes(completion.raw_output)
        if completion.raw_output is not None
        else None
    )
    record = AttemptRecord(
        str(envelope.value["logicalWorkId"]),
        int(envelope.value["revision"]),
        int(envelope.value["attempt"]),
        envelope.sha256,
        "SUCCEEDED" if kind is None else "FAILED",
        kind,
        diagnostic,
        raw_digest,
        digest,
        completion.usage,
        completion.timing,
    )
    for existing in ledger.attempt_records.values():
        if existing.envelope_sha256 == envelope.sha256:
            if existing.normalized_result_sha256 != digest or (
                digest is None and existing != replace(record, outcome=existing.outcome)
            ):
                raise ValueError("同一 Action 不允许不同结果。")
            return ledger, existing
    if any(
        item.value["logicalWorkId"] == record.logical_work_id
        and (item.value["revision"], item.value["attempt"])
        > (record.revision, record.attempt)
        for item in ledger.envelopes_by_sha256.values()
    ):
        record = replace(record, outcome="SUPERSEDED")
    record_sha256 = sha256_bytes(canonical_json_bytes(attempt_record_value(record)))
    return (
        replace(
            ledger,
            attempt_records={**ledger.attempt_records, record_sha256: record},
            raw_outputs={
                **ledger.raw_outputs,
                **(
                    {raw_digest: completion.raw_output}
                    if raw_digest is not None
                    else {}
                ),
            },
            normalized_results={
                **ledger.normalized_results,
                **({digest: normalized} if digest is not None else {}),
            },
        ),
        record,
    )


@lru_cache(maxsize=8)
def _record_validator(
    skill_root: Path, registry_content_hashes: tuple[tuple[str, str], ...]
) -> Draft202012Validator:
    return Draft202012Validator(
        {"$ref": "urn:ai-sow:generate:next:action:1#/$defs/attemptRecord"},
        registry=load_schema_registry(skill_root),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )


def attempt_record_from_value(value: Mapping[str, object]) -> AttemptRecord:
    # Only the compiled validator is cached; changed installed contracts get a new key.
    registry_content_hashes = tuple(
        (path.name, sha256_bytes(path.read_bytes()))
        for path in sorted((SKILL_ROOT / "contracts").glob("*.schema.json"))
    )
    validator = _record_validator(SKILL_ROOT, registry_content_hashes)
    if list(validator.iter_errors(value)):
        raise ValueError("AttemptRecord 合同无效。")
    usage, timing, diagnostic = value["usage"], value["timing"], value["diagnostic"]
    record = AttemptRecord(
        value["logicalWorkId"],
        value["revision"],
        value["attempt"],
        value["envelopeSha256"],
        value["outcome"],
        value["failureKind"],
        (
            None
            if diagnostic is None
            else AttemptDiagnostic(
                diagnostic["code"], diagnostic["path"], tuple(diagnostic["subjectIds"])
            )
        ),
        value["rawSha256"],
        value["normalizedResultSha256"],
        Usage(
            usage["provenance"],
            usage["inputTokens"],
            usage["outputTokens"],
            usage["cachedInputTokens"],
            usage["reasoningTokens"],
        ),
        AttemptTiming(timing["startedAtUtc"], timing["endedAtUtc"]),
    )
    validate_attempt_timing(
        record.timing,
        failed=record.failure_kind is not None and record.raw_sha256 is None,
    )
    validate_usage(
        record.usage, provider_started=record.timing.started_at_utc is not None
    )
    return record


def _record_envelope(record, envelopes_by_sha256):
    envelope = envelopes_by_sha256.get(record.envelope_sha256)
    if (
        envelope is None
        or envelope.sha256 != record.envelope_sha256
        or sha256_bytes(canonical_json_bytes(envelope.value)) != record.envelope_sha256
    ):
        raise ValueError("AttemptRecord 必须绑定可复算 canonical hash 的 Envelope。")
    if (
        envelope.value["logicalWorkId"],
        envelope.value["revision"],
        envelope.value["attempt"],
    ) != (record.logical_work_id, record.revision, record.attempt):
        raise ValueError("AttemptRecord 与 Envelope logical/revision/attempt 不一致。")
    contract, digest = action_contract_binding(
        SKILL_ROOT, envelope.value["actionContractId"]
    )
    if digest != envelope.value["actionContractSha256"]:
        raise ValueError("Envelope Action contract hash 无效。")
    return envelope, contract


def _repair_record(logical_work_id, digest, attempt_records, envelopes_by_sha256):
    record = attempt_records.get(digest)
    if (
        record is None
        or sha256_bytes(canonical_json_bytes(attempt_record_value(record))) != digest
    ):
        raise ValueError("repair AttemptRecord canonical hash 无效。")
    _, contract = _record_envelope(record, envelopes_by_sha256)
    if (
        contract["executionKind"] != "MODEL_PROVIDER"
        or record.logical_work_id != logical_work_id
        or record.revision != 1
        or record.outcome != "FAILED"
        or record.failure_kind not in ("INVALID_JSON", "INVALID_IR")
        or record.diagnostic is None
        or record.raw_sha256 is None
    ):
        raise ValueError(
            "只有同 Logical Work 前一 revision 的 MODEL_PROVIDER JSON/IR failure 可作为 repair context。"
        )
    return record


def build_attempt_repair_context(
    logical_work_id: str,
    failed_attempt_record_sha256: str,
    attempt_records: Mapping[str, AttemptRecord],
    raw_outputs: Mapping[str, bytes],
    *,
    envelopes_by_sha256: Mapping[str, ActionEnvelope],
) -> ContextRefDescriptor:
    record = _repair_record(
        logical_work_id,
        failed_attempt_record_sha256,
        attempt_records,
        envelopes_by_sha256,
    )
    raw = raw_outputs.get(record.raw_sha256)
    if raw is None or sha256_bytes(raw) != record.raw_sha256:
        raise ValueError("repair raw output hash 无效。")
    content = {
        "kind": "ATTEMPT_REPAIR",
        "attemptRecordSha256": failed_attempt_record_sha256,
        "rawOutputUtf8": raw.decode("utf-8"),
        "diagnostic": attempt_record_value(record)["diagnostic"],
    }
    return ContextRefDescriptor(
        "repair-from-attempt-" + failed_attempt_record_sha256,
        canonical_json_bytes(content),
    )


def validate_attempt_repair_context(
    context_ref: ContextRefDescriptor,
    logical_work_id: str,
    attempt_records: Mapping[str, AttemptRecord],
    *,
    envelopes_by_sha256: Mapping[str, ActionEnvelope],
) -> None:
    content = json.loads(context_ref.canonical_content)
    if (
        not isinstance(content, dict)
        or set(content)
        != {"kind", "attemptRecordSha256", "rawOutputUtf8", "diagnostic"}
        or content["kind"] != "ATTEMPT_REPAIR"
        or canonical_json_bytes(content) != context_ref.canonical_content
    ):
        raise ValueError("repair context 必须是精确 canonical content。")
    digest = content["attemptRecordSha256"]
    if (
        not isinstance(digest, str)
        or context_ref.ref_id != "repair-from-attempt-" + digest
    ):
        raise ValueError("repair refId 未绑定 AttemptRecord hash。")
    record = _repair_record(
        logical_work_id, digest, attempt_records, envelopes_by_sha256
    )
    if (
        not isinstance(content["rawOutputUtf8"], str)
        or sha256_bytes(content["rawOutputUtf8"].encode("utf-8")) != record.raw_sha256
        or content["diagnostic"] != attempt_record_value(record)["diagnostic"]
    ):
        raise ValueError("repair context 的 raw/diagnostic 与记录不一致。")
