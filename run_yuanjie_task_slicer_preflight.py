#!/usr/bin/env python3
"""Validate Yuanjie task slicing output shape."""

from __future__ import annotations

import json

from yuanjie_task_slicer import slice_goal


def main() -> int:
    result = slice_goal(
        "Verify external node can receive a file task and report rollout evidence.",
        node_id="node-c",
        prefix="NODEC",
    )
    slices = result.get("slices") or []
    ok = (
        result.get("schema") == "yuanjie_task_slices_v0.1"
        and len(slices) == 3
        and all(item.get("expected_agent_message") for item in slices)
        and all("formal_ack" in item.get("cannot_claim", []) for item in slices)
        and slices[0].get("kind") == "READ"
        and slices[1].get("kind") == "STRUCT"
        and slices[2].get("kind") == "FILE_PREFLIGHT"
    )
    print(json.dumps({
        "ok": ok,
        "slice_count": len(slices),
        "markers": [item.get("slice_id") for item in slices],
        "claim": "yuanjie_task_slicer_preflight_passed" if ok else "yuanjie_task_slicer_preflight_failed",
        "cannot_claim": result.get("cannot_claim"),
    }, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
