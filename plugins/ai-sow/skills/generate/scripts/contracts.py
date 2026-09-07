from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from datetime import datetime
from collections.abc import Mapping
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.exceptions import NoSuchResource

from models import canonical_json_bytes, AttemptDiagnostic, AttemptTiming, Diagnostic, DiagnosticClassification, Usage


def validate_attempt_timing(timing: AttemptTiming, *, failed: bool) -> None:
    for index, value in enumerate((timing.started_at_utc, timing.ended_at_utc)):
        if index == 0 and value is None:
            continue
        if not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z", value
        ):
            raise ValueError("Attempt 时间必须是 UTC RFC 3339。")
        datetime.fromisoformat(value)
    if timing.ended_at_utc is None or (timing.started_at_utc is None and not failed):
        raise ValueError("只有执行前失败允许 startedAtUtc 为空。")
    if timing.active_seconds < 0:
        raise ValueError("Attempt endedAtUtc 不得早于 startedAtUtc。")


def usage_value(usage: Usage) -> dict[str, object]:
    return {
        "provenance": usage.provenance,
        "inputTokens": usage.input_tokens,
        "outputTokens": usage.output_tokens,
        "cachedInputTokens": usage.cached_input_tokens,
        "reasoningTokens": usage.reasoning_tokens,
    }


def validate_usage(usage: Usage, *, provider_started: bool = True) -> None:
    if usage.provenance not in {"PROVIDER_REPORTED", "LOCALLY_ESTIMATED"}:
        raise ValueError("Usage provenance 无效。")
    values = [usage.input_tokens, usage.output_tokens, usage.cached_input_tokens]
    if usage.reasoning_tokens is not None:
        values.append(usage.reasoning_tokens)
    if any(type(value) is not int or value < 0 for value in values):
        raise ValueError("Usage token 必须是非负整数。")
    if (
        usage.cached_input_tokens > usage.input_tokens
        or (usage.reasoning_tokens or 0) > usage.output_tokens
    ):
        raise ValueError("Usage breakdown 不得超过所属总量。")
    if not provider_started and (any(values) or usage.reasoning_tokens is not None):
        raise ValueError("执行前失败必须使用零 Usage 且 reasoning 为 null。")




def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


_ACTION_CONTRACT_KEYS = {
    "actionContractId",
    "goal",
    "inputTypes",
    "workOrder",
    "instruction",
    "resultSchema",
    "sealPredicates",
    "uncertaintyExit",
    "repairRoute",
    "executionKind",
    "usageCategory",
    "limits",
}


def _registered_skill_file(skill_root: Path, relative_path: object) -> Path:
    if not isinstance(relative_path, str) or not relative_path:
        raise ValueError("Action contract 文件路径必须是非空相对路径。")
    root = skill_root.resolve()
    candidate = (root / relative_path).resolve()
    if candidate == root or root not in candidate.parents:
        raise ValueError("Action contract 文件路径越出 Skill 根目录。")
    if not candidate.is_file():
        raise ValueError(f"Action contract 文件不存在：{relative_path}")
    return candidate


def _verified_file_binding(
    skill_root: Path,
    binding: object,
    *,
    binding_name: str,
) -> Path:
    expected_keys = (
        {"id", "path", "sha256"}
        if binding_name == "resultSchema"
        else {"path", "sha256"}
    )
    if not isinstance(binding, Mapping) or set(binding) != expected_keys:
        raise ValueError(f"{binding_name} binding 字段不完整或包含额外字段。")
    path = _registered_skill_file(skill_root, binding.get("path"))
    expected_sha256 = binding.get("sha256")
    if expected_sha256 != sha256_bytes(path.read_bytes()):
        raise ValueError(f"{binding_name} 文件 hash 与 registry 不一致。")
    return path


