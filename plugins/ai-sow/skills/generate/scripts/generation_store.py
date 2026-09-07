from __future__ import annotations

import json
import re
import secrets
import shutil
import stat
from collections.abc import Mapping
from pathlib import Path

from contracts import (
    canonical_json_bytes,
    load_registry,
    sha256_bytes,
    validate_contract,
)
from models import CurrentGeneration, PublicationResult
from runtime.project_io import ProjectFiles, ProjectIOError


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_REGISTRY = load_registry(SKILL_ROOT / "contracts")
SIX_DIGITS = re.compile(r"^[0-9]{6}$")


def step_fingerprint(inputs, *, parameters, implementations, tool=None):
    return {
        'contract':'ai-sow-step-fingerprint-v1',
        'inputSha256':sha256_bytes(canonical_json_bytes(inputs)),
        'parametersSha256':sha256_bytes(canonical_json_bytes(parameters)),
        'implementationSha256':sha256_bytes(canonical_json_bytes({
            name:sha256_bytes((SKILL_ROOT/'scripts'/name).read_bytes())
            for name in implementations
        })),
        'toolSha256':sha256_bytes(canonical_json_bytes(tool)),
    }


def replace_current(files: ProjectFiles, payload: bytes) -> None:
    """Atomically replace the sole mutable pointer after immutable publication."""
    files.write_atomic(".ai-sow/current.json", payload)


def _error(code: str, path: str, message: str) -> ProjectIOError:
    return ProjectIOError(code, path, message)


def _optional_json(files: ProjectFiles, relative_path: str) -> object | None:
    try:
        return files.read_json(relative_path)
    except ProjectIOError as error:
        if error.code == "PROJECT_PATH_MISSING":
            return None
        raise


def _validated_json(
    files: ProjectFiles,
    path: str,
    schema_name: str,
) -> Mapping[str, object]:
    value = files.read_json(path)
    if not isinstance(value, Mapping) or validate_contract(
        value, schema_name, SCHEMA_REGISTRY
    ):
        raise _error("PROJECT_CONTRACT_INVALID", path, "stored contract is invalid")
    return value


def _numeric_directories(files: ProjectFiles, relative_root: str) -> set[int]:
    try:
        root = files.resolve(relative_root, expect="dir")
    except ProjectIOError as error:
        if error.code == "PROJECT_PATH_MISSING":
            return set()
        raise
    values: set[int] = set()
    for child in sorted(root.iterdir(), key=lambda item: item.name):
        if SIX_DIGITS.fullmatch(child.name) is None:
            continue
        snapshot = child.lstat()
        if stat.S_ISLNK(snapshot.st_mode) or not stat.S_ISDIR(snapshot.st_mode):
            raise _error(
                "IMMUTABLE_DIRECTORY_CONFLICT",
                f"{relative_root}/{child.name}",
                "six-digit immutable entry is not a regular directory",
            )
        values.add(int(child.name))
    return values


def _next_artifact_manifest(
    files: ProjectFiles,
    run_id: str,
    expected_sha256: str,
) -> tuple[str, Mapping[str, object]]:
    root_relative = f".ai-sow/work/runs/{run_id}/artifacts"
    root = files.resolve(root_relative, expect="dir")
    matches: list[tuple[str, Mapping[str, object]]] = []
    for version in sorted(root.iterdir(), key=lambda item: item.name):
        if not version.is_dir() or re.fullmatch(
            r"[0-9]{6}-[0-9a-f]{64}", version.name
        ) is None:
            continue
        relative = f"{root_relative}/{version.name}/artifact-manifest.json"
        try:
            payload = files.read_bytes(relative)
        except ProjectIOError as error:
            if error.code == "PROJECT_PATH_MISSING":
                continue
            raise
        if sha256_bytes(payload) != expected_sha256:
            continue
        value = files.read_json(relative)
        diagnostics = validate_contract(
            value,
            "artifact-approval.schema.json",
            SCHEMA_REGISTRY,
        )
        if diagnostics or not isinstance(value, Mapping):
            raise _error(
                "ARTIFACT_MANIFEST_INVALID",
                relative,
                "artifact manifest does not satisfy the frozen contract",
            )
        matches.append((relative, value))
    if len(matches) != 1:
        raise _error(
            "ARTIFACT_MANIFEST_NOT_UNIQUE",
            root_relative,
            "approval must resolve exactly one immutable artifact manifest",
        )
    return matches[0]


def _next_generation_id(files: ProjectFiles) -> str:
    values = _numeric_directories(files, ".ai-sow/generations")
    return f"{max(values, default=0) + 1:06d}"


def load_current(files: ProjectFiles) -> CurrentGeneration | None:
    current_value = _optional_json(files, ".ai-sow/current.json")
    if current_value is None:
        return None
    return _load_current_value(files, current_value)


