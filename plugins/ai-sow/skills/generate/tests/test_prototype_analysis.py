from __future__ import annotations

TEST_LAYER = "unit"

import hashlib
import copy
import sys
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(SKILL_ROOT / "tests"))
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from prototype_analysis import inventory_demo_bundle
from prototype_analysis import verify_scenario_manifest
from prototype_analysis import verify_prototype_trace
from prototype_analysis import verify_prototype_observations
from contracts import canonical_json_bytes, sha256_bytes


def demo_files():
    return [
        {"sourceId": "demo-html", "relativePath": "demo/index.html", "content": b'<link rel="stylesheet" href="style.css"><button id="save" data-state="idle">Save</button><script src="app.js"></script>'},
        {"sourceId": "demo-css", "relativePath": "demo/style.css", "content": b'button { color: blue; }'},
        {"sourceId": "demo-js", "relativePath": "demo/app.js", "content": b'document.querySelector("#save").addEventListener("click", () => { document.querySelector("#save").dataset.state = "saved"; });'},
    ]


def test_bundle_inventory_preserves_bytes_and_stable_source_interactions():
    files = demo_files()
    before = [hashlib.sha256(item["content"]).hexdigest() for item in files]
    inventory = inventory_demo_bundle("demo/index.html", files)
    assert inventory == inventory_demo_bundle("demo/index.html", list(reversed(files)))
    assert [hashlib.sha256(item["content"]).hexdigest() for item in files] == before
    assert inventory["routes"] == ["demo/index.html"]
    assert {(item["target"], item["executable"]) for item in inventory["references"]} == {("demo/style.css", True), ("demo/app.js", True)}
    assert inventory["controls"][0]["selector"] == "#save"
    assert inventory["states"][0]["value"] == "idle"
    assert inventory["events"][0]["event"] == "click"
    assert inventory["interactions"][0]["selector"] == "#save"
    evidence_ids = {item["evidenceId"] for item in inventory["evidence"]}
    assert set(inventory["interactions"][0]["evidenceIds"]) <= evidence_ids
    assert len(inventory["files"]) == len(evidence_ids) == 3


@pytest.mark.parametrize("remaining", [{"maxScenarioSteps": 0, "maxScreenshots": 1}, {"maxScenarioSteps": 1, "maxScreenshots": 0}])
def test_scenario_frozen_remaining_constraints_reject_overplanned_ir(remaining):
    from contracts import InvalidActionResult
    from prototype_analysis import validate_bound_prototype_result
    inventory = inventory_demo_bundle("demo/index.html", demo_files())
    payload = {"inventory": inventory, "identity": {"round": 1},
               "demoLimits": {"maxDiscoveryRounds": 2, "maxScenarioSteps": 30, "maxScreenshots": 12},
               "demoRemaining": remaining}
    with pytest.raises(InvalidActionResult):
        validate_bound_prototype_result("PROTOTYPE_SCENARIO", payload, canonical_json_bytes(scenario_fixture(inventory)))


@pytest.mark.parametrize("remaining", [{"maxScenarioSteps": 1, "maxScreenshots": 2}, {"maxScenarioSteps": 2, "maxScreenshots": 1}])
def test_scenario_known_critical_replay_must_fit_frozen_remaining(remaining):
    from contracts import InvalidActionResult
    from prototype_analysis import validate_bound_prototype_result
    inventory = inventory_demo_bundle("demo/index.html", demo_files())
    scenario = scenario_fixture(inventory)
    scenario["scenarios"][0]["critical"] = True
    payload = {"inventory": inventory, "identity": {"round": 1},
               "demoLimits": {"maxDiscoveryRounds": 2, "maxScenarioSteps": 30, "maxScreenshots": 12},
               "demoRemaining": remaining}
    with pytest.raises(InvalidActionResult):
        validate_bound_prototype_result("PROTOTYPE_SCENARIO", payload, canonical_json_bytes(scenario))


@pytest.mark.parametrize("invalid", [False, True])
def test_bound_owner_validator_finish_works_without_file_read_capability(monkeypatch, invalid):
    from action_ledger import ActionLedger, issue, finish
    from contracts import action_contract_binding
    from models import ActionEnvelope
    from prototype_analysis import validate_bound_prototype_result
    from test_action_ledger import prepared_envelope, successful_completion
    inventory = inventory_demo_bundle("demo/index.html", demo_files())
    scenario = scenario_fixture(inventory)
    payload = {"inventory": inventory, "identity": {"round": 1},
        "scenario": {"normalizedResult": scenario}, "trace": {"normalizedResult": trace_fixture(inventory, scenario)}}
    envelope_value = dict(prepared_envelope().value)
    envelope_value["actionContractId"] = "PROTOTYPE_ANALYZE-v1"
    envelope_value["actionContractSha256"] = action_contract_binding(SKILL_ROOT, "PROTOTYPE_ANALYZE-v1")[1]
    envelope = ActionEnvelope(envelope_value, "actions/action-1/envelope.json", sha256_bytes(canonical_json_bytes(envelope_value)))
    result = {"observations": [observation_fixture(inventory)]}
    if invalid:
        result["observations"][0]["evidenceIds"] = ["unknown-source"]
    raw = canonical_json_bytes(result)

    def no_file_reads(*args, **kwargs):
        raise AssertionError("Owner callback has no file-read capability")

    def validator(normalized_result: bytes) -> None:
        with monkeypatch.context() as guard:
            guard.setattr("io.open", no_file_reads)
            validate_bound_prototype_result("PROTOTYPE_ANALYZE", payload, normalized_result)

    ledger, record = finish(issue(ActionLedger(), envelope), envelope, successful_completion(raw), bound_result_validator=validator)
    assert ledger.raw_outputs[record.raw_sha256] == raw
    if invalid:
        assert record.failure_kind == "INVALID_IR"
        assert record.normalized_result_sha256 is None
        assert not ledger.normalized_results
    else:
        assert record.outcome == "SUCCEEDED"
        assert ledger.normalized_results[record.normalized_result_sha256] == raw


