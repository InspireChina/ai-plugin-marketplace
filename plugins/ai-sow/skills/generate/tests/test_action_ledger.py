from __future__ import annotations

TEST_LAYER = "unit"

import json
import sys
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))
sys.path.insert(0, str(SKILL_ROOT / "tests"))


def source_scan_result():
    return [{"coverageRootId": "block-prd-001", "disposition": "FACT", "facts": [
        {"localKey": "fact", "factKind": "REQUIREMENT", "statement": "订单可查询。",
         "evidenceIds": ["block-prd-001"], "qualifiers": []}]}]


def result_envelope():
    from contracts import action_contract_binding

    _, digest = action_contract_binding(SKILL_ROOT, "SOURCE_SCAN-v1")
    return {"actionContractId": "SOURCE_SCAN-v1", "actionContractSha256": digest}


def test_normalized_transport():
    from contracts import normalize_action_result, sha256_bytes

    result = source_scan_result()
    pretty = json.dumps(result, ensure_ascii=False, indent=2).encode()
    compact = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode()
    assert sha256_bytes(pretty) != sha256_bytes(compact)
    normalized = normalize_action_result(
        result_envelope(), pretty, skill_root=SKILL_ROOT
    )
    assert normalized == normalize_action_result(
        result_envelope(), compact, skill_root=SKILL_ROOT
    )
    assert json.loads(normalized) == result
    duplicate = compact.replace(b'"disposition":', b'"disposition":"FACT","disposition":')
    with pytest.raises(ValueError, match="duplicate"):
        normalize_action_result(result_envelope(), duplicate, skill_root=SKILL_ROOT)
    with pytest.raises(ValueError):
        normalize_action_result(
            result_envelope(), b'{"arbitrary":true}', skill_root=SKILL_ROOT
        )


def prepared_envelope():
    from contracts import canonical_json_bytes, sha256_bytes
    from models import ActionEnvelope
    from test_contracts import valid_action_envelope

    value = {**valid_action_envelope(), **result_envelope()}
    return ActionEnvelope(
        value,
        "actions/action-1/envelope.json",
        sha256_bytes(canonical_json_bytes(value)),
    )


def successful_completion(raw=None):
    from models import AttemptCompletion, AttemptTiming, Usage

    return AttemptCompletion(
        raw or json.dumps(source_scan_result()).encode(),
        None,
        None,
        Usage("PROVIDER_REPORTED", 10, 4, 3, 1),
        AttemptTiming("2026-09-05T00:00:00Z", "2026-09-05T00:00:01Z"),
    )


def test_bound_result_validator_receives_canonical_bytes():
    from action_ledger import ActionLedger, issue, finish
    from contracts import InvalidActionResult

    envelope = prepared_envelope()
    completion = successful_completion()

    def validate_source_binding(normalized_result: bytes) -> None:
        result = json.loads(normalized_result.decode("utf-8"))
        if result[0]["facts"][0]["evidenceIds"] != ["authorized-block"]:
            raise InvalidActionResult("未知来源绑定")

    ledger, record = finish(
        issue(ActionLedger(), envelope), envelope, completion,
        bound_result_validator=validate_source_binding,
    )
    assert record.outcome == "FAILED"
    assert record.failure_kind == "INVALID_IR"
    assert record.normalized_result_sha256 is None
    assert not ledger.normalized_results
    assert ledger.raw_outputs[record.raw_sha256] == completion.raw_output


def test_bound_invalid_ir_preserves_actionable_diagnostic_in_retry_context():
    from action_ledger import ActionLedger, issue, finish, build_attempt_repair_context
    from contracts import InvalidActionResult
    from models import AttemptDiagnostic
    envelope = prepared_envelope()
    expected = AttemptDiagnostic('SCOPE_RELATION_ENDPOINT_INVALID', '/decisions/0/relations/0', ('design-root',))
    def reject(raw):
        error = InvalidActionResult('设计只能关联 Feature。')
        error.diagnostic = expected
        raise error
    ledger, record = finish(issue(ActionLedger(), envelope), envelope, successful_completion(), bound_result_validator=reject)
    assert record.failure_kind == 'INVALID_IR'
    assert record.diagnostic == expected
    digest = next(iter(ledger.attempt_records))
    context = build_attempt_repair_context(record.logical_work_id, digest, ledger.attempt_records, ledger.raw_outputs, envelopes_by_sha256=ledger.envelopes_by_sha256)
    assert json.loads(context.canonical_content)['diagnostic'] == {'code': expected.code, 'path': expected.path, 'subjectIds': ['design-root']}


