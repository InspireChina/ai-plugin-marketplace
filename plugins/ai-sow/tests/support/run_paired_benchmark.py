"""Local operations support for one review decision over two sealed workbooks.

The host drives each returned rerun with production NextActions. Replaying the
same persisted REJECT continues its transaction; it is not another user decision.
The three names in __all__ retain the paired-review API. The separate benchmark
CLI and calculate_benchmark_result read frozen benchmark inputs and run evidence.
No model worker is implemented here.
"""
from __future__ import annotations

import copy
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from jsonschema import Draft202012Validator

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = PLUGIN_ROOT / 'skills/generate'
for _path in (PLUGIN_ROOT, SKILL_ROOT / 'scripts'):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import generation_store
import orchestrator
from contracts import canonical_json_bytes, load_registry, sha256_bytes, validate_contract
from runtime.project_io import ProjectFiles, ProjectIOError

__all__ = ['instantiate_brownfield_request', 'prepare_pair_review', 'submit_pair_decision']
REGISTRY = load_registry(SKILL_ROOT / 'contracts')
PRIOR_PATH = '${PRIOR_SOW_PATH}'
PRIOR_HASH = '${PRIOR_SOW_SHA256}'
FORBIDDEN = re.compile(r'(^|[/_.-])(model|checkpoint|manifest|chat|sidecar)([/_.-]|$)', re.I)
SIDES = ('green', 'brown')

_BENCHMARK_BASELINE_SHA256 = {
    'inputs/v1/prd.md': '3a02205ad5087fe5536df8f70dce700507db25218e0da6bd2581f75e9fbc6566',
    'inputs/v1/hld.md': '7731f6ccdded6d76e95fd9fcae46a72a372c2a468631b8b5e3013940b68bb4b9',
    'inputs/v1/demo.md': '1390a6949d08356e197f47b1838aecdb646432cecea7a1fcb7d1876e21fae665',
    'inputs/v2/prd.md': 'ccc1852c32493645c6803f8017c03bfb6eadb33d04b8a162a2abfb199279cfa8',
    'inputs/v2/hld.md': 'ddaf008ae79c36d1ec632663869fe30f599c6ffa78f0340d39bbf5707d5d35af',
    'inputs/v2/demo.md': '2b728b1239dc39330cd2de335bca28da4f35530968de1432e8af8346a46f7c24',
    'requests/v1.json': '88d7e5505301ed9ec6f5d59a0166a77c8baf9f13a34b2d6f48ad7b9efade4bd3',
    'requests/v2.json': '83b9a1776b137c760a2f4bdba51c86c97e78d2da8a98253917e9857eda12b690',
}


def _prepare_benchmark(baseline_root, output_root, expectation_draft):
    from benchmark_preparation import prepare
    return prepare(sys.modules[__name__], baseline_root, output_root, expectation_draft)


def calculate_benchmark_result(pair_root, pair_run_id):
    """Recompute the paired result exclusively from sealed production records."""
    from benchmark_calculation import calculate
    return calculate(sys.modules[__name__], pair_root, pair_run_id)

def _load_host_invocation_observation(pair_root, pair_run_id):
    files = ProjectFiles.open(Path(pair_root))
    directory = files.resolve('host-invocations', expect='dir')
    matches = []
    for path in sorted(directory.glob('*.json')):
        relative = path.relative_to(files.root).as_posix()
        raw = files.read_bytes(relative)
        digest = sha256_bytes(raw)
        if path.name != digest + '.json':
            raise ValueError('host invocation observation filename does not bind canonical bytes')
        value = json.loads(raw)
        if canonical_json_bytes(value) != raw:
            raise ValueError('host invocation observation is not canonical JSON')
        _validate(value, 'host-invocation-observation')
        if value['pairRunId'] == pair_run_id:
            matches.append((digest, value))
    if len(matches) != 1:
        raise ValueError('pairRunId requires exactly one host invocation observation')
    return matches[0]


def _host_actions_for_run(side, project, run_id, events, ledger):
    from contracts import action_contract_binding
    expected = []
    for event in events:
        if event.type != 'ACTION_ISSUED':
            continue
        envelope = ledger.envelopes_by_sha256[event.payload['envelopeSha256']].value
        contract, _ = action_contract_binding(SKILL_ROOT, envelope['actionContractId'])
        if contract['executionKind'] != 'MODEL_PROVIDER':
            continue
        expected.append({'side': side.upper(), 'runId': run_id,
            'actionId': envelope['actionId'],
            'pluginRequestSha256': sha256_bytes(
                orchestrator.read_provider_request(project.root, envelope['actionId']))})
    return expected


def _expected_host_invocation_actions(pair_root, pair_run_id):
    from benchmark_execution import prepared, select_run
    files, _, _, _ = prepared(sys.modules[__name__], pair_root, pair_run_id)
    expected = []
    for side in ('greenfield', 'brownfield'):
        project = ProjectFiles.open(files.resolve(f'runs/{pair_run_id}/{side}/project', expect='dir'))
        run_id, events, _ = select_run(sys.modules[__name__], project)
        ledger = orchestrator._load_action_ledger(project, run_id)
        expected.extend(_host_actions_for_run(side, project, run_id, events, ledger))
    return expected


def _validate_host_invocation_observation(value, expected):
    _validate(value, 'host-invocation-observation')
    action_ids = [row['actionId'] for row in value['actions']]
    if len(action_ids) != len(set(action_ids)):
        raise ValueError('host observation actionId must be globally unique')
    invocation_ids = [row['workerInvocationIdSha256'] for row in value['actions']
        if row['workerInvocationIdSha256'] is not None]
    if len(invocation_ids) != len(set(invocation_ids)):
        raise ValueError('fresh workers cannot reuse a host invocation ID')
    for row in value['actions']:
        for key in ('host', 'model'):
            observed = row[key]
            if observed is not None and (Path(observed).is_absolute()
                    or observed.startswith(('~', '\\\\')) or re.match(r'^[A-Za-z]:[\\/]', observed)):
                raise ValueError(key + ' observation must not contain an absolute path')
    keys = ('side', 'runId', 'actionId', 'pluginRequestSha256')
    actual_rows = [tuple(row[key] for key in keys) for row in value['actions']]
    expected_rows = [tuple(row[key] for key in keys) for row in expected]
    if len(expected_rows) != len(set(expected_rows)):
        raise ValueError('expected model Action inventory is not unique')
    if sorted(actual_rows) != sorted(expected_rows):
        raise ValueError('host observation does not cover the exact model Action inventory')


def _verify_host_invocations(pair_root, pair_run_id, expected=None):
    digest, value = _load_host_invocation_observation(pair_root, pair_run_id)
    expected = _expected_host_invocation_actions(pair_root, pair_run_id) if expected is None else expected
    _validate_host_invocation_observation(value, expected)
    return {'outcome': 'VERIFIED', 'pairRunId': pair_run_id,
        'modelActionCount': len(expected), 'observationSha256': digest}


