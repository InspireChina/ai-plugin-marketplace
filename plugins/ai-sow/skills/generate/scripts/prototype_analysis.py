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


class PrototypeError(ValueError):
    def __init__(self, code: str):
        self.code = code
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


def _verify_scenario_bindings(inventory, scenario, round):
    if scenario["bundleSha256"] != inventory["bundleSha256"]:
        raise PrototypeError("PROTOTYPE_BUNDLE_MISMATCH")
    if scenario["round"] != round:
        raise PrototypeError("PROTOTYPE_SCENARIO_INVALID")
    interaction_ids = {item["interactionId"] for item in inventory["interactions"]}
    scenarios = scenario["scenarios"]
    steps = [step for item in scenarios for step in item["steps"]]
    if any(not set(item["interactionIds"]) <= interaction_ids for item in scenarios) or any(step["interactionId"] is not None and step["interactionId"] not in interaction_ids for step in steps):
        raise PrototypeError("PROTOTYPE_INTERACTION_UNKNOWN")
    if len({item["scenarioId"] for item in scenarios}) != len(scenarios) or len({step["stepId"] for step in steps}) != len(steps):
        raise PrototypeError("PROTOTYPE_SCENARIO_INVALID")
    if any(set(item["interactionIds"]) != {step["interactionId"] for step in item["steps"] if step["interactionId"] is not None} for item in scenarios):
        raise PrototypeError("PROTOTYPE_SCENARIO_INVALID")
    operations = {"navigate": {"navigate"}, "click": {"click"}, "fill": {"input"},
                  "select": {"input", "change"}, "check": {"input", "change", "click"},
                  "press": {"keydown", "keyup"}, "wait": set()}
    interactions = {item["interactionId"]: item for item in inventory["interactions"]}
    for step in steps:
        if step["page"] not in inventory["routes"]:
            raise PrototypeError("PROTOTYPE_SCENARIO_INVALID")
        if step["operation"] == "navigate" and step["value"] not in {None, step["page"]}:
            raise PrototypeError("PROTOTYPE_SCENARIO_INVALID")
        if step["interactionId"] is None:
            continue
        interaction = interactions[step["interactionId"]]
        if step["page"] != interaction["page"] or step["selector"] != interaction["selector"] or interaction["event"] not in operations[step["operation"]]:
            raise PrototypeError("PROTOTYPE_SCENARIO_INVALID")


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
        raise PrototypeError("INCOMPLETE_BUDGET")
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


def _verify_observation_bindings(inventory, scenario, trace, result):
    evidence = _verify_trace_bindings(inventory, scenario, trace)
    if evidence["unresolvedDiscoveryCount"]:
        raise PrototypeError("PROTOTYPE_UNRESOLVED_DISCOVERY")
    source_ids = {item["evidenceId"] for item in inventory["evidence"] if item["content"]}
    interaction_ids = {item["interactionId"] for item in inventory["interactions"]}
    observed = {item["interactionId"] for item in evidence["interactionDispositions"] if item["disposition"] == "OBSERVED"}
    local_keys = [item["localKey"] for item in result["observations"]]
    if len(set(local_keys)) != len(local_keys):
        raise PrototypeError("PROTOTYPE_OBSERVATION_INVALID")
    intent_review = []
    for observation in result["observations"]:
        if not observation["evidenceIds"] or not set(observation["evidenceIds"]) <= source_ids:
            raise PrototypeError("PROTOTYPE_SOURCE_EVIDENCE_REQUIRED")
        if observation["behavior"]["page"] not in inventory["routes"] or not set(observation["interactionIds"]) <= interaction_ids:
            raise PrototypeError("PROTOTYPE_OBSERVATION_INVALID")
        if observation["runtimeStatus"] == "OBSERVED" and (not observation["interactionIds"] or not set(observation["interactionIds"]) <= observed):
            raise PrototypeError("PROTOTYPE_RUNTIME_EVIDENCE_REQUIRED")
        if observation["runtimeStatus"] == "OBSERVED" and any(item["page"] != observation["behavior"]["page"] for item in inventory["interactions"] if item["interactionId"] in observation["interactionIds"]):
            raise PrototypeError("PROTOTYPE_RUNTIME_EVIDENCE_REQUIRED")
    for observation in result["observations"]:
        if observation["scopeRelation"] in {"CONFIRMS", "SUPPLEMENTS", "ADDITIONAL"}:
            if observation["runtimeStatus"] in {"BROKEN", "NOT_EXERCISED"}:
                raise PrototypeError("PROTOTYPE_SCOPE_EVIDENCE_REQUIRED")
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


def validate_bound_prototype_result(action_kind, payload, normalized_result: bytes) -> None:
    """Pure binding checks on strictly normalized IR and prevalidated context."""
    result = json.loads(normalized_result)
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
            raise InvalidActionResult(error.code) from error
        if error.code not in {"PROTOTYPE_SCOPE_EVIDENCE_REQUIRED", "INCOMPLETE_BUDGET", "PROTOTYPE_UNSTABLE"}:
            raise
