"""Pair control tests: cheap isolation first; real publication in its own layer."""
import copy
import importlib
import json
import shutil
import sys
from pathlib import Path

import pytest

TEST_LAYER = 'unit'
PLUGIN = Path(__file__).parents[1]
SKILL = PLUGIN / 'skills/generate'
for path in (PLUGIN, SKILL / 'scripts', PLUGIN / 'tests/support'):
    sys.path.insert(0, str(path))
from contracts import canonical_json_bytes, sha256_bytes
from runtime.project_io import ProjectFiles


def harness():
    path = PLUGIN / 'tests/support/run_paired_benchmark.py'
    assert path.is_file(), 'independent pair harness is missing'
    return importlib.import_module('run_paired_benchmark')


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))
    return path


def freeze_feedback(root, value):
    raw = canonical_json_bytes(value)
    path = f'pair-feedback/request-{sha256_bytes(raw)}.json'
    ProjectFiles.open(root).publish_new(path, raw)
    return path


def input_project(root, mode='BROWNFIELD'):
    root.mkdir(parents=True, exist_ok=True)
    source = SKILL / f'fixtures/pipeline/e2e/{mode.lower()}'
    request = json.loads((source / 'request.json').read_bytes())
    for item in request['sources']:
        shutil.copyfile(source / item['path'], root / item['path'])
    return request


def template(root):
    request = input_project(root)
    request['sources'].append({'sourceId': 'prior-green', 'role': 'PRIOR_SOW',
        'path': '${PRIOR_SOW_PATH}', 'expectedSha256': '${PRIOR_SOW_SHA256}'})
    return write(root / 'brown-template.json', request)


def test_pair_isolation_mechanical_copy_is_immutable_and_canonical_fields_unchanged(tmp_path):
    pair = harness()
    root = tmp_path / 'brown'; source = template(root)
    prior = tmp_path / 'green.xlsx'; shutil.copyfile(SKILL / 'assets/sow-template.xlsx', prior)
    before = source.read_bytes(); original = json.loads(before)
    output = pair.instantiate_brownfield_request(source, prior, root / 'request.json')
    request = json.loads(output.read_bytes()); binding = request['sources'][-1]
    copied = root / binding['path']
    assert copied.read_bytes() == prior.read_bytes()
    assert binding['expectedSha256'] == sha256_bytes(prior.read_bytes())
    request['sources'][-1] = original['sources'][-1]
    assert canonical_json_bytes(request) == canonical_json_bytes(original)
    assert source.read_bytes() == before
    assert pair.instantiate_brownfield_request(source, prior, output) == output
    changed = json.loads(before); changed['project']['name'] = '修改项目'
    write(source, changed)
    with pytest.raises(ValueError): pair.instantiate_brownfield_request(source, prior, output)


@pytest.mark.parametrize('bad', ['duplicate', 'missing', 'schema', 'hidden', 'model', 'checkpoint', 'manifest', 'chat', 'sidecar', 'symlink', 'hash'])
def test_pair_isolation_rejects_unapproved_inputs_before_output(tmp_path, bad):
    pair = harness(); root = tmp_path / 'brown'; source = template(root)
    prior = tmp_path / 'green.xlsx'; shutil.copyfile(SKILL / 'assets/sow-template.xlsx', prior)
    value = json.loads(source.read_bytes())
    if bad == 'duplicate': value['sources'].append(copy.deepcopy(value['sources'][-1]))
    elif bad == 'missing': value['sources'][-1]['expectedSha256'] = '0' * 64
    elif bad == 'schema': value['responsibilityBoundaries'] = []
    elif bad == 'hash': value['sources'][0]['expectedSha256'] = '0' * 64
    elif bad == 'symlink':
        (root / 'prd.md').unlink(); (root / 'prd.md').symlink_to(tmp_path / 'external.md')
        (tmp_path / 'external.md').write_text('secret')
    else:
        path = '.ai-sow/prd.md' if bad == 'hidden' else f'{bad}.md'
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / 'prd.md', root / path)
        value['sources'][0]['path'] = path
    write(source, value)
    with pytest.raises(ValueError): pair.instantiate_brownfield_request(source, prior, root / 'request.json')
    assert not (root / 'request.json').exists()


