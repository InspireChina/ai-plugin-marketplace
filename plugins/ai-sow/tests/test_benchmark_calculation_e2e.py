"""Synthetic model/browser IR with actual public runs and Office-generated XLSX.

This transport regression is not the real provider/browser benchmark acceptance.
The oracle is authored from fixture source locators before any Action is issued.
"""
from __future__ import annotations

import base64
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_real_benchmark_contracts import attempt_fixture, benchmark, preparation_fixture

TEST_LAYER = 'e2e'


def test_calculate_benchmark_result_from_sequential_sealed_raw_records(tmp_path, monkeypatch):
    attempt_fixture()
    from contracts import canonical_json_bytes, sha256_bytes
    from runtime.project_io import ProjectFiles
    from source_readers import extract_source_blocks
    from test_prototype_analysis import scenario_fixture, trace_fixture
    from stage_driver import stage_result
    from benchmark_execution import instantiate
    pair = benchmark(); baseline, output, draft, hashes = preparation_fixture(tmp_path,
        hld_text='# 设计\n\nLocal status only.\n\nAutomated validation and deployment.\n')
    monkeypatch.setattr(pair, '_BENCHMARK_BASELINE_SHA256', hashes)
    anchors = {}
    oracle = {'expectedObligations': [], 'expectedBrownfieldChanges': [], 'expectedUnchangedCapabilities': []}
    for version in ('v1', 'v2'):
        anchors[version] = []
        for role in ('prd', 'hld'):
            document = extract_source_blocks(baseline / f'inputs/{version}/{role}.md', source_role=role.upper(), parser_version='benchmark-source-v1')
            for block in document.blocks:
                if '/gap:' in block['locator']: continue
                anchor = version + '-' + role + '#' + block['locator']; anchors[version].append(anchor)
                oracle['expectedObligations'].append({'expectationId': 'obligation-' + str(len(oracle['expectedObligations'])),
                    'sourceId': version + '-' + role, 'exactLocator': block['locator'], 'requiredDisposition': 'FORMAL_CLAIM'})
    # The fixture's epic and three policy nodes each use one distinct source block;
    # its feature adjusts the prior capability and keeps all source anchors.
    assert len(anchors['v2']) == 5
    new_anchors = [anchor for anchor in anchors['v2'] if '-hld#' in anchor or '#heading:业务' in anchor]
    for index, anchor in enumerate(new_anchors):
        oracle['expectedBrownfieldChanges'].append({'expectationId': f'new-{index}', 'allowedKinds': ['NEW'],
            'priorLocatorIds': [], 'targetLocatorIds': [anchor]})
    oracle['expectedBrownfieldChanges'].append({'expectationId': 'adjust-feature', 'allowedKinds': ['ADJUST'],
        'priorLocatorIds': anchors['v1'], 'targetLocatorIds': anchors['v2']})
    draft.write_bytes(canonical_json_bytes(oracle))
    # Match the existing paired raw-record fixture's sizing for visible XLSX rows.
    # These are transport-test limits, never an assertion of real provider capacity.
    policy_path = output / 'run-budget-policy-source.json'
    policy = json.loads(policy_path.read_bytes())
    policy.update(modelContextLimitTokens=2000000, maxPlannedTokens=100000000)
    policy_path.write_bytes(canonical_json_bytes(policy))
    prepared = pair._prepare_benchmark(baseline, output, draft); pair_id = prepared['pairRunId']
    image = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aK1sAAAAASUVORK5CYII=')
    image_hash = sha256_bytes(image)
    original_write = ProjectFiles.write_atomic
    recovery = {'injected': False}

    def interrupt_final_pointer(files, path, raw):
        if path == pair.orchestrator.ACTIVE_RUN_PATH and '/greenfield/' in str(files.root) and not recovery['injected']:
            marker = json.loads(raw)
            if marker.get('statePath') and files.read_json(marker['statePath'])['phase'] == 'AWAITING_FINAL_REVIEW':
                recovery['injected'] = True
                raise OSError('fixture crash after final boundary before mutable pointer')
        return original_write(files, path, raw)

    monkeypatch.setattr(ProjectFiles, 'write_atomic', interrupt_final_pointer)

    def drive(side):
        project = ProjectFiles.open(output / 'runs' / pair_id / side / 'project')
        source_roots = {}
        state = pair.orchestrator.run_mode(project.root, 'start', request='request.json', budget_policy=str(output / 'run-budget-policy-source.json'))
        while state['outcome'] == 'ACTIVE':
            action = state['nextAction']; actions = action.get('actions', [action])
            for action in actions:
                packet = project.read_json(action['packetPath']); kind = action['actionContractId'][:-3]
                started = datetime.now(UTC).isoformat(timespec='seconds').replace('+00:00', 'Z')
                if kind == 'PROTOTYPE_SCENARIO': response = scenario_fixture(packet['workItems'][0]['payload']['inventory'])
                elif kind == 'PROTOTYPE_BROWSER':
                    payload = packet['workItems'][0]['payload']
                    response = trace_fixture(payload['inventory'], payload['scenario']['normalizedResult'])
                    project.publish_new(f".ai-sow/work/runs/{state['state']['runId']}/browser-screenshots/{image_hash}.png", image)
                    for run in response['runs']:
                        for step in run['steps']:
                            if step['screenshotSha256']: step['screenshotSha256'] = image_hash
                elif kind == 'PROTOTYPE_ANALYZE': response = {'observations': []}
                elif kind == 'PRIOR_ANALYZE':
                    response = {'entities': [], 'sourceRelations': [], 'entitySupersessions': [], 'unsupportedRegions': [], 'unextractedEvidence': []}
                    for item in packet['workItems']:
                        selected = [row['priorEvidenceId'] for row in item['payload']['evidence']
                            if any(cell['value'] == 'SourceRef' for cell in row['canonicalCellValues'])]
                        if selected:
                            response['entities'].append({'localKey': item['workItemId'] + ':entity', 'sourceId': item['payload']['sourceId'],
                                'entityKind': 'CONTRACT_ENTITY', 'semanticSummary': '已交付的订单查询能力',
                                'deliveryStatus': 'CURRENT_BY_CONTRACT', 'evidenceIds': selected})
                        unused = sorted(set(item['payload']['evidenceIds']) - set(selected))
                        if unused:
                            response['unextractedEvidence'].append({'sourceId': item['payload']['sourceId'], 'evidenceIds': unused,
                                'reason': '测试夹具的表头、估算和重复展示，不形成独立交付'})
                elif kind == 'PRIOR_CONSOLIDATE':
                    response = {'sourceRelations': [], 'entitySupersessions': []}
                else:
                    response = stage_result(kind, packet)
                    if kind == 'SOURCE_SCAN':
                        for item in packet['workItems']:
                            block = item['payload']['sourceBlock']
                            source_roots[block['sourceId'] + '#' + block['locator']] = item['payload']['coverageRootId']
                    if kind == 'SCOPE_SYNTHESIS' and side == 'brownfield':
                        decisions = response['decisions']; roots = decisions[0]['boundaryEvidence']['evidenceIds']
                        assert len(roots) == 5
                        for index, row in enumerate([row for row in decisions if row['decisionKind'] != 'FEATURE']):
                            row['boundaryEvidence']['evidenceIds'] = [source_roots[new_anchors[index]]]
                        prior = next(entity for ref in packet['contextRefs'] if ref['canonicalContent'].get('kind') == 'DEPENDENCY_RESULT'
                            and isinstance(ref['canonicalContent']['normalizedResult'], dict)
                            for entity in ref['canonicalContent']['normalizedResult'].get('entities', []))
                        feature = next(row for row in decisions if row['decisionKind'] == 'FEATURE')
                        feature['priorEntityIds'] = [prior['localKey']]
                        feature['relations'].append({'kind': 'ADJUST', 'targetLocalKeys': [feature['localKey']], 'evidenceIds': roots})
                facts = {'failureKind': None, 'diagnostic': None,
                    'usage': {'provenance': 'LOCALLY_ESTIMATED', 'inputTokens': 0 if kind == 'PROTOTYPE_BROWSER' else 1,
                        'outputTokens': 0 if kind == 'PROTOTYPE_BROWSER' else 1, 'cachedInputTokens': 0, 'reasoningTokens': None},
                    'timing': {'startedAtUtc': started, 'endedAtUtc': datetime.now(UTC).isoformat(timespec='seconds').replace('+00:00', 'Z')}}
                project.publish_new(action['resultPath'], canonical_json_bytes(response))
                execution = 'execution/' + action['actionId'] + '.json'; project.publish_new(execution, canonical_json_bytes(facts))
                state = pair.orchestrator.run_mode(project.root, 'submit', action_id=action['actionId'], result=action['resultPath'], execution=execution)
                if side == 'greenfield' and state['outcome'] == 'BLOCKED' and recovery['injected']:
                    state = pair.orchestrator.run_mode(project.root, 'resume')
                assert state['outcome'] in {'ACTIVE', 'REQUEST_APPROVAL'}, state
        assert state['outcome'] == 'REQUEST_APPROVAL', state
        return project, state

    green, green_result = drive('greenfield')
    assert recovery['injected']
    events = pair.orchestrator._read_run_events(green, green_result['state']['runId'])
    assert len([event for event in events if event.type == 'RUN_STATE_CHANGED'
        and event.payload['toState'] == 'AWAITING_FINAL_REVIEW']) == 1
    instantiate(pair, output, pair_id, green.root / green_result['workbookPath'])
    brown, brown_result = drive('brownfield')
    value = pair.calculate_benchmark_result(output, pair_id)
    pair._validate_benchmark_result(value)
    assert value['scopePrecision'] == value['obligationRecall'] == value['changePrecision'] == 1.0
    assert value['tokensPerFormalNode'] > 0 and value['retryAmplification'] == 1.0
    assert value['activeWallTime'] > 0
    # A forged aggregate cannot influence the calculation; a bound raw byte can.
    (output / 'benchmark-result.json').write_text('{"scopePrecision":0}')
    assert pair.calculate_benchmark_result(output, pair_id) == value
    import pytest
    workbook = brown.root / brown_result['workbookPath']; original = workbook.read_bytes()
    try:
        workbook.write_bytes(b'tampered final Brownfield workbook')
        with pytest.raises(ValueError): pair.calculate_benchmark_result(output, pair_id)
    finally:
        workbook.write_bytes(original)
    prior = pair._prior(brown.read_json('request.json'))
    (brown.root / prior['path']).write_bytes(b'tampered workbook')
    with pytest.raises(ValueError): pair.calculate_benchmark_result(output, pair_id)
