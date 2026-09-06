"""Publication boundaries consume a real verified artifact, without re-rendering."""
import json
import shutil
import sys
from pathlib import Path
import pytest

TEST_LAYER='e2e'
ROOT=Path(__file__).parents[1]
for path in (ROOT/'scripts',ROOT/'tests',ROOT.parents[1]):sys.path.insert(0,str(path))
from test_artifact_lifecycle import verified_artifact
from contracts import canonical_json_bytes, sha256_bytes
from runtime.project_io import ProjectFiles
import generation_store
import orchestrator


def copied_artifact(verified_artifact,tmp_path):
    project,result,_=verified_artifact
    target=tmp_path/'project';shutil.copytree(project,target)
    return target,result,ProjectFiles.open(target)


def test_artifact_promotion_gate_is_byte_identical_self_contained_and_never_recalculates(verified_artifact,tmp_path,monkeypatch):
    import package_renderer
    project,result,files=copied_artifact(verified_artifact,tmp_path)
    raw=files.read_bytes(result['workbookPath'])
    def forbidden(*args,**kwargs):raise AssertionError('publication must never calculate/render')
    monkeypatch.setattr(package_renderer,'project_artifact',forbidden)
    monkeypatch.setattr(package_renderer,'calculate_artifact',forbidden)
    monkeypatch.setattr(package_renderer,'render_artifact',forbidden)
    published=orchestrator.approve(project,result['artifactManifestSha256'])
    assert published['outcome']=='PUBLISHED',published
    assert files.read_bytes(published['workbookPath'])==raw
    current=files.read_bytes('.ai-sow/current.json')
    assert orchestrator.approve(project,result['artifactManifestSha256'])['outcome']=='REUSED'
    assert files.read_bytes('.ai-sow/current.json')==current
    shutil.rmtree(project/'.ai-sow/work')
    shutil.rmtree(project/'.ai-sow/inputs')
    loaded=generation_store.load_current(files)
    assert files.read_bytes(loaded.workbook_path)==raw


def test_artifact_promotion_gate_rejects_stale_approval_and_preserves_current(verified_artifact,tmp_path):
    project,result,files=copied_artifact(verified_artifact,tmp_path)
    published=orchestrator.approve(project,result['artifactManifestSha256'])
    assert published['outcome']=='PUBLISHED'
    current=files.read_bytes('.ai-sow/current.json')
    approval=files.read_json(published['approvalPath']);approval['candidateSha256']='0'*64
    with pytest.raises(Exception):generation_store.promote(result['artifactManifestSha256'],approval,files=files)
    assert files.read_bytes('.ai-sow/current.json')==current


def test_artifact_promotion_gate_crash_before_current_swap_keeps_last_known_good(verified_artifact,tmp_path,monkeypatch):
    project,result,files=copied_artifact(verified_artifact,tmp_path)
    first=orchestrator.approve(project,result['artifactManifestSha256']);assert first['outcome']=='PUBLISHED'
    current=files.read_bytes('.ai-sow/current.json')
    approval=files.read_json(first['approvalPath']);approval['approvedAt']='2026-10-02T00:00:00Z'
    def crash(*args):raise RuntimeError('before current swap')
    monkeypatch.setattr(generation_store,'replace_current',crash)
    with pytest.raises(RuntimeError):generation_store.promote(result['artifactManifestSha256'],approval,files=files)
    assert files.read_bytes('.ai-sow/current.json')==current
    assert generation_store.load_current(files).generation_id==first['generationId']


def test_generation_repeated_bindings_must_match_portable_artifact(verified_artifact,tmp_path):
    project,result,files=copied_artifact(verified_artifact,tmp_path)
    assert orchestrator.approve(project,result['artifactManifestSha256'])['outcome']=='PUBLISHED'
    current=files.read_json('.ai-sow/current.json')
    path=current['generationManifestPath']; original=files.read_bytes(path)
    manifest=json.loads(original)
    # Rehash the mutable pointer so rejection must come from the deep cross-binding.
    for field in ('rendererSha256','runId','inputRevisionSha256'):
        bad={**manifest,field:('run-forged' if field=='runId' else '0'*64)}
        raw=canonical_json_bytes(bad)
        (project/path).write_bytes(raw)
        files.write_atomic('.ai-sow/current.json',canonical_json_bytes({**current,'generationManifestSha256':sha256_bytes(raw)}))
        with pytest.raises(Exception,match='generation.*artifact'):
            generation_store.load_current(files)
    (project/path).write_bytes(original)
    files.write_atomic('.ai-sow/current.json',canonical_json_bytes(current))
    assert generation_store.load_current(files) is not None


def test_pair_publication_recovers_generation_before_current_swap(verified_artifact, tmp_path, monkeypatch):
    project, result, files = copied_artifact(verified_artifact, tmp_path)
    manifest = files.read_json(result['artifactManifestPath'])
    approval = {key: manifest[key] for key in ('runId', 'candidateSha256', 'sourceManifestSha256',
        'reviewDecisionSha256', 'templateSha256', 'effectivePolicyDecisionSha256')}
    approval.update(contract='ai-sow-approval-v1', decision='APPROVE', approvedAt='2026-09-06T00:00:00Z',
        artifactManifestSha256=result['artifactManifestSha256'], pairDecisionSha256='a' * 64)
    def crash(*args): raise RuntimeError('pair current swap crash')
    with monkeypatch.context() as patch:
        patch.setattr(generation_store, 'replace_current', crash)
        with pytest.raises(RuntimeError, match='pair current swap'):
            generation_store.promote(result['artifactManifestSha256'], approval, files=files)
    assert len(list((project / '.ai-sow/generations').iterdir())) == 1
    # The decision/artifact identity, not a caller's regenerated timestamp, is the key.
    approval['approvedAt'] = '2026-09-07T00:00:00Z'
    published = generation_store.promote(result['artifactManifestSha256'], approval, files=files)
    assert published.outcome == 'REUSED'
    assert len(list((project / '.ai-sow/generations').iterdir())) == 1
    current = generation_store.load_current(files)
    generated = files.read_json(current.manifest_path)
    assert generated['pairDecisionSha256'] == 'a' * 64
    raw = canonical_json_bytes({**generated, 'pairDecisionSha256': 'b' * 64})
    (project / current.manifest_path).write_bytes(raw)
    pointer = files.read_json('.ai-sow/current.json'); pointer['generationManifestSha256'] = sha256_bytes(raw)
    files.write_atomic('.ai-sow/current.json', canonical_json_bytes(pointer))
    with pytest.raises(ValueError, match='pair decision'):
        generation_store.load_current(files)