@pytest.mark.parametrize('decision', [
    {'decision': 'APPROVE', 'side': 'GREENFIELD'},
    {'decision': 'REJECT', 'side': 'GREENFIELD'},
    {'decision': 'REJECT', 'side': 'BOTH', 'feedbackInputPath': 'feedback.json'},
    {'decision': 'APPROVE', 'feedbackInputPath': 'feedback.json'},
])
def test_one_pair_decision_closed_union(decision):
    pair = harness()
    value = {'contract': 'ai-sow-pair-decision-v1', 'pairReviewManifestSha256': '1' * 64, **decision}
    with pytest.raises(ValueError): pair._validate(value, 'pair-decision')


@pytest.fixture(scope='session')
def real_pair(tmp_path_factory):
    # Imported only by e2e tests; unit collection does not import a generation driver.
    sys.path.insert(0, str(SKILL / 'tests'))
    from test_e2e import drive_fixture_host, drive_result_host
    from test_contracts import valid_run_budget_policy
    import orchestrator
    pair = harness(); root = tmp_path_factory.mktemp('pair-artifacts')
    green = root / 'green'; green.mkdir()
    ready, _ = drive_fixture_host(green)
    brown = root / 'brown'; source = template(brown)
    pair.instantiate_brownfield_request(source, green / ready['workbookPath'], brown / 'request.json')
    policy = valid_run_budget_policy()
    policy.update(modelContextLimitTokens=2000000, maxPlannedTokens=100000000)
    write(brown / 'budget.json', policy)
    result = orchestrator.run_mode(brown, 'start', request='request.json', budget_policy='budget.json')
    ready_brown, _ = drive_result_host(brown, result)
    assert ready_brown['outcome'] == 'REQUEST_APPROVAL', ready_brown
    return root


def pair_copy(real_pair, tmp_path):
    root = tmp_path / 'pair'; shutil.copytree(real_pair, root)
    green = {'projectRoot': str(root / 'green'), 'requestPath': 'request.json', 'budgetPolicyPath': 'budget.json'}
    brown = {'projectRoot': str(root / 'brown'), 'requestPath': 'request.json', 'budgetPolicyPath': 'budget.json', 'templatePath': 'brown-template.json'}
    return harness(), green, brown


def decision(manifest, kind='APPROVE', **extra):
    return {'contract': 'ai-sow-pair-decision-v1',
        'pairReviewManifestSha256': sha256_bytes(canonical_json_bytes(manifest)), 'decision': kind, **extra}


@pytest.mark.e2e
def test_pair_review_readiness_and_approval_bytes_invalidation(real_pair, tmp_path):
    pair, green, brown = pair_copy(real_pair, tmp_path)
    manifest = pair.prepare_pair_review(green, brown)
    assert manifest['status'] == 'READY_FOR_REVIEW'
    for side in ('green', 'brown'):
        entry = manifest[side]
        assert entry['workbookSha256'] == sha256_bytes((Path(entry['projectRoot']) / entry['workbookPath']).read_bytes())
    target = Path(brown['projectRoot']) / manifest['brown']['workbookPath']
    target.write_bytes(target.read_bytes() + b'tampered')
    with pytest.raises(ValueError): pair.submit_pair_decision(manifest, decision(manifest))
    assert pair._read_result(manifest)['status'] == 'SUPERSEDED'
    assert not (Path(green['projectRoot']) / '.ai-sow/current.json').exists()