def test_bundle_inventory_linked_htm_page_is_not_silently_uncovered():
    files = demo_files()
    files[0]["content"] += b'<a href="details.htm">Details</a>'
    files.append({"sourceId": "details", "relativePath": "demo/details.htm", "content": b'<button id="confirm">Confirm</button>'})
    inventory = inventory_demo_bundle("demo/index.html", files)
    assert "demo/details.htm" in inventory["routes"]
    assert any(item["page"] == "demo/details.htm" and item["selector"] == "#confirm" for item in inventory["interactions"])


def test_bundle_inventory_html_without_ids_has_usable_selectors_and_static_page_interaction():
    files = [{"sourceId": "page", "relativePath": "index.html", "content": b'<h1>Page</h1><div><button onblur="check()">One</button><button>Two</button></div>'}]
    inventory = inventory_demo_bundle("index.html", files)
    assert [item["selector"] for item in inventory["controls"]] == ["div:nth-of-type(1) > button:nth-of-type(1)", "div:nth-of-type(1) > button:nth-of-type(2)"]
    assert any(item["event"] == "blur" for item in inventory["interactions"])
    files[0]["content"] = b'<h1>Read only page</h1><p>Details</p>'
    readonly = inventory_demo_bundle("index.html", files)
    assert [(item["selector"], item["event"]) for item in readonly["interactions"]] == [("html", "navigate")]


@pytest.mark.parametrize("entrypoint,extra,path,html,code", [
    ("demo/missing.html", None, None, None, "DEMO_ENTRYPOINT_MISSING"),
    ("demo/index.html", "outside.js", None, None, "DEMO_OUTSIDE_BUNDLE"),
    ("demo/index.html", "demo/../escape.js", None, None, "DEMO_PATH_UNSAFE"),
    ("demo/index.html", None, None, b'<script src="missing.js"></script>', "DEMO_DEPENDENCY_UNDECLARED"),
    ("demo/index.html", "demo/package.json", None, None, "DEMO_BUILD_UNSUPPORTED"),
    ("demo/index.html", None, None, b'<script src="https://cdn.example/script.js"></script>', "DEMO_REMOTE_DEPENDENCY"),
    ("demo/index.html", None, "demo/style.css", b'@import "missing.css";', "DEMO_DEPENDENCY_UNDECLARED"),
    ("demo/index.html", None, "demo/app.js", b'import "./missing.js";', "DEMO_DEPENDENCY_UNDECLARED"),
    ("demo/index.html", None, None, b'<img src="../escape.png">', "DEMO_PATH_UNSAFE"),
])
def test_bundle_boundary_rejects_unsupported_bundle(entrypoint, extra, path, html, code):
    files = demo_files()
    if extra:
        files.append({"sourceId": "extra", "relativePath": extra, "content": b'{}'})
    if html:
        next(item for item in files if item["relativePath"] == (path or "demo/index.html"))["content"] = html
    with pytest.raises(ValueError) as failure:
        inventory_demo_bundle(entrypoint, files)
    assert failure.value.code == code


def test_bundle_boundary_marks_ordinary_external_link_unexecutable():
    files = demo_files()
    files[0]["content"] += b'<a href="https://example.org/help">Help</a>'
    inventory = inventory_demo_bundle("demo/index.html", files)
    assert {"source": "demo/index.html", "target": "https://example.org/help", "executable": False} in inventory["references"]


@pytest.mark.parametrize("seam", ["scenario", "trace"])
@pytest.mark.parametrize("change", ["selector", "operation"])
def test_known_interaction_cannot_borrow_another_operation(seam, change):
    files = demo_files()
    files[0]["content"] += b'<button id="cancel">Cancel</button>'
    inventory = inventory_demo_bundle("demo/index.html", files)
    scenario = scenario_fixture(inventory)
    step = scenario["scenarios"][0]["steps"][0]
    if change == "selector":
        step["selector"] = "#cancel"
        step["assertions"] = [{"selector": "#cancel", "attribute": "textContent", "expected": "Cancel"}]
    else:
        step["operation"] = "wait"
    with pytest.raises(ValueError) as failure:
        if seam == "scenario":
            verify_scenario_manifest(inventory, scenario, {"maxDiscoveryRounds": 2, "maxScenarioSteps": 30, "maxScreenshots": 12}, round=1)
        else:
            verify_prototype_trace(inventory, scenario, trace_fixture(inventory, scenario))
    assert failure.value.code == "PROTOTYPE_SCENARIO_INVALID"


@pytest.mark.parametrize("kind", ["PROTOTYPE_SCENARIO", "PROTOTYPE_BROWSER"])
def test_prototype_typed_step_can_express_page_and_preparation(kind):
    from contracts import action_contract_binding, normalize_action_result
    inventory = inventory_demo_bundle("demo/index.html", demo_files())
    scenario = scenario_fixture(inventory)
    step = scenario["scenarios"][0]["steps"][0]
    step["page"] = "demo/index.html"
    preparation = copy.deepcopy(step) | {"stepId": "prepare", "interactionId": None, "operation": "wait"}
    scenario["scenarios"][0]["steps"].insert(0, preparation)
    result = scenario
    if kind == "PROTOTYPE_BROWSER":
        result = trace_fixture(inventory, scenario)
        for actual in result["runs"][0]["steps"]:
            actual["eventObserved"] = actual["interactionId"] is not None
    contract, digest = action_contract_binding(SKILL_ROOT, kind + "-v1")
    envelope = {"actionContractId": contract["actionContractId"], "actionContractSha256": digest}
    normalized = normalize_action_result(envelope, canonical_json_bytes(result), skill_root=SKILL_ROOT)
    assert normalized == canonical_json_bytes(result)


