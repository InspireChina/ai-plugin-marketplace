"""Explicit changes only; complements are derived from the effective Prior root."""
from __future__ import annotations
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from contracts import load_schema_registry, validate_contract
from prior_state import derive_effective_prior

ChangeGraph = Mapping[str, object]
PriorStateSnapshot = Mapping[str, object]


@dataclass(frozen=True)
class ChangeViews:
    target_origin: Mapping[str, str]
    prior_fate: Mapping[str, str]


class ChangeGraphUnsupported(ValueError):
    code = "CONTRACT_UNSUPPORTED"


def change_cardinality_supported(kind: str, prior_count: int, target_count: int) -> bool:
    return ((kind in {"REUSE_DEPENDENCY", "ADJUST"} and (prior_count, target_count) == (1, 1))
            or (kind == "SPLIT" and prior_count == 1 and target_count > 1)
            or (kind == "MERGE" and prior_count > 1 and target_count == 1))


def derive_change_views(graph: ChangeGraph, prior: PriorStateSnapshot | None,
                        target_entity_ids: Sequence[str]) -> ChangeViews:
    if validate_contract(graph, "change-graph.schema.json", load_schema_registry(Path(__file__).parents[1])):
        raise ValueError("ChangeGraph schema 无效。")
    if len(target_entity_ids) != len(set(target_entity_ids)):
        raise ValueError("target 全集必须唯一。")
    active = set(derive_effective_prior(prior)["activeEntityIds"]) if prior is not None else set()
    targets = dict.fromkeys(sorted(target_entity_ids), "NEW")
    fates = dict.fromkeys(sorted(active), "KEEP")
    used_prior, used_target = set(), set()
    for group in graph["changeGroups"]:
        previous, current = set(group["priorEntityIds"]), set(group["targetEntityIds"])
        if not change_cardinality_supported(group["kind"], len(previous), len(current)):
            raise ChangeGraphUnsupported("V1 不支持该变更基数；必须由来源提供可解释的独立边界。")
        if not previous <= active or not current <= targets.keys() or previous & used_prior or current & used_target:
            raise ValueError("ChangeGraph 引用缺失、非 active Prior 或显式集合重叠。")
        used_prior.update(previous)
        used_target.update(current)
        targets.update(dict.fromkeys(current, group["kind"]))
        fates.update(dict.fromkeys(previous, group["kind"]))
    evidence = {item["priorEvidenceId"] for item in prior["evidence"]} if prior is not None else set()
    by_id = {item["entityId"]: item for item in prior["entities"]} if prior is not None else {}
    for retired in graph["retiredPrior"]:
        entity_id, refs = retired["priorEntityId"], set(retired["evidenceIds"])
        if entity_id not in active or entity_id in used_prior:
            raise ValueError("退役必须引用唯一未进入变更组的 active Prior。")
        if not refs & set(by_id[entity_id]["evidenceIds"]) or not refs - evidence:
            raise ValueError("退役必须同时引用该 Prior 证据与本轮显式移除依据。")
        used_prior.add(entity_id)
        fates[entity_id] = "RETIRE"
    return ChangeViews(MappingProxyType(targets), MappingProxyType(fates))