def _load_current_value(files: ProjectFiles, current_value: object) -> CurrentGeneration:
    """Deep-validate a generation before publishing or accepting its pointer."""
    if not isinstance(current_value, Mapping) or validate_contract(
        current_value, "current.schema.json", SCHEMA_REGISTRY
    ):
        raise _error(
            "PROJECT_CURRENT_INVALID",
            ".ai-sow/current.json",
            "current pointer does not satisfy the v8 contract",
        )
    generation_id = str(current_value["generationId"])
    manifest_path = f".ai-sow/generations/{generation_id}/manifest.json"
    if current_value["generationManifestPath"] != manifest_path:
        raise _error(
            "PROJECT_CURRENT_PATH_MISMATCH",
            ".ai-sow/current.json",
            "current pointer does not name its generation manifest",
        )
    manifest_payload = files.read_bytes(manifest_path)
    if sha256_bytes(manifest_payload) != current_value["generationManifestSha256"]:
        raise _error(
            "PROJECT_HASH_MISMATCH",
            manifest_path,
            "generation manifest hash does not match current pointer",
        )
    manifest = _validated_json(
        files,
        manifest_path,
        "generation-manifest.schema.json",
    )
    if manifest["generationId"] != generation_id:
        raise _error(
            "PROJECT_GENERATION_ID_MISMATCH",
            manifest_path,
            "generation manifest ID does not match its directory",
        )
    for path_field, hash_field in (
        ("sowModelPath", "sowModelSha256"),
        ("workbookPath", "workbookSha256"),
        ("notesPath", "notesSha256"),
    ):
        path = str(manifest[path_field])
        if not path.startswith(f".ai-sow/generations/{generation_id}/") or sha256_bytes(
            files.read_bytes(path)
        ) != manifest[hash_field]:
            raise _error(
                "PROJECT_HASH_MISMATCH",
                path,
                "generation artifact path or hash is invalid",
            )
    proof_hashes = (
        ("proof/review-decision.json", manifest["reviewDecisionSha256"]),
        ("proof/artifact-manifest.json", manifest["artifactManifestSha256"]),
        ("proof/approval.json", manifest["approvalSha256"]),
        ("input/sow-template.xlsx", manifest["templateSha256"]),
        (
            "input/effective-policy-decision.json",
            manifest["effectivePolicyDecisionSha256"],
        ),
    )
    for relative, expected in proof_hashes:
        path = f".ai-sow/generations/{generation_id}/{relative}"
        if sha256_bytes(files.read_bytes(path)) != expected:
            raise _error(
                "PROJECT_HASH_MISMATCH",
                path,
                "generation proof hash does not match manifest",
            )
    checkpoint_paths = (
        "proof/scope-closure-checkpoint.json",
        "proof/story-ac-checkpoint.json",
        "proof/task-checkpoint.json",
    )
    actual_checkpoint_hashes = [
        sha256_bytes(files.read_bytes(f".ai-sow/generations/{generation_id}/{path}"))
        for path in checkpoint_paths
    ]
    if actual_checkpoint_hashes != list(manifest["stageCheckpointSha256s"]):
        raise _error(
            "PROJECT_HASH_MISMATCH",
            manifest_path,
            "generation checkpoint hashes do not match manifest",
        )
    artifact = validate_artifact_manifest(files, f".ai-sow/generations/{generation_id}/proof/artifact/artifact-manifest.json", str(manifest["artifactManifestSha256"]))
    model = files.read_json(str(manifest["sowModelPath"]))
    expected = {key: artifact[key] for key in (
        "runId", "stageCheckpointSha256s", "reviewDecisionSha256", "templateSha256",
        "effectivePolicyDecisionSha256", "rendererContract", "rendererSha256")}
    expected.update({"inputRevisionSha256": model["project"]["inputRevisionSha256"],
        "sowModelSha256": artifact["candidateSha256"], "workbookSha256": artifact["workbook"]["sha256"],
        "notesSha256": artifact["notes"]["sha256"]})
    if any(manifest[key] != value for key, value in expected.items()):
        raise _error("GENERATION_ARTIFACT_BINDING_MISMATCH", manifest_path,
                     "generation fields do not match the verified artifact")
    approval_path = f".ai-sow/generations/{generation_id}/proof/approval.json"
    approval = _validated_json(files, approval_path, "artifact-approval.schema.json")
    if (approval.get("decision") != "APPROVE"
        or approval.get("artifactManifestSha256") != manifest["artifactManifestSha256"]
        or any(approval.get(key) != artifact[key] for key in (
            "runId", "candidateSha256", "sourceManifestSha256", "reviewDecisionSha256",
            "templateSha256", "effectivePolicyDecisionSha256"))):
        raise _error("GENERATION_ARTIFACT_BINDING_MISMATCH", approval_path,
                     "generation approval does not match the verified artifact")
    if manifest.get("pairDecisionSha256") != approval.get("pairDecisionSha256"):
        raise _error("GENERATION_PAIR_BINDING_MISMATCH", approval_path,
                     "generation pair decision does not match its approval")
    return CurrentGeneration(
        generation_id=generation_id,
        manifest_path=manifest_path,
        workbook_path=str(manifest["workbookPath"]),
        notes_path=str(manifest["notesPath"]),
    )


