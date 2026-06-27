#!/usr/bin/env python3
"""Optional Codex IPC backend for collaborative bridge tasks.

This is opt-in and requires an approved collaborative_bridge task plus a valid
Codex Desktop session binding. It sends a fixed exact-reply marker through
Codex IPC, observes the reply, and then returns the task result to the relay.
It does not touch the input box or automate the frontstage UI.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from run_node_c_codex_ipc_start_turn_probe import (
    Kernel32,
    cannot_claim,
    exact_expected_seen,
    extract_runtime_status,
    is_zombie_conversation,
    open_pipe,
    read_frame,
    read_response_for,
    runtime_status_summary,
    scrub_start_response,
    write_frame,
)


NODE_ID = "node-c"
PIPE = r"\\.\pipe\codex-ipc"


def http_json(method: str, url: str, body: dict[str, Any] | None = None, token: str = "") -> dict[str, Any]:
    data = None
    headers = {"accept": "application/json"}
    if token:
        headers["X-Node-Bridge-Token"] = token
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["content-type"] = "application/json"
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            return json.loads(exc.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "error": str(exc)}


def read_session_binding(path: str) -> dict[str, Any]:
    binding_path = Path(path).expanduser()
    if not binding_path.exists():
        return {}
    data = json.loads(binding_path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def update_task_state(relay_url: str, task_id: str, status: str, token: str = "") -> dict[str, Any]:
    return http_json(
        "POST",
        f"{relay_url.rstrip('/')}/tasks/{task_id}/state",
        {"node_id": NODE_ID, "status": status},
        token=token,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the optional Codex IPC collaborative backend.")
    parser.add_argument("--relay-url", required=True)
    parser.add_argument("--token", default=os.environ.get("NODE_BRIDGE_TOKEN", ""))
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--session-binding", default=".node_c_avatar/session_binding.json")
    parser.add_argument("--pipe", default=PIPE)
    parser.add_argument("--open-timeout", type=float, default=3.0)
    parser.add_argument("--read-timeout", type=float, default=10.0)
    parser.add_argument("--observe-timeout", type=float, default=120.0)
    parser.add_argument("--marker", default="NODEC_COLLAB_IPC_OK_001")
    parser.add_argument("--prompt", default="")
    parser.add_argument("--approval-policy", default="never")
    args = parser.parse_args()

    binding = read_session_binding(args.session_binding)
    conversation_id = str(binding.get("conversation_id") or "")
    if not conversation_id:
        print(json.dumps({
            "ok": False,
            "error": "missing_session_binding_conversation_id",
            "claim": "collaborative_bridge_codex_ipc_backend_missing_binding",
            "cannot_claim": cannot_claim(),
        }, ensure_ascii=False, indent=2))
        return 1

    task = http_json("GET", f"{args.relay_url.rstrip('/')}/tasks/{args.task_id}", token=args.token)
    if not task.get("ok"):
        print(json.dumps({
            "ok": False,
            "stage": "fetch_task",
            "response": task,
            "claim": "collaborative_bridge_codex_ipc_backend_task_fetch_failed",
            "cannot_claim": cannot_claim(),
        }, ensure_ascii=False, indent=2))
        return 1
    task_data = task.get("task") if isinstance(task.get("task"), dict) else {}
    if task_data.get("task_type") != "collaborative_bridge":
        print(json.dumps({
            "ok": False,
            "stage": "task_type",
            "task": task_data,
            "claim": "collaborative_bridge_codex_ipc_backend_wrong_task_type",
            "cannot_claim": cannot_claim(),
        }, ensure_ascii=False, indent=2))
        return 1
    if task_data.get("status") != "approved":
        print(json.dumps({
            "ok": False,
            "stage": "approval",
            "task_status": task_data.get("status"),
            "claim": "collaborative_bridge_codex_ipc_backend_not_approved",
            "cannot_claim": cannot_claim(),
        }, ensure_ascii=False, indent=2))
        return 1

    k = Kernel32()
    handle, open_error = open_pipe(k, args.pipe, args.open_timeout)
    if handle is None:
        update_task_state(args.relay_url, args.task_id, "failed", token=args.token)
        print(json.dumps({
            "ok": False,
            "stage": "open",
            "opened": False,
            "windows_error_code": open_error,
            "claim": "collaborative_bridge_codex_ipc_backend_open_failed",
            "cannot_claim": cannot_claim(),
        }, ensure_ascii=False, indent=2))
        return 1

    try:
        init_id = f"init-{int(time.time() * 1000)}"
        write_frame(k, handle, {
            "type": "request",
            "requestId": init_id,
            "method": "initialize",
            "params": {"clientType": "yuanjie-collaborative-bridge-backend"},
        })
        init_response, _, _ = read_response_for(k, handle, init_id, args.read_timeout)
        if not (
            init_response.get("type") == "response"
            and init_response.get("resultType") == "success"
        ):
            update_task_state(args.relay_url, args.task_id, "failed", token=args.token)
            print(json.dumps({
                "ok": False,
                "stage": "initialize",
                "response": scrub_start_response(init_response),
                "claim": "collaborative_bridge_codex_ipc_backend_initialize_failed",
                "cannot_claim": cannot_claim(),
            }, ensure_ascii=False, indent=2))
            return 1

        runtime_status = extract_runtime_status(init_response, conversation_id)  # type: ignore[arg-type]
        zombie, reason = is_zombie_conversation(runtime_status) if runtime_status else (False, "")
        if zombie:
            update_task_state(args.relay_url, args.task_id, "failed", token=args.token)
            print(json.dumps({
                "ok": False,
                "stage": "preflight",
                "conversation_id": conversation_id,
                "runtime_status": runtime_status_summary(runtime_status),
                "error": reason,
                "claim": "collaborative_bridge_codex_ipc_backend_zombie_conversation",
                "cannot_claim": cannot_claim(),
            }, ensure_ascii=False, indent=2))
            return 1

        prompt = args.prompt or f"Reply exactly: {args.marker}"
        sent_state = update_task_state(args.relay_url, args.task_id, "sent_to_codex", token=args.token)
        if not sent_state.get("ok"):
            print(json.dumps({
                "ok": False,
                "stage": "state_sent_to_codex",
                "response": sent_state,
                "claim": "collaborative_bridge_codex_ipc_backend_state_failed",
                "cannot_claim": cannot_claim(),
            }, ensure_ascii=False, indent=2))
            return 1
        start_id = f"start-{int(time.time() * 1000)}"
        write_frame(k, handle, {
            "type": "request",
            "requestId": start_id,
            "method": "thread-follower-start-turn",
            "version": 1,
            "sourceClientId": str(init_response.get("result", {}).get("clientId", "")),
            "params": {
                "conversationId": conversation_id,
                "turnStartParams": {
                    "input": [{"type": "text", "text": prompt, "text_elements": []}],
                    "cwd": binding.get("cwd"),
                    "approvalPolicy": args.approval_policy,
                    "attachments": [],
                    "commentAttachments": [],
                    "serviceTier": None,
                },
            },
            "timeoutMs": int(args.observe_timeout * 1000),
        })
        start_response, _, _ = read_response_for(k, handle, start_id, args.read_timeout)
        if not (start_response.get("type") == "response" and start_response.get("resultType") == "success"):
            update_task_state(args.relay_url, args.task_id, "failed", token=args.token)
            print(json.dumps({
                "ok": False,
                "stage": "start_turn",
                "response": scrub_start_response(start_response),
                "claim": "collaborative_bridge_codex_ipc_backend_start_failed",
                "cannot_claim": cannot_claim(),
            }, ensure_ascii=False, indent=2))
            return 1
        running_state = update_task_state(args.relay_url, args.task_id, "running", token=args.token)
        if not running_state.get("ok"):
            print(json.dumps({
                "ok": False,
                "stage": "state_running",
                "response": running_state,
                "claim": "collaborative_bridge_codex_ipc_backend_state_failed",
                "cannot_claim": cannot_claim(),
            }, ensure_ascii=False, indent=2))
            return 1

        deadline = time.monotonic() + args.observe_timeout
        observed = False
        while time.monotonic() < deadline and not observed:
            frame = read_frame(k, handle, max(0.1, min(1.0, deadline - time.monotonic())))
            if exact_expected_seen(frame, conversation_id, args.marker):
                observed = True

        if not observed:
            update_task_state(args.relay_url, args.task_id, "failed", token=args.token)
            print(json.dumps({
                "ok": False,
                "stage": "observe",
                "conversation_id": conversation_id,
                "marker": args.marker,
                "claim": "collaborative_bridge_codex_ipc_backend_reply_not_observed",
                "cannot_claim": cannot_claim(),
            }, ensure_ascii=False, indent=2))
            return 1

        review_state = update_task_state(args.relay_url, args.task_id, "result_pending_review", token=args.token)
        if not review_state.get("ok"):
            print(json.dumps({
                "ok": False,
                "stage": "state_result_pending_review",
                "response": review_state,
                "claim": "collaborative_bridge_codex_ipc_backend_state_failed",
                "cannot_claim": cannot_claim(),
            }, ensure_ascii=False, indent=2))
            return 1
        result = {
            "status": "ok",
            "node_id": NODE_ID,
            "marker": args.marker,
            "agent_message": args.marker,
            "execution": "collaborative_bridge_codex_ipc_start_turn",
            "safe_mode": True,
            "denied_capabilities": [
                "shell_execution",
                "file_execution",
                "external_send",
                "frontstage_auto_injection",
            ],
        }
        posted = http_json(
            "POST",
            f"{args.relay_url.rstrip('/')}/tasks/{args.task_id}/result",
            {"node_id": NODE_ID, "result": result},
            token=args.token,
        )
        if not posted.get("ok"):
            update_task_state(args.relay_url, args.task_id, "failed", token=args.token)
            print(json.dumps({
                "ok": False,
                "stage": "submit_result",
                "response": posted,
                "claim": "collaborative_bridge_codex_ipc_backend_submit_failed",
                "cannot_claim": cannot_claim(),
            }, ensure_ascii=False, indent=2))
            return 1

        print(json.dumps({
            "ok": True,
            "relay": args.relay_url,
            "conversation_id": conversation_id,
            "task_id": args.task_id,
            "marker": args.marker,
            "claim": "collaborative_bridge_codex_ipc_backend_completed",
            "cannot_claim": cannot_claim(),
        }, ensure_ascii=False, indent=2))
        return 0
    finally:
        k.close_handle(handle)


if __name__ == "__main__":
    raise SystemExit(main())
