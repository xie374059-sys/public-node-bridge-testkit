#!/usr/bin/env python3
"""Run a local-only allowlisted task-package execution preflight."""

from __future__ import annotations

import base64
import hashlib
import json

from node_bridge_testkit.node_adapter import execute_task


def main() -> int:
    package = {
        "schema": "yuanjie_task_package_v0.1",
        "marker": "NODEC-PACKAGE-LOCAL",
        "action": "count_lines",
        "input_text": "one\ntwo\nthree\n",
        "expected_line_count": 3,
        "boundary": {
            "shell_execution": False,
            "file_execution": False,
            "external_send": False,
        },
    }
    raw = json.dumps(package, ensure_ascii=False, indent=2).encode("utf-8")
    task = {
        "task_id": "task_local_package",
        "target_node": "node-c",
        "task_type": "task_package",
        "payload": {
            "marker": "NODEC-PACKAGE-LOCAL",
            "filename": "nodec_task_package_local.json",
            "content_b64": base64.b64encode(raw).decode("ascii"),
            "sha256": hashlib.sha256(raw).hexdigest(),
        },
    }
    result = execute_task(task, "node-c", sandbox_dir=".node_c_avatar")
    ok = (
        result.get("status") == "ok"
        and result.get("execution") == "local_adapter_task_package_execute_allowlist"
        and result.get("action") == "count_lines"
        and result.get("line_count") == 3
    )
    print(json.dumps({
        "ok": ok,
        "result": result,
        "claim": "node_c_task_package_local_preflight_passed" if ok else "node_c_task_package_local_preflight_failed",
        "cannot_claim": [
            "real_codex_ipc",
            "formal_ack",
            "external_send",
            "arbitrary_file_execution",
            "persistent_service",
            "long_running_autonomy",
        ],
    }, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
