# Implementation Plan: Collaborative Bridge

## Overview
Implement a bilingual Host + Controller visual collaboration bridge with mandatory Host approval before any task reaches Codex. The first implementation should complete a manual Codex bridge flow before adding optional IPC automation.

## Architecture Decisions
- Keep the existing Python standard-library approach for the first version to preserve the current no-third-party-dependency property.
- Extend the existing relay/task model before adding new execution backends.
- Build Host approval as a protocol state, not only as UI behavior.
- Default UI language to Chinese while keeping protocol fields in English.
- Treat Codex IPC as a later backend; the first end-to-end flow uses manual prompt/result transfer.

## Phase 1: Protocol and State Foundation

### Task 1: Define collaborative task schema
**Description:** Add a versioned task shape for collaborative bridge requests while preserving existing light-task behavior.

**Acceptance criteria:**
- [ ] Collaborative tasks include requester, target node, target project, requested capabilities, prompt, approval state, and audit id.
- [ ] Existing `reply_exactly`, `file_deliver`, and `task_package` flows remain compatible.
- [ ] Invalid collaborative task payloads are rejected at the relay boundary.

**Verification:**
- [ ] Run existing local demo: `python3 run_local_demo.py`
- [ ] Run Node-C preflight: `python3 run_node_c_preflight.py`
- [ ] Add or run focused schema/state tests when introduced.

**Dependencies:** None

**Files likely touched:**
- `node_bridge_testkit/relay.py`
- `PROTOCOL.md`
- `README.md`

**Estimated scope:** Medium

### Task 2: Add approval lifecycle states
**Description:** Extend task states to support Host review and explicit rejection/cancellation.

**Acceptance criteria:**
- [ ] Relay can represent `pending_approval`, `approved`, `rejected`, `canceled`, `sent_to_codex`, `running`, `result_pending_review`, `completed`, and `failed`.
- [ ] State transitions reject invalid jumps.
- [ ] Existing polling behavior remains unchanged for legacy tasks.

**Verification:**
- [ ] State transition tests pass.
- [ ] Existing preflight scripts still pass.

**Dependencies:** Task 1

**Files likely touched:**
- `node_bridge_testkit/relay.py`
- `run_local_demo.py` or a new collaborative preflight script

**Estimated scope:** Medium

### Checkpoint: Protocol Foundation
- [ ] Existing demo/preflight commands pass.
- [ ] Collaborative task shape and states are documented.
- [ ] No execution backend has been added yet.

## Phase 2: Audit and Capability Guardrails

### Task 3: Add append-only audit log helper
**Description:** Create a small audit helper that records request, approval, rejection, execution, result review, and return events.

**Acceptance criteria:**
- [ ] Every collaborative task receives an `audit_id`.
- [ ] Audit records are JSONL and append-only.
- [ ] Audit records avoid secrets and full unrelated file content.

**Verification:**
- [ ] Unit or preflight check confirms JSONL records are written for a full approved path.
- [ ] Manual inspection confirms no tokens or credentials are logged.

**Dependencies:** Task 1

**Files likely touched:**
- `node_bridge_testkit/`
- `.node_c_avatar/` runtime paths
- `README.md`

**Estimated scope:** Medium

### Task 4: Add capability validation
**Description:** Add allowlisted collaborative capabilities and explicit forbidden capability rejection.

**Acceptance criteria:**
- [ ] Allowed capabilities include `send_prompt_to_codex`, `read_task_result`, `return_artifact_summary`, and `read_project_manifest`.
- [ ] Forbidden capabilities are rejected before approval.
- [ ] Rejection response names the forbidden capability without exposing internals.

**Verification:**
- [ ] Tests or preflight cover allowed and forbidden capability payloads.
- [ ] Existing Node-C adapter denied-capability boundaries remain intact.

**Dependencies:** Task 1

**Files likely touched:**
- `node_bridge_testkit/relay.py`
- `node_bridge_testkit/node_adapter.py` or a new collaborative helper module
- `PROTOCOL.md`

**Estimated scope:** Small

### Checkpoint: Security Foundation
- [ ] Collaborative requests cannot request shell execution or arbitrary file access.
- [ ] Audit log captures the lifecycle.
- [ ] Existing safety claims remain true.

## Phase 3: Bilingual UI Foundation

### Task 5: Add UI shell with language switching
**Description:** Add a local web UI shell served by the project that can switch between Chinese and English.

**Acceptance criteria:**
- [ ] UI defaults to Chinese.
- [ ] Language can switch to English without changing protocol values.
- [ ] Missing translation keys fall back predictably.

**Verification:**
- [ ] Manual browser check in Chinese and English.
- [ ] Translation key check passes if a helper script is added.

**Dependencies:** None

**Files likely touched:**
- `node_bridge_testkit/relay.py` or a new UI server module
- `i18n/zh.json`
- `i18n/en.json`
- `README.md`

**Estimated scope:** Medium