@pytest.mark.parametrize("seam", ["scenario", "trace", "observation"])
def test_interaction_page_binding_cannot_move_between_identical_selectors(seam):
    files = demo_files() + [{"sourceId": "other", "relativePath": "demo/other.html", "content": b'<button id="save">Save</button>'}]
    inventory = inventory_demo_bundle("demo/index.html", files)
    scenario = scenario_fixture(inventory)
    trace = trace_fixture(inventory, scenario)
    observation = observation_fixture(inventory)
    if seam == "scenario":
        scenario["scenarios"][0]["steps"][0]["page"] = "demo/other.html"
    elif seam == "trace":
        trace["runs"][0]["steps"][0]["page"] = "demo/other.html"
    else:
        observation["behavior"]["page"] = "demo/other.html"
    with pytest.raises(ValueError):
        if seam == "scenario":
            verify_scenario_manifest(inventory, scenario, {"maxDiscoveryRounds": 2, "maxScenarioSteps": 30, "maxScreenshots": 12}, round=1)
        elif seam == "trace":
            verify_prototype_trace(inventory, scenario, trace)
        else:
            verify_prototype_observations(inventory, scenario, trace, {"observations": [observation]})


@pytest.mark.parametrize("case", ["preparation", "declared-only", "undeclared-step"])
def test_scenario_coverage_ids_exclude_preparation_and_match_executed_steps(case):
    files = demo_files()
    files[0]["content"] += b'<button id="cancel">Cancel</button>'
    inventory = inventory_demo_bundle("demo/index.html", files)
    scenario = scenario_fixture(inventory)
    item = scenario["scenarios"][0]
    if case == "preparation":
        for operation in ("wait", "navigate"):
            item["steps"].insert(0, copy.deepcopy(item["steps"][0]) | {
                "stepId": operation, "interactionId": None, "operation": operation, "selector": "html"})
        assert verify_scenario_manifest(inventory, scenario, {"maxDiscoveryRounds": 2, "maxScenarioSteps": 30, "maxScreenshots": 12}, round=1) == scenario
        evidence = verify_prototype_trace(inventory, scenario, trace_fixture(inventory, scenario))
        assert evidence["stepCount"] == 3
        assert evidence["interactionDispositions"] == [{"interactionId": inventory["interactions"][0]["interactionId"], "disposition": "OBSERVED"}]
    else:
        second = inventory["interactions"][1]["interactionId"]
        item["interactionIds"] = item["interactionIds"] + [second] if case == "declared-only" else [second]
        with pytest.raises(ValueError) as failure:
            verify_scenario_manifest(inventory, scenario, {"maxDiscoveryRounds": 2, "maxScenarioSteps": 30, "maxScreenshots": 12}, round=1)
        assert failure.value.code == "PROTOTYPE_SCENARIO_INVALID"


@pytest.mark.parametrize("case", ["missing-event", "preparation-claims-event"])
def test_trace_coverage_requires_actual_bound_event_not_api_success(case):
    inventory = inventory_demo_bundle("demo/index.html", demo_files())
    scenario = scenario_fixture(inventory)
    if case == "preparation-claims-event":
        scenario["scenarios"][0]["steps"].insert(0, copy.deepcopy(scenario["scenarios"][0]["steps"][0]) | {
            "stepId": "prepare", "operation": "wait", "interactionId": None})
    trace = trace_fixture(inventory, scenario)
    trace["runs"][0]["steps"][0]["eventObserved"] = case == "preparation-claims-event"
    if case == "preparation-claims-event":
        with pytest.raises(ValueError) as failure:
            verify_prototype_trace(inventory, scenario, trace)
        assert failure.value.code == "PROTOTYPE_TRACE_STEP_INVALID"
    else:
        evidence = verify_prototype_trace(inventory, scenario, trace)
        assert evidence["interactionDispositions"] == [{"interactionId": inventory["interactions"][0]["interactionId"], "disposition": "BROKEN"}]
        with pytest.raises(ValueError) as failure:
            verify_prototype_observations(inventory, scenario, trace, {"observations": [observation_fixture(inventory)]})
        assert failure.value.code == "PROTOTYPE_RUNTIME_EVIDENCE_REQUIRED"


@pytest.mark.parametrize("value", [None, "demo/index.html", "demo/other.html"])
def test_navigation_value_cannot_override_bound_target_page(value):
    inventory = inventory_demo_bundle("demo/index.html", demo_files())
    scenario = scenario_fixture(inventory)
    scenario["scenarios"][0]["steps"].insert(0, copy.deepcopy(scenario["scenarios"][0]["steps"][0]) | {
        "stepId": "navigate", "operation": "navigate", "interactionId": None, "selector": "html", "value": value})
    limits = {"maxDiscoveryRounds": 2, "maxScenarioSteps": 30, "maxScreenshots": 12}
    if value == "demo/other.html":
        with pytest.raises(ValueError) as failure:
            verify_scenario_manifest(inventory, scenario, limits, round=1)
        assert failure.value.code == "PROTOTYPE_SCENARIO_INVALID"
    else:
        assert verify_scenario_manifest(inventory, scenario, limits, round=1) == scenario
        assert verify_prototype_trace(inventory, scenario, trace_fixture(inventory, scenario))["stepCount"] == 2