def promote(
    draft_manifest_sha256: str,
    approval: Mapping[str, object],
    *,
    files: ProjectFiles,
) -> PublicationResult:
    """Promote approved draft bytes without invoking renderer or Office."""
    approval_diagnostics = validate_contract(
        approval,
        "artifact-approval.schema.json",
        SCHEMA_REGISTRY,
    )
    if approval_diagnostics or approval.get("decision") != "APPROVE":
        raise _error(
            "APPROVAL_INVALID",
            "approval.json",
            "promote requires a contract-valid APPROVE decision",
        )
    if approval.get("artifactManifestSha256") != draft_manifest_sha256:
        raise _error(
            "APPROVAL_BINDING_MISMATCH",
            "approval.json",
            "approval does not bind the requested artifact manifest",
        )
    manifest_path, artifact = _next_artifact_manifest(
        files,
        str(approval["runId"]),
        draft_manifest_sha256,
    )
    validate_artifact_manifest(files, manifest_path, draft_manifest_sha256)
    for field in (
        "runId",
        "candidateSha256",
        "sourceManifestSha256",
        "reviewDecisionSha256",
        "templateSha256",
        "effectivePolicyDecisionSha256",
    ):
        if approval.get(field) != artifact.get(field):
            raise _error(
                "APPROVAL_BINDING_MISMATCH",
                "approval.json",
                f"approval field does not bind artifact: {field}",
            )
    approval_payload = canonical_json_bytes(approval)
    approval_sha256 = sha256_bytes(approval_payload)
    pair_digest = approval.get("pairDecisionSha256")
    if pair_digest is not None:
        # A tree may already exist after a crash immediately before current swap.
        # Find it by the immutable pair-decision/artifact key, not wall-clock time.
        matches = []
        for number in sorted(_numeric_directories(files, ".ai-sow/generations")):
            path = f".ai-sow/generations/{number:06d}/manifest.json"
            existing = files.read_json(path)
            if (existing.get("pairDecisionSha256") == pair_digest
                and existing.get("artifactManifestSha256") == draft_manifest_sha256):
                matches.append((path, existing))
        if len(matches) > 1:
            raise _error("PAIR_PUBLICATION_CONFLICT", "generations", "duplicate pair publication identity")
        if matches:
            path, existing = matches[0]
            pointer = {"contract": "ai-sow-current-v2", "generationId": existing["generationId"],
                "generationManifestPath": path, "generationManifestSha256": sha256_bytes(files.read_bytes(path))}
            recovered = _load_current_value(files, pointer)
            current_pointer = _optional_json(files, ".ai-sow/current.json")
            if current_pointer is not None:
                current_generation = load_current(files)
                if int(current_generation.generation_id) > int(recovered.generation_id):
                    raise _error("PAIR_PUBLICATION_STALE", path, "pair replay cannot roll back a newer current")
            if current_pointer != pointer:
                replace_current(files, canonical_json_bytes(pointer))
            return PublicationResult(outcome="REUSED", decision="PASS", generation_id=recovered.generation_id,
                revision_id=None, workbook_path=recovered.workbook_path, notes_path=recovered.notes_path,
                change_counts={}, questions=())
    current = _optional_json(files, ".ai-sow/current.json")
    if isinstance(current, Mapping) and current.get("contract") == "ai-sow-current-v2":
        current_manifest = _optional_json(
            files, str(current.get("generationManifestPath"))
        )
        if (
            isinstance(current_manifest, Mapping)
            and current_manifest.get("artifactManifestSha256")
            == draft_manifest_sha256
            and current_manifest.get("approvalSha256") == approval_sha256
        ):
            load_current(files)
            return PublicationResult(
                outcome="REUSED",
                decision="PASS",
                generation_id=str(current["generationId"]),
                revision_id=None,
                workbook_path=str(current_manifest["workbookPath"]),
                notes_path=str(current_manifest["notesPath"]),
                change_counts={},
                questions=(),
            )
    artifact_root = str(Path(manifest_path).parent.as_posix())

    def artifact_bytes(name: str) -> bytes:
        return files.read_bytes(f"{artifact_root}/{name}")

    for field, name in (("workbook", "sow.xlsx"), ("notes", "sow-notes.md")):
        binding = artifact.get(field)
        if not isinstance(binding, Mapping) or sha256_bytes(
            artifact_bytes(name)
        ) != binding.get("sha256"):
            raise _error(
                "ARTIFACT_HASH_MISMATCH",
                f"{artifact_root}/{name}",
                "approved artifact bytes do not match the manifest",
            )
    model_payload = artifact_bytes("sow-model.json")
    model = json.loads(model_payload.decode("utf-8"))
    if not isinstance(model, Mapping) or sha256_bytes(model_payload) != artifact.get(
        "candidateSha256"
    ):
        raise _error(
            "ARTIFACT_HASH_MISMATCH",
            f"{artifact_root}/sow-model.json",
            "approved sow-model bytes do not match the manifest",
        )
    project = model.get("project")
    if not isinstance(project, Mapping):
        raise _error(
            "ARTIFACT_MODEL_INVALID",
            f"{artifact_root}/sow-model.json",
            "approved sow-model lacks project bindings",
        )
    generation_id = _next_generation_id(files)
    generation_root = f".ai-sow/generations/{generation_id}"
    workbook_payload = artifact_bytes("sow.xlsx")
    notes_payload = artifact_bytes("sow-notes.md")
    project_meta_root = files.ensure_dir(".ai-sow")
    stage_root = project_meta_root / f".generation-stage-{secrets.token_hex(6)}"
    stage_root.mkdir()
    try:
        stage_files = ProjectFiles.open(stage_root)
        copied = (
            ("data/sow-model.json", model_payload),
            ("input/sow-template.xlsx", artifact_bytes("sow-template.xlsx")),
            (
                "input/effective-policy-decision.json",
                artifact_bytes("effective-policy-decision.json"),
            ),
            ("proof/review-decision.json", artifact_bytes("review-decision.json")),
            (
                "proof/scope-closure-checkpoint.json",
                artifact_bytes("scope-closure-checkpoint.json"),
            ),
            (
                "proof/story-ac-checkpoint.json",
                artifact_bytes("story-ac-checkpoint.json"),
            ),
            ("proof/task-checkpoint.json", artifact_bytes("task-checkpoint.json")),
            ("proof/artifact-manifest.json", files.read_bytes(manifest_path)),
            ("proof/approval.json", approval_payload),
            ("output/sow.xlsx", workbook_payload),
            ("output/sow-notes.md", notes_payload),
        )
        for relative, payload in copied:
            stage_files.write_atomic(relative, payload)
        proof_names = ['sow-model.json','sow-template.xlsx','sow.xlsx','sow-notes.md','effective-policy-decision.json',
            'review-decision.json','scope-closure-checkpoint.json','story-ac-checkpoint.json','task-checkpoint.json',
            'proof-bundle.json','verification.json','renderer-fingerprint.json','artifact-manifest.json']
        proof_names.extend(item['path'] for item in artifact['renders'])
        for name in proof_names:
            stage_files.publish_new('proof/artifact/'+name,artifact_bytes(name))
        validate_artifact_manifest(stage_files,'proof/artifact/artifact-manifest.json',draft_manifest_sha256)
        generation_manifest = {
            "contract": "ai-sow-generation-manifest-v2",
            "generationId": generation_id,
            "runId": artifact["runId"],
            "inputRevisionSha256": project["inputRevisionSha256"],
            "sowModelPath": f"{generation_root}/data/sow-model.json",
            "sowModelSha256": artifact["candidateSha256"],
            "stageCheckpointSha256s": artifact["stageCheckpointSha256s"],
            "reviewDecisionSha256": artifact["reviewDecisionSha256"],
            "artifactManifestSha256": draft_manifest_sha256,
            "approvalSha256": approval_sha256,
            "templateSha256": artifact["templateSha256"],
            "effectivePolicyDecisionSha256": artifact[
                "effectivePolicyDecisionSha256"
            ],
            "rendererContract": artifact["rendererContract"],
            "rendererSha256": artifact["rendererSha256"],
            "workbookPath": f"{generation_root}/output/sow.xlsx",
            "workbookSha256": artifact["workbook"]["sha256"],
            "notesPath": f"{generation_root}/output/sow-notes.md",
            "notesSha256": artifact["notes"]["sha256"],
            "publicationComplete": True,
        }
        if pair_digest is not None:
            generation_manifest["pairDecisionSha256"] = pair_digest
        manifest_diagnostics = validate_contract(
            generation_manifest,
            "generation-manifest.schema.json",
            SCHEMA_REGISTRY,
        )
        if manifest_diagnostics:
            raise _error(
                "GENERATION_MANIFEST_INVALID",
                "manifest.json",
                "generation manifest does not satisfy the frozen contract",
            )
        manifest_payload = canonical_json_bytes(generation_manifest)
        stage_files.write_atomic("manifest.json", manifest_payload)
        files.publish_tree_new(stage_root, generation_root)
        final_manifest_path = f"{generation_root}/manifest.json"
        if files.read_bytes(final_manifest_path) != manifest_payload:
            raise _error(
                "GENERATION_HASH_MISMATCH",
                final_manifest_path,
                "published generation manifest changed",
            )
        current_value = {
            "contract": "ai-sow-current-v2",
            "generationId": generation_id,
            "generationManifestPath": final_manifest_path,
            "generationManifestSha256": sha256_bytes(manifest_payload),
        }
        current_diagnostics = validate_contract(
            current_value,
            "current.schema.json",
            SCHEMA_REGISTRY,
        )
        if current_diagnostics:
            raise _error(
                "CURRENT_INVALID",
                ".ai-sow/current.json",
                "current pointer does not satisfy the frozen contract",
            )
        replace_current(files, canonical_json_bytes(current_value))
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)
    return PublicationResult(
        outcome="PUBLISHED",
        decision="PASS",
        generation_id=generation_id,
        revision_id=None,
        workbook_path=f"{generation_root}/output/sow.xlsx",
        notes_path=f"{generation_root}/output/sow-notes.md",
        change_counts={},
        questions=(),
    )



