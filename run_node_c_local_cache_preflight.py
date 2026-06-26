#!/usr/bin/env python3
"""Validate Node-C local task cache without contacting a relay."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from node_bridge_testkit.node_adapter import execute_task, write_task_cache


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="node_c_cache_preflight_"))
    try:
        task = {
            "task_id": "task_cache_preflight_001",
            "target_node": "node-c",
            "task_type": "reply_exactly",
            "payload": {
                "marker": "NODEC-CACHE-001",
                "text": "STATUS=NODEC_CACHE_OK; MARKER=NODEC_CACHE_001; NEXT=READY_FOR_CODEX_CACHE_ADAPTER",
            },
        }
        pulled_path = write_task_cache(root, task, "pulled")
        in_progress_path = write_task_cache(root, task, "in_progress")
        result = execute_task(task, "node-c", sandbox_dir=root)
        completed_path = write_task_cache(root, task, "completed", result=result, posted={"ok": True})
        record = json.loads(Path(completed_path).read_text(encoding="utf-8"))
        ok = (
            pulled_path == in_progress_path == completed_path
            and record.get("status") == "completed"
            and (record.get("result") or {}).get("agent_message") == task["payload"]["text"]
            and record.get("posted_ok") is True
        )
        print(json.dumps({
            "ok": ok,
            "cache_path": completed_path,
            "record_status": record.get("status"),
            "agent_message": (record.get("result") or {}).get("agent_message"),
            "claim": "node_c_local_task_cache_preflight_passed" if ok else "node_c_local_task_cache_preflight_failed",
            "cannot_claim": [
                "real_codex_ipc",
                "external_node_connected",
                "formal_ack",
                "external_send",
                "file_execution",
                "persistent_service",
                "long_running_autonomy",
                "production_ready_connection",
            ],
        }, ensure_ascii=False, indent=2))
        return 0 if ok else 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
