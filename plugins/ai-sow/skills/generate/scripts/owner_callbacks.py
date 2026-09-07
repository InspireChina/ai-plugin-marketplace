from __future__ import annotations

import json
from pathlib import Path

from contracts import (
    InvalidActionResult,
    canonical_json_bytes,
    normalize_action_result,
    sha256_bytes,
)
from final_review import (
    OWNER_COLLECTION,
    is_manual_repair,
    repair_root_keys,
    validate_bound_review_result,
)


SKILL_ROOT = Path(__file__).resolve().parents[1]


def _semantic_owner_binding(stage, owner_packet):
    import delivery_compiler
    import scope_compiler
    import task_compiler

    if stage == "SCOPE":
        return scope_compiler, lambda raw: scope_compiler.validate_bound_scope_result(
            "SCOPE_SYNTHESIS", owner_packet, raw
        )
    if stage == "STORY_AC":
        return delivery_compiler, lambda raw: delivery_compiler.validate_bound_story_result(
            owner_packet, raw
        )
    if stage == "TASK":
        return task_compiler, lambda raw: task_compiler.validate_bound_task_result(
            owner_packet, raw
        )
    raise ValueError("语义修复只属于三个阶段 Owner。")


def _semantic_candidate_callbacks(envelope, packet, semantic_source):
    from candidate_repair import (
        build_repair_plan,
        diagnostic_report,
        group_fields,
        index_candidate,
        issues_from_diagnostics,
        make_issue,
        schema_at,
        transform_roots_group,
    )

    stage = semantic_source["stageKind"]
    owner_packet = semantic_source["ownerPacket"]
    review = semantic_source["reviewDecision"]
    resolution = semantic_source.get("ownerResolution")
    owner_contract_id = semantic_source["ownerActionContractId"]
    owner, bound = _semantic_owner_binding(stage, owner_packet)
    collection = OWNER_COLLECTION[stage]

    def semantic_issue(finding):
        root = finding["subjectIds"][0] if finding["subjectIds"] else ""
        path = "/" + collection + "/" + root if root else "/" + collection
        issue = make_issue(
            "SEMANTIC_" + finding["code"],
            path,
            stage,
            finding["message"],
            "仅修改 Review 明确定位的 Owner root，并由 fresh Review 重新判断。",
            subjects=[
                {"objectId": collection + "/" + key}
                for key in finding["subjectIds"]
            ],
        )
        issue["evidenceRefs"] = [
            {
                "refId": key,
                "sha256": sha256_bytes(canonical_json_bytes(key)),
            }
            for key in finding.get("evidenceIds", ())
        ]
        return issue

    def mechanical_issues(raw):
        try:
            bound(raw)
        except InvalidActionResult as error:
            diagnostics = error.diagnostic.findings or (error.diagnostic,)
            return issues_from_diagnostics(diagnostics, stage, json.loads(raw))
        return []

    def diagnose(raw, origin):
        issues = mechanical_issues(raw)
        if sha256_bytes(raw) == semantic_source["ownerIRSha256"]:
            issues.extend(semantic_issue(finding) for finding in review["findings"])
        return diagnostic_report(
            raw,
            issues,
            owner=stage,
            checker_file=owner.__file__,
            packet=owner_packet,
            origin=origin,
            blocked=(),
            domains=["SCHEMA", "OWNER_BINDINGS", "SEMANTIC_REVIEW"],
        )

    def plan(raw, report, origin):
        value = json.loads(raw)
        roots = repair_root_keys(stage, value, review, resolution)
        rows = {
            row["localKey"]: index
            for index, row in enumerate(value[collection])
        }
        direct = {}
        broad = False
        for finding in review["findings"]:
            issue_id = semantic_issue(finding)["issueId"]
            paths = []
            for key in finding["subjectIds"]:
                projected = semantic_source["ownerIndex"][key]["path"]
                suffix = (
                    finding["path"][len(projected) :]
                    if finding["path"].startswith(projected)
                    else ""
                )
                if stage == "SCOPE" and suffix == "/name":
                    paths.append(
                        f"/{collection}/{rows[key]}/boundaryEvidence/name"
                    )
                elif stage == "STORY_AC" and suffix == "/name":
                    paths.append(
                        f"/{collection}/{rows[key]}/deliverableOutcome"
                    )
                elif stage == "TASK" and suffix in {
                    "/name",
                    "/deliverableBoundary",
                }:
                    paths.append(
                        f"/{collection}/{rows[key]}/deliverableBoundary"
                    )
                elif stage == "TASK" and suffix == "/complexity":
                    paths.append(
                        f"/{collection}/{rows[key]}/complexityDecision"
                    )
                else:
                    broad = True
            direct[issue_id] = paths
        if is_manual_repair(resolution):
            allowed = set(resolution["allowedFields"])

            def permitted(path):
                return (
                    path.rsplit("/", 1)[-1] in allowed
                    or stage == "SCOPE"
                    and "boundaryEvidence" in allowed
                    and "/boundaryEvidence/" in path
                )

            direct = {
                issue_id: [path for path in paths if permitted(path)]
                for issue_id, paths in direct.items()
            }
            if broad or any(not paths for paths in direct.values()):
                raise InvalidActionResult(
                    "人工裁定 finding 不能映射到 allowedFields。"
                )
        if not broad:
            groups = group_fields(raw, report, owner_contract_id, direct)
            if groups:
                return build_repair_plan(raw, report, groups, origin=origin)
        entries = [
            entry
            for entry in index_candidate(
                raw, inherited=report.get("objectIndex", ())
            )
            if entry["objectId"]
            in {collection + "/" + key for key in roots}
        ]
        if len(entries) != len(roots):
            raise InvalidActionResult(
                "Review root 不能解析为唯一 Owner 对象。"
            )
        schema = schema_at(owner_contract_id, f"/{collection}/0")
        group = transform_roots_group(
            raw,
            entries,
            schema,
            [
                item["issueId"]
                for item in report["issues"]
                if item["code"].startswith("SEMANTIC_")
            ],
            namespace=roots[0] + ":repair:",
            maximum=max(1, len(roots) * 2),
        )
        return build_repair_plan(raw, report, [group], origin=origin)

    def full(raw):
        bound(raw)

    return diagnose, plan, full


