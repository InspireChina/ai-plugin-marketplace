from __future__ import annotations

TEST_LAYER = "unit"

import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))


@pytest.mark.parametrize(
    "mutation",
    [
        "none",
        "open",
        "run",
        "gap",
        "duplicate",
        "payload",
        "unmatched",
        "double_enter",
        "reused_wait",
        "closed_state",
        "middle_open",
    ],
)
def test_run_event_log_closure(mutation):
    from models import RunEvent
    from run_events import validate_run_event_log

    def event(sequence, kind, payload):
        return RunEvent("run-1", sequence, kind, "2026-09-05T00:00:00Z", payload)

    events = [
        event(
            1, "RUN_STATE_CHANGED", {"fromState": "CREATED", "toState": "WAITING_INPUT"}
        ),
        event(
            2,
            "WAITING_INPUT_ENTERED",
            {"waitId": "wait-1", "reasonCode": "BUDGET_EXHAUSTED"},
        ),
        event(
            3,
            "WAITING_INPUT_EXITED",
            {"waitId": "wait-1", "resolutionKind": "ABANDONED"},
        ),
        event(
            4,
            "RUN_STATE_CHANGED",
            {"fromState": "WAITING_INPUT", "toState": "ABANDONED"},
        ),
    ]
    if mutation == "open":
        events = events[:2]
    elif mutation == "run":
        events[1] = replace(events[1], run_id="run-2")
    elif mutation == "gap":
        events[1] = replace(events[1], sequence=3)
    elif mutation == "duplicate":
        events[1] = replace(events[1], sequence=1)
    elif mutation == "payload":
        events[1] = replace(events[1], payload={"waitId": "wait-1"})
    elif mutation == "unmatched":
        events[2] = replace(
            events[2], payload={"waitId": "wait-2", "resolutionKind": "ABANDONED"}
        )
    elif mutation == "double_enter":
        events[2] = event(
            3,
            "WAITING_INPUT_ENTERED",
            {"waitId": "wait-2", "reasonCode": "BUDGET_EXHAUSTED"},
        )
    elif mutation == "reused_wait":
        events[3] = event(
            4,
            "WAITING_INPUT_ENTERED",
            {"waitId": "wait-1", "reasonCode": "BUDGET_EXHAUSTED"},
        )
    elif mutation == "closed_state":
        events = events[:2] + [replace(events[3], sequence=3)]
    elif mutation == "middle_open":
        events = events[:2] + [
            event(
                3,
                "WAITING_INPUT_ENTERED",
                {"waitId": "wait-2", "reasonCode": "BUDGET_EXHAUSTED"},
            ),
            event(
                4,
                "WAITING_INPUT_EXITED",
                {"waitId": "wait-2", "resolutionKind": "ABANDONED"},
            ),
        ]
    if mutation in {"none", "open"}:
        validate_run_event_log(events)
    else:
        with pytest.raises(ValueError):
            validate_run_event_log(events)
