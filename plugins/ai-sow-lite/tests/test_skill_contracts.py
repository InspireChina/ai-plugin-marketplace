"""Discovery and authoring surface contracts; these do not prove SOW semantics."""
import hashlib
import json
from pathlib import Path
import re
import tomllib
from urllib.parse import unquote, urlsplit

import pytest


PLUGIN = Path(__file__).resolve().parents[1]
SKILL = PLUGIN / "skills/generate/SKILL.md"


def required_text(path):
    assert path.is_file(), f"Missing discovery/reference file: {path.relative_to(PLUGIN)}"
    return path.read_text(encoding="utf-8")


def test_generate_is_discoverable_without_explicit_only_policy():
    text = required_text(SKILL)
    assert text.startswith("---\n")
    frontmatter = text.split("---", 2)[1]
    assert re.search(r"^name: generate$", frontmatter, re.M)
    assert re.search(r"^description: .+\S", frontmatter, re.M)
    assert not re.search(r"disable-model-invocation:\s*true", frontmatter)
    assert not re.search(r"allow_implicit_invocation:\s*false", text)
    assert sorted(p.parent.name for p in (PLUGIN / "skills").glob("*/SKILL.md")) == ["generate"]


@pytest.mark.parametrize("host", ["codex", "claude"])
def test_development_manifest_discovers_only_implemented_skills(host):
    manifest = json.loads(required_text(PLUGIN / f".{host}-plugin/plugin.json"))
    assert manifest["name"] == PLUGIN.name
    pep440 = tomllib.loads((PLUGIN / "pyproject.toml").read_text())["project"]["version"]
    assert manifest["version"].replace("-alpha.", "a") == pep440
    assert manifest["description"].strip()
    skill_dir = (PLUGIN / manifest.get("skills", "./skills")).resolve()
    assert skill_dir.is_relative_to(PLUGIN)
    assert sorted(p.parent.name for p in skill_dir.glob("*/SKILL.md")) == ["generate"]
    assert not {"hooks", "mcpServers", "apps", "commands", "agents"} & manifest.keys()


def test_host_manifests_agree_on_identity_and_description():
    manifests = [json.loads(required_text(PLUGIN / f".{host}-plugin/plugin.json"))
                 for host in ("codex", "claude")]
    for key in ("name", "version", "description"):
        assert manifests[0][key] == manifests[1][key]


@pytest.mark.parametrize("relative", [
    "skills/generate/SKILL.md", "references/generate-slices.md",
    "references/generate-authoring.md", "references/input-analysis.md",
    "references/tools.md", "README.md",
])
def test_relative_reference_links_resolve_inside_plugin(relative):
    path = PLUGIN / relative
    text = required_text(path)
    links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", text)
    assert links, f"No reachable references in {relative}"
    for link in links:
        parsed = urlsplit(link)
        if parsed.scheme or not parsed.path:
            continue
        target = (path.parent / unquote(parsed.path)).resolve()
        assert target.is_relative_to(PLUGIN), (relative, link)
        assert target.exists(), (relative, link)


def test_runtime_instructions_route_to_their_own_executable_files():
    text = "\n".join(required_text(path) for path in (
        SKILL, PLUGIN / "references/generate-authoring.md", PLUGIN / "references/generate-slices.md"))
    targets = re.findall(r"<plugin-root>/(scripts/[\w./-]+)", text)
    assert {"scripts/lite.py", "scripts/bootstrap.sh", "scripts/bootstrap.ps1"} <= set(targets)
    for target in targets:
        assert (PLUGIN / target).is_file(), target
    assert not re.search(r"(?:/Users/|[A-Z]:\\Users\\|plugins/ai-sow/|\.superpowers/)", text)
    assert not re.search(r"\]\([^)]*(?:docs/design|tests/fixtures)[^)]*\)", text)
    assert not re.search(r'"operation"\s*:\s*"(?:next|submit)"|--(?:next|submit)\b', text)
    # A lint for accidental affirmative gates, not a test of an agent's judgment.
    assert not re.search(r"(?:必须|先|等待)用户(?:批准|审批)(?:骨架|初稿|candidate|packet)", text)


