from __future__ import annotations

TEST_LAYER = "integration"

import copy
import json
import shutil
import sys
from pathlib import Path

import pytest


SKILL_ROOT = Path(__file__).parents[1]
PLUGIN_ROOT = SKILL_ROOT.parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
FIXTURES = SKILL_ROOT / "fixtures"
TESTS = SKILL_ROOT / "tests"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from contracts import canonical_json_bytes, sha256_bytes  # noqa: E402
import orchestrator as orchestrator_module  # noqa: E402
from models import Diagnostic, RenderedPackage, WorkbookAudit  # noqa: E402
from package_renderer import PackageRenderError  # noqa: E402
from runtime.project_io import ProjectFiles, ProjectIOError  # noqa: E402


@pytest.mark.unit
def test_no_cross_run_reuse_has_no_legacy_route_api():
    import inspect
    import models
    for name in ("plan_route", "_generation_route_materials", "_route_context_for_revision",
                 "_valid_generation_proof_closure", "_input_revision_by_sha256"):
        assert not hasattr(orchestrator_module, name), name
    assert not hasattr(models, "RouteDecision")
    assert "lowestRecoveryStage" not in inspect.getsource(orchestrator_module.prepare_artifact)


def test_fresh_run_independence_no_cross_run_reuse_with_deleted_or_corrupt_history(tmp_path, monkeypatch):
    request = write_run_store_request(tmp_path)
    budget = write_budget_policy(tmp_path)
    plans = []
    run_ids = set()
    protected = set()
    original_read = Path.read_bytes
    original_open = Path.open

    def guard(path):
        relative = path.relative_to(tmp_path).as_posix() if path.is_relative_to(tmp_path) else ""
        assert relative not in protected and not any(relative.startswith(root + "/") for root in protected), relative

    def guarded_read(path):
        guard(path)
        return original_read(path)

    def guarded_open(path, *args, **kwargs):
        guard(path)
        return original_open(path, *args, **kwargs)

    for history in ("present", "corrupt", "deleted"):
        if history == "present":
            write_json(tmp_path / ".ai-sow/current.json", {"generationManifestPath": ".ai-sow/generations/old/manifest.json"})
            write_json(tmp_path / ".ai-sow/generations/old/manifest.json", {"publicationComplete": True})
        elif history == "corrupt":
            for path in (tmp_path / ".ai-sow/work/runs").rglob("*.json"):
                path.write_bytes(b"corrupt hidden work")
            (tmp_path / ".ai-sow/current.json").write_bytes(b"corrupt current")
            (tmp_path / ".ai-sow/generations/old/manifest.json").write_bytes(b"corrupt generation")
        else:
            shutil.rmtree(tmp_path / ".ai-sow/generations")
            shutil.rmtree(tmp_path / ".ai-sow/work/runs")
            (tmp_path / ".ai-sow/current.json").unlink()
        protected |= {".ai-sow/current.json", ".ai-sow/generations"}
        with monkeypatch.context() as guarded:
            guarded.setattr(Path, "read_bytes", guarded_read)
            guarded.setattr(Path, "open", guarded_open)
            started = orchestrator_module.run_mode(tmp_path, "start", request=request, budget_policy=budget)
            assert started["outcome"] == "ACTIVE", started
            state = started["state"]
            assert state["route"] == "FULL_COMPILE"
            assert state["checkpointRefs"] == []
            assert state["runId"] not in run_ids
            root = tmp_path / ".ai-sow/work/runs" / state["runId"]
            plans.append(next((root / "stages/SCOPE/plans").glob("*.json")).read_bytes())
            before = {path: path.read_bytes() for path in root.rglob("*.json")}
            assert orchestrator_module.run_mode(tmp_path, "resume")["nextAction"] == started["nextAction"]
            assert {path: path.read_bytes() for path in root.rglob("*.json")} == before
            assert orchestrator_module.abandon(tmp_path)["outcome"] == "ABANDONED"
        run_ids.add(state["runId"])
        protected.add(root.relative_to(tmp_path).as_posix())
    assert len(set(plans)) == 1, "identical explicit inputs must produce byte-identical StagePlans"


@pytest.mark.parametrize("include_prior", [False, True])
def test_explicit_brownfield_inputs_only_selected_prior_and_current_change_context(tmp_path, include_prior):
    from test_intake import write_next_request
    request_path = write_next_request(tmp_path, mode="BROWNFIELD", include_prior=include_prior)
    request = json.loads(request_path.read_bytes())
    write_json(tmp_path / ".ai-sow/current.json", {"unexpected": "must not be consulted"})
    write_json(tmp_path / ".ai-sow/work/hidden-prior.json", {"declaredChangeContext": "旧上下文", "priorSowSha256s": ["f" * 64]})
    contexts = []
    for summary in ("本期保留退款接口。", "本期扩展退款审计。"):
        request["declaredChangeContext"]["summary"] = summary
        write_json(request_path, request)
        started = orchestrator_module.run_mode(tmp_path, "start", request=request_path.name, budget_policy=write_budget_policy(tmp_path))
        assert started["outcome"] == "ACTIVE", started
        marker = active_marker(tmp_path)
        revision = json.loads((tmp_path / marker["inputRevisionPath"]).read_bytes())
        expected = sorted({source["expectedSha256"] for source in request["sources"] if source["role"] == "PRIOR_SOW"})
        assert revision["priorSowSha256s"] == expected
        assert revision["priorSowState"] == ("PROVIDED" if include_prior else "NOT_PROVIDED")
        root = tmp_path / ".ai-sow/work/runs" / started["state"]["runId"]
        plan = json.loads(next((root / "stages/SCOPE/plans").glob("*.json")).read_bytes())
        assert any(work["packetPlan"]["actionKind"].startswith("PRIOR_") for work in plan["works"]) == include_prior
        _, _, bound_contexts, _, _ = orchestrator_module._frozen_stage_inputs(ProjectFiles.open(tmp_path), started["state"], "SCOPE")
        scope_context = next(json.loads(ref.canonical_content) for ref in bound_contexts if ref.ref_id == "scope-context")
        assert scope_context.get("declaredChangeContext") == request["declaredChangeContext"]
        frozen = json.loads((tmp_path / marker["inputRevisionPath"]).with_name("request.json").read_bytes())
        assert frozen["declaredChangeContext"] == request["declaredChangeContext"]
        contexts.append(marker["inputRevisionSha256"])
        assert orchestrator_module.abandon(tmp_path)["outcome"] == "ABANDONED"
    assert contexts[0] != contexts[1]


def test_new_material_requires_new_run_and_preserves_old_audit(tmp_path):
    request = write_run_store_request(tmp_path)
    budget = write_budget_policy(tmp_path)
    first = orchestrator_module.run_mode(tmp_path, "start", request=request, budget_policy=budget)
    old_marker = active_marker(tmp_path)
    before = managed_snapshot(tmp_path)
    with pytest.raises(TypeError):
        orchestrator_module.resume(tmp_path, request_path=request)
    assert orchestrator_module.run_mode(tmp_path, "resume", request=request)["diagnostics"][0]["code"] == "CLI_ARGUMENTS_INVALID"
    assert managed_snapshot(tmp_path) == before
    assert orchestrator_module.abandon(tmp_path)["outcome"] == "ABANDONED"
    old_root = tmp_path / ".ai-sow/work/runs" / first["state"]["runId"]
    audit = {path: path.read_bytes() for path in old_root.rglob("*") if path.is_file()}
    new_request = json.loads((tmp_path / request).read_bytes())
    supplement = tmp_path / "inputs/answer.md"
    supplement.write_text("客户确认本期包含退款撤销。", encoding="utf-8")
    new_request["sources"].append({"sourceId": "answer-new", "role": "SUPPLEMENT", "path": "inputs/answer.md", "expectedSha256": sha256_bytes(supplement.read_bytes())})
    write_json(tmp_path / "new-request.json", new_request)
    second = orchestrator_module.run_mode(tmp_path, "start", request="new-request.json", budget_policy=budget)
    assert second["state"]["runId"] != first["state"]["runId"]
    assert second["state"]["currentInputRevisionSha256"] != first["state"]["currentInputRevisionSha256"]
    assert second["state"]["route"] == "FULL_COMPILE"
    marker = active_marker(tmp_path)
    revision = json.loads((tmp_path / marker["inputRevisionPath"]).read_bytes())
    assert {source["sourceId"] for source in revision["sources"]} == {source["sourceId"] for source in new_request["sources"]}
    bindings = list((tmp_path / ".ai-sow/work/runs" / second["state"]["runId"]).glob("input-*.json"))
    assert len(bindings) == 1
    assert json.loads(bindings[0].read_bytes())["inputRevisionSha256"] == marker["inputRevisionSha256"]
    assert {path: path.read_bytes() for path in audit} == audit
    assert (tmp_path / old_marker["inputRevisionPath"]).read_bytes() == before[old_marker["inputRevisionPath"]]


def test_public_stage_plan_cutover_freezes_complete_owner_dag_before_issuance(tmp_path):
    for name in ('_issue_public_specs', '_issue_action_group', '_pipeline_plans',
                 '_logical_work_id', 'advance_stage_one', 'advance_stage_two', 'advance_stage_three', 'advance_review'):
        assert not hasattr(orchestrator_module, name), name
    started = orchestrator_module.run_mode(tmp_path, "start", request=write_run_store_request(tmp_path),
        budget_policy=write_budget_policy(tmp_path, maxConcurrency=1))
    assert started["outcome"] == "ACTIVE", started
    run_root = tmp_path / ".ai-sow/work/runs" / started["state"]["runId"]
    plans = list((run_root / "stages/SCOPE/plans").glob("*.json"))
    assert len(plans) == 1, "public start must freeze the complete Scope StagePlan"
    plan = json.loads(plans[0].read_bytes())
    assert {work["packetPlan"]["actionKind"] for work in plan["works"]} == {
        "SOURCE_SCAN", "SOURCE_AUDIT", "SCOPE_SYNTHESIS"}
    assert all(len(group["requiredLogicalWorkIds"]) <= 1 for group in plan["groups"])
    action = started["nextAction"]
    work = next(work for work in plan["works"] if work["logicalWorkId"] == action["logicalWorkId"])
    assert action["groupId"] == plan["groups"][0]["groupId"]
    packet = json.loads((tmp_path / action["packetPath"]).read_bytes())
    assert [item["workItemId"] for item in packet["workItems"]] == [
        item["workItemId"] for item in work["packetPlan"]["orderedWorkItems"]]
    snapshot = {path: path.read_bytes() for path in run_root.rglob("*.json")}
    assert orchestrator_module.run_mode(tmp_path, "resume")["nextAction"] == action
    assert {path: path.read_bytes() for path in run_root.rglob("*.json")} == snapshot


def test_public_stage_plan_cutover_requires_owner_bound_preseal_validation(tmp_path):
    from models import AttemptCompletion, AttemptTiming, Usage
    action = orchestrator_module.run_mode(tmp_path, "start", request=write_run_store_request(tmp_path),
        budget_policy=write_budget_policy(tmp_path))["nextAction"]
    invalid = [{"coverageRootId": "unrelated-root", "disposition": "NO_RELEVANT_FACT", "facts": [], "noRelevantReason": "无业务范围"}]
    from contracts import validate_contract, load_schema_registry
    assert not validate_contract(invalid, 'fact-decision.schema.json', load_schema_registry(SKILL_ROOT))
    completion = AttemptCompletion(canonical_json_bytes(invalid), None, None,
        Usage("PROVIDER_REPORTED", 100, 20, 0, None), AttemptTiming("2026-09-05T00:00:00Z", "2026-09-05T00:00:01Z"))
    result = orchestrator_module.submit(tmp_path, action["actionId"], completion)
    assert result["outcome"] == "RECORDED", result
    assert result["record"]["failureKind"] == "INVALID_IR", "schema-valid unrelated roots cannot seal"
    retry = orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]
    assert retry["logicalWorkId"] == action["logicalWorkId"]
    assert retry["revision"] == 2


def scope_review_action(project, *, request_path=None):
    from test_scope_compiler import scope_owner_result
    from models import AttemptCompletion, AttemptTiming, Usage
    response = orchestrator_module.run_mode(project, "start", request=request_path or write_run_store_request(project),
        budget_policy=write_budget_policy(project))
    for _ in range(60):
        assert response['outcome'] == 'ACTIVE', response
        next_action = response['nextAction']
        actions = next_action.get('actions', [next_action])
        if any(action['actionContractId'] == 'SOURCE_SCOPE-v1' for action in actions):
            assert len(actions) == 1
            return actions[0]
        for action in actions:
            packet = json.loads((project/action['packetPath']).read_bytes())
            result = scope_owner_result(action['actionContractId'][:-3], packet)
            recorded = orchestrator_module.submit(project, action['actionId'], AttemptCompletion(
                canonical_json_bytes(result), None, None, Usage('PROVIDER_REPORTED',100,20,0,None),
                AttemptTiming('2026-09-05T00:00:00Z','2026-09-05T00:00:01Z')))
            assert recorded['outcome'] == 'RECORDED' and recorded['record']['outcome'] == 'SUCCEEDED', recorded
        response = orchestrator_module.run_mode(project, 'resume')
    pytest.fail('Scope did not reach its fresh Review')


def test_explicit_brownfield_inputs_fresh_review_binds_each_current_declaration(tmp_path):
    from test_intake import write_next_request
    statements = ("本期排除退款能力。", "本期包含退款能力。")
    for index, summary in enumerate(statements):
        request = write_next_request(tmp_path, mode="BROWNFIELD")
        value = json.loads(request.read_bytes())
        value["declaredChangeContext"] = {"status": "CHANGES_RECORDED", "summary": summary, "supplementalSourceIds": []}
        write_json(request, value)
        action = scope_review_action(tmp_path, request_path=request.name)
        body = prototype_payload(tmp_path, action)
        obligations = [row for row in body["reviewObligations"] if row["kind"] == "DECLARED_CHANGE_CONTEXT"]
        assert obligations == [{"kind": "DECLARED_CHANGE_CONTEXT", "inputRevisionSha256": action["inputRevisionSha256"],
            "declaredChangeContext": value["declaredChangeContext"]}]
        assert statements[1-index] not in json.dumps(body, ensure_ascii=False)
        if index == 0:
            # The semantic reviewer rejects the candidate's included refund scope.
            key = next(key for key, row in body["ownerIndex"].items() if row["path"].startswith("/features/"))
            review = {"decision": "INPUT_REQUIRED", "findings": [{"code": "CHANGE_CONTEXT_CONFLICT", "path": "/features",
                "subjectIds": [key], "evidenceIds": [], "message": "候选退款能力与本期排除声明冲突。"}]}
        else:
            review = {"decision": "PASS", "findings": []}
        assert submit_prototype(tmp_path, action, review)["record"]["outcome"] == "SUCCEEDED"
        result = orchestrator_module.run_mode(tmp_path, "resume")
        assert result["outcome"] == ("WAITING_INPUT" if index == 0 else "ACTIVE"), result
        assert len(result["state"]["checkpointRefs"]) == index
        assert orchestrator_module.abandon(tmp_path)["outcome"] == "ABANDONED"


@pytest.mark.parametrize("tamper", ["omitted", "changed"])
def test_explicit_brownfield_inputs_review_declaration_restored_from_frozen_context(tmp_path, monkeypatch, tamper):
    from test_intake import write_next_request
    request = write_next_request(tmp_path, mode="BROWNFIELD")
    def stop(*args, **kwargs):
        raise OSError("stop before fresh Review issuance")
    response = orchestrator_module.run_mode(tmp_path, "start", request=request.name, budget_policy=write_budget_policy(tmp_path))
    from test_scope_compiler import scope_owner_result
    with monkeypatch.context() as fault:
        fault.setattr(orchestrator_module, "_issue_control", stop)
        for _ in range(12):
            if response["outcome"] != "ACTIVE": break
            for action in response["nextAction"].get("actions", [response["nextAction"]]):
                packet = json.loads((tmp_path/action["packetPath"]).read_bytes())
                submit_prototype(tmp_path, action, scope_owner_result(action["actionContractId"][:-3], packet))
            response = orchestrator_module.run_mode(tmp_path, "resume")
    assert response["outcome"] == "BLOCKED", response
    root = tmp_path / ".ai-sow/work/runs" / active_marker(tmp_path)["runId"]
    path = next((root / "stages/SCOPE/review-inputs/1").glob("*.json"))
    value = json.loads(path.read_bytes())
    obligations = value["workItems"][0]["payload"]["reviewObligations"]
    assert any(row["kind"] == "DECLARED_CHANGE_CONTEXT" for row in obligations)
    if tamper == "omitted":
        obligations[:] = [row for row in obligations if row["kind"] != "DECLARED_CHANGE_CONTEXT"]
    else:
        next(row for row in obligations if row["kind"] == "DECLARED_CHANGE_CONTEXT")["declaredChangeContext"]["summary"] = "伪造本期范围声明。"
    raw = canonical_json_bytes(value)
    path.unlink()
    (path.parent / (sha256_bytes(raw) + ".json")).write_bytes(raw)
    for event_path in (root / "events").glob("*.json"):
        event = json.loads(event_path.read_bytes())
        if event["type"] == "DETERMINISTIC_STEP_FINISHED" and event["payload"]["stepKind"] == "MATERIALIZE":
            event["payload"]["outputSha256"] = sha256_bytes(raw)
            write_json(event_path, event)
    before = managed_snapshot(tmp_path)
    result = orchestrator_module.run_mode(tmp_path, "resume")
    assert result["outcome"] == "BLOCKED", result
    assert managed_snapshot(tmp_path) == before


def test_fresh_control_review_hydrate_uses_original_source_and_exact_request(tmp_path):
    action = scope_review_action(tmp_path)
    body = prototype_payload(tmp_path, action)
    evidence_id = body['evidenceIds'][0]
    before = orchestrator_module.read_provider_request(tmp_path, action['actionId'])
    response = orchestrator_module.hydrate(tmp_path, action['actionId'], [evidence_id])
    assert response['outcome'] == 'HYDRATED', response
    evidence = response['evidence'][0]
    assert set(evidence) == {'refId', 'canonicalContent', 'contentSha256'}
    assert evidence['refId'] == evidence_id
    content = evidence['canonicalContent']
    assert content['sourceRef']['blockId'] == evidence_id
    assert sha256_bytes(content['content'].encode()) == content['sourceRef']['sha256']
    assert sha256_bytes(canonical_json_bytes(content)) == evidence['contentSha256']
    request = json.loads(orchestrator_module.read_provider_request(tmp_path, action['actionId']))
    assert request['messages'][:2] == json.loads(before)['messages']
    assert json.loads(request['messages'][2]['content']) == response
    snapshot = managed_snapshot(tmp_path)
    assert orchestrator_module.hydrate(tmp_path, action['actionId'], [evidence_id])['outcome'] == 'REUSED'
    assert orchestrator_module.hydrate(tmp_path, action['actionId'], ['unknown'])['diagnostics'][0]['code'] == 'ACTION_EVIDENCE_NOT_ALLOWED'
    assert managed_snapshot(tmp_path) == snapshot


@pytest.mark.parametrize('reserve', [1, 12000])
def test_public_task_rule_hydration_uses_frozen_catalog_and_capacity(tmp_path, reserve):
    from stage_driver import stage_result
    response = orchestrator_module.run_mode(tmp_path, 'start', request=write_run_store_request(tmp_path),
        budget_policy=write_budget_policy(tmp_path, hydrateReserveTokens=reserve))
    for _ in range(30):
        assert response['outcome'] == 'ACTIVE', response
        actions = response['nextAction'].get('actions', [response['nextAction']])
        if actions[0]['actionContractId'] == 'TASK-v1': break
        for action in actions:
            submit_prototype(tmp_path, action, stage_result(action['actionContractId'][:-3],
                json.loads((tmp_path/action['packetPath']).read_bytes())))
        response = orchestrator_module.run_mode(tmp_path, 'resume')
    else: pytest.fail('Task action was not issued')
    action = actions[0]
    result = orchestrator_module.hydrate(tmp_path, action['actionId'], ['task-rule:ENG-PIPELINE'])
    assert result['outcome'] == ('HYDRATED' if reserve == 12000 else 'BLOCKED'), result
    if reserve == 1:
        assert result['diagnostics'][0]['code'] == 'ACTION_HYDRATION_LIMIT_EXCEEDED'
        assert not list((tmp_path/Path(action['packetPath']).parent/'hydrations').glob('*.json'))
    else:
        content = result['evidence'][0]['canonicalContent']
        assert content['kind'] == 'TASK_RULES'
        assert content['rows'][0]['workTypeId'] == 'ENG-PIPELINE'
        assert len(content['rows']) > 1
        assert all('baseDays' not in row for row in content['rows'])


def test_public_task_review_includes_exact_selected_template_rules(tmp_path):
    from stage_driver import stage_result
    from task_standard_catalog import catalog, decision_catalog
    response = orchestrator_module.run_mode(tmp_path, 'start', request=write_run_store_request(tmp_path),
        budget_policy=write_budget_policy(tmp_path))
    for _ in range(30):
        assert response['outcome'] == 'ACTIVE', response
        actions = response['nextAction'].get('actions', [response['nextAction']])
        if actions[0]['actionContractId'] == 'TASK_ESTIMATION-v1': break
        for action in actions:
            submit_prototype(tmp_path, action, stage_result(action['actionContractId'][:-3],
                json.loads((tmp_path/action['packetPath']).read_bytes())))
        response = orchestrator_module.run_mode(tmp_path, 'resume')
    else: pytest.fail('Task Review was not issued')
    action = actions[0]
    body = prototype_payload(tmp_path, action)
    source = catalog(SKILL_ROOT/'assets/sow-template.xlsx')
    rules = {row['workTypeId']: row for row in decision_catalog(source)}
    selected = sorted({task['workTypeId'] for task in body['candidate']['tasks']})
    assert body['taskRules']['rows'] == [rules[key] for key in selected]
    assert body['taskRules']['templateSha256'] == body['candidate']['project']['templateSha256']
    assert 'authorHistory' not in body
    submit_prototype(tmp_path, action, {'decision': 'PASS', 'findings': []})
    resumed = orchestrator_module.run_mode(tmp_path, 'resume')
    assert resumed['outcome'] == 'ACTIVE' and resumed['state']['phase'] == 'DRAFT', resumed
    checkpoint = json.loads(next((tmp_path/'.ai-sow/work/runs'/action['runId']/'stages/TASK/checkpoints').glob('*.json')).read_bytes())
    assert checkpoint['reviewPacketSha256'] == action['packetSha256']


def test_stage_seal_order_public_scope_validation_precedes_fresh_review_and_no_stage_approval(tmp_path):
    action = scope_review_action(tmp_path)
    root = tmp_path/'.ai-sow/work/runs'/action['runId']
    packet = json.loads((tmp_path/action['packetPath']).read_bytes())
    body = packet['workItems'][0]['payload']
    assert body['candidateSha256'] == action['baseCandidateSha256']
    assert body['ownerIndex'] and body['candidate']
    assert not {'authorHistory','sealedIR','rawOutput'} & body.keys()
    assert not list((root/'checkpoints').glob('*.json'))
    events = [json.loads(path.read_bytes()) for path in sorted((root/'events').glob('*.json'))]
    assert [event['payload']['stepKind'] for event in events if event['type']=='DETERMINISTIC_STEP_FINISHED'] == ['MATERIALIZE','VALIDATE']
    submit_prototype(tmp_path, action, {'decision':'PASS','findings':[]})
    response = orchestrator_module.run_mode(tmp_path,'resume')
    assert response['outcome']=='ACTIVE', response
    actions = response['nextAction'].get('actions',[response['nextAction']])
    assert all(item['actionContractId']=='STORY_AC-v1' for item in actions)
    checkpoints = list((root/'stages/SCOPE/checkpoints').glob('*.json'))
    assert len(checkpoints)==1
    checkpoint=json.loads(checkpoints[0].read_bytes())
    assert checkpoint['reviewPacketSha256']==action['packetSha256']
    assert 'priorStateSha256' not in checkpoint


@pytest.mark.parametrize('target', ['plan','candidate','validator','review-input','attempt'])
def test_checkpoint_deep_binding_public_resume_rejects_changed_stage_proof(tmp_path,target):
    action=scope_review_action(tmp_path)
    submit_prototype(tmp_path,action,{'decision':'PASS','findings':[]})
    started=orchestrator_module.run_mode(tmp_path,'resume')
    assert started['outcome']=='ACTIVE',started
    root=tmp_path/'.ai-sow/work/runs'/action['runId']
    patterns={'plan':'stages/SCOPE/plans/*.json','candidate':'stages/SCOPE/candidates/*.json',
        'validator':'stages/SCOPE/validators/1/*.json','review-input':'stages/SCOPE/review-inputs/1/*.json',
        'attempt':'actions/*/record.json'}
    path=next(root.glob(patterns[target]));value=json.loads(path.read_bytes())
    if target=='plan': value['groups'].reverse()
    elif target=='candidate': value['features'][0]['name']='被篡改'
    elif target=='validator': value['diagnostics']=['forged']
    elif target=='review-input': value['workItems'][0]['payload']['ownerIndex']={}
    else: value['usage']['inputTokens']+=1
    path.write_bytes(canonical_json_bytes(value))
    before={p:p.read_bytes() for p in root.rglob('*.json')}
    resumed=orchestrator_module.run_mode(tmp_path,'resume')
    assert resumed['outcome']!='ACTIVE',resumed
    assert resumed.get('nextAction') is None
    assert {p:p.read_bytes() for p in root.rglob('*.json')}==before


def test_bounded_semantic_repair_public_immutable_candidate_and_fresh_pass(tmp_path):
    action=scope_review_action(tmp_path)
    body=prototype_payload(tmp_path,action)
    key=next(key for key,row in body['ownerIndex'].items() if row['path'].startswith('/features/'))
    review={'decision':'REPAIRABLE_SEMANTIC','findings':[{'code':'BOUNDARY','path':body['ownerIndex'][key]['path'],
        'subjectIds':[key],'evidenceIds':body['evidenceIds'][:1],'message':'能力名称需点明交付结果。'}]}
    submit_prototype(tmp_path,action,review)
    repair=orchestrator_module.run_mode(tmp_path,'resume')['nextAction']
    assert repair['actionContractId']=='SCOPE_REPAIR-v1'
    payload=prototype_payload(tmp_path,repair)
    row=copy.deepcopy(next(row for row in payload['ownerIR']['decisions'] if row['localKey']==key))
    row['boundaryEvidence']['name']='已明确的订单查询能力'
    submit_prototype(tmp_path,repair,{'decisions':[row]})
    fresh=orchestrator_module.run_mode(tmp_path,'resume')['nextAction']
    assert fresh['actionContractId']=='SOURCE_SCOPE-v1' and fresh['logicalWorkId']!=action['logicalWorkId']
    assert fresh['baseCandidateSha256']!=action['baseCandidateSha256']
    submit_prototype(tmp_path,fresh,{'decision':'PASS','findings':[]})
    passed=orchestrator_module.run_mode(tmp_path,'resume')
    assert passed['outcome']=='ACTIVE',passed
    root=tmp_path/'.ai-sow/work/runs'/action['runId']/'stages/SCOPE'
    assert len(list((root/'candidates').glob('*.json')))==2
    checkpoint=json.loads(next((root/'checkpoints').glob('*.json')).read_bytes())
    assert checkpoint['reviewPacketSha256']==fresh['packetSha256']


def test_fresh_control_review_input_required_keeps_scope_unsealed(tmp_path):
    action=scope_review_action(tmp_path);body=prototype_payload(tmp_path,action)
    submit_prototype(tmp_path,action,{'decision':'INPUT_REQUIRED','findings':[{'code':'SOURCE_EQUIVALENCE',
        'path':'/sourceRelations','subjectIds':['source-prior'],'evidenceIds':body['evidenceIds'][:1],
        'message':'部分重合不足以证明完整 DUPLICATE，需确认来源适用范围。'}]})
    result=orchestrator_module.run_mode(tmp_path,'resume')
    assert result['outcome']=='WAITING_INPUT' and result['nextAction'] is None
    assert not list((tmp_path/'.ai-sow/work/runs'/action['runId']/'stages/SCOPE/checkpoints').glob('*.json'))
    assert orchestrator_module.run_mode(tmp_path,'resume')['outcome']=='WAITING_INPUT'


def test_public_stage_plan_cutover_actual_dependency_capacity_waits_without_replanning(tmp_path):
    from stage_driver import stage_result
    response = orchestrator_module.run_mode(tmp_path, 'start', request=write_run_store_request(tmp_path),
        budget_policy=write_budget_policy(tmp_path, modelContextLimitTokens=20000,
            outputReserveTokens=2000, hydrateReserveTokens=1000, safetyMarginTokens=1000))
    assert response['outcome'] == 'ACTIVE', response
    action = response['nextAction']
    packet = json.loads((tmp_path/action['packetPath']).read_bytes())
    output = stage_result('SOURCE_SCAN', packet)
    output[0]['facts'][0]['statement'] += ' 来源中需要保留的详细条件。' * 2000
    root = tmp_path/'.ai-sow/work/runs'/action['runId']
    plan_path = next((root/'stages/SCOPE/plans').glob('*.json'))
    plan = plan_path.read_bytes()
    recorded = submit_prototype(tmp_path, action, output)
    assert recorded['record']['outcome'] == 'SUCCEEDED', recorded
    response = orchestrator_module.run_mode(tmp_path, 'resume')
    assert response['outcome'] == 'WAITING_INPUT', response
    assert response['diagnostics'][0]['code'] == 'BUDGET_EXHAUSTED'
    assert response['nextAction'] is None
    assert len(list((root/'actions').glob('*/envelope.json'))) == 1
    assert plan_path.read_bytes() == plan
    assert len(list(plan_path.parent.glob('*.json'))) == 1
    assert orchestrator_module.run_mode(tmp_path, 'resume')['outcome'] == 'WAITING_INPUT'