def test_successful_attempt_record():
    from dataclasses import FrozenInstanceError
    from action_ledger import ActionLedger, issue, finish, attempt_record_value
    from contracts import canonical_json_bytes, sha256_bytes

    empty = ActionLedger()
    envelope = prepared_envelope()
    before = canonical_json_bytes(envelope.value)
    issued = issue(empty, envelope)
    ledger, record = finish(issued, envelope, successful_completion())
    assert not empty.envelopes_by_sha256
    assert not issued.attempt_records
    assert len(ledger.attempt_records) == 1
    assert record.outcome == "SUCCEEDED"
    assert record.envelope_sha256 == envelope.sha256
    from contracts import load_schema_registry
    from jsonschema import Draft202012Validator

    Draft202012Validator(
        {"$ref": "urn:ai-sow:generate:next:action:1#/$defs/attemptRecord"},
        registry=load_schema_registry(SKILL_ROOT),
    ).validate(attempt_record_value(record))
    assert record.normalized_result_sha256 in ledger.normalized_results
    assert (
        json.loads(ledger.normalized_results[record.normalized_result_sha256])
        == source_scan_result()
    )
    assert sha256_bytes(ledger.raw_outputs[record.raw_sha256]) == record.raw_sha256
    assert canonical_json_bytes(envelope.value) == before
    with pytest.raises(FrozenInstanceError):
        record.outcome = "FAILED"
    repeated, same = finish(
        ledger,
        envelope,
        successful_completion(json.dumps(source_scan_result(), indent=2).encode()),
    )
    assert repeated == ledger
    assert same == record


@pytest.mark.parametrize("seam", ("finish", "restore"))
@pytest.mark.parametrize("raw_output", (b"{", b"{}", b"\xff"))
def test_received_raw_output_requires_started_timing(seam, raw_output):
    from dataclasses import replace
    from action_ledger import (
        ActionLedger,
        issue,
        finish,
        attempt_record_value,
        attempt_record_from_value,
    )
    from models import AttemptTiming, Usage

    envelope = prepared_envelope()
    ledger = issue(ActionLedger(), envelope)
    completion = successful_completion(raw_output)
    zero_usage = Usage("PROVIDER_REPORTED", 0, 0, 0, None)
    no_start = AttemptTiming(None, completion.timing.ended_at_utc)
    if seam == "finish":
        with pytest.raises(ValueError, match="startedAtUtc"):
            finish(
                ledger, envelope, replace(completion, usage=zero_usage, timing=no_start)
            )
    else:
        _, record = finish(ledger, envelope, replace(completion, usage=zero_usage))
        malformed = attempt_record_value(replace(record, timing=no_start))
        with pytest.raises(ValueError, match="startedAtUtc"):
            attempt_record_from_value(malformed)