def freeze_workbook(files, path, payload, expected_sha256):
    if sha256_bytes(payload) != expected_sha256:
        raise ValueError('final workbook hash mismatch before publication')
    files.publish_new(path, payload)
    if sha256_bytes(files.read_bytes(path)) != expected_sha256:
        raise ValueError('final workbook hash mismatch after publication')



ARTIFACT_PREFIX_STEPS=('MATERIALIZE','OFFICE','OFFICE_REFERENCE','VALIDATE')


def artifact_step_directory(run_root, kind, revision):
    return run_root+'/artifact-steps/'+kind if revision==1 else run_root+f'/artifact-revisions/{revision:06d}/steps/'+kind


def artifact_repair_plan(entries, events, ledger, packets, run_id, candidate_hash):
    """Derive render revisions only from real failed visuals and immutable decisions."""
    from package_renderer import validate_visual_result
    selected=[event for event in events if event['type']=='ARTIFACT_REPAIR_AUTHORIZED']
    if len(selected)!=len(entries): raise ValueError('工件修复裁定与事件集合不完整。')
    revision=1
    for event in selected:
        fact=event['payload'];entry=entries.get(fact['authorizationSha256'],{})
        answer=entry.get('authorization',{});terminal=entry.get('terminalState',{})
        if (validate_contract(answer,'artifact-repair-authorization.schema.json',SCHEMA_REGISTRY)
                or validate_contract(terminal,'run-state.schema.json',SCHEMA_REGISTRY)
                or sha256_bytes(canonical_json_bytes(answer))!=fact['authorizationSha256']
                or sha256_bytes(canonical_json_bytes(terminal))!=answer['terminalStateSha256']
                or answer['runId']!=run_id or terminal['runId']!=run_id
                or answer['candidateSha256']!=candidate_hash or terminal['currentCandidateSha256']!=candidate_hash
                or terminal['phase']!='DONE' or terminal['result']!='MANUAL_REVIEW_REQUIRED'
                or fact['previousArtifactRevision']!=revision or fact['artifactRevision']!=revision+1):
            raise ValueError('预览修复必须绑定原始终态、同一模型和连续工件版本。')
        record=ledger.attempt_records.get(answer['visualReviewAttemptRecordSha256'])
        if record is None or record.outcome!='SUCCEEDED': raise ValueError('预览修复缺少实际视觉失败记录。')
        envelope=ledger.envelopes_by_sha256[record.envelope_sha256].value
        if envelope['actionContractId']!='ARTIFACT_VISUAL_REVIEW-v1' or envelope['baseCandidateSha256']!=candidate_hash:
            raise ValueError('预览修复绑定了无关 Action。')
        packet=json.loads(packets[envelope['packetSha256']]);body=packet['workItems'][0]['payload']
        validate_visual_result(packet,ledger.normalized_results[record.normalized_result_sha256])
        if json.loads(ledger.normalized_results[record.normalized_result_sha256])['overallDecision']!='FAIL':
            raise ValueError('已通过的视觉工件不能由该入口改写。')
        if body['workbook']['path']!=f'.ai-sow/work/runs/{run_id}/artifacts/{revision:06d}-{candidate_hash}/sow.xlsx':
            raise ValueError('预览裁定不是前一工件。')
        issued=[item['sequence'] for item in events if item['type']=='ACTION_ISSUED' and item['payload']['envelopeSha256']==record.envelope_sha256]
        if len(issued)!=1 or issued[0]>=event['sequence']: raise ValueError('预览裁定早于实际视觉 Action。')
        revision+=1
    return {'revision':revision,'stepRevisions':{**{kind:1 for kind in ARTIFACT_PREFIX_STEPS},'RENDER':revision,'FINAL_VALIDATE':revision}}

