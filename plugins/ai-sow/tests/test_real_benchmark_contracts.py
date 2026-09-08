"""The real benchmark's primitive contract gates; no provider or browser calls."""
from __future__ import annotations

import copy
import importlib
import json
import sys
from pathlib import Path

import pytest

TEST_LAYER = 'unit'
SUPPORT = Path(__file__).parent / 'support'
sys.path.insert(0, str(SUPPORT))


def benchmark():
    return importlib.import_module('run_paired_benchmark')


def test_total_calculator_requires_sealed_runs_and_does_not_consume_aggregate(tmp_path, monkeypatch):
    attempt_fixture()
    baseline, output, draft, hashes = preparation_fixture(tmp_path); pair = benchmark()
    monkeypatch.setattr(pair, '_BENCHMARK_BASELINE_SHA256', hashes)
    prepared = pair._prepare_benchmark(baseline, output, draft)
    (output / 'benchmark-result.json').write_text(json.dumps(result()))
    before = {p.relative_to(output).as_posix(): p.read_bytes() for p in output.rglob('*') if p.is_file()}
    with pytest.raises((ValueError, OSError)):
        pair.calculate_benchmark_result(output, prepared['pairRunId'])
    assert before == {p.relative_to(output).as_posix(): p.read_bytes() for p in output.rglob('*') if p.is_file()}


def expectation():
    return {
        'expectedObligations': [{'expectationId': 'expected-1', 'sourceId': 'v1-prd',
            'exactLocator': 'section:退款/paragraph:0001', 'requiredDisposition': 'FORMAL_CLAIM'}],
        'expectedBrownfieldChanges': [{'expectationId': 'change-1',
            'priorLocatorIds': ['v1-prd#section:退款/paragraph:0001'],
            'targetLocatorIds': ['v2-prd#section:退款/paragraph:0001'], 'allowedKinds': ['ADJUST']}],
        'expectedUnchangedCapabilities': [{'expectationId': 'unchanged-1',
            'priorLocatorIds': ['v1-hld#heading:接口']}],
    }


@pytest.mark.parametrize('mutation', ['valid', 'extra', 'duplicate', 'disposition', 'kind', 'empty-id'])
def test_expectation_manifest_closed_contract(mutation):
    value = expectation()
    if mutation == 'extra': value['metrics'] = {}
    elif mutation == 'duplicate': value['expectedUnchangedCapabilities'][0]['expectationId'] = 'expected-1'
    elif mutation == 'disposition': value['expectedObligations'][0]['requiredDisposition'] = 'SCOPE_NODE'
    elif mutation == 'kind': value['expectedBrownfieldChanges'][0]['allowedKinds'] = ['KEEP']
    elif mutation == 'empty-id': value['expectedObligations'][0]['sourceId'] = ''
    if mutation == 'valid': benchmark()._validate_expectation_manifest(value)
    else:
        with pytest.raises(ValueError): benchmark()._validate_expectation_manifest(value)


ZERO_GATES = ('unresolvedDiagnostics', 'unsupportedFormalClaims', 'forbiddenScopeClaims',
    'unresolvedReviewerFindings', 'implicitRetireCount')
ONE_GATES = ('workItemDispositionRate', 'obligationRecall', 'scopePrecision',
    'sourceRefResolutionRate', 'changeGraphClosureRate', 'changeRecall', 'changePrecision',
    'unchangedRetention', 'demoInteractionDispositionRate')


def result(token_state='COMPLETE'):
    provider_count = {'COMPLETE': 3, 'PARTIAL': 2, 'UNAVAILABLE': 0}[token_state]
    observed = {'COMPLETE': 42, 'PARTIAL': 28, 'UNAVAILABLE': None}[token_state]
    rows = ([{'usageCategory': 'AUTHOR', 'provenance': 'PROVIDER_REPORTED',
        'tokenKind': 'INPUT', 'tokens': observed - 12 if token_state == 'COMPLETE' else observed - 8},
        {'usageCategory': 'AUTHOR', 'provenance': 'PROVIDER_REPORTED',
        'tokenKind': 'OUTPUT', 'tokens': 12 if token_state == 'COMPLETE' else 8}]
        if observed is not None else [])
    if token_state != 'COMPLETE':
        rows.append({'usageCategory': 'AUTHOR', 'provenance': 'LOCALLY_ESTIMATED',
            'tokenKind': 'INPUT', 'tokens': 10})
    complete = token_state == 'COMPLETE'
    return {'contract': 'ai-sow-benchmark-result-v2', 'functionalOutcome': 'PASS',
        **dict.fromkeys(ZERO_GATES, 0), **dict.fromkeys(ONE_GATES, 1.0),
        'greenfieldRunState': 'AWAITING_FINAL_REVIEW', 'brownfieldRunState': 'AWAITING_FINAL_REVIEW',
        'priorTransferChecks': [{'point': point, 'size': 42, 'sha256': 'a' * 64}
            for point in ('GREENFIELD_FROZEN', 'BROWNFIELD_INPUT', 'BROWNFIELD_REVISION', 'BROWNFIELD_FINAL')],
        'tokenObservationState': token_state, 'modelAttemptCount': 3,
        'providerReportedAttemptCount': provider_count,
        'observedActualTokens': observed, 'completeActualTokens': observed if complete else None,
        'tokensByCategoryProvenanceAndKind': rows,
        'tokensPerFormalNode': 2.5 if complete else None,
        'retryAmplification': 1.0 if complete else None,
        'invalidIrRate': 0.0, 'repairRate': 0.0,
        'budgetVarianceTokens': -10 if complete else None,
        'activeWallTime': 3.0, 'userWaitingTime': 2.0,
        'claimMappings': [],
    }


def verified_host(action_count=3):
    return {'outcome': 'VERIFIED', 'modelActionCount': action_count}


@pytest.mark.parametrize('field', [*ZERO_GATES, *ONE_GATES, 'greenfieldRunState',
    'brownfieldRunState', 'prior-size', 'prior-hash', 'prior-duplicate',
    'functionalOutcome', 'host'])
def test_benchmark_functional_gates_each_failure(field):
    value = result('PARTIAL'); host = verified_host()
    if field in ZERO_GATES: value[field] = 1
    elif field in ONE_GATES: value[field] = .99
    elif field.endswith('RunState'): value[field] = 'PUBLISHED'
    elif field == 'prior-size': value['priorTransferChecks'][3]['size'] += 1
    elif field == 'prior-hash': value['priorTransferChecks'][3]['sha256'] = 'b' * 64
    elif field == 'prior-duplicate': value['priorTransferChecks'][3] = copy.deepcopy(value['priorTransferChecks'][0])
    elif field == 'functionalOutcome': value[field] = 'FAIL'
    else: host['outcome'] = 'ERROR'
    with pytest.raises(ValueError):
        benchmark()._validate_functional_acceptance(value, host)


@pytest.mark.parametrize('token_state', ['COMPLETE', 'PARTIAL', 'UNAVAILABLE'])
def test_benchmark_functional_acceptance_is_independent_of_token_observation(token_state):
    value = result(token_state)
    benchmark()._validate_functional_acceptance(value, verified_host())
    benchmark()._validate_performance_observation(value)

