#!/usr/bin/env python3
"""Validate the local loop-readiness sensor with a temporary avatar sandbox."""

from __future__ import annotations

import base64
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from node_bridge_testkit.avatar_runtime import install_avatar, now_utc, update_state, write_json
from node_bridge_testkit.node_adapter import write_task_cache
from run_node_c_loop_readiness import build_loop_readiness


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="node_c_loop_readiness_"))
    try:
        install = install_avatar(node_id="node-c", install_dir=root)
        state = json.loads((root / "state.json").read_text(encoding="utf-8"))
        update_state(root, state, "loop_readiness_preflight_heartbeat")
        write_json(root / "session_binding.json", {
            "schema": "node_c_session_binding_v0.1",
            "node_id": "node-c",
            "conversation_id": "local-preflight-conversation",
            "bound_at": now_utc(),
            "zombie": False,
            "runtime_status": {
                "runtime": "idle",
                "last_turn_status": "completed",
            },
            "cannot_claim": [
                "real_codex_ipc",
                "task_sent_to_codex",
                "codex_reply_read",
            ],
        })
        package = {
            "schema": "yuanjie_task_package_v0.1",
            "marker": "LOOP-READINESS-001",
            "action": "count_lines",
            "input_text": "loop\ncache\napproval\n",
            "approval_gate": {
                "gate_id": "HOST_APPROVAL_GATE_V1",
                "status": "approved_once",
                "host_decision": {"decision": "approve_once"},
                "cannot_claim": ["formal_ack", "external_send", "production_ready_connection"],
            },
        }
        raw = json.dumps(package, ensure_ascii=False, indent=2).encode("utf-8")
        task = {
            "task_id": "task_loop_readiness_001",
            "target_node": "node-c",
            "task_type": "task_package",
            "payload": {
                "marker": "LOOP-READINESS-001",
                "filename": "approval_gate_loop_readiness_001.json",
                "content_b64": base64.b64encode(raw).decode("ascii"),
                "sha256": hashlib.sha256(raw).hexdigest(),
            },
        }
        seed_path = write_task_cache(root, task, "pulled")
        result = build_loop_readiness(root)
        ok = (
            result.get("ok") is True
            and result.get("readiness") == "local_loop_ready"
            and result.get("checks", {}).get("session_bound") is True
            and result.get("checks", {}).get("approval_gate_seen") is True
            and result.get("pending_task_count") == 1
        )
        print(json.dumps({
            "ok": ok,
            "install": install,
            "seed_cache_path": seed_path,
            "readiness": result,
            "claim": "node_c_loop_readiness_preflight_passed" if ok else "node_c_loop_readiness_preflight_failed",
            "cannot_claim": [
                "real_codex_ipc",
                "task_sent_to_codex",
                "codex_reply_read",
                "frontstage_auto_injection",
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
