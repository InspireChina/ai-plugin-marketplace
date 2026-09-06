"""Read the prepared pair and immutable production records without starting work."""
from __future__ import annotations

import json
from pathlib import Path

from contracts import canonical_json_bytes, sha256_bytes, validate_contract
from runtime.project_io import ProjectFiles
from source_readers import extract_source_blocks
from benchmark_preparation import _migrate, _read_demos


def bound(files, binding):
    raw = files.read_bytes(binding['path'])
    if sha256_bytes(raw) != binding['sha256']: raise ValueError('frozen file hash mismatch: ' + binding['path'])
    return raw


def prepared(api, output_root, pair_id):
    files = ProjectFiles.open(Path(output_root))
    raw = files.read_bytes('benchmark-input-manifest.json'); manifest = json.loads(raw)
    if canonical_json_bytes(manifest) != raw: raise ValueError('input manifest is not canonical')
    api._validate(manifest, 'benchmark-input-manifest')
    if manifest['pairRunId'] != pair_id: raise ValueError('pairRunId does not match frozen input manifest')
    bindings = {row['relativePath']: row['sha256'] for row in manifest['baselineFiles']}
    if len(bindings) != 8 or bindings != api._BENCHMARK_BASELINE_SHA256:
        raise ValueError('input manifest changed one of the eight frozen baseline bindings')
    originals = {path: bound(files, {'path': 'frozen/' + path, 'sha256': digest}) for path, digest in bindings.items()}
    locators = {'greenfield': set(), 'brownfield': set()}; source_ids = set()
    for side, version in (('greenfield', 'v1'), ('brownfield', 'v2')):
        rows = [row for row in manifest['frozenSources'] if row['side'] == side]
        if sorted(row['role'] for row in rows) != ['DEMO', 'HLD', 'PRD']:
            raise ValueError('six frozen source roles must cover each side exactly')
        for row in rows:
            expected_path = f"inputs/{version}/{row['role'].lower()}.md"
            if (row['baselinePath'] != expected_path or row['frozenPath'] != 'frozen/' + expected_path
                or row['sha256'] != bindings[expected_path] or row['sourceId'] != version + '-' + row['role'].lower()
                or row['sourceId'] in source_ids):
                raise ValueError('frozen source identity or path drift')
            source_ids.add(row['sourceId'])
            document = extract_source_blocks(files.resolve(row['frozenPath'], expect='file'),
                source_role='SUPPLEMENT' if row['role'] == 'DEMO' else row['role'], parser_version='benchmark-source-v1')
            if row['locators'] != [block['locator'] for block in document.blocks]:
                raise ValueError('frozen exact source locators changed')
            locators[side].update(row['sourceId'] + '#' + locator for locator in row['locators'])
    conversion = {}
    for side, bundle in manifest['bundles'].items():
        project = f'runs/{pair_id}/{side}/project/'
        if bundle['entrypoint'] != project + 'inputs/demo/index.html': raise ValueError('Demo entrypoint escaped project')
        rows = []
        for row in bundle['files']:
            relative = Path(row['path']).name
            if row['path'] != project + 'inputs/demo/' + relative: raise ValueError('Demo file escaped project')
            bound(files, row)
            if row['sourceId'] in source_ids: raise ValueError('Demo source IDs must be globally unique')
            source_ids.add(row['sourceId'])
            rows.append({'relativePath': relative, 'sourceId': row['sourceId'], 'draftPath': row['path']})
        conversion[side] = {'entrypoint': 'index.html', 'files': rows, 'reverseMappings': bundle['reverseMappings']}
    demos = _read_demos(files, locators, conversion)
    if manifest['policySource']['path'] != 'run-budget-policy-source.json': raise ValueError('shared policy source path changed')
    policy_raw = bound(files, manifest['policySource']); policy = json.loads(policy_raw)
    if canonical_json_bytes(policy) != policy_raw or validate_contract(policy, 'run-budget-policy.schema.json', api.REGISTRY):
        raise ValueError('shared policy source is invalid')
    if manifest['expectationManifest']['path'] != 'benchmark-expectation-manifest.json': raise ValueError('oracle path changed')
    oracle_raw = bound(files, manifest['expectationManifest']); oracle = json.loads(oracle_raw)
    api._validate_expectation_manifest(oracle)
    if canonical_json_bytes(oracle) != oracle_raw: raise ValueError('oracle is not canonical')
    for side, version, key in (('greenfield', 'v1', 'greenfield'), ('brownfield', 'v2', 'brownfieldTemplate')):
        rows = [row for row in manifest['frozenSources'] if row['side'] == side]
        expected = _migrate(api, json.loads(originals[f'requests/{version}.json']), version, side, rows, demos[side]['files'])
        path = f'runs/{pair_id}/greenfield/project/request.json' if side == 'greenfield' else 'brownfield-request-template.json'
        if manifest['requests'][key]['path'] != path or bound(files, manifest['requests'][key]) != canonical_json_bytes(expected):
            raise ValueError('request business fields drifted from mechanical frozen migration')
    identity = {'baseline': bindings, 'expectationSha256': sha256_bytes(oracle_raw), 'policySha256': sha256_bytes(policy_raw),
        'demos': {side: {'files': [{'path': item['relativePath'], 'sha256': sha256_bytes(item['content'])} for item in data['files']],
            'reverseMappings': data['reverseMappings']} for side, data in demos.items()}}
    if pair_id != 'pair-' + sha256_bytes(canonical_json_bytes(identity)):
        raise ValueError('prepared pair identity changed')
    return files, manifest, oracle, demos


