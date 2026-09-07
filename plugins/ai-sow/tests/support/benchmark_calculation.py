"""Read-only benchmark calculation over the two immutable run proof closures."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from contracts import canonical_json_bytes, sha256_bytes, validate_contract
from runtime.project_io import ProjectFiles
from benchmark_execution import bound, prepared, select_run, revision_from_events, initial_policy, verify_browser


def _json(files, path, digest=None):
    raw = files.read_bytes(path) if digest is None else bound(files, {'path': path, 'sha256': digest})
    value = json.loads(raw)
    if canonical_json_bytes(value) != raw: raise ValueError('noncanonical sealed JSON: ' + path)
    return value


def _references(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == 'sourceRefs': yield from child
            else: yield from _references(child)
    elif isinstance(value, list):
        for child in value: yield from _references(child)


def _source_catalog(project, revision, input_manifest, side, proof):
    sources = {row['sourceId']: row for row in revision['sources']}
    if len(sources) != len(revision['sources']): raise ValueError('duplicate frozen source ID')
    for row in sources.values(): bound(project, {'path': row['path'], 'sha256': row['rawSha256']})
    refs = {canonical_json_bytes({'sourceId': row['sourceId'], 'blockId': row['blockId'],
        'locator': row['locator'], 'sha256': row['contentSha256']}) for row in revision['blocks']}
    anchors = {(row['sourceId'], row['locator']) for row in revision['blocks']}
    aliases = {}
    bundle = input_manifest['bundles'][side]
    for item in bundle['files']:
        source = sources[item['sourceId']]
        if source['rawSha256'] != item['sha256']: raise ValueError('revision Demo differs from prepared bundle')
        filename = Path(item['path']).name
        mappings = {row['subject']: {tuple(locator.split('#', 1)) for locator in row['sourceLocators']}
            for row in bundle['reverseMappings'] if row['kind'] == 'SOURCE'}
        file_anchors = set().union(*(value for key, value in mappings.items() if key.startswith(filename + '#')))
        for anchor in list(anchors):
            if anchor[0] == item['sourceId']: aliases[anchor] = mappings.get(filename + '#' + anchor[1], set())
        # Prototype inventories retain file-level SourceRefs, whose anchors resolve
        # through the independently frozen source conversion map.
        for action in proof['actions']:
            if action['envelope']['actionContractId'] != 'PROTOTYPE_BROWSER-v1': continue
            inventory = action['packet']['workItems'][0]['payload']['inventory']
            for file in inventory['files']:
                if file['sourceId'] != item['sourceId']: continue
                if file['sha256'] != item['sha256']: raise ValueError('prototype inventory source hash drift')
                evidence_id = 'evidence-' + sha256_bytes(canonical_json_bytes([file['sourceId'], file['relativePath'], file['sha256']]))
                ref = {'sourceId': item['sourceId'], 'blockId': evidence_id,
                    'locator': 'file:' + file['relativePath'], 'sha256': file['sha256']}
                refs.add(canonical_json_bytes(ref)); anchor = (ref['sourceId'], ref['locator'])
                anchors.add(anchor); aliases[anchor] = file_anchors
    originals = {(row['sourceId'], locator) for row in input_manifest['frozenSources'] if row['side'] == side
        for locator in row['locators']}
    return refs, anchors | originals, aliases


def _read_side(api, root, pair_id, side, inputs, oracle):
    project = ProjectFiles.open(root.resolve(f'runs/{pair_id}/{side}/project', expect='dir'))
    request = api._request(project, 'request.json', side.upper())
    run_id, events, state = select_run(api, project)
    if state != 'AWAITING_FINAL_REVIEW': raise ValueError(side + ' has no sealed final-review boundary')
    initial_policy(api, project, run_id, events, inputs)
    revision = revision_from_events(project, events)
    if revision['requestSha256'] != sha256_bytes(canonical_json_bytes(request)):
        raise ValueError('run request differs from immutable InputRevision')
    if validate_contract(revision, 'input-revision.schema.json', api.REGISTRY): raise ValueError('invalid InputRevision')
    run_root = f'.ai-sow/work/runs/{run_id}'
    # FINAL_VALIDATE is the event-bound publication of the ArtifactManifest.
    finals = [e for e in events if e.type == 'DETERMINISTIC_STEP_FINISHED'
        and e.payload['stepKind'] == 'FINAL_VALIDATE' and e.payload['outcome'] == 'SUCCEEDED']
    if len(finals) != 1: raise ValueError('one successful final artifact validation is required')
    digest = finals[0].payload['outputSha256']
    sealed = _json(project, run_root + '/artifact-steps/FINAL_VALIDATE/' + digest + '.json', digest)
    manifest = _json(project, sealed['manifestPath'], sealed['manifestSha256'])
    if manifest != sealed['manifest'] or manifest['runId'] != run_id:
        raise ValueError('final artifact publication does not bind this run')
    if validate_contract(manifest, 'artifact-approval.schema.json', api.REGISTRY): raise ValueError('invalid ArtifactManifest')
    artifact_root = Path(sealed['manifestPath']).parent.as_posix()
    bound(project, {'path': artifact_root + '/' + manifest['workbook']['path'], 'sha256': manifest['workbook']['sha256']})
    model = _json(project, artifact_root + '/sow-model.json', manifest['candidateSha256'])
    proof = _json(project, artifact_root + '/' + manifest['proofBundle']['path'], manifest['proofBundle']['sha256'])
    revision_path = '.ai-sow/inputs/revisions/' + revision['revisionId'] + '/manifest.json'
    actual = api.generation_store.collect_artifact_proof(project, {'runId': run_id}, revision_path)
    if actual != proof or proof['inputRevision'] != revision:
        raise ValueError('portable proof differs from actual immutable run records')
    api.generation_store.verify_artifact_proof(proof, model, manifest)
    # The production ledger reader additionally verifies policy-at-issuance and
    # exact canonical raw/normalized bytes; it never reads a run summary.
    ledger = api.orchestrator._load_action_ledger(project, run_id)
    proof_ledger, packets = api.generation_store._proof_ledger(proof)
    if set(ledger.attempt_records) != set(proof_ledger.attempt_records):
        raise ValueError('artifact proof omits actual AttemptRecords')
    publications = {}
    for event in events:
        if event.type == 'RUN_BUDGET_POLICY_PUBLISHED': publications.setdefault(event.payload['budgetPolicySha256'], event.sequence)
    for body in proof['stages'].values():
        plan = body['plan']; first = min(e.sequence for e in events if e.type == 'ACTION_ISSUED'
            and ledger.envelopes_by_sha256[e.payload['envelopeSha256']].value['stageKind'] == plan['stageKind'])
        if plan['budgetPolicySha256'] not in publications or publications[plan['budgetPolicySha256']] >= first:
            raise ValueError('StagePlan policy was not published before its first Action')
    refs, locators, aliases = _source_catalog(project, revision, inputs, side, proof)
    if any(canonical_json_bytes(ref) not in refs for ref in _references(model)):
        raise ValueError('SOW Model SourceRef does not match exact frozen source bytes')
    scope = api._benchmark_scope_evidence(model, oracle, locators, aliases=aliases)
    browser = verify_browser(api, root.root, pair_id, side)
    if browser['outcome'] != 'VERIFIED': raise ValueError('browser discovery remains INCOMPLETE_BUDGET')
    inventory, dispositions = [], []
    from stage_planner import _effective_success
    for stage, body in proof['stages'].items():
        for work in body['plan']['works']:
            _, record = _effective_success(ledger, work['logicalWorkId'])
            envelope = ledger.envelopes_by_sha256[record.envelope_sha256].value
            packet = json.loads(packets[envelope['packetSha256']])
            expected = [row['workItemId'] for row in work['packetPlan']['orderedWorkItems']]
            if [row['workItemId'] for row in packet['workItems']] != expected:
                raise ValueError('effective packet does not preserve sealed work-item inventory')
            for identity in expected:
                key = stage + '/' + work['logicalWorkId'] + '/' + identity
                inventory.append(key); dispositions.append({'workItemId': key, 'disposition': 'SUCCEEDED'})
    rate = api._benchmark_disposition_rate(inventory, dispositions, id_key='workItemId', terminal={'SUCCEEDED'}, sealed=True)
    return {'project': project, 'request': request, 'runId': run_id, 'events': events, 'state': state,
        'revision': revision, 'manifest': manifest, 'artifactRoot': artifact_root, 'proof': proof,
        'ledger': ledger, 'scope': scope, 'refs': refs, 'aliases': aliases,
        'workRate': rate, 'browserRate': browser['demoInteractionDispositionRate'], 'browserProfileSha256': browser['browserProfileSha256'],
        'counts': api._benchmark_final_counts(proof['stages'], ledger, packets),
        'observations': api._benchmark_attempt_observations(ledger, scope['formalNodeCount']),
        'time': api._benchmark_time_observations(ledger, events)}


def calculate(api, pair_root, pair_id):
    files, inputs, oracle, _ = prepared(api, pair_root, pair_id)
    green = _read_side(api, files, pair_id, 'greenfield', inputs, oracle)
    brown = _read_side(api, files, pair_id, 'brownfield', inputs, oracle)
    if green['browserProfileSha256'] != brown['browserProfileSha256']:
        raise ValueError('the two sides must use the same frozen browser environment')
    end = next(e.occurred_at_utc for e in green['events'] if e.type == 'RUN_STATE_CHANGED'
        and e.payload['toState'] == 'AWAITING_FINAL_REVIEW')
    if datetime.fromisoformat(brown['events'][0].occurred_at_utc) < datetime.fromisoformat(end):
        raise ValueError('Brownfield started before Greenfield final verification')
    if any(row['role'] == 'PRIOR_SOW' for row in green['request']['sources']): raise ValueError('Greenfield must not consume a Prior SOW')
    priors = [row for row in brown['request']['sources'] if row['role'] == 'PRIOR_SOW']
    if len(priors) != 1: raise ValueError('Brownfield must consume exactly the selected Greenfield workbook')
    prior = priors[0]
    template = _json(files, inputs['requests']['brownfieldTemplate']['path'], inputs['requests']['brownfieldTemplate']['sha256'])
    if brown['request'] != api._replace_prior(template, prior['path'], prior['expectedSha256']):
        raise ValueError('Brownfield request differs from frozen template beyond Prior binding')
    revision_priors = [row for row in brown['revision']['sources'] if row['role'] == 'PRIOR_SOW']
    if len(revision_priors) != 1: raise ValueError('Brownfield revision has no unique Prior source')
    checks = []
    def check(point, project, path, digest):
        raw = bound(project, {'path': path, 'sha256': digest})
        checks.append({'point': point, 'size': len(raw), 'sha256': sha256_bytes(raw)})
    check('GREENFIELD_FROZEN', green['project'], green['artifactRoot'] + '/' + green['manifest']['workbook']['path'], green['manifest']['workbook']['sha256'])
    check('BROWNFIELD_INPUT', brown['project'], prior['path'], prior['expectedSha256'])
    check('BROWNFIELD_REVISION', brown['project'], revision_priors[0]['path'], revision_priors[0]['rawSha256'])
    scope_body = brown['proof']['stages']['SCOPE']; checkpoint = scope_body['checkpoint']
    review = scope_body['reviewInputs'][checkpoint['reviewPacketSha256']]
    graph = review['workItems'][0]['payload']['changeGraph']
    scope_model = scope_body['candidates'][checkpoint['candidateSha256']]
    target_ids = {row[key] for name, key in list(api._FORMAL_COLLECTIONS.items())[:6] for row in scope_model[name]}
    changes = api._benchmark_brownfield_evidence(brown['project'], f".ai-sow/work/runs/{brown['runId']}/stages/SCOPE",
        checkpoint, graph, {key: value for key, value in brown['scope']['formalEvidence'].items() if key in target_ids}, oracle,
        prior_refs=green['refs'], aliases=green['aliases'])
    check('BROWNFIELD_FINAL', brown['project'], prior['path'], prior['expectedSha256'])
    sides = [green, brown]; scopes = [row['scope'] for row in sides]; observations = [row['observations'] for row in sides]
    host_expected = []
    for side_name, side in zip(('greenfield', 'brownfield'), sides):
        host_expected.extend(api._host_actions_for_run(
            side_name, side['project'], side['runId'], side['events'], side['ledger']))
    host_observation = api._verify_host_invocations(files.root, pair_id, host_expected)
    nodes = sum(row['formalNodeCount'] for row in scopes)
    matched = set().union(*(set(row['matchedExpectationIds']) for row in scopes))
    total_refs = sum(row['sourceRefCount'] for row in scopes)
    mappings, cells = {}, {}
    for scope in scopes:
        for row in scope['claimMappings']:
            mappings.setdefault(row['formalClaimId'], set()).update(row['expectationIds'])
    for observation in observations:
        for row in observation['tokensByCategoryProvenanceAndKind']:
            key = (row['usageCategory'], row['provenance'], row['tokenKind'])
            previous = cells.get(key, 0)
            cells[key] = None if previous is None or row['tokens'] is None else previous + row['tokens']
    def total(key): return sum(row[key] for row in observations)
    def ratio(numerator, denominator, empty=1.0): return numerator / denominator if denominator else empty
    model_attempts = total('modelAttemptCount')
    provider_attempts = total('providerReportedAttemptCount')
    token_state = ('UNAVAILABLE' if provider_attempts == 0 else
        'COMPLETE' if provider_attempts == model_attempts else 'PARTIAL')
    actual_tokens = total('providerActualTokens')
    complete = token_state == 'COMPLETE'
    result = {'contract': 'ai-sow-benchmark-result-v2', 'functionalOutcome': 'PASS',
        **{key: changes[key] for key in ('changeGraphClosureRate', 'changeRecall', 'changePrecision', 'unchangedRetention', 'implicitRetireCount')},
        **{key: sum(row['counts'][key] for row in sides) for key in ('unresolvedDiagnostics', 'unresolvedReviewerFindings')},
        **{key: sum(row[key] for row in scopes) for key in ('unsupportedFormalClaims', 'forbiddenScopeClaims')},
        'workItemDispositionRate': min(row['workRate'] for row in sides),
        'demoInteractionDispositionRate': min(row['browserRate'] for row in sides),
        'obligationRecall': ratio(len(matched), len(oracle['expectedObligations'])),
        'scopePrecision': ratio(sum(len(row['claimMappings']) for row in scopes), nodes),
        'sourceRefResolutionRate': ratio(sum(row['resolvedSourceRefCount'] for row in scopes), total_refs),
        'greenfieldRunState': green['state'], 'brownfieldRunState': brown['state'], 'priorTransferChecks': checks,
        'claimMappings': [{'formalClaimId': key, 'expectationIds': sorted(value)}
            for key, value in sorted(mappings.items())],
        'tokenObservationState': token_state,
        'modelAttemptCount': model_attempts,
        'providerReportedAttemptCount': provider_attempts,
        'observedActualTokens': actual_tokens if provider_attempts else None,
        'completeActualTokens': actual_tokens if complete else None,
        'tokensByCategoryProvenanceAndKind': [{'usageCategory': key[0], 'provenance': key[1],
            'tokenKind': key[2], 'tokens': value} for key, value in sorted(cells.items())],
        'tokensPerFormalNode': ratio(actual_tokens, nodes, None) if complete else None,
        'retryAmplification': ratio(actual_tokens, total('providerEffectiveSuccessTokens'), None) if complete else None,
        'invalidIrRate': ratio(total('invalidIrCount'), model_attempts),
        'repairRate': ratio(total('successfulRepairCount'), total('successfulAuthorCount')),
        'budgetVarianceTokens': actual_tokens - total('plannedTokens') if complete else None,
        **{key: sum(row['time'][key] for row in sides) for key in ('activeWallTime', 'userWaitingTime')}}
    api._validate_functional_acceptance(result, host_observation)
    api._validate_performance_observation(result)
    return result
