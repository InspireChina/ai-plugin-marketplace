from __future__ import annotations

TEST_LAYER = "unit"

import ast
import copy
import json
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError
from referencing import Registry, Resource


SKILL_ROOT = Path(__file__).parents[1]
CONTRACTS = SKILL_ROOT / "contracts"
sys.path.insert(0, str(SKILL_ROOT / "tests"))
FIXTURES = SKILL_ROOT / "fixtures"
SCRIPTS = SKILL_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from contracts import (  # noqa: E402
    canonical_json_bytes,
    classify_diagnostic,
    load_registry,
    load_schema_registry,
    sha256_bytes,
    validate_action_binding,
    validate_contract,
    validate_state_combination,
)
from models import (  # noqa: E402
    ActionEnvelope,
    AttemptRecord,
    CatalogHydration,
    CompilerProgress,
    CompilerResult,
    Diagnostic,
    InputRevisionResult,
    ReplacementOutcome,
    ReviewProgress,
    RunState,
    SourceDocument,
    TaskStandardCatalog,
)
from questions import (  # noqa: E402
    question_answer_anchors,
    question_sha256,
    validate_question_answers,
    validate_typed_gap_question,
)


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


NEXT_CONTRACTS = CONTRACTS
NEXT_SCHEMA_IDS = {
    "artifact-repair-authorization.schema.json": "urn:ai-sow:generate:next:artifact-repair-authorization:1",
    "owner-clarification.schema.json": "urn:ai-sow:generate:next:owner-clarification:1",
    "owner-repair-authorization.schema.json": "urn:ai-sow:generate:next:owner-repair-authorization:1",
    "candidate-repair.schema.json": "urn:ai-sow:generate:next:candidate-repair:1",
    "visual-review.schema.json": "urn:ai-sow:generate:visual-review:1",
    "task-decision.schema.json": "urn:ai-sow:generate:next:task-decision:1",
    "story-ac-decision.schema.json": "urn:ai-sow:generate:next:story-ac-decision:1",
    "fact-decision.schema.json": "urn:ai-sow:generate:next:fact-decision:1",
    "source-audit.schema.json": "urn:ai-sow:generate:next:source-audit:1",
    "scope-decision.schema.json": "urn:ai-sow:generate:next:scope-decision:1",
    "change-graph.schema.json": "urn:ai-sow:generate:next:change-graph:1",
    "prior-state-snapshot.schema.json": "urn:ai-sow:generate:next:prior-state-snapshot:1",
    "prior-state-decision.schema.json": "urn:ai-sow:generate:next:prior-state-decision:1",
    "prior-state-decision-v2.schema.json": "urn:ai-sow:generate:next:prior-state-decision:2",
    "prototype-scenario.schema.json": "urn:ai-sow:generate:next:prototype-scenario:1",
    "prototype-trace.schema.json": "urn:ai-sow:generate:next:prototype-trace:1",
    "prototype-observation.schema.json": "urn:ai-sow:generate:next:prototype-observation:1",
    "run-budget-policy.schema.json": "urn:ai-sow:generate:next:run-budget-policy:1",
    "run-event.schema.json": "urn:ai-sow:generate:next:run-event:1",
    "common.schema.json": "urn:ai-sow:generate:next:common:1",
    "request.schema.json": "urn:ai-sow:generate:next:request:1",
    "input-revision.schema.json": "urn:ai-sow:generate:next:input-revision:1",
    "sow-model.schema.json": "urn:ai-sow:generate:next:sow-model:1",
    "run-state.schema.json": "urn:ai-sow:generate:next:run-state:1",
    "action.schema.json": "urn:ai-sow:generate:next:action:1",
    "stage-checkpoint.schema.json": "urn:ai-sow:generate:next:stage-checkpoint:1",
    "review-repair.schema.json": "urn:ai-sow:generate:next:review-repair:1",
    "artifact-approval.schema.json": "urn:ai-sow:generate:next:artifact-approval:1",
    "generation-manifest.schema.json": "urn:ai-sow:generate:next:generation-manifest:1",
    "current.schema.json": "urn:ai-sow:generate:next:current:1",
}
HEX_A = "a" * 64
HEX_B = "b" * 64
HEX_C = "c" * 64



def artifact_manifest_sample():
    from office_engine import OFFICE_ARGUMENTS
    return {'contract':'ai-sow-artifact-manifest-v2','runId':'run-0001',
        **{key:HEX_A for key in ('candidateSha256','sourceManifestSha256','reviewDecisionSha256','templateSha256',
            'effectivePolicyDecisionSha256','taskCatalogSemanticSha256','rendererSha256','structureFormulaSha256')},
        'stageCheckpointSha256s':[HEX_A,HEX_B,HEX_C],'rendererContract':'generation-renderer-v12',
        **{key:{'path':name,'sha256':HEX_A} for key,name in [('workbook','sow.xlsx'),('notes','sow-notes.md'),
            ('proofBundle','proof-bundle.json'),('verification','verification.json')]},
        'workbookVerification':{'trustState':'VERIFIED','engineName':'LibreOffice','engineVersion':'LibreOffice fixture'},
        'office':{'executableBasename':'soffice','binarySha256':HEX_A,'version':'LibreOffice fixture','platform':'Linux',
            'normalizedArguments':OFFICE_ARGUMENTS[:],'exitCode':0},
        'priorStateSha256':None,'visibleSheets':['sheet-a'],
        'renders':[{'sheetKey':'sheet-a','path':'renders/sheet-001.pdf','sha256':HEX_A}],
        'visualReview':{'attemptRecordSha256':HEX_A}}


def test_schema_definition_reuse_keeps_fresh_data_and_registry_isolation(tmp_path, monkeypatch):
    """Skipping fresh definitions or reusing mutable resources breaks this boundary."""
    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema",
              "$id": "urn:test:content-reuse", "type": "string"}
    path = tmp_path / "one.schema.json"
    path.write_text(json.dumps(schema))
    checked = []
    original = Draft202012Validator.check_schema
    def measure(value, *args, **kwargs):
        checked.append(copy.deepcopy(value))
        return original(value, *args, **kwargs)
    monkeypatch.setattr(Draft202012Validator, "check_schema", measure)
    first = load_registry(tmp_path)
    second = load_registry(tmp_path)
    assert len(checked) == 1
    first.get(schema["$id"]).contents["type"] = "integer"
    assert second.get(schema["$id"]).contents["type"] == "string"
    validator = Draft202012Validator({"$ref": schema["$id"]}, registry=load_registry(tmp_path))
    validator.validate("合法")
    with pytest.raises(ValidationError):
        validator.validate(42)