def action_contract_binding(
    skill_root: Path,
    action_contract_id: str,
) -> tuple[Mapping[str, object], str]:
    registry_path = skill_root / "contracts" / "action-contracts-v1.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    if not isinstance(registry, Mapping) or set(registry) != {"contract", "contracts"}:
        raise ValueError("Action contract registry 结构无效。")
    if registry.get("contract") != "ai-sow-action-contract-registry-v1":
        raise ValueError("Action contract registry 版本无效。")
    contracts = registry.get("contracts")
    if not isinstance(contracts, list):
        raise ValueError("Action contract registry contracts 必须是数组。")
    contract_ids = [
        item.get("actionContractId")
        for item in contracts
        if isinstance(item, Mapping)
    ]
    if (
        len(contract_ids) != len(contracts)
        or not all(isinstance(item, str) and item for item in contract_ids)
        or len(set(contract_ids)) != len(contract_ids)
    ):
        raise ValueError("Action contract registry ID 必须完整且唯一。")
    matches = [
        item
        for item in contracts
        if isinstance(item, Mapping)
        and item.get("actionContractId") == action_contract_id
    ]
    if len(matches) != 1:
        raise LookupError(f"Action contract 必须唯一注册：{action_contract_id}")
    contract = matches[0]
    if set(contract) != _ACTION_CONTRACT_KEYS:
        raise ValueError(f"Action contract 字段不完整或包含额外字段：{action_contract_id}")
    if action_contract_id in {"TASK-v2", "TASK_REPAIR-v2"}:
        original, _ = action_contract_binding(skill_root, action_contract_id[:-1] + "1")
        expected = {**original, "actionContractId": action_contract_id,
                    "limits": {**original["limits"], "maxHydrateTokens": 65536}}
        if contract != expected:
            raise ValueError("Task v2 只增加完整规则读取容量，必须保留 v1 专业合同。")
    if action_contract_id in {"PRIOR_ANALYZE-v1", "PRIOR_CONSOLIDATE-v1"}:
        prompt = "prompts/" + action_contract_id.removesuffix("-v1").lower().replace("_", "-") + ".md"
        if (
            contract["instruction"].get("path") != prompt
            or contract["resultSchema"].get("path") != "contracts/prior-state-decision.schema.json"
            or contract["resultSchema"].get("id") != "urn:ai-sow:generate:next:prior-state-decision:1#/$defs/priorStateDecision"
        ):
            raise ValueError("Prior Action 必须绑定自身 prompt 与唯一 PriorStateDecision schema。")
    if action_contract_id in {"PRIOR_ANALYZE-v2", "PRIOR_ANALYZE-v3", "PRIOR_CONSOLIDATE-v2"}:
        kind = action_contract_id[:-3]
        definition = "priorStateDecision" if kind == "PRIOR_ANALYZE" else "priorRelations"
        if (contract["instruction"].get("path") != "prompts/" + kind.lower().replace("_", "-") + "-v2.md"
                or contract["resultSchema"].get("path") != "contracts/prior-state-decision-v2.schema.json"
                or contract["resultSchema"].get("id") != "urn:ai-sow:generate:next:prior-state-decision:2#/$defs/" + definition):
            raise ValueError("Prior v2 必须绑定自身 prompt 与精确 Analyze/relations schema。")
    if contract.get("executionKind") not in ("MODEL_PROVIDER", "HOST_BROWSER"):
        raise ValueError(f"Action contract executionKind 无效：{action_contract_id}")
    if contract.get("usageCategory") not in ("AUTHOR", "HYDRATE", "REVIEW", "REPAIR"):
        raise ValueError(f"Action contract usageCategory 无效：{action_contract_id}")
    _verified_file_binding(
        skill_root,
        contract.get("instruction"),
        binding_name="instruction",
    )
    result_schema = contract.get("resultSchema")
    schema_path = _verified_file_binding(
        skill_root,
        result_schema,
        binding_name="resultSchema",
    )
    assert isinstance(result_schema, Mapping)
    result_schema_id = result_schema.get("id")
    if not isinstance(result_schema_id, str) or "#/$defs/" not in result_schema_id:
        raise ValueError(f"Action contract result schema id 无效：{action_contract_id}")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    if result_schema_id.partition("#")[0] != schema.get("$id"):
        raise ValueError(f"Action contract result schema id/path 不一致：{action_contract_id}")
    fragment_name = result_schema_id.removeprefix(str(schema.get("$id")) + "#/$defs/")
    if (
        not fragment_name
        or not isinstance(schema.get("$defs"), Mapping)
        or fragment_name not in schema["$defs"]
    ):
        raise ValueError(f"Action contract result schema fragment 不存在：{action_contract_id}")
    limits = contract.get("limits")
    if not isinstance(limits, Mapping) or set(limits) != {
        "maxOutputTokens",
        "maxHydrateTokens",
    }:
        raise ValueError(f"Action contract limits 无效：{action_contract_id}")
    if any(
        not isinstance(limits.get(name), int)
        or isinstance(limits.get(name), bool)
        or limits[name] < 0
        for name in ("maxOutputTokens", "maxHydrateTokens")
    ):
        raise ValueError(f"Action contract limits 必须是非负整数：{action_contract_id}")
    return contract, sha256_bytes(canonical_json_bytes(contract))


def validate_action_usage(
    envelope: Mapping[str, object],
    usage: Usage,
    *,
    skill_root: Path,
) -> None:
    validate_usage(usage)
    contract, digest = action_contract_binding(
        skill_root, str(envelope.get("actionContractId"))
    )
    if envelope.get("actionContractSha256") != digest:
        raise ValueError("Envelope Action contract hash 与 registry 正文不一致。")
    if contract["executionKind"] == "HOST_BROWSER":
        validate_usage(usage, provider_started=False)


def action_provider_request(
    skill_root: Path,
    action_contract_id: str,
    packet_payload: bytes,
    *,
    budget_policy: Mapping[str, object],
    max_output_tokens: int,
    hydration_responses=(),
) -> bytes:
    from provider_adapter import canonical_provider_request

    contract, _ = action_contract_binding(skill_root, action_contract_id)
    if contract["executionKind"] == "HOST_BROWSER":
        raise ValueError("HOST_BROWSER 不构造provider request。")
    instruction = contract["instruction"]
    assert isinstance(instruction, Mapping)
    instruction_path = _registered_skill_file(skill_root, instruction["path"])
    packet=json.loads(packet_payload)
    prior_retry=(action_contract_id in {'PRIOR_ANALYZE-v1','PRIOR_ANALYZE-v2'}
        and any(ref['canonicalContent'].get('kind')=='ATTEMPT_REPAIR' for ref in packet.get('contextRefs',[]))
        and any(item['payload'].get('priorInputLayout')=='ai-sow-prior-row-partition-v1' for item in packet.get('workItems',[])))
    instruction_text=instruction_path.read_text(encoding='utf-8')
    if prior_retry and action_contract_id == 'PRIOR_ANALYZE-v1':
        instruction_text+='\n行分区只定义本请求分配的输入；同一请求内、同来源和 Sheet 的已授权分区可以共同支撑一个实体，但须保留所属 namespace 中的证据。sheet.usedRange 是全表结构，分区外未分配给本请求的行由其它计划工作处理，不能仅因本请求未包含它们而声明 unsupportedRegions。修复已有结果，保留正确实体；不要把分区边界当作合同缺失。'
    if action_contract_id == "PRIOR_ANALYZE-v3":
        responses = tuple(hydration_responses)
        requests = [canonical_provider_request(
            str(budget_policy["modelProfileId"]), instruction_text, packet_payload,
            max_output_tokens, responses, lossless_tables=compact,
        ) for compact in (False, True)]
        return min(requests, key=len)
    return canonical_provider_request(
        str(budget_policy["modelProfileId"]),
        instruction_text,
        packet_payload,
        max_output_tokens,
        hydration_responses,
        lossless_tables=prior_retry,
    )


