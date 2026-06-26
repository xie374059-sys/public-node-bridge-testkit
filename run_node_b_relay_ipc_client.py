#!/usr/bin/env python3
"""Poll relay tasks and send safe reply_exactly tasks into Node-B Codex IPC.

This joins two already validated pieces:

relay -> local node poll/cache/result
local node -> Codex Desktop IPC thread-follower-start-turn -> rollout evidence

It supports only `reply_exactly` tasks. It does not use the input box, execute
files, send external messages, claim formal ACK, or run as a persistent service.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
from urllib.parse import urlencode

from node_bridge_testkit.avatar_runtime import DEFAULT_INSTALL_DIR, health_packet, install_avatar, load_avatar, update_state
from node_bridge_testkit.node_adapter import http_json, write_task_cache


SCRIPT_DIR = Path(__file__).resolve().parent
START_TURN_PROBE = SCRIPT_DIR / "run_node_b_codex_ipc_start_turn_probe.py"


def cannot_claim() -> list[str]:
    return [
        "formal_ack",
        "external_send",
        "file_execution",
        "persistent_service",
        "long_running_autonomy",
        "production_ready_connection",
        "frontstage_auto_injection",
        "input_box_automation",
    ]


def progress(enabled: bool, message: str) -> None:
    if enabled:
        print(message, file=sys.stderr, flush=True)


def poll_task(relay: str, node_id: str, token: str) -> dict[str, Any] | None:
    polled = http_json("GET", f"{relay.rstrip('/')}/poll?{urlencode({'node_id': node_id})}", token=token)
    task = polled.get("task")
    return task if isinstance(task, dict) else None


def submit_result(relay: str, task_id: str, node_id: str, result: dict[str, Any], token: str) -> dict[str, Any]:
    return http_json(
        "POST",
        f"{relay.rstrip('/')}/tasks/{task_id}/result",
        {"node_id": node_id, "result": result},
        token=token,
    )


def parse_probe_stdout(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
    return {}


def dry_run_probe(expected: str, preflight_completed_marker: str) -> dict[str, Any]:
    return {
        "ok": True,
        "task_sent_to_codex": True,
        "codex_exact_reply_observed": True,
        "agent_message": expected,
        "preflight_completed_marker": preflight_completed_marker or None,
        "gates": {
            "target_thread_ok": True,
            "start_turn_ok": True,
            "completion_observed": True,
            "refresh_after_ok": None,
        },
        "completion_observation": {
            "observed": True,
            "status": "dry_run_ipc_not_real_codex",
        },
        "claim": "node_b_relay_ipc_client_dry_run_probe_passed",
        "cannot_claim": [
            "real_codex_ipc",
            "codex_desktop_reply",
            "formal_ack",
            "external_send",
            "file_execution",
        ],
    }


def run_ipc_probe(
    conversation_id: str,
    expected: str,
    preflight_completed_marker: str,
    cwd: str,
    timeout: float,
    dry_run: bool,
    extra_args: list[str],
) -> dict[str, Any]:
    if dry_run:
        return dry_run_probe(expected, preflight_completed_marker)
    if not conversation_id:
        return {"ok": False, "error": "missing_conversation_id"}

    cmd = [
        sys.executable,
        str(START_TURN_PROBE),
        "--conversation-id",
        conversation_id,
        "--marker",
        expected,
        "--completion-timeout",
        str(timeout),
    ]
    if cwd:
        cmd.extend(["--cwd", cwd])
    if preflight_completed_marker:
        cmd.extend(["--preflight-completed-marker", preflight_completed_marker])
    cmd.extend(extra_args)
    completed = subprocess.run(cmd, cwd=str(SCRIPT_DIR), text=True, capture_output=True, check=False)
    parsed = parse_probe_stdout(completed.stdout)
    if not parsed:
        parsed = {
            "ok": False,
            "error": "probe_output_not_json",
            "stdout_tail": completed.stdout[-1000:],
            "stderr_tail": completed.stderr[-1000:],
        }
    parsed["probe_returncode"] = completed.returncode
    if completed.stderr.strip():
        parsed["probe_stderr_tail"] = completed.stderr[-1000:]
    return parsed


def result_from_probe(task: dict[str, Any], probe: dict[str, Any], expected: str) -> dict[str, Any]:
    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    gates = probe.get("gates") if isinstance(probe.get("gates"), dict) else {}
    ok = bool(
        probe.get("task_sent_to_codex")
        and probe.get("codex_exact_reply_observed")
        and (probe.get("agent_message") == expected or probe.get("ok"))
    )
    completion = probe.get("completion_observation") if isinstance(probe.get("completion_observation"), dict) else {}
    return {
        "status": "ok" if ok else "error",
        "node_id": task.get("target_node"),
        "marker": payload.get("marker"),
        "agent_message": probe.get("agent_message") if probe.get("agent_message") is not None else expected if ok else None,
        "expected": expected,
        "task_sent_to_codex": bool(probe.get("task_sent_to_codex")),
        "codex_exact_reply_observed": bool(probe.get("codex_exact_reply_observed")),
        "completion_observed": bool(completion.get("observed") or gates.get("completion_observed")),
        "rollout_path": completion.get("rollout_path"),
        "execution": "node_b_relay_to_codex_ipc_start_turn",
        "safe_mode": True,
        "probe_claim": probe.get("claim"),
        "probe_error": probe.get("error"),
        "cannot_claim": cannot_claim(),
    }


def handle_task(
    relay: str,
    node_id: str,
    token: str,
    root: Path,
    task: dict[str, Any],
    conversation_id: str,
    preflight_marker: str,
    cwd: str,
    completion_timeout: float,
    dry_run: bool,
    extra_probe_args: list[str],
) -> tuple[dict[str, Any], str]:
    task_id = str(task.get("task_id") or "")
    write_task_cache(root, task, "pulled")
    write_task_cache(root, task, "in_progress")
    task_type = str(task.get("task_type") or "")
    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}

    if task_type != "reply_exactly":
        result = {
            "status": "error",
            "error": f"unsupported_task_type_for_codex_ipc_client:{task_type}",
            "node_id": node_id,
            "marker": payload.get("marker"),
            "execution": "node_b_relay_to_codex_ipc_start_turn_rejected",
            "cannot_claim": cannot_claim(),
        }
        posted = submit_result(relay, task_id, node_id, result, token)
        write_task_cache(root, task, "completed" if posted.get("ok") else "submit_failed", result=result, posted=posted)
        return {
            "task_id": task_id,
            "task_type": task_type,
            "marker": payload.get("marker"),
            "result": result,
            "posted_ok": bool(posted.get("ok")),
        }, preflight_marker

    expected = payload.get("text")
    if not isinstance(expected, str) or not expected.strip():
        result = {
            "status": "error",
            "error": "reply_exactly_missing_payload_text",
            "node_id": node_id,
            "marker": payload.get("marker"),
            "execution": "node_b_relay_to_codex_ipc_start_turn_rejected",
            "cannot_claim": cannot_claim(),
        }
        posted = submit_result(relay, task_id, node_id, result, token)
        write_task_cache(root, task, "completed" if posted.get("ok") else "submit_failed", result=result, posted=posted)
        return {
            "task_id": task_id,
            "task_type": task_type,
            "marker": payload.get("marker"),
            "result": result,
            "posted_ok": bool(posted.get("ok")),
        }, preflight_marker

    probe = run_ipc_probe(
        conversation_id=conversation_id,
        expected=expected.strip(),
        preflight_completed_marker=preflight_marker,
        cwd=cwd,
        timeout=completion_timeout,
        dry_run=dry_run,
        extra_args=extra_probe_args,
    )
    result = result_from_probe(task, probe, expected.strip())
    posted = submit_result(relay, task_id, node_id, result, token)
    write_task_cache(root, task, "completed" if posted.get("ok") else "submit_failed", result=result, posted=posted)
    next_preflight_marker = expected.strip() if result.get("status") == "ok" else preflight_marker
    return {
        "task_id": task_id,
        "task_type": task_type,
        "marker": payload.get("marker"),
        "agent_message": result.get("agent_message"),
        "task_sent_to_codex": result.get("task_sent_to_codex"),
        "codex_exact_reply_observed": result.get("codex_exact_reply_observed"),
        "completion_observed": result.get("completion_observed"),
        "execution": result.get("execution"),
        "posted_ok": bool(posted.get("ok")),
        "cache_status": "completed" if posted.get("ok") else "submit_failed",
        "probe_claim": probe.get("claim"),
        "probe_error": probe.get("error"),
    }, next_preflight_marker


def main() -> int:
    parser = argparse.ArgumentParser(description="Poll relay and send reply_exactly tasks to Node-B Codex IPC.")
    parser.add_argument("--relay-url", required=True)
    parser.add_argument("--token", default=os.environ.get("NODE_BRIDGE_TOKEN", ""))
    parser.add_argument("--node-id", default="node-b")
    parser.add_argument("--install-dir", default=DEFAULT_INSTALL_DIR)
    parser.add_argument("--conversation-id", default="")
    parser.add_argument("--preflight-completed-marker", default="")
    parser.add_argument("--cwd", default=os.getcwd())
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--max-tasks", type=int, default=1)
    parser.add_argument("--completion-timeout", type=float, default=180.0)
    parser.add_argument("--dry-run-ipc", action="store_true", help="Test relay glue without contacting Codex Desktop.")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--probe-arg", action="append", default=[], help="Extra raw arg passed to the IPC start-turn probe.")
    args = parser.parse_args()

    relay = args.relay_url.rstrip("/")
    show_progress = not args.quiet
    install = install_avatar(node_id=args.node_id, install_dir=args.install_dir)
    root, config, state = load_avatar(args.install_dir)
    health = health_packet(config)
    progress(show_progress, f"[config] relay={relay} node={args.node_id}")
    progress(show_progress, f"[health] status={health.get('status')} heartbeat={health.get('heartbeat_at')}")

    deadline = time.monotonic() + args.timeout
    completed: list[dict[str, Any]] = []
    poll_count = 0
    preflight_marker = args.preflight_completed_marker.strip()

    while time.monotonic() < deadline and len(completed) < args.max_tasks:
        poll_count += 1
        progress(show_progress, f"[poll #{poll_count}] relay={relay} node={args.node_id}")
        task = poll_task(relay, args.node_id, args.token)
        if task is None:
            time.sleep(args.interval)
            continue
        progress(show_progress, f"[task] task_id={task.get('task_id')} type={task.get('task_type')}")
        item, preflight_marker = handle_task(
            relay=relay,
            node_id=args.node_id,
            token=args.token,
            root=root,
            task=task,
            conversation_id=args.conversation_id,
            preflight_marker=preflight_marker,
            cwd=args.cwd,
            completion_timeout=args.completion_timeout,
            dry_run=args.dry_run_ipc,
            extra_probe_args=args.probe_arg,
        )
        completed.append(item)
        progress(show_progress, f"[submit] task_id={item.get('task_id')} ok={str(bool(item.get('posted_ok'))).lower()}")

    ok = bool(completed) and all(item.get("posted_ok") for item in completed)
    claim = "node_b_relay_to_codex_ipc_completed_task" if ok else "node_b_relay_to_codex_ipc_no_completed_task"
    updated_state = update_state(root, state, claim)
    print(json.dumps({
        "ok": ok,
        "relay": relay,
        "node_id": args.node_id,
        "install_dir": str(install.get("install_dir")),
        "conversation_id": args.conversation_id or None,
        "dry_run_ipc": bool(args.dry_run_ipc),
        "health": health,
        "completed": completed,
        "state": {
            "last_heartbeat_at": updated_state["last_heartbeat_at"],
            "last_run_claim": updated_state["last_run_claim"],
        },
        "claim": claim,
        "cannot_claim": cannot_claim(),
    }, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