def test_complete_token_observation_allows_undefined_zero_denominator_ratio():
    value = result('COMPLETE')
    value['retryAmplification'] = None
    benchmark()._validate_functional_acceptance(value, verified_host())
    benchmark()._validate_performance_observation(value)


def test_benchmark_result_v2_closed_schema_requires_every_field():
    for field in result():
        value = result(); del value[field]
        with pytest.raises(ValueError):
            benchmark()._validate_performance_observation(value)


@pytest.mark.parametrize('mutation', ['state', 'count', 'subtotal', 'complete-total',
    'ratio', 'variance', 'duplicate-cell', 'reasoning-null'])
def test_benchmark_token_observation_semantics_are_closed(mutation):
    value = result('PARTIAL')
    if mutation == 'state': value['tokenObservationState'] = 'COMPLETE'
    elif mutation == 'count': value['providerReportedAttemptCount'] = 4
    elif mutation == 'subtotal': value['observedActualTokens'] += 1
    elif mutation == 'complete-total': value['completeActualTokens'] = value['observedActualTokens']
    elif mutation == 'ratio': value['tokensPerFormalNode'] = 2.5
    elif mutation == 'variance': value['budgetVarianceTokens'] = -10
    elif mutation == 'duplicate-cell': value['tokensByCategoryProvenanceAndKind'].append(
        copy.deepcopy(value['tokensByCategoryProvenanceAndKind'][0]))
    else: value['tokensByCategoryProvenanceAndKind'] = [
        {'usageCategory': 'AUTHOR', 'provenance': 'PROVIDER_REPORTED',
            'tokenKind': 'INPUT', 'tokens': None}]
    with pytest.raises(ValueError):
        benchmark()._validate_performance_observation(value)


def host_observation():
    pair_id = 'pair-' + 'a' * 64
    actions = [
        {'side': side, 'runId': 'run-' + side.lower(), 'actionId': 'action-' + side.lower(),
            'pluginRequestSha256': digest * 64, 'contextPolicy': 'FRESH_NO_HISTORY',
            'freshWorker': True, 'workerInvocationIdSha256': worker * 64,
            'host': None, 'model': None}
        for side, digest, worker in (('GREENFIELD', 'b', 'd'), ('BROWNFIELD', 'c', 'e'))]
    expected = [{key: row[key] for key in ('side', 'runId', 'actionId', 'pluginRequestSha256')}
        for row in actions]
    return {'contract': 'ai-sow-host-invocation-observation-v1', 'pairRunId': pair_id,
        'controllerSessionFresh': True, 'maxConcurrency': 1, 'actions': actions}, expected


@pytest.mark.parametrize('mutation', ['valid', 'missing', 'duplicate', 'request-hash',
    'fresh-worker', 'worker-reuse', 'extra', 'absolute-host'])
def test_host_invocation_observation_covers_exact_fresh_actions(mutation):
    value, expected = host_observation()
    if mutation == 'missing': value['actions'].pop()
    elif mutation == 'duplicate':
        duplicate = copy.deepcopy(value['actions'][0])
        duplicate['workerInvocationIdSha256'] = 'f' * 64
        value['actions'].append(duplicate)
    elif mutation == 'request-hash': value['actions'][0]['pluginRequestSha256'] = '0' * 64
    elif mutation == 'fresh-worker': value['actions'][0]['freshWorker'] = False
    elif mutation == 'worker-reuse':
        value['actions'][1]['workerInvocationIdSha256'] = value['actions'][0]['workerInvocationIdSha256']
    elif mutation == 'extra': value['actions'][0]['messages'] = []
    elif mutation == 'absolute-host': value['actions'][0]['host'] = '/private/host'
    if mutation == 'valid':
        benchmark()._validate_host_invocation_observation(value, expected)
    else:
        with pytest.raises(ValueError):
            benchmark()._validate_host_invocation_observation(value, expected)

def publish_host_observation(root, pair_id, expected):
    pair = benchmark()
    actions = []
    for index, row in enumerate(expected, 1):
        actions.append({**row, 'contextPolicy': 'FRESH_NO_HISTORY', 'freshWorker': True,
            'workerInvocationIdSha256': f'{index:064x}', 'host': None, 'model': None})
    value = {'contract': 'ai-sow-host-invocation-observation-v1', 'pairRunId': pair_id,
        'controllerSessionFresh': True, 'maxConcurrency': 1, 'actions': actions}
    raw = pair.canonical_json_bytes(value)
    directory = root / 'host-invocations'
    directory.mkdir(exist_ok=True)
    path = directory / f'{pair.sha256_bytes(raw)}.json'
    path.write_bytes(raw)
    return path


def test_host_invocation_observation_is_canonical_content_addressed_and_unique(tmp_path):
    pair = benchmark()
    value, expected = host_observation()
    path = publish_host_observation(tmp_path, value['pairRunId'], expected)
    other = copy.deepcopy(value)
    other['pairRunId'] = 'pair-' + 'f' * 64
    other_raw = pair.canonical_json_bytes(other)
    (path.parent / f'{pair.sha256_bytes(other_raw)}.json').write_bytes(other_raw)
    digest, loaded = pair._load_host_invocation_observation(tmp_path, value['pairRunId'])
    assert digest == path.stem and loaded['pairRunId'] == value['pairRunId']
    duplicate = copy.deepcopy(value)
    duplicate['actions'][0]['host'] = 'Codex'
    duplicate_raw = pair.canonical_json_bytes(duplicate)
    (path.parent / f'{pair.sha256_bytes(duplicate_raw)}.json').write_bytes(duplicate_raw)
    with pytest.raises(ValueError, match='exactly one'):
        pair._load_host_invocation_observation(tmp_path, value['pairRunId'])

@pytest.mark.parametrize('mutation', ['filename', 'canonical'])
def test_host_invocation_observation_rejects_unbound_storage(tmp_path, mutation):
    pair = benchmark()
    value, expected = host_observation()
    path = publish_host_observation(tmp_path, value['pairRunId'], expected)
    raw = path.read_bytes()
    path.unlink()
    if mutation == 'filename':
        (path.parent / ('0' * 64 + '.json')).write_bytes(raw)
    else:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
        (path.parent / f'{pair.sha256_bytes(raw)}.json').write_bytes(raw)
    with pytest.raises(ValueError):
        pair._load_host_invocation_observation(tmp_path, value['pairRunId'])


@pytest.mark.parametrize('ids,rows,sealed,expected', [
    (['a', 'b'], [{'id': 'a', 'disposition': 'OBSERVED'}], True, .5),
    (['a'], [{'id': 'a', 'disposition': 'OBSERVED'}, {'id': 'a', 'disposition': 'BROKEN'}], True, 0.0),
    ([], [], True, 1.0), ([], [], False, None),
    ([], [{'id': 'a', 'disposition': 'OBSERVED'}], True, None),
    (['a', 'a'], [], True, None),
])
def test_benchmark_inventory_disposition_sealed_denominator(ids, rows, sealed, expected):
    fn = benchmark()._benchmark_disposition_rate
    if expected is None:
        with pytest.raises(ValueError): fn(ids, rows, id_key='id', terminal={'OBSERVED', 'BROKEN'}, sealed=sealed)
    else:
        assert fn(ids, rows, id_key='id', terminal={'OBSERVED', 'BROKEN'}, sealed=sealed) == expected