def verify_host_invocations(pair_root, pair_run_id):
    return _verify_host_invocations(pair_root, pair_run_id)


def _benchmark_cli_main(argv=None):
    import argparse
    from benchmark_execution import instantiate, verify_browser

    class Parser(argparse.ArgumentParser):
        def error(self, message): raise ValueError(message)

    parser = Parser(description='Prepare and inspect a frozen sequential benchmark pair.')
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('prepare')
    prepare.add_argument('--baseline-root', required=True, type=Path)
    prepare.add_argument('--output-root', required=True, type=Path)
    prepare.add_argument('--expectation-draft', required=True, type=Path)
    instantiate_parser = commands.add_parser('instantiate-brownfield-request')
    instantiate_parser.add_argument('--output-root', required=True, type=Path)
    instantiate_parser.add_argument('--pair-run-id', required=True)
    instantiate_parser.add_argument('--prior-path', required=True, type=Path)
    browser = commands.add_parser('verify-browser-evidence')
    browser.add_argument('--output-root', required=True, type=Path)
    browser.add_argument('--pair-run-id', required=True)
    browser.add_argument('--side', choices=['greenfield', 'brownfield'], required=True)
    host_invocations = commands.add_parser('verify-host-invocations')
    host_invocations.add_argument('--output-root', required=True, type=Path)
    host_invocations.add_argument('--pair-run-id', required=True)
    try:
        args = parser.parse_args(argv)
        if args.command == 'prepare':
            result = _prepare_benchmark(args.baseline_root, args.output_root, args.expectation_draft)
        elif args.command == 'instantiate-brownfield-request':
            result = instantiate(sys.modules[__name__], args.output_root, args.pair_run_id, args.prior_path)
        elif args.command == 'verify-browser-evidence':
            result = verify_browser(sys.modules[__name__], args.output_root, args.pair_run_id, args.side)
        else:
            result = verify_host_invocations(args.output_root, args.pair_run_id)
        print(canonical_json_bytes(result).decode('utf-8'), end='')
        return 0 if result['outcome'] in {'PREPARED', 'INSTANTIATED', 'VERIFIED'} else 2
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(canonical_json_bytes({'outcome': 'ERROR', 'reasonCode': getattr(error, 'code', 'BENCHMARK_INPUT_INVALID'),
            'message': str(error)}).decode('utf-8'), end='')
        return 2


def _validate_expectation_manifest(value):
    _validate(value, 'benchmark-expectation-manifest')
    rows = [item for collection in value.values() for item in collection]
    ids = [item['expectationId'] for item in rows]
    if len(ids) != len(set(ids)):
        raise ValueError('expectationId must be globally unique')
    obligations = value['expectedObligations']
    anchors = [(item['sourceId'], item['exactLocator']) for item in obligations]
    if len(anchors) != len(set(anchors)):
        raise ValueError('an obligation locator must have one explicit disposition')
    for item in value['expectedBrownfieldChanges']:
        if not item['priorLocatorIds'] and not item['targetLocatorIds']:
            raise ValueError('change expectation requires source evidence')


def _validate_functional_acceptance(value, host_observation):
    _validate(value, 'benchmark-result')
    if host_observation.get('outcome') != 'VERIFIED':
        raise ValueError('host invocation observation is not verified')
    if value['modelAttemptCount'] != host_observation.get('modelActionCount'):
        raise ValueError('host invocation inventory differs from started model Attempts')
    if any(value[key] != 0 for key in ('unresolvedDiagnostics', 'unsupportedFormalClaims',
            'forbiddenScopeClaims', 'unresolvedReviewerFindings', 'implicitRetireCount')):
        raise ValueError('functional acceptance requires zero unresolved defects')
    if any(value[key] != 1.0 for key in ('workItemDispositionRate', 'obligationRecall',
            'scopePrecision', 'sourceRefResolutionRate', 'changeGraphClosureRate',
            'changeRecall', 'changePrecision', 'unchangedRetention',
            'demoInteractionDispositionRate')):
        raise ValueError('functional acceptance requires complete coverage')
    checks = value['priorTransferChecks']
    if len({item['point'] for item in checks}) != 4:
        raise ValueError('four distinct prior transfer points are required')
    if len({(item['size'], item['sha256']) for item in checks}) != 1:
        raise ValueError('prior transfer bytes changed')
    ids = [item['formalClaimId'] for item in value['claimMappings']]
    if len(ids) != len(set(ids)):
        raise ValueError('formal claim mappings must be unique')


def _validate_performance_observation(value):
    _validate(value, 'benchmark-result')
    model_count = value['modelAttemptCount']
    provider_count = value['providerReportedAttemptCount']
    if provider_count > model_count:
        raise ValueError('provider-reported Attempt count exceeds started model Attempts')
    expected_state = ('UNAVAILABLE' if provider_count == 0 else
        'COMPLETE' if provider_count == model_count else 'PARTIAL')
    if value['tokenObservationState'] != expected_state:
        raise ValueError('token observation state does not match Attempt coverage')
    cells = [(item['usageCategory'], item['provenance'], item['tokenKind'])
        for item in value['tokensByCategoryProvenanceAndKind']]
    if len(cells) != len(set(cells)):
        raise ValueError('token cells must retain unique category, provenance and kind')
    provider_rows = [item for item in value['tokensByCategoryProvenanceAndKind']
        if item['provenance'] == 'PROVIDER_REPORTED']
    local_rows = [item for item in value['tokensByCategoryProvenanceAndKind']
        if item['provenance'] == 'LOCALLY_ESTIMATED']
    if expected_state == 'COMPLETE' and local_rows:
        raise ValueError('complete token observation cannot contain locally estimated Attempts')
    if expected_state != 'COMPLETE' and not local_rows:
        raise ValueError('incomplete token observation must retain locally estimated Attempts')
    observed = sum(item['tokens'] for item in provider_rows
        if item['tokenKind'] in {'INPUT', 'OUTPUT'})
    if provider_count == 0:
        if provider_rows or value['observedActualTokens'] is not None:
            raise ValueError('unavailable token observation cannot report actual token values')
    elif not provider_rows or value['observedActualTokens'] != observed:
        raise ValueError('observed actual token subtotal differs from provider-reported cells')
    complete_only_fields = ('tokensPerFormalNode', 'retryAmplification', 'budgetVarianceTokens')
    if expected_state == 'COMPLETE':
        if value['completeActualTokens'] != value['observedActualTokens']:
            raise ValueError('complete actual token total differs from observed subtotal')
        if value['budgetVarianceTokens'] is None:
            raise ValueError('complete token observation requires budget variance')
    elif value['completeActualTokens'] is not None or any(
            value[key] is not None for key in complete_only_fields):
        raise ValueError('incomplete token observation cannot report complete totals or ratios')


