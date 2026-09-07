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
    candidate_resolutions: Mapping[str, bytes] = field(default_factory=dict)
    resolved_candidates: Mapping[str, bytes] = field(default_factory=dict)
    repair_heads: Mapping[str, tuple] = field(default_factory=dict)
    candidate_repair_bases: Mapping[str, bytes] = field(default_factory=dict)
    candidate_repair_semantic_sources: Mapping[str, bytes] = field(default_factory=dict)

    def __post_init__(self):
        for name in (
            "envelopes_by_sha256",
            "attempt_records",
            "raw_outputs",
            "normalized_results", "candidate_resolutions", "resolved_candidates", "repair_heads",
            "candidate_repair_bases", "candidate_repair_semantic_sources",
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


def diagnostic_value(diagnostic: AttemptDiagnostic) -> dict[str, object]:
    value = {'code':diagnostic.code,'path':diagnostic.path,'subjectIds':list(diagnostic.subject_ids)}
    if diagnostic.findings:
        value['findings'] = [diagnostic_value(item) for item in diagnostic.findings]
    return value


def diagnostic_from_value(value: Mapping[str, object]) -> AttemptDiagnostic:
    if (not isinstance(value, Mapping)
            or set(value) not in ({'code','path','subjectIds'}, {'code','path','subjectIds','findings'})
            or not isinstance(value['code'], str) or not value['code']
            or not isinstance(value['path'], str) or not isinstance(value['subjectIds'], list)
            or any(not isinstance(key, str) or not key for key in value['subjectIds'])
            or ('findings' in value and (not isinstance(value['findings'], list) or not value['findings']))):
        raise ValueError('AttemptDiagnostic 字段无效。')
    return AttemptDiagnostic(value['code'], value['path'], tuple(value['subjectIds']),
        tuple(diagnostic_from_value(item) for item in value.get('findings', ())))


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
            else diagnostic_value(diagnostic)
        ),
        "rawSha256": record.raw_sha256,
        "normalizedResultSha256": record.normalized_result_sha256,
        "usage": usage_value(record.usage),
        "timing": {
            "startedAtUtc": record.timing.started_at_utc,
            "endedAtUtc": record.timing.ended_at_utc,
        },
    }


class AttemptLimitReached(ValueError):
    """A finite retry allowance is exhausted; preserve work for an explicit increase."""


def issue(ledger: ActionLedger, prepared_envelope: ActionEnvelope, *,
          max_revisions: int = 2, max_attempts: int = 2) -> ActionLedger:
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
        or not 1 <= revision <= max_revisions
        or not 1 <= attempt <= max_attempts
        or (contract["executionKind"] == "HOST_BROWSER" and revision != 1)
    ):
        raise AttemptLimitReached("Attempt 超出 execution/revision 上限。")
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
        if max_revisions == 2 and max_attempts == 2 and len(diagnostics) != len(set(diagnostics)):
            raise AttemptLimitReached("重复 canonical diagnostic，停止 retry。")
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
    return all(effective_result_bytes(ledger, key) is not None for key in required_logical_work_ids)


def finish(
    ledger: ActionLedger, envelope: ActionEnvelope, completion: AttemptCompletion,
    *, bound_result_validator: Callable[[bytes], None] | None = None,
    packet_payload: bytes | None = None,
    bound_result_normalizer: Callable[[bytes], bytes] | None = None,
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
                envelope.value, completion.raw_output, skill_root=skill_root, packet_payload=packet_payload
            )
            if envelope.value['actionContractId'] == 'CANDIDATE_PATCH-v1':
                if bound_result_normalizer is None:
                    raise InvalidActionResult('Patch 必须由绑定的 Owner 合并器生成 receipt。')
                normalized = bound_result_normalizer(normalized)
            elif bound_result_normalizer is not None:
                raise ValueError('只有 Patch 合同允许派生 normalized receipt。')
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
            else diagnostic_from_value(diagnostic)
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
        or record.revision < 1
        or record.outcome != "FAILED"
        or record.failure_kind not in ("INVALID_JSON", "INVALID_IR")
        or record.diagnostic is None
        or record.raw_sha256 is None
    ):
        raise ValueError(
            "只有同 Logical Work 前一 revision 的 MODEL_PROVIDER JSON/IR failure 可作为 repair context。"
        )
    return record


