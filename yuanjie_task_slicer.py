#!/usr/bin/env python3
"""Create small Yuanjie task slices from one larger goal.

The slicer is deliberately deterministic and local-only. It does not call a
model. Its job is to turn a broad goal into small, observable task cards with
markers, expected outputs, acceptance gates, and explicit cannot-claim fields.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from typing import Any


DEFAULT_CANNOT_CLAIM = [
    "formal_ack",
    "external_send",
    "file_execution",
    "long_running_autonomy",
    "production_ready_connection",
    "full_loop",
    "global_experience_write",
]


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_marker_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", value.upper()).strip("_")
    return (cleaned or "TASK")[:32]


def make_slice(
    node_id: str,
    prefix: str,
    index: int,
    kind: str,
    goal: str,
) -> dict[str, Any]:
    marker = f"{safe_marker_part(prefix)}_{index:03d}_{kind}"
    if kind == "READ":
        expected = f"STATUS=READ_OK; MARKER={marker}; NEXT=STRUCT"
        prompt = (
            f"Read this task slice only. Goal: {goal}. "
            f"Reply exactly: {expected}"
        )
        gates = ["assistant_answer_seen", "expected_answer_seen", "task_complete_seen"]
    elif kind == "STRUCT":
        expected = f"STATUS=STRUCT_OK; MARKER={marker}; NEXT=FILE_OR_NEXT_SLICE"
        prompt = (
            f"Return one structured status for this slice. Goal: {goal}. "
            f"Reply exactly: {expected}"
        )
        gates = ["assistant_answer_seen", "expected_answer_seen", "task_complete_seen"]
    elif kind == "FILE_PREFLIGHT":
        expected = f"STATUS=FILE_PREFLIGHT_OK; MARKER={marker}; NEXT=SANDBOX_ONLY"
        prompt = (
            "Confirm file-channel boundary only. "
            "Do not read arbitrary files. Do not execute files. "
            f"Goal: {goal}. Reply exactly: {expected}"
        )
        gates = ["sandbox_file_write", "sha256_match", "task_complete_seen"]
    else:
        raise ValueError(f"unsupported slice kind: {kind}")

    return {
        "slice_id": marker,
        "node_id": node_id,
        "kind": kind,
        "goal_excerpt": goal[:240],
        "prompt": prompt,
        "expected_agent_message": expected,
        "acceptance_gates": gates,
        "boundary": {
            "small_task": True,
            "no_input_box": True,
            "no_external_send": True,
            "no_formal_ack": True,
            "no_file_execution": True,
            "rollout_required": True,
        },
        "cannot_claim": DEFAULT_CANNOT_CLAIM,
    }


def slice_goal(goal: str, node_id: str = "node-c", prefix: str = "YJ_SLICE") -> dict[str, Any]:
    kinds = ["READ", "STRUCT", "FILE_PREFLIGHT"]
    slices = [make_slice(node_id, prefix, index + 1, kind, goal) for index, kind in enumerate(kinds)]
    return {
        "schema": "yuanjie_task_slices_v0.1",
        "created_at": now_utc(),
        "goal": goal,
        "node_id": node_id,
        "strategy": "small_observable_slices",
        "slice_count": len(slices),
        "slices": slices,
        "claim": "yuanjie_task_slices_created",
        "cannot_claim": DEFAULT_CANNOT_CLAIM,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create Yuanjie small task slices.")
    parser.add_argument("--goal", required=True)
    parser.add_argument("--node-id", default="node-c")
    parser.add_argument("--prefix", default="YJ_SLICE")
    args = parser.parse_args()
    print(json.dumps(slice_goal(args.goal, node_id=args.node_id, prefix=args.prefix), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