def scope_fixture():
    source = {'sourceId': 'v1-prd', 'locator': 'section:退款/paragraph:0001'}
    model = {name: [] for name in ('epics', 'features', 'designItems', 'integrations',
        'nfrs', 'policyInstances', 'stories', 'acceptanceCriteria', 'tasks')}
    model.update(inputItems=[{'inputItemId': 'input-1', 'sourceRefs': [source]}], scopeClosure=[])
    model['features'] = [{'featureId': 'feature-1', 'requirementRefs': ['input-1']}]
    model['stories'] = [{'storyId': 'story-1', 'coverageSet': ['feature-1'], 'requirementRefs': ['input-1']}]
    model['tasks'] = [{'taskId': 'task-1', 'acceptanceCriterionIds': ['ac-1']}]
    model['acceptanceCriteria'] = [{'acceptanceCriterionId': 'ac-1', 'requirementRefs': ['input-1']}]
    return model, expectation(), {('v1-prd', 'section:退款/paragraph:0001')}


@pytest.mark.parametrize('mutation', ['valid', 'unsupported', 'forbidden', 'gate', 'missing-gate', 'dangling', 'cycle'])
def test_benchmark_scope_evidence_typed_join(mutation):
    model, oracle, locators = scope_fixture()
    if mutation == 'unsupported': model['features'][0]['requirementRefs'] = []
    elif mutation == 'forbidden': oracle['expectedObligations'][0]['requiredDisposition'] = 'OUT_OF_SCOPE'
    elif mutation in {'gate', 'missing-gate'}:
        oracle['expectedObligations'].append({'expectationId': 'gate-1', 'sourceId': 'v1-hld',
            'exactLocator': 'heading:验收', 'requiredDisposition': 'PROJECT_GATE'})
        locators.add(('v1-hld', 'heading:验收'))
        if mutation == 'gate': model['scopeClosure'].append({'disposition': 'PROJECT_GATE',
            'sourceRefs': [{'sourceId': 'v1-hld', 'locator': 'heading:验收'}]})
    elif mutation == 'dangling': model['tasks'][0]['acceptanceCriterionIds'] = ['unknown']
    elif mutation == 'cycle': model['inputItems'][0]['requirementRefs'] = ['input-1']
    fn = benchmark()._benchmark_scope_evidence
    if mutation in {'dangling', 'cycle'}:
        with pytest.raises(ValueError): fn(model, oracle, locators)
        return
    value = fn(model, oracle, locators)
    assert value['formalNodeCount'] == 4
    assert value['sourceRefResolutionRate'] == 1.0
    assert value['unsupportedFormalClaims'] == (1 if mutation == 'unsupported' else 0)
    assert value['forbiddenScopeClaims'] == (4 if mutation == 'forbidden' else 0)
    assert value['obligationRecall'] == (0.0 if mutation == 'forbidden' else .5 if mutation == 'missing-gate' else 1.0)
    assert value['scopePrecision'] == (0.0 if mutation == 'forbidden' else .75 if mutation == 'unsupported' else 1.0)


def attempt_fixture(token_state='PARTIAL'):
    benchmark()
    sys.path.insert(0, str(SUPPORT.parents[1] / 'skills/generate/tests'))
    from test_action_ledger import prepared_envelope, changed_envelope, successful_completion
    from action_ledger import ActionLedger, issue, finish
    from models import AttemptCompletion, AttemptDiagnostic, AttemptTiming, Usage
    from dataclasses import replace
    first = prepared_envelope()
    retry = changed_envelope(first, actionId='action-retry', attempt=2)
    ledger = issue(issue(ActionLedger(), first), retry)
    success = successful_completion()
    if token_state == 'UNAVAILABLE':
        success = replace(success, usage=Usage('LOCALLY_ESTIMATED', 10, 4, 3, None))
    ledger, _ = finish(ledger, retry, success)
    ledger, _ = finish(ledger, first, success)
    bad = changed_envelope(first, logicalWorkId='logical-bad', actionId='action-bad')
    ledger = issue(ledger, bad)
    bad_provenance = 'PROVIDER_REPORTED' if token_state == 'COMPLETE' else 'LOCALLY_ESTIMATED'
    ledger, _ = finish(ledger, bad, replace(
        successful_completion(b'{}'), usage=Usage(bad_provenance, 10, 4, 3, None)))
    pre = changed_envelope(first, logicalWorkId='logical-pre', actionId='action-pre')
    ledger = issue(ledger, pre)
    ledger, _ = finish(ledger, pre, AttemptCompletion(None, 'SYSTEM',
        AttemptDiagnostic('NOT_STARTED', '', ()), Usage('PROVIDER_REPORTED', 0, 0, 0, None),
        AttemptTiming(None, '2026-09-05T00:00:01Z')))
    return ledger


def test_benchmark_partial_token_totals_retain_actual_subtotal_and_provenance():
    ledger = attempt_fixture()
    value = benchmark()._benchmark_attempt_observations(ledger, 2)
    cells = {(r['usageCategory'], r['provenance'], r['tokenKind']): r['tokens']
        for r in value['tokensByCategoryProvenanceAndKind']}
    assert cells[('AUTHOR', 'PROVIDER_REPORTED', 'INPUT')] == 20
    assert cells[('AUTHOR', 'PROVIDER_REPORTED', 'OUTPUT')] == 8
    assert cells[('AUTHOR', 'PROVIDER_REPORTED', 'CACHED_INPUT')] == 6
    assert cells[('AUTHOR', 'PROVIDER_REPORTED', 'REASONING')] == 2
    assert cells[('AUTHOR', 'LOCALLY_ESTIMATED', 'REASONING')] is None
    assert cells[('AUTHOR', 'LOCALLY_ESTIMATED', 'INPUT')] == 10
    assert value['tokenObservationState'] == 'PARTIAL'
    assert value['modelAttemptCount'] == 3
    assert value['providerReportedAttemptCount'] == 2
    assert value['observedActualTokens'] == 28
    assert value['completeActualTokens'] is None
    assert value['tokensPerFormalNode'] is None
    assert value['retryAmplification'] is None
    assert value['budgetVarianceTokens'] is None
    assert value['invalidIrRate'] == 1 / 3
    assert value['repairRate'] == 0


@pytest.mark.parametrize('token_state,observed', [('COMPLETE', 42), ('UNAVAILABLE', None)])
def test_benchmark_complete_and_unavailable_token_observations(token_state, observed):
    ledger = attempt_fixture(token_state)
    value = benchmark()._benchmark_attempt_observations(ledger, 2)
    assert value['tokenObservationState'] == token_state
    assert value['observedActualTokens'] == observed
    assert value['completeActualTokens'] == observed
    if token_state == 'COMPLETE':
        estimated = sum(sum(e.value['executionLimits'].values())
            for e in ledger.envelopes_by_sha256.values())
        assert value['tokensPerFormalNode'] == 21
        assert value['retryAmplification'] == 3
        assert value['budgetVarianceTokens'] == 42 - estimated
    else:
        assert value['tokensPerFormalNode'] is None
        assert value['retryAmplification'] is None
        assert value['budgetVarianceTokens'] is None