def _benchmark_disposition_rate(ids, rows, *, id_key, terminal, sealed):
    """Count only exactly one terminal disposition per sealed inventory ID."""
    if not sealed or len(ids) != len(set(ids)):
        raise ValueError('denominator must be an explicitly sealed unique inventory')
    universe = set(ids)
    if any(row[id_key] not in universe for row in rows):
        raise ValueError('disposition references undiscovered inventory ID')
    counts = {item: 0 for item in ids}
    for row in rows:
        if row['disposition'] in terminal:
            counts[row[id_key]] += 1
    return sum(count == 1 for count in counts.values()) / len(ids) if ids else 1.0


_FORMAL_COLLECTIONS = {
    'epics': 'epicId', 'features': 'featureId', 'designItems': 'designItemId',
    'integrations': 'integrationId', 'nfrs': 'nfrId', 'policyInstances': 'policyInstanceId',
    'stories': 'storyId', 'acceptanceCriteria': 'acceptanceCriterionId', 'tasks': 'taskId',
}
_EVIDENCE_REFS = {
    'requirementRefs': 'inputItems', 'coverageSet': 'features',
    'designRefs': 'designItems', 'designItemIds': 'designItems',
    'policyRefs': 'policyInstances', 'policyInstanceIds': 'policyInstances',
    'integrationIds': 'integrations', 'nfrIds': 'nfrs',
    'acceptanceCriterionIds': 'acceptanceCriteria',
}


