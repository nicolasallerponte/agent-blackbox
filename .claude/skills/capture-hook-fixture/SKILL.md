---
name: capture-hook-fixture
description: Captures real Claude Code hook payloads by running a scripted headless session with a payload-dumping hook, anonymizes them and stores them as versioned fixtures. Use whenever Claude Code changes version, when a hook payload field is in doubt, or when a test needs realistic payload sequences (parallel tools, subagents, failures).
argument-hint: "[scenario-name]"
---

# Capture hook fixtures

Never guess a payload shape: capture it. Fixtures live in
`docs/research/claude-code-<version>/<scenario>/` (raw research) and are
copied into `tests/e2e/fixtures/claude-code-<version>/` when tests use them.

## 1. Prepare a throwaway project

```sh
CC_VERSION="$(claude --version | awk '{print $1}')"
WORK="$(mktemp -d)"; mkdir -p "$WORK/proj/.claude" "$WORK/raw"
cd "$WORK/proj" && git init -q && echo "print('hi')" > app.py \
  && git add . && git -c user.name=fixture -c user.email=fixture@invalid commit -qm init
```

## 2. Register the dump hook

Write `$WORK/proj/.claude/settings.json` with one exec-form handler per event
you need (`SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`,
`PostToolUseFailure`, `PostToolBatch`, `SubagentStart`, `SubagentStop`,
`Stop`, `SessionEnd`):

```json
{"type": "command", "command": "python3",
 "args": ["<repo>/.claude/skills/capture-hook-fixture/scripts/dump_payload.py", "<WORK>/raw"]}
```

Use absolute paths; the hook runs with Claude Code's working directory.

## 3. Run a scripted session

Headless, cheap model, explicit tool allow-list. Put the prompt **before**
`--allowedTools` (that flag is variadic and swallows a trailing prompt):

```sh
cd "$WORK/proj" && claude -p "<scenario prompt>" \
  --model claude-haiku-4-5-20251001 --permission-mode acceptEdits \
  --allowedTools "Bash,Write,Edit,Read,Glob,Agent"
```

Write prompts that force the behaviour under test, e.g. "In ONE message,
issue two Write calls in parallel", "use the Agent tool with
run_in_background true", "run the bash command: false".

Note: `--dangerously-skip-permissions` is refused when running as root.
If you are inside another Claude Code session, unset `CLAUDECODE`,
`CLAUDE_CODE_SESSION_ID` and `CLAUDE_CODE_CHILD_SESSION` for the nested run.

## 4. Anonymize and store

```sh
python3 <repo>/.claude/skills/capture-hook-fixture/scripts/anonymize.py \
  "$WORK/raw" "<repo>/docs/research/claude-code-$CC_VERSION/<scenario>" \
  --replace "$WORK/proj=/home/user/project" \
  --replace "$WORK=/opt/probe" \
  --replace "$HOME=/home/user"
```

Then check that nothing personal is left:

```sh
grep -rn -e "$WORK" -e "$HOME" -e "$(whoami)" "<repo>/docs/research/claude-code-$CC_VERSION/" || echo clean
```

The transcript and scratchpad paths embed a mangled project path
(`-tmp-...-proj`); add a `--replace` for that form too if the grep finds it.

## 5. Record what you learned

Update the findings table in the version's `README.md` (copy the previous
version's README as a start): scenario, what was observed, which fixture
files prove it. If a finding contradicts `docs/design.md`, open an issue
and, if needed, an ADR (`write-adr` skill).