def test_benchmark_token_ratios_empty_denominators_are_explicit():
    benchmark()
    from action_ledger import ActionLedger
    value = benchmark()._benchmark_attempt_observations(ActionLedger(), 0)
    assert value['tokensPerFormalNode'] is None and value['retryAmplification'] is None
    assert value['invalidIrRate'] == value['repairRate'] == 1.0


@pytest.mark.parametrize('contract_id', ['SCOPE_REPAIR-v1', 'STORY_AC_REPAIR-v1', 'TASK_REPAIR-v1'])
def test_benchmark_repair_usage_category_is_owned_by_versioned_contract(contract_id):
    attempt_fixture()
    from contracts import action_contract_binding
    assert action_contract_binding(benchmark().SKILL_ROOT, contract_id)[0]['usageCategory'] == 'REPAIR'


def test_benchmark_repair_tokens_and_rate_use_actual_repair_attempt():
    attempt_fixture()
    from test_action_ledger import prepared_envelope, changed_envelope, successful_completion
    from action_ledger import ActionLedger, issue, finish
    from contracts import action_contract_binding, canonical_json_bytes
    from ir_samples import scope_decision_ir
    author = prepared_envelope(); ledger = issue(ActionLedger(), author)
    ledger, _ = finish(ledger, author, successful_completion())
    repair = changed_envelope(author, actionId='action-repair', logicalWorkId='logical-repair',
        actionContractId='SCOPE_REPAIR-v1', actionContractSha256=action_contract_binding(benchmark().SKILL_ROOT, 'SCOPE_REPAIR-v1')[1])
    ledger = issue(ledger, repair)
    ledger, record = finish(ledger, repair, successful_completion(canonical_json_bytes(scope_decision_ir())))
    assert record.outcome == 'SUCCEEDED'
    value = benchmark()._benchmark_attempt_observations(ledger, 1)
    assert value['repairRate'] == 1.0
    assert {row['usageCategory'] for row in value['tokensByCategoryProvenanceAndKind']} == {'AUTHOR', 'REPAIR'}


def timing_events(open_wait=False):
    benchmark()
    from models import RunEvent
    rows = [
        (0, 'ACTION_ISSUED', {'actionId': 'action-1', 'logicalWorkId': 'logical-1', 'envelopeSha256': 'a'*64}),
        (3, 'RUN_STATE_CHANGED', {'fromState': 'EPIC_FEATURE', 'toState': 'WAITING_INPUT'}),
        (3, 'WAITING_INPUT_ENTERED', {'waitId': 'wait-1', 'reasonCode': 'BUDGET_EXHAUSTED'}),
    ]
    if not open_wait:
        rows += [(5, 'WAITING_INPUT_EXITED', {'waitId': 'wait-1', 'resolutionKind': 'ABANDONED'}),
            (8, 'DETERMINISTIC_STEP_FINISHED', {'stepKind': 'OFFICE', 'outcome': 'SUCCEEDED',
                'startedAtUtc': '2026-09-05T00:00:02Z', 'endedAtUtc': '2026-09-05T00:00:08Z'}),
            (10, 'RUN_STATE_CHANGED', {'fromState': 'DRAFT', 'toState': 'AWAITING_FINAL_REVIEW'})]
    return [RunEvent('run-1', i + 1, kind, f'2026-09-05T00:00:{second:02d}Z', payload)
        for i, (second, kind, payload) in enumerate(rows)]


def test_benchmark_active_time_unions_intervals_and_excludes_waits():
    value = benchmark()._benchmark_time_observations(attempt_fixture(), timing_events())
    assert value == {'activeWallTime': 5.0, 'userWaitingTime': 2.0}


@pytest.mark.parametrize('mutation', ['open', 'unmatched', 'reused', 'bad-state', 'reverse-time'])
def test_benchmark_user_waiting_rejects_unfinished_or_invalid_log(mutation):
    from dataclasses import replace
    ledger = attempt_fixture(); events = timing_events(mutation in {'open', 'bad-state'})
    if mutation == 'bad-state': events[1] = replace(events[1], payload={'fromState': 'CREATED', 'toState': 'DRAFT'})
    elif mutation == 'unmatched': events[3] = replace(events[3], payload={'waitId': 'unknown', 'resolutionKind': 'ABANDONED'})
    elif mutation == 'reused': events[3] = replace(events[2], sequence=4)
    elif mutation == 'reverse-time': events[3] = replace(events[3], occurred_at_utc='2026-09-05T00:00:01Z')
    with pytest.raises(ValueError): benchmark()._benchmark_time_observations(ledger, events)


def prior_fixture(root):
    pair = benchmark()
    from contracts import canonical_json_bytes, sha256_bytes
    from test_change_graph import prior_snapshot
    from runtime.project_io import ProjectFiles
    snapshot = prior_snapshot()
    for evidence in snapshot['evidence']:
        digit = evidence['priorEvidenceId'][0]
        evidence['canonicalCellValues'] = [{'value': 'p-' + digit}, {'value': 'SourceRef'},
            {'value': json.dumps({'sourceId': 'v1-prd', 'locator': 'paragraph:' + digit,
                'blockId': 'block-' + digit, 'sha256': digit * 64})}]
        evidence['canonicalCellValuesSha256'] = sha256_bytes(canonical_json_bytes(evidence['canonicalCellValues']))
    raw = canonical_json_bytes(snapshot); digest = sha256_bytes(raw)
    files = ProjectFiles.open(root)
    files.publish_new('scope/prior-states/' + digest + '.json', raw)
    oracle = {'expectedObligations': [], 'expectedBrownfieldChanges': [
        {'expectationId': 'adjust-1', 'priorLocatorIds': ['v1-prd#paragraph:1'],
            'targetLocatorIds': ['v2-prd#paragraph:1'], 'allowedKinds': ['ADJUST']}],
        'expectedUnchangedCapabilities': [{'expectationId': 'keep-1', 'priorLocatorIds': ['v1-prd#paragraph:3']}]}
    graph = {'changeGroups': [{'kind': 'ADJUST', 'priorEntityIds': ['p-a'],
        'targetEntityIds': ['t-a'], 'evidenceIds': ['current-change']}], 'retiredPrior': []}
    return files, {'priorStateSha256': digest}, graph, {'t-a': {('v2-prd', 'paragraph:1')}}, oracle


@pytest.mark.parametrize('mutation', ['valid', 'hash', 'missing', 'duplicate-source', 'predecessor',
    'unexpected-new', 'expected-missing', 'ambiguous', 'retired', 'implicit-retire'])
