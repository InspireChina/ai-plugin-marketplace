from __future__ import annotations
from action_ledger import CandidateResult, effective_result, effective_result_bytes, source_record_for_result

import argparse
from copy import deepcopy
import json
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Mapping, Sequence
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from referencing import Registry


PLUGIN_ROOT = Path(__file__).resolve().parents[3]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from contracts import InvalidActionResult, action_contract_binding, action_provider_request, canonical_json_bytes, estimate_action_input_tokens, load_registry, load_schema_registry, sha256_bytes, usable_action_input_tokens, validate_contract, validate_action_envelope, validate_state_combination
from generation_store import load_current, promote  # noqa: E402
from intake import prepare as prepare_input_revision  # noqa: E402
from action_ledger import (
    ActionLedger,
    AttemptLimitReached,
    diagnostic_from_value,
    diagnostic_value,
    attempt_record_from_value,
    attempt_record_value,
    issue as issue_attempt,
    finish as finish_attempt,
    is_group_ready,
    build_attempt_repair_context,
    validate_attempt_repair_context,
)
from run_events import run_event_value, validate_run_event_log
from models import (
    ActionEnvelope,
    AttemptCompletion,
    AttemptDiagnostic,
    AttemptTiming,
    ContextRefDescriptor,
    Diagnostic,
    RunEvent,
    Usage,
)  # noqa: E402
from package_renderer import PackageRenderError, prepare_draft  # noqa: E402
from runtime.project_io import ProjectFiles, ProjectIOError  # noqa: E402
from sow_model import model_skeleton  # noqa: E402
from task_standard_catalog import catalog as load_task_standard_catalog  # noqa: E402
from stage_planner import StagePlanningBlocked


SKILL_ROOT = Path(__file__).resolve().parents[1]
NEXT_SCHEMA_REGISTRY = load_registry(SKILL_ROOT / "contracts")
WORK_ROOT = ".ai-sow/work"
ACTIVE_RUN_PATH = f"{WORK_ROOT}/active-run.json"
RUNS_ROOT = f"{WORK_ROOT}/runs"
RENDERER_FINGERPRINT_PATH = SKILL_ROOT / "contracts/renderer-fingerprint-baseline.json"
def _renderer_sha256() -> str:
    baseline = json.loads(RENDERER_FINGERPRINT_PATH.read_text(encoding="utf-8"))
    files = baseline.get("files") if isinstance(baseline, Mapping) else None
    if not isinstance(files, Mapping):
        raise ProjectIOError(
            "RENDERER_FINGERPRINT_INVALID",
            "contracts/renderer-fingerprint-baseline.json",
            "renderer fingerprint baseline 结构无效。",
        )
    actual = {
        "rendererContract": baseline.get("rendererContract"),
        "files": {
            str(path): sha256_bytes((SKILL_ROOT / str(path)).read_bytes())
            for path in sorted(files)
        },
    }
    return sha256_bytes(canonical_json_bytes(actual))


def prepare_artifact(state, files, *, template_path):
    """Artifact work only starts from the current run's three verified checkpoints."""
    marker = _read_active_marker(files)
    if marker is None or marker['runId'] != state.get('runId'):
        return _blocked('ARTIFACT_INPUT_INVALID','工件生成必须使用本轮 sealed checkpoints。')
    current = _recover_active_run(files, marker)
    if state != current or template_path != _revision_template_path(files,marker['inputRevisionPath']):
        return _blocked('ARTIFACT_INPUT_INVALID','工件输入必须绑定当前 frozen run。')
    return _advance_artifact(files,current)


def _artifact_budget_guard(files, state):
    ledger = _load_action_ledger(files,state['runId'])
    if _active_seconds(ledger,_read_run_events(files,state['runId'])) >= _effective_budget_policy(files,state['runId'])[1]['maxActiveSeconds']:
        raise StagePlanningBlocked('BUDGET_EXHAUSTED')


def _artifact_result(files, state, manifest_path, digest):
    from generation_store import validate_artifact_manifest
    manifest = validate_artifact_manifest(files,manifest_path,digest)
    root = Path(manifest_path).parent.as_posix()
    return {'outcome':'REQUEST_APPROVAL','state':dict(state),'artifactManifestPath':manifest_path,
        'artifactManifestSha256':digest,'workbookPath':root+'/sow.xlsx','notesPath':root+'/sow-notes.md',
        'summary':'候选 SOW 已完成 Office 重算、双复读、完整校验及全部可见 Sheet 视觉评审。',
        'nextAction':{'contract':'ai-sow-next-action-v1','kind':'REQUEST_APPROVAL',
            'artifactManifestPath':manifest_path,'artifactManifestSha256':digest},'diagnostics':[]}



def _artifact_repair_entries(files,state):
    entries={}
    for event in _read_run_events(files,state['runId']):
        if event.type!='ARTIFACT_REPAIR_AUTHORIZED': continue
        digest=event.payload['authorizationSha256']
        answer=_mapping(files,f"{RUNS_ROOT}/{state['runId']}/artifact-repairs/{digest}.json")
        terminal=_mapping(files,_state_snapshot_path(state['runId'],answer['terminalStateSha256']))
        if digest in entries: raise ValueError('同一预览裁定不可重复授权。')
        entries[digest]={'authorization':answer,'terminalState':terminal}
    return entries


def _current_artifact_repair_plan(files,state):
    from generation_store import artifact_repair_plan
    entries=_artifact_repair_entries(files,state)
    ledger=_load_action_ledger(files,state['runId'])
    packets={envelope.value['packetSha256']:files.read_bytes(envelope.value['packetPath']) for envelope in ledger.envelopes_by_sha256.values()}
    return artifact_repair_plan(entries,[run_event_value(event) for event in _read_run_events(files,state['runId'])],
        ledger,packets,state['runId'],state['currentCandidateSha256'])


def _resume_artifact_repair(files,path):
    from generation_store import artifact_repair_plan
    answer=_mapping(files,_managed_request_path(files,path))
    if validate_contract(answer,'artifact-repair-authorization.schema.json',load_schema_registry(SKILL_ROOT)):
        raise ValueError('工件预览修复裁定无效。')
    marker=_read_active_marker(files)
    if marker is None or marker['runId']!=answer['runId']: raise ValueError('工件修复必须作用于当前停止的 run。')
    state=_read_active_run(files,marker);entries=_artifact_repair_entries(files,state);digest=sha256_bytes(canonical_json_bytes(answer))
    if digest in entries and state.get('result') is None: return
    if (state['phase']!='DONE' or state['result']!='MANUAL_REVIEW_REQUIRED'
            or sha256_bytes(canonical_json_bytes(state))!=answer['terminalStateSha256']
            or state['currentCandidateSha256']!=answer['candidateSha256'] or answer['rendererSha256']!=_renderer_sha256()):
        raise ValueError('预览修复未绑定原终态、模型和当前已修 renderer。')
    _verify_completed_stages(files,state)
    current=_current_artifact_repair_plan(files,state)
    events=[run_event_value(event) for event in _read_run_events(files,state['runId'])]
    if digest not in entries:
        entries[digest]={'authorization':answer,'terminalState':dict(state)}
        payload={'artifactRevision':current['revision']+1,'previousArtifactRevision':current['revision'],'authorizationSha256':digest}
        events.append({'runId':state['runId'],'sequence':len(events)+1,'type':'ARTIFACT_REPAIR_AUTHORIZED','payload':payload})
        ledger=_load_action_ledger(files,state['runId']);packets={e.value['packetSha256']:files.read_bytes(e.value['packetPath']) for e in ledger.envelopes_by_sha256.values()}
        artifact_repair_plan(entries,events,ledger,packets,state['runId'],state['currentCandidateSha256'])
        files.publish_new(f"{RUNS_ROOT}/{state['runId']}/artifact-repairs/{digest}.json",canonical_json_bytes(answer))
        _append_run_event(files,state['runId'],'ARTIFACT_REPAIR_AUTHORIZED',payload)
    _write_active_state(files,marker,{**state,'phase':'DRAFT','result':None,'wait':'NONE'})

def _advance_artifact(files, state):
    import package_renderer as renderer
    from generation_store import freeze_workbook, collect_artifact_proof, prepare_artifact_manifest, artifact_step_directory
    from stage_planner import _effective_envelope, _effective_success
    _verify_completed_stages(files,state)
    marker = _read_active_marker(files)
    template = _revision_template_path(files,marker['inputRevisionPath'])
    model = files.read_json(state['currentCandidatePath'])
    run_root = f"{RUNS_ROOT}/{state['runId']}"
    repair_plan=_current_artifact_repair_plan(files,state)
    temporary = files.ensure_dir(f"{RUNS_ROOT}/{state['runId']}/render-temp")
    def step(kind, operation, actual_inputs):
        revision=repair_plan['stepRevisions'][kind]
        directory=artifact_step_directory(run_root,kind,revision)
        implementation={'MATERIALIZE':['package_renderer.py','workbook.py','story_notes.py'],
            'OFFICE':['office_engine.py'],'OFFICE_REFERENCE':['office_engine.py'],
            'VALIDATE':['package_renderer.py','workbook.py'], 'RENDER':['package_renderer.py','office_engine.py'],
            'FINAL_VALIDATE':['generation_store.py','final_review.py','candidate_repair.py']}[kind]
        fingerprint=_step_fingerprint(actual_inputs,parameters={'stage':'ARTIFACT','revision':revision,'kind':kind},
            implementations=implementation,tool=_office_tool_fingerprint() if kind in {'OFFICE','OFFICE_REFERENCE','RENDER'} else None)
        raw = _read_step_output(files,state,'ARTIFACT',revision,kind,directory,fingerprint=fingerprint)
        if raw is None:
            raw = _deterministic_step(files,state,kind,operation,stage='ARTIFACT',revision=revision,fingerprint=fingerprint)
            _content(files,directory,raw)
        return json.loads(raw)
    projection = step('MATERIALIZE',lambda:renderer.project_artifact(model,template,temporary,{'decision':'PASS'}),[model,sha256_bytes(template.read_bytes())])
    calculated = step('OFFICE',lambda:renderer.calculate_artifact(projection,temporary),projection)
    reference = step('OFFICE_REFERENCE',lambda:renderer.calculate_artifact(projection,temporary),projection)
    verification = step('VALIDATE',lambda:renderer.verify_artifact(model,template,projection,calculated,reference,temporary),[model,sha256_bytes(template.read_bytes()),projection,calculated,reference])
    renders = step('RENDER',lambda:renderer.render_artifact(calculated,temporary),calculated)
    _artifact_budget_guard(files,state)
    artifact_root = f"{RUNS_ROOT}/{state['runId']}/artifacts/{repair_plan['revision']:06d}-{state['currentCandidateSha256']}"
    workbook = renderer.decode_binary(calculated['workbook']); workbook_hash=sha256_bytes(workbook)
    freeze_workbook(files,artifact_root+'/sow.xlsx',workbook,workbook_hash)
    render_refs=[]
    for item in renders['renders']:
        payload=renderer.decode_binary(item['bytes'])
        if sha256_bytes(payload)!=item['sha256']: raise ValueError('render step output hash mismatch')
        path=artifact_root+'/renders/'+item['path']; files.publish_new(path,payload)
        render_refs.append({'sheetKey':item['sheetKey'],'path':path,'sha256':item['sha256']})
    _,contract_hash = action_contract_binding(SKILL_ROOT,'ARTIFACT_VISUAL_REVIEW-v1')
    identity,logical,group = renderer.visual_identity(workbook_hash,[r['sha256'] for r in render_refs],contract_hash)
    body={'identity':identity,'workbook':{'path':artifact_root+'/sow.xlsx','sha256':workbook_hash},
        'visibleSheets':[r['sheetKey'] for r in render_refs],'renders':render_refs}
    packet={'workItems':[{'workItemId':'workbook','payload':body}],'contextRefs':[]}
    ledger=_load_action_ledger(files,state['runId'])
    if _effective_envelope(ledger,logical) is None:
        return _issue_singleton(files,state,'ARTIFACT',group,logical,'ARTIFACT_VISUAL_REVIEW-v1',canonical_json_bytes(packet))
    record_hash,record=effective_result(ledger,logical)
    renderer.validate_visual_result(packet,ledger.normalized_results[record.normalized_result_sha256])
    if json.loads(ledger.normalized_results[record.normalized_result_sha256])['overallDecision']!='PASS':
        terminal=_write_active_state(files,marker,{**state,'phase':'DONE','wait':'NONE','result':'MANUAL_REVIEW_REQUIRED','expectedActionIds':[]})
        return {'outcome':'MANUAL_REVIEW_REQUIRED','state':dict(terminal),'nextAction':None,'diagnostics':[{'code':'ARTIFACT_VISUAL_REVIEW_FAILED','message':'工作簿视觉检查未通过。'}]}
    def manifest_operation():
        fingerprint=json.loads(RENDERER_FINGERPRINT_PATH.read_bytes())
        if fingerprint['rendererContract']!=renderer.RENDERER_CONTRACT or any(
            sha256_bytes((SKILL_ROOT/path).read_bytes())!=digest for path,digest in fingerprint['files'].items()):
            raise ValueError('renderer fingerprint baseline drift')
        return prepare_artifact_manifest(files,state,template_path=template,
            proof=collect_artifact_proof(files,state,marker['inputRevisionPath'],repair_entries=_artifact_repair_entries(files,state)),calculated=calculated,
            projection=projection,verification=verification,renders=renders,renderer_fingerprint=fingerprint,
            visual_record_sha256=record_hash)
    sealed=step('FINAL_VALIDATE',manifest_operation,[state['currentCandidateSha256'],projection,calculated,reference,verification,renders,record_hash])
    _artifact_budget_guard(files,state)
    files.publish_new(sealed['manifestPath'],canonical_json_bytes(sealed['manifest']))
    # This immutable event is the benchmark's verified terminal boundary. A
    # crash before the mutable state pointer advances must not duplicate it.
    events = _read_run_events(files, state['runId'])
    latest = next((event for event in reversed(events) if event.type == 'RUN_STATE_CHANGED'), None)
    if latest is None or latest.payload['toState'] != 'AWAITING_FINAL_REVIEW':
        _append_run_event(files, state['runId'], 'RUN_STATE_CHANGED',
            {'fromState': state['phase'], 'toState': 'AWAITING_FINAL_REVIEW'})
    state=_write_active_state(files,marker,{**state,'phase':'AWAITING_FINAL_REVIEW','wait':'APPROVAL','expectedActionIds':[]})
    return _artifact_result(files,state,sealed['manifestPath'],sealed['manifestSha256'])


def _diagnostic(code: str, message: str, path: str = "") -> Diagnostic:
    return Diagnostic(code=code, message=message, path=path, details={})


def _diagnostic_value(value: Diagnostic) -> dict[str, object]:
    return {
        "code": value.code,
        "message": value.message,
        "path": value.path,
        "details": dict(value.details),
    }