@pytest.mark.parametrize("html", [
    '<script type="module">import "TARGET";</script>',
    '<script>fetch("TARGET")</script>',
    '<style>body{background:url("TARGET")}</style>',
    '<div style="background:url(TARGET)"></div>',
    '<img srcset="TARGET 1x">',
    '<picture><source srcset="TARGET 1x"></picture>',
])
@pytest.mark.parametrize("target,code", [("missing.png", "DEMO_DEPENDENCY_UNDECLARED"), ("https://example.invalid/asset", "DEMO_REMOTE_DEPENDENCY")])
def test_html_static_dependency_closure_rejects_missing_and_remote(html, target, code):
    files = [{"sourceId": "page", "relativePath": "index.html", "content": html.replace("TARGET", target).encode()}]
    with pytest.raises(ValueError) as failure:
        inventory_demo_bundle("index.html", files)
    assert failure.value.code == code


def test_html_static_dependency_closure_accepts_declared_local_inline_assets():
    files = [{"sourceId": "page", "relativePath": "index.html", "content": b'<script type="module">import "app.js";</script><style>@import "theme.css"; p{background:url(pixel.png)}</style><img style="background:url(pixel.png)" srcset="pixel.png 1x, pixel2.png 2x">'},
             {"sourceId": "script", "relativePath": "app.js", "content": b'console.log("local")'},
             {"sourceId": "style", "relativePath": "theme.css", "content": b'p{color:blue}'},
             {"sourceId": "pixel", "relativePath": "pixel.png", "content": b'\x89PNG'},
             {"sourceId": "pixel2", "relativePath": "pixel2.png", "content": b'\x89PNG2'}]
    before = copy.deepcopy(files)
    inventory = inventory_demo_bundle("index.html", files)
    assert {item["target"] for item in inventory["references"]} == {"app.js", "theme.css", "pixel.png", "pixel2.png"}
    assert all(item["executable"] for item in inventory["references"])
    assert files == before


@pytest.mark.parametrize("mode", ["inline", "script", "module-import"])
@pytest.mark.parametrize("tag,event,operation", [("div", "click", "click"), ("input", "keydown", "press")])
def test_static_literal_listener_has_source_bound_interaction_and_scenario(mode, tag, event, operation):
    javascript = f'document.querySelector("#save").addEventListener("{event}", () => {{ document.title = "Saved"; }});'.encode()
    html = f'<{tag} id="save">Save</{tag}>'.encode()
    files = []
    if mode == "inline":
        html += b'<script>' + javascript + b'</script>'
    else:
        html += b'<script type="module" src="app.js"></script>'
        files.append({"sourceId": "script", "relativePath": "app.js", "content": javascript if mode == "script" else b'import "./listener.js";'})
        if mode == "module-import":
            files.append({"sourceId": "listener", "relativePath": "listener.js", "content": javascript})
    files.append({"sourceId": "page", "relativePath": "index.html", "content": html})
    inventory = inventory_demo_bundle("index.html", files)
    matches = [item for item in inventory["interactions"] if item["selector"] == "#save" and item["event"] == event]
    assert len(matches) == 1
    interaction = matches[0]
    assert interaction["page"] == "index.html"
    source_paths = {item["relativePath"] for item in inventory["evidence"] if item["evidenceId"] in interaction["evidenceIds"]}
    assert source_paths == ({"index.html"} if mode == "inline" else {"index.html", "app.js" if mode == "script" else "listener.js"})
    assert inventory_demo_bundle("index.html", list(reversed(files))) == inventory
    scenario = scenario_fixture(inventory)
    scenario["scenarios"][0]["interactionIds"] = [interaction["interactionId"]]
    scenario["scenarios"][0]["steps"][0].update(interactionId=interaction["interactionId"], page="index.html", selector="#save", operation=operation, value="Enter" if operation == "press" else None)
    assert verify_scenario_manifest(inventory, scenario, {"maxDiscoveryRounds": 2, "maxScenarioSteps": 30, "maxScreenshots": 12}, round=1) == scenario
    assert verify_prototype_trace(inventory, scenario, trace_fixture(inventory, scenario))["interactionDispositions"] == [{"interactionId": interaction["interactionId"], "disposition": "OBSERVED"}]


def test_literal_listener_identity_follows_only_its_pages_and_deduplicates_declarations():
    listener = b'document.querySelector("#common").addEventListener("click", () => {});'
    files = [
        {"sourceId": "page", "relativePath": "index.html", "content": b'<div id="common"></div><div id="local"></div><script src="shared.js"></script><script src="local.js"></script>'},
        {"sourceId": "other", "relativePath": "other.html", "content": b'<div id="common"></div><script src="shared.js"></script>'},
        {"sourceId": "data", "relativePath": "data.html", "content": b'<div id="common"></div><script type="application/json" src="shared.js"></script>'},
        {"sourceId": "shared", "relativePath": "shared.js", "content": listener + listener},
        {"sourceId": "local", "relativePath": "local.js", "content": b'document.querySelector("#local").addEventListener("keydown", () => {});'},
        {"sourceId": "unused", "relativePath": "unused.js", "content": b'document.querySelector("#unused").addEventListener("click", () => {});'},
    ]
    inventory = inventory_demo_bundle("index.html", files)
    active = [item for item in inventory["interactions"] if item["event"] != "navigate"]
    assert {(item["page"], item["selector"], item["event"]) for item in active} == {
        ("index.html", "#common", "click"), ("other.html", "#common", "click"), ("index.html", "#local", "keydown")}
    assert len(active) == 3
    evidence = {item["evidenceId"]: item["relativePath"] for item in inventory["evidence"]}
    for item in active:
        assert {evidence[key] for key in item["evidenceIds"]} == {item["page"], "local.js" if item["selector"] == "#local" else "shared.js"}