def test_benchmark_brownfield_evidence_checkpoint_projection_and_unique_join(tmp_path, mutation):
    # Import previous shared fixtures only after the existing benchmark module is loaded.
    attempt_fixture()
    files, checkpoint, graph, target, oracle = prior_fixture(tmp_path)
    if mutation == 'hash': checkpoint['priorStateSha256'] = 'f' * 64
    elif mutation == 'missing': (tmp_path / 'scope/prior-states' / (checkpoint['priorStateSha256'] + '.json')).unlink()
    elif mutation == 'duplicate-source': graph['changeGroups'][0]['priorEntityIds'] = ['p-b']
    elif mutation == 'predecessor': graph['changeGroups'][0]['priorEntityIds'] = ['p-old']
    elif mutation == 'unexpected-new': target['t-b'] = {('v2-prd', 'paragraph:2')}
    elif mutation == 'expected-missing': oracle['expectedBrownfieldChanges'][0]['targetLocatorIds'] = ['v2-prd#paragraph:missing']
    elif mutation == 'ambiguous': oracle['expectedBrownfieldChanges'].append({**oracle['expectedBrownfieldChanges'][0], 'expectationId': 'other'})
    elif mutation in {'retired', 'implicit-retire'}:
        graph['retiredPrior'] = [{'priorEntityId': 'p-new', 'evidenceIds': ['3' * 64, 'current-removal']}]
        if mutation == 'implicit-retire': graph['retiredPrior'][0]['evidenceIds'] = ['3' * 64]
    fn = benchmark()._benchmark_brownfield_evidence
    if mutation in {'hash', 'missing', 'duplicate-source', 'predecessor', 'ambiguous'}:
        with pytest.raises(ValueError): fn(files, 'scope', checkpoint, graph, target, oracle)
        return
    value = fn(files, 'scope', checkpoint, graph, target, oracle)
    assert value['activePriorEntityIds'] == ['p-a', 'p-new']
    assert value['unchangedRetention'] == (0.0 if mutation in {'retired', 'implicit-retire'} else 1.0)
    assert value['changeRecall'] == (0.0 if mutation == 'expected-missing' else 1.0)
    assert value['changePrecision'] == (0.0 if mutation == 'expected-missing' else .5 if mutation in {'unexpected-new', 'retired', 'implicit-retire'} else 1.0)
    assert value['implicitRetireCount'] == (1 if mutation == 'implicit-retire' else 0)


@pytest.mark.parametrize('tampered', [False, True])
def test_benchmark_visible_source_refs_still_bind_original_hash_with_xlsx_locators(tmp_path, tampered):
    attempt_fixture()
    pair = benchmark()
    files, checkpoint, graph, target, oracle = prior_fixture(tmp_path)
    snapshot = files.read_json('scope/prior-states/' + checkpoint['priorStateSha256'] + '.json')
    prior_refs = set()
    for index, row in enumerate(snapshot['evidence'], start=5):
        cells = row['canonicalCellValues']
        ref = json.loads(cells[-1]['value'])
        prior_refs.add(pair.canonical_json_bytes(ref))
        if tampered and index == 5:
            ref['sha256'] = 'f' * 64
            cells[-1]['value'] = json.dumps(ref)
        row.update(sheet='03-工作量汇总', absoluteA1Range=f'$A${index}:$C${index}',
            canonicalCellValuesSha256=pair.sha256_bytes(pair.canonical_json_bytes(cells)))
    raw = pair.canonical_json_bytes(snapshot)
    checkpoint['priorStateSha256'] = pair.sha256_bytes(raw)
    files.publish_new('scope/prior-states/' + checkpoint['priorStateSha256'] + '.json', raw)
    if tampered:
        with pytest.raises(ValueError, match='SourceRef does not resolve to frozen v1 bytes'):
            pair._benchmark_brownfield_evidence(files, 'scope', checkpoint, graph, target, oracle, prior_refs=prior_refs)
    else:
        value = pair._benchmark_brownfield_evidence(files, 'scope', checkpoint, graph, target, oracle, prior_refs=prior_refs)
        assert value['changePrecision'] == value['changeRecall'] == value['unchangedRetention'] == 1.0


@pytest.mark.parametrize('mutation', ['valid', 'diagnostic', 'resolved', 'no-repair', 'wrong-trigger', 'non-semantic', 'no-pass'])
def test_benchmark_final_counts_requires_actual_repair_successor(mutation):
    attempt_fixture()
    from test_action_ledger import prepared_envelope, changed_envelope, successful_completion
    from action_ledger import ActionLedger, issue, finish, attempt_record_value
    from contracts import canonical_json_bytes, sha256_bytes, action_contract_binding
    from ir_samples import scope_decision_ir
    pair = benchmark(); packets = {}; ledger = ActionLedger()
    finding = {'code': 'MISSING_BOUNDARY', 'path': '', 'subjectIds': ['root-1'], 'evidenceIds': [], 'message': '缺少边界'}
    old = {'decision': 'CONTRACT_GAP' if mutation == 'non-semantic' else 'REPAIRABLE_SEMANTIC', 'findings': [finding]}
    old_hash = sha256_bytes(canonical_json_bytes(old))

    def complete(name, contract_id, candidate, response, packet):
        nonlocal ledger
        packet_raw = canonical_json_bytes(packet); packet_hash = sha256_bytes(packet_raw); packets[packet_hash] = packet_raw
        _, contract_hash = action_contract_binding(pair.SKILL_ROOT, contract_id)
        envelope = changed_envelope(prepared_envelope(), actionId='action-' + name, logicalWorkId='logical-' + name,
            actionContractId=contract_id, actionContractSha256=contract_hash, stageKind='SCOPE',
            baseCandidateSha256=candidate, packetSha256=packet_hash)
        ledger = issue(ledger, envelope)
        ledger, record = finish(ledger, envelope, successful_completion(canonical_json_bytes(response)))
        assert record.outcome == 'SUCCEEDED'
        return record

    complete('old', 'SOURCE_SCOPE-v1', 'a'*64, old, {'workItems': [], 'contextRefs': []})
    if mutation not in {'no-repair', 'non-semantic'}:
        complete('repair', 'SCOPE_REPAIR-v1', old_hash, scope_decision_ir(),
            {'workItems': [{'workItemId': 'repair-decisions', 'payload': {
                'reviewDecisionSha256': 'c'*64 if mutation == 'wrong-trigger' else old_hash, 'reviewDecision': old}}], 'contextRefs': []})
    final = old if mutation == 'no-pass' else {'decision': 'PASS', 'findings': []}
    final_record = complete('final', 'SOURCE_SCOPE-v1', 'b'*64, final, {'workItems': [], 'contextRefs': []})
    validator = {'diagnostics': [{'code': 'ISSUE', 'status': 'RESOLVED' if mutation == 'resolved' else 'OPEN'}]
        if mutation in {'diagnostic', 'resolved'} else []}
    validator_hash = sha256_bytes(canonical_json_bytes(validator))
    stages = {'SCOPE': {'checkpoint': {'candidateSha256': 'b'*64,
        'reviewDecisionSha256': final_record.normalized_result_sha256, 'validatorResultSha256': validator_hash},
        'validators': {validator_hash: validator}}}
    value = pair._benchmark_final_counts(stages, ledger, packets)
    assert value['unresolvedDiagnostics'] == (1 if mutation == 'diagnostic' else 0)
    assert value['unresolvedReviewerFindings'] == (2 if mutation == 'no-pass' else 1 if mutation in {'no-repair', 'wrong-trigger', 'non-semantic'} else 0)