def instantiate(api, output_root, pair_id, prior_path):
    files, manifest, _, _ = prepared(api, output_root, pair_id)
    project_relative = f'runs/{pair_id}/brownfield/project'
    project = ProjectFiles.open(files.resolve(project_relative, expect='dir'))
    raw = bound(files, manifest['requests']['brownfieldTemplate'])
    project.publish_new('brownfield-request-template.json', raw)
    path = api.instantiate_brownfield_request(project.root / 'brownfield-request-template.json', Path(prior_path), project.root / 'request.json')
    raw = project.read_bytes(path.name)
    return {'outcome': 'INSTANTIATED', 'pairRunId': pair_id,
        'request': {'path': path.relative_to(files.root).as_posix(), 'sha256': sha256_bytes(raw)}}


def select_run(api, project):
    root = project.resolve('.ai-sow/work/runs', expect='dir'); runs = []
    failed_results = {'ABANDONED', 'MANUAL_REVIEW_REQUIRED', 'CONTRACT_UNSUPPORTED', 'SYSTEM_FAILED'}
    for path in sorted(root.iterdir()):
        project.resolve(path.relative_to(project.root).as_posix(), expect='dir')
        events = api.orchestrator._read_run_events(project, path.name)
        states = [event.payload['toState'] for event in events if event.type == 'RUN_STATE_CHANGED']
        state = states[-1] if states else 'ACTIVE'
        # Public terminal outcomes may publish a content-addressed terminal
        # state without a RUN_STATE_CHANGED event. Read that original
        # proof too; never delete failed runs or trust a mutable run summary.
        for snapshot in sorted((path / 'states').glob('state-*.json')):
            relative = snapshot.relative_to(project.root).as_posix()
            raw = project.read_bytes(relative); value = json.loads(raw)
            if value.get('result') not in failed_results: continue
            if canonical_json_bytes(value) != raw or snapshot.name != 'state-' + sha256_bytes(raw) + '.json':
                raise ValueError('terminal snapshot bytes or hash mismatch')
            api.orchestrator._validated_run_state(value, relative)
            binding = project.read_json(path.relative_to(project.root).as_posix() + '/input-binding.json')
            if (value['phase'] != 'DONE' or value['runId'] != path.name
                or binding.get('runId') != path.name or value['requestSha256'] != binding.get('requestSha256')
                or value['currentInputRevisionSha256'] != binding.get('inputRevisionSha256')):
                raise ValueError('terminal snapshot input binding mismatch')
            marker = api.orchestrator._read_active_marker(project)
            if marker is not None and marker['runId'] == path.name:
                raise ValueError('terminal snapshot conflicts with active run')
            state = value['result']
        if state not in failed_results: runs.append((path.name, events, state))
    if len(runs) != 1: raise ValueError('benchmark side must resolve to exactly one viable run')
    return runs[0]


