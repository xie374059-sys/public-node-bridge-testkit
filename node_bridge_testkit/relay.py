#!/usr/bin/env python3
"""Local relay for the public node bridge testkit.

The relay is intentionally in-memory and local-first. It supports only
allowlisted light tasks so contributors can verify the protocol without using
Yuanjie private infrastructure.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import parse_qs, urlparse


COLLABORATIVE_TASK_TYPE = "collaborative_bridge"
ALLOWED_TASK_TYPES = {
    "reply_exactly",
    "file_deliver",
    "task_package",
    "desktop_manual_exact",
    COLLABORATIVE_TASK_TYPE,
}
COLLABORATIVE_ALLOWED_CAPABILITIES = {
    "send_prompt_to_codex",
    "read_task_result",
    "return_artifact_summary",
    "read_project_manifest",
    "run_project_command",
}

UI_TRANSLATIONS = {
    "zh": {
        "controller_title": "控制端控制台",
        "host_title": "Host 控制台",
        "role_controller": "控制端",
        "role_host": "Host",
        "language": "语言",
        "task_queue": "任务队列",
        "pending_approval": "待审批",
        "approved": "已批准",
        "rejected": "已拒绝",
        "completed": "已完成",
        "new_task": "新建任务",
        "requester": "请求方",
        "target_node": "目标节点",
        "target_project": "目标项目",
        "prompt": "任务内容",
        "capabilities": "请求能力",
        "submit_task": "提交任务",
        "run_local_demo": "运行本地 Demo",
        "run_node_c_preflight": "运行 Node-C 预检",
        "run_collaborative_preflight": "运行协作桥预检",
        "execution_request": "执行请求",
        "pending_tasks": "待审批任务",
        "approve_once": "批准一次",
        "reject": "拒绝",
        "reason": "原因",
        "manual_result": "手动结果回传",
        "return_result": "回传结果",
        "agent_message": "Codex 回复",
        "result": "结果",
        "no_tasks": "暂无任务",
    },
    "en": {
        "controller_title": "Controller Console",
        "host_title": "Host Console",
        "role_controller": "Controller",
        "role_host": "Host",
        "language": "Language",
        "task_queue": "Task Queue",
        "pending_approval": "Pending Approval",
        "approved": "Approved",
        "rejected": "Rejected",
        "completed": "Completed",
        "new_task": "New Task",
        "requester": "Requester",
        "target_node": "Target Node",
        "target_project": "Target Project",
        "prompt": "Prompt",
        "capabilities": "Requested Capabilities",
        "submit_task": "Submit Task",
        "run_local_demo": "Run Local Demo",
        "run_node_c_preflight": "Run Node-C Preflight",
        "run_collaborative_preflight": "Run Collaborative Preflight",
        "execution_request": "Execution Request",
        "pending_tasks": "Pending Approval Tasks",
        "approve_once": "Approve Once",
        "reject": "Reject",
        "reason": "Reason",
        "manual_result": "Manual Result Return",
        "return_result": "Return Result",
        "agent_message": "Codex Reply",
        "result": "Result",
        "no_tasks": "No tasks",
    },
}


@dataclass
class Task:
    task_id: str
    target_node: str
    task_type: str
    payload: dict[str, Any]
    status: str = "queued"
    audit_id: str | None = None
    created_at: float = field(default_factory=time.time)
    claimed_at: float | None = None
    approved_at: float | None = None
    rejected_at: float | None = None
    completed_at: float | None = None
    approval: dict[str, Any] | None = None
    result: dict[str, Any] | None = None


class RelayState:
    def __init__(self, audit_path: str | Path = "") -> None:
        self._tasks: dict[str, Task] = {}
        self._lock = Lock()
        self.audit_path = self._resolve_audit_path(audit_path)

    def _resolve_audit_path(self, audit_path: str | Path = "") -> Path:
        if isinstance(audit_path, Path):
            return audit_path.expanduser().resolve()
        if isinstance(audit_path, str) and audit_path:
            return Path(audit_path).expanduser().resolve()
        env_path = os.environ.get("NODE_BRIDGE_AUDIT_PATH", "")
        if env_path:
            return Path(env_path).expanduser().resolve()
        return Path(".node_c_avatar") / "audit" / "collaborative_audit.jsonl"

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _append_audit(self, event_type: str, task: Task, details: dict[str, Any] | None = None) -> None:
        record = {
            "schema": "node_bridge_collaborative_audit_v0.1",
            "audit_id": task.audit_id,
            "task_id": task.task_id,
            "target_node": task.target_node,
            "task_type": task.task_type,
            "event_type": event_type,
            "timestamp": self._now_iso(),
            "status": task.status,
            "details": details or {},
        }
        path = self.audit_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _result_audit_details(self, node_id: str, result: dict[str, Any]) -> dict[str, Any]:
        agent_message = result.get("agent_message", "")
        return {
            "node_id": node_id,
            "execution": result.get("execution"),
            "agent_message_chars": len(agent_message) if isinstance(agent_message, str) else None,
        }

    def create_task(self, target_node: str, task_type: str, payload: dict[str, Any]) -> Task:
        if task_type not in ALLOWED_TASK_TYPES:
            raise ValueError(f"task_type not allowed: {task_type}")
        if task_type == "reply_exactly" and not isinstance(payload.get("text"), str):
            raise ValueError("reply_exactly requires payload.text")
        if task_type == "file_deliver":
            if not isinstance(payload.get("filename"), str):
                raise ValueError("file_deliver requires payload.filename")
            if not isinstance(payload.get("content_b64"), str):
                raise ValueError("file_deliver requires payload.content_b64")
            if not isinstance(payload.get("sha256"), str):
                raise ValueError("file_deliver requires payload.sha256")
        if task_type == "task_package":
            if not isinstance(payload.get("filename"), str):
                raise ValueError("task_package requires payload.filename")
            if not isinstance(payload.get("content_b64"), str):
                raise ValueError("task_package requires payload.content_b64")
            if not isinstance(payload.get("sha256"), str):
                raise ValueError("task_package requires payload.sha256")
        if task_type == "desktop_manual_exact":
            if not isinstance(payload.get("prompt"), str):
                raise ValueError("desktop_manual_exact requires payload.prompt")
            if not isinstance(payload.get("expected"), str):
                raise ValueError("desktop_manual_exact requires payload.expected")
        if task_type == COLLABORATIVE_TASK_TYPE:
            self._validate_collaborative_payload(payload)
        status = "pending_approval" if task_type == COLLABORATIVE_TASK_TYPE else "queued"
        audit_id = f"audit_{uuid.uuid4().hex[:12]}" if task_type == COLLABORATIVE_TASK_TYPE else None
        task = Task(
            task_id=f"task_{uuid.uuid4().hex[:12]}",
            target_node=target_node,
            task_type=task_type,
            payload=payload,
            status=status,
            audit_id=audit_id,
        )
        with self._lock:
            self._tasks[task.task_id] = task
        if task.task_type == COLLABORATIVE_TASK_TYPE:
            self._append_audit(
                "task_created",
                task,
                {
                    "requester": payload.get("requester"),
                    "target_project": payload.get("target_project"),
                    "capabilities": payload.get("capabilities"),
                },
            )
        return task

    def _validate_collaborative_payload(self, payload: dict[str, Any]) -> None:
        if not isinstance(payload.get("requester"), str) or not payload.get("requester"):
            raise ValueError("collaborative_bridge requires payload.requester")
        if not isinstance(payload.get("target_project"), str) or not payload.get("target_project"):
            raise ValueError("collaborative_bridge requires payload.target_project")
        if not isinstance(payload.get("prompt"), str) or not payload.get("prompt"):
            raise ValueError("collaborative_bridge requires payload.prompt")
        capabilities = payload.get("capabilities")
        if not isinstance(capabilities, list) or not capabilities:
            raise ValueError("collaborative_bridge requires payload.capabilities")
        for capability in capabilities:
            if not isinstance(capability, str):
                raise ValueError("collaborative_bridge capabilities must be strings")
            if capability not in COLLABORATIVE_ALLOWED_CAPABILITIES:
                raise ValueError(f"collaborative_bridge capability not allowed: {capability}")
        execution_request = payload.get("execution_request")
        if execution_request is None:
            return
        if not isinstance(execution_request, dict):
            raise ValueError("collaborative_bridge execution_request must be an object")
        if "run_project_command" not in capabilities:
            raise ValueError("collaborative_bridge execution_request requires run_project_command capability")
        if execution_request.get("kind") != "allowlisted_command":
            raise ValueError("collaborative_bridge execution_request.kind must be allowlisted_command")
        command_id = execution_request.get("command_id")
        if not isinstance(command_id, str) or not command_id:
            raise ValueError("collaborative_bridge execution_request.command_id is required")
        if any(char in command_id for char in "\\/.:"):
            raise ValueError("collaborative_bridge execution_request.command_id must be a simple id")

    def poll(self, node_id: str) -> Task | None:
        with self._lock:
            for task in self._tasks.values():
                if task.target_node == node_id and task.status == "queued":
                    task.status = "in_progress"
                    task.claimed_at = time.time()
                    return task
        return None

    def decide_approval(self, task_id: str, node_id: str, decision: str, reason: str = "") -> Task:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise KeyError(task_id)
            if task.target_node != node_id:
                raise PermissionError("node_id does not own task")
            if task.task_type != COLLABORATIVE_TASK_TYPE:
                raise ValueError("approval is only supported for collaborative_bridge tasks")
            if task.status != "pending_approval":
                raise ValueError(f"task is not pending approval: {task.status}")
            if decision == "approve":
                task.status = "approved"
                task.approved_at = time.time()
                task.approval = {"decision": "approve", "node_id": node_id, "reason": ""}
                self._append_audit("task_approved", task, {"node_id": node_id, "reason": ""})
                return task
            if decision == "reject":
                task.status = "rejected"
                task.rejected_at = time.time()
                task.approval = {"decision": "reject", "node_id": node_id, "reason": reason}
                self._append_audit("task_rejected", task, {"node_id": node_id, "reason": reason})
                return task
            raise ValueError("decision must be approve or reject")

    def update_state(self, task_id: str, node_id: str, status: str) -> Task:
        allowed = {
            "approved": {"sent_to_codex", "running", "result_pending_review", "completed", "failed", "canceled"},
            "sent_to_codex": {"running", "result_pending_review", "completed", "failed", "canceled"},
            "running": {"result_pending_review", "completed", "failed", "canceled"},
            "result_pending_review": {"completed", "failed", "canceled"},
        }
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise KeyError(task_id)
            if task.target_node != node_id:
                raise PermissionError("node_id does not own task")
            if task.task_type != COLLABORATIVE_TASK_TYPE:
                raise ValueError("state changes are only supported for collaborative_bridge tasks")
            current = task.status
            if current not in allowed:
                raise ValueError(f"task state cannot be advanced from {current}")
            if status not in allowed[current]:
                raise ValueError(f"invalid collaborative_bridge state transition: {current} -> {status}")
            task.status = status
            if status == "completed":
                task.completed_at = time.time()
            if status == "canceled":
                task.rejected_at = task.rejected_at or time.time()
            self._append_audit(
                f"task_{status}",
                task,
                {
                    "node_id": node_id,
                    "previous_status": current,
                    "status": status,
                },
            )
            return task

    def complete(self, task_id: str, node_id: str, result: dict[str, Any]) -> Task:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise KeyError(task_id)
            if task.target_node != node_id:
                raise PermissionError("node_id does not own task")
            if task.task_type == COLLABORATIVE_TASK_TYPE and task.status not in {
                "approved",
                "sent_to_codex",
                "running",
                "result_pending_review",
            }:
                raise ValueError(f"collaborative_bridge task is not approved: {task.status}")
            task.status = "completed"
            task.completed_at = time.time()
            task.result = result
            if task.task_type == COLLABORATIVE_TASK_TYPE:
                self._append_audit(
                    "task_completed",
                    task,
                    self._result_audit_details(node_id, result),
                )
            return task

    def get(self, task_id: str) -> Task | None:
        with self._lock:
            return self._tasks.get(task_id)

    def list_tasks(self, node_id: str = "", status: str = "", summary: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            tasks = list(self._tasks.values())
        rows: list[dict[str, Any]] = []
        for task in tasks:
            if node_id and task.target_node != node_id:
                continue
            if status and task.status != status:
                continue
            if summary:
                rows.append({
                    "task_id": task.task_id,
                    "target_node": task.target_node,
                    "task_type": task.task_type,
                    "status": task.status,
                    "created_at": task.created_at,
                    "claimed_at": task.claimed_at,
                    "completed_at": task.completed_at,
                })
            else:
                rows.append(asdict(task))
        return rows

    def stats(self) -> dict[str, Any]:
        with self._lock:
            counts: dict[str, int] = {"queued": 0, "in_progress": 0, "completed": 0}
            for task in self._tasks.values():
                counts[task.status] = counts.get(task.status, 0) + 1
            return {"tasks": len(self._tasks), "by_status": counts}


def response_from_task(task: Task | None) -> dict[str, Any]:
    if task is None:
        return {"ok": True, "task": None}
    return {"ok": True, "task": asdict(task)}


class RelayHandler(BaseHTTPRequestHandler):
    server_version = "NodeBridgeTestkitRelay/0.1"

    def log_message(self, format: str, *args: Any) -> None:
        if getattr(self.server, "quiet", False):
            return
        super().log_message(format, *args)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid json: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("json body must be an object")
        return data

    def _read_form(self) -> dict[str, str]:
        length = int(self.headers.get("content-length", "0"))
        raw = self.rfile.read(length) if length else b""
        parsed = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
        return {key: values[0] if values else "" for key, values in parsed.items()}

    def _write_json(self, status: int, body: dict[str, Any]) -> None:
        data = json.dumps(body, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _write_html(self, status: int, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _write_redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("location", location)
        self.send_header("content-length", "0")
        self.end_headers()

    def _wants_html(self) -> bool:
        accept = self.headers.get("accept", "")
        return "text/html" in accept and "application/json" not in accept

    def _token(self) -> str:
        return str(getattr(self.server, "token", "") or "")

    def _authorized(self) -> bool:
        token = self._token()
        if not token:
            return True
        supplied = self.headers.get("X-Node-Bridge-Token", "")
        return supplied == token

    def _require_auth(self) -> bool:
        if self._authorized():
            return True
        self._write_json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "forbidden"})
        return False

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/controller":
            self._write_html(HTTPStatus.OK, self._ui_html("controller", query.get("lang", ["zh"])[0]))
            return
        if parsed.path == "/host":
            self._write_html(HTTPStatus.OK, self._ui_html("host", query.get("lang", ["zh"])[0]))
            return
        if parsed.path == "/health":
            self._write_json(HTTPStatus.OK, {
                "ok": True,
                "service": "node-bridge-testkit-relay",
                "auth_required": bool(self._token()),
            })
            return
        if parsed.path == "/dashboard":
            self._write_html(HTTPStatus.OK, self._dashboard_html())
            return
        if parsed.path == "/stats":
            if not self._require_auth():
                return
            self._write_json(HTTPStatus.OK, {"ok": True, "stats": self.server.state.stats()})  # type: ignore[attr-defined]
            return
        if parsed.path == "/tasks":
            if not self._require_auth():
                return
            node_id = query.get("node_id", [""])[0]
            status = query.get("status", [""])[0]
            summary = query.get("format", [""])[0] == "summary"
            self._write_json(HTTPStatus.OK, {
                "ok": True,
                "tasks": self.server.state.list_tasks(node_id=node_id, status=status, summary=summary),  # type: ignore[attr-defined]
            })
            return
        if parsed.path == "/poll":
            if not self._require_auth():
                return
            node_id = query.get("node_id", [""])[0]
            if not node_id:
                self._write_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "missing node_id"})
                return
            self._write_json(HTTPStatus.OK, response_from_task(self.server.state.poll(node_id)))  # type: ignore[attr-defined]
            return
        if parsed.path.startswith("/tasks/"):
            if not self._require_auth():
                return
            task_id = parsed.path.rsplit("/", 1)[-1]
            task = self.server.state.get(task_id)  # type: ignore[attr-defined]
            if task is None:
                self._write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "task_not_found"})
                return
            self._write_json(HTTPStatus.OK, {"ok": True, "task": asdict(task)})
            return
        self._write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})

    def _dashboard_html(self) -> str:
        title = html.escape("Node Bridge Dashboard")
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    body {{ font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 24px; color: #1f2937; }}
    header {{ display: flex; gap: 12px; align-items: center; justify-content: space-between; flex-wrap: wrap; }}
    input {{ padding: 7px 9px; border: 1px solid #cbd5e1; border-radius: 6px; min-width: 260px; }}
    .stats {{ display: flex; gap: 10px; margin: 18px 0; flex-wrap: wrap; }}
    .pill {{ border-radius: 999px; padding: 6px 10px; background: #f1f5f9; font-size: 13px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ border-bottom: 1px solid #e5e7eb; padding: 9px; text-align: left; vertical-align: top; }}
    th {{ background: #f8fafc; position: sticky; top: 0; }}
    tr {{ cursor: pointer; }}
    .queued {{ color: #64748b; font-weight: 700; }}
    .in_progress {{ color: #2563eb; font-weight: 700; }}
    .completed {{ color: #059669; font-weight: 700; }}
    pre {{ white-space: pre-wrap; word-break: break-word; background: #0f172a; color: #e2e8f0; padding: 12px; border-radius: 8px; max-height: 320px; overflow: auto; }}
    .muted {{ color: #64748b; font-size: 12px; }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Node Bridge Dashboard</h1>
      <div class="muted">Local relay task queue. Refreshes every second.</div>
    </div>
    <label>Token <input id="token" placeholder="optional token"></label>
  </header>
  <div class="stats" id="stats"></div>
  <table>
    <thead><tr><th>task_id</th><th>node</th><th>type</th><th>status</th><th>created</th></tr></thead>
    <tbody id="tasks"><tr><td colspan="5">Loading...</td></tr></tbody>
  </table>
  <h2>Task detail</h2>
  <pre id="detail">Click a task row.</pre>
  <script>
    const tokenInput = document.getElementById('token');
    tokenInput.value = localStorage.getItem('node_bridge_token') || '';
    tokenInput.addEventListener('input', () => localStorage.setItem('node_bridge_token', tokenInput.value));
    function headers() {{
      const token = tokenInput.value.trim();
      return token ? {{'X-Node-Bridge-Token': token}} : {{}};
    }}
    function ts(value) {{
      return value ? new Date(value * 1000).toLocaleTimeString() : '';
    }}
    async function getJson(url) {{
      const res = await fetch(url, {{headers: headers()}});
      if (!res.ok) throw new Error(res.status + ' ' + res.statusText);
      return await res.json();
    }}
    async function refresh() {{
      try {{
        const [stats, tasks] = await Promise.all([
          getJson('/stats'),
          getJson('/tasks?format=summary')
        ]);
        const s = stats.stats || {{}};
        const by = s.by_status || {{}};
        document.getElementById('stats').innerHTML =
          `<span class="pill">total: ${{s.tasks || 0}}</span>` +
          `<span class="pill queued">queued: ${{by.queued || 0}}</span>` +
          `<span class="pill in_progress">in_progress: ${{by.in_progress || 0}}</span>` +
          `<span class="pill completed">completed: ${{by.completed || 0}}</span>`;
        const rows = tasks.tasks || [];
        document.getElementById('tasks').innerHTML = rows.length ? rows.map(t =>
          `<tr data-id="${{t.task_id}}"><td>${{t.task_id}}</td><td>${{t.target_node}}</td><td>${{t.task_type}}</td>` +
          `<td class="${{t.status}}">${{t.status}}</td><td>${{ts(t.created_at)}}</td></tr>`
        ).join('') : '<tr><td colspan="5">No tasks</td></tr>';
        document.querySelectorAll('tr[data-id]').forEach(row => {{
          row.onclick = async () => {{
            const data = await getJson('/tasks/' + row.dataset.id);
            document.getElementById('detail').textContent = JSON.stringify(data.task.result || data.task, null, 2);
          }};
        }});
      }} catch (err) {{
        document.getElementById('stats').innerHTML = `<span class="pill">error: ${{err.message}}</span>`;
      }}
    }}
    refresh();
    setInterval(refresh, 1000);
  </script>
</body>
</html>"""

    def _ui_html(self, role: str, lang: str) -> str:
        selected = "en" if lang == "en" else "zh"
        strings = UI_TRANSLATIONS[selected]
        role_label = strings["role_controller"] if role == "controller" else strings["role_host"]
        page_title = strings["controller_title"] if role == "controller" else strings["host_title"]
        main_panel = self._controller_panel(strings, selected) if role == "controller" else self._host_panel(strings, selected)
        task_items = self._task_items_html(strings)
        return f"""<!doctype html>
<html lang="{selected}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(page_title)}</title>
  <style>
    body {{ font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; color: #0f172a; background: #f8fafc; }}
    .app {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}
    header {{ display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 20px; }}
    .role {{ font-size: 13px; color: #475569; text-transform: uppercase; letter-spacing: .04em; }}
    h1 {{ margin: 4px 0 0; font-size: 28px; }}
    .toolbar {{ display: flex; gap: 8px; align-items: center; }}
    .lang {{ display: inline-flex; gap: 6px; align-items: center; }}
    .seg {{ display: inline-flex; border: 1px solid #cbd5e1; border-radius: 8px; overflow: hidden; background: white; }}
    .seg a {{ padding: 8px 12px; text-decoration: none; color: #334155; border-right: 1px solid #cbd5e1; }}
    .seg a:last-child {{ border-right: 0; }}
    .seg a.active {{ background: #0f172a; color: white; }}
    .grid {{ display: grid; grid-template-columns: 280px 1fr; gap: 16px; }}
    .panel {{ background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; }}
    .panel h2 {{ margin: 0 0 12px; font-size: 16px; }}
    .list {{ display: grid; gap: 8px; }}
    .item {{ border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px 12px; background: #fff; }}
    .badge {{ display: inline-block; font-size: 12px; border-radius: 999px; padding: 4px 8px; background: #e2e8f0; margin-right: 8px; }}
    .muted {{ color: #64748b; font-size: 13px; }}
    form {{ display: grid; gap: 10px; margin: 0; }}
    label {{ display: grid; gap: 5px; font-size: 13px; color: #334155; }}
    input, textarea {{ width: 100%; box-sizing: border-box; border: 1px solid #cbd5e1; border-radius: 6px; padding: 8px 10px; font: inherit; }}
    textarea {{ min-height: 96px; resize: vertical; }}
    button {{ border: 0; border-radius: 6px; padding: 8px 12px; font: inherit; cursor: pointer; background: #0f172a; color: white; }}
    button.secondary {{ background: #e2e8f0; color: #0f172a; }}
    button.danger {{ background: #991b1b; color: white; }}
    .actions {{ display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }}
    .task-detail {{ display: grid; gap: 8px; }}
    .task-detail code {{ word-break: break-all; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid #e2e8f0; text-align: left; padding: 10px 8px; font-size: 14px; }}
    th {{ background: #f8fafc; }}
    @media (max-width: 900px) {{
      .grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body data-role="{role}">
  <div class="app">
    <header>
      <div>
        <div class="role">{html.escape(role_label)}</div>
        <h1>{html.escape(page_title)}</h1>
      </div>
      <div class="toolbar">
        <span class="muted">{html.escape(strings["language"])}</span>
        <div class="seg">
          <a class="{ 'active' if selected == 'zh' else '' }" href="/{role}?lang=zh">中文</a>
          <a class="{ 'active' if selected == 'en' else '' }" href="/{role}?lang=en">English</a>
        </div>
      </div>
    </header>
    <div class="grid">
      <aside class="panel">
        <h2>{html.escape(strings["task_queue"])}</h2>
        <div class="list">
          {task_items}
        </div>
      </aside>
      <section class="panel">
        {main_panel}
      </section>
    </div>
  </div>
</body>
</html>"""

    def _task_items_html(self, strings: dict[str, str]) -> str:
        tasks = self.server.state.list_tasks(summary=False)  # type: ignore[attr-defined]
        if not tasks:
            return f'<div class="item muted">{html.escape(strings["no_tasks"])}</div>'
        rows: list[str] = []
        for task in tasks:
            status = str(task.get("status", ""))
            label = strings.get(status, status)
            rows.append(
                '<div class="item">'
                f'<span class="badge">{html.escape(label)}</span>'
                f'<code>{html.escape(str(task.get("task_id", "")))}</code>'
                f'<div class="muted">{html.escape(str(task.get("task_type", "")))}</div>'
                '</div>'
            )
        return "\n".join(rows)

    def _controller_panel(self, strings: dict[str, str], lang: str) -> str:
        tasks = self.server.state.list_tasks(summary=False)  # type: ignore[attr-defined]
        result_rows: list[str] = []
        for task in tasks:
            result = task.get("result") if isinstance(task.get("result"), dict) else {}
            agent_message = result.get("agent_message") if isinstance(result, dict) else ""
            result_rows.append(
                "<tr>"
                f"<td><code>{html.escape(str(task.get('task_id', '')))}</code></td>"
                f"<td>{html.escape(str(task.get('status', '')))}</td>"
                f"<td>{html.escape(str(agent_message or ''))}</td>"
                "</tr>"
            )
        result_body = "\n".join(result_rows) or f'<tr><td colspan="3">{html.escape(strings["no_tasks"])}</td></tr>'
        return f"""
        <h2>{html.escape(strings["new_task"])}</h2>
        <form method="post" action="/ui/controller/tasks">
          <input type="hidden" name="lang" value="{html.escape(lang)}">
          <label>{html.escape(strings["requester"])}
            <input name="requester" value="yuanjie-controller" required>
          </label>
          <label>{html.escape(strings["target_node"])}
            <input name="target_node" value="node-c" required>
          </label>
          <label>{html.escape(strings["target_project"])}
            <input name="target_project" value="D:\\work\\repo-b" required>
          </label>
          <label>{html.escape(strings["prompt"])}
            <textarea name="prompt" required>Inspect the failing test summary and propose a minimal fix.</textarea>
          </label>
          <label>{html.escape(strings["capabilities"])}
            <input name="capabilities" value="send_prompt_to_codex,read_task_result,return_artifact_summary" required>
          </label>
          <div class="actions">
            <button type="submit">{html.escape(strings["submit_task"])}</button>
          </div>
        </form>
        <h2 style="margin-top:22px">{html.escape(strings["execution_request"])}</h2>
        <form method="post" action="/ui/controller/tasks">
          <input type="hidden" name="lang" value="{html.escape(lang)}">
          <input type="hidden" name="requester" value="yuanjie-controller">
          <input type="hidden" name="target_node" value="node-c">
          <input type="hidden" name="target_project" value="D:\\test001\\public-node-bridge-testkit">
          <input type="hidden" name="capabilities" value="run_project_command,read_task_result,return_artifact_summary">
          <input type="hidden" name="prompt" value="Run selected Host allowlisted command.">
          <div class="actions">
            <button name="command_id" value="local_demo" type="submit">{html.escape(strings["run_local_demo"])}</button>
            <button name="command_id" value="node_c_preflight" type="submit">{html.escape(strings["run_node_c_preflight"])}</button>
            <button name="command_id" value="collaborative_bridge_preflight" type="submit">{html.escape(strings["run_collaborative_preflight"])}</button>
          </div>
        </form>
        <h2 style="margin-top:22px">{html.escape(strings["result"])}</h2>
        <table>
          <thead><tr><th>task_id</th><th>status</th><th>{html.escape(strings["agent_message"])}</th></tr></thead>
          <tbody>{result_body}</tbody>
        </table>
        """

    def _host_panel(self, strings: dict[str, str], lang: str) -> str:
        tasks = self.server.state.list_tasks(summary=False)  # type: ignore[attr-defined]
        cards: list[str] = []
        for task in tasks:
            if task.get("task_type") != COLLABORATIVE_TASK_TYPE:
                continue
            payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
            execution_request = payload.get("execution_request") if isinstance(payload.get("execution_request"), dict) else {}
            execution_line = ""
            if execution_request:
                execution_line = (
                    f'<div><strong>{html.escape(strings["execution_request"])}:</strong> '
                    f'{html.escape(str(execution_request.get("kind", "")))} / '
                    f'{html.escape(str(execution_request.get("command_id", "")))}</div>'
                )
            task_id = str(task.get("task_id", ""))
            status = str(task.get("status", ""))
            approve_controls = ""
            result_controls = ""
            if status == "pending_approval":
                approve_controls = f"""
                <form method="post" action="/ui/host/approval">
                  <input type="hidden" name="lang" value="{html.escape(lang)}">
                  <input type="hidden" name="task_id" value="{html.escape(task_id)}">
                  <input type="hidden" name="node_id" value="{html.escape(str(task.get('target_node', '')))}">
                  <div class="actions">
                    <button name="decision" value="approve" type="submit">{html.escape(strings["approve_once"])}</button>
                    <input name="reason" placeholder="{html.escape(strings["reason"])}">
                    <button class="danger" name="decision" value="reject" type="submit">{html.escape(strings["reject"])}</button>
                  </div>
                </form>
                """
            if status == "approved":
                result_controls = f"""
                <form method="post" action="/ui/host/result">
                  <input type="hidden" name="lang" value="{html.escape(lang)}">
                  <input type="hidden" name="task_id" value="{html.escape(task_id)}">
                  <input type="hidden" name="node_id" value="{html.escape(str(task.get('target_node', '')))}">
                  <label>{html.escape(strings["agent_message"])}
                    <textarea name="agent_message" required>Host-approved manual bridge result.</textarea>
                  </label>
                  <div class="actions">
                    <button type="submit">{html.escape(strings["return_result"])}</button>
                  </div>
                </form>
                """
            cards.append(
                '<div class="item task-detail">'
                f'<div><span class="badge">{html.escape(status)}</span><code>{html.escape(task_id)}</code></div>'
                f'<div><strong>{html.escape(strings["requester"])}:</strong> {html.escape(str(payload.get("requester", "")))}</div>'
                f'<div><strong>{html.escape(strings["target_project"])}:</strong> {html.escape(str(payload.get("target_project", "")))}</div>'
                f'<div><strong>{html.escape(strings["prompt"])}:</strong> {html.escape(str(payload.get("prompt", "")))}</div>'
                f'{execution_line}'
                f'{approve_controls}{result_controls}'
                '</div>'
            )
        body = "\n".join(cards) or f'<div class="item muted">{html.escape(strings["no_tasks"])}</div>'
        return f"""
        <h2>{html.escape(strings["pending_tasks"])}</h2>
        <div class="list">{body}</div>
        """

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if not self._require_auth():
            return
        try:
            if parsed.path == "/ui/controller/tasks":
                form = self._read_form()
                capabilities = [
                    capability.strip()
                    for capability in form.get("capabilities", "").split(",")
                    if capability.strip()
                ]
                task = self.server.state.create_task(  # type: ignore[attr-defined]
                    target_node=form.get("target_node", ""),
                    task_type=COLLABORATIVE_TASK_TYPE,
                    payload={
                        "requester": form.get("requester", ""),
                        "target_project": form.get("target_project", ""),
                        "prompt": form.get("prompt", ""),
                        "capabilities": capabilities,
                        **({
                            "execution_request": {
                                "kind": "allowlisted_command",
                                "command_id": form.get("command_id", ""),
                            },
                        } if form.get("command_id", "") else {}),
                    },
                )
                if self._wants_html():
                    self._write_redirect(f"/controller?lang={form.get('lang', 'zh') or 'zh'}")
                    return
                self._write_json(HTTPStatus.CREATED, {"ok": True, "task": asdict(task)})
                return
            if parsed.path == "/ui/host/approval":
                form = self._read_form()
                task = self.server.state.decide_approval(  # type: ignore[attr-defined]
                    task_id=form.get("task_id", ""),
                    node_id=form.get("node_id", ""),
                    decision=form.get("decision", ""),
                    reason=form.get("reason", ""),
                )
                if self._wants_html():
                    self._write_redirect(f"/host?lang={form.get('lang', 'zh') or 'zh'}")
                    return
                self._write_json(HTTPStatus.OK, {"ok": True, "task": asdict(task)})
                return
            if parsed.path == "/ui/host/result":
                form = self._read_form()
                task = self.server.state.complete(  # type: ignore[attr-defined]
                    task_id=form.get("task_id", ""),
                    node_id=form.get("node_id", ""),
                    result={
                        "status": "ok",
                        "agent_message": form.get("agent_message", ""),
                        "execution": "manual_codex_bridge",
                    },
                )
                if self._wants_html():
                    self._write_redirect(f"/host?lang={form.get('lang', 'zh') or 'zh'}")
                    return
                self._write_json(HTTPStatus.OK, {"ok": True, "task": asdict(task)})
                return
            body = self._read_json()
            if parsed.path == "/tasks":
                task = self.server.state.create_task(  # type: ignore[attr-defined]
                    target_node=str(body.get("target_node", "")),
                    task_type=str(body.get("task_type", "")),
                    payload=dict(body.get("payload", {})),
                )
                self._write_json(HTTPStatus.CREATED, {"ok": True, "task": asdict(task)})
                return
            if parsed.path.startswith("/tasks/") and parsed.path.endswith("/result"):
                parts = parsed.path.strip("/").split("/")
                task_id = parts[1]
                task = self.server.state.complete(  # type: ignore[attr-defined]
                    task_id=task_id,
                    node_id=str(body.get("node_id", "")),
                    result=dict(body.get("result", {})),
                )
                self._write_json(HTTPStatus.OK, {"ok": True, "task": asdict(task)})
                return
            if parsed.path.startswith("/tasks/") and parsed.path.endswith("/approval"):
                parts = parsed.path.strip("/").split("/")
                task_id = parts[1]
                task = self.server.state.decide_approval(  # type: ignore[attr-defined]
                    task_id=task_id,
                    node_id=str(body.get("node_id", "")),
                    decision=str(body.get("decision", "")),
                    reason=str(body.get("reason", "")),
                )
                self._write_json(HTTPStatus.OK, {"ok": True, "task": asdict(task)})
                return
            if parsed.path.startswith("/tasks/") and parsed.path.endswith("/state"):
                parts = parsed.path.strip("/").split("/")
                task_id = parts[1]
                task = self.server.state.update_state(  # type: ignore[attr-defined]
                    task_id=task_id,
                    node_id=str(body.get("node_id", "")),
                    status=str(body.get("status", "")),
                )
                self._write_json(HTTPStatus.OK, {"ok": True, "task": asdict(task)})
                return
            self._write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
        except ValueError as exc:
            self._write_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
        except KeyError:
            self._write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "task_not_found"})
        except PermissionError as exc:
            self._write_json(HTTPStatus.FORBIDDEN, {"ok": False, "error": str(exc)})


def make_server(host: str, port: int, quiet: bool = False, token: str = "", audit_path: str | Path = "") -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), RelayHandler)
    server.quiet = quiet  # type: ignore[attr-defined]
    server.token = token  # type: ignore[attr-defined]
    server.state = RelayState(audit_path=audit_path)  # type: ignore[attr-defined]
    return server


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local node bridge relay.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--token", default=os.environ.get("NODE_BRIDGE_TOKEN", ""))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    server = make_server(args.host, args.port, quiet=args.quiet, token=args.token)
    print(f"relay_listening=http://{args.host}:{args.port}")
    print(f"auth_required={str(bool(args.token)).lower()}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("relay_stopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