def estimate_action_input_tokens(
    skill_root: Path,
    action_contract_id: str,
    packet_payload: bytes,
    *,
    budget_policy: Mapping[str, object],
    max_output_tokens: int,
) -> int:
    from provider_adapter import estimate_provider_request

    contract, _ = action_contract_binding(skill_root, action_contract_id)
    if contract["executionKind"] == "HOST_BROWSER":
        return 0
    return estimate_provider_request(
        str(budget_policy["modelProfileId"]),
        str(budget_policy["estimatorVersion"]),
        action_provider_request(
            skill_root, action_contract_id, packet_payload,
            budget_policy=budget_policy, max_output_tokens=max_output_tokens,
        ),
    )


def usable_action_input_tokens(policy: Mapping[str, object], *, max_hydrate_tokens: int | None = None) -> int:
    # Unbound planning stays conservative; issued Actions cannot hydrate beyond
    # their own immutable limit, even when a later Owner needs a larger reserve.
    hydrate = int(policy["hydrateReserveTokens"])
    if max_hydrate_tokens is not None:
        hydrate = min(hydrate, max_hydrate_tokens)
    return int(policy["modelContextLimitTokens"]) - int(policy["outputReserveTokens"]) - hydrate - int(policy["safetyMarginTokens"])


def validate_action_envelope(
    envelope: Mapping[str, object],
    *,
    packet_payload: bytes,
    skill_root: Path,
    effective_budget_policy: Mapping[str, object],
    registry: Registry | None = None,
) -> tuple[Diagnostic, ...]:
    registry = load_schema_registry(skill_root) if registry is None else registry
    diagnostics = list(
        validate_contract(
            envelope,
            "action.schema.json",
            registry,
        )
    )
    if diagnostics:
        return _sort_diagnostics(diagnostics)
    try:
        contract, contract_sha256 = action_contract_binding(
            skill_root,
            str(envelope.get("actionContractId")),
        )
    except (LookupError, OSError, ValueError, json.JSONDecodeError) as error:
        return (
            _diagnostic(
                "ACTION_CONTRACT_INVALID",
                "/actionContractId",
                "Envelope 绑定的 Action contract 无法从 registry 唯一解析。",
                errorType=type(error).__name__,
            ),
        )
    if (envelope['revision'] > effective_budget_policy.get('maxActionRevisions', 2)
            or envelope['attempt'] > effective_budget_policy.get('maxExecutionAttempts', 2)):
        diagnostics.append(_diagnostic('ACTION_RETRY_LIMIT_EXCEEDED', '/revision', 'Action 超出其发行时预算的有限次数。'))
    if envelope.get("actionContractSha256") != contract_sha256:
        diagnostics.append(
            _diagnostic(
                "ACTION_CONTRACT_HASH_MISMATCH",
                "/actionContractSha256",
                "Envelope 的 Action contract hash 与 registry 正文不一致。",
            )
        )
    if envelope.get("packetSha256") != sha256_bytes(packet_payload):
        diagnostics.append(
            _diagnostic(
                "ACTION_PACKET_HASH_MISMATCH",
                "/packetSha256",
                "Envelope 的 packet hash 与实际 bytes 不一致。",
            )
        )
    diagnostics.extend(validate_contract(
        effective_budget_policy, "run-budget-policy.schema.json", registry
    ))
    if diagnostics:
        return _sort_diagnostics(diagnostics)
    if envelope.get("budgetPolicySha256") != sha256_bytes(canonical_json_bytes(effective_budget_policy)):
        diagnostics.append(
            _diagnostic(
                "ACTION_BUDGET_POLICY_MISMATCH",
                "/budgetPolicySha256",
                "Envelope 必须绑定签发时的 effective budget policy。",
            )
        )
    execution_limits = envelope.get("executionLimits")
    assert isinstance(execution_limits, Mapping)
    if contract["executionKind"] == "HOST_BROWSER" and any(execution_limits.values()):
        diagnostics.append(_diagnostic("ACTION_BROWSER_TOKEN_LIMIT_INVALID", "/executionLimits", "HOST_BROWSER的三个token limit必须为零。"))
    try:
        estimated_input_tokens = estimate_action_input_tokens(
            skill_root,
            str(envelope.get("actionContractId")),
            packet_payload,
            budget_policy=effective_budget_policy,
            max_output_tokens=int(execution_limits["maxOutputTokens"]),
        )
    except ValueError:
        diagnostics.append(
            _diagnostic(
                "ACTION_PACKET_INVALID",
                "/packetPath",
                "Action packet 无法构造确定性 provider request。",
            )
        )
    else:
        if execution_limits.get("estimatedInputTokens") != estimated_input_tokens:
            diagnostics.append(
                _diagnostic(
                    "ACTION_INPUT_ESTIMATE_MISMATCH",
                    "/executionLimits/estimatedInputTokens",
                    "Envelope 输入估值与绑定 estimator 对实际 request bytes 的结果不一致。",
                )
            )
        if estimated_input_tokens > usable_action_input_tokens(effective_budget_policy, max_hydrate_tokens=execution_limits["maxHydrateTokens"]):
            diagnostics.append(_diagnostic("ACTION_INPUT_CAPACITY_EXCEEDED", "/executionLimits/estimatedInputTokens", "完整request超过policy声明的usable input容量。"))
    contract_limits = contract["limits"]
    assert isinstance(contract_limits, Mapping)
    for name in ("maxOutputTokens", "maxHydrateTokens"):
        value = execution_limits.get(name)
        reserve = "outputReserveTokens" if name == "maxOutputTokens" else "hydrateReserveTokens"
        maximum = min(int(contract_limits[name]), int(effective_budget_policy[reserve]))
        if isinstance(value, int) and isinstance(maximum, int) and value > maximum:
            diagnostics.append(
                _diagnostic(
                    "ACTION_EXECUTION_LIMIT_EXCEEDED",
                    f"/executionLimits/{name}",
                    "Envelope 执行上限超过 Action contract。",
                    contractMaximum=maximum,
                )
            )
    return _sort_diagnostics(diagnostics)