def test_public_stage_plan_cutover_whole_batch_budget_preflight_and_replacement(tmp_path):
    def prepare(project, maximum):
        project.mkdir()
        request_path = write_run_store_request(project)
        request = json.loads((project/request_path).read_bytes())
        source = project/request['sources'][0]['path']
        source.write_text('\n\n'.join('边界'+str(i)+' '+' '.join('field'+str(n) for n in range(4000)) for i in range(3)))
        request['sources'][0]['expectedSha256'] = sha256_bytes(source.read_bytes())
        write_json(project/request_path, request)
        budget = write_budget_policy(project, maxPlannedTokens=maximum, maxConcurrency=2,
            modelContextLimitTokens=60000, outputReserveTokens=2000, hydrateReserveTokens=1000,
            safetyMarginTokens=1000, referenceOverheadTokens=256)
        return orchestrator_module.run_mode(project, 'start', request=request_path, budget_policy=budget)
    probe = prepare(tmp_path/'probe', 1000000)
    group = probe['nextAction']['actions']
    assert len(group) == 2
    total = sum(sum(row['executionLimits'].values()) for row in group)
    project = tmp_path/'bounded'
    waiting = prepare(project, total-1)
    assert waiting['outcome'] == 'WAITING_INPUT', waiting
    root = project/'.ai-sow/work/runs'/waiting['state']['runId']
    assert not list((root/'actions').glob('*/envelope.json'))
    plan_path = next((root/'stages/SCOPE/plans').glob('*.json'))
    plan = plan_path.read_bytes()
    policy = json.loads((project/'budget.json').read_bytes())
    write_json(project/'budget.json', {**policy, 'maxPlannedTokens': 1000000})
    resumed = orchestrator_module.run_mode(project, 'resume', budget_policy='budget.json')
    assert resumed['outcome'] == 'ACTIVE', resumed
    assert len(resumed['nextAction']['actions']) == 2
    assert plan_path.read_bytes() == plan
    events = [json.loads(path.read_bytes()) for path in (root/'events').glob('*.json')]
    assert sum(row['type'] == 'ACTION_ISSUED' for row in events) == 2


def test_fresh_control_review_invalid_root_retry_binds_actual_overlay_and_stops_second_repair(tmp_path):
    action = scope_review_action(tmp_path)
    body = prototype_payload(tmp_path, action)
    review = {'decision': 'REPAIRABLE_SEMANTIC', 'findings': [{'code': 'BOUNDARY', 'path': '/features',
        'subjectIds': ['unrelated-root'], 'evidenceIds': [], 'message': '需纠正能力边界。'}]}
    recorded = submit_prototype(tmp_path, action, review)
    assert recorded['record']['failureKind'] == 'INVALID_IR'
    retry = orchestrator_module.run_mode(tmp_path, 'resume')['nextAction']
    assert retry['revision'] == 2 and retry['logicalWorkId'] == action['logicalWorkId']
    assert retry['packetSha256'] != action['packetSha256']
    submit_prototype(tmp_path, retry, {'decision': 'PASS', 'findings': []})
    passed = orchestrator_module.run_mode(tmp_path, 'resume')
    assert passed['outcome'] == 'ACTIVE', passed
    checkpoint = json.loads(next((tmp_path/'.ai-sow/work/runs'/action['runId']/'stages/SCOPE/checkpoints').glob('*.json')).read_bytes())
    assert checkpoint['reviewPacketSha256'] == retry['packetSha256']
    assert orchestrator_module.run_mode(tmp_path, 'resume')['outcome'] == 'ACTIVE'


def test_bounded_semantic_repair_public_second_finding_does_not_close_original(tmp_path):
    action = scope_review_action(tmp_path)
    body = prototype_payload(tmp_path, action)
    key = next(key for key, row in body['ownerIndex'].items() if row['path'].startswith('/features/'))
    review = {'decision': 'REPAIRABLE_SEMANTIC', 'findings': [{'code': 'BOUNDARY', 'path': '/features',
        'subjectIds': [key], 'evidenceIds': [], 'message': '需纠正能力边界。'}]}
    submit_prototype(tmp_path, action, review)
    repair = orchestrator_module.run_mode(tmp_path, 'resume')['nextAction']
    owner_ir = prototype_payload(tmp_path, repair)['ownerIR']
    row = copy.deepcopy(next(row for row in owner_ir['decisions'] if row['localKey'] == key))
    row['boundaryEvidence']['name'] = '已修正的交付能力'
    submit_prototype(tmp_path, repair, {'decisions': [row]})
    second = orchestrator_module.run_mode(tmp_path, 'resume')['nextAction']
    submit_prototype(tmp_path, second, review)
    stopped = orchestrator_module.run_mode(tmp_path, 'resume')
    assert stopped['state']['result'] == 'MANUAL_REVIEW_REQUIRED', stopped
    root = tmp_path/'.ai-sow/work/runs'/action['runId']
    assert not list((root/'stages/SCOPE/checkpoints').glob('*.json'))
    envelopes = [json.loads(path.read_bytes()) for path in (root/'actions').glob('*/envelope.json')]
    assert sum(row['actionContractId'] == 'SCOPE_REPAIR-v1' for row in envelopes) == 1


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def write_budget_policy(project: Path, **changes) -> str:
    from test_contracts import valid_run_budget_policy

    write_json(project / "budget.json", {**valid_run_budget_policy(), **changes})
    return "budget.json"


def start_demo(project, *, two_controls=False, second_page=False, rounds=2, steps=30, screenshots=12):
    from test_intake import write_next_request
    request = write_next_request(project, include_demos=True)
    if two_controls:
        value = json.loads(request.read_bytes())
        source = project / value["demo"]["entrypoint"]
        source.write_bytes(source.read_bytes() + b'<button id="cancel">Cancel</button>')
        value["demo"]["files"][0]["expectedSha256"] = sha256_bytes(source.read_bytes())
        request.write_bytes(canonical_json_bytes(value))
    if second_page:
        value = json.loads(request.read_bytes())
        page = project / "inputs/z-other.html"
        page.write_bytes(b'<button id="refund">Refund</button>')
        value["demo"]["files"].append({"sourceId": "other-page", "role": "DEMO", "path": "inputs/z-other.html", "expectedSha256": sha256_bytes(page.read_bytes())})
        request.write_bytes(canonical_json_bytes(value))
    return orchestrator_module.run_mode(project, "start", request=request.name, budget_policy=write_budget_policy(project, demoLimits={"maxDiscoveryRounds": rounds, "maxScenarioSteps": steps, "maxScreenshots": screenshots}))


def prototype_payload(project, action):
    return json.loads((project / action["packetPath"]).read_bytes())["workItems"][0]["payload"]


def submit_prototype(project, action, result, failure=None):
    from models import AttemptCompletion, AttemptDiagnostic, AttemptTiming, Usage
    browser = action["actionContractId"] == "PROTOTYPE_BROWSER-v1"
    completion = AttemptCompletion(None if failure else canonical_json_bytes(result), failure,
        AttemptDiagnostic("HOST_EXECUTION_FAILED", "", ()) if failure else None,
        Usage("PROVIDER_REPORTED", 0 if browser else 100, 0 if browser else 20, 0, None),
        AttemptTiming("2026-09-05T00:00:00Z", "2026-09-05T00:00:01Z"))
    recorded = orchestrator_module.submit(project, action["actionId"], completion)
    assert recorded["outcome"] == "RECORDED", recorded
    return recorded


def test_prototype_native_fill_public_chain_seals_source_and_runtime_evidence(tmp_path):
    from test_intake import write_next_request
    from test_prototype_analysis import scenario_fixture, trace_fixture, observation_fixture
    request_path = write_next_request(tmp_path, include_demos=True)
    request = json.loads(request_path.read_bytes())
    source = tmp_path / request["demo"]["entrypoint"]
    source.write_bytes(b'<label for="name">Name</label><input id="name">')
    request["demo"]["files"][0]["expectedSha256"] = sha256_bytes(source.read_bytes())
    write_json(request_path, request)
    action = orchestrator_module.run_mode(tmp_path, "start", request=request_path.name, budget_policy=write_budget_policy(tmp_path))["nextAction"]
    inventory = prototype_payload(tmp_path, action)["inventory"]
    scenario = scenario_fixture(inventory)
    scenario["scenarios"][0]["steps"][0].update(operation="fill", value="Saved", assertions=[{"selector": "#name", "attribute": "value", "expected": "Saved"}])
    assert submit_prototype(tmp_path, action, scenario)["record"]["outcome"] == "SUCCEEDED"
    browser = orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]
    assert submit_prototype(tmp_path, browser, trace_fixture(inventory, scenario))["record"]["outcome"] == "SUCCEEDED"
    analyze = orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]
    observation = observation_fixture(inventory)
    observation["behavior"].update(trigger="输入名称", resultingState="名称值已更新")
    assert submit_prototype(tmp_path, analyze, {"observations": [observation]})["record"]["outcome"] == "SUCCEEDED"
    assert orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]["actionContractId"] == "SOURCE_SCAN-v1"


@pytest.mark.parametrize("case", ["scenario-selector", "scenario-page", "trace-page", "observation-page", "missing-event"])
def test_prototype_actual_target_binding_public_classification(tmp_path, case):
    from test_prototype_analysis import scenario_fixture, trace_fixture, observation_fixture
    action = start_demo(tmp_path, two_controls=True, second_page=True)["nextAction"]
    inventory = prototype_payload(tmp_path, action)["inventory"]
    scenario = scenario_fixture(inventory)
    other_page = next(page for page in inventory["routes"] if page.endswith("other.html"))
    if case.startswith("scenario"):
        result = copy.deepcopy(scenario)
        result["scenarios"][0]["steps"][0]["selector" if case == "scenario-selector" else "page"] = "#cancel" if case == "scenario-selector" else other_page
    else:
        submit_prototype(tmp_path, action, scenario)
        action = orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]
        result = trace_fixture(inventory, scenario)
        if case == "trace-page":
            result["runs"][0]["steps"][0]["page"] = other_page
        elif case == "missing-event":
            result["runs"][0]["steps"][0]["eventObserved"] = False
            assert submit_prototype(tmp_path, action, result)["record"]["outcome"] == "SUCCEEDED"
            action = orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]
            broken = observation_fixture(inventory)
            broken["runtimeStatus"] = "BROKEN"
            assert submit_prototype(tmp_path, action, {"observations": [broken]})["record"]["outcome"] == "SUCCEEDED"
            waiting = orchestrator_module.run_mode(tmp_path, "resume")
            assert waiting["outcome"] == "WAITING_INPUT"
            assert waiting["nextAction"] is None
            return
        else:
            submit_prototype(tmp_path, action, result)
            action = orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]
            observation = observation_fixture(inventory)
            observation["behavior"]["page"] = other_page
            result = {"observations": [observation]}
    recorded = submit_prototype(tmp_path, action, result)["record"]
    assert recorded["outcome"] == "FAILED"
    assert recorded["failureKind"] == ("SYSTEM" if case == "trace-page" else "INVALID_IR")
    assert recorded["normalizedResultSha256"] is None
    assert recorded["rawSha256"] == sha256_bytes(canonical_json_bytes(result))
    resumed = orchestrator_module.run_mode(tmp_path, "resume")
    if case == "trace-page":
        assert resumed["outcome"] == "SYSTEM_FAILED"
        assert resumed["nextAction"] is None
    else:
        assert resumed["nextAction"]["revision"] == 2
        assert resumed["nextAction"]["logicalWorkId"] == action["logicalWorkId"]


@pytest.mark.parametrize("case", ["unknown-interaction", "wrong-bundle", "wrong-round", "unknown-evidence", "broken-then-invalid"])
def test_prototype_model_invalid_binding_uses_existing_ir_repair(tmp_path, case):
    from test_prototype_analysis import scenario_fixture, trace_fixture, observation_fixture
    action = start_demo(tmp_path)["nextAction"]
    inventory = prototype_payload(tmp_path, action)["inventory"]
    valid = scenario_fixture(inventory)
    if case in {"unknown-evidence", "broken-then-invalid"}:
        submit_prototype(tmp_path, action, valid)
        browser = orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]
        submit_prototype(tmp_path, browser, trace_fixture(inventory, valid))
        action = orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]
        valid = {"observations": [observation_fixture(inventory, "save")]}
    invalid = copy.deepcopy(valid)
    if case == "unknown-interaction":
        invalid["scenarios"][0]["steps"][0]["interactionId"] = "interaction-unknown"
    elif case == "wrong-bundle":
        invalid["bundleSha256"] = "f" * 64
    elif case == "wrong-round":
        invalid["round"] = 2
    else:
        invalid["observations"][0]["evidenceIds"] = ["source-unknown"]
        if case == "broken-then-invalid":
            broken = observation_fixture(inventory, "a-broken")
            broken["runtimeStatus"] = "BROKEN"
            invalid["observations"].insert(0, broken)
    recorded = submit_prototype(tmp_path, action, invalid)
    assert recorded["record"]["failureKind"] == "INVALID_IR"
    assert recorded["record"]["normalizedResultSha256"] is None
    assert (tmp_path / action["packetPath"]).is_file()
    repaired = orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]
    assert (repaired["revision"], repaired["attempt"]) == (2, 1)
    assert repaired["logicalWorkId"] == action["logicalWorkId"]
    assert submit_prototype(tmp_path, repaired, valid)["record"]["outcome"] == "SUCCEEDED"
    assert orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]["actionContractId"] == ("SOURCE_SCAN-v1" if case in {"unknown-evidence", "broken-then-invalid"} else "PROTOTYPE_BROWSER-v1")


def test_prototype_scenario_frozen_limits_survive_replacement_and_repair(tmp_path):
    from test_prototype_analysis import scenario_fixture
    from contracts import estimate_action_input_tokens
    action = start_demo(tmp_path, steps=1)["nextAction"]
    payload = prototype_payload(tmp_path, action)
    limits = {"maxDiscoveryRounds": 2, "maxScenarioSteps": 1, "maxScreenshots": 12}
    assert payload["demoLimits"] == limits
    packet_bytes = (tmp_path / action["packetPath"]).read_bytes()
    request_bytes = orchestrator_module.read_provider_request(tmp_path, action["actionId"])
    policy = json.loads((tmp_path / "budget.json").read_bytes())
    assert action["executionLimits"]["estimatedInputTokens"] == estimate_action_input_tokens(SKILL_ROOT, action["actionContractId"], packet_bytes, budget_policy=policy, max_output_tokens=action["executionLimits"]["maxOutputTokens"])
    write_budget_policy(tmp_path, demoLimits={**limits, "maxScenarioSteps": 3})
    assert orchestrator_module.resume(tmp_path, replacement_budget_policy_path="budget.json")["outcome"] == "ACTIVE"
    assert (tmp_path / action["packetPath"]).read_bytes() == packet_bytes
    assert orchestrator_module.read_provider_request(tmp_path, action["actionId"]) == request_bytes
    valid = scenario_fixture(payload["inventory"])
    submit_prototype(tmp_path, action, {**valid, "bundleSha256": "f" * 64})
    repair = orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]
    assert repair["revision"] == 2
    assert prototype_payload(tmp_path, repair) == payload
    submit_prototype(tmp_path, repair, valid)
    browser = orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]
    assert prototype_payload(tmp_path, browser)["demoLimits"] == limits


@pytest.mark.parametrize("limit", ["steps", "screenshots"])
def test_prototype_scenario_static_frozen_limit_uses_ir_repair(tmp_path, limit):
    from test_prototype_analysis import scenario_fixture
    action = start_demo(tmp_path, steps=1 if limit == "steps" else 30)["nextAction"]
    payload = prototype_payload(tmp_path, action)
    valid = scenario_fixture(payload["inventory"])
    invalid = copy.deepcopy(valid)
    count = 2 if limit == "steps" else 13
    invalid["scenarios"][0]["steps"] = [dict(valid["scenarios"][0]["steps"][0], stepId=f"step-{number}") for number in range(count)]
    replacement = {**payload["demoLimits"], "maxScenarioSteps": 40, "maxScreenshots": 20}
    write_budget_policy(tmp_path, demoLimits=replacement)
    orchestrator_module.resume(tmp_path, replacement_budget_policy_path="budget.json")
    record = submit_prototype(tmp_path, action, invalid)["record"]
    assert record["failureKind"] == "INVALID_IR"
    assert record["normalizedResultSha256"] is None
    repair = orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]
    assert (repair["revision"], repair["attempt"]) == (2, 1)
    assert prototype_payload(tmp_path, repair) == payload
    assert submit_prototype(tmp_path, repair, valid)["record"]["outcome"] == "SUCCEEDED"
    assert orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]["actionContractId"] == "PROTOTYPE_BROWSER-v1"


def test_prototype_remaining_packet_counts_unique_prior_trace_and_allows_no_screenshot(tmp_path):
    from test_prototype_analysis import scenario_fixture, trace_fixture, observation_fixture
    action = start_demo(tmp_path, two_controls=True, steps=3, screenshots=1)["nextAction"]
    inventory = prototype_payload(tmp_path, action)["inventory"]
    scenario = scenario_fixture(inventory)
    submit_prototype(tmp_path, action, scenario)
    browser = orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]
    trace = trace_fixture(inventory, scenario)
    first = submit_prototype(tmp_path, browser, trace)
    assert submit_prototype(tmp_path, browser, trace) == first
    analyze = orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]
    submit_prototype(tmp_path, analyze, {"observations": [observation_fixture(inventory, "first")]})
    second = orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]
    payload = prototype_payload(tmp_path, second)
    assert payload["demoRemaining"] == {"maxScenarioSteps": 2, "maxScreenshots": 0}
    assert orchestrator_module.run_mode(tmp_path, "resume")["nextAction"] == second
    chosen = {**inventory, "interactions": [inventory["interactions"][1]]}
    scenario = scenario_fixture(chosen, round=2)
    scenario["scenarios"][0]["steps"][0]["screenshot"] = False
    submit_prototype(tmp_path, second, scenario)
    browser = orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]
    assert prototype_payload(tmp_path, browser)["demoRemaining"] == payload["demoRemaining"]
    submit_prototype(tmp_path, browser, trace_fixture(inventory, scenario))
    analyze = orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]
    submit_prototype(tmp_path, analyze, {"observations": [observation_fixture(chosen, "second")]})
    assert orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]["actionContractId"] == "SOURCE_SCAN-v1"


@pytest.mark.parametrize("case", ["no-next-round", "replay-overflow", "screenshot-overflow"])
def test_prototype_cumulative_execution_budget_waits_without_new_work(tmp_path, case):
    from test_prototype_analysis import scenario_fixture, trace_fixture, observation_fixture
    action = start_demo(tmp_path, two_controls=True,
        steps={"no-next-round": 1, "replay-overflow": 2, "screenshot-overflow": 4}[case],
        screenshots=2 if case == "screenshot-overflow" else 12)["nextAction"]
    inventory = prototype_payload(tmp_path, action)["inventory"]
    scenario = scenario_fixture(inventory)
    submit_prototype(tmp_path, action, scenario)
    browser = orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]
    submit_prototype(tmp_path, browser, trace_fixture(inventory, scenario))
    analyze = orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]
    submit_prototype(tmp_path, analyze, {"observations": [observation_fixture(inventory, "first")]})
    result = orchestrator_module.run_mode(tmp_path, "resume")
    if case != "no-next-round":
        second = result["nextAction"]
        chosen = {**inventory, "interactions": [inventory["interactions"][1]]}
        scenario = scenario_fixture(chosen, round=2)
        submit_prototype(tmp_path, second, scenario)
        browser = orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]
        trace = trace_fixture(inventory, scenario)
        trace["runs"][0]["stable"] = False
        trace["runs"].append(copy.deepcopy(trace["runs"][0]) | {"replay": 1, "stable": True})
        assert submit_prototype(tmp_path, browser, trace)["record"]["outcome"] == "SUCCEEDED"
        result = orchestrator_module.run_mode(tmp_path, "resume")
    assert result["outcome"] == "WAITING_INPUT", result
    assert result["diagnostics"][0]["code"] == "INCOMPLETE_BUDGET"
    assert result["nextAction"] is None
    assert orchestrator_module.run_mode(tmp_path, "resume")["outcome"] == "WAITING_INPUT"


@pytest.mark.parametrize("started", [False, True])
def test_prototype_execution_unknown_counts_wait_but_prestart_failure_can_resume(tmp_path, started):
    from models import AttemptCompletion, AttemptDiagnostic, AttemptTiming, Usage
    from test_prototype_analysis import scenario_fixture, trace_fixture
    action = start_demo(tmp_path)["nextAction"]
    inventory = prototype_payload(tmp_path, action)["inventory"]
    scenario = scenario_fixture(inventory)
    submit_prototype(tmp_path, action, scenario)
    browser = orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]
    failure = AttemptCompletion(None, "EXECUTION", AttemptDiagnostic("HOST_EXECUTION_FAILED", "", ()),
        Usage("PROVIDER_REPORTED", 0, 0, 0, None),
        AttemptTiming("2026-09-05T00:00:00Z" if started else None, "2026-09-05T00:00:01Z"))
    assert orchestrator_module.submit(tmp_path, browser["actionId"], failure)["outcome"] == "RECORDED"
    retry = orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]
    assert (retry["revision"], retry["attempt"]) == (1, 2)
    successful = submit_prototype(tmp_path, retry, trace_fixture(inventory, scenario))["record"]
    assert successful["outcome"] == "SUCCEEDED"
    result = orchestrator_module.run_mode(tmp_path, "resume")
    if started:
        assert result["outcome"] == "WAITING_INPUT", result
        assert result["diagnostics"][0]["code"] == "PROTOTYPE_EXECUTION_UNMEASURED"
        write_budget_policy(tmp_path, demoLimits={"maxDiscoveryRounds": 3, "maxScenarioSteps": 60, "maxScreenshots": 24})
        orchestrator_module.resume(tmp_path, replacement_budget_policy_path="budget.json")
        assert orchestrator_module.run_mode(tmp_path, "resume")["outcome"] == "WAITING_INPUT"
    else:
        assert result["nextAction"]["actionContractId"] == "PROTOTYPE_ANALYZE-v1"


def test_prototype_scenario_control_identity(tmp_path):
    from contracts import action_contract_binding, estimate_action_input_tokens
    first = start_demo(tmp_path)
    assert first["outcome"] == "ACTIVE", first
    action = first["nextAction"]
    assert action["actionContractId"] == "PROTOTYPE_SCENARIO-v1"
    packet = json.loads((tmp_path / action["packetPath"]).read_bytes())
    payload = packet["workItems"][0]["payload"]
    identity = {"stageKind": "SCOPE", "actionKind": "PROTOTYPE_SCENARIO", "inputRevisionSha256": action["inputRevisionSha256"], "bundleSha256": payload["inventory"]["bundleSha256"], "round": 1}
    assert action["logicalWorkId"] == "logical-" + sha256_bytes(canonical_json_bytes(identity))
    assert action["revision"] == action["attempt"] == 1
    assert payload["prototypeLedger"] is None
    contract, _ = action_contract_binding(SKILL_ROOT, action["actionContractId"])
    assert (contract["executionKind"], contract["usageCategory"]) == ("MODEL_PROVIDER", "AUTHOR")
    assert orchestrator_module.read_provider_request(tmp_path, action["actionId"])
    resumed = orchestrator_module.run_mode(tmp_path, "resume")
    assert resumed["nextAction"] == action
    root = tmp_path / ".ai-sow/work/runs" / action["runId"]
    assert len(list((root / "actions").glob("*/envelope.json"))) == 1
    assert not list(root.glob("stages/SCOPE/*plan*.json"))


def test_prototype_browser_control_identity_and_system_trace_failure(tmp_path):
    from test_prototype_analysis import scenario_fixture
    from contracts import action_contract_binding
    scenario_action = start_demo(tmp_path)["nextAction"]
    payload = prototype_payload(tmp_path, scenario_action)
    scenario = scenario_fixture(payload["inventory"])
    submit_prototype(tmp_path, scenario_action, scenario)
    next_result = orchestrator_module.run_mode(tmp_path, "resume")
    assert next_result["outcome"] == "ACTIVE", next_result
    browser = next_result["nextAction"]
    assert browser["actionContractId"] == "PROTOTYPE_BROWSER-v1"
    identity = {**payload["identity"], "actionKind": "PROTOTYPE_BROWSER"}
    assert browser["logicalWorkId"] == "logical-" + sha256_bytes(canonical_json_bytes(identity))
    assert browser["executionLimits"] == {"estimatedInputTokens": 0, "maxOutputTokens": 0, "maxHydrateTokens": 0}
    contract, _ = action_contract_binding(SKILL_ROOT, browser["actionContractId"])
    assert (contract["executionKind"], contract["usageCategory"]) == ("HOST_BROWSER", "AUTHOR")
    assert prototype_payload(tmp_path, browser)["scenario"]["normalizedResult"] == scenario
    submit_prototype(tmp_path, browser, None, "EXECUTION")
    retried = orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]
    assert retried["logicalWorkId"] == browser["logicalWorkId"]
    assert (retried["revision"], retried["attempt"]) == (1, 2)
    recorded = submit_prototype(tmp_path, retried, {})
    assert recorded["record"]["failureKind"] == "SYSTEM"
    stopped = orchestrator_module.run_mode(tmp_path, "resume")
    assert stopped["outcome"] == "SYSTEM_FAILED"
    root = tmp_path / ".ai-sow/work/runs" / browser["runId"]
    assert len(list((root / "actions").glob("*/envelope.json"))) == 3


def test_prototype_analyze_scope_handoff_multiple_observation_refs(tmp_path):
    from test_prototype_analysis import scenario_fixture, trace_fixture, observation_fixture
    action = start_demo(tmp_path)["nextAction"]
    inventory = prototype_payload(tmp_path, action)["inventory"]
    scenario = scenario_fixture(inventory)
    scenario_record = submit_prototype(tmp_path, action, scenario)["record"]
    browser = orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]
    trace = trace_fixture(inventory, scenario)
    browser_record = submit_prototype(tmp_path, browser, trace)["record"]
    resumed = orchestrator_module.run_mode(tmp_path, "resume")
    assert resumed["outcome"] == "ACTIVE", resumed
    analyze = resumed["nextAction"]
    assert analyze["actionContractId"] == "PROTOTYPE_ANALYZE-v1"
    assert analyze["logicalWorkId"] == "logical-" + sha256_bytes(canonical_json_bytes({**prototype_payload(tmp_path, action)["identity"], "actionKind": "PROTOTYPE_ANALYZE"}))
    assert (analyze["revision"], analyze["attempt"]) == (1, 1)
    payload = prototype_payload(tmp_path, analyze)
    assert payload["trace"]["normalizedResult"] == trace
    result = {"observations": [observation_fixture(inventory, "save"), observation_fixture(inventory, "success") ]}
    analyze_record = submit_prototype(tmp_path, analyze, result)["record"]
    scope = orchestrator_module.run_mode(tmp_path, "resume")
    assert scope["nextAction"]["actionContractId"] == "SOURCE_SCAN-v1"
    paths = list((tmp_path / ".ai-sow/work/runs" / analyze["runId"] / "stages/SCOPE/prototype-ledgers").glob("*.json"))
    assert len(paths) == 1
    body = paths[0].read_bytes()
    assert paths[0].stem == sha256_bytes(body)
    ledger = json.loads(body)
    assert ledger["sealed"] is True
    assert [item["localKey"] for item in ledger["rounds"][0]["observationRefs"]] == ["save", "success"]
    assert "resultingState" not in body.decode()
    assert ledger["rounds"][0]["attemptRecordSha256s"] == [sha256_bytes(canonical_json_bytes(record)) for record in (scenario_record, browser_record, analyze_record)]


@pytest.mark.parametrize("rounds", [1, 2])
def test_interaction_coverage_preserves_round_one_observation_and_waits_at_limit(tmp_path, rounds):
    from test_prototype_analysis import scenario_fixture, trace_fixture, observation_fixture
    action = start_demo(tmp_path, two_controls=True, rounds=rounds)["nextAction"]
    inventory = prototype_payload(tmp_path, action)["inventory"]
    root = tmp_path / ".ai-sow/work/runs" / action["runId"]
    first_reference = None
    for number in range(1, rounds + 1):
        packet = prototype_payload(tmp_path, action)
        assert packet["identity"]["round"] == number
        if number == 2:
            assert packet["prototypeLedger"]["value"]["rounds"][0]["observationRefs"][0] == first_reference
        chosen = copy.deepcopy(inventory)
        chosen["interactions"] = [inventory["interactions"][number - 1]]
        scenario = scenario_fixture(chosen, round=number)
        submit_prototype(tmp_path, action, scenario)
        browser = orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]
        submit_prototype(tmp_path, browser, trace_fixture(inventory, scenario))
        analyze = orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]
        submit_prototype(tmp_path, analyze, {"observations": [observation_fixture(chosen, "only-round-" + str(number))]})
        next_result = orchestrator_module.run_mode(tmp_path, "resume")
        ledger_paths = list((root / "stages/SCOPE/prototype-ledgers").glob("*.json"))
        ledgers = [json.loads(path.read_bytes()) for path in ledger_paths]
        ledger = max(ledgers, key=lambda body: len(body["rounds"]))
        first_reference = ledger["rounds"][0]["observationRefs"][0]
        if number == 1 and rounds == 2:
            assert next_result["nextAction"]["actionContractId"] == "PROTOTYPE_SCENARIO-v1"
            assert not ledger["sealed"]
            action = next_result["nextAction"]
    if rounds == 1:
        assert next_result["outcome"] == "WAITING_INPUT"
        assert next_result["diagnostics"][0]["code"] == "INCOMPLETE_BUDGET"
        assert orchestrator_module.run_mode(tmp_path, "resume")["outcome"] == "WAITING_INPUT"
    else:
        assert next_result["nextAction"]["actionContractId"] == "SOURCE_SCAN-v1"
        assert ledger["sealed"]
        assert [r["observationRefs"][0]["localKey"] for r in ledger["rounds"]] == ["only-round-1", "only-round-2"]
        assert len(ledger["interactionDispositions"]) == 2