@pytest.mark.parametrize(
    "kind",
    [
        "EXECUTION",
        "INVALID_JSON",
        "INVALID_IR",
        "INPUT_REQUIRED",
        "CONTRACT_GAP",
        "OWNER_BUG",
        "SYSTEM",
    ],
)
def test_attempt_failure_kinds(kind):
    from action_ledger import ActionLedger, issue, finish, attempt_record_value
    from contracts import canonical_json_bytes, load_schema_registry, sha256_bytes
    from jsonschema import Draft202012Validator, ValidationError
    from models import AttemptCompletion, AttemptDiagnostic

    envelope = prepared_envelope()
    ledger = issue(ActionLedger(), envelope)
    diagnostic = AttemptDiagnostic(kind, "/fixture", ("subject-1",))
    base = successful_completion()
    if kind in {"INVALID_JSON", "INVALID_IR"}:
        completion = AttemptCompletion(
            b"{" if kind == "INVALID_JSON" else b"{}",
            None,
            None,
            base.usage,
            base.timing,
        )
    else:
        completion = AttemptCompletion(None, kind, diagnostic, base.usage, base.timing)
    final, record = finish(ledger, envelope, completion)
    assert record.outcome == "FAILED"
    assert record.failure_kind == kind
    assert record.normalized_result_sha256 is None
    assert record.usage == base.usage and record.timing == base.timing
    assert record.diagnostic == (
        AttemptDiagnostic(kind, "", ())
        if kind in {"INVALID_JSON", "INVALID_IR"}
        else diagnostic
    )
    value = attempt_record_value(record)
    assert list(final.attempt_records) == [sha256_bytes(canonical_json_bytes(value))]
    validator = Draft202012Validator(
        {"$ref": "urn:ai-sow:generate:next:action:1#/$defs/attemptRecord"},
        registry=load_schema_registry(SKILL_ROOT),
    )
    validator.validate(value)
    for field in ("code", "path", "subjectIds"):
        malformed = json.loads(json.dumps(value))
        del malformed["diagnostic"][field]
        with pytest.raises(ValidationError):
            validator.validate(malformed)
    for field in ("failureCode", "fingerprint"):
        with pytest.raises(ValidationError):
            validator.validate({**value, field: "extra"})
    with pytest.raises(ValidationError):
        validator.validate(
            {**value, "diagnostic": {**value["diagnostic"], "extra": True}}
        )
    with pytest.raises(ValueError):
        finish(
            ledger,
            envelope,
            AttemptCompletion(
                None, "REPAIRABLE_SEMANTIC", diagnostic, base.usage, base.timing
            ),
        )
    with pytest.raises(ValueError):
        finish(
            ledger,
            envelope,
            AttemptCompletion(b"{}", kind, diagnostic, base.usage, base.timing),
        )
    with pytest.raises(ValueError):
        finish(
            ledger,
            envelope,
            AttemptCompletion(None, kind, None, base.usage, base.timing),
        )


def changed_envelope(envelope, **changes):
    from contracts import canonical_json_bytes, sha256_bytes
    from models import ActionEnvelope

    value = {**envelope.value, **changes}
    return ActionEnvelope(
        value, envelope.path, sha256_bytes(canonical_json_bytes(value))
    )


def test_retry_logical_identity():
    from action_ledger import ActionLedger, issue, finish, is_group_ready
    from models import AttemptCompletion, AttemptDiagnostic

    first = prepared_envelope()
    ledger = issue(ActionLedger(), first)
    base = successful_completion()
    ledger, _ = finish(
        ledger,
        first,
        AttemptCompletion(
            None,
            "EXECUTION",
            AttemptDiagnostic("TIMEOUT", "", ()),
            base.usage,
            base.timing,
        ),
    )
    logical = first.value["logicalWorkId"]
    assert not is_group_ready(ledger, [logical])
    with pytest.raises(ValueError):
        issue(ledger, changed_envelope(first, attempt=2))
    retry = changed_envelope(first, actionId="action-retry", attempt=2)
    ledger = issue(ledger, retry)
    ledger, record = finish(ledger, retry, base)
    assert retry.value["actionId"] != first.value["actionId"]
    assert record.logical_work_id == logical
    assert is_group_ready(ledger, [logical])
    assert not is_group_ready(ledger, [logical, "logical-missing"])