@pytest.mark.parametrize('mutation', ['valid', 'profile', 'external', 'source', 'dirty', 'incomplete'])
def test_browser_trace_fixture_contract_fixed_environment_and_budget(mutation):
    attempt_fixture()
    from test_prototype_analysis import demo_files, scenario_fixture, trace_fixture
    from prototype_analysis import inventory_demo_bundle
    from contracts import canonical_json_bytes, sha256_bytes
    inventory = inventory_demo_bundle('demo/index.html', demo_files())
    scenario = scenario_fixture(inventory); trace = trace_fixture(inventory, scenario)
    expected_profile = copy.deepcopy(trace['browserProfile'])
    if mutation == 'profile':
        trace['browserProfile']['locale'] = 'changed'
        for row in trace['runs']: row['browserProfileSha256'] = sha256_bytes(canonical_json_bytes(trace['browserProfile']))
    elif mutation == 'external': trace['externalRequestCount'] = 1
    elif mutation == 'source': trace['files'][0]['sha256'] = 'f'*64
    elif mutation == 'dirty': trace['browserProfile']['cleanProfile'] = False
    elif mutation == 'incomplete':
        scenario['scenarios'][0]['critical'] = True
        trace['scenarioSha256'] = sha256_bytes(canonical_json_bytes(scenario))
    fn = benchmark()._benchmark_browser_trace
    if mutation in {'profile', 'external', 'source', 'dirty'}:
        with pytest.raises(ValueError): fn(inventory, scenario, trace, expected_profile)
    else:
        value = fn(inventory, scenario, trace, expected_profile)
        assert value['outcome'] == ('WAITING_INPUT' if mutation == 'incomplete' else 'VERIFIED')
        if mutation == 'incomplete': assert value['reasonCode'] == 'INCOMPLETE_BUDGET'


def preparation_fixture(root, hld_text='# 设计\n\nLocal status only.\n', two_controls=False):
    pair = benchmark()
    from contracts import canonical_json_bytes, sha256_bytes
    from source_readers import html_elements, extract_source_blocks
    from test_contracts import valid_run_budget_policy
    baseline = root / 'baseline'; output = root / 'output'
    baseline.mkdir(); output.mkdir()
    hashes, conversions = {}, {}
    for version, side, mode, date in [('v1', 'greenfield', 'GREENFIELD', '2026-11-16'),
        ('v2', 'brownfield', 'BROWNFIELD', '2027-02-15')]:
        request = json.loads((pair.SKILL_ROOT / f'fixtures/pipeline/e2e/{side}/request.json').read_bytes())
        request['contract'] = 'ai-sow-generate-request-v2'; request['project']['plannedEffectiveDate'] = date
        request['sources'] = []
        for kind, text in [('prd', '# 业务\n\nSave updates status.\n'), ('hld', hld_text),
            ('demo', '# 演示\n\nClick Save to display saved. Each batch contains at most 100 rows.\n')]:
            relative = f'inputs/{version}/{kind}.md'; path = baseline / relative; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text); hashes[relative] = sha256_bytes(path.read_bytes())
            request['sources'].append({'sourceId': kind, 'role': kind.upper(), 'path': relative, 'expectedSha256': hashes[relative]})
        req_path = f'requests/{version}.json'; path = baseline / req_path; path.parent.mkdir(exist_ok=True)
        path.write_bytes(canonical_json_bytes(request)); hashes[req_path] = sha256_bytes(path.read_bytes())
        contents = {'index.html': '<button id="save">Save</button><script src="app.js"></script><link rel="stylesheet" href="style.css">',
            'app.js': 'document.querySelector("#save").addEventListener("click",()=>{document.querySelector("#save").textContent="saved"});',
            'style.css': 'button { color: blue; }'}
        if two_controls: contents['index.html'] += '<button id="cancel">Cancel</button>'
        rows, mappings = [], []
        locator = f'{version}-demo#heading:演示'
        for relative, content in contents.items():
            draft = f'oracle/demo/{side}/{relative}'; path = output / draft; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(content)
            rows.append({'relativePath': relative, 'sourceId': f'{version}-demo-' + relative.replace('.', '-'), 'draftPath': draft})
            for block in extract_source_blocks(path, source_role='DEMO', parser_version='benchmark-source-v1').blocks:
                mappings.append({'kind': 'SOURCE', 'subject': relative + '#' + block['locator'],
                    'disposition': 'SOURCE_MAPPED', 'sourceLocators': [locator]})
        for element in html_elements(contents['index.html']):
            selector = '#' + element['attributes']['id'] if element['attributes'].get('id') else element['selector']
            mappings.append({'kind': 'DOM', 'subject': 'index.html#' + selector,
                'disposition': 'SOURCE_MAPPED', 'sourceLocators': [locator]})
        mappings.append({'kind': 'SCENARIO', 'subject': 'index.html##save:click',
            'disposition': 'SOURCE_MAPPED', 'sourceLocators': [locator]})
        if two_controls:
            mappings.append({'kind': 'SCENARIO', 'subject': 'index.html##cancel:click',
                'disposition': 'SOURCE_MAPPED', 'sourceLocators': [locator]})
        conversions[side] = {'entrypoint': 'index.html', 'files': rows, 'reverseMappings': mappings}
    (output / 'oracle/demo-conversion-draft.json').write_bytes(canonical_json_bytes(conversions))
    draft = output / 'oracle/benchmark-expectation-draft.json'
    draft.write_bytes(canonical_json_bytes({'expectedObligations': [], 'expectedBrownfieldChanges': [], 'expectedUnchangedCapabilities': []}))
    (output / 'run-budget-policy-source.json').write_bytes(canonical_json_bytes(valid_run_budget_policy()))
    return baseline, output, draft, hashes


def test_frozen_baseline_prepare_complete_inputs_without_starting_runs(tmp_path, monkeypatch):
    attempt_fixture()
    baseline, output, draft, hashes = preparation_fixture(tmp_path)
    pair = benchmark()
    monkeypatch.setattr(pair, '_BENCHMARK_BASELINE_SHA256', hashes, raising=False)
    before = {p.relative_to(baseline).as_posix(): p.read_bytes() for p in baseline.rglob('*') if p.is_file()}
    result = pair._prepare_benchmark(baseline, output, draft)
    assert result['outcome'] == 'PREPARED'
    assert not list(output.rglob('.ai-sow'))
    assert pair._prepare_benchmark(baseline, output, draft) == result
    manifest = json.loads((output / 'benchmark-input-manifest.json').read_bytes())
    assert manifest['pairRunId'] == result['pairRunId']
    assert len(manifest['baselineFiles']) == 8 and len(manifest['frozenSources']) == 6
    request = json.loads((output / manifest['requests']['greenfield']['path']).read_bytes())
    template = json.loads((output / manifest['requests']['brownfieldTemplate']['path']).read_bytes())
    assert request['contract'] == 'ai-sow-generate-request-v3'
    assert request['project']['plannedEffectiveDate'] == '2026-11-16'
    assert template['project']['plannedEffectiveDate'] == '2027-02-15'
    assert sum(s['role'] == 'PRIOR_SOW' for s in template['sources']) == 1
    assert {p.relative_to(baseline).as_posix(): p.read_bytes() for p in baseline.rglob('*') if p.is_file()} == before


