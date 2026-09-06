"""Small pure IR values shared by independently runnable tests."""
import copy


def scan_ir(root="block-a", key="fact-a"):
    return [{"coverageRootId": root, "disposition": "FACT", "facts": [
        {"localKey": key, "factKind": "REQUIREMENT", "statement": "管理员可查询订单。",
         "evidenceIds": [root], "qualifiers": ["仅管理员", "七日内"]}]}]


def audit_ir(root="block-a", key="fact-a"):
    return {"checks": [{"coverageRootId": root, "category": category, "decision": "COVERED",
        "relatedFactKeys": [key], "evidenceIds": [root]} for category in
        ["THRESHOLD", "NEGATION", "EXCLUSION", "EXCEPTION", "ROLE", "TIME"]]}


def scope_decision_ir(local_key="feature-a", fact_ids=None):
    return {"decisions": [{"localKey": local_key, "decisionKind": "FEATURE",
        "factIds": fact_ids if fact_ids is not None else ["block-a:fact-a"], "priorEntityIds": [],
        "boundaryEvidence": {"name": "订单查询", "classification": "BUSINESS", "evidenceIds": ["block-a"],
            "facetFacts": [], "observationKeys": []},
        "relations": [{"kind": "PARENT", "targetLocalKeys": ["epic-a"], "evidenceIds": ["block-a"]}]}]}


def complete_scope_ir():
    result = scope_decision_ir()
    epic = copy.deepcopy(result["decisions"][0])
    epic.update(localKey="epic-a", decisionKind="EPIC", factIds=[], relations=[])
    epic["boundaryEvidence"]["name"] = "订单管理"
    result["decisions"].append(epic)
    return result


def story_ac_ir():
    return {"stories": [{"localKey": "query", "scopeDecisionKeys": ["obligation-a", "obligation-b"],
        "actorKey": "fact-a", "deliverableOutcome": "管理员查询订单", "sourceFactIds": ["fact-a", "fact-b"],
        "acceptanceCriteria": [
            {"localKey": "success", "condition": "管理员提交有效条件", "observableResult": "显示匹配订单", "sourceFactIds": ["fact-a"]},
            {"localKey": "empty", "condition": "管理员提交无匹配条件", "observableResult": "显示空结果", "sourceFactIds": ["fact-b"]}]}]}


def task_decision_ir():
    return {"tasks": [{"localKey": "query-view", "storyLocalKey": "story:story-query",
        "acceptanceCriterionKeys": ["ac:ac-success", "ac:ac-empty"], "workTypeId": "FE-VIEW",
        "technicalTarget": "target:story-query", "deliverableBoundary": "一张订单查询页面",
        "workModeDecision": "新建", "complexityDecision": "M", "evidenceIds": ["evidence-a", "evidence-b"]}]}


def story_scope_model():
    """Pure Scope projection; no host, checkpoint replay or Office setup."""
    model = {'contract': 'ai-sow-model-v1', 'project': {
        'projectId': 'orders', 'mode': 'GREENFIELD', 'inputRevisionSha256': 'a'*64,
        'sourceManifestSha256': 'b'*64, 'templateSha256': 'c'*64,
        'policyDefinitionSha256': 'd'*64, 'responsibilityBoundaries': ['customer']}}
    for key in ('inputItems', 'scopeClosure', 'epics', 'features', 'designItems', 'integrations',
                'nfrs', 'policyInstances', 'scopeAnnotations', 'stories', 'acceptanceCriteria',
                'deliveryAnnotations', 'tasks', 'dependencies', 'effectiveStartMatches',
                'estimationAnnotations', 'decisions'):
        model[key] = []
    for key in ('a', 'b'):
        ref = {'sourceId': 'prd', 'blockId': 'block-'+key, 'sha256': key*64, 'locator': 'paragraph:'+key}
        model['inputItems'].append({'inputItemId': 'input-'+key, 'kind': 'REQUIREMENT',
            'text': '管理员查询订单' if key == 'a' else '管理员查询无匹配订单',
            'conditions': [], 'thresholds': [], 'prohibitions': [], 'applicableScopes': [], 'sourceRefs': [ref]})
        model['scopeClosure'].append({'inputItemId': 'input-'+key, 'sourceRefs': [ref], 'disposition': 'SCOPE_NODE',
            'targetNodeIds': ['feature-query'], 'preservedQualifiers': [], 'crossFeatureRuleIds': [],
            'mechanicalCoverage': 'COMPLETE', 'semanticSufficiency': 'SUFFICIENT', 'designCoverageStatus': 'SUFFICIENT',
            'deliveryDisposition': 'STORY_AC_REQUIRED', 'assignedFeatureIds': ['feature-query'],
            'requiredQualifierRefs': [], 'crossFeatureTargetIds': []})
    common = {'scopeClass': 'BUSINESS', 'requirementRefs': ['input-a', 'input-b'], 'designRefs': [],
              'policyRefs': [], 'effortPhase': 'BUILD', 'activationPhase': 'BUILD', 'inclusionPolicy': 'SOURCE_GATED'}
    model['epics'] = [{'epicId': 'epic-orders', 'name': '订单管理', **common}]
    model['features'] = [{'featureId': 'feature-query', 'epicId': 'epic-orders', 'name': '订单查询',
                         'scopeDecision': 'IN_SCOPE', **common}]
    return model


def task_story_model():
    model = story_scope_model()
    refs = [item['sourceRefs'][0] for item in model['inputItems']]
    model['stories'] = [{'storyId':'story-query', 'featureId':'feature-query', 'name':'管理员查询订单',
        'sourceRefs':refs, 'uatApplicable':True, 'coverageSet':['input-a','input-b'],
        'requirementRefs':['input-a','input-b'], 'designRefs':[], 'policyRefs':[]}]
    for key, ref in zip(('success','empty'),refs):
        model['acceptanceCriteria'].append({'acceptanceCriterionId':'ac-'+key,'storyId':'story-query',
            'text':'当管理员查询；显示结果' if key=='success' else '当无匹配记录；显示空结果',
            'sourceRefs':[ref], 'coverageSet':['input-'+('a' if key=='success' else 'b')],
            'requirementRefs':['input-'+('a' if key=='success' else 'b')], 'designRefs':[], 'policyRefs':[]})
    return model