@pytest.mark.parametrize("late_failure", [False, True])
def test_late_attempt_superseded(late_failure):
    from action_ledger import (
        ActionLedger,
        issue,
        finish,
        is_group_ready,
        attempt_record_value,
    )
    from contracts import load_schema_registry
    from jsonschema import Draft202012Validator
    from models import AttemptCompletion, AttemptDiagnostic

    first = prepared_envelope()
    retry = changed_envelope(first, actionId="action-retry", attempt=2)
    ledger = issue(issue(ActionLedger(), first), retry)
    ledger, active = finish(ledger, retry, successful_completion())
    completion = successful_completion()
    if late_failure:
        completion = AttemptCompletion(
            None,
            "EXECUTION",
            AttemptDiagnostic("LATE_TIMEOUT", "", ()),
            completion.usage,
            completion.timing,
        )
    ledger, late = finish(ledger, first, completion)
    assert late.outcome == "SUPERSEDED"
    assert late.usage == completion.usage and late.timing == completion.timing
    assert active in ledger.attempt_records.values()
    assert len(ledger.attempt_records) == 2
    assert is_group_ready(ledger, [first.value["logicalWorkId"]])
    assert finish(ledger, first, completion) == (ledger, late)
    Draft202012Validator(
        {"$ref": "urn:ai-sow:generate:next:action:1#/$defs/attemptRecord"},
        registry=load_schema_registry(SKILL_ROOT),
    ).validate(attempt_record_value(late))
    different = AttemptCompletion(
        None,
        "SYSTEM",
        AttemptDiagnostic("DIFFERENT", "", ()),
        completion.usage,
        completion.timing,
    )
    with pytest.raises(ValueError):
        finish(ledger, first, different)


@pytest.mark.parametrize("group_id", ["group-planned", "control-group-singleton"])
@pytest.mark.parametrize("failure_kind", ["INVALID_JSON", "INVALID_IR"])
def test_bounded_retry_diagnostic_recovery(tmp_path, group_id, failure_kind):
    from dataclasses import replace
    from action_ledger import (
        ActionLedger,
        issue,
        finish,
        attempt_record_value,
        attempt_record_from_value,
        build_attempt_repair_context,
        validate_attempt_repair_context,
    )
    from contracts import canonical_json_bytes, sha256_bytes
    from models import AttemptCompletion, AttemptDiagnostic, ContextRefDescriptor

    first = changed_envelope(prepared_envelope(), groupId=group_id)
    with pytest.raises(ValueError):
        issue(ActionLedger(), changed_envelope(first, revision=2))
    ledger = issue(ActionLedger(), first)
    base = successful_completion()
    ledger, _ = finish(
        ledger,
        first,
        AttemptCompletion(
            None,
            "EXECUTION",
            AttemptDiagnostic("TIMEOUT", "", ()),
            base.usage,
            base.timing,
        ),
    )
    retry = changed_envelope(first, attempt=2, actionId="action-retry")
    ledger = issue(ledger, retry)
    raw = b"{" if failure_kind == "INVALID_JSON" else b"{}"
    ledger, failed = finish(
        ledger, retry, AttemptCompletion(raw, None, None, base.usage, base.timing)
    )
    digest = sha256_bytes(canonical_json_bytes(attempt_record_value(failed)))
    context = build_attempt_repair_context(
        failed.logical_work_id,
        digest,
        ledger.attempt_records,
        ledger.raw_outputs,
        envelopes_by_sha256=ledger.envelopes_by_sha256,
    )
    assert context.ref_id == "repair-from-attempt-" + digest
    assert json.loads(context.canonical_content) == {
        "kind": "ATTEMPT_REPAIR",
        "attemptRecordSha256": digest,
        "rawOutputUtf8": raw.decode(),
        "diagnostic": {"code": failure_kind, "path": "", "subjectIds": []},
    }
    validate_attempt_repair_context(
        context,
        failed.logical_work_id,
        ledger.attempt_records,
        envelopes_by_sha256=ledger.envelopes_by_sha256,
    )
    for field, replacement in [
        ("rawOutputUtf8", "tampered"),
        ("diagnostic", {"code": "OTHER", "path": "", "subjectIds": []}),
        ("attemptRecordSha256", "a" * 64),
    ]:
        content = {**json.loads(context.canonical_content), field: replacement}
        with pytest.raises(ValueError):
            validate_attempt_repair_context(
                ContextRefDescriptor(context.ref_id, canonical_json_bytes(content)),
                failed.logical_work_id,
                ledger.attempt_records,
                envelopes_by_sha256=ledger.envelopes_by_sha256,
            )
    with pytest.raises(ValueError):
        validate_attempt_repair_context(
            context,
            "logical-other",
            ledger.attempt_records,
            envelopes_by_sha256=ledger.envelopes_by_sha256,
        )
    with pytest.raises(ValueError):
        build_attempt_repair_context(
            failed.logical_work_id,
            digest,
            {
                **ledger.attempt_records,
                digest: replace(
                    failed, diagnostic=AttemptDiagnostic("TAMPERED", "", ())
                ),
            },
            ledger.raw_outputs,
            envelopes_by_sha256=ledger.envelopes_by_sha256,
        )
    with pytest.raises(ValueError):
        build_attempt_repair_context(
            failed.logical_work_id,
            digest,
            ledger.attempt_records,
            {failed.raw_sha256: b"changed"},
            envelopes_by_sha256=ledger.envelopes_by_sha256,
        )
    with pytest.raises(ValueError):
        build_attempt_repair_context(
            failed.logical_work_id,
            digest,
            ledger.attempt_records,
            ledger.raw_outputs,
            envelopes_by_sha256={
                retry.sha256: changed_envelope(retry, logicalWorkId="logical-tampered")
            },
        )
    with pytest.raises(ValueError):
        finish(
            issue(ActionLedger(), first),
            first,
            AttemptCompletion(
                None,
                failure_kind,
                AttemptDiagnostic(failure_kind, "", ()),
                base.usage,
                base.timing,
            ),
        )
    revision2 = changed_envelope(
        first, revision=2, attempt=1, actionId="action-revision2"
    )
    ledger = issue(ledger, revision2)
    ledger, repeated = finish(
        ledger, revision2, AttemptCompletion(raw, None, None, base.usage, base.timing)
    )
    # Rebuild through real serialized records, then repeated canonical diagnostics stop issuance.
    restored_records = {}
    for record_hash, record in ledger.attempt_records.items():
        path = tmp_path / (record_hash + ".json")
        path.write_bytes(canonical_json_bytes(attempt_record_value(record)))
        restored_records[record_hash] = attempt_record_from_value(
            json.loads(path.read_bytes())
        )
    restored = ActionLedger(
        ledger.envelopes_by_sha256,
        restored_records,
        ledger.raw_outputs,
        ledger.normalized_results,
    )
    assert restored == ledger
    with pytest.raises(ValueError):
        issue(
            restored, changed_envelope(revision2, attempt=2, actionId="action-repeat")
        )
    with pytest.raises(ValueError):
        issue(
            restored, changed_envelope(revision2, revision=3, actionId="action-third")
        )
    with pytest.raises(ValueError):
        issue(
            restored,
            changed_envelope(revision2, attempt=3, actionId="action-third-attempt"),
        )
    with pytest.raises(ValueError):
        ActionLedger(
            ledger.envelopes_by_sha256,
            {"a" * 64: repeated},
            ledger.raw_outputs,
            ledger.normalized_results,
        )


