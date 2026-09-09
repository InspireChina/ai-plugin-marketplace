"""Direct P00 contract fixture. Does not invoke or simulate ingest/apply."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil

PLUGIN = Path(__file__).resolve().parents[2]
FIXTURES = PLUGIN / "tests/fixtures"


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass
class Case:
    project: Path
    request_id: str
    candidate_path: Path
    template_hash: str
    ids: dict[str, str]

    def file(self, name):
        return self.candidate_path.parent / name


def build_contract_case(project):
    project.mkdir(parents=True, exist_ok=True)
    source = FIXTURES / "generate"
    ids = read_json(source / "ids.json")
    root = project / ".ai-sow-lite"
    template_hash = hashlib.sha256((PLUGIN / "assets/sow-template.xlsx").read_bytes()).hexdigest()
    target = root / "template" / template_hash / "sow-template.xlsx"
    target.parent.mkdir(parents=True)
    shutil.copyfile(PLUGIN / "assets/sow-template.xlsx", target)
    work = root / "work/generate" / ids["request"]
    work.mkdir(parents=True)
    for name in ["model.json", "pending-items.json", "decisions.json", "candidate.json"]:
        shutil.copyfile(source / name, work / name)
    inputs = []
    for alias, filename, role, use in [("P1", "prd.md", "prd", "to-be-scope"),
                                      ("H1", "hld.md", "hld", "to-be-architecture"),
                                      ("A1", "answers.md", "answer", "to-be-scope")]:
        path = root / "inputs/originals" / ids[alias] / filename
        path.parent.mkdir(parents=True)
        shutil.copyfile(source / filename, path)
        inputs.append(dict(input_version_id=ids[alias], input_id=ids[alias + '-logical'],
                           content_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
                           relative_path=path.relative_to(project).as_posix(), format="text", encoding="utf-8",
                           material_types=[role], uses=[use], use_regions=[]))
    write_json(root / "inputs/index.json", {"schema_version": "1.0", "items": inputs})
    write_json(root / "project.json", dict(schema_version="1.0", project_id=ids["project"],
                                          project_type="new", template_hash=template_hash))
    analysis_path = root / "analysis/topics" / ids["topic-version"] / "analysis.json"
    write_json(analysis_path, read_json(source / "analysis.json"))
    return Case(project, ids["request"], work / "candidate.json", template_hash, ids)


def seed_applied_history(case):
    version = '00000000-0000-4000-8000-000000006001'
    old_task = '00000000-0000-4000-8000-000000006002'
    root = case.project / '.ai-sow-lite'
    version_dir = root / 'versions' / version
    model = read_json(case.file('model.json'))
    model['tasks'][0]['id'] = old_task
    model_path = version_dir / 'model.json'
    write_json(model_path, model)
    def ref(path):
        return dict(path=path.relative_to(case.project).as_posix(), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    # Additional manifest file refs are only structural fixture records; no Excel is delivered.
    model_ref = ref(model_path)
    manifest = dict(schema_version='1.0', version_id=version, request_id=case.request_id,
                    base_version_id=None, intent_digest='json-v1:'+'0'*64, candidate_digest='json-v1:'+'0'*64,
                    files=[model_ref], input_version_ids=[], topic_version_ids=[], evidence_ids=[], dependencies=[],
                    template_hash=case.template_hash, projection_version='lite-projection-v1',
                    office_identity='contract-fixture-no-office-execution', verification_ref=model_ref)
    manifest_path = version_dir / 'manifest.json'
    write_json(manifest_path, manifest)
    write_json(root / 'current.json', dict(version_id=version, manifest_hash=ref(manifest_path)['sha256']))
    return version, old_task


def seed_lineage_versions(case, versions):
    """Hash-bound input snapshots for lineage unit tests; does not run apply."""
    previous = None
    previous_ref = None
    for version, model in versions:
        directory = case.project / '.ai-sow-lite/versions' / version
        model_path = directory / 'model.json'
        write_json(model_path, model)
        model_ref = dict(path=model_path.relative_to(case.project).as_posix(),
                         sha256=hashlib.sha256(model_path.read_bytes()).hexdigest())
        manifest = dict(schema_version='1.0', version_id=version, request_id=case.request_id,
                        base_version_id=previous, intent_digest='json-v1:'+'0'*64, candidate_digest='json-v1:'+'0'*64,
                        files=[model_ref], input_version_ids=[], topic_version_ids=[], evidence_ids=[],
                        dependencies=[previous_ref] if previous_ref else [], template_hash=case.template_hash,
                        projection_version='lite-projection-v1', office_identity='contract-fixture-no-office-execution',
                        verification_ref=model_ref)
        path = directory / 'manifest.json'
        write_json(path, manifest)
        previous_ref = dict(path=path.relative_to(case.project).as_posix(), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        previous = version
    write_json(case.project / '.ai-sow-lite/current.json', dict(version_id=previous, manifest_hash=previous_ref['sha256']))


def build_ingested_case(project):
    """Use genuine public CLI sources/analysis; only business drafts remain fixtures."""
    from .cli import run_request
    from uuid import uuid4
    source = FIXTURES / 'generate'
    ids = read_json(source / 'ids.json')
    request = str(uuid4())
    payload = dict(kind='sources', entrypoint='generate', project_type='new', sources=[
        dict(source_path=str(source / filename), input_id=None, material_types=[role], uses=[use], use_regions=[])
        for filename, role, use in [('prd.md', 'prd', 'to-be-scope'), ('hld.md', 'hld', 'to-be-architecture'),
                                    ('answers.md', 'answer', 'to-be-scope')]])
    result = run_request(project, request, 'ingest', payload)
    assert result['ok'], result
    refs = result['result']['input_refs']
    replacements = {ids[k]: ref['input_version_id'] for k, ref in zip(['P1', 'H1', 'A1'], refs)}
    replacements[ids['request']] = request
    def translate(value):
        if isinstance(value, str):
            for before, after in replacements.items():
                value = value.replace(before, after)
            return value
        if isinstance(value, dict):
            return {key: translate(item) for key, item in value.items()}
        if isinstance(value, list):
            return [translate(item) for item in value]
        return value
    work = project / '.ai-sow-lite/work/generate' / request
    for name in ['model.json', 'pending-items.json', 'decisions.json', 'candidate.json', 'analysis.json']:
        write_json(work / name, translate(read_json(source / name)))
    # Resolve real locators through inspect and keep the actual returned excerpt hashes.
    analysis = read_json(work / 'analysis.json')
    for owner in [*analysis['evidence'], *analysis['topics']]:
        for ref in owner.get('source_refs', owner.get('covered_regions', [])):
            observed = run_request(project, request, 'inspect', dict(view='regions', selector=dict(
                input_version_id=ref['input_version_id'], locator=ref['locator']), limit=100, cursor=None))
            assert observed['ok'], observed
            ref['excerpt_hash'] = observed['result']['coverage']['excerpt_hash']
    write_json(work / 'analysis.json', analysis)
    registered = run_request(project, request, 'ingest', dict(kind='analysis', entrypoint='generate',
                            analysis_path=(work / 'analysis.json').relative_to(project).as_posix()))
    assert registered['ok'], registered
    candidate = read_json(work / 'candidate.json')
    candidate['input_version_ids'] = [ref['input_version_id'] for ref in refs]
    candidate['evidence_ids'] = registered['result']['evidence_ids']
    candidate['topic_version_ids'] = registered['result']['topic_version_ids']
    write_json(work / 'candidate.json', candidate)
    return Case(project, request, work / 'candidate.json', candidate['template_hash'], translate(ids))


def storage_package(project, request_id=None, expected_current=None):
    """Controlled storage contract only. sow.xlsx is deliberately not an Office workbook."""
    from uuid import uuid4
    from ai_sow_lite.contracts import canonical_json_bytes, semantic_digest
    from ai_sow_lite.project import initialize, ensure_request
    request_id = request_id or str(uuid4())
    entrypoint = 'clarify' if expected_current else 'generate'
    identity = initialize(project, 'new', PLUGIN / 'assets/sow-template.xlsx')
    ensure_request(project, request_id, entrypoint)
    version = str(uuid4())
    directory = project / f'.ai-sow-lite/work/{entrypoint}/{request_id}/package-{version}'
    directory.mkdir()
    contents = {'model.json': b'{"controlled":"model"}', 'pending-items.json': b'{}', 'decisions.json': b'{}',
                'projection.json': b'{}', 'sow.xlsx': b'NOT AN OFFICE WORKBOOK; STORAGE UNIT ONLY',
                'summary.md': b'controlled summary', 'pending-items.md': b'controlled pending',
                'verification.json': b'{"unit":"storage-only"}'}
    files = []
    for name, raw in contents.items():
        (directory / name).write_bytes(raw)
        files.append(dict(path=f'.ai-sow-lite/versions/{version}/{name}', sha256=hashlib.sha256(raw).hexdigest()))
    digest = semantic_digest(dict(request_id=request_id, scope='storage-unit'))
    dependencies = [] if expected_current is None else [dict(
        path=f".ai-sow-lite/versions/{expected_current['version_id']}/manifest.json", sha256=expected_current['manifest_hash'])]
    manifest = dict(schema_version='1.0', version_id=version, request_id=request_id,
                    base_version_id=expected_current['version_id'] if expected_current else None,
                    intent_digest=digest, candidate_digest=digest, files=files,
                    input_version_ids=[], topic_version_ids=[], evidence_ids=[], dependencies=dependencies,
                    template_hash=identity['template_hash'], projection_version='lite-projection-v1',
                    office_identity='unit-storage-no-office', verification_ref=files[-1])
    return dict(project=project, request_id=request_id, entrypoint=entrypoint, prepared_directory=directory,
                manifest=manifest, expected_current=expected_current)