def test_interaction_coverage_unresolved_trace_waits_without_scope_or_analyze(tmp_path):
    from test_prototype_analysis import scenario_fixture, trace_fixture, unresolved_discovery
    action = start_demo(tmp_path)["nextAction"]
    inventory = prototype_payload(tmp_path, action)["inventory"]
    scenario = scenario_fixture(inventory)
    submit_prototype(tmp_path, action, scenario)
    browser = orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]
    trace = trace_fixture(inventory, scenario)
    trace["unresolvedDiscoveries"] = [unresolved_discovery(inventory)]
    record = submit_prototype(tmp_path, browser, trace)["record"]
    assert record["outcome"] == "SUCCEEDED"
    result = orchestrator_module.run_mode(tmp_path, "resume")
    assert result["outcome"] == "WAITING_INPUT", result
    assert result["diagnostics"][0]["code"] == "PROTOTYPE_UNRESOLVED_DISCOVERY"
    assert orchestrator_module.run_mode(tmp_path, "resume")["outcome"] == "WAITING_INPUT"
    root = tmp_path / ".ai-sow/work/runs" / browser["runId"]
    assert len(list((root / "actions").glob("*/envelope.json"))) == 2
    assert not list((root / "stages/SCOPE/prototype-ledgers").glob("*.json"))


@pytest.mark.parametrize("case", ["budget", "missing"])
def test_interaction_coverage_replay_counts_actual_budget_and_incomplete_wait(tmp_path, case):
    from test_prototype_analysis import scenario_fixture, trace_fixture
    action = start_demo(tmp_path, steps=1)["nextAction"]
    inventory = prototype_payload(tmp_path, action)["inventory"]
    scenario = scenario_fixture(inventory)
    submit_prototype(tmp_path, action, scenario)
    browser = orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]
    trace = trace_fixture(inventory, scenario)
    trace["runs"][0]["stable"] = False
    if case == "budget":
        trace["runs"].append(copy.deepcopy(trace["runs"][0]) | {"stable": True, "replay": 1})
    record = submit_prototype(tmp_path, browser, trace)["record"]
    assert record["outcome"] == "SUCCEEDED"
    result = orchestrator_module.run_mode(tmp_path, "resume")
    assert result["outcome"] == "WAITING_INPUT", result
    assert result["diagnostics"][0]["code"] == "INCOMPLETE_BUDGET"
    root = tmp_path / ".ai-sow/work/runs" / browser["runId"]
    assert len(list((root / "actions").glob("*/envelope.json"))) == 2


@pytest.mark.parametrize("case", ["unbound-discovery", "false-assertion", "incomplete-and-invalid"])
def test_trace_binding_public_invalid_evidence_records_system_and_raw_only(tmp_path, case):
    from test_prototype_analysis import scenario_fixture, trace_fixture, unresolved_discovery
    action = start_demo(tmp_path)["nextAction"]
    inventory = prototype_payload(tmp_path, action)["inventory"]
    scenario = scenario_fixture(inventory)
    submit_prototype(tmp_path, action, scenario)
    browser = orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]
    trace = trace_fixture(inventory, scenario)
    if case == "unbound-discovery":
        trace["unresolvedDiscoveries"] = [unresolved_discovery(inventory) | {"sourceEvidenceIds": ["fake-source"]}]
    if case == "false-assertion":
        trace["runs"][0]["steps"][0]["assertions"][0]["actual"] = "failed"
    if case == "incomplete-and-invalid":
        trace["runs"][0]["stable"] = False
        trace["runs"][0]["steps"][0]["operation"] = "fill"
    recorded = submit_prototype(tmp_path, browser, trace)
    assert recorded["record"]["failureKind"] == "SYSTEM"
    assert recorded["record"]["normalizedResultSha256"] is None
    root = tmp_path / browser["resultPath"]
    assert (root.parent / "raw-output.bin").read_bytes() == canonical_json_bytes(trace)
    assert not (root.parent / "normalized-result.json").exists()
    assert submit_prototype(tmp_path, browser, trace) == recorded
    result = orchestrator_module.run_mode(tmp_path, "resume")
    assert result["outcome"] == "SYSTEM_FAILED"
    assert len(list(root.parent.parent.glob("*/envelope.json"))) == 2


def test_trace_binding_public_second_round_uses_first_authorized_profile(tmp_path):
    from test_prototype_analysis import scenario_fixture, trace_fixture, observation_fixture
    action = start_demo(tmp_path, two_controls=True)["nextAction"]
    inventory = prototype_payload(tmp_path, action)["inventory"]
    scenario = scenario_fixture(inventory)
    submit_prototype(tmp_path, action, scenario)
    browser = orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]
    first_trace = trace_fixture(inventory, scenario)
    first_record = submit_prototype(tmp_path, browser, first_trace)["record"]
    analyze = orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]
    submit_prototype(tmp_path, analyze, {"observations": [observation_fixture(inventory)]})
    action2 = orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]
    chosen = copy.deepcopy(inventory)
    chosen["interactions"] = [inventory["interactions"][1]]
    scenario2 = scenario_fixture(chosen, round=2)
    submit_prototype(tmp_path, action2, scenario2)
    browser2 = orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]
    payload = prototype_payload(tmp_path, browser2)
    assert "browserProfileSource" in payload
    assert payload["browserProfileSource"]["attemptRecordSha256"] == sha256_bytes(canonical_json_bytes(first_record))
    assert payload["browserProfileSource"]["normalizedResult"] == first_trace
    changed = trace_fixture(inventory, scenario2)
    changed["browserProfile"]["viewport"]["width"] = 800
    changed["runs"][0]["browserProfileSha256"] = sha256_bytes(canonical_json_bytes(changed["browserProfile"]))
    assert submit_prototype(tmp_path, browser2, changed)["record"]["failureKind"] == "SYSTEM"
    assert orchestrator_module.run_mode(tmp_path, "resume")["outcome"] == "SYSTEM_FAILED"


@pytest.mark.parametrize("runtime_status", ["BROKEN", "CODE_ONLY"])
def test_demo_scope_semantics_owner_gates_formal_claim_and_preserves_code_candidate(tmp_path, runtime_status):
    from test_prototype_analysis import scenario_fixture, trace_fixture, observation_fixture
    action = start_demo(tmp_path)["nextAction"]
    inventory = prototype_payload(tmp_path, action)["inventory"]
    scenario = scenario_fixture(inventory)
    submit_prototype(tmp_path, action, scenario)
    browser = orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]
    submit_prototype(tmp_path, browser, trace_fixture(inventory, scenario))
    analyze = orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]
    observation = observation_fixture(inventory) | {"runtimeStatus": runtime_status}
    submit_prototype(tmp_path, analyze, {"observations": [observation]})
    result = orchestrator_module.run_mode(tmp_path, "resume")
    root = tmp_path / ".ai-sow/work/runs" / analyze["runId"]
    if runtime_status == "BROKEN":
        assert result["outcome"] == "WAITING_INPUT", result
        assert result["diagnostics"][0]["code"] == "PROTOTYPE_SCOPE_EVIDENCE_REQUIRED"
        assert not list((root / "stages/SCOPE/prototype-ledgers").glob("*.json"))
    else:
        assert result["nextAction"]["actionContractId"] == "SOURCE_SCAN-v1"
        ledger = json.loads(next((root / "stages/SCOPE/prototype-ledgers").glob("*.json")).read_bytes())
        assert ledger["sealed"]
        assert "requiresIntentReviewLocalKeys" not in json.dumps(ledger)


@pytest.mark.parametrize("relation,disposition", [("NON_SCOPE", "EXCLUDED"), ("ADDITIONAL", "NOT_EXERCISED")])
def test_interaction_coverage_explicit_source_disposition_closes_unexecuted_control(tmp_path, relation, disposition):
    from test_prototype_analysis import scenario_fixture, trace_fixture, observation_fixture
    action = start_demo(tmp_path, two_controls=True)["nextAction"]
    inventory = prototype_payload(tmp_path, action)["inventory"]
    scenario = scenario_fixture(inventory)
    submit_prototype(tmp_path, action, scenario)
    browser = orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]
    submit_prototype(tmp_path, browser, trace_fixture(inventory, scenario))
    analyze = orchestrator_module.run_mode(tmp_path, "resume")["nextAction"]
    chosen = copy.deepcopy(inventory)
    chosen["interactions"] = [inventory["interactions"][1]]
    observation = observation_fixture(chosen, "unexecuted-control") | {"runtimeStatus": "CODE_ONLY", "scopeRelation": relation}
    submit_prototype(tmp_path, analyze, {"observations": [observation_fixture(inventory), observation]})
    result = orchestrator_module.run_mode(tmp_path, "resume")
    assert result["nextAction"]["actionContractId"] == "SOURCE_SCAN-v1"
    path = next((tmp_path / ".ai-sow/work/runs" / analyze["runId"] / "stages/SCOPE/prototype-ledgers").glob("*.json"))
    ledger = json.loads(path.read_bytes())
    assert ledger["sealed"]
    assert {"interactionId": inventory["interactions"][1]["interactionId"], "disposition": disposition} in ledger["interactionDispositions"]


def test_public_budget_policy_seam_start_publishes_canonical_policy(tmp_path):
    request_path = write_run_store_request(tmp_path)
    policy_path = write_budget_policy(tmp_path)
    result = orchestrator_module.start(tmp_path, request_path, policy_path)
    assert result["outcome"] == "ACTIVE"
    run_root = tmp_path / ".ai-sow/work/runs" / result["state"]["runId"]
    policy_bytes = (tmp_path / policy_path).read_bytes()
    digest = sha256_bytes(policy_bytes)
    assert (run_root / "budget-policies" / f"{digest}.json").read_bytes() == policy_bytes
    events = [json.loads(path.read_bytes()) for path in sorted((run_root / "events").glob("*.json"))]
    assert events[0]["type"] == "RUN_BUDGET_POLICY_PUBLISHED"
    assert events[0]["payload"] == {"budgetPolicySha256": digest}
    revision = json.loads(next((tmp_path / ".ai-sow/inputs/revisions").glob("*/manifest.json")).read_bytes())
    assert digest not in json.dumps(revision)


def test_public_budget_policy_seam_dispatch_passes_explicit_policy(tmp_path):
    request = write_run_store_request(tmp_path)
    budget = write_budget_policy(tmp_path)
    result = orchestrator_module.run_mode(tmp_path, "start", request=request, budget_policy=budget)
    assert result["nextAction"]["contract"] == "ai-sow-action-v3"


@pytest.mark.parametrize("mode,arguments", [
    ("start", {"request": "request.json"}),
    ("resume", {"request": "request.json"}),
    ("submit", {"action_id": "action-test", "execution": "missing.json", "budget_policy": "budget.json"}),
    ("approve", {"artifact_manifest_sha256": "a" * 64, "budget_policy": "budget.json"}),
])
def test_public_budget_policy_seam_rejects_wrong_mode_arguments(tmp_path, mode, arguments):
    before = managed_snapshot(tmp_path)
    result = orchestrator_module.run_mode(tmp_path, mode, **arguments)
    assert result["diagnostics"][0]["code"] == "CLI_ARGUMENTS_INVALID", result
    assert managed_snapshot(tmp_path) == before


@pytest.mark.parametrize("interruption", ["body", "event"])
def test_public_budget_policy_seam_pre_reservation_failure_has_no_issued_work(tmp_path, monkeypatch, interruption):
    request = write_run_store_request(tmp_path)
    budget = write_budget_policy(tmp_path)
    publish = ProjectFiles.publish_new

    def fail_after_publish(files, path, payload):
        result = publish(files, path, payload)
        if (interruption == "body" and "/budget-policies/" in path) or (
            interruption == "event" and "/events/" in path
        ):
            raise OSError("injected pre-reservation failure")
        return result

    with monkeypatch.context() as fault:
        fault.setattr(ProjectFiles, "publish_new", fail_after_publish)
        result = orchestrator_module.run_mode(tmp_path, "start", request=request, budget_policy=budget)
    assert result["outcome"] == "BLOCKED"
    assert not (tmp_path / ".ai-sow/work/active-run.json").exists()
    orphan = next((tmp_path / ".ai-sow/work/runs").iterdir())
    assert not (orphan / "actions").exists()
    assert not (orphan / "candidates").exists()
    before = managed_snapshot(tmp_path)
    assert orchestrator_module.status(tmp_path)["outcome"] == "BLOCKED"
    assert managed_snapshot(tmp_path) == before
    retried = orchestrator_module.run_mode(tmp_path, "start", request=request, budget_policy=budget)
    assert retried["outcome"] == "ACTIVE", retried
    assert retried["state"]["runId"] != orphan.name
    for path, content in before.items():
        assert managed_snapshot(tmp_path)[path] == content
    root = tmp_path / ".ai-sow/work/runs" / retried["state"]["runId"]
    events = [json.loads(path.read_bytes()) for path in sorted((root / "events").glob("*.json"))]
    assert [event["type"] for event in events] == ["RUN_BUDGET_POLICY_PUBLISHED", "ACTION_ISSUED"]


def test_public_budget_policy_seam_external_source_is_read_only_and_run_local(tmp_path):
    source = tmp_path / write_budget_policy(tmp_path)
    source_before = (source.read_bytes(), source.stat().st_mtime_ns)
    projects = [tmp_path / "one", tmp_path / "two"]
    runs = []
    for project in projects:
        project.mkdir()
        request = write_run_store_request(project)
        result = orchestrator_module.start(project, request, str(source))
        assert result["outcome"] == "ACTIVE", result
        runs.append(project / ".ai-sow/work/runs" / result["state"]["runId"])
    digest = sha256_bytes(source_before[0])
    for run in runs:
        assert (run / "budget-policies" / f"{digest}.json").read_bytes() == source_before[0]
    assert (source.read_bytes(), source.stat().st_mtime_ns) == source_before
    other_before = managed_snapshot(projects[1])
    replacement = tmp_path / "increased.json"
    write_json(replacement, {**json.loads(source_before[0]), "maxPlannedTokens": 2000000})
    replacement_before = (replacement.read_bytes(), replacement.stat().st_mtime_ns)
    replaced = orchestrator_module.resume(projects[0], str(replacement))
    assert replaced["outcome"] == "ACTIVE", replaced
    assert managed_snapshot(projects[1]) == other_before
    assert len(list((runs[0] / "budget-policies").glob("*.json"))) == 2
    assert (replacement.read_bytes(), replacement.stat().st_mtime_ns) == replacement_before
    source.unlink()
    replacement.unlink()
    for project in projects:
        before = managed_snapshot(project)
        assert orchestrator_module.resume(project)["outcome"] == "ACTIVE"
        assert managed_snapshot(project) == before



@pytest.mark.parametrize('interruption',[None,'before_exit','after_exit'])
def test_resume_fitting_unissued_ir_retry_keeps_original_attempt_and_budget(tmp_path,monkeypatch,interruption):
    from stage_planner import StagePlanningBlocked
    action=orchestrator_module.run_mode(tmp_path,'start',request=write_run_store_request(tmp_path),
        budget_policy=write_budget_policy(tmp_path))['nextAction']
    materialize=orchestrator_module._materialize_action_retry
    def over_capacity(*args,**kwargs):raise StagePlanningBlocked('BUDGET_EXHAUSTED')
    monkeypatch.setattr(orchestrator_module,'_materialize_action_retry',over_capacity)
    write_json(tmp_path/action['resultPath'],{'invalid':'retained old result'})
    write_json(tmp_path/'execution.json',{'failureKind':None,'diagnostic':None,
        'usage':{'provenance':'PROVIDER_REPORTED','inputTokens':100,'outputTokens':20,'cachedInputTokens':0,'reasoningTokens':None},
        'timing':{'startedAtUtc':'2026-09-05T00:00:00Z','endedAtUtc':'2026-09-05T00:00:01Z'}})
    waiting=orchestrator_module.run_mode(tmp_path,'submit',action_id=action['actionId'],result=action['resultPath'],execution='execution.json')
    assert waiting['outcome']=='WAITING_INPUT'
    root=tmp_path/'.ai-sow/work/runs'/action['runId']
    before={path:path.read_bytes() for path in root.rglob('*') if path.is_file()}
    monkeypatch.setattr(orchestrator_module,'_materialize_action_retry',materialize)
    if interruption:
        append=orchestrator_module._append_run_event
        def crash(files,run_id,kind,payload):
            if kind=='WAITING_INPUT_EXITED' and payload.get('resolutionKind')=='FITTING_UNISSUED_RETRY':
                if interruption=='after_exit':append(files,run_id,kind,payload)
                raise RuntimeError('interrupted retry recovery')
            return append(files,run_id,kind,payload)
        monkeypatch.setattr(orchestrator_module,'_append_run_event',crash)
        with pytest.raises(RuntimeError,match='interrupted retry recovery'):orchestrator_module.resume(tmp_path)
        monkeypatch.setattr(orchestrator_module,'_append_run_event',append)
    result=orchestrator_module.run_mode(tmp_path,'resume')
    assert result['outcome']=='ACTIVE',result
    retry=result['nextAction']
    assert retry['logicalWorkId']==action['logicalWorkId'] and retry['revision']==2
    assert retry['budgetPolicySha256']==action['budgetPolicySha256']
    assert all(path.read_bytes()==raw for path,raw in before.items())
    assert len(list((root/'actions').glob('*/envelope.json')))==2
    assert orchestrator_module.run_mode(tmp_path,'resume')['nextAction']==retry