def collect_artifact_proof(files, state, revision_path, *, repair_entries=None):
    """Freeze one portable proof closure over this run's authorized records."""
    from package_renderer import encode_binary
    run_root = f".ai-sow/work/runs/{state['runId']}"
    actions = []
    for path in sorted(files.resolve(run_root+'/actions',expect='dir').iterdir()):
        relative = path.relative_to(files.root).as_posix()
        if not (path/'record.json').is_file(): raise ValueError('artifact has unfinished action')
        record = files.read_json(relative+'/record.json')
        actions.append({'envelope':files.read_json(relative+'/envelope.json'),
            'packet':files.read_json(relative+'/packet.json'),'record':record,
            'raw':encode_binary(files.read_bytes(relative+'/raw-output.bin')) if record['rawSha256'] else None,
            'normalized':encode_binary(files.read_bytes(relative+'/normalized-result.json')) if record['normalizedResultSha256'] else None})
    stages = {}
    for stage in ('SCOPE','STORY_AC','TASK'):
        root = files.resolve(run_root+'/stages/'+stage,expect='dir')
        def contents(directory, pattern='*.json'):
            return {p.stem:files.read_json(p.relative_to(files.root).as_posix()) for p in sorted((root/directory).glob(pattern))}
        checkpoints, plans = contents('checkpoints'), contents('plans')
        if len(checkpoints)!=1 or len(plans)!=1: raise ValueError('artifact requires three unique final checkpoints/plans')
        stages[stage] = {'checkpoint':next(iter(checkpoints.values())), 'plan':next(iter(plans.values())),
            'candidates':contents('candidates'),'validators':contents('validators','*/*.json'),
            'reviewInputs':contents('review-inputs','*/*.json'),'priorStates':contents('prior-states')}
        manual=contents('manual-repairs','*/*.json')
        if manual:
            stages[stage]['manualRepairs']={answer['reviewDecisionSha256']:{'authorization':answer,
                'terminalState':files.read_json(run_root+'/states/state-'+answer['terminalStateSha256']+'.json')}
                for answer in manual.values()}
    events = [files.read_json(p.relative_to(files.root).as_posix()) for p in sorted(files.resolve(run_root+'/events',expect='dir').glob('*.json'))]
    cutoff=max(i for i,e in enumerate(events) if e['type']=='ACTION_ISSUED')
    proof={'inputRevision':files.read_json(revision_path),'stages':stages,'actions':actions,'events':events[:cutoff+1]}
    patch_actions=[a for a in actions if a['envelope']['actionContractId']=='CANDIDATE_PATCH-v1']
    if patch_actions:
        from candidate_repair import patch_context
        hashes={patch_context(a['packet'])['repairPlanSha256'] for a in patch_actions}
        proof['candidateRepairPlans']={h:files.read_json(run_root+'/candidate-repairs/plans/'+h+'.json') for h in hashes}
        inventory_root=files.resolve(run_root+'/stages/SCOPE',expect='dir')/'prior-inventories'
        proof['candidateRepairInventories']=[files.read_json(p.relative_to(files.root).as_posix()) for p in sorted(inventory_root.glob('*.json'))]
        semantic_plans=[proof['candidateRepairPlans'][digest] for digest in hashes
                        if proof['candidateRepairPlans'][digest]['origin']['sourceKind']=='SEMANTIC_REVIEW']
        if semantic_plans:
            proof['candidateRepairBases']={plan['baseCandidateSha256']:
                files.read_json(run_root+'/candidate-repairs/bases/'+plan['baseCandidateSha256']+'.json')
                for plan in semantic_plans}
            proof['candidateRepairSemanticSources']={plan['origin']['semanticSourceSha256']:
                files.read_json(run_root+'/candidate-repairs/semantic-sources/'+plan['origin']['semanticSourceSha256']+'.json')
                for plan in semantic_plans}
    ledger,packets=_proof_ledger(proof,require_bundled_resolutions=False)
    if ledger.candidate_resolutions:
        proof['candidateResolutions']={key:json.loads(raw) for key,raw in ledger.candidate_resolutions.items()}
    # The final checkpoint owns this artifact's candidate, independently of the
    # mutable active state (offline readers only need the immutable run identity).
    candidate_hash=stages['TASK']['checkpoint']['candidateSha256']
    candidate=stages['TASK']['candidates'].get(candidate_hash)
    if candidate is None or sha256_bytes(canonical_json_bytes(candidate))!=candidate_hash:
        raise ValueError('工件候选未绑定最终 Task checkpoint。')
    if repair_entries is None:
        repair_entries={}
        for event in proof['events']:
            if event['type']!='ARTIFACT_REPAIR_AUTHORIZED': continue
            digest=event['payload']['authorizationSha256']
            answer=files.read_json(run_root+'/artifact-repairs/'+digest+'.json')
            repair_entries[digest]={'authorization':answer,'terminalState':files.read_json(
                run_root+'/states/state-'+answer['terminalStateSha256']+'.json')}
    plan=artifact_repair_plan(repair_entries,proof['events'],ledger,packets,state['runId'],candidate_hash)
    steps={kind:files.read_json(artifact_step_directory(run_root,kind,plan['stepRevisions'][kind])+'/'+_artifact_step_digest(proof['events'],kind,plan['stepRevisions'][kind])+'.json')
        for kind in (*ARTIFACT_PREFIX_STEPS,'RENDER')}
    proof['artifactSteps']=steps
    from office_engine import office_tool_fingerprint
    proof['officeToolFingerprint']=office_tool_fingerprint()
    if repair_entries:
        proof.update(artifactRepairAuthorizations=repair_entries,artifactRevision=plan['revision'],artifactStepRevisions=plan['stepRevisions'])
    return proof


def _proof_ledger(proof, *, expected_resolutions=None, require_bundled_resolutions=True):
    from action_ledger import ActionLedger, attempt_record_from_value
    from models import ActionEnvelope, RunEvent
    from contracts import normalize_action_result, validate_action_envelope
    from package_renderer import decode_binary
    from run_events import validate_run_event_log
    envelopes,records,raw,normalized,packets = {},{},{},{},{}
    events = [RunEvent(v['runId'],v['sequence'],v['type'],v['occurredAtUtc'],v['payload']) for v in proof['events']]
    validate_run_event_log(events)
    issued = {e.payload['envelopeSha256']:e.payload for e in events if e.type=='ACTION_ISSUED'}
    for action in proof['actions']:
        envelope = action['envelope']; digest = sha256_bytes(canonical_json_bytes(envelope))
        if digest in envelopes or issued.get(digest)!={'envelopeSha256':digest,'actionId':envelope['actionId'],'logicalWorkId':envelope['logicalWorkId']}:
            raise ValueError('artifact Attempt issuance binding invalid')
        packets[envelope['packetSha256']] = canonical_json_bytes(action['packet'])
        if sha256_bytes(packets[envelope['packetSha256']]) != envelope['packetSha256']:
            raise ValueError('artifact packet hash invalid')
        contract, contract_hash = __import__('contracts').action_contract_binding(SKILL_ROOT,envelope['actionContractId'])
        if contract_hash != envelope['actionContractSha256']: raise ValueError('artifact action contract drift')
        envelopes[digest] = ActionEnvelope(envelope,'proof/envelope.json',digest)
        record = attempt_record_from_value(action['record'])
        records[sha256_bytes(canonical_json_bytes(action['record']))] = record
        if record.raw_sha256: raw[record.raw_sha256] = decode_binary(action['raw'])
        if record.normalized_result_sha256:
            payload = decode_binary(action['normalized']); normalized[record.normalized_result_sha256] = payload
            if envelope['actionContractId']!='CANDIDATE_PATCH-v1' and normalize_action_result(envelope,raw[record.raw_sha256],skill_root=SKILL_ROOT,
                                       packet_payload=packets[envelope['packetSha256']]) != payload:
                raise ValueError('artifact normalized result/schema binding invalid')
    if set(issued)!=set(envelopes): raise ValueError('artifact omits issued Attempt proof')
    ledger=ActionLedger(envelopes,records,raw,normalized)
    if any(e.value['actionContractId']=='CANDIDATE_PATCH-v1' for e in envelopes.values()):
        from candidate_repair import replay_candidate_ledger
        from owner_callbacks import candidate_owner_callbacks
        plans={h:canonical_json_bytes(value) for h,value in proof.get('candidateRepairPlans',{}).items()}
        ledger=replay_candidate_ledger(ledger,packets,plans,
            owner_callbacks=lambda e,p,semantic_source=None:candidate_owner_callbacks(
                e,p,inventories=proof.get('candidateRepairInventories',()),
                revision_bytes=canonical_json_bytes(proof['inputRevision']),semantic_source=semantic_source),
            events=events,bases=proof.get('candidateRepairBases',{}),
            semantic_sources=proof.get('candidateRepairSemanticSources',{}))
    bundled_resolutions={key:canonical_json_bytes(value) for key,value in proof.get('candidateResolutions',{}).items()}
    if (require_bundled_resolutions or bundled_resolutions) and bundled_resolutions!=dict(ledger.candidate_resolutions):
        raise ValueError('portable proof 缺少或篡改 CandidateResolution。')
    if expected_resolutions is not None and {key:sha256_bytes(raw) for key,raw in ledger.candidate_resolutions.items()}!=expected_resolutions:
        raise ValueError('离线 Resolution 与调用方冻结的证明根不一致。')
    return ledger, packets


