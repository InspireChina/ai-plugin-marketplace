"""Discovery and authoring surface contracts; these do not prove SOW semantics."""
import hashlib
import json
from pathlib import Path
import re
import tomllib
from urllib.parse import unquote, urlsplit

import pytest

from .support.clarify import delivered_baseline, clarify_case


PLUGIN = Path(__file__).resolve().parents[1]
SKILL = PLUGIN / "skills/generate/SKILL.md"


def required_text(path):
    assert path.is_file(), f"Missing discovery/reference file: {path.relative_to(PLUGIN)}"
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ["generate", "clarify"])
def test_skill_is_discoverable_without_explicit_only_policy(name):
    text = required_text(PLUGIN / f"skills/{name}/SKILL.md")
    assert text.startswith("---\n")
    frontmatter = text.split("---", 2)[1]
    assert re.search(rf"^name: {name}$", frontmatter, re.M)
    assert re.search(r"^description: .+\S", frontmatter, re.M)
    assert not re.search(r"disable-model-invocation:\s*true", frontmatter)
    assert not re.search(r"allow_implicit_invocation:\s*false", text)
    assert sorted(p.parent.name for p in (PLUGIN / "skills").glob("*/SKILL.md")) == ["clarify", "generate"]


@pytest.mark.parametrize("host", ["codex", "claude"])
def test_development_manifest_discovers_only_implemented_skills(host):
    manifest = json.loads(required_text(PLUGIN / f".{host}-plugin/plugin.json"))
    assert manifest["name"] == PLUGIN.name
    pep440 = tomllib.loads((PLUGIN / "pyproject.toml").read_text())["project"]["version"]
    assert manifest["version"].replace("-alpha.", "a") == pep440
    assert manifest["description"].strip()
    skill_dir = (PLUGIN / manifest.get("skills", "./skills")).resolve()
    assert skill_dir.is_relative_to(PLUGIN)
    assert sorted(p.parent.name for p in skill_dir.glob("*/SKILL.md")) == ["clarify", "generate"]
    assert not {"hooks", "mcpServers", "apps", "commands", "agents"} & manifest.keys()


def test_host_manifests_agree_on_identity_and_description():
    manifests = [json.loads(required_text(PLUGIN / f".{host}-plugin/plugin.json"))
                 for host in ("codex", "claude")]
    for key in ("name", "version", "description"):
        assert manifests[0][key] == manifests[1][key]


@pytest.mark.parametrize("relative", ["README.md", *sorted(
    str(path.relative_to(PLUGIN)) for pattern in ("skills/*/SKILL.md", "references/*.md")
    for path in PLUGIN.glob(pattern)
)])
def test_relative_reference_links_resolve_inside_plugin(relative):
    path = PLUGIN / relative
    text = required_text(path)
    links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", text)
    assert links, f"No reachable references in {relative}"
    for link in links:
        parsed = urlsplit(link)
        if parsed.scheme:
            continue
        target = (path.parent / unquote(parsed.path)).resolve() if parsed.path else path.resolve()
        assert target.is_relative_to(PLUGIN), (relative, link)
        assert target.exists(), (relative, link)
        if parsed.fragment and target.suffix == ".md":
            body = required_text(target)
            # Check the sections agents are told to read, not specific prose or headings.
            headings = re.findall(r"^#{1,6}\s+(.+?)\s*#*\s*$", body, re.M)
            anchors = {re.sub(r"[^\w\s-]", "", heading.lower()).replace(" ", "-")
                       for heading in headings}
            anchors.update(re.findall(r'<a\s+(?:id|name)="([^"]+)"', body))
            assert unquote(parsed.fragment) in anchors, (relative, link)


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
    assert "docs/validation/README.md" in links


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
    assert context["evidence_source_ref"] == dict(
        input_version_id=entry["input_version_id"], locator=locator, excerpt_hash=excerpt_hash)
    from ai_sow_lite.authoring import source_ref
    assert source_ref(response["result"]) == context["evidence_source_ref"]
    assert context["standard_id"] == row["工作类型 ID"]
    assert context["work_type_name"] == row["工作类型"]

    from ai_sow_lite.authoring import Client
    source_spec=dict(source_path=str(project/entry['relative_path']),input_id=entry['input_id'],
                     material_types=entry['material_types'],uses=entry['uses'],use_regions=entry['use_regions'])
    usage_guide=required_text(PLUGIN/'references/python-client.md')
    example=re.search(r'<!-- source-use-region-example -->\s*```python\n(.*?)\n```',usage_guide,re.S)
    assert example, 'Missing executable existing-ingest use-region example'
    example_context=dict(client=Client(project,request,'generate'),registered_source=entry,
                         source_spec=source_spec,selected_region_results=[response['result']],
                         chosen_material_type=entry['material_types'][0],chosen_use=entry['uses'][0],
                         project_type='new' if file_format=='text' else 'existing')
    exec(compile(example[1],'python-client.md','exec'),example_context)
    actual=example_context['registered']['input_refs'][0]
    assert actual['input_id']==entry['input_id'] and actual['input_version_id']==entry['input_version_id']
    assert example_context['region_entry']==dict(material_type=entry['material_types'][0],use=entry['uses'][0],locators=[locator])