def _benchmark_scope_evidence(model, expectation, frozen_locators, *, aliases=None):
    """Join typed references to frozen exact locators without semantic matching."""
    _validate_expectation_manifest(expectation)
    indexes, seen = {}, set()
    for collection, id_key in {**_FORMAL_COLLECTIONS, 'inputItems': 'inputItemId'}.items():
        rows = model[collection]
        ids = [row[id_key] for row in rows]
        if len(ids) != len(set(ids)) or seen.intersection(ids):
            raise ValueError('formal and input IDs must be globally unique')
        indexes[collection] = dict(zip(ids, rows)); seen.update(ids)
    cache, visiting = {}, set()
    aliases = aliases or {}

    def resolve(refs):
        anchors = {(ref['sourceId'], ref['locator']) for ref in refs} & frozen_locators
        return set().union(*(aliases.get(anchor, {anchor}) for anchor in anchors)) if anchors else set()

    # Qualifier coverage IDs are owned by their frozen InputItem/ScopeClosure.
    from delivery_compiler import _coverage_set
    coverage_owners = {}
    for row in model['scopeClosure']:
        identity = row.get('inputItemId')
        if identity not in indexes['inputItems']: continue
        for target in _coverage_set(indexes['inputItems'][identity], row):
            coverage_owners.setdefault(target, set()).add(identity)

    def evidence(collection, identity):
        key = (collection, identity)
        if key in visiting: raise ValueError('typed evidence reference cycle')
        if key in cache: return cache[key]
        if identity not in indexes[collection]: raise ValueError('dangling typed evidence reference')
        visiting.add(key)
        node = indexes[collection][identity]
        anchors = resolve(node.get('sourceRefs', []))
        for field, target_collection in _EVIDENCE_REFS.items():
            for target in node.get(field, []):
                if field == 'coverageSet' and target not in indexes['features'] and target in coverage_owners:
                    for owner in coverage_owners[target]: anchors.update(evidence('inputItems', owner))
                else: anchors.update(evidence(target_collection, target))
        visiting.remove(key)
        cache[key] = anchors
        return cache[key]

    formal = {identity: evidence(collection, identity)
        for collection in _FORMAL_COLLECTIONS for identity in indexes[collection]}
    obligations = expectation['expectedObligations']
    forbidden = {(item['sourceId'], item['exactLocator']) for item in obligations
        if item['requiredDisposition'] == 'OUT_OF_SCOPE'}
    mappings = [{'formalClaimId': identity, 'expectationIds': sorted(item['expectationId']
        for item in obligations if item['requiredDisposition'] == 'FORMAL_CLAIM'
        and (item['sourceId'], item['exactLocator']) in anchors)}
        for identity, anchors in sorted(formal.items())]
    mappings = [item for item in mappings if item['expectationIds']]
    matched = {identity for row in mappings for identity in row['expectationIds']}
    for item in obligations:
        if item['requiredDisposition'] == 'FORMAL_CLAIM': continue
        anchor = (item['sourceId'], item['exactLocator'])
        if anchor in frozen_locators and any(row['disposition'] == item['requiredDisposition']
            and anchor in resolve(row['sourceRefs'])
            for row in model['scopeClosure']):
            matched.add(item['expectationId'])

    def source_refs(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == 'sourceRefs': yield from child
                else: yield from source_refs(child)
        elif isinstance(value, list):
            for child in value: yield from source_refs(child)

    refs = list(source_refs(model))
    return {
        'formalNodeCount': len(formal), 'claimMappings': mappings,
        'formalEvidence': formal, 'matchedExpectationIds': sorted(matched),
        'sourceRefCount': len(refs),
        'resolvedSourceRefCount': sum((ref['sourceId'], ref['locator']) in frozen_locators for ref in refs),
        'obligationRecall': len(matched) / len(obligations) if obligations else 1.0,
        'scopePrecision': len(mappings) / len(formal) if formal else 1.0,
        'unsupportedFormalClaims': sum(not anchors for anchors in formal.values()),
        'forbiddenScopeClaims': sum(bool(anchors & forbidden) for anchors in formal.values()),
        'sourceRefResolutionRate': sum((ref['sourceId'], ref['locator']) in frozen_locators
            for ref in refs) / len(refs) if refs else 1.0,
    }


def _benchmark_attempt_observations(ledger, formal_node_count):
    from action_ledger import ActionLedger
    from contracts import action_contract_binding, validate_action_usage, validate_usage
    # Reconstructing verifies Record -> Envelope -> versioned contract and raw hashes.
    ledger = ActionLedger(ledger.envelopes_by_sha256, ledger.attempt_records,
        ledger.raw_outputs, ledger.normalized_results)
    categories, planned = {}, 0
    for digest, envelope in ledger.envelopes_by_sha256.items():
        contract, contract_hash = action_contract_binding(SKILL_ROOT, envelope.value['actionContractId'])
        if contract_hash != envelope.value['actionContractSha256']:
            raise ValueError('Attempt category contract hash mismatch')
        categories[digest] = contract
        if contract['executionKind'] == 'MODEL_PROVIDER':
            planned += sum(envelope.value['executionLimits'][field]
                for field in ('estimatedInputTokens', 'maxOutputTokens', 'maxHydrateTokens'))
    cells, invoked, effective = {}, [], {}
    for record in ledger.attempt_records.values():
        contract = categories[record.envelope_sha256]
        envelope = ledger.envelopes_by_sha256[record.envelope_sha256].value
        validate_action_usage(envelope, record.usage, skill_root=SKILL_ROOT)
        started = record.timing.started_at_utc is not None
        validate_usage(record.usage, provider_started=started)
        if contract['executionKind'] != 'MODEL_PROVIDER' or not started:
            continue
        invoked.append(record)
        category = contract['usageCategory']; provenance = record.usage.provenance
        for kind, amount in (('INPUT', record.usage.input_tokens), ('OUTPUT', record.usage.output_tokens),
            ('CACHED_INPUT', record.usage.cached_input_tokens), ('REASONING', record.usage.reasoning_tokens)):
            key = (category, provenance, kind)
            previous = cells.get(key, 0)
            cells[key] = None if amount is None or previous is None else previous + amount
        if record.outcome == 'SUCCEEDED':
            previous = effective.get(record.logical_work_id)
            if previous is None or (record.revision, record.attempt) > (previous.revision, previous.attempt):
                effective[record.logical_work_id] = record
    provider = [record for record in invoked if record.usage.provenance == 'PROVIDER_REPORTED']
    actual = sum(record.usage.charged_tokens for record in provider)
    effective_actual = sum(record.usage.charged_tokens for record in effective.values()
        if record.usage.provenance == 'PROVIDER_REPORTED')
    successful_by_category = {category: {record.logical_work_id for record in effective.values()
        if categories[record.envelope_sha256]['usageCategory'] == category}
        for category in ('AUTHOR', 'REPAIR')}
    authors, repairs = map(len, (successful_by_category['AUTHOR'], successful_by_category['REPAIR']))
    if not authors and repairs:
        raise ValueError('repair numerator has no sealed author denominator')
    state = ('UNAVAILABLE' if not provider else
        'COMPLETE' if len(provider) == len(invoked) else 'PARTIAL')
    complete = state == 'COMPLETE'
    return {
        'tokenObservationState': state,
        'modelAttemptCount': len(invoked),
        'providerReportedAttemptCount': len(provider),
        'providerActualTokens': actual,
        'providerEffectiveSuccessTokens': effective_actual,
        'plannedTokens': planned,
        'observedActualTokens': actual if provider else None,
        'completeActualTokens': actual if complete else None,
        'invalidIrCount': sum(record.outcome == 'FAILED' and record.failure_kind == 'INVALID_IR'
            for record in invoked),
        'successfulAuthorCount': authors,
        'successfulRepairCount': repairs,
        'tokensByCategoryProvenanceAndKind': [{'usageCategory': key[0], 'provenance': key[1],
            'tokenKind': key[2], 'tokens': amount} for key, amount in sorted(cells.items())],
        'tokensPerFormalNode': actual / formal_node_count if complete and formal_node_count else None,
        'retryAmplification': actual / effective_actual if complete and effective_actual else None,
        'invalidIrRate': sum(record.outcome == 'FAILED' and record.failure_kind == 'INVALID_IR'
            for record in invoked) / len(invoked) if invoked else 1.0,
        'repairRate': repairs / authors if authors else 1.0,
        'budgetVarianceTokens': actual - planned if complete else None,
    }


def _benchmark_time_observations(ledger, events):
    from contracts import validate_attempt_timing
    from run_events import validate_run_event_log
    validate_run_event_log(events)
    timestamps = [datetime.fromisoformat(event.occurred_at_utc) for event in events]
    if timestamps != sorted(timestamps): raise ValueError('RunEvent time reverses')
    starts = [datetime.fromisoformat(event.occurred_at_utc) for event in events if event.type == 'ACTION_ISSUED']
    ends = [datetime.fromisoformat(event.occurred_at_utc) for event in events
        if event.type == 'RUN_STATE_CHANGED' and event.payload['toState'] == 'AWAITING_FINAL_REVIEW']
    if not starts or len(ends) != 1 or ends[0] < starts[0]:
        raise ValueError('completed benchmark requires first issuance and one final review boundary')
    beginning, ending = starts[0], ends[0]
    waits, pending, intervals = [], {}, []
    for event in events:
        at = datetime.fromisoformat(event.occurred_at_utc)
        if event.type == 'WAITING_INPUT_ENTERED': pending[event.payload['waitId']] = at
        elif event.type == 'WAITING_INPUT_EXITED': waits.append((pending.pop(event.payload['waitId']), at))
        elif event.type == 'DETERMINISTIC_STEP_FINISHED':
            intervals.append(tuple(datetime.fromisoformat(event.payload[key]) for key in ('startedAtUtc', 'endedAtUtc')))
    if pending: raise ValueError('open waiting interval is status-only, not a completed benchmark')
    for record in ledger.attempt_records.values():
        validate_attempt_timing(record.timing, failed=record.outcome != 'SUCCEEDED')
        if record.timing.started_at_utc is not None:
            intervals.append((datetime.fromisoformat(record.timing.started_at_utc), datetime.fromisoformat(record.timing.ended_at_utc)))

    def union(rows):
        merged = []
        for start, end in sorted(rows):
            if end < start: raise ValueError('execution interval reverses')
            if merged and start <= merged[-1][1]: merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else: merged.append((start, end))
        return merged

    active = union(intervals); waiting = union(waits)
    total = 0.0
    for start, end in active:
        start, end = max(start, beginning), min(end, ending)
        if end <= start: continue
        total += (end - start).total_seconds()
        for wait_start, wait_end in waiting:
            total -= max(0.0, (min(end, wait_end) - max(start, wait_start)).total_seconds())
    return {'activeWallTime': total,
        'userWaitingTime': sum((end - start).total_seconds() for start, end in waiting)}


def _benchmark_brownfield_evidence(files, scope_root, checkpoint, graph, target_evidence, expectation, *, prior_refs=None, aliases=None):
    from prior_state import derive_effective_prior
    from change_graph import change_cardinality_supported
    _validate_expectation_manifest(expectation)
    digest = checkpoint['priorStateSha256']
    raw = files.read_bytes(f'{scope_root}/prior-states/{digest}.json')
    if sha256_bytes(raw) != digest or canonical_json_bytes(json.loads(raw)) != raw:
        raise ValueError('ScopeCheckpoint prior snapshot hash mismatch')
    snapshot = json.loads(raw)
    active = set(derive_effective_prior(snapshot)['activeEntityIds'])
    entities = {item['entityId']: item for item in snapshot['entities']}
    if len(entities) != len(snapshot['entities']): raise ValueError('duplicate prior entity ID')
    prior_anchors = {}
    for identity in active:
        entity = entities[identity]; anchors = set()
        for evidence_id in entity['evidenceIds']:
            matches = [row for row in snapshot['evidence'] if row['priorEvidenceId'] == evidence_id
                and row.get('sourceId', entity['sourceId']) == entity['sourceId']]
            if len(matches) != 1: raise ValueError('prior entity evidence must resolve uniquely')
            row = matches[0]; cells = row['canonicalCellValues']
            if sha256_bytes(canonical_json_bytes(cells)) != row['canonicalCellValuesSha256']:
                raise ValueError('prior visible cell evidence hash mismatch')
            # Current compact SOWs expose business rows, not the source ledger.
            # The source ID and XLSX locator come from the bound Prior snapshot.
            if row.get('sheet') and row.get('absoluteA1Range'):
                anchors.add(entity['sourceId'] + '#' + row['sheet'] + '!' + row['absoluteA1Range'])
            values = [cell['value'] for cell in cells]
            for index, value in enumerate(values[:-1]):
                if value != 'SourceRef' or not isinstance(values[index + 1], str): continue
                try: ref = json.loads(values[index + 1])
                except (TypeError, ValueError) as error: raise ValueError('visible SourceRef JSON is invalid') from error
                if not isinstance(ref, dict) or set(ref) != {'sourceId', 'blockId', 'locator', 'sha256'}:
                    raise ValueError('visible SourceRef must retain original frozen locator')
                if prior_refs is not None and canonical_json_bytes(ref) not in prior_refs:
                    raise ValueError('visible prior SourceRef does not resolve to frozen v1 bytes')
                anchor = (ref['sourceId'], ref['locator'])
                anchors.update(source + '#' + locator for source, locator in (aliases or {}).get(anchor, {anchor}))
        if not anchors: raise ValueError('active prior entity lacks frozen visible evidence locators')
        prior_anchors[identity] = anchors
    targets = {identity: {source + '#' + locator for source, locator in anchors}
        for identity, anchors in target_evidence.items()}
    if validate_contract(graph, 'change-graph.schema.json', REGISTRY):
        raise ValueError('benchmark ChangeGraph schema invalid')
    prior_counts = dict.fromkeys(active, 0); target_counts = dict.fromkeys(targets, 0)
    actual, retired, implicit = [], set(), 0
    for group in graph['changeGroups']:
        previous, current = set(group['priorEntityIds']), set(group['targetEntityIds'])
        if not previous <= active or not current <= targets.keys():
            raise ValueError('ChangeGraph references inactive or missing entity')
        if not change_cardinality_supported(group['kind'], len(previous), len(current)):
            raise ValueError('unsupported ChangeGraph cardinality')
        for identity in previous: prior_counts[identity] += 1
        for identity in current: target_counts[identity] += 1
        actual.append((group['kind'], set().union(*(prior_anchors[i] for i in previous)),
            set().union(*(targets[i] for i in current))))
    prior_evidence_ids = {row['priorEvidenceId'] for row in snapshot['evidence']}
    for row in graph['retiredPrior']:
        identity = row['priorEntityId']
        if identity not in active: raise ValueError('RETIRE references inactive prior')
        prior_counts[identity] += 1; retired.add(identity)
        refs = set(row['evidenceIds'])
        implicit += not (refs & set(entities[identity]['evidenceIds'])) or not (refs - prior_evidence_ids)
        actual.append(('RETIRE', prior_anchors[identity], set()))
    for identity, count in target_counts.items():
        if count == 0:
            target_counts[identity] = 1
            actual.append(('NEW', set(), targets[identity]))
    for identity, count in prior_counts.items():
        if count == 0: prior_counts[identity] = 1  # derived KEEP, excluded from actual changes
    expected = expectation['expectedBrownfieldChanges']
    joins = [[index for index, (kind, previous, current) in enumerate(actual)
        if kind in item['allowedKinds'] and set(item['priorLocatorIds']) <= previous
        and set(item['targetLocatorIds']) <= current] for item in expected]
    if any(len(matches) > 1 for matches in joins): raise ValueError('ambiguous expected change signature')
    matched = [matches[0] for matches in joins if matches]
    if len(matched) != len(set(matched)): raise ValueError('actual change matches multiple expectations')
    unchanged = expectation['expectedUnchangedCapabilities']; retained = 0
    for item in unchanged:
        matches = [identity for identity, anchors in prior_anchors.items() if set(item['priorLocatorIds']) <= anchors]
        if len(matches) != 1: raise ValueError('unchanged capability must resolve to one active prior entity')
        retained += matches[0] not in retired
    total = len(prior_counts) + len(target_counts)
    return {'activePriorEntityIds': sorted(active),
        'changeGraphClosureRate': sum(count == 1 for count in [*prior_counts.values(), *target_counts.values()]) / total if total else 1.0,
        'changeRecall': len(matched) / len(expected) if expected else 1.0,
        'changePrecision': len(set(matched)) / len(actual) if actual else 1.0,
        'unchangedRetention': retained / len(unchanged) if unchanged else 1.0,
        'implicitRetireCount': implicit}


def _benchmark_final_counts(stages, ledger, packets):
    from action_ledger import ActionLedger
    from final_review import REVIEW_CONTRACT
    ledger = ActionLedger(ledger.envelopes_by_sha256, ledger.attempt_records,
        ledger.raw_outputs, ledger.normalized_results)
    diagnostics, unresolved = 0, 0
    for stage, proof in stages.items():
        checkpoint = proof['checkpoint']; digest = checkpoint['validatorResultSha256']
        validator = proof['validators'][digest]
        if sha256_bytes(canonical_json_bytes(validator)) != digest:
            raise ValueError('final validator hash mismatch')
        diagnostics += sum(row.get('status') != 'RESOLVED' for row in validator['diagnostics'])
        reviews, repairs = [], []
        for record in ledger.attempt_records.values():
            envelope = ledger.envelopes_by_sha256[record.envelope_sha256].value
            if envelope['stageKind'] != stage or record.outcome != 'SUCCEEDED': continue
            if envelope['actionContractId'] == REVIEW_CONTRACT[stage]:
                decision = json.loads(ledger.normalized_results[record.normalized_result_sha256])
                reviews.append((envelope, record, decision))
            elif envelope['actionContractId'] == stage + '_REPAIR-v1':
                packet_raw = packets[envelope['packetSha256']]
                if sha256_bytes(packet_raw) != envelope['packetSha256']:
                    raise ValueError('repair packet hash mismatch')
                repairs.append(json.loads(packet_raw)['workItems'][0]['payload'])
        final = [row for row in reviews if row[0]['baseCandidateSha256'] == checkpoint['candidateSha256']
            and row[1].normalized_result_sha256 == checkpoint['reviewDecisionSha256']]
        if len(final) != 1: raise ValueError('final review must bind one actual candidate and decision')
        for envelope, record, decision in reviews:
            if decision['decision'] == 'PASS': continue
            closed = (decision['decision'] == 'REPAIRABLE_SEMANTIC'
                and final[0][2] == {'decision': 'PASS', 'findings': []}
                and envelope['baseCandidateSha256'] != checkpoint['candidateSha256']
                and any(repair['reviewDecisionSha256'] == record.normalized_result_sha256
                    and repair['reviewDecision'] == decision for repair in repairs))
            if not closed: unresolved += len(decision['findings'])
    return {'unresolvedDiagnostics': diagnostics, 'unresolvedReviewerFindings': unresolved}


def _benchmark_browser_trace(inventory, scenario, trace, expected_profile):
    from prototype_analysis import PrototypeError, verify_prototype_trace
    if trace['browserProfile'] != expected_profile:
        raise ValueError('browser trace changed the frozen actual environment')
    try:
        proof = verify_prototype_trace(inventory, scenario, trace)
    except PrototypeError as error:
        if error.code == 'INCOMPLETE_BUDGET':
            return {'outcome': 'WAITING_INPUT', 'reasonCode': error.code}
        raise
    return {'outcome': 'VERIFIED', **proof}


def _validate(value, name):
    schema = json.loads((PLUGIN_ROOT / f'tests/contracts/{name}.schema.json').read_bytes())
    errors = list(Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER).iter_errors(value))
    if errors:
        raise ValueError(f'{name} schema invalid: {errors[0].message}')