def test_public_budget_policy_seam_relative_source_cannot_escape_project(tmp_path):
    write_budget_policy(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    request = write_run_store_request(project)
    result = orchestrator_module.start(project, request, "../budget.json")
    assert result["outcome"] != "ACTIVE"
    assert not (project / ".ai-sow/work/runs").exists()


def test_public_budget_policy_seam_resume_replaces_only_explicit_policy(tmp_path):
    request = write_run_store_request(tmp_path)
    budget = write_budget_policy(tmp_path)
    first = orchestrator_module.start(tmp_path, request, budget)
    first_revision = first["state"]["currentInputRevisionSha256"]
    before = managed_snapshot(tmp_path)
    write_budget_policy(tmp_path, maxPlannedTokens=2000000)
    orchestrator_module.resume(tmp_path)
    assert managed_snapshot(tmp_path) == before
    result = orchestrator_module.resume(tmp_path, replacement_budget_policy_path=budget)
    assert result["outcome"] == "ACTIVE"
    assert result["state"]["currentInputRevisionSha256"] == first_revision
    run_root = tmp_path / ".ai-sow/work/runs" / first["state"]["runId"]
    assert len(list((run_root / "budget-policies").glob("*.json"))) == 2
    events = [json.loads(path.read_bytes()) for path in sorted((run_root / "events").glob("*.json"))]
    assert [event["type"] for event in events] == ["RUN_BUDGET_POLICY_PUBLISHED"] * 2
    assert events[-1]["payload"]["budgetPolicySha256"] == sha256_bytes((tmp_path / budget).read_bytes())

@pytest.mark.parametrize('interruption', [None, 'before_exit', 'after_exit'])
@pytest.mark.parametrize('with_demo', [False, True])
def test_resume_fitting_unissued_scope_plan_preserves_run_and_budget(tmp_path, monkeypatch, interruption, with_demo):
    import scope_compiler
    from stage_planner import StagePlanningBlocked
    original = scope_compiler.build_scope_work_descriptors
    def blocked(*args, **kwargs):
        raise StagePlanningBlocked('BUDGET_EXHAUSTED')
    monkeypatch.setattr(scope_compiler, 'build_scope_work_descriptors', blocked)
    if with_demo:
        from test_prototype_analysis import scenario_fixture, trace_fixture, observation_fixture
        action = start_demo(tmp_path)['nextAction']
        inventory = prototype_payload(tmp_path, action)['inventory']
        scenario = scenario_fixture(inventory)
        submit_prototype(tmp_path, action, scenario)
        action = orchestrator_module.run_mode(tmp_path, 'resume')['nextAction']
        submit_prototype(tmp_path, action, trace_fixture(inventory, scenario))
        action = orchestrator_module.run_mode(tmp_path, 'resume')['nextAction']
        submit_prototype(tmp_path, action, {'observations':[observation_fixture(inventory)]})
        waiting = orchestrator_module.run_mode(tmp_path, 'resume')
    else:
        request = write_run_store_request(tmp_path)
        budget = write_budget_policy(tmp_path)
        waiting = orchestrator_module.run_mode(tmp_path, 'start', request=request, budget_policy=budget)
    assert waiting['outcome'] == 'WAITING_INPUT'
    run_id = waiting['state']['runId']
    run_root = tmp_path / '.ai-sow/work/runs' / run_id
    before = {path:path.read_bytes() for path in run_root.rglob('*') if path.is_file()}
    monkeypatch.setattr(scope_compiler, 'build_scope_work_descriptors', original)
    if interruption:
        append_event = orchestrator_module._append_run_event
        def interrupted(files, run_id, kind, payload):
            if kind=='WAITING_INPUT_EXITED' and payload.get('resolutionKind')=='FITTING_UNISSUED_PLAN':
                if interruption=='after_exit': append_event(files,run_id,kind,payload)
                raise RuntimeError('simulated interruption')
            return append_event(files,run_id,kind,payload)
        monkeypatch.setattr(orchestrator_module, '_append_run_event', interrupted)
        with pytest.raises(RuntimeError, match='simulated interruption'):
            orchestrator_module.resume(tmp_path)
        monkeypatch.setattr(orchestrator_module, '_append_run_event', append_event)
    resumed = orchestrator_module.run_mode(tmp_path, 'resume')
    assert resumed['outcome'] == 'ACTIVE' and resumed['nextAction'], resumed
    assert resumed['state']['runId'] == run_id
    assert resumed['state']['currentInputRevisionSha256'] == waiting['state']['currentInputRevisionSha256']
    assert all(path.read_bytes() == content for path,content in before.items())
    assert len(list((run_root / 'budget-policies').glob('*.json'))) == 1
    events = [json.loads(path.read_bytes()) for path in sorted((run_root/'events').glob('*.json'))]
    exits = [event for event in events if event['type']=='WAITING_INPUT_EXITED']
    assert len(exits) == 1 and exits[0]['payload']['resolutionKind']=='FITTING_UNISSUED_PLAN'
    assert orchestrator_module.run_mode(tmp_path, 'resume')['nextAction'] == resumed['nextAction']



@pytest.mark.parametrize("changes", [
    {},
    {"maxPlannedTokens": 999999},
    {"maxActiveSeconds": 3599},
    {"demoLimits": {"maxDiscoveryRounds": 1, "maxScenarioSteps": 30, "maxScreenshots": 12}},
    {"demoLimits": {"maxDiscoveryRounds": 2, "maxScenarioSteps": 29, "maxScreenshots": 12}},
    {"demoLimits": {"maxDiscoveryRounds": 2, "maxScenarioSteps": 30, "maxScreenshots": 11}},
    {"outputReserveTokens": 8193, "maxPlannedTokens": 2000000},
    {"hydrateReserveTokens": 4097, "maxPlannedTokens": 2000000},
    {"safetyMarginTokens": 1025, "maxPlannedTokens": 2000000},
    {"referenceOverheadTokens": 257, "maxPlannedTokens": 2000000},
    {"modelContextLimitTokens": 64000, "maxPlannedTokens": 2000000},
    {"maxConcurrency": 7, "maxPlannedTokens": 2000000},
    {"contractVersion": "other-contract", "maxPlannedTokens": 2000000},
    {"modelProfileId": "other-model", "maxPlannedTokens": 2000000},
    {"estimatorVersion": "other-estimator", "maxPlannedTokens": 2000000},
])
def test_budget_update_not_business_input_replacement_only_monotonic_limits(tmp_path, changes):
    request = write_run_store_request(tmp_path)
    budget = write_budget_policy(tmp_path)
    orchestrator_module.start(tmp_path, request, budget)
    before = managed_snapshot(tmp_path)
    write_budget_policy(tmp_path, **changes)
    result = orchestrator_module.resume(tmp_path, budget)
    assert result["outcome"] == "BLOCKED"
    code = "RUN_BUDGET_POLICY_INVALID" if set(changes) & {"contractVersion", "modelProfileId", "estimatorVersion"} else "RUN_BUDGET_REPLACEMENT_INVALID"
    assert result["diagnostics"][0]["code"] == code
    assert managed_snapshot(tmp_path) == before


@pytest.mark.parametrize("field", ["maxPlannedTokens", "maxActiveSeconds", "modelContextLimitTokens", "maxDiscoveryRounds", "maxScenarioSteps", "maxScreenshots"])
def test_budget_update_not_business_input_increase_preserves_frozen_plan_and_attempt(tmp_path, field):
    from stage_driver import stage_result
    request = write_run_store_request(tmp_path)
    budget = write_budget_policy(tmp_path)
    started = orchestrator_module.run_mode(tmp_path, "start", request=request, budget_policy=budget)
    action = started["nextAction"]
    packet = json.loads((tmp_path / action["packetPath"]).read_bytes())
    submit_prototype(tmp_path, action, stage_result(action["actionContractId"][:-3], packet))
    before = managed_snapshot(tmp_path)
    policy = json.loads((tmp_path / budget).read_bytes())
    target = policy if field in policy else policy["demoLimits"]
    target[field] += 1
    write_json(tmp_path / budget, policy)
    result = orchestrator_module.resume(tmp_path, replacement_budget_policy_path=budget)
    assert result["outcome"] == "ACTIVE", result
    assert result["state"]["currentInputRevisionSha256"] == started["state"]["currentInputRevisionSha256"]
    after = managed_snapshot(tmp_path)
    assert {path: after[path] for path in before} == before
    added = set(after) - set(before)
    assert len(added) == 2
    assert sum("/budget-policies/" in path for path in added) == 1
    event = json.loads(after[next(path for path in added if "/events/" in path)])
    assert event["type"] == "RUN_BUDGET_POLICY_PUBLISHED"
    assert event["payload"] == {"budgetPolicySha256": sha256_bytes(canonical_json_bytes(policy))}
    assert orchestrator_module._effective_budget_policy(ProjectFiles.open(tmp_path), started["state"]["runId"])[1] == policy
    unchanged = managed_snapshot(tmp_path)
    replay = orchestrator_module.resume(tmp_path, replacement_budget_policy_path=budget)
    assert replay["outcome"] == "BLOCKED", replay
    assert replay["diagnostics"][0]["code"] == "RUN_BUDGET_REPLACEMENT_INVALID"
    assert managed_snapshot(tmp_path) == unchanged


def test_budget_update_not_business_input_keeps_completed_checkpoint(tmp_path):
    action = scope_review_action(tmp_path)
    submit_prototype(tmp_path, action, {"decision": "PASS", "findings": []})
    current = orchestrator_module.run_mode(tmp_path, "resume")
    assert len(current["state"]["checkpointRefs"]) == 1
    before = managed_snapshot(tmp_path)
    budget = write_budget_policy(tmp_path, maxActiveSeconds=7200)
    updated = orchestrator_module.resume(tmp_path, replacement_budget_policy_path=budget)
    assert updated["outcome"] == "ACTIVE", updated
    assert updated["state"]["checkpointRefs"] == current["state"]["checkpointRefs"]
    after = managed_snapshot(tmp_path)
    assert {path: after[path] for path in before} == before
    assert len(set(after) - set(before)) == 2


def test_budget_update_not_business_input_published_event_crash_recovers_without_resubmission(tmp_path, monkeypatch):
    request = write_run_store_request(tmp_path)
    started = orchestrator_module.run_mode(tmp_path, "start", request=request,
        budget_policy=write_budget_policy(tmp_path, maxPlannedTokens=1))
    assert started["outcome"] == "WAITING_INPUT"
    budget = write_budget_policy(tmp_path)
    digest = sha256_bytes((tmp_path / budget).read_bytes())
    original = ProjectFiles.publish_new

    def fail_after_event(files, path, payload):
        result = original(files, path, payload)
        if "/events/" in path and json.loads(payload).get("payload") == {"budgetPolicySha256": digest}:
            raise OSError("interrupted after budget publication event")
        return result

    with monkeypatch.context() as fault:
        fault.setattr(ProjectFiles, "publish_new", fail_after_event)
        assert orchestrator_module.run_mode(tmp_path, "resume", budget_policy=budget)["outcome"] == "BLOCKED"
    assert orchestrator_module.resume(tmp_path, replacement_budget_policy_path=budget)["diagnostics"][0]["code"] == "RUN_BUDGET_REPLACEMENT_INVALID"
    resumed = orchestrator_module.run_mode(tmp_path, "resume")
    assert resumed["outcome"] == "ACTIVE", resumed
    assert resumed["state"]["runId"] == started["state"]["runId"]
    assert resumed["nextAction"]["budgetPolicySha256"] == digest


def test_context_capacity_increase_recovers_unissued_retry_and_preserves_frozen_bytes(tmp_path):
    request = write_run_store_request(tmp_path)
    budget = write_budget_policy(tmp_path)
    started = orchestrator_module.run_mode(tmp_path, "start", request=request, budget_policy=budget)
    action = started["nextAction"]
    policy = json.loads((tmp_path / budget).read_bytes())
    write_json(tmp_path / action["resultPath"], {"invalid": "x" * policy["modelContextLimitTokens"]})
    write_json(tmp_path / "execution.json", {"failureKind": None, "diagnostic": None,
        "usage": {"provenance": "PROVIDER_REPORTED", "inputTokens": 100, "outputTokens": 20, "cachedInputTokens": 0, "reasoningTokens": None},
        "timing": {"startedAtUtc": "2026-09-05T00:00:00Z", "endedAtUtc": "2026-09-05T00:00:01Z"}})
    waiting = orchestrator_module.run_mode(tmp_path, "submit", action_id=action["actionId"], result=action["resultPath"], execution="execution.json")
    assert waiting["outcome"] == "WAITING_INPUT", waiting
    assert waiting["diagnostics"][0]["code"] == "BUDGET_EXHAUSTED"
    run = tmp_path / ".ai-sow/work/runs" / started["state"]["runId"]
    immutable = {path: path.read_bytes() for root in (run / "actions", run / "budget-policies", run / "stages", tmp_path / ".ai-sow/inputs")
                 for path in root.rglob("*") if path.is_file()}
    write_json(tmp_path / budget, {**policy, "modelContextLimitTokens": policy["modelContextLimitTokens"] * 2})
    resumed = orchestrator_module.run_mode(tmp_path, "resume", budget_policy=budget)
    assert resumed["outcome"] == "ACTIVE", resumed
    retry = resumed["nextAction"]
    assert retry["revision"] == 2 and retry["attempt"] == 1
    assert retry["logicalWorkId"] == action["logicalWorkId"]
    assert retry["budgetPolicySha256"] != action["budgetPolicySha256"]
    assert retry["inputRevisionSha256"] == action["inputRevisionSha256"]
    assert {path: path.read_bytes() for path in immutable} == immutable
    assert orchestrator_module.read_provider_request(tmp_path, retry["actionId"])


def test_public_budget_policy_seam_rejects_published_policy_hash_drift(tmp_path):
    request = write_run_store_request(tmp_path)
    started = orchestrator_module.start(tmp_path, request, write_budget_policy(tmp_path))
    root = tmp_path / ".ai-sow/work/runs" / started["state"]["runId"]
    published = next((root / "budget-policies").glob("*.json"))
    body = json.loads(published.read_bytes())
    write_json(published, {**body, "maxPlannedTokens": 2000000})
    before = managed_snapshot(tmp_path)
    result = orchestrator_module.resume(tmp_path)
    assert result["outcome"] == "BLOCKED"
    assert result["diagnostics"][0]["code"] == "RUN_BUDGET_POLICY_HASH_INVALID"
    assert managed_snapshot(tmp_path) == before


@pytest.mark.parametrize("consumer", ["resume", "status"])
@pytest.mark.parametrize("change", [
    {"maxPlannedTokens": 999999},
    {"modelContextLimitTokens": 64000, "maxPlannedTokens": 2000000},
])
def test_public_budget_policy_seam_rejects_illegal_event_history(tmp_path, consumer, change):
    request = write_run_store_request(tmp_path)
    budget = write_budget_policy(tmp_path)
    started = orchestrator_module.run_mode(tmp_path, "start", request=request, budget_policy=budget)
    root = tmp_path / ".ai-sow/work/runs" / started["state"]["runId"]
    body = {**json.loads((tmp_path / budget).read_bytes()), **change}
    digest = sha256_bytes(canonical_json_bytes(body))
    write_json(root / "budget-policies" / f"{digest}.json", body)
    first = json.loads((root / "events/000001.json").read_bytes())
    write_json(root / "events/000003.json", {
        **first, "sequence": 3, "payload": {"budgetPolicySha256": digest},
    })
    before = managed_snapshot(tmp_path)
    result = getattr(orchestrator_module, consumer)(tmp_path)
    assert result["outcome"] == "BLOCKED", result
    assert result["diagnostics"][0]["code"] == "RUN_BUDGET_REPLACEMENT_INVALID"
    assert managed_snapshot(tmp_path) == before


def test_public_budget_policy_seam_issuance_binds_effective_policy(tmp_path):
    request = write_run_store_request(tmp_path)
    budget = write_budget_policy(tmp_path)
    result = orchestrator_module.run_mode(tmp_path, "start", request=request, budget_policy=budget)
    envelope = result["nextAction"]
    assert envelope["budgetPolicySha256"] == sha256_bytes((tmp_path / budget).read_bytes())


def test_planned_token_guard_estimates_complete_bound_provider_request(tmp_path):
    from contracts import action_contract_binding

    request = write_run_store_request(tmp_path)
    result = orchestrator_module.run_mode(
        tmp_path, "start", request=request, budget_policy=write_budget_policy(tmp_path)
    )
    envelope = result["nextAction"]
    contract, _ = action_contract_binding(SKILL_ROOT, envelope["actionContractId"])
    packet_text = (tmp_path / envelope["packetPath"]).read_text(encoding="utf-8")
    expected_request = canonical_json_bytes({
        "messages": [
            {"role": "system", "content": (SKILL_ROOT / contract["instruction"]["path"]).read_text(encoding="utf-8")},
            {"role": "user", "content": packet_text},
        ],
        "maxOutputTokens": envelope["executionLimits"]["maxOutputTokens"],
    })
    assert envelope["executionLimits"]["estimatedInputTokens"] == len(expected_request)


def test_planned_token_guard_host_reads_same_frozen_request_after_replacement(tmp_path):
    request = write_run_store_request(tmp_path)
    budget = write_budget_policy(tmp_path)
    started = orchestrator_module.run_mode(tmp_path, "start", request=request, budget_policy=budget)
    action = started["nextAction"]
    before = managed_snapshot(tmp_path)
    payload = orchestrator_module.read_provider_request(tmp_path, action["actionId"])
    assert managed_snapshot(tmp_path) == before
    assert len(payload) == action["executionLimits"]["estimatedInputTokens"]
    value = json.loads(payload)
    assert value["maxOutputTokens"] == action["executionLimits"]["maxOutputTokens"]
    assert value["messages"][0]["role"] == "system"
    assert value["messages"][1] == {
        "role": "user", "content": (tmp_path / action["packetPath"]).read_text(encoding="utf-8"),
    }
    write_budget_policy(tmp_path, maxPlannedTokens=2000000)
    assert orchestrator_module.resume(tmp_path, budget)["outcome"] == "ACTIVE"
    before = managed_snapshot(tmp_path)
    assert orchestrator_module.read_provider_request(tmp_path, action["actionId"]) == payload
    assert managed_snapshot(tmp_path) == before


def test_planned_token_guard_state_has_no_persisted_budget_aggregate(tmp_path):
    request = write_run_store_request(tmp_path)
    result = orchestrator_module.run_mode(
        tmp_path, "start", request=request, budget_policy=write_budget_policy(tmp_path)
    )
    assert result["outcome"] == "ACTIVE"
    assert "budget" not in result["state"]
    root = tmp_path / ".ai-sow/work/runs" / result["state"]["runId"]
    assert all("budget" not in json.loads(path.read_bytes()) for path in (root / "states").glob("*.json"))


@pytest.mark.parametrize("output,hydrate,expected_output,expected_hydrate", [
    (100, 50, 100, 50), (15000, 16000, 12000, 12000),
])
def test_planned_token_guard_envelope_limits_use_policy_and_contract_caps(tmp_path, output, hydrate, expected_output, expected_hydrate):
    request = write_run_store_request(tmp_path)
    result = orchestrator_module.run_mode(
        tmp_path, "start", request=request,
        budget_policy=write_budget_policy(tmp_path, outputReserveTokens=output, hydrateReserveTokens=hydrate),
    )
    assert result["outcome"] == "ACTIVE", result
    limits = result["nextAction"]["executionLimits"]
    assert limits["maxOutputTokens"] == expected_output
    assert limits["maxHydrateTokens"] == expected_hydrate
    assert limits["estimatedInputTokens"] == len(orchestrator_module.read_provider_request(tmp_path, result["nextAction"]["actionId"]))


def test_planned_token_guard_waits_before_first_issuance(tmp_path):
    request = write_run_store_request(tmp_path)
    result = orchestrator_module.run_mode(
        tmp_path, "start", request=request,
        budget_policy=write_budget_policy(tmp_path, maxPlannedTokens=100),
    )
    assert result["outcome"] == "WAITING_INPUT", result
    assert result["diagnostics"][0]["code"] == "BUDGET_EXHAUSTED"
    assert result["state"]["wait"] == "INPUT"
    assert result["state"]["expectedActionIds"] == []
    root = tmp_path / ".ai-sow/work/runs" / result["state"]["runId"]
    assert not list((root / "actions").glob("*/envelope.json"))
    events = [json.loads(path.read_bytes()) for path in sorted((root / "events").glob("*.json"))]
    assert not any(event["type"] == "ACTION_ISSUED" for event in events)
    assert events[-1]["type"] == "WAITING_INPUT_ENTERED"
    assert events[-1]["payload"]["reasonCode"] == "BUDGET_EXHAUSTED"
    before = managed_snapshot(tmp_path)
    assert orchestrator_module.status(tmp_path)["outcome"] == "WAITING_INPUT"
    assert orchestrator_module.run_mode(tmp_path, "resume")["outcome"] == "WAITING_INPUT"
    assert managed_snapshot(tmp_path) == before


def test_planned_token_guard_explicit_increase_resumes_unissued_group(tmp_path):
    request = write_run_store_request(tmp_path)
    budget = write_budget_policy(tmp_path, maxPlannedTokens=100)
    waiting = orchestrator_module.run_mode(tmp_path, "start", request=request, budget_policy=budget)
    run_id = waiting["state"]["runId"]
    candidate = waiting["state"]["currentCandidateSha256"]
    revision = waiting["state"]["currentInputRevisionSha256"]
    write_budget_policy(tmp_path, maxPlannedTokens=1000000)
    resumed = orchestrator_module.run_mode(tmp_path, "resume", budget_policy=budget)
    assert resumed["outcome"] == "ACTIVE", resumed
    assert resumed["state"]["runId"] == run_id
    assert resumed["state"]["currentCandidateSha256"] == candidate
    assert resumed["state"]["currentInputRevisionSha256"] == revision
    assert resumed["nextAction"]["budgetPolicySha256"] == sha256_bytes((tmp_path / budget).read_bytes())
    root = tmp_path / ".ai-sow/work/runs" / run_id
    assert len(list((root / "stages/SCOPE/plans").glob("*.json"))) == 1
    events = [json.loads(path.read_bytes()) for path in sorted((root / "events").glob("*.json"))]
    assert [event["payload"]["resolutionKind"] for event in events if event["type"] == "WAITING_INPUT_EXITED"] == ["BUDGET_POLICY"]
    assert len([event for event in events if event["type"] == "ACTION_ISSUED"]) == 1


@pytest.mark.parametrize("actual_allowance,outcome", [(119, "WAITING_INPUT"), (120, "ACTIVE")])
def test_planned_token_guard_actual_usage_replaces_terminal_estimate(tmp_path, actual_allowance, outcome):
    probe = tmp_path / "probe"
    probe.mkdir()
    request = write_run_store_request(probe)
    first = orchestrator_module.run_mode(probe, "start", request=request, budget_policy=write_budget_policy(probe))["nextAction"]
    planned = sum(first["executionLimits"].values())
    project = tmp_path / "project"
    project.mkdir()
    request = write_run_store_request(project)
    started = orchestrator_module.run_mode(project, "start", request=request, budget_policy=write_budget_policy(project, maxPlannedTokens=planned + actual_allowance))
    action = started["nextAction"]
    assert sum(action["executionLimits"].values()) == planned
    write_json(project / "failure.json", execution_facts(status="FAILED"))
    result = orchestrator_module.run_mode(project, "submit", action_id=action["actionId"], execution="failure.json")
    assert result["outcome"] == outcome, result
    root = project / ".ai-sow/work/runs" / action["runId"]
    assert len(list((root / "actions").glob("*/envelope.json"))) == (1 if outcome == "WAITING_INPUT" else 2)


def test_planned_token_guard_retry_wait_resumes_only_remaining_attempt(tmp_path):
    request = write_run_store_request(tmp_path)
    budget = write_budget_policy(tmp_path, maxPlannedTokens=19000)
    started = orchestrator_module.run_mode(tmp_path, "start", request=request, budget_policy=budget)
    action = started["nextAction"]
    root = tmp_path / ".ai-sow/work/runs" / action["runId"]
    original = (tmp_path / action_artifact_path(action, "envelope.json")).read_bytes()
    facts = execution_facts(status="FAILED")
    facts["usage"]["inputTokens"] = 19000
    write_json(tmp_path / "failure.json", facts)
    waiting = orchestrator_module.run_mode(tmp_path, "submit", action_id=action["actionId"], execution="failure.json")
    assert waiting["outcome"] == "WAITING_INPUT", waiting
    write_budget_policy(tmp_path, maxPlannedTokens=1000000)
    resumed = orchestrator_module.run_mode(tmp_path, "resume", budget_policy=budget)
    assert resumed["outcome"] == "ACTIVE", resumed
    assert resumed["nextAction"]["logicalWorkId"] == action["logicalWorkId"]
    assert resumed["nextAction"]["attempt"] == 2
    assert len(list((root / "stages/SCOPE/plans").glob("*.json"))) == 1
    assert (tmp_path / action_artifact_path(action, "envelope.json")).read_bytes() == original


def test_planned_token_guard_variance_is_read_only_and_not_a_second_charge(tmp_path):
    request = write_run_store_request(tmp_path)
    started = orchestrator_module.run_mode(tmp_path, "start", request=request, budget_policy=write_budget_policy(tmp_path, maxPlannedTokens=19000))
    action = started["nextAction"]
    planned = sum(action["executionLimits"].values())
    before = managed_snapshot(tmp_path)
    observed = orchestrator_module.status(tmp_path)
    assert observed["budgetVarianceTokens"] == -planned
    assert managed_snapshot(tmp_path) == before
    facts = execution_facts(status="FAILED")
    facts["usage"]["inputTokens"] = 19000
    write_json(tmp_path / "failure.json", facts)
    waiting = orchestrator_module.run_mode(tmp_path, "submit", action_id=action["actionId"], execution="failure.json")
    assert waiting["outcome"] == "WAITING_INPUT"
    assert waiting["budgetVarianceTokens"] == 19020 - planned
    assert waiting["diagnostics"][0]["details"]["chargedTokens"] == 19020
    assert waiting["diagnostics"][0]["details"]["unfinishedPlannedTokens"] == 0
    before = managed_snapshot(tmp_path)
    assert orchestrator_module.status(tmp_path)["budgetVarianceTokens"] == 19020 - planned
    assert managed_snapshot(tmp_path) == before
    assert all(b'"budgetVarianceTokens"' not in content for content in before.values())








def test_planned_token_guard_host_browser_has_zero_limits_and_no_provider_request(tmp_path, monkeypatch):
    import action_ledger

    root = tmp_path / "skill"
    shutil.copytree(SKILL_ROOT, root)
    registry_path = root / "contracts/action-contracts-v1.json"
    registry = json.loads(registry_path.read_bytes())
    registry["contracts"][0]["executionKind"] = "HOST_BROWSER"
    write_json(registry_path, registry)
    monkeypatch.setattr(orchestrator_module, "SKILL_ROOT", root)
    monkeypatch.setattr(action_ledger, "SKILL_ROOT", root)
    project = tmp_path / "project"
    project.mkdir()
    request = write_run_store_request(project)
    result = orchestrator_module.run_mode(project, "start", request=request, budget_policy=write_budget_policy(project, maxPlannedTokens=1))
    assert result["outcome"] == "ACTIVE", result
    action = result["nextAction"]
    assert action["executionLimits"] == {"estimatedInputTokens": 0, "maxOutputTokens": 0, "maxHydrateTokens": 0}
    assert orchestrator_module.status(project)["budgetVarianceTokens"] == 0
    with pytest.raises(ValueError, match="HOST_BROWSER"):
        orchestrator_module.read_provider_request(project, action["actionId"])
    write_json(project / "execution.json", execution_facts(status="FAILED"))
    before = managed_snapshot(project)
    invalid = orchestrator_module.run_mode(project, "submit", action_id=action["actionId"], execution="execution.json")
    assert invalid["outcome"] == "BLOCKED"
    assert managed_snapshot(project) == before
    facts = execution_facts(status="FAILED")
    facts["usage"] = {"provenance": "PROVIDER_REPORTED", "inputTokens": 0, "outputTokens": 0, "cachedInputTokens": 0, "reasoningTokens": None}
    write_json(project / "execution.json", facts)
    completed = orchestrator_module.run_mode(project, "submit", action_id=action["actionId"], execution="execution.json")
    assert completed["outcome"] == "ACTIVE", completed
    assert completed["nextAction"]["attempt"] == 2
    assert orchestrator_module.status(project)["budgetVarianceTokens"] == 0


@pytest.mark.parametrize("boundary", ["WAITING_INPUT_ENTERED", "RUN_BUDGET_POLICY_PUBLISHED", "WAITING_INPUT_EXITED", "RESUME_STATE_CHANGED"])
def test_planned_token_guard_wait_event_crash_recovers_from_run_facts(tmp_path, monkeypatch, boundary):
    request = write_run_store_request(tmp_path)
    budget = write_budget_policy(tmp_path, maxPlannedTokens=100)
    if boundary != "WAITING_INPUT_ENTERED":
        assert orchestrator_module.run_mode(tmp_path, "start", request=request, budget_policy=budget)["outcome"] == "WAITING_INPUT"
        write_budget_policy(tmp_path, maxPlannedTokens=1000000)
    publish = ProjectFiles.publish_new

    def fail_after_event(files, path, payload):
        result = publish(files, path, payload)
        if "/events/" in path:
            event = json.loads(payload)
            matches = event["type"] == boundary or (
                boundary == "RESUME_STATE_CHANGED" and event["type"] == "RUN_STATE_CHANGED" and event["payload"]["fromState"] == "WAITING_INPUT"
            )
            if matches:
                raise OSError("injected budget event crash")
        return result

    with monkeypatch.context() as fault:
        fault.setattr(ProjectFiles, "publish_new", fail_after_event)
        try:
            if boundary == "WAITING_INPUT_ENTERED":
                interrupted = orchestrator_module.run_mode(tmp_path, "start", request=request, budget_policy=budget)
            else:
                interrupted = orchestrator_module.run_mode(tmp_path, "resume", budget_policy=budget)
            assert interrupted["outcome"] == "BLOCKED"
        except OSError as error:
            assert str(error) == "injected budget event crash"
    before = managed_snapshot(tmp_path)
    orchestrator_module.status(tmp_path)
    assert managed_snapshot(tmp_path) == before
    resumed = orchestrator_module.run_mode(tmp_path, "resume")
    expected = "WAITING_INPUT" if boundary == "WAITING_INPUT_ENTERED" else "ACTIVE"
    assert resumed["outcome"] == expected, resumed
    root = tmp_path / ".ai-sow/work/runs" / resumed["state"]["runId"]
    events = [json.loads(path.read_bytes()) for path in sorted((root / "events").glob("*.json"))]
    assert sum(event["type"] == "WAITING_INPUT_ENTERED" for event in events) == 1
    assert sum(event["type"] == "WAITING_INPUT_EXITED" for event in events) == (0 if expected == "WAITING_INPUT" else 1)
    assert sum(event["type"] == "ACTION_ISSUED" for event in events) == (0 if expected == "WAITING_INPUT" else 1)


def test_active_deadline_status_unions_attempt_and_step_intervals_without_writes(tmp_path):
    request = write_run_store_request(tmp_path)
    started = orchestrator_module.run_mode(tmp_path, "start", request=request, budget_policy=write_budget_policy(tmp_path))
    action = started["nextAction"]
    facts = execution_facts(status="FAILED")
    facts["timing"]["endedAtUtc"] = "2026-09-05T00:00:04Z"
    write_json(tmp_path / "execution.json", facts)
    assert orchestrator_module.run_mode(tmp_path, "submit", action_id=action["actionId"], execution="execution.json")["outcome"] == "ACTIVE"
    root = tmp_path / ".ai-sow/work/runs" / action["runId"]
    count = len(list((root / "events").glob("*.json")))
    for index, (start, end) in enumerate(((2, 6), (10, 12)), count + 1):
        write_json(root / "events" / f"{index:06d}.json", {
            "runId": action["runId"], "sequence": index, "type": "DETERMINISTIC_STEP_FINISHED",
            "occurredAtUtc": f"2026-09-05T00:00:{end:02d}Z",
            "payload": {"stepKind": "VALIDATE", "outcome": "SUCCEEDED", "startedAtUtc": f"2026-09-05T00:00:{start:02d}Z", "endedAtUtc": f"2026-09-05T00:00:{end:02d}Z"},
        })
    before = managed_snapshot(tmp_path)
    observed = orchestrator_module.status(tmp_path)
    assert observed["activeSeconds"] == 8
    assert managed_snapshot(tmp_path) == before
    assert all(b'"activeSeconds"' not in payload for payload in before.values())


@pytest.mark.parametrize("maximum,expected", [(3, "WAITING_INPUT"), (4, "WAITING_INPUT"), (5, "ACTIVE")])
@pytest.mark.parametrize("execution_kind", ["MODEL_PROVIDER", "HOST_BROWSER"])
def test_active_deadline_finished_attempt_stops_next_action_until_increase(tmp_path, monkeypatch, maximum, expected, execution_kind):
    if execution_kind == "HOST_BROWSER":
        import action_ledger

        skill = tmp_path / "skill"
        shutil.copytree(SKILL_ROOT, skill)
        registry_path = skill / "contracts/action-contracts-v1.json"
        registry = json.loads(registry_path.read_bytes())
        registry["contracts"][0]["executionKind"] = "HOST_BROWSER"
        write_json(registry_path, registry)
        monkeypatch.setattr(orchestrator_module, "SKILL_ROOT", skill)
        monkeypatch.setattr(action_ledger, "SKILL_ROOT", skill)
    request = write_run_store_request(tmp_path)
    budget = write_budget_policy(tmp_path, maxActiveSeconds=maximum)
    started = orchestrator_module.run_mode(tmp_path, "start", request=request, budget_policy=budget)
    action = started["nextAction"]
    facts = execution_facts(status="FAILED")
    facts["timing"]["endedAtUtc"] = "2026-09-05T00:00:04Z"
    if execution_kind == "HOST_BROWSER":
        facts["usage"] = {"provenance": "PROVIDER_REPORTED", "inputTokens": 0, "outputTokens": 0, "cachedInputTokens": 0, "reasoningTokens": None}
    write_json(tmp_path / "execution.json", facts)
    result = orchestrator_module.run_mode(tmp_path, "submit", action_id=action["actionId"], execution="execution.json")
    assert result["outcome"] == expected, result
    root = tmp_path / ".ai-sow/work/runs" / action["runId"]
    record_path = root / "actions" / action["actionId"] / "record.json"
    completed = record_path.read_bytes()
    assert json.loads(completed)["timing"] == facts["timing"]
    assert len(list((root / "actions").glob("*/envelope.json"))) == (1 if expected == "WAITING_INPUT" else 2)
    if expected == "WAITING_INPUT":
        assert result["activeSeconds"] == 4
        before = managed_snapshot(tmp_path)
        assert orchestrator_module.status(tmp_path)["activeSeconds"] == 4
        assert managed_snapshot(tmp_path) == before
        assert orchestrator_module.run_mode(tmp_path, "resume")["outcome"] == "WAITING_INPUT"
        write_budget_policy(tmp_path, maxActiveSeconds=5)
        resumed = orchestrator_module.run_mode(tmp_path, "resume", budget_policy=budget)
        assert resumed["outcome"] == "ACTIVE", resumed
        assert resumed["nextAction"]["attempt"] == 2
        assert resumed["nextAction"]["logicalWorkId"] == action["logicalWorkId"]
        assert record_path.read_bytes() == completed
        assert orchestrator_module.status(tmp_path)["activeSeconds"] == 4


def test_active_deadline_rejects_reversed_deterministic_interval(tmp_path):
    request = write_run_store_request(tmp_path)
    started = orchestrator_module.start(tmp_path, request, write_budget_policy(tmp_path))
    run_id = started["state"]["runId"]
    root = tmp_path / ".ai-sow/work/runs" / run_id
    sequence = len(list((root / "events").glob("*.json"))) + 1
    write_json(root / "events" / f"{sequence:06d}.json", {
        "runId": run_id, "sequence": sequence, "type": "DETERMINISTIC_STEP_FINISHED", "occurredAtUtc": "2026-09-05T00:00:10Z",
        "payload": {"stepKind": "OFFICE", "outcome": "SUCCEEDED", "startedAtUtc": "2026-09-05T00:00:10Z", "endedAtUtc": "2026-09-05T00:00:05Z"},
    })
    before = managed_snapshot(tmp_path)
    observed = orchestrator_module.status(tmp_path)
    assert observed["outcome"] == "BLOCKED", observed
    assert "activeSeconds" not in observed
    assert managed_snapshot(tmp_path) == before


@pytest.mark.parametrize("outcome", ["SUCCEEDED", "FAILED"])
def test_active_deadline_step_fact_guards_first_action_and_wait_gap_is_free(tmp_path, outcome):
    request = write_run_store_request(tmp_path)
    budget = write_budget_policy(tmp_path, maxActiveSeconds=5)
    started = orchestrator_module.start(tmp_path, request, budget)
    run_id = started["state"]["runId"]
    root = tmp_path / ".ai-sow/work/runs" / run_id
    sequence = len(list((root / "events").glob("*.json"))) + 1
    payload = {"stepKind": "VALIDATE", "outcome": outcome, "startedAtUtc": "2026-09-05T00:00:00Z", "endedAtUtc": "2026-09-05T00:00:05Z"}
    if outcome == "FAILED":
        payload["failureCode"] = "VALIDATION_FAILED"
    write_json(root / "events" / f"{sequence:06d}.json", {
        "runId": run_id, "sequence": sequence, "type": "DETERMINISTIC_STEP_FINISHED", "occurredAtUtc": "2026-09-05T00:00:05Z", "payload": payload,
    })
    waiting = orchestrator_module.run_mode(tmp_path, "resume")
    assert waiting["outcome"] == "WAITING_INPUT", waiting
    assert waiting["activeSeconds"] == 5
    assert not list((root / "actions").glob("*/envelope.json"))
    assert orchestrator_module.run_mode(tmp_path, "resume")["outcome"] == "WAITING_INPUT"
    write_budget_policy(tmp_path, maxActiveSeconds=6)
    resumed = orchestrator_module.run_mode(tmp_path, "resume", budget_policy=budget)
    assert resumed["outcome"] == "ACTIVE", resumed
    assert orchestrator_module.status(tmp_path)["activeSeconds"] == 5


def test_planned_token_guard_actual_initial_request_must_fit_usable_input(tmp_path):
    request = write_run_store_request(tmp_path)
    result = orchestrator_module.run_mode(tmp_path, "start", request=request, budget_policy=write_budget_policy(tmp_path, modelContextLimitTokens=13313))
    assert result["outcome"] == "WAITING_INPUT", result
    assert result["diagnostics"][0]["code"] == "BUDGET_EXHAUSTED"
    root = tmp_path / ".ai-sow/work/runs" / result["state"]["runId"]
    assert not list((root / "actions").glob("*/envelope.json"))


def test_planned_token_guard_strict_reader_rejects_self_consistent_over_capacity_envelope(tmp_path):
    request = write_run_store_request(tmp_path)
    budget = write_budget_policy(tmp_path)
    result = orchestrator_module.run_mode(tmp_path, "start", request=request, budget_policy=budget)
    envelope = copy.deepcopy(result["nextAction"])
    root = tmp_path / ".ai-sow/work/runs" / envelope["runId"]
    policy = json.loads((tmp_path / budget).read_bytes())
    policy["modelContextLimitTokens"] = 13313
    digest = sha256_bytes(canonical_json_bytes(policy))
    write_json(root / "budget-policies" / f"{digest}.json", policy)
    envelope["budgetPolicySha256"] = digest
    write_json(root / "actions" / envelope["actionId"] / "envelope.json", envelope)
    for path in (root / "events").glob("*.json"):
        event = json.loads(path.read_bytes())
        if event["type"] == "RUN_BUDGET_POLICY_PUBLISHED":
            event["payload"]["budgetPolicySha256"] = digest
        elif event["type"] == "ACTION_ISSUED":
            event["payload"]["envelopeSha256"] = sha256_bytes(canonical_json_bytes(envelope))
        write_json(path, event)
    before = managed_snapshot(tmp_path)
    observed = orchestrator_module.status(tmp_path)
    assert observed["outcome"] == "BLOCKED", observed
    assert "budgetVarianceTokens" not in observed
    assert managed_snapshot(tmp_path) == before


def test_planned_token_guard_actual_repair_packet_must_fit_original_capacity(tmp_path):
    request = write_run_store_request(tmp_path)
    limits = dict(modelContextLimitTokens=20000, outputReserveTokens=2000,
        hydrateReserveTokens=1000, safetyMarginTokens=1000)
    budget = write_budget_policy(tmp_path, **limits)
    started = orchestrator_module.run_mode(tmp_path, "start", request=request, budget_policy=budget)
    assert started['outcome'] == 'ACTIVE', started
    action = started['nextAction']
    ProjectFiles.open(tmp_path).publish_new(action['resultPath'], b'{' + b'x' * 30000)
    write_json(tmp_path / 'execution.json', execution_facts())
    result = orchestrator_module.run_mode(tmp_path, 'submit', action_id=action['actionId'],
        result=action['resultPath'], execution='execution.json')
    assert result['outcome'] == 'WAITING_INPUT', result
    root = tmp_path / '.ai-sow/work/runs' / action['runId']
    assert len(list((root/'actions').glob('*/envelope.json'))) == 1
    assert json.loads((root/'actions'/action['actionId']/'record.json').read_bytes())['failureKind'] == 'INVALID_JSON'
    write_budget_policy(tmp_path, **limits, maxPlannedTokens=2000000)
    assert orchestrator_module.run_mode(tmp_path, 'resume', budget_policy=budget)['outcome'] == 'WAITING_INPUT'



def test_planned_token_guard_independent_reads_revalidate_changed_schema(tmp_path, monkeypatch):
    import action_ledger
    from test_intake import write_next_request

    skill = tmp_path / "skill"
    shutil.copytree(SKILL_ROOT, skill)
    monkeypatch.setattr(orchestrator_module, "SKILL_ROOT", skill)
    monkeypatch.setattr(action_ledger, "SKILL_ROOT", skill)
    project = tmp_path / "project"
    project.mkdir()
    # Prepare one current action without entering the legacy Scope pipeline.
    request = write_next_request(project, include_demos=True).name
    assert orchestrator_module.run_mode(project, "start", request=request, budget_policy=write_budget_policy(project))["outcome"] == "ACTIVE"
    before = managed_snapshot(project)
    assert orchestrator_module.status(project)["outcome"] == "ACTIVE"
    assert managed_snapshot(project) == before
    schema_path = skill / "contracts/action.schema.json"
    schema = json.loads(schema_path.read_bytes())
    write_json(schema_path, {**schema, "not": {}})
    observed = orchestrator_module.status(project)
    assert observed["outcome"] == "BLOCKED", observed
    assert "budgetVarianceTokens" not in observed
    assert managed_snapshot(project) == before


@pytest.mark.parametrize("boundary", ["source", "no_action", "zero_action_wait", "replacement", "history", "old_issuance", "new_issuance"])
def test_public_budget_policy_seam_independent_reads_revalidate_budget_schema(tmp_path, monkeypatch, boundary):
    import action_ledger
    from test_intake import write_next_request

    skill = tmp_path / "skill"
    shutil.copytree(SKILL_ROOT, skill)
    monkeypatch.setattr(orchestrator_module, "SKILL_ROOT", skill)
    monkeypatch.setattr(action_ledger, "SKILL_ROOT", skill)
    project = tmp_path / "project"
    project.mkdir()
    # Prepare one current action without entering the legacy Scope pipeline.
    request = write_next_request(project, include_demos=True).name
    maximum = 1 if boundary == "zero_action_wait" else 1000000
    budget = write_budget_policy(project, maxPlannedTokens=maximum)
    if boundary in {"replacement", "zero_action_wait", "old_issuance", "new_issuance"}:
        started = orchestrator_module.run_mode(project, "start", request=request, budget_policy=budget)
    else:
        started = orchestrator_module.start(project, request, budget)
    expected_outcome = "WAITING_INPUT" if boundary == "zero_action_wait" else "ACTIVE"
    assert started["outcome"] == expected_outcome
    root = project / ".ai-sow/work/runs" / started["state"]["runId"]
    if boundary in {"replacement", "history", "old_issuance", "new_issuance"}:
        maximum = 2000000
        write_budget_policy(project, maxPlannedTokens=maximum)
        assert orchestrator_module.resume(project, budget)["outcome"] == "ACTIVE"
        if boundary == "history":
            write_budget_policy(project, maxPlannedTokens=3000000)
            assert orchestrator_module.resume(project, budget)["outcome"] == "ACTIVE"
    if boundary in {"old_issuance", "new_issuance"}:
        write_json(project / "failure.json", execution_facts(status="FAILED"))
        retried = orchestrator_module.run_mode(project, "submit", action_id=started["nextAction"]["actionId"], execution="failure.json")
        assert retried["outcome"] == "ACTIVE"
        assert retried["nextAction"]["budgetPolicySha256"] != started["nextAction"]["budgetPolicySha256"]
        assert orchestrator_module.read_provider_request(project, retried["nextAction"]["actionId"])
        maximum = 1000000 if boundary == "old_issuance" else 2000000
    envelopes = list((root / "actions").glob("*/envelope.json"))
    assert len(envelopes) == (2 if boundary in {"old_issuance", "new_issuance"} else 1 if boundary == "replacement" else 0)
    if envelopes:
        original_policy_hash = started["nextAction"]["budgetPolicySha256"]
        assert json.loads((root / "budget-policies" / f"{original_policy_hash}.json").read_bytes())["maxPlannedTokens"] == 1000000
    before = managed_snapshot(project)
    assert orchestrator_module.status(project)["outcome"] == expected_outcome
    assert managed_snapshot(project) == before
    schema_path = skill / "contracts/run-budget-policy.schema.json"
    schema = json.loads(schema_path.read_bytes())
    write_json(schema_path, {**schema, "not": {"properties": {"maxPlannedTokens": {"const": maximum}}, "required": ["maxPlannedTokens"]}})
    observed = (
        orchestrator_module.start(project, request, budget)
        if boundary == "source"
        else orchestrator_module.status(project)
    )
    assert observed["outcome"] == "BLOCKED", observed
    assert observed["diagnostics"][0]["code"] == "RUN_BUDGET_POLICY_INVALID"
    assert "budgetVarianceTokens" not in observed
    assert "activeSeconds" not in observed
    if boundary in {"old_issuance", "new_issuance"}:
        with pytest.raises(ProjectIOError) as invalid_request:
            orchestrator_module.read_provider_request(project, retried["nextAction"]["actionId"])
        assert invalid_request.value.code == "RUN_BUDGET_POLICY_INVALID"
    assert managed_snapshot(project) == before


def test_planned_token_guard_rejects_rehashed_false_estimate_before_observation(tmp_path):
    request = write_run_store_request(tmp_path)
    result = orchestrator_module.run_mode(tmp_path, "start", request=request, budget_policy=write_budget_policy(tmp_path))
    envelope = copy.deepcopy(result["nextAction"])
    envelope["executionLimits"]["estimatedInputTokens"] = 1
    root = tmp_path / ".ai-sow/work/runs" / envelope["runId"]
    write_json(root / "actions" / envelope["actionId"] / "envelope.json", envelope)
    for path in (root / "events").glob("*.json"):
        event = json.loads(path.read_bytes())
        if event["type"] == "ACTION_ISSUED":
            event["payload"]["envelopeSha256"] = sha256_bytes(canonical_json_bytes(envelope))
            write_json(path, event)
    before = managed_snapshot(tmp_path)
    observed = orchestrator_module.status(tmp_path)
    assert observed["outcome"] == "BLOCKED", observed
    assert "budgetVarianceTokens" not in observed
    assert managed_snapshot(tmp_path) == before


@pytest.mark.parametrize("mutation", ["late", "unpublished"])
def test_public_budget_policy_seam_resume_rejects_invalid_issuance_policy(tmp_path, mutation):
    request = write_run_store_request(tmp_path)
    result = orchestrator_module.run_mode(
        tmp_path, "start", request=request, budget_policy=write_budget_policy(tmp_path)
    )
    envelope = result["nextAction"]
    root = tmp_path / ".ai-sow/work/runs" / envelope["runId"]
    event_paths = sorted((root / "events").glob("*.json"))
    events = [json.loads(path.read_bytes()) for path in event_paths]
    if mutation == "late":
        events.reverse()
        for index, (path, event) in enumerate(zip(event_paths, events, strict=True), 1):
            write_json(path, {**event, "sequence": index})
    else:
        envelope = {**envelope, "budgetPolicySha256": "f" * 64}
        write_json(root / "actions" / envelope["actionId"] / "envelope.json", envelope)
        issued = events[-1]
        issued["payload"]["envelopeSha256"] = sha256_bytes(canonical_json_bytes(envelope))
        write_json(event_paths[-1], issued)
    before = managed_snapshot(tmp_path)
    resumed = orchestrator_module.resume(tmp_path)
    assert resumed["outcome"] == "BLOCKED"
    assert managed_snapshot(tmp_path) == before


def test_public_budget_policy_seam_replacement_retry_preserves_old_envelope(tmp_path):
    request = write_run_store_request(tmp_path)
    budget = write_budget_policy(tmp_path)
    first = orchestrator_module.run_mode(tmp_path, "start", request=request, budget_policy=budget)["nextAction"]
    envelope_path = tmp_path / action_artifact_path(first, "envelope.json")
    original_bytes = envelope_path.read_bytes()
    write_budget_policy(tmp_path, maxPlannedTokens=2000000)
    assert orchestrator_module.resume(tmp_path, budget)["outcome"] == "ACTIVE"
    write_json(tmp_path / "failure.json", execution_facts(status="FAILED"))
    result = orchestrator_module.run_mode(
        tmp_path, "submit", action_id=first["actionId"], execution="failure.json"
    )
    assert result["outcome"] == "ACTIVE", result
    retry = result["nextAction"]
    assert retry["budgetPolicySha256"] == sha256_bytes((tmp_path / budget).read_bytes())
    assert retry["logicalWorkId"] == first["logicalWorkId"]
    assert retry["attempt"] == 2
    assert envelope_path.read_bytes() == original_bytes


@pytest.mark.parametrize('interruption', ['initial', 'partial', 'retry'])
def test_public_budget_policy_seam_replacement_finishes_frozen_issuance_first(tmp_path, monkeypatch, interruption):
    request = write_run_store_request(tmp_path)
    limits = {}
    if interruption == 'partial':
        value = json.loads((tmp_path/request).read_bytes())
        source = tmp_path/value['sources'][0]['path']
        source.write_text('\n\n'.join('边界'+str(i)+' '+' '.join('field'+str(n) for n in range(4000)) for i in range(3)))
        value['sources'][0]['expectedSha256'] = sha256_bytes(source.read_bytes())
        write_json(tmp_path/request, value)
        limits = dict(maxConcurrency=2, modelContextLimitTokens=60000, outputReserveTokens=2000,
            hydrateReserveTokens=1000, safetyMarginTokens=1000, referenceOverheadTokens=256)
    budget = write_budget_policy(tmp_path, **limits)
    if interruption == 'retry':
        first = orchestrator_module.run_mode(tmp_path, 'start', request=request, budget_policy=budget)['nextAction']
        write_json(tmp_path/'completion.json', execution_facts(status='FAILED'))
    original = ProjectFiles.publish_new
    envelopes = 0
    def fail_issuance(files, path, payload):
        nonlocal envelopes
        if path.endswith('/envelope.json'): envelopes += 1
        if (interruption == 'partial' and path.endswith('/envelope.json') and envelopes == 2
                or interruption != 'partial' and '/events/' in path and json.loads(payload)['type'] == 'ACTION_ISSUED'):
            raise OSError('injected frozen issuance failure')
        return original(files, path, payload)
    with monkeypatch.context() as fault:
        fault.setattr(ProjectFiles, 'publish_new', fail_issuance)
        interrupted = (orchestrator_module.run_mode(tmp_path, 'submit', action_id=first['actionId'], execution='completion.json')
            if interruption == 'retry' else orchestrator_module.run_mode(tmp_path, 'start', request=request, budget_policy=budget))
    assert interrupted['outcome'] == 'BLOCKED', interrupted
    root = tmp_path/'.ai-sow/work/runs'/active_marker(tmp_path)['runId']
    frozen = {path: path.read_bytes() for path in (root/'actions').glob('*/envelope.json')}
    plans = {path: path.read_bytes() for path in (root/'stages/SCOPE/plans').glob('*.json')}
    write_budget_policy(tmp_path, **limits, maxPlannedTokens=2000000)
    result = orchestrator_module.run_mode(tmp_path, 'resume', budget_policy=budget)
    assert result['outcome'] == 'ACTIVE', result
    assert all(path.read_bytes() == payload for path, payload in frozen.items())
    assert {path: path.read_bytes() for path in (root/'stages/SCOPE/plans').glob('*.json')} == plans
    events = [json.loads(path.read_bytes()) for path in sorted((root/'events').glob('*.json'))]
    assert events[0]['type'] == events[-1]['type'] == 'RUN_BUDGET_POLICY_PUBLISHED'
    issued = [event['payload']['envelopeSha256'] for event in events if event['type'] == 'ACTION_ISSUED']
    assert len(issued) == len(set(issued)) == len(list((root/'actions').glob('*/envelope.json')))
    if interruption == 'partial': assert len(result['nextAction']['actions']) == 2



def test_public_parser_exposes_exact_host_neutral_operations() -> None:
    parser = orchestrator_module._parser()
    mode_action = next(
        action for action in parser._actions if action.dest == "mode"
    )
    assert tuple(mode_action.choices) == (
        "start",
        "submit",
        "hydrate",
        "resume",
        "approve",
        "abandon",
        "status",
    )


def test_public_dispatch_rejects_retired_stage_mode(tmp_path: Path) -> None:
    result = orchestrator_module.run_mode(tmp_path, "prepare")

    assert result["outcome"] == "BLOCKED"
    assert result["diagnostics"][0]["code"] == "CLI_MODE_INVALID"


def test_source_role_and_hash_contract_rejects_tampering_and_greenfield_prior_sow(
    tmp_path: Path,
) -> None:
    request_path = write_run_store_request(tmp_path)
    (tmp_path / "inputs/primary-prd.md").write_text("tampered", encoding="utf-8")
    tampered = orchestrator_module.start(tmp_path, request_path, write_budget_policy(tmp_path))
    assert tampered["outcome"] == "BLOCKED"
    assert tampered["diagnostics"][0]["code"] == "SOURCE_HASH_MISMATCH"

    request_path = write_run_store_request(tmp_path, name="prior")
    request = json.loads((tmp_path / request_path).read_text(encoding="utf-8"))
    prior_path = tmp_path / "inputs/prior.xlsx"
    prior_path.write_bytes((SKILL_ROOT / "assets/sow-template.xlsx").read_bytes())
    request["sources"].append({
        "sourceId": "prior-main", "role": "PRIOR_SOW", "path": "inputs/prior.xlsx",
        "expectedSha256": sha256_bytes(prior_path.read_bytes()),
    })
    write_json(tmp_path / request_path, request)
    forbidden = orchestrator_module.start(tmp_path, request_path, write_budget_policy(tmp_path))
    assert forbidden["outcome"] == "BLOCKED"
    assert forbidden["diagnostics"][0]["code"] == "GREENFIELD_PRIOR_SOW_FORBIDDEN"


@pytest.mark.parametrize(
    "invalid_path",
    (["inputs/demo/index.html"], {"value": "inputs/demo/index.html"}),
)
def test_public_demo_bundle_request_reports_non_string_file_path(
    tmp_path: Path,
    invalid_path: object,
) -> None:
    request_path = write_run_store_request(tmp_path)
    request = json.loads((tmp_path / request_path).read_text(encoding="utf-8"))
    request["demo"] = {
        "entrypoint": "inputs/demo/index.html",
        "files": [
            {
                "sourceId": "demo-index",
                "role": "DEMO",
                "path": invalid_path,
                "expectedSha256": "a" * 64,
            }
        ],
    }
    write_json(tmp_path / request_path, request)

    result = orchestrator_module.start(tmp_path, request_path, write_budget_policy(tmp_path))

    assert result["outcome"] == "BLOCKED"
    assert {item["code"] for item in result["diagnostics"]} >= {"CONTRACT_INVALID"}


def test_public_start_emits_and_accepts_path_locked_fresh_action(tmp_path):
    from stage_driver import stage_result
    started = orchestrator_module.run_mode(tmp_path, 'start', request=write_run_store_request(tmp_path), budget_policy=write_budget_policy(tmp_path))
    assert started['outcome'] == 'ACTIVE'
    actions = started['nextAction'].get('actions', [started['nextAction']])
    files = ProjectFiles.open(tmp_path)
    for action in actions:
        assert action['contract'] == 'ai-sow-action-v3' and action['actionContractId'] == 'SOURCE_SCAN-v1'
        request = json.loads(orchestrator_module.read_provider_request(tmp_path, action['actionId']))
        assert [m['role'] for m in request['messages']] == ['system', 'user']
        packet = files.read_json(action['packetPath'])
        assert json.loads(request['messages'][1]['content']) == packet
        raw = canonical_json_bytes(stage_result('SOURCE_SCAN', packet))
        files.publish_new(action['resultPath'], raw)
        execution_path = f"execution-{action['actionId']}.json"
        write_json(tmp_path / execution_path, execution_facts())
        recorded = orchestrator_module.run_mode(tmp_path, 'submit', action_id=action['actionId'], result=action['resultPath'], execution=execution_path)
        assert recorded['outcome'] == 'ACTIVE', recorded
        ledger = orchestrator_module._load_action_ledger(files, recorded['state']['runId'])
        record = next(item for item in ledger.attempt_records.values()
            if ledger.envelopes_by_sha256[item.envelope_sha256].value['actionId'] == action['actionId'])
        assert record.outcome == 'SUCCEEDED' and record.raw_sha256 == sha256_bytes(raw)
    following = recorded['nextAction'].get('actions', [recorded['nextAction']])
    assert {item['actionContractId'] for item in following} == {'SOURCE_AUDIT-v1'}


def write_run_store_request(project: Path, name: str = "primary") -> str:
    inputs = project / "inputs"
    inputs.mkdir(exist_ok=True)
    prd_path = inputs / f"{name}-prd.md"
    hld_path = inputs / f"{name}-hld.md"
    prd_path.write_text(
        f"# {name} 范围\n\n用户提交退款并看到处理结果。\n",
        encoding="utf-8",
    )
    hld_path.write_text(
        f"# {name} 目标架构\n\n门户调用退款服务并支持生产回退。\n",
        encoding="utf-8",
    )
    path = project / f"{name}-request.json"
    write_json(
        path,
        {
            "contract": "ai-sow-generate-request-v3",
            "project": {
                "projectId": "project-run-store",
                "name": "Run Store 测试项目",
                "plannedEffectiveDate": "2026-10-01",
            },
            "mode": "GREENFIELD",
            "responsibilityBoundaries": [
                {
                    "responsibilityBoundaryId": "responsibility-vendor",
                    "party": "VENDOR",
                    "name": "供应商交付责任",
                    "responsibilities": ["实现并验证范围内能力"],
                }
            ],
            "sources": [
                {
                    "sourceId": f"prd-{name}",
                    "role": "PRD",
                    "path": prd_path.relative_to(project).as_posix(),
                    "expectedSha256": sha256_bytes(prd_path.read_bytes()),
                },
                {
                    "sourceId": f"hld-{name}",
                    "role": "HLD",
                    "path": hld_path.relative_to(project).as_posix(),
                    "expectedSha256": sha256_bytes(hld_path.read_bytes()),
                },
            ],
            "questions": [],
            "questionnaireAnswers": [],
            "declaredChangeContext": None,
        },
    )
    return path.name


def managed_snapshot(project: Path) -> dict[str, bytes]:
    root = project / ".ai-sow"
    if not root.exists():
        return {}
    return {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def active_marker(project: Path) -> dict[str, object]:
    return json.loads(
        (project / ".ai-sow/work/active-run.json").read_text(encoding="utf-8")
    )


def filesystem_snapshot(project: Path) -> dict[str, tuple[bytes | None, int]]:
    return {
        path.relative_to(project).as_posix(): (
            path.read_bytes() if path.is_file() else None,
            path.stat().st_mtime_ns,
        )
        for path in project.rglob("*")
    }


@pytest.mark.parametrize(
    "proof",
    (
        "missing",
        "duplicate",
        "wrong_run",
        "mismatch",
        "raw_only",
        "normalized_only",
        "record_only",
        "envelope_missing",
    ),
)
@pytest.mark.parametrize("consumer", ("resume", "submit"))
def test_issued_proof_required_before_public_owner_consumption(
    tmp_path: Path, proof: str, consumer: str
) -> None:
    from test_e2e import _prepare_project, _submission

    started = orchestrator_module.run_mode(
        tmp_path, "start", budget_policy=write_budget_policy(tmp_path), request=_prepare_project(tmp_path)
    )
    next_action = started["nextAction"]
    actions = next_action.get("actions", [next_action])
    assert len(actions) == 1
    action = actions[0]
    files = ProjectFiles.open(tmp_path)
    write_json(
        tmp_path / action["resultPath"],
        _submission(action, files.read_json(action["packetPath"])),
    )
    assert (
        orchestrator_module.submit(
            tmp_path, action["actionId"], completion_for(files, action)
        )["outcome"]
        == "RECORDED"
    )
    event_path = next((tmp_path / ".ai-sow/work/runs").glob("*/events/000002.json"))
    event = json.loads(event_path.read_bytes())
    if proof in {"missing", "raw_only", "normalized_only", "record_only"}:
        event_path.unlink()
        if proof != "missing":
            retain = {
                "raw_only": "raw-output.bin",
                "normalized_only": "normalized-result.json",
                "record_only": "record.json",
            }[proof]
            for name in ("record.json", "raw-output.bin", "normalized-result.json"):
                if name != retain:
                    (tmp_path / action_artifact_path(action, name)).unlink()
    elif proof == "envelope_missing":
        (tmp_path / action_artifact_path(action, "envelope.json")).unlink()
    elif proof == "duplicate":
        write_json(event_path.with_name("000003.json"), {**event, "sequence": 3})
    elif proof == "wrong_run":
        write_json(event_path, {**event, "runId": "run-000000000001"})
    else:
        event["payload"]["envelopeSha256"] = "0" * 64
        write_json(event_path, event)
    arguments = {}
    if consumer == "submit":
        write_json(tmp_path / "execution.json", execution_facts())
        arguments = {
            "action_id": action["actionId"],
            "result": action["resultPath"],
            "execution": "execution.json",
        }
    before = managed_snapshot(tmp_path)

    result = orchestrator_module.run_mode(tmp_path, consumer, **arguments)

    assert result["outcome"] == "BLOCKED", result
    expected_code = (
        "PROJECT_PATH_MISSING"
        if consumer == "submit" and proof == "envelope_missing"
        else "ACTION_ISSUANCE_PROOF_INVALID"
    )
    assert result["diagnostics"][0]["code"] == expected_code
    assert managed_snapshot(tmp_path) == before


@pytest.mark.parametrize("mode", ("resume", "submit", "hydrate"))
def test_unissued_action_cannot_be_consumed_before_public_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    started = orchestrator_module.run_mode(
        tmp_path, "start", budget_policy=write_budget_policy(tmp_path), request=write_run_store_request(tmp_path)
    )
    next_action = started["nextAction"]
    action = next_action.get("actions", [next_action])[0]
    files = ProjectFiles.open(tmp_path)
    if mode == "resume":
        next((tmp_path / ".ai-sow/work/runs").glob("*/events/000002.json")).unlink()
        arguments = {}
    else:
        write_json(tmp_path / "failure.json", execution_facts(status="FAILED"))
        original = ProjectFiles.publish_new

        def fail_retry_event(files, path, payload):
            if path.endswith("/events/000003.json"):
                raise OSError("injected retry event failure")
            return original(files, path, payload)

        with monkeypatch.context() as fault:
            fault.setattr(ProjectFiles, "publish_new", fail_retry_event)
            interrupted = orchestrator_module.run_mode(
                tmp_path,
                "submit",
                action_id=action["actionId"],
                execution="failure.json",
            )
        assert interrupted["outcome"] == "BLOCKED"
        retry = next(
            json.loads(path.read_bytes())
            for path in (tmp_path / ".ai-sow/work/runs").glob(
                "*/actions/*/envelope.json"
            )
            if json.loads(path.read_bytes())["attempt"] == 2
        )
        arguments = {"action_id": retry["actionId"]}
        if mode == "submit":
            write_json(tmp_path / "retry-failure.json", execution_facts(status="LATE"))
            arguments["execution"] = "retry-failure.json"
        else:
            arguments["evidence_ids"] = [
                files.read_json(retry["packetPath"])["workItems"][0]["payload"]["evidenceIds"][0]
            ]
    before = managed_snapshot(tmp_path)

    result = orchestrator_module.run_mode(tmp_path, mode, **arguments)

    assert result["outcome"] == "BLOCKED", result
    assert result["diagnostics"][0]["code"] == "ACTION_ISSUANCE_PROOF_INVALID"
    assert managed_snapshot(tmp_path) == before


@pytest.mark.parametrize("failure_kind", (None, "INPUT_REQUIRED"))
def test_unissued_completion_cannot_change_recovered_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_kind: str | None
) -> None:
    from test_e2e import _prepare_project, _submission

    started = orchestrator_module.run_mode(
        tmp_path, "start", budget_policy=write_budget_policy(tmp_path), request=_prepare_project(tmp_path)
    )
    next_action = started["nextAction"]
    action = next_action.get("actions", [next_action])[0]
    files = ProjectFiles.open(tmp_path)
    arguments = {"action_id": action["actionId"], "execution": "execution.json"}
    facts = execution_facts()
    if failure_kind is None:
        write_json(
            tmp_path / action["resultPath"],
            _submission(action, files.read_json(action["packetPath"])),
        )
        arguments["result"] = action["resultPath"]
    else:
        facts["failureKind"] = failure_kind
        facts["diagnostic"] = {
            "code": "INPUT_NEEDED",
            "path": "/input",
            "subjectIds": [],
        }
    write_json(tmp_path / "execution.json", facts)
    original = ProjectFiles.write_atomic

    def fail_pointer(files, path, payload):
        if path == orchestrator_module.ACTIVE_RUN_PATH:
            raise OSError("injected completion pointer failure")
        return original(files, path, payload)

    with monkeypatch.context() as fault:
        fault.setattr(ProjectFiles, "write_atomic", fail_pointer)
        assert (
            orchestrator_module.run_mode(tmp_path, "submit", **arguments)["outcome"]
            == "BLOCKED"
        )
    # Keep the immutable result; remove its issuance proof from the log fixture.
    event_paths = sorted((tmp_path / ".ai-sow/work/runs").glob("*/events/*.json"))
    for event_path in event_paths:
        if json.loads(event_path.read_bytes())["type"] != "RUN_BUDGET_POLICY_PUBLISHED":
            event_path.unlink()
    before = managed_snapshot(tmp_path)

    result = orchestrator_module.run_mode(tmp_path, "resume")

    assert result["outcome"] == "BLOCKED", result
    assert result["diagnostics"][0]["code"] == "ACTION_ISSUANCE_PROOF_INVALID"
    assert managed_snapshot(tmp_path) == before


def test_unissued_orphan_does_not_become_run_progress(tmp_path: Path) -> None:
    started = orchestrator_module.run_mode(
        tmp_path, "start", budget_policy=write_budget_policy(tmp_path), request=write_run_store_request(tmp_path)
    )
    next_action = started["nextAction"]
    action = next_action.get("actions", [next_action])[0]
    orphan_id = "action-000000000001"
    orphan_root = f".ai-sow/work/runs/{action['runId']}/actions/{orphan_id}"
    orphan = {
        **action,
        "actionId": orphan_id,
        "packetPath": f"{orphan_root}/packet.json",
        "resultPath": f"{orphan_root}/submission.json",
    }
    files = ProjectFiles.open(tmp_path)
    write_json(tmp_path / f"{orphan_root}/envelope.json", orphan)
    files.publish_new(orphan["packetPath"], files.read_bytes(action["packetPath"]))
    before = managed_snapshot(tmp_path)

    resumed = orchestrator_module.run_mode(tmp_path, "resume")

    assert resumed["outcome"] == "ACTIVE", resumed
    assert resumed["nextAction"] == started["nextAction"]
    assert managed_snapshot(tmp_path) == before


def test_issued_envelope_malformed_type_fails_closed(tmp_path: Path) -> None:
    started = orchestrator_module.run_mode(
        tmp_path, "start", budget_policy=write_budget_policy(tmp_path), request=write_run_store_request(tmp_path)
    )
    next_action = started["nextAction"]
    action = next_action.get("actions", [next_action])[0]
    write_json(tmp_path / action_artifact_path(action, "envelope.json"), [])
    before = managed_snapshot(tmp_path)

    result = orchestrator_module.run_mode(tmp_path, "resume")

    assert result["outcome"] == "BLOCKED", result
    assert result["diagnostics"][0]["code"] == "ACTION_ISSUANCE_PROOF_INVALID"
    assert managed_snapshot(tmp_path) == before


@pytest.mark.parametrize(
    "failure_kind,revision,attempt",
    (
        ("EXECUTION", 1, 2),
        ("INVALID_JSON", 2, 1),
        ("INVALID_IR", 2, 1),
    ),
)
@pytest.mark.parametrize("boundary", ("packet.json", "envelope.json", "event"))
def test_issued_retry_recovery_completes_only_derived_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
    revision: int,
    attempt: int,
    boundary: str,
) -> None:
    started = orchestrator_module.run_mode(
        tmp_path, "start", budget_policy=write_budget_policy(tmp_path), request=write_run_store_request(tmp_path)
    )
    next_action = started["nextAction"]
    action = next_action.get("actions", [next_action])[0]
    files = ProjectFiles.open(tmp_path)
    arguments = {"action_id": action["actionId"], "execution": "execution.json"}
    facts = execution_facts(
        status="FAILED" if failure_kind == "EXECUTION" else "SUCCESS"
    )
    if failure_kind != "EXECUTION":
        files.publish_new(
            action["resultPath"], b"{" if failure_kind == "INVALID_JSON" else b"{}"
        )
        arguments["result"] = action["resultPath"]
    write_json(tmp_path / "execution.json", facts)
    original = ProjectFiles.publish_new

    def fail_retry_publication(files, path, payload):
        if (boundary == "event" and path.endswith("/events/000003.json")) or (
            boundary != "event"
            and path.endswith("/" + boundary)
            and f"/actions/{action['actionId']}/" not in path
        ):
            raise OSError("injected retry publication failure")
        return original(files, path, payload)

    with monkeypatch.context() as fault:
        fault.setattr(ProjectFiles, "publish_new", fail_retry_publication)
        assert (
            orchestrator_module.run_mode(tmp_path, "submit", **arguments)["outcome"]
            == "BLOCKED"
        )
    before = managed_snapshot(tmp_path)

    resumed = orchestrator_module.run_mode(tmp_path, "resume")

    assert resumed["outcome"] == "ACTIVE", resumed
    retry = resumed["nextAction"]
    assert (retry["revision"], retry["attempt"]) == (revision, attempt)
    assert retry["logicalWorkId"] == action["logicalWorkId"]
    events = [
        json.loads(path.read_bytes())
        for path in sorted((tmp_path / ".ai-sow/work/runs").glob("*/events/*.json"))
    ]
    assert len(events) == 3
    assert events[2]["payload"] == {
        "actionId": retry["actionId"],
        "logicalWorkId": retry["logicalWorkId"],
        "envelopeSha256": sha256_bytes(canonical_json_bytes(retry)),
    }
    for path, payload in before.items():
        if path != orchestrator_module.ACTIVE_RUN_PATH:
            assert files.read_bytes(path) == payload
    complete = managed_snapshot(tmp_path)
    assert orchestrator_module.run_mode(tmp_path, "resume")["nextAction"] == retry
    assert managed_snapshot(tmp_path) == complete


