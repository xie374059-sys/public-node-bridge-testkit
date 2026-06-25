# Security Boundary

This project is a public light-task testkit. It is not a remote-control tool.

## Safe By Design

V0.1 uses:

```text
localhost relay
in-memory task queue
mock node
reply_exactly task only
Python standard library only
```

## Not Included

```text
No shell command execution
No file execution
No browser control
No account login
No external message sending
No payment, deletion, approval, or authorization actions
No private Yuanjie endpoints
No Aliyun token or route
No Codex Desktop IPC implementation
```

## Reporting Security Issues

Open a GitHub issue only for public testkit concerns.

Do not post:

```text
API tokens
private relay URLs
screenshots with personal data
private keys
cookies
internal company data
```

## Project Claim Boundary

Passing the local demo means:

```text
local_public_testkit_l0_l1_passed
```

It does not mean:

```text
external node connected
formal ACK completed
real Codex IPC validated
file channel validated
autonomous agent collaboration completed
```