@pytest.mark.parametrize("mutation", ["same_metadata", "add", "delete", "other_root", "invalid_json", "invalid_schema", "duplicate_id", "missing_id"])
def test_schema_definition_reuse_observes_actual_contents(tmp_path, mutation):
    import os
    from jsonschema.exceptions import SchemaError
    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema",
              "$id": "urn:test:definition-invalidation", "type": "string"}
    path = tmp_path / "one.schema.json"
    path.write_text(json.dumps(schema))
    initial = load_registry(tmp_path)
    metadata = path.stat()
    root = tmp_path
    if mutation == "same_metadata":
        path.write_text(json.dumps({**schema, "type": "number"}))
        assert path.stat().st_size == metadata.st_size
        os.utime(path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
    elif mutation == "other_root":
        root = tmp_path / "other"
        root.mkdir()
        (root / path.name).write_text(json.dumps({**schema, "type": "number"}))
    elif mutation == "add":
        (root / "two.schema.json").write_text(json.dumps({**schema, "$id": "urn:test:added"}))
    elif mutation == "delete":
        path.unlink()
    elif mutation == "invalid_json":
        path.write_text("{")
    elif mutation == "invalid_schema":
        path.write_text(json.dumps({**schema, "type": "bogus"}))
    elif mutation == "duplicate_id":
        (root / "two.schema.json").write_text(json.dumps(schema))
    else:
        del schema["$id"]
        path.write_text(json.dumps(schema))
    if mutation in {"invalid_json", "invalid_schema", "duplicate_id", "missing_id"}:
        for _ in range(2):
            with pytest.raises((ValueError, SchemaError)):
                load_registry(root)
        return
    latest = load_registry(root)
    assert initial.get("urn:test:definition-invalidation").contents["type"] == "string"
    if mutation == "delete":
        assert latest.get("urn:test:definition-invalidation") is None
    elif mutation == "add":
        assert latest.get("urn:test:added") is not None
    else:
        validator = Draft202012Validator({"$ref": schema["$id"]}, registry=latest)
        validator.validate(42)
        with pytest.raises(ValidationError):
            validator.validate("旧类型")


@pytest.mark.parametrize("kind,prompt", [("PRIOR_ANALYZE", "prior-analyze.md"), ("PRIOR_CONSOLIDATE", "prior-consolidate.md")])
def test_prior_action_contracts_bind_exact_prompt_and_shared_ir(kind, prompt):
    from contracts import action_contract_binding, normalize_action_result
    contract, digest = action_contract_binding(SKILL_ROOT, kind + "-v1")
    assert contract["instruction"] == {
        "path": "prompts/" + prompt,
        "sha256": sha256_bytes((SKILL_ROOT / "prompts" / prompt).read_bytes()),
    }
    assert contract["resultSchema"] == {
        "id": "urn:ai-sow:generate:next:prior-state-decision:1#/$defs/priorStateDecision",
        "path": "contracts/prior-state-decision.schema.json",
        "sha256": sha256_bytes((CONTRACTS / "prior-state-decision.schema.json").read_bytes()),
    }
    value = {"entities": [], "sourceRelations": [], "entitySupersessions": [], "unsupportedRegions": []}
    assert normalize_action_result({"actionContractId": kind + "-v1", "actionContractSha256": digest}, canonical_json_bytes(value), skill_root=SKILL_ROOT) == canonical_json_bytes(value)


@pytest.mark.parametrize("kind", ["PRIOR_ANALYZE", "PRIOR_CONSOLIDATE"])
def test_prior_action_contracts_normalize_only_declared_sets(kind):
    from contracts import action_contract_binding, normalize_action_result
    _, digest = action_contract_binding(SKILL_ROOT, kind + "-v1")
    envelope = {"actionContractId": kind + "-v1", "actionContractSha256": digest}
    entity = {"localKey": "item:a", "sourceId": "source-a", "entityKind": "CONTRACT_ENTITY", "semanticSummary": "保持 e\u0301 原文", "deliveryStatus": "CURRENT_BY_CONTRACT", "evidenceIds": ["e-b", "e-a"]}
    value = {"entities": [entity, {**entity, "localKey": "item:b"}], "sourceRelations": [{"sourceAId": "source-a", "sourceBId": "source-b", "relation": "UNRELATED", "evidenceIds": ["e-b", "e-a"]}], "entitySupersessions": [{"predecessorLocalKeys": ["item:b", "item:a"], "successorLocalKeys": ["item:d", "item:c"], "evidenceIds": ["e-b", "e-a"]}], "unsupportedRegions": [{"sourceId": "source-b", "regionId": "region-b", "reason": "乙"}, {"sourceId": "source-a", "regionId": "region-a", "reason": "甲"}]}
    permuted = copy.deepcopy(value)
    for key in permuted:
        permuted[key].reverse()
        for item in permuted[key]:
            for member in ("evidenceIds", "predecessorLocalKeys", "successorLocalKeys"):
                if member in item:
                    item[member].reverse()
    assert sha256_bytes(canonical_json_bytes(value)) != sha256_bytes(canonical_json_bytes(permuted))
    normalized = normalize_action_result(envelope, canonical_json_bytes(value), skill_root=SKILL_ROOT)
    assert normalized == normalize_action_result(envelope, canonical_json_bytes(permuted), skill_root=SKILL_ROOT)
    assert json.loads(normalized)["entities"][0]["semanticSummary"] == entity["semanticSummary"]


def valid_run_budget_policy() -> dict[str, object]:
    return {
        "contractVersion": "ai-sow-run-budget-policy-v1",
        "modelProfileId": "host-canonical-messages-v1",
        "modelContextLimitTokens": 128000,
        "estimatorVersion": "utf8-bytes-v1",
        "maxPlannedTokens": 1000000,
        "maxActiveSeconds": 3600,
        "outputReserveTokens": 8192,
        "hydrateReserveTokens": 4096,
        "safetyMarginTokens": 1024,
        "referenceOverheadTokens": 256,
        "maxConcurrency": 8,
        "demoLimits": {
            "maxDiscoveryRounds": 2,
            "maxScenarioSteps": 30,
            "maxScreenshots": 12,
        },
    }


@pytest.mark.parametrize("mutation", ["missing", "cross_prompt", "cross_schema", "prompt_bytes", "schema_bytes"])
def test_prior_action_contracts_reject_missing_cross_binding_and_drift(tmp_path, mutation):
    import shutil
    from contracts import action_contract_binding
    root = tmp_path / "generate"
    shutil.copytree(CONTRACTS, root / "contracts")
    shutil.copytree(SKILL_ROOT / "prompts", root / "prompts")
    path = root / "contracts/action-contracts-v1.json"
    registry = read_json(path)
    contract = next(item for item in registry["contracts"] if item["actionContractId"] == "PRIOR_ANALYZE-v1")
    other = next(item for item in registry["contracts"] if item["actionContractId"] == "PRIOR_CONSOLIDATE-v1")
    if mutation == "missing":
        registry["contracts"].remove(contract)
    elif mutation == "cross_prompt":
        contract["instruction"] = other["instruction"]
    elif mutation == "cross_schema":
        contract["resultSchema"] = registry["contracts"][0]["resultSchema"]
    else:
        target = root / contract["instruction" if mutation == "prompt_bytes" else "resultSchema"]["path"]
        target.write_bytes(target.read_bytes() + b" ")
    path.write_bytes(canonical_json_bytes(registry))
    with pytest.raises((LookupError, ValueError)):
        action_contract_binding(root, "PRIOR_ANALYZE-v1")


@pytest.mark.parametrize("kind,field", [("PROTOTYPE_SCENARIO", "page"), ("PROTOTYPE_BROWSER", "page"), ("PROTOTYPE_BROWSER", "eventObserved")])
def test_prototype_step_target_facts_are_required_by_exact_action_contract(kind, field):
    from contracts import action_contract_binding, normalize_action_result, InvalidActionResult
    sys.path.insert(0, str(SKILL_ROOT / "tests"))
    from test_prototype_analysis import demo_files, scenario_fixture, trace_fixture
    from prototype_analysis import inventory_demo_bundle
    inventory = inventory_demo_bundle("demo/index.html", demo_files())
    scenario = scenario_fixture(inventory)
    result = scenario if kind == "PROTOTYPE_SCENARIO" else trace_fixture(inventory, scenario)
    contract, digest = action_contract_binding(SKILL_ROOT, kind + "-v1")
    envelope = {"actionContractId": contract["actionContractId"], "actionContractSha256": digest}
    assert normalize_action_result(envelope, canonical_json_bytes(result), skill_root=SKILL_ROOT) == canonical_json_bytes(result)
    steps = result["scenarios" if kind == "PROTOTYPE_SCENARIO" else "runs"][0]["steps"]
    del steps[0][field]
    with pytest.raises(InvalidActionResult):
        normalize_action_result(envelope, canonical_json_bytes(result), skill_root=SKILL_ROOT)


def test_run_budget_policy_accepts_complete_explicit_body():
    diagnostics = validate_contract(
        valid_run_budget_policy(),
        "run-budget-policy.schema.json",
        load_schema_registry(SKILL_ROOT),
    )
    assert diagnostics == ()


@pytest.mark.parametrize(
    "field,value",
    [
        ("maxPlannedTokens", 0),
        ("maxPlannedTokens", -1),
        ("maxActiveSeconds", 0),
        ("referenceOverheadTokens", 0),
        ("modelContextLimitTokens", 0),
        ("maxConcurrency", 0),
        ("maxConcurrency", 9),
        ("outputReserveTokens", -1),
        ("hydrateReserveTokens", -1),
        ("safetyMarginTokens", -1),
        ("maxDiscoveryRounds", 0),
        ("maxScenarioSteps", 0),
        ("maxScreenshots", 0),
    ],
)
def test_run_budget_policy_rejects_invalid_numeric_limits(field, value):
    policy = valid_run_budget_policy()
    target = policy["demoLimits"] if field in policy["demoLimits"] else policy
    target[field] = value
    diagnostics = validate_contract(
        policy, "run-budget-policy.schema.json", load_schema_registry(SKILL_ROOT)
    )
    assert diagnostics
    assert all(item.code != "CONTRACT_REFERENCE_INVALID" for item in diagnostics)


@pytest.mark.parametrize("context_limit", [13312, 13311])
def test_run_budget_policy_rejects_nonpositive_usable_input(context_limit):
    policy = {**valid_run_budget_policy(), "modelContextLimitTokens": context_limit}
    diagnostics = validate_contract(
        policy, "run-budget-policy.schema.json", load_schema_registry(SKILL_ROOT)
    )
    assert {item.code for item in diagnostics} == {"RUN_BUDGET_USABLE_INPUT_INVALID"}


@pytest.mark.parametrize(
    "changes",
    [
        {"modelProfileId": "unregistered-model"},
        {"estimatorVersion": "unregistered-estimator"},
    ],
)
def test_run_budget_policy_rejects_unregistered_profile_estimator(changes):
    diagnostics = validate_contract(
        {**valid_run_budget_policy(), **changes},
        "run-budget-policy.schema.json", load_schema_registry(SKILL_ROOT),
    )
    assert {item.code for item in diagnostics} == {"RUN_BUDGET_ADAPTER_INVALID"}



def test_lossless_table_transport_preserves_packet_and_rejects_drift():
    from provider_adapter import pack_lossless_tables, unpack_lossless_tables, canonical_provider_request
    packet={'workItems':[{'workItemId':'prior-1','payload':{'evidence':[
        {'priorEvidenceId':str(index), 'sheet':'合同', 'canonicalCellValues':[
            {'address':f'A{index}', 'value':'完整条件、排除项与旧 ID', 'formula':None, 'cachedValue':None, 'cellType':'s'},
            {'address':f'B{index}', 'value':index, 'formula':None, 'cachedValue':None, 'cellType':'n'},
            {'address':f'C{index}', 'value':None, 'formula':'=B1+1', 'cachedValue':2, 'cellType':'f'}]}
        for index in range(300)]}}], 'contextRefs':[{'canonicalContent':{
            'kind':'ATTEMPT_REPAIR','rawOutputUtf8':'  { "保留": true }\\n','diagnostic':{'code':'INVALID_IR'}}}]}
    raw=canonical_json_bytes(packet)
    compact=pack_lossless_tables(raw)
    assert unpack_lossless_tables(compact)==raw
    assert len(canonical_json_bytes(compact)) < len(raw)*0.8
    request=json.loads(canonical_provider_request('host-canonical-messages-v1','test',raw,12000,lossless_tables=True))
    assert unpack_lossless_tables(json.loads(request['messages'][1]['content']))==raw
    assert json.loads(canonical_provider_request('host-canonical-messages-v1','test',raw,12000))['messages'][1]['content']==raw.decode()
    for defect in ('cell','hash','columns','duplicate'):
        broken=json.loads(canonical_json_bytes(compact))
        if defect=='cell':broken['packet']['workItems'][0]['workItemId']='changed'
        elif defect=='hash':broken['packetSha256']='0'*64
        elif defect=='columns':broken['tables'][0]['columns'].append('extra')
        else:broken['tables'].append(broken['tables'][0])
        with pytest.raises(ValueError):unpack_lossless_tables(broken)


def test_run_budget_policy_estimator_uses_complete_canonical_provider_request():
    from provider_adapter import canonical_provider_request, estimate_provider_request

    request = canonical_provider_request(
        "host-canonical-messages-v1", "读", b'{"workItems":[],"contextRefs":[]}\n', 20
    )
    assert request == (
        '{"maxOutputTokens":20,"messages":[{"content":"读","role":"system"},'
        '{"content":"{\\"contextRefs\\":[],\\"workItems\\":[]}\\n","role":"user"}]}\n'
    ).encode("utf-8")
    assert estimate_provider_request(
        "host-canonical-messages-v1", "utf8-bytes-v1", request
    ) == 138


@pytest.mark.parametrize(
    "started,ended,valid",
    [
        ("2026-09-05T00:00:00Z", "2026-09-05T00:00:01.500Z", True),
        (None, "2026-09-05T00:00:01Z", True),
        ("2026-09-05T00:00:02Z", "2026-09-05T00:00:01Z", False),
        ("2026-09-05T00:00:00+08:00", "2026-09-05T00:00:01Z", False),
        ("2026-09-05 00:00:00Z", "2026-09-05T00:00:01Z", False),
        ("2026-02-30T00:00:00Z", "2026-09-05T00:00:01Z", False),
        (None, None, False),
    ],
)
def test_attempt_timing_contract(started, ended, valid):
    from models import AttemptTiming
    from contracts import validate_attempt_timing

    timing = AttemptTiming(started, ended)
    if not valid:
        with pytest.raises(ValueError):
            validate_attempt_timing(timing, failed=True)
        return
    validate_attempt_timing(timing, failed=started is None)
    schema = next_schemas()["action.schema.json"]["$defs"]["attemptTiming"]
    validator = Draft202012Validator(
        schema, format_checker=Draft202012Validator.FORMAT_CHECKER
    )
    value = {"startedAtUtc": started, "endedAtUtc": ended}
    validator.validate(value)
    assert timing.active_seconds == (0 if started is None else 1.5)
    with pytest.raises(ValidationError):
        validator.validate({**value, "duration": 1.5})
    if started is None:
        with pytest.raises(ValueError):
            validate_attempt_timing(timing, failed=False)


@pytest.mark.parametrize(
    "category,execution_kind",
    [
        ("AUTHOR", "MODEL_PROVIDER"),
        ("HYDRATE", "MODEL_PROVIDER"),
        ("REVIEW", "MODEL_PROVIDER"),
        ("REPAIR", "MODEL_PROVIDER"),
        ("REVIEW", "HOST_BROWSER"),
    ],
)
def test_action_contract_registry_usage_binding(tmp_path, category, execution_kind):
    import shutil
    from contracts import action_contract_binding, validate_action_usage
    from models import Usage

    root = tmp_path / "skill"
    shutil.copytree(CONTRACTS, root / "contracts")
    shutil.copytree(SKILL_ROOT / "prompts", root / "prompts")
    registry_path = root / "contracts/action-contracts-v1.json"
    registry = read_json(registry_path)
    contract = registry["contracts"][0]
    contract["usageCategory"] = category
    contract["executionKind"] = execution_kind
    registry_path.write_bytes(canonical_json_bytes(registry))
    _, digest = action_contract_binding(root, contract["actionContractId"])
    envelope = {
        **valid_action_envelope(),
        "actionContractId": contract["actionContractId"],
        "actionContractSha256": digest,
    }
    validate_action_usage(
        envelope, Usage("PROVIDER_REPORTED", 0, 0, 0, None), skill_root=root
    )
    if execution_kind == "HOST_BROWSER":
        with pytest.raises(ValueError):
            validate_action_usage(
                envelope, Usage("PROVIDER_REPORTED", 1, 0, 0, None), skill_root=root
            )
    else:
        validate_action_usage(
            envelope, Usage("PROVIDER_REPORTED", 10, 4, 2, 1), skill_root=root
        )
    with pytest.raises(ValueError):
        validate_action_usage(
            {**envelope, "actionContractSha256": HEX_A},
            Usage("PROVIDER_REPORTED", 0, 0, 0, None),
            skill_root=root,
        )
    for field in ("usageCategory", "executionKind"):
        original = contract.pop(field)
        registry_path.write_bytes(canonical_json_bytes(registry))
        with pytest.raises(ValueError):
            action_contract_binding(root, contract["actionContractId"])
        contract[field] = [original]
        registry_path.write_bytes(canonical_json_bytes(registry))
        with pytest.raises(ValueError):
            action_contract_binding(root, contract["actionContractId"])
        contract[field] = original


@pytest.mark.parametrize(
    "changes,valid",
    [
        ({}, True),
        ({"provenance": "LOCALLY_ESTIMATED", "reasoning_tokens": None}, True),
        ({"provenance": "UNKNOWN"}, False),
        ({"input_tokens": -1}, False),
        ({"output_tokens": -1}, False),
        ({"cached_input_tokens": -1}, False),
        ({"reasoning_tokens": -1}, False),
        ({"cached_input_tokens": 11}, False),
        ({"reasoning_tokens": 5}, False),
        ({"input_tokens": True}, False),
    ],
)
def test_usage_contract(changes, valid):
    from models import Usage
    from contracts import validate_usage

    schema = next_schemas()["action.schema.json"]["$defs"]["attemptUsage"]
    schema_validator = Draft202012Validator(schema)

    values = dict(
        provenance="PROVIDER_REPORTED",
        input_tokens=10,
        output_tokens=4,
        cached_input_tokens=3,
        reasoning_tokens=2,
    )
    values.update(changes)
    if not valid:
        with pytest.raises(ValueError):
            validate_usage(Usage(**values))
        return
    usage = Usage(**values)
    json_usage = {
        "provenance": usage.provenance,
        "inputTokens": usage.input_tokens,
        "outputTokens": usage.output_tokens,
        "cachedInputTokens": usage.cached_input_tokens,
        "reasoningTokens": usage.reasoning_tokens,
    }
    schema_validator.validate(json_usage)
    with pytest.raises(ValidationError):
        schema_validator.validate({**json_usage, "chargedTokens": 14})
    validate_usage(usage)
    assert usage.charged_tokens == 14
    with pytest.raises(ValueError):
        validate_usage(usage, provider_started=False)
    validate_usage(Usage("LOCALLY_ESTIMATED", 0, 0, 0, None), provider_started=False)
    with pytest.raises(ValueError):
        validate_usage(Usage("PROVIDER_REPORTED", 0, 0, 0, 0), provider_started=False)


@pytest.mark.parametrize(
    "event_type,payload",
    [
        ("RUN_BUDGET_POLICY_PUBLISHED", {"budgetPolicySha256": HEX_A}),
        (
            "ACTION_ISSUED",
            {
                "actionId": "action-1",
                "logicalWorkId": "logical-1",
                "envelopeSha256": HEX_A,
            },
        ),
        ("INPUT_REVISION_CREATED", {"inputRevisionSha256": HEX_A}),
        (
            "WAITING_INPUT_ENTERED",
            {"waitId": "wait-1", "reasonCode": "BUDGET_EXHAUSTED"},
        ),
        (
            "WAITING_INPUT_EXITED",
            {
                "waitId": "wait-1",
                "resolutionKind": "BUDGET_POLICY",
                "budgetPolicySha256": HEX_A,
            },
        ),
        ("WAITING_INPUT_EXITED", {"waitId": "wait-1", "resolutionKind": "ABANDONED"}),
        ("WAITING_INPUT_EXITED", {"waitId":"wait-1", "resolutionKind":"FITTING_UNISSUED_PLAN",
            "stageKind":"SCOPE", "stagePlanSha256":HEX_A, "groupId":"group-1"}),
        ("WAITING_INPUT_EXITED", {"waitId":"wait-1", "resolutionKind":"FITTING_UNISSUED_RETRY",
            "actionId":"action-1", "envelopeSha256":HEX_A, "failedAttemptRecordSha256":HEX_B}),
        (
            "DETERMINISTIC_STEP_FINISHED",
            {
                "stepKind": "MATERIALIZE",
                "outcome": "SUCCEEDED",
                "startedAtUtc": "2026-09-05T00:00:00Z",
                "endedAtUtc": "2026-09-05T00:00:01Z",
            },
        ),
        (
            "DETERMINISTIC_STEP_FINISHED",
            {
                "stepKind": "OFFICE",
                "outcome": "FAILED",
                "failureCode": "OFFICE_FAILED",
                "startedAtUtc": "2026-09-05T00:00:00Z",
                "endedAtUtc": "2026-09-05T00:00:01Z",
            },
        ),
        ("RUN_STATE_CHANGED", {"fromState": "CREATED", "toState": "WAITING_INPUT"}),
    ],
)
def test_run_event_payload_contract(event_type, payload):
    schema = read_json(CONTRACTS / "run-event.schema.json")
    validator = Draft202012Validator(
        schema, format_checker=Draft202012Validator.FORMAT_CHECKER
    )
    event = {
        "runId": "run-1",
        "sequence": 1,
        "type": event_type,
        "occurredAtUtc": "2026-09-05T00:00:01Z",
        "payload": payload,
    }
    validator.validate(event)
    for key in payload:
        malformed = copy.deepcopy(event)
        del malformed["payload"][key]
        with pytest.raises(ValidationError):
            validator.validate(malformed)
    for target in (event, payload):
        target["unexpected"] = True
        with pytest.raises(ValidationError):
            validator.validate(event)
        del target["unexpected"]
    malformed = copy.deepcopy(event)
    malformed["payload"][
        (
            "failureCode"
            if event_type == "DETERMINISTIC_STEP_FINISHED"
            and payload["outcome"] == "SUCCEEDED"
            else "budgetPolicySha256"
        )
    ] = "invalid"
    with pytest.raises(ValidationError):
        validator.validate(malformed)


def next_schemas() -> dict[str, dict[str, object]]:
    return {name: read_json(NEXT_CONTRACTS / name) for name in NEXT_SCHEMA_IDS}


def next_registry(
    values: dict[str, dict[str, object]] | None = None,
) -> Registry:
    result = Registry()
    for schema in (values or next_schemas()).values():
        Draft202012Validator.check_schema(schema)
        result = result.with_resource(
            str(schema["$id"]), Resource.from_contents(schema)
        )
    return result


def validate_next(schema_name: str, value: object) -> None:
    values = next_schemas()
    Draft202012Validator(
        values[schema_name],
        registry=next_registry(values),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    ).validate(value)


def valid_next_request() -> dict[str, object]:
    return {
        "contract": "ai-sow-generate-request-v3",
        "project": {
            "projectId": "project-training",
            "name": "培训平台",
            "plannedEffectiveDate": "2026-10-01",
        },
        "mode": "GREENFIELD",
        "responsibilityBoundaries": [
            {
                "responsibilityBoundaryId": "responsibility-vendor",
                "party": "VENDOR",
                "name": "供应商交付责任",
                "responsibilities": ["交付范围内实现与验证"],
            }
        ],
        "sources": [
            {
                "sourceId": "prd-main",
                "role": "PRD",
                "path": "inputs/prd.md",
                "expectedSha256": HEX_A,
            },
            {
                "sourceId": "hld-main",
                "role": "HLD",
                "path": "inputs/hld.md",
                "expectedSha256": HEX_B,
            },
        ],
        "questions": [],
        "questionnaireAnswers": [],
        "declaredChangeContext": None,
    }


def valid_input_revision() -> dict[str, object]:
    return {
        "contract": "ai-sow-input-revision-v1",
        "revisionId": "revision-0001",
        "requestSha256": HEX_A,
        "templateSha256": HEX_B,
        "deliveryPolicySha256": HEX_C,
        "executionPolicySha256": "d" * 64,
        "project": {"projectId": "project-training", "name": "培训平台", "plannedEffectiveDate": "2026-10-01"},
        "priorSowState": "NOT_PROVIDED",
        "priorSowSha256s": [],
        "sources": [
            {
                "sourceId": "prd-main",
                "role": "PRD",
                "status": "APPROVED",
                "path": "inputs/revisions/revision-0001/sources/prd-main.md",
                "rawSha256": HEX_A,
                "parserId": "markdown-blocks",
                "parserVersion": "1",
                "blockIds": ["block-prd-001"],
            }
        ],
        "blocks": [
            {
                "blockId": "block-prd-001",
                "sourceId": "prd-main",
                "rawSha256": HEX_A,
                "contentSha256": HEX_B,
                "locator": "heading:1",
                "primaryCoverageBlockId": "block-prd-001",
                "contextBlockIds": [],
                "structuralParentId": None,
                "extractionDisposition": "INCLUDED",
                "droppedContentCategories": [],
            }
        ],
    }


def test_request_change_context_rejects_retired_field_and_accepts_declared_context() -> None:
    """A request must carry the v3 Brownfield change declaration, never v2 state."""
    retired_token = valid_next_request()
    retired_token["contract"] = "ai-sow-generate-request-v2"
    with pytest.raises(ValidationError):
        validate_next("request.schema.json", retired_token)

    retired_field = valid_next_request()
    retired_field["currentStateDelta"] = None
    with pytest.raises(ValidationError):
        validate_next("request.schema.json", retired_field)

    value = valid_next_request()
    validate_next("request.schema.json", value)


def test_project_effective_start_is_preserved_in_input_revision() -> None:
    for name in ("greenfield.json", "demo-extension.json", "brownfield.json"):
        fixture = read_json(FIXTURES / "pipeline/input-revisions" / name)
        validate_next("input-revision.schema.json", fixture)
        assert fixture["project"]["plannedEffectiveDate"] == "2026-10-01"

    missing_project = valid_input_revision()
    del missing_project["project"]
    with pytest.raises(ValidationError):
        validate_next("input-revision.schema.json", missing_project)

    value = valid_input_revision()
    value["project"] = {
        "projectId": "project-training",
        "name": "培训平台",
        "plannedEffectiveDate": "2026-10-01",
    }
    validate_next("input-revision.schema.json", value)

    value["projectEffectiveStart"] = "2026-10-01"
    with pytest.raises(ValidationError):
        validate_next("input-revision.schema.json", value)

    for invalid_date in ("2026-9-1", "2026-02-30", "2026-10-01T00:00:00Z"):
        invalid_request = valid_next_request()
        invalid_request["project"]["plannedEffectiveDate"] = invalid_date
        with pytest.raises(ValidationError):
            validate_next("request.schema.json", invalid_request)
        assert validate_contract(
            invalid_request,
            "request.schema.json",
            load_registry(CONTRACTS),
        )

    missing_date = valid_next_request()
    del missing_date["project"]["plannedEffectiveDate"]
    with pytest.raises(ValidationError):
        validate_next("request.schema.json", missing_date)


def test_source_role_and_hash_contract_requires_hash_without_status() -> None:
    value = valid_next_request()
    assert all(
        set(source) == {"sourceId", "role", "path", "expectedSha256"}
        for source in value["sources"]
    )
    validate_next("request.schema.json", value)

    invalid = copy.deepcopy(value)
    invalid["sources"][0].pop("expectedSha256")
    invalid["sources"][0]["status"] = "APPROVED"
    with pytest.raises(ValidationError):
        validate_next("request.schema.json", invalid)

    brownfield = copy.deepcopy(value)
    brownfield["mode"] = "BROWNFIELD"
    brownfield["declaredChangeContext"] = {
        "status": "NO_KNOWN_CHANGES",
        "summary": "以往期 SOW 建立按合同推定的现状基线。",
        "supplementalSourceIds": [],
    }
    brownfield["sources"].append(
        {
            "sourceId": "prior-main",
            "role": "PRIOR_SOW",
            "path": "inputs/prior.xlsx",
            "expectedSha256": HEX_C,
        }
    )
    validate_next("request.schema.json", brownfield)

    reference_only = copy.deepcopy(brownfield)
    reference_only["sources"][-1]["status"] = "REFERENCE_ONLY"
    with pytest.raises(ValidationError):
        validate_next("request.schema.json", reference_only)


def test_full_compile_only_rejects_reuse_render_and_delta_routes() -> None:
    value = valid_run_state()
    assert value["contract"] == "ai-sow-run-state-v3"
    validate_next("run-state.schema.json", value)
    for route in ("REUSE", "RENDER_ONLY", "DELTA_COMPILE"):
        invalid = valid_run_state()
        invalid["route"] = route
        with pytest.raises(ValidationError):
            validate_next("run-state.schema.json", invalid)


def test_demo_bundle_request_requires_hash_bound_html_entrypoint() -> None:
    value = valid_next_request()
    value["sources"] = [source for source in value["sources"] if source["role"] != "DEMO"]
    value["demo"] = {
        "entrypoint": "inputs/demo/index.html",
        "files": [
            {"sourceId": "demo-index", "role": "DEMO", "path": "inputs/demo/index.html", "expectedSha256": HEX_A},
            {"sourceId": "demo-js", "role": "DEMO", "path": "inputs/demo/app.js", "expectedSha256": HEX_B},
        ],
    }
    validate_next("request.schema.json", value)

    legacy_single_file = copy.deepcopy(value)
    del legacy_single_file["demo"]
    legacy_single_file["sources"].append(
        {
            "sourceId": "demo-index",
            "role": "DEMO",
            "path": "inputs/demo/index.html",
            "expectedSha256": HEX_A,
        }
    )
    with pytest.raises(ValidationError):
        validate_next("request.schema.json", legacy_single_file)

    for mutation in (
        lambda demo: demo.update({"entrypoint": "inputs/demo/missing.js"}),
        lambda demo: demo["files"][0].pop("expectedSha256"),
    ):
        invalid = copy.deepcopy(value)
        mutation(invalid["demo"])
        with pytest.raises(ValidationError):
            validate_next("request.schema.json", invalid)
    outside = copy.deepcopy(value)
    outside["demo"]["entrypoint"] = "inputs/demo/missing.html"
    assert {item.code for item in validate_contract(outside, "request.schema.json", load_registry(CONTRACTS))} == {
        "DEMO_ENTRYPOINT_OUTSIDE_BUNDLE"
    }


def test_input_item_boundary_keeps_transport_to_work_and_context_refs() -> None:
    defs = next_schemas()["action.schema.json"]["$defs"]
    assert "actionPacket" in defs
    schema = defs["actionPacket"]
    validator = Draft202012Validator(schema)
    validator.validate({
        "workItems": [
            {"workItemId": f"work-{index}"}
            for index in range(1, 5)
        ],
        "contextRefs": [],
    })
    with pytest.raises(ValidationError):
        validator.validate({"workItems": [], "contextRefs": [], "inputItems": [{"inputItemId": "input-1"}]})


def test_result_schema_dispatch_uses_registered_action_contract_only() -> None:
    from contracts import (  # noqa: PLC0415
        action_contract_binding,
        validate_action_result,
    )

    registry_path = CONTRACTS / "action-contracts-v1.json"
    assert registry_path.exists()
    registry = read_json(registry_path)
    contracts = registry["contracts"]
    assert len(contracts) == 25
    assert {item["actionContractId"] for item in contracts if item["actionContractId"].startswith("PROTOTYPE_")} == {
        "PROTOTYPE_SCENARIO-v1", "PROTOTYPE_BROWSER-v1", "PROTOTYPE_ANALYZE-v1",
    }
    assert len({item["actionContractId"] for item in contracts}) == len(contracts)
    for item in contracts:
        contract, contract_sha256 = action_contract_binding(
            SKILL_ROOT,
            item["actionContractId"],
        )
        assert contract == item
        assert contract_sha256 == sha256_bytes(canonical_json_bytes(item))
        for binding_name in ("instruction", "resultSchema"):
            binding = item[binding_name]
            assert sha256_bytes((SKILL_ROOT / binding["path"]).read_bytes()) == binding["sha256"]

    contract = contracts[0]
    assert contract["actionContractId"] == "SOURCE_SCAN-v1"
    assert contract["instruction"]["path"] == "prompts/stage1-source-scan.md"
    assert contract["resultSchema"]["id"] == (
        "urn:ai-sow:generate:next:fact-decision:1#/$defs/sourceScanResult"
    )

    envelope = valid_action_envelope()
    _, contract_sha256 = action_contract_binding(SKILL_ROOT, "SOURCE_SCAN-v1")
    envelope["actionContractSha256"] = contract_sha256
    from ir_samples import scan_ir
    source_scan = scan_ir()
    assert validate_action_result(envelope, source_scan, skill_root=SKILL_ROOT) == ()

    wrong_registered_subtype = {
        "contract": "ai-sow-stage-result-v1",
        "resultKind": "PATCH",
        "reviewedEvidenceIds": [],
        "replacementSet": {"expectedNodeHashes": {}, "upserts": [], "deletes": []},
        "selfCheck": {"completedCheckIds": [], "unresolvedItems": []},
    }
    with pytest.raises(ValidationError): validate_next("action.schema.json", wrong_registered_subtype)
    assert {
        item.code
        for item in validate_action_result(
            envelope,
            wrong_registered_subtype,
            skill_root=SKILL_ROOT,
        )
    } == {"ACTION_RESULT_SCHEMA_INVALID"}

    assert {
        item.code
        for item in validate_action_result(
            envelope,
            {"arbitrary": "json"},
            skill_root=SKILL_ROOT,
        )
    } == {"ACTION_RESULT_SCHEMA_INVALID"}

    unregistered = copy.deepcopy(envelope)
    unregistered["actionContractId"] = "CALLER_SCHEMA-v1"
    assert {
        item.code
        for item in validate_action_result(
            unregistered,
            source_scan,
            skill_root=SKILL_ROOT,
        )
    } == {"ACTION_CONTRACT_INVALID"}

    caller_selected = copy.deepcopy(envelope)
    caller_selected["resultSchema"] = "any.json"
    with pytest.raises(ValidationError):
        validate_next("action.schema.json", caller_selected)


@pytest.mark.parametrize(
    "name",
    ["greenfield.json", "demo-extension.json", "brownfield.json"],
)
def test_pipeline_input_revision_fixtures_match_strict_contract(name: str) -> None:
    value = read_json(FIXTURES / "pipeline/input-revisions" / name)
    diagnostics = validate_contract(
        value,
        "input-revision.schema.json",
        load_registry(NEXT_CONTRACTS),
    )
    assert diagnostics == ()


def valid_sow_model() -> dict[str, object]:
    return {
        "contract": "ai-sow-model-v1",
        "project": {
            "projectId": "project-training",
            "mode": "GREENFIELD",
            "inputRevisionSha256": HEX_A,
            "sourceManifestSha256": HEX_B,
            "templateSha256": HEX_C,
            "policyDefinitionSha256": "d" * 64,
            "responsibilityBoundaries": [],
        },
        "inputItems": [],
        "scopeClosure": [],
        "epics": [],
        "features": [],
        "designItems": [],
        "integrations": [],
        "nfrs": [],
        "policyInstances": [],
        "scopeAnnotations": [],
        "stories": [],
        "acceptanceCriteria": [],
        "deliveryAnnotations": [],
        "tasks": [],
        "dependencies": [],
        "effectiveStartMatches": [],
        "estimationAnnotations": [],
        "decisions": [],
    }


def valid_action_envelope() -> dict[str, object]:
    return {
        "contract": "ai-sow-action-v3",
        "runId": "run-0001",
        "actionId": "action-0007",
        "logicalWorkId": "logical-story-feature-006",
        "revision": 1,
        "attempt": 1,
        "stageKind": "STORY_AC",
        "groupId": "group-story-ac",
        "inputRevisionSha256": HEX_A,
        "upstreamCheckpointSha256s": [],
        "baseCandidateSha256": HEX_B,
        "actionContractId": "SOURCE_SCAN-v1",
        "actionContractSha256": HEX_C,
        "packetPath": "work/runs/run-0001/actions/action-0007/packet.json",
        "packetSha256": HEX_C,
        "resultPath": "work/runs/run-0001/actions/action-0007/result.json",
        "validatorVersion": "validator-v1",
        "budgetPolicySha256": "d" * 64,
        "executionLimits": {"estimatedInputTokens": 100, "maxOutputTokens": 200, "maxHydrateTokens": 50},
    }


def valid_run_state() -> dict[str, object]:
    return {
        "contract": "ai-sow-run-state-v3",
        "runId": "run-0001",
        "requestSha256": HEX_A,
        "route": "FULL_COMPILE",
        "phase": "STORY_AC",
        "wait": "MODEL",
        "result": None,
        "currentInputRevisionSha256": HEX_B,
        "currentCandidateSha256": HEX_C,
        "currentCandidatePath": "work/runs/run-0001/candidates/0001-" + HEX_C + ".json",
        "expectedActionIds": ["action-0007"],
        "checkpointRefs": [],
        "resumeFromPhase": None,
    }


def checkpoint_value(kind: str) -> dict[str, object]:
    stage = {'SCOPE_CLOSURE': 'SCOPE', 'SCOPE': 'SCOPE', 'STORY_AC': 'STORY_AC', 'TASK': 'TASK'}[kind]
    return {'stageKind': stage, 'inputRevisionSha256': HEX_A, 'stagePlanSha256': HEX_B,
        'upstreamCheckpointSha256s': [] if stage == 'SCOPE' else [HEX_C],
        'effectiveAttemptRecordSha256s': [HEX_C], 'candidateSha256': HEX_A,
        'validatorResultSha256': HEX_B, 'reviewPacketSha256': HEX_C, 'reviewDecisionSha256': HEX_A}


def test_stage_seal_contract_retires_generic_patch_and_reuses_exact_owner_ir():
    from contracts import action_contract_binding, validate_action_result
    from ir_samples import complete_scope_ir, story_ac_ir, task_decision_ir
    patch = {'contract': 'ai-sow-stage-result-v1', 'resultKind': 'PATCH', 'reviewedEvidenceIds': [],
        'replacementSet': {'expectedNodeHashes': {}, 'upserts': [], 'deletes': []},
        'selfCheck': {'completedCheckIds': [], 'unresolvedItems': []}}
    with pytest.raises(ValidationError): validate_next('action.schema.json', patch)
    for stage, owner, result in [('SCOPE', 'SCOPE_SYNTHESIS', complete_scope_ir()),
                                ('STORY_AC', 'STORY_AC', story_ac_ir()), ('TASK', 'TASK', task_decision_ir())]:
        repair, digest = action_contract_binding(SKILL_ROOT, stage+'_REPAIR-v1')
        author, _ = action_contract_binding(SKILL_ROOT, owner+'-v1')
        assert repair['resultSchema'] == author['resultSchema']
        envelope = {'actionContractId': stage+'_REPAIR-v1', 'actionContractSha256': digest}
        assert not validate_action_result(envelope, result, skill_root=SKILL_ROOT)
        assert validate_action_result(envelope, patch, skill_root=SKILL_ROOT)


def test_nine_contract_families_have_stable_ids_and_reject_extra_fields() -> None:
    sys.path.insert(0, str(SKILL_ROOT / "tests"))
    from test_prototype_analysis import demo_files, scenario_fixture, trace_fixture, observation_fixture
    from prototype_analysis import inventory_demo_bundle
    from test_candidate_repair_protocol import field_case
    import candidate_repair

    inventory = inventory_demo_bundle("demo/index.html", demo_files())
    scenario = scenario_fixture(inventory)
    values = next_schemas()
    assert {name: value["$id"] for name, value in values.items()} == NEXT_SCHEMA_IDS
    from ir_samples import scan_ir, audit_ir, complete_scope_ir, story_ac_ir, task_decision_ir
    repair_base, repair_report, repair_groups, repair_origin = field_case()
    repair_plan = json.loads(candidate_repair.build_repair_plan(
        repair_base, repair_report, repair_groups, origin=repair_origin
    ))
    samples = {
        "task-decision.schema.json": task_decision_ir(),
        "story-ac-decision.schema.json": story_ac_ir(),
        "fact-decision.schema.json": scan_ir(),
        "source-audit.schema.json": audit_ir(),
        "scope-decision.schema.json": complete_scope_ir(),
        "change-graph.schema.json": {"changeGroups": [], "retiredPrior": []},
        "prior-state-snapshot.schema.json": {"contractVersion": "prior-state-snapshot-v1", "inputRevisionSha256": HEX_A, "evidence": [], "entities": [], "sourceRelations": [], "entitySupersessions": []},
        "prior-state-decision.schema.json": {"entities": [], "sourceRelations": [], "entitySupersessions": [], "unsupportedRegions": []},
        "prior-state-decision-v2.schema.json": {"entities": [], "sourceRelations": [], "entitySupersessions": [], "unsupportedRegions": [], "unextractedEvidence": []},
        "prototype-scenario.schema.json": scenario,
        "prototype-trace.schema.json": trace_fixture(inventory, scenario),
        "prototype-observation.schema.json": {"observations": [observation_fixture(inventory)]},
        "run-budget-policy.schema.json": valid_run_budget_policy(),
        "run-event.schema.json": {
            "runId": "run-1",
            "sequence": 1,
            "type": "RUN_STATE_CHANGED",
            "occurredAtUtc": "2026-09-05T00:00:00Z",
            "payload": {"fromState": "CREATED", "toState": "RUNNING"},
        },
        "request.schema.json": valid_next_request(),
        "input-revision.schema.json": valid_input_revision(),
        "sow-model.schema.json": valid_sow_model(),
        "run-state.schema.json": valid_run_state(),
        "action.schema.json": valid_action_envelope(),
        "stage-checkpoint.schema.json": checkpoint_value("SCOPE_CLOSURE"),
        "artifact-repair-authorization.schema.json": {'contract':'ai-sow-artifact-repair-authorization-v1','runId':'run-123456abcdef',
            'terminalStateSha256':HEX_A,'candidateSha256':HEX_B,'visualReviewAttemptRecordSha256':HEX_C,'rendererSha256':HEX_A,
            'repairFromStep':'RENDER','decision':'仅修复预览分页。','provenance':'USER','authorization':'用户要求继续修复。'},
        "review-repair.schema.json": {'decision': 'PASS', 'findings': []},
        "owner-clarification.schema.json": {'contract':'ai-sow-owner-clarification-v1','stageKind':'TASK',
            'candidateSha256':HEX_A,'reviewDecisionSha256':HEX_B,'scope':'IMPLEMENTATION_WITHIN_APPROVED_TARGETS',
            'technicalTargetKeys':['target:existing'],'decision':'使用既有批准目标内的实施方式。',
            'provenance':'USER','authorization':'用户已明确决定。'},
        "owner-repair-authorization.schema.json": {'contract':'ai-sow-owner-repair-authorization-v1','stageKind':'TASK',
            'runId':'run-123456abcdef','candidateSha256':HEX_A,'reviewDecisionSha256':HEX_B,'terminalStateSha256':HEX_C,
            'rootKeys':['task:existing'],'allowedFields':['complexityDecision'],'additionalRevisions':1,
            'decision':'仅修正复杂度。','provenance':'SIMULATED_USER','authorization':'用户已授权模拟裁定。'},
        "visual-review.schema.json": {'sheets':[{'sheetKey':'sheet-a','checks':{key:'PASS' for key in
            ('clipping','readability','unexpectedBlank','styleLoss')},'decision':'PASS','findings':[]}],'overallDecision':'PASS'},
        "candidate-repair.schema.json": repair_plan,
        "artifact-approval.schema.json": artifact_manifest_sample(),
        "generation-manifest.schema.json": {
            "contract": "ai-sow-generation-manifest-v2",
            "generationId": "generation-0001",
            "runId": "run-0001",
            "inputRevisionSha256": HEX_A,
            "sowModelPath": "generations/generation-0001/data/sow-model.json",
            "sowModelSha256": HEX_B,
            "stageCheckpointSha256s": [HEX_A, HEX_B, HEX_C],
            "reviewDecisionSha256": "d" * 64,
            "artifactManifestSha256": "e" * 64,
            "approvalSha256": "f" * 64,
            "templateSha256": HEX_C,
            "effectivePolicyDecisionSha256": "1" * 64,
            "rendererContract": "generation-renderer-v12",
            "rendererSha256": "6" * 64,
            "workbookPath": "generations/generation-0001/output/sow.xlsx",
            "workbookSha256": "2" * 64,
            "notesPath": "generations/generation-0001/output/sow-notes.md",
            "notesSha256": "3" * 64,
            "publicationComplete": True,
        },
        "current.schema.json": {
            "contract": "ai-sow-current-v2",
            "generationId": "generation-0001",
            "generationManifestPath": "generations/generation-0001/manifest.json",
            "generationManifestSha256": HEX_A,
        },
    }
    assert set(samples) == set(NEXT_SCHEMA_IDS) - {"common.schema.json"}
    for schema_name, sample in samples.items():
        validate_next(schema_name, sample)
        invalid = copy.deepcopy(sample)
        (invalid[0] if isinstance(invalid, list) else invalid)["unexpected"] = True
        with pytest.raises(ValidationError):
            validate_next(schema_name, invalid)


def test_run_state_rejects_illegal_route_phase_wait_result_combinations() -> None:
    validate_next("run-state.schema.json", valid_run_state())
    invalid = valid_run_state()
    invalid["result"] = "PUBLISHED"
    with pytest.raises(ValidationError):
        validate_next("run-state.schema.json", invalid)

    done = valid_run_state()
    done.update(
        {
            "phase": "DONE",
            "wait": "NONE",
            "result": "PUBLISHED",
            "expectedActionIds": [],
            "resumeFromPhase": None,
        }
    )
    validate_next("run-state.schema.json", done)


def test_action_envelope_v3_requires_exact_execution_limits() -> None:
    from contracts import (  # noqa: PLC0415
        action_contract_binding,
        estimate_action_input_tokens,
        validate_action_envelope,
    )

    policy = valid_run_budget_policy()
    packet_payload = canonical_json_bytes(
        {
            "workItems": [
                {"workItemId": "source-block-001", "payload": {"text": "范围事实"}}
            ],
            "contextRefs": [],
        }
    )
    _, action_contract_sha256 = action_contract_binding(
        SKILL_ROOT,
        "SOURCE_SCAN-v1",
    )
    value = valid_action_envelope()
    value.update(
        {
            "actionContractSha256": action_contract_sha256,
            "packetSha256": sha256_bytes(packet_payload),
            "budgetPolicySha256": sha256_bytes(canonical_json_bytes(policy)),
        }
    )
    assert estimate_action_input_tokens(
        SKILL_ROOT,
        "SOURCE_SCAN-v1",
        packet_payload,
        budget_policy=policy,
        max_output_tokens=200,
    ) == 1171
    value["executionLimits"] = {
        "estimatedInputTokens": 1171,
        "maxOutputTokens": 200,
        "maxHydrateTokens": 50,
    }
    assert validate_action_envelope(
        value,
        packet_payload=packet_payload,
        skill_root=SKILL_ROOT,
        effective_budget_policy=policy,
    ) == ()

    inherited = copy.deepcopy(value)
    inherited["executionLimits"]["activeDeadline"] = 1
    with pytest.raises(ValidationError):
        validate_next("action.schema.json", inherited)

    escaped = copy.deepcopy(value)
    escaped["resultPath"] = "../submission.json"
    with pytest.raises(ValidationError):
        validate_next("action.schema.json", escaped)

    for retired_field in (
        "normalizedResultSha256",
        "resultSchema",
        "reviewPolicySelector",
        "activeDeadline",
    ):
        invalid = copy.deepcopy(value)
        invalid[retired_field] = HEX_B
        with pytest.raises(ValidationError):
            validate_next("action.schema.json", invalid)

    invalid_policy = copy.deepcopy(value)
    invalid_policy["budgetPolicySha256"] = HEX_B
    assert {
        item.code
        for item in validate_action_envelope(
            invalid_policy,
            packet_payload=packet_payload,
            skill_root=SKILL_ROOT,
            effective_budget_policy=policy,
        )
    } == {"ACTION_BUDGET_POLICY_MISMATCH"}

    invalid_estimate = copy.deepcopy(value)
    invalid_estimate["executionLimits"]["estimatedInputTokens"] += 1
    assert {
        item.code
        for item in validate_action_envelope(
            invalid_estimate,
            packet_payload=packet_payload,
            skill_root=SKILL_ROOT,
            effective_budget_policy=policy,
        )
    } == {"ACTION_INPUT_ESTIMATE_MISMATCH"}

    retired_v1 = copy.deepcopy(value)
    retired_v1["contract"] = "ai-sow-action-envelope-v1"
    with pytest.raises(ValidationError):
        validate_next("action.schema.json", retired_v1)

    contract, _ = action_contract_binding(SKILL_ROOT, "SOURCE_SCAN-v1")
    for field in ("maxOutputTokens", "maxHydrateTokens"):
        over_limit = copy.deepcopy(value)
        over_limit["executionLimits"][field] = contract["limits"][field] + 1
        over_limit["executionLimits"]["estimatedInputTokens"] = estimate_action_input_tokens(
            SKILL_ROOT, "SOURCE_SCAN-v1", packet_payload,
            budget_policy=policy, max_output_tokens=over_limit["executionLimits"]["maxOutputTokens"],
        )
        assert {
            item.code
            for item in validate_action_envelope(
                over_limit,
                packet_payload=packet_payload,
                skill_root=SKILL_ROOT,
                effective_budget_policy=policy,
            )
        } == {"ACTION_EXECUTION_LIMIT_EXCEEDED"}


def test_next_action_union_never_waits_for_an_empty_model_action_group() -> None:
    first_action = valid_action_envelope()
    second_action = copy.deepcopy(first_action)
    second_action.update({"actionId": "action-0008", "logicalWorkId": "logical-story-feature-007"})
    for value in (
        {
            "contract": "ai-sow-next-action-v1",
            "kind": "REQUEST_INPUT",
            "questions": [
                {
                    "questionId": "confirm-design",
                    "subjectIds": ["FEATURE-006"],
                    "question": "请补充批准设计。",
                    "whyAsked": "当前设计不足以形成实施边界。",
                    "answerDetermines": ["Story 技术边界"],
                    "unansweredConsequence": "阻断正式 SOW。",
                    "requiredSourceRole": "APPROVED_DESIGN",
                    "checkedEvidenceIds": ["SRC-HLD:B-003"],
                }
            ],
        },
        {
            "contract": "ai-sow-next-action-v1",
            "kind": "REQUEST_APPROVAL",
            "artifactManifestPath": "work/runs/run-0001/artifacts/manifest.json",
            "artifactManifestSha256": HEX_A,
        },
        {
            "contract": "ai-sow-next-action-v1",
            "kind": "DONE",
            "result": "PUBLISHED",
            "generationManifestPath": "generations/generation-0001/manifest.json",
        },
    ):
        validate_next("action.schema.json", value)

    empty_group = {
        "contract": "ai-sow-next-action-v1",
        "kind": "MODEL_ACTION_GROUP",
        "groupId": "group-story-ac",
        "maxConcurrency": 2,
        "groupDeadlineMilliseconds": 120000,
        "actions": [],
    }
    with pytest.raises(ValidationError):
        validate_next("action.schema.json", empty_group)


def test_attempt_record_rejects_retired_usage_and_inline_result():
    value = {
        "logicalWorkId": "logical-source-scan",
        "revision": 1,
        "attempt": 1,
        "envelopeSha256": "a" * 64,
        "outcome": "SUCCEEDED",
        "failureKind": None,
        "diagnostic": None,
        "rawSha256": "b" * 64,
        "normalizedResultSha256": "b" * 64,
        "usage": {
            "provenance": "PROVIDER_REPORTED",
            "inputTokens": 1,
            "outputTokens": 1,
            "cachedInputTokens": 0,
            "reasoningTokens": None,
        },
        "timing": {
            "startedAtUtc": "2026-09-05T00:00:00Z",
            "endedAtUtc": "2026-09-05T00:00:01Z",
        },
    }
    validate_next("action.schema.json", value)
    for extra in (
        "submission",
        "submissionSha256",
        "modelAttempts",
        "controlPlaneTokens",
    ):
        with pytest.raises(ValidationError):
            validate_next("action.schema.json", {**value, extra: {}})
    with pytest.raises(ValidationError):
        validate_next(
            "action.schema.json",
            {**value, "usage": {"accountingMode": "LOCALLY_ESTIMATED"}},
        )


def test_new_material_requires_new_run_approval_union_only_approve_and_abandon() -> None:
    base = {
        "contract": "ai-sow-approval-v1",
        "runId": "run-0001",
        "artifactManifestSha256": HEX_A,
        "reviewDecisionSha256": HEX_B,
        "candidateSha256": HEX_C,
        "sourceManifestSha256": "d" * 64,
        "templateSha256": "e" * 64,
        "effectivePolicyDecisionSha256": "f" * 64,
    }
    for decision, extra in (
        ("APPROVE", {"approvedAt": "2026-09-04T00:00:00Z"}),
        ("ABANDON", {"reason": "用户终止本轮。"}),
    ):
        value = {**base, "decision": decision, **extra}
        validate_next("artifact-approval.schema.json", value)
        wrong = {**value, "foreignDecisionField": True}
        with pytest.raises(ValidationError):
            validate_next("artifact-approval.schema.json", wrong)

    with pytest.raises(ValidationError):
        validate_next("artifact-approval.schema.json", {**base, "decision": "EXCLUDE_DEFAULT_AUTOMATION", "excludedPolicyInstanceIds": ["policy-sit-automation"], "reason": "更改范围须新 run。"})


def test_no_cross_run_reuse_is_not_a_run_terminal_result():
    value = valid_run_state()
    value.update(phase="DONE", wait="NONE", result="REUSED", expectedActionIds=[])
    with pytest.raises(ValidationError):
        validate_next("run-state.schema.json", value)


def test_policies_pin_delivery_lifecycle_and_execution_limits() -> None:
    delivery = read_json(CONTRACTS / "delivery-policy-v1.json")
    execution = read_json(CONTRACTS / "execution-policy-v1.json")
    assert delivery["contract"] == "ai-sow-delivery-policy-v1"
    assert {item["policyId"] for item in delivery["policies"]} >= {
        "policy-sit-automation",
        "policy-uat-automation",
        "policy-go-live",
        "policy-data-migration",
    }
    assert execution["contract"] == "ai-sow-execution-policy-v1"
    assert execution["contextAllocation"] == {
        "initialPacketRatio": 0.60,
        "hydrationRatio": 0.15,
        "outputRatio": 0.20,
        "safetyMarginRatio": 0.05,
    }
    assert execution["hardLimits"] == {
        "maxHydrationRoundsPerAction": 2,
        "maxExecutionAttemptsPerShard": 2,
        "maxSemanticRepairRoundsPerProposition": 2,
        "maxAdjudicationsPerProposition": 1,
        "maxReviewReshardDepth": 2,
        "maxPhysicalShardsPerLogicalTheme": 8,
    }


def test_pipeline_dtos_are_frozen() -> None:
    dto_types = (
        SourceDocument,
        InputRevisionResult,
        ActionEnvelope,
        AttemptRecord,
        RunState,
        CompilerProgress,
        CompilerResult,
        ReplacementOutcome,
        ReviewProgress,
        TaskStandardCatalog,
        CatalogHydration,
    )
    for dto_type in dto_types:
        assert dto_type.__dataclass_params__.frozen, dto_type.__name__

    state = RunState(value=valid_run_state())
    with pytest.raises(FrozenInstanceError):
        state.value = {}  # type: ignore[misc]


def test_action_binding_rejects_stale_envelope_revision_candidate_and_path() -> None:
    envelope = valid_action_envelope()
    envelope_sha256 = sha256_bytes(canonical_json_bytes(envelope))
    valid = {
        "action_id": "action-0007",
        "envelope_sha256": envelope_sha256,
        "input_revision_sha256": HEX_A,
        "base_candidate_sha256": HEX_B,
        "result_path": envelope["resultPath"],
        "expected_action_ids": ("action-0007",),
    }
    assert validate_action_binding(envelope, **valid) == ()

    cases = {
        "action_id": ("action-stale", "ACTION_ID_MISMATCH"),
        "envelope_sha256": (HEX_C, "ACTION_ENVELOPE_HASH_MISMATCH"),
        "input_revision_sha256": (HEX_C, "ACTION_INPUT_REVISION_STALE"),
        "base_candidate_sha256": (HEX_C, "ACTION_BASE_CANDIDATE_STALE"),
        "result_path": ("work/escaped.json", "ACTION_RESULT_PATH_MISMATCH"),
        "expected_action_ids": (("action-other",), "ACTION_NOT_EXPECTED"),
    }
    for field, (wrong_value, expected_code) in cases.items():
        arguments = {**valid, field: wrong_value}
        assert {item.code for item in validate_action_binding(envelope, **arguments)} == {
            expected_code
        }


def test_state_combination_rejects_retired_persistent_budget_aggregate() -> None:
    value = valid_run_state()
    assert validate_state_combination(value, next_registry()) == ()
    value["budget"] = {"modelActionsStarted": 1, "modelActionsCompleted": 0}
    assert validate_state_combination(value, next_registry())


def test_diagnostic_code_maps_to_exact_category_owner_and_retryability() -> None:
    expected = {
        "GLOBAL_SCOPE_CAPACITY_EXCEEDED": ("CONTRACT_UNSUPPORTED", "STAGE_1", False),
        "SOURCE_SEMANTIC_CONFLICT": ("INPUT_REQUIRED", "INPUT", True),
        "DESIGN_COVERAGE_INSUFFICIENT": ("INPUT_REQUIRED", "INPUT", True),
        "STORY_COVERAGE_OUTSTANDING": ("OWNER_FIX_REQUIRED", "STAGE_2", True),
        "STORY_GLOBAL_JOIN_REQUIRED": ("CONTROL", "STAGE_2", True),
        "TASK_STANDARD_TYPE_UNREPRESENTABLE": ("CONTRACT_UNSUPPORTED", "STAGE_3", False),
        "TASK_CHALLENGER_NOT_REVIEWED": ("OWNER_FIX_REQUIRED", "STAGE_3", True),
        "PRIOR_MATCH_SEARCH_INCOMPLETE": ("OWNER_FIX_REQUIRED", "STAGE_3", True),
        "TASK_X_SPLIT_REQUIRED": ("OWNER_FIX_REQUIRED", "STAGE_3", True),
        "THEME_JOIN_REQUIRED": ("CONTROL", "REVIEW", True),
        "RUN_IN_PROGRESS": ("CONTROL", "ORCHESTRATOR", False),
        "SIT_SUPPORT_ASSIGNMENT_NON_UNIQUE": ("OWNER_FIX_REQUIRED", "STAGE_3", True),
        "HOST_CAPABILITY_MISSING": ("SYSTEM_FAILED", "ORCHESTRATOR", False),
        "BUDGET_EXCEEDED": ("SYSTEM_FAILED", "ORCHESTRATOR", False),
    }
    for code, values in expected.items():
        classification = classify_diagnostic(code)
        assert (
            classification.category,
            classification.owner,
            classification.retryable,
        ) == values

    assert classify_diagnostic("TASK_TYPE_AMBIGUOUS", source_sufficient=True).category == (
        "OWNER_FIX_REQUIRED"
    )
    assert classify_diagnostic("TASK_TYPE_AMBIGUOUS", source_sufficient=False).category == (
        "INPUT_REQUIRED"
    )
    with pytest.raises(ValueError, match="source_sufficient"):
        classify_diagnostic("TASK_TYPE_AMBIGUOUS")
    with pytest.raises(ValueError, match="未知诊断码"):
        classify_diagnostic("UNKNOWN_CODE")


def test_question_hash_and_answer_binding_preserve_typed_gap_wording() -> None:
    question = {
        "questionId": "confirm-design",
        "subjectIds": ["FEATURE-006"],
        "question": "请在批准设计中补充语言回退规则。",
        "whyAsked": "需求已成立，但现有设计不能支持实施拆分和验收。",
        "answerDetermines": ["Story 技术边界", "Task 类型和复杂度"],
        "unansweredConsequence": "阻断正式实施型 SOW。",
        "requiredSourceRole": "APPROVED_DESIGN",
        "checkedEvidenceIds": ["SRC-HLD:B-003"],
    }
    assert validate_typed_gap_question(question) == ()
    answer = {
        "questionId": question["questionId"],
        "questionSha256": question_sha256(question),
        "answer": "回退到中文，并由前端负责切换。",
    }
    assert validate_question_answers([question], [answer]) == ()
    anchor = question_answer_anchors([question], [answer])[0]
    for exact_text in (
        question["question"],
        question["whyAsked"],
        *question["answerDetermines"],
        question["unansweredConsequence"],
    ):
        assert exact_text in anchor.normalized_text

    changed = copy.deepcopy(question)
    changed["whyAsked"] += " 这会影响计费边界。"
    assert question_sha256(changed) != question_sha256(question)
    assert {item.code for item in validate_question_answers([changed], [answer])} == {
        "QUESTION_ANSWER_HASH_MISMATCH"
    }

    invalid_role = {**question, "requiredSourceRole": "MODEL_GUESS"}
    assert {item.code for item in validate_typed_gap_question(invalid_role)} == {
        "QUESTION_REQUIRED_SOURCE_ROLE_INVALID"
    }


def test_contracts_module_contains_no_story_task_or_estimation_rules() -> None:
    source = (SCRIPTS / "contracts.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert not imported_modules.intersection(
        {"scope_compiler", "delivery_compiler", "task_standard_catalog", "workbook"}
    )
    for business_field in (
        '"workMode"',
        '"complexity"',
        '"taskCatalogSemanticSha256"',
    ):
        assert business_field not in source


def test_canonical_registry_contains_only_the_cutover_contracts() -> None:
    runtime_registry = load_schema_registry(SKILL_ROOT)
    next_contract_registry = load_registry(NEXT_CONTRACTS)
    runtime_ids = set(runtime_registry)
    next_ids = set(next_contract_registry)
    assert runtime_ids
    assert next_ids == set(NEXT_SCHEMA_IDS.values())
    assert runtime_ids == next_ids


@pytest.mark.parametrize("kind", ["SOURCE_SCAN", "SOURCE_AUDIT", "SCOPE_SYNTHESIS", "SCOPE_PROPOSAL", "SCOPE_JOIN"])
def test_scope_ir_set_normalization_preserves_qualifier_sequence(kind):
    from contracts import action_contract_binding, normalize_action_result
    sys.path.insert(0, str(SKILL_ROOT / "tests"))
    from ir_samples import scan_ir, audit_ir, scope_decision_ir
    if kind == "SOURCE_SCAN":
        first = scan_ir("root-z") + scan_ir("root-a")
        first[0]["facts"][0]["evidenceIds"] = ["e-z", "e-a"]
        second = copy.deepcopy(first[::-1])
        second[1]["facts"][0]["evidenceIds"].reverse()
    elif kind == "SOURCE_AUDIT":
        first = audit_ir()
        first["checks"][0]["relatedFactKeys"] = ["z", "a"]
        second = copy.deepcopy(first)
        second["checks"][0]["relatedFactKeys"].reverse()
        second["checks"].reverse()
    else:
        first = scope_decision_ir()
        first["decisions"][0]["factIds"] = ["z", "a"]
        first["decisions"].append(copy.deepcopy(first["decisions"][0]))
        first["decisions"][1]["localKey"] = "other"
        second = copy.deepcopy(first)
        second["decisions"][0]["factIds"].reverse()
        second["decisions"].reverse()
    raw_first, raw_second = canonical_json_bytes(first), canonical_json_bytes(second)
    assert raw_first != raw_second
    _, digest = action_contract_binding(SKILL_ROOT, kind + "-v1")
    envelope = {"actionContractId": kind + "-v1", "actionContractSha256": digest}
    normalized = normalize_action_result(envelope, raw_first, skill_root=SKILL_ROOT)
    assert normalized == normalize_action_result(envelope, raw_second, skill_root=SKILL_ROOT)
    if kind == "SOURCE_SCAN":
        changed = copy.deepcopy(first)
        changed[0]["facts"][0]["qualifiers"].reverse()
        assert normalized != normalize_action_result(envelope, canonical_json_bytes(changed), skill_root=SKILL_ROOT)


@pytest.mark.unit
def test_story_ac_action_contract_normalizes_sets_without_rewriting_text():
    from contracts import action_contract_binding, normalize_action_result
    from ir_samples import story_ac_ir
    contract, digest = action_contract_binding(SKILL_ROOT, "STORY_AC-v1")
    assert contract["resultSchema"]["path"] == "contracts/story-ac-decision.schema.json"
    envelope = {"actionContractId": "STORY_AC-v1", "actionContractSha256": digest}
    first = story_ac_ir()
    second = copy.deepcopy(first)
    for field in ("scopeDecisionKeys", "sourceFactIds", "acceptanceCriteria"):
        second["stories"][0][field].reverse()
    first_raw, second_raw = canonical_json_bytes(first), canonical_json_bytes(second)
    assert first_raw != second_raw
    normalized = normalize_action_result(envelope, first_raw, skill_root=SKILL_ROOT)
    assert normalized == normalize_action_result(envelope, second_raw, skill_root=SKILL_ROOT)
    second["stories"][0]["deliverableOutcome"] += "  e\u0301"
    changed = normalize_action_result(envelope, canonical_json_bytes(second), skill_root=SKILL_ROOT)
    assert changed != normalized
    assert json.loads(changed)["stories"][0]["deliverableOutcome"].endswith("  e\u0301")