@pytest.mark.parametrize("boundary", ("reserved", "prepare", "completion"))
def test_single_writer_atomic_recovery_status_never_mutates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    request = write_run_store_request(tmp_path)
    if boundary == "prepare":
        orchestrator_module.start(tmp_path, request, write_budget_policy(tmp_path))
    else:
        if boundary == "completion":
            started = orchestrator_module.run_mode(tmp_path, "start", budget_policy=write_budget_policy(tmp_path), request=request)
            next_action = started["nextAction"]
            action = next_action.get("actions", [next_action])[0]
            write_json(tmp_path / "execution.json", execution_facts(status="FAILED"))
        method = "publish_new" if boundary == "reserved" else "write_atomic"
        original = getattr(ProjectFiles, method)

        def fail_write(files, path, payload):
            if (boundary == "reserved" and path.endswith("/state.json")) or (
                boundary == "completion" and path == orchestrator_module.ACTIVE_RUN_PATH
            ):
                raise OSError("injected atomic failure")
            return original(files, path, payload)

        with monkeypatch.context() as fault:
            fault.setattr(ProjectFiles, method, fail_write)
            result = orchestrator_module.run_mode(
                tmp_path,
                "start" if boundary == "reserved" else "submit",
                **(
                    {"request": request, "budget_policy": write_budget_policy(tmp_path)}
                    if boundary == "reserved"
                    else {
                        "action_id": action["actionId"],
                        "execution": "execution.json",
                    }
                ),
            )
        assert result["outcome"] == "BLOCKED"
    before = filesystem_snapshot(tmp_path)
    for query in (
        orchestrator_module.status,
        lambda root: orchestrator_module.run_mode(root, "status"),
    ):
        observed = query(tmp_path)
        assert observed["outcome"] == "ACTIVE", observed
        assert filesystem_snapshot(tmp_path) == before


