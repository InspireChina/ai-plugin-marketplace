from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import posixpath
import re
from pathlib import PurePosixPath
from pathlib import Path
from urllib.parse import unquote, urlsplit

from contracts import canonical_json_bytes, sha256_bytes, load_registry, validate_contract, InvalidActionResult
from source_readers import html_elements, PROTOTYPE_BINARY_SUFFIXES
from models import AttemptDiagnostic


class PrototypeError(ValueError):
    def __init__(self, code: str, path: str = "", subject_ids=()):
        self.code = code
        self.diagnostic = AttemptDiagnostic(code, path, tuple(sorted(set(subject_ids)))) if path else None
        super().__init__(code)


def _relative(path: str) -> str:
    if not path or path.startswith("/") or "\\" in path or ":" in path or ".." in path.split("/"):
        raise PrototypeError("DEMO_PATH_UNSAFE")
    return posixpath.normpath(path)


def inventory_demo_bundle(entrypoint: str, files: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Inventory declared revision-relative files with their original content bytes."""
    entrypoint = _relative(entrypoint)
    declared = {_relative(str(file["relativePath"])) for file in files}
    if entrypoint not in declared:
        raise PrototypeError("DEMO_ENTRYPOINT_MISSING")
    root = posixpath.dirname(entrypoint)
    if any(root and not path.startswith(root + "/") for path in declared):
        raise PrototypeError("DEMO_OUTSIDE_BUNDLE")
    if any(PurePosixPath(path).name in {"package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"} or PurePosixPath(path).name.startswith(("vite.config.", "webpack.config.")) for path in declared):
        raise PrototypeError("DEMO_BUILD_UNSUPPORTED")
    if len(declared) != len(files) or len({file["sourceId"] for file in files}) != len(files):
        raise PrototypeError("DEMO_FILE_DUPLICATE")
    inventory = {"entrypoint": entrypoint, "files": [], "references": [], "routes": [],
                 "controls": [], "events": [], "states": [], "interactions": [], "evidence": []}
    script_edges = {}
    javascript_sources = {}

    def reference(source, target, ordinary_link=False):
        parts = urlsplit(target)
        if parts.scheme or parts.netloc:
            if not ordinary_link:
                raise PrototypeError("DEMO_REMOTE_DEPENDENCY")
            inventory["references"].append({"source": source, "target": target, "executable": False})
            return
        if not parts.path:
            return
        target = posixpath.join(posixpath.dirname(source), _relative(unquote(parts.path)))
        target = posixpath.normpath(target)
        if target not in declared:
            raise PrototypeError("DEMO_DEPENDENCY_UNDECLARED")
        inventory["references"].append({"source": source, "target": target, "executable": True})
        return target

    def css_references(path, text):
        for match in re.finditer(r"(?:url\(\s*['\"]?|@import\s+['\"])([^'\")\s;]+)", text):
            reference(path, match[1])

    def javascript_references(path, text):
        javascript_sources.setdefault(path, []).append(text)
        for match in re.finditer(r"(\bimport\s*(?:\(\s*)?|\bfrom\s*|\bfetch\(\s*)['\"]([^'\"]+)['\"]", text):
            target = reference(path, match[2])
            if target and not match[1].startswith("fetch"):
                script_edges.setdefault(path, set()).add(target)

    for file in sorted(files, key=lambda item: item["relativePath"]):
        path, content = str(file["relativePath"]), file["content"]
        digest = sha256_bytes(content)
        suffix = PurePosixPath(path).suffix.lower()
        evidence_id = "evidence-" + sha256_bytes(canonical_json_bytes([file["sourceId"], path, digest]))
        inventory["files"].append({"sourceId": file["sourceId"], "relativePath": path, "sha256": digest,
                                   "mediaType": {".html": "text/html", ".htm": "text/html", ".css": "text/css", ".js": "text/javascript"}.get(suffix, "application/octet-stream")})
        text = "" if suffix in PROTOTYPE_BINARY_SUFFIXES else content.decode("utf-8")
        inventory["evidence"].append({"evidenceId": evidence_id, "sourceId": file["sourceId"], "relativePath": path, "sha256": digest, "content": text})
        if suffix in {".html", ".htm"}:
            inventory["routes"].append(path)
            for index, element in enumerate(html_elements(text)):
                tag, attrs = element["tag"], element["attributes"]
                executable_script = tag == "script" and attrs.get("type", "").lower() in {"", "module", "text/javascript", "application/javascript"}
                selector = "#" + attrs["id"] if attrs.get("id") else element["selector"]
                for attr in ("src", "href"):
                    if attrs.get(attr):
                        target = reference(path, attrs[attr], tag == "a" and attr == "href")
                        if executable_script and attr == "src" and target:
                            script_edges.setdefault(path, set()).add(target)
                if attrs.get("srcset"):
                    for candidate in attrs["srcset"].split(","):
                        if candidate.strip():
                            reference(path, candidate.split()[0])
                if attrs.get("style"):
                    css_references(path, attrs["style"])
                if tag == "style":
                    css_references(path, element["content"])
                if executable_script:
                    javascript_references(path, element["content"])
                if tag in {"button", "input", "select", "textarea", "a", "form"}:
                    inventory["controls"].append({"page": path, "selector": selector, "tag": tag, "evidenceIds": [evidence_id]})
                    default_event = "click" if tag in {"button", "a"} else "change"
                    input_type = (attrs.get("type") or "text").lower()
                    if tag == "textarea" or (tag == "input" and input_type in {"text", "search", "email", "url", "tel", "password", "number"}):
                        default_event = "input"
                    elif tag == "input" and input_type in {"button", "submit", "reset"}:
                        default_event = "click"
                    interaction = {"page": path, "selector": selector, "event": default_event, "evidenceIds": [evidence_id]}
                    inventory["interactions"].append({"interactionId": "interaction-" + sha256_bytes(canonical_json_bytes(interaction)), **interaction})
                for attr, value in attrs.items():
                    if attr.startswith("on") and value:
                        event = {"page": path, "selector": selector, "event": attr[2:], "evidenceIds": [evidence_id]}
                        inventory["events"].append({"relativePath": path, "event": attr[2:], "evidenceIds": [evidence_id]})
                        if not any(all(item[key] == event[key] for key in ("page", "selector", "event")) for item in inventory["interactions"]):
                            inventory["interactions"].append({"interactionId": "interaction-" + sha256_bytes(canonical_json_bytes(event)), **event})
                    if attr.startswith("data-") or attr in {"hidden", "disabled", "required", "checked"}:
                        inventory["states"].append({"page": path, "selector": selector, "attribute": attr, "value": value, "evidenceIds": [evidence_id]})
        for match in re.finditer(r"addEventListener\(\s*['\"]([^'\"]+)['\"]", text):
            inventory["events"].append({"relativePath": path, "event": match[1], "evidenceIds": [evidence_id]})
        if suffix == ".css":
            css_references(path, text)
        if suffix == ".js":
            javascript_references(path, text)
    evidence_by_path = {item["relativePath"]: item["evidenceId"] for item in inventory["evidence"]}
    listener_pattern = r"\bdocument\s*\.\s*querySelector\s*\(\s*(['\"])([^'\"\\]+)\1\s*\)\s*\.\s*addEventListener\s*\(\s*(['\"])([A-Za-z][A-Za-z0-9:_-]*)\3\s*,"
    for page in inventory["routes"]:
        pending, reachable = [page], set()
        while pending:
            source = pending.pop()
            if source in reachable:
                continue
            reachable.add(source)
            pending.extend(sorted(script_edges.get(source, set())))
        for source in sorted(reachable):
            for text in javascript_sources.get(source, []):
                for match in re.finditer(listener_pattern, text):
                    selector, event = match[2], match[4]
                    if not selector.strip() or any(item["page"] == page and item["selector"] == selector and item["event"] == event for item in inventory["interactions"]):
                        continue
                    interaction = {"page": page, "selector": selector, "event": event,
                                   "evidenceIds": sorted({evidence_by_path[page], evidence_by_path[source]})}
                    inventory["interactions"].append({"interactionId": "interaction-" + sha256_bytes(canonical_json_bytes(interaction)), **interaction})
        if not any(item["page"] == page for item in inventory["interactions"]):
            evidence_id = next(item["evidenceId"] for item in inventory["evidence"] if item["relativePath"] == page)
            interaction = {"page": page, "selector": "html", "event": "navigate", "evidenceIds": [evidence_id]}
            inventory["interactions"].append({"interactionId": "interaction-" + sha256_bytes(canonical_json_bytes(interaction)), **interaction})
    inventory["bundleSha256"] = sha256_bytes(canonical_json_bytes({"entrypoint": entrypoint, "files": inventory["files"]}))
    inventory["bundleId"] = "bundle-" + inventory["bundleSha256"]
    return inventory


def _verify_scenario_bindings(inventory, scenario, round, *, diagnostics=None):
    def emit(error):
        if diagnostics is None: raise error
        diagnostics.append(error.diagnostic)
    if scenario["bundleSha256"] != inventory["bundleSha256"]:
        emit(PrototypeError("PROTOTYPE_BUNDLE_MISMATCH", "/bundleSha256"))
    if scenario["round"] != round:
        emit(PrototypeError("PROTOTYPE_SCENARIO_INVALID", "/round"))
    interaction_ids = {item["interactionId"] for item in inventory["interactions"]}
    scenarios = scenario["scenarios"]
    scenario_keys, step_owners = set(), {}
    operations = {"navigate": {"navigate"}, "click": {"click"}, "fill": {"input"},
                  "select": {"input", "change"}, "check": {"input", "change", "click"},
                  "press": {"keydown", "keyup"}, "wait": set()}
    interactions = {item["interactionId"]: item for item in inventory["interactions"]}
    for index, item in enumerate(scenarios):
        path, subject = "/scenarios/" + str(index), item["scenarioId"]
        if subject in scenario_keys:
            emit(PrototypeError("PROTOTYPE_SCENARIO_INVALID", path + "/scenarioId", (subject,)))
        scenario_keys.add(subject)
        if not set(item["interactionIds"]) <= interaction_ids:
            emit(PrototypeError("PROTOTYPE_INTERACTION_UNKNOWN", path + "/interactionIds", (subject,)))
        for position, step in enumerate(item["steps"]):
            step_path = path + "/steps/" + str(position)
            if step["stepId"] in step_owners:
                emit(PrototypeError("PROTOTYPE_SCENARIO_INVALID", step_path + "/stepId",
                                     (subject, step_owners[step["stepId"]])))
            step_owners[step["stepId"]] = subject
            if step["interactionId"] is not None and step["interactionId"] not in interaction_ids:
                emit(PrototypeError("PROTOTYPE_INTERACTION_UNKNOWN", step_path + "/interactionId", (subject,)))
            if step["page"] not in inventory["routes"]:
                emit(PrototypeError("PROTOTYPE_SCENARIO_INVALID", step_path + "/page", (subject,)))
            if step["operation"] == "navigate" and step["value"] not in {None, step["page"]}:
                emit(PrototypeError("PROTOTYPE_SCENARIO_INVALID", step_path + "/value", (subject,)))
            if step["interactionId"] not in interactions:
                continue
            interaction = interactions[step["interactionId"]]
            for field in ("page", "selector"):
                if step[field] != interaction[field]:
                    emit(PrototypeError("PROTOTYPE_SCENARIO_INVALID", step_path + "/" + field, (subject,)))
            if interaction["event"] not in operations[step["operation"]]:
                emit(PrototypeError("PROTOTYPE_SCENARIO_INVALID", step_path + "/operation", (subject,)))
        if set(item["interactionIds"]) != {step["interactionId"] for step in item["steps"] if step["interactionId"] is not None}:
            emit(PrototypeError("PROTOTYPE_SCENARIO_INVALID", path + "/interactionIds", (subject,)))


def verify_scenario_manifest(inventory, scenario, limits, *, round):
    """Validate model bindings and declared limits without planning scenarios."""
    registry = load_registry(Path(__file__).parents[1] / "contracts")
    if validate_contract(scenario, "prototype-scenario.schema.json", registry):
        raise PrototypeError("PROTOTYPE_SCENARIO_INVALID")
    return _verify_scenario_plan(inventory, scenario, limits, round)


def _verify_scenario_plan(inventory, scenario, limits, round):
    _verify_scenario_bindings(inventory, scenario, round)
    steps = [step for item in scenario["scenarios"] for _ in range(2 if item["critical"] else 1) for step in item["steps"]]
    if round > limits["maxDiscoveryRounds"] or len(steps) > limits["maxScenarioSteps"] or sum(step["screenshot"] for step in steps) > limits["maxScreenshots"]:
        raise PrototypeError("INCOMPLETE_BUDGET", "/scenarios",
                             tuple(item["scenarioId"] for item in scenario["scenarios"]))
    return scenario


def verify_prototype_trace(inventory, scenario, trace):
    """Verify typed host evidence without launching or installing a browser."""
    registry = load_registry(Path(__file__).parents[1] / "contracts")
    if validate_contract(trace, "prototype-trace.schema.json", registry) or validate_contract(scenario, "prototype-scenario.schema.json", registry):
        raise PrototypeError("PROTOTYPE_TRACE_INVALID")
    return _verify_trace_bindings(inventory, scenario, trace)


def _verify_trace_bindings(inventory, scenario, trace):
    _verify_scenario_bindings(inventory, scenario, scenario["round"])
    if trace["bundleSha256"] != inventory["bundleSha256"] or trace["scenarioSha256"] != sha256_bytes(canonical_json_bytes(scenario)):
        raise PrototypeError("PROTOTYPE_TRACE_BINDING_INVALID")
    if trace["files"] != [{"relativePath": item["relativePath"], "sha256": item["sha256"]} for item in inventory["files"]]:
        raise PrototypeError("PROTOTYPE_SOURCE_CHANGED")
    profile_hash = sha256_bytes(canonical_json_bytes(trace["browserProfile"]))
    dispositions = {}
    pairs = []
    position = 0
    incomplete = False
    unstable = False
    for expected in scenario["scenarios"]:
        if position >= len(trace["runs"]):
            incomplete = True
            continue
        first = trace["runs"][position]
        if first["scenarioId"] != expected["scenarioId"] or first["replay"] != 0:
            raise PrototypeError("PROTOTYPE_TRACE_RUNS_INVALID")
        pairs.append((expected, first))
        position += 1
        if expected["critical"] or not first["stable"]:
            if position >= len(trace["runs"]):
                incomplete = True
                continue
            replay = trace["runs"][position]
            if replay["scenarioId"] != expected["scenarioId"]:
                incomplete = True
                continue
            if replay["replay"] != 1:
                raise PrototypeError("PROTOTYPE_TRACE_RUNS_INVALID")
            if not replay["stable"] or replay["steps"] != first["steps"]:
                unstable = True
            pairs.append((expected, replay))
            position += 1
    if position != len(trace["runs"]):
        raise PrototypeError("PROTOTYPE_TRACE_RUNS_INVALID")
    for expected, actual in pairs:
        if actual["scenarioId"] != expected["scenarioId"] or actual["browserProfileSha256"] != profile_hash or len(actual["steps"]) != len(expected["steps"]):
            raise PrototypeError("PROTOTYPE_TRACE_RUNS_INVALID")
        for step, result in zip(expected["steps"], actual["steps"], strict=True):
            if any(step[key] != result[key] for key in ("stepId", "page", "interactionId", "operation", "selector", "value")):
                raise PrototypeError("PROTOTYPE_TRACE_STEP_INVALID")
            assertions = [{key: item[key] for key in ("selector", "attribute", "expected")} for item in result["assertions"]]
            if assertions != step["assertions"] or any(item["passed"] != (item["actual"] == item["expected"]) for item in result["assertions"]):
                raise PrototypeError("PROTOTYPE_TRACE_ASSERTION_INVALID")
            if step["screenshot"] != (result["screenshotSha256"] is not None):
                raise PrototypeError("PROTOTYPE_TRACE_SCREENSHOT_INVALID")
            if step["interactionId"] is None:
                if result["eventObserved"]:
                    raise PrototypeError("PROTOTYPE_TRACE_STEP_INVALID")
                continue
            disposition = "OBSERVED" if result["eventObserved"] and all(item["passed"] for item in result["assertions"]) else "BROKEN"
            if dispositions.get(step["interactionId"]) != "BROKEN":
                dispositions[step["interactionId"]] = disposition
    source_ids = {item["evidenceId"] for item in inventory["evidence"] if item["content"]}
    screenshots = {step["screenshotSha256"] for run in trace["runs"] for step in run["steps"] if step["screenshotSha256"]}
    for discovery in trace["unresolvedDiscoveries"]:
        if discovery["page"] not in inventory["routes"] or not set(discovery["sourceEvidenceIds"]) <= source_ids or discovery["screenshotSha256"] not in screenshots:
            raise PrototypeError("PROTOTYPE_DISCOVERY_BINDING_INVALID")
    if incomplete:
        raise PrototypeError("INCOMPLETE_BUDGET")
    if unstable:
        raise PrototypeError("PROTOTYPE_UNSTABLE")
    return {"interactionDispositions": [{"interactionId": key, "disposition": value} for key, value in sorted(dispositions.items())],
            "stepCount": sum(len(run["steps"]) for run in trace["runs"]),
            "unresolvedDiscoveryCount": len(trace["unresolvedDiscoveries"]),
            "screenshotCount": sum(step["screenshotSha256"] is not None for run in trace["runs"] for step in run["steps"])}


def verify_prototype_observations(inventory, scenario, trace, result):
    """Validate this round's target-scope evidence; formal review is downstream."""
    registry = load_registry(Path(__file__).parents[1] / "contracts")
    if validate_contract(result, "prototype-observation.schema.json", registry):
        raise PrototypeError("PROTOTYPE_OBSERVATION_INVALID")
    verify_prototype_trace(inventory, scenario, trace)
    return _verify_observation_bindings(inventory, scenario, trace, result)


def _verify_observation_bindings(inventory, scenario, trace, result, *, diagnostics=None):
    def emit(error):
        if diagnostics is None: raise error
        diagnostics.append(error.diagnostic)
    evidence = _verify_trace_bindings(inventory, scenario, trace)
    if evidence["unresolvedDiscoveryCount"]:
        emit(PrototypeError("PROTOTYPE_UNRESOLVED_DISCOVERY"))
    source_ids = {item["evidenceId"] for item in inventory["evidence"] if item["content"]}
    interaction_ids = {item["interactionId"] for item in inventory["interactions"]}
    observed = {item["interactionId"] for item in evidence["interactionDispositions"] if item["disposition"] == "OBSERVED"}
    local_keys = [item["localKey"] for item in result["observations"]]
    if len(set(local_keys)) != len(local_keys):
        duplicate = next(key for key in local_keys if local_keys.count(key) > 1)
        emit(PrototypeError("PROTOTYPE_OBSERVATION_INVALID", "/observations/" + str(local_keys.index(duplicate)) + "/localKey", (duplicate,)))
    intent_review = []
    for index, observation in enumerate(result["observations"]):
        path, subject = "/observations/" + str(index), (observation["localKey"],)
        if not observation["evidenceIds"] or not set(observation["evidenceIds"]) <= source_ids:
            emit(PrototypeError("PROTOTYPE_SOURCE_EVIDENCE_REQUIRED", path + "/evidenceIds", subject))
        if observation["behavior"]["page"] not in inventory["routes"]:
            emit(PrototypeError("PROTOTYPE_OBSERVATION_INVALID", path + "/behavior/page", subject))
        if not set(observation["interactionIds"]) <= interaction_ids:
            emit(PrototypeError("PROTOTYPE_OBSERVATION_INVALID", path + "/interactionIds", subject))
        if observation["runtimeStatus"] == "OBSERVED" and (not observation["interactionIds"] or not set(observation["interactionIds"]) <= observed):
            emit(PrototypeError("PROTOTYPE_RUNTIME_EVIDENCE_REQUIRED", path + "/interactionIds", subject))
        if observation["runtimeStatus"] == "OBSERVED" and any(item["page"] != observation["behavior"]["page"] for item in inventory["interactions"] if item["interactionId"] in observation["interactionIds"]):
            emit(PrototypeError("PROTOTYPE_RUNTIME_EVIDENCE_REQUIRED", path + "/interactionIds", subject))
    for index, observation in enumerate(result["observations"]):
        if observation["scopeRelation"] in {"CONFIRMS", "SUPPLEMENTS", "ADDITIONAL"}:
            if observation["runtimeStatus"] in {"BROKEN", "NOT_EXERCISED"}:
                emit(PrototypeError("PROTOTYPE_SCOPE_EVIDENCE_REQUIRED", "/observations/" + str(index) + "/runtimeStatus", (observation["localKey"],)))
            if observation["runtimeStatus"] == "CODE_ONLY":
                intent_review.append(observation["localKey"])
    return {"authority": "TARGET_SCOPE_ONLY", "requiresIntentReviewLocalKeys": sorted(intent_review)}


def validate_bound_prototype_context(action_kind, payload) -> None:
    """Validate authorized predecessor schemas before entering the pure callback."""
    if action_kind in {"PROTOTYPE_BROWSER", "PROTOTYPE_ANALYZE"}:
        verify_scenario_manifest(payload["inventory"], payload["scenario"]["normalizedResult"],
            {**payload["demoLimits"], **payload["demoRemaining"]}, round=payload["identity"]["round"])
    if action_kind == "PROTOTYPE_ANALYZE":
        verify_prototype_trace(payload["inventory"], payload["scenario"]["normalizedResult"], payload["trace"]["normalizedResult"])
    if "browserProfileSource" in payload:
        registry = load_registry(Path(__file__).parents[1] / "contracts")
        if validate_contract(payload["browserProfileSource"]["normalizedResult"], "prototype-trace.schema.json", registry):
            raise PrototypeError("PROTOTYPE_PROFILE_CONTEXT_INVALID")


def _preserve_prototype_candidate(action_kind, packet, result):
    from candidate_repair import repair_baseline, preserve_roots
    baseline = repair_baseline(packet, action_kind + "-v1")
    if baseline is None:
        return
    previous, diagnostic = baseline
    if not diagnostic["code"].startswith("PROTOTYPE_") and diagnostic["code"] != "INCOMPLETE_BUDGET":
        return
    roots = set(diagnostic["subjectIds"])
    if action_kind == "PROTOTYPE_SCENARIO":
        # Scenario IDs remain the public contract; localKey is a transient helper projection.
        def projected(value):
            return {**value, "scenarios": [{**item, "localKey": item["scenarioId"]} for item in value["scenarios"]]}
        fields = (diagnostic["path"][1:],) if diagnostic["path"] in {"/bundleSha256", "/round"} else ()
        preserve_roots(projected(previous), projected(result), "scenarios", roots, mutable_fields=fields)
        before = [item["scenarioId"] for item in previous["scenarios"] if item["scenarioId"] not in roots]
        after = [item["scenarioId"] for item in result["scenarios"] if item["scenarioId"] not in roots]
        if before != after:
            raise InvalidActionResult("修复不得改变无关场景的执行顺序。", diagnostic=AttemptDiagnostic(
                "REPAIR_SCOPE_VIOLATION", "/scenarios", tuple(sorted(set(before + after)))))
    else:
        preserve_roots(previous, result, "observations", roots)


def validate_bound_prototype_result(action_kind, payload, normalized_result: bytes, packet=None) -> None:
    """Pure binding checks on strictly normalized IR and prevalidated context."""
    result = json.loads(normalized_result)
    if packet is not None and action_kind in {"PROTOTYPE_SCENARIO", "PROTOTYPE_ANALYZE"}:
        _preserve_prototype_candidate(action_kind, packet, result)
    if action_kind in {"PROTOTYPE_BROWSER", "PROTOTYPE_ANALYZE"}:
        _verify_scenario_bindings(payload["inventory"], payload["scenario"]["normalizedResult"], payload["identity"]["round"])
    if action_kind == "PROTOTYPE_ANALYZE":
        _verify_trace_bindings(payload["inventory"], payload["scenario"]["normalizedResult"], payload["trace"]["normalizedResult"])
    try:
        if action_kind == "PROTOTYPE_SCENARIO":
            limits = {**payload["demoLimits"], **payload["demoRemaining"]}
            _verify_scenario_plan(payload["inventory"], result, limits, payload["identity"]["round"])
        elif action_kind == "PROTOTYPE_BROWSER":
            if "browserProfileSource" in payload and result["browserProfile"] != payload["browserProfileSource"]["normalizedResult"]["browserProfile"]:
                raise InvalidActionResult("PROTOTYPE_PROFILE_MISMATCH")
            _verify_trace_bindings(payload["inventory"], payload["scenario"]["normalizedResult"], result)
        elif action_kind == "PROTOTYPE_ANALYZE":
            _verify_observation_bindings(payload["inventory"], payload["scenario"]["normalizedResult"], payload["trace"]["normalizedResult"], result)
        else:
            raise ValueError("未知 Prototype Action。")
    except PrototypeError as error:
        current_invalid = {
            "PROTOTYPE_SCENARIO_INVALID", "PROTOTYPE_BUNDLE_MISMATCH", "PROTOTYPE_INTERACTION_UNKNOWN",
            "PROTOTYPE_OBSERVATION_INVALID", "PROTOTYPE_SOURCE_EVIDENCE_REQUIRED", "PROTOTYPE_RUNTIME_EVIDENCE_REQUIRED",
        }
        trace_invalid = {
            "PROTOTYPE_TRACE_INVALID", "PROTOTYPE_TRACE_BINDING_INVALID", "PROTOTYPE_SOURCE_CHANGED",
            "PROTOTYPE_TRACE_RUNS_INVALID", "PROTOTYPE_TRACE_STEP_INVALID", "PROTOTYPE_TRACE_ASSERTION_INVALID",
            "PROTOTYPE_TRACE_SCREENSHOT_INVALID", "PROTOTYPE_DISCOVERY_BINDING_INVALID",
        }
        if error.code in current_invalid or (action_kind == "PROTOTYPE_BROWSER" and error.code in trace_invalid) or (action_kind == "PROTOTYPE_SCENARIO" and error.code == "INCOMPLETE_BUDGET"):
            raise InvalidActionResult(error.code, diagnostic=error.diagnostic) from error
        if error.code not in {"PROTOTYPE_SCOPE_EVIDENCE_REQUIRED", "INCOMPLETE_BUDGET", "PROTOTYPE_UNSTABLE"}:
            raise


def diagnose_candidate(action_kind, packet, candidate, **owner_context):
    from candidate_repair import schema_issues, diagnostic_report, issues_from_diagnostics
    raw=candidate if isinstance(candidate,bytes) else canonical_json_bytes(candidate);value=json.loads(raw)
    issues=schema_issues(owner_context.get('action_contract_id',action_kind+'-v1'),value,'PROTOTYPE')
    blocked=[];domains=['SCHEMA'];payload=packet['workItems'][0]['payload'];diagnostics=[]
    try:
        if action_kind=='PROTOTYPE_SCENARIO':
            _verify_scenario_bindings(payload['inventory'],value,payload['identity']['round'],diagnostics=diagnostics)
            try:_verify_scenario_plan(payload['inventory'],value,{**payload['demoLimits'],**payload['demoRemaining']},payload['identity']['round'])
            except PrototypeError as error:
                if error.code=='INCOMPLETE_BUDGET':diagnostics.append(error.diagnostic)
        elif action_kind=='PROTOTYPE_ANALYZE':
            _verify_observation_bindings(payload['inventory'],payload['scenario']['normalizedResult'],payload['trace']['normalizedResult'],value,diagnostics=diagnostics)
        else:
            try:validate_bound_prototype_result(action_kind,payload,raw,packet=packet)
            except InvalidActionResult as error:diagnostics.append(error.diagnostic)
    except (KeyError,TypeError,IndexError):
        blocked.append('PROTOTYPE_BINDINGS')
    else:
        domains.append('PROTOTYPE_BINDINGS')
    issues+=issues_from_diagnostics(diagnostics,'PROTOTYPE',value)
    for issue in issues:
        if issue['code']=='PROTOTYPE_SCOPE_EVIDENCE_REQUIRED':
            issue['repairClass']='INPUT_REQUIRED'
    if action_kind=='PROTOTYPE_BROWSER':
        for issue in issues:issue['repairClass']='EXECUTION'
    return diagnostic_report(raw,issues,owner='PROTOTYPE',checker_file=__file__,packet=packet,
        origin=owner_context.get('origin'),blocked=blocked,domains=domains)


def plan_candidate_repair(action_kind, packet, candidate, report, *, origin, **owner_context):
    from candidate_repair import group_fields, build_repair_plan
    if action_kind=='PROTOTYPE_BROWSER':raise InvalidActionResult('浏览器观察必须由实际工具执行，不能由模型修补运行事实。')
    selected={issue['issueId']:issue['paths'] for issue in report['issues']}
    groups=group_fields(candidate,report,owner_context.get('action_contract_id',action_kind+'-v1'),selected)
    if not groups:raise InvalidActionResult('原型缺口需要真实执行或输入，不能改写已有观察。')
    if len(groups)>1:
        issue_ids=sorted({
            issue_id for group in groups for issue_id in group['issueIds']
        })
        slots=list({
            slot['slotId']:slot for group in groups for slot in group['slots']
        }.values())
        read_set=list({
            (entry['objectId'],tuple(entry['fields'])):entry
            for group in groups for entry in group['readSet']
        }.values())
        groups=[{
            'groupId':'group-'+sha256_bytes(canonical_json_bytes(issue_ids))[:24],
            'issueIds':issue_ids,
            'readSet':read_set,
            'slots':slots,
            'verificationObligations':issue_ids,
        }]
    return build_repair_plan(candidate if isinstance(candidate,bytes) else canonical_json_bytes(candidate),report,groups,origin=origin)


def candidate_repair_context(action_kind, packet, candidate, plan, group):
    value=json.loads(candidate);payload=packet['workItems'][0]['payload'];inventory=payload['inventory']
    index={r['objectId']:r for r in plan['objectIndex']};interactions=set();evidence=set();scenario_ids=set()
    scenario_rows=payload.get('scenario',{}).get('normalizedResult',{}).get('scenarios',[])
    scenario_keys={row['scenarioId'] for row in scenario_rows}
    for slot in group['slots']:
        parts=index.get(slot['objectId'],{}).get('path','').split('/')
        if len(parts)>2 and parts[1] in {'observations','scenarios'}:
            row=value[parts[1]][int(parts[2])];interactions.update(row.get('interactionIds',[]));evidence.update(row.get('evidenceIds',[]))
            if 'scenarioId' in row:scenario_ids.add(row['scenarioId'])
            elif row.get('localKey') in scenario_keys:scenario_ids.add(row['localKey'])
    if not scenario_ids:
        for scenario in scenario_rows:
            if interactions.intersection(scenario['interactionIds']):
                scenario_ids.add(scenario['scenarioId'])
    selected=[row for row in inventory['interactions'] if row['interactionId'] in interactions]
    evidence.update(key for row in selected for key in row.get('evidenceIds',[]))
    result=[{'kind':'PROTOTYPE_BOUND_CONTEXT','bundleSha256':inventory['bundleSha256'],'round':payload['identity']['round'],
             'routes':sorted({row['page'] for row in selected}),'interactions':selected,
             'evidence':[row for row in inventory['evidence'] if row['evidenceId'] in evidence]}]
    if 'trace' in payload:
        trace=payload['trace']['normalizedResult']
        selected_runs=[]
        for run in trace['runs']:
            if run['scenarioId'] not in scenario_ids:continue
            steps=[step for step in run['steps'] if not interactions or step['interactionId'] in interactions]
            if steps:selected_runs.append({**run,'steps':steps})
        filtered={**trace,'runs':selected_runs,
            'unresolvedDiscoveries':[row for row in trace['unresolvedDiscoveries']
                                     if evidence.intersection(row['sourceEvidenceIds'])]}
        result.append({'kind':'READ_ONLY_RUNTIME_FACTS','trace':filtered})
    if 'demoLimits' in payload:result.append({'demoLimits':payload['demoLimits'],'demoRemaining':payload['demoRemaining']})
    return result
