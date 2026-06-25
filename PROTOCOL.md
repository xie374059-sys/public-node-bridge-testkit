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

## Forbidden In V0.1

```text
shell execution
file execution
external message sending
formal ACK
credential handling
private endpoint routing
```
