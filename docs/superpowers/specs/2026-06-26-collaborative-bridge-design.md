# Collaborative Bridge Design

## Status
Draft approved for planning.

## Date
2026-06-26

## Goal
Build a visual, bilingual collaborative bridge that lets a Controller send a task to a Host machine, lets the Host review and approve the task, then lets the Host-side Codex session produce a result that is returned to the Controller.

The first version is an authorization-first collaboration tool, not a hidden remote-control tool.

## Product Positioning
Node-C Collaborative Bridge lets two trusted users collaborate across local Codex or agent sessions without granting unrestricted access to each other's machines.

The Controller can request work. The Host remains in control of execution, project access, and result sharing.

## Users and Roles

### Controller
- Select paired Host nodes.
- Select an exposed Host project.
- Write and submit a task prompt.
- Request narrowly-scoped capabilities.
- Track approval, execution, and result status.
- Read only the result and artifacts explicitly returned by the Host.

### Host
- Pair with a Controller.
- Choose which local projects are visible.
- Review every incoming task before execution.
- Approve or reject each task.
- Bind or manually use a local Codex session.
- Review the outgoing result before it is returned.
- Inspect and export audit logs.

## Non-Negotiable Boundaries
The first version must not:
- hide execution from the Host;
- bypass Host approval;
- read arbitrary Host files;
- execute shell commands;
- execute received files;
- access credentials, cookies, or private tokens;
- read old Codex conversations unless explicitly attached as task output;
- run as an invisible persistent background controller;
- claim formal ACK, unrestricted remote control, or production-grade autonomy.

The first version must:
- require Host approval for every task;
- show the full prompt before approval;
- show requested capabilities before approval;
- support Host rejection with a reason;
- write audit records for request, approval, execution, result, and return;
- keep protocol fields in English;
- support Chinese and English UI labels.

## Architecture

```text
Controller UI
  -> Relay
    -> Host UI
      -> Host approval
        -> Codex manual bridge or Codex IPC bridge
          -> Host result review
            -> Relay
              -> Controller UI
```

### Components

#### Relay
The relay keeps the shared task queue and state transitions. It does not execute tasks. It stores task metadata, approval state, result summary, and audit references.

#### Controller UI
The Controller UI is the task-sending surface. It is responsible for creating task drafts, submitting tasks, tracking status, and reading returned results.

#### Host UI
The Host UI is the security gate. It is responsible for showing incoming tasks, project scope, capability requests, risk labels, approval controls, execution status, and audit history.

#### Codex Bridge
The first implementation should support a manual bridge path:

```text
Host UI displays prompt -> Host copies prompt into Codex -> Host pastes Codex result back
```

Codex IPC can be added later as an optional execution backend after the approval flow is stable.

#### Audit Log
Audit records should be append-only JSONL records. They should include task id, audit id, actor role, event type, timestamp, request summary, approval decision, execution state, and result return summary.

## Task Lifecycle

```text
draft
-> submitted
-> pending_approval
-> approved
-> sent_to_codex
-> running
-> result_pending_review
-> completed
```

Failure or cancellation branches:

```text
pending_approval -> rejected
submitted/pending_approval/approved -> canceled
sent_to_codex/running/result_pending_review -> failed
```

## Capability Model
First-version capabilities:

```text
send_prompt_to_codex
read_task_result
return_artifact_summary
read_project_manifest
```

Capabilities that remain forbidden:

```text
shell_execution
arbitrary_file_read
arbitrary_file_write
file_execution
credential_access
browser_cookie_access
hidden_background_control
unapproved_persistent_control
destructive_git_operation
automatic_external_send
```

## UI Information Architecture

### Shared Header
- Current role: Controller or Host.
- Language switch: 中文 / English.
- Relay connection state.
- Current node identity.

### Controller Console
- Paired node list.
- Host project list.
- New task composer.
- Requested capability selector.
- Submitted task list.
- Task detail and status timeline.
- Returned result view.

### Host Console
- Shared project list.
- Pending approval queue.
- Incoming task detail.
- Approve once / reject controls.
- Manual Codex bridge panel.
- Result review and return panel.
- Audit log.

### Settings
- UI language.
- Node identity.
- Pairing card.
- Shared project configuration.
- Allowed capability descriptions.
- Audit export.

## Bilingual UI
The UI should default to Chinese and allow switching to English.

Protocol values remain English and stable:

```json
{
  "status": "pending_approval",
  "capabilities": ["send_prompt_to_codex", "read_task_result"]
}
```

UI copy should use translation keys:

```text
task.approve = 批准
task.reject = 拒绝
task.pendingApproval = 待审批
node.ready = 已就绪
```

Suggested files:

```text
i18n/zh.json
i18n/en.json
```

## First-Version Flow

1. Host starts the bridge in a selected project.
2. Host opens the Host UI and generates a pairing card.
3. Controller imports the pairing card.
4. Controller writes a task and selects requested capabilities.
5. Relay stores the task as `pending_approval`.
6. Host reviews the task in the Host UI.
7. Host approves or rejects the task.
8. If approved, Host uses the manual Codex bridge panel to send the prompt.
9. Host pastes or captures the Codex result.
10. Host reviews the outgoing result.
11. Host returns the result to Relay.
12. Controller sees the completed result and audit summary.

## Error Handling
- Invalid task payload: reject at Relay boundary.
- Unknown node: task remains unrouteable and visible to Controller as failed.
- Host rejects task: status becomes `rejected` with a reason.
- Host times out: status remains `pending_approval` until canceled or expired.
- Manual Codex bridge fails: Host marks task `failed` with a reason.
- Relay unavailable: local UI keeps unsent drafts and displays disconnected state.

## Testing Strategy
- Unit tests for task state transitions.
- Unit tests for capability validation.
- Unit tests for i18n key loading and fallback.
- Local preflight for Controller -> Relay -> Host approval -> completed result.
- Manual UI verification for Chinese and English labels.
- Security-focused tests for forbidden capability rejection.

## Deliberate Deferrals
- Automatic Codex IPC execution.
- Mobile-first remote deployment.
- Auto-approval rules.
- Full A2A compatibility.
- OAuth/OIDC/mTLS enterprise identity.
- Multi-tenant hosted relay.

## Success Criteria
- A Controller can submit a task from a visual UI.
- A Host can review and approve the task from a visual UI.
- No task reaches Codex without Host approval.
- The Host can return a result to the Controller.
- Both sides can view status and result.
- The UI can switch between Chinese and English.
- Audit records exist for the full task lifecycle.
