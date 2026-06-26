#!/usr/bin/env python3
"""Validate the local cached-task wakeup path without contacting a relay."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from node_bridge_testkit.avatar_runtime import install_avatar, read_json
from node_bridge_testkit.node_adapter import write_task_cache
from run_next_cached_task import execute_next_cached_task


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="node_c_next_cache_preflight_"))
    try:
        install_avatar(node_id="node-c", install_dir=root)
        task = {
            "task_id": "task_next_cache_preflight_001",
            "target_node": "node-c",
            "task_type": "reply_exactly",
            "payload": {
                "marker": "NODEC-NEXT-CACHE-001",
                "text": "STATUS=NODEC_NEXT_CACHE_OK; MARKER=NODEC_NEXT_CACHE_001; NEXT=READY_FOR_CACHE_WAKEUP",
            },
        }
        seed_path = write_task_cache(root, task, "pulled")
        result = execute_next_cached_task(install_dir=root, node_id="node-c")
        record = read_json(Path(result.get("cache_path", seed_path)))
        ok = (
            result.get("ok") is True
            and record.get("status") == "completed_local"
            and result.get("agent_message") == task["payload"]["text"]
        )
        print(json.dumps({
            "ok": ok,
            "seed_cache_path": seed_path,
            "result": result,
            "record_status": record.get("status"),
            "claim": "node_c_next_cached_task_preflight_passed" if ok else "node_c_next_cached_task_preflight_failed",
            "cannot_claim": [
                "real_codex_ipc",
                "task_sent_to_codex",
                "codex_reply_read",
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
