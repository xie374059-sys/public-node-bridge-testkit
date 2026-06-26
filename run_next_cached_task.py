#!/usr/bin/env python3
"""Execute the next safe task already stored in the local Node-C cache.

This is the manual wakeup path: the relay can deliver a task into
`.node_c_avatar/task_cache/`, and a local agent can later read and execute the
next allowlisted cached task without contacting the relay or touching the
Codex input box.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from node_bridge_testkit.avatar_runtime import (
    DEFAULT_INSTALL_DIR,
    DEFAULT_NODE_ID,
    read_json,
    resolve_install_dir,
)
from node_bridge_testkit.node_adapter import execute_task, write_task_cache
from run_node_c_connection_state import decide_state, list_cache


PENDING_STATUSES = ("pulled", "queued", "ready")

CANNOT_CLAIM = [
    "real_codex_ipc",
    "task_sent_to_codex",
    "codex_reply_read",
    "formal_ack",
    "external_send",
    "file_execution",
    "persistent_service",
    "long_running_autonomy",
    "production_ready_connection",
]


def parse_time(value: str | None) -> datetime:
    if not value:
        return datetime.min
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return datetime.min


def load_binding(root: Path) -> dict[str, Any] | None:
    path = root / "session_binding.json"
    if not path.exists():
        return None
    try:
        return read_json(path)
    except Exception:
        return {"zombie": True, "error": "invalid_session_binding_json"}


def connection_snapshot(root: Path) -> dict[str, Any]:
    config_exists = (root / "config.json").exists()
    state = read_json(root / "state.json") if (root / "state.json").exists() else {}
    binding = load_binding(root)
    cache = list_cache(root)
    return {
        "config_exists": config_exists,
        "connection_state": decide_state(config_exists, state, binding, cache),
        "node_id": state.get("node_id") or (binding or {}).get("node_id"),
        "session_bound": bool(binding and binding.get("conversation_id")),
        "conversation_id": (binding or {}).get("conversation_id"),
        "session_zombie": bool(binding and binding.get("zombie")),
        "task_cache": cache,
    }


def iter_cache_records(root: Path, statuses: Iterable[str]) -> list[dict[str, Any]]:
    wanted = set(statuses)
    cache_dir = root / "task_cache"
    if not cache_dir.exists():
        return []
    records: list[dict[str, Any]] = []
    for path in cache_dir.glob("*.json"):
        try:
            record = read_json(path)
        except Exception:
            continue
        if str(record.get("status") or "") not in wanted:
            continue
        task = record.get("task")
        if not isinstance(task, dict):
            continue
        records.append({
            "path": str(path),
            "mtime": path.stat().st_mtime,
            "cached_at_sort": parse_time(record.get("cached_at")),
            "record": record,
            "task": task,
        })
    records.sort(key=lambda item: (item["cached_at_sort"], item["mtime"], item["path"]))
    return records


def execute_next_cached_task(
    install_dir: str | Path = DEFAULT_INSTALL_DIR,
    node_id: str = DEFAULT_NODE_ID,
    statuses: Iterable[str] = PENDING_STATUSES,
    dry_run: bool = False,
) -> dict[str, Any]:
    root = resolve_install_dir(install_dir)
    snapshot = connection_snapshot(root)
    if not snapshot["config_exists"]:
        return {
            "ok": False,
            "install_dir": str(root),
            "connection_state": snapshot,
            "claim": "node_c_next_cached_task_not_installed",
            "cannot_claim": CANNOT_CLAIM,
        }

    records = iter_cache_records(root, statuses)
    if snapshot["connection_state"] == "busy":
        return {
            "ok": False,
            "install_dir": str(root),
            "connection_state": snapshot,
            "claim": "node_c_next_cached_task_busy",
            "cannot_claim": CANNOT_CLAIM,
        }
    if not records:
        return {
            "ok": False,
            "install_dir": str(root),
            "connection_state": snapshot,
            "claim": "node_c_next_cached_task_none",
            "cannot_claim": CANNOT_CLAIM,
        }

    selected = records[0]
    task = selected["task"]
    task_id = str(task.get("task_id") or selected["record"].get("task_id") or "")
    if snapshot["session_zombie"]:
        cache_path = write_task_cache(
            root,
            task,
            "blocked_by_bad_conversation",
            result={"status": "blocked", "error": "session_zombie"},
            posted={"ok": False},
        )
        return {
            "ok": False,
            "install_dir": str(root),
            "connection_state": snapshot,
            "task_id": task_id,
            "marker": selected["record"].get("marker"),
            "cache_path": cache_path,
            "claim": "node_c_next_cached_task_blocked_by_bad_conversation",
            "cannot_claim": CANNOT_CLAIM,
        }

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "install_dir": str(root),
            "connection_state": snapshot,
            "task_id": task_id,
            "task_type": task.get("task_type"),
            "marker": selected["record"].get("marker"),
            "cache_path": selected["path"],
            "claim": "node_c_next_cached_task_dry_run",
            "cannot_claim": CANNOT_CLAIM,
        }

    cache_path = write_task_cache(root, task, "in_progress")
    result = execute_task(task, node_id, sandbox_dir=root)
    ok = result.get("status") == "ok"
    final_status = "completed_local" if ok else "failed_local"
    cache_path = write_task_cache(root, task, final_status, result=result, posted={"ok": ok})
    return {
        "ok": ok,
        "install_dir": str(root),
        "connection_state": snapshot,
        "task_id": task_id,
        "task_type": task.get("task_type"),
        "marker": result.get("marker") or selected["record"].get("marker"),
        "agent_message": result.get("agent_message"),
        "filename": result.get("filename"),
        "bytes": result.get("bytes"),
        "sha256": result.get("sha256"),
        "saved_to": result.get("saved_to"),
        "action": result.get("action"),
        "line_count": result.get("line_count"),
        "text_sha256": result.get("text_sha256"),
        "execution": result.get("execution"),
        "cache_path": cache_path,
        "claim": "node_c_next_cached_task_completed_local" if ok else "node_c_next_cached_task_failed_local",
        "cannot_claim": CANNOT_CLAIM,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Execute the next safe task from local Node-C task cache.")
    parser.add_argument("--install-dir", default=DEFAULT_INSTALL_DIR)
    parser.add_argument("--node-id", default=DEFAULT_NODE_ID)
    parser.add_argument("--statuses", default=",".join(PENDING_STATUSES))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    statuses = [item.strip() for item in args.statuses.split(",") if item.strip()]
    result = execute_next_cached_task(
        install_dir=args.install_dir,
        node_id=args.node_id,
        statuses=statuses,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