def test_computed_listener_identity_remains_bound_unresolved_evidence_not_invented_id():
    files = [{"sourceId": "page", "relativePath": "index.html", "content": b'<div id="dynamic">Dynamic</div><script>const selector = "#" + "dynamic"; document.querySelector(selector).addEventListener("click", () => {});</script>'}]
    inventory = inventory_demo_bundle("index.html", files)
    assert [(item["selector"], item["event"]) for item in inventory["interactions"]] == [("html", "navigate")]
    scenario = scenario_fixture(inventory)
    scenario["scenarios"][0]["steps"][0]["operation"] = "navigate"
    trace = trace_fixture(inventory, scenario)
    trace["unresolvedDiscoveries"] = [unresolved_discovery(inventory)]
    assert verify_prototype_trace(inventory, scenario, trace)["unresolvedDiscoveryCount"] == 1
    with pytest.raises(ValueError) as failure:
        verify_prototype_observations(inventory, scenario, trace, {"observations": [observation_fixture(inventory)]})
    assert failure.value.code == "PROTOTYPE_UNRESOLVED_DISCOVERY"


@pytest.mark.parametrize("html,operation,event", [
    ('<textarea id="control"></textarea>', "fill", "input"),
    *[(f'<input id="control"{attribute}>', "fill", "input") for attribute in ["", *[f' type="{kind}"' for kind in ("text", "search", "email", "url", "tel", "password", "number")]]],
    *[(f'<input id="control" type="{kind}">', "click", "click") for kind in ("button", "submit", "reset")],
    *[(f'<input id="control" type="{kind}">', "check", "change") for kind in ("checkbox", "radio")],
    ('<select id="control"><option>Saved</option></select>', "select", "change"),
])
def test_native_control_defaults_allow_their_supported_scenario_operation(html, operation, event):
    inventory = inventory_demo_bundle("index.html", [{"sourceId": "page", "relativePath": "index.html", "content": html.encode()}])
    scenario = scenario_fixture(inventory)
    scenario["scenarios"][0]["steps"][0].update(operation=operation, value="Saved" if operation in {"fill", "select"} else None)
    assert verify_scenario_manifest(inventory, scenario, {"maxDiscoveryRounds": 2, "maxScenarioSteps": 30, "maxScreenshots": 12}, round=1) == scenario
    assert inventory["interactions"][0]["event"] == event


def scenario_fixture(inventory, round=1):
    interaction = inventory["interactions"][0]["interactionId"]
    selector = inventory["interactions"][0]["selector"]
    return {"bundleSha256": inventory["bundleSha256"], "round": round, "scenarios": [
        {"scenarioId": "save", "critical": False, "interactionIds": [interaction], "steps": [
            {"stepId": "click-save", "page": inventory["interactions"][0]["page"], "interactionId": interaction, "operation": "click", "selector": selector, "value": None,
             "assertions": [{"selector": selector, "attribute": "data-state", "expected": "saved"}], "screenshot": True}
        ]}
    ]}


@pytest.mark.parametrize("change,expected", [
    ("valid", None), ("unknown", "PROTOTYPE_INTERACTION_UNKNOWN"),
    ("round", "INCOMPLETE_BUDGET"), ("steps", "INCOMPLETE_BUDGET"),
    ("screenshots", "INCOMPLETE_BUDGET"), ("schema", "PROTOTYPE_SCENARIO_INVALID"),
    ("bundle", "PROTOTYPE_BUNDLE_MISMATCH"),
])
def test_scenario_manifest_contract(change, expected):
    inventory = inventory_demo_bundle("demo/index.html", demo_files())
    scenario = scenario_fixture(inventory)
    limits = {"maxDiscoveryRounds": 2, "maxScenarioSteps": 3, "maxScreenshots": 2}
    if change == "unknown":
        scenario["scenarios"][0]["steps"][0]["interactionId"] = "unknown"
    if change == "round":
        scenario["round"] = 3
    if change == "steps":
        limits["maxScenarioSteps"] = 0
    if change == "screenshots":
        limits["maxScreenshots"] = 0
    if change == "schema":
        scenario["invented"] = True
    if change == "bundle":
        scenario["bundleSha256"] = "0" * 64
    if expected:
        with pytest.raises(ValueError) as failure:
            verify_scenario_manifest(inventory, scenario, limits, round=scenario["round"])
        assert failure.value.code == expected
    else:
        before = copy.deepcopy(scenario)
        assert verify_scenario_manifest(inventory, scenario, limits, round=1) == scenario
        assert scenario == before


def trace_fixture(inventory, scenario):
    """Synthetic typed transport fixture; never claimed as real browser execution."""
    profile = {"browserVersion": "Chromium-fixture-1", "viewport": {"width": 1280, "height": 720}, "dpr": 1,
               "locale": "zh-CN", "timezone": "Asia/Shanghai", "cleanProfile": True, "emptyStorage": True,
               "clockPolicy": "fixed:2026-09-05T00:00:00Z", "randomPolicy": "seed:1", "waitPolicy": "dom-assertion-stable:100ms"}
    runs = []
    for item in scenario["scenarios"]:
        steps = []
        for step in item["steps"]:
            steps.append({key: copy.deepcopy(value) for key, value in step.items() if key not in {"screenshot", "assertions"}} | {
                "assertions": [assertion | {"actual": assertion["expected"], "passed": True} for assertion in step["assertions"]],
                "screenshotSha256": "a" * 64 if step["screenshot"] else None,
                "eventObserved": step["interactionId"] is not None})
        for replay in range(2 if item["critical"] else 1):
            runs.append({"scenarioId": item["scenarioId"], "replay": replay, "stable": True,
                         "browserProfileSha256": sha256_bytes(canonical_json_bytes(profile)), "steps": copy.deepcopy(steps)})
    return {"bundleSha256": inventory["bundleSha256"], "scenarioSha256": sha256_bytes(canonical_json_bytes(scenario)),
            "browserProfile": profile, "files": [{"relativePath": item["relativePath"], "sha256": item["sha256"]} for item in inventory["files"]],
            "externalRequestCount": 0, "unresolvedDiscoveries": [], "runs": runs}