### Task 6: Add Controller console
**Description:** Add visual Controller surfaces for node selection, project selection, task creation, status, and result viewing.

**Acceptance criteria:**
- [ ] Controller can compose and submit a collaborative task.
- [ ] Controller can see task status timeline.
- [ ] Controller can read returned result and rejection reasons.

**Verification:**
- [ ] Manual browser flow submits a task to the relay.
- [ ] Relay shows the task as `pending_approval`.

**Dependencies:** Tasks 1, 2, 5

**Files likely touched:**
- UI server/static files
- `node_bridge_testkit/relay.py`

**Estimated scope:** Medium

### Task 7: Add Host console
**Description:** Add visual Host surfaces for project sharing, pending approvals, approval/rejection, manual Codex bridge, result review, and audit log.

**Acceptance criteria:**
- [ ] Host can see incoming pending tasks.
- [ ] Host can approve once or reject with a reason.
- [ ] Host can paste a Codex result and mark it ready for return.
- [ ] Host can review outgoing result before returning it.

**Verification:**
- [ ] Manual browser flow approves a pending task.
- [ ] Manual browser flow rejects a pending task with a visible reason.

**Dependencies:** Tasks 1, 2, 3, 5

**Files likely touched:**
- UI server/static files
- `node_bridge_testkit/relay.py`
- audit helper module

**Estimated scope:** Medium

### Checkpoint: Visual Approval Flow
- [ ] Controller and Host UIs both load.
- [ ] UI can switch Chinese/English.
- [ ] Host approval is visible and required.
- [ ] No task reaches manual Codex bridge before approval.

## Phase 4: Manual End-to-End Bridge

### Task 8: Add manual Codex bridge preflight
**Description:** Add a local preflight that exercises Controller submit -> Host approve -> manual result -> Controller complete.

**Acceptance criteria:**
- [ ] Preflight creates a collaborative task.
- [ ] Preflight simulates Host approval and result return.
- [ ] Output includes success claim and `cannot_claim` boundaries.

**Verification:**
- [ ] Run: `python3 run_collaborative_bridge_preflight.py`
- [ ] Existing preflight commands still pass.

**Dependencies:** Tasks 1, 2, 3, 4

**Files likely touched:**
- `run_collaborative_bridge_preflight.py`
- `node_bridge_testkit/`
- `README.md`

**Estimated scope:** Medium

### Task 9: Document manual operating flow
**Description:** Update project docs so testers understand the Controller and Host paths.

**Acceptance criteria:**
- [ ] README explains how to start relay/UI.
- [ ] README explains how Host approves a task.
- [ ] README states what the manual bridge proves and does not prove.

**Verification:**
- [ ] Follow README steps on a clean local run.

**Dependencies:** Tasks 5, 6, 7, 8

**Files likely touched:**
- `README.md`
- `PROTOCOL.md`
- `SECURITY.md`

**Estimated scope:** Small

### Checkpoint: MVP Complete
- [ ] Controller can submit from UI.
- [ ] Host can approve from UI.
- [ ] Manual Codex result can be returned.
- [ ] Controller can view completed result.
- [ ] Audit log covers the lifecycle.
- [ ] Chinese and English labels are available.

## Phase 5: Optional Automation After MVP

### Task 10: Add optional Codex IPC execution backend
**Description:** Add Codex IPC execution only after the manual bridge is stable and keep Host approval mandatory.

**Acceptance criteria:**
- [ ] IPC backend is opt-in.
- [ ] Host can disable IPC and fall back to manual bridge.
- [ ] IPC execution refuses zombie or busy conversations.
- [ ] IPC result handling preserves audit logging.

**Verification:**
- [ ] Existing Codex IPC probes pass before using IPC backend.
- [ ] Manual bridge still works when IPC is disabled.

**Dependencies:** MVP checkpoint

**Files likely touched:**
- Existing `run_node_c_codex_*` integration points
- new bridge backend module
- `README.md`

**Estimated scope:** Large; split before implementation.

## Risks and Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Feature is perceived as hidden remote control | High | Keep Host approval mandatory, visible, and auditable |
| UI scope grows too large | Medium | Ship minimal Controller/Host consoles first |
| Codex IPC instability blocks MVP | High | Use manual bridge as MVP execution path |
| Sensitive data leaks through prompt/result | High | Show full prompt/result to Host, require review, log summaries only |
| Protocol conflicts with existing light-task flows | Medium | Keep legacy task types compatible and add collaborative shape separately |
| Translation drift | Low | Use key-based i18n and fallback checks |

## Open Questions
- Should the first UI be served from the existing relay process or a separate local UI server?
- Should Host project sharing start with one active project only, or a small allowlist?
- Should pairing cards be file-based only in MVP, or also pasteable text?
- What exact local port defaults should be used for relay and UI to avoid conflict with existing `8765` relay?

## Human Review Gate
Do not begin implementation until this plan is reviewed and approved.
