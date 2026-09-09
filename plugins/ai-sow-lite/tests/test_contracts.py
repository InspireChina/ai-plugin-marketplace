"""P00/D02 contract behavior, with real source bytes and template identity."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from .support.fixtures import FIXTURES, read_json, write_json
from .support.cli import run_request


def check(case, scope="full", plan=None):
    from ai_sow_lite.validation import check_candidate
    return check_candidate(case.project, case.candidate_path, scope, plan)


def mutate(case, filename, change):
    value = read_json(case.file(filename))
    change(value)
    write_json(case.file(filename), value)


def pending(case, field, *, target=None, unestimated=False):
    return dict(id="00000000-0000-4000-8000-000000009999", revision=1,
                question="请补充本项尚缺的事实", targets=[dict(object_id=target or case.ids["T-01"], field=field)],
                evidence_refs=[case.ids["EV-P-B1"]], current_handling="保留本期范围；已有部分照常出稿。",
                unestimated_work=unestimated, status="open", resolution=None)


def add_pending(case, item):
    mutate(case, "pending-items.json", lambda value: value["items"].append(item))


@pytest.mark.parametrize("text", ['{"a":1,"a":2}', '{"a":{"b":1,"b":2}}',
                                  '{"a":NaN}', '{"a":Infinity}', '"\\ud800"', '1.5'])
def test_strict_json_rejects_ambiguous_or_non_contract_values(text):
    from ai_sow_lite.contracts import strict_json_loads
    with pytest.raises(ValueError):
        strict_json_loads(text)


def test_digest_vector_and_text_whitespace_are_exact():
    from ai_sow_lite.contracts import canonical_json_bytes, semantic_digest, strict_json_loads
    value = {"z": "中文", "a": [1, True, None]}
    expected = b'{"a":[1,true,null],"z":"\xe4\xb8\xad\xe6\x96\x87"}'
    assert canonical_json_bytes(value) == expected
    assert semantic_digest(value) == "json-v1:" + hashlib.sha256(expected).hexdigest()
    assert semantic_digest(value) == semantic_digest({"a": [1, True, None], "z": "中文"})
    assert semantic_digest(value) != semantic_digest({"z": "中文 ", "a": [1, True, None]})
    assert strict_json_loads('{"n":9007199254740993}')["n"] == 9007199254740993
    for invalid in [{1: "key"}, {"x": 1.0}, {"x": "\udfff"}, (1, 2)]:
        with pytest.raises((TypeError, ValueError)):
            canonical_json_bytes(invalid)


def test_synthetic_candidate_is_valid_and_read_only(contract_case):
    case = contract_case
    before = {p: p.read_bytes() for p in case.project.rglob("*") if p.is_file()}
    report = check(case)
    assert report["diagnostics"] == []
    assert report["valid_for_render"] is True
    assert report["unknowns_count"] == 1
    assert report["scope"] == "full"
    assert before == {p: p.read_bytes() for p in before}
    assert not (case.project / ".ai-sow-lite/current.json").exists()


def test_valid_slice_is_never_render_authority(contract_case):
    report = check(contract_case, "slice")
    assert report["diagnostics"] == []
    assert report["valid_for_render"] is False


@pytest.mark.parametrize("field,value", [("complexity", None), ("complexity", "X"),
    ("work_mode", "REUSE"), ("integration_type", "external"), ("work_type_name", None)])
def test_invalid_classification_is_not_unknown_without_explanation(contract_case, field, value):
    mutate(contract_case, "model.json", lambda m: m["tasks"][0].update({field: value}))
    report = check(contract_case)
    assert report["valid_for_render"] is False
    assert any(d["target"]["field"] == field for d in report["diagnostics"])


def test_unknown_type_default_m_and_null_standard_are_legal(contract_case):
    def change(m):
        task = m["tasks"][0]
        task["work_type_name"] = None
        for basis in task["classification_basis"]:
            basis["standard_id"] = None
            basis["fields"] = [f for f in basis["fields"] if f != "work_type_name"]
    mutate(contract_case, "model.json", change)
    add_pending(contract_case, pending(contract_case, "work_type_name"))
    report = check(contract_case)
    assert report["valid_for_render"] is True, report


def test_non_integration_null_requires_not_applicable_or_exact_open_item(contract_case):
    mutate(contract_case, "model.json", lambda m: m["tasks"][0].update(not_applicable_fields=[]))
    assert check(contract_case)["valid_for_render"] is False
    add_pending(contract_case, pending(contract_case, "integration_type"))
    assert check(contract_case)["valid_for_render"] is True


def test_default_m_and_new_values_do_not_close_open_items(contract_case):
    add_pending(contract_case, pending(contract_case, "work_mode"))
    assert check(contract_case)["valid_for_render"] is True
    assert read_json(contract_case.file("pending-items.json"))["items"][-1]["status"] == "open"


def test_known_tasks_can_coexist_with_unestimated_remainder(contract_case):
    add_pending(contract_case, pending(contract_case, None, target=contract_case.ids["S-01"], unestimated=True))
    assert check(contract_case)["valid_for_render"] is True


@pytest.mark.parametrize("level,children", [("stories", "tasks"), ("features", "stories"), ("epics", "features")])
def test_empty_parent_requires_explicit_work_gap(contract_case, level, children):
    case = contract_case
    model = read_json(case.file("model.json"))
    obj = copy.deepcopy(model[level][0])
    obj["id"] = "00000000-0000-4000-8000-000000008888"
    if level == "stories":
        obj["acs"] = []
    model[level].append(obj)
    write_json(case.file("model.json"), model)
    assert check(case)["valid_for_render"] is False
    add_pending(case, pending(case, None, target=obj["id"], unestimated=True))
    if level == "stories":
        item = pending(case, "acs", target=obj["id"])
        item["id"] = "00000000-0000-4000-8000-000000008889"
        add_pending(case, item)
    assert check(case)["valid_for_render"] is True


@pytest.mark.parametrize("mutation", ["duplicate_id", "parent", "ac_evidence", "standard", "basis", "mode",
                                       "integration_na", "task_gap", "empty_targets", "resolved", "superseded",
                                       "unknown_field", "version", "dependency"])
def test_rejects_structural_and_cross_file_counterexamples(contract_case, mutation):
    case = contract_case
    model = read_json(case.file("model.json"))
    task = model["tasks"][0]
    if mutation == "duplicate_id": task["id"] = model["epics"][0]["id"]
    elif mutation == "parent": task["story_id"] = case.ids["E-01"]
    elif mutation == "ac_evidence": model["stories"][0]["acs"][0]["evidence_refs"] = []
    elif mutation == "standard": task["classification_basis"][0]["standard_id"] = "REL-PLAN"
    elif mutation == "basis": task["classification_basis"] = []
    elif mutation == "mode": task["work_mode"] = "接入复用"
    elif mutation == "integration_na":
        task["work_type_name"] = "跨系统业务交互集成"
        task["classification_basis"][0]["standard_id"] = "IN-INTEGRATION"
    elif mutation == "task_gap": add_pending(case, pending(case, None, unestimated=True))
    elif mutation == "empty_targets":
        item = pending(case, None); item["targets"] = []; add_pending(case, item)
    elif mutation == "resolved":
        mutate(case, "pending-items.json", lambda p: p["items"][0].update(status="resolved", resolution={
            "decision_id": case.ids["D-01"], "request_id": case.request_id, "summary": "采用"}))
    elif mutation == "superseded":
        mutate(case, "pending-items.json", lambda p: p["items"][0].update(status="superseded", resolution={
            "replacement_item_ids": [], "lineage_refs": [], "request_id": case.request_id, "reason": "替换"}))
    elif mutation == "unknown_field": task["effort"] = 3
    elif mutation == "version": model["schema_version"] = "2.0"
    elif mutation == "dependency": model["dependencies"][0]["to_story_id"] = case.ids["T-01"]
    write_json(case.file("model.json"), model)
    report = check(case)
    assert report["valid_for_render"] is False, mutation
    assert report["diagnostics"], mutation


def test_reports_all_candidate_errors_in_one_batch(contract_case):
    mutate(contract_case, "model.json", lambda m: m["tasks"][0].update(complexity="X", work_mode="invalid"))
    mutate(contract_case, "pending-items.json", lambda p: p["items"][0].update(status="invalid"))
    fields = {d["target"]["field"] for d in check(contract_case)["diagnostics"]}
    assert {"complexity", "work_mode", "status"} <= fields


def analysis_file(case):
    return case.project / ".ai-sow-lite/analysis/topics" / case.ids["topic-version"] / "analysis.json"


@pytest.mark.parametrize("kind", ["cycle", "missing_basis", "source_hash", "source_range", "source_bytes"])
def test_evidence_graph_and_real_source_integrity(contract_case, kind):
    case = contract_case
    path = analysis_file(case)
    analysis = read_json(path)
    ev = analysis["evidence"][0]
    if kind == "cycle": ev.update(kind="judgment", source_refs=[], basis_refs=[ev["id"]])
    elif kind == "missing_basis": ev.update(kind="judgment", source_refs=[], basis_refs=[case.ids["T-01"]])
    elif kind == "source_hash": ev["source_refs"][0]["excerpt_hash"] = "0" * 64
    elif kind == "source_range": ev["source_refs"][0]["locator"]["end_line"] = 99999
    elif kind == "source_bytes":
        original = case.project / ".ai-sow-lite/inputs/originals" / case.ids["P1"] / "prd.md"
        original.write_bytes(original.read_bytes() + b"changed")
    write_json(path, analysis)
    assert check(case)["valid_for_render"] is False


def test_empty_gap_requires_consistent_analysis_not_keywords(contract_case):
    case = contract_case
    empty = dict(schema_version="1.0", epics=[], features=[], stories=[], tasks=[], dependencies=[], lineage=[])
    write_json(case.file("model.json"), empty)
    write_json(case.file("pending-items.json"), {"schema_version": "1.0", "items": []})
    write_json(case.file("decisions.json"), {"schema_version": "1.0", "items": []})
    assert check(case)["valid_for_render"] is False  # analysis still refers to removed objects
    analysis = read_json(analysis_file(case))
    topic = analysis["topics"][0]
    topic["related_object_ids"] = []
    topic["conclusion"] = "现有能力已覆盖本次目标，本期无需新增交付工作。"
    write_json(analysis_file(case), analysis)
    assert check(case)["valid_for_render"] is True
    analysis_file(case).unlink()
    assert check(case)["valid_for_render"] is False


@pytest.mark.parametrize("escape", ["parent", "absolute", "symlink"])
def test_candidate_paths_cannot_escape_work_area(contract_case, tmp_path, escape):
    case = contract_case
    candidate = read_json(case.candidate_path)
    external = tmp_path / "private.json"
    external.write_text('{"private":"do not disclose"}', encoding="utf-8")
    if escape == "parent": candidate["model_path"] = ".ai-sow-lite/../private.json"
    elif escape == "absolute": candidate["model_path"] = str(external)
    else:
        case.file("linked.json").symlink_to(external)
        candidate["model_path"] = case.file("linked.json").relative_to(case.project).as_posix()
    write_json(case.candidate_path, candidate)
    report = check(case)
    assert report["valid_for_render"] is False
    assert str(external) not in json.dumps(report)
    assert "do not disclose" not in json.dumps(report)


def test_check_cli_returns_file_reference_and_no_fake_delivery(contract_case):
    case = contract_case
    response = run_request(case.project, case.request_id, "check", dict(
        candidate_path=case.candidate_path.relative_to(case.project).as_posix(), scope="full", plan_path=None))
    assert response["ok"] is True, response
    result = response["result"]
    report_path = case.project / result["check_ref"]["path"]
    assert hashlib.sha256(report_path.read_bytes()).hexdigest() == result["check_ref"]["sha256"]
    assert read_json(report_path)["valid_for_render"] is True
    assert result["plan_ref"] is None and result["review_ref"] is None
    assert not (case.project / ".ai-sow-lite/current.json").exists()


@pytest.mark.parametrize("operation,payload", [("ingest", {"kind": "sources"}), ("inspect", {}),
                                               ("render", {}), ("apply", {}), ("recover", {})])
def test_unimplemented_operations_are_explicitly_unsupported(contract_case, operation, payload):
    result = run_request(contract_case.project, contract_case.request_id, operation, payload)
    assert result["ok"] is False
    assert result["diagnostics"][0]["code"] == "OPERATION_UNSUPPORTED"


def test_edits_path_must_belong_to_the_clarify_request(contract_case):
    result = run_request(contract_case.project, contract_case.request_id, 'check', dict(
        edit_path='.ai-sow-lite/work/edits.json', scope='full'))
    assert not result['ok']
    assert result['diagnostics'][0]['code'] == 'PATH_UNSAFE'


def test_unknown_protocol_and_payload_fields_are_rejected(contract_case):
    from ai_sow_lite.cli import execute
    request = dict(protocol_version="2.0", request_id=contract_case.request_id,
                   project_path=str(contract_case.project), operation="check", payload={})
    assert execute(request)["diagnostics"][0]["code"] == "VERSION_INCOMPATIBLE"
    request["protocol_version"] = "1.0"
    request["payload"] = dict(candidate_path="x", scope="full", plan_path=None, force=True)
    assert execute(request)["diagnostics"][0]["code"] == "PROTOCOL_INVALID"


def test_template_identity_and_candidate_bytes_are_bound(contract_case):
    case = contract_case
    before = check(case)
    mutate(case, "model.json", lambda m: m["tasks"][0].update(notes="空白 "))
    after = check(case)
    assert before["candidate_digest"] != after["candidate_digest"]
    assert before["dependencies"] != after["dependencies"]
    mutate(case, "candidate.json", lambda c: c.update(template_hash="0" * 64))
    assert check(case)["valid_for_render"] is False


def test_all_schemas_compile_and_generate_fixture_ids_are_uuid4():
    from ai_sow_lite.contracts import schema_validator
    from uuid import UUID
    for name in ["model", "pending-items", "decisions", "evidence", "protocol", "artifacts", "change-plan"]:
        schema_validator(name).check_schema(schema_validator(name).schema)
    assert all(UUID(value).version == 4 for value in read_json(FIXTURES / "generate/ids.json").values())


def test_independent_questions_can_share_a_field_target(contract_case):
    first = pending(contract_case, 'work_mode')
    second = copy.deepcopy(first)
    second.update(id='00000000-0000-4000-8000-000000009998', question='另一个复用候选的适用边界是什么？')
    add_pending(contract_case, first)
    add_pending(contract_case, second)
    assert check(contract_case)['valid_for_render'] is True


@pytest.mark.parametrize('kind', ['duplicate_evidence', 'evidence_question_id', 'decision_cycle', 'question_cycle'])
def test_identity_and_terminal_replacement_graphs_are_checked(contract_case, kind):
    case = contract_case
    if kind == 'duplicate_evidence':
        analysis = read_json(analysis_file(case))
        analysis['evidence'].append(copy.deepcopy(analysis['evidence'][0]))
        write_json(analysis_file(case), analysis)
    elif kind == 'evidence_question_id':
        mutate(case, 'pending-items.json', lambda p: p['items'][0].update(id=case.ids['EV-P-B1']))
    elif kind == 'decision_cycle':
        data = read_json(case.file('decisions.json'))
        other = copy.deepcopy(data['items'][0])
        other.update(id='00000000-0000-4000-8000-000000007777', supersedes=[data['items'][0]['id']])
        data['items'][0]['supersedes'] = [other['id']]
        data['items'].append(other)
        write_json(case.file('decisions.json'), data)
    else:
        data = read_json(case.file('pending-items.json'))
        other = copy.deepcopy(data['items'][0])
        other['id'] = '00000000-0000-4000-8000-000000007778'
        for item, replacement in [(data['items'][0], other['id']), (other, data['items'][0]['id'])]:
            item.update(status='superseded', resolution=dict(replacement_item_ids=[replacement], lineage_refs=[], request_id=case.request_id, reason='替换事项'))
        data['items'].append(other)
        # Retain a distinct actual open question for default M; no fake closure.
        actual = pending(case, 'complexity', target=case.ids['T-06'])
        data['items'].append(actual)
        write_json(case.file('pending-items.json'), data)
    assert check(case)['valid_for_render'] is False


def seed_history(case):
    """Explicit contract fixture, not apply: a hash-bound applied-history input."""
    from .support.fixtures import seed_applied_history
    return seed_applied_history(case)


def test_historical_lineage_and_superseded_question_use_exact_composite_key(contract_case):
    case = contract_case
    version, old_task = seed_history(case)
    record = dict(from_version_id=version, from_ids=[old_task], to_ids=[case.ids['T-01']],
                  reason='原义务实质替换为本期新对象。', evidence_refs=[case.ids['EV-P-B1']])
    mutate(case, 'model.json', lambda m: m['lineage'].append(record))
    item = pending(case, None, target=old_task)
    item.update(status='superseded', resolution=dict(replacement_item_ids=[],
        lineage_refs=[dict(from_version_id=version, from_ids=[old_task])], request_id=case.request_id, reason='义务替换。'))
    add_pending(case, item)
    assert check(case)['valid_for_render'] is True
    mutate(case, 'model.json', lambda m: m['lineage'][0].update(from_version_id='00000000-0000-4000-8000-000000006666'))
    assert check(case)['valid_for_render'] is False


def test_literal_json_whitespace_changes_file_binding_not_semantic_digest(contract_case):
    before = check(contract_case)
    p = contract_case.file('model.json')
    p.write_bytes(p.read_bytes() + b' \n')
    after = check(contract_case)
    assert before['candidate_digest'] == after['candidate_digest']
    assert before['dependencies'] != after['dependencies']


def test_report_schema_and_request_ownership(contract_case):
    from ai_sow_lite.contracts import schema_validator
    assert list(schema_validator('artifacts', 'check').iter_errors(check(contract_case))) == []
    response = run_request(contract_case.project, '00000000-0000-4000-8000-000000006666', 'check', dict(
        candidate_path=contract_case.candidate_path.relative_to(contract_case.project).as_posix(), scope='full', plan_path=None))
    assert response['diagnostics'][0]['code'] == 'CANDIDATE_INVALID'
    assert list(schema_validator('protocol', 'response').iter_errors(response)) == []


def test_all_errors_include_schema_valid_reports_with_invalid_id(contract_case):
    from ai_sow_lite.contracts import schema_validator
    mutate(contract_case, 'model.json', lambda m: m['tasks'][0].update(id='not-a-uuid', complexity=None))
    report = check(contract_case)
    assert report['valid_for_render'] is False
    assert list(schema_validator('artifacts', 'check').iter_errors(report)) == []


def test_explicit_project_root_symlink_alias_is_supported(contract_case, tmp_path):
    from ai_sow_lite.validation import check_candidate
    case = contract_case
    alias = tmp_path / '项目入口 alias'
    alias.symlink_to(case.project, target_is_directory=True)
    candidate = alias / case.candidate_path.relative_to(case.project)
    report = check_candidate(alias, candidate, 'full', None)
    assert report['valid_for_render'] is True, report
    assert report['candidate_ref']['path'] == case.candidate_path.relative_to(case.project).as_posix()


def test_macos_var_project_root_alias_is_supported():
    import sys
    import tempfile
    from .support.fixtures import build_contract_case
    from ai_sow_lite.validation import check_candidate
    if sys.platform != 'darwin':
        pytest.skip('macOS /var alias regression')
    with tempfile.TemporaryDirectory(prefix='lite-alias-') as directory:
        resolved = Path(directory).resolve()
        if not resolved.is_relative_to('/private/var'):
            pytest.skip('temp directory is not in the macOS /var alias')
        alias = Path('/var') / resolved.relative_to('/private/var') / '项目'
        case = build_contract_case(alias)
        report = check_candidate(alias, case.candidate_path, 'full', None)
        assert report['valid_for_render'] is True, report


def test_child_symlink_to_another_request_stays_rejected_with_root_alias(contract_case, tmp_path):
    from ai_sow_lite.validation import check_candidate
    case = contract_case
    alias = tmp_path / 'root-alias'
    alias.symlink_to(case.project, target_is_directory=True)
    other = case.candidate_path.parent.parent / '00000000-0000-4000-8000-000000003333'
    other.mkdir()
    other_model = other / 'model.json'
    other_model.write_bytes(case.file('model.json').read_bytes())
    case.file('borrowed.json').symlink_to(other_model)
    mutate(case, 'candidate.json', lambda c: c.update(model_path=case.file('borrowed.json').relative_to(case.project).as_posix()))
    report = check_candidate(alias, alias / case.candidate_path.relative_to(case.project), 'full', None)
    assert report['valid_for_render'] is False
    assert any(d['target']['field'] == 'model_path' for d in report['diagnostics'])


@pytest.mark.parametrize('form,valid', [('omitted', True), ('registered', True), ('basename', True),
                                      ('wrong', False), ('missing', False), ('escape', False), ('absolute', False)])
def test_single_text_locator_accepts_only_its_registered_file(contract_case, form, valid):
    case = contract_case
    path = analysis_file(case)
    analysis = read_json(path)
    source = analysis['evidence'][0]['source_refs'][0]
    registered = f".ai-sow-lite/inputs/originals/{case.ids['P1']}/prd.md"
    value = {'registered': registered, 'basename': 'prd.md', 'wrong': 'hld.md',
             'missing': 'missing.md', 'escape': '../prd.md', 'absolute': str(case.project / registered)}
    if form != 'omitted':
        source['locator']['path'] = value[form]
    write_json(path, analysis)
    report = check(case)
    assert report['valid_for_render'] is valid, report


def test_candidate_digest_binds_adopted_topic_analysis(contract_case):
    before = check(contract_case)
    path = analysis_file(contract_case)
    data = read_json(path)
    data['topics'][0]['conclusion'] += ' 新补充的范围解释。'
    write_json(path, data)
    after = check(contract_case)
    assert before['candidate_digest'] != after['candidate_digest']


@pytest.mark.parametrize('identity', ['00000000000040008000000000000001', '00000000-0000-4000-8000-00000000ABCD'])
def test_invalid_uuid_spelling_never_leaks_into_diagnostic_identity(contract_case, identity):
    from ai_sow_lite.cli import execute
    from ai_sow_lite.contracts import schema_validator
    mutate(contract_case, 'model.json', lambda m: m['tasks'][0].update(id=identity))
    report = check(contract_case)
    assert report['valid_for_render'] is False
    assert list(schema_validator('artifacts', 'check').iter_errors(report)) == []
    response = execute(dict(protocol_version='1.0', request_id=identity, project_path=str(contract_case.project), operation='inspect', payload={}))
    assert list(schema_validator('protocol', 'response').iter_errors(response)) == []


def test_schema_error_does_not_hide_independent_source_diagnostics(contract_case):
    case = contract_case
    mutate(case, 'model.json', lambda m: m['tasks'][0].update(complexity='X'))
    data = read_json(analysis_file(case))
    data['evidence'][0]['source_refs'][0]['excerpt_hash'] = '0' * 64
    write_json(analysis_file(case), data)
    report = check(case)
    fields = {d['target']['field'] for d in report['diagnostics']}
    assert {'complexity', 'source_refs'} <= fields


@pytest.mark.parametrize('schema_name', ['model', 'pending-items', 'decisions', 'evidence', 'protocol', 'artifacts', 'change-plan'])
def test_review_s5_uuid_and_digest_tokens_reject_trailing_lf(schema_name):
    from ai_sow_lite.contracts import schema_validator
    from jsonschema import Draft202012Validator
    # Exercise every exact-token leaf used by these public contracts, not just one ID.
    # A permissive anchor on any reference field must fail this regression.
    def leaves(value):
        if isinstance(value, dict):
            if value.get('type') == 'string' and 'pattern' in value:
                pattern = value['pattern']
                if '[0-9a-f]{8}' in pattern:
                    yield value, '00000000-0000-4000-8000-000000000001'
                elif pattern == '^[0-9a-f]{64}$':
                    yield value, 'a' * 64
                elif pattern == '^json-v1:[0-9a-f]{64}$':
                    yield value, 'json-v1:' + 'a' * 64
            for child in value.values():
                yield from leaves(child)
        elif isinstance(value, list):
            for child in value:
                yield from leaves(child)
    tokens = list(leaves(schema_validator(schema_name).schema))
    assert tokens
    for schema, token in tokens:
        validator = Draft202012Validator(schema)
        assert validator.is_valid(token)
        assert not validator.is_valid(token + '\n'), schema


def test_review_s5_full_candidate_rejects_uuid_lf_without_normalizing(contract_case):
    case = contract_case
    old_id = case.ids['T-01']
    mutate(case, 'model.json', lambda m: m['tasks'][0].update(id=old_id + '\n'))
    data = read_json(analysis_file(case))
    related = data['topics'][0]['related_object_ids']
    related[related.index(old_id)] = old_id + '\n'
    write_json(analysis_file(case), data)
    original = case.file('model.json').read_bytes()
    assert check(case)['valid_for_render'] is False
    assert case.file('model.json').read_bytes() == original


def history_item(case, suffix='001'):
    return dict(id='00000000-0000-4000-8000-000000021'+suffix,
                label='历史查询能力', description='', evidence_refs=[case.ids['EV-P-B1']])


@pytest.mark.parametrize('violation,field', [('nested_basis', 'instance_facts'), ('missing_parent', 'parent_id'),
                                          ('duplicate_id', 'id'), ('parent_cycle', 'parent_id')])
def test_review_s1_historical_item_references_close_in_topic_version(contract_case, violation, field):
    case = contract_case
    data = read_json(analysis_file(case))
    item = history_item(case)
    items = [item]
    if violation == 'nested_basis':
        item['instance_facts'] = [dict(text='已知调用条件', evidence_refs=['00000000-0000-4000-8000-000000029999'])]
    elif violation == 'missing_parent':
        item['parent_id'] = '00000000-0000-4000-8000-000000029998'
    elif violation == 'duplicate_id':
        items.append({**item, 'description': '同身份的另一份说明'})
    else:
        other = history_item(case, '002')
        item['parent_id'], other['parent_id'] = other['id'], item['id']
        items.append(other)
    data['topics'][0]['historical_items'] = items
    write_json(analysis_file(case), data)
    report = check(case)
    assert report['valid_for_render'] is False
    assert any(d['target']['field'] == field for d in report['diagnostics'])


def test_review_s1_sparse_history_and_explicit_parent_are_legal(contract_case):
    case = contract_case
    data = read_json(analysis_file(case))
    parent, child = history_item(case), history_item(case, '002')
    child.update(parent_id=parent['id'], instance_facts=[dict(text='单角色查询', evidence_refs=[case.ids['EV-P-B1']])])
    data['topics'][0]['historical_items'] = [child, parent]
    write_json(analysis_file(case), data)
    assert check(case)['valid_for_render'] is True


def second_topic(case):
    data = read_json(analysis_file(case))
    topic = copy.deepcopy(data['topics'][0])
    topic.update(topic_id='00000000-0000-4000-8000-000000022001',
                 topic_version_id='00000000-0000-4000-8000-000000022002', conclusion='第二个独立主题的分析。')
    data['topics'] = [topic]
    path = analysis_file(case).parent.parent / topic['topic_version_id'] / 'analysis.json'
    write_json(path, data)
    mutate(case, 'candidate.json', lambda c: c['topic_version_ids'].append(topic['topic_version_id']))
    return path, data


@pytest.mark.parametrize('violation', ['duplicate_same', 'duplicate_conflict', 'cross_file_conflict', 'wrong_topic_identity'])
def test_review_s2_topic_version_has_one_immutable_content(contract_case, violation):
    case = contract_case
    original = read_json(analysis_file(case))
    repeated = copy.deepcopy(original['topics'][0])
    if violation.startswith('duplicate'):
        if violation == 'duplicate_conflict':
            repeated['conclusion'] += ' 与同版冲突的新结论。'
        original['topics'].append(repeated)
        write_json(analysis_file(case), original)
    else:
        other_path, data = second_topic(case)
        if violation == 'cross_file_conflict': repeated['conclusion'] += ' 冲突副本。'
        else: repeated['topic_id'] = data['topics'][0]['topic_id']
        data['topics'].append(repeated)
        write_json(other_path, data)
    report = check(case)
    assert report['valid_for_render'] is False
    assert any(d['target']['field'] == 'topic_version_id' for d in report['diagnostics'])


def test_review_s2_multiple_topics_and_identical_shared_content_are_legal(contract_case):
    case = contract_case
    original = read_json(analysis_file(case))
    other_path, data = second_topic(case)
    original['topics'].append(copy.deepcopy(data['topics'][0]))
    data['topics'].insert(0, copy.deepcopy(original['topics'][0]))
    write_json(analysis_file(case), original)
    write_json(other_path, data)
    report = check(case)
    assert report['valid_for_render'] is True, report


def test_review_s1_history_parent_cannot_resolve_from_another_topic_version(contract_case):
    case = contract_case
    original = read_json(analysis_file(case))
    other_path, data = second_topic(case)
    parent, child = history_item(case), history_item(case, '002')
    child['parent_id'] = parent['id']
    original['topics'][0]['historical_items'] = [child]
    data['topics'][0]['historical_items'] = [parent]
    write_json(analysis_file(case), original)
    write_json(other_path, data)
    assert any(d['target']['field'] == 'parent_id' for d in check(case)['diagnostics'])


@pytest.mark.parametrize('violation,field', [('unknown_uncovered_input', 'uncovered_regions'),
    ('reversed_uncovered_range', 'locator'), ('covered_outside_topic', 'covered_regions'),
    ('uncovered_outside_topic', 'uncovered_regions'), ('wrong_uncovered_path', 'locator')])
def test_review_s3_coverage_records_match_topic_inputs_and_locator_order(contract_case, violation, field):
    case = contract_case
    data = read_json(analysis_file(case))
    topic = data['topics'][0]
    region = dict(input_version_id=case.ids['P1'], locator=dict(kind='text_lines', start_line=1, end_line=900),
                  reason='尚未完成本区域分析。')
    if violation == 'unknown_uncovered_input':
        region['input_version_id'] = '00000000-0000-4000-8000-000000023333'
    elif violation == 'reversed_uncovered_range':
        region['locator'].update(start_line=900, end_line=1)
    elif violation == 'covered_outside_topic':
        topic['input_version_ids'] = []
    elif violation == 'uncovered_outside_topic':
        topic['input_version_ids'].remove(case.ids['P1'])
        topic['covered_regions'] = [r for r in topic['covered_regions'] if r['input_version_id'] != case.ids['P1']]
    else:
        region['locator']['path'] = 'another-file.md'
    if violation != 'covered_outside_topic':
        topic['uncovered_regions'].append(region)
    write_json(analysis_file(case), data)
    report = check(case)
    assert report['valid_for_render'] is False
    assert any(d['target']['field'] == field for d in report['diagnostics'])


def test_review_s3_uncovered_text_needs_no_excerpt_or_successful_region_read(contract_case):
    case = contract_case
    data = read_json(analysis_file(case))
    # An analysis coverage declaration, not a claim that these lines were read.
    data['topics'][0]['uncovered_regions'].append(dict(input_version_id=case.ids['P1'],
        locator=dict(kind='text_lines', start_line=900, end_line=901, path='prd.md'), reason='待定位补读。'))
    write_json(analysis_file(case), data)
    assert check(case)['valid_for_render'] is True


@pytest.mark.parametrize('invalid_file,violation,expected', [
    ('decisions.json', 'standard', 'standard_id'), ('pending-items.json', 'standard', 'standard_id'),
    ('decisions.json', 'empty_parent', None), ('model.json', 'decision_self', 'supersedes'),
    ('model.json', 'question_self', 'replacement_item_ids')])
def test_review_q1_invalid_file_does_not_hide_independent_checks(contract_case, invalid_file, violation, expected):
    case = contract_case
    if violation == 'standard':
        mutate(case, 'model.json', lambda m: m['tasks'][0]['classification_basis'][0].update(standard_id='REL-PLAN'))
    elif violation == 'empty_parent':
        mutate(case, 'model.json', lambda m: m['epics'].append(dict(id='00000000-0000-4000-8000-000000024001', title='空父项', evidence_refs=[case.ids['EV-P-B1']])))
    elif violation == 'decision_self':
        mutate(case, 'decisions.json', lambda d: d['items'][0].update(supersedes=[case.ids['D-01']]))
    else:
        mutate(case, 'pending-items.json', lambda p: p['items'][0].update(status='superseded', resolution=dict(
            replacement_item_ids=[case.ids['P-01']], lineage_refs=[], request_id=case.request_id, reason='错误自替代。')))
    mutate(case, invalid_file, lambda d: d.update(unrecognized=True))
    report = check(case)
    assert report['valid_for_render'] is False
    assert any(d['target']['field'] == expected for d in report['diagnostics']), report


@pytest.mark.parametrize('invalid_file', ['decisions.json', 'pending-items.json', 'model.json', 'input_index', 'analysis'])
def test_review_q1_invalid_dependencies_are_not_legal_empty_collections(contract_case, invalid_file):
    case = contract_case
    if invalid_file == 'decisions.json':
        mutate(case, 'model.json', lambda m: m['tasks'][0]['evidence_refs'].append(case.ids['D-01']))
    elif invalid_file == 'pending-items.json':
        mutate(case, 'model.json', lambda m: m['tasks'][0].update(work_mode=None))
    if invalid_file == 'input_index':
        path = case.project / '.ai-sow-lite/inputs/index.json'
    elif invalid_file == 'analysis':
        path = analysis_file(case)
    else:
        path = case.file(invalid_file)
    data = read_json(path)
    data['unrecognized'] = True
    write_json(path, data)
    report = check(case)
    assert report['valid_for_render'] is False
    assert len(report['diagnostics']) == 1, report  # only the actual malformed dependency
    assert report['diagnostics'][0]['target']['path'] == path.relative_to(case.project).as_posix()


def lineage_record(case, version, source, targets):
    return dict(from_version_id=version, from_ids=[source], to_ids=targets,
                reason='合成义务的明确替换或退出。', evidence_refs=[case.ids['EV-P-B1']])


def lineage_chain(case, *, record_in_history=True, delete=False):
    from .support.fixtures import seed_lineage_versions
    v1 = '00000000-0000-4000-8000-000000025001'
    v2 = '00000000-0000-4000-8000-000000025002'
    a = '00000000-0000-4000-8000-000000025011'
    b = '00000000-0000-4000-8000-000000025012'
    current = read_json(case.file('model.json'))
    first, second = copy.deepcopy(current), copy.deepcopy(current)
    first['tasks'][0]['id'], second['tasks'][0]['id'] = a, b
    inherited = lineage_record(case, v1, a, [b])
    if record_in_history:
        second['lineage'] = [copy.deepcopy(inherited)]
    successor = lineage_record(case, v2, b, [] if delete else [case.ids['T-01']])
    current['lineage'] = [inherited, successor]
    write_json(case.file('model.json'), current)
    seed_lineage_versions(case, [(v1, first), (v2, second)])
    return v1, v2, a, b


@pytest.mark.parametrize('reverse_recorded', [False, True])
def test_review_s4_rejects_newer_object_pointing_back_to_retired_ancestor(contract_case, reverse_recorded):
    from .support.fixtures import seed_lineage_versions
    case = contract_case
    v1, v2, a, b = lineage_chain(case, record_in_history=False)
    current = read_json(case.file('model.json'))
    current['lineage'] = [lineage_record(case, v2, b, [a]), lineage_record(case, v1, a, [case.ids['T-01']])]
    write_json(case.file('model.json'), current)
    if reverse_recorded:
        first = read_json(case.project / f'.ai-sow-lite/versions/{v1}/model.json')
        second = read_json(case.project / f'.ai-sow-lite/versions/{v2}/model.json')
        second['lineage'] = [copy.deepcopy(current['lineage'][0])]
        seed_lineage_versions(case, [(v1, first), (v2, second)])
    report = check(case)
    assert report['valid_for_render'] is False
    assert any(d['target']['field'] in ('to_ids', 'from_ids', 'from_version_id', 'lineage') for d in report['diagnostics'])


@pytest.mark.parametrize('delete', [False, True])
def test_review_s4_accepts_bound_forward_chain_to_current_or_explicit_deletion(contract_case, delete):
    case = contract_case
    lineage_chain(case, delete=delete)
    before = {path: path.read_bytes() for path in case.project.rglob('*') if path.is_file()}
    report = check(case)
    assert report['valid_for_render'] is True, report
    assert before == {path: path.read_bytes() for path in before}


def test_review_s4_historical_intermediate_needs_bound_replacement_record(contract_case):
    lineage_chain(contract_case, record_in_history=False)
    report = check(contract_case)
    assert report['valid_for_render'] is False
    assert any(d['target']['field'] in ('to_ids', 'from_ids', 'lineage') for d in report['diagnostics'])


def test_review_s4_inherited_record_cannot_be_rewritten_to_skip_its_successor(contract_case):
    case = contract_case
    lineage_chain(case)
    mutate(case, 'model.json', lambda m: m['lineage'][0].update(to_ids=[case.ids['T-01']]))
    report = check(case)
    assert report['valid_for_render'] is False
    assert any(d['target']['field'] == 'lineage' for d in report['diagnostics'])


@pytest.mark.parametrize('payload,valid', [
    (dict(candidate_path='.ai-sow-lite/work/candidate.json', scope='full', plan_path=None), True),
    (dict(edit_path='.ai-sow-lite/work/edit.json', scope='full'), True),
    (dict(edit_path='.ai-sow-lite/work/edit.json', scope='slice'), False),
    (dict(candidate_path='.ai-sow-lite/work/candidate.json', scope='full', plan_path=None, force=True), False)])
def test_review_q2_payload_definition_and_request_enforce_same_contract(contract_case, payload, valid):
    from ai_sow_lite.contracts import schema_validator
    request = dict(protocol_version='1.0', request_id=contract_case.request_id,
                   project_path=str(contract_case.project), operation='check', payload=payload)
    assert schema_validator('protocol', 'check_payload').is_valid(payload) is valid
    assert schema_validator('protocol').is_valid(request) is valid


@pytest.mark.parametrize('status,resolution,valid', [
    ('open', None, True),
    ('resolved', dict(decision_id='00000000-0000-4000-8000-000000000001',
                      request_id='00000000-0000-4000-8000-000000000002', summary='采用事实。'), True),
    ('resolved', None, False),
    ('superseded', dict(replacement_item_ids=['00000000-0000-4000-8000-000000000003'], lineage_refs=[],
                        request_id='00000000-0000-4000-8000-000000000002', reason='替换问题。'), True),
    ('superseded', dict(replacement_item_ids=[], lineage_refs=[],
                        request_id='00000000-0000-4000-8000-000000000002', reason='缺少去向。'), False)])
def test_review_q2_resolution_selects_exact_state_contract(contract_case, status, resolution, valid):
    from ai_sow_lite.contracts import schema_validator
    item = pending(contract_case, 'complexity')
    item.update(status=status, resolution=resolution)
    assert schema_validator('pending-items', 'item').is_valid(item) is valid