def validate_action_result(
    envelope: Mapping[str, object],
    result: object,
    *,
    skill_root: Path,
) -> tuple[Diagnostic, ...]:
    try:
        contract, contract_sha256 = action_contract_binding(
            skill_root,
            str(envelope.get("actionContractId")),
        )
    except (LookupError, OSError, ValueError, json.JSONDecodeError) as error:
        return (
            _diagnostic(
                "ACTION_CONTRACT_INVALID",
                "/actionContractId",
                "Envelope 绑定的 Action contract 无法从 registry 唯一解析。",
                errorType=type(error).__name__,
            ),
        )
    if envelope.get("actionContractSha256") != contract_sha256:
        return (
            _diagnostic(
                "ACTION_CONTRACT_HASH_MISMATCH",
                "/actionContractSha256",
                "Envelope 的 Action contract hash 与 registry 正文不一致。",
            ),
        )
    result_schema = contract["resultSchema"]
    assert isinstance(result_schema, Mapping)
    result_schema_id = result_schema["id"]
    registry = load_schema_registry(skill_root)
    errors = Draft202012Validator(
        {"$ref": result_schema_id},
        registry=registry,
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    ).iter_errors(result)
    diagnostics = [
        _diagnostic(
            "ACTION_RESULT_SCHEMA_INVALID",
            _json_pointer(error.absolute_path),
            "Action result 不符合 registry 绑定的精确 result schema。",
            actionContractId=envelope.get("actionContractId"),
            resultSchemaId=result_schema_id,
            validator=str(error.validator),
        )
        for error in errors
    ]
    if not diagnostics and envelope.get("actionContractId") == "PROTOTYPE_ANALYZE-v1":
        keys = [item["localKey"] for item in result["observations"]]
        if len(set(keys)) != len(keys):
            diagnostics.extend(_diagnostic("ACTION_RESULT_LOCAL_KEY_DUPLICATE", f"/observations/{index}", "本轮 observation localKey 必须唯一。")
                for index, key in enumerate(keys) if keys.count(key) > 1)
    return _sort_diagnostics(diagnostics)


class InvalidActionResult(ValueError):
    def __init__(self, message: str, *, diagnostic: AttemptDiagnostic | None = None):
        super().__init__(message)
        if diagnostic is not None and not isinstance(diagnostic, AttemptDiagnostic):
            raise TypeError("InvalidActionResult diagnostic 必须是 AttemptDiagnostic。")
        self.diagnostic = diagnostic or AttemptDiagnostic("INVALID_IR", "", ())


def current_action_contract_id(action_kind: str) -> str:
    if action_kind == "PRIOR_ANALYZE":
        return "PRIOR_ANALYZE-v3"
    return action_kind + ("-v2" if action_kind in {"PRIOR_CONSOLIDATE", "TASK", "TASK_REPAIR"} else "-v1")


def prior_dependencies(action_kind, packet):
    dependencies = []
    for ref in packet["contextRefs"]:
        body = ref["canonicalContent"]
        if body.get("kind") == "DEPENDENCY_RESULT":
            if set(ref) != {"refId", "canonicalContent"} or set(body) not in ({"kind", "logicalWorkId", "attemptRecordSha256", "normalizedResult"}, {"kind", "logicalWorkId", "candidateResolutionSha256", "sourceAttemptRecordSha256", "normalizedResult"}) or ref["refId"] != "dependency-result-" + body["logicalWorkId"]:
                raise ValueError("Prior dependency 必须使用唯一 planner wrapper。")
            dependencies.append(body["normalizedResult"])
    if (action_kind == "PRIOR_ANALYZE" and dependencies) or (action_kind == "PRIOR_CONSOLIDATE" and len(dependencies) < 2):
        raise ValueError("Prior Analyze/Consolidate dependency 数量无效。")
    return dependencies


def assemble_prior_result(packet, additions, *, skill_root):
    """Normalize narrow v2 relations by retaining the frozen successful inputs."""
    dependencies = prior_dependencies("PRIOR_CONSOLIDATE", packet)
    registry = load_schema_registry(skill_root)
    for dependency in dependencies:
        if validate_contract(dependency, "prior-state-decision-v2.schema.json", registry):
            raise ValueError("Prior v2 dependency schema 无效；不升级旧结果。")
    result = {key: [item for dependency in dependencies for item in dependency[key]]
              for key in ("entities", "unextractedEvidence")}
    keys = [item["localKey"] for item in result["entities"]]
    if len(keys) != len(set(keys)):
        raise InvalidActionResult("Prior dependencies 重复 entity localKey。")
    for collection in ("sourceRelations", "entitySupersessions", "unsupportedRegions"):
        retained = {canonical_json_bytes(item): item for dependency in dependencies for item in dependency[collection]}
        for item in additions.get(collection, []):
            key = canonical_json_bytes(item)
            if key in retained:
                raise InvalidActionResult("Consolidate 只能返回新增关系，不能重报已有关系。")
            retained[key] = item
        result[collection] = [retained[key] for key in sorted(retained)]
    return result