def revision_from_events(project, events):
    declared = {event.payload['inputRevisionSha256'] for event in events if event.type == 'INPUT_REVISION_CREATED'}
    digests = set()
    for event in events:
        if event.type != 'ACTION_ISSUED': continue
        action_id = event.payload['actionId']
        raw = bound(project, {'path': f'.ai-sow/work/runs/{event.run_id}/actions/{action_id}/envelope.json',
            'sha256': event.payload['envelopeSha256']})
        envelope = json.loads(raw)
        if envelope['runId'] != event.run_id or envelope['actionId'] != action_id:
            raise ValueError('issuance event references a different Action')
        digests.add(envelope['inputRevisionSha256'])
    if declared and declared != digests: raise ValueError('InputRevision event and issued Envelopes disagree')
    if len(digests) != 1: raise ValueError('run must bind exactly one immutable InputRevision')
    digest = next(iter(digests)); matches = []
    root = project.resolve('.ai-sow/inputs/revisions', expect='dir')
    for path in root.glob('*/manifest.json'):
        raw = project.read_bytes(path.relative_to(project.root).as_posix())
        if sha256_bytes(raw) == digest: matches.append(json.loads(raw))
    if len(matches) != 1: raise ValueError('InputRevision hash must resolve uniquely')
    return matches[0]


def initial_policy(api, project, run_id, events, manifest):
    publications = [event for event in events if event.type == 'RUN_BUDGET_POLICY_PUBLISHED']
    issued = [event for event in events if event.type == 'ACTION_ISSUED']
    if not publications or not issued or publications[0].sequence >= issued[0].sequence:
        raise ValueError('run-local initial policy must precede first issued Action')
    digest = publications[0].payload['budgetPolicySha256']
    if digest != manifest['policySource']['sha256']: raise ValueError('both runs must start from the same frozen policy source')
    bound(project, {'path': f'.ai-sow/work/runs/{run_id}/budget-policies/{digest}.json', 'sha256': digest})


def sealed_prototype_ledger(project, run_id, revision, inventory, ledger):
    """Resolve the final Analyze dispositions through the frozen Scope plan."""
    from scope_compiler import prepare_scope_prototype_contexts
    root = f'.ai-sow/work/runs/{run_id}/stages/SCOPE'
    plans = list(project.resolve(root + '/plans', expect='dir').glob('*.json'))
    if len(plans) != 1: raise ValueError('browser evidence requires one frozen Scope StagePlan')
    raw = bound(project, {'path': plans[0].relative_to(project.root).as_posix(), 'sha256': plans[0].stem})
    plan = json.loads(raw)
    if canonical_json_bytes(plan) != raw or plan['stageKind'] != 'SCOPE': raise ValueError('invalid Scope StagePlan bytes')
    references = {ref['contentSha256'] for work in plan['works'] for ref in work['packetPlan']['contextRefs'] if ref['refId'] == 'prototype-ledger'}
    if len(references) != 1: raise ValueError('Scope StagePlan must bind one sealed Prototype ledger')
    expected = next(iter(references)); matches = []
    revision_hash = sha256_bytes(canonical_json_bytes(revision))
    for path in project.resolve(root + '/prototype-ledgers', expect='dir').glob('*.json'):
        raw = bound(project, {'path': path.relative_to(project.root).as_posix(), 'sha256': path.stem})
        value = json.loads(raw)
        if canonical_json_bytes(value) != raw: raise ValueError('noncanonical Prototype ledger')
        context = {'kind': 'PROTOTYPE_LEDGER', 'ledger': value, 'inputRevisionSha256': revision_hash}
        if sha256_bytes(canonical_json_bytes(context)) == expected: matches.append(value)
    if len(matches) != 1: raise ValueError('Scope-bound Prototype ledger must resolve uniquely')
    value = matches[0]
    contexts = prepare_scope_prototype_contexts(inventory, value, ledger)
    if sha256_bytes(contexts[0].canonical_content) != expected:
        raise ValueError('Prototype ledger does not match actual scenario/browser/Analyze Attempts')
    return value