@pytest.mark.parametrize("mode", ("start", "resume"))
@pytest.mark.parametrize(
    "boundary",
    ("stage-plan", "packet.json", "envelope.json", "events/000002.json"),
)
def test_single_writer_atomic_recovery_retries_interrupted_issuance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str, boundary: str
) -> None:
    request = write_run_store_request(tmp_path)
    if mode == "resume":
        orchestrator_module.start(tmp_path, request, write_budget_policy(tmp_path))
    arguments = {"request": request, "budget_policy": write_budget_policy(tmp_path)} if mode == "start" else {}
    original = ProjectFiles.publish_new

    def fail_plan(files, path, payload):
        if path.endswith("/" + boundary) or (boundary == "stage-plan" and "/stages/SCOPE/plans/" in path):
            raise OSError("injected plan publication failure")
        return original(files, path, payload)

    with monkeypatch.context() as fault:
        fault.setattr(ProjectFiles, "publish_new", fail_plan)
        interrupted = orchestrator_module.run_mode(tmp_path, mode, **arguments)
    assert interrupted["outcome"] == "BLOCKED"
    before = managed_snapshot(tmp_path)
    marker = active_marker(tmp_path)
    assert orchestrator_module.status(tmp_path)["state"]["runId"] == marker["runId"]

    retried = orchestrator_module.run_mode(tmp_path, mode, **arguments)

    assert retried["outcome"] == "ACTIVE", retried
    assert retried["state"]["wait"] == "MODEL"
    assert retried["state"]["runId"] == marker["runId"]
    envelopes = list((tmp_path / ".ai-sow/work/runs").glob("*/actions/*/envelope.json"))
    assert "budget" not in retried["state"]
    for path, payload in before.items():
        if path != orchestrator_module.ACTIVE_RUN_PATH:
            assert (tmp_path / path).read_bytes() == payload


@pytest.mark.parametrize('conflict', ('binding', 'duplicate', 'candidate'))
def test_single_writer_atomic_recovery_rejects_conflicting_unsealed_group(tmp_path, monkeypatch, conflict):
    request = write_run_store_request(tmp_path)
    original = ProjectFiles.publish_new
    def fail_event(files, path, payload):
        if '/events/' in path and json.loads(payload)['type'] == 'ACTION_ISSUED':
            raise OSError('injected before issuance event')
        return original(files, path, payload)
    with monkeypatch.context() as fault:
        fault.setattr(ProjectFiles, 'publish_new', fail_event)
        result = orchestrator_module.run_mode(tmp_path, 'start', request=request, budget_policy=write_budget_policy(tmp_path))
    assert result['outcome'] == 'BLOCKED'
    root = tmp_path/'.ai-sow/work/runs'/active_marker(tmp_path)['runId']
    plan_path = next((root/'stages/SCOPE/plans').glob('*.json'))
    if conflict == 'binding':
        plan = json.loads(plan_path.read_bytes())
        plan['inputRevisionSha256'] = '0' * 64
        write_json(plan_path, plan)
    elif conflict == 'duplicate':
        (plan_path.parent/('0'*64+'.json')).write_bytes(plan_path.read_bytes())
    else:
        envelope_path = next((root/'actions').glob('*/envelope.json'))
        envelope = json.loads(envelope_path.read_bytes())
        envelope['baseCandidateSha256'] = '0' * 64
        write_json(envelope_path, envelope)
    before = managed_snapshot(tmp_path)
    result = orchestrator_module.run_mode(tmp_path, 'resume')
    assert result['outcome'] == 'BLOCKED', result
    assert result.get('nextAction') is None
    for path, payload in before.items():
        if '/stages/' in path or '/actions/' in path:
            assert (tmp_path/path).read_bytes() == payload



@pytest.mark.parametrize(
    "boundary",
    ("raw-output.bin", "normalized-result.json", "record.json", "active-run.json"),
)
def test_single_writer_atomic_recovery_submit_reuses_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    from test_e2e import _prepare_project, _submission

    request = _prepare_project(tmp_path, "greenfield")
    started = orchestrator_module.run_mode(tmp_path, "start", budget_policy=write_budget_policy(tmp_path), request=request)
    next_action = started["nextAction"]
    action = next_action.get("actions", [next_action])[0]
    files = ProjectFiles.open(tmp_path)
    write_json(
        tmp_path / action["resultPath"],
        _submission(action, files.read_json(action["packetPath"])),
    )
    write_json(tmp_path / "execution.json", execution_facts())
    arguments = {
        "action_id": action["actionId"],
        "result": action["resultPath"],
        "execution": "execution.json",
    }
    method = "write_atomic" if boundary == "active-run.json" else "publish_new"
    original = getattr(ProjectFiles, method)

    def fail_write(files, path, payload):
        if path.endswith("/" + boundary) or (boundary == "stage-plan" and "/stages/SCOPE/plans/" in path):
            raise OSError("injected atomic failure")
        return original(files, path, payload)

    with monkeypatch.context() as fault:
        fault.setattr(ProjectFiles, method, fail_write)
        interrupted = orchestrator_module.run_mode(tmp_path, "submit", **arguments)
    assert interrupted["outcome"] == "BLOCKED", interrupted
    before = managed_snapshot(tmp_path)
    assert orchestrator_module.status(tmp_path)["outcome"] == "ACTIVE"
    retried = orchestrator_module.run_mode(tmp_path, "submit", **arguments)
    assert retried["outcome"] == "ACTIVE", retried
    record_path = action_artifact_path(action, "record.json")
    record = files.read_bytes(record_path)
    assert (
        orchestrator_module.run_mode(tmp_path, "submit", **arguments)["outcome"]
        == "ACTIVE"
    )
    assert files.read_bytes(record_path) == record
    for path, payload in before.items():
        if path != orchestrator_module.ACTIVE_RUN_PATH:
            assert files.read_bytes(path) == payload


def test_single_writer_atomic_recovery_hydrate_reuses_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = write_run_store_request(tmp_path)
    started = orchestrator_module.run_mode(tmp_path, "start", budget_policy=write_budget_policy(tmp_path), request=request)
    next_action = started["nextAction"]
    action = next_action.get("actions", [next_action])[0]
    files = ProjectFiles.open(tmp_path)
    evidence = files.read_json(action["packetPath"])["workItems"][0]["payload"]["evidenceIds"][0]
    original = ProjectFiles.publish_new

    def fail_response(files, path, payload):
        if "/hydrations/" in path:
            raise OSError("injected atomic failure")
        return original(files, path, payload)

    with monkeypatch.context() as fault:
        fault.setattr(ProjectFiles, "publish_new", fail_response)
        result = orchestrator_module.run_mode(
            tmp_path, "hydrate", action_id=action["actionId"], evidence_ids=[evidence]
        )
    assert result["outcome"] == "BLOCKED"
    before = managed_snapshot(tmp_path)
    assert orchestrator_module.status(tmp_path)["outcome"] == "ACTIVE"
    result = orchestrator_module.run_mode(
        tmp_path, "hydrate", action_id=action["actionId"], evidence_ids=[evidence]
    )
    assert result["outcome"] == "HYDRATED"
    hydrated = managed_snapshot(tmp_path)
    assert (
        orchestrator_module.run_mode(
            tmp_path, "hydrate", action_id=action["actionId"], evidence_ids=[evidence]
        )["outcome"]
        == "REUSED"
    )
    assert managed_snapshot(tmp_path) == hydrated
    assert all(hydrated[path] == payload for path, payload in before.items())


@pytest.mark.parametrize(
    "boundary", ("state.json", "input-binding.json", "active-run.json")
)
def test_single_writer_atomic_recovery_start_keeps_reserved_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    from runtime import project_io

    request = write_run_store_request(tmp_path)
    operation = "replace" if boundary == "active-run.json" else "link"
    original = getattr(project_io.os, operation)

    def fail_publication(source, target, *args, **kwargs):
        if Path(target).name == boundary:
            raise OSError("injected atomic publication failure")
        return original(source, target, *args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(project_io.os, operation, fail_publication)
        result = orchestrator_module.run_mode(tmp_path, "start", budget_policy=write_budget_policy(tmp_path), request=request)
    assert result["outcome"] == "BLOCKED"
    marker = active_marker(tmp_path)
    before = filesystem_snapshot(tmp_path)
    assert orchestrator_module.status(tmp_path)["state"]["runId"] == marker["runId"]
    assert filesystem_snapshot(tmp_path) == before
    retried = orchestrator_module.run_mode(tmp_path, "start", budget_policy=write_budget_policy(tmp_path), request=request)
    assert retried["outcome"] == "ACTIVE", retried
    assert retried["state"]["runId"] == marker["runId"]
    assert len(list((tmp_path / ".ai-sow/work/runs").iterdir())) == 1
    for path, (payload, _mtime) in before.items():
        if payload is not None and path != orchestrator_module.ACTIVE_RUN_PATH:
            assert (tmp_path / path).read_bytes() == payload





@pytest.fixture(scope="module")
def reviewed_public_artifact(tmp_path_factory):
    from test_e2e import drive_fixture_host

    project = tmp_path_factory.mktemp("writer-artifact")
    prepared, _ = drive_fixture_host(project)
    return project, prepared


@pytest.mark.e2e
def test_single_writer_atomic_recovery_abandon_replays_persisted_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reviewed_public_artifact
) -> None:
    source, _prepared = reviewed_public_artifact
    shutil.copytree(source, tmp_path, dirs_exist_ok=True)
    original = ProjectFiles.write_atomic
    before = managed_snapshot(tmp_path)

    def fail_pointer(files, path, payload):
        if path == orchestrator_module.ACTIVE_RUN_PATH:
            raise OSError("injected terminal pointer failure")
        return original(files, path, payload)

    with monkeypatch.context() as fault:
        fault.setattr(ProjectFiles, "write_atomic", fail_pointer)
        result = orchestrator_module.run_mode(tmp_path, "abandon")
    assert result["outcome"] == "BLOCKED"
    assert (
        managed_snapshot(tmp_path)[orchestrator_module.ACTIVE_RUN_PATH]
        == before[orchestrator_module.ACTIVE_RUN_PATH]
    )
    assert orchestrator_module.status(tmp_path)["state"]["phase"] == "AWAITING_FINAL_REVIEW"
    interrupted = managed_snapshot(tmp_path)

    retried = orchestrator_module.run_mode(tmp_path, "abandon")

    assert retried["outcome"] == "ABANDONED", retried
    assert not (tmp_path / orchestrator_module.ACTIVE_RUN_PATH).exists()
    for path, payload in interrupted.items():
        if path != orchestrator_module.ACTIVE_RUN_PATH:
            assert (tmp_path / path).read_bytes() == payload


@pytest.mark.parametrize(
    "decision_kind,boundary,expected",
    (
        ("APPROVE", "current", "PUBLISHED"),
        ("APPROVE", "terminal", "REUSED"),
        ("ABANDON", "terminal", "ABANDONED"),
    ),
)
@pytest.mark.e2e
def test_single_writer_atomic_recovery_approve_replays_exact_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reviewed_public_artifact,
    decision_kind: str,
    boundary: str,
    expected: str,
) -> None:
    from test_e2e import _artifact_decision

    source, prepared = reviewed_public_artifact
    shutil.copytree(source, tmp_path, dirs_exist_ok=True)
    extra = (
        {"approvedAt": "2026-09-05T00:00:00Z"}
        if decision_kind == "APPROVE"
        else {"reason": "用户确认本次决定。"}
    )
    write_json(
        tmp_path / "decision.json",
        _artifact_decision(tmp_path, prepared, decision_kind, **extra),
    )
    arguments = {
        "artifact_manifest_sha256": prepared["artifactManifestSha256"],
        "decision": "decision.json",
    }
    method = "write_atomic"
    original = getattr(ProjectFiles, method)

    def fail_write(files, path, payload):
        if boundary == "current" and path == ".ai-sow/current.json":
            raise OSError("injected current pointer failure")
        if boundary == "terminal" and path == orchestrator_module.ACTIVE_RUN_PATH:
            if decision_kind == "APPROVE":
                original(files, path, payload)
            raise OSError("injected terminal pointer failure")
        return original(files, path, payload)

    with monkeypatch.context() as fault:
        fault.setattr(ProjectFiles, method, fail_write)
        result = orchestrator_module.run_mode(tmp_path, "approve", **arguments)
    assert result["outcome"] == "BLOCKED", result
    before = managed_snapshot(tmp_path)
    assert orchestrator_module.status(tmp_path)["outcome"] == "ACTIVE"
    if boundary == "current":
        assert ".ai-sow/current.json" not in before

    retried = orchestrator_module.run_mode(tmp_path, "approve", **arguments)

    assert retried["outcome"] == expected, retried
    for path, payload in before.items():
        if path not in {orchestrator_module.ACTIVE_RUN_PATH, ".ai-sow/current.json"}:
            assert (tmp_path / path).read_bytes() == payload
    assert not (tmp_path / orchestrator_module.ACTIVE_RUN_PATH).exists()


def reserve_marker_again(project: Path) -> dict[str, object]:
    marker = active_marker(project)
    marker.update({"status": "RESERVED", "stateSha256": None})
    write_json(project / ".ai-sow/work/active-run.json", marker)
    return marker


def test_start_creates_one_active_run_and_orthogonal_state(tmp_path: Path) -> None:
    request_path = write_run_store_request(tmp_path)
    result = orchestrator_module.start(tmp_path, request_path, write_budget_policy(tmp_path))

    assert result["outcome"] == "ACTIVE"
    state = result["state"]
    assert (state["route"], state["phase"], state["wait"], state["result"]) == (
        "FULL_COMPILE",
        "PREPARE",
        "NONE",
        None,
    )
    marker = active_marker(tmp_path)
    assert marker["status"] == "ACTIVE"
    assert marker["runId"] == state["runId"]
    assert marker["inputRevisionSha256"] != marker["requestSha256"]
    revision_manifests = list(
        (tmp_path / ".ai-sow/inputs/revisions").glob("*/manifest.json")
    )
    assert len(revision_manifests) == 1
    assert marker["inputRevisionSha256"] == sha256_bytes(
        revision_manifests[0].read_bytes()
    )
    assert marker["stateSha256"] == sha256_bytes(
        (tmp_path / marker["statePath"]).read_bytes()
    )


def test_same_request_start_is_idempotent(tmp_path: Path) -> None:
    request_path = write_run_store_request(tmp_path)
    first = orchestrator_module.start(tmp_path, request_path, write_budget_policy(tmp_path))
    before = managed_snapshot(tmp_path)
    second = orchestrator_module.start(tmp_path, request_path, write_budget_policy(tmp_path))

    assert second == first
    assert managed_snapshot(tmp_path) == before
    assert len(list((tmp_path / ".ai-sow/work/runs").iterdir())) == 1


def test_start_rejects_tampered_bound_input_revision(tmp_path: Path) -> None:
    request_path = write_run_store_request(tmp_path)
    orchestrator_module.start(tmp_path, request_path, write_budget_policy(tmp_path))
    marker = active_marker(tmp_path)
    (tmp_path / marker["inputRevisionPath"]).write_bytes(b"{}\n")

    result = orchestrator_module.resume(tmp_path)

    assert result["outcome"] == "BLOCKED"
    assert [item["code"] for item in result["diagnostics"]] == [
        "RUN_INPUT_REVISION_HASH_MISMATCH"
    ]


def test_different_request_returns_run_in_progress_without_mutation(
    tmp_path: Path,
) -> None:
    first_path = write_run_store_request(tmp_path)
    orchestrator_module.start(tmp_path, first_path, write_budget_policy(tmp_path))
    second_path = write_run_store_request(tmp_path, "different")
    before = managed_snapshot(tmp_path)

    result = orchestrator_module.start(tmp_path, second_path, write_budget_policy(tmp_path))

    assert result["outcome"] == "RUN_IN_PROGRESS"
    assert [item["code"] for item in result["diagnostics"]] == ["RUN_IN_PROGRESS"]
    assert managed_snapshot(tmp_path) == before


def test_candidate_snapshots_are_sequential_immutable_and_hash_named(
    tmp_path: Path,
) -> None:
    request_path = write_run_store_request(tmp_path)
    started = orchestrator_module.start(tmp_path, request_path, write_budget_policy(tmp_path))
    files = ProjectFiles.open(tmp_path)
    run_id = started["state"]["runId"]

    first = orchestrator_module._append_candidate_snapshot(
        files, run_id, {"contract": "ai-sow-model-v1", "nodes": ["one"]}
    )
    first_payload = files.read_bytes(first["path"])
    second = orchestrator_module._append_candidate_snapshot(
        files, run_id, {"contract": "ai-sow-model-v1", "nodes": ["two"]}
    )

    assert Path(first["path"]).name == f"000001-{first['sha256']}.json"
    assert Path(second["path"]).name == f"000002-{second['sha256']}.json"
    assert files.read_bytes(first["path"]) == first_payload
    state = orchestrator_module.status(tmp_path)["state"]
    assert state["currentCandidatePath"] == second["path"]
    assert state["currentCandidateSha256"] == second["sha256"]


def test_abandon_persists_terminal_state_before_clearing_active_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = write_run_store_request(tmp_path)
    orchestrator_module.start(tmp_path, request_path, write_budget_policy(tmp_path))
    marker = active_marker(tmp_path)
    original = ProjectFiles.unlink_exact

    def assert_terminal_before_unlink(
        files: ProjectFiles, relative_path: str, *, expected_payload: bytes
    ) -> bool:
        current_marker = files.read_json(orchestrator_module.ACTIVE_RUN_PATH)
        state = files.read_json(current_marker["statePath"])
        assert state["phase"] == "DONE"
        assert state["wait"] == "NONE"
        assert state["result"] == "ABANDONED"
        return original(files, relative_path, expected_payload=expected_payload)

    monkeypatch.setattr(ProjectFiles, "unlink_exact", assert_terminal_before_unlink)
    result = orchestrator_module.abandon(tmp_path)

    assert result["outcome"] == "ABANDONED"
    assert not (tmp_path / ".ai-sow/work/active-run.json").exists()
    terminal_payload = canonical_json_bytes(result["state"])
    terminal_path = orchestrator_module._state_snapshot_path(
        str(result["state"]["runId"]), sha256_bytes(terminal_payload)
    )
    assert (tmp_path / terminal_path).read_bytes() == terminal_payload


def test_crash_resume_never_starts_a_second_run(tmp_path: Path) -> None:
    request_path = write_run_store_request(tmp_path)
    first = orchestrator_module.start(tmp_path, request_path, write_budget_policy(tmp_path))
    marker = reserve_marker_again(tmp_path)
    (tmp_path / marker["statePath"]).unlink()
    (tmp_path / marker["bindingPath"]).unlink()

    second = orchestrator_module.start(tmp_path, request_path, write_budget_policy(tmp_path))

    assert second["state"]["runId"] == first["state"]["runId"]
    assert len(list((tmp_path / ".ai-sow/work/runs").iterdir())) == 1


def test_crash_after_marker_before_state_recovers_without_second_run(
    tmp_path: Path,
) -> None:
    request_path = write_run_store_request(tmp_path)
    started = orchestrator_module.start(tmp_path, request_path, write_budget_policy(tmp_path))
    marker = reserve_marker_again(tmp_path)
    (tmp_path / marker["statePath"]).unlink()
    (tmp_path / marker["bindingPath"]).unlink()

    resumed = orchestrator_module.resume(tmp_path)

    assert resumed["state"]["runId"] == started["state"]["runId"]
    assert active_marker(tmp_path)["status"] == "ACTIVE"


def test_crash_after_state_before_revision_binding_recovers_deterministically(
    tmp_path: Path,
) -> None:
    request_path = write_run_store_request(tmp_path)
    started = orchestrator_module.start(tmp_path, request_path, write_budget_policy(tmp_path))
    marker = reserve_marker_again(tmp_path)
    state_payload = (tmp_path / marker["statePath"]).read_bytes()
    (tmp_path / marker["bindingPath"]).unlink()

    resumed = orchestrator_module.resume(tmp_path)

    assert resumed["state"] == started["state"]
    assert (tmp_path / marker["statePath"]).read_bytes() == state_payload
    assert (tmp_path / marker["bindingPath"]).is_file()


def test_crash_after_revision_before_state_pointer_recovers_deterministically(
    tmp_path: Path,
) -> None:
    request_path = write_run_store_request(tmp_path)
    started = orchestrator_module.start(tmp_path, request_path, write_budget_policy(tmp_path))
    marker = reserve_marker_again(tmp_path)
    state_payload = (tmp_path / marker["statePath"]).read_bytes()
    binding_payload = (tmp_path / marker["bindingPath"]).read_bytes()

    resumed = orchestrator_module.resume(tmp_path)

    assert resumed["state"] == started["state"]
    assert (tmp_path / marker["statePath"]).read_bytes() == state_payload
    assert (tmp_path / marker["bindingPath"]).read_bytes() == binding_payload
    assert active_marker(tmp_path)["stateSha256"] == sha256_bytes(state_payload)


def test_crash_after_new_state_before_marker_keeps_previous_snapshot_recoverable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_path = write_run_store_request(tmp_path)
    started = orchestrator_module.start(tmp_path, request_path, write_budget_policy(tmp_path))
    files = ProjectFiles.open(tmp_path)
    marker = active_marker(tmp_path)
    previous_state = copy.deepcopy(started["state"])
    next_state = {
        **previous_state,
            "route": "FULL_COMPILE",
    }
    original_write_atomic = ProjectFiles.write_atomic

    def crash_before_marker(
        self: ProjectFiles, relative_path: str, payload: bytes
    ) -> None:
        if relative_path == orchestrator_module.ACTIVE_RUN_PATH:
            raise RuntimeError("simulated marker crash")
        original_write_atomic(self, relative_path, payload)

    monkeypatch.setattr(ProjectFiles, "write_atomic", crash_before_marker)
    with pytest.raises(RuntimeError, match="simulated marker crash"):
        orchestrator_module._write_active_state(files, marker, next_state)
    monkeypatch.setattr(ProjectFiles, "write_atomic", original_write_atomic)

    resumed = orchestrator_module.status(tmp_path)

    assert resumed["outcome"] == "ACTIVE", resumed
    assert resumed["state"] == previous_state


def execution_facts(
    *, accounting_mode: str = "PROVIDER_REPORTED", status: str = "SUCCESS"
) -> dict[str, object]:
    return {
        "failureKind": None if status == "SUCCESS" else "EXECUTION",
        "diagnostic": (
            None
            if status == "SUCCESS"
            else {"code": "HOST_EXECUTION_FAILED", "path": "", "subjectIds": []}
        ),
        "usage": {
            "provenance": accounting_mode,
            "inputTokens": 100,
            "outputTokens": 20,
            "cachedInputTokens": 10,
            "reasoningTokens": None if accounting_mode == "LOCALLY_ESTIMATED" else 4,
        },
        "timing": {
            "startedAtUtc": "2026-09-05T00:00:00Z",
            "endedAtUtc": "2026-09-05T00:00:01Z",
        },
    }


def completion_for(files, envelope, facts=None):
    from models import AttemptCompletion, AttemptDiagnostic, AttemptTiming, Usage

    value = facts if facts is not None else execution_facts()
    usage, timing, diagnostic = value["usage"], value["timing"], value["diagnostic"]
    return AttemptCompletion(
        (
            files.read_bytes(envelope["resultPath"])
            if value["failureKind"] is None
            else None
        ),
        value["failureKind"],
        (
            None
            if diagnostic is None
            else AttemptDiagnostic(
                diagnostic["code"], diagnostic["path"], tuple(diagnostic["subjectIds"])
            )
        ),
        Usage(
            usage["provenance"],
            usage["inputTokens"],
            usage["outputTokens"],
            usage["cachedInputTokens"],
            usage["reasoningTokens"],
        ),
        AttemptTiming(timing["startedAtUtc"], timing["endedAtUtc"]),
    )


def action_artifact_path(envelope: dict[str, object], name: str) -> str:
    return str(Path(str(envelope["resultPath"])).with_name(name))