@pytest.mark.parametrize('locator, valid', [
    ('v2-prior#01-需求故事!$A$5:$I$5', True),
    ('v1-prior#01-需求故事!$A$5:$I$5', False),
    ('unselected-prior#01-需求故事!$A$5:$I$5', False),
    ('v2-prior#!$A$5:$I$5', False),
    ('v2-prior#01-需求故事!A5:I5', False),
    ('v2-prior#01-需求故事!$A$0:$I$0', False),
    ('v2-prior#01-需求故事!$I$5:$A$5', False),
    ('v2-prior#01-需求故事!$A$5:$I$6', False),
    ('v2-prior#01-需求故事!$A$5:$XFE$5', False),
    ('v2-prior#01-需求故事!$A$1048577:$I$1048577', False),
])
def test_frozen_baseline_anticipated_prior_locator_binds_selected_source_and_row(tmp_path, monkeypatch, locator, valid):
    attempt_fixture()
    baseline, output, draft, hashes = preparation_fixture(tmp_path)
    pair = benchmark()
    monkeypatch.setattr(pair, '_BENCHMARK_BASELINE_SHA256', hashes)
    oracle = json.loads(draft.read_bytes())
    oracle['expectedUnchangedCapabilities'] = [{'expectationId': 'keep-prior-row', 'priorLocatorIds': [locator]}]
    draft.write_bytes(pair.canonical_json_bytes(oracle))
    if valid:
        assert pair._prepare_benchmark(baseline, output, draft)['outcome'] == 'PREPARED'
        assert not list(output.rglob('.ai-sow'))
    else:
        with pytest.raises(ValueError, match='oracle change locators'):
            pair._prepare_benchmark(baseline, output, draft)
        assert not (output / 'benchmark-input-manifest.json').exists()


def test_frozen_baseline_migrates_legacy_status_and_current_state_delta(tmp_path, monkeypatch):
    attempt_fixture()
    baseline, output, draft, hashes = preparation_fixture(tmp_path)
    pair = benchmark()
    originals = {}
    for version in ('v1', 'v2'):
        relative = f'requests/{version}.json'; path = baseline / relative
        request = json.loads(path.read_bytes())
        request['currentStateDelta'] = request.pop('declaredChangeContext')
        for row in request['sources']:
            row.pop('expectedSha256')
            row['status'] = 'SELECTED' if row['role'] == 'DEMO' else 'APPROVED'
        originals[version] = request
        path.write_bytes(pair.canonical_json_bytes(request)); hashes[relative] = pair.sha256_bytes(path.read_bytes())
    monkeypatch.setattr(pair, '_BENCHMARK_BASELINE_SHA256', hashes)
    result = pair._prepare_benchmark(baseline, output, draft)
    green = json.loads((output / 'runs' / result['pairRunId'] / 'greenfield/project/request.json').read_bytes())
    brown = json.loads((output / 'brownfield-request-template.json').read_bytes())
    assert green['declaredChangeContext'] == originals['v1']['currentStateDelta']
    assert brown['declaredChangeContext'] == originals['v2']['currentStateDelta']
    assert green['responsibilityBoundaries'] == originals['v1']['responsibilityBoundaries']
    assert all('status' not in row and len(row['expectedSha256']) == 64 for row in green['sources'])


@pytest.mark.parametrize('arguments', [
    ['prepare', '--baseline-root', 'missing', '--output-root', 'missing', '--expectation-draft', 'missing.json'],
    ['instantiate-brownfield-request', '--output-root', 'missing', '--pair-run-id', 'pair-missing', '--prior-path', 'missing.xlsx'],
    ['verify-browser-evidence', '--output-root', 'missing', '--pair-run-id', 'pair-missing', '--side', 'greenfield'],
    ['verify-host-invocations', '--output-root', 'missing', '--pair-run-id', 'pair-missing'],
    ['verify-browser-evidence', '--side', 'invalid'], ['verify-host-invocations'], ['unknown-command']])
def test_benchmark_cli_contract_stable_json_and_nonzero_failure(arguments, capsys):
    pair = benchmark()
    assert pair._benchmark_cli_main(arguments) == 2
    first = capsys.readouterr().out; assert json.loads(first)['outcome'] == 'ERROR'
    assert pair._benchmark_cli_main(arguments) == 2
    assert capsys.readouterr().out == first


def test_benchmark_cli_contract_prepare_then_instantiate_is_immutable(tmp_path, monkeypatch, capsys):
    attempt_fixture()
    baseline, output, draft, hashes = preparation_fixture(tmp_path); pair = benchmark()
    monkeypatch.setattr(pair, '_BENCHMARK_BASELINE_SHA256', hashes)
    assert pair._benchmark_cli_main(['prepare', '--baseline-root', str(baseline), '--output-root', str(output),
        '--expectation-draft', str(draft)]) == 0
    result = json.loads(capsys.readouterr().out); pair_id = result['pairRunId']
    prior = output / 'runs' / pair_id / 'brownfield/project/inputs/prior/greenfield-sow.xlsx'
    prior.parent.mkdir(parents=True); prior.write_bytes((pair.SKILL_ROOT / 'assets/sow-template.xlsx').read_bytes())
    args = ['instantiate-brownfield-request', '--output-root', str(output), '--pair-run-id', pair_id, '--prior-path', str(prior)]
    assert pair._benchmark_cli_main(args) == 0
    first = capsys.readouterr().out; request = json.loads(first)['request']
    from contracts import sha256_bytes
    assert sha256_bytes((output / request['path']).read_bytes()) == request['sha256']
    assert pair._benchmark_cli_main(args) == 0
    assert capsys.readouterr().out == first
    assert not list(output.rglob('.ai-sow'))


