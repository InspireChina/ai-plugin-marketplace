from __future__ import annotations
from action_ledger import effective_result, effective_result_bytes

from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path

from contracts import canonical_json_bytes, load_registry, sha256_bytes, validate_contract
from models import Diagnostic
from sow_model import validate as validate_sow_model


SKILL_ROOT = Path(__file__).resolve().parents[1]
STAGE_2_COLLECTIONS = frozenset(
    {"stories", "acceptanceCriteria", "deliveryAnnotations"}
)


def _diagnostic(code: str, message: str, path: str = "") -> Diagnostic:
    return Diagnostic(code=code, message=message, path=path, details={})


def _sort_diagnostics(values: Sequence[Diagnostic]) -> tuple[Diagnostic, ...]:
    return tuple(sorted(values, key=lambda item: (item.path, item.code, item.message)))


def _mappings(value: object) -> list[Mapping[str, object]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _ids(value: object) -> tuple[str, ...]:
    return tuple(item for item in value if isinstance(item, str)) if isinstance(value, list) else ()


def _unique(values: Sequence[object]) -> list[str]:
    result: list[str] = []
    for value in values:
        if isinstance(value, str) and value not in result:
            result.append(value)
    return result


def _policy_decision_map(
    model: Mapping[str, object],
    effective_policy_decisions: object,
) -> dict[str, str]:
    expected = {
        str(item["policyInstanceId"]): item
        for item in _mappings(model.get("policyInstances"))
        if isinstance(item.get("policyInstanceId"), str)
    }
    if isinstance(effective_policy_decisions, Mapping):
        raw = dict(effective_policy_decisions)
    elif isinstance(effective_policy_decisions, list):
        raw = {
            str(item.get("policyInstanceId")): item.get("decision")
            for item in _mappings(effective_policy_decisions)
        }
    else:
        raise ValueError("effective policy decisions must be a mapping or list")
    if set(raw) != set(expected) or any(
        value not in {"INCLUDED", "EXCLUDED"} for value in raw.values()
    ):
        raise ValueError("effective policy decisions must cover every policy instance")
    for policy_instance_id, decision in raw.items():
        policy = expected[policy_instance_id]
        if decision == "EXCLUDED" and policy.get("inclusionPolicy") in {
            "REQUIRED",
            "SOURCE_GATED",
        }:
            raise ValueError("required or source-gated policy instance cannot be excluded")
    return {key: str(raw[key]) for key in sorted(raw)}


def _story_boundary_key(
    closure: Mapping[str, object],
) -> str:
    qualifiers = [
        value
        for value in _ids(closure.get("preservedQualifiers"))
        if any(
            marker in value
            for marker in (
                "独立",
                "责任方",
                "验收边界",
                "发布边界",
                "定制",
                "custom",
                "responsibility",
                "acceptance",
                "release",
            )
        )
    ]
    boundary = {
        "assignedFeatureIds": list(_ids(closure.get("assignedFeatureIds"))),
        "crossFeatureRuleIds": list(_ids(closure.get("crossFeatureRuleIds"))),
        "crossFeatureTargetIds": list(
            _ids(closure.get("crossFeatureTargetIds"))
        ),
        "requiredQualifierRefs": list(
            _ids(closure.get("requiredQualifierRefs"))
        ),
        "independentQualifiers": qualifiers,
    }
    digest = sha256_bytes(canonical_json_bytes(boundary))[:16]
    return f"story-boundary-{digest}"


def _coverage_set(
    input_item: Mapping[str, object],
    closure: Mapping[str, object],
) -> list[str]:
    qualifiers = [
        *_ids(closure.get("preservedQualifiers")),
        *_ids(input_item.get("thresholds")),
        *_ids(input_item.get("applicableScopes")),
    ]
    if any("九个服务" in value for value in qualifiers):
        return [f"service-{index:02d}" for index in range(1, 10)]
    explicit = _unique(
        [
            *_ids(closure.get("requiredQualifierRefs")),
            *_ids(closure.get("crossFeatureTargetIds")),
        ]
    )
    return explicit or list(_ids(closure.get("assignedFeatureIds")))


def derive_story_obligations(
    model: Mapping[str, object],
    effective_policy_decisions: object,
) -> Mapping[str, object]:
    """Deterministically project frozen Stage 1 scope into Story/AC obligations."""
    decisions = _policy_decision_map(model, effective_policy_decisions)
    input_by_id = {
        str(item["inputItemId"]): item
        for item in _mappings(model.get("inputItems"))
        if isinstance(item.get("inputItemId"), str)
    }
    feature_by_id = {
        str(item["featureId"]): item
        for item in _mappings(model.get("features"))
        if isinstance(item.get("featureId"), str)
    }
    design_ids = {
        str(item["designItemId"])
        for item in _mappings(model.get("designItems"))
        if isinstance(item.get("designItemId"), str)
    }
    obligations: list[dict[str, object]] = []
    for closure in _mappings(model.get("scopeClosure")):
        if closure.get("deliveryDisposition") != "STORY_AC_REQUIRED":
            continue
        input_id = closure.get("inputItemId")
        input_item = input_by_id.get(str(input_id))
        if input_item is None:
            continue
        feature_ids = list(_ids(closure.get("assignedFeatureIds")))
        design_refs = _unique(
            [
                *(
                    value
                    for value in _ids(closure.get("targetNodeIds"))
                    if value in design_ids
                ),
                *(
                    ref
                    for feature_id in feature_ids
                    for ref in _ids(feature_by_id.get(feature_id, {}).get("designRefs"))
                ),
            ]
        )
        obligation_id = f"story-obligation-requirement-{input_id}"
        obligations.append(
            {
                "obligationId": obligation_id,
                "kind": "REQUIREMENT",
                "subjectId": input_id,
                "assignedFeatureIds": feature_ids,
                "requirementRefs": [input_id],
                "designRefs": design_refs,
                "policyRefs": [],
                "coverageSet": _coverage_set(input_item, closure),
                "qualifiers": list(_ids(closure.get("preservedQualifiers"))),
                "crossFeatureRuleIds": list(
                    _ids(closure.get("crossFeatureRuleIds"))
                ),
                "crossFeatureTargetIds": list(
                    _ids(closure.get("crossFeatureTargetIds"))
                ),
                "sourceRefs": deepcopy(list(_mappings(closure.get("sourceRefs")))),
                "storyBoundaryKey": _story_boundary_key(closure),
                "affinityKey": "feature-affinity-"
                + sha256_bytes(canonical_json_bytes(feature_ids))[:16],
            }
        )
    for instance in _mappings(model.get("policyInstances")):
        instance_id = instance.get("policyInstanceId")
        if not isinstance(instance_id, str) or decisions.get(instance_id) != "INCLUDED":
            continue
        targets = set(_ids(instance.get("targetNodeIds")))
        feature_ids = sorted({
            feature_id for feature_id, feature in feature_by_id.items()
            if feature_id in targets or feature.get("epicId") in targets
        })
        design_refs = _unique(
            [
                ref
                for feature_id in feature_ids
                for ref in _ids(feature_by_id.get(feature_id, {}).get("designRefs"))
            ]
        )
        obligations.append(
            {
                "obligationId": f"story-obligation-policy-{instance_id}",
                "kind": "DELIVERY_POLICY",
                "subjectId": instance_id,
                "assignedFeatureIds": feature_ids,
                "requirementRefs": [],
                "designRefs": design_refs,
                "policyRefs": [instance_id],
                "coverageSet": feature_ids,
                "qualifiers": [],
                "crossFeatureRuleIds": [],
                "crossFeatureTargetIds": [],
                "sourceRefs": deepcopy(list(_mappings(instance.get("sourceRefs")))),
                "storyBoundaryKey": f"story-boundary-policy-{instance_id}",
                "affinityKey": "feature-affinity-"
                + sha256_bytes(canonical_json_bytes(feature_ids))[:16],
            }
        )
    obligations.sort(key=lambda item: str(item["obligationId"]))
    routing = [
        {
            "obligationId": item["obligationId"],
            "kind": item["kind"],
            "assignedFeatureIds": item["assignedFeatureIds"],
            "storyBoundaryKey": item["storyBoundaryKey"],
            "affinityKey": item["affinityKey"],
        }
        for item in obligations
    ]
    projection_core = {
        "contract": "ai-sow-story-obligation-projection-v1",
        "algorithmVersion": "1",
        "effectivePolicyDecisions": decisions,
        "obligations": obligations,
        "obligationIds": [str(item["obligationId"]) for item in obligations],
        "routing": routing,
    }
    return {
        **projection_core,
        "projectionSha256": sha256_bytes(canonical_json_bytes(projection_core)),
    }


# Exact IR Owner boundary.
from dataclasses import dataclass
import json
from contracts import InvalidActionResult, load_schema_registry
from models import ContextRefDescriptor
from stage_planner import AtomicWorkItemDescriptor, make_planned_work


@dataclass(frozen=True)
class StoryInputs:
    scope_candidate_bytes: bytes
    checkpoint_bytes: bytes
    checkpoint_sha256: str
    work_items: tuple[AtomicWorkItemDescriptor, ...]
    context_refs: tuple[ContextRefDescriptor, ...]


class StoryInputRequired(ValueError):
    pass


def _canonical_object(payload):
    value = json.loads(payload)
    if not isinstance(value, dict) or canonical_json_bytes(value) != payload:
        raise ValueError('Story 输入必须是 canonical JSON object。')
    return value


def _scope_policy_decisions(model):
    excluded = {subject for item in model['decisions'] if item['kind'] == 'EXCLUDED_BY_USER'
                for subject in item['subjectIds']}
    return _policy_decision_map(model, {item['policyInstanceId']:
        'EXCLUDED' if item['policyInstanceId'] in excluded else 'INCLUDED' for item in model['policyInstances']})


def prepare_story_inputs(scope_candidate_bytes, checkpoint_bytes, *, checkpoint_sha256):
    """Consume the caller-resolved sealed Scope proof; never reopen upstream sources.

    Public checkpoint resolution/Review replay belongs to orchestration. This
    boundary checks current schema, exact authorized bytes and Scope projection.
    """
    from sow_model import owner_projection_sha256
    model, checkpoint = _canonical_object(scope_candidate_bytes), _canonical_object(checkpoint_bytes)
    registry = load_schema_registry(SKILL_ROOT)
    if (sha256_bytes(checkpoint_bytes) != checkpoint_sha256
            or validate_contract(checkpoint, 'stage-checkpoint.schema.json', registry)
            or checkpoint['stageKind'] != 'SCOPE'
            or checkpoint['candidateSha256'] != sha256_bytes(scope_candidate_bytes)
            or checkpoint['inputRevisionSha256'] != model['project']['inputRevisionSha256']
            or validate_sow_model(model, 'STAGE_1', registry=registry)):
        raise ValueError('Story 输入没有绑定有效的 sealed Scope checkpoint。')
    if any(model[collection] for collection in ('stories', 'acceptanceCriteria', 'deliveryAnnotations', 'tasks',
            'dependencies', 'effectiveStartMatches', 'estimationAnnotations')):
        raise ValueError('Story 基础投影只能包含 sealed Scope 写集合。')
    projection = derive_story_obligations(model, _scope_policy_decisions(model))
    facts = {item['inputItemId']: item for item in model['inputItems']}
    closures = {item['inputItemId']: item for item in model['scopeClosure']}
    features = {item['featureId']: item for item in model['features']}
    designs = {item['designItemId']: item for item in model['designItems']}
    policies = {item['policyInstanceId']: item for item in model['policyInstances']}
    bodies = []
    for obligation in projection['obligations']:
        if not obligation['assignedFeatureIds']:
            raise StoryInputRequired('Scope delivery obligation 没有具体 Feature，必须修正上游。')
        feature_ids = sorted(obligation['assignedFeatureIds'])
        if any(features[key]['scopeDecision'] != 'IN_SCOPE' for key in feature_ids):
            raise StoryInputRequired('非 IN_SCOPE Feature 不能产生 Story obligation。')
        policy = policies.get(obligation['subjectId']) if obligation['kind'] == 'DELIVERY_POLICY' else None
        shared_release = policy is not None and policy['policyId']=='policy-go-live'
        # One declared release policy keeps its full scope under one hierarchy
        # owner. Per-Feature projection must not manufacture release charges.
        for feature_id in feature_ids[:1] if shared_release else feature_ids:
            covered_features = feature_ids if shared_release else [feature_id]
            fact_ids = obligation['requirementRefs'] or sorted({key for covered in covered_features
                for key in features[covered]['requirementRefs']})
            if policy and policy['inclusionPolicy'] == 'SOURCE_GATED' or not fact_ids:
                anchors = {canonical_json_bytes(ref) for ref in obligation['sourceRefs']}
                fact_ids = [key for key, fact in facts.items() if anchors.intersection(
                    canonical_json_bytes(ref) for ref in fact['sourceRefs'])]
            if not fact_ids:
                raise StoryInputRequired('交付义务缺少可追溯的来源事实。')
            body = deepcopy(obligation)
            # All these fields are sets. Qualifier text/sequence is preserved.
            for field in ('assignedFeatureIds', 'requirementRefs', 'designRefs', 'policyRefs', 'coverageSet',
                          'crossFeatureRuleIds', 'crossFeatureTargetIds'):
                body[field] = sorted(body[field])
            body['assignedFeatureIds'] = covered_features
            if policy is None:
                # The obligation now belongs to one Feature. The original
                # multi-Feature assignment is applicability, not a distinct
                # outcome boundary within this Feature. Keep all independent
                # qualifiers and cross-Feature rule/target references intact.
                body['storyBoundaryKey'] = _story_boundary_key({
                    **closures[obligation['subjectId']], 'assignedFeatureIds':[feature_id]})
            body['designRefs'] = [key for key in body['designRefs']
                                  if set(covered_features).intersection(designs[key]['featureIds'])]
            body['coverageSet'] = [key for key in body['coverageSet'] if key not in features or key in covered_features]
            body['uatApplicable'] = policy is None or policy['policyId'] in {'policy-uat-automation', 'policy-data-migration'}
            if policy:
                from stable_ids import CONTROLLED_DISCRIMINATORS
                if policy['policyId'] not in CONTROLLED_DISCRIMINATORS['POLICY_INSTANCE']:
                    raise ValueError('Story 政策必须属于唯一受控政策表。')
                body['policyId'] = policy['policyId']
            body['sourceRefs'] = sorted(body['sourceRefs'], key=canonical_json_bytes)
            body.update(featureId=feature_id, sourceFactIds=sorted('fact:'+key for key in fact_ids))
            key = 'obligation-' + sha256_bytes(canonical_json_bytes(body))
            bodies.append({'contractVersion': 'story-obligation-v1', 'scopeDecisionKey': key, 'obligation': body})
    bodies.sort(key=lambda body: (body['obligation']['subjectId'], body['obligation']['featureId'], body['scopeDecisionKey']))
    items = tuple(AtomicWorkItemDescriptor(sha256_bytes(canonical_json_bytes(body)), 'STORY_AC',
        'SCOPE_CHECKPOINT', checkpoint_sha256, ordinal, body) for ordinal, body in enumerate(bodies))
    used_facts = {key for body in bodies for key in body['obligation']['sourceFactIds']}
    design_ids = {key for body in bodies for key in body['obligation']['designRefs']}
    feature_ids = {key for body in bodies for key in body['obligation']['assignedFeatureIds']}
    contexts = [ContextRefDescriptor('sealed-story-scope', canonical_json_bytes({
        'kind': 'STORY_SCOPE_CHECKPOINT', 'checkpointSha256': checkpoint_sha256,
        'candidateSha256': checkpoint['candidateSha256'], 'inputRevisionSha256': model['project']['inputRevisionSha256']}))]
    for key in sorted(facts):
        if 'fact:'+key in used_facts:
            contexts.append(ContextRefDescriptor('fact:'+key, canonical_json_bytes({
                'kind':'STORY_SOURCE_FACT', 'factKey':'fact:'+key, 'inputItem':facts[key]})))
    for key in sorted(feature_ids):
        contexts.append(ContextRefDescriptor('feature:'+key, canonical_json_bytes({
            'kind':'STORY_FEATURE', 'feature':features[key]})))
    for item in sorted(model['designItems'], key=lambda item:item['designItemId']):
        if item['designItemId'] in design_ids:
            contexts.append(ContextRefDescriptor('design:'+item['designItemId'], canonical_json_bytes({
                'kind':'STORY_DESIGN', 'designItem':item})))
    return StoryInputs(scope_candidate_bytes, checkpoint_bytes, checkpoint_sha256, items,
                       tuple(contexts) if items else ())


def _story_contexts_for_items(items, contexts):
    required = {'sealed-story-scope'} if items else set()
    for item in items:
        obligation = item.work_item_payload['obligation']
        required.update(obligation['sourceFactIds'])
        required.update('feature:'+key for key in obligation['assignedFeatureIds'])
        required.update('design:'+key for key in obligation['designRefs'])
    selected = [ref for ref in contexts if ref.ref_id in required]
    if {ref.ref_id for ref in selected} != required:
        raise ValueError('Story packet 缺少关联 context。')
    return selected


def build_story_work_descriptors(work_items, context_refs, budget_policy):
    """Declare independent Story work; the shared planner owns IDs and packing."""
    from stage_planner import estimate_work_input_tokens, StagePlanningBlocked, run_budget_policy_value
    from contracts import usable_action_input_tokens
    if any(item.action_kind != 'STORY_AC' or item.source_role != 'SCOPE_CHECKPOINT' for item in work_items):
        raise ValueError('Story 原子项必须来自 Scope checkpoint。')
    ordered = sorted(work_items, key=lambda item: (item.work_item_payload['obligation']['subjectId'],
        item.work_item_payload['obligation']['featureId'], item.work_item_payload['scopeDecisionKey']))
    if len({item.work_item_id for item in ordered}) != len(ordered):
        raise ValueError('Story 义务不得重复。')
    checkpoints = [json.loads(ref.canonical_content) for ref in context_refs if ref.ref_id == 'sealed-story-scope']
    if ordered and (len(checkpoints) != 1 or any(item.block_ordinal != ordinal
            or item.source_sha256 != checkpoints[0]['checkpointSha256'] for ordinal,item in enumerate(ordered))):
        raise ValueError('Story source hash/ordinal 必须由 sealed Scope 机械生成。')
    # Keep a compatible Feature boundary together so splitting by capacity does
    # not manufacture independently billable Stories. Different boundaries pack
    # by the same stable next-fit rule used by Scope.
    units = {}
    for item in ordered:
        body = item.work_item_payload
        if item.work_item_id != sha256_bytes(canonical_json_bytes(body)):
            raise ValueError('Story workItemId 必须绑定 versioned obligation body。')
        obligation = body['obligation']
        units.setdefault((obligation['featureId'], obligation['storyBoundaryKey']), []).append(item)
    usable = usable_action_input_tokens(run_budget_policy_value(budget_policy))
    works, current = [], []
    for unit in units.values():
        if current and estimate_work_input_tokens('STORY_AC', current + unit, _story_contexts_for_items(current + unit, context_refs), budget_policy) > usable:
            works.append(make_planned_work('STORY_AC', current, _story_contexts_for_items(current, context_refs), [])); current = []
        current += unit
        if estimate_work_input_tokens('STORY_AC', current, _story_contexts_for_items(current, context_refs), budget_policy) > usable:
            raise StagePlanningBlocked('BUDGET_EXHAUSTED')
    if current:
        works.append(make_planned_work('STORY_AC', current, _story_contexts_for_items(current, context_refs), []))
    return tuple(works)


def _story_packet_catalog(packet):
    contexts = [ref['canonicalContent'] for ref in packet['contextRefs']]
    checkpoints = [item for item in contexts if item.get('kind') == 'STORY_SCOPE_CHECKPOINT']
    if packet['workItems'] and len(checkpoints) != 1:
        raise ValueError('Story packet 必须绑定唯一 sealed Scope context。')
    obligations = {item['payload']['scopeDecisionKey']: item['payload']['obligation'] for item in packet['workItems']}
    fact_contexts = [item for item in contexts if item.get('kind') == 'STORY_SOURCE_FACT']
    facts = {item['factKey']: item['inputItem'] for item in fact_contexts}
    if len(obligations) != len(packet['workItems']) or len(facts) != len(fact_contexts):
        raise ValueError('冻结 Story packet 义务或事实身份重复。')
    return obligations, facts


def validate_bound_story_context(packet):
    """Prepare frozen context before the bytes-only pre-seal callback."""
    if set(packet) != {'workItems', 'contextRefs'}:
        raise ValueError('Story packet 只能包含 workItems/contextRefs。')
    obligations, facts = _story_packet_catalog(packet)
    registry = load_schema_registry(SKILL_ROOT)
    for ref in packet['contextRefs']:
        content = canonical_json_bytes(ref['canonicalContent'])
        if ref['contentSha256'] != sha256_bytes(content):
            raise ValueError('Story context hash 漂移。')
    for fact in facts.values():
        from jsonschema import Draft202012Validator
        # validate_contract handles whole models; resolve the exact existing node definition.
        if list(Draft202012Validator({'$ref': 'urn:ai-sow:generate:next:sow-model:1#/$defs/inputItem'},
                registry=registry).iter_errors(fact)):
            raise ValueError('Story 冻结事实不符合 inputItem schema。')
    if any(not set(item['sourceFactIds']).issubset(facts) for item in obligations.values()):
        raise ValueError('Story 冻结义务引用不存在的事实。')


def _story_decision_diagnostics(packet, result):
    obligations, facts = _story_packet_catalog(packet)
    diagnostics, adopted, story_keys, rule_keys = [], set(), set(), {}
    def add(code, path):
        diagnostics.append(Diagnostic(code=code, message='Story/AC 未满足冻结义务或来源绑定。', path=path,
            details={'subjectIds': [story['localKey']] if path.startswith('/stories/') else []}))
    for story in result['stories']:
        path = '/stories/'+story['localKey']
        if story['localKey'] in story_keys:
            add('STORY_LOCAL_KEY_DUPLICATE', path)
        story_keys.add(story['localKey'])
        keys = set(story['scopeDecisionKeys'])
        if not keys.issubset(obligations):
            add('STORY_SCOPE_KEY_NOT_AUTHORIZED', path)
        selected = [obligations[key] for key in sorted(keys & obligations.keys())]
        adopted.update(keys)
        allowed_facts = {key for item in selected for key in item['sourceFactIds']}
        story_facts = set(story['sourceFactIds'])
        if not story_facts.issubset(allowed_facts):
            add('STORY_FACT_NOT_AUTHORIZED', path)
        if story['actorKey'] not in story_facts or story['actorKey'] not in allowed_facts:
            add('STORY_ACTOR_NOT_AUTHORIZED', path)
        features = {item['featureId'] for item in selected}
        boundaries = {item['storyBoundaryKey'] for item in selected}
        if len(features) != 1 or len(boundaries) > 1:
            add('INDEPENDENT_STORY_BOUNDARIES_MERGED', path)
        local_keys, criteria = set(), story['acceptanceCriteria']
        for ac in criteria:
            if ac['localKey'] in local_keys:
                add('STORY_LOCAL_KEY_DUPLICATE', path+'/'+ac['localKey'])
            local_keys.add(ac['localKey'])
            if not set(ac['sourceFactIds']).issubset(story_facts & allowed_facts):
                add('STORY_FACT_NOT_AUTHORIZED', path+'/'+ac['localKey'])
            signature = (tuple(sorted(features)), tuple(sorted(ac['sourceFactIds'])), ac['condition'])
            if signature in rule_keys:
                add('STORY_RULE_DUPLICATE' if rule_keys[signature] == ac['observableResult'] else 'STORY_RULE_CONTRADICTORY', path+'/'+ac['localKey'])
            rule_keys[signature] = ac['observableResult']
        for obligation in selected:
            required_facts = set(obligation['sourceFactIds'])
            matching = [ac for ac in criteria if required_facts.intersection(ac['sourceFactIds'])]
            covered = {key for ac in matching for key in ac['sourceFactIds']}
            if not required_facts.issubset(story_facts) or not required_facts.issubset(covered):
                add('STORY_OBLIGATION_UNCLOSED', path+'/'+obligation['obligationId'])
            combined = '\n'.join(ac['condition']+'\n'+ac['observableResult'] for ac in matching)
            if any(qualifier not in combined for qualifier in obligation['qualifiers']):
                add('STORY_QUALIFIER_MISSING', path+'/'+obligation['obligationId'])
    for key in sorted(obligations.keys() - adopted):
        add('STORY_OBLIGATION_UNCLOSED', '/obligations/'+key)
    return _sort_diagnostics(diagnostics)


def verify_story_ac_decision(packet, result):
    validate_bound_story_context(packet)
    diagnostics = validate_contract(result, 'story-ac-decision.schema.json', load_schema_registry(SKILL_ROOT))
    return diagnostics or _story_decision_diagnostics(packet, result)


def validate_bound_story_result(packet, normalized_result):
    # finish already performed strict parsing, exact schema validation and the
    # sole set normalization. This core does no schema reads or other I/O.
    result = json.loads(normalized_result)
    from candidate_repair import repair_baseline, preserve_roots
    baseline = repair_baseline(packet, 'STORY_AC-v1')
    if baseline is not None:
        previous, diagnostic = baseline
        if diagnostic['code'] == 'STORY_DECISION_INVALID':
            missing = {item['path'].removeprefix('/obligations/') for item in diagnostic.get('findings', [])
                       if item['path'].startswith('/obligations/')}
            authorized = missing | {key for row in previous['stories']
                if row['localKey'] in diagnostic['subjectIds'] for key in row['scopeDecisionKeys']}
            preserve_roots(previous, result, 'stories', set(diagnostic['subjectIds']),
                allow_new=lambda row: bool(row['scopeDecisionKeys']) and set(row['scopeDecisionKeys']) <= authorized)
    diagnostics = _story_decision_diagnostics(packet, result)
    if diagnostics:
        from models import AttemptDiagnostic
        findings = tuple(AttemptDiagnostic(item.code, item.path, tuple(item.details.get('subjectIds', ()))) for item in diagnostics)
        raise InvalidActionResult('Story/AC 未关闭已授权的义务/来源绑定。', diagnostic=AttemptDiagnostic(
            'STORY_DECISION_INVALID', '/stories', tuple(sorted({key for item in findings for key in item.subject_ids})), findings))


@dataclass(frozen=True)
class StoryMaterialization:
    candidate_bytes: bytes
    candidate_sha256: str
    scope_candidate_bytes: bytes
    checkpoint_sha256: str
    packet_bytes: bytes
    decision_bytes: bytes


def _complete_story_results(inputs, plan, ledger, budget_policy):
    from stage_planner import validate_stage_plan, materialize_packet, _effective_envelope
    from action_ledger import build_attempt_repair_context
    expected = prepare_story_inputs(inputs.scope_candidate_bytes, inputs.checkpoint_bytes,
                                    checkpoint_sha256=inputs.checkpoint_sha256)
    if (sorted(inputs.work_items, key=lambda item:item.work_item_id) != sorted(expected.work_items, key=lambda item:item.work_item_id)
            or sorted(inputs.context_refs, key=lambda ref:ref.ref_id) != sorted(expected.context_refs, key=lambda ref:ref.ref_id)):
        raise ValueError('Story work/context 不是 sealed Scope 的确定性投影。')
    descriptors = build_story_work_descriptors(inputs.work_items, inputs.context_refs, budget_policy)
    validate_stage_plan(plan, inputs.work_items, inputs.context_refs, descriptors, [inputs.checkpoint_sha256], budget_policy)
    scope = json.loads(inputs.scope_candidate_bytes)
    checkpoint = json.loads(inputs.checkpoint_bytes)
    results = []
    for work in plan['works']:
        key, packet_plan = work['logicalWorkId'], work['packetPlan']
        envelope = _effective_envelope(ledger, key)
        if envelope is None or effective_result_bytes(ledger,key) is None:
            raise StoryInputRequired('Story plan 尚有未 sealed 的 LogicalWork。')
        _, record = effective_result(ledger, key)
        if (envelope.value['actionContractId'] != packet_plan['actionContractId']
                or envelope.value['actionContractSha256'] != packet_plan['actionContractSha256']
                or envelope.value['inputRevisionSha256'] != scope['project']['inputRevisionSha256']
                or envelope.value['baseCandidateSha256'] != sha256_bytes(inputs.scope_candidate_bytes)
                or len({item.value['runId'] for item in ledger.envelopes_by_sha256.values()}) != 1):
            raise ValueError('Story effective Attempt 未绑定本轮 Scope/合同。')
        normalized = ledger.normalized_results[record.normalized_result_sha256]
        if sha256_bytes(normalized) != record.normalized_result_sha256:
            raise ValueError('Story normalized result hash 漂移。')
        repair = None
        if envelope.value['revision'] > 1:
            failed = [digest for digest, item in ledger.attempt_records.items()
                      if item.logical_work_id == key and item.revision == envelope.value['revision'] - 1 and item.failure_kind in {'INVALID_JSON', 'INVALID_IR'}]
            if len(failed) != 1:
                raise ValueError('Story revision 2 没有唯一 INVALID_IR Attempt。')
            repair = build_attempt_repair_context(key, failed[0], ledger.attempt_records, ledger.raw_outputs,
                envelopes_by_sha256=ledger.envelopes_by_sha256)
        packet_bytes = materialize_packet(plan, key, envelope.value['revision'], inputs.work_items, inputs.context_refs, [], ledger, repair)
        if sha256_bytes(packet_bytes) != envelope.value['packetSha256']:
            raise ValueError('Story Attempt 未绑定实际计划 packet。')
        packet, result = json.loads(packet_bytes), json.loads(normalized)
        if verify_story_ac_decision(packet, result):
            raise InvalidActionResult('Story sealed IR 未关闭当前义务。')
        results.append((key, result))
    return results


def _story_source_refs(facts, fact_keys):
    refs = {canonical_json_bytes(ref): ref for key in fact_keys for ref in facts[key]['sourceRefs']}
    return [refs[key] for key in sorted(refs)]


def _story_coverage_fields(obligations):
    return {field: sorted({key for item in obligations for key in item[field]})
            for field in ('coverageSet', 'requirementRefs', 'designRefs', 'policyRefs')}


def materialize_story_candidate(inputs, plan, ledger, budget_policy, *, semantic_repair=None, semantic_repairs=None):
    """Deterministic conversion of a fully sealed Author revision.

    Review/Repair scheduling and avoiding conversion on public resume remain the
    existing checkpoint owner's responsibility; this does not create a receipt.
    """
    results = _complete_story_results(inputs, plan, ledger, budget_policy)
    packet = {'workItems': [{'workItemId': item.work_item_id, 'payload': item.work_item_payload} for item in inputs.work_items],
        'contextRefs': [{'refId': ref.ref_id, 'canonicalContent': json.loads(ref.canonical_content),
                         'contentSha256': sha256_bytes(ref.canonical_content)} for ref in inputs.context_refs]}
    obligations, facts = _story_packet_catalog(packet)
    joined = {'stories': []}
    for key, result in results:
        for original in result['stories']:
            story = deepcopy(original)
            story['localKey'] = key+':'+story['localKey']
            joined['stories'].append(story)
    repairs=semantic_repairs if semantic_repairs is not None else ([semantic_repair] if semantic_repair else [])
    for repair in repairs:
        from final_review import replace_owner_decisions
        joined = replace_owner_decisions('STORY_AC', joined, *repair)
    diagnostics = _story_decision_diagnostics(packet, joined)
    if diagnostics:
        raise InvalidActionResult('Story 完整 IR union 存在重复/矛盾规则或未关闭义务。')
    model = json.loads(inputs.scope_candidate_bytes)
    for collection, node in _story_node_bindings(packet, joined):
        model[collection].append(node)
    for collection, key in (('stories','storyId'), ('acceptanceCriteria','acceptanceCriterionId')):
        model[collection].sort(key=lambda item: item[key])
    joined['stories'].sort(key=lambda item: item['localKey'])
    return StoryMaterialization(canonical_json_bytes(model), sha256_bytes(canonical_json_bytes(model)), inputs.scope_candidate_bytes, inputs.checkpoint_sha256,
        canonical_json_bytes(packet), canonical_json_bytes(joined))


def _story_node_bindings(packet, joined):
    """Derive single-node bindings; no ledger, planning or candidate assembly."""
    from stable_ids import stable_entity_id
    obligations, facts = _story_packet_catalog(packet)
    identities = set()
    def identity(kind, parent, refs, actor_refs=(), policy_ids=()):
        anchors = [canonical_json_bytes({'role':'SOURCE', 'sourceRef':ref}).decode() for ref in refs]
        anchors += [canonical_json_bytes({'role':'ACTOR', 'sourceRef':ref}).decode() for ref in actor_refs]
        anchors += [canonical_json_bytes({'role':'POLICY', 'policyId':policy_id, 'sourceRef':ref}).decode()
                    for policy_id in sorted(set(policy_ids)) for ref in refs]
        key = stable_entity_id('story-ac-id-v1', kind, parent, anchors,
                               ('DELIVERABLE_OUTCOME' if kind == 'STORY' else 'OBSERVABLE_RESULT',))
        if key in identities:
            raise StoryInputRequired('Story/AC 来源身份碰撞；需要可区分的证据锚点，不能使用序号或名称后缀。')
        identities.add(key)
        return key
    for story in joined['stories']:
        selected = [obligations[key] for key in story['scopeDecisionKeys']]
        feature_id = selected[0]['featureId']
        source_refs = _story_source_refs(facts, story['sourceFactIds'])
        story_id = identity('STORY', feature_id, source_refs, _story_source_refs(facts, [story['actorKey']]),
                            [item['policyId'] for item in selected if item['kind'] == 'DELIVERY_POLICY'])
        yield 'stories', ({'storyId': story_id, 'featureId': feature_id, 'name': story['deliverableOutcome'],
            'sourceRefs': source_refs, 'uatApplicable': any(item['uatApplicable'] for item in selected), **_story_coverage_fields(selected)})
        for criterion in story['acceptanceCriteria']:
            ac_refs = _story_source_refs(facts, criterion['sourceFactIds'])
            ac_obligations = [item for item in selected if set(item['sourceFactIds']).intersection(criterion['sourceFactIds'])]
            ac_id = identity('ACCEPTANCE_CRITERION', story_id, ac_refs)
            yield 'acceptanceCriteria', ({'acceptanceCriterionId': ac_id, 'storyId': story_id,
                'text': '当'+criterion['condition']+'；'+criterion['observableResult'],
                'sourceRefs': ac_refs, **_story_coverage_fields(ac_obligations)})


def validate_story_candidate(material):
    """Complete mechanical validation, independently callable after materialize."""
    model, scope = json.loads(material.candidate_bytes), json.loads(material.scope_candidate_bytes)
    diagnostics = list(validate_sow_model(model, 'STAGE_2', registry=load_schema_registry(SKILL_ROOT)))
    if sha256_bytes(material.candidate_bytes) != material.candidate_sha256:
        diagnostics.append(_diagnostic('STORY_CANDIDATE_HASH_MISMATCH', '候选不再是本次物化的精确字节。'))
    for collection, value in scope.items():
        if collection not in STAGE_2_COLLECTIONS and model.get(collection) != value:
            diagnostics.append(_diagnostic('STAGE_2_WRITE_SCOPE', 'Story 不得修改 sealed 上游。', '/'+collection))
    packet, decisions = json.loads(material.packet_bytes), json.loads(material.decision_bytes)
    expected = {collection: {} for collection in STAGE_2_COLLECTIONS}
    for collection, node in _story_node_bindings(packet, decisions):
        key = node['storyId'] if collection == 'stories' else node['acceptanceCriterionId']
        expected[collection][key] = node
    for collection, field in (('stories','storyId'), ('acceptanceCriteria','acceptanceCriterionId'), ('deliveryAnnotations','annotationId')):
        actual = {node[field]: node for node in model[collection]}
        if actual != expected[collection]:
            diagnostics.append(_diagnostic('STORY_NODE_IR_BINDING_MISMATCH',
                'Story/AC 节点字段、身份、SourceRef 或 annotation 不匹配 sealed IR。', '/'+collection))
    for story in model['stories']:
        criteria = [item for item in model['acceptanceCriteria'] if item['storyId'] == story['storyId']]
        if not criteria:
            diagnostics.append(_diagnostic('STORY_AC_MINIMUM', '每个 Story 至少一条完整关闭义务的 AC。', '/stories/'+story['storyId']))
    diagnostics.extend(_story_decision_diagnostics(json.loads(material.packet_bytes), json.loads(material.decision_bytes)))
    return _sort_diagnostics(diagnostics)


def publish_story_candidate(files, run_id, material):
    digest = sha256_bytes(material.candidate_bytes)
    if digest != material.candidate_sha256:
        raise ValueError('Story candidate hash 漂移。')
    files.publish_new(f'.ai-sow/work/runs/{run_id}/stages/STORY_AC/candidates/{digest}.json', material.candidate_bytes)
    return {'candidateSha256': digest}


def diagnose_candidate(action_kind, packet, candidate, **owner_context):
    from candidate_repair import schema_issues, diagnostic_report, issues_from_diagnostics
    raw=candidate if isinstance(candidate,bytes) else canonical_json_bytes(candidate);value=json.loads(raw)
    issues=schema_issues(owner_context.get('action_contract_id','STORY_AC-v1'),value,'STORY_AC')
    blocked=[];domains=['SCHEMA']
    try:
        diagnostics=_story_decision_diagnostics(packet,value)
    except (KeyError,TypeError,IndexError):
        blocked.append('STORY_BINDINGS')
    else:
        issues+=issues_from_diagnostics(diagnostics,'STORY_AC',value);domains.append('STORY_BINDINGS')
    return diagnostic_report(raw,issues,owner='STORY_AC',checker_file=__file__,packet=packet,
        origin=owner_context.get('origin'),blocked=blocked,domains=domains)


def plan_candidate_repair(action_kind, packet, candidate, report, *, origin, **owner_context):
    from candidate_repair import group_fields, build_repair_plan
    value=json.loads(candidate) if isinstance(candidate,bytes) else candidate
    obligations,_=_story_packet_catalog(packet)
    fields={'STORY_SCOPE_KEY_NOT_AUTHORIZED':['scopeDecisionKeys'], 'STORY_FACT_NOT_AUTHORIZED':['sourceFactIds'],
        'STORY_ACTOR_NOT_AUTHORIZED':['actorKey'],
        'STORY_OBLIGATION_UNCLOSED':['sourceFactIds'],
        'STORY_RULE_DUPLICATE':['condition','observableResult'], 'STORY_RULE_CONTRADICTORY':['condition','observableResult']}
    selected={};qualifier_appends=[]
    for issue in report['issues']:
        path=issue['paths'][0];parts=path.split('/');story_index=None
        if len(parts)>2 and parts[1]=='stories' and not parts[2].isdigit():
            matches=[i for i,row in enumerate(value['stories']) if row['localKey']==parts[2]]
            if len(matches)!=1:continue
            story_index=matches[0];path='/stories/'+str(story_index)
            if len(parts)>3:
                ac=[i for i,row in enumerate(value['stories'][story_index]['acceptanceCriteria']) if row['localKey']==parts[3]]
                if len(ac)==1:path+='/acceptanceCriteria/'+str(ac[0])
        if issue['code']=='STORY_QUALIFIER_MISSING' and story_index is not None:
            obligation=next((row for row in obligations.values() if row['obligationId']==parts[3]),None)
            if obligation is None:continue
            required=set(obligation['sourceFactIds'])
            matching=[i for i,row in enumerate(value['stories'][story_index]['acceptanceCriteria'])
                      if required.intersection(row['sourceFactIds'])]
            if matching:
                selected[issue['issueId']]=[
                    f'/stories/{story_index}/acceptanceCriteria/{i}/{field}'
                    for i in matching for field in ('condition','observableResult')]
            else:
                qualifier_appends.append((issue,story_index,obligation))
            continue
        selected[issue['issueId']]=[path+'/'+field for field in fields[issue['code']]] if issue['code'] in fields else [path]
    contract_id=owner_context.get('action_contract_id','STORY_AC-v1')
    groups=group_fields(candidate,report,contract_id,selected)
    for group in groups:
        qualifier_ids=set(group['issueIds']) & {issue['issueId'] for issue in report['issues'] if issue['code']=='STORY_QUALIFIER_MISSING'}
        if qualifier_ids:
            choice='qualifier-'+next(iter(qualifier_ids))
            for slot in group['slots']:
                slot['alternativeSet']=choice
    from candidate_repair import append_object_group,transform_roots_group,schema_at,index_candidate
    raw=candidate if isinstance(candidate,bytes) else canonical_json_bytes(candidate)
    for issue,story_index,obligation in qualifier_appends:
        story=value['stories'][story_index]
        schema=schema_at(contract_id,'/stories/0/acceptanceCriteria/0')
        schema={**schema,'properties':{**schema['properties'],
            'localKey':{'type':'string','pattern':'^'+re.escape(story['localKey']+':ac:repair:')},
            'sourceFactIds':{'const':sorted(obligation['sourceFactIds'])}}}
        groups.append(append_object_group(raw,f'stories/{story_index}/acceptanceCriteria',schema,
            [issue['issueId']],group_id='qualifier-'+issue['issueId']))
    for issue in report['issues']:
        if issue['code']=='STORY_OBLIGATION_UNCLOSED' and issue['paths'][0].startswith('/obligations/'):
            key=issue['paths'][0].removeprefix('/obligations/')
            schema=schema_at(contract_id,'/stories/0')
            schema={**schema,'properties':{**schema['properties'],'scopeDecisionKeys':{'const':[key]}}}
            groups.append(append_object_group(raw,'stories',schema,[issue['issueId']],group_id='missing-'+issue['issueId']))
        elif issue['code']=='INDEPENDENT_STORY_BOUNDARIES_MERGED':
            key=issue['paths'][0].split('/')[2]
            entries=[e for e in index_candidate(raw,inherited=report.get('objectIndex',())) if e['objectId']=='stories/'+key]
            if entries:
                row=value['stories'][int(entries[0]['path'].split('/')[2])]
                schema=schema_at(contract_id,'/stories/0')
                schema={**schema,'properties':{**schema['properties'],'scopeDecisionKeys':{'type':'array','items':{'enum':row['scopeDecisionKeys']},'minItems':1,'uniqueItems':True}}}
                groups.append(transform_roots_group(raw,entries,schema,[issue['issueId']],namespace=key+':repair:',maximum=len(row['scopeDecisionKeys'])))
    if not groups:raise InvalidActionResult('Story 问题需要精确 root 变换或真实输入，不能改写其它 Story。')
    return build_repair_plan(raw,report,groups,origin=origin)


def candidate_repair_context(action_kind, packet, candidate, plan, group):
    value=json.loads(candidate);index={r['objectId']:r for r in plan['objectIndex']};keys=set()
    for slot in group['slots']:
        path=index.get(slot['objectId'],{}).get('path')
        if path:
            parts=path.split('/')
            if len(parts)>2 and parts[1]=='stories':keys.update(value['stories'][int(parts[2])]['scopeDecisionKeys'])
        collection=slot['collection'].split('/')
        if len(collection)>1 and collection[0]=='stories' and collection[1].isdigit():
            keys.update(value['stories'][int(collection[1])]['scopeDecisionKeys'])
        const=slot.get('valueSchema',{}).get('properties',{}).get('scopeDecisionKeys',{}).get('const')
        if isinstance(const,list):keys.update(const)
    items=[item['payload'] for item in packet['workItems'] if item['payload']['scopeDecisionKey'] in keys]
    facts={key for item in items for key in item['obligation']['sourceFactIds']}
    return [{'kind':'OWNER_OBLIGATION','value':item} for item in items]+[
        ref['canonicalContent'] for ref in packet['contextRefs'] if ref['canonicalContent'].get('factKey') in facts]
