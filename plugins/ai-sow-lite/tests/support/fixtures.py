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