def _mappings(value: object) -> list[Mapping[str, object]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _result(
    outcome: str,
    summary: str,
    *,
    diagnostics: Sequence[Diagnostic] = (),
    **values: object,
) -> dict[str, object]:
    return {
        "outcome": outcome,
        "summary": summary,
        "diagnostics": [_diagnostic_value(item) for item in diagnostics],
        **values,
    }


def _blocked(code: str, message: str, path: str = "") -> dict[str, object]:
    return _result("BLOCKED", message, diagnostics=(_diagnostic(code, message, path),))


def _optional_json(files: ProjectFiles, path: str) -> object | None:
    try:
        return files.read_json(path)
    except ProjectIOError as error:
        if error.code == "PROJECT_PATH_MISSING":
            return None
        raise


def _mapping(files: ProjectFiles, path: str) -> Mapping[str, object]:
    value = files.read_json(path)
    if not isinstance(value, Mapping):
        raise ProjectIOError("PROJECT_CONTRACT_INVALID", path, "JSON 必须是对象。")
    return value


def _input_mapping(files: ProjectFiles, path: str) -> Mapping[str, object]:
    if Path(path).is_absolute():
        try:
            relative = Path(path).resolve().relative_to(files.root).as_posix()
        except ValueError as error:
            raise ProjectIOError(
                "PROJECT_PATH_OUTSIDE_ROOT", path, "候选文件必须位于项目目录内。"
            ) from error
    else:
        relative = path
    return _mapping(files, relative)


def _managed_request_path(files: ProjectFiles, request_path: str) -> str:
    candidate = Path(request_path)
    if candidate.is_absolute():
        try:
            relative_path = candidate.absolute().relative_to(files.root).as_posix()
        except ValueError as error:
            raise ProjectIOError(
                "PROJECT_PATH_OUTSIDE_ROOT",
                request_path,
                "request 必须位于项目目录内。",
            ) from error
    else:
        relative_path = request_path
    files.resolve(relative_path, expect="file")
    return relative_path


def _run_paths(run_id: str) -> tuple[str, str, str]:
    if not isinstance(run_id, str) or not re.fullmatch(r"run-[0-9a-f]{12}", run_id):
        raise ProjectIOError("RUN_ID_INVALID", str(run_id), "run ID 格式无效。")
    root = f"{RUNS_ROOT}/{run_id}"
    return root, f"{root}/state.json", f"{root}/input-binding.json"


def _state_snapshot_path(run_id: str, state_sha256: str) -> str:
    root, _, _ = _run_paths(run_id)
    if re.fullmatch(r"[0-9a-f]{64}", state_sha256) is None:
        raise ProjectIOError(
            "RUN_STATE_HASH_INVALID", state_sha256, "run state hash 格式无效。"
        )
    return f"{root}/states/state-{state_sha256}.json"


def _active_marker_value(
    *,
    run_id: str,
    request_path: str,
    request_sha256: str,
    input_revision_sha256: str,
    input_revision_path: str,
) -> dict[str, object]:
    _, state_path, binding_path = _run_paths(run_id)
    return {
        "runId": run_id,
        "requestPath": request_path,
        "requestSha256": request_sha256,
        "inputRevisionSha256": input_revision_sha256,
        "inputRevisionPath": input_revision_path,
        "statePath": state_path,
        "bindingPath": binding_path,
        "status": "RESERVED",
        "stateSha256": None,
    }


def _read_active_marker(files: ProjectFiles) -> Mapping[str, object] | None:
    try:
        value = files.read_json(ACTIVE_RUN_PATH)
    except ProjectIOError as error:
        if error.code == "PROJECT_PATH_MISSING":
            return None
        raise
    required = {
        "runId",
        "requestPath",
        "requestSha256",
        "inputRevisionSha256",
        "inputRevisionPath",
        "statePath",
        "bindingPath",
        "status",
        "stateSha256",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise ProjectIOError(
            "ACTIVE_RUN_MARKER_INVALID",
            ACTIVE_RUN_PATH,
            "active run marker 结构无效。",
        )
    run_id = value.get("runId")
    run_root, initial_state_path, expected_binding_path = _run_paths(str(run_id))
    state_path = value.get("statePath")
    state_path_valid = state_path == initial_state_path or (
        isinstance(state_path, str)
        and re.fullmatch(
            rf"{re.escape(run_root)}/states/state-[0-9a-f]{{64}}\.json",
            state_path,
        )
        is not None
    )
    sha_fields = (value.get("requestSha256"), value.get("inputRevisionSha256"))
    input_revision_path = value.get("inputRevisionPath")
    if (
        not all(
            isinstance(item, str) and re.fullmatch(r"[0-9a-f]{64}", item)
            for item in sha_fields
        )
        or not isinstance(input_revision_path, str)
        or re.fullmatch(
            r"\.ai-sow/inputs/revisions/revision-[0-9a-f]{16}/manifest\.json",
            input_revision_path,
        )
        is None
        or not state_path_valid
        or value.get("bindingPath") != expected_binding_path
        or value.get("status") not in {"RESERVED", "ACTIVE"}
        or not isinstance(value.get("requestPath"), str)
    ):
        raise ProjectIOError(
            "ACTIVE_RUN_MARKER_INVALID",
            ACTIVE_RUN_PATH,
            "active run marker 绑定无效。",
        )
    state_sha256 = value.get("stateSha256")
    if value.get("status") == "RESERVED" and state_sha256 is not None:
        raise ProjectIOError(
            "ACTIVE_RUN_MARKER_INVALID",
            ACTIVE_RUN_PATH,
            "预留中的 active run 不得提前绑定 state hash。",
        )
    if value.get("status") == "ACTIVE" and not (
        isinstance(state_sha256, str)
        and re.fullmatch(r"[0-9a-f]{64}", state_sha256)
    ):
        raise ProjectIOError(
            "ACTIVE_RUN_MARKER_INVALID",
            ACTIVE_RUN_PATH,
            "已激活的 active run 必须绑定 state hash。",
        )
    if value.get("status") == "ACTIVE" and state_path != _state_snapshot_path(
        str(run_id), str(state_sha256)
    ):
        raise ProjectIOError(
            "ACTIVE_RUN_MARKER_INVALID",
            ACTIVE_RUN_PATH,
            "已激活的 active run 必须指向内容寻址 state snapshot。",
        )
    return value


def _initial_run_state(marker: Mapping[str, object]) -> dict[str, object]:
    return {
        "contract": "ai-sow-run-state-v3",
        "runId": marker["runId"],
        "requestSha256": marker["requestSha256"],
        "route": "FULL_COMPILE",
        "phase": "PREPARE",
        "wait": "NONE",
        "result": None,
        "currentInputRevisionSha256": marker["inputRevisionSha256"],
        "currentCandidateSha256": None,
        "currentCandidatePath": None,
        "expectedActionIds": [],
        "checkpointRefs": [],
        "resumeFromPhase": None,
    }


def _input_binding(marker: Mapping[str, object]) -> dict[str, object]:
    return {
        "runId": marker["runId"],
        "requestPath": marker["requestPath"],
        "requestSha256": marker["requestSha256"],
        "inputRevisionSha256": marker["inputRevisionSha256"],
        "inputRevisionPath": marker["inputRevisionPath"],
    }


def _validated_run_state(value: object, path: str) -> Mapping[str, object]:
    diagnostics = validate_state_combination(value, NEXT_SCHEMA_REGISTRY)
    if diagnostics or not isinstance(value, Mapping):
        raise ProjectIOError("RUN_STATE_INVALID", path, "run state 合同无效。")
    return value


def _read_active_run(
    files: ProjectFiles,
    marker: Mapping[str, object],
    *,
    verify_request: bool = True,
) -> Mapping[str, object]:
    _effective_budget_policy(files, str(marker["runId"]))
    request_path = str(marker["requestPath"])
    if (
        verify_request
        and sha256_bytes(files.read_bytes(request_path)) != marker["requestSha256"]
    ):
        raise ProjectIOError(
            "RUN_REQUEST_BINDING_STALE",
            request_path,
            "active run 绑定的 request 已变化。",
        )
    input_revision_path = str(marker["inputRevisionPath"])
    if (
        sha256_bytes(files.read_bytes(input_revision_path))
        != marker["inputRevisionSha256"]
    ):
        raise ProjectIOError(
            "RUN_INPUT_REVISION_HASH_MISMATCH",
            input_revision_path,
            "active run 绑定的 Input Revision 已变化。",
        )

    state_path = str(marker["statePath"])
    expected_state = _initial_run_state(marker)
    try:
        state = _validated_run_state(files.read_json(state_path), state_path)
    except ProjectIOError as error:
        if error.code != "PROJECT_PATH_MISSING" or marker["status"] != "RESERVED":
            raise
        state = expected_state
    if (
        state.get("runId") != marker["runId"]
        or state.get("requestSha256") != marker["requestSha256"]
        or state.get("currentInputRevisionSha256") != marker["inputRevisionSha256"]
    ):
        raise ProjectIOError(
            "RUN_STATE_BINDING_INVALID",
            state_path,
            "run state 与 active marker 绑定不一致。",
        )

    binding_path = str(marker["bindingPath"])
    expected_binding = _input_binding(marker)
    try:
        binding = files.read_json(binding_path)
    except ProjectIOError as error:
        if error.code != "PROJECT_PATH_MISSING" or marker["status"] != "RESERVED":
            raise
        binding = expected_binding
    if binding != expected_binding:
        raise ProjectIOError(
            "RUN_INPUT_BINDING_INVALID",
            binding_path,
            "run input binding 与 active marker 不一致。",
        )

    if marker["status"] == "ACTIVE":
        state_sha256 = sha256_bytes(files.read_bytes(state_path))
        if marker["stateSha256"] != state_sha256:
            raise ProjectIOError(
                "RUN_STATE_HASH_MISMATCH",
                state_path,
                "active marker 未绑定当前 run state。",
            )
    return state


def _recover_active_run(
    files: ProjectFiles,
    marker: Mapping[str, object],
    *,
    verify_request: bool = True,
) -> Mapping[str, object]:
    state = _read_active_run(files, marker, verify_request=verify_request)
    if marker["status"] == "ACTIVE":
        reconciled = _reconcile_active_state(files, marker, state)
        if (
            reconciled.get("phase") == "DONE"
            and reconciled.get("result") == "ABANDONED"
        ):
            current_marker = _read_active_marker(files)
            if current_marker is not None and current_marker.get("runId") == marker.get(
                "runId"
            ):
                active_payload = files.read_bytes(ACTIVE_RUN_PATH)
                files.unlink_exact(ACTIVE_RUN_PATH, expected_payload=active_payload)
        return reconciled

    files.publish_new(str(marker["statePath"]), canonical_json_bytes(state))
    files.publish_new(
        str(marker["bindingPath"]), canonical_json_bytes(_input_binding(marker))
    )
    return _write_active_state(files, marker, state)


def _active_result(state: Mapping[str, object]) -> dict[str, object]:
    return {
        "outcome": "ACTIVE",
        "state": dict(state),
        "diagnostics": [],
    }


def _source_contents_for_revision(
    files: ProjectFiles,
    input_revision_path: str,
    input_revision: Mapping[str, object],
) -> dict[str, str]:
    revision_root = str(Path(input_revision_path).parent.as_posix())
    contents: dict[str, str] = {}
    for block in _mappings(input_revision.get("blocks")):
        block_id = block.get("blockId")
        if not isinstance(block_id, str):
            raise ProjectIOError(
                "INPUT_REVISION_INVALID",
                input_revision_path,
                "Input Revision block 缺少 blockId。",
            )
        value = _mapping(files, f"{revision_root}/blocks/{block_id}.json")
        content = value.get("content")
        if (
            not isinstance(content, str)
            or sha256_bytes(content.encode("utf-8")) != block.get("contentSha256")
        ):
            raise ProjectIOError(
                "INPUT_REVISION_BLOCK_HASH_MISMATCH",
                f"{revision_root}/blocks/{block_id}.json",
                "Input Revision block 正文与 manifest hash 不一致。",
            )
        contents[block_id] = content
    return contents


def _next_model_action(
    files: ProjectFiles,
    state: Mapping[str, object],
) -> Mapping[str, object] | None:
    action_ids = [
        item for item in state.get("expectedActionIds", []) if isinstance(item, str)
    ]
    if state.get("wait") != "MODEL" or not action_ids:
        return None
    ledger = _load_action_ledger(files, str(state["runId"]))
    issued = {
        str(item.value["actionId"]): item
        for item in ledger.envelopes_by_sha256.values()
    }
    if any(action_id not in issued for action_id in action_ids):
        raise ProjectIOError(
            "ACTION_ISSUANCE_PROOF_INVALID", "", "等待的 action 缺少精确发行证明。"
        )
    envelopes = [dict(issued[action_id].value) for action_id in action_ids]
    if len(envelopes) == 1:
        return envelopes[0]
    group_ids = {str(envelope.get("groupId")) for envelope in envelopes}
    if len(group_ids) != 1:
        raise ProjectIOError(
            "ACTION_GROUP_BINDING_INVALID", "", "等待中的 action groupId 不一致。"
        )
    group_id = group_ids.pop()
    policies = [_published_budget_policy(files, state['runId'], envelope['budgetPolicySha256']) for envelope in envelopes]
    next_action = {
        "contract": "ai-sow-next-action-v1", "kind": "MODEL_ACTION_GROUP", "groupId": group_id,
        "maxConcurrency": min(len(envelopes), *(policy['maxConcurrency'] for policy in policies)),
        "groupDeadlineMilliseconds": 600000, "actions": envelopes,
    }
    if validate_contract(next_action, "action.schema.json", NEXT_SCHEMA_REGISTRY):
        raise ProjectIOError(
            "NEXT_ACTION_INVALID", "", "已持久化的 MODEL_ACTION_GROUP 合同无效。"
        )
    return next_action


def _public_active_result(
    files: ProjectFiles,
    state: Mapping[str, object],
) -> dict[str, object]:
    return {
        "outcome": "ACTIVE",
        "state": dict(state),
        "nextAction": _next_model_action(files, state),
        "diagnostics": [],
    }


def _prototype_inventory(files, state):
    from prototype_analysis import inventory_demo_bundle

    marker = _read_active_marker(files)
    revision_path = str(marker["inputRevisionPath"])
    revision_root = Path(revision_path).parent.as_posix()
    request = _mapping(files, f"{revision_root}/request.json")
    revision = _mapping(files, revision_path)
    demo = request.get("demo")
    if not demo:
        return None
    sources = {source["sourceId"]: source for source in revision["sources"]}
    declared = []
    for file in demo["files"]:
        source = sources[file["sourceId"]]
        content = files.read_bytes(source["path"])
        if sha256_bytes(content) != source["rawSha256"]:
            raise ProjectIOError("SOURCE_HASH_MISMATCH", source["path"], "Demo 原始字节发生变化。")
        declared.append({"sourceId": file["sourceId"], "relativePath": Path(source["path"]).relative_to(revision_root).as_posix(), "content": content})
    return inventory_demo_bundle("demo/" + demo["entrypoint"], declared)


def _prototype_execution_counts(files: ProjectFiles, run_id: str) -> tuple[dict[str, int], bool]:
    """Derive known trace counts and uncertainty; never persist counters."""
    ledger = _load_action_ledger(files, run_id)
    counts = {"maxScenarioSteps": 0, "maxScreenshots": 0}
    unmeasured = False
    for record in ledger.attempt_records.values():
        envelope = ledger.envelopes_by_sha256[record.envelope_sha256]
        if envelope.value["actionContractId"] != "PROTOTYPE_BROWSER-v1":
            continue
        if record.normalized_result_sha256 is None:
            if record.failure_kind == "EXECUTION" and record.timing.started_at_utc is not None:
                unmeasured = True
            continue
        trace = json.loads(ledger.normalized_results[record.normalized_result_sha256])
        steps = [step for run in trace["runs"] for step in run["steps"]]
        counts["maxScenarioSteps"] += len(steps)
        counts["maxScreenshots"] += sum(step["screenshotSha256"] is not None for step in steps)
    return counts, unmeasured


def _prototype_bundles(files,state):
    from stage_planner import _effective_envelope,_effective_success
    ledger=_load_action_ledger(files,state['runId'])
    keys=[]
    for event in _read_run_events(files,state['runId']):
        if event.type!='ACTION_ISSUED': continue
        envelope=ledger.envelopes_by_sha256[event.payload['envelopeSha256']]
        key=envelope.value['logicalWorkId']
        if envelope.value['actionContractId'].startswith('PROTOTYPE_') and key not in keys: keys.append(key)
    bundles=[]
    for key in keys:
        envelope=_effective_envelope(ledger,key)
        if not is_group_ready(ledger,[key]): continue
        digest,result=effective_result(ledger,key)
        source=source_record_for_result(ledger,digest)
        source_sha=sha256_bytes(canonical_json_bytes(attempt_record_value(source)))
        normalized=effective_result_bytes(ledger,key)
        bundles.append({'attemptRecord':attempt_record_value(source),
            **({'candidateResolutionSha256':digest,'sourceAttemptRecordSha256':source_sha}
               if isinstance(result,CandidateResult) else {}),
            'normalizedResultSha256':result.normalized_result_sha256,'envelope':dict(envelope.value),
            'packet':_mapping(files,envelope.value['packetPath']),
            'normalizedResult':json.loads(normalized)})
    return bundles


def _issue_prototype(files,state,action_kind,round):
    inventory=_prototype_inventory(files,state)
    identity={'stageKind':'SCOPE','actionKind':action_kind,'inputRevisionSha256':state['currentInputRevisionSha256'],
        'bundleSha256':inventory['bundleSha256'],'round':round}
    payload={'identity':identity,'inventory':inventory,'prototypeLedger':None}
    records=_prototype_bundles(files,state)
    def of_kind(kind): return [row for row in records if row['envelope']['actionContractId']==kind+'-v1']
    if action_kind=='PROTOTYPE_SCENARIO':
        payload['demoLimits']=_effective_budget_policy(files,state['runId'])[1]['demoLimits']
        counts,unmeasured=_prototype_execution_counts(files,state['runId'])
        if unmeasured: return _prototype_wait(files,state,'PROTOTYPE_EXECUTION_UNMEASURED')
        payload['demoRemaining']={key:max(0,payload['demoLimits'][key]-count) for key,count in counts.items()}
    if of_kind('PROTOTYPE_ANALYZE'):
        payload['prototypeLedger']=_publish_prototype_ledger(files,state)
    if action_kind in {'PROTOTYPE_BROWSER','PROTOTYPE_ANALYZE'}:
        scenario=of_kind('PROTOTYPE_SCENARIO')[-1]
        payload['scenario']=_prototype_result_ref(scenario)
        for key in ('demoLimits','demoRemaining'): payload[key]=scenario['packet']['workItems'][0]['payload'][key]
    if action_kind=='PROTOTYPE_BROWSER' and of_kind('PROTOTYPE_BROWSER'):
        payload['browserProfileSource']=_prototype_result_ref(of_kind('PROTOTYPE_BROWSER')[0])
    if action_kind=='PROTOTYPE_ANALYZE': payload['trace']=_prototype_result_ref(of_kind('PROTOTYPE_BROWSER')[-1])
    logical='logical-'+sha256_bytes(canonical_json_bytes(identity))
    group='control-group-'+sha256_bytes(canonical_json_bytes({'logicalWorkId':logical}))
    packet=canonical_json_bytes({'workItems':[{'workItemId':logical,'payload':payload}],'contextRefs':[]})
    return _issue_singleton(files,state,'SCOPE',group,logical,action_kind+'-v1',packet)


def _prototype_result_ref(bundle):
    return {**({'candidateResolutionSha256':bundle['candidateResolutionSha256']} if 'candidateResolutionSha256' in bundle else {}),
            "logicalWorkId": bundle["envelope"]["logicalWorkId"],
            "attemptRecordSha256": sha256_bytes(canonical_json_bytes(bundle["attemptRecord"])),
            "normalizedResultSha256": bundle["normalizedResultSha256"],
            "normalizedResult": bundle["normalizedResult"]}


def _prototype_wait(files, state, code):
    run_id = str(state["runId"])
    wait_id = "prototype-wait-" + code
    events = _read_run_events(files, run_id)
    if not any(event.type == "WAITING_INPUT_ENTERED" and event.payload["waitId"] == wait_id for event in events):
        _append_run_event(files, run_id, "RUN_STATE_CHANGED", {"fromState": state["phase"], "toState": "WAITING_INPUT"})
        _append_run_event(files, run_id, "WAITING_INPUT_ENTERED", {"waitId": wait_id, "reasonCode": code})
    waiting = _write_active_state(files, _read_active_marker(files), {**state, "wait": "INPUT", "expectedActionIds": [], "resumeFromPhase": state["phase"]})
    return {"outcome": "WAITING_INPUT", "state": dict(waiting), "nextAction": None,
            "diagnostics": [_diagnostic_value(_diagnostic(code, "Demo 证据尚未闭合，请补充完整输入后重新启动。"))]}


def _publish_prototype_ledger(files, state):
    from prototype_analysis import verify_prototype_trace, verify_prototype_observations

    run_id = str(state["runId"])
    inventory = _prototype_inventory(files, state)
    ledger = _load_action_ledger(files, run_id)
    rounds = []
    dispositions = {}
    bundles=_prototype_bundles(files,state)
    for bundle in bundles:
        if bundle['envelope']['actionContractId']!='PROTOTYPE_ANALYZE-v1': continue
        payload = bundle["packet"]["workItems"][0]["payload"]
        round_number = payload["identity"]["round"]
        verify_prototype_observations(inventory, payload["scenario"]["normalizedResult"], payload["trace"]["normalizedResult"], bundle["normalizedResult"])
        evidence = verify_prototype_trace(inventory, payload["scenario"]["normalizedResult"], payload["trace"]["normalizedResult"])
        attempts = []
        for item in bundles:
            if item['packet']['workItems'][0]['payload']['identity']['round']==round_number:
                work=item['envelope']['logicalWorkId']
                attempts.extend(digest for digest,record in sorted(ledger.attempt_records.items(),key=lambda pair:(pair[1].revision,pair[1].attempt)) if record.logical_work_id==work)
                from candidate_repair import patch_context
                attempts.extend(d for d,r in ledger.attempt_records.items() if
                    ledger.envelopes_by_sha256[r.envelope_sha256].value['actionContractId']=='CANDIDATE_PATCH-v1'
                    and patch_context(files.read_json(ledger.envelopes_by_sha256[r.envelope_sha256].value['packetPath']))['origin']['originLogicalWorkId']==work)
        observations = bundle["normalizedResult"]["observations"]
        round_dispositions = {item["interactionId"]: item["disposition"] for item in evidence["interactionDispositions"]}
        for observation in observations:
            for interaction_id in observation["interactionIds"]:
                if observation["scopeRelation"] == "NON_SCOPE":
                    round_dispositions[interaction_id] = "EXCLUDED"
                elif observation["runtimeStatus"] == "CODE_ONLY":
                    round_dispositions.setdefault(interaction_id, "NOT_EXERCISED")
                elif observation["runtimeStatus"] in {"BROKEN", "NOT_EXERCISED"}:
                    round_dispositions[interaction_id] = observation["runtimeStatus"]
        evidence["interactionDispositions"] = [{"interactionId": key, "disposition": value} for key, value in sorted(round_dispositions.items())]
        rounds.append({"round": round_number, "attemptRecordSha256s": attempts,
                       "observationRefs": [{**({'candidateResolutionSha256':bundle['candidateResolutionSha256']} if 'candidateResolutionSha256' in bundle else {}), "localKey": item["localKey"], "attemptRecordSha256": sha256_bytes(canonical_json_bytes(bundle["attemptRecord"])), "normalizedResultSha256": bundle["normalizedResultSha256"], "pointer": f"/observations/{index}"} for index, item in enumerate(observations)],
                       "interactionDispositions": evidence["interactionDispositions"]})
        dispositions.update({item["interactionId"]: item["disposition"] for item in evidence["interactionDispositions"]})
    value = {"bundleSha256": inventory["bundleSha256"], "rounds": rounds,
             "interactionDispositions": [{"interactionId": key, "disposition": value} for key, value in sorted(dispositions.items())],
             "sealed": set(dispositions) == {item["interactionId"] for item in inventory["interactions"]}}
    payload = canonical_json_bytes(value)
    digest = sha256_bytes(payload)
    path = f"{RUNS_ROOT}/{run_id}/stages/SCOPE/prototype-ledgers/{digest}.json"
    files.publish_new(path, payload)
    return {"path": path, "sha256": digest, "value": value}


def _planning_policy(value):
    from stage_planner import RunBudgetPolicy, DemoBudgetLimits
    return RunBudgetPolicy(value['contractVersion'], value['modelProfileId'], value['modelContextLimitTokens'],
        value['estimatorVersion'], value['maxPlannedTokens'], value['maxActiveSeconds'], value['outputReserveTokens'],
        value['hydrateReserveTokens'], value['safetyMarginTokens'], value['referenceOverheadTokens'],
        value['maxConcurrency'], DemoBudgetLimits(value['demoLimits']['maxDiscoveryRounds'],
            value['demoLimits']['maxScenarioSteps'], value['demoLimits']['maxScreenshots']))


def _prior_inventories(files, state):
    from prior_state import inventory_prior_workbook
    marker = _read_active_marker(files)
    revision = _mapping(files, marker['inputRevisionPath'])
    inventories = {}
    for source in revision['sources']:
        if source['role'] != 'PRIOR_SOW' or source['rawSha256'] in inventories:
            continue
        digest = source['rawSha256']
        path = f"{RUNS_ROOT}/{state['runId']}/stages/SCOPE/prior-inventories/{digest}.json"
        inventory = _optional_json(files, path)
        if inventory is None:
            source_path = files.resolve(source['path'], expect='file')
            if sha256_bytes(files.read_bytes(source['path'])) != digest:
                raise ValueError('Prior input hash 漂移。')
            inventory = inventory_prior_workbook(source_path)
            files.publish_new(path, canonical_json_bytes(inventory))
        if inventory['workbookSha256'] != digest:
            raise ValueError('Prior inventory 未绑定输入。')
        inventories[digest] = inventory
    return tuple(inventories.values())


def _scope_plan_inputs(files, state):
    from scope_compiler import prepare_scope_inputs, prepare_scope_prototype_contexts
    marker = _read_active_marker(files)
    revision_path = marker['inputRevisionPath']
    revision_bytes = files.read_bytes(revision_path)
    revision = json.loads(revision_bytes)
    request = _mapping(files, str(Path(revision_path).parent / 'request.json'))
    refs = ()
    if request.get('demo'):
        inventory = _prototype_inventory(files, state)
        prototype = _publish_prototype_ledger(files, state)
        refs = prepare_scope_prototype_contexts(inventory, prototype['value'], _load_action_ledger(files, state['runId']))
    items, contexts = prepare_scope_inputs(revision_bytes, _source_contents_for_revision(files, revision_path, revision),
        request=request, prior_inventories=_prior_inventories(files, state), prototype_context_refs=refs)
    return items, contexts


def _frozen_scope_plan(files, state):
    from stage_planner import plan_stage, bound_action_contract_ids
    from scope_compiler import build_scope_work_descriptors
    root = files.ensure_dir(f"{RUNS_ROOT}/{state['runId']}/stages/SCOPE/plans")
    paths = list(root.glob('*.json'))
    if len(paths) > 1:
        raise ValueError('每阶段只能有一个完整冻结 StagePlan。')
    existing = json.loads(paths[0].read_bytes()) if paths else None
    policy_value = (_published_budget_policy(files, state['runId'], existing['budgetPolicySha256'])
                    if existing else _effective_budget_policy(files, state['runId'])[1])
    policy = _planning_policy(policy_value)
    items, contexts = _scope_plan_inputs(files, state)
    contract_ids = bound_action_contract_ids(existing) if existing else None
    works = build_scope_work_descriptors(items, contexts, policy, action_contract_ids=contract_ids)
    plan = plan_stage('SCOPE', items, contexts, works, [], policy, action_contract_ids=contract_ids)
    if existing:
        if existing != plan or paths[0].stem != sha256_bytes(canonical_json_bytes(existing)):
            raise ValueError('StagePlan 与完整冻结输入不一致。')
    else:
        files.publish_new(f"{RUNS_ROOT}/{state['runId']}/stages/SCOPE/plans/{sha256_bytes(canonical_json_bytes(plan))}.json", canonical_json_bytes(plan))
    return plan, items, contexts, policy


def _envelope_for_work(files, state, stage, group_id, logical_id, contract_id, packet):
    contract, digest = action_contract_binding(SKILL_ROOT, contract_id)
    policy_hash, policy = _effective_budget_policy(files, state['runId'])
    action_id = 'action-' + sha256_bytes(canonical_json_bytes({'runId':state['runId'], 'logicalWorkId':logical_id, 'revision':1, 'attempt':1}))[:12]
    paths = _action_paths(state['runId'], action_id)
    output = min(contract['limits']['maxOutputTokens'], policy['outputReserveTokens'])
    hydrate = min(contract['limits']['maxHydrateTokens'], policy['hydrateReserveTokens'])
    if contract['executionKind'] == 'HOST_BROWSER': output, hydrate = 0, 0
    value = {'contract':'ai-sow-action-v3','runId':state['runId'],'actionId':action_id,
        'logicalWorkId':logical_id,'revision':1,'attempt':1,'stageKind':stage,'groupId':group_id,
        'inputRevisionSha256':state['currentInputRevisionSha256'],
        'upstreamCheckpointSha256s':sorted(ref['sha256'] for ref in state['checkpointRefs']),
        'baseCandidateSha256':state['currentCandidateSha256'],'actionContractId':contract_id,
        'actionContractSha256':digest,'packetPath':paths['packet'],'packetSha256':sha256_bytes(packet),
        'resultPath':paths['output'],'validatorVersion':'action-result-dispatch-v1','budgetPolicySha256':policy_hash,
        'executionLimits':{'estimatedInputTokens':estimate_action_input_tokens(SKILL_ROOT, contract_id, packet,
            budget_policy=policy,max_output_tokens=output),'maxOutputTokens':output,'maxHydrateTokens':hydrate}}
    previous = _optional_json(files, paths['envelope'])
    if previous is not None:
        # Physical interrupted publication retains its original issuance policy.
        if any(previous[key] != value[key] for key in value if key not in {'budgetPolicySha256','executionLimits'}):
            raise ValueError('原 Envelope 与冻结工作不一致。')
        return previous
    return value


def _issue_frozen_group(files, state, plan, items, contexts, group):
    from stage_planner import materialize_packet, DependencyResultRef, _effective_success, _effective_envelope
    ledger = _load_action_ledger(files, state['runId'])
    works = {work['logicalWorkId']: work['packetPlan'] for work in plan['works']}
    prepared = []
    for key in group['requiredLogicalWorkIds']:
        previous = _effective_envelope(ledger, key)
        if previous is not None:
            continue
        descriptor = works[key]
        dependencies = []
        for dependency in descriptor['dependencyLogicalWorkIds']:
            digest, result = effective_result(ledger, dependency)
            dependencies.append(DependencyResultRef(dependency, digest, effective_result_bytes(ledger,dependency),
                result.source_attempt_record_sha256 if isinstance(result,CandidateResult) else None))
        packet = materialize_packet(plan, key, 1, items, contexts, dependencies, ledger)
        envelope = _envelope_for_work(files, state, plan['stageKind'], group['groupId'], key, descriptor['actionContractId'], packet)
        prepared.append((envelope, packet))
    policy = _effective_budget_policy(files, state['runId'])[1]
    _guard_action_budget(ledger, _read_run_events(files, state['runId']), policy, [
        ActionEnvelope(value, _action_paths(state['runId'],value['actionId'])['envelope'], sha256_bytes(canonical_json_bytes(value)))
        for value, packet in prepared])
    for envelope, packet in prepared:
        _persist_issued_action(files, envelope, packet)
    ledger = _load_action_ledger(files, state['runId'])
    expected = []
    for key in group['requiredLogicalWorkIds']:
        envelope = _effective_envelope(ledger, key)
        record = next((record for record in ledger.attempt_records.values() if record.envelope_sha256 == envelope.sha256), None)
        if effective_result_bytes(ledger,key) is None: expected.append(envelope.value['actionId'])
    state = _write_active_state(files, _read_active_marker(files), {**state,
        'phase':_phase_for_action_stage(plan['stageKind']), 'wait':'MODEL' if expected else 'NONE', 'expectedActionIds':expected})
    return _public_active_result(files, state)


def _start_public_pipeline(files, state):
    marker = _read_active_marker(files)
    revision = _mapping(files, marker['inputRevisionPath'])
    request = _mapping(files, str(Path(marker['inputRevisionPath']).parent / 'request.json'))
    if state['currentCandidateSha256'] is None:
        _append_candidate_snapshot(files, state['runId'], model_skeleton(request, revision))
        state = _read_active_run(files, _read_active_marker(files))
    if request.get('demo'):
        return _issue_prototype(files, state, 'PROTOTYPE_SCENARIO', 1)
    from stage_planner import next_issuable_group
    plan, items, contexts, policy = _frozen_scope_plan(files, state)
    group = next_issuable_group(plan, _load_action_ledger(files, state['runId']))
    return _issue_frozen_group(files, state, plan, items, contexts, group)


def _pending_abandon_decision(
    files: ProjectFiles,
    state: Mapping[str, object],
) -> bool:
    root_path = f"{RUNS_ROOT}/{state['runId']}/decisions"
    try:
        root = files.resolve(root_path, expect="dir")
    except ProjectIOError as error:
        if error.code == "PROJECT_PATH_MISSING":
            return False
        raise
    for path in sorted(root.glob("abandon-*.json")):
        relative = path.relative_to(files.root).as_posix()
        decision = _mapping(files, relative)
        payload = canonical_json_bytes(decision)
        if (
            path.name != f"abandon-{sha256_bytes(payload)}.json"
            or decision.get("decision") != "ABANDON"
            or validate_contract(
                decision, "artifact-approval.schema.json", NEXT_SCHEMA_REGISTRY
            )
        ):
            raise ProjectIOError(
                "ABANDON_DECISION_INVALID", relative, "放弃决定合同或文件名无效。"
            )
        if decision.get("candidateSha256") == state.get("currentCandidateSha256"):
            return True
    return False




def _verify_completed_stages(files,state):
    from final_review import verify_checkpoint_proof
    from task_compiler import verify_task_repair_chain
    ledger=_load_action_ledger(files,state['runId'])
    packets={item.value['packetSha256']:files.read_bytes(item.value['packetPath']) for item in ledger.envelopes_by_sha256.values()}
    completed={}
    for stage in ('SCOPE','STORY_AC','TASK'):
        root=_stage_root(state,stage)
        raw=_one_content(files,root+'/checkpoints')
        if raw is None: break
        checkpoint=json.loads(raw)
        plan=_one_content(files,root+'/plans')
        for revision in range(1,_stage_revision_limit(files,state,stage)+1):
            review = _read_step_output(files,state,stage,revision,'MATERIALIZE',root+f'/review-inputs/{revision}')
            validator = _read_step_output(files,state,stage,revision,'VALIDATE',root+f'/validators/{revision}')
            if (review is None) != (validator is None):
                raise ValueError('Checkpoint 缺少完整物化或验证输出事务。')
        def content_map(relative,pattern):
            try: directory=files.resolve(root+'/'+relative,expect='dir')
            except ProjectIOError as error:
                if error.code=='PROJECT_PATH_MISSING': return {}
                raise
            values={}
            for path in directory.glob(pattern):
                payload=files.read_bytes(path.relative_to(files.root).as_posix())
                if sha256_bytes(payload)!=path.stem: raise ValueError('Checkpoint proof 内容 hash 漂移。')
                if path.stem in values: raise ValueError('Checkpoint proof 不唯一。')
                values[path.stem]=payload
            return values
        upstream=[] if stage=='SCOPE' else [completed['SCOPE' if stage=='STORY_AC' else 'STORY_AC']]
        verify_checkpoint_proof(checkpoint,task_repair_verifier=verify_task_repair_chain,revision_bytes=files.read_bytes(_read_active_marker(files)['inputRevisionPath']),
            plan_bytes=plan,upstream_bytes=upstream,ledger=ledger,candidates=content_map('candidates','*.json'),
            validators=content_map('validators','*/*.json'),review_inputs=content_map('review-inputs','*/*.json'),
            packets=packets,prior_states=content_map('prior-states','*.json'),
            manual_authorizations={key:value['answer'] for key,value in _manual_repair_records(files,state,stage).items()})
        completed[stage]=raw
    for ref in state['checkpointRefs']:
        stage='SCOPE' if ref['kind']=='SCOPE_CLOSURE' else ref['kind']
        if stage not in completed or sha256_bytes(completed[stage])!=ref['sha256'] or files.read_bytes(ref['path'])!=completed[stage]:
            raise ValueError('状态 checkpoint 引用未绑定完整证明。')


def _stage_root(state, stage):
    return f"{RUNS_ROOT}/{state['runId']}/stages/{stage}"


def _one_content(files, directory):
    try:
        root = files.resolve(directory, expect='dir')
    except ProjectIOError as error:
        if error.code == 'PROJECT_PATH_MISSING': return None
        raise
    paths = list(root.glob('*.json'))
    if len(paths) > 1: raise ValueError('同一已封输入只能有一个内容寻址值。')
    if not paths: return None
    raw = files.read_bytes(paths[0].relative_to(files.root).as_posix())
    if sha256_bytes(raw) != paths[0].stem: raise ValueError('内容寻址文件 hash 漂移。')
    return raw


def _content(files, directory, raw):
    digest = sha256_bytes(raw)
    files.publish_new(f'{directory}/{digest}.json', raw)
    return digest


def _checkpoint_bytes(files, state, stage):
    raw = _one_content(files, _stage_root(state, stage)+'/checkpoints')
    if raw is None: raise ValueError('缺少 sealed 上游 checkpoint。')
    return raw


def _frozen_stage_inputs(files, state, stage):
    if stage == 'SCOPE':
        plan, items, contexts, policy = _frozen_scope_plan(files, state)
        return plan, items, contexts, policy, None
    from delivery_compiler import prepare_story_inputs, build_story_work_descriptors
    from task_compiler import prepare_task_inputs, build_task_work_descriptors
    from stage_planner import plan_stage, bound_action_contract_ids
    upstream = 'SCOPE' if stage == 'STORY_AC' else 'STORY_AC'
    checkpoint_raw = _checkpoint_bytes(files, state, upstream)
    checkpoint = json.loads(checkpoint_raw)
    candidate = files.read_bytes(_stage_root(state, upstream)+f"/candidates/{checkpoint['candidateSha256']}.json")
    if stage == 'STORY_AC':
        inputs = prepare_story_inputs(candidate, checkpoint_raw, checkpoint_sha256=sha256_bytes(checkpoint_raw))
        builder = build_story_work_descriptors
    else:
        scope_checkpoint = json.loads(_checkpoint_bytes(files,state,'SCOPE'))
        prior_hash = scope_checkpoint.get('priorStateSha256')
        prior = files.read_bytes(_stage_root(state,'SCOPE')+f'/prior-states/{prior_hash}.json') if prior_hash else None
        scope_packet = _review_packet_for_candidate(files,state,'SCOPE',scope_checkpoint['candidateSha256'])
        graph = canonical_json_bytes(scope_packet['workItems'][0]['payload']['changeGraph'])
        inputs = prepare_task_inputs(candidate, checkpoint_raw, checkpoint_sha256=sha256_bytes(checkpoint_raw),
            task_catalog=load_task_standard_catalog(_revision_template_path(files,_read_active_marker(files)['inputRevisionPath'])),
            input_revision_bytes=files.read_bytes(_read_active_marker(files)['inputRevisionPath']),
            prior_state_bytes=prior,prior_state_sha256=prior_hash,change_graph_bytes=graph if prior else None,
            change_graph_sha256=sha256_bytes(graph) if prior else None)
        builder=build_task_work_descriptors
    existing=_one_content(files,_stage_root(state,stage)+'/plans')
    policy_value=(_published_budget_policy(files,state['runId'],json.loads(existing)['budgetPolicySha256'])
                  if existing else _effective_budget_policy(files,state['runId'])[1])
    policy=_planning_policy(policy_value)
    contract_ids=bound_action_contract_ids(json.loads(existing)) if existing else None
    options={'action_contract_ids':contract_ids} if stage=='TASK' else {}
    plan=plan_stage(stage,inputs.work_items,inputs.context_refs,builder(inputs.work_items,inputs.context_refs,policy,**options),
        [sha256_bytes(checkpoint_raw)],policy,action_contract_ids=contract_ids)
    raw=canonical_json_bytes(plan)
    if existing is not None and raw!=existing: raise ValueError('阶段计划不再匹配 sealed 上游。')
    _content(files,_stage_root(state,stage)+'/plans',raw)
    return plan,inputs.work_items,inputs.context_refs,policy,inputs


def _step_output_hash(files, state, stage, revision, kind, *, fingerprint=None):
    events=[e for e in _read_run_events(files,state['runId']) if e.type=='DETERMINISTIC_STEP_FINISHED'
            and e.payload['outcome']=='SUCCEEDED' and e.payload.get('stageKind')==stage
            and e.payload.get('semanticRevision')==revision and e.payload['stepKind']==kind]
    if fingerprint is None and events:
        fingerprint=events[-1].payload.get('stepFingerprint')
    hashes={e.payload['outputSha256'] for e in events if e.payload.get('stepFingerprint')==fingerprint}
    if len(hashes)>1:raise ValueError('相同实际输入与指纹的步骤有冲突输出。')
    return next(iter(hashes),None)


def _read_step_output(files, state, stage, revision, kind, directory, *, fingerprint=None):
    expected=_step_output_hash(files,state,stage,revision,kind,fingerprint=fingerprint)
    if expected is None:return None
    try:raw=files.read_bytes(f'{directory}/{expected}.json')
    except ProjectIOError as error:
        if error.code=='PROJECT_PATH_MISSING':return None
        raise
    if sha256_bytes(raw)!=expected:raise ValueError('确定性输出未绑定实际完成事件。')
    return raw


def _step_fingerprint(inputs, *, parameters, implementations, tool=None):
    from generation_store import step_fingerprint
    return step_fingerprint(
        inputs,parameters=parameters,implementations=implementations,tool=tool
    )


def _office_tool_fingerprint():
    from office_engine import office_tool_fingerprint
    return office_tool_fingerprint()


class DeterministicStepFailure(ValueError):
    def __init__(self, message, diagnostic, *, stage, revision, kind, attempt, limit):
        super().__init__(message)
        self.diagnostic = diagnostic
        self.stage, self.revision, self.kind = stage, revision, kind
        self.attempt, self.limit = attempt, limit


def _failed_deterministic_steps(files, state):
    latest = {}
    for event in _read_run_events(files, state['runId']):
        if event.type != 'DETERMINISTIC_STEP_FINISHED' or 'stageKind' not in event.payload: continue
        item = event.payload
        key = (item['stageKind'], item['semanticRevision'], item['stepKind'])
        latest[key] = item
    return [item for _, item in sorted(latest.items()) if item['outcome'] == 'FAILED']


def _deterministic_step(files, state, kind, operation, *, stage, revision, fingerprint=None):
    ledger = _load_action_ledger(files, state['runId'])
    if _active_seconds(ledger, _read_run_events(files, state['runId'])) >= _effective_budget_policy(files, state['runId'])[1]['maxActiveSeconds']:
        raise StagePlanningBlocked('BUDGET_EXHAUSTED')
    previous = _step_output_hash(files, state, stage, revision, kind, fingerprint=fingerprint)
    limit = _effective_budget_policy(files, state['runId'])[1].get('maxDeterministicAttempts', 2)
    failures = [event for event in _read_run_events(files, state['runId'])
        if event.type == 'DETERMINISTIC_STEP_FINISHED' and event.payload['outcome'] == 'FAILED'
        and event.payload.get('stageKind') == stage and event.payload.get('semanticRevision') == revision
        and event.payload['stepKind'] == kind]
    if previous is None and len(failures) >= limit:
        raise StagePlanningBlocked('BUDGET_EXHAUSTED')
    attempt = len(failures) + 1
    started = datetime.now(UTC).isoformat().replace('+00:00', 'Z')
    outcome = 'SUCCEEDED'; failure = None; digest = None; diagnostic = None; record_event = True
    try:
        raw = None
        recovery_root = f"{RUNS_ROOT}/{state['runId']}/step-recovery/{stage}/{revision}/{kind}"
        if previous is not None:
            try:
                raw = files.read_bytes(f'{recovery_root}/{previous}.json')
            except ProjectIOError as error:
                if error.code != 'PROJECT_PATH_MISSING':
                    raise
        if (raw is None or (previous is not None and sha256_bytes(raw) != previous)) and len(failures) >= limit:
            record_event = False
            raise StagePlanningBlocked('BUDGET_EXHAUSTED')
        if raw is None:
            raw = operation()
        digest = sha256_bytes(raw)
        if previous is not None and digest != previous:
            raise ValueError('恢复运算与原完成事件输出不一致。')
        # Preserve the actual result before its completion event. Recovery uses
        # only an exact hash bound to success, including nondeterministic Office bytes.
        files.publish_new(f'{recovery_root}/{digest}.json', raw)
        return raw
    except StagePlanningBlocked:
        record_event = False
        raise
    except Exception as error:
        from models import AttemptDiagnostic
        outcome = 'FAILED'; failure = getattr(error, 'code', type(error).__name__)
        diagnostic = getattr(error, 'diagnostic', None) or AttemptDiagnostic(
            str(failure), f'/{stage}/{revision}/{kind}', ())
        from scope_compiler import ScopeInputRequired
        from prior_state import PriorInputRequired
        from delivery_compiler import StoryInputRequired
        from task_compiler import TaskInputRequired
        if isinstance(error, (ScopeInputRequired, PriorInputRequired, StoryInputRequired, TaskInputRequired)):
            raise
        raise DeterministicStepFailure(str(error), diagnostic, stage=stage, revision=revision,
            kind=kind, attempt=attempt, limit=limit) from error
    finally:
        payload = {'stepKind': kind, 'outcome': outcome, 'startedAtUtc': started,
            'endedAtUtc': datetime.now(UTC).isoformat().replace('+00:00', 'Z')}
        if failure is not None:
            payload.update(failureCode=failure, stageKind=stage, semanticRevision=revision,
                attempt=attempt, diagnostic=diagnostic_value(diagnostic))
        else:
            payload.update(stageKind=stage, semanticRevision=revision, outputSha256=digest)
        # Record the completed computation and its exact output before any output publication.
        if fingerprint is not None:payload['stepFingerprint']=fingerprint
        if record_event:
            _append_run_event(files, state['runId'], 'DETERMINISTIC_STEP_FINISHED', payload)


def _stage_ir(files,state,stage,plan,items,contexts,policy,inputs):
    ledger=_load_action_ledger(files,state['runId'])
    if stage=='SCOPE':
        from scope_compiler import _complete_scope_results
        refs,packets,results=_complete_scope_results(plan,items,contexts,ledger,policy)
        scope_works={work['logicalWorkId'] for work in plan['works'] if work['packetPlan']['actionKind'].startswith('SCOPE_')}
        consumed={key for work in plan['works'] if work['logicalWorkId'] in scope_works for key in work['packetPlan']['dependencyLogicalWorkIds']}
        root=(scope_works-consumed).pop()
        return packets[root],results[root]
    from delivery_compiler import _complete_story_results
    from task_compiler import _complete_task_results
    from final_review import OWNER_COLLECTION
    results=(_complete_story_results if stage=='STORY_AC' else _complete_task_results)(inputs,plan,ledger,policy)
    packet={'workItems':[{'workItemId':item.work_item_id,'payload':item.work_item_payload} for item in items],
        'contextRefs':[{'refId':ref.ref_id,'canonicalContent':json.loads(ref.canonical_content),'contentSha256':sha256_bytes(ref.canonical_content)} for ref in contexts]}
    collection=OWNER_COLLECTION[stage]
    joined={collection:[]}
    for key,result in results:
        for original in result[collection]:
            row=deepcopy(original);row['localKey']=key+':'+row['localKey'];joined[collection].append(row)
    joined[collection].sort(key=lambda row:row['localKey'])
    return packet,joined


def _owner_index(stage,material,packet,decisions):
    from final_review import OWNER_COLLECTION
    from delivery_compiler import _story_node_bindings
    from task_compiler import _task_node_bindings
    from sow_model import NODE_COLLECTIONS
    model=json.loads(material.candidate_bytes)
    paths={node[field]:'/'+collection+'/'+str(index) for collection,field in NODE_COLLECTIONS.items()
           for index,node in enumerate(model[collection])}
    if stage=='SCOPE':
        return {key:{'id':value,'path':paths[value]} for key,value in sorted(material.identity_by_local_key.items())}
    collection=OWNER_COLLECTION[stage];field='storyId' if stage=='STORY_AC' else 'taskId'
    bindings=_story_node_bindings if stage=='STORY_AC' else _task_node_bindings
    return {row['localKey']:{'id':node[field],'path':paths[node[field]]} for row in decisions[collection]
            for name,node in bindings(packet,{collection:[row]}) if name==collection}


def _review_packet_for_candidate(files,state,stage,candidate_hash):
    root=files.resolve(_stage_root(state,stage)+'/review-inputs',expect='dir')
    matches=[]
    for path in root.glob('*/*.json'):
        raw=files.read_bytes(path.relative_to(files.root).as_posix())
        if sha256_bytes(raw)!=path.stem: raise ValueError('Review input hash 漂移。')
        value=json.loads(raw)
        if value['workItems'][0]['payload']['candidateSha256']==candidate_hash: matches.append(value)
    if len(matches)!=1: raise ValueError('候选必须绑定唯一 fresh Review input。')
    return matches[0]


def _control_contract_id(files,state,stage,kind):
    from final_review import REVIEW_CONTRACT, repair_action_contract_id
    if kind=='REVIEW': return REVIEW_CONTRACT[stage]
    plan=_one_content(files,_stage_root(state,stage)+'/plans')
    if plan is None: raise ValueError('Owner Repair 缺少冻结计划。')
    return repair_action_contract_id(stage,json.loads(plan))


def _control_bundle(files,state,stage,kind,subject_hash):
    from final_review import control_identity,REVIEW_CONTRACT
    from stage_planner import _effective_envelope,_effective_success
    contract_id=_control_contract_id(files,state,stage,kind)
    _,digest=action_contract_binding(SKILL_ROOT,contract_id)
    logical,group=control_identity(stage,kind,subject_hash,digest)
    ledger=_load_action_ledger(files,state['runId'])
    envelope=_effective_envelope(ledger,logical)
    if envelope is None: return logical,group,None
    record_hash,record=effective_result(ledger,logical)
    return logical,group,{'envelope':envelope.value,'record':record,'recordSha256':record_hash,
                         'result':json.loads(ledger.normalized_results[record.normalized_result_sha256])}


def _issue_control(files,state,stage,kind,subject_hash,packet):
    from final_review import control_identity,REVIEW_CONTRACT
    contract_id=_control_contract_id(files,state,stage,kind)
    _,digest=action_contract_binding(SKILL_ROOT,contract_id)
    logical,group=control_identity(stage,kind,subject_hash,digest)
    return _issue_singleton(files,state,stage,group,logical,contract_id,canonical_json_bytes(packet))

def _semantic_owner_contract(stage,plan):
    from stage_planner import bound_action_contract_ids
    if stage=='SCOPE':return 'SCOPE_SYNTHESIS-v1'
    if stage=='STORY_AC':return 'STORY_AC-v1'
    return bound_action_contract_ids(plan)['TASK']


def _semantic_repair_paths(run_id,base_sha256,source_sha256):
    root=f"{RUNS_ROOT}/{run_id}/candidate-repairs"
    return (f"{root}/bases/{base_sha256}.json",
            f"{root}/semantic-sources/{source_sha256}.json")


def _semantic_repair_bundle(files,state,stage,review_bundle,original,resolution):
    from final_review import candidate_repair_replacement,semantic_repair_lineage
    _,contract_sha=action_contract_binding(SKILL_ROOT,'CANDIDATE_PATCH-v1')
    review_sha=review_bundle['record'].normalized_result_sha256
    lineage=semantic_repair_lineage(stage,review_sha,contract_sha)
    ledger=_load_action_ledger(files,state['runId'])
    raw=effective_result_bytes(ledger,lineage)
    if raw is None:
        issued=[envelope for envelope in ledger.envelopes_by_sha256.values()
                if envelope.value['actionContractId']=='CANDIDATE_PATCH-v1'
                and any(json.loads(files.read_bytes(
                    f"{RUNS_ROOT}/{state['runId']}/candidate-repairs/plans/{json.loads(files.read_bytes(envelope.value['packetPath']))['contextRefs'][0]['canonicalContent']['repairPlanSha256']}.json"
                ))['origin']['originLogicalWorkId']==lineage for _ in (0,))]
        return {'pending':True} if issued else None
    proof=json.loads(ledger.candidate_resolutions[lineage])
    semantic_sha=proof['origin']['semanticSourceSha256']
    _,source_path=_semantic_repair_paths(state['runId'],proof['authorRawSha256'],semantic_sha)
    source=files.read_json(source_path)
    if sha256_bytes(canonical_json_bytes(source))!=semantic_sha:
        raise ValueError('语义修复来源描述符 hash 漂移。')
    repaired=json.loads(raw)
    replacement=candidate_repair_replacement(stage,original,repaired,review_bundle['result'],resolution)
    return {'replacement':replacement,'repaired':repaired,'resolutionSha256':sha256_bytes(ledger.candidate_resolutions[lineage])}


def _issue_semantic_candidate_repair(files,state,stage,plan,owner_packet,owner_ir,review_packet,review_bundle,resolution):
    from candidate_repair import _at
    from final_review import semantic_repair_lineage
    from owner_callbacks import candidate_owner_callbacks
    review=review_bundle['result'];review_sha=review_bundle['record'].normalized_result_sha256
    patch_contract,patch_contract_sha=action_contract_binding(SKILL_ROOT,'CANDIDATE_PATCH-v1')
    if stage=='TASK':
        from task_compiler import prepare_task_repair_packet
        _,_,_,_,task_inputs=_frozen_stage_inputs(files,state,'TASK')
        owner_packet=prepare_task_repair_packet(
            owner_packet,owner_ir,review,
            task_inputs.story_candidate_bytes,
            task_inputs.input_revision_bytes,
            resolution,
        )
    lineage=semantic_repair_lineage(stage,review_sha,patch_contract_sha)
    owner_raw=canonical_json_bytes(owner_ir);owner_sha=sha256_bytes(owner_raw)
    owner_contract=_semantic_owner_contract(stage,plan)
    descriptor={'stageKind':stage,'ownerPacket':owner_packet,'ownerIRSha256':owner_sha,
        'ownerActionContractId':owner_contract,'ownerIndex':review_packet['workItems'][0]['payload']['ownerIndex'],
        'reviewDecision':review,'reviewDecisionSha256':review_sha,
        'reviewAttemptRecordSha256':review_bundle['recordSha256'],
        'reviewCandidateSha256':review_packet['workItems'][0]['payload']['candidateSha256']}
    if resolution is not None:descriptor['ownerResolution']=resolution
    semantic_sha=sha256_bytes(canonical_json_bytes(descriptor))
    base_path,source_path=_semantic_repair_paths(state['runId'],owner_sha,semantic_sha)
    files.publish_new(base_path,owner_raw);files.publish_new(source_path,canonical_json_bytes(descriptor))
    policy_sha,policy=_effective_budget_policy(files,state['runId'])
    origin={'runId':state['runId'],'inputRevisionSha256':state['currentInputRevisionSha256'],
        'originLogicalWorkId':lineage,'sourceKind':'SEMANTIC_REVIEW',
        'sourceActionContractId':review_bundle['envelope']['actionContractId'],
        'sourceAttemptRecordSha256':review_bundle['recordSha256'],'stageKind':stage,
        'repairRound':2,'budgetPolicySha256':policy_sha,'reviewDecisionSha256':review_sha,
        'reviewCandidateSha256':descriptor['reviewCandidateSha256'],'semanticSourceSha256':semantic_sha}
    diagnose,make_plan,_=candidate_owner_callbacks(
        review_bundle['envelope'],json.loads(files.read_bytes(review_bundle['envelope']['packetPath'])),
        semantic_source=descriptor)
    report=diagnose(owner_raw,origin);plan_raw=make_plan(owner_raw,report,origin)
    repair_plan=json.loads(plan_raw);group=repair_plan['groups'][0]
    index={row['objectId']:row for row in repair_plan['objectIndex']};candidate=json.loads(owner_raw)
    evidence=[{'kind':'SEMANTIC_REVIEW_FINDINGS','value':review['findings']}]
    for read in group['readSet']:
        row=_at(candidate,index[read['objectId']]['path'])
        evidence.append({'objectId':read['objectId'],'fields':row if not read['fields']
                         else {field:row[field] for field in read['fields'] if field in row}})
    repair_packet=_patch_request_packet(plan_raw,group['groupId'],review_packet,evidence_values=evidence)
    identity={'originLogicalWorkId':lineage,'round':2,'groupId':group['groupId'],'planSha256':sha256_bytes(plan_raw)}
    logical='candidate-patch-'+sha256_bytes(canonical_json_bytes(identity))
    envelope=_envelope_for_work(files,state,stage,review_bundle['envelope']['groupId'],logical,
        'CANDIDATE_PATCH-v1',canonical_json_bytes(repair_packet))
    files.publish_new(f"{RUNS_ROOT}/{state['runId']}/candidate-repairs/plans/{sha256_bytes(plan_raw)}.json",plan_raw)
    ledger=_load_action_ledger(files,state['runId'])
    prepared=ActionEnvelope(envelope,_action_paths(state['runId'],envelope['actionId'])['envelope'],
        sha256_bytes(canonical_json_bytes(envelope)))
    _guard_action_budget(ledger,_read_run_events(files,state['runId']),policy,[prepared])
    selection={'originLogicalWorkId':lineage,'sourceAttemptRecordSha256':review_bundle['recordSha256'],
        'sourceActionContractId':review_bundle['envelope']['actionContractId'],'selectionKind':'SEMANTIC_REVIEW',
        'repairRound':2,'candidatePatchActionContractSha256':patch_contract_sha,
        'candidateRepairSchemaSha256':sha256_bytes((SKILL_ROOT/'contracts/candidate-repair.schema.json').read_bytes())}
    selections=[event for event in _read_run_events(files,state['runId'])
                if event.type=='CANDIDATE_REPAIR_PROTOCOL_SELECTED' and event.payload['originLogicalWorkId']==lineage]
    if not selections:_append_run_event(files,state['runId'],'CANDIDATE_REPAIR_PROTOCOL_SELECTED',selection)
    elif len(selections)!=1 or dict(selections[0].payload)!=selection:raise ValueError('语义修复协议选择事件冲突。')
    _persist_issued_action(files,envelope,canonical_json_bytes(repair_packet))
    updated=_write_active_state(files,_read_active_marker(files),{**state,'wait':'MODEL','expectedActionIds':[envelope['actionId']]})
    return _public_active_result(files,updated)


def _issue_singleton(files,state,stage,group,logical,contract_id,packet):
    envelope=_envelope_for_work(files,state,stage,group,logical,contract_id,packet)
    _persist_issued_action(files,envelope,packet)
    updated=_write_active_state(files,_read_active_marker(files),{**state,'phase':_phase_for_action_stage(stage),
        'wait':'MODEL','expectedActionIds':[envelope['actionId']]})
    return _public_active_result(files,updated)


def _prior_business_gate(files,state,plan):
    from stage_planner import _effective_success,DependencyResultRef
    from prior_state import resolve_prior_root,verify_prior_decision,materialize_prior_snapshot
    works=[work for work in plan['works'] if work['packetPlan']['actionKind'] in {'PRIOR_ANALYZE','PRIOR_CONSOLIDATE'}]
    if not works: return
    ledger=_load_action_ledger(files,state['runId'])
    if not is_group_ready(ledger,[work['logicalWorkId'] for work in works]): return
    consumed={key for work in works for key in work['packetPlan']['dependencyLogicalWorkIds']}
    root=next(work['logicalWorkId'] for work in works if work['logicalWorkId'] not in consumed)
    digest,result=effective_result(ledger,root)
    reference=resolve_prior_root(plan,ledger,[DependencyResultRef(root,digest,effective_result_bytes(ledger,root),
        result.source_attempt_record_sha256 if isinstance(result,CandidateResult) else None)])
    revision=files.read_bytes(_read_active_marker(files)['inputRevisionPath'])
    inventories=_prior_inventories(files,state)
    verify_prior_decision(inventories,json.loads(reference.normalized_result),input_revision_bytes=revision)
    # No dependent Scope action may escape this gate. Conversion belongs to MATERIALIZE.
    return reference


def _stage_wait(files,state,code):
    run_id=state['runId'];wait_id='stage-wait-'+code
    events=_read_run_events(files,run_id)
    if not any(event.type=='WAITING_INPUT_ENTERED' and event.payload['waitId']==wait_id for event in events):
        _append_run_event(files,run_id,'RUN_STATE_CHANGED',{'fromState':state['phase'],'toState':'WAITING_INPUT'})
        _append_run_event(files,run_id,'WAITING_INPUT_ENTERED',{'waitId':wait_id,'reasonCode':code})
    waiting=_write_active_state(files,_read_active_marker(files),{**state,'wait':'INPUT','expectedActionIds':[],'resumeFromPhase':state['phase']})
    return {'outcome':'WAITING_INPUT','state':waiting,'nextAction':None,'diagnostics':[_diagnostic_value(_diagnostic(code,'阶段需要补充完整业务输入后重新启动。'))]}



def _manual_repair_records(files,state,stage):
    records={}
    for event in _read_run_events(files,state['runId']):
        if event.type!='OWNER_REPAIR_AUTHORIZED' or event.payload['stageKind']!=stage: continue
        value=event.payload;digest=value['authorizationSha256']
        raw=_one_content(files,_stage_root(state,stage)+'/manual-repairs/'+value['reviewDecisionSha256'])
        if raw is None or sha256_bytes(raw)!=digest: raise ValueError('人工继续裁定缺少精确不可变正文。')
        answer=json.loads(raw)
        terminal_raw=files.read_bytes(_state_snapshot_path(state['runId'],value['terminalStateSha256']))
        terminal=json.loads(terminal_raw)
        if (sha256_bytes(terminal_raw)!=value['terminalStateSha256'] or answer['terminalStateSha256']!=value['terminalStateSha256']
                or terminal.get('result')!='MANUAL_REVIEW_REQUIRED' or terminal.get('phase')!='DONE'
                or answer['runId']!=state['runId'] or terminal['runId']!=state['runId']
                or answer['candidateSha256']!=terminal['currentCandidateSha256']
                or terminal['currentInputRevisionSha256']!=state['currentInputRevisionSha256']):
            raise ValueError('人工继续裁定未绑定原始终态和冻结输入。')
        _,_,review=_control_bundle(files,state,stage,'REVIEW',answer['candidateSha256'])
        from final_review import validate_owner_resolution
        if review is None: raise ValueError('人工继续缺少实际失败 Review。')
        validate_owner_resolution(stage,review['result'],answer)
        review_raw=_one_content(files,_stage_root(state,stage)+f'/review-inputs/{value["semanticRevision"]}')
        if review_raw is None or json.loads(review_raw)['workItems'][0]['payload']['candidateSha256']!=answer['candidateSha256']:
            raise ValueError('人工继续裁定必须保留真实累计候选次数。')
        if value['reviewDecisionSha256'] in records: raise ValueError('同一 Review 只能授权一次。')
        records[value['reviewDecisionSha256']]={'answer':answer,'event':event,'terminal':terminal}
    from final_review import verify_manual_authorization_records
    verify_manual_authorization_records({key:{'authorization':value['answer'],'terminalState':value['terminal']} for key,value in records.items()},
        [run_event_value(event) for event in _read_run_events(files,state['runId'])],stage,state['runId'],state['currentInputRevisionSha256'],
        stage_plan=json.loads(_one_content(files,_stage_root(state,stage)+'/plans')) if records and stage=='TASK' else None)
    return records


def _stage_revision_limit(files,state,stage):
    manual=len(_manual_repair_records(files,state,stage))
    clarified=sum(event.type=='WAITING_INPUT_EXITED' and event.payload.get('resolutionKind')=='OWNER_CLARIFICATION'
                  for event in _read_run_events(files,state['runId'])) if stage=='TASK' else 0
    return 2+manual+clarified


def _resume_manual_owner_repair(files,path):
    from final_review import (replace_owner_decisions, repair_root_keys,
        owner_resolution, semantic_repair_lineage, validate_owner_resolution)
    answer=_mapping(files,_managed_request_path(files,path))
    if validate_contract(answer,'owner-repair-authorization.schema.json',load_schema_registry(SKILL_ROOT)):
        raise ValueError('人工继续修复合同无效。')
    run_id=answer['runId'];stage=answer['stageKind'];root,_,binding_path=_run_paths(run_id)
    terminal_path=_state_snapshot_path(run_id,answer['terminalStateSha256'])
    terminal_raw=files.read_bytes(terminal_path);terminal=_validated_run_state(json.loads(terminal_raw),terminal_path)
    if (sha256_bytes(terminal_raw)!=answer['terminalStateSha256'] or terminal['result']!='MANUAL_REVIEW_REQUIRED'
            or terminal['currentCandidateSha256']!=answer['candidateSha256'] or terminal['runId']!=run_id):
        raise ValueError('只可恢复明确裁定绑定的原 Manual Review 终态。')
    marker=_read_active_marker(files)
    if marker is not None and marker['runId']!=run_id: raise ValueError('另一个 run 已激活，不可恢复旧 run。')
    records=_manual_repair_records(files,terminal,stage)
    old=records.get(answer['reviewDecisionSha256'])
    if old is not None and old['answer']!=answer: raise ValueError('同一 Review 的裁定不可回写。')
    if old is not None and marker is not None: return
    if marker is not None and _read_active_run(files,marker)!=terminal: raise ValueError('裁定不是当前终态。')
    binding=_mapping(files,binding_path)
    terminal_marker={**binding,'bindingPath':binding_path,'statePath':terminal_path,'status':'ACTIVE','stateSha256':answer['terminalStateSha256']}
    if _read_active_run(files,terminal_marker)!=terminal: raise ValueError('终态输入绑定漂移。')
    directory=files.resolve(_stage_root(terminal,stage)+'/review-inputs',expect='dir')
    revisions=sorted(int(child.name) for child in directory.iterdir() if child.is_dir() and child.name.isdigit())
    revision=revisions[-1]
    if revision<2 or _one_content(files,_stage_root(terminal,stage)+'/checkpoints') is not None:
        raise ValueError('只可继续尚未封存且已停止自动修复的阶段。')
    latest=json.loads(_one_content(files,_stage_root(terminal,stage)+f'/review-inputs/{revision}'))['workItems'][0]['payload']
    if latest['candidateSha256']!=answer['candidateSha256']: raise ValueError('裁定指向历史候选。')
    _,_,review=_control_bundle(files,terminal,stage,'REVIEW',answer['candidateSha256'])
    if review is None: raise ValueError('裁定缺少当前 Review。')
    validate_owner_resolution(stage,review['result'],answer)
    previous=json.loads(_one_content(files,_stage_root(terminal,stage)+f'/review-inputs/{revision-1}'))['workItems'][0]['payload']
    _,_,previous_review=_control_bundle(files,terminal,stage,'REVIEW',previous['candidateSha256'])
    _,_,previous_repair=_control_bundle(files,terminal,stage,'REPAIR',previous_review['record'].normalized_result_sha256)
    if previous_repair is not None:
        previous_body=json.loads(files.read_bytes(previous_repair['envelope']['packetPath']))['workItems'][0]['payload']
        current_ir=replace_owner_decisions(stage,previous_body['ownerIR'],
            previous_body['reviewDecision'],previous_repair['result'],
            owner_resolution(previous_body))
    else:
        _,patch_contract_sha=action_contract_binding(
            SKILL_ROOT,'CANDIDATE_PATCH-v1'
        )
        lineage=semantic_repair_lineage(
            stage,previous_review['record'].normalized_result_sha256,
            patch_contract_sha,
        )
        ledger=_load_action_ledger(files,run_id)
        if lineage not in ledger.candidate_resolutions:
            raise ValueError('人工继续缺少前一版实际 Repair。')
        current_ir=json.loads(effective_result_bytes(ledger,lineage))
    keys=repair_root_keys(stage,current_ir,review['result'],answer)
    from final_review import OWNER_COLLECTION
    if any(not set(answer['allowedFields'])<=row.keys() for row in current_ir[OWNER_COLLECTION[stage]] if row['localKey'] in keys):
        raise ValueError('裁定只能调整既有 Owner 字段。')
    _,_,issued=_control_bundle(files,terminal,stage,'REPAIR',answer['reviewDecisionSha256'])
    if issued is not None: raise ValueError('已完成裁定不可重开旧 run。')
    raw=canonical_json_bytes(answer);digest=_content(files,_stage_root(terminal,stage)+'/manual-repairs/'+answer['reviewDecisionSha256'],raw)
    if old is None:
        _append_run_event(files,run_id,'OWNER_REPAIR_AUTHORIZED',{'stageKind':stage,'semanticRevision':revision,
            'reviewDecisionSha256':answer['reviewDecisionSha256'],'authorizationSha256':digest,'terminalStateSha256':answer['terminalStateSha256']})
    _write_active_state(files,terminal_marker,{**terminal,'phase':_phase_for_action_stage(stage),'result':None,'wait':'NONE'})

def _read_owner_clarification(files,state,review_hash):
    raw=_one_content(files,_stage_root(state,'TASK')+'/clarifications/'+review_hash)
    return json.loads(raw) if raw is not None else None


def _task_context_at_candidate(files,state):
    from task_compiler import apply_task_repairs
    from final_review import owner_resolution, semantic_repair_lineage
    plan,items,contexts,policy,inputs=_frozen_stage_inputs(files,state,'TASK')
    packet,decisions=_stage_ir(files,state,'TASK',plan,items,contexts,policy,inputs)
    for revision in range(1,_stage_revision_limit(files,state,'TASK')+1):
        raw=_one_content(files,_stage_root(state,'TASK')+f'/review-inputs/{revision}')
        if raw is None: break
        body=json.loads(raw)['workItems'][0]['payload']
        if body['candidateSha256']==state['currentCandidateSha256']:
            return packet,decisions,inputs,revision
        _,_,review=_control_bundle(files,state,'TASK','REVIEW',body['candidateSha256'])
        if review is None: break
        _,_,repair=_control_bundle(files,state,'TASK','REPAIR',review['record'].normalized_result_sha256)
        if repair is not None:
            payload=json.loads(files.read_bytes(repair['envelope']['packetPath']))['workItems'][0]['payload']
            resolution=owner_resolution(payload)
            replacement=repair['result']
        else:
            _,patch_contract_sha=action_contract_binding(
                SKILL_ROOT,'CANDIDATE_PATCH-v1'
            )
            lineage=semantic_repair_lineage(
                'TASK',review['record'].normalized_result_sha256,
                patch_contract_sha,
            )
            ledger=_load_action_ledger(files,state['runId'])
            proof=ledger.candidate_resolutions.get(lineage)
            if proof is None:
                break
            origin=json.loads(proof)['origin']
            semantic=json.loads(
                ledger.candidate_repair_semantic_sources[
                    origin['semanticSourceSha256']
                ]
            )
            resolution=semantic.get('ownerResolution')
            bundle=_semantic_repair_bundle(
                files,state,'TASK',review,decisions,resolution
            )
            if bundle is None or bundle.get('pending'):
                break
            replacement=bundle['replacement']
        operation=(review['result'],replacement,resolution) if resolution is not None else (review['result'],replacement)
        packet,decisions=apply_task_repairs(packet,decisions,[operation],inputs)
    raise ValueError('澄清候选未绑定连续的实际 Owner 修复链。')


def _accept_owner_clarification(files,state,path):
    from task_compiler import prepare_task_repair_packet
    answer=_mapping(files,_managed_request_path(files,path))
    if validate_contract(answer,'owner-clarification.schema.json',load_schema_registry(SKILL_ROOT)):
        raise ValueError('实施澄清合同无效。')
    prior_answer=_read_owner_clarification(files,state,answer['reviewDecisionSha256'])
    if prior_answer==answer and any(event.type=='WAITING_INPUT_EXITED'
        and event.payload.get('resolutionKind')=='OWNER_CLARIFICATION'
        and event.payload['reviewDecisionSha256']==answer['reviewDecisionSha256']
        and event.payload['clarificationSha256']==sha256_bytes(canonical_json_bytes(answer))
        for event in _read_run_events(files,state['runId'])): return
    if state.get('result') is not None or state['phase']!='TASK' or state.get('wait')!='INPUT':
        raise ValueError('仅可为等待澄清的当前 Task 候选提交决定。')
    _,_,review=_control_bundle(files,state,'TASK','REVIEW',state['currentCandidateSha256'])
    if review is None: raise ValueError('澄清缺少当前 Review。')
    packet,decisions,inputs,revision=_task_context_at_candidate(files,state)
    if revision>=3: raise ValueError('本轮澄清修复已达到候选上限。')
    prepare_task_repair_packet(packet,decisions,review['result'],inputs.story_candidate_bytes,inputs.input_revision_bytes,answer)
    review_hash=review['record'].normalized_result_sha256
    old=_read_owner_clarification(files,state,review_hash)
    if old is not None and old!=answer: raise ValueError('同一 Review 的批准澄清不可回写。')
    raw=canonical_json_bytes(answer);digest=_content(files,_stage_root(state,'TASK')+'/clarifications/'+review_hash,raw)
    events=_read_run_events(files,state['runId']);closed={event.payload['waitId'] for event in events if event.type=='WAITING_INPUT_EXITED'}
    waiting=next((event for event in reversed(events) if event.type=='WAITING_INPUT_ENTERED'
        and event.payload['reasonCode']=='REVIEW_INPUT_REQUIRED' and event.payload['waitId'] not in closed),None)
    if waiting is None: raise ValueError('澄清没有匹配的输入等待。')
    _append_run_event(files,state['runId'],'WAITING_INPUT_EXITED',{'waitId':waiting.payload['waitId'],
        'resolutionKind':'OWNER_CLARIFICATION','reviewDecisionSha256':review_hash,'clarificationSha256':digest})


def _reconcile_owner_clarification(files,state):
    if state.get('wait')!='INPUT' or state.get('result') is not None: return state
    events=_read_run_events(files,state['runId'])
    entered=next((event for event in reversed(events) if event.type=='WAITING_INPUT_ENTERED'),None)
    if entered is None: return state
    exited=next((event for event in events if event.type=='WAITING_INPUT_EXITED'
        and event.payload['waitId']==entered.payload['waitId'] and event.payload['resolutionKind']=='OWNER_CLARIFICATION'),None)
    if exited is None:return state
    answer=_read_owner_clarification(files,state,exited.payload['reviewDecisionSha256'])
    if (answer is None or sha256_bytes(canonical_json_bytes(answer))!=exited.payload['clarificationSha256']
            or answer['candidateSha256']!=state['currentCandidateSha256']):
        raise ValueError('澄清恢复事件未绑定该候选的不可变决定。')
    last=next((event for event in reversed(events) if event.type=='RUN_STATE_CHANGED'),None)
    if last is not None and last.payload['toState']=='WAITING_INPUT':
        _append_run_event(files,state['runId'],'RUN_STATE_CHANGED',{'fromState':'WAITING_INPUT','toState':state['phase']})
    return {**state,'wait':'NONE','resumeFromPhase':None}


def _owner_repair_packet(stage, packet, decisions, review, inputs, resolution=None):
    from final_review import repair_root_keys, resolution_field
    if stage == 'TASK':
        from task_compiler import prepare_task_repair_packet, factor_task_repair_packet
        packet = factor_task_repair_packet(prepare_task_repair_packet(packet, decisions, review,
            inputs.story_candidate_bytes, inputs.input_revision_bytes, resolution))
    result = {'workItems':[{'workItemId':'repair-decisions','payload':{
        'stageKind':stage,'reviewDecisionSha256':sha256_bytes(canonical_json_bytes(review)),
        'reviewDecision':review,'authorizedRootKeys':repair_root_keys(stage,decisions,review,resolution),
        'ownerIR':decisions,'ownerPacket':packet}}],'contextRefs':[]}
    if resolution is not None: result['workItems'][0]['payload'][resolution_field(resolution)]=resolution
    return result


def _seal_stage(files,state,stage,plan,items,contexts,policy,inputs):
    from final_review import REVIEW_CONTRACT,stage_checkpoint,review_route,replace_owner_decisions,review_resolution_fields
    import scope_compiler,delivery_compiler,task_compiler
    owner={'SCOPE':scope_compiler,'STORY_AC':delivery_compiler,'TASK':task_compiler}[stage]
    root=_stage_root(state,stage)
    ledger=_load_action_ledger(files,state['runId'])
    previous_review=None;semantic_repair=None;semantic_repairs=[]
    packet,decisions=_stage_ir(files,state,stage,plan,items,contexts,policy,inputs)
    revision_raw=files.read_bytes(_read_active_marker(files)['inputRevisionPath'])
    request=_mapping(files,str(Path(_read_active_marker(files)['inputRevisionPath']).parent/'request.json'))
    for revision in range(1,_stage_revision_limit(files,state,stage)+1):
        if stage=='TASK':
            current_packet,merged=owner.apply_task_repairs(packet,decisions,semantic_repairs,inputs)
        else:
            current_packet=packet
            merged=decisions
            for operation in semantic_repairs: merged=replace_owner_decisions(stage,merged,*operation)
        resolution_fields=review_resolution_fields(semantic_repairs)
        directory=root+f'/review-inputs/{revision}'
        material_fingerprint=_step_fingerprint([plan,current_packet,merged,semantic_repairs],
            parameters={'stage':stage,'revision':revision,'kind':'MATERIALIZE'},
            implementations=[owner.__name__+'.py','stable_ids.py','sow_model.py'])
        review_raw=_read_step_output(files,state,stage,revision,'MATERIALIZE',directory,fingerprint=material_fingerprint)
        if review_raw is None:
            def materialize():
                current_ledger=_load_action_ledger(files,state['runId'])
                if stage=='SCOPE':
                    material=owner.materialize_scope_candidate(revision_raw,request,plan,items,contexts,current_ledger,policy,
                        prior_inventories=_prior_inventories(files,state),prototype_inventory=_prototype_inventory(files,state),semantic_repairs=semantic_repairs)
                elif stage=='TASK':
                    material=owner.materialize_task_candidate(inputs,plan,current_ledger,policy,semantic_repairs=semantic_repairs)
                else:
                    material=owner.materialize_story_candidate(inputs,plan,current_ledger,policy,semantic_repairs=semantic_repairs)
                index=_owner_index(stage,material,current_packet,merged)
                candidate=json.loads(material.candidate_bytes)
                from sow_model import NODE_COLLECTIONS
                evidence=sorted({ref['blockId'] for collection in NODE_COLLECTIONS for item in candidate[collection] for ref in item.get('sourceRefs',[])})
                obligations=list(material.review_obligations) if stage=='SCOPE' else []
                body={'stageKind':stage,'candidateSha256':sha256_bytes(material.candidate_bytes),'candidate':candidate,
                    'ownerIndex':index,'reviewObligations':obligations,'evidenceIds':evidence}
                if stage=='TASK':
                    body['taskRules']=owner.task_review_rules(candidate,inputs.task_catalog)
                body.update(resolution_fields)
                if stage=='SCOPE':
                    body['changeGraph']=json.loads(material.change_graph_bytes)
                    body['priorState']=json.loads(material.prior_state_bytes) if material.prior_state_bytes else None
                    expected=owner.scope_review_obligations(merged,material.identity_by_local_key,contexts,current_ledger,
                        body['priorState'],body['changeGraph'],_prior_business_gate(files,state,plan),prior_work_items=items)
                    if sorted(obligations,key=canonical_json_bytes)!=list(expected):
                        raise ValueError('Scope candidate 缺少完整 intent/identity review obligations。')
                    if material.prior_state_bytes:
                        body['evidenceIds']=sorted(set(evidence)|{row['priorEvidenceId'] for row in body['priorState']['evidence']})
                        body['evidenceIds']=sorted(set(body['evidenceIds'])|{row['priorEvidenceId']
                            for obligation in obligations if obligation['kind']=='PRIOR_EXTRACTION'
                            for row in obligation['priorContext']['evidence']})
                        obligations.append({'kind':'PRIOR_SOURCE_EQUIVALENCE','priorStateSha256':sha256_bytes(material.prior_state_bytes),
                            'sourceRelations':body['priorState']['sourceRelations'], 'entities':body['priorState']['entities']})
                review_packet={'workItems':[{'workItemId':'review-candidate','payload':body}],'contextRefs':[]}
                raw=canonical_json_bytes(review_packet)
                return raw
            review_raw=_deterministic_step(files,state,'MATERIALIZE',materialize,stage=stage,revision=revision,fingerprint=material_fingerprint)
            _content(files,directory,review_raw)
        review_packet=json.loads(review_raw);body=review_packet['workItems'][0]['payload']
        candidate_bytes=canonical_json_bytes(body['candidate']);candidate_hash=sha256_bytes(candidate_bytes)
        if candidate_hash!=body['candidateSha256']:
            raise ValueError('候选与 frozen Review input 不一致。')
        state={**state,'currentCandidateSha256':candidate_hash,'currentCandidatePath':root+f'/candidates/{candidate_hash}.json'}
        if {key:body[key] for key in ('ownerClarification','ownerRepairAuthorization') if key in body}!=resolution_fields:
            raise ValueError('Review 未绑定该候选累计批准裁定。')
        if stage=='SCOPE':
            from prior_state import materialize_prior_snapshot
            prior_root = _prior_business_gate(files,state,plan)
            prior_decision = json.loads(prior_root.normalized_result) if prior_root else None
            prior_state = materialize_prior_snapshot(_prior_inventories(files,state),prior_decision,
                input_revision_bytes=revision_raw) if prior_root else None
            if body['priorState'] != prior_state:
                raise ValueError('Review Prior snapshot 未绑定原 inventory 和 sealed Prior root。')
            expected_index = owner.scope_review_owner_index(candidate_bytes,merged,items,
                prototype_inventory=_prototype_inventory(files,state),prior_decision=prior_decision,prior_state=prior_state,
                context_refs=contexts,ledger=_load_action_ledger(files,state['runId']))
            if body['ownerIndex'] != expected_index:
                raise ValueError('Scope Review root index 未绑定冻结 IR 的精确实体。')
            identities = {key:value['id'] for key,value in expected_index.items()}
            graph = owner.scope_change_graph(merged,identities,prior_decision,prior_state)
            if body['changeGraph'] != graph:
                raise ValueError('Review ChangeGraph 未绑定 sealed Scope/Prior decisions。')
            expected = list(owner.scope_review_obligations(merged,identities,contexts,
                _load_action_ledger(files,state['runId']),prior_state,graph,prior_root,prior_work_items=items))
            if prior_state is not None:
                expected.append({'kind':'PRIOR_SOURCE_EQUIVALENCE','priorStateSha256':sha256_bytes(canonical_json_bytes(prior_state)),
                    'sourceRelations':prior_state['sourceRelations'],'entities':prior_state['entities']})
            if sorted(body['reviewObligations'],key=canonical_json_bytes)!=sorted(expected,key=canonical_json_bytes):
                raise ValueError('Scope Review input 义务不完整。')
            material=owner.ScopeMaterialization(candidate_bytes,canonical_json_bytes(graph),
                canonical_json_bytes(prior_state) if prior_state else None,identities,tuple(expected))
        else:
            cls=owner.StoryMaterialization if stage=='STORY_AC' else owner.TaskMaterialization
            upstream_bytes=inputs.scope_candidate_bytes if stage=='STORY_AC' else inputs.story_candidate_bytes
            material=cls(candidate_bytes,candidate_hash,upstream_bytes,inputs.checkpoint_sha256,canonical_json_bytes(current_packet),canonical_json_bytes(merged))
            if body['ownerIndex'] != _owner_index(stage,material,current_packet,merged):
                raise ValueError('Review root index 未绑定冻结 Owner IR。')
            if stage=='TASK' and body.get('taskRules') != owner.task_review_rules(body['candidate'],inputs.task_catalog):
                raise ValueError('Task Review 规则未绑定当前候选与冻结模板。')
        _content(files,root+'/candidates',candidate_bytes)
        if stage=='SCOPE':
            _content(files,root+'/change-graphs',material.change_graph_bytes)
            if material.prior_state_bytes is not None:
                _content(files,root+'/prior-states',material.prior_state_bytes)
        validator_fingerprint=_step_fingerprint([candidate_hash,body],parameters={'stage':stage,'revision':revision,'kind':'VALIDATE'},
            implementations=[owner.__name__+'.py','sow_model.py'])
        validator_raw=_read_step_output(files,state,stage,revision,'VALIDATE',root+f'/validators/{revision}',fingerprint=validator_fingerprint)
        if validator_raw is None:
            def validate():
                diagnostics=(owner.validate_scope_candidate if stage=='SCOPE' else owner.validate_story_candidate if stage=='STORY_AC' else owner.validate_task_candidate)(material)
                if diagnostics:
                    from models import AttemptDiagnostic
                    raise InvalidActionResult('完整机械校验失败。', diagnostic=AttemptDiagnostic(
                        'STAGE_VALIDATION_FAILED', '/' + stage, (), tuple(AttemptDiagnostic(
                            item.code, item.path, tuple(item.details.get('subjectIds', ()))) for item in diagnostics)))
                value={'stageKind':stage,'candidateSha256':candidate_hash,
                    'validatorContractSha256':sha256_bytes((SKILL_ROOT/'contracts/sow-model.schema.json').read_bytes()),'diagnostics':[]}
                return canonical_json_bytes(value)
            validator_raw=_deterministic_step(files,state,'VALIDATE',validate,stage=stage,revision=revision,fingerprint=validator_fingerprint)
            _content(files,root+f'/validators/{revision}',validator_raw)
        validator=json.loads(validator_raw)
        if validator!={'stageKind':stage,'candidateSha256':candidate_hash,'validatorContractSha256':sha256_bytes((SKILL_ROOT/'contracts/sow-model.schema.json').read_bytes()),'diagnostics':[]}:
            raise ValueError('完整 validator result 绑定失效。')
        state=_write_active_state(files,_read_active_marker(files),state)
        logical,group,bundle=_control_bundle(files,state,stage,'REVIEW',candidate_hash)
        if bundle is None: return _issue_control(files,state,stage,'REVIEW',candidate_hash,review_packet)
        actual_review_raw=files.read_bytes(bundle['envelope']['packetPath'])
        if json.loads(actual_review_raw)['workItems']!=review_packet['workItems'] or bundle['envelope']['baseCandidateSha256']!=candidate_hash:
            raise ValueError('Review 不是该候选的 fresh singleton。')
        review=bundle['result']
        manual=_manual_repair_records(files,state,stage).get(bundle['record'].normalized_result_sha256)
        resolution=manual['answer'] if manual else (_read_owner_clarification(files,state,bundle['record'].normalized_result_sha256) if stage=='TASK' else None)
        route=review_route(review,previous_review=previous_review,resolution=resolution)
        if route=='WAITING_INPUT': return _stage_wait(files,state,'REVIEW_INPUT_REQUIRED')
        if route in {'MANUAL_REVIEW_REQUIRED','CONTRACT_UNSUPPORTED'}:
            return {'outcome':route,'state':_terminalize_active_run(files,_read_active_marker(files),result=route),'nextAction':None,'diagnostics':[]}
        if route=='REPAIR':
            review_hash=bundle['record'].normalized_result_sha256
            logical,group,repair_bundle=_control_bundle(files,state,stage,'REPAIR',review_hash)
            if repair_bundle is not None:
                repair_packet=_owner_repair_packet(stage,current_packet,merged,review,inputs,resolution)
                actual_repair=json.loads(files.read_bytes(repair_bundle['envelope']['packetPath']))
                if actual_repair['workItems'] != repair_packet['workItems']:
                    raise ValueError('已发行 legacy Repair 未绑定原 IR、影响闭包和确定性上下文。')
                replacement=repair_bundle['result']
            else:
                semantic=_semantic_repair_bundle(files,state,stage,bundle,merged,resolution)
                if semantic is None:
                    return _issue_semantic_candidate_repair(
                        files,state,stage,plan,current_packet,merged,review_packet,bundle,resolution)
                if semantic.get('pending'):
                    return _public_active_result(files,state)
                replacement=semantic['replacement']
            semantic_repair=(review,replacement,resolution) if resolution is not None else (review,replacement)
            semantic_repairs.append(semantic_repair);previous_review=review
            continue
        upstream=[_checkpoint_bytes(files,state,'SCOPE' if stage=='STORY_AC' else 'STORY_AC')] if stage!='SCOPE' else []
        stage_ledger=_load_action_ledger(files,state['runId'])
        hashes=[digest for digest,record in stage_ledger.attempt_records.items()
                if stage_ledger.envelopes_by_sha256[record.envelope_sha256].value['stageKind']==stage]
        checkpoint=stage_checkpoint(stage,revision_raw,canonical_json_bytes(plan),upstream,candidate_bytes,validator_raw,
            actual_review_raw,canonical_json_bytes(review),hashes,prior_state_bytes=material.prior_state_bytes if stage=='SCOPE' else None)
        checkpoint_raw=canonical_json_bytes(checkpoint);digest=_content(files,root+'/checkpoints',checkpoint_raw)
        kind='SCOPE_CLOSURE' if stage=='SCOPE' else stage
        refs=[ref for ref in state['checkpointRefs'] if ref['kind']!=kind]+[{'kind':kind,'path':root+f'/checkpoints/{digest}.json','sha256':digest}]
        state=_write_active_state(files,_read_active_marker(files),{**state,'checkpointRefs':refs,'wait':'NONE','expectedActionIds':[]})
        return _advance_public_pipeline(files,state)
    raise ValueError('新增候选缺少本次继续修复裁定。')


def _advance_prototype(files,state):
    from prototype_analysis import PrototypeError,verify_prototype_trace
    if _prototype_inventory(files,state) is None: return None
    bundles=_prototype_bundles(files,state)
    if not bundles: return _issue_prototype(files,state,'PROTOTYPE_SCENARIO',1)
    last=bundles[-1];kind=last['envelope']['actionContractId'];payload=last['packet']['workItems'][0]['payload']
    round_number=payload['identity']['round']
    if kind=='PROTOTYPE_SCENARIO-v1': return _issue_prototype(files,state,'PROTOTYPE_BROWSER',round_number)
    counts,unmeasured=_prototype_execution_counts(files,state['runId'])
    if unmeasured: return _prototype_wait(files,state,'PROTOTYPE_EXECUTION_UNMEASURED')
    limits=_effective_budget_policy(files,state['runId'])[1]['demoLimits']
    if any(count>limits[key] for key,count in counts.items()): return _prototype_wait(files,state,'INCOMPLETE_BUDGET')
    if kind=='PROTOTYPE_BROWSER-v1':
        try: verify_prototype_trace(payload['inventory'],payload['scenario']['normalizedResult'],last['normalizedResult'])
        except PrototypeError as error:
            if error.code not in {'INCOMPLETE_BUDGET','PROTOTYPE_UNSTABLE'}: raise
            return _prototype_wait(files,state,error.code)
        if last['normalizedResult']['unresolvedDiscoveries']: return _prototype_wait(files,state,'PROTOTYPE_UNRESOLVED_DISCOVERY')
        return _issue_prototype(files,state,'PROTOTYPE_ANALYZE',round_number)
    try: prototype=_publish_prototype_ledger(files,state)
    except PrototypeError as error: return _prototype_wait(files,state,error.code)
    if not prototype['value']['sealed']:
        if round_number>=limits['maxDiscoveryRounds'] or counts['maxScenarioSteps']>=limits['maxScenarioSteps']:
            return _prototype_wait(files,state,'INCOMPLETE_BUDGET')
        return _issue_prototype(files,state,'PROTOTYPE_SCENARIO',round_number+1)
    return None


def _advance_public_pipeline(files,state):
    from stage_planner import next_issuable_group
    from scope_compiler import ScopeInputRequired
    from prior_state import PriorInputRequired
    from delivery_compiler import StoryInputRequired
    from task_compiler import TaskInputRequired
    try:
        prototype=_advance_prototype(files,state)
        if prototype is not None: return prototype
        for stage in ('SCOPE','STORY_AC','TASK'):
            if _one_content(files,_stage_root(state,stage)+'/checkpoints') is not None:
                continue
            plan,items,contexts,policy,inputs=_frozen_stage_inputs(files,state,stage)
            if stage=='SCOPE': _prior_business_gate(files,state,plan)
            group=next_issuable_group(plan,_load_action_ledger(files,state['runId']))
            if group is not None: return _issue_frozen_group(files,state,plan,items,contexts,group)
            return _seal_stage(files,state,stage,plan,items,contexts,policy,inputs)
        state=_write_active_state(files,_read_active_marker(files),{**state,'phase':'DRAFT','wait':'NONE','expectedActionIds':[]})
        return _advance_artifact(files,state)
    except (ScopeInputRequired,PriorInputRequired,StoryInputRequired,TaskInputRequired) as error:
        return _stage_wait(files,state,type(error).__name__)


def _attempt_stop_response(
    files: ProjectFiles, state: Mapping[str, object]
) -> dict[str, object] | None:
    if state.get("result") is None:
        events = _read_run_events(files, str(state["runId"]))
        exited = {event.payload["waitId"] for event in events if event.type == "WAITING_INPUT_EXITED"}
        prototype_wait = next((event for event in events if event.type == "WAITING_INPUT_ENTERED" and event.payload["waitId"].startswith(("prototype-wait-", "stage-wait-")) and event.payload["waitId"] not in exited), None)
        if prototype_wait is not None:
            return {"outcome": "WAITING_INPUT", "state": dict(state), "nextAction": None,
                    "diagnostics": [_diagnostic_value(_diagnostic(prototype_wait.payload["reasonCode"], "Demo 证据尚未闭合，请补充完整输入后重新启动。"))]}
        if any(
            event.type == "WAITING_INPUT_ENTERED"
            and event.payload["waitId"] not in exited
            and event.payload["reasonCode"] == "BUDGET_EXHAUSTED"
            for event in events
        ):
            ledger = _load_action_ledger(files, str(state["runId"]))
            charged, unfinished, planned = _model_token_totals(ledger)
            active_seconds = _active_seconds(ledger, events)
            _, policy = _effective_budget_policy(files, str(state["runId"]))
            latest = {}
            for envelope in ledger.envelopes_by_sha256.values():
                key = envelope.value['logicalWorkId']
                if key not in latest or (envelope.value['revision'], envelope.value['attempt']) > (latest[key].value['revision'], latest[key].value['attempt']):
                    latest[key] = envelope
            pending_repairs = [attempt_record_value(record) for record in ledger.attempt_records.values()
                if record.outcome == 'FAILED' and record.envelope_sha256 == latest[record.logical_work_id].sha256]
            return {
                "outcome": "WAITING_INPUT", "state": {**state, "wait": "INPUT", "expectedActionIds": [], "resumeFromPhase": state["phase"]}, "nextAction": None,
                "budgetVarianceTokens": charged - planned,
                "activeSeconds": active_seconds,
                "diagnostics": [{
                    **_diagnostic_value(_diagnostic("BUDGET_EXHAUSTED", "请求容量、运行预算或候选/执行次数已用尽；保留现有候选和成功进度，按诊断修复并显式增加所需有限预算后继续。")),
                    "details": {"chargedTokens": charged, "unfinishedPlannedTokens": unfinished, "maxPlannedTokens": policy["maxPlannedTokens"], "activeSeconds": active_seconds, "maxActiveSeconds": policy["maxActiveSeconds"], "maxActionRevisions": policy.get("maxActionRevisions", 2), "maxExecutionAttempts": policy.get("maxExecutionAttempts", 2), "pendingRepairs": pending_repairs, "maxDeterministicAttempts": policy.get("maxDeterministicAttempts", 2), "pendingSteps": _failed_deterministic_steps(files, state)},
                }],
            }
        candidate_input_wait = next((
            event for event in events
            if event.type == 'WAITING_INPUT_ENTERED'
            and event.payload['waitId'] not in exited
            and event.payload['reasonCode'] != 'BUDGET_EXHAUSTED'
            and not event.payload['waitId'].startswith(('prototype-wait-','stage-wait-'))
        ), None)
        if candidate_input_wait is not None and not any(
            record.outcome == 'FAILED' and record.failure_kind == 'INPUT_REQUIRED'
            for record in _load_action_ledger(files, str(state['runId'])).attempt_records.values()
        ):
            code=candidate_input_wait.payload['reasonCode']
            return {
                'outcome':'WAITING_INPUT',
                'state':{**state,'wait':'INPUT','expectedActionIds':[],
                         'resumeFromPhase':state['phase']},
                'nextAction':None,
                'diagnostics':[_diagnostic_value(_diagnostic(
                    code,'候选修复发现必须由真实输入关闭的问题；已保留失败候选和全部进度。'
                ))],
            }
    routes = {
        "CONTRACT_UNSUPPORTED": ("CONTRACT_GAP", "CONTRACT_UNSUPPORTED"),
        "MANUAL_REVIEW_REQUIRED": ("OWNER_BUG", "OWNER_FIX_REQUIRED"),
        "SYSTEM_FAILED": ("SYSTEM", "SYSTEM_FAILED"),
    }
    route = (
        ("INPUT_REQUIRED", "WAITING_INPUT")
        if state.get("wait") == "INPUT"
        else routes.get(state.get("result")) if state.get("phase") == "DONE" else None
    )
    if route is None:
        return None
    ledger = _load_action_ledger(files, str(state["runId"]))
    failed = [
        record
        for record in ledger.attempt_records.values()
        if record.outcome == "FAILED" and record.failure_kind == route[0]
    ]
    if not failed:
        return None
    return {
        "outcome": route[1],
        "state": dict(state),
        "nextAction": None,
        "diagnostics": [
            attempt_record_value(record)["diagnostic"]
            for record in sorted(
                failed,
                key=lambda record: (
                    record.logical_work_id,
                    record.revision,
                    record.attempt,
                ),
            )
        ],
    }


def _drive_public_active(
    project_root: Path,
    result: Mapping[str, object],
) -> dict[str, object]:
    if result.get("outcome") != "ACTIVE" or not isinstance(
        result.get("state"), Mapping
    ):
        return dict(result)
    files = ProjectFiles.open(project_root)
    state = result["state"]
    assert isinstance(state, Mapping)
    stopped = _attempt_stop_response(files, state)
    if stopped is not None:
        return stopped
    if state.get("phase") == "DONE" and isinstance(state.get("result"), str):
        diagnostics = []
        if state["result"] == "SYSTEM_FAILED":
            ledger = _load_action_ledger(files, str(state["runId"]))
            if any(
                record.outcome == "FAILED"
                and record.failure_kind in {"EXECUTION", "INVALID_JSON", "INVALID_IR"}
                for record in ledger.attempt_records.values()
            ):
                diagnostics.append(
                    _diagnostic_value(
                        _diagnostic(
                            "BUDGET_EXCEEDED", "Action 已达到重试限额或安全停止条件。"
                        )
                    )
                )
        return {
            "outcome": state["result"],
            "state": dict(state),
            "nextAction": None,
            "diagnostics": diagnostics,
        }
    if state.get('phase') == 'AWAITING_FINAL_REVIEW' and state.get('wait') == 'APPROVAL':
        path,manifest,digest = _active_artifact(files,state)
        return _artifact_result(files,state,path,digest)
    if state.get("phase") == "PREPARE" and state.get("wait") == "NONE":
        return _start_public_pipeline(files, state)
    if state.get("wait") == "NONE" and state.get("result") is None:
        return _advance_public_pipeline(files, state)
    return _complete_frozen_issuance(files,state) or _public_active_result(files, state)


def _reconcile_active_state(
    files: ProjectFiles,
    marker: Mapping[str, object],
    state: Mapping[str, object],
) -> Mapping[str, object]:
    """Replay immutable action facts across a crash before the state pointer swap."""

    _verify_completed_stages(files, state)
    run_id = str(state["runId"])
    ledger = _load_action_ledger(files, run_id)
    reconciled = dict(state)
    changed = False
    if _pending_abandon_decision(files, reconciled):
        reconciled.update(
            {
                "phase": "DONE",
                "wait": "NONE",
                "result": "ABANDONED",
                "expectedActionIds": [],
                "resumeFromPhase": None,
            }
        )
        return _write_active_state(files, marker, reconciled)
    reconciled = _reconcile_owner_clarification(files,reconciled)
    changed = reconciled != state
    budget_reconciled = _reconcile_budget_wait(files, reconciled)
    if budget_reconciled != reconciled:
        reconciled = budget_reconciled
        changed = True
    if reconciled.get('result') is None and reconciled.get('wait') != 'INPUT':
        latest = {}
        for envelope in ledger.envelopes_by_sha256.values():
            key=envelope.value['logicalWorkId']
            if key not in latest or (envelope.value['revision'],envelope.value['attempt']) > (latest[key].value['revision'],latest[key].value['attempt']):
                latest[key]=envelope
        records={record.envelope_sha256:record for record in ledger.attempt_records.values()}
        from candidate_repair import patch_context
        patch_by_source={}
        for item in latest.values():
            if item.value['actionContractId']!='CANDIDATE_PATCH-v1':continue
            view=patch_context(json.loads(files.read_bytes(item.value['packetPath'])))
            origin_id=view['origin']['originLogicalWorkId']
            if effective_result_bytes(ledger,origin_id) is not None:continue
            if item.sha256 in records and records[item.sha256].outcome=='SUCCEEDED':continue
            head=ledger.repair_heads.get(origin_id)
            if head and view['baseCandidateSha256']!=sha256_bytes(head[0]):continue
            score=(view['origin']['repairRound'],item.value['attempt'],item.value['actionId'])
            if origin_id not in patch_by_source or score>patch_by_source[origin_id][0]:patch_by_source[origin_id]=(score,item)
        pending=[item for key,item in latest.items() if item.value['actionContractId']!='CANDIDATE_PATCH-v1'
                 and key not in patch_by_source and effective_result_bytes(ledger,key) is None]
        pending.extend(entry[1] for entry in patch_by_source.values())
        if pending:
            groups={item.value['groupId'] for item in pending}
            if len(groups)!=1: raise ValueError('未完成工作不能越过当前 frozen group。')
            reconciled.update(phase=_phase_for_action_stage(pending[0].value['stageKind']),wait='MODEL',
                expectedActionIds=sorted(item.value['actionId'] for item in pending))
            changed=reconciled!=state

    expected_ids = [
        item for item in reconciled.get("expectedActionIds", []) if isinstance(item, str)
    ]
    if reconciled.get("wait") == "MODEL" and expected_ids:
        remaining: list[str] = []
        failure_route = None
        for action_id in expected_ids:
            record = _optional_json(files, _action_paths(run_id, action_id)["record"])
            if record is None:
                remaining.append(action_id)
                continue
            if not isinstance(record, Mapping) or validate_contract(
                record, "action.schema.json", NEXT_SCHEMA_REGISTRY
            ):
                raise ProjectIOError(
                    "ACTION_RECORD_INVALID",
                    _action_paths(run_id, action_id)["record"],
                    "恢复时发现无效 AttemptRecord。",
                )
            if record.get("outcome") == "SUCCEEDED" or effective_result_bytes(ledger,record['logicalWorkId']) is not None:
                changed = True
                continue
            if record.get("outcome") not in {"FAILED", "SUPERSEDED"}:
                raise ProjectIOError(
                    "ACTION_RECORD_INVALID",
                    _action_paths(run_id, action_id)["record"],
                    "恢复时发现未知 AttemptRecord 状态。",
                )
            envelope = _mapping(
                files, _action_paths(run_id, action_id)["envelope"]
            )
            if record["outcome"] == "FAILED" and record["failureKind"] in {
                "INPUT_REQUIRED",
                "CONTRACT_GAP",
                "OWNER_BUG",
                "SYSTEM",
            }:
                failure_route = record["failureKind"]
                if failure_route == "INPUT_REQUIRED":
                    _enter_attempt_input_wait(files, reconciled, record)
                changed = True
                break
            try:
                transition = _materialize_action_retry(
                    files, action_id, envelope, record
                )
            except CandidateRepairRoute as routed:
                failure_route=routed.failure_kind
                if failure_route=='INPUT_REQUIRED':
                    _enter_attempt_input_wait(files,reconciled,{**record,'diagnostic':{
                        'code':routed.reason_code,'path':'','subjectIds':[]}})
                changed=True
                break
            except (AttemptLimitReached,StagePlanningBlocked):
                # Only real capacity/attempt limits use the cumulative budget wait.
                return _wait_for_budget(files)['state']
            remaining.append(str(transition["actionId"]))
            changed = True
        if failure_route is not None:
            result_by_kind = {
                "CONTRACT_GAP": "CONTRACT_UNSUPPORTED",
                "OWNER_BUG": "MANUAL_REVIEW_REQUIRED",
                "SYSTEM": "SYSTEM_FAILED",
            }
            reconciled.update(
                {
                    "phase": (
                        reconciled["phase"]
                        if failure_route == "INPUT_REQUIRED"
                        else "DONE"
                    ),
                    "wait": "INPUT" if failure_route == "INPUT_REQUIRED" else "NONE",
                    "result": result_by_kind.get(failure_route),
                    "expectedActionIds": [],
                    "resumeFromPhase": None,
                }
            )
        elif remaining != expected_ids:
            reconciled["expectedActionIds"] = remaining
            reconciled["wait"] = "MODEL" if remaining else "NONE"

    if not changed:
        return state
    return _write_active_state(files, marker, reconciled)


def _write_active_state(
    files: ProjectFiles,
    marker: Mapping[str, object],
    state: Mapping[str, object],
) -> Mapping[str, object]:
    validation_path = str(marker["statePath"])
    validated = _validated_run_state(state, validation_path)
    state_payload = canonical_json_bytes(validated)
    state_sha256 = sha256_bytes(state_payload)
    state_path = _state_snapshot_path(str(validated["runId"]), state_sha256)
    files.publish_new(state_path, state_payload)
    active_marker = {
        **marker,
        "statePath": state_path,
        "status": "ACTIVE",
        "stateSha256": state_sha256,
    }
    files.write_atomic(ACTIVE_RUN_PATH, canonical_json_bytes(active_marker))
    return validated


def _revision_template_path(files: ProjectFiles, input_revision_path: str) -> Path:
    return files.resolve(
        f"{Path(input_revision_path).parent.as_posix()}/sow-template.xlsx",
        expect="file",
    )


def _budget_policy_source(
    files: ProjectFiles, source_path: str, *, registry: Registry | None = None
) -> Mapping[str, object]:
    registry = load_schema_registry(SKILL_ROOT) if registry is None else registry
    source = Path(source_path)
    value = (
        ProjectFiles.open(source.parent).read_json(source.name)
        if source.is_absolute()
        else files.read_json(source_path)
    )
    if not isinstance(value, Mapping) or validate_contract(
        value, "run-budget-policy.schema.json", registry
    ):
        raise ProjectIOError("RUN_BUDGET_POLICY_INVALID", source_path, "运行预算正文无效。")
    return value


def _published_budget_policy(
    files: ProjectFiles, run_id: str, digest: str, *, registry: Registry | None = None
) -> Mapping[str, object]:
    registry = load_schema_registry(SKILL_ROOT) if registry is None else registry
    relative = f"{RUNS_ROOT}/{run_id}/budget-policies/{digest}.json"
    body = _budget_policy_source(files, relative, registry=registry)
    payload = files.read_bytes(relative)
    if sha256_bytes(payload) != digest or canonical_json_bytes(body) != payload:
        raise ProjectIOError("RUN_BUDGET_POLICY_HASH_INVALID", relative, "已发布预算正文 hash 不匹配。")
    return body


def _effective_budget_policy(
    files: ProjectFiles, run_id: str, *, registry: Registry | None = None
) -> tuple[str, Mapping[str, object]]:
    registry = load_schema_registry(SKILL_ROOT) if registry is None else registry
    selected = None
    for event in _read_run_events(files, run_id):
        if event.type == "RUN_BUDGET_POLICY_PUBLISHED":
            digest = str(event.payload["budgetPolicySha256"])
            policy = _published_budget_policy(files, run_id, digest, registry=registry)
            if selected is not None:
                _validate_budget_replacement(selected[1], policy)
            selected = digest, policy
    if selected is None:
        raise ProjectIOError("RUN_BUDGET_POLICY_MISSING", "", "运行必须先发布显式预算。")
    return selected


def _budget_at_issuance(
    files: ProjectFiles, run_id: str, action_id: str, *, registry: Registry | None = None
) -> str:
    registry = load_schema_registry(SKILL_ROOT) if registry is None else registry
    _effective_budget_policy(files, run_id, registry=registry)
    selected = None
    for event in _read_run_events(files, run_id):
        if event.type == "RUN_BUDGET_POLICY_PUBLISHED":
            selected = str(event.payload["budgetPolicySha256"])
            _published_budget_policy(files, run_id, selected, registry=registry)
        elif event.type == "ACTION_ISSUED" and event.payload["actionId"] == action_id:
            if selected is None:
                raise ProjectIOError("RUN_BUDGET_POLICY_MISSING", "", "Action 发放前没有预算事件。")
            return selected
    raise ProjectIOError("ACTION_ISSUANCE_PROOF_INVALID", "", "Action 缺少精确发放事件。")


def _validate_budget_replacement(previous: Mapping[str, object], policy: Mapping[str, object]) -> None:
    variable_keys = {"maxPlannedTokens", "maxActiveSeconds", "modelContextLimitTokens", "hydrateReserveTokens", "demoLimits", "maxActionRevisions", "maxExecutionAttempts", "maxDeterministicAttempts"}
    old_limits = [previous[key] for key in ("maxPlannedTokens", "maxActiveSeconds", "modelContextLimitTokens", "hydrateReserveTokens")]
    new_limits = [policy[key] for key in ("maxPlannedTokens", "maxActiveSeconds", "modelContextLimitTokens", "hydrateReserveTokens")]
    for key in ("maxActionRevisions", "maxExecutionAttempts", "maxDeterministicAttempts"):
        old_limits.append(previous.get(key, 2))
        new_limits.append(policy.get(key, 2))
    for key in ("maxDiscoveryRounds", "maxScenarioSteps", "maxScreenshots"):
        old_limits.append(previous["demoLimits"][key])
        new_limits.append(policy["demoLimits"][key])
    if (
        any(policy[key] != previous[key] for key in policy if key not in variable_keys)
        or any(new < old for old, new in zip(old_limits, new_limits, strict=True))
        or not any(new > old for old, new in zip(old_limits, new_limits, strict=True))
    ):
        raise ProjectIOError(
            "RUN_BUDGET_REPLACEMENT_INVALID", "",
            "同 run 必须严格增加至少一项 token、active time、未来请求的上下文容量、hydrate reserve 或 Demo 限额；已发放 Envelope 和冻结计划保持原绑定。正文相同、降低限额或改变其它配置均拒绝，需要新 run。",
        )


def _publish_budget_policy(
    files: ProjectFiles, run_id: str, policy: Mapping[str, object]
) -> str:
    payload = canonical_json_bytes(policy)
    digest = sha256_bytes(payload)
    budget_events = [
        event for event in _read_run_events(files, run_id)
        if event.type == "RUN_BUDGET_POLICY_PUBLISHED"
    ]
    if budget_events:
        previous_digest = str(budget_events[-1].payload["budgetPolicySha256"])
        previous = _published_budget_policy(files, run_id, previous_digest)
        if previous_digest == digest:
            return digest
        _validate_budget_replacement(previous, policy)
    files.publish_new(f"{RUNS_ROOT}/{run_id}/budget-policies/{digest}.json", payload)
    _append_run_event(
        files, run_id, "RUN_BUDGET_POLICY_PUBLISHED", {"budgetPolicySha256": digest}
    )
    return digest


def start(
    project_root: Path, request_path: str, budget_policy_path: str
) -> dict[str, object]:
    files = ProjectFiles.open(project_root)
    try:
        policy = _budget_policy_source(files, budget_policy_path)
        managed_request_path = _managed_request_path(files, request_path)
        request_sha256 = sha256_bytes(files.read_bytes(managed_request_path))
        marker = _read_active_marker(files)
        if marker is not None:
            if marker["requestSha256"] != request_sha256:
                return _result(
                    "RUN_IN_PROGRESS",
                    "同一项目已有绑定不同 request 的 active run。",
                    diagnostics=(
                        _diagnostic(
                            "RUN_IN_PROGRESS",
                            "请继续或明确放弃现有 run，不能并行启动第二个顶层 run。",
                            ACTIVE_RUN_PATH,
                        ),
                    ),
                )
            recovered = _recover_active_run(files, marker)
            return _attempt_stop_response(files, recovered) or _active_result(recovered)

        run_id = f"run-{uuid4().hex[:12]}"
        revision = prepare_input_revision(managed_request_path, files=files)
        if revision.value is None or revision.sha256 is None:
            return _result(
                "BLOCKED",
                "输入未通过 Prepare 门禁，未创建 active run。",
                diagnostics=revision.diagnostics,
            )
        _publish_budget_policy(files, run_id, policy)
        reservation = _active_marker_value(
            run_id=run_id,
            request_path=managed_request_path,
            request_sha256=request_sha256,
            input_revision_sha256=revision.sha256,
            input_revision_path=str(revision.path),
        )
        if not files.create_exclusive(
            ACTIVE_RUN_PATH, canonical_json_bytes(reservation)
        ):
            marker = _read_active_marker(files)
            if marker is None:
                raise ProjectIOError(
                    "ACTIVE_RUN_RACE",
                    ACTIVE_RUN_PATH,
                    "active run reservation 未能稳定建立。",
                )
            if marker["requestSha256"] != request_sha256:
                return _result(
                    "RUN_IN_PROGRESS",
                    "同一项目已有绑定不同 request 的 active run。",
                    diagnostics=(
                        _diagnostic(
                            "RUN_IN_PROGRESS",
                            "请继续或明确放弃现有 run，不能并行启动第二个顶层 run。",
                            ACTIVE_RUN_PATH,
                        ),
                    ),
                )
            recovered = _recover_active_run(files, marker)
            return _attempt_stop_response(files, recovered) or _active_result(recovered)
        state = _recover_active_run(files, reservation)
        return _active_result(state)
    except ProjectIOError as error:
        return _blocked(error.code, str(error), error.relative_path)


def _complete_frozen_issuance(files,state):
    if not state.get('expectedActionIds'): return None
    ledger=_load_action_ledger(files,state['runId'])
    envelope=next((item for item in ledger.envelopes_by_sha256.values() if item.value['actionId']==state['expectedActionIds'][0]), None)
    if envelope is None:
        return _blocked('ACTION_ISSUANCE_PROOF_INVALID', '预期 Action 缺少有效发放证明。', state['expectedActionIds'][0])
    stage=envelope.value['stageKind'];group_id=envelope.value['groupId']
    raw=_one_content(files,_stage_root(state,stage)+'/plans')
    if raw is None: return None
    group=next((item for item in json.loads(raw)['groups'] if item['groupId']==group_id),None)
    if group is None: return None
    issued={item.value['logicalWorkId'] for item in ledger.envelopes_by_sha256.values()}
    if set(group['requiredLogicalWorkIds'])<=issued: return None
    plan,items,contexts,policy,inputs=_frozen_stage_inputs(files,state,stage)
    return _issue_frozen_group(files,state,plan,items,contexts,group)


def _recover_group_before_budget_replacement(files,state):
    # Complete physical Envelopes with their original policy before publishing a replacement.
    root=files.ensure_dir(f"{RUNS_ROOT}/{state['runId']}/actions")
    ledger=_load_action_ledger(files,state['runId'])
    for path in root.glob('*/envelope.json'):
        value=json.loads(path.read_bytes())
        if sha256_bytes(path.read_bytes()) not in ledger.envelopes_by_sha256:
            _persist_issued_action(files,value,files.read_bytes(value['packetPath']))
    if state.get('wait')!='INPUT': _complete_frozen_issuance(files,state)


def resume(
    project_root: Path,
    replacement_budget_policy_path: str | None = None,
    owner_clarification_path: str | None = None,
) -> dict[str, object]:
    files = ProjectFiles.open(project_root)
    try:
        if owner_clarification_path is not None:
            answer=_mapping(files,_managed_request_path(files,owner_clarification_path))
            if answer.get('contract')=='ai-sow-owner-repair-authorization-v1':
                _resume_manual_owner_repair(files,owner_clarification_path)
                owner_clarification_path=None
            elif answer.get('contract')=='ai-sow-artifact-repair-authorization-v1':
                _resume_artifact_repair(files,owner_clarification_path)
                owner_clarification_path=None
        marker = _read_active_marker(files)
        if marker is None:
            return _blocked("RUN_NOT_ACTIVE", "当前项目没有 active run。")
        _, previous_policy = _effective_budget_policy(files, str(marker["runId"]))
        if replacement_budget_policy_path is not None:
            policy = _budget_policy_source(files, replacement_budget_policy_path)
            _validate_budget_replacement(previous_policy, policy)
            try:
                state = _recover_active_run(files, marker)
            except StagePlanningBlocked as error:
                state = _read_active_run(files, marker)
                if error.reason_code != "BUDGET_EXHAUSTED" or state.get("wait") != "INPUT" or state.get("expectedActionIds"):
                    raise
                # An unissued retry may exceed the old capacity. Publish the
                # explicit increase before retrying, retaining every issued byte.
            if state.get('phase') == 'DONE':
                return _attempt_stop_response(files, state) or _active_result(state)
            _recover_group_before_budget_replacement(files, state)
            digest = _publish_budget_policy(files, str(marker["runId"]), policy)
            _exit_budget_wait(files, digest)
            marker = _read_active_marker(files)
        recovered = _recover_active_run(files, marker)
        if recovered.get('phase') == 'DONE':
            return _attempt_stop_response(files, recovered) or _active_result(recovered)
        if owner_clarification_path is not None:
            _accept_owner_clarification(files,recovered,owner_clarification_path)
            recovered = _recover_active_run(files, marker)
        if replacement_budget_policy_path is None:
            _resume_fitting_unissued_retry(files,recovered)
            recovered = _recover_active_run(files, marker)
            _resume_fitting_unissued_plan(files,recovered)
            recovered = _recover_active_run(files, marker)
            _resume_fitting_owner_repair(files,recovered)
            recovered = _recover_active_run(files, marker)
        return _attempt_stop_response(files, recovered) or _active_result(recovered)
    except ProjectIOError as error:
        return _blocked(error.code, str(error), error.relative_path)


def _approval_artifact(
    files: ProjectFiles,
    artifact_manifest_sha256: str,
) -> tuple[str, Mapping[str, object]]:
    if re.fullmatch(r"[0-9a-f]{64}", artifact_manifest_sha256) is None:
        raise ProjectIOError(
            "ARTIFACT_MANIFEST_HASH_INVALID",
            str(artifact_manifest_sha256),
            "artifact manifest hash must be lower-case SHA-256",
        )
    try:
        runs_root = files.resolve(RUNS_ROOT, expect="dir")
    except ProjectIOError as error:
        if error.code == "PROJECT_PATH_MISSING":
            raise ProjectIOError(
                "ARTIFACT_MANIFEST_NOT_FOUND",
                RUNS_ROOT,
                "requested artifact manifest was not found",
            ) from error
        raise
    matches: list[tuple[str, Mapping[str, object]]] = []
    for path in sorted(runs_root.glob("*/artifacts/*/artifact-manifest.json")):
        relative = path.relative_to(files.root).as_posix()
        payload = files.read_bytes(relative)
        if sha256_bytes(payload) != artifact_manifest_sha256:
            continue
        value = files.read_json(relative)
        diagnostics = validate_contract(
            value,
            "artifact-approval.schema.json",
            NEXT_SCHEMA_REGISTRY,
        )
        if diagnostics or not isinstance(value, Mapping):
            raise ProjectIOError(
                "ARTIFACT_MANIFEST_INVALID",
                relative,
                "artifact manifest is not contract-valid",
            )
        matches.append((relative, value))
    if not matches:
        raise ProjectIOError(
            "ARTIFACT_MANIFEST_NOT_FOUND",
            RUNS_ROOT,
            "requested artifact manifest was not found",
        )
    if len(matches) > 1:
        raise ProjectIOError(
            "ARTIFACT_MANIFEST_NOT_UNIQUE",
            RUNS_ROOT,
            "artifact approval must resolve exactly one manifest",
        )
    return matches[0]


def _existing_nonapproval_decision(
    files: ProjectFiles,
    manifest: Mapping[str, object],
    artifact_manifest_sha256: str,
) -> tuple[str, Mapping[str, object]] | None:
    decisions_root = f"{RUNS_ROOT}/{manifest['runId']}/decisions"
    try:
        root = files.resolve(decisions_root, expect="dir")
    except ProjectIOError as error:
        if error.code == "PROJECT_PATH_MISSING":
            return None
        raise
    matches: list[tuple[str, Mapping[str, object]]] = []
    for path in sorted(root.glob("*.json")):
        relative = path.relative_to(files.root).as_posix()
        value = files.read_json(relative)
        if (
            isinstance(value, Mapping)
            and value.get("artifactManifestSha256")
            == artifact_manifest_sha256
        ):
            matches.append((relative, value))
    if len(matches) > 1:
        raise ProjectIOError(
            "ARTIFACT_DECISION_CONFLICT",
            decisions_root,
            "artifact has more than one non-approval decision",
        )
    return matches[0] if matches else None


def _terminalize_active_run(
    files: ProjectFiles,
    marker: Mapping[str, object],
    *,
    result: str,
) -> Mapping[str, object]:
    state = dict(_recover_active_run(files, marker))
    current_marker = _read_active_marker(files)
    if (
        current_marker is None
        and state.get("phase") == "DONE"
        and state.get("result") == result
    ):
        return state
    if current_marker is None or current_marker.get("runId") != marker.get("runId"):
        raise ProjectIOError(
            "ACTIVE_RUN_MARKER_MISSING",
            ACTIVE_RUN_PATH,
            "终态切换期间 active run 已变化。",
        )
    if result == "ABANDONED":
        _close_attempt_input_wait(files, str(state["runId"]))
    terminal_state = _write_active_state(
        files,
        current_marker,
        {
            **state,
            "phase": "DONE",
            "wait": "NONE",
            "result": result,
            "expectedActionIds": [],
            "resumeFromPhase": None,
        },
    )
    active_payload = files.read_bytes(ACTIVE_RUN_PATH)
    files.unlink_exact(ACTIVE_RUN_PATH, expected_payload=active_payload)
    return terminal_state


def _active_artifact(
    files: ProjectFiles,
    state: Mapping[str, object],
) -> tuple[str, Mapping[str, object], str] | None:
    if state.get("phase") != "AWAITING_FINAL_REVIEW":
        return None
    root_path = f"{RUNS_ROOT}/{state['runId']}/artifacts"
    try:
        root = files.resolve(root_path, expect="dir")
    except ProjectIOError as error:
        if error.code == "PROJECT_PATH_MISSING":
            return None
        raise
    matches: list[tuple[str, Mapping[str, object], str]] = []
    for path in sorted(root.glob("*/artifact-manifest.json")):
        relative = path.relative_to(files.root).as_posix()
        payload = files.read_bytes(relative)
        manifest = files.read_json(relative)
        if (
            isinstance(manifest, Mapping)
            and manifest.get("runId") == state.get("runId")
            and manifest.get("candidateSha256")
            == state.get("currentCandidateSha256")
            and not validate_contract(
                manifest,
                "artifact-approval.schema.json",
                NEXT_SCHEMA_REGISTRY,
            )
        ):
            matches.append((relative, manifest, sha256_bytes(payload)))
    if len(matches) != 1:
        raise ProjectIOError(
            "ACTIVE_ARTIFACT_NOT_UNIQUE",
            root_path,
            "批准等待态必须精确绑定一份当前 artifact manifest。",
        )
    return matches[0]


def approve(
    project_root: Path,
    artifact_manifest_sha256: str,
    decision_path: str | None = None,
) -> dict[str, object]:
    """Record one hash-bound decision and promote only exact APPROVE bytes."""
    files = ProjectFiles.open(project_root)
    try:
        manifest_path, manifest = _approval_artifact(
            files, artifact_manifest_sha256
        )
        artifact_root = Path(manifest_path).parent.as_posix()
        approval_path = f"{artifact_root}/approval.json"
        if decision_path is None:
            try:
                existing = files.read_json(approval_path)
            except ProjectIOError as error:
                if error.code != "PROJECT_PATH_MISSING":
                    raise
                existing = None
            if isinstance(existing, Mapping):
                decision = dict(existing)
            else:
                decision = {
                    "contract": "ai-sow-approval-v1",
                    "runId": manifest["runId"],
                    "artifactManifestSha256": artifact_manifest_sha256,
                    "reviewDecisionSha256": manifest["reviewDecisionSha256"],
                    "candidateSha256": manifest["candidateSha256"],
                    "sourceManifestSha256": manifest["sourceManifestSha256"],
                    "templateSha256": manifest["templateSha256"],
                    "effectivePolicyDecisionSha256": manifest[
                        "effectivePolicyDecisionSha256"
                    ],
                    "decision": "APPROVE",
                    "approvedAt": datetime.now(UTC).isoformat().replace(
                        "+00:00", "Z"
                    ),
                }
        else:
            managed_decision_path = _managed_request_path(files, decision_path)
            decision_value = files.read_json(managed_decision_path)
            if not isinstance(decision_value, Mapping):
                raise ProjectIOError(
                    "APPROVAL_INVALID",
                    managed_decision_path,
                    "approval decision must be a JSON object",
                )
            decision = dict(decision_value)
        diagnostics = validate_contract(
            decision,
            "artifact-approval.schema.json",
            NEXT_SCHEMA_REGISTRY,
        )
        if diagnostics:
            raise ProjectIOError(
                "APPROVAL_INVALID",
                decision_path or approval_path,
                "approval decision does not satisfy the strict union",
            )
        for field in (
            "runId",
            "candidateSha256",
            "sourceManifestSha256",
            "reviewDecisionSha256",
            "templateSha256",
            "effectivePolicyDecisionSha256",
        ):
            if decision.get(field) != manifest.get(field):
                raise ProjectIOError(
                    "APPROVAL_BINDING_MISMATCH",
                    decision_path or approval_path,
                    f"approval does not bind artifact field: {field}",
                )
        if decision.get("artifactManifestSha256") != artifact_manifest_sha256:
            raise ProjectIOError(
                "APPROVAL_BINDING_MISMATCH",
                decision_path or approval_path,
                "approval does not bind the selected artifact manifest",
            )
        decision_payload = canonical_json_bytes(decision)
        existing_nonapproval = _existing_nonapproval_decision(
            files,
            manifest,
            artifact_manifest_sha256,
        )
        if existing_nonapproval is not None:
            existing_path, existing_decision = existing_nonapproval
            if canonical_json_bytes(existing_decision) != decision_payload:
                raise ProjectIOError(
                    "ARTIFACT_MANIFEST_STALE",
                    existing_path,
                    "artifact already has a different terminal decision",
                )
        marker = _read_active_marker(files)
        if marker is not None and marker.get("runId") != manifest["runId"]:
            raise ProjectIOError(
                "RUN_NOT_ACTIVE",
                ACTIVE_RUN_PATH,
                "工件决策不能跨越另一个 active run。",
            )
        active_decision_state: Mapping[str, object] | None = None
        if marker is not None:
            active_decision_state = _recover_active_run(files, marker)
            if existing_nonapproval is not None:
                if (
                    decision["decision"] == "ABANDON"
                    and active_decision_state.get("phase") == "DONE"
                    and active_decision_state.get("result") == "ABANDONED"
                ):
                    return {
                        "outcome": "ABANDONED",
                        "state": dict(active_decision_state),
                        "decisionPath": existing_nonapproval[0],
                        "nextAction": None,
                        "diagnostics": [],
                    }
            published_replay = (
                decision["decision"] == "APPROVE"
                and active_decision_state.get("phase") == "DONE"
                and active_decision_state.get("result") == "PUBLISHED"
                and _optional_json(files, approval_path) == decision
            )
            if (
                active_decision_state.get("phase") != "AWAITING_FINAL_REVIEW"
                and not published_replay
            ) or active_decision_state.get("currentCandidateSha256") != manifest[
                "candidateSha256"
            ]:
                raise ProjectIOError(
                    "ARTIFACT_MANIFEST_STALE",
                    manifest_path,
                    "工件决定只能作用于当前批准等待态的 artifact。",
                )
        if decision["decision"] == "APPROVE":
            if existing_nonapproval is not None:
                raise ProjectIOError(
                    "ARTIFACT_MANIFEST_STALE",
                    existing_nonapproval[0],
                    "abandoned artifact cannot be approved",
                )
            files.publish_new(approval_path, decision_payload)
            publication = promote(
                artifact_manifest_sha256,
                decision,
                files=files,
            )
            result = {
                "outcome": publication.outcome,
                "generationId": publication.generation_id,
                "workbookPath": publication.workbook_path,
                "notesPath": publication.notes_path,
                "approvalPath": approval_path,
                "artifactManifestSha256": artifact_manifest_sha256,
                "diagnostics": [],
            }
            if marker is not None:
                state = dict(_recover_active_run(files, marker))
                terminal_state = _write_active_state(
                    files,
                    marker,
                    {
                        **state,
                        "phase": "DONE",
                        "wait": "NONE",
                        "result": "PUBLISHED",
                        "expectedActionIds": [],
                        "resumeFromPhase": None,
                    },
                )
                active_payload = files.read_bytes(ACTIVE_RUN_PATH)
                files.unlink_exact(ACTIVE_RUN_PATH, expected_payload=active_payload)
                result["state"] = dict(terminal_state)
            return result
        decision_sha256 = sha256_bytes(decision_payload)
        run_root = f"{RUNS_ROOT}/{manifest['runId']}"
        record_path = f"{run_root}/decisions/abandon-{decision_sha256}.json"
        files.publish_new(record_path, decision_payload)
        result: dict[str, object] = {
            "outcome": "ABANDONED",
            "decisionPath": record_path,
            "nextAction": None,
            "diagnostics": [],
        }
        if marker is not None:
            result["state"] = dict(
                _terminalize_active_run(files, marker, result="ABANDONED")
            )
        return result
    except ProjectIOError as error:
        return _blocked(error.code, str(error), error.relative_path)


def abandon(project_root: Path) -> dict[str, object]:
    files = ProjectFiles.open(project_root)
    try:
        marker = _read_active_marker(files)
        if marker is None:
            return _blocked("RUN_NOT_ACTIVE", "当前项目没有 active run。")
        state = dict(_recover_active_run(files, marker))
        if state.get("phase") == "DONE" and state.get("result") == "ABANDONED":
            return {"outcome": "ABANDONED", "state": state, "diagnostics": []}
        active_artifact = _active_artifact(files, state)
        decision_path: str | None = None
        if active_artifact is not None:
            _manifest_path, manifest, manifest_sha256 = active_artifact
            decision = {
                "contract": "ai-sow-approval-v1",
                "runId": manifest["runId"],
                "artifactManifestSha256": manifest_sha256,
                "reviewDecisionSha256": manifest["reviewDecisionSha256"],
                "candidateSha256": manifest["candidateSha256"],
                "sourceManifestSha256": manifest["sourceManifestSha256"],
                "templateSha256": manifest["templateSha256"],
                "effectivePolicyDecisionSha256": manifest[
                    "effectivePolicyDecisionSha256"
                ],
                "decision": "ABANDON",
                "reason": "用户通过公共 abandon 操作终止本轮。",
            }
            decision_payload = canonical_json_bytes(decision)
            decision_sha256 = sha256_bytes(decision_payload)
            decision_path = (
                f"{RUNS_ROOT}/{state['runId']}/decisions/"
                f"abandon-{decision_sha256}.json"
            )
            files.publish_new(decision_path, decision_payload)
        current_marker = _read_active_marker(files)
        if current_marker is None:
            raise ProjectIOError(
                "ACTIVE_RUN_MARKER_MISSING",
                ACTIVE_RUN_PATH,
                "active run marker 意外缺失。",
            )
        terminal_state = _terminalize_active_run(
            files, current_marker, result="ABANDONED"
        )
        return {
            "outcome": "ABANDONED",
            "state": dict(terminal_state),
            **({"decisionPath": decision_path} if decision_path else {}),
            "diagnostics": [],
        }
    except ProjectIOError as error:
        return _blocked(error.code, str(error), error.relative_path)


def _append_candidate_snapshot(
    files: ProjectFiles,
    run_id: str,
    model: Mapping[str, object],
) -> dict[str, object]:
    marker = _read_active_marker(files)
    if marker is None or marker["runId"] != run_id:
        raise ProjectIOError(
            "RUN_NOT_ACTIVE",
            ACTIVE_RUN_PATH,
            "candidate 只能写入当前 active run。",
        )
    state = dict(_recover_active_run(files, marker))
    payload = canonical_json_bytes(model)
    candidate_sha256 = sha256_bytes(payload)
    if state.get("currentCandidateSha256") == candidate_sha256:
        current_path = str(state["currentCandidatePath"])
        if files.read_bytes(current_path) != payload:
            raise ProjectIOError(
                "RUN_CANDIDATE_HASH_MISMATCH",
                current_path,
                "当前 candidate 文件与 state hash 不一致。",
            )
        return {"path": current_path, "sha256": candidate_sha256}

    run_root, _, _ = _run_paths(run_id)
    candidate_root = f"{run_root}/candidates"
    directory = files.ensure_dir(candidate_root)
    highest_sequence = 0
    for child in directory.iterdir():
        relative = f"{candidate_root}/{child.name}"
        files.resolve(relative, expect="file")
        match = re.fullmatch(r"([0-9]{6})-([0-9a-f]{64})\.json", child.name)
        if match is None:
            raise ProjectIOError(
                "RUN_CANDIDATE_PATH_INVALID",
                relative,
                "candidate 目录包含非合同文件。",
            )
        if sha256_bytes(files.read_bytes(relative)) != match.group(2):
            raise ProjectIOError(
                "RUN_CANDIDATE_HASH_MISMATCH",
                relative,
                "历史 candidate 文件名哈希与内容不一致。",
            )
        highest_sequence = max(highest_sequence, int(match.group(1)))

    sequence = highest_sequence + 1
    candidate_path = f"{candidate_root}/{sequence:06d}-{candidate_sha256}.json"
    files.publish_new(candidate_path, payload)
    marker = _read_active_marker(files)
    if marker is None or marker["runId"] != run_id:
        raise ProjectIOError(
            "RUN_NOT_ACTIVE",
            ACTIVE_RUN_PATH,
            "candidate 写入期间 active run 已变化。",
        )
    state.update(
        {
            "currentCandidateSha256": candidate_sha256,
            "currentCandidatePath": candidate_path,
        }
    )
    _write_active_state(files, marker, state)
    return {"path": candidate_path, "sha256": candidate_sha256}


def _action_paths(run_id: str, action_id: str) -> dict[str, str]:
    run_root, _, _ = _run_paths(run_id)
    if not isinstance(action_id, str) or not re.fullmatch(
        r"action-[0-9a-f]{12}", action_id
    ):
        raise ProjectIOError("ACTION_ID_INVALID", str(action_id), "action ID 格式无效。")
    root = f"{run_root}/actions/{action_id}"
    return {
        "root": root,
        "envelope": f"{root}/envelope.json",
        "packet": f"{root}/packet.json",
        "normalized": f"{root}/normalized-result.json",
        "raw": f"{root}/raw-output.bin",
        "hydrations": f"{root}/hydrations",
        "output": f"{root}/submission.json",
        "record": f"{root}/record.json",
    }


def _phase_for_action_stage(stage: object) -> str:
    if stage == "SCOPE":
        return "EPIC_FEATURE"
    if stage == "ARTIFACT":
        return "DRAFT"
    if stage in {"EPIC_FEATURE", "STORY_AC", "TASK", "REPAIR"}:
        return str(stage)
    if stage in {
        "SOURCE_AUDIT",
        "SOURCE_SCOPE",
        "STORY_DESIGN",
        "TASK_ESTIMATION",
        "THEME_JOIN",
        "ADJUDICATION",
    }:
        return "REVIEW"
    raise ProjectIOError("ACTION_STAGE_INVALID", str(stage), "action stage 不受支持。")


def _read_run_events(files: ProjectFiles, run_id: str) -> list[RunEvent]:
    root = f"{RUNS_ROOT}/{run_id}/events"
    try:
        directory = files.resolve(root, expect="dir")
    except ProjectIOError as error:
        if error.code == "PROJECT_PATH_MISSING":
            return []
        raise
    events = []
    for path in sorted(directory.glob("*.json")):
        value = _mapping(files, f"{root}/{path.name}")
        if value.get("runId") != run_id:
            raise ProjectIOError(
                "ACTION_ISSUANCE_PROOF_INVALID", f"{root}/{path.name}",
                "运行事件不属于当前 run，不能授权发放或恢复。",
            )
        events.append(
            RunEvent(
                value["runId"],
                value["sequence"],
                value["type"],
                value["occurredAtUtc"],
                value["payload"],
            )
        )
    validate_run_event_log(events)
    return events


def _append_run_event(
    files: ProjectFiles, run_id: str, event_type: str, payload: Mapping[str, object]
) -> None:
    events = _read_run_events(files, run_id)
    event = RunEvent(
        run_id,
        len(events) + 1,
        event_type,
        datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        payload,
    )
    validate_run_event_log([*events, event])
    files.publish_new(
        f"{RUNS_ROOT}/{run_id}/events/{event.sequence:06d}.json",
        canonical_json_bytes(run_event_value(event)),
    )


def _enter_attempt_input_wait(
    files: ProjectFiles, state: Mapping[str, object], record: Mapping[str, object]
) -> None:
    run_id = str(state["runId"])
    wait_id = "wait-" + sha256_bytes(canonical_json_bytes(record))
    events = _read_run_events(files, run_id)
    if any(
        event.type == "WAITING_INPUT_ENTERED" and event.payload["waitId"] == wait_id
        for event in events
    ):
        return
    latest_state = next(
        (
            event.payload["toState"]
            for event in reversed(events)
            if event.type == "RUN_STATE_CHANGED"
        ),
        None,
    )
    if latest_state != "WAITING_INPUT":
        _append_run_event(
            files,
            run_id,
            "RUN_STATE_CHANGED",
            {"fromState": state["phase"], "toState": "WAITING_INPUT"},
        )
    _append_run_event(
        files,
        run_id,
        "WAITING_INPUT_ENTERED",
        {"waitId": wait_id, "reasonCode": record["diagnostic"]["code"]},
    )


def _close_attempt_input_wait(files: ProjectFiles, run_id: str) -> None:
    events = _read_run_events(files, run_id)
    exited = {
        event.payload["waitId"]
        for event in events
        if event.type == "WAITING_INPUT_EXITED"
    }
    open_waits = [
        event.payload["waitId"]
        for event in events
        if event.type == "WAITING_INPUT_ENTERED"
        and event.payload["waitId"] not in exited
    ]
    if open_waits:
        _append_run_event(
            files,
            run_id,
            "WAITING_INPUT_EXITED",
            {"waitId": open_waits[0], "resolutionKind": "ABANDONED"},
        )
        _append_run_event(
            files,
            run_id,
            "RUN_STATE_CHANGED",
            {"fromState": "WAITING_INPUT", "toState": "ABANDONED"},
        )


def _wait_for_budget(files: ProjectFiles) -> dict[str, object]:
    marker = _read_active_marker(files)
    if marker is None:
        raise ProjectIOError("RUN_NOT_ACTIVE", ACTIVE_RUN_PATH, "预算等待缺少active run。")
    state = _read_active_run(files, marker)
    stopped = _attempt_stop_response(files, state)
    if stopped is not None:
        return stopped
    run_id = str(state["runId"])
    events = _read_run_events(files, run_id)
    wait_id = "wait-budget-" + sha256_bytes(canonical_json_bytes({"runId": run_id, "sequence": len(events) + 1}))
    _append_run_event(files, run_id, "RUN_STATE_CHANGED", {"fromState": state["phase"], "toState": "WAITING_INPUT"})
    _append_run_event(files, run_id, "WAITING_INPUT_ENTERED", {"waitId": wait_id, "reasonCode": "BUDGET_EXHAUSTED"})
    waiting = _write_active_state(files, marker, {
        **state, "wait": "INPUT", "expectedActionIds": [], "resumeFromPhase": state["phase"],
    })
    return _attempt_stop_response(files, waiting)


def _resume_fitting_unissued_retry(files,state):
    if state.get('wait')!='INPUT' or state.get('result') is not None: return
    events=_read_run_events(files,state['runId'])
    closed={event.payload['waitId'] for event in events if event.type=='WAITING_INPUT_EXITED'}
    waiting=next((event for event in reversed(events) if event.type=='WAITING_INPUT_ENTERED'
        and event.payload['reasonCode']=='BUDGET_EXHAUSTED' and event.payload['waitId'] not in closed),None)
    if waiting is None: return
    ledger=_load_action_ledger(files,state['runId'])
    earlier={event.payload['actionId'] for event in events if event.type=='ACTION_ISSUED' and event.sequence<waiting.sequence}
    records = sorted(
        ledger.attempt_records.items(),
        key=lambda item: (
            ledger.envelopes_by_sha256[item[1].envelope_sha256].value[
                'actionContractId'
            ] != 'CANDIDATE_PATCH-v1',
            item[1].logical_work_id,
            item[1].revision,
            item[1].attempt,
        ),
    )
    for digest,record in records:
        original=ledger.envelopes_by_sha256[record.envelope_sha256].value
        if (record.outcome!='FAILED' or record.failure_kind not in {'INVALID_JSON','INVALID_IR'}
                or original['actionId'] not in earlier): continue
        later=[env for env in ledger.envelopes_by_sha256.values() if env.value['logicalWorkId']==record.logical_work_id
            and (env.value['revision'],env.value['attempt'])>(record.revision,record.attempt)]
        if any(env.value['actionId'] in earlier or any(item.envelope_sha256==env.sha256
                for item in ledger.attempt_records.values()) for env in later): continue
        try:
            retry=_materialize_action_retry(files,original['actionId'],original,attempt_record_value(record))
        except AttemptLimitReached:
            return
        _append_run_event(files,state['runId'],'WAITING_INPUT_EXITED',{
            'waitId':waiting.payload['waitId'],'resolutionKind':'FITTING_UNISSUED_RETRY',
            'actionId':retry['actionId'],'envelopeSha256':sha256_bytes(canonical_json_bytes(retry)),
            'failedAttemptRecordSha256':digest})
        return


def _resume_fitting_unissued_plan(files, state):
    from stage_planner import next_issuable_group
    if state.get('wait')!='INPUT' or state.get('result') is not None: return
    stage={'PREPARE':'SCOPE','EPIC_FEATURE':'SCOPE','SCOPE':'SCOPE','STORY_AC':'STORY_AC','TASK':'TASK'}.get(state['phase'])
    if stage is None: return
    events=_read_run_events(files,state['runId'])
    closed={event.payload['waitId'] for event in events if event.type=='WAITING_INPUT_EXITED'}
    waiting=next((event for event in reversed(events) if event.type=='WAITING_INPUT_ENTERED'
        and event.payload['reasonCode']=='BUDGET_EXHAUSTED' and event.payload['waitId'] not in closed),None)
    if waiting is None: return
    earlier={event.payload['actionId'] for event in events if event.type=='ACTION_ISSUED' and event.sequence<waiting.sequence}
    ledger=_load_action_ledger(files,state['runId'])
    if any(env.value['actionId'] in earlier and env.value['stageKind']==stage
           and not env.value['actionContractId'].startswith('PROTOTYPE_')
           for env in ledger.envelopes_by_sha256.values()): return
    if _one_content(files,_stage_root(state,stage)+'/checkpoints') is not None: return
    plan,items,contexts,policy,inputs=_frozen_stage_inputs(files,state,stage)
    group=next_issuable_group(plan,ledger)
    if group is None: return
    # Guard and publish this exact first group before recording recovery. Any
    # interrupted issuance is reconstructed from the same immutable plan.
    _issue_frozen_group(files,state,plan,items,contexts,group)
    _append_run_event(files,state['runId'],'WAITING_INPUT_EXITED',{
        'waitId':waiting.payload['waitId'],'resolutionKind':'FITTING_UNISSUED_PLAN',
        'stageKind':stage,'stagePlanSha256':sha256_bytes(canonical_json_bytes(plan)),
        'groupId':group['groupId']})


def _resume_fitting_owner_repair(files, state):
    if state.get('wait') != 'INPUT' or state.get('result') is not None or state['phase'] not in {'SCOPE','STORY_AC','TASK'}: return
    events = _read_run_events(files,state['runId'])
    closed = {event.payload['waitId'] for event in events if event.type=='WAITING_INPUT_EXITED'}
    waiting = next((event for event in reversed(events) if event.type=='WAITING_INPUT_ENTERED'
        and event.payload['reasonCode']=='BUDGET_EXHAUSTED' and event.payload['waitId'] not in closed),None)
    if waiting is None or not state.get('currentCandidateSha256'): return
    stage=state['phase']
    _,_,review=_control_bundle(files,state,stage,'REVIEW',state['currentCandidateSha256'])
    if review is None or review['result']['decision']!='REPAIRABLE_SEMANTIC': return
    ledger=_load_action_ledger(files,state['runId'])
    earlier={event.payload['actionId'] for event in events if event.type=='ACTION_ISSUED' and event.sequence<waiting.sequence}
    if any(env.value['actionId'] in earlier and env.value['stageKind']==stage
           and env.value['actionContractId'] in {'SCOPE_REPAIR-v1','STORY_AC_REPAIR-v1','TASK_REPAIR-v1','TASK_REPAIR-v2'}
           for env in ledger.envelopes_by_sha256.values()): return
    plan,items,contexts,planning,inputs=_frozen_stage_inputs(files,state,stage)
    packet,decisions=_stage_ir(files,state,stage,plan,items,contexts,planning,inputs)
    review_packet=_review_packet_for_candidate(files,state,stage,state['currentCandidateSha256'])
    response=_issue_semantic_candidate_repair(
        files,state,stage,plan,packet,decisions,review_packet,review,None)
    envelope=response['nextAction'];envelope_sha=sha256_bytes(canonical_json_bytes(envelope))
    _append_run_event(files,state['runId'],'WAITING_INPUT_EXITED',{
        'waitId':waiting.payload['waitId'],'resolutionKind':'FITTING_UNISSUED_CANDIDATE_REPAIR',
        'actionId':envelope['actionId'],'envelopeSha256':envelope_sha})


def _exit_budget_wait(files: ProjectFiles, policy_sha256: str) -> None:
    marker = _read_active_marker(files)
    if marker is None:
        raise ProjectIOError("RUN_NOT_ACTIVE", ACTIVE_RUN_PATH, "预算恢复缺少active run。")
    state = _read_active_run(files, marker)
    reconciled = _reconcile_budget_wait(files, state)
    if reconciled != state:
        _write_active_state(files, marker, reconciled)


def _reconcile_budget_wait(
    files: ProjectFiles, state: Mapping[str, object]
) -> dict[str, object]:
    """Finish only budget-wait transitions already authorized by run events."""
    run_id = str(state["runId"])
    events = _read_run_events(files, run_id)
    entered = next((event for event in reversed(events) if event.type == "WAITING_INPUT_ENTERED"), None)
    if entered is None or entered.payload["reasonCode"] != "BUDGET_EXHAUSTED" or state.get("result") is not None:
        return dict(state)
    exited = next((event for event in events if event.type == "WAITING_INPUT_EXITED" and event.payload["waitId"] == entered.payload["waitId"]), None)
    replacement = next((event for event in reversed(events) if event.type == "RUN_BUDGET_POLICY_PUBLISHED" and event.sequence > entered.sequence), None)
    if exited is None and replacement is None:
        return {**state, "wait": "INPUT", "expectedActionIds": [], "resumeFromPhase": state["phase"]}
    if exited is None:
        _append_run_event(files, run_id, "WAITING_INPUT_EXITED", {
            "waitId": entered.payload["waitId"], "resolutionKind": "BUDGET_POLICY", "budgetPolicySha256": replacement.payload["budgetPolicySha256"],
        })
    elif exited.payload["resolutionKind"] in {"FITTING_UNISSUED_REPAIR","FITTING_UNISSUED_CANDIDATE_REPAIR"}:
        issuance = next((event for event in events if event.type=='ACTION_ISSUED'
            and event.payload['actionId']==exited.payload['actionId']
            and event.payload['envelopeSha256']==exited.payload['envelopeSha256']
            and entered.sequence < event.sequence < exited.sequence),None)
        if issuance is None: raise ValueError('容量恢复缺少等待期间实际发行的 Repair 证明。')
        action=_mapping(files,_action_paths(run_id,exited.payload['actionId'])['envelope'])
        if exited.payload['resolutionKind']=='FITTING_UNISSUED_CANDIDATE_REPAIR':
            from candidate_repair import patch_context
            if action['actionContractId']!='CANDIDATE_PATCH-v1':
                raise ValueError('候选修复容量恢复必须复用 CANDIDATE_PATCH。')
            view=patch_context(_mapping(files,action['packetPath']))
            plan_raw=files.read_bytes(
                f"{RUNS_ROOT}/{run_id}/candidate-repairs/plans/{view['repairPlanSha256']}.json"
            )
            plan=json.loads(plan_raw);origin=plan['origin']
            ledger=_load_action_ledger(files,run_id)
            source=ledger.attempt_records.get(origin['sourceAttemptRecordSha256'])
            source_envelope=(
                ledger.envelopes_by_sha256.get(source.envelope_sha256)
                if source is not None else None
            )
            if (sha256_bytes(plan_raw)!=view['repairPlanSha256']
                    or origin!=view['origin']
                    or origin['sourceKind']!='SEMANTIC_REVIEW'
                    or source is None
                    or source.normalized_result_sha256!=origin['reviewDecisionSha256']
                    or source_envelope is None
                    or source_envelope.value['baseCandidateSha256']!=origin['reviewCandidateSha256']):
                raise ValueError('候选修复容量恢复未绑定当前 Review 与精确计划。')
        elif action['actionContractId'] != _control_contract_id(
            files,state,action['stageKind'],'REPAIR'
        ):
            raise ValueError('容量恢复只能复用尚未发行的 Owner Repair。')
    elif exited.payload["resolutionKind"] == "FITTING_UNISSUED_RETRY":
        ledger=_load_action_ledger(files,run_id)
        record=ledger.attempt_records.get(exited.payload['failedAttemptRecordSha256'])
        issuance=next((event for event in events if event.type=='ACTION_ISSUED'
            and event.payload['actionId']==exited.payload['actionId']
            and event.payload['envelopeSha256']==exited.payload['envelopeSha256']
            and entered.sequence<event.sequence<exited.sequence),None)
        if record is None or issuance is None or record.outcome!='FAILED' or record.failure_kind not in {'INVALID_JSON','INVALID_IR'}:
            raise ValueError('IR 修复容量恢复缺少原失败或等待期间的发行证明。')
        original=ledger.envelopes_by_sha256[record.envelope_sha256].value
        retry=_mapping(files,_action_paths(run_id,exited.payload['actionId'])['envelope'])
        if (retry['logicalWorkId']!=record.logical_work_id or retry['revision']!=record.revision+1 or retry['attempt']!=1
                or retry['actionContractSha256']!=original['actionContractSha256']
                or sha256_bytes(canonical_json_bytes(retry))!=exited.payload['envelopeSha256']):
            raise ValueError('IR 修复容量恢复改变了逻辑工作、合同或累计 revision。')
        packet=_mapping(files,retry['packetPath'])
        prior=_mapping(files,original['packetPath'])
        ref=build_attempt_repair_context(record.logical_work_id,exited.payload['failedAttemptRecordSha256'],
            ledger.attempt_records,ledger.raw_outputs,envelopes_by_sha256=ledger.envelopes_by_sha256)
        prior['contextRefs']=[item for item in prior['contextRefs'] if not str(item.get('refId','')).startswith('repair-from-attempt-')]
        prior['contextRefs'].append({'refId':ref.ref_id,'canonicalContent':json.loads(ref.canonical_content),'contentSha256':sha256_bytes(ref.canonical_content)})
        if packet!=prior: raise ValueError('IR 修复容量恢复不得改变原 packet 或丢失失败输出。')
    elif exited.payload["resolutionKind"] == "FITTING_UNISSUED_PLAN":
        stage=exited.payload['stageKind']
        raw=_one_content(files,_stage_root(state,stage)+'/plans')
        if raw is None or sha256_bytes(raw)!=exited.payload['stagePlanSha256']:
            raise ValueError('规划容量恢复缺少精确冻结计划。')
        plan=json.loads(raw)
        groups=[group for group in plan['groups'] if group['groupId']==exited.payload['groupId']]
        if plan['stageKind']!=stage or len(groups)!=1:
            raise ValueError('规划容量恢复未绑定该阶段工作组。')
        issued=[event for event in events if event.type=='ACTION_ISSUED' and entered.sequence<event.sequence<exited.sequence]
        actual=[]
        for event in issued:
            envelope=_mapping(files,_action_paths(run_id,event.payload['actionId'])['envelope'])
            if sha256_bytes(canonical_json_bytes(envelope))!=event.payload['envelopeSha256']:
                raise ValueError('规划容量恢复发行摘要漂移。')
            if envelope['stageKind']==stage and envelope['groupId']==groups[0]['groupId']:
                actual.append(envelope['logicalWorkId'])
        if sorted(actual)!=sorted(groups[0]['requiredLogicalWorkIds']):
            raise ValueError('规划容量恢复缺少等待期间实际发行的完整组。')
    elif exited.payload["resolutionKind"] != "BUDGET_POLICY":
        return dict(state)
    latest_state = next((event for event in reversed(events) if event.type == "RUN_STATE_CHANGED"), None)
    if latest_state is not None and latest_state.payload["toState"] == "WAITING_INPUT":
        _append_run_event(files, run_id, "RUN_STATE_CHANGED", {"fromState": "WAITING_INPUT", "toState": state["phase"]})
    if state.get("wait") == "INPUT":
        return {**state, "wait": "NONE", "resumeFromPhase": None}
    return dict(state)


def _issued_action_events(files: ProjectFiles, run_id: str) -> dict[str, RunEvent]:
    issued: dict[str, RunEvent] = {}
    hashes: set[str] = set()
    for event in _read_run_events(files, run_id):
        if event.type != "ACTION_ISSUED":
            continue
        action_id = str(event.payload["actionId"])
        digest = str(event.payload["envelopeSha256"])
        if event.run_id != run_id or action_id in issued or digest in hashes:
            raise ProjectIOError(
                "ACTION_ISSUANCE_PROOF_INVALID",
                "",
                "Action 必须有唯一且属于本 run 的发行事件。",
            )
        issued[action_id] = event
        hashes.add(digest)
    return issued


def _load_action_ledger(files: ProjectFiles, run_id: str) -> ActionLedger:
    registry = load_schema_registry(SKILL_ROOT)
    _effective_budget_policy(files, run_id, registry=registry)
    issued = _issued_action_events(files, run_id)
    root = f"{RUNS_ROOT}/{run_id}/actions"
    try:
        directory = files.resolve(root, expect="dir")
    except ProjectIOError as error:
        if error.code == "PROJECT_PATH_MISSING" and not issued:
            return ActionLedger()
        raise
    envelopes, records, raw_outputs, normalized_results = {}, {}, {}, {}
    loaded_actions: set[str] = set()
    for path in sorted(directory.iterdir()):
        paths = _action_paths(run_id, path.name)
        value = _optional_json(files, paths["envelope"])
        event = issued.get(path.name)
        if event is None or value is None:
            for name in ("record", "raw", "normalized"):
                try:
                    files.resolve(paths[name], expect="file")
                except ProjectIOError as error:
                    if error.code != "PROJECT_PATH_MISSING":
                        raise
                else:
                    raise ProjectIOError(
                        "ACTION_ISSUANCE_PROOF_INVALID",
                        paths[name],
                        "已有结果事实缺少精确发行证明，不能作为未完成发行忽略。",
                    )
            if event is not None:
                raise ProjectIOError(
                    "ACTION_ISSUANCE_PROOF_INVALID",
                    paths["envelope"],
                    "发行事件缺少 Envelope。",
                )
            # Unissued physical content is not an authorized ledger fact.
            continue
        payload = files.read_bytes(paths["envelope"])
        digest = sha256_bytes(payload)
        if canonical_json_bytes(value) != payload:
            raise ValueError("Envelope 必须保存 canonical bytes。")
        if (
            not isinstance(value, Mapping)
            or value.get("runId") != run_id
            or value.get("actionId") != path.name
            or event.payload
            != {
                "actionId": value.get("actionId"),
                "logicalWorkId": value.get("logicalWorkId"),
                "envelopeSha256": digest,
            }
        ):
            raise ProjectIOError(
                "ACTION_ISSUANCE_PROOF_INVALID",
                paths["envelope"],
                "ACTION_ISSUED 与 Envelope 不匹配。",
            )
        envelope = ActionEnvelope(value, paths["envelope"], digest)
        if value["budgetPolicySha256"] != _budget_at_issuance(files, run_id, path.name, registry=registry):
            raise ProjectIOError(
                "ACTION_BUDGET_POLICY_MISMATCH", paths["envelope"],
                "Envelope 必须绑定其发放事件之前的 effective budget policy。",
            )
        envelopes[digest] = envelope
        loaded_actions.add(path.name)
        record_value = _optional_json(files, paths["record"])
        if record_value is None:
            continue
        record = attempt_record_from_value(record_value)
        record_payload = files.read_bytes(paths["record"])
        if canonical_json_bytes(record_value) != record_payload:
            raise ValueError("AttemptRecord 必须保存 canonical bytes。")
        records[sha256_bytes(record_payload)] = record
        if record.raw_sha256 is not None:
            raw_outputs[record.raw_sha256] = files.read_bytes(paths["raw"])
        if record.normalized_result_sha256 is not None:
            normalized_results[record.normalized_result_sha256] = files.read_bytes(
                paths["normalized"]
            )
    if set(issued) != loaded_actions:
        raise ProjectIOError(
            "ACTION_ISSUANCE_PROOF_INVALID", root, "发行事件未唯一解析到 action 文件。"
        )
    ledger = ActionLedger(envelopes, records, raw_outputs, normalized_results)
    for envelope in envelopes.values():
        packet_payload = files.read_bytes(str(envelope.value["packetPath"]))
        if sha256_bytes(packet_payload) != envelope.value["packetSha256"]:
            raise ProjectIOError(
                "ACTION_BINDING_INVALID", str(envelope.value["packetPath"]),
                "恢复时发现 Envelope packet hash 不匹配。",
            )
        policy = _published_budget_policy(files, run_id, str(envelope.value["budgetPolicySha256"]), registry=registry)
        if validate_action_envelope(
            envelope.value, packet_payload=packet_payload, skill_root=SKILL_ROOT,
            effective_budget_policy=policy, registry=registry,
        ):
            raise ProjectIOError("ACTION_ENVELOPE_INVALID", envelope.path, "发行账本的 Envelope 估值或合同绑定无效。")
        _validate_attempt_repair_packet(
            envelope.value, json.loads(packet_payload), ledger
        )
    if any(e.value['actionContractId']=='CANDIDATE_PATCH-v1' for e in envelopes.values()):
        from candidate_repair import replay_candidate_ledger, patch_context
        from owner_callbacks import candidate_owner_callbacks
        packets={e.value['packetSha256']:files.read_bytes(e.value['packetPath']) for e in envelopes.values()}
        plans={}
        for e in envelopes.values():
            if e.value['actionContractId']=='CANDIDATE_PATCH-v1':
                digest=patch_context(json.loads(packets[e.value['packetSha256']]))['repairPlanSha256']
                plans[digest]=files.read_bytes(f'{RUNS_ROOT}/{run_id}/candidate-repairs/plans/{digest}.json')
        marker=_read_active_marker(files)
        revision=files.read_bytes(marker['inputRevisionPath']) if marker else None
        inventories=_prior_inventories(files, {'runId':run_id}) if marker and any(
            json.loads(raw)['origin']['sourceActionContractId'].startswith('PRIOR_') for raw in plans.values()) else ()
        bases={};semantic_sources={}
        for raw in plans.values():
            value=json.loads(raw);origin=value['origin']
            if origin['sourceKind']=='SEMANTIC_REVIEW':
                bases[value['baseCandidateSha256']]=files.read_bytes(
                    f"{RUNS_ROOT}/{run_id}/candidate-repairs/bases/{value['baseCandidateSha256']}.json")
                semantic_sources[origin['semanticSourceSha256']]=files.read_bytes(
                    f"{RUNS_ROOT}/{run_id}/candidate-repairs/semantic-sources/{origin['semanticSourceSha256']}.json")
        ledger=replay_candidate_ledger(ledger,packets,plans,
            owner_callbacks=lambda e,p,semantic_source=None:candidate_owner_callbacks(
                e,p,inventories=inventories,revision_bytes=revision,semantic_source=semantic_source),
            events=_read_run_events(files,run_id),bases=bases,semantic_sources=semantic_sources)
    return ledger


def _validate_attempt_repair_packet(
    envelope: Mapping[str, object], packet: Mapping[str, object], ledger: ActionLedger
) -> None:
    repair_refs = [
        item
        for item in packet["contextRefs"]
        if str(item.get("refId", "")).startswith("repair-from-attempt-")
    ]
    if envelope["revision"] > 1:
        contract, contract_hash = action_contract_binding(
            SKILL_ROOT, envelope["actionContractId"]
        )
        if (
            contract["executionKind"] != "MODEL_PROVIDER"
            or contract_hash != envelope["actionContractSha256"]
        ):
            raise ValueError("只有精确绑定的 MODEL_PROVIDER 允许 revision 2 repair。")
        if len(repair_refs) != 1:
            raise ValueError("revision 2 必须绑定唯一 attempt repair context。")
        ref = repair_refs[0]
        failed = ledger.attempt_records.get(ref.get('canonicalContent', {}).get('attemptRecordSha256'))
        if failed is None or failed.revision != envelope['revision'] - 1:
            raise ValueError('repair 必须绑定紧邻前一候选的失败，不能重置累计次数。')
        content = canonical_json_bytes(ref.get("canonicalContent"))
        if (
            set(ref) != {"refId", "canonicalContent", "contentSha256"}
            or sha256_bytes(content) != ref["contentSha256"]
        ):
            raise ValueError("repair context content hash 无效。")
        validate_attempt_repair_context(
            ContextRefDescriptor(ref["refId"], content),
            str(envelope["logicalWorkId"]),
            ledger.attempt_records,
            envelopes_by_sha256=ledger.envelopes_by_sha256,
        )
    elif repair_refs:
        raise ValueError("revision 1 不允许 attempt repair context。")


def _active_seconds(ledger: ActionLedger, events: Sequence[RunEvent]) -> float:
    intervals = [
        (datetime.fromisoformat(record.timing.started_at_utc), datetime.fromisoformat(record.timing.ended_at_utc))
        for record in ledger.attempt_records.values() if record.timing.started_at_utc is not None
    ]
    intervals.extend(
        (datetime.fromisoformat(str(event.payload["startedAtUtc"])), datetime.fromisoformat(str(event.payload["endedAtUtc"])))
        for event in events if event.type == "DETERMINISTIC_STEP_FINISHED"
    )
    total = 0.0
    previous_end = None
    for start, end in sorted(intervals):
        if end < start:
            raise ProjectIOError("RUN_ACTIVE_INTERVAL_INVALID", "", "active区间结束时间不得早于开始时间。")
        if previous_end is None or start > previous_end:
            total += (end - start).total_seconds()
        elif end > previous_end:
            total += (end - previous_end).total_seconds()
        previous_end = max(previous_end, end) if previous_end is not None else end
    return total


def _model_token_totals(ledger: ActionLedger) -> tuple[int, int, int]:
    records = {record.envelope_sha256: record for record in ledger.attempt_records.values()}
    charged, unfinished, planned = 0, 0, 0
    for digest, envelope in ledger.envelopes_by_sha256.items():
        contract, _ = action_contract_binding(SKILL_ROOT, str(envelope.value["actionContractId"]))
        if contract["executionKind"] != "MODEL_PROVIDER":
            continue
        estimate = sum(int(value) for value in envelope.value["executionLimits"].values())
        planned += estimate
        record = records.get(digest)
        if record is None:
            unfinished += estimate
        else:
            charged += record.usage.input_tokens + record.usage.output_tokens
    return charged, unfinished, planned


def _guard_action_budget(
    ledger: ActionLedger, events: Sequence[RunEvent], policy: Mapping[str, object], envelopes: Sequence[ActionEnvelope]
) -> None:
    if any(envelope.sha256 not in ledger.envelopes_by_sha256 for envelope in envelopes):
        if _active_seconds(ledger, events) >= policy["maxActiveSeconds"]:
            raise StagePlanningBlocked("BUDGET_EXHAUSTED")
    new_model_actions = []
    for envelope in envelopes:
        if envelope.sha256 in ledger.envelopes_by_sha256:
            continue
        contract, _ = action_contract_binding(SKILL_ROOT, str(envelope.value["actionContractId"]))
        if contract["executionKind"] == "MODEL_PROVIDER":
            hydrate = envelope.value["executionLimits"]["maxHydrateTokens"]
            usable = usable_action_input_tokens(policy, max_hydrate_tokens=hydrate)
            if envelope.value["executionLimits"]["estimatedInputTokens"] > usable:
                raise StagePlanningBlocked("BUDGET_EXHAUSTED", {
                    "reason":"ACTION_CONTEXT_CAPACITY", "actionContractId":envelope.value["actionContractId"],
                    "estimatedInputTokens":envelope.value["executionLimits"]["estimatedInputTokens"],
                    "usableInputTokens":usable,
                    "modelContextLimitTokens":policy["modelContextLimitTokens"],
                    "outputReserveTokens":policy["outputReserveTokens"],
                    "hydrateReserveTokens":min(hydrate, policy["hydrateReserveTokens"]),
                    "safetyMarginTokens":policy["safetyMarginTokens"]})
            new_model_actions.append(envelope)
    if not new_model_actions:
        return
    charged, unfinished, _ = _model_token_totals(ledger)
    planned = sum(sum(int(value) for value in item.value["executionLimits"].values()) for item in new_model_actions)
    maximum = int(policy["maxPlannedTokens"])
    if charged >= maximum or charged + unfinished + planned > maximum:
        raise StagePlanningBlocked("BUDGET_EXHAUSTED")


def _persist_issued_action(
    files: ProjectFiles, envelope: Mapping[str, object], packet_payload: bytes
) -> None:
    run_id, action_id = str(envelope["runId"]), str(envelope["actionId"])
    paths = _action_paths(run_id, action_id)
    payload = canonical_json_bytes(envelope)
    prepared = ActionEnvelope(envelope, paths["envelope"], sha256_bytes(payload))
    ledger = _load_action_ledger(files, run_id)
    effective_budget = (
        _budget_at_issuance(files, run_id, action_id)
        if prepared.sha256 in ledger.envelopes_by_sha256
        else _effective_budget_policy(files, run_id)[0]
    )
    policy = _published_budget_policy(files, run_id, effective_budget)
    diagnostics = validate_action_envelope(
        envelope,
        packet_payload=packet_payload,
        skill_root=SKILL_ROOT,
        effective_budget_policy=policy,
    )
    if diagnostics:
        if all(item.code == "ACTION_INPUT_CAPACITY_EXCEEDED" for item in diagnostics):
            _guard_action_budget(ledger, _read_run_events(files, run_id), policy, [prepared])
        raise ValueError("Action Envelope 合同或 packet 绑定无效。")
    _validate_attempt_repair_packet(envelope, json.loads(packet_payload), ledger)
    issue_attempt(ledger, prepared, max_revisions=policy.get("maxActionRevisions", 2),
                  max_attempts=policy.get("maxExecutionAttempts", 2))
    _guard_action_budget(ledger, _read_run_events(files, run_id), policy, [prepared])
    files.publish_new(paths["packet"], packet_payload)
    files.publish_new(paths["envelope"], payload)
    events = _read_run_events(files, run_id)
    prior = [
        event
        for event in events
        if event.type == "ACTION_ISSUED" and event.payload["actionId"] == action_id
    ]
    if prior:
        if prior[0].payload["envelopeSha256"] != prepared.sha256:
            raise ValueError("Action 已签发为不同 Envelope。")
        return
    event = RunEvent(
        run_id,
        len(events) + 1,
        "ACTION_ISSUED",
        datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        {
            "actionId": action_id,
            "logicalWorkId": envelope["logicalWorkId"],
            "envelopeSha256": prepared.sha256,
        },
    )
    files.publish_new(
        f"{RUNS_ROOT}/{run_id}/events/{event.sequence:06d}.json",
        canonical_json_bytes(run_event_value(event)),
    )

    _load_action_ledger(files, run_id)


def _load_action_bundle(files: ProjectFiles, action_id: str):
    marker = _read_active_marker(files)
    if marker is None:
        raise ProjectIOError("RUN_NOT_ACTIVE", ACTIVE_RUN_PATH, "当前项目没有 active run。")
    state = _read_active_run(files, marker)
    paths = _action_paths(str(marker["runId"]), action_id)
    envelope = _mapping(files, paths["envelope"])
    packet_payload = files.read_bytes(paths["packet"])
    if (
        envelope.get("actionId") != action_id
        or envelope.get("runId") != marker["runId"]
        or validate_action_envelope(
            envelope,
            packet_payload=packet_payload,
            skill_root=SKILL_ROOT,
            effective_budget_policy=_published_budget_policy(
                files, str(marker["runId"]),
                _budget_at_issuance(files, str(marker["runId"]), action_id),
            ),
        )
    ):
        raise ProjectIOError(
            "ACTION_BINDING_INVALID",
            paths["envelope"],
            "action 文件绑定无效或已被修改。",
        )
    ledger = _load_action_ledger(files, str(marker["runId"]))
    digest = sha256_bytes(files.read_bytes(paths["envelope"]))
    if digest not in ledger.envelopes_by_sha256:
        raise ProjectIOError(
            "ACTION_ISSUANCE_PROOF_INVALID", paths["envelope"], "请求的 action 尚未签发。"
        )
    state = _recover_active_run(files, marker)
    return state, envelope, json.loads(packet_payload)


def read_provider_request(project_root: Path, action_id: str) -> bytes:
    files = ProjectFiles.open(project_root)
    marker = _read_active_marker(files)
    if marker is None:
        raise ProjectIOError("RUN_NOT_ACTIVE", ACTIVE_RUN_PATH, "当前项目没有 active run。")
    state = _read_active_run(files, marker)
    run_id = str(marker["runId"])
    ledger = _load_action_ledger(files, run_id)
    matches = [
        envelope.value for envelope in ledger.envelopes_by_sha256.values()
        if envelope.value["actionId"] == action_id
    ]
    if len(matches) != 1:
        raise ProjectIOError("ACTION_ISSUANCE_PROOF_INVALID", "", "请求的Action没有唯一发行证明。")
    envelope = matches[0]
    policy = _published_budget_policy(files, run_id, _budget_at_issuance(files, run_id, action_id))
    packet = files.read_bytes(str(envelope["packetPath"]))
    if validate_action_envelope(
        envelope, packet_payload=packet, skill_root=SKILL_ROOT, effective_budget_policy=policy,
    ):
        raise ProjectIOError("ACTION_BINDING_INVALID", "", "provider request绑定无效。")
    return action_provider_request(
        SKILL_ROOT, str(envelope["actionContractId"]), packet,
        budget_policy=policy, max_output_tokens=int(envelope["executionLimits"]["maxOutputTokens"]),
        hydration_responses=_read_hydrations(files, state, envelope, json.loads(packet)),
    )


def _hydrate_evidence(files, state, packet, requested):
    """Resolve only source/rule references present in the immutable Action packet."""
    revision_path = _read_active_marker(files)['inputRevisionPath']
    revision = _mapping(files, revision_path)
    sources = {row['sourceId']: row for row in revision['sources']}
    blocks = {row['blockId']: row for row in revision['blocks']}
    references, declared, catalog = {}, set(), None

    def visit(value):
        nonlocal catalog
        if isinstance(value, list):
            for row in value: visit(row)
        elif isinstance(value, dict):
            declared.update(value.get('evidenceIds', []))
            if value.get('kind') == 'TASK_CATALOG': catalog = value
            ref = value.get('sourceRef')
            if isinstance(ref, dict) and 'blockId' in ref:
                references[value.get('evidenceId', ref['blockId'])] = ref
            if {'sourceId', 'blockId', 'sha256', 'locator'}.issubset(value):
                references[value['blockId']] = {key: value[key] for key in ('sourceId', 'blockId', 'sha256', 'locator')}
            for row in value.values(): visit(row)
    visit(packet)
    prior = {}
    if any(source['role'] == 'PRIOR_SOW' for source in sources.values()):
        from prior_state import hydrate_prior_evidence
        prior = hydrate_prior_evidence(packet, requested, inventories=_prior_inventories(files, state),
                                       input_revision_bytes=files.read_bytes(revision_path))
    for key in declared.intersection(blocks):
        block = blocks[key]
        references.setdefault(key, {'sourceId': block['sourceId'], 'blockId': key,
            'sha256': block['contentSha256'], 'locator': block['locator']})
    result = {}
    for key in requested:
        if key in prior:
            content = prior[key]
        elif key.startswith('task-rule:') and catalog is not None:
            selected = key.removeprefix('task-rule:')
            rows = {row['workTypeId']: row for row in catalog['rows']}
            if selected not in rows: continue
            from task_standard_catalog import decision_catalog, hydrate as hydrate_rules
            template = load_task_standard_catalog(_revision_template_path(files, revision_path))
            if (template.template_sha256 != catalog['templateSha256']
                    or template.task_catalog_semantic_sha256 != catalog['catalogSemanticSha256']):
                raise ValueError('hydrate 模板与冻结 Task catalog 不一致。')
            selected_rows = hydrate_rules(template, [selected], rows[selected]['name']).rows
            rules = {row['workTypeId']: row for row in decision_catalog(template)}
            content = {'kind': 'TASK_RULES', 'templateSha256': catalog['templateSha256'],
                'catalogSemanticSha256': catalog['catalogSemanticSha256'],
                'rows': [rules[row['工作类型ID']] for row in selected_rows]}
        elif key in references:
            ref = references[key]
            source = sources.get(ref['sourceId'])
            block = blocks.get(ref['blockId'])
            if source is None or source['status'] == 'REFERENCE_ONLY': continue
            if block is not None:
                if (block['sourceId'], block['contentSha256'], block['locator']) != (ref['sourceId'], ref['sha256'], ref['locator']):
                    raise ValueError('hydrate SourceRef 未绑定本轮原文。')
                raw = _mapping(files, str(Path(revision_path).parent/'blocks'/f"{ref['blockId']}.json"))['content'].encode('utf-8')
            elif source['role'] == 'DEMO' and ref['locator'] == 'file:' + source['path']:
                raw = files.read_bytes(source['path'])
            else: continue
            if sha256_bytes(raw) != ref['sha256']: raise ValueError('hydrate 原文 hash 漂移。')
            content = {'kind': 'SOURCE_EVIDENCE', 'sourceRef': ref, 'content': raw.decode('utf-8')}
        else: continue
        result[key] = {'refId': key, 'canonicalContent': content,
            'contentSha256': sha256_bytes(canonical_json_bytes(content))}
    return result


def _read_hydrations(files, state, envelope, packet):
    path = _action_paths(envelope['runId'], envelope['actionId'])['hydrations']
    try:
        directory = files.resolve(path, expect='dir')
    except ProjectIOError as error:
        if error.code == 'PROJECT_PATH_MISSING': return []
        raise
    responses, seen = [], set()
    for index, file in enumerate(sorted(directory.glob('*.json')), 1):
        response = _mapping(files, f'{path}/{file.name}')
        ids = response.get('evidenceIds', [])
        allowed = _hydrate_evidence(files, state, packet, ids)
        if (index > 2 or file.name != f'{index:02d}.json' or not ids or seen.intersection(ids)
                or len(set(ids)) != len(ids) or set(ids) != set(allowed)
                or response != {'outcome': 'HYDRATED', 'actionId': envelope['actionId'],
                    'evidenceIds': ids, 'evidence': [allowed[key] for key in ids], 'diagnostics': []}):
            raise ValueError('hydration response 与已签发 packet 不匹配。')
        seen.update(ids)
        responses.append(response)
    return responses


def hydrate(
    project_root: Path, action_id: str, evidence_ids: Sequence[str]
) -> dict[str, object]:
    files = ProjectFiles.open(project_root)
    try:
        state, envelope, packet = _load_action_bundle(files, action_id)
        if action_id not in state.get("expectedActionIds", []):
            return _blocked(
                "ACTION_NOT_EXPECTED", "该 action 不是当前等待的动作。", "/actionId"
            )
        if not evidence_ids:
            return _blocked(
                "ACTION_HYDRATION_EMPTY", "hydrate 必须请求至少一个 evidence ID。"
            )
        requested = list(dict.fromkeys(evidence_ids))
        catalog = _hydrate_evidence(files, state, packet, requested)
        if any(item not in catalog for item in requested):
            return _blocked(
                "ACTION_EVIDENCE_NOT_ALLOWED",
                "hydrate 请求包含 allowlist 外的 evidence ID。",
                "/evidenceIds",
            )
        paths = _action_paths(str(envelope["runId"]), action_id)
        responses = _read_hydrations(files, state, envelope, packet)
        previous = {
            item["refId"] for response in responses for item in response["evidence"]
        }
        new_ids = [item for item in requested if item not in previous]
        if not new_ids:
            return {
                "outcome": "REUSED",
                "actionId": action_id,
                "evidenceIds": [],
                "evidence": [],
                "diagnostics": [],
            }
        if len(responses) >= 2:
            return _blocked(
                "ACTION_HYDRATION_LIMIT_EXCEEDED",
                "该 action 已达到 hydration 轮数上限。",
                "/hydrations",
            )
        evidence = [dict(catalog[item]) for item in new_ids]
        response = {
            "outcome": "HYDRATED",
            "actionId": action_id,
            "evidenceIds": new_ids,
            "evidence": evidence,
            "diagnostics": [],
        }
        payload = canonical_json_bytes(response)
        from provider_adapter import estimate_canonical_transport, estimate_provider_request

        policy = _published_budget_policy(files, str(envelope["runId"]), str(envelope["budgetPolicySha256"]))
        total_tokens = sum(
            estimate_canonical_transport(str(policy["modelProfileId"]), str(policy["estimatorVersion"]), canonical_json_bytes(item))
            for item in [*responses, response]
        )
        request = action_provider_request(SKILL_ROOT, envelope['actionContractId'], canonical_json_bytes(packet),
            budget_policy=policy, max_output_tokens=envelope['executionLimits']['maxOutputTokens'],
            hydration_responses=[*responses, response])
        request_tokens = estimate_provider_request(policy['modelProfileId'], policy['estimatorVersion'], request)
        if (total_tokens > envelope["executionLimits"]["maxHydrateTokens"]
                or request_tokens + envelope['executionLimits']['maxOutputTokens'] + policy['safetyMarginTokens'] > policy['modelContextLimitTokens']):
            return _blocked(
                "ACTION_HYDRATION_LIMIT_EXCEEDED",
                "该 action 已达到 hydration token 上限。",
                "/executionLimits/maxHydrateTokens",
            )
        if _active_seconds(_load_action_ledger(files, state['runId']), _read_run_events(files, state['runId'])) >= _effective_budget_policy(files, state['runId'])[1]['maxActiveSeconds']:
            return _wait_for_budget(files)
        files.publish_new(
            f"{paths['hydrations']}/{len(responses) + 1:02d}.json", payload
        )
        return response
    except ProjectIOError as error:
        return _blocked(error.code, str(error), error.relative_path)
    except (ValueError, KeyError, TypeError) as error:
        return _blocked("ACTION_BINDING_INVALID", str(error), "/hydrations")


def _is_non_negative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0

class CandidateRepairRoute(ValueError):
    def __init__(self, failure_kind, reason_code):
        self.failure_kind=failure_kind
        self.reason_code=reason_code
        super().__init__(reason_code)




def _materialize_action_retry(
    files: ProjectFiles,
    action_id: str,
    envelope: Mapping[str, object],
    failed_record: Mapping[str, object],
) -> Mapping[str, object]:
    run_id = str(envelope["runId"])
    ledger = _load_action_ledger(files, run_id)
    if failed_record['failureKind'] in {'INVALID_JSON','INVALID_IR'}:
        try:
            patch = _issue_candidate_patch(files, envelope, failed_record, ledger)
        except CandidateRepairRoute as routed:
            if routed.failure_kind!='EXECUTION':
                raise
            failed_record={**failed_record,'failureKind':'EXECUTION'}
        else:
            if patch is not None:return patch
    paths = _action_paths(run_id, action_id)
    revision, attempt = int(envelope["revision"]), int(envelope["attempt"])
    packet = json.loads(files.read_bytes(paths["packet"]))
    policy = _effective_budget_policy(files, run_id)[1]
    if ((failed_record['failureKind'] in {'INVALID_JSON', 'INVALID_IR'} and revision >= policy.get('maxActionRevisions', 2))
            or (failed_record['failureKind'] == 'EXECUTION' and attempt >= policy.get('maxExecutionAttempts', 2))):
        raise AttemptLimitReached('当前候选/执行次数已用尽；显式增加对应有限预算后接续。')
    if failed_record["failureKind"] in {"INVALID_JSON", "INVALID_IR"}:
        revision, attempt = revision + 1, 1
        digest = sha256_bytes(canonical_json_bytes(failed_record))
        ref = build_attempt_repair_context(
            str(envelope["logicalWorkId"]),
            digest,
            ledger.attempt_records,
            ledger.raw_outputs,
            envelopes_by_sha256=ledger.envelopes_by_sha256,
        )
        packet["contextRefs"] = [
            *(item for item in packet["contextRefs"] if not str(item.get('refId', '')).startswith('repair-from-attempt-')),
            {
                "refId": ref.ref_id,
                "canonicalContent": json.loads(ref.canonical_content),
                "contentSha256": sha256_bytes(ref.canonical_content),
            },
        ]
    else:
        attempt += 1
    identity = {
        "runId": run_id,
        "logicalWorkId": envelope["logicalWorkId"],
        "revision": revision,
        "attempt": attempt,
    }
    retry_id = "action-" + sha256_bytes(canonical_json_bytes(identity))[:12]
    retry_paths = _action_paths(run_id, retry_id)
    packet_payload = canonical_json_bytes(packet)
    limits = {
        **envelope["executionLimits"],
        "estimatedInputTokens": estimate_action_input_tokens(
            SKILL_ROOT, str(envelope["actionContractId"]), packet_payload,
            budget_policy=_effective_budget_policy(files, run_id)[1],
            max_output_tokens=int(envelope["executionLimits"]["maxOutputTokens"]),
        ),
    }
    retry = {
        **envelope,
        "budgetPolicySha256": _effective_budget_policy(files, run_id)[0],
        "revision": revision,
        "attempt": attempt,
        "actionId": retry_id,
        "packetPath": retry_paths["packet"],
        "packetSha256": sha256_bytes(packet_payload),
        "resultPath": retry_paths["output"],
        "executionLimits": limits,
    }
    _persist_issued_action(files, retry, packet_payload)
    return retry


def submit(
    project_root: Path, action_id: str, completion: AttemptCompletion
) -> dict[str, object]:
    files = ProjectFiles.open(project_root)
    try:
        if not isinstance(completion, AttemptCompletion):
            raise ValueError("submit 必须接收 AttemptCompletion。")
        state, value, packet = _load_action_bundle(files, action_id)
        run_id = str(value["runId"])
        paths = _action_paths(run_id, action_id)
        ledger = _load_action_ledger(files, run_id)
        digest = sha256_bytes(files.read_bytes(paths["envelope"]))
        envelope = ledger.envelopes_by_sha256[digest]
        validator = None
        normalizer = None
        if value["actionContractId"] in {"PROTOTYPE_SCENARIO-v1", "PROTOTYPE_BROWSER-v1", "PROTOTYPE_ANALYZE-v1"}:
            from prototype_analysis import validate_bound_prototype_context, validate_bound_prototype_result

            payload = packet["workItems"][0]["payload"]
            validate_bound_prototype_context(payload["identity"]["actionKind"], payload)

            def validator(normalized_result: bytes) -> None:
                validate_bound_prototype_result(payload["identity"]["actionKind"], payload, normalized_result, packet=packet)

        elif value['actionContractId']=='CANDIDATE_PATCH-v1':
            normalizer=lambda raw:_normalize_candidate_patch(files,state,value,packet,raw,ledger)
        elif value['actionContractId'] in {'SOURCE_SCAN-v1','SOURCE_AUDIT-v1','SCOPE_SYNTHESIS-v1','SCOPE_PROPOSAL-v1','SCOPE_JOIN-v1'}:
            from scope_compiler import validate_bound_scope_context, validate_bound_scope_result
            kind = value['actionContractId'][:-3]
            validate_bound_scope_context(kind, packet)
            validator = lambda normalized: validate_bound_scope_result(kind, packet, normalized)
        elif value['actionContractId'] in {'PRIOR_ANALYZE-v1','PRIOR_CONSOLIDATE-v1','PRIOR_ANALYZE-v2','PRIOR_ANALYZE-v3','PRIOR_CONSOLIDATE-v2'}:
            from prior_state import validate_bound_prior_context, validate_bound_prior_result
            kind = value['actionContractId'][:-3]
            inventories = _prior_inventories(files, state)
            revision = files.read_bytes(_read_active_marker(files)['inputRevisionPath'])
            validate_bound_prior_context(kind, packet, inventories=inventories, input_revision_bytes=revision)
            validator = lambda normalized: validate_bound_prior_result(kind, packet, normalized, inventories=inventories, input_revision_bytes=revision)
        elif value['actionContractId'] == 'STORY_AC-v1':
            from delivery_compiler import validate_bound_story_context, validate_bound_story_result
            validate_bound_story_context(packet)
            validator = lambda normalized: validate_bound_story_result(packet, normalized)
        elif value['actionContractId'] in {'TASK-v1','TASK-v2'}:
            from task_compiler import validate_bound_task_context, validate_bound_task_result
            validate_bound_task_context(packet)
            validator = lambda normalized: validate_bound_task_result(packet, normalized)
        elif value['actionContractId'] == 'ARTIFACT_VISUAL_REVIEW-v1':
            from package_renderer import validate_visual_result
            body = packet['workItems'][0]['payload']
            for ref in [body['workbook'], *body['renders']]:
                if sha256_bytes(files.read_bytes(ref['path'])) != ref['sha256']:
                    raise ValueError('Visual Review frozen file hash drift')
            validator = lambda normalized: validate_visual_result(packet,normalized)
        elif value['actionContractId'] in {'SOURCE_SCOPE-v1','STORY_DESIGN-v1','TASK_ESTIMATION-v1'}:
            from final_review import validate_bound_review_result
            validator=lambda normalized:validate_bound_review_result(packet,normalized)
        elif value['actionContractId'] in {'SCOPE_REPAIR-v1','STORY_AC_REPAIR-v1','TASK_REPAIR-v1','TASK_REPAIR-v2'}:
            from final_review import replace_owner_decisions, owner_resolution
            from contracts import InvalidActionResult
            body=packet['workItems'][0]['payload'];stage=body['stageKind'];owner_packet=body['ownerPacket']
            if stage=='SCOPE':
                from scope_compiler import validate_bound_scope_context,validate_bound_scope_result
                validate_bound_scope_context('SCOPE_SYNTHESIS',owner_packet)
                bound=lambda raw:validate_bound_scope_result('SCOPE_SYNTHESIS',owner_packet,raw)
            elif stage=='STORY_AC':
                from delivery_compiler import validate_bound_story_context,validate_bound_story_result
                validate_bound_story_context(owner_packet);bound=lambda raw:validate_bound_story_result(owner_packet,raw)
            else:
                from task_compiler import validate_bound_task_context,validate_bound_task_result,expand_task_repair_packet
                owner_packet=expand_task_repair_packet(owner_packet)
                validate_bound_task_context(owner_packet);bound=lambda raw:validate_bound_task_result(owner_packet,raw)
            def validator(normalized):
                try:
                    replacement=json.loads(normalized)
                    if stage=='TASK':
                        from task_compiler import verify_task_replacement_ac_scope
                        verify_task_replacement_ac_scope(body['ownerIR'],body['reviewDecision'],replacement,owner_resolution(body))
                    merged=replace_owner_decisions(stage,body['ownerIR'],body['reviewDecision'],replacement,owner_resolution(body))
                except ValueError as error: raise InvalidActionResult(str(error)) from error
                bound(canonical_json_bytes(merged))
        ledger, record = finish_attempt(ledger, envelope, completion, bound_result_validator=validator,
                                        packet_payload=canonical_json_bytes(packet), bound_result_normalizer=normalizer)
        record_value = attempt_record_value(record)
        if record.raw_sha256 is not None:
            files.publish_new(paths["raw"], ledger.raw_outputs[record.raw_sha256])
        if record.normalized_result_sha256 is not None:
            files.publish_new(
                paths["normalized"],
                ledger.normalized_results[record.normalized_result_sha256],
            )
        files.publish_new(paths["record"], canonical_json_bytes(record_value))
        marker = _read_active_marker(files)
        if marker is not None:
            _recover_active_run(files, marker)
        return {"outcome": "RECORDED", "record": record_value, "diagnostics": []}
    except ProjectIOError as error:
        return _blocked(error.code, str(error), error.relative_path)
    except (ValueError, KeyError, TypeError) as error:
        return _blocked("ACTION_COMPLETION_INVALID", str(error), "/completion")


def _retry_action(files: ProjectFiles, action_id: str) -> dict[str, object]:
    state, envelope, _ = _load_action_bundle(files, action_id)
    ledger = _load_action_ledger(files, str(envelope["runId"]))
    latest = max(
        (
            item
            for item in ledger.envelopes_by_sha256.values()
            if item.value["logicalWorkId"] == envelope["logicalWorkId"]
        ),
        key=lambda item: (item.value["revision"], item.value["attempt"]),
    )
    if latest.value["actionId"] != action_id:
        return dict(latest.value)
    return _result(
        "SYSTEM_FAILED",
        "Action 已停止重试。",
        diagnostics=(
            _diagnostic("BUDGET_EXCEEDED", "Action 已达到重试限额或安全停止条件。"),
        ),
    )


def status(project_root: Path) -> dict[str, object]:
    files = ProjectFiles.open(project_root)
    try:
        marker = _read_active_marker(files)
        if marker is None:
            current = load_current(files)
            if current is None:
                return _blocked("RUN_NOT_ACTIVE", "当前项目没有 active run 或有效 generation。")
            next_action = {
                "contract": "ai-sow-next-action-v1",
                "kind": "DONE",
                "result": "PUBLISHED",
                "generationManifestPath": current.manifest_path,
            }
            if validate_contract(next_action, "action.schema.json", NEXT_SCHEMA_REGISTRY):
                raise ProjectIOError(
                    "NEXT_ACTION_INVALID", "", "生成的 DONE action 合同无效。"
                )
            return {
                "outcome": "DONE",
                "nextAction": next_action,
                "diagnostics": [],
            }
        recovered = _read_active_run(files, marker)
        _verify_completed_stages(files, recovered)
        response = _attempt_stop_response(files, recovered) or _active_result(recovered)
        ledger = _load_action_ledger(files, str(marker["runId"]))
        charged, _, planned = _model_token_totals(ledger)
        return {**response, "budgetVarianceTokens": charged - planned, "activeSeconds": _active_seconds(ledger, _read_run_events(files, str(marker["runId"])))}
    except ProjectIOError as error:
        return _blocked(error.code, str(error), error.relative_path)


def run_mode(
    project_root: Path,
    mode: str,
    *,
    request: str | None = None,
    budget_policy: str | None = None,
    action_id: str | None = None,
    result: str | None = None,
    execution: str | None = None,
    evidence_ids: Sequence[str] = (),
    artifact_manifest_sha256: str | None = None,
    decision: str | None = None,
) -> dict[str, object]:
    try:
        supplied = {
            "request": request,
            "budget_policy": budget_policy,
            "action_id": action_id,
            "result": result,
            "execution": execution,
            "artifact_manifest_sha256": artifact_manifest_sha256,
            "decision": decision,
        }
        if mode == "start":
            if request is None or budget_policy is None or any(
                value is not None
                for name, value in supplied.items()
                if name not in {"request", "budget_policy"}
            ) or evidence_ids:
                return _blocked("CLI_ARGUMENTS_INVALID", "start 必须提供 --request 和 --budget-policy。")
            return _drive_public_active(project_root, start(project_root, request, budget_policy))
        if mode == "resume":
            if any(
                value is not None
                for name, value in supplied.items()
                if name not in {"budget_policy","decision"}
            ) or evidence_ids or budget_policy is not None and decision is not None:
                return _blocked(
                    "CLI_ARGUMENTS_INVALID", "resume 可选接受 --budget-policy 或绑定当前 Review 的 --decision 实施澄清。"
                )
            return _drive_public_active(project_root, resume(project_root, budget_policy, decision))
        if mode == "hydrate":
            if action_id is None or any(
                value is not None
                for name, value in supplied.items()
                if name != "action_id"
            ):
                return _blocked(
                    "CLI_ARGUMENTS_INVALID",
                    "hydrate 必须提供 --action-id，且只可附加 --evidence-id。",
                )
            return hydrate(project_root, action_id, evidence_ids)
        if mode == "submit":
            if (
                action_id is None
                or execution is None
                or request is not None
                or budget_policy is not None
                or artifact_manifest_sha256 is not None
                or decision is not None
                or evidence_ids
            ):
                return _blocked(
                    "CLI_ARGUMENTS_INVALID",
                    "submit 必须提供 --action-id 和 --execution；成功执行还必须提供 --result。",
                )
            files = ProjectFiles.open(project_root)
            execution_path = _managed_request_path(files, execution)
            value = files.read_json(execution_path)
            if not isinstance(value, Mapping) or set(value) != {
                "failureKind",
                "diagnostic",
                "usage",
                "timing",
            }:
                return _blocked(
                    "ACTION_COMPLETION_INVALID",
                    "execution 文件必须是唯一 Completion metadata。",
                    execution_path,
                )
            usage, timing, diagnostic = (
                value["usage"],
                value["timing"],
                value["diagnostic"],
            )
            if (
                not isinstance(usage, Mapping)
                or set(usage)
                != {
                    "provenance",
                    "inputTokens",
                    "outputTokens",
                    "cachedInputTokens",
                    "reasoningTokens",
                }
                or not isinstance(timing, Mapping)
                or set(timing) != {"startedAtUtc", "endedAtUtc"}
                or (
                    diagnostic is not None
                    and (
                        not isinstance(diagnostic, Mapping)
                        or set(diagnostic) not in ({"code", "path", "subjectIds"}, {"code", "path", "subjectIds", "findings"})
                    )
                )
            ):
                return _blocked(
                    "ACTION_COMPLETION_INVALID",
                    "Completion usage/timing/diagnostic 字段无效。",
                    execution_path,
                )
            raw = None
            if result is not None:
                marker = _read_active_marker(files)
                if marker is None:
                    return _blocked("RUN_NOT_ACTIVE", "当前项目没有 active run。")
                envelope = _mapping(
                    files, _action_paths(str(marker["runId"]), action_id)["envelope"]
                )
                if result != envelope["resultPath"]:
                    return _blocked(
                        "ACTION_RESULT_PATH_MISMATCH",
                        "submit 只能读取 Envelope 锁定的 result path。",
                        "/result",
                    )
                raw = files.read_bytes(result)
            completion = AttemptCompletion(
                raw,
                value["failureKind"],
                (
                    None
                    if diagnostic is None
                    else diagnostic_from_value(diagnostic)
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
            submitted = submit(project_root, action_id, completion)
            if submitted.get("outcome") != "RECORDED":
                return submitted
            return _drive_public_active(project_root, status(project_root))
        if mode == "approve":
            if (
                artifact_manifest_sha256 is None
                or request is not None
                or budget_policy is not None
                or action_id is not None
                or result is not None
                or execution is not None
                or evidence_ids
            ):
                return _blocked(
                    "CLI_ARGUMENTS_INVALID",
                    "approve 必须提供 --artifact-manifest-sha256，且只可附加 --decision。",
                )
            return approve(
                project_root,
                artifact_manifest_sha256,
                decision_path=decision,
            )
        if mode == "abandon":
            if any(value is not None for value in supplied.values()) or evidence_ids:
                return _blocked("CLI_ARGUMENTS_INVALID", "abandon 不接受附加参数。")
            return abandon(project_root)
        if mode == "status":
            if any(value is not None for value in supplied.values()) or evidence_ids:
                return _blocked("CLI_ARGUMENTS_INVALID", "status 不接受工件参数。")
            return status(project_root)
        return _blocked("CLI_MODE_INVALID", "不支持的运行模式。")
    except DeterministicStepFailure as error:
        files = ProjectFiles.open(project_root)
        if error.attempt >= error.limit:
            return _wait_for_budget(files)
        return {**_blocked('DETERMINISTIC_STEP_FAILED', '步骤失败已保存；按定位修复后 resume，仅接续未完成步骤。',
            error.diagnostic.path), 'nextStep': {'mode':'resume', 'stageKind':error.stage,
                'semanticRevision':error.revision, 'stepKind':error.kind,
                'attempt':error.attempt, 'remainingAttempts':error.limit-error.attempt,
                'diagnostic':diagnostic_value(error.diagnostic)}}
    except StagePlanningBlocked as error:
        response = _wait_for_budget(ProjectFiles.open(project_root))
        if error.details:
            response['diagnostics'][0]['details'].update(error.details)
            response['diagnostics'][0]['message']='单次请求超过上下文容量；需无损减少未发行输入或核实并增加模型容量，增加总 token 预算无效。'
        return response
    except ProjectIOError as error:
        return _blocked(error.code, str(error), error.relative_path)
    except (OSError, ValueError, KeyError, TypeError):
        return _blocked("ORCHESTRATION_FAILED", "生成编排未能安全完成。")


class _JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def _parser() -> argparse.ArgumentParser:
    parser = _JsonArgumentParser(add_help=True, exit_on_error=False)
    parser.add_argument("--project-root", required=True)
    parser.add_argument(
        "--mode",
        required=True,
        choices=(
            "start",
            "submit",
            "hydrate",
            "resume",
            "approve",
            "abandon",
            "status",
        ),
    )
    parser.add_argument("--request")
    parser.add_argument("--budget-policy")
    parser.add_argument("--action-id")
    parser.add_argument("--result")
    parser.add_argument("--execution")
    parser.add_argument("--evidence-id", action="append", default=[])
    parser.add_argument("--artifact-manifest-sha256")
    parser.add_argument("--decision")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        arguments = _parser().parse_args(argv)
    except (argparse.ArgumentError, ValueError):
        result = _blocked("CLI_ARGUMENTS_INVALID", "命令行参数无效。")
        sys.stdout.buffer.write(canonical_json_bytes(result))
        return 2
    root = Path(arguments.project_root)
    if not root.is_absolute():
        result = _blocked(
            "PROJECT_ROOT_NOT_ABSOLUTE", "--project-root 必须是绝对路径。"
        )
        exit_code = 2
    else:
        result = run_mode(
            root,
            arguments.mode,
            request=arguments.request,
            budget_policy=arguments.budget_policy,
            action_id=arguments.action_id,
            result=arguments.result,
            execution=arguments.execution,
            evidence_ids=arguments.evidence_id,
            artifact_manifest_sha256=arguments.artifact_manifest_sha256,
            decision=arguments.decision,
        )
        exit_code = 0 if result["outcome"] != "BLOCKED" else 2
    sys.stdout.buffer.write(canonical_json_bytes(result))
    return exit_code




def _candidate_callbacks(files, envelope, packet, semantic_source=None):
    from owner_callbacks import candidate_owner_callbacks
    inventories=();revision=None
    if envelope['actionContractId'].startswith('PRIOR_'):
        inventories=_prior_inventories(files,{'runId':envelope['runId']})
        revision=files.read_bytes(_read_active_marker(files)['inputRevisionPath'])
    return candidate_owner_callbacks(envelope,packet,inventories=inventories,
        revision_bytes=revision,semantic_source=semantic_source)


def _candidate_source(files, envelope, ledger):
    from candidate_repair import patch_context
    if envelope['actionContractId']=='CANDIDATE_PATCH-v1':
        view=patch_context(json.loads(files.read_bytes(envelope['packetPath'])))
        plan=json.loads(files.read_bytes(f"{RUNS_ROOT}/{envelope['runId']}/candidate-repairs/plans/{view['repairPlanSha256']}.json"))
        digest=plan['origin']['sourceAttemptRecordSha256']
    else:
        matches=[(d,r) for d,r in ledger.attempt_records.items() if r.envelope_sha256==sha256_bytes(canonical_json_bytes(envelope))]
        if len(matches)!=1:return None
        digest=matches[0][0]
    record=ledger.attempt_records[digest];source=ledger.envelopes_by_sha256[record.envelope_sha256].value
    return digest,record,source,json.loads(files.read_bytes(source['packetPath']))


def _patch_request_packet(plan_raw, group_id, source_packet, *, evidence_values):
    from candidate_repair import _at
    plan=json.loads(plan_raw);group=next(g for g in plan['groups'] if g['groupId']==group_id)
    issues=[i for i in plan['diagnostic']['issues'] if i['issueId'] in group['issueIds']]
    view={'contract':'ai-sow-candidate-patch-context-v1','repairPlanSha256':sha256_bytes(plan_raw),
          'baseCandidateSha256':plan['baseCandidateSha256'],'origin':plan['origin'],
          'role':'REVIEWER' if plan['diagnostic']['owner']=='REVIEWER' else 'AUTHOR',
          'group':group,'issues':issues,'evidence':evidence_values}
    # Caller fills only Owner-selected field slices; full bases never enter packet.
    return {'workItems':[{'workItemId':group_id,'payload':{'groupId':group_id}}],
            'contextRefs':[{'refId':'candidate-repair-plan-v1','canonicalContent':view,
                            'contentSha256':sha256_bytes(canonical_json_bytes(view))}]}


def _issue_candidate_patch(files, envelope, failed_record, ledger):
    from candidate_repair import _read_candidate, _at, patch_context, repair_progress_sha256
    from contracts import InvalidActionResult
    supported={'SOURCE_SCAN','SOURCE_AUDIT','SCOPE_SYNTHESIS','SCOPE_PROPOSAL','SCOPE_JOIN','PRIOR_ANALYZE','PRIOR_CONSOLIDATE',
               'STORY_AC','TASK','PROTOTYPE_SCENARIO','PROTOTYPE_ANALYZE','SOURCE_SCOPE','STORY_DESIGN','TASK_ESTIMATION','CANDIDATE_PATCH'}
    if envelope['actionContractId'].rpartition('-v')[0] not in supported:return None
    source_info=_candidate_source(files,envelope,ledger)
    if source_info is None:return None
    source_digest,source_record,source,packet=source_info
    last_plan=None
    if envelope['actionContractId']=='CANDIDATE_PATCH-v1':
        last_view=patch_context(json.loads(files.read_bytes(envelope['packetPath'])))
        last_plan=json.loads(files.read_bytes(
            f"{RUNS_ROOT}/{source['runId']}/candidate-repairs/plans/{last_view['repairPlanSha256']}.json"))
    source_kind=last_plan['origin']['sourceKind'] if last_plan is not None else 'AUTHOR_FAILURE'
    lineage=last_plan['origin']['originLogicalWorkId'] if last_plan is not None else source['logicalWorkId']
    semantic_source=None
    if source_kind=='SEMANTIC_REVIEW':
        semantic_sha=last_plan['origin']['semanticSourceSha256']
        semantic_path=f"{RUNS_ROOT}/{source['runId']}/candidate-repairs/semantic-sources/{semantic_sha}.json"
        semantic_source=files.read_json(semantic_path)
        if sha256_bytes(canonical_json_bytes(semantic_source))!=semantic_sha:
            raise ValueError('语义来源描述符 hash 漂移。')
        initial=files.read_bytes(
            f"{RUNS_ROOT}/{source['runId']}/candidate-repairs/bases/{last_plan['baseCandidateSha256']}.json")
    else:
        if source_record.raw_sha256 is None:return None
        initial=ledger.raw_outputs[source_record.raw_sha256]
    base,chain,old_index=ledger.repair_heads.get(lineage,(initial,[],None))
    try:_read_candidate(base)
    except InvalidActionResult:return None  # Existing bounded format recovery only.
    policy_hash,policy=_effective_budget_policy(files,source['runId'])
    rounds=[json.loads(item['plan'])['origin']['repairRound'] for item in chain]
    round_number=max([source['revision']+1,*rounds])
    if last_plan is not None:
        round_number=max(round_number,last_plan['origin']['repairRound']+1)
    if round_number>policy.get('maxActionRevisions',2):
        raise AttemptLimitReached('当前逻辑工作的累计内容轮数已达上限。')
    origin={'runId':source['runId'],'inputRevisionSha256':source['inputRevisionSha256'],
            'originLogicalWorkId':lineage,'sourceKind':source_kind,
            'sourceActionContractId':source['actionContractId'],'sourceAttemptRecordSha256':source_digest,
            'stageKind':source['stageKind'],'repairRound':round_number,'budgetPolicySha256':policy_hash}
    if source_kind=='SEMANTIC_REVIEW':
        for key in ('reviewDecisionSha256','reviewCandidateSha256','semanticSourceSha256'):
            origin[key]=last_plan['origin'][key]
    if chain:
        origin['previousReceiptSha256']=sha256_bytes(chain[-1]['receipt'])
    diagnose,make_plan,_=_candidate_callbacks(files,source,packet,semantic_source)
    report=diagnose(base,origin)
    if old_index is not None:report['objectIndex']=old_index
    if not report['issues']:return None
    classes={issue['repairClass'] for issue in report['issues']}
    for repair_class,failure_kind in (('OWNER_BUG','OWNER_BUG'),('CONTRACT_GAP','CONTRACT_GAP'),('INPUT_REQUIRED','INPUT_REQUIRED')):
        if repair_class in classes:
            issue=next(item for item in report['issues'] if item['repairClass']==repair_class)
            raise CandidateRepairRoute(failure_kind,issue['code'])
    if classes=={'EXECUTION'}:
        raise CandidateRepairRoute('EXECUTION',report['issues'][0]['code'])
    if not classes<={'DATA','FORMAT','EVIDENCE'}:
        raise CandidateRepairRoute('CONTRACT_GAP','CANDIDATE_REPAIR_CLASS_UNSUPPORTED')
    try:plan_raw=make_plan(base,report,origin)
    except InvalidActionResult as error:
        raise CandidateRepairRoute('CONTRACT_GAP','CANDIDATE_REPAIR_GRANT_UNAVAILABLE') from error
    plan=json.loads(plan_raw);group=plan['groups'][0]
    values=[];index={row['objectId']:row for row in plan['objectIndex']};candidate=json.loads(base)
    for read in group['readSet']:
        row=_at(candidate,index[read['objectId']]['path'])
        values.append({'objectId':read['objectId'],'fields':row if not read['fields'] else {f:row[f] for f in read['fields'] if f in row}})
    if semantic_source is not None:
        values.append({'kind':'SEMANTIC_REVIEW_FINDINGS','value':semantic_source['reviewDecision']['findings']})
    elif source['actionContractId'].startswith('PRIOR_'):
        from prior_state import _inventory_evidence,_verified_revision
        revision=files.read_bytes(_read_active_marker(files)['inputRevisionPath'])
        evidence=_inventory_evidence(_prior_inventories(files,{'runId':source['runId']}),_verified_revision(revision))
        needed={(s['sourceId'],s['evidenceId']) for i in report['issues'] if i['issueId'] in group['issueIds'] for s in i['subjects'] if 'sourceId' in s and 'evidenceId' in s}
        values.extend({'kind':'PRIOR_EVIDENCE','value':evidence[key]} for key in sorted(needed) if key in evidence)
    else:
        import scope_compiler,delivery_compiler,task_compiler,prototype_analysis
        kind=source['actionContractId'].rpartition('-v')[0]
        owner=(task_compiler if kind=='TASK' else delivery_compiler if kind=='STORY_AC'
            else prototype_analysis if kind.startswith('PROTOTYPE_') else scope_compiler)
        if report['owner']=='REVIEWER':
            values.extend({'kind':'REVIEW_OBLIGATIONS','value':item} for item in packet['workItems'])
        else:values.extend(owner.candidate_repair_context(kind,packet,base,plan,group))
    proposal=ledger.raw_outputs.get(failed_record.get('rawSha256')) if envelope['actionContractId']=='CANDIDATE_PATCH-v1' else None
    if proposal is not None:
        progress=repair_progress_sha256(base,report,group,values,proposal)
        current_record_sha=sha256_bytes(canonical_json_bytes(failed_record))
        for record_sha,prior_record in ledger.attempt_records.items():
            if record_sha==current_record_sha or prior_record.outcome!='FAILED' or prior_record.raw_sha256 is None:
                continue
            prior_envelope=ledger.envelopes_by_sha256[prior_record.envelope_sha256].value
            if prior_envelope['actionContractId']!='CANDIDATE_PATCH-v1':continue
            prior_packet=json.loads(files.read_bytes(prior_envelope['packetPath']));prior_view=patch_context(prior_packet)
            prior_plan=json.loads(files.read_bytes(
                f"{RUNS_ROOT}/{source['runId']}/candidate-repairs/plans/{prior_view['repairPlanSha256']}.json"))
            if prior_plan['baseCandidateSha256']!=sha256_bytes(base):continue
            if repair_progress_sha256(base,prior_plan['diagnostic'],prior_view['group'],
                    prior_view['evidence'],ledger.raw_outputs[prior_record.raw_sha256])==progress:
                raise CandidateRepairRoute('INPUT_REQUIRED','CANDIDATE_REPAIR_NO_PROGRESS')
    repair_packet=_patch_request_packet(plan_raw,group['groupId'],packet,evidence_values=values)
    identity={'originLogicalWorkId':lineage,'round':round_number,'groupId':group['groupId'],'planSha256':sha256_bytes(plan_raw)}
    logical='candidate-patch-'+sha256_bytes(canonical_json_bytes(identity))
    state={'runId':source['runId'],'currentInputRevisionSha256':source['inputRevisionSha256'],
           'currentCandidateSha256':source['baseCandidateSha256'],'checkpointRefs':[{'sha256':h} for h in source['upstreamCheckpointSha256s']]}
    result=_envelope_for_work(files,state,source['stageKind'],source['groupId'],logical,'CANDIDATE_PATCH-v1',canonical_json_bytes(repair_packet))
    files.publish_new(f"{RUNS_ROOT}/{source['runId']}/candidate-repairs/plans/{sha256_bytes(plan_raw)}.json",plan_raw)
    result_envelope=ActionEnvelope(result,_action_paths(source['runId'],result['actionId'])['envelope'],sha256_bytes(canonical_json_bytes(result)))
    _guard_action_budget(ledger,_read_run_events(files,source['runId']),policy,[result_envelope])
    selection_round=(json.loads(chain[0]['plan'])['origin']['repairRound'] if chain
                     else last_plan['origin']['repairRound'] if last_plan is not None else round_number)
    selection={'originLogicalWorkId':lineage,'sourceAttemptRecordSha256':source_digest,
        'sourceActionContractId':source['actionContractId'],
        'selectionKind':'SEMANTIC_REVIEW' if source_kind=='SEMANTIC_REVIEW' else 'AUTHOR_FAILURE',
        'repairRound':selection_round,'candidatePatchActionContractSha256':result['actionContractSha256'],
        'candidateRepairSchemaSha256':sha256_bytes((SKILL_ROOT/'contracts/candidate-repair.schema.json').read_bytes())}
    selections=[event for event in _read_run_events(files,source['runId'])
                if event.type=='CANDIDATE_REPAIR_PROTOCOL_SELECTED' and event.payload['originLogicalWorkId']==lineage]
    if not selections:_append_run_event(files,source['runId'],'CANDIDATE_REPAIR_PROTOCOL_SELECTED',selection)
    elif len(selections)!=1 or dict(selections[0].payload)!=selection:raise ValueError('候选修复协议选择事件冲突。')
    _persist_issued_action(files,result,canonical_json_bytes(repair_packet))
    return result


def _normalize_candidate_patch(files,state,envelope,packet,raw,ledger):
    from candidate_repair import patch_context, apply_repair_patch, verify_group_progress
    view=patch_context(packet)
    plan_raw=files.read_bytes(f"{RUNS_ROOT}/{envelope['runId']}/candidate-repairs/plans/{view['repairPlanSha256']}.json")
    plan=json.loads(plan_raw);_,record,source,source_packet=_candidate_source(files,envelope,ledger)
    origin=plan['origin'];semantic_source=None
    if origin['sourceKind']=='SEMANTIC_REVIEW':
        semantic_source=files.read_json(
            f"{RUNS_ROOT}/{envelope['runId']}/candidate-repairs/semantic-sources/{origin['semanticSourceSha256']}.json")
        initial=files.read_bytes(
            f"{RUNS_ROOT}/{envelope['runId']}/candidate-repairs/bases/{plan['baseCandidateSha256']}.json")
    else:
        initial=ledger.raw_outputs[record.raw_sha256]
    base=ledger.repair_heads.get(origin['originLogicalWorkId'],(initial,))[0]
    # Duplicate submit must replay against its original base, even after head advanced.
    for head,chain,index in ledger.repair_heads.values():
        for item in chain:
            if sha256_bytes(item['plan'])==sha256_bytes(plan_raw) and item['envelope']==canonical_json_bytes(envelope):
                if canonical_json_bytes(json.loads(item['patch']))!=raw:raise ValueError('同一 Action 不允许不同补丁。')
                return item['receipt']
    diagnose,_,_=_candidate_callbacks(files,source,source_packet,semantic_source)
    _,receipt=apply_repair_patch(base,plan_raw,raw,group_id=view['group']['groupId'],
        verify_group=lambda result,group:verify_group_progress(plan['diagnostic'],diagnose(result,plan['origin']),group))
    return receipt


if __name__ == "__main__":
    raise SystemExit(main())