def _safe_source(files, item):
    path = item['path']
    if '.ai-sow' in Path(path).parts or FORBIDDEN.search(path):
        raise ValueError('pair isolation forbids hidden state, model, checkpoint, manifest, chat or sidecar')
    suffix = Path(path).suffix.lower()
    allowed = {'PRD': {'.md'}, 'HLD': {'.md'}, 'PRIOR_SOW': {'.xlsx'},
               'DEMO': {'.html', '.ts', '.tsx', '.css', '.js', '.json', '.txt', '.md'}}
    if item['role'] not in allowed or suffix not in allowed[item['role']]:
        raise ValueError('pair isolation only accepts explicit PRD/HLD/Demo/Prior XLSX')
    raw = files.read_bytes(path)
    if sha256_bytes(raw) != item['expectedSha256']:
        raise ValueError('pair source bytes do not match expectedSha256')
    return raw


def _request(files, path, mode):
    value = files.read_json(path)
    if validate_contract(value, 'request.schema.json', REGISTRY) or value['mode'] != mode:
        raise ValueError('complete v3 request with matching side is required')
    if mode == 'BROWNFIELD' and value['declaredChangeContext'] is None:
        raise ValueError('Brownfield needs declared change context')
    for item in value['sources'] + (value.get('demo') or {}).get('files', []):
        _safe_source(files, item)
    return value