def _preservation_base_record(record, attempt_records):
    def rank(item):
        if item.failure_kind != 'INVALID_IR' or item.diagnostic is None: return 0
        if item.diagnostic.code not in {'INVALID_IR', 'REPAIR_SCOPE_VIOLATION'}: return 2
        return int(item.diagnostic.code == 'INVALID_IR' and any(
            finding.code in {'ACTION_RESULT_SCHEMA_INVALID', 'ACTION_RESULT_LOCAL_KEY_DUPLICATE'}
            for finding in item.diagnostic.findings))
    if rank(record) == 2: return None
    eligible = [(key, item) for key, item in attempt_records.items()
        if item.logical_work_id == record.logical_work_id and item.revision < record.revision and rank(item)]
    located = [pair for pair in eligible if rank(pair[1]) == 2]
    if located: return max(located, key=lambda pair: (pair[1].revision, pair[1].attempt))
    # A later malformed candidate cannot invalidate an earlier valid sibling.
    return min(eligible, key=lambda pair: (pair[1].revision, pair[1].attempt)) if eligible else None


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
    base = _preservation_base_record(record, attempt_records)
    if base is not None:
        base_hash, base_record = base
        base_raw = raw_outputs[base_record.raw_sha256]
        if sha256_bytes(base_raw) != base_record.raw_sha256: raise ValueError('保留候选 hash 漂移。')
        content['preservationBase'] = {'attemptRecordSha256': base_hash,
            'rawOutputUtf8': base_raw.decode('utf-8'), 'diagnostic': attempt_record_value(base_record)['diagnostic']}
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
        or set(content) not in (
            {"kind", "attemptRecordSha256", "rawOutputUtf8", "diagnostic"},
            {"kind", "attemptRecordSha256", "rawOutputUtf8", "diagnostic", "preservationBase"})
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
    expected_base = _preservation_base_record(record, attempt_records)
    base = content.get('preservationBase')
    if expected_base is not None:
        base_hash, base_record = expected_base
        if (not isinstance(base, dict) or set(base) != {'attemptRecordSha256','rawOutputUtf8','diagnostic'}
                or base['attemptRecordSha256'] != base_hash
                or not isinstance(base['rawOutputUtf8'], str)
                or sha256_bytes(base['rawOutputUtf8'].encode('utf-8')) != base_record.raw_sha256
                or base['diagnostic'] != attempt_record_value(base_record)['diagnostic']):
            raise ValueError('修复不得把越界候选当作新的正确基线。')
    elif base is not None:
        raise ValueError('当前失败不允许另选保留基线。')



def resolved_result(ledger, logical_work_id: str, *, verify_resolution: Callable[[bytes], bytes]) -> bytes | None:
    resolution = ledger.candidate_resolutions.get(logical_work_id)
    if resolution is not None:
        raw = verify_resolution(resolution)
        value = json.loads(resolution)
        if value['origin']['originLogicalWorkId'] != logical_work_id or value['ownerIrSha256'] != sha256_bytes(raw):
            raise ValueError('Resolution 身份或完整 IR hash 漂移。')
        return raw
    envelopes = [e for e in ledger.envelopes_by_sha256.values() if e.value['logicalWorkId'] == logical_work_id]
    if not envelopes: return None
    latest_rank = max((e.value['revision'], e.value['attempt']) for e in envelopes)
    effective = [
        e for e in envelopes
        if (e.value['revision'], e.value['attempt']) == latest_rank
    ]
    if len(effective) != 1:
        raise ValueError('依赖effective Attempt必须唯一。')
    latest = effective[0]
    records = [r for r in ledger.attempt_records.values() if r.envelope_sha256 == latest.sha256 and r.outcome == 'SUCCEEDED']
    if len(records) > 1:
        raise ValueError('依赖必须有唯一effective SUCCEEDED Attempt。')
    if records:
        if latest.value['actionContractId'] == 'CANDIDATE_PATCH-v1': return None
        return ledger.normalized_results[records[0].normalized_result_sha256]
    return None