def preserve_schema_candidate(packet, action_id, current):
    """Preserve schema-valid sibling objects using the previous located schema failures.

    This is structural only. The Owner still validates the repaired candidate's
    meaning and dependencies before it can succeed.
    """
    from copy import deepcopy
    refs = [ref['canonicalContent'] for ref in packet.get('contextRefs', ())
            if str(ref.get('refId', '')).startswith('repair-from-attempt-')]
    if not refs: return
    if len(refs) != 1: raise ValueError('候选修复必须绑定唯一前次失败。')
    base = refs[0].get('preservationBase', refs[0])
    diagnostic = base.get('diagnostic', {})
    if diagnostic.get('code') != 'INVALID_IR': return
    paths = [item['path'] for item in diagnostic.get('findings', ())
             if item['code'] in {'ACTION_RESULT_SCHEMA_INVALID', 'ACTION_RESULT_LOCAL_KEY_DUPLICATE'}]
    if not paths: return
    try: previous = json.loads(base['rawOutputUtf8'])
    except (ValueError, KeyError): return
    if not isinstance(previous, (dict, list)): return
    def normalized_row(collection, row):
        wrapper = [deepcopy(row)] if collection is None else {
            **{key: [] for key, value in previous.items() if isinstance(value, list)},
            collection: [deepcopy(row)]}
        try:
            value = normalize_result_sets(action_id, wrapper)
            return canonical_json_bytes(value[0] if collection is None else value[collection][0])
        except (KeyError, TypeError, AttributeError):
            return canonical_json_bytes(row)
    def identity(row):
        if not isinstance(row, dict): return None
        for key in ('localKey', 'scenarioId', 'coverageRootId'):
            if isinstance(row.get(key), str):
                return (key, row[key], row.get('category') if key == 'coverageRootId' else None)
        return None
    changed = []
    collections = [(None, previous)] if isinstance(previous, list) else list(previous.items())
    for collection, old in collections:
        prefix = '' if collection is None else '/' + collection
        new = current if collection is None else current.get(collection)
        relevant = [path for path in paths if path == prefix or path.startswith(prefix + '/')]
        if not isinstance(old, list):
            if not relevant and '' not in paths and new != old: changed.append(prefix)
            continue
        if not isinstance(new, list):
            changed.append(prefix); continue
        bad_indices = {int(path[len(prefix)+1:].split('/')[0]) for path in relevant
            if path.startswith(prefix + '/') and path[len(prefix)+1:].split('/')[0].isdigit()}
        bad_ids = {identity(old[index]) for index in bad_indices if index < len(old)}
        protected = [normalized_row(collection, row) for index, row in enumerate(old)
                     if index not in bad_indices]
        replacements = [normalized_row(collection, row) for row in new]
        # Collection-level cardinality/uniqueness errors can remove duplicate
        # copies, but cannot erase the distinct valid objects already present.
        if prefix in relevant: protected = list(set(protected))
        remaining = replacements[:]
        for row in protected:
            if row not in remaining: changed.append(prefix); break
            remaining.remove(row)
        can_add = prefix in relevant or None in bad_ids
        if not can_add:
            allowed = [normalized_row(collection, row) for row in new if identity(row) in bad_ids]
            for row in remaining:
                if row not in allowed: changed.append(prefix); break
                allowed.remove(row)
    if changed:
        raise InvalidActionResult('修复改变了 Schema 诊断范围之外的有效对象；恢复原值后再提交。',
            diagnostic=AttemptDiagnostic('REPAIR_SCOPE_VIOLATION', '/', tuple(sorted(set(changed)))))


def normalize_action_result(
    envelope: Mapping[str, object],
    raw_output: bytes,
    *,
    skill_root: Path,
    packet_payload: bytes | None = None,
) -> bytes:
    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise json.JSONDecodeError("duplicate object key", key, 0)
            value[key] = item
        return value

    def invalid_constant(value):
        raise json.JSONDecodeError("non-finite JSON number", value, 0)

    result = json.loads(
        raw_output.decode("utf-8"),
        object_pairs_hook=unique_object,
        parse_constant=invalid_constant,
    )
    diagnostics = validate_action_result(envelope, result, skill_root=skill_root)
    if diagnostics:
        findings = tuple(AttemptDiagnostic(item.code, item.path, ()) for item in diagnostics)
        raise InvalidActionResult("Action result 未通过精确 IR schema。",
            diagnostic=AttemptDiagnostic('INVALID_IR', '', (), findings))
    action_id = envelope.get("actionContractId")
    if packet_payload is not None:
        preserve_schema_candidate(json.loads(packet_payload), action_id, result)
    if action_id == "PRIOR_CONSOLIDATE-v2":
        if packet_payload is None or sha256_bytes(packet_payload) != envelope.get("packetSha256"):
            raise ValueError("Prior Consolidate normalization 必须绑定实际冻结 packet。")
        packet = json.loads(packet_payload)
        if canonical_json_bytes(packet) != packet_payload:
            raise ValueError("Prior Consolidate packet 必须是 canonical bytes。")
        result = assemble_prior_result(packet, result, skill_root=skill_root)
    return canonical_json_bytes(normalize_result_sets(action_id, result))