@pytest.mark.parametrize('reference, expected_activities, event_count', [
    ('generate-authoring.md', ['input_analysis', 'outline', 'generation', 'merge', 'export', 'user_wait'], 16),
    ('clarify-changes.md', ['input_analysis', 'design_discussion', 'user_wait', 'export'], 12),
])
def test_authoring_observation_recipe_executes_coarse_boundaries(tmp_path, capsys, reference,
                                                               expected_activities, event_count):
    """Changing detailed activities must not split the guide's root request interval."""
    from datetime import datetime, timedelta
    from uuid import uuid4
    from ai_sow_lite import telemetry

    guide = required_text(PLUGIN / 'references' / reference)
    # Clarify links to this shared recorder envelope; consume it for both recipes.
    envelope = required_text(PLUGIN / 'references/generate-authoring.md')
    example = re.search(r'<!-- observation-mark-example -->\s*```json\n(.*?)\n```', envelope, re.S)
    assert example, 'The required best-effort observation recipe needs a runnable mark envelope'
    ids = {key: str(uuid4()) for key in ('request-id', 'execution-id')}
    activities = {name: str(uuid4()) for name in expected_activities}
    slices = [str(uuid4()), str(uuid4())]
    rows = re.findall(r'^\|[^\n|]+\| `(\w+)` \| `(start/end|milestone)` \|', guide, re.M)
    assert dict(rows) == dict(request='start/end', useful_feedback='milestone', usable_file='milestone',
                             **{name: 'start/end' for name in expected_activities})
    project = tmp_path / 'project'; path = tmp_path / 'mark.json'

    def record(name, phase, activity, slice_id):
        raw = example[1]
        for key, value in dict(ids, **{'activity-id': activity, 'slice-id': slice_id}).items():
            raw = raw.replace('<'+key+'>', value)
        mark = json.loads(raw)
        mark.update(name=name, phase=phase)
        if name != 'request':
            mark.update(activity_ids=[activity], slice_ids=[slice_id])
        path.write_text(json.dumps(mark), encoding='utf-8')
        assert telemetry.main(['--project', str(project), '--mark-file', str(path)]) == 0
        assert json.loads(capsys.readouterr().out)['recording'] == 'recorded'

    # The current activity/slice changes between real recorder calls, as in a request.
    record('request', 'start', activities['input_analysis'], slices[0])
    for name, phases in rows:
        if name == 'request':
            continue
        for phase in phases.split('/'):
            record(name, phase, activities.get(name, activities['export']), slices[0])
    record('request', 'end', activities['export'], slices[1])
    report = telemetry.build_report(project, ids['request-id'])
    wall = next(m for m in report['metrics'] if m['name'] == 'request_wall_ns')
    assert wall['value'] is not None, (wall, report['diagnostics'])
    assert wall['value'] > 0 and wall['basis']['kind'] == 'utc_observed_interval'
    assert 'LIFECYCLE_INCOMPLETE' not in report['diagnostics']
    events = [json.loads(line) for file in (project / '.ai-sow-lite/telemetry' / ids['request-id']).glob(
        'events/*/*.jsonl') for line in file.read_text(encoding='utf-8').splitlines()]
    roots = {e['data']['phase']: e for e in events if e['data']['name'] == 'request'}
    assert set(roots) == {'start', 'end'}
    assert all(e['activity_ids'] == e['slice_ids'] == [] for e in roots.values())
    assert {e['execution_id'] for e in events} == {ids['execution-id']}
    elapsed = datetime.fromisoformat(roots['end']['observed_at']) - datetime.fromisoformat(roots['start']['observed_at'])
    assert wall['value'] == (elapsed // timedelta(microseconds=1)) * 1000
    spans = {m['scope']['id']: m for m in report['metrics'] if m['name'] == 'observed_wall_ns'}
    for event in events:
        name = event['data']['name']
        if name in activities and event['data']['phase'] == 'start':
            assert event['activity_ids'] == [activities[name]] and event['slice_ids'] == [slices[0]]
            assert spans[event['data']['span_id']]['value'] is not None
    assert report['event_count'] == event_count
    assert not (project / '.ai-sow-lite/current.json').exists()
    assert all(m['value'] is None for m in report['metrics'] if m['name'] in ('total_tokens', 'model_duration_ns'))


def test_clarify_confirmation_example_consumes_real_responses(clarify_case, monkeypatch, capsys):
    """The public snippet must bind the shown plan using actual registered answer bytes."""
    from .support.clarify import check_edits, edit_draft
    from .support.cli import run_request
    from .support.fixtures import write_json, read_json

    guide = required_text(PLUGIN / 'references/clarify-changes.md')
    snippets = re.findall(r'```python\n(.*?)\n```', guide, re.S)
    assert len(snippets) == 1
    case = clarify_case
    project, request = case['project'], case['request_id']
    checked = check_edits(case, edit_draft(case, [dict(op='replace', collection='stories',
        object_id=case['ids']['S-01'], field='notes', value='保留既有范围')]))
    assert checked['ok'], checked
    shown = project / checked['result']['plan_ref']['path']
    shown_bytes = shown.read_bytes()
    # The controller supplies this text only after the concrete review exists.
    assert (project / checked['result']['review_ref']['path']).is_file()
    answer = project / 'actual-execution-answer.md'
    answer.write_text('确认执行刚展示的备注修改，其他内容保持。\n', encoding='utf-8')
    registered = run_request(project, request, 'ingest', dict(kind='sources', entrypoint='clarify',
        project_type='new', sources=[dict(source_path=str(answer), input_id=None,
            material_types=['answer'], uses=['to-be-scope'], use_regions=[])]))
    assert registered['ok'], registered
    identity = registered['result']['input_refs'][0]['input_version_id']
    region = run_request(project, request, 'inspect', dict(view='regions', selector=dict(
        input_version_id=identity, locator=dict(kind='text_lines', start_line=1, end_line=1))))
    assert region['ok'], region
    replies = [project / name for name in ('check-reply.json', 'answer-reply.json', 'region-reply.json')]
    for path, reply in zip(replies, (checked, registered, region)):
        write_json(path, reply)
    monkeypatch.setattr('sys.argv', ['example', str(PLUGIN), str(project), *map(str, replies)])
    exec(compile(snippets[0], 'clarify-changes.md', 'exec'), {})
    confirmation_ref = json.loads(capsys.readouterr().out)
    confirmed = read_json(project / confirmation_ref['path'])
    assert confirmed['confirmation']['shown_plan_ref'] == checked['result']['plan_ref']
    assert confirmed['confirmation']['input_ref']['input_version_id'] == identity
    assert shown.read_bytes() == shown_bytes
    accepted = run_request(project, request, 'check', dict(
        candidate_path=checked['result']['candidate_ref']['path'],
        plan_path=confirmation_ref['path'], scope='full'))
    assert accepted['ok'] and accepted['result']['valid_for_render'], accepted
    assert read_json(project / '.ai-sow-lite/current.json') == case['current']


def test_xlsx_first_region_recipe_uses_directory_identity_then_actual_region(tmp_path):
    from ai_sow_lite.authoring import Client, source_ref
    from .test_xlsx_inputs import ingest_history

    project, request, entry, _ = ingest_history(tmp_path)
    client = Client(project, request, 'generate')
    directory = client.call('inspect', dict(view='regions', selector=dict(
        input_version_id=entry['input_version_id'])))
    guide = required_text(PLUGIN / 'references/tools.md')
    example = re.search(r'<!-- xlsx-region-request-example -->\s*```json\n(.*?)\n```', guide, re.S)
    assert example, 'Missing executable first-region request recipe'
    directory_id = directory['selected_version']['read_id']
    payload = json.loads(example[1].replace('<input-version-id>', entry['input_version_id'])
                         .replace('<directory-read-id>', directory_id))
    region = client.call('inspect', payload)
    ref = source_ref(region)
    assert ref['locator']['read_id'] != directory_id
    assert ref['locator']['sheet'] == '历史范围' and ref['locator']['range'] == 'A1:C8'
    assert ref['excerpt_hash'] == hashlib.sha256(
        (project / region['coverage']['excerpt_ref']['path']).read_bytes()).hexdigest()
    assert next(c for c in region['items'] if c['address'] == 'A2')['value']['value'] == '订单查询'


def test_python_client_setup_example_works_before_first_generate_ingest(tmp_path):
    from uuid import uuid4

    guide = required_text(PLUGIN / 'references/python-client.md')
    setup = re.findall(r'```python\n(.*?)\n```', guide, re.S)[0]
    project = tmp_path / 'new project'
    context = dict(plugin=PLUGIN, project=project, request_id=str(uuid4()),
                   entrypoint='generate', observation_context=None)
    exec(compile(setup, 'python-client.md', 'exec'), context)
    assert not project.exists()
    source = tmp_path / 'prd.md'
    source.write_text('本期交付资料查询。', encoding='utf-8')
    result = context['client'].call('ingest', dict(kind='sources', entrypoint='generate',
        project_type='new', sources=[dict(source_path=str(source), input_id=None,
            material_types=['PRD'], uses=['to-be'], use_regions=[])]))
    assert len(result['input_refs']) == 1