def verify_artifact_proof(proof, model, manifest):
    from final_review import verify_checkpoint_proof, verify_manual_authorization_records
    from task_compiler import verify_task_repair_chain
    from package_renderer import decode_binary, visual_identity, validate_visual_result
    from stage_planner import _effective_success, _effective_envelope
    from contracts import action_contract_binding
    ledger, packets = _proof_ledger(proof)
    repair_plan=artifact_repair_plan(proof.get('artifactRepairAuthorizations',{}),proof['events'],ledger,packets,manifest['runId'],manifest['candidateSha256'])
    if (proof.get('artifactRevision',1)!=repair_plan['revision']
            or proof.get('artifactStepRevisions',repair_plan['stepRevisions'])!=repair_plan['stepRevisions']):
        raise ValueError('工件修复步骤未绑定已验证前缀。')
    tool=proof.get('officeToolFingerprint')
    if not isinstance(tool,dict):
        raise ValueError('artifact proof 缺少无路径 Office 工具身份。')
    artifact_inputs={
        'MATERIALIZE':[model,proof['inputRevision']['templateSha256']],
        'OFFICE':proof['artifactSteps']['MATERIALIZE'],
        'OFFICE_REFERENCE':proof['artifactSteps']['MATERIALIZE'],
        'VALIDATE':[model,proof['inputRevision']['templateSha256'],
            proof['artifactSteps']['MATERIALIZE'],proof['artifactSteps']['OFFICE'],
            proof['artifactSteps']['OFFICE_REFERENCE']],
        'RENDER':proof['artifactSteps']['OFFICE']}
    implementations={'MATERIALIZE':['package_renderer.py','workbook.py','story_notes.py'],
        'OFFICE':['office_engine.py'],'OFFICE_REFERENCE':['office_engine.py'],
        'VALIDATE':['package_renderer.py','workbook.py'],
        'RENDER':['package_renderer.py','office_engine.py']}
    for kind,value in proof['artifactSteps'].items():
        revision=repair_plan['stepRevisions'][kind]
        fingerprint=step_fingerprint(artifact_inputs[kind],
            parameters={'stage':'ARTIFACT','revision':revision,'kind':kind},
            implementations=implementations[kind],
            tool=tool if kind in {'OFFICE','OFFICE_REFERENCE','RENDER'} else None)
        expected=_artifact_step_digest(proof['events'],kind,revision,fingerprint=fingerprint)
        if expected!=sha256_bytes(canonical_json_bytes(value)):
            raise ValueError('工件步骤未绑定可重算的实际输入指纹与成功输出。')
    if set(proof['artifactSteps'])!={'MATERIALIZE','OFFICE','OFFICE_REFERENCE','VALIDATE','RENDER'}:
        raise ValueError('artifact deterministic step closure incomplete')
    if (sha256_bytes(decode_binary(proof['artifactSteps']['OFFICE']['workbook']))!=manifest['workbook']['sha256']
        or proof['artifactSteps']['OFFICE']['office']!=manifest['office']
        or sha256_bytes(canonical_json_bytes(proof['artifactSteps']['VALIDATE']))!=manifest['verification']['sha256']
        or [r['sha256'] for r in proof['artifactSteps']['RENDER']['renders']]!=[r['sha256'] for r in manifest['renders']]):
        raise ValueError('artifact step output does not bind workbook/Office/reopen/renders')
    for entry in proof.get('artifactRepairAuthorizations',{}).values():
        old=ledger.attempt_records[entry['authorization']['visualReviewAttemptRecordSha256']]
        envelope=ledger.envelopes_by_sha256[old.envelope_sha256].value
        previous=json.loads(packets[envelope['packetSha256']])['workItems'][0]['payload']
        if previous['workbook']['sha256']!=manifest['workbook']['sha256']:
            raise ValueError('仅预览修复不得替换此前已验证的工作簿。')
    revision = canonical_json_bytes(proof['inputRevision'])
    if manifest['sourceManifestSha256'] != sha256_bytes(canonical_json_bytes({key:proof['inputRevision'][key] for key in ('sources','blocks')})):
        raise ValueError('artifact source manifest not derived from input revision')
    if model['project']['policyDefinitionSha256'] != proof['inputRevision']['deliveryPolicySha256']:
        raise ValueError('artifact model policy definition binding invalid')
    from sow_model import validate as validate_model
    if validate_model(model,'STAGE_3',registry=SCHEMA_REGISTRY): raise ValueError('artifact SOW Model validation failed')
    checkpoints = []
    for stage in ('SCOPE','STORY_AC','TASK'):
        body = proof['stages'][stage]; checkpoint = body['checkpoint']
        def byte_map(name):
            values={key:canonical_json_bytes(value) for key,value in body[name].items()}
            if any(sha256_bytes(raw)!=key for key,raw in values.items()): raise ValueError('artifact stage content address drift')
            return values
        verify_checkpoint_proof(checkpoint,task_repair_verifier=verify_task_repair_chain,revision_bytes=revision,plan_bytes=canonical_json_bytes(body['plan']),
            upstream_bytes=checkpoints[-1:],ledger=ledger,candidates=byte_map('candidates'),validators=byte_map('validators'),
            review_inputs=byte_map('reviewInputs'),packets=packets,prior_states=byte_map('priorStates'),
            manual_authorizations=verify_manual_authorization_records(body.get('manualRepairs',{}),proof['events'],
                stage,manifest['runId'],sha256_bytes(revision),require_repair=True,review_inputs=body['reviewInputs'],stage_plan=body['plan']))
        checkpoints.append(canonical_json_bytes(checkpoint))
    final = proof['stages']['TASK']['checkpoint']
    if (manifest['stageCheckpointSha256s'] != [sha256_bytes(raw) for raw in checkpoints]
        or final['candidateSha256'] != manifest['candidateSha256']
        or final['reviewDecisionSha256'] != manifest['reviewDecisionSha256']
        or proof['stages']['SCOPE']['checkpoint'].get('priorStateSha256') != manifest['priorStateSha256']
        or model['project']['inputRevisionSha256'] != sha256_bytes(revision)
        or model['project']['sourceManifestSha256'] != manifest['sourceManifestSha256']
        or proof['inputRevision']['templateSha256'] != manifest['templateSha256']):
        raise ValueError('artifact model/checkpoint/Prior/input binding invalid')
    _, contract_hash = action_contract_binding(SKILL_ROOT,'ARTIFACT_VISUAL_REVIEW-v1')
    identity, logical, group = visual_identity(manifest['workbook']['sha256'],[r['sha256'] for r in manifest['renders']],contract_hash)
    record_hash, record = _effective_success(ledger,logical)
    envelope = _effective_envelope(ledger,logical).value
    if (record_hash != manifest['visualReview']['attemptRecordSha256'] or envelope['groupId']!=group
        or envelope['stageKind']!='ARTIFACT' or envelope['actionContractId']!='ARTIFACT_VISUAL_REVIEW-v1'
        or envelope['baseCandidateSha256']!=manifest['candidateSha256']
        or envelope['upstreamCheckpointSha256s']!=sorted(manifest['stageCheckpointSha256s'])):
        raise ValueError('artifact visual Attempt identity binding invalid')
    packet = json.loads(packets[envelope['packetSha256']]); body=packet['workItems'][0]['payload']
    expected_root=f".ai-sow/work/runs/{manifest['runId']}/artifacts/{repair_plan['revision']:06d}-{manifest['candidateSha256']}"
    if (body['workbook']['path']!=expected_root+'/sow.xlsx'
        or [r['path'] for r in body['renders']]!=[expected_root+'/'+r['path'] for r in manifest['renders']]
        or body['identity']!=identity or body['visibleSheets']!=manifest['visibleSheets']
        or [r['sha256'] for r in body['renders']]!=[r['sha256'] for r in manifest['renders']]
        or [r['sheetKey'] for r in body['renders']]!=manifest['visibleSheets']
        or body['workbook']['sha256']!=manifest['workbook']['sha256']):
        raise ValueError('artifact visual packet omits/reorders visible render')
    validate_visual_result(packet,ledger.normalized_results[record.normalized_result_sha256])
    if json.loads(ledger.normalized_results[record.normalized_result_sha256])['overallDecision']!='PASS':
        raise ValueError('artifact visual review is not PASS')
    return proof