def normalize_result_sets(action_id, result):
    """Pure set normalization; callers separately validate schema before success."""
    action_id = {"SCOPE_REPAIR-v1":"SCOPE_SYNTHESIS-v1", "STORY_AC_REPAIR-v1":"STORY_AC-v1", "TASK_REPAIR-v1":"TASK-v1", "TASK_REPAIR-v2":"TASK-v2"}.get(action_id, action_id)
    if action_id in {"SOURCE_SCOPE-v1", "STORY_DESIGN-v1", "TASK_ESTIMATION-v1"}:
        for finding in result["findings"]:
            finding["subjectIds"].sort()
            finding["evidenceIds"].sort()
        result["findings"].sort(key=canonical_json_bytes)
    if action_id == "SOURCE_SCAN-v1":
        for item in result:
            for fact in item["facts"]:
                fact["evidenceIds"].sort()
            item["facts"].sort(key=lambda fact: fact["localKey"])
        result.sort(key=lambda item: item["coverageRootId"])
    elif action_id == "SOURCE_AUDIT-v1":
        for check in result["checks"]:
            check["relatedFactKeys"].sort()
            check["evidenceIds"].sort()
        result["checks"].sort(key=lambda check: (check["coverageRootId"], check["category"]))
    elif action_id in {"SCOPE_SYNTHESIS-v1", "SCOPE_PROPOSAL-v1", "SCOPE_JOIN-v1"}:
        for item in result["decisions"]:
            for key in ("factIds", "priorEntityIds"):
                item[key].sort()
            boundary = item["boundaryEvidence"]
            for key in ("evidenceIds", "observationKeys"):
                boundary[key].sort()
            boundary["facetFacts"].sort(key=canonical_json_bytes)
            if "responsibilityBoundaryIds" in boundary:
                boundary["responsibilityBoundaryIds"].sort()
            for relation in item["relations"]:
                relation["targetLocalKeys"].sort()
                relation["evidenceIds"].sort()
            item["relations"].sort(key=canonical_json_bytes)
        result["decisions"].sort(key=lambda item: item["localKey"])
    if action_id in {"TASK-v1", "TASK-v2"}:
        for task in result["tasks"]:
            task["acceptanceCriterionKeys"].sort()
            task["evidenceIds"].sort()
        result["tasks"].sort(key=lambda item: item["localKey"])
    if action_id == "STORY_AC-v1":
        for story in result["stories"]:
            for key in ("scopeDecisionKeys", "sourceFactIds"):
                story[key].sort()
            for criterion in story["acceptanceCriteria"]:
                criterion["sourceFactIds"].sort()
            story["acceptanceCriteria"].sort(key=lambda item: item["localKey"])
        result["stories"].sort(key=lambda item: item["localKey"])
    if action_id == "PROTOTYPE_ANALYZE-v1":
        result["observations"].sort(key=lambda item: item["localKey"])
        for observation in result["observations"]:
            for key in ("evidenceIds", "interactionIds", "relatedFactIds"):
                observation[key].sort()
    if action_id == "PROTOTYPE_BROWSER-v1":
        for discovery in result["unresolvedDiscoveries"]:
            discovery["sourceEvidenceIds"].sort()
    if action_id in {"PRIOR_ANALYZE-v1", "PRIOR_CONSOLIDATE-v1", "PRIOR_ANALYZE-v2", "PRIOR_ANALYZE-v3", "PRIOR_CONSOLIDATE-v2"}:
        for collection in ("entities", "sourceRelations", "entitySupersessions", "unextractedEvidence"):
            for item in result.get(collection, []):
                for key in ("evidenceIds", "predecessorLocalKeys", "successorLocalKeys"):
                    if key in item:
                        item[key].sort()
                if "cellAnchors" in item:
                    item["cellAnchors"].sort(key=canonical_json_bytes)
        result["entities"].sort(key=lambda item: item["localKey"])
        for collection in ("sourceRelations", "entitySupersessions", "unsupportedRegions", "unextractedEvidence"):
            if collection in result:
                result[collection].sort(key=canonical_json_bytes)
    return result


@lru_cache(maxsize=128)
def _check_schema_definition(payload: bytes) -> None:
    """Cache only successful checks of exact bytes, never mutable resources."""
    Draft202012Validator.check_schema(json.loads(payload.decode("utf-8")))


def load_registry(contract_root: Path) -> Registry:
    registry = Registry()
    seen_ids: set[str] = set()
    for path in sorted(contract_root.glob("*.schema.json")):
        payload = path.read_bytes()
        _check_schema_definition(payload)
        schema = json.loads(payload.decode("utf-8"))
        schema_id = schema.get("$id")
        if not isinstance(schema_id, str) or not schema_id:
            raise ValueError(f"Schema 缺少非空 $id：{path.name}")
        if schema_id in seen_ids:
            raise ValueError(f"Schema $id 重复：{schema_id}")
        seen_ids.add(schema_id)
        registry = registry.with_resource(schema_id, Resource.from_contents(schema))
    return registry


def load_schema_registry(skill_root: Path) -> Registry:
    return load_registry(skill_root / "contracts")