@pytest.mark.e2e
def test_pair_publish_recovery_and_pair_published_proof(real_pair, tmp_path, monkeypatch):
    pair, green, brown = pair_copy(real_pair, tmp_path)
    manifest = pair.prepare_pair_review(green, brown); approve = decision(manifest)
    original = pair.orchestrator.run_mode
    def crash(root, mode, **kwargs):
        if str(root) == brown['projectRoot'] and mode == 'approve': raise RuntimeError('second publication crash')
        return original(root, mode, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(pair.orchestrator, 'run_mode', crash)
        with pytest.raises(RuntimeError, match='second publication'): pair.submit_pair_decision(manifest, approve)
    assert pair._read_result(manifest)['status'] == 'PUBLISHING'
    current_path = Path(green['projectRoot']) / '.ai-sow/current.json'; first = current_path.read_bytes()
    with pytest.raises(ValueError):
        pair.submit_pair_decision(manifest, decision(manifest, 'REJECT', side='BROWNFIELD', feedbackInputPath='request.json'))
    result = pair.submit_pair_decision(manifest, approve)
    assert result['status'] == 'PUBLISHED'
    assert current_path.read_bytes() == first
    assert len(list((Path(green['projectRoot']) / '.ai-sow/generations').iterdir())) == 1
    assert pair.submit_pair_decision(manifest, approve) == result
    for side in ('green', 'brown'):
        entry = result[side + 'Generation']
        generated = json.loads((Path(manifest[side]['projectRoot']) / entry['manifestPath']).read_bytes())
        assert generated['pairDecisionSha256'] == sha256_bytes(canonical_json_bytes(approve))
        assert generated['workbookSha256'] == manifest[side]['workbookSha256']
    # Current pointing elsewhere can never be reported as the approved pair.
    (Path(brown['projectRoot']) / '.ai-sow/current.json').write_text('{}')
    with pytest.raises(ValueError): pair.submit_pair_decision(manifest, approve)


@pytest.mark.e2e
@pytest.mark.parametrize('side', ['GREENFIELD', 'BROWNFIELD'])
def test_pair_rejection_rerun_full_request_and_frozen_green(real_pair, tmp_path, side):
    pair, green, brown = pair_copy(real_pair, tmp_path)
    manifest = pair.prepare_pair_review(green, brown)
    selected = green if side == 'GREENFIELD' else brown
    feedback = json.loads((Path(selected['projectRoot']) / 'request.json').read_bytes())
    feedback['project']['name'] += '复审'
    feedback_path = freeze_feedback(Path(selected['projectRoot']), feedback)
    reject = decision(manifest, 'REJECT', side=side, feedbackInputPath=feedback_path)
    result = pair.submit_pair_decision(manifest, reject)
    assert result['status'] == 'SUPERSEDED' and result['rerun']['side'] == side
    assert not list(Path(green['projectRoot']).glob('.ai-sow/generations/*'))
    assert not list(Path(brown['projectRoot']).glob('.ai-sow/generations/*'))
    assert pair.orchestrator.status(Path(selected['projectRoot']))['state']['runId'] != manifest[side.lower().replace('field','')]['runId']
    if side == 'BROWNFIELD':
        assert pair.orchestrator.status(Path(green['projectRoot']))['state']['runId'] == manifest['green']['runId']
    else:
        assert pair.orchestrator.status(Path(brown['projectRoot']))['outcome'] != 'ACTIVE'
    with pytest.raises(ValueError): pair.submit_pair_decision(manifest, decision(manifest))
    # Finish the actual newly started run, then the same persisted decision continues.
    from test_e2e import drive_result_host
    drive_result_host(Path(selected['projectRoot']), pair.orchestrator.run_mode(Path(selected['projectRoot']), 'resume'))
    result = pair.submit_pair_decision(manifest, reject)
    if side == 'GREENFIELD':
        assert result['rerun']['side'] == 'BROWNFIELD'
        drive_result_host(Path(brown['projectRoot']), pair.orchestrator.run_mode(Path(brown['projectRoot']), 'resume'))
        result = pair.submit_pair_decision(manifest, reject)
    assert result['nextPairManifestPath']
    fresh = json.loads(Path(result['nextPairManifestPath']).read_bytes())
    assert fresh['status'] == 'READY_FOR_REVIEW' and decision(fresh) != decision(manifest)
    assert fresh['green']['runId'] != manifest['green']['runId'] if side == 'GREENFIELD' else fresh['green'] == manifest['green']


@pytest.mark.integration
def test_pair_review_readiness_rejects_unsealed_production_runs(tmp_path):
    pair = harness()
    sys.path.insert(0, str(SKILL / 'tests'))
    from test_contracts import valid_run_budget_policy
    descriptors = []
    for name in ('green', 'brown'):
        root = tmp_path / name
        write(root / 'request.json', input_project(root, 'GREENFIELD'))
        write(root / 'budget.json', valid_run_budget_policy())
        result = pair.orchestrator.run_mode(root, 'start', request='request.json', budget_policy='budget.json')
        assert result['outcome'] == 'ACTIVE'
        descriptors.append({'projectRoot': str(root), 'requestPath': 'request.json', 'budgetPolicyPath': 'budget.json'})
    with pytest.raises(ValueError, match='AWAITING_FINAL_REVIEW'):
        pair.prepare_pair_review(*descriptors)
    assert not list((tmp_path / 'green').glob('pair-reviews/*'))


def test_one_pair_decision_requires_exact_manifest_hash_and_valid_result_state():
    pair = harness()
    for value in ({'decision': 'APPROVE'}, {'decision': 'REJECT', 'side': 'BROWNFIELD', 'feedbackInputPath': 'pair-feedback/request-' + 'c' * 64 + '.json'}):
        valid = {'contract': 'ai-sow-pair-decision-v1', 'pairReviewManifestSha256': 'a' * 64, **value}
        pair._validate(valid, 'pair-decision')
        with pytest.raises(ValueError): pair._validate({**valid, 'pairReviewManifestSha256': 'stale'}, 'pair-decision')
    result = {'contract': 'ai-sow-pair-result-v1', 'status': 'PUBLISHED', 'pairReviewManifestSha256': 'a' * 64,
        'pairDecisionSha256': 'b' * 64, 'greenGeneration': None, 'brownGeneration': None,
        'rerun': None, 'nextPairManifestPath': None}
    with pytest.raises(ValueError): pair._validate(result, 'pair-result')


def test_pair_rejection_rerun_feedback_must_be_complete_and_bind_frozen_prior(tmp_path):
    pair = harness(); root = tmp_path / 'brown'; source = template(root)
    prior = tmp_path / 'green.xlsx'; shutil.copyfile(SKILL / 'assets/sow-template.xlsx', prior)
    pair.instantiate_brownfield_request(source, prior, root / 'request.json')
    manifest = {'brown': {'projectRoot': str(root)}, 'green': {'workbookSha256': '0' * 64}}
    reject = {'side': 'BROWNFIELD', 'feedbackInputPath': freeze_feedback(root, json.loads((root / 'request.json').read_bytes()))}
    with pytest.raises(ValueError, match='frozen Greenfield'): pair._feedback(manifest, reject, 'a' * 64)
    partial = freeze_feedback(root, {'project': {'name': 'partial'}})
    with pytest.raises(ValueError, match='complete v3'):
        pair._feedback(manifest, {**reject, 'feedbackInputPath': partial}, 'a' * 64)


def test_pair_rejection_rerun_rejects_changed_frozen_feedback_and_unhashed_path(tmp_path):
    pair = harness(); root = tmp_path / 'green'
    request = input_project(root, 'GREENFIELD')
    path = freeze_feedback(root, request)
    manifest = {'green': {'projectRoot': str(root)}}
    reject = {'side': 'GREENFIELD', 'feedbackInputPath': path}
    digest = 'a' * 64
    original = (root / path).read_bytes()
    assert pair._feedback(manifest, reject, digest) == path
    changed = json.loads(original); changed['project']['name'] = 'another valid request'
    write(root / path, changed)
    with pytest.raises(ValueError, match='feedback.*hash'):
        pair._feedback(manifest, reject, digest)
    (root / path).write_bytes(original)
    assert pair._feedback(manifest, reject, digest) == path
    with pytest.raises(ValueError, match='feedback.*hash'):
        pair._feedback(manifest, {**reject, 'feedbackInputPath': 'feedback.json'}, digest)


@pytest.mark.e2e
@pytest.mark.parametrize('window', ['before_result', 'after_result'])
def test_pair_rejection_rerun_feedback_binding_survives_first_result_crash(real_pair, tmp_path, monkeypatch, window):
    pair, green, brown = pair_copy(real_pair, tmp_path)
    manifest = pair.prepare_pair_review(green, brown)
    feedback_path = freeze_feedback(Path(brown['projectRoot']), json.loads((Path(brown['projectRoot']) / 'request.json').read_bytes()))
    reject = decision(manifest, 'REJECT', side='BROWNFIELD', feedbackInputPath=feedback_path)
    original_write = pair._write_result
    def crash(current, result):
        if result['status'] == 'SUPERSEDED' and result['pairDecisionSha256']:
            if window == 'after_result': original_write(current, result)
            raise RuntimeError('first result crash')
        return original_write(current, result)
    with monkeypatch.context() as patch:
        patch.setattr(pair, '_write_result', crash)
        with pytest.raises(RuntimeError, match='first result crash'):
            pair.submit_pair_decision(manifest, reject)
    frozen = pair._feedback(manifest, reject, sha256_bytes(canonical_json_bytes(reject)))
    path = Path(brown['projectRoot']) / frozen
    value = json.loads(path.read_bytes()); value['project']['name'] = 'substituted after decision'
    write(path, value)
    digest = sha256_bytes(canonical_json_bytes(reject))
    replacement = freeze_feedback(Path(brown['projectRoot']), value)
    write(Path(brown['projectRoot']) / f'pair-feedback/{digest}/binding.json',
          {'path': replacement, 'sha256': sha256_bytes(canonical_json_bytes(value))})
    with pytest.raises(ValueError, match='feedback.*hash'):
        pair.submit_pair_decision(manifest, reject)
    for side in ('green', 'brown'):
        assert pair.orchestrator.status(Path(manifest[side]['projectRoot']))['state']['runId'] == manifest[side]['runId']
        assert not (Path(manifest[side]['projectRoot']) / '.ai-sow/current.json').exists()


def test_pair_rejection_rerun_decision_pins_feedback_despite_replaced_binding(tmp_path):
    pair = harness(); root = tmp_path / 'green'
    value = input_project(root, 'GREENFIELD'); original = canonical_json_bytes(value)
    path = f'pair-feedback/request-{sha256_bytes(original)}.json'
    ProjectFiles.open(root).publish_new(path, original)
    manifest = {'green': {'projectRoot': str(root)}}
    reject = {'side': 'GREENFIELD', 'feedbackInputPath': path}; digest = 'a' * 64
    pair._feedback(manifest, reject, digest)
    changed = copy.deepcopy(value); changed['project']['name'] = 'replacement'; raw = canonical_json_bytes(changed)
    replacement = f'pair-feedback/{digest}/request-{sha256_bytes(raw)}.json'
    write(root / replacement, changed)
    write(root / f'pair-feedback/{digest}/binding.json', {'path': replacement, 'sha256': sha256_bytes(raw)})
    # An unanchored lookup record cannot redirect the decision's selected request.
    actual = pair._feedback(manifest, reject, digest)
    assert (root / actual).read_bytes() == original
    write(root / path, changed)
    with pytest.raises(ValueError, match='feedback.*hash'):
        pair._feedback(manifest, reject, digest)