def _replace_prior(template, path, digest):
    value = copy.deepcopy(template)
    priors = [item for item in value['sources'] if item['role'] == 'PRIOR_SOW']
    if (value.get('mode') != 'BROWNFIELD' or len(priors) != 1
        or priors[0]['path'] != PRIOR_PATH or priors[0]['expectedSha256'] != PRIOR_HASH):
        raise ValueError('template must contain exactly one PRIOR_SOW path/hash placeholder')
    # Placeholders elsewhere, including free text, are not an alternate substitution seam.
    encoded = canonical_json_bytes(template)
    if encoded.count(PRIOR_PATH.encode()) != 1 or encoded.count(PRIOR_HASH.encode()) != 1:
        raise ValueError('template placeholders must be unique')
    priors[0].update(path=path, expectedSha256=digest)
    if validate_contract(value, 'request.schema.json', REGISTRY):
        raise ValueError('instantiated request does not satisfy full v3 schema')
    restored = copy.deepcopy(value)
    item = next(item for item in restored['sources'] if item['role'] == 'PRIOR_SOW')
    item.update(path=PRIOR_PATH, expectedSha256=PRIOR_HASH)
    if canonical_json_bytes(restored) != encoded:
        raise ValueError('template fields changed outside PRIOR_SOW binding')
    return value


def instantiate_brownfield_request(template_path, prior_path, output_path) -> Path:
    """Copy just the selected XLSX; retain all other canonical template fields.

    Template and output live at the Brownfield project root so source paths keep
    their original meaning. The prior may be an explicitly selected Green XLSX.
    """
    template_path, prior_path, output_path = map(Path, (template_path, prior_path, output_path))
    if template_path.absolute().parent != output_path.absolute().parent:
        raise ValueError('template and request must share their project root')
    if prior_path.suffix.lower() != '.xlsx':
        raise ValueError('prior must be XLSX')
    files = ProjectFiles.open(output_path.absolute().parent)
    template = files.read_json(template_path.name)
    source = ProjectFiles.open(prior_path.absolute().parent)
    raw = source.read_bytes(prior_path.name)
    digest = sha256_bytes(raw)
    copied_path = f'pair-inputs/prior-{digest}.xlsx'
    value = _replace_prior(template, copied_path, digest)
    for item in value['sources'] + (value.get('demo') or {}).get('files', []):
        if item['role'] != 'PRIOR_SOW':
            _safe_source(files, item)
    if source.read_bytes(prior_path.name) != raw:
        raise ValueError('selected prior bytes changed during copy')
    files.publish_new(copied_path, raw)
    _safe_source(files, next(item for item in value['sources'] if item['role'] == 'PRIOR_SOW'))
    files.publish_new(output_path.name, canonical_json_bytes(value))
    if files.read_bytes(copied_path) != raw:
        raise ValueError('copied prior bytes changed')
    return output_path


def _freeze(files, name, raw):
    path = f'pair-{name}-{sha256_bytes(raw)}.json'
    files.publish_new(path, raw)
    return path


def _prior(request):
    matches = [item for item in request['sources'] if item['role'] == 'PRIOR_SOW']
    if len(matches) != 1:
        raise ValueError('paired Brownfield must bind exactly one prior workbook')
    return matches[0]


def _bind_side(descriptor, mode):
    files = ProjectFiles.open(Path(descriptor['projectRoot']))
    request = _request(files, descriptor['requestPath'], mode)
    request_hash = sha256_bytes(files.read_bytes(descriptor['requestPath']))
    state = orchestrator.status(files.root).get('state', {})
    if state.get('phase') != 'AWAITING_FINAL_REVIEW' or state.get('requestSha256') != request_hash:
        raise ValueError('pair review requires both exact runs AWAITING_FINAL_REVIEW')
    ready = orchestrator.run_mode(files.root, 'resume')
    if ready.get('outcome') != 'REQUEST_APPROVAL':
        raise ValueError('pair review requires a sealed artifact on both sides')
    artifact = generation_store.validate_artifact_manifest(files, ready['artifactManifestPath'], ready['artifactManifestSha256'])
    policy_raw = files.read_bytes(descriptor['budgetPolicyPath'])
    if validate_contract(json.loads(policy_raw), 'run-budget-policy.schema.json', REGISTRY):
        raise ValueError('rerun requires a complete explicit budget policy')
    binding = {'projectRoot': str(files.root), 'runId': state['runId'],
        'requestPath': descriptor['requestPath'], 'requestSha256': request_hash,
        'budgetPolicyPath': _freeze(files, 'budget', policy_raw), 'budgetPolicySha256': sha256_bytes(policy_raw),
        'artifactManifestPath': ready['artifactManifestPath'], 'artifactManifestSha256': ready['artifactManifestSha256'],
        'workbookPath': ready['workbookPath'], 'workbookSha256': artifact['workbook']['sha256']}
    return binding, request


def _location(manifest):
    digest = sha256_bytes(canonical_json_bytes(manifest))
    return ProjectFiles.open(Path(manifest['green']['projectRoot'])), f'pair-reviews/{digest}'


