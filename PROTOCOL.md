# Node Bridge Public Protocol V0.1

## Scope

V0.1 is a light-task protocol for local verification.

It has three roles:

```text
caller -> relay -> node
```

## State Flow

```text
created -> queued -> in_progress -> completed
```

## Endpoints

### Health

```http
GET /health
```

### Create Task

```http
POST /tasks
Content-Type: application/json
```

Body:

```json
{
  "target_node": "node-b",
  "task_type": "reply_exactly",
  "payload": {
    "marker": "L0-OK",
    "text": "OK"
  }
}
```

### Node Poll

```http
GET /poll?node_id=node-b
```

### Submit Result

```http
POST /tasks/{task_id}/result
Content-Type: application/json
```

Body:

```json
{
  "node_id": "node-b",
  "result": {
    "status": "ok",
    "agent_message": "OK",
    "execution": "mock_reply_exactly"
  }
}
```

### Read Task

```http
GET /tasks/{task_id}
```

## Acceptance Rule

For `reply_exactly`, the acceptance rule is:

```text
task.status == completed
task.result.agent_message == task.payload.text
```

For `file_deliver`, the acceptance rule is:

```text
task.status == completed
task.result.execution == local_adapter_file_deliver_sandbox_write
task.result.marker == task.payload.marker
task.result.filename == task.payload.filename
task.result.sha256 == task.payload.sha256
```

`file_deliver` payload:

```json
{
  "target_node": "node-c",
  "task_type": "file_deliver",
  "payload": {
    "marker": "NODEC-FILE-001",
    "filename": "nodec_file_preflight_001.txt",
    "content_b64": "base64-encoded-small-file",
    "sha256": "expected-sha256"
  }
}
```

Node-C writes only into its own sandbox:

```text
.node_c_avatar/inbox/<task_id>/
```

## Node-C Local Adapter Preflight

`run_node_c_preflight.py` uses the same relay and the same `reply_exactly`
acceptance rule, but targets `node-c` through `node_bridge_testkit.node_adapter`.

Expected result:

```json
{
  "status": "ok",
  "node_id": "node-c",
  "marker": "NODEC-PREFLIGHT",
  "agent_message": "STATUS=NODEC_PREFLIGHT_OK; MARKER=NODEC_PREFLIGHT; NEXT=READY_FOR_REVIEW",
  "execution": "local_adapter_reply_exactly",
  "safe_mode": true
}
```

## Node-C Avatar Installer Preflight

`install_node_c_avatar.py` creates local testkit state:

```text
.node_c_avatar/config.json
.node_c_avatar/state.json
```

`run_node_c_avatar.py` then returns a structured packet with:

```text
health
heartbeat
capabilities
allowed_task_types
denied_capabilities
completed light tasks
```

The installer preflight supports `reply_exactly` and sandboxed `file_deliver`.
It remains local-only until a relay URL and token are provided.

## Remote Relay Token Preflight

When a relay is started with `NODE_BRIDGE_TOKEN` or `--token`, task endpoints
require:

```http
X-Node-Bridge-Token: <token>
```

Maintainer flow:

```text
send_node_c_remote_probe.py -> POST /tasks -> wait GET /tasks/{task_id}
```

Node-C flow:

```text
run_node_c_remote_client.py -> GET /poll?node_id=node-c -> POST /tasks/{task_id}/result
```

Acceptance rule remains:

```text
task.status == completed
task.result.agent_message == task.payload.text
```

For file-channel preflight:

```text
send_node_c_file_probe.py -> POST /tasks task_type=file_deliver -> wait GET /tasks/{task_id}
run_node_c_remote_client.py -> GET /poll?node_id=node-c -> sandbox write -> POST /tasks/{task_id}/result
```

Forbidden claims:

```text
formal ACK
real Codex Desktop IPC
external send
file execution
persistent service
long-running autonomy
```

## Forbidden In V0.1

```text
shell execution
file execution
external message sending
formal ACK
credential handling
private endpoint routing
```
