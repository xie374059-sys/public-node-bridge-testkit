# v0.1.0-local-proof

First public local proof for `public-node-bridge-testkit`.

## What This Release Includes

- Local in-memory relay
- Safe mock node
- `reply_exactly` light-task protocol
- L0 demo: returns `OK`
- L1 demo: returns structured text
- One-command local demo:

```bash
python3 run_local_demo.py
```

- Protocol document
- Security boundary
- Roadmap
- GitHub Actions workflow
- GitHub issue templates

## Verified Locally

Expected claim:

```text
local_public_testkit_l0_l1_passed
```

Expected L0 result:

```text
OK
```

Expected L1 result:

```text
STATUS=READ_OK; MARKER=PUBLIC_L1; NEXT=SMALL_TASK
```

## Claim Boundary

This release proves:

```text
local relay + mock node + L0/L1 light task protocol can run on a user's machine
```

This release does not prove:

```text
real Codex Desktop IPC
real external node connection
formal ACK
external message sending
file execution
long-running autonomy
Yuanjie core open source
```

## Requirements

```text
Python 3.10+
No third-party Python packages
```

## Safety

V0.1 does not run shell commands, open private files, send external messages,
install packages, or connect to Yuanjie private infrastructure.