def _optional(files, path):
    try:
        return files.read_json(path)
    except ProjectIOError as error:
        if error.code == 'PROJECT_PATH_MISSING':
            return None
        raise


def _read_result(manifest):
    files, root = _location(manifest)
    result = files.read_json(root + '/result.json')
    _validate(result, 'pair-result')
    if result['pairReviewManifestSha256'] != sha256_bytes(canonical_json_bytes(manifest)):
        raise ValueError('pair result does not bind manifest')
    return result


def _write_result(manifest, result):
    _validate(result, 'pair-result')
    files, root = _location(manifest)
    files.write_atomic(root + '/result.json', canonical_json_bytes(result))
    return result


def prepare_pair_review(green, brown):
    """Freeze a joint review only after both production runs have sealed artifacts.

    Descriptors provide projectRoot, requestPath and budgetPolicyPath. Brown also
    provides templatePath. Paths within each project are project-relative.
    """
    roots = [Path(side['projectRoot']).resolve() for side in (green, brown)]
    if roots[0] == roots[1] or roots[0] in roots[1].parents or roots[1] in roots[0].parents:
        raise ValueError('pair projects must be distinct, non-nested directories')
    green_binding, green_request = _bind_side(green, 'GREENFIELD')
    brown_binding, brown_request = _bind_side(brown, 'BROWNFIELD')
    if any(item['role'] == 'PRIOR_SOW' for item in green_request['sources']):
        raise ValueError('Greenfield cannot inherit prior input')
    prior = _prior(brown_request)
    if prior['expectedSha256'] != green_binding['workbookSha256']:
        raise ValueError('Brownfield prior must be the exact frozen Greenfield workbook')
    brown_files = ProjectFiles.open(roots[1])
    template_raw = brown_files.read_bytes(brown['templatePath'])
    expected = _replace_prior(json.loads(template_raw), prior['path'], prior['expectedSha256'])
    if canonical_json_bytes(expected) != canonical_json_bytes(brown_request):
        raise ValueError('Brownfield request differs from the frozen template outside prior binding')
    frozen_template = _freeze(brown_files, 'template', template_raw)
    manifest = {'contract': 'ai-sow-pair-review-manifest-v1', 'status': 'READY_FOR_REVIEW',
        'green': green_binding, 'brown': brown_binding,
        'brownTemplatePath': frozen_template, 'brownTemplateSha256': sha256_bytes(template_raw)}
    _validate(manifest, 'pair-review-manifest')
    files, root = _location(manifest)
    files.publish_new(root + '/manifest.json', canonical_json_bytes(manifest))
    previous = _optional(files, root + '/result.json')
    if previous is not None:
        if previous['status'] != 'READY_FOR_REVIEW':
            raise ValueError('this review cycle already has a terminal decision')
        return manifest
    _write_result(manifest, {'contract': 'ai-sow-pair-result-v1', 'status': 'READY_FOR_REVIEW',
        'pairReviewManifestSha256': sha256_bytes(canonical_json_bytes(manifest)),
        'pairDecisionSha256': None, 'greenGeneration': None, 'brownGeneration': None,
        'rerun': None, 'nextPairManifestPath': None})
    return manifest


def _artifact(entry):
    files = ProjectFiles.open(Path(entry['projectRoot']))
    value = generation_store.validate_artifact_manifest(files, entry['artifactManifestPath'], entry['artifactManifestSha256'])
    if (value['runId'] != entry['runId'] or value['workbook']['sha256'] != entry['workbookSha256']
        or entry['workbookPath'] != (Path(entry['artifactManifestPath']).parent / value['workbook']['path']).as_posix()
        or sha256_bytes(files.read_bytes(entry['workbookPath'])) != entry['workbookSha256']):
        raise ValueError('pair artifact/workbook binding changed')
    return value


def _awaiting(entry):
    state = orchestrator.status(Path(entry['projectRoot'])).get('state', {})
    if (state.get('phase') != 'AWAITING_FINAL_REVIEW' or state.get('runId') != entry['runId']
        or state.get('requestSha256') != entry['requestSha256']):
        raise ValueError('review run is no longer the exact awaiting run')


def _published(entry, digest):
    files = ProjectFiles.open(Path(entry['projectRoot']))
    current = generation_store.load_current(files)
    if current is None:
        return None
    raw = files.read_bytes(current.manifest_path); value = json.loads(raw)
    if value['artifactManifestSha256'] != entry['artifactManifestSha256']:
        return None
    if value.get('pairDecisionSha256') != digest or value['workbookSha256'] != entry['workbookSha256']:
        raise ValueError('published generation does not bind the same pair APPROVE and workbook')
    return {'generationId': current.generation_id, 'manifestPath': current.manifest_path,
        'manifestSha256': sha256_bytes(raw), 'workbookPath': current.workbook_path,
        'workbookSha256': value['workbookSha256']}


def _approve_side(entry, digest):
    files = ProjectFiles.open(Path(entry['projectRoot']))
    artifact = _artifact(entry)
    path = f'pair-approve-{digest}-{entry["artifactManifestSha256"]}.json'
    approval = _optional(files, path)
    if approval is None:
        approval = {key: artifact[key] for key in ('runId', 'candidateSha256', 'sourceManifestSha256',
            'reviewDecisionSha256', 'templateSha256', 'effectivePolicyDecisionSha256')}
        approval.update(contract='ai-sow-approval-v1', decision='APPROVE',
            artifactManifestSha256=entry['artifactManifestSha256'], pairDecisionSha256=digest,
            approvedAt=datetime.now(UTC).isoformat().replace('+00:00', 'Z'))
        files.publish_new(path, canonical_json_bytes(approval))
    if approval.get('pairDecisionSha256') != digest or approval.get('decision') != 'APPROVE':
        raise ValueError('stored approval does not match pair decision')
    result = orchestrator.run_mode(files.root, 'approve', artifact_manifest_sha256=entry['artifactManifestSha256'], decision=path)
    if result.get('outcome') not in {'PUBLISHED', 'REUSED'}:
        raise ValueError(f'pair publication failed: {result}')
    published = _published(entry, digest)
    if published is None:
        raise ValueError('publication did not install the approved current')
    return published


def _feedback(manifest, decision, digest):
    side = 'green' if decision['side'] == 'GREENFIELD' else 'brown'
    files = ProjectFiles.open(Path(manifest[side]['projectRoot']))
    frozen = decision['feedbackInputPath']
    match = re.fullmatch(r'pair-feedback/request-([0-9a-f]{64})\.json', frozen)
    if match is None:
        raise ValueError('feedback path must bind its canonical content hash')
    raw = files.read_bytes(frozen)
    # The hash is part of PairDecision itself, through its existing path field.
    # No mutable lookup/pointer can redirect the accepted decision to new input.
    if sha256_bytes(raw) != match.group(1):
        raise ValueError('frozen feedback content hash changed')
    request = _request(files, frozen, decision['side'])
    if canonical_json_bytes(request) != raw:
        raise ValueError('feedback hash path must contain canonical request bytes')
    if side == 'brown' and _prior(request)['expectedSha256'] != manifest['green']['workbookSha256']:
        raise ValueError('Brownfield feedback must bind the frozen Greenfield prior')
    if side == 'green' and any(item['role'] == 'PRIOR_SOW' for item in request['sources']):
        raise ValueError('Greenfield feedback cannot inherit a prior')
    return frozen


