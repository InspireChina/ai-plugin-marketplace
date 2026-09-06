"""Freeze independently authored benchmark inputs; never invoke a provider or start a run."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from contracts import canonical_json_bytes, sha256_bytes, validate_contract
from runtime.project_io import ProjectFiles, ProjectIOError
from source_readers import extract_source_blocks, html_elements
from prototype_analysis import inventory_demo_bundle


def _binding(path, raw):
    return {'path': path, 'sha256': sha256_bytes(raw)}


def _read_demos(files, locators, draft=None):
    if draft is None: draft = files.read_json('oracle/demo-conversion-draft.json')
    if set(draft) != {'greenfield', 'brownfield'}:
        raise ValueError('conversion draft must contain both independent sides')
    result = {}
    for side, value in draft.items():
        if set(value) != {'entrypoint', 'files', 'reverseMappings'}:
            raise ValueError('conversion draft fields are closed')
        if value['entrypoint'] != 'index.html': raise ValueError('benchmark Demo entrypoint must be index.html')
        prepared = []
        for item in value['files']:
            if set(item) != {'relativePath', 'sourceId', 'draftPath'}:
                raise ValueError('conversion file fields are closed')
            relative = item['relativePath']
            if relative not in {'index.html', 'style.css', 'app.js'}:
                raise ValueError('benchmark conversion must be a static three-file bundle')
            raw = files.read_bytes(item['draftPath'])
            document = extract_source_blocks(files.resolve(item['draftPath'], expect='file'),
                source_role='DEMO', parser_version='benchmark-source-v1')
            prepared.append({'relativePath': relative, 'sourceId': item['sourceId'], 'content': raw,
                'locators': [block['locator'] for block in document.blocks]})
        if {item['relativePath'] for item in prepared} != {'index.html', 'style.css', 'app.js'}:
            raise ValueError('all three static bundle files are required')
        inventory = inventory_demo_bundle(value['entrypoint'], prepared)
        subjects = set()
        for item in prepared:
            subjects.update(('SOURCE', item['relativePath'] + '#' + locator) for locator in item['locators'])
            if item['relativePath'].endswith('.html'):
                for element in html_elements(item['content'].decode('utf-8')):
                    selector = '#' + element['attributes']['id'] if element['attributes'].get('id') else element['selector']
                    subjects.add(('DOM', item['relativePath'] + '#' + selector))
        subjects.update(('SCENARIO', item['page'] + '#' + item['selector'] + ':' + item['event'])
            for item in inventory['interactions'])
        mapped = set()
        for row in value['reverseMappings']:
            if set(row) != {'kind', 'subject', 'disposition', 'sourceLocators'}:
                raise ValueError('reverse mapping fields are closed')
            key = (row['kind'], row['subject'])
            if key in mapped or key not in subjects: raise ValueError('reverse mapping is duplicate or unrelated')
            mapped.add(key)
            refs = row['sourceLocators']
            if len(refs) != len(set(refs)) or not set(refs) <= locators[side]:
                raise ValueError('Demo reverse mapping must resolve to this side frozen sources')
            if row['disposition'] == 'SOURCE_MAPPED':
                if not refs: raise ValueError('scope-bearing conversion requires frozen evidence')
            elif row['disposition'] == 'NON_SCOPE_PRESENTATION':
                if refs or row['kind'] == 'SCENARIO': raise ValueError('interactions cannot be presentation-only')
            else: raise ValueError('unknown conversion disposition')
        if mapped != subjects: raise ValueError('unmapped Demo DOM, scenario or source locator')
        result[side] = {'files': prepared, 'reverseMappings': value['reverseMappings']}
    return result


def _migrate(api, legacy, version, side, source_rows, demo_rows):
    value = copy.deepcopy(legacy)
    if value.get('contract') not in {'ai-sow-generate-request-v2', 'ai-sow-generate-request-v3'}:
        raise ValueError('unsupported legacy request contract')
    if 'currentStateDelta' in value:
        if value['contract'] != 'ai-sow-generate-request-v2' or 'declaredChangeContext' in value:
            raise ValueError('ambiguous legacy change context')
        value['declaredChangeContext'] = value.pop('currentStateDelta')
    mode, date = ('GREENFIELD', '2026-11-16') if side == 'greenfield' else ('BROWNFIELD', '2027-02-15')
    if value.get('mode') != mode or value['project']['plannedEffectiveDate'] != date:
        raise ValueError('request mode or plannedEffectiveDate drift')
    old = value['sources']; aliases = {}; sources = []
    for role in ('PRD', 'HLD'):
        matches = [row for row in old if row['role'] == role]
        current = next(row for row in source_rows if row['role'] == role)
        if len(matches) != 1 or matches[0].get('expectedSha256', current['sha256']) != current['sha256'] or matches[0]['path'] != current['baselinePath']:
            raise ValueError('legacy request must bind the exact frozen source bytes')
        aliases[matches[0]['sourceId']] = current['sourceId']
        sources.append({'sourceId': current['sourceId'], 'role': role,
            'path': 'inputs/' + role.lower() + '.md', 'expectedSha256': current['sha256']})
    if any(row['role'] not in {'PRD', 'HLD', 'DEMO', 'PRIOR_SOW'} for row in old):
        raise ValueError('legacy request contains an unfrozen source')
    priors = [row for row in old if row['role'] == 'PRIOR_SOW']
    if len(priors) > 1 or (side == 'greenfield' and priors): raise ValueError('unexpected prior source')
    if side == 'brownfield':
        prior = copy.deepcopy(priors[0]) if priors else {'sourceId': version + '-prior', 'role': 'PRIOR_SOW'}
        prior.pop('status', None)
        prior.update(path=api.PRIOR_PATH, expectedSha256=api.PRIOR_HASH); sources.append(prior)
    original_demo = next(row for row in source_rows if row['role'] == 'DEMO')
    legacy_demo = [row for row in old if row['role'] == 'DEMO']
    if len(legacy_demo) != 1 or legacy_demo[0].get('expectedSha256', original_demo['sha256']) != original_demo['sha256'] or legacy_demo[0]['path'] != original_demo['baselinePath']:
        raise ValueError('legacy Demo must bind the frozen original Markdown')
    aliases[legacy_demo[0]['sourceId']] = next(item['sourceId'] for item in demo_rows if item['relativePath'] == 'index.html')
    value.update(contract='ai-sow-generate-request-v3', sources=sources,
        demo={'entrypoint': 'inputs/demo/index.html', 'files': [
            {'sourceId': item['sourceId'], 'role': 'DEMO', 'path': 'inputs/demo/' + item['relativePath'],
                'expectedSha256': sha256_bytes(item['content'])} for item in demo_rows]})
    if value['declaredChangeContext'] is not None:
        value['declaredChangeContext']['supplementalSourceIds'] = [aliases.get(key, key)
            for key in value['declaredChangeContext']['supplementalSourceIds']]
    candidate = api._replace_prior(value, 'inputs/prior/greenfield-sow.xlsx', '0'*64) if side == 'brownfield' else value
    if validate_contract(candidate, 'request.schema.json', api.REGISTRY):
        raise ValueError('migration cannot preserve business fields within complete v3 request')
    return value


def prepare(api, baseline_root, output_root, expectation_draft):
    baseline_root, output_root, expectation_draft = map(lambda p: Path(p).absolute(),
        (baseline_root, output_root, expectation_draft))
    if baseline_root.is_relative_to(output_root) or output_root.is_relative_to(baseline_root):
        raise ValueError('baseline and benchmark output roots must be separate')
    baseline, files = ProjectFiles.open(baseline_root), ProjectFiles.open(output_root)
    for path in output_root.glob('runs/*/*/project/.ai-sow/work/runs/*/events/*.json'):
        event = files.read_json(path.relative_to(output_root).as_posix())
        if event.get('type') == 'ACTION_ISSUED': raise ValueError('oracle must precede first ACTION_ISSUED')
    raw_sources = {relative: baseline.read_bytes(relative) for relative in api._BENCHMARK_BASELINE_SHA256}
    if any(sha256_bytes(raw) != api._BENCHMARK_BASELINE_SHA256[path] for path, raw in raw_sources.items()):
        raise ValueError('frozen baseline source or legacy request bytes drifted')
    oracle = ProjectFiles.open(expectation_draft.parent).read_json(expectation_draft.name)
    api._validate_expectation_manifest(oracle); oracle_raw = canonical_json_bytes(oracle)
    policy_raw = files.read_bytes('run-budget-policy-source.json'); policy = json.loads(policy_raw)
    if canonical_json_bytes(policy) != policy_raw or validate_contract(policy, 'run-budget-policy.schema.json', api.REGISTRY):
        raise ValueError('explicit shared policy source must be complete canonical bytes')
    from provider_adapter import validate_model_estimator
    validate_model_estimator(policy['modelProfileId'], policy['estimatorVersion'])
    source_rows, locators = [], {'greenfield': set(), 'brownfield': set()}
    for version, side in (('v1', 'greenfield'), ('v2', 'brownfield')):
        for kind in ('prd', 'hld', 'demo'):
            relative = f'inputs/{version}/{kind}.md'
            document = extract_source_blocks(baseline.resolve(relative, expect='file'),
                source_role='SUPPLEMENT' if kind == 'demo' else kind.upper(), parser_version='benchmark-source-v1')
            source_id = version + '-' + kind
            locator_values = [block['locator'] for block in document.blocks]
            locators[side].update(source_id + '#' + value for value in locator_values)
            source_rows.append({'side': side, 'role': kind.upper(), 'sourceId': source_id,
                'baselinePath': relative, 'sha256': sha256_bytes(raw_sources[relative]), 'locators': locator_values})
    all_locators = set.union(*locators.values())
    for item in oracle['expectedObligations']:
        if item['sourceId'] + '#' + item['exactLocator'] not in all_locators:
            raise ValueError('oracle obligation does not resolve to frozen source locator')
    for item in oracle['expectedBrownfieldChanges'] + oracle['expectedUnchangedCapabilities']:
        if not set(item['priorLocatorIds']) <= locators['greenfield'] or not set(item.get('targetLocatorIds', [])) <= locators['brownfield']:
            raise ValueError('oracle change locators must reference frozen v1/v2 sources')
    demos = _read_demos(files, locators)
    identity = {'baseline': api._BENCHMARK_BASELINE_SHA256, 'expectationSha256': sha256_bytes(oracle_raw),
        'policySha256': sha256_bytes(policy_raw), 'demos': {side: {
            'files': [_binding(item['relativePath'], item['content']) for item in data['files']],
            'reverseMappings': data['reverseMappings']} for side, data in demos.items()}}
    pair_id = 'pair-' + sha256_bytes(canonical_json_bytes(identity))
    writes = {f'frozen/{path}': raw for path, raw in raw_sources.items()}
    writes['benchmark-expectation-manifest.json'] = oracle_raw
    requests, bundles = {}, {}
    for version, side in (('v1', 'greenfield'), ('v2', 'brownfield')):
        project = f'runs/{pair_id}/{side}/project/'
        rows = [row for row in source_rows if row['side'] == side]
        for row in rows:
            row['frozenPath'] = 'frozen/' + row['baselinePath']
            writes[row['frozenPath']] = raw_sources[row['baselinePath']]
            if row['role'] != 'DEMO':
                writes[project + 'inputs/' + row['role'].lower() + '.md'] = raw_sources[row['baselinePath']]
        bundle_rows = []
        for item in demos[side]['files']:
            path = project + 'inputs/demo/' + item['relativePath']; writes[path] = item['content']
            bundle_rows.append({'sourceId': item['sourceId'], **_binding(path, item['content'])})
        bundles[side] = {'entrypoint': project + 'inputs/demo/index.html', 'files': bundle_rows,
            'reverseMappings': demos[side]['reverseMappings']}
        request = _migrate(api, json.loads(raw_sources[f'requests/{version}.json']), version, side, rows, demos[side]['files'])
        path = project + 'request.json' if side == 'greenfield' else 'brownfield-request-template.json'
        raw = canonical_json_bytes(request); writes[path] = raw
        requests['greenfield' if side == 'greenfield' else 'brownfieldTemplate'] = _binding(path, raw)
    manifest = {'contract': 'ai-sow-benchmark-input-v1', 'pairRunId': pair_id,
        'baselineFiles': [{'relativePath': path, 'sha256': digest} for path, digest in sorted(api._BENCHMARK_BASELINE_SHA256.items())],
        'frozenSources': source_rows, 'requests': requests, 'bundles': bundles,
        'policySource': _binding('run-budget-policy-source.json', policy_raw),
        'expectationManifest': _binding('benchmark-expectation-manifest.json', oracle_raw),
        'brownfieldMaximumBatchRows': 100,
        'historicalCorrections': [{'obsoleteMaximumBatchRows': 500, 'currentMaximumBatchRows': 100, 'reason': '旧记录错误；当前冻结来源每批最多 100 行。'}]}
    api._validate(manifest, 'benchmark-input-manifest')
    writes['benchmark-input-manifest.json'] = canonical_json_bytes(manifest)
    for path, raw in writes.items():
        try: existing = files.read_bytes(path)
        except ProjectIOError as error:
            if error.code != 'PROJECT_PATH_MISSING': raise
        else:
            if existing != raw: raise ValueError('immutable benchmark preparation conflicts with existing bytes')
    if any(baseline.read_bytes(path) != raw for path, raw in raw_sources.items()):
        raise ValueError('baseline changed during preparation')
    for path, raw in writes.items(): files.publish_new(path, raw)
    return {'outcome': 'PREPARED', 'pairRunId': pair_id,
        'inputManifest': _binding('benchmark-input-manifest.json', writes['benchmark-input-manifest.json']),
        'expectationManifest': manifest['expectationManifest']}