@pytest.mark.parametrize('mutation', ['baseline', 'business', 'unmapped-demo', 'wrong-side-map', 'batch-500', 'first-action'])
def test_frozen_baseline_demo_reverse_mapping_and_expectation_precedes_first_action(tmp_path, monkeypatch, mutation):
    attempt_fixture()
    baseline, output, draft, hashes = preparation_fixture(tmp_path); pair = benchmark()
    monkeypatch.setattr(pair, '_BENCHMARK_BASELINE_SHA256', hashes)
    if mutation == 'baseline': (baseline / 'inputs/v2/prd.md').write_text('changed')
    elif mutation in {'unmapped-demo', 'wrong-side-map'}:
        p = output / 'oracle/demo-conversion-draft.json'; value = json.loads(p.read_bytes())
        if mutation == 'unmapped-demo': value['greenfield']['reverseMappings'].pop()
        else: value['greenfield']['reverseMappings'][0]['sourceLocators'] = ['v2-demo#heading:演示']
        p.write_text(json.dumps(value))
    elif mutation == 'first-action':
        p = output / 'runs/pair-test/greenfield/project/.ai-sow/work/runs/run-test/events/000001.json'
        p.parent.mkdir(parents=True); p.write_text(json.dumps({'type': 'ACTION_ISSUED'}))
    else:
        result = pair._prepare_benchmark(baseline, output, draft)
        manifest_path = output / 'benchmark-input-manifest.json'; manifest = json.loads(manifest_path.read_bytes())
        if mutation == 'business':
            p = output / manifest['requests']['greenfield']['path']; value = json.loads(p.read_bytes()); value['project']['name'] = 'changed'; p.write_text(json.dumps(value))
        else:
            manifest['brownfieldMaximumBatchRows'] = 500; manifest_path.write_text(json.dumps(manifest))
        from benchmark_execution import prepared
        with pytest.raises(ValueError): prepared(pair, output, result['pairRunId'])
        return
    with pytest.raises(ValueError): pair._prepare_benchmark(baseline, output, draft)
    assert not (output / 'benchmark-input-manifest.json').exists()


@pytest.mark.integration
@pytest.mark.parametrize('disposition', ['OBSERVED', 'EXCLUDED', 'NOT_EXERCISED'])
def test_benchmark_cli_contract_browser_reads_real_run_files_and_screenshot_bytes(tmp_path, monkeypatch, capsys, disposition):
    attempt_fixture()
    from test_prototype_analysis import scenario_fixture, trace_fixture, observation_fixture
    from test_orchestrator import execution_facts
    from contracts import canonical_json_bytes, sha256_bytes
    from runtime.project_io import ProjectFiles
    baseline, output, draft, hashes = preparation_fixture(tmp_path, two_controls=disposition != 'OBSERVED'); pair = benchmark()
    monkeypatch.setattr(pair, '_BENCHMARK_BASELINE_SHA256', hashes)
    result = pair._prepare_benchmark(baseline, output, draft); pair_id = result['pairRunId']
    project = ProjectFiles.open(output / 'runs' / pair_id / 'greenfield/project')
    state = pair.orchestrator.run_mode(project.root, 'start', request='request.json',
        budget_policy=str(output / 'run-budget-policy-source.json'))
    for kind in ('PROTOTYPE_SCENARIO-v1', 'PROTOTYPE_BROWSER-v1', 'PROTOTYPE_ANALYZE-v1'):
        assert state['outcome'] == 'ACTIVE', state
        action = state['nextAction']; assert action['actionContractId'] == kind
        payload = project.read_json(action['packetPath'])['workItems'][0]['payload']
        facts = execution_facts()
        if kind == 'PROTOTYPE_SCENARIO-v1': response = scenario_fixture(payload['inventory'])
        elif kind == 'PROTOTYPE_BROWSER-v1':
            response = trace_fixture(payload['inventory'], payload['scenario']['normalizedResult'])
            import base64
            image = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aK1sAAAAASUVORK5CYII=')
            digest = sha256_bytes(image)
            screenshot = f".ai-sow/work/runs/{state['state']['runId']}/browser-screenshots/{digest}.png"
            project.publish_new(screenshot, image)
            for run in response['runs']:
                for step in run['steps']:
                    if step['screenshotSha256']: step['screenshotSha256'] = digest
            facts['usage'].update(inputTokens=0, outputTokens=0, cachedInputTokens=0, reasoningTokens=None)
        else:
            observations = []
            if disposition != 'OBSERVED':
                chosen = copy.deepcopy(payload['inventory']); chosen['interactions'] = [chosen['interactions'][1]]
                observations.append(observation_fixture(chosen, 'unexecuted') | {'runtimeStatus': 'CODE_ONLY',
                    'scopeRelation': 'NON_SCOPE' if disposition == 'EXCLUDED' else 'ADDITIONAL'})
            response = {'observations': observations}
        project.publish_new(action['resultPath'], canonical_json_bytes(response))
        execution_path = 'execution/' + action['actionId'] + '.json'; project.publish_new(execution_path, canonical_json_bytes(facts))
        state = pair.orchestrator.run_mode(project.root, 'submit', action_id=action['actionId'], result=action['resultPath'], execution=execution_path)
    args = ['verify-browser-evidence', '--output-root', str(output), '--pair-run-id', pair_id, '--side', 'greenfield']
    assert pair._benchmark_cli_main(args) == 0, capsys.readouterr().out
    verified = json.loads(capsys.readouterr().out)
    assert verified['screenshotsVerified'] == 1 and verified['demoInteractionDispositionRate'] == 1.0
    ledger_path = next((project.root / f".ai-sow/work/runs/{verified['runId']}/stages/SCOPE/prototype-ledgers").glob('*.json'))
    original = ledger_path.read_bytes()
    try:
        ledger_path.write_bytes(original + b' ')
        assert pair._benchmark_cli_main(args) == 2
        assert json.loads(capsys.readouterr().out)['outcome'] == 'ERROR'
    finally:
        ledger_path.write_bytes(original)
    (project.root / screenshot).write_bytes(b'changed')
    assert pair._benchmark_cli_main(args) == 2
    assert json.loads(capsys.readouterr().out)['outcome'] == 'ERROR'


@pytest.mark.parametrize('mutation', ['valid', 'bytes', 'binding'])
@pytest.mark.parametrize('terminal_result', ['ABANDONED', 'MANUAL_REVIEW_REQUIRED', 'CONTRACT_UNSUPPORTED', 'SYSTEM_FAILED'])
def test_run_selection_reads_bound_abandon_snapshot_without_wait_event(tmp_path, mutation, terminal_result):
    api = benchmark()
    from contracts import canonical_json_bytes, sha256_bytes
    from runtime.project_io import ProjectFiles
    from benchmark_execution import select_run
    api = benchmark(); files = ProjectFiles.open(tmp_path)
    marker = {'runId':'run-abandoned', 'requestSha256':'a'*64, 'inputRevisionSha256':'b'*64}
    terminal = {**api.orchestrator._initial_run_state(marker), 'phase':'DONE', 'result':terminal_result}
    raw = canonical_json_bytes(terminal)
    location = '.ai-sow/work/runs/run-abandoned/states/state-' + sha256_bytes(raw) + '.json'
    files.publish_new(location, raw + b' ' if mutation == 'bytes' else raw)
    files.publish_new('.ai-sow/work/runs/run-abandoned/input-binding.json', canonical_json_bytes({
        **marker, 'requestSha256':'c'*64 if mutation == 'binding' else 'a'*64,
        'requestPath':'request.json', 'inputRevisionPath':'revision.json'}))
    (tmp_path / '.ai-sow/work/runs/run-current').mkdir()
    if mutation == 'valid':
        assert select_run(api, files) == ('run-current', [], 'ACTIVE')
    else:
        with pytest.raises(ValueError, match='terminal snapshot'):
            select_run(api, files)