def candidate_owner_callbacks(
    envelope,
    packet,
    *,
    inventories=(),
    revision_bytes=None,
    semantic_source=None,
):
    """Bind professional validators for live and portable candidate proofs."""
    if semantic_source is not None:
        return _semantic_candidate_callbacks(envelope, packet, semantic_source)

    from candidate_repair import (
        build_repair_plan,
        diagnostic_report,
        group_fields,
        issues_from_diagnostics,
        schema_issues,
    )
    import delivery_compiler
    import prior_state
    import prototype_analysis
    import scope_compiler
    import task_compiler

    contract_id = envelope["actionContractId"]
    kind = contract_id.rpartition("-v")[0]
    context = {"action_contract_id": contract_id}
    if kind.startswith("PRIOR_"):
        owner = prior_state
        context.update(
            inventories=inventories,
            input_revision_bytes=revision_bytes,
        )
        bound = lambda raw: prior_state.validate_bound_prior_result(
            kind,
            packet,
            raw,
            inventories=inventories,
            input_revision_bytes=revision_bytes,
        )
    elif kind in {
        "SOURCE_SCAN",
        "SOURCE_AUDIT",
        "SCOPE_SYNTHESIS",
        "SCOPE_PROPOSAL",
        "SCOPE_JOIN",
    }:
        owner = scope_compiler
        bound = lambda raw: owner.validate_bound_scope_result(
            kind, packet, raw
        )
    elif kind == "STORY_AC":
        owner = delivery_compiler
        bound = lambda raw: owner.validate_bound_story_result(packet, raw)
    elif kind == "TASK":
        owner = task_compiler
        bound = lambda raw: owner.validate_bound_task_result(packet, raw)
    elif kind in {"PROTOTYPE_SCENARIO", "PROTOTYPE_ANALYZE"}:
        owner = prototype_analysis
        bound = lambda raw: owner.validate_bound_prototype_result(
            kind,
            packet["workItems"][0]["payload"],
            raw,
            packet=packet,
        )
    elif kind in {"SOURCE_SCOPE", "STORY_DESIGN", "TASK_ESTIMATION"}:
        owner = None
        bound = lambda raw: validate_bound_review_result(packet, raw)
    else:
        raise InvalidActionResult(
            "该执行责任不接受模型字段补丁。"
        )

    def normalize(raw):
        return normalize_action_result(
            envelope,
            raw,
            skill_root=SKILL_ROOT,
            packet_payload=canonical_json_bytes(packet),
        )

    def full(raw):
        bound(normalize(raw))

    def diagnose(raw, origin):
        if owner is not None:
            return owner.diagnose_candidate(
                kind, packet, raw, origin=origin, **context
            )
        value = json.loads(raw)
        issues = schema_issues(contract_id, value, "REVIEWER")
        blocked = ["REVIEW_OBLIGATIONS"] if issues else []
        if not issues:
            try:
                bound(canonical_json_bytes(value))
            except InvalidActionResult as error:
                issues += issues_from_diagnostics(
                    error.diagnostic.findings or [error.diagnostic],
                    "REVIEWER",
                    value,
                )
        return diagnostic_report(
            raw,
            issues,
            owner="REVIEWER",
            checker_file=__file__,
            packet=packet,
            origin=origin,
            blocked=blocked,
            domains=(
                ["SCHEMA", "REVIEW_OBLIGATIONS"]
                if not blocked
                else ["SCHEMA"]
            ),
        )

    def plan(raw, report, origin):
        if owner is not None:
            return owner.plan_candidate_repair(
                kind,
                packet,
                raw,
                report,
                origin=origin,
                **context,
            )
        groups = group_fields(
            raw,
            report,
            contract_id,
            {
                issue["issueId"]: ["/decision", "/findings"]
                for issue in report["issues"]
            },
        )
        if not groups:
            raise InvalidActionResult(
                "Review 格式缺口不能安全定位，保留完整义务等待 Reviewer。"
            )
        return build_repair_plan(raw, report, groups, origin=origin)

    return diagnose, plan, full