@pytest.mark.parametrize("execution_kind", ["MODEL_PROVIDER", "HOST_BROWSER"])
def test_bounded_retry_diagnostic_recovery_execution_kind(
    tmp_path, monkeypatch, execution_kind
):
    import shutil
    import action_ledger
    from action_ledger import (
        ActionLedger,
        issue,
        finish,
        attempt_record_value,
        build_attempt_repair_context,
    )
    from contracts import action_contract_binding, canonical_json_bytes, sha256_bytes
    from models import AttemptCompletion, AttemptDiagnostic, Usage

    root = tmp_path / "skill"
    shutil.copytree(SKILL_ROOT / "contracts", root / "contracts")
    shutil.copytree(SKILL_ROOT / "prompts", root / "prompts")
    registry_path = root / "contracts/action-contracts-v1.json"
    registry = json.loads(registry_path.read_bytes())
    registry["contracts"][0]["executionKind"] = execution_kind
    registry_path.write_bytes(canonical_json_bytes(registry))
    monkeypatch.setattr(action_ledger, "SKILL_ROOT", root)
    _, digest = action_contract_binding(root, "SOURCE_SCAN-v1")
    envelope = changed_envelope(prepared_envelope(), actionContractSha256=digest)
    base = successful_completion()
    usage = (
        Usage("PROVIDER_REPORTED", 0, 0, 0, None)
        if execution_kind == "HOST_BROWSER"
        else base.usage
    )
    ledger = issue(ActionLedger(), envelope)
    ledger, _ = finish(
        ledger,
        envelope,
        AttemptCompletion(
            None,
            "EXECUTION",
            AttemptDiagnostic("TIMEOUT_ONE", "", ()),
            usage,
            base.timing,
        ),
    )
    retry = changed_envelope(envelope, attempt=2, actionId="action-two")
    ledger = issue(ledger, retry)
    ledger, failure = finish(
        ledger, retry, AttemptCompletion(b"{}", None, None, usage, base.timing)
    )
    digest = sha256_bytes(canonical_json_bytes(attempt_record_value(failure)))
    if execution_kind == "HOST_BROWSER":
        assert failure.failure_kind == "SYSTEM"
        assert failure.usage.charged_tokens == 0
        with pytest.raises(ValueError):
            build_attempt_repair_context(
                failure.logical_work_id,
                digest,
                ledger.attempt_records,
                ledger.raw_outputs,
                envelopes_by_sha256=ledger.envelopes_by_sha256,
            )
        with pytest.raises(ValueError):
            issue(
                ledger, changed_envelope(envelope, revision=2, actionId="action-three")
            )
    else:
        revision2 = changed_envelope(
            envelope, revision=2, attempt=1, actionId="action-three"
        )
        ledger = issue(ledger, revision2)
        ledger, _ = finish(
            ledger,
            revision2,
            AttemptCompletion(
                None,
                "EXECUTION",
                AttemptDiagnostic("TIMEOUT_TWO", "", ()),
                usage,
                base.timing,
            ),
        )
        final = changed_envelope(revision2, attempt=2, actionId="action-four")
        ledger = issue(ledger, final)
        ledger, _ = finish(ledger, final, base)
        assert len(ledger.attempt_records) == 4
        with pytest.raises(ValueError):
            issue(ledger, changed_envelope(final, attempt=3, actionId="action-five"))
    non_utf = changed_envelope(
        envelope, logicalWorkId="logical-other", actionId="action-non-utf"
    )
    ledger = issue(ledger, non_utf)
    _, failed = finish(
        ledger, non_utf, AttemptCompletion(b"\xff", None, None, usage, base.timing)
    )
    assert failed.failure_kind == "SYSTEM"


