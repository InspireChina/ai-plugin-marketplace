from __future__ import annotations
from action_ledger import effective_result, effective_result_bytes

from collections import defaultdict
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path

from contracts import InvalidActionResult, canonical_json_bytes, load_registry, sha256_bytes, validate_contract
from models import Diagnostic, TaskStandardCatalog
from sow_model import validate as validate_sow_model
from task_standard_catalog import hydrate


SKILL_ROOT = Path(__file__).resolve().parents[1]
STAGE_3_COLLECTIONS = frozenset(
    {"tasks", "dependencies", "effectiveStartMatches", "estimationAnnotations"}
)


def _diagnostic(code: str, message: str, path: str = "") -> Diagnostic:
    return Diagnostic(code=code, message=message, path=path, details={})


def _sort(values: Sequence[Diagnostic]) -> tuple[Diagnostic, ...]:
    return tuple(sorted(values, key=lambda item: (item.path, item.code, item.message)))


def _mappings(value: object) -> list[Mapping[str, object]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _ids(value: object) -> tuple[str, ...]:
    return tuple(item for item in value if isinstance(item, str)) if isinstance(value, list) else ()


def _task_coverage_diagnostics(model: Mapping[str, object]) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    tasks = _mappings(model.get("tasks"))
    matches = {
        str(item.get("taskId")): item
        for item in _mappings(model.get("effectiveStartMatches"))
    }
    criteria_by_story: defaultdict[str, set[str]] = defaultdict(set)
    for criterion in _mappings(model.get("acceptanceCriteria")):
        criteria_by_story[str(criterion.get("storyId"))].add(
            str(criterion.get("acceptanceCriterionId"))
        )
    for story in _mappings(model.get("stories")):
        story_id = str(story.get("storyId"))
        story_tasks = [item for item in tasks if criteria_by_story[story_id].intersection(
            _ids(item.get("acceptanceCriterionIds")))]
        covered = {
            ac_id
            for task in story_tasks
            for ac_id in _ids(task.get("acceptanceCriterionIds"))
        }
        if not story_tasks or not criteria_by_story[story_id].issubset(covered):
            diagnostics.append(
                _diagnostic(
                    "TASK_STORY_AC_COVERAGE_INCOMPLETE",
                    "每个 Story 的全部 AC 必须由至少一个实际 Task 覆盖。",
                    f"/stories/{story_id}",
                )
            )
        for field, task_field, code in (
            ("designRefs", "designItemIds", "TASK_STORY_DESIGN_COVERAGE_INCOMPLETE"),
            ("policyRefs", "policyInstanceIds", "TASK_STORY_POLICY_COVERAGE_INCOMPLETE"),
        ):
            required = set(_ids(story.get(field)))
            actual = {
                value
                for task in story_tasks
                for value in _ids(task.get(task_field))
            }
            if not required.issubset(actual):
                diagnostics.append(
                    _diagnostic(
                        code,
                        "Story 引用的批准设计与交付政策必须由覆盖其 AC 的 Task 落实。",
                        f"/stories/{story_id}/{field}",
                    )
                )
    for integration in _mappings(model.get("integrations")):
        integration_id = str(integration.get("integrationId"))
        owners = [
            task
            for task in tasks
            if integration_id in task.get("integrationIds", [])
            and task.get("workTypeId") in {"IN-INTEGRATION", "IN-IDENTITY"}
        ]
        if len(owners) != 1:
            diagnostics.append(
                _diagnostic(
                    "TASK_INTEGRATION_OWNER_NON_UNIQUE",
                    "每个已批准 Integration 必须由唯一集成 Task 负责。",
                    f"/integrations/{integration_id}",
                )
            )
    for task in tasks:
        task_id = str(task.get("taskId"))
        decision = matches.get(task_id, {}).get("decision")
        expected = {
            "新建": "NO_MATCH_NEW",
            "调整": "MATCHED_ADJUSTMENT",
            "接入复用": "MATCHED_REUSE",
        }.get(str(task.get("workMode")))
        if decision != expected:
            diagnostics.append(
                _diagnostic(
                    "TASK_EFFECTIVE_START_MODE_MISMATCH",
                    "Task 与 Effective Start decision 不一致。",
                    f"/tasks/{task_id}/workMode",
                )
            )
    if set(matches) != {str(item.get("taskId")) for item in tasks}:
        diagnostics.append(
            _diagnostic(
                "TASK_EFFECTIVE_START_SET_MISMATCH",
                "每个 Task 必须恰有一个 Effective Start decision。",
                "/effectiveStartMatches",
            )
        )
    return _sort(diagnostics)


# Exact TaskDecisionIR boundary.
from dataclasses import dataclass
import json
from contracts import InvalidActionResult, load_schema_registry
from models import ContextRefDescriptor
from stage_planner import AtomicWorkItemDescriptor, make_planned_work
from task_standard_catalog import decision_catalog


@dataclass(frozen=True)
class TaskInputs:
    story_candidate_bytes: bytes
    checkpoint_bytes: bytes
    checkpoint_sha256: str
    input_revision_bytes: bytes
    task_catalog: TaskStandardCatalog
    work_items: tuple[AtomicWorkItemDescriptor, ...]
    context_refs: tuple[ContextRefDescriptor, ...]
    prior_state_bytes: bytes | None = None
    prior_state_sha256: str | None = None
    change_graph_bytes: bytes | None = None
    change_graph_sha256: str | None = None


class TaskInputRequired(ValueError):
    pass


class TaskIdentityCollision(TaskInputRequired):
    def __init__(self, first_key, second_key):
        super().__init__('Task 来源身份碰撞；需要独立技术对象证据，不能使用名称或序号后缀。')
        self.subject_ids = tuple(sorted((first_key, second_key)))


def task_review_rules(candidate, task_catalog):
    """Bind the candidate's selected full rules for independent semantic Review."""
    if candidate['project']['templateSha256'] != task_catalog.template_sha256:
        raise ValueError('Task Review 模板与候选不一致。')
    rules = {row['workTypeId']: row for row in decision_catalog(task_catalog)}
    selected = set()
    for task in candidate['tasks']:
        key = task['workTypeId']
        if key not in rules or task['rowSemanticSha256'] != rules[key]['rowSemanticSha256']:
            raise ValueError('Task Review 工作类型或行 hash 与本轮模板不一致。')
        selected.add(key)
    return {'kind': 'TASK_RULES', 'templateSha256': task_catalog.template_sha256,
        'catalogSemanticSha256': task_catalog.task_catalog_semantic_sha256,
        'rows': [rules[key] for key in sorted(selected)]}


def factor_task_repair_packet(packet):
    """Send repeated sealed Story values once without changing their meaning."""
    validate_bound_task_context(packet)
    factored = deepcopy(packet)
    stories = {}
    for item in factored['workItems']:
        story = item['payload']['story']
        digest = sha256_bytes(canonical_json_bytes(story))
        stories[digest] = story
        item['payload']['story'] = {'storyRef': digest}
    return {'contract': 'ai-sow-task-repair-context-v1',
        'packetSha256': sha256_bytes(canonical_json_bytes(packet)),
        'packet': factored, 'stories': {key: stories[key] for key in sorted(stories)}}


def expand_task_repair_packet(value):
    """Restore and verify the exact bound Owner packet before any validation."""
    if value.get('contract') != 'ai-sow-task-repair-context-v1':
        validate_bound_task_context(value)
        return deepcopy(value)
    if set(value) != {'contract', 'packetSha256', 'packet', 'stories'}:
        raise ValueError('Task Repair context 字段不完整或包含额外字段。')
    stories = value['stories']
    if not isinstance(stories, dict) or any(sha256_bytes(canonical_json_bytes(story)) != key
                                           for key, story in stories.items()):
        raise ValueError('Task Repair Story 字典 hash 漂移。')
    packet = deepcopy(value['packet'])
    used = set()
    for item in packet['workItems']:
        reference = item['payload'].get('story')
        if not isinstance(reference, dict) or set(reference) != {'storyRef'} or reference['storyRef'] not in stories:
            raise ValueError('Task Repair 缺失精确 Story 引用。')
        used.add(reference['storyRef'])
        item['payload']['story'] = deepcopy(stories[reference['storyRef']])
    if set(stories) != used or sha256_bytes(canonical_json_bytes(packet)) != value['packetSha256']:
        raise ValueError('Task Repair 展开结果与原 Owner packet 不一致。')
    validate_bound_task_context(packet)
    return packet


# Source authority only. The template alone defines selection/calculation rules.
_UI_WORK_TYPES = frozenset({'FE-VIEW', 'FE-EDIT', 'FE-FLOW', 'FE-DASHBOARD', 'FE-UI-COMPONENT'})
_TECHNICAL_ROLES = frozenset({'HLD', 'ADR', 'SUPPLEMENT', 'QUESTION_ANSWER'})


def _current_task_start_contexts(packet, model, revision, target_keys):
    """Offer source-bound counterpart commitments, never infer an existing vendor implementation."""
    _, targets, _, _ = _task_packet_catalog(packet)
    sources = {row['sourceId']: row for row in revision['sources']}
    blocks = {(row['sourceId'], row['blockId']): row for row in revision['blocks']}
    def approved(ref, roles):
        source = sources.get(ref['sourceId'], {})
        block = blocks.get((ref['sourceId'], ref['blockId']), {})
        return (source.get('status') == 'APPROVED' and source.get('role') in roles
                and (block.get('contentSha256'), block.get('locator')) == (ref['sha256'], ref['locator']))
    facts = {row['inputItemId']: row for row in model['inputItems']}
    integrations = {row['integrationId']: row for row in model['integrations']}
    result = []
    for target_key in sorted(target_keys):
        target = targets.get(target_key)
        if target is None or target['targetKind'] != 'INTEGRATION': continue
        integration = integrations.get(target['nodeId'])
        if (integration is None or integration['counterpartyBoundary'] != 'EXTERNAL'
                or not integration['responsibilityBoundaryIds']
                or not any(approved(ref, _TECHNICAL_ROLES) for ref in target['sourceRefs'])): continue
        scope = {target['nodeId'], *integration['featureIds']}
        scope.update(row['epicId'] for row in model['features'] if row['featureId'] in scope)
        anchors = set(map(canonical_json_bytes, integration['sourceRefs']))
        for closure in model['scopeClosure']:
            fact = facts[closure['inputItemId']]
            if (closure['disposition'] != 'PROJECT_GATE' or fact['kind'] != 'ASSUMPTION'
                    or not scope.intersection(closure['targetNodeIds'])
                    or not anchors.intersection(map(canonical_json_bytes, fact['sourceRefs']))
                    or not all(approved(ref, {'PRD', *_TECHNICAL_ROLES}) for ref in fact['sourceRefs'])): continue
            key = 'current:' + sha256_bytes(canonical_json_bytes([fact['inputItemId'], target_key]))
            result.append({'kind':'TASK_EFFECTIVE_START','evidenceId':key,'entityId':fact['inputItemId'],
                'basis':'CURRENT_RESPONSIBILITY_COMMITMENT','summary':fact['text'],'commitment':deepcopy(fact),
                'targetKeys':[target_key],'modes':['接入复用'],'sourceRefs':deepcopy(fact['sourceRefs']),
                'responsibilityBoundaryIds':integration['responsibilityBoundaryIds'],
                'interpretation':'仅为现有对端可使用的责任承诺候选；不是供应商侧集成已实现的证明。保留全部条件，结合模板和原文判断是否适用。'})
    return result


def prepare_task_repair_packet(packet, original, review, story_candidate_bytes, input_revision_bytes, resolution=None):
    from final_review import repair_root_keys, is_manual_repair, resolution_field
    validate_bound_task_context(packet)
    model, revision = map(_task_object, (story_candidate_bytes, input_revision_bytes))
    checkpoint = next(ref['canonicalContent'] for ref in packet['contextRefs']
                      if ref['canonicalContent'].get('kind') == 'TASK_STORY_CHECKPOINT')
    if (checkpoint['candidateSha256'] != sha256_bytes(story_candidate_bytes)
            or checkpoint['inputRevisionSha256'] != sha256_bytes(input_revision_bytes)):
        raise ValueError('Task Repair 补充上下文必须绑定同一 sealed Story 与 revision。')
    roots = set(repair_root_keys('TASK', original, review, resolution))
    previous = [ref['canonicalContent'] for ref in packet['contextRefs']
                if ref['canonicalContent'].get('kind')=='TASK_REPAIR_AUTHORIZATION']
    if len(previous)>1: raise ValueError('Task Repair 授权上下文不唯一。')
    if resolution is not None:
        _,targets,_,_=_task_packet_catalog(packet)
        allowed_targets={row['technicalTarget'] for row in original['tasks'] if row['localKey'] in roots}
        if (not is_manual_repair(resolution) and not set(resolution['technicalTargetKeys'])<=allowed_targets) or not allowed_targets<=targets.keys():
            raise ValueError('澄清只能绑定当前问题 Task 的既有批准技术目标。')
        current=deepcopy(model)
        for collection,node in _task_node_bindings(packet,original): current[collection].append(node)
        for collection in ('tasks','effectiveStartMatches'): current[collection].sort(key=lambda node:node['taskId'])
        if resolution['candidateSha256']!=sha256_bytes(canonical_json_bytes(current)):
            raise ValueError('澄清不是当前候选。')
    authorized = [{field: deepcopy(row[field]) for field in
        ('localKey','storyLocalKey','acceptanceCriterionKeys','technicalTarget')}
        for row in original['tasks'] if row['localKey'] in roots]
    old_roots={row['localKey']:row for row in previous[0]['roots']} if previous else {}
    old_roots.update({row['localKey']:row for row in authorized})
    context = {'kind':'TASK_REPAIR_AUTHORIZATION','reviewDecisionSha256':sha256_bytes(canonical_json_bytes(review)),
               'ownerIRSha256':sha256_bytes(canonical_json_bytes(original)),
               'roots':[old_roots[key] for key in sorted(old_roots)]}
    if previous: context['previousAuthorizationSha256']=sha256_bytes(canonical_json_bytes(previous[0]))
    if resolution is not None: context[resolution_field(resolution)]=resolution
    extra = [context, *_current_task_start_contexts(packet, model, revision,
        {row['technicalTarget'] for row in authorized})]
    result = deepcopy(packet)
    inherited = {ref['refId']:ref['canonicalContent'] for ref in result['contextRefs']
                 if ref['canonicalContent'].get('basis')=='CURRENT_RESPONSIBILITY_COMMITMENT'}
    inherited.update({entry.get('evidenceId','task-repair-authorization'):entry for entry in extra})
    extra = [inherited[key] for key in sorted(inherited)] if previous else extra
    result['contextRefs'] = [ref for ref in result['contextRefs'] if
        ref['canonicalContent'].get('kind') != 'TASK_REPAIR_AUTHORIZATION'
        and ref['canonicalContent'].get('basis') != 'CURRENT_RESPONSIBILITY_COMMITMENT']
    for entry in extra:
        key = entry.get('evidenceId', 'task-repair-authorization')
        result['contextRefs'].append({'refId':key,'canonicalContent':entry,
            'contentSha256':sha256_bytes(canonical_json_bytes(entry))})
    validate_bound_task_context(result)
    return result


def _task_covered_targets(packet, task, obligations, targets):
    """Return exact target projections for authorized shared AC coverage, or None."""
    from final_review import repair_key_root
    from sow_model import stories_share_task_scope
    target = targets.get(task['technicalTarget'])
    story_key = task['storyLocalKey']
    keys = set(task['acceptanceCriterionKeys'])
    if target is None or story_key not in target['storyKeys'] or not keys <= obligations.keys(): return None
    criteria = [obligations[key] for key in keys]
    primary = next((row['story'] for row in criteria if row['storyLocalKey'] == story_key), None)
    if primary is None: return None
    foreign = [row for row in criteria if row['storyLocalKey'] != story_key]
    if not foreign: return [target]
    contexts = [ref['canonicalContent'] for ref in packet['contextRefs']
                if ref['canonicalContent'].get('kind') == 'TASK_REPAIR_AUTHORIZATION']
    if len(contexts) != 1: return None
    roots = contexts[0]['roots']
    if repair_key_root(task['localKey'], {row['localKey'] for row in roots}) is None: return None
    # Every foreign obligation must originate in an explicitly affected root and
    # share an approved implementation target or declared Feature scope.
    selected = {target['targetKey']: target}
    for criterion in foreign:
        matches = [row for row in roots if criterion['acceptanceCriterionKey'] in row['acceptanceCriterionKeys']
                   and row['storyLocalKey'] == criterion['storyLocalKey']]
        candidates = [targets[row['technicalTarget']] for row in matches if row['technicalTarget'] in targets]
        candidates = [other for other in candidates if other['targetKind'] == target['targetKind']
            and (other['targetKey'] == target['targetKey'] or stories_share_task_scope(primary, criterion['story']))]
        if not candidates: return None
        for other in candidates: selected[other['targetKey']] = other
    return [selected[key] for key in sorted(selected)]


def _task_object(payload):
    value = json.loads(payload)
    if not isinstance(value, dict) or canonical_json_bytes(value) != payload:
        raise ValueError('Task 输入必须是 canonical JSON object。')
    return value


def prepare_task_inputs(story_candidate_bytes, checkpoint_bytes, *, checkpoint_sha256,
                        task_catalog, input_revision_bytes, prior_state_bytes=None, prior_state_sha256=None,
                        change_graph_bytes=None, change_graph_sha256=None):
    """Consume resolved upstream bytes and proof; never reopen source files."""
    from sow_model import owner_projection_sha256
    model, checkpoint, revision = map(_task_object, (story_candidate_bytes, checkpoint_bytes, input_revision_bytes))
    registry = load_schema_registry(SKILL_ROOT)
    if (validate_contract(checkpoint, 'stage-checkpoint.schema.json', registry)
            or validate_contract(revision, 'input-revision.schema.json', registry)
            or validate_sow_model(model, 'STAGE_2', registry=registry)
            or checkpoint['stageKind'] != 'STORY_AC'
            or sha256_bytes(checkpoint_bytes) != checkpoint_sha256
            or not checkpoint['upstreamCheckpointSha256s']
            or checkpoint['candidateSha256'] != sha256_bytes(story_candidate_bytes)
            or checkpoint['inputRevisionSha256'] != sha256_bytes(input_revision_bytes)
            or model['project']['inputRevisionSha256'] != sha256_bytes(input_revision_bytes)
            or not isinstance(task_catalog, TaskStandardCatalog)
            or model['project']['templateSha256'] != task_catalog.template_sha256
            or revision['templateSha256'] != task_catalog.template_sha256
            or any(model[collection] for collection in STAGE_3_COLLECTIONS)):
        raise ValueError('Task 输入没有绑定 sealed Story/AC、revision 和本轮模板。')
    sources = {item['sourceId']:item for item in revision['sources']}
    blocks = {(item['sourceId'],item['blockId']):item for item in revision['blocks']}
    if len(sources) != len(revision['sources']) or len(blocks) != len(revision['blocks']):
        raise ValueError('Task revision 来源身份重复。')
    facts = model['inputItems']
    evidence, targets, bodies = {}, {}, []
    def evidence_keys(refs):
        keys = []
        for ref in refs:
            source, block = sources.get(ref['sourceId']), blocks.get((ref['sourceId'],ref['blockId']))
            block_bound = block is not None and (block['contentSha256'],block['locator']) == (ref['sha256'],ref['locator'])
            file_bound = source is not None and source['role']=='DEMO' and source['rawSha256']==ref['sha256'] and ref['locator']=='file:'+source['path']
            if source is None or source['status']=='REFERENCE_ONLY' or not (block_bound or file_bound):
                raise ValueError('Task SourceRef 未绑定本轮授权来源。')
            key = 'evidence-' + sha256_bytes(canonical_json_bytes(ref))
            constraints = [text for fact in facts if ref in fact['sourceRefs']
                           for field in ('conditions','thresholds','prohibitions') for text in fact[field]]
            evidence[key] = {'kind':'TASK_EVIDENCE','evidenceId':key,'sourceRole':source['role'],
                             'sourceRef':ref,'measurementConstraints':constraints}
            keys.append(key)
        if not keys:
            raise TaskInputRequired('Task 技术对象/AC 缺少来源证据。')
        return sorted(set(keys))
    def target(key, kind, name, node, story):
        refs = list(node['sourceRefs'])
        target_key = 'target:'+key
        if kind == 'STORY_IMPLEMENTATION':
            baseline = [item for item in model['designItems']
                        if item['status']=='APPROVED' and story['featureId'] in item['featureIds']
                        and item['designItemId'] in story['designRefs']
                        and any(sources[ref['sourceId']]['role'] in _TECHNICAL_ROLES
                                and sources[ref['sourceId']]['status']=='APPROVED'
                                for ref in item['sourceRefs'])]
            if not baseline:
                return
            refs += [ref for item in baseline for ref in item['sourceRefs']
                     if sources[ref['sourceId']]['role'] in _TECHNICAL_ROLES
                     and sources[ref['sourceId']]['status']=='APPROVED']
            refs = list({canonical_json_bytes(ref):ref for ref in refs}.values())
            target_key += ':implementation'
        if kind == 'POLICY_INSTANCE':
            # Policy authority and its implementation baseline are distinct.
            # Shared release coverage may span the policy's declared targets;
            # other policies retain this Feature's technical source boundary.
            baseline_features = {story['featureId']}
            if node['policyId']=='policy-go-live':
                declared = {feature['featureId'] for feature in model['features']
                            if feature['featureId'] in node['targetNodeIds']
                            or feature['epicId'] in node['targetNodeIds']}
                baseline_features = declared.intersection(baseline_features | set(story['coverageSet']))
            baseline = [item for item in model['designItems']
                        if item['status']=='APPROVED' and baseline_features.intersection(item['featureIds'])]
            baseline += [item for item in model['integrations'] if baseline_features.intersection(item['featureIds'])]
            baseline += [item for item in model['nfrs']
                         if item['status']=='DEFINED' and baseline_features.intersection(item['featureIds'])]
            refs += [ref for item in baseline for ref in item['sourceRefs']
                     if sources[ref['sourceId']]['role'] in _TECHNICAL_ROLES
                     and sources[ref['sourceId']]['status']=='APPROVED']
            refs = list({canonical_json_bytes(ref):ref for ref in refs}.values())
            target_key += ':story:'+story['storyId']
        entry = targets.setdefault(target_key, {'kind':'TASK_TARGET','targetKey':target_key,
            'targetKind':kind,'nodeId':key,'name':name,'sourceRefs':sorted(refs,key=canonical_json_bytes),
            'evidenceIds':evidence_keys(refs),'storyKeys':[], 'designItemIds':[], 'integrationIds':[],
            'nfrIds':[], 'policyInstanceIds':[]})
        entry['storyKeys'].append('story:'+story['storyId'])
        if kind == 'DESIGN_ITEM': entry['designItemIds'] = [key]
        if kind == 'STORY_IMPLEMENTATION':
            entry['designItemIds'] = sorted(item['designItemId'] for item in baseline)
        if kind == 'INTEGRATION':
            entry['integrationIds'] = [key]
        if kind == 'NFR': entry['nfrIds'] = [key]
        if kind == 'POLICY_INSTANCE':
            entry['policyInstanceIds'] = [key]
            entry['designItemIds'] = sorted(set(story['designRefs']).intersection(
                item['designItemId'] for item in baseline if 'designItemId' in item))
    for story in sorted(model['stories'],key=lambda item:item['storyId']):
        story_key = 'story:'+story['storyId']
        target(story['storyId'],'USER_INTERFACE',story['name'],story,story)
        if not story['policyRefs']:
            target(story['storyId'],'STORY_IMPLEMENTATION',story['name'],story,story)
        for design in model['designItems']:
            if design['designItemId'] in story['designRefs']:
                if design['status'] != 'APPROVED': raise TaskInputRequired('Task 所需设计尚未批准。')
                target(design['designItemId'],'DESIGN_ITEM',design['name'],design,story)
        for integration in model['integrations']:
            if story['featureId'] in integration['featureIds']:
                target(integration['integrationId'],'INTEGRATION',integration['name'],integration,story)
        for nfr in model['nfrs']:
            if story['featureId'] in nfr['featureIds'] and nfr['status']=='DEFINED':
                target(nfr['nfrId'],'NFR',nfr['target'],nfr,story)
        for policy in model['policyInstances']:
            if policy['policyInstanceId'] in story['policyRefs']:
                target(policy['policyInstanceId'],'POLICY_INSTANCE',policy['policyId'],policy,story)
        criteria = sorted((ac for ac in model['acceptanceCriteria'] if ac['storyId']==story['storyId']),key=lambda ac:ac['acceptanceCriterionId'])
        if not criteria: raise TaskInputRequired('Task Story 至少需要一条完整关闭义务的 sealed AC。')
        for ac in criteria:
            bodies.append({'contractVersion':'task-obligation-v1','storyLocalKey':story_key,
                'storyId':story['storyId'],'acceptanceCriterionKey':'ac:'+ac['acceptanceCriterionId'],
                'acceptanceCriterionId':ac['acceptanceCriterionId'],'story':story,'acceptanceCriterion':ac,
                'evidenceIds':evidence_keys(ac['sourceRefs'])})
    for entry in targets.values():
        entry['storyKeys'] = sorted(set(entry['storyKeys']))
        if entry['targetKind']=='INTEGRATION':
            owned_inputs = {item['inputItemId'] for item in model['scopeClosure']
                            if entry['nodeId'] in item['targetNodeIds'] and item['disposition']=='SCOPE_NODE'}
            anchors = set(map(canonical_json_bytes,entry['sourceRefs']))
            candidates = [story for story in model['stories'] if 'story:'+story['storyId'] in entry['storyKeys']]
            responsible = min(candidates,key=lambda story:(
                -len(owned_inputs.intersection(story['requirementRefs'])),
                -len(anchors.intersection(map(canonical_json_bytes,story['sourceRefs']))),
                bool(story['policyRefs']),story['storyId']))
            entry['storyKeys'] = ['story:'+responsible['storyId']]
            entry['designItemIds'] = sorted(design['designItemId'] for design in model['designItems']
                if design['designItemId'] in responsible['designRefs'] and set(map(canonical_json_bytes,design['sourceRefs'])).intersection(map(canonical_json_bytes,entry['sourceRefs'])))
    items = tuple(AtomicWorkItemDescriptor(sha256_bytes(canonical_json_bytes(body)), 'TASK',
        'STORY_AC_CHECKPOINT',checkpoint_sha256,ordinal,body) for ordinal,body in enumerate(bodies))
    contexts = [ContextRefDescriptor('sealed-task-story',canonical_json_bytes({'kind':'TASK_STORY_CHECKPOINT',
        'checkpointSha256':checkpoint_sha256,'candidateSha256':checkpoint['candidateSha256'],
        'inputRevisionSha256':sha256_bytes(input_revision_bytes)})),
        ContextRefDescriptor('task-catalog',canonical_json_bytes({'kind':'TASK_CATALOG',
            'templateSha256':task_catalog.template_sha256,'catalogSemanticSha256':task_catalog.semantic_sha256,
            'rows':[{key:row[key] for key in ('workTypeId','name','category','unit','deliverable','modes','neighbors','sitEligibility','rowSemanticSha256')}
                    for row in decision_catalog(task_catalog)]}))]
    prior_contexts = _task_prior_contexts(model, revision, targets, prior_state_bytes, prior_state_sha256,
                                        change_graph_bytes, change_graph_sha256, registry)
    contexts += [ContextRefDescriptor(key,canonical_json_bytes(entry)) for key,entry in sorted({**targets,**evidence}.items())]
    contexts += prior_contexts
    return TaskInputs(story_candidate_bytes,checkpoint_bytes,checkpoint_sha256,input_revision_bytes,task_catalog,items,
                      tuple(contexts) if items else (),prior_state_bytes,prior_state_sha256,change_graph_bytes,change_graph_sha256)


def _task_prior_contexts(model, revision, targets, prior_bytes, prior_hash, graph_bytes, graph_hash, registry):
    """Project already resolved Prior/ChangeGraph proofs; never analyze cells."""
    if revision['priorSowState']=='NOT_PROVIDED':
        if any(value is not None for value in (prior_bytes,prior_hash,graph_bytes,graph_hash)):
            raise ValueError('未提供 Prior 的 revision 不得注入现状证明。')
        return []
    if any(value is None for value in (prior_bytes,prior_hash,graph_bytes,graph_hash)):
        raise TaskInputRequired('Task 需要调用者解析并授权 Prior 与 ChangeGraph hash 证明。')
    snapshot,graph = _task_object(prior_bytes),_task_object(graph_bytes)
    if (sha256_bytes(prior_bytes)!=prior_hash or sha256_bytes(graph_bytes)!=graph_hash
            or validate_contract(snapshot,'prior-state-snapshot.schema.json',registry)
            or snapshot['inputRevisionSha256']!=model['project']['inputRevisionSha256']):
        raise ValueError('Task Prior snapshot 与本轮证明不一致。')
    from change_graph import derive_change_views
    target_ids = [item[field] for collection,field in (('epics','epicId'),('features','featureId'),
        ('designItems','designItemId'),('integrations','integrationId'),('nfrs','nfrId'),('policyInstances','policyInstanceId'))
        for item in model[collection]]
    derive_change_views(graph,snapshot,target_ids)
    sources = {item['sourceId']:item for item in revision['sources']}
    prior_evidence = {}
    for item in snapshot['evidence']:
        source = sources.get(item['sourceId'])
        if (source is None or source['role']!='PRIOR_SOW' or source['status']!='APPLICABLE'
                or source['rawSha256']!=item['workbookSha256']):
            raise ValueError('Task Prior 证据不是本轮适用 PRIOR_SOW。')
        prior_evidence[(item['sourceId'],item['priorEvidenceId'])] = item
    contexts = []
    for entity in snapshot['entities']:
        groups = [group for group in graph['changeGroups'] if entity['entityId'] in group['priorEntityIds']]
        bound_targets = sorted(key for key,target in targets.items()
            if any(target['nodeId'] in group['targetEntityIds'] for group in groups))
        if not bound_targets: continue
        refs=[]
        for evidence_id in entity['evidenceIds']:
            item=prior_evidence.get((entity['sourceId'],evidence_id))
            if item is None: raise ValueError('Task Prior 实体缺少该来源的证据。')
            refs.append({'sourceId':entity['sourceId'],'blockId':evidence_id,'sha256':item['workbookSha256'],
                'locator':item['sheet']+'!'+item['absoluteA1Range']})
        modes = sorted({'接入复用' if group['kind']=='REUSE_DEPENDENCY' else '调整' for group in groups})
        key='prior:'+entity['entityId']
        contexts.append(ContextRefDescriptor(key,canonical_json_bytes({'kind':'TASK_EFFECTIVE_START',
            'evidenceId':key,'entityId':entity['entityId'],'summary':entity['semanticSummary'],
            'targetKeys':bound_targets,'modes':modes,'sourceRefs':sorted(refs,key=canonical_json_bytes),
            'priorStateSha256':prior_hash,'changeGraphSha256':graph_hash})))
    return contexts


def hydrate_task_rules(inputs, selected_work_type_ids, query):
    """Read selected, adjacent and challenger rules from the frozen catalog."""
    hydrated = hydrate(inputs.task_catalog, selected_work_type_ids, query)
    rows = {row['workTypeId']:row for row in decision_catalog(inputs.task_catalog)}
    return tuple(rows[row['工作类型ID']] for row in hydrated.rows)


def _task_contexts_for_items(items, contexts):
    stories = {item.work_item_payload['storyLocalKey'] for item in items}
    required = {'sealed-task-story','task-catalog'} if items else set()
    required.update(key for item in items for key in item.work_item_payload['evidenceIds'])
    for ref in contexts:
        value = json.loads(ref.canonical_content)
        if value.get('kind')=='TASK_TARGET' and stories.intersection(value['storyKeys']):
            required.add(ref.ref_id);required.update(value['evidenceIds'])
    for ref in contexts:
        value = json.loads(ref.canonical_content)
        if value.get('kind')=='TASK_EFFECTIVE_START' and required.intersection(value['targetKeys']):
            required.add(ref.ref_id)
    selected = [ref for ref in contexts if ref.ref_id in required]
    if {ref.ref_id for ref in selected} != required: raise ValueError('Task 缺少关联 context。')
    return selected


def build_task_work_descriptors(work_items, context_refs, budget_policy, *, action_contract_ids=None):
    from stage_planner import estimate_work_input_tokens, StagePlanningBlocked, run_budget_policy_value
    from contracts import usable_action_input_tokens
    ordered = sorted(work_items,key=lambda item:(item.work_item_payload['storyId'],item.work_item_payload['acceptanceCriterionId']))
    checkpoints = [json.loads(ref.canonical_content) for ref in context_refs if ref.ref_id=='sealed-task-story']
    if ordered and (len(checkpoints)!=1 or len({item.work_item_id for item in ordered})!=len(ordered)
            or any(item.source_role!='STORY_AC_CHECKPOINT' or item.action_kind!='TASK'
                or item.source_sha256!=checkpoints[0]['checkpointSha256'] or item.block_ordinal!=ordinal
                or item.work_item_id!=sha256_bytes(canonical_json_bytes(item.work_item_payload))
                for ordinal,item in enumerate(ordered))):
        raise ValueError('Task Atomic metadata 必须绑定 sealed Story/AC 的排序投影。')
    units = {}
    for item in ordered: units.setdefault(item.work_item_payload['storyId'],[]).append(item)
    usable = usable_action_input_tokens(run_budget_policy_value(budget_policy))
    works, current = [], []
    for unit in units.values():
        if current and estimate_work_input_tokens('TASK',current+unit,_task_contexts_for_items(current+unit,context_refs),budget_policy,action_contract_ids=action_contract_ids)>usable:
            works.append(make_planned_work('TASK',current,_task_contexts_for_items(current,context_refs),[]));current=[]
        current += unit
        if estimate_work_input_tokens('TASK',current,_task_contexts_for_items(current,context_refs),budget_policy,action_contract_ids=action_contract_ids)>usable:
            raise StagePlanningBlocked('BUDGET_EXHAUSTED')
    if current: works.append(make_planned_work('TASK',current,_task_contexts_for_items(current,context_refs),[]))
    return tuple(works)


def _task_packet_catalog(packet):
    contents = [ref['canonicalContent'] for ref in packet['contextRefs']]
    rows = [item for item in contents if item.get('kind')=='TASK_CATALOG']
    checkpoints = [item for item in contents if item.get('kind')=='TASK_STORY_CHECKPOINT']
    if packet['workItems'] and (len(rows)!=1 or len(checkpoints)!=1): raise ValueError('Task packet 缺少唯一目录/checkpoint。')
    obligations = {item['payload']['acceptanceCriterionKey']:item['payload'] for item in packet['workItems']}
    targets = {item['targetKey']:item for item in contents if item.get('kind')=='TASK_TARGET'}
    evidence = {item['evidenceId']:item for item in contents if item.get('kind') in {'TASK_EVIDENCE','TASK_EFFECTIVE_START'}}
    if len(obligations)!=len(packet['workItems']): raise ValueError('Task packet 义务重复。')
    return obligations, targets, evidence, {row['workTypeId']:row for row in rows[0]['rows']} if rows else {}


def validate_bound_task_context(packet):
    """Check frozen context outside current-output INVALID_IR conversion."""
    if set(packet)!={'workItems','contextRefs'}: raise ValueError('Task packet 只允许两集合。')
    if len({ref['refId'] for ref in packet['contextRefs']})!=len(packet['contextRefs']): raise ValueError('Task context 重复。')
    for ref in packet['contextRefs']:
        if 'contentSha256' in ref and ref['contentSha256']!=sha256_bytes(canonical_json_bytes(ref['canonicalContent'])):
            raise ValueError('Task context hash 漂移。')
    obligations,targets,evidence,rows = _task_packet_catalog(packet)
    for item in packet['workItems']:
        if item['workItemId']!=sha256_bytes(canonical_json_bytes(item['payload'])): raise ValueError('Task obligation hash 漂移。')
    for item in [*obligations.values(),*targets.values()]:
        if not set(item['evidenceIds']).issubset(evidence): raise ValueError('Task 冻结证据引用未闭合。')
    if any(target['storyKeys']==[] for target in targets.values()): raise ValueError('Task target 无 Story 归属。')


def _task_ui_policy_authority(task, covered_targets, obligations, evidence):
    """Bind UI automation to its own sealed policy and observable AC evidence."""
    if task['workTypeId'] != 'TEST-UI-E2E' or not covered_targets:
        return False
    selected = set(task['evidenceIds'])
    for key in task['acceptanceCriterionKeys']:
        obligation = obligations[key]
        story, criterion = obligation['story'], obligation['acceptanceCriterion']
        if story['designRefs'] or criterion['designRefs']:
            return False
        if not any(evidence[key]['sourceRole'] in {'PRD', 'DEMO'}
                   for key in selected.intersection(obligation['evidenceIds'])):
            return False
        matching = [target for target in covered_targets
                    if obligation['storyLocalKey'] in target['storyKeys']]
        if not any(target['targetKind'] == 'POLICY_INSTANCE'
                   and target['name'] in {'policy-sit-automation', 'policy-uat-automation'}
                   and target['nodeId'] in story['policyRefs']
                   and target['nodeId'] in criterion['policyRefs']
                   and any(evidence[key]['sourceRole'] == 'PRD'
                           for key in selected.intersection(target['evidenceIds']))
                   for target in matching):
            return False
    return True


def _task_decision_diagnostics(packet, result):
    obligations,targets,evidence,rows = _task_packet_catalog(packet)
    diagnostics, covered, local_keys, charges, counts, integration_owners = [],set(),set(),set(),defaultdict(int),defaultdict(int)
    stories = {item['storyLocalKey'] for item in obligations.values()}
    closed_designs, closed_policies = defaultdict(set), defaultdict(set)
    diagnostic_keys=set(); current_path='/tasks'; current_key=None
    def add(code, field=''):
        path = current_path + ('/'+field if field else '')
        identity=(code,path,current_key)
        if identity not in diagnostic_keys:
            diagnostic_keys.add(identity)
            diagnostics.append(Diagnostic(code=code,message='Task 决策未关闭当前义务、目录或来源权威。',
                path=path,details={'subjectIds':[current_key]} if current_key else {}))
    for index,task in enumerate(result['tasks']):
        current_path='/tasks/'+str(index);current_key=task['localKey']
        story_key, keys, work_type = task['storyLocalKey'],set(task['acceptanceCriterionKeys']),task['workTypeId']
        if task['localKey'] in local_keys: add('TASK_LOCAL_KEY_DUPLICATE')
        local_keys.add(task['localKey'])
        if story_key not in stories: add('TASK_STORY_NOT_ASSIGNED')
        covered_targets = _task_covered_targets(packet, task, obligations, targets)
        if covered_targets is None: add('TASK_AC_STORY_MISMATCH')
        else: covered.update(keys)
        covered_stories = {obligations[key]['storyLocalKey'] for key in keys if key in obligations}
        for covered_story in covered_stories: counts[covered_story] += 1
        row = rows.get(work_type)
        if row is None: add('TASK_STANDARD_UNKNOWN')
        elif task['workModeDecision'] not in row['modes']: add('TASK_WORK_MODE_NOT_ALLOWED')
        selected = set(task['evidenceIds'])
        if not selected.issubset(evidence): add('TASK_EVIDENCE_UNBOUND', 'evidenceIds')
        target = targets.get(task['technicalTarget'])
        if target is None or story_key not in target['storyKeys']:
            add('TASK_TARGET_UNBOUND');continue
        bound_targets = covered_targets or [target]
        allowed = {key for entry in bound_targets for key in entry['evidenceIds']}
        allowed.update(key for ac in keys if ac in obligations for key in obligations[ac]['evidenceIds'])
        allowed.update(item['evidenceId'] for item in _task_start_evidence(task,evidence))
        if not selected.issubset(allowed): add('TASK_EVIDENCE_UNBOUND', 'evidenceIds')
        for covered_story in covered_stories:
            for entry in bound_targets:
                if covered_story in entry['storyKeys']:
                    closed_designs[covered_story].update(entry['designItemIds'])
                    closed_policies[covered_story].update(entry['policyInstanceIds'])
        if not selected.intersection(target['evidenceIds']): add('TASK_EVIDENCE_UNBOUND', 'evidenceIds')
        target_evidence = [evidence[key] for key in selected.intersection(target['evidenceIds'])]
        technical = any(item['sourceRole'] in _TECHNICAL_ROLES for item in target_evidence)
        if (work_type not in _UI_WORK_TYPES and not technical
                and not _task_ui_policy_authority(task, covered_targets, obligations, evidence)):
            add('TASK_DEMO_TECHNICAL_AUTHORITY')
        if target['targetKind']=='USER_INTERFACE' and work_type not in _UI_WORK_TYPES: add('TASK_TARGET_TYPE_INVALID')
        if target['targetKind']=='INTEGRATION':
            if row is None or row['sitEligibility']!='PER_INTEGRATION': add('TASK_INTEGRATION_TYPE_INVALID')
            else:
                for key in target['integrationIds']: integration_owners[key]+=1
        elif row and row['sitEligibility']=='PER_INTEGRATION': add('TASK_INTEGRATION_TYPE_INVALID')
        if task['workModeDecision']!='新建' and not _task_start_evidence(task,evidence):
            add('TASK_EFFECTIVE_START_EVIDENCE_MISSING')
        if task['complexityDecision']=='L' and not (technical and target['targetKind']!='USER_INTERFACE'
                or any(item['measurementConstraints'] for item in target_evidence)):
            add('TASK_COMPLEXITY_EVIDENCE_MISSING')
        # One approved design may contain several independent counting objects.
        # Source anchors distinguish them; changing a local label/boundary alone
        # cannot turn the same supported object into another billable instance.
        source_anchors = tuple(sorted(canonical_json_bytes(evidence[key]['sourceRef']) for key in selected
            if key in evidence and evidence[key]['kind']=='TASK_EVIDENCE'))
        charge = (story_key,task['technicalTarget'],work_type,source_anchors)
        if charge in charges: add('TASK_DUPLICATE_CHARGE')
        charges.add(charge)
    current_path='/tasks';current_key=None
    for key in sorted(set(obligations) - covered):
        current_path='/obligations/'+key;current_key=obligations[key]['storyLocalKey']
        add('TASK_STORY_AC_COVERAGE_INCOMPLETE')
    for item in obligations.values():
        current_path='/stories/'+item['storyLocalKey'];current_key=item['storyLocalKey']
        if not set(item['story']['designRefs']).issubset(closed_designs[item['storyLocalKey']]): add('TASK_STORY_DESIGN_COVERAGE_INCOMPLETE')
        if not set(item['story']['policyRefs']).issubset(closed_policies[item['storyLocalKey']]): add('TASK_STORY_POLICY_COVERAGE_INCOMPLETE')
    for story_key,value in counts.items():
        current_path='/stories/'+story_key;current_key=story_key
        if value>4: add('TASK_STORY_TASK_LIMIT')
    current_path='/integrations';current_key=None
    integration_ids = {key for target in targets.values() for key in target['integrationIds']}
    for key in sorted(integration_ids):
        if integration_owners[key] == 1: continue
        current_path='/integrations/'+key
        for story in sorted({story for target in targets.values() if key in target['integrationIds'] for story in target['storyKeys']}):
            current_key=story;add('TASK_INTEGRATION_OWNER_NON_UNIQUE')
    return _sort(diagnostics)


def verify_task_decision(packet, result):
    diagnostics = validate_contract(result,'task-decision.schema.json',load_schema_registry(SKILL_ROOT))
    if diagnostics: return diagnostics
    validate_bound_task_context(packet)
    return _task_decision_diagnostics(packet,result)


def _preserve_task_candidate(packet, result):
    from candidate_repair import repair_baseline, preserve_roots
    baseline = repair_baseline(packet, 'TASK-v1')
    if baseline is None: return
    previous, diagnostic = baseline
    if diagnostic['code'] not in {'TASK_DECISION_INVALID', 'TASK_IDENTITY_COLLISION'}: return
    roots = set(diagnostic['subjectIds'])
    stories = {key for item in diagnostic.get('findings', []) for key in item['subjectIds']
               if key not in {row['localKey'] for row in previous['tasks']}}
    roots.update(row['localKey'] for row in previous['tasks'] if row['storyLocalKey'] in stories)
    def allowed_new(row):
        if row['storyLocalKey'] in stories: return True
        return any(old['localKey'] in roots and old['storyLocalKey'] == row['storyLocalKey']
            and old['technicalTarget'] == row['technicalTarget']
            and set(row['acceptanceCriterionKeys']) <= set(old['acceptanceCriterionKeys'])
            for old in previous['tasks'])
    preserve_roots(previous, result, 'tasks', roots, allow_new=allowed_new)


def validate_bound_task_result(packet, normalized_result):
    """Pure bytes-only pre-seal check after shared schema/normalization."""
    result = json.loads(normalized_result)
    _preserve_task_candidate(packet, result)
    diagnostics = _task_decision_diagnostics(packet,result)
    if diagnostics:
        from models import AttemptDiagnostic
        findings = tuple(AttemptDiagnostic(item.code, item.path,
            tuple(item.details.get('subjectIds', ()))) for item in diagnostics)
        raise InvalidActionResult('Task IR 未关闭当前义务与来源权威。', diagnostic=AttemptDiagnostic(
            'TASK_DECISION_INVALID', '/tasks',
            tuple(sorted({key for item in findings for key in item.subject_ids})), findings=findings))
    try:
        for _ in _task_node_bindings(packet, result):
            pass
    except TaskIdentityCollision as error:
        from models import AttemptDiagnostic
        raise InvalidActionResult(str(error), diagnostic=AttemptDiagnostic(
            'TASK_IDENTITY_COLLISION', '/tasks', error.subject_ids)) from error


def _task_start_evidence(task, evidence):
    return [evidence[key] for key in task['evidenceIds'] if key in evidence
        and evidence[key]['kind']=='TASK_EFFECTIVE_START'
        and task['technicalTarget'] in evidence[key]['targetKeys']
        and task['workModeDecision'] in evidence[key]['modes']]


@dataclass(frozen=True)
class TaskMaterialization:
    candidate_bytes: bytes
    candidate_sha256: str
    story_candidate_bytes: bytes
    checkpoint_sha256: str
    packet_bytes: bytes
    decision_bytes: bytes


def _complete_task_results(inputs, plan, ledger, budget_policy):
    from stage_planner import validate_stage_plan, materialize_packet, _effective_envelope, bound_action_contract_ids
    from action_ledger import build_attempt_repair_context
    expected = prepare_task_inputs(inputs.story_candidate_bytes,inputs.checkpoint_bytes,
        checkpoint_sha256=inputs.checkpoint_sha256,task_catalog=inputs.task_catalog,input_revision_bytes=inputs.input_revision_bytes,
        prior_state_bytes=inputs.prior_state_bytes,prior_state_sha256=inputs.prior_state_sha256,
        change_graph_bytes=inputs.change_graph_bytes,change_graph_sha256=inputs.change_graph_sha256)
    if (sorted(inputs.work_items,key=lambda item:item.work_item_id)!=sorted(expected.work_items,key=lambda item:item.work_item_id)
            or sorted(inputs.context_refs,key=lambda ref:ref.ref_id)!=sorted(expected.context_refs,key=lambda ref:ref.ref_id)):
        raise ValueError('Task work/context 不是 sealed 上游的确定性投影。')
    contract_ids=bound_action_contract_ids(plan)
    descriptors=build_task_work_descriptors(inputs.work_items,inputs.context_refs,budget_policy,action_contract_ids=contract_ids)
    validate_stage_plan(plan,inputs.work_items,inputs.context_refs,descriptors,[inputs.checkpoint_sha256],budget_policy,action_contract_ids=contract_ids)
    checkpoint=json.loads(inputs.checkpoint_bytes)
    results=[]
    for work in plan['works']:
        key,packet_plan=work['logicalWorkId'],work['packetPlan']
        envelope=_effective_envelope(ledger,key)
        if envelope is None or effective_result_bytes(ledger,key) is None:
            raise TaskInputRequired('Task plan 尚有未 sealed 的 LogicalWork。')
        _,record=effective_result(ledger,key)
        if (envelope.value['actionContractId']!=packet_plan['actionContractId']
                or envelope.value['actionContractSha256']!=packet_plan['actionContractSha256']
                or envelope.value['inputRevisionSha256']!=sha256_bytes(inputs.input_revision_bytes)
                or envelope.value['baseCandidateSha256']!=sha256_bytes(inputs.story_candidate_bytes)
                or len({item.value['runId'] for item in ledger.envelopes_by_sha256.values()})!=1):
            raise ValueError('Task effective Attempt 未绑定本轮上游/合同。')
        normalized=ledger.normalized_results[record.normalized_result_sha256]
        if sha256_bytes(normalized)!=record.normalized_result_sha256: raise ValueError('Task normalized hash 漂移。')
        repair=None
        if envelope.value['revision']>1:
            failed=[digest for digest,item in ledger.attempt_records.items()
                if item.logical_work_id==key and item.revision==envelope.value['revision']-1 and item.failure_kind in {'INVALID_JSON','INVALID_IR'}]
            if len(failed)!=1: raise ValueError('Task revision 2 没有唯一 INVALID_IR Attempt。')
            repair=build_attempt_repair_context(key,failed[0],ledger.attempt_records,ledger.raw_outputs,
                envelopes_by_sha256=ledger.envelopes_by_sha256)
        packet_bytes=materialize_packet(plan,key,envelope.value['revision'],inputs.work_items,inputs.context_refs,[],ledger,repair)
        if sha256_bytes(packet_bytes)!=envelope.value['packetSha256']: raise ValueError('Task Attempt 未绑定实际计划 packet。')
        result=json.loads(normalized)
        if verify_task_decision(json.loads(packet_bytes),result): raise InvalidActionResult('Task sealed IR 未关闭当前义务。')
        results.append((key,result))
    return results


def _task_node_bindings(packet, result):
    """Single-node binding rules shared with independent complete validation."""
    from stable_ids import stable_entity_id
    obligations,targets,evidence,rows=_task_packet_catalog(packet)
    identities={}
    for task in result['tasks']:
        target=targets[task['technicalTarget']]
        criteria=[obligations[key] for key in task['acceptanceCriterionKeys']]
        story=next(item['story'] for item in criteria if item['storyLocalKey']==task['storyLocalKey'])
        bound_targets=_task_covered_targets(packet,task,obligations,targets)
        if bound_targets is None: raise ValueError('Task 共享覆盖未经授权。')
        selected=[evidence[key] for key in task['evidenceIds'] if evidence[key]['kind']=='TASK_EVIDENCE']
        source_refs={canonical_json_bytes(item['sourceRef']):item['sourceRef'] for item in selected}
        anchors=[canonical_json_bytes({'role':'SOURCE','sourceRef':ref}).decode() for ref in source_refs.values()]
        anchors += [canonical_json_bytes({'role':'TARGET','sourceRef':ref}).decode() for entry in bound_targets for ref in entry['sourceRefs']]
        task_id=stable_entity_id('task-id-v1','TASK',story['storyId'],sorted(set(anchors)),(target['targetKind'],))
        if task_id in identities:
            raise TaskIdentityCollision(identities[task_id], task['localKey'])
        identities[task_id] = task['localKey']
        yield 'tasks', {'taskId':task_id,'storyId':story['storyId'],'name':target['name'],
            'workTypeId':task['workTypeId'],'rowSemanticSha256':rows[task['workTypeId']]['rowSemanticSha256'],
            'workMode':task['workModeDecision'],'actualMeasurementScope':task['deliverableBoundary'],
            'complexity':task['complexityDecision'],'sourceRefs':[source_refs[key] for key in sorted(source_refs)],
            'acceptanceCriterionIds':sorted(item['acceptanceCriterionId'] for item in criteria),
            'designItemIds':sorted({key for entry in bound_targets for key in entry['designItemIds']
                if any(key in criterion['story']['designRefs'] and criterion['storyLocalKey'] in entry['storyKeys'] for criterion in criteria)}),
            'integrationIds':sorted({key for entry in bound_targets for key in entry['integrationIds']}),
            'nfrIds':sorted({key for entry in bound_targets for key in entry['nfrIds']}),
            'policyInstanceIds':sorted({key for entry in bound_targets for key in entry['policyInstanceIds']})}
        starts=_task_start_evidence(task,evidence) if task['workModeDecision']!='新建' else []
        yield 'effectiveStartMatches', {'taskId':task_id,'queryKey':target['targetKey'],
            'candidateIds':sorted({item['entityId'] for item in starts}),
            'checkedLocators':sorted({ref['locator'] for item in starts for ref in item['sourceRefs']}),
            'decision':{'新建':'NO_MATCH_NEW','调整':'MATCHED_ADJUSTMENT','接入复用':'MATCHED_REUSE'}[task['workModeDecision']]}


def verify_task_replacement_ac_scope(original, review, replacement, resolution=None):
    """Each repair may redistribute only its own affected roots' existing ACs."""
    from final_review import repair_root_keys, repair_key_root
    roots=set(repair_root_keys('TASK',original,review,resolution))
    allowed={key for task in original['tasks'] if task['localKey'] in roots
             for key in task['acceptanceCriterionKeys']}
    for task in replacement['tasks']:
        if (repair_key_root(task['localKey'],roots) is None
                or not set(task['acceptanceCriterionKeys'])<=allowed):
            raise ValueError('当前修复只能分配本轮授权 roots 已有的 AC；历史授权不扩展新修复范围。')


def apply_task_repairs(packet, decisions, repairs, inputs):
    from final_review import replace_owner_decisions
    for repair in repairs:
        review,replacement,*answers=repair
        resolution=answers[0] if answers else None
        verify_task_replacement_ac_scope(decisions,review,replacement,resolution)
        packet=prepare_task_repair_packet(packet,decisions,review,
            inputs.story_candidate_bytes,inputs.input_revision_bytes,resolution)
        decisions=replace_owner_decisions('TASK',decisions,review,replacement,resolution)
    return packet,decisions


def materialize_task_candidate(inputs, plan, ledger, budget_policy, *, semantic_repair=None, semantic_repairs=None):
    results=_complete_task_results(inputs,plan,ledger,budget_policy)
    packet={'workItems':[{'workItemId':item.work_item_id,'payload':item.work_item_payload} for item in inputs.work_items],
        'contextRefs':[{'refId':ref.ref_id,'canonicalContent':json.loads(ref.canonical_content),
            'contentSha256':sha256_bytes(ref.canonical_content)} for ref in inputs.context_refs]}
    joined={'tasks':[]}
    for key,result in results:
        for original in result['tasks']:
            task=deepcopy(original);task['localKey']=key+':'+task['localKey'];joined['tasks'].append(task)
    repairs = semantic_repairs if semantic_repairs is not None else ([semantic_repair] if semantic_repair else [])
    packet,joined=apply_task_repairs(packet,joined,repairs,inputs)
    if _task_decision_diagnostics(packet,joined): raise InvalidActionResult('Task 完整 IR union 未关闭义务或重复计价。')
    model=json.loads(inputs.story_candidate_bytes)
    for collection,node in _task_node_bindings(packet,joined): model[collection].append(node)
    for collection in ('tasks','effectiveStartMatches'): model[collection].sort(key=lambda node:node['taskId'])
    joined['tasks'].sort(key=lambda task:task['localKey'])
    raw=canonical_json_bytes(model)
    return TaskMaterialization(raw,sha256_bytes(raw),inputs.story_candidate_bytes,inputs.checkpoint_sha256,
        canonical_json_bytes(packet),canonical_json_bytes(joined))


def validate_task_candidate(material):
    model,upstream=json.loads(material.candidate_bytes),json.loads(material.story_candidate_bytes)
    diagnostics=list(validate_sow_model(model,'STAGE_3',registry=load_schema_registry(SKILL_ROOT)))
    if sha256_bytes(material.candidate_bytes)!=material.candidate_sha256:
        diagnostics.append(_diagnostic('TASK_CANDIDATE_HASH_MISMATCH','Task 候选 hash 漂移。'))
    for collection,value in upstream.items():
        if collection not in STAGE_3_COLLECTIONS and model.get(collection)!=value:
            diagnostics.append(_diagnostic('STAGE_3_WRITE_SCOPE','Task 不得修改 sealed 上游。','/'+collection))
    packet,result=json.loads(material.packet_bytes),json.loads(material.decision_bytes)
    expected={collection:{} for collection in STAGE_3_COLLECTIONS}
    for collection,node in _task_node_bindings(packet,result): expected[collection][node['taskId']]=node
    for collection,field in (('tasks','taskId'),('effectiveStartMatches','taskId'),('dependencies','dependencyId'),('estimationAnnotations','annotationId')):
        if {node[field]:node for node in model[collection]}!=expected[collection]:
            diagnostics.append(_diagnostic('TASK_NODE_IR_BINDING_MISMATCH','Task 节点与 sealed IR 完整绑定不一致。','/'+collection))
    diagnostics.extend(_task_coverage_diagnostics(model))
    diagnostics.extend(_task_decision_diagnostics(packet,result))
    return _sort(diagnostics)


def verify_task_repair_chain(entries, candidates, revision_bytes, author_ir, final_hash):
    from final_review import replace_owner_decisions, repair_root_keys, owner_resolution, resolution_field
    remaining=list(entries);current_ir=author_ir;previous_packet=None;last_hash=None;resolutions={};fields={}
    while remaining:
        matches=[row for row in remaining if row[1]['ownerIR']==current_ir]
        if len(matches)!=1: raise ValueError('Task Repair 链必须从实际 Author IR 唯一连续恢复。')
        entry=matches[0];remaining.remove(entry);old_hash,body,replacement=entry
        if last_hash is not None and old_hash!=last_hash: raise ValueError('Task Repair 跳过了前一个候选。')
        before=json.loads(candidates[old_hash]);packet=expand_task_repair_packet(body['ownerPacket'])
        if previous_packet is None:
            previous_packet=deepcopy(packet)
            previous_packet['contextRefs']=[ref for ref in previous_packet['contextRefs'] if
                ref['canonicalContent'].get('kind')!='TASK_REPAIR_AUTHORIZATION'
                and ref['canonicalContent'].get('basis')!='CURRENT_RESPONSIBILITY_COMMITMENT']
        upstream=deepcopy(before)
        for collection in STAGE_3_COLLECTIONS: upstream[collection]=[]
        resolution=owner_resolution(body)
        expected=prepare_task_repair_packet(previous_packet,current_ir,body['reviewDecision'],
            canonical_json_bytes(upstream),revision_bytes,resolution)
        if packet!=expected or body['authorizedRootKeys']!=repair_root_keys('TASK',current_ir,body['reviewDecision'],resolution):
            raise ValueError('Task Repair 上下文或授权闭包漂移。')
        if verify_task_decision(previous_packet,current_ir): raise ValueError('Task Repair 原义务未闭合。')
        original=deepcopy(upstream)
        for collection,node in _task_node_bindings(previous_packet,current_ir): original[collection].append(node)
        for collection in ('tasks','effectiveStartMatches'): original[collection].sort(key=lambda node:node['taskId'])
        if original!=before: raise ValueError('Task Repair 原候选未绑定实际 IR。')
        verify_task_replacement_ac_scope(current_ir,body['reviewDecision'],replacement,resolution)
        current_ir=replace_owner_decisions('TASK',current_ir,body['reviewDecision'],replacement,resolution)
        if verify_task_decision(packet,current_ir): raise ValueError('Task Repair 义务未闭合。')
        after=deepcopy(upstream)
        for collection,node in _task_node_bindings(packet,current_ir): after[collection].append(node)
        for collection in ('tasks','effectiveStartMatches'): after[collection].sort(key=lambda node:node['taskId'])
        raw=canonical_json_bytes(after);last_hash=sha256_bytes(raw)
        if candidates.get(last_hash)!=raw: raise ValueError('Task Repair 未保留未改变结果或缺少完整后继候选。')
        if resolution is not None: fields[resolution_field(resolution)]=resolution
        resolutions[last_hash]=deepcopy(fields);previous_packet=packet
    if last_hash!=final_hash: raise ValueError('Task Repair 链未到达最终 PASS 候选。')
    return resolutions


def publish_task_candidate(files,run_id,material):
    if sha256_bytes(material.candidate_bytes)!=material.candidate_sha256: raise ValueError('Task candidate hash 漂移。')
    files.publish_new(f'.ai-sow/work/runs/{run_id}/stages/TASK/candidates/{material.candidate_sha256}.json',material.candidate_bytes)
    return {'candidateSha256':material.candidate_sha256}


def diagnose_candidate(action_kind, packet, candidate, **owner_context):
    from candidate_repair import schema_issues, diagnostic_report, issues_from_diagnostics
    from contracts import current_action_contract_id
    contract_id = owner_context.get('action_contract_id', current_action_contract_id(action_kind))
    raw = candidate if isinstance(candidate, bytes) else canonical_json_bytes(candidate)
    value = json.loads(raw)
    issues = schema_issues(contract_id, value, 'TASK')
    blocked=[];domains=['SCHEMA']
    try:
        diagnostics=_task_decision_diagnostics(packet,value)
    except (KeyError,TypeError,IndexError):
        blocked.append('TASK_BINDINGS')
    else:
        issues+=issues_from_diagnostics(diagnostics,'TASK',value);domains.append('TASK_BINDINGS')
        if not issues:
            try:
                list(_task_node_bindings(packet,value))
            except TaskIdentityCollision as error:
                from models import AttemptDiagnostic
                issues+=issues_from_diagnostics([AttemptDiagnostic('TASK_IDENTITY_COLLISION','/tasks',error.subject_ids)],'TASK',value)
    return diagnostic_report(raw,issues,owner='TASK',checker_file=__file__,packet=packet,
        origin=owner_context.get('origin'),blocked=blocked,domains=domains)


def plan_candidate_repair(action_kind, packet, candidate, report, *, origin, **owner_context):
    from candidate_repair import group_fields, build_repair_plan
    from contracts import current_action_contract_id
    contract_id=owner_context.get('action_contract_id',current_action_contract_id(action_kind))
    fields = {'TASK_STORY_NOT_ASSIGNED':['storyLocalKey'], 'TASK_AC_STORY_MISMATCH':['acceptanceCriterionKeys'],
        'TASK_STANDARD_UNKNOWN':['workTypeId'], 'TASK_WORK_MODE_NOT_ALLOWED':['workModeDecision'],
        'TASK_TARGET_UNBOUND':['technicalTarget'], 'TASK_TARGET_TYPE_INVALID':['workTypeId'],
        'TASK_INTEGRATION_TYPE_INVALID':['workTypeId'], 'TASK_EFFECTIVE_START_EVIDENCE_MISSING':['workModeDecision','evidenceIds'],
        'TASK_COMPLEXITY_EVIDENCE_MISSING':['complexityDecision','evidenceIds'],
        'TASK_DEMO_TECHNICAL_AUTHORITY':['workTypeId','evidenceIds']}
    selected={}
    for issue in report['issues']:
        path=issue['paths'][0]
        selected[issue['issueId']] = ([path+'/'+field for field in fields[issue['code']]]
            if issue['code'] in fields else [path])
    groups=group_fields(candidate,report,contract_id,selected)
    from candidate_repair import append_object_group, schema_at, index_candidate, remove_object_group
    raw=candidate if isinstance(candidate,bytes) else canonical_json_bytes(candidate);value=json.loads(raw)
    obligations,targets,evidence,rows=_task_packet_catalog(packet)
    missing=[issue for issue in report['issues'] if issue['code']=='TASK_STORY_AC_COVERAGE_INCOMPLETE']
    for issue in missing:
        key=issue['paths'][0].removeprefix('/obligations/');story=obligations[key]['storyLocalKey']
        related=[i['issueId'] for i in report['issues'] if i['code'].endswith('COVERAGE_INCOMPLETE')
                 and (i['paths'][0]=='/stories/'+story or i['paths'][0].startswith('/obligations/') and obligations.get(i['paths'][0].removeprefix('/obligations/'),{}).get('storyLocalKey')==story)]
        if any(set(related)&set(g['issueIds']) for g in groups):continue
        schema=schema_at(contract_id,'/tasks/0')
        schema={**schema,'properties':{**schema['properties'],'storyLocalKey':{'const':story},
            'acceptanceCriterionKeys':{'type':'array','items':{'enum':[k for k,o in obligations.items() if o['storyLocalKey']==story]},'contains':{'const':key},'minItems':1,'uniqueItems':True}}}
        groups.append(append_object_group(raw,'tasks',schema,related,group_id='missing-'+issue['issueId']))
    for issue in report['issues']:
        if issue['code'] not in {'TASK_DUPLICATE_CHARGE','TASK_LOCAL_KEY_DUPLICATE'}:continue
        path=issue['paths'][0];entry=next((e for e in index_candidate(raw,inherited=report.get('objectIndex',())) if e['path']==path),None)
        if entry is not None:groups.append(remove_object_group(raw,entry,[issue['issueId']]))
    if not groups: raise InvalidActionResult('当前 Task 问题需要明确根对象或真实输入，不能扩大字段授权。')
    return build_repair_plan(candidate if isinstance(candidate,bytes) else canonical_json_bytes(candidate),report,groups,origin=origin)


def candidate_repair_context(action_kind, packet, candidate, plan, group):
    value=json.loads(candidate);index={r['objectId']:r for r in plan['objectIndex']}
    selected=[];stories=set()
    for slot in group['slots']:
        path=index.get(slot['objectId'],{}).get('path','').split('/')
        if len(path)>2 and path[1]=='tasks' and path[2].isdigit():
            selected.append(value['tasks'][int(path[2])])
        story=slot.get('valueSchema',{}).get('properties',{}).get('storyLocalKey',{}).get('const')
        if isinstance(story,str):stories.add(story)
    stories.update(row['storyLocalKey'] for row in selected)
    selected.extend(row for row in value['tasks'] if row['storyLocalKey'] in stories and row not in selected)
    items=[item for item in packet['workItems'] if item['payload']['storyLocalKey'] in stories]
    evidence={eid for item in items for eid in item['payload']['evidenceIds']}
    contexts=[]
    for ref in packet['contextRefs']:
        body=ref['canonicalContent']
        if body.get('kind')=='TASK_TARGET' and stories.intersection(body['storyKeys']):
            contexts.append(body);evidence.update(body['evidenceIds'])
        elif body.get('kind')=='TASK_CATALOG':
            rows={row['workTypeId']:row for row in body['rows']}
            selected_types={row['workTypeId'] for row in selected if row.get('workTypeId') in rows}
            challenger_types=selected_types | {key for work_type in selected_types for key in rows[work_type]['neighbors']}
            contexts.append({**body,'rows':[row for row in body['rows'] if row['workTypeId'] in challenger_types]})
    contexts.extend(ref['canonicalContent'] for ref in packet['contextRefs']
        if ref['canonicalContent'].get('evidenceId') in evidence)
    return [{'kind':'OWNER_OBLIGATION','value':item['payload']} for item in items]+contexts
