# Security policy

## Supported versions

agent-blackbox is pre-1.0. Only the latest released minor version receives
security fixes.

## Reporting a vulnerability

Please **do not open a public issue**. Report it privately through GitHub:
**Security → Report a vulnerability** on this repository (private
vulnerability reporting). Include affected versions, a reproduction and the
impact you expect.

You can expect an acknowledgement within 7 days and a fix or mitigation plan
within 30 days for confirmed issues. Credit is given in the release notes
unless you ask otherwise.

## Threat model

agent-blackbox runs on a developer's machine, inside the project directory,
with the developer's privileges. It is invoked in two ways: as a Claude Code
hook on every file-changing tool call, and as a CLI typed by the developer.

### Assets

1. The developer's work tree and git repository.
2. The developer's agent session: it must never be broken, blocked or slowed
   down noticeably by agent-blackbox.
3. Secrets that may appear in tool inputs, prompts or files.
4. The recordings in `.agent-blackbox/` (snapshots and metadata).

### Trust boundaries and inputs

| Input | Trusted? | Why |
|---|---|---|
| Hook payload on stdin (tool names, inputs, prompts) | **Untrusted** | Produced by an LLM that may have read attacker-controlled content (prompt injection). |
| Files in the work tree | **Untrusted** | May come from the agent, dependencies or third parties. |
| The test and `--setup` commands passed to `agent-blackbox bisect` | Trusted | Typed by the developer. Executed as the developer would execute them. |
| `.agent-blackbox/config.toml` | Trusted | Written by the developer; it lives inside their project. |
| Claude Code settings files | Trusted | Owned by the developer; agent-blackbox only edits its own entries. |

### Threats and mitigations

| Threat | Mitigation |
|---|---|
| Command injection through agent-controlled strings (file names, tool inputs) | Every subprocess is launched with an argument vector; `shell=True` is banned (lint rule S602/S604, code review). Agent-controlled content is never interpreted as a command. |
| Secrets persisted in metadata | Tool inputs and prompts are redacted before touching disk (tokens, API keys, credentials in URLs, private-key blocks, password assignments). Each pattern is unit-tested. |
| Regular-expression denial of service in redaction | Patterns are linear-time by construction, inputs are size-capped before matching, and adversarial inputs are covered by timing tests. |
| Hook failure breaking the agent session | The hook catches every exception, never writes to stdout, always exits 0, and enforces its own time budget. Errors go to a capped local log. |
| Corrupting the developer's git repository | Snapshots use a separate shadow repository (`GIT_DIR` inside `.agent-blackbox/`); the developer's `.git` is never written, except for one line appended to `.git/info/exclude`. |
| Overwriting the work tree on restore | `restore` writes to a separate directory by default; in-place restore requires explicit flags and refuses if the tree changed since the last snapshot. |
| Malformed or huge hook payloads | Payloads are size-capped, schema-validated, and unknown fields are ignored. |
| Data exfiltration | There are no network calls in any code path; a lint rule bans network modules and the test suite runs with sockets disabled. |
| Concurrent writers corrupting recordings | A per-project `flock` serializes writes; crash recovery repairs interrupted snapshots (design §6). |

### Accepted risks

- **Snapshots contain file contents.** Any secret stored in a file that is
  not git-ignored is copied into the shadow repository, exactly as it exists
  in the work tree. `.agent-blackbox/` is created with mode `0700`, excluded
  from git, and never leaves the machine. Use `agent-blackbox gc` to delete
  recordings.
- **The bisect test command runs arbitrary code** from past workspace
  states, including code the agent wrote. This is inherent to bisecting: it
  is the same risk as running the test suite on the agent's final result.
  Run it in a sandbox or container if you do not trust the session.
- **Local attackers** with write access to the project directory can tamper
  with recordings. agent-blackbox does not defend against a compromised
  local account.
- **Side effects outside the project** (other directories, databases,
  network services) are neither recorded nor restored.