@pytest.mark.integration
def test_successful_attempt_record_public_completion_cutover(tmp_path):
    from dataclasses import replace
    import orchestrator
    from test_orchestrator import write_run_store_request, write_budget_policy
    from stage_driver import stage_result
    from contracts import canonical_json_bytes, sha256_bytes, normalize_action_result

    envelope = orchestrator.run_mode(tmp_path, 'start', request=write_run_store_request(tmp_path),
        budget_policy=write_budget_policy(tmp_path))['nextAction']
    before = (tmp_path/Path(envelope['resultPath']).with_name('envelope.json')).read_bytes()
    output = stage_result(envelope['actionContractId'][:-3], json.loads((tmp_path/envelope['packetPath']).read_bytes()))
    completion = replace(
        successful_completion(), raw_output=canonical_json_bytes(output)
    )
    result = orchestrator.submit(tmp_path, envelope["actionId"], completion)
    assert result["outcome"] == "RECORDED", result
    record = result["record"]
    assert record["outcome"] == "SUCCEEDED"
    assert record["envelopeSha256"] == sha256_bytes(before)
    action_root = tmp_path / Path(envelope["resultPath"]).parent
    assert not (action_root / "issued.json").exists()
    assert not (action_root / "progress.json").exists()
    assert json.loads((action_root / "record.json").read_bytes()) == record
    assert (
        json.loads((action_root / "normalized-result.json").read_bytes())
        == json.loads(normalize_action_result(envelope, canonical_json_bytes(output), skill_root=SKILL_ROOT))
    )
    assert (action_root / "envelope.json").read_bytes() == before
    assert (
        orchestrator.submit(tmp_path, envelope["actionId"], completion)["record"]
        == record
    )
    assert orchestrator.status(tmp_path)["state"]["expectedActionIds"] == []