@pytest.mark.parametrize("delta,outcome", [(-1, "BLOCKED"), (0, "HYDRATED")])
def test_planned_token_guard_hydration_uses_full_canonical_byte_threshold(tmp_path, delta, outcome):
    def start_at(project, reserve):
        project.mkdir()
        request = write_run_store_request(project)
        result = orchestrator_module.run_mode(project, "start", request=request, budget_policy=write_budget_policy(project, hydrateReserveTokens=reserve))
        action = result["nextAction"]
        evidence = json.loads((project / action["packetPath"]).read_bytes())["workItems"][0]["payload"]["evidenceIds"][0]
        return action, evidence

    probe = tmp_path / "probe"
    action, evidence = start_at(probe, 4096)
    hydrated = orchestrator_module.hydrate(probe, action["actionId"], [evidence])
    assert hydrated["outcome"] == "HYDRATED"
    byte_count = len(json.dumps(hydrated, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")) + 1
    project = tmp_path / "project"
    action, evidence = start_at(project, byte_count + delta)
    before = managed_snapshot(project)
    result = orchestrator_module.hydrate(project, action["actionId"], [evidence])
    assert result["outcome"] == outcome, result
    if outcome == "BLOCKED":
        assert result["diagnostics"][0]["code"] == "ACTION_HYDRATION_LIMIT_EXCEEDED"
        assert managed_snapshot(project) == before
    else:
        assert len(canonical_json_bytes(result)) == byte_count
        after = managed_snapshot(project)
        assert orchestrator_module.hydrate(project, action["actionId"], [evidence])["outcome"] == "REUSED"
        assert managed_snapshot(project) == after


@pytest.mark.parametrize(
    ("failure_kind", "outcome", "stored_result"),
    [
        ("INPUT_REQUIRED", "WAITING_INPUT", None),
        ("CONTRACT_GAP", "CONTRACT_UNSUPPORTED", "CONTRACT_UNSUPPORTED"),
        ("OWNER_BUG", "OWNER_FIX_REQUIRED", "MANUAL_REVIEW_REQUIRED"),
        ("SYSTEM", "SYSTEM_FAILED", "SYSTEM_FAILED"),
    ],
)
def test_public_non_retry_attempt_routes_and_wait_closure(
    tmp_path, failure_kind, outcome, stored_result
):
    from models import RunEvent
    from run_events import validate_run_event_log

    envelope = orchestrator_module.run_mode(tmp_path, 'start', request=write_run_store_request(tmp_path),
        budget_policy=write_budget_policy(tmp_path))['nextAction']
    files, run_id = ProjectFiles.open(tmp_path), envelope['runId']
    initial_phase = orchestrator_module.status(tmp_path)["state"]["phase"]
    completion = execution_facts(status="FAILED")
    completion["failureKind"] = failure_kind
    completion["diagnostic"] = {
        "code": "FIXTURE_STOP",
        "path": "/source",
        "subjectIds": ["source-1"],
    }
    write_json(tmp_path / "completion.json", completion)
    result = orchestrator_module.run_mode(
        tmp_path, "submit", action_id=envelope["actionId"], execution="completion.json"
    )
    assert result["outcome"] == outcome, result
    assert result["diagnostics"][0]["code"] == "FIXTURE_STOP"
    assert result["diagnostics"][0]["subjectIds"] == ["source-1"]
    assert result["state"]["result"] == stored_result
    assert result["state"]["expectedActionIds"] == []
    assert result["state"]["phase"] == (
        initial_phase if failure_kind == "INPUT_REQUIRED" else "DONE"
    )
    assert result["state"]["wait"] == (
        "INPUT" if failure_kind == "INPUT_REQUIRED" else "NONE"
    )
    action_root = tmp_path / f".ai-sow/work/runs/{run_id}/actions"
    record_path = tmp_path / action_artifact_path(envelope, "record.json")
    saved = record_path.read_bytes()
    for mode in ("status", "resume", "status"):
        recovered = orchestrator_module.run_mode(tmp_path, mode)
        assert recovered["outcome"] == outcome
        assert recovered["diagnostics"] == result["diagnostics"]
        assert len(list(action_root.glob("*/envelope.json"))) == 1
        assert record_path.read_bytes() == saved
    if failure_kind == "INPUT_REQUIRED":

        def read_events():
            values = [
                json.loads(path.read_bytes())
                for path in sorted(
                    (tmp_path / f".ai-sow/work/runs/{run_id}/events").glob("*.json")
                )
            ]
            return [
                RunEvent(
                    value["runId"],
                    value["sequence"],
                    value["type"],
                    value["occurredAtUtc"],
                    value["payload"],
                )
                for value in values
            ]

        validate_run_event_log(read_events())
        assert (
            sum(event.type == "WAITING_INPUT_ENTERED" for event in read_events()) == 1
        )
        assert (
            orchestrator_module.run_mode(tmp_path, "abandon")["outcome"] == "ABANDONED"
        )
        events = read_events()
        validate_run_event_log(events)
        assert [
            event.payload["resolutionKind"]
            for event in events
            if event.type == "WAITING_INPUT_EXITED"
        ] == ["ABANDONED"]


def test_artifact_promotion_gate_rejects_unsealed_or_external_inputs(tmp_path):
    result=orchestrator_module.prepare_artifact({'runId':'unsealed'},ProjectFiles.open(tmp_path),
        template_path=SKILL_ROOT/'assets/sow-template.xlsx')
    assert result['outcome']=='BLOCKED'
    assert not (tmp_path/'.ai-sow/current.json').exists()
    assert not list(tmp_path.glob('.ai-sow/work/runs/*/artifacts/*/artifact-manifest.json'))


@pytest.mark.parametrize(
    ("decision_kind", "extra", "expected_outcome"),
    [
        (
            "EXCLUDE_DEFAULT_AUTOMATION",
            {
                "excludedPolicyInstanceIds": ["policy-instance-sit"],
                "reason": "客户明确排除默认 SIT 自动化。",
            },
            "BLOCKED",
        ),
        ("ABANDON", {"reason": "用户终止本轮。"}, "ABANDONED"),
    ],
)
def test_new_material_requires_new_run_artifact_decisions_never_write_approval_generation_or_current(
    tmp_path: Path,
    decision_kind: str,
    extra: dict[str, object],
    expected_outcome: str,
) -> None:
    # Decision boundary only: abandonment does not need workbook contents.
    project = tmp_path
    files = ProjectFiles.open(project)
    from test_contracts import artifact_manifest_sample
    manifest=artifact_manifest_sample();manifest['runId']='run-decision-boundary'
    payload = canonical_json_bytes(manifest)
    digest = sha256_bytes(payload)
    relative = f".ai-sow/work/runs/{manifest['runId']}/artifacts/000001-{digest}/artifact-manifest.json"
    files.publish_new(relative, payload)
    prepared = {"artifactManifestPath": relative, "artifactManifestSha256": digest}
    decision = {
        "contract": "ai-sow-approval-v1",
        "runId": manifest["runId"],
        "artifactManifestSha256": prepared["artifactManifestSha256"],
        "reviewDecisionSha256": manifest["reviewDecisionSha256"],
        "candidateSha256": manifest["candidateSha256"],
        "sourceManifestSha256": manifest["sourceManifestSha256"],
        "templateSha256": manifest["templateSha256"],
        "effectivePolicyDecisionSha256": manifest[
            "effectivePolicyDecisionSha256"
        ],
        "decision": decision_kind,
        **extra,
    }
    write_json(project / "decision.json", decision)

    result = orchestrator_module.approve(
        project,
        prepared["artifactManifestSha256"],
        "decision.json",
    )

    assert result["outcome"] == expected_outcome
    artifact_root = Path(prepared["artifactManifestPath"]).parent
    assert not (project / artifact_root / "approval.json").exists()
    assert not (project / ".ai-sow/current.json").exists()
    assert not (project / ".ai-sow/generations").exists()
    if decision_kind == "EXCLUDE_DEFAULT_AUTOMATION":
        assert result["diagnostics"][0]["code"] == "APPROVAL_INVALID"
        assert not (project / ".ai-sow/work/runs" / manifest["runId"] / "decisions").exists()

    before_replay = managed_snapshot(project)
    assert orchestrator_module.approve(project, digest, "decision.json") == result
    assert managed_snapshot(project) == before_replay
    if decision_kind == "ABANDON":
        stale = orchestrator_module.approve(project, digest)
        assert stale["diagnostics"][0]["code"] == "ARTIFACT_MANIFEST_STALE"


def test_no_stage_approval_all_three_owners_complete_with_one_materialization_each(tmp_path,monkeypatch):
    monkeypatch.setattr(orchestrator_module, '_advance_artifact', lambda files,state: {'outcome':'ACTIVE','state':state,'nextAction':None})
    from stage_driver import stage_result
    response=orchestrator_module.run_mode(tmp_path,'start',request=write_run_store_request(tmp_path),budget_policy=write_budget_policy(tmp_path))
    contracts=[]
    for _ in range(60):
        assert response['outcome']=='ACTIVE',response
        if response['state']['phase']=='DRAFT': break
        actions=response['nextAction'].get('actions',[response['nextAction']])
        for action in actions:
            contracts.append(action['actionContractId'])
            packet=json.loads((tmp_path/action['packetPath']).read_bytes())
            result=stage_result(action['actionContractId'][:-3],packet)
            if action['actionContractId']=='STORY_AC-v1':
                from delivery_compiler import verify_story_ac_decision
                assert not verify_story_ac_decision(packet,result), verify_story_ac_decision(packet,result)
            if action['actionContractId']=='TASK-v1':
                from task_compiler import verify_task_decision
                assert not verify_task_decision(packet,result), verify_task_decision(packet,result)
            record=submit_prototype(tmp_path,action,result)['record']
            assert record['outcome']=='SUCCEEDED',record
        response=orchestrator_module.run_mode(tmp_path,'resume')
    else: pytest.fail('three Owners did not seal')
    root=tmp_path/'.ai-sow/work/runs'/response['state']['runId']
    for stage in ('SCOPE','STORY_AC','TASK'):
        assert len(list((root/f'stages/{stage}/checkpoints').glob('*.json')))==1
        assert len(list((root/f'stages/{stage}/plans').glob('*.json')))==1
    assert set(contracts)=={'SOURCE_SCAN-v1','SOURCE_AUDIT-v1','SCOPE_SYNTHESIS-v1','SOURCE_SCOPE-v1',
        'STORY_AC-v1','STORY_DESIGN-v1','TASK-v1','TASK_ESTIMATION-v1'}
    events=[json.loads(path.read_bytes()) for path in sorted((root/'events').glob('*.json'))]
    assert [event['payload']['stepKind'] for event in events if event['type']=='DETERMINISTIC_STEP_FINISHED']==['MATERIALIZE','VALIDATE']*3
    import scope_compiler,delivery_compiler,task_compiler
    def forbidden(*args,**kwargs): raise AssertionError('sealed Owner work must not be repeated')
    for module,name in [(scope_compiler,'materialize_scope_candidate'),(scope_compiler,'validate_scope_candidate'),
            (delivery_compiler,'materialize_story_candidate'),(delivery_compiler,'validate_story_candidate'),
            (task_compiler,'materialize_task_candidate'),(task_compiler,'validate_task_candidate')]:
        monkeypatch.setattr(module,name,forbidden)
    assert orchestrator_module.run_mode(tmp_path,'resume')['state']['phase']=='DRAFT'
    before={p:p.read_bytes() for p in root.rglob('*.json')}
    orchestrator_module.status(tmp_path)
    assert {p:p.read_bytes() for p in root.rglob('*.json')}==before


@pytest.mark.parametrize('prior_count',[1,2])
def test_stage_seal_order_prior_public_hash_only_consumers_never_reparse(tmp_path,monkeypatch,prior_count):
    monkeypatch.setattr(orchestrator_module, '_advance_artifact', lambda files,state: {'outcome':'ACTIVE','state':state,'nextAction':None})
    from test_intake import write_next_request
    from test_scope_compiler import scope_owner_result
    from stage_driver import stage_result
    import prior_state
    request_path=write_next_request(tmp_path,mode='BROWNFIELD',include_prior=True)
    request=json.loads(request_path.read_bytes())
    if prior_count==2:
        shutil.copyfile(tmp_path/'inputs/prior.xlsx',tmp_path/'inputs/prior-copy.xlsx')
        request['sources'].append({**next(row for row in request['sources'] if row['role']=='PRIOR_SOW'),
            'sourceId':'prior-copy','path':'inputs/prior-copy.xlsx'})
        write_json(request_path,request)
    response=orchestrator_module.run_mode(tmp_path,'start',request=request_path.name,budget_policy=write_budget_policy(tmp_path))
    assert response['outcome']=='ACTIVE',response
    def forbidden(*args,**kwargs): raise AssertionError('Prior workbook reparsed after frozen preparation')
    monkeypatch.setattr(prior_state,'inventory_prior_workbook',forbidden)
    prior_actions=[]
    for _ in range(60):
        assert response['outcome']=='ACTIVE',response
        if response['state']['phase']=='DRAFT': break
        for action in response['nextAction'].get('actions',[response['nextAction']]):
            packet=json.loads((tmp_path/action['packetPath']).read_bytes());kind=action['actionContractId'][:-3]
            if kind.startswith('PRIOR_'):
                prior_actions.append(action)
                date=next(ref['canonicalContent'] for ref in packet['contextRefs'] if ref['refId']=='PROJECT_EFFECTIVE_START')
                assert date['plannedEffectiveDate']=='2026-10-01'
                result=scope_owner_result(kind,packet)
            else: result=stage_result(kind,packet)
            assert submit_prototype(tmp_path,action,result)['record']['outcome']=='SUCCEEDED'
        response=orchestrator_module.run_mode(tmp_path,'resume')
    else: pytest.fail('Prior did not reach all three sealed stages')
    assert prior_actions
    root=tmp_path/'.ai-sow/work/runs'/response['state']['runId']/'stages/SCOPE'
    checkpoint=json.loads(next((root/'checkpoints').glob('*.json')).read_bytes())
    snapshot=(root/'prior-states'/f"{checkpoint['priorStateSha256']}.json").read_bytes()
    assert sha256_bytes(snapshot)==checkpoint['priorStateSha256']
    assert len({row['sourceId'] for row in json.loads(snapshot)['entities']})==prior_count
    assert orchestrator_module.run_mode(tmp_path,'resume')['state']['phase']=='DRAFT'


def test_stage_seal_order_prior_wait_blocks_dependent_scope_issuance(tmp_path):
    from test_intake import write_next_request
    from test_scope_compiler import scope_owner_result
    from stage_driver import stage_result
    request=write_next_request(tmp_path,mode='BROWNFIELD',include_prior=True)
    response=orchestrator_module.run_mode(tmp_path,'start',request=request.name,budget_policy=write_budget_policy(tmp_path))
    root=None;prior_record=None
    for _ in range(12):
        if response['outcome']=='WAITING_INPUT': break
        assert response['outcome']=='ACTIVE',response
        for action in response['nextAction'].get('actions',[response['nextAction']]):
            root=tmp_path/'.ai-sow/work/runs'/action['runId'];kind=action['actionContractId'][:-3]
            assert kind not in {'SCOPE_SYNTHESIS','SCOPE_PROPOSAL'}
            packet=json.loads((tmp_path/action['packetPath']).read_bytes())
            result=scope_owner_result(kind,packet) if kind.startswith('PRIOR_') else stage_result(kind,packet)
            if kind=='PRIOR_ANALYZE':
                row=packet['workItems'][0]['payload']
                result['unsupportedRegions']=[{'sourceId':row['sourceId'],'regionId':row['evidenceIds'][0],'reason':'需要确认该合同区域适用性'}]
            recorded=submit_prototype(tmp_path,action,result)['record']
            assert recorded['outcome']=='SUCCEEDED'
            if kind=='PRIOR_ANALYZE': prior_record=recorded
        response=orchestrator_module.run_mode(tmp_path,'resume')
    assert response['outcome']=='WAITING_INPUT' and response['nextAction'] is None
    assert prior_record['normalizedResultSha256']
    assert not list((root/'stages/SCOPE/prior-states').glob('*.json'))
    assert not list((root/'stages/SCOPE/checkpoints').glob('*.json'))


@pytest.mark.parametrize('step',['MATERIALIZE','VALIDATE'])
def test_stage_seal_order_active_overrun_prevents_next_operation_and_recovers_once(tmp_path,monkeypatch,step):
    import time,scope_compiler
    from stage_driver import stage_result
    name='materialize_scope_candidate' if step=='MATERIALIZE' else 'validate_scope_candidate'
    original=getattr(scope_compiler,name)
    def slow(*args,**kwargs):
        result=original(*args,**kwargs)
        time.sleep(1.1)
        return result
    monkeypatch.setattr(scope_compiler,name,slow)
    response=orchestrator_module.run_mode(tmp_path,'start',request=write_run_store_request(tmp_path),
        budget_policy=write_budget_policy(tmp_path,maxActiveSeconds=2))
    for _ in range(12):
        if response['outcome']=='WAITING_INPUT': break
        assert response['outcome']=='ACTIVE',response
        for action in response['nextAction'].get('actions',[response['nextAction']]):
            assert action['actionContractId']!='SOURCE_SCOPE-v1'
            packet=json.loads((tmp_path/action['packetPath']).read_bytes())
            assert submit_prototype(tmp_path,action,stage_result(action['actionContractId'][:-3],packet))['record']['outcome']=='SUCCEEDED'
        response=orchestrator_module.run_mode(tmp_path,'resume')
    assert response['outcome']=='WAITING_INPUT',response
    root=tmp_path/'.ai-sow/work/runs'/response['state']['runId']
    events=[json.loads(path.read_bytes()) for path in sorted((root/'events').glob('*.json'))]
    expected=['MATERIALIZE'] if step=='MATERIALIZE' else ['MATERIALIZE','VALIDATE']
    assert [event['payload']['stepKind'] for event in events if event['type']=='DETERMINISTIC_STEP_FINISHED']==expected
    assert not list((root/'stages/SCOPE/checkpoints').glob('*.json'))
    def forbidden(*args,**kwargs): raise AssertionError('completed deterministic operation repeated')
    monkeypatch.setattr(scope_compiler,name,forbidden)
    resumed=orchestrator_module.run_mode(tmp_path,'resume',budget_policy=write_budget_policy(tmp_path,maxActiveSeconds=300))
    assert resumed['outcome']=='ACTIVE',resumed
    assert resumed['nextAction']['actionContractId']=='SOURCE_SCOPE-v1'
    events=[json.loads(path.read_bytes()) for path in sorted((root/'events').glob('*.json'))]
    assert [event['payload']['stepKind'] for event in events if event['type']=='DETERMINISTIC_STEP_FINISHED']==['MATERIALIZE','VALIDATE']


@pytest.mark.parametrize('case',['pass','missing-obligation','intent-refused'])
def test_fresh_control_review_code_only_all_original_rounds_and_obligations(tmp_path,monkeypatch,case):
    from test_prototype_analysis import scenario_fixture,trace_fixture,observation_fixture
    from stage_driver import stage_result
    from dataclasses import replace
    import scope_compiler
    action=start_demo(tmp_path,two_controls=True)['nextAction'];inventory=prototype_payload(tmp_path,action)['inventory']
    root=tmp_path/'.ai-sow/work/runs'/action['runId'];attempts=[]
    for number in (1,2):
        assert not list((root/'stages/SCOPE/plans').glob('*.json'))
        chosen=copy.deepcopy(inventory);chosen['interactions']=[inventory['interactions'][number-1]]
        scenario=scenario_fixture(chosen,round=number)
        attempts.append(submit_prototype(tmp_path,action,scenario)['record'])
        browser=orchestrator_module.run_mode(tmp_path,'resume')['nextAction']
        attempts.append(submit_prototype(tmp_path,browser,trace_fixture(inventory,scenario))['record'])
        analyze=orchestrator_module.run_mode(tmp_path,'resume')['nextAction']
        observation=observation_fixture(chosen,'round-'+str(number));observation['runtimeStatus']='CODE_ONLY'
        attempts.append(submit_prototype(tmp_path,analyze,{'observations':[observation]})['record'])
        response=orchestrator_module.run_mode(tmp_path,'resume')
        action=response['nextAction']
    if case=='missing-obligation':
        original=scope_compiler.materialize_scope_candidate
        def missing(*args,**kwargs): return replace(original(*args,**kwargs),review_obligations=())
        monkeypatch.setattr(scope_compiler,'materialize_scope_candidate',missing)
    for _ in range(12):
        if response['outcome']!='ACTIVE': break
        action=response['nextAction']
        if action.get('actionContractId')=='SOURCE_SCOPE-v1': break
        for current in action.get('actions',[action]):
            packet=json.loads((tmp_path/current['packetPath']).read_bytes());kind=current['actionContractId'][:-3]
            result=stage_result(kind,packet)
            if kind=='SCOPE_SYNTHESIS':
                refs=[ref['canonicalContent'] for ref in packet['contextRefs'] if ref['canonicalContent'].get('kind')=='PROTOTYPE_OBSERVATION_REF']
                feature=next(row for row in result['decisions'] if row['decisionKind']=='FEATURE')
                feature['boundaryEvidence']['observationKeys']=sorted(key for ref in refs for key in ref['observationKeys'])
                feature['boundaryEvidence']['evidenceIds']=sorted(set(feature['boundaryEvidence']['evidenceIds'])|{key for ref in refs for key in ref['evidenceIds']})
            assert submit_prototype(tmp_path,current,result)['record']['outcome']=='SUCCEEDED'
        response=orchestrator_module.run_mode(tmp_path,'resume')
    if case=='missing-obligation':
        assert response['outcome']!='ACTIVE',response
        assert response.get('nextAction') is None
        return
    assert action['actionContractId']=='SOURCE_SCOPE-v1',response
    body=prototype_payload(tmp_path,action)
    obligations=[row for row in body['reviewObligations'] if row['kind']=='PROTOTYPE_INTENT']
    assert {row['round'] for row in obligations}=={1,2}
    for row in obligations:
        original=next(json.loads(path.read_bytes()) for path in (root/'actions').glob('*/normalized-result.json') if sha256_bytes(path.read_bytes())==row['normalizedResultSha256'])
        assert row['observation']==next(item for item in original['observations'] if item['localKey']==row['localKey'])
    assert {row['attemptRecordSha256'] for row in obligations}=={sha256_bytes(canonical_json_bytes(attempts[2])),sha256_bytes(canonical_json_bytes(attempts[5]))}
    if case=='intent-refused':
        review={'decision':'INPUT_REQUIRED','findings':[{'code':'PROTOTYPE_INTENT','path':'/features','subjectIds':['round-1'],
            'evidenceIds':obligations[0]['sourceEvidenceIds'],'message':'请明确该源码候选是否纳入正式目标范围。'}]}
    else: review={'decision':'PASS','findings':[]}
    assert submit_prototype(tmp_path,action,review)['record']['outcome']=='SUCCEEDED'
    response=orchestrator_module.run_mode(tmp_path,'resume')
    if case=='intent-refused':
        assert response['outcome']=='WAITING_INPUT'
        assert not list((root/'stages/SCOPE/checkpoints').glob('*.json'))
    else:
        assert response['outcome']=='ACTIVE',response
        checkpoint=json.loads(next((root/'stages/SCOPE/checkpoints').glob('*.json')).read_bytes())
        assert {sha256_bytes(canonical_json_bytes(record)) for record in attempts}<=set(checkpoint['effectiveAttemptRecordSha256s'])


@pytest.mark.parametrize('cap',[1,2])
def test_public_stage_plan_cutover_low_cap_interrupted_issuance_complete_groups(tmp_path,monkeypatch,cap):
    from stage_driver import stage_result
    from test_scope_compiler import scope_owner_result
    request_path=write_run_store_request(tmp_path);request=json.loads((tmp_path/request_path).read_bytes())
    source=tmp_path/request['sources'][0]['path']
    source.write_text('\n\n'.join('查询边界'+str(number)+' '+' '.join('field'+str(i) for i in range(4000)) for number in range(14)),encoding='utf-8')
    request['sources'][0]['expectedSha256']=sha256_bytes(source.read_bytes());write_json(tmp_path/request_path,request)
    budget=write_budget_policy(tmp_path,maxConcurrency=cap,modelContextLimitTokens=60000,outputReserveTokens=2000,hydrateReserveTokens=1000,safetyMarginTokens=1000,referenceOverheadTokens=256)
    original=ProjectFiles.publish_new;fired=False
    def interrupted(files,path,payload):
        nonlocal fired
        result=original(files,path,payload)
        boundary = path.endswith('/envelope.json') if cap == 1 else ('/events/' in path and json.loads(payload).get('type') == 'ACTION_ISSUED')
        if boundary and not fired:
            fired=True;raise OSError('injected interruption after exact Envelope publication')
        return result
    with monkeypatch.context() as fault:
        fault.setattr(ProjectFiles,'publish_new',interrupted)
        response=orchestrator_module.run_mode(tmp_path,'start',request=request_path,budget_policy=budget)
    assert fired and response['outcome']=='BLOCKED'
    files=ProjectFiles.open(tmp_path);marker=files.read_json('.ai-sow/work/active-run.json');root=tmp_path/'.ai-sow/work/runs'/marker['runId']
    original_envelopes={path:path.read_bytes() for path in (root/'actions').glob('*/envelope.json')}
    response=orchestrator_module.run_mode(tmp_path,'resume')
    assert response['outcome']=='ACTIVE',response
    plan=json.loads(next((root/'stages/SCOPE/plans').glob('*.json')).read_bytes());original_plan=canonical_json_bytes(plan)
    assert len(plan['works'])>8
    assert all(len(group['requiredLogicalWorkIds'])<=cap for group in plan['groups'])
    assert all(path.read_bytes()==raw for path,raw in original_envelopes.items())
    # Complete sequential low-cap groups: partial siblings never release dependencies.
    seen=set()
    for _ in range(40):
        assert response['outcome']=='ACTIVE',response
        action=response['nextAction'];actions=action.get('actions',[action])
        if any(row['actionContractId'] == 'SOURCE_SCOPE-v1' for row in actions): break
        group=next(group for group in plan['groups'] if group['groupId']==actions[0]['groupId'])
        assert {row['logicalWorkId'] for row in actions}==set(group['requiredLogicalWorkIds'])
        for current in actions:
            packet=json.loads((tmp_path/current['packetPath']).read_bytes())
            kind = current['actionContractId'][:-3]
            result=scope_owner_result(kind,packet) if kind.startswith('SCOPE_') else stage_result(kind,packet)
            if current['actionContractId']=='SOURCE_SCAN-v1':
                for row in result: row['facts'][0]['statement']='查询字段能力'
            assert submit_prototype(tmp_path,current,result)['record']['outcome']=='SUCCEEDED'
            seen.add(current['logicalWorkId'])
        response=orchestrator_module.run_mode(tmp_path,'resume')
    assert seen == {work['logicalWorkId'] for work in plan['works']}
    assert canonical_json_bytes(json.loads(next((root/'stages/SCOPE/plans').glob('*.json')).read_bytes()))==original_plan
    events=[json.loads(path.read_bytes()) for path in (root/'events').glob('*.json')]
    issued=[event['payload']['envelopeSha256'] for event in events if event['type']=='ACTION_ISSUED']
    assert len(issued)==len(set(issued))


def scope_review_boundary(project, *, excluded=False, separate_roots=False):
    from stage_driver import stage_result
    from test_scope_compiler import scope_owner_result
    from test_intake import write_next_request
    request = write_next_request(project,mode='BROWNFIELD',include_prior=True).name if excluded=='RETIRE' else write_run_store_request(project)
    response = orchestrator_module.run_mode(project, 'start', request=request,
        budget_policy=write_budget_policy(project))
    for _ in range(12):
        if response['outcome'] != 'ACTIVE': return response
        action = response['nextAction']
        if action.get('actionContractId') == 'SOURCE_SCOPE-v1': return response
        for current in action.get('actions', [action]):
            packet = json.loads((project/current['packetPath']).read_bytes())
            kind = current['actionContractId'][:-3]
            result = scope_owner_result(kind,packet) if kind.startswith('PRIOR_') or separate_roots and kind.startswith('SCOPE_') else stage_result(kind, packet)
            if separate_roots and kind.startswith('SCOPE_'):
                for row in result['decisions']:
                    if row['decisionKind'] in {'EPIC','FEATURE'}: row['boundaryEvidence']['name']='同名能力'
            if excluded and kind == 'SCOPE_SYNTHESIS':
                feature = next(row for row in result['decisions'] if row['decisionKind'] == 'FEATURE')
                handle = feature['factIds'].pop()
                result['decisions'].append({'localKey':'excluded-root','decisionKind':excluded,'factIds':[handle],
                    'priorEntityIds':[], 'boundaryEvidence':{'name':'本期排除范围','classification':'DISPOSITION',
                        'evidenceIds':[handle.rsplit(':',1)[0]],'facetFacts':[],'observationKeys':[]},
                    'relations':[], 'exclusionReason':'本期不实施'})
                if excluded=='RETIRE':
                    prior = next(ref['canonicalContent']['normalizedResult']['entities'][0] for ref in packet['contextRefs'] if ref['canonicalContent'].get('kind')=='DEPENDENCY_RESULT' and isinstance(ref['canonicalContent']['normalizedResult'],dict) and 'entities' in ref['canonicalContent']['normalizedResult'])
                    result['decisions'][-1]['priorEntityIds']=[prior['localKey']]
                    result['decisions'][-1]['boundaryEvidence']['evidenceIds']+=prior['evidenceIds']
            assert submit_prototype(project,current,result)['record']['outcome'] == 'SUCCEEDED'
        response = orchestrator_module.run_mode(project,'resume')
    pytest.fail('Scope did not reach Review boundary')


@pytest.mark.parametrize('kind',['EXCLUDE','RETIRE'])
def test_bounded_semantic_repair_excluded_scope_root_is_reviewable(tmp_path,kind):
    response = scope_review_boundary(tmp_path, excluded=kind)
    assert response['outcome'] == 'ACTIVE', response
    action = response['nextAction'];body = prototype_payload(tmp_path,action)
    entry = body['ownerIndex']['excluded-root']
    assert entry['path'].startswith('/scopeAnnotations/')
    review = {'decision':'REPAIRABLE_SEMANTIC','findings':[{'code':'EXCLUSION_REASON','path':entry['path'],
        'subjectIds':['excluded-root'],'evidenceIds':body['evidenceIds'][:1],'message':'排除理由需要明确本期责任边界。'}]}
    assert submit_prototype(tmp_path,action,review)['record']['outcome'] == 'SUCCEEDED'
    repair = orchestrator_module.run_mode(tmp_path,'resume')['nextAction']
    row = next(row for row in prototype_payload(tmp_path,repair)['ownerIR']['decisions'] if row['localKey']=='excluded-root')
    row['exclusionReason'] = '本期由客户既有系统承担，不纳入本次实施交付'
    assert submit_prototype(tmp_path,repair,{'decisions':[row]})['record']['outcome'] == 'SUCCEEDED'
    fresh = orchestrator_module.run_mode(tmp_path,'resume')['nextAction']
    assert fresh['baseCandidateSha256'] != action['baseCandidateSha256']
    assert prototype_payload(tmp_path,fresh)['ownerIndex']['excluded-root']['id'] == entry['id']


@pytest.mark.parametrize('step', ['MATERIALIZE','VALIDATE'])
@pytest.mark.parametrize('boundary', ['output','after-event','after-output'])
def test_stage_seal_order_step_output_transaction_recovers_exact_timing(tmp_path,monkeypatch,step,boundary):
    import scope_compiler
    called = {'MATERIALIZE':0,'VALIDATE':0};fired=False
    for kind,name in [('MATERIALIZE','materialize_scope_candidate'),('VALIDATE','validate_scope_candidate')]:
        original = getattr(scope_compiler,name)
        def count(*args,_original=original,_kind=kind,**kwargs):
            called[_kind] += 1
            return _original(*args,**kwargs)
        monkeypatch.setattr(scope_compiler,name,count)
    original_publish = ProjectFiles.publish_new
    directory = '/review-inputs/1/' if step=='MATERIALIZE' else '/validators/1/'
    def interrupt(files,path,payload):
        nonlocal fired
        is_event = '/events/' in path and json.loads(payload).get('type')=='DETERMINISTIC_STEP_FINISHED' and json.loads(payload)['payload']['stepKind']==step
        if not fired and (boundary in {'output','after-output'} and directory in path or boundary=='after-event' and is_event):
            if boundary in {'after-event','after-output'}: original_publish(files,path,payload)
            fired=True
            raise OSError('injected deterministic publication interruption')
        return original_publish(files,path,payload)
    with monkeypatch.context() as fault:
        fault.setattr(ProjectFiles,'publish_new',interrupt)
        result=scope_review_boundary(tmp_path)
    assert fired and result['outcome']=='BLOCKED',result
    root=tmp_path/'.ai-sow/work/runs'/active_marker(tmp_path)['runId']
    events=lambda:[json.loads(path.read_bytes()) for path in sorted((root/'events').glob('*.json'))]
    steps=[row['payload'] for row in events() if row['type']=='DETERMINISTIC_STEP_FINISHED' and row['payload']['stepKind']==step]
    assert len(steps)==1 and steps[0]['outcome']=='SUCCEEDED'
    digest=steps[0]['outputSha256']
    assert steps[0]['stageKind']=='SCOPE' and steps[0]['semanticRevision']==1
    response=orchestrator_module.run_mode(tmp_path,'resume')
    assert response['outcome']=='ACTIVE',response
    assert response['nextAction']['actionContractId']=='SOURCE_SCOPE-v1'
    repeated=[row['payload'] for row in events() if row['type']=='DETERMINISTIC_STEP_FINISHED' and row['payload']['stepKind']==step]
    assert len(repeated)==(1 if boundary=='after-output' else 2) and all(row['outputSha256']==digest for row in repeated)
    assert called[step]==len(repeated)
    assert (root/('stages/SCOPE'+directory)/f'{digest}.json').is_file()
    before=dict(called)
    assert orchestrator_module.run_mode(tmp_path,'resume')['outcome']=='ACTIVE'
    assert called==before


@pytest.mark.parametrize('tamper',['input-only','input-and-event','swapped-roots-and-event'])
def test_checkpoint_deep_binding_rehashed_review_input_cannot_replace_completed_output(tmp_path,monkeypatch,tamper):
    original=orchestrator_module._issue_control
    def stop(*args,**kwargs): raise OSError('interrupt before Review issuance')
    with monkeypatch.context() as fault:
        fault.setattr(orchestrator_module,'_issue_control',stop)
        response=scope_review_boundary(tmp_path,separate_roots=True)
    assert response['outcome']=='BLOCKED'
    root=tmp_path/'.ai-sow/work/runs'/active_marker(tmp_path)['runId']
    path=next((root/'stages/SCOPE/review-inputs/1').glob('*.json'))
    value=json.loads(path.read_bytes());index=value['workItems'][0]['payload']['ownerIndex']
    if tamper=='swapped-roots-and-event':
        keys=[key for key,entry in index.items() if entry['path'].startswith('/features/')]
        assert len(keys)>1
        index[keys[0]],index[keys[1]]=index[keys[1]],index[keys[0]]
    else: value['workItems'][0]['payload']['ownerIndex']={}
    raw=canonical_json_bytes(value);path.unlink();(path.parent/(sha256_bytes(raw)+'.json')).write_bytes(raw)
    if tamper!='input-only':
        for event_path in (root/'events').glob('*.json'):
            event=json.loads(event_path.read_bytes())
            if event['type']=='DETERMINISTIC_STEP_FINISHED' and event['payload']['stepKind']=='MATERIALIZE':
                event['payload']['outputSha256']=sha256_bytes(raw);write_json(event_path,event)
    before=managed_snapshot(tmp_path)
    result=orchestrator_module.run_mode(tmp_path,'resume')
    assert result['outcome']=='BLOCKED',result
    assert result.get('nextAction') is None
    assert managed_snapshot(tmp_path)==before


@pytest.mark.parametrize('tamper',['prior','graph'])
def test_checkpoint_deep_binding_prior_graph_recovery_uses_sealed_owner_sources(tmp_path,monkeypatch,tamper):
    def stop(*args,**kwargs): raise OSError('stop before Review')
    with monkeypatch.context() as fault:
        fault.setattr(orchestrator_module,'_issue_control',stop)
        response=scope_review_boundary(tmp_path,excluded='RETIRE')
    assert response['outcome']=='BLOCKED'
    root=tmp_path/'.ai-sow/work/runs'/active_marker(tmp_path)['runId']
    path=next((root/'stages/SCOPE/review-inputs/1').glob('*.json'))
    value=json.loads(path.read_bytes());body=value['workItems'][0]['payload']
    if tamper=='prior':
        body['priorState']['entities'][0]['semanticSummary']='未获原合同授权的伪造历史承诺'
        digest=sha256_bytes(canonical_json_bytes(body['priorState']))
        for obligation in body['reviewObligations']:
            if 'priorStateSha256' in obligation: obligation['priorStateSha256']=digest
            if obligation['kind']=='PRIOR_SOURCE_EQUIVALENCE': obligation['entities']=body['priorState']['entities']
    else:
        body['changeGraph']['retiredPrior']=[]
        body['reviewObligations']=[row for row in body['reviewObligations'] if row.get('relationKind')!='RETIRE']
    raw=canonical_json_bytes(value);path.unlink();(path.parent/(sha256_bytes(raw)+'.json')).write_bytes(raw)
    for event_path in (root/'events').glob('*.json'):
        event=json.loads(event_path.read_bytes())
        if event['type']=='DETERMINISTIC_STEP_FINISHED' and event['payload']['stepKind']=='MATERIALIZE':
            event['payload']['outputSha256']=sha256_bytes(raw);write_json(event_path,event)
    before=managed_snapshot(tmp_path)
    result=orchestrator_module.run_mode(tmp_path,'resume')
    assert result['outcome']=='BLOCKED',result
    assert result.get('nextAction') is None
    assert managed_snapshot(tmp_path)==before


@pytest.mark.parametrize(('clarify','borrow_prior_ac'),[(False,False),(True,False),(True,True)],
    ids=['shared-repair','shared-clarification','unrelated-ac-rejected'])
def test_public_localized_task_repair_resumes_unissued_capacity_and_preserves_checkpoints(tmp_path, monkeypatch, clarify, borrow_prior_ac):
    # This integration ends at Task checkpoint; real Office is a separate E2E gate.
    monkeypatch.setattr(orchestrator_module,'_advance_artifact',lambda files,state: {'outcome':'ACTIVE','state':state,'nextAction':None})
    from stage_driver import stage_result
    from task_compiler import expand_task_repair_packet
    response = orchestrator_module.run_mode(tmp_path,'start',request=write_run_store_request(tmp_path),
        budget_policy=write_budget_policy(tmp_path))
    for _ in range(30):
        assert response['outcome']=='ACTIVE',response
        actions=response['nextAction'].get('actions',[response['nextAction']])
        if actions[0]['actionContractId']=='TASK_ESTIMATION-v1': break
        for action in actions:
            submit_prototype(tmp_path,action,stage_result(action['actionContractId'][:-3],
                json.loads((tmp_path/action['packetPath']).read_bytes())))
        response=orchestrator_module.run_mode(tmp_path,'resume')
    else: pytest.fail('Task Review was not issued')
    action=actions[0];body=prototype_payload(tmp_path,action)
    root=tmp_path/'.ai-sow/work/runs'/action['runId']
    frozen={path:path.read_bytes() for stage in ('SCOPE','STORY_AC')
            for path in (root/'stages'/stage).rglob('*.json')}
    candidate_one=canonical_json_bytes(body['candidate'])
    policies={row['policyInstanceId']:row['policyId'] for row in body['candidate']['policyInstances']}
    keys=[key for key,entry in body['ownerIndex'].items() if any(
        policies[policy] in ('policy-sit-automation','policy-uat-automation')
        for task in body['candidate']['tasks'] if task['taskId']==entry['id'] for policy in task['policyInstanceIds'])]
    assert len(keys)==2
    review={'decision':'REPAIRABLE_SEMANTIC','findings':[{'code':'DUPLICATE_ASSET','path':'/tasks',
        'subjectIds':keys,'evidenceIds':[],'message':'同一资产同时承担两项验收义务。'}]}
    submit_prototype(tmp_path,action,review)
    estimator=orchestrator_module.estimate_action_input_tokens
    def oversized(skill,contract,*args,**kwargs):
        value=estimator(skill,contract,*args,**kwargs)
        return value+1000000 if contract=='TASK_REPAIR-v1' else value
    with monkeypatch.context() as fault:
        import contracts
        fault.setattr(orchestrator_module,'estimate_action_input_tokens',oversized)
        fault.setattr(contracts,'estimate_action_input_tokens',oversized)
        waiting=orchestrator_module.run_mode(tmp_path,'resume')
        assert waiting['outcome']=='WAITING_INPUT',waiting
        detail=waiting['diagnostics'][0]['details']
        assert detail['reason']=='ACTION_CONTEXT_CAPACITY'
        assert detail['estimatedInputTokens']>detail['usableInputTokens']
        assert orchestrator_module.run_mode(tmp_path,'resume')['outcome']=='WAITING_INPUT'
    policy_files={p:p.read_bytes() for p in (root/'budget-policies').glob('*.json')}
    resumed=orchestrator_module.run_mode(tmp_path,'resume')
    assert resumed['outcome']=='ACTIVE',resumed
    repair=resumed['nextAction'];payload=prototype_payload(tmp_path,repair)
    assert repair['actionContractId']=='TASK_REPAIR-v1'
    assert payload['authorizedRootKeys']==sorted(keys)
    packet=expand_task_repair_packet(payload['ownerPacket'])
    assert payload['ownerPacket']['contract']=='ai-sow-task-repair-context-v1'
    assert all(p.read_bytes()==raw for p,raw in policy_files.items())
    assert all(p.read_bytes()==raw for p,raw in frozen.items())
    assert orchestrator_module.run_mode(tmp_path,'resume')['nextAction']['actionId']==repair['actionId']
    rows=[row for row in payload['ownerIR']['tasks'] if row['localKey'] in keys]
    row=copy.deepcopy(rows[0])
    for field in ('acceptanceCriterionKeys','evidenceIds'): row[field]=sorted({key for task in rows for key in task[field]})
    row['deliverableBoundary']='一套共享自动化资产，分别提供集成和用户验收结果。'
    assert submit_prototype(tmp_path,repair,{'tasks':[row]})['record']['outcome']=='SUCCEEDED'
    second=orchestrator_module.run_mode(tmp_path,'resume')['nextAction']
    assert second['actionContractId']=='TASK_ESTIMATION-v1'
    revised=prototype_payload(tmp_path,second)['candidate']
    assert len(revised['tasks'])==len(body['candidate']['tasks'])-1
    for collection in ('stories','acceptanceCriteria','features','inputItems'): assert revised[collection]==body['candidate'][collection]
    assert not list((root/'stages/TASK/checkpoints').glob('*.json'))
    assert orchestrator_module.run_mode(tmp_path,'resume')['nextAction']['actionId']==second['actionId']
    if borrow_prior_ac:
        other=next(copy.deepcopy(task) for task in payload['ownerIR']['tasks'] if task['localKey'] not in keys)
        question={'decision':'INPUT_REQUIRED','findings':[{'code':'IMPLEMENTATION_BOUNDARY','path':'/tasks',
            'subjectIds':[other['localKey']],'evidenceIds':[],'message':'仅明确这个独立资产的移交边界。'}]}
        submit_prototype(tmp_path,second,question)
        assert orchestrator_module.run_mode(tmp_path,'resume')['outcome']=='WAITING_INPUT'
        answer={'contract':'ai-sow-owner-clarification-v1','stageKind':'TASK',
            'candidateSha256':second['baseCandidateSha256'],'reviewDecisionSha256':sha256_bytes(canonical_json_bytes(question)),
            'scope':'IMPLEMENTATION_WITHIN_APPROVED_TARGETS','technicalTargetKeys':[other['technicalTarget']],
            'decision':'保留原实施目标和原验收覆盖，仅明确移交原有资产。',
            'provenance':'SIMULATED_USER','authorization':'用户已授权模拟技术选择。'}
        write_json(tmp_path/'answer.json',answer)
        repair_two=orchestrator_module.run_mode(tmp_path,'resume',decision='answer.json')['nextAction']
        assert repair_two['actionContractId']=='TASK_REPAIR-v1'
        bad=copy.deepcopy(other)
        for field in ('acceptanceCriterionKeys','evidenceIds'): bad[field]=sorted(set(bad[field]+row[field]))
        rejected=submit_prototype(tmp_path,repair_two,{'tasks':[bad]})
        assert rejected['record']['outcome']=='FAILED',rejected
        assert rejected['record']['failureKind']=='INVALID_IR'
        assert rejected['record']['normalizedResultSha256'] is None
        retry=orchestrator_module.run_mode(tmp_path,'resume')['nextAction']
        assert retry['logicalWorkId']==repair_two['logicalWorkId'] and retry['revision']==repair_two['revision']+1
        assert submit_prototype(tmp_path,retry,{'tasks':[other]})['record']['outcome']=='SUCCEEDED'
        assert all(p.read_bytes()==raw for p,raw in frozen.items())
        return
    if clarify:
        question={'decision':'INPUT_REQUIRED','findings':[{'code':'IMPLEMENTATION_BOUNDARY','path':'/tasks',
            'subjectIds':[row['localKey']],'evidenceIds':[],'message':'明确共享资产的执行与移交边界。'}]}
        submit_prototype(tmp_path,second,question)
        assert orchestrator_module.run_mode(tmp_path,'resume')['outcome']=='WAITING_INPUT'
        answer={'contract':'ai-sow-owner-clarification-v1','stageKind':'TASK',
            'candidateSha256':second['baseCandidateSha256'],'reviewDecisionSha256':sha256_bytes(canonical_json_bytes(question)),
            'scope':'IMPLEMENTATION_WITHIN_APPROVED_TARGETS','technicalTargetKeys':[row['technicalTarget']],
            'decision':'共享资产使用原已批准实施目标，移交同一套脚本与两次验收运行记录。',
            'provenance':'SIMULATED_USER','authorization':'用户已授权模拟技术选择。'}
        wrong={**answer,'technicalTargetKeys':['target:unapproved-component']};write_json(tmp_path/'answer.json',wrong)
        assert orchestrator_module.run_mode(tmp_path,'resume',decision='answer.json')['outcome']=='BLOCKED'
        write_json(tmp_path/'answer.json',answer)
        publish=ProjectFiles.publish_new
        interrupted=False
        def after_clarification_event(files,path,payload):
            nonlocal interrupted
            value=publish(files,path,payload)
            if '/events/' in path and json.loads(payload).get('payload',{}).get('resolutionKind')=='OWNER_CLARIFICATION' and not interrupted:
                interrupted=True;raise OSError('interrupt after immutable clarification event')
            return value
        with monkeypatch.context() as fault:
            fault.setattr(ProjectFiles,'publish_new',after_clarification_event)
            assert orchestrator_module.run_mode(tmp_path,'resume',decision='answer.json')['outcome']=='BLOCKED'
        assert interrupted
        continued=orchestrator_module.run_mode(tmp_path,'resume')
        assert continued['outcome']=='ACTIVE',continued
        assert orchestrator_module.run_mode(tmp_path,'resume',decision='answer.json')['nextAction']['actionId']==continued['nextAction']['actionId']
        repair_two=continued['nextAction'];payload_two=prototype_payload(tmp_path,repair_two)
        assert payload_two['ownerClarification']==answer
        assert len(payload_two['ownerIR']['tasks'])==len(payload['ownerIR']['tasks'])-1
        row=next(copy.deepcopy(task) for task in payload_two['ownerIR']['tasks'] if task['localKey']==row['localKey'])
        row['deliverableBoundary']+='移交同一套脚本与两个阶段运行记录。'
        assert submit_prototype(tmp_path,repair_two,{'tasks':[row]})['record']['outcome']=='SUCCEEDED'
        third=orchestrator_module.run_mode(tmp_path,'resume')['nextAction']
        third_body=prototype_payload(tmp_path,third)
        assert third['actionContractId']=='TASK_ESTIMATION-v1' and third_body['ownerClarification']==answer
        assert len(third_body['candidate']['tasks'])==len(revised['tasks'])
        assert all(p.read_bytes()==raw for p,raw in frozen.items())
        second=third
        finding={'decision':'REPAIRABLE_SEMANTIC','findings':[{'code':'COMPLEXITY','path':'/tasks',
            'subjectIds':[row['localKey']],'evidenceIds':[],'message':'按模板修正这一资产复杂度。'}]}
        submit_prototype(tmp_path,third,finding)
        stopped=orchestrator_module.run_mode(tmp_path,'resume')
        assert stopped['outcome']=='MANUAL_REVIEW_REQUIRED',stopped
        stopped_raw=canonical_json_bytes(stopped['state'])
        authorization={'contract':'ai-sow-owner-repair-authorization-v1','runId':action['runId'],'stageKind':'TASK',
            'terminalStateSha256':sha256_bytes(stopped_raw),'candidateSha256':third['baseCandidateSha256'],
            'reviewDecisionSha256':sha256_bytes(canonical_json_bytes(finding)),
            'rootKeys':[row['localKey']],'allowedFields':['complexityDecision'],'additionalRevisions':1,
            'decision':'仅调整该资产复杂度为 L，保留其他结果。','provenance':'SIMULATED_USER','authorization':'用户已授权模拟技术裁定。'}
        write_json(tmp_path/'continue.json',{**authorization,'candidateSha256':'0'*64})
        assert orchestrator_module.run_mode(tmp_path,'resume',decision='continue.json')['outcome']=='BLOCKED'
        write_json(tmp_path/'continue.json',authorization)
        interrupted=False
        def after_authorization_event(files,path,payload):
            nonlocal interrupted
            value=publish(files,path,payload)
            if '/events/' in path and json.loads(payload).get('type')=='OWNER_REPAIR_AUTHORIZED' and not interrupted:
                interrupted=True;raise OSError('interrupt after manual repair authorization')
            return value
        with monkeypatch.context() as fault:
            fault.setattr(ProjectFiles,'publish_new',after_authorization_event)
            assert orchestrator_module.run_mode(tmp_path,'resume',decision='continue.json')['outcome']=='BLOCKED'
        assert interrupted
        continued=orchestrator_module.run_mode(tmp_path,'resume',decision='continue.json')
        assert continued['outcome']=='ACTIVE',continued
        manual=continued['nextAction'];manual_body=prototype_payload(tmp_path,manual)
        assert manual_body['ownerRepairAuthorization']==authorization
        assert orchestrator_module.run_mode(tmp_path,'resume',decision='continue.json')['nextAction']['actionId']==manual['actionId']
        manual_row=next(copy.deepcopy(task) for task in manual_body['ownerIR']['tasks'] if task['localKey']==row['localKey'])
        assert manual_row['complexityDecision']=='M'
        manual_row['complexityDecision']='L'
        assert submit_prototype(tmp_path,manual,{'tasks':[manual_row]})['record']['outcome']=='SUCCEEDED'
        second=orchestrator_module.run_mode(tmp_path,'resume')['nextAction']
        fourth=prototype_payload(tmp_path,second)
        assert fourth['ownerRepairAuthorization']==authorization and fourth['ownerClarification']==answer
        assert len(fourth['candidate']['tasks'])==len(revised['tasks'])
        assert (root/'states'/f'state-{authorization["terminalStateSha256"]}.json').read_bytes()==stopped_raw
        assert len(list((root/'stages/TASK/review-inputs').glob('*/*.json')))==4
        assert all(p.read_bytes()==raw for p,raw in frozen.items())
        from final_review import verify_manual_authorization_records
        entries={authorization['reviewDecisionSha256']:{'authorization':authorization,'terminalState':stopped['state']}}
        events=[json.loads(p.read_bytes()) for p in sorted((root/'events').glob('*.json'))]
        review_inputs={p.stem:json.loads(p.read_bytes()) for p in (root/'stages/TASK/review-inputs').glob('*/*.json')}
        def portable(values,log):
            return verify_manual_authorization_records(values,log,'TASK',action['runId'],stopped['state']['currentInputRevisionSha256'],
                require_repair=True,review_inputs=review_inputs)
        assert portable(entries,events)=={authorization['reviewDecisionSha256']:authorization}
        for mutate in ('missing-stop','changed-authorization','missing-event','reset-count','late-authorization'):
            bad_entries=copy.deepcopy(entries);bad_events=copy.deepcopy(events)
            event=next(item for item in bad_events if item['type']=='OWNER_REPAIR_AUTHORIZED')
            if mutate=='missing-stop': bad_entries[authorization['reviewDecisionSha256']]['terminalState']={}
            elif mutate=='changed-authorization': bad_entries[authorization['reviewDecisionSha256']]['authorization']['allowedFields']=['deliverableBoundary']
            elif mutate=='missing-event': bad_events.remove(event)
            elif mutate=='reset-count': event['payload']['semanticRevision']=1
            else: event['sequence']=len(bad_events)+1
            with pytest.raises(ValueError): portable(bad_entries,bad_events)
    submit_prototype(tmp_path,second,{'decision':'PASS','findings':[]})
    result=orchestrator_module.run_mode(tmp_path,'resume')
    assert result['outcome']=='ACTIVE' and result['state']['phase']=='DRAFT',result
    assert all(p.read_bytes()==raw for p,raw in frozen.items())
    assert (root/'stages/TASK/candidates'/f'{sha256_bytes(candidate_one)}.json').read_bytes()==candidate_one
    assert orchestrator_module.status(tmp_path)['outcome']=='ACTIVE'


@pytest.mark.parametrize('stage,review_contract,collection,field',[
    ('SCOPE','SOURCE_SCOPE-v1','decisions','boundaryEvidence'),
    ('STORY_AC','STORY_DESIGN-v1','stories','deliverableOutcome')])
def test_public_manual_owner_repair_preserves_prior_candidates_and_cumulative_changes(tmp_path,monkeypatch,stage,review_contract,collection,field):
    from stage_driver import stage_result
    from final_review import repair_root_keys
    monkeypatch.setattr(orchestrator_module,'_advance_artifact',lambda files,state:{'outcome':'ACTIVE','state':state,'nextAction':None})
    response=orchestrator_module.run_mode(tmp_path,'start',request=write_run_store_request(tmp_path),budget_policy=write_budget_policy(tmp_path))
    for _ in range(25):
        assert response['outcome']=='ACTIVE',response
        actions=response['nextAction'].get('actions',[response['nextAction']])
        if actions[0]['actionContractId']==review_contract: break
        for action in actions: submit_prototype(tmp_path,action,stage_result(action['actionContractId'][:-3],json.loads((tmp_path/action['packetPath']).read_bytes())))
        response=orchestrator_module.run_mode(tmp_path,'resume')
    else: pytest.fail('Owner Review missing')
    action=actions[0];body=prototype_payload(tmp_path,action)
    key=next(key for key,entry in body['ownerIndex'].items() if entry['path'].startswith('/features/' if stage=='SCOPE' else '/stories/'))
    finding={'decision':'REPAIRABLE_SEMANTIC','findings':[{'code':'NAME','path':'/features' if stage=='SCOPE' else '/stories',
        'subjectIds':[key],'evidenceIds':[],'message':'调整既有对象名称。'}]}
    submit_prototype(tmp_path,action,finding)
    repair=orchestrator_module.run_mode(tmp_path,'resume')['nextAction'];repair_body=prototype_payload(tmp_path,repair)
    first=copy.deepcopy(next(row for row in repair_body['ownerIR'][collection] if row['localKey']==key))
    if stage=='SCOPE': first['boundaryEvidence']['name']+='已修正'
    else: first['deliverableOutcome']+='已修正'
    assert submit_prototype(tmp_path,repair,{collection:[first]})['record']['outcome']=='SUCCEEDED'
    second=orchestrator_module.run_mode(tmp_path,'resume')['nextAction']
    # A distinct review hash is essential; each approval binds exactly one actual finding.
    next_finding=copy.deepcopy(finding);next_finding['findings'][0]['message']='根据本候选进一步明确名称。'
    submit_prototype(tmp_path,second,next_finding)
    stopped=orchestrator_module.run_mode(tmp_path,'resume');assert stopped['outcome']=='MANUAL_REVIEW_REQUIRED'
    from final_review import replace_owner_decisions
    ir=replace_owner_decisions(stage,repair_body['ownerIR'],finding,{collection:[first]})
    keys=repair_root_keys(stage,ir,next_finding)
    auth={'contract':'ai-sow-owner-repair-authorization-v1','runId':action['runId'],'stageKind':stage,
        'terminalStateSha256':sha256_bytes(canonical_json_bytes(stopped['state'])),'candidateSha256':second['baseCandidateSha256'],
        'reviewDecisionSha256':sha256_bytes(canonical_json_bytes(next_finding)),'rootKeys':keys,'allowedFields':[field],
        'additionalRevisions':1,'decision':'保留已修正内容，仅进一步明确这一名称。','provenance':'SIMULATED_USER','authorization':'用户授权局部修复裁定。'}
    root=tmp_path/'.ai-sow/work/runs'/action['runId']
    frozen={p:p.read_bytes() for p in (root/'stages').rglob('*.json')}
    write_json(tmp_path/'manual.json',auth)
    response=orchestrator_module.run_mode(tmp_path,'resume',decision='manual.json');assert response['outcome']=='ACTIVE',response
    manual=response['nextAction'];payload=prototype_payload(tmp_path,manual)
    assert payload['ownerIR']==ir
    rows=[copy.deepcopy(row) for row in ir[collection] if row['localKey'] in keys]
    selected=next(row for row in rows if row['localKey']==key)
    if stage=='SCOPE': selected['boundaryEvidence']['name']+='且已明确'
    else: selected['deliverableOutcome']+='且已明确'
    assert submit_prototype(tmp_path,manual,{collection:rows})['record']['outcome']=='SUCCEEDED'
    third=orchestrator_module.run_mode(tmp_path,'resume')['nextAction']
    assert prototype_payload(tmp_path,third)['ownerRepairAuthorization']==auth
    assert all(p.read_bytes()==raw for p,raw in frozen.items())
    submit_prototype(tmp_path,third,{'decision':'PASS','findings':[]})
    resumed=orchestrator_module.run_mode(tmp_path,'resume');assert resumed['outcome']=='ACTIVE',resumed
    assert any(ref['kind']==('SCOPE_CLOSURE' if stage=='SCOPE' else stage) for ref in resumed['state']['checkpointRefs'])
    assert orchestrator_module.status(tmp_path)['outcome']=='ACTIVE'


def test_render_completion_recovers_durable_exact_bytes_without_reexport(tmp_path,monkeypatch):
    response=orchestrator_module.start(tmp_path,write_run_store_request(tmp_path),write_budget_policy(tmp_path))
    state=response['state'];files=ProjectFiles.open(tmp_path)
    raw=canonical_json_bytes({'renders':[{'bytes':'first-real-Office-export'}]})
    digest=sha256_bytes(raw)
    staged=f".ai-sow/work/runs/{state['runId']}/step-recovery/ARTIFACT/1/RENDER/{digest}.json"
    publish=ProjectFiles.publish_new;durable_before_event=[]
    def check_order(self,path,payload):
        if '/events/' in path and json.loads(payload).get('type')=='DETERMINISTIC_STEP_FINISHED':
            durable_before_event.append(self.read_bytes(staged)==raw)
        return publish(self,path,payload)
    monkeypatch.setattr(ProjectFiles,'publish_new',check_order)
    assert orchestrator_module._deterministic_step(files,state,'RENDER',lambda:raw,stage='ARTIFACT',revision=1)==raw
    def should_not_reexport(): pytest.fail('Completed Office PDF bytes must survive the publication interruption')
    assert orchestrator_module._deterministic_step(files,state,'RENDER',should_not_reexport,stage='ARTIFACT',revision=1)==raw
    assert durable_before_event==[True,True]
    (tmp_path/staged).write_bytes(b'corrupted durable output')
    with pytest.raises(ValueError,match='不一致'):
        orchestrator_module._deterministic_step(files,state,'RENDER',should_not_reexport,stage='ARTIFACT',revision=1)


def test_uncompleted_render_staging_never_authorizes_output_reuse(tmp_path):
    response=orchestrator_module.start(tmp_path,write_run_store_request(tmp_path),write_budget_policy(tmp_path))
    state=response['state'];files=ProjectFiles.open(tmp_path)
    orphan=canonical_json_bytes({'renders':['uncompleted']});raw=canonical_json_bytes({'renders':['new real export']})
    root=f".ai-sow/work/runs/{state['runId']}/step-recovery/ARTIFACT/1/RENDER"
    files.publish_new(f'{root}/{sha256_bytes(orphan)}.json',orphan)
    another=canonical_json_bytes({'renders':['another uncompleted export']})
    files.publish_new(f'{root}/{sha256_bytes(another)}.json',another)
    called=[]
    def render(): called.append(True);return raw
    assert orchestrator_module._deterministic_step(files,state,'RENDER',render,stage='ARTIFACT',revision=1)==raw
    assert called==[True]
    assert files.read_bytes(f'{root}/{sha256_bytes(raw)}.json')==raw
    assert orchestrator_module._deterministic_step(files,state,'RENDER',
        lambda:pytest.fail('Multiple orphan blobs cannot replace the completed hash binding'),stage='ARTIFACT',revision=1)==raw


def test_render_recovery_without_staging_requires_exact_recomputed_bytes(tmp_path):
    response=orchestrator_module.start(tmp_path,write_run_store_request(tmp_path),write_budget_policy(tmp_path))
    state=response['state'];files=ProjectFiles.open(tmp_path)
    raw=canonical_json_bytes({'renders':['original export']})
    digest=sha256_bytes(raw)
    staged=tmp_path/f".ai-sow/work/runs/{state['runId']}/step-recovery/ARTIFACT/1/RENDER/{digest}.json"
    assert orchestrator_module._deterministic_step(files,state,'RENDER',lambda:raw,stage='ARTIFACT',revision=1)==raw
    staged.unlink()
    with pytest.raises(ValueError,match='不一致'):
        orchestrator_module._deterministic_step(files,state,'RENDER',lambda:b'changed Office bytes',stage='ARTIFACT',revision=1)
    assert not staged.exists()
    assert orchestrator_module._deterministic_step(files,state,'RENDER',lambda:raw,stage='ARTIFACT',revision=1)==raw
    assert staged.read_bytes()==raw