def _abandon_old(entry):
    state = orchestrator.status(Path(entry['projectRoot'])).get('state')
    if state and state['runId'] == entry['runId']:
        result = orchestrator.run_mode(Path(entry['projectRoot']), 'abandon')
        if result.get('outcome') != 'ABANDONED':
            raise ValueError('could not abandon the rejected run')
    elif state:
        raise ValueError('another active run cannot be abandoned by the old pair')


def _restart(entry, request_path):
    files = ProjectFiles.open(Path(entry['projectRoot']))
    policy = files.read_bytes(entry['budgetPolicyPath'])
    if sha256_bytes(policy) != entry['budgetPolicySha256']:
        raise ValueError('frozen explicit rerun budget changed')
    state = orchestrator.status(files.root).get('state')
    if state and state['runId'] == entry['runId']:
        _abandon_old(entry)
        state = None
    if state:
        if state.get('requestSha256') != sha256_bytes(files.read_bytes(request_path)):
            raise ValueError('rerun is already bound to a different complete request')
        return orchestrator.run_mode(files.root, 'resume')
    return orchestrator.run_mode(files.root, 'start', request=request_path, budget_policy=entry['budgetPolicyPath'])


def _descriptor(entry, request_path):
    return {key: entry[key] for key in ('projectRoot', 'budgetPolicyPath')} | {'requestPath': request_path}


def _rerun_result(result, entry, request_path, side):
    result['rerun'] = {'side': side, **_descriptor(entry, request_path)}
    return result


def _continue_rejection(manifest, decision, digest, result):
    feedback = _feedback(manifest, decision, digest)
    green, brown = manifest['green'], manifest['brown']
    brown_files = ProjectFiles.open(Path(brown['projectRoot']))
    template_path = manifest['brownTemplatePath']
    template_raw = brown_files.read_bytes(template_path)
    if sha256_bytes(template_raw) != manifest['brownTemplateSha256']:
        raise ValueError('frozen Brownfield template changed')
    if decision['side'] == 'GREENFIELD':
        # Brown must be abandoned before restarting Green. Once the new Brown has
        # started, it is resumed below rather than being abandoned a second time.
        brown_state = orchestrator.status(brown_files.root).get('state')
        if brown_state and brown_state['runId'] == brown['runId']:
            _abandon_old(brown)
        ready_green = _restart(green, feedback)
        green_descriptor = _descriptor(green, feedback)
        if ready_green.get('outcome') != 'REQUEST_APPROVAL':
            return _write_result(manifest, _rerun_result(result, green, feedback, 'GREENFIELD'))
        green_prior = Path(green['projectRoot']) / ready_green['workbookPath']
        brown_request = f'pair-rerun-{digest}.json'
        instantiate_brownfield_request(brown_files.root / template_path, green_prior, brown_files.root / brown_request)
    else:
        _artifact(green); _awaiting(green)
        green_descriptor = _descriptor(green, green['requestPath'])
        brown_request = feedback
        # A complete Brown feedback may change business fields. Freeze its own
        # next-cycle template, restoring only the unique prior placeholders.
        next_template = copy.deepcopy(_request(brown_files, feedback, 'BROWNFIELD'))
        _prior(next_template).update(path=PRIOR_PATH, expectedSha256=PRIOR_HASH)
        template_path = _freeze(brown_files, 'template', canonical_json_bytes(next_template))
    ready_brown = _restart(brown, brown_request)
    if ready_brown.get('outcome') != 'REQUEST_APPROVAL':
        return _write_result(manifest, _rerun_result(result, brown, brown_request, 'BROWNFIELD'))
    next_manifest = prepare_pair_review(green_descriptor, {**_descriptor(brown, brown_request), 'templatePath': template_path})
    next_files, next_root = _location(next_manifest)
    result.update(rerun=None, nextPairManifestPath=str(next_files.root / next_root / 'manifest.json'))
    return _write_result(manifest, result)


def submit_pair_decision(pair_manifest, decision):
    """Consume one closed decision; exact replays recover interrupted operations."""
    manifest = pair_manifest
    _validate(manifest, 'pair-review-manifest'); _validate(decision, 'pair-decision')
    files, root = _location(manifest)
    raw = canonical_json_bytes(manifest)
    if files.read_bytes(root + '/manifest.json') != raw:
        raise ValueError('pair manifest is not the exact frozen review')
    if decision['pairReviewManifestSha256'] != sha256_bytes(raw):
        raise ValueError('decision must bind the exact pair manifest hash')
    digest = sha256_bytes(canonical_json_bytes(decision))
    result = _read_result(manifest)
    previous = _optional(files, root + '/decision.json')
    if previous is not None and previous != decision:
        raise ValueError('one pair review cycle accepts only one decision')
    if result['pairDecisionSha256'] not in (None, digest):
        raise ValueError('pair result belongs to a different decision')
    if result['status'] == 'SUPERSEDED':
        if previous != decision or decision['decision'] != 'REJECT':
            raise ValueError('superseded review cannot publish')
        if result['nextPairManifestPath']:
            return result
        return _continue_rejection(manifest, decision, digest, result)
    try:
        for side in SIDES:
            _artifact(manifest[side])
            published = _published(manifest[side], digest)
            if published is None:
                _awaiting(manifest[side])
            result[side + 'Generation'] = published
    except ValueError:
        result['status'] = 'SUPERSEDED'
        _write_result(manifest, result)
        raise
    if decision['decision'] == 'REJECT':
        _feedback(manifest, decision, digest)  # Validate complete input before consuming decision.
    files.publish_new(root + '/decision.json', canonical_json_bytes(decision))
    result['pairDecisionSha256'] = digest
    if decision['decision'] == 'REJECT':
        result['status'] = 'SUPERSEDED'
        _write_result(manifest, result)
        return _continue_rejection(manifest, decision, digest, result)
    result['status'] = 'PUBLISHING'
    _write_result(manifest, result)
    for side in SIDES:
        # Call approve even for an existing current: production repairs a crash
        # between current swap and active-run terminalization idempotently.
        result[side + 'Generation'] = _approve_side(manifest[side], digest)
        _write_result(manifest, result)
    for side in SIDES:
        if _published(manifest[side], digest) != result[side + 'Generation']:
            raise ValueError('both current pointers must match approved generations')
    result['status'] = 'PUBLISHED'
    return _write_result(manifest, result)


if __name__ == '__main__':
    raise SystemExit(_benchmark_cli_main())