def _schema_ids(schema_name: str) -> tuple[str, ...]:
    if schema_name == "prior-state-decision-v2.schema.json":
        return ("urn:ai-sow:generate:next:prior-state-decision:2",)
    suffix = ".schema.json"
    if not schema_name.endswith(suffix):
        raise ValueError(f"Schema 名称必须以 {suffix} 结尾")
    stem = schema_name.removesuffix(suffix)
    return (f"urn:ai-sow:generate:next:{stem}:1",)


def _schema_contents(schema_name: str, registry: Registry) -> object:
    matches: list[object] = []
    for schema_id in _schema_ids(schema_name):
        resource = registry.get(schema_id)
        if resource is not None:
            matches.append(resource.contents)
    if len(matches) != 1:
        raise LookupError(
            f"Schema 必须由显式注入的单一 registry 唯一解析：{schema_name}"
        )
    return matches[0]


def _json_pointer(parts: object) -> str:
    escaped = [
        str(part).replace("~", "~0").replace("/", "~1") for part in parts  # type: ignore[arg-type]
    ]
    return "/" + "/".join(escaped) if escaped else ""


def _diagnostic(
    code: str,
    path: str,
    message: str,
    **details: object,
) -> Diagnostic:
    return Diagnostic(code=code, message=message, path=path, details=details)


def _sort_diagnostics(diagnostics: list[Diagnostic]) -> tuple[Diagnostic, ...]:
    return tuple(sorted(diagnostics, key=lambda item: (item.path, item.code, item.message)))


def validate_contract(
    value: object,
    schema_name: str,
    registry: Registry,
) -> tuple[Diagnostic, ...]:
    try:
        schema = _schema_contents(schema_name, registry)
        errors = tuple(
            Draft202012Validator(
                schema,
                registry=registry,
                format_checker=Draft202012Validator.FORMAT_CHECKER,
            ).iter_errors(value)
        )
    except (NoSuchResource, LookupError, ValueError) as error:
        return (
            _diagnostic(
                "CONTRACT_REFERENCE_INVALID",
                "",
                "合同引用无法解析。",
                schema=schema_name,
                errorType=type(error).__name__,
            ),
        )

    diagnostics: list[Diagnostic] = []
    for error in errors:
        code = {
            "required": "CONTRACT_REQUIRED",
            "additionalProperties": "CONTRACT_UNEXPECTED_PROPERTY",
        }.get(error.validator, "CONTRACT_INVALID")
        message = {
            "CONTRACT_REQUIRED": "合同缺少必填字段。",
            "CONTRACT_UNEXPECTED_PROPERTY": "合同包含未声明字段。",
            "CONTRACT_INVALID": "合同值不符合 Schema。",
        }[code]
        diagnostics.append(
            _diagnostic(
                code,
                _json_pointer(error.absolute_path),
                message,
                schema=schema_name,
                validator=str(error.validator),
                schemaPath=_json_pointer(error.absolute_schema_path),
            )
        )
    if schema_name == "run-budget-policy.schema.json" and not diagnostics:
        from provider_adapter import validate_model_estimator

        assert isinstance(value, Mapping)
        try:
            validate_model_estimator(value["modelProfileId"], value["estimatorVersion"])
        except ValueError:
            diagnostics.append(
                _diagnostic(
                    "RUN_BUDGET_ADAPTER_INVALID",
                    "/estimatorVersion",
                    "预算必须绑定已注册 model profile 的 estimator。",
                )
            )
        reserves = sum(
            value[name]
            for name in (
                "outputReserveTokens", "hydrateReserveTokens", "safetyMarginTokens"
            )
        )
        if value["modelContextLimitTokens"] <= reserves:
            diagnostics.append(
                _diagnostic(
                    "RUN_BUDGET_USABLE_INPUT_INVALID",
                    "/modelContextLimitTokens",
                    "模型上下文扣除预留后必须仍有正数输入余额。",
                )
            )
    if schema_name == "request.schema.json" and isinstance(value, Mapping):
        demo = value.get("demo")
        if isinstance(demo, Mapping):
            entrypoint = demo.get("entrypoint")
            files = demo.get("files")
            paths = {
                path
                for item in files
                if isinstance(item, Mapping)
                and isinstance((path := item.get("path")), str)
            } if isinstance(files, list) else set()
            if (
                not diagnostics
                and isinstance(entrypoint, str)
                and entrypoint not in paths
            ):
                diagnostics.append(
                    _diagnostic(
                        "DEMO_ENTRYPOINT_OUTSIDE_BUNDLE",
                        "/demo/entrypoint",
                        "Demo entrypoint 必须引用 files[] 中声明的 HTML 文件。",
                    )
                )
    return _sort_diagnostics(diagnostics)


def validate_state_combination(
    value: object,
    registry: Registry,
) -> tuple[Diagnostic, ...]:
    diagnostics = list(validate_contract(value, "run-state.schema.json", registry))
    if diagnostics or not isinstance(value, Mapping):
        return _sort_diagnostics(diagnostics)

    candidate_sha256 = value.get("currentCandidateSha256")
    candidate_path = value.get("currentCandidatePath")
    if (candidate_sha256 is None) != (candidate_path is None):
        diagnostics.append(
            _diagnostic(
                "RUN_CANDIDATE_BINDING_INCOMPLETE",
                "/currentCandidatePath",
                "当前候选路径与哈希必须同时存在或同时为空。",
            )
        )
    return _sort_diagnostics(diagnostics)