def observation_fixture(inventory, local_key="save"):
    return {"localKey": local_key, "behavior": {"page": inventory["entrypoint"], "trigger": "点击提交", "resultingState": "显示成功"},
            "evidenceIds": inventory["interactions"][0]["evidenceIds"], "interactionIds": [inventory["interactions"][0]["interactionId"]],
            "scopeRelation": "ADDITIONAL", "runtimeStatus": "OBSERVED", "relatedFactIds": []}


@pytest.mark.parametrize("change", ["valid", "bundle", "scenario", "version", "viewport", "dpr", "locale", "timezone", "profile", "storage", "clock", "random", "wait", "file", "operation", "assertion", "screenshot", "external", "run-profile", "step-order"])
def test_trace_binding(change):
    inventory = inventory_demo_bundle("demo/index.html", demo_files())
    scenario = scenario_fixture(inventory)
    trace = trace_fixture(inventory, scenario)
    profile = trace["browserProfile"]
    if change in {"bundle", "scenario"}: trace[change + "Sha256"] = "0" * 64
    profile_keys = {"version": "browserVersion", "locale": "locale", "timezone": "timezone", "clock": "clockPolicy", "random": "randomPolicy", "wait": "waitPolicy"}
    if change in profile_keys: profile[profile_keys[change]] = " "
    if change == "viewport": profile["viewport"]["width"] = 0
    if change == "dpr": profile["dpr"] = 0
    if change == "profile": profile["cleanProfile"] = False
    if change == "storage": profile["emptyStorage"] = False
    if change == "file": trace["files"][0]["sha256"] = "0" * 64
    if change == "operation": trace["runs"][0]["steps"][0]["operation"] = "fill"
    if change == "assertion": trace["runs"][0]["steps"][0]["assertions"][0]["actual"] = "wrong"
    if change == "screenshot": trace["runs"][0]["steps"][0]["screenshotSha256"] = "invalid"
    if change == "external": trace["externalRequestCount"] = 1
    if change == "run-profile": trace["runs"][0]["browserProfileSha256"] = "0" * 64
    if change == "step-order": trace["runs"][0]["steps"][0]["stepId"] = "different"
    if change == "valid":
        verified = verify_prototype_trace(inventory, scenario, trace)
        assert verified["interactionDispositions"] == [{"interactionId": inventory["interactions"][0]["interactionId"], "disposition": "OBSERVED"}]
    else:
        with pytest.raises(ValueError): verify_prototype_trace(inventory, scenario, trace)


def test_prototype_analyze_scope_handoff_normalizes_only_observation_sets():
    from contracts import action_contract_binding, normalize_action_result, InvalidActionResult
    inventory = inventory_demo_bundle("demo/index.html", demo_files())
    a, b = observation_fixture(inventory, "z"), observation_fixture(inventory, "a")
    a["evidenceIds"] = ["evidence-z", "evidence-a"]
    a["interactionIds"] = ["interaction-z", "interaction-a"]
    a["relatedFactIds"] = ["fact-z", "fact-a"]
    one = {"observations": [a, b]}
    two = copy.deepcopy(one)
    two["observations"].reverse()
    for key in ("evidenceIds", "interactionIds", "relatedFactIds"):
        two["observations"][1][key].reverse()
    contract, digest = action_contract_binding(SKILL_ROOT, "PROTOTYPE_ANALYZE-v1")
    envelope = {"actionContractId": contract["actionContractId"], "actionContractSha256": digest}
    first, second = canonical_json_bytes(one), canonical_json_bytes(two)
    assert sha256_bytes(first) != sha256_bytes(second)
    assert normalize_action_result(envelope, first, skill_root=SKILL_ROOT) == normalize_action_result(envelope, second, skill_root=SKILL_ROOT)
    with pytest.raises(InvalidActionResult):
        normalize_action_result(envelope, canonical_json_bytes({"observations": [a, a]}), skill_root=SKILL_ROOT)


@pytest.mark.parametrize("critical,unstable,replay", [(True, False, True), (True, False, False), (False, True, True), (False, True, False), (False, False, False)])
def test_interaction_coverage_replays_critical_or_unstable_once(critical, unstable, replay):
    inventory = inventory_demo_bundle("demo/index.html", demo_files())
    scenario = scenario_fixture(inventory)
    scenario["scenarios"][0]["critical"] = critical
    trace = trace_fixture(inventory, scenario)
    trace["runs"] = trace["runs"][:1]
    trace["runs"][0]["stable"] = not unstable
    if replay:
        trace["runs"].append(copy.deepcopy(trace["runs"][0]) | {"replay": 1, "stable": True})
    if (critical or unstable) and not replay:
        with pytest.raises(ValueError) as failure:
            verify_prototype_trace(inventory, scenario, trace)
        assert failure.value.code == "INCOMPLETE_BUDGET"
    else:
        assert verify_prototype_trace(inventory, scenario, trace)["interactionDispositions"][0]["disposition"] == "OBSERVED"


def unresolved_discovery(inventory):
    return {"page": inventory["entrypoint"], "selector": "#new-control", "event": "click",
            "sourceEvidenceIds": inventory["interactions"][0]["evidenceIds"], "domExcerpt": '<button id="new-control">新增</button>', "screenshotSha256": "a" * 64}