def validate_artifact_manifest(files, manifest_path, expected_sha256):
    from office_engine import validate_office_identity
    from package_renderer import RENDERER_CONTRACT
    from workbook import scan_workbook_integrity
    raw = files.read_bytes(manifest_path)
    if sha256_bytes(raw)!=expected_sha256: raise ValueError('artifact manifest hash mismatch')
    manifest = json.loads(raw)
    if validate_contract(manifest,'artifact-approval.schema.json',SCHEMA_REGISTRY): raise ValueError('artifact manifest schema invalid')
    return _validate_artifact_contents(files, Path(manifest_path).parent.as_posix(), manifest)


def _validate_artifact_contents(files, root, manifest):
    from office_engine import validate_office_identity
    from package_renderer import RENDERER_CONTRACT
    from workbook import scan_workbook_integrity
    def read(name): return files.read_bytes(root+'/'+name)
    def bound(binding):
        payload = read(binding['path'])
        if sha256_bytes(payload)!=binding['sha256']: raise ValueError('artifact content hash mismatch: '+binding['path'])
        return payload
    model = json.loads(read('sow-model.json'))
    if sha256_bytes(read('sow-model.json'))!=manifest['candidateSha256']: raise ValueError('artifact model hash mismatch')
    if sha256_bytes(read('sow-template.xlsx'))!=manifest['templateSha256'] or model['project']['templateSha256']!=manifest['templateSha256']:
        raise ValueError('artifact template hash mismatch')
    fingerprint = json.loads(read('renderer-fingerprint.json'))
    current = {'rendererContract':RENDERER_CONTRACT,'files':{key:sha256_bytes((SKILL_ROOT/key).read_bytes()) for key in fingerprint['files']}}
    baseline=json.loads((SKILL_ROOT/'contracts/renderer-fingerprint-baseline.json').read_bytes())
    if set(fingerprint['files'])!=set(baseline['files']) or fingerprint!=current or sha256_bytes(canonical_json_bytes(fingerprint))!=manifest['rendererSha256']:
        raise ValueError('artifact renderer fingerprint mismatch')
    bound(manifest['workbook']); bound(manifest['notes'])
    verification = json.loads(bound(manifest['verification']))
    if (validate_office_identity(manifest['office'])!=verification['office']
        or manifest['workbookVerification'] != {'trustState':'VERIFIED','engineName':'LibreOffice','engineVersion':verification['office']['version']}
        or verification['trustState']!='VERIFIED' or verification['workbookSha256']!=manifest['workbook']['sha256']
        or sha256_bytes(canonical_json_bytes(verification['structureFormula']))!=manifest['structureFormulaSha256']):
        raise ValueError('artifact Office/reopen verification mismatch')
    import openpyxl
    path=files.resolve(root+'/'+manifest['workbook']['path'],expect='file')
    if scan_workbook_integrity(path)!= {key:verification['structureFormula'][key] for key in ('formulaSha256','formulaCount')}:
        raise ValueError('artifact formula inventory mismatch')
    book=openpyxl.load_workbook(path,data_only=True)
    try: sheets=[s.title for s in book if s.sheet_state=='visible']
    finally: book.close()
    if sheets!=manifest['visibleSheets'] or [r['sheetKey'] for r in manifest['renders']]!=sheets:
        raise ValueError('artifact visible render inventory mismatch')
    for render in manifest['renders']: bound(render)
    proof = json.loads(bound(manifest['proofBundle']))
    verify_artifact_proof(proof,model,manifest)
    if sha256_bytes(read('effective-policy-decision.json'))!=manifest['effectivePolicyDecisionSha256']:
        raise ValueError('artifact derived policy projection mismatch')
    from task_standard_catalog import catalog
    if catalog(files.resolve(root+'/sow-template.xlsx',expect='file')).semantic_sha256!=manifest['taskCatalogSemanticSha256']:
        raise ValueError('artifact template catalog semantic hash mismatch')
    expected_policy = canonical_json_bytes(model['policyInstances'])
    if read('effective-policy-decision.json')!=expected_policy: raise ValueError('artifact policy projection is not model derived')
    if read('review-decision.json')!=canonical_json_bytes({'decision':'PASS','findings':[]}): raise ValueError('artifact final review changed')
    return manifest