def validate_action_binding(
    envelope: Mapping[str, object],
    *,
    action_id: str,
    envelope_sha256: str,
    input_revision_sha256: str,
    base_candidate_sha256: str,
    result_path: object,
    expected_action_ids: tuple[str, ...],
) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    envelope_action_id = envelope.get("actionId")
    if action_id != envelope_action_id:
        diagnostics.append(
            _diagnostic(
                "ACTION_ID_MISMATCH",
                "/actionId",
                "提交的 action ID 与 envelope 不一致。",
            )
        )
    if envelope_action_id not in expected_action_ids:
        diagnostics.append(
            _diagnostic(
                "ACTION_NOT_EXPECTED",
                "/actionId",
                "该 action 不是当前 Run State 等待的动作。",
            )
        )
    if envelope_sha256 != sha256_bytes(canonical_json_bytes(envelope)):
        diagnostics.append(
            _diagnostic(
                "ACTION_ENVELOPE_HASH_MISMATCH",
                "",
                "提交未绑定当前 action envelope 的规范哈希。",
            )
        )
    if input_revision_sha256 != envelope.get("inputRevisionSha256"):
        diagnostics.append(
            _diagnostic(
                "ACTION_INPUT_REVISION_STALE",
                "/inputRevisionSha256",
                "提交绑定的 Input Revision 已过期。",
            )
        )
    if base_candidate_sha256 != envelope.get("baseCandidateSha256"):
        diagnostics.append(
            _diagnostic(
                "ACTION_BASE_CANDIDATE_STALE",
                "/baseCandidateSha256",
                "提交绑定的基础候选已过期。",
            )
        )

    if result_path != envelope.get("resultPath"):
        diagnostics.append(
            _diagnostic(
                "ACTION_RESULT_PATH_MISMATCH",
                "/resultPath",
                "提交路径必须与 envelope 锁定的输出路径完全一致。",
            )
        )
    return _sort_diagnostics(diagnostics)


_DIAGNOSTIC_CLASSIFICATIONS: dict[str, DiagnosticClassification] = {
    "GLOBAL_SCOPE_CAPACITY_EXCEEDED": DiagnosticClassification(
        "CONTRACT_UNSUPPORTED", "STAGE_1", False
    ),
    "SOURCE_SEMANTIC_CONFLICT": DiagnosticClassification(
        "INPUT_REQUIRED", "INPUT", True
    ),
    "DESIGN_COVERAGE_INSUFFICIENT": DiagnosticClassification(
        "INPUT_REQUIRED", "INPUT", True
    ),
    "STORY_COVERAGE_OUTSTANDING": DiagnosticClassification(
        "OWNER_FIX_REQUIRED", "STAGE_2", True
    ),
    "STORY_GLOBAL_JOIN_REQUIRED": DiagnosticClassification("CONTROL", "STAGE_2", True),
    "TASK_STANDARD_TYPE_UNREPRESENTABLE": DiagnosticClassification(
        "CONTRACT_UNSUPPORTED", "STAGE_3", False
    ),
    "TASK_CHALLENGER_NOT_REVIEWED": DiagnosticClassification(
        "OWNER_FIX_REQUIRED", "STAGE_3", True
    ),
    "PRIOR_MATCH_SEARCH_INCOMPLETE": DiagnosticClassification(
        "OWNER_FIX_REQUIRED", "STAGE_3", True
    ),
    "TASK_X_SPLIT_REQUIRED": DiagnosticClassification(
        "OWNER_FIX_REQUIRED", "STAGE_3", True
    ),
    "THEME_JOIN_REQUIRED": DiagnosticClassification("CONTROL", "REVIEW", True),
    "RUN_IN_PROGRESS": DiagnosticClassification("CONTROL", "ORCHESTRATOR", False),
    "SIT_SUPPORT_ASSIGNMENT_NON_UNIQUE": DiagnosticClassification(
        "OWNER_FIX_REQUIRED", "STAGE_3", True
    ),
    "HOST_CAPABILITY_MISSING": DiagnosticClassification(
        "SYSTEM_FAILED", "ORCHESTRATOR", False
    ),
    "BUDGET_EXCEEDED": DiagnosticClassification(
        "SYSTEM_FAILED", "ORCHESTRATOR", False
    ),
}


def classify_diagnostic(
    code: str,
    *,
    source_sufficient: bool | None = None,
) -> DiagnosticClassification:
    if code == "TASK_TYPE_AMBIGUOUS":
        if source_sufficient is None:
            raise ValueError("TASK_TYPE_AMBIGUOUS 必须提供 source_sufficient")
        if source_sufficient:
            return DiagnosticClassification("OWNER_FIX_REQUIRED", "STAGE_3", True)
        return DiagnosticClassification("INPUT_REQUIRED", "INPUT", True)
    try:
        return _DIAGNOSTIC_CLASSIFICATIONS[code]
    except KeyError as error:
        raise ValueError(f"未知诊断码：{code}") from error


def parse_repair_document(payload: bytes, definition: str) -> object:
    """Strict versioned repair values; callers own execution and business validation."""
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('修复 JSON 包含重复属性。')
            value[key] = item
        return value
    def reject_constant(value):
        raise ValueError('修复 JSON 数字必须有限。')
    try:
        value = json.loads(payload.decode('utf-8'), object_pairs_hook=unique, parse_constant=reject_constant)
        root = Path(__file__).resolve().parents[1]
        validator = Draft202012Validator({'$ref': 'urn:ai-sow:generate:next:candidate-repair:1#/$defs/' + definition},
                                        registry=load_schema_registry(root))
        errors = list(validator.iter_errors(value))
        if errors:
            raise ValueError('修复记录不符合封闭 Schema：' + ', '.join(_json_pointer(e.absolute_path) for e in errors))
        return value
    except (ValueError, UnicodeError) as error:
        raise InvalidActionResult(str(error)) from error
