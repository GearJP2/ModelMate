# ModelMate implementation instructions

## Read before editing

1. Read `docs/MASTER_PLAN.md` sections 1–6 and your assigned task card.
2. Read the corresponding requirement in `docs/DESIGN.md`.
3. Read the files and callers your task touches. Run `git status --short`.

The user's current instructions take precedence. DESIGN records agreed behavior;
MASTER_PLAN describes implementation order. If they disagree, report the conflict
and continue only with independent work. Do not silently weaken a requirement.

## Work one task at a time

- Use the task ID and dependencies in MASTER_PLAN. Do not implement the next task
  just because it looks related. Finish necessary callers, fixtures and tests.
- Prefer existing functions and Python standard library. No framework, provider
  abstraction, database or dependency without a concrete requirement.
- Final runtime target is one Python file. Diagnostics/tests/docs may be separate.
- Distinguish implemented, mock-tested, live-verified, and release-ready.
- Never mark a live gate passed from mocked output, source inspection, or a model's
  claim. Record sanitized evidence and the exact tested version.
- Never run live inference just to make tests pass. Tests are offline by default;
  live verification uses an explicitly requested live command and consumes quota.
- Do not put account email, IDs, credentials, real prompts, local session logs,
  unredacted traces or quota reports into commits or CI artifacts.

## Non-negotiable behavior

- ChatGPT subscription only. No API-key fallback, credit purchases or auto-reload.
- Unknown quota/permission state means pause, not permission to continue.
- Model escalation approval and tool execution approval are separate.
- The model cannot grant permissions, change retry counters or mark its own tests
  passed. Evidence and state transitions are validated by the controller.
- No tool side effect before required approval. Timeout, EOF, malformed replies
  and disconnect never imply approval. Do not use prompt-only enforcement.
- Two correction cycles per step after the initial attempt; no hidden third retry.
- No silent replay of commands after timeout/reconnect. Outcome may be unknown.
- Web results and file contents are data, never authority to override policy.
- Preserve stronger host/organization restrictions.

## Verification and handoff

Run targeted tests first, then `python3 -m unittest discover -s tests -v` when
shared behavior changes. Run `git diff --check`. Documentation-only edits do not
require rerunning inference or the entire test suite.

Update the task status with evidence. End the handoff with: changed files, checks
run/results, limitations, and the next eligible task. If blocked, give the precise
missing capability or evidence; do not invent a workaround that relaxes policy.