@pytest.mark.parametrize("change", ["valid", "missing", "unknown-source", "unknown-page", "blank-dom", "unbound-image", "invented-id"])
def test_interaction_coverage_unresolved_discovery_preserves_bound_evidence(change):
    inventory = inventory_demo_bundle("demo/index.html", demo_files())
    scenario = scenario_fixture(inventory)
    trace = trace_fixture(inventory, scenario)
    discovery = unresolved_discovery(inventory)
    trace["unresolvedDiscoveries"] = [discovery]
    if change == "missing": del trace["unresolvedDiscoveries"]
    if change == "unknown-source": discovery["sourceEvidenceIds"] = ["fake"]
    if change == "unknown-page": discovery["page"] = "not-a-route.html"
    if change == "blank-dom": discovery["domExcerpt"] = " "
    if change == "unbound-image": discovery["screenshotSha256"] = "b" * 64
    if change == "invented-id": discovery["interactionId"] = "fake"
    if change == "valid":
        assert verify_prototype_trace(inventory, scenario, trace)["unresolvedDiscoveryCount"] == 1
    else:
        with pytest.raises(ValueError): verify_prototype_trace(inventory, scenario, trace)


def test_trace_binding_normalization_preserves_sequences_and_sorts_discovery_sources():
    from contracts import action_contract_binding, normalize_action_result
    inventory = inventory_demo_bundle("demo/index.html", demo_files())
    scenario = scenario_fixture(inventory)
    trace = trace_fixture(inventory, scenario)
    trace["unresolvedDiscoveries"] = [unresolved_discovery(inventory), unresolved_discovery(inventory) | {"selector": "#another"}]
    trace["unresolvedDiscoveries"][0]["sourceEvidenceIds"] = ["source-z", "source-a"]
    other = copy.deepcopy(trace)
    other["unresolvedDiscoveries"][0]["sourceEvidenceIds"].reverse()
    contract, digest = action_contract_binding(SKILL_ROOT, "PROTOTYPE_BROWSER-v1")
    envelope = {"actionContractId": contract["actionContractId"], "actionContractSha256": digest}
    normalize = lambda value: normalize_action_result(envelope, canonical_json_bytes(value), skill_root=SKILL_ROOT)
    assert canonical_json_bytes(trace) != canonical_json_bytes(other)
    assert normalize(trace) == normalize(other)
    other["unresolvedDiscoveries"].reverse()
    assert normalize(trace) != normalize(other)
    trace["runs"][0]["steps"].append(copy.deepcopy(trace["runs"][0]["steps"][0]) | {"stepId": "second"})
    other = copy.deepcopy(trace)
    other["runs"][0]["steps"].reverse()
    assert normalize(trace) != normalize(other)


@pytest.mark.parametrize("status,source,runtime,expected", [
    ("OBSERVED", True, True, None), ("OBSERVED", False, True, "PROTOTYPE_SOURCE_EVIDENCE_REQUIRED"),
    ("OBSERVED", True, False, "PROTOTYPE_RUNTIME_EVIDENCE_REQUIRED"),
    ("CODE_ONLY", True, False, None), ("CODE_ONLY", False, False, "PROTOTYPE_SOURCE_EVIDENCE_REQUIRED"),
    ("BROKEN", True, False, "PROTOTYPE_SCOPE_EVIDENCE_REQUIRED"),
    ("NOT_EXERCISED", True, False, "PROTOTYPE_SCOPE_EVIDENCE_REQUIRED"),
])
def test_demo_scope_semantics_candidate_authority(status, source, runtime, expected):
    inventory = inventory_demo_bundle("demo/index.html", demo_files())
    scenario = scenario_fixture(inventory)
    trace = trace_fixture(inventory, scenario)
    observation = observation_fixture(inventory)
    observation["runtimeStatus"] = status
    if not source: observation["evidenceIds"] = []
    if not runtime: observation["interactionIds"] = []
    if expected:
        with pytest.raises(ValueError) as failure:
            verify_prototype_observations(inventory, scenario, trace, {"observations": [observation]})
        assert failure.value.code == expected
    else:
        result = verify_prototype_observations(inventory, scenario, trace, {"observations": [observation]})
        assert result == {"authority": "TARGET_SCOPE_ONLY", "requiresIntentReviewLocalKeys": ["save"] if status == "CODE_ONLY" else []}


def prototype_repair_packet(bad, diagnostic):
    from action_ledger import diagnostic_value
    return {"workItems": [], "contextRefs": [{"refId": "repair-from-attempt-synthetic",
        "canonicalContent": {"kind": "ATTEMPT_REPAIR", "rawOutputUtf8": canonical_json_bytes(bad).decode(),
            "diagnostic": diagnostic_value(diagnostic)}}]}


def prototype_candidate_case():
    inventory = inventory_demo_bundle("demo/index.html", demo_files())
    scenario = scenario_fixture(inventory)
    scenario["scenarios"].append(copy.deepcopy(scenario["scenarios"][0]) | {"scenarioId": "untouched"})
    scenario["scenarios"][1]["steps"][0]["stepId"] = "untouched-step"
    payload = {"inventory": inventory, "identity": {"round": 1},
        "demoLimits": {"maxDiscoveryRounds": 2, "maxScenarioSteps": 30, "maxScreenshots": 12},
        "demoRemaining": {}, "scenario": {"normalizedResult": scenario},
        "trace": {"normalizedResult": trace_fixture(inventory, scenario)}}
    return inventory, scenario, payload


