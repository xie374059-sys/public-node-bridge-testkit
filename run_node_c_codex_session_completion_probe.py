#!/usr/bin/env python3
"""Observe Codex Desktop completion from local session rollout files.

This probe does not send a task. It reads local `.codex/sessions` rollout files
and checks whether a previously sent marker reached the assistant message and
task_complete records. This separates model completion from UI refresh state.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from node_bridge_testkit.avatar_runtime import read_json


CANNOT_CLAIM = [
    "task_sent_to_codex",
    "frontstage_auto_injection",
    "input_box_automation",
    "formal_ack",
    "external_send",
    "file_execution",
    "persistent_service",
    "long_running_autonomy",
    "production_ready_connection",
]


def iter_strings(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, str):
        found.append(value)
    elif isinstance(value, list):
        for item in value:
            found.extend(iter_strings(item))
    elif isinstance(value, dict):
        for item in value.values():
            found.extend(iter_strings(item))
    return found


def read_session_binding(path: str) -> dict[str, Any]:
    if not path:
        return {}
    binding_path = Path(path).expanduser()
    if not binding_path.exists():
        return {}
    data = read_json(binding_path)
    return data if isinstance(data, dict) else {}


def candidate_files(
    sessions_root: Path,
    conversation_id: str,
    lookback_hours: float,
    max_files: int,
) -> list[Path]:
    if not sessions_root.exists():
        return []
    cutoff = time.time() - max(0.0, lookback_hours) * 3600
    files = [
        path
        for path in sessions_root.rglob("*.jsonl")
        if path.is_file() and path.stat().st_mtime >= cutoff
    ]
    if conversation_id:
        exact = [path for path in files if conversation_id in path.name or conversation_id in str(path)]
        if exact:
            files = exact
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return files[:max_files]


def tail_lines(path: Path, max_bytes: int) -> list[str]:
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > max_bytes:
            handle.seek(max(0, size - max_bytes))
            handle.readline()
        data = handle.read()
    return data.decode("utf-8", errors="replace").splitlines()


def exact_marker_seen(value: Any, marker: str) -> bool:
    return any(text.strip() == marker for text in iter_strings(value))


def marker_contained(value: Any, marker: str) -> bool:
    return any(marker in text for text in iter_strings(value))


def scrub_message(text: str, marker: str) -> str:
    if marker not in text and text.strip() != marker:
        return ""
    return text[:500]


def inspect_file(path: Path, marker: str, max_bytes: int) -> dict[str, Any]:
    user_message_seen = False
    assistant_answer_seen = False
    expected_answer_seen = False
    task_complete_seen = False
    last_agent_message = ""
    line_count = 0
    matched_event_types: dict[str, int] = {}
    parse_errors = 0

    for raw_line in tail_lines(path, max_bytes):
        if not raw_line.strip():
            continue
        line_count += 1
        try:
            row = json.loads(raw_line)
        except json.JSONDecodeError:
            parse_errors += 1
            continue
        payload = row.get("payload") if isinstance(row, dict) else None
        if not isinstance(payload, dict):
            payload = {}
        event_type = str(payload.get("type") or row.get("type") or "unknown")
        if marker_contained(row, marker):
            matched_event_types[event_type] = matched_event_types.get(event_type, 0) + 1
        if event_type == "user_message" and marker_contained(payload, marker):
            user_message_seen = True
        if event_type == "agent_message" and exact_marker_seen(payload, marker):
            assistant_answer_seen = True
            expected_answer_seen = True
            message = payload.get("message")
            if isinstance(message, str):
                last_agent_message = scrub_message(message, marker) or last_agent_message
        if event_type == "message":
            role = str(payload.get("role") or "")
            if role == "assistant" and exact_marker_seen(payload, marker):
                assistant_answer_seen = True
                expected_answer_seen = True
        if exact_marker_seen(payload, marker):
            expected_answer_seen = True
        if event_type == "task_complete":
            message = payload.get("last_agent_message")
            if isinstance(message, str) and marker in message:
                task_complete_seen = True
                last_agent_message = scrub_message(message, marker) or last_agent_message

    return {
        "path": str(path),
        "mtime": path.stat().st_mtime,
        "lines_read": line_count,
        "parse_errors": parse_errors,
        "user_message_seen": user_message_seen,
        "assistant_answer_seen": assistant_answer_seen,
        "expected_answer_seen": expected_answer_seen,
        "task_complete_seen": task_complete_seen,
        "last_agent_message": last_agent_message or None,
        "matched_event_types": matched_event_types,
    }


def observe_completion(
    sessions_root: Path,
    conversation_id: str,
    marker: str,
    timeout: float,
    poll_interval: float,
    lookback_hours: float,
    max_files: int,
    max_bytes_per_file: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    best: dict[str, Any] | None = None
    files_seen: list[str] = []
    while True:
        files = candidate_files(sessions_root, conversation_id, lookback_hours, max_files)
        files_seen = [str(path) for path in files[:10]]
        for path in files:
            result = inspect_file(path, marker, max_bytes_per_file)
            score = sum(
                bool(result.get(key))
                for key in (
                    "user_message_seen",
                    "assistant_answer_seen",
                    "expected_answer_seen",
                    "task_complete_seen",
                )
            )
            best_score = sum(
                bool((best or {}).get(key))
                for key in (
                    "user_message_seen",
                    "assistant_answer_seen",
                    "expected_answer_seen",
                    "task_complete_seen",
                )
            )
            if best is None or score > best_score or result["mtime"] > best.get("mtime", 0):
                best = result
            if result["assistant_answer_seen"] and result["task_complete_seen"]:
                return {
                    "ok": True,
                    "observed": result,
                    "files_considered": len(files),
                    "sample_files": files_seen,
                }
        if time.monotonic() >= deadline:
            return {
                "ok": False,
                "observed": best,
                "files_considered": len(files),
                "sample_files": files_seen,
            }
        time.sleep(poll_interval)


def main() -> int:
    parser = argparse.ArgumentParser(description="Observe Codex completion from local session rollout files.")
    parser.add_argument("--conversation-id", default="")
    parser.add_argument("--session-binding", default="", help="Path to .node_c_avatar/session_binding.json")
    parser.add_argument("--marker", default="NODEC_IPC_OK_001")
    parser.add_argument("--sessions-root", default=str(Path.home() / ".codex" / "sessions"))
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--lookback-hours", type=float, default=24.0)
    parser.add_argument("--max-files", type=int, default=200)
    parser.add_argument("--max-bytes-per-file", type=int, default=4 * 1024 * 1024)
    args = parser.parse_args()

    binding = read_session_binding(args.session_binding)
    conversation_id = args.conversation_id or str(binding.get("conversation_id") or "")
    sessions_root = Path(args.sessions_root).expanduser().resolve()
    marker = args.marker.strip()
    result = observe_completion(
        sessions_root=sessions_root,
        conversation_id=conversation_id,
        marker=marker,
        timeout=args.timeout,
        poll_interval=args.poll_interval,
        lookback_hours=args.lookback_hours,
        max_files=args.max_files,
        max_bytes_per_file=args.max_bytes_per_file,
    )
    observed = result.get("observed") or {}
    ok = bool(result.get("ok"))
    print(json.dumps({
        "ok": ok,
        "sessions_root": str(sessions_root),
        "conversation_id": conversation_id or None,
        "marker": marker,
        "gates": {
            "user_message_seen": bool(observed.get("user_message_seen")),
            "assistant_answer_seen": bool(observed.get("assistant_answer_seen")),
            "expected_answer_seen": bool(observed.get("expected_answer_seen")),
            "task_complete_seen": bool(observed.get("task_complete_seen")),
        },
        "last_agent_message": observed.get("last_agent_message"),
        "observed_file": observed.get("path"),
        "diagnostics": {
            "timeout_seconds": args.timeout,
            "files_considered": result.get("files_considered", 0),
            "sample_files": result.get("sample_files", []),
            "matched_event_types": observed.get("matched_event_types") or {},
            "lines_read": observed.get("lines_read"),
            "parse_errors": observed.get("parse_errors"),
        },
        "claim": "node_c_codex_session_completion_observed" if ok else "node_c_codex_session_completion_not_observed",
        "cannot_claim": CANNOT_CLAIM,
    }, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
