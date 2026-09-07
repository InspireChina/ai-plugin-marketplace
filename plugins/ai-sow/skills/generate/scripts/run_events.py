from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from jsonschema import Draft202012Validator

from models import RunEvent
from referencing import Registry, Resource


def run_event_value(event: RunEvent) -> dict[str, object]:
    return {
        "runId": event.run_id,
        "sequence": event.sequence,
        "type": event.type,
        "occurredAtUtc": event.occurred_at_utc,
        "payload": dict(event.payload),
    }


def validate_run_event_log(events: Sequence[RunEvent]) -> None:
    schema = json.loads(
        (Path(__file__).parents[1] / "contracts/run-event.schema.json").read_text(
            encoding="utf-8"
        )
    )
    action_schema = json.loads((Path(__file__).parents[1] / "contracts/action.schema.json").read_bytes())
    registry = Registry().with_resource(action_schema['$id'], Resource.from_contents(action_schema))
    validator = Draft202012Validator(
        schema, registry=registry,
        format_checker=Draft202012Validator.FORMAT_CHECKER
    )
    run_id = events[0].run_id if events else None
    seen_waits: set[str] = set()
    open_wait: str | None = None
    state: str | None = None
    repair_selections: dict[str, Mapping[str, object]] = {}
    for sequence, event in enumerate(events, 1):
        errors = list(validator.iter_errors(run_event_value(event)))
        if errors:
            raise ValueError("RunEvent payload 与 type 不匹配。")
        if event.run_id != run_id or event.sequence != sequence:
            raise ValueError("RunEvent 必须属于同一 run 且 sequence 从 1 连续。")
        if event.type == "CANDIDATE_REPAIR_PROTOCOL_SELECTED":
            logical_id = str(event.payload["originLogicalWorkId"])
            if logical_id in repair_selections:
                raise ValueError("同一 lineage 只能选择一次候选修复协议。")
            repair_selections[logical_id] = event.payload
        if event.type == "RUN_STATE_CHANGED":
            state = str(event.payload["toState"])
        elif event.type == "WAITING_INPUT_ENTERED":
            wait_id = str(event.payload["waitId"])
            if open_wait is not None or wait_id in seen_waits:
                raise ValueError("waitId 必须唯一且不能重叠等待。")
            seen_waits.add(wait_id)
            open_wait = wait_id
        elif event.type == "WAITING_INPUT_EXITED":
            if open_wait != event.payload["waitId"]:
                raise ValueError("等待退出必须匹配尚未闭合的 waitId。")
            open_wait = None
    if open_wait is not None and state != "WAITING_INPUT":
        raise ValueError("只有 WAITING_INPUT 状态允许最后一个等待尚未闭合。")