def verify_browser(api, output_root, pair_id, side):
    files, manifest, _, _ = prepared(api, output_root, pair_id)
    if side not in {'greenfield', 'brownfield'}: raise ValueError('unknown benchmark side')
    project = ProjectFiles.open(files.resolve(f'runs/{pair_id}/{side}/project', expect='dir'))
    request = api._request(project, 'request.json', side.upper())
    run_id, events, state = select_run(api, project)
    initial_policy(api, project, run_id, events, manifest)
    revision = revision_from_events(project, events)
    if revision['requestSha256'] != sha256_bytes(canonical_json_bytes(request)):
        raise ValueError('browser run belongs to a different frozen request')
    ledger = api.orchestrator._load_action_ledger(project, run_id)
    def discovery_round(record):
        envelope = ledger.envelopes_by_sha256[record.envelope_sha256].value
        packet = json.loads(bound(project, {'path': envelope['packetPath'], 'sha256': envelope['packetSha256']}))
        return packet['workItems'][0]['payload']['identity']['round']
    records = sorted((record for record in ledger.attempt_records.values() if record.outcome == 'SUCCEEDED'
        and ledger.envelopes_by_sha256[record.envelope_sha256].value['actionContractId'] == 'PROTOTYPE_BROWSER-v1'), key=discovery_round)
    profile, rounds, discovered, screenshot_count = None, [], set(), 0
    for record in records:
        envelope = ledger.envelopes_by_sha256[record.envelope_sha256].value
        if envelope['actionContractId'] != 'PROTOTYPE_BROWSER-v1' or record.outcome != 'SUCCEEDED': continue
        raw = bound(project, {'path': envelope['packetPath'], 'sha256': envelope['packetSha256']})
        payload = json.loads(raw)['workItems'][0]['payload']; inventory = payload['inventory']
        scenario = payload['scenario']['normalizedResult']
        trace = json.loads(ledger.normalized_results[record.normalized_result_sha256])
        if profile is None: profile = trace['browserProfile']
        proof = api._benchmark_browser_trace(inventory, scenario, trace, profile)
        if proof['outcome'] == 'WAITING_INPUT': return {'pairRunId': pair_id, 'side': side, **proof}
        source_by_id = {row['sourceId']: row for row in revision['sources']}
        for item in inventory['files']:
            source = source_by_id[item['sourceId']]
            if sha256_bytes(project.read_bytes(source['path'])) != item['sha256']:
                raise ValueError('immutable Demo source bytes changed')
        for run in trace['runs']:
            for step in run['steps']:
                digest = step['screenshotSha256']
                if digest is not None:
                    raw = bound(project, {'path': f'.ai-sow/work/runs/{run_id}/browser-screenshots/{digest}.png', 'sha256': digest})
                    if not raw.startswith(b'\x89PNG\r\n\x1a\n'): raise ValueError('browser screenshot must be original PNG bytes')
                    screenshot_count += 1
        discovered.update(item['interactionId'] for item in inventory['interactions'])
        if trace['unresolvedDiscoveries']: return {'outcome': 'WAITING_INPUT', 'reasonCode': 'INCOMPLETE_BUDGET', 'pairRunId': pair_id, 'side': side}
        rounds.append(payload['identity']['round'])
    if not rounds or rounds != list(range(1, len(rounds) + 1)):
        raise ValueError('browser evidence must retain all contiguous discovery rounds')
    sealed = sealed_prototype_ledger(project, run_id, revision, inventory, ledger)
    rate = api._benchmark_disposition_rate(sorted(discovered), sealed['interactionDispositions'],
        id_key='interactionId', terminal={'OBSERVED', 'BROKEN', 'NOT_EXERCISED', 'EXCLUDED'}, sealed=sealed['sealed'])
    if rate != 1.0: raise ValueError('browser interaction inventory is not fully disposed')
    return {'outcome': 'VERIFIED', 'pairRunId': pair_id, 'side': side, 'runId': run_id,
        'browserProfileSha256': sha256_bytes(canonical_json_bytes(profile)),
        'discoveryRounds': len(rounds), 'screenshotsVerified': screenshot_count,
        'demoInteractionDispositionRate': rate, 'externalRequestCount': 0}