def effective_result_bytes(ledger, logical_work_id):
    # These maps are constructed only by replay_candidate_ledger at I/O boundaries.
    return resolved_result(ledger,logical_work_id,
        verify_resolution=lambda proof:ledger.resolved_candidates[sha256_bytes(proof)])


@dataclass(frozen=True)
class CandidateResult:
    """Derived IR reference. This is deliberately not an AttemptRecord."""
    normalized_result_sha256: str
    resolution_sha256: str
    source_attempt_record_sha256: str


def effective_result(ledger, logical_work_id):
    raw=effective_result_bytes(ledger,logical_work_id)
    if raw is None:raise ValueError('逻辑工作尚无完整有效结果。')
    resolution=ledger.candidate_resolutions.get(logical_work_id)
    if resolution is not None:
        proof=json.loads(resolution)
        return sha256_bytes(resolution), CandidateResult(sha256_bytes(raw),sha256_bytes(resolution),proof['origin']['sourceAttemptRecordSha256'])
    records=[(digest,record) for digest,record in ledger.attempt_records.items() if record.logical_work_id==logical_work_id and record.outcome=='SUCCEEDED']
    return max(records,key=lambda item:(item[1].revision,item[1].attempt))


def dependency_context(ledger,logical_work_id):
    digest,result=effective_result(ledger,logical_work_id)
    value={'kind':'DEPENDENCY_RESULT','logicalWorkId':logical_work_id,'normalizedResult':json.loads(effective_result_bytes(ledger,logical_work_id))}
    if isinstance(result,CandidateResult):
        value.update(candidateResolutionSha256=digest,sourceAttemptRecordSha256=result.source_attempt_record_sha256)
    else:value['attemptRecordSha256']=digest
    return {'refId':'dependency-result-'+logical_work_id,'canonicalContent':value}


def source_record_for_result(ledger, digest):
    if digest in ledger.attempt_records:return ledger.attempt_records[digest]
    matches=[json.loads(raw) for raw in ledger.candidate_resolutions.values() if sha256_bytes(raw)==digest]
    if len(matches)!=1:raise ValueError('有效结果缺少原始物理来源。')
    return ledger.attempt_records[matches[0]['origin']['sourceAttemptRecordSha256']]


def verify_result_reference(ledger, reference):
    if 'candidateResolutionSha256' in reference:
        declared={value for value in (reference.get('sourceAttemptRecordSha256'),
                  reference.get('attemptRecordSha256')) if value is not None}
        if len(declared)!=1:
            raise ValueError('派生结果必须唯一绑定物理来源 Attempt。')
        source_digest=next(iter(declared))
        record=ledger.attempt_records.get(source_digest)
    else:
        if 'sourceAttemptRecordSha256' in reference:
            raise ValueError('物理结果不能声明派生来源。')
        source_digest=reference.get('attemptRecordSha256')
        record=ledger.attempt_records.get(source_digest)
    if record is None:
        raise ValueError('有效结果引用缺少物理来源。')
    digest,result=effective_result(ledger,record.logical_work_id)
    if result.normalized_result_sha256!=reference['normalizedResultSha256']:
        raise ValueError('有效结果引用 hash 漂移。')
    if isinstance(result,CandidateResult):
        if reference.get('candidateResolutionSha256')!=digest or source_digest!=result.source_attempt_record_sha256:
            raise ValueError('派生结果缺少明确 Resolution/原始记录绑定。')
    elif 'candidateResolutionSha256' in reference or digest!=source_digest:
        raise ValueError('物理成功引用不能伪装成派生结果。')
    return record,effective_result_bytes(ledger,record.logical_work_id)