def test_readme_links_to_actual_validation_record():
    text = required_text(PLUGIN / "README.md")
    links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", text)
    assert "docs/validation/I2-generate.md" in links


@pytest.mark.parametrize("file_format", ["text", "xlsx"])
def test_authoring_example_maps_real_region_and_standard_response_fields(tmp_path, file_format):
    """Execute the guide against existing CLI response fixtures, not keyword checks."""
    from .test_inputs import ingest, inspect
    from .test_xlsx_inputs import ingest_history, region

    guide = required_text(PLUGIN / "references/generate-authoring.md")
    snippets = re.findall(r"```python\n(.*?)\n```", guide, re.S)
    assert len(snippets) == 1, "Missing executable response-to-reference mapping example"
    if file_format == "text":
        raw = b"mapping\r\n"
        project, request, _, registered = ingest(tmp_path, raw)
        entry = registered["input_refs"][0]
        locator = dict(kind="text_lines", start_line=1, end_line=1)
        response = inspect(project, request, "regions", dict(
            input_version_id=entry["input_version_id"], locator=locator))
        excerpt_hash = hashlib.sha256(raw).hexdigest()
    else:
        project, request, entry, directory_reading = ingest_history(tmp_path)
        response = region(project, request, entry, directory_reading)
        coverage = response["result"]["coverage"]
        reading = json.loads((project / coverage["reading_ref"]["path"]).read_text())
        locator = dict(kind="xlsx_range", sheet="历史范围", range="A1:C4", read_id=reading["read_id"])
        assert locator["read_id"] != directory_reading["read_id"]
        excerpt_hash = hashlib.sha256((project / coverage["excerpt_ref"]["path"]).read_bytes()).hexdigest()
    assert response["ok"], response
    standards = inspect(project, request, "standards")
    assert standards["ok"], standards
    row = standards["result"]["items"][0]
    context = {"region_result": response["result"], "standard_row": row}
    exec(compile(snippets[0], "generate-authoring.md", "exec"), context)
    assert context["source_ref"] == dict(
        input_version_id=entry["input_version_id"], locator=locator, excerpt_hash=excerpt_hash)
    assert context["standard_id"] == row["工作类型 ID"]
    assert context["work_type_name"] == row["工作类型"]


def test_authoring_observation_recipe_executes_coarse_boundaries(tmp_path, capsys):
    """The published mark example and boundary table must work in the real recorder."""
    from uuid import uuid4
    from ai_sow_lite import telemetry

    guide = required_text(PLUGIN / 'references/generate-authoring.md')
    example = re.search(r'<!-- observation-mark-example -->\s*```json\n(.*?)\n```', guide, re.S)
    assert example, 'The required best-effort observation recipe needs a runnable mark envelope'
    ids = {key: str(uuid4()) for key in ('request-id', 'execution-id', 'activity-id')}
    raw = example[1]
    for key, value in ids.items(): raw = raw.replace('<'+key+'>', value)
    mark = json.loads(raw)
    rows = re.findall(r'^\|[^\n|]+\| `(\w+)` \| `(start/end|milestone)` \|', guide, re.M)
    assert dict(rows) == dict(request='start/end', input_analysis='start/end', outline='start/end',
                             generation='start/end', merge='start/end', export='start/end',
                             user_wait='start/end', useful_feedback='milestone', usable_file='milestone')
    project = tmp_path / 'project'; path = tmp_path / 'mark.json'
    for name, phases in rows:
        for phase in phases.split('/'):
            path.write_text(json.dumps(dict(mark, name=name, phase=phase)))
            assert telemetry.main(['--project', str(project), '--mark-file', str(path)]) == 0
            assert json.loads(capsys.readouterr().out)['recording'] == 'recorded'
    report = telemetry.build_report(project, ids['request-id'])
    assert report['event_count'] == 16
    assert not (project / '.ai-sow-lite/current.json').exists()
    assert all(m['value'] is None for m in report['metrics'] if m['name'] in ('total_tokens', 'model_duration_ns'))