@pytest.mark.parametrize("kind", ["PROTOTYPE_SCENARIO", "PROTOTYPE_ANALYZE"])
def test_prototype_candidate_repair_preserves_unrelated_objects(kind):
    from contracts import InvalidActionResult
    from prototype_analysis import validate_bound_prototype_result
    inventory, scenario, payload = prototype_candidate_case()
    if kind == "PROTOTYPE_SCENARIO":
        good, collection = scenario, "scenarios"
        bad = copy.deepcopy(good)
        bad[collection][0]["steps"][0]["selector"] = "#unknown"
        subject = good[collection][0]["scenarioId"]
        expected_path = "/scenarios/0/steps/0/selector"
    else:
        good, collection = {"observations": [observation_fixture(inventory), observation_fixture(inventory, "untouched")]}, "observations"
        bad = copy.deepcopy(good)
        bad[collection][0]["evidenceIds"] = ["unknown-source"]
        subject = "save"
        expected_path = "/observations/0/evidenceIds"
    with pytest.raises(InvalidActionResult) as failure:
        validate_bound_prototype_result(kind, payload, canonical_json_bytes(bad))
    assert failure.value.diagnostic.subject_ids == (subject,)
    assert failure.value.diagnostic.path == expected_path
    packet = prototype_repair_packet(bad, failure.value.diagnostic)
    validate_bound_prototype_result(kind, payload, canonical_json_bytes(good), packet=packet)
    changed = copy.deepcopy(good)
    if kind == "PROTOTYPE_SCENARIO": changed[collection][1]["critical"] = not changed[collection][1]["critical"]
    else: changed[collection][1]["behavior"]["trigger"] = "无关改写"
    with pytest.raises(InvalidActionResult) as protected:
        validate_bound_prototype_result(kind, payload, canonical_json_bytes(changed), packet=packet)
    assert protected.value.diagnostic.code == "REPAIR_SCOPE_VIOLATION"
    assert protected.value.diagnostic.subject_ids == ("untouched",)
    added = copy.deepcopy(good)
    new = copy.deepcopy(good[collection][0])
    new["scenarioId" if kind == "PROTOTYPE_SCENARIO" else "localKey"] = "unrelated-new"
    added[collection].append(new)
    with pytest.raises(InvalidActionResult) as protected:
        validate_bound_prototype_result(kind, payload, canonical_json_bytes(added), packet=packet)
    assert protected.value.diagnostic.code == "REPAIR_SCOPE_VIOLATION"


def test_scenario_binding_field_repair_keeps_all_scenarios():
    from contracts import InvalidActionResult
    from prototype_analysis import validate_bound_prototype_result
    _, good, payload = prototype_candidate_case()
    bad = copy.deepcopy(good); bad["bundleSha256"] = "0" * 64
    with pytest.raises(InvalidActionResult) as failure:
        validate_bound_prototype_result("PROTOTYPE_SCENARIO", payload, canonical_json_bytes(bad))
    assert failure.value.diagnostic.path == "/bundleSha256"
    packet = prototype_repair_packet(bad, failure.value.diagnostic)
    validate_bound_prototype_result("PROTOTYPE_SCENARIO", payload, canonical_json_bytes(good), packet=packet)
    changed = copy.deepcopy(good); changed["scenarios"][0]["critical"] = not changed["scenarios"][0]["critical"]
    with pytest.raises(InvalidActionResult) as protected:
        validate_bound_prototype_result("PROTOTYPE_SCENARIO", payload, canonical_json_bytes(changed), packet=packet)
    assert protected.value.diagnostic.code == "REPAIR_SCOPE_VIOLATION"


def test_scenario_duplicate_step_diagnostic_includes_both_owning_roots():
    from contracts import InvalidActionResult
    from prototype_analysis import validate_bound_prototype_result
    _, bad, payload = prototype_candidate_case()
    bad["scenarios"][1]["steps"][0]["stepId"] = bad["scenarios"][0]["steps"][0]["stepId"]
    with pytest.raises(InvalidActionResult) as failure:
        validate_bound_prototype_result("PROTOTYPE_SCENARIO", payload, canonical_json_bytes(bad))
    assert failure.value.diagnostic.subject_ids == tuple(sorted([bad["scenarios"][0]["scenarioId"], "untouched"]))
    assert failure.value.diagnostic.path == "/scenarios/1/steps/0/stepId"
    good = copy.deepcopy(bad); good["scenarios"][0]["steps"][0]["stepId"] = "corrected-first"
    validate_bound_prototype_result("PROTOTYPE_SCENARIO", payload, canonical_json_bytes(good),
        packet=prototype_repair_packet(bad, failure.value.diagnostic))


def test_scenario_repair_preserves_unrelated_execution_order():
    from contracts import InvalidActionResult
    from prototype_analysis import validate_bound_prototype_result
    _, good, payload = prototype_candidate_case()
    third = copy.deepcopy(good["scenarios"][1]) | {"scenarioId": "third"}
    third["steps"][0]["stepId"] = "third-step"
    good["scenarios"].append(third)
    bad = copy.deepcopy(good); bad["scenarios"][0]["steps"][0]["selector"] = "#unknown"
    with pytest.raises(InvalidActionResult) as failure:
        validate_bound_prototype_result("PROTOTYPE_SCENARIO", payload, canonical_json_bytes(bad))
    packet = prototype_repair_packet(bad, failure.value.diagnostic)
    changed = copy.deepcopy(good); changed["scenarios"].reverse()
    with pytest.raises(InvalidActionResult) as protected:
        validate_bound_prototype_result("PROTOTYPE_SCENARIO", payload, canonical_json_bytes(changed), packet=packet)
    assert protected.value.diagnostic.code == "REPAIR_SCOPE_VIOLATION"
    assert set(protected.value.diagnostic.subject_ids) == {"untouched", "third"}