def prepare_artifact_manifest(files, state, *, template_path, proof, calculated, projection, verification, renders, renderer_fingerprint, visual_record_sha256):
    from package_renderer import decode_binary, RENDERER_CONTRACT
    from task_standard_catalog import catalog
    model = proof['stages']['TASK']['candidates'][state['currentCandidateSha256']]
    checkpoints = [proof['stages'][stage]['checkpoint'] for stage in ('SCOPE','STORY_AC','TASK')]
    root = f".ai-sow/work/runs/{state['runId']}/artifacts/{proof.get('artifactRevision',1):06d}-{state['currentCandidateSha256']}"
    payloads = {'sow.xlsx':decode_binary(calculated['workbook']),'sow-notes.md':projection['notes'].encode('utf-8'),
        'sow-model.json':canonical_json_bytes(model),'sow-template.xlsx':Path(template_path).read_bytes(),
        'proof-bundle.json':canonical_json_bytes(proof),'verification.json':canonical_json_bytes(verification),
        'renderer-fingerprint.json':canonical_json_bytes(renderer_fingerprint),
        'effective-policy-decision.json':canonical_json_bytes(model['policyInstances']),
        'review-decision.json':canonical_json_bytes({'decision':'PASS','findings':[]})}
    for name,checkpoint in zip(('scope-closure-checkpoint.json','story-ac-checkpoint.json','task-checkpoint.json'),checkpoints):
        payloads[name]=canonical_json_bytes(checkpoint)
    render_refs=[]
    for item in renders['renders']:
        name='renders/'+item['path']; payloads[name]=decode_binary(item['bytes'])
        render_refs.append({'sheetKey':item['sheetKey'],'path':name,'sha256':item['sha256']})
    def binding(name): return {'path':name,'sha256':sha256_bytes(payloads[name])}
    manifest={'contract':'ai-sow-artifact-manifest-v2','runId':state['runId'],
        'candidateSha256':sha256_bytes(payloads['sow-model.json']), 'sourceManifestSha256':model['project']['sourceManifestSha256'],
        'stageCheckpointSha256s':[sha256_bytes(canonical_json_bytes(cp)) for cp in checkpoints],
        'reviewDecisionSha256':checkpoints[-1]['reviewDecisionSha256'],'templateSha256':sha256_bytes(payloads['sow-template.xlsx']),
        'effectivePolicyDecisionSha256':sha256_bytes(payloads['effective-policy-decision.json']),
        'taskCatalogSemanticSha256':catalog(template_path).semantic_sha256,'rendererContract':RENDERER_CONTRACT,
        'rendererSha256':sha256_bytes(payloads['renderer-fingerprint.json']),'workbook':binding('sow.xlsx'),'notes':binding('sow-notes.md'),
        'workbookVerification':{'trustState':'VERIFIED','engineName':'LibreOffice','engineVersion':calculated['office']['version']},
        'proofBundle':binding('proof-bundle.json'),'verification':binding('verification.json'),
        'structureFormulaSha256':sha256_bytes(canonical_json_bytes(verification['structureFormula'])),
        'priorStateSha256':checkpoints[0].get('priorStateSha256'),'office':calculated['office'],
        'visibleSheets':[r['sheetKey'] for r in render_refs],'renders':render_refs,'visualReview':{'attemptRecordSha256':visual_record_sha256}}
    if validate_contract(manifest,'artifact-approval.schema.json',SCHEMA_REGISTRY): raise ValueError('artifact manifest schema invalid')
    # Validate proof before exposing any approval manifest. Workbook has already been frozen for visual review.
    verify_artifact_proof(proof,model,manifest)
    for name,payload in payloads.items():
        if name=='sow.xlsx': freeze_workbook(files,root+'/'+name,payload,manifest['workbook']['sha256'])
        else: files.publish_new(root+'/'+name,payload)
    raw=canonical_json_bytes(manifest); digest=sha256_bytes(raw)
    # All dependent bytes are immutable before the manifest becomes addressable.
    _validate_artifact_contents(files,root,manifest)
    return canonical_json_bytes({'manifestPath':root+'/artifact-manifest.json','manifestSha256':digest,'manifest':manifest})


def _artifact_step_digest(events, kind, revision, *, fingerprint=None):
    matches=[e['payload'] for e in events if e['type']=='DETERMINISTIC_STEP_FINISHED'
        and e['payload']['outcome']=='SUCCEEDED' and e['payload'].get('stageKind')=='ARTIFACT'
        and e['payload'].get('semanticRevision')==revision and e['payload']['stepKind']==kind]
    if fingerprint is None:
        if not matches:raise ValueError('工件缺少实际步骤完成事实。')
        fingerprint=matches[-1].get('stepFingerprint')
    if fingerprint is None:
        raise ValueError('旧成功事件缺少完整指纹，不能由新生产路径复用。')
    hashes={e['outputSha256'] for e in matches if e.get('stepFingerprint')==fingerprint}
    if len(hashes)!=1:raise ValueError('相同工件输入与工具身份缺失或存在冲突输出。')
    return next(iter(hashes))
