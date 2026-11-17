# Verification evidence

## P00 — MOCK_VERIFIED

Offline checks (2026-11-17):

- `python3 -m unittest discover -s tests -q`: 28 tests passed.
- `python3 -m py_compile doctor.py verify.py`: passed.
- `git diff --check`: passed.

Regression coverage:

- Fragmented JSONL notifications/results followed by EOF are consumed before
  reporting the closed stream. Unexpected response IDs are rejected.
- Missing, malformed, exhausted, boolean and multiple quota windows fail closed.
- Account identity must be supplied by each quota read and remain stable between
  turns. The backend's ordinaryUsageAllowed remains the authority for included
  usage; this is not independent credential or user-identity validation.
- Unknown/malformed approval requests and stale thread/turn requests are not
  answered. Diagnostic methods remain restricted to read-only RPCs.
- Turn deadline includes time waiting for turn/start; it is not renewed per event.
- Events arriving before the start RPC response are retained.
- Missing start response without a turn ID leaves outcome unknown, blocks retry,
  and retains the scratch directory. If turn/started supplies an ID, interruption
  can target that turn despite the lost response.
- Interrupt acknowledgement alone is insufficient: a matching terminal event is
  required before clearing active state and deleting scratch data.
- Interruption/cleanup errors preserve the original failure. Unconfirmed stop
  cannot produce a successful report.
- Recall success reports requested models separately from unknown reported models;
  actual model dispatch is not claimed as verified.

The test output includes intentional cleanup/interruption warnings from injected
failures. They are expected assertions, not live Codex failures.

Live inference: NOT RUN. G1–G4 remain unverified. No account identifiers or raw
account reports are recorded here. P00 still needs the designated lifecycle review
before being treated as release-ready. Next eligible offline task: P02. P01 needs
normal-terminal live evidence; no sandbox bypass has been added.


## P02 — MOCK_VERIFIED

Shared protocol and account inspection now live in `modelmate.py`; doctor and
verify import that code, and no protocol reader is duplicated. The base method
allowlist remains read-only; only the verification subclass permits live turns.
Runtime import creates no process, selector or network connection, even when only
modelmate.py is copied to a fresh directory. This is a runtime foundation, not a
finished chat CLI.

Offline checks (2026-11-17):

- `python3 -m unittest discover -s tests -q`: 34 tests passed.
- `python3 -m py_compile modelmate.py doctor.py verify.py`: passed.
- `git diff --check`: passed.
- `python3 doctor.py --help` and `python3 verify.py --help`: passed without login.

Additional tests exercise invalid response envelopes (including boolean IDs),
unknown server requests, bounded receive buffers, a notification flood with a
fixed RPC deadline, single-file import isolation and shared-class identity.
Existing byte-fragmentation, interleaving, EOF, cancellation and process shutdown
regressions remain passing. Verification event storage retains its 10,000-event
limit; the receive buffer retains its 4 MiB limit.

Live inference: NOT RUN. G1–G4 are unchanged. Next eligible offline task: P04.
P01 still requires normal-terminal evidence; P03 still requires the permission
capability investigation before real tool execution can be exposed.


## P04 — MOCK_VERIFIED

Shared quota policy now lives in `modelmate.py`. `quota_decision` returns
allow/pause, a machine-readable reason, monotonic checked_at and account identity
for in-memory use. `refresh_quota` reads ChatGPT auth and quota for each new turn;
verify uses it rather than maintaining a duplicate policy. The compatibility
ensure_quota entry point validates a snapshot but does not start or authorize a
future turn by itself.

Offline checks (2026-11-17):

- `python3 -m unittest discover -s tests -p test_quota.py -v`: 14 tests passed.
- `python3 -m unittest discover -s tests -v`: 48 tests passed.
- `python3 -m py_compile modelmate.py doctor.py verify.py`: passed.
- Doctor and verify help commands: passed without connecting to Codex.
- `git diff --check`: passed.

The JSONL subprocess tests record actual request methods and assert no turn/start
is transmitted for unknown/exhausted quota, missing identity, RPC failure,
closed connection or API-key auth. Further tests confirm every turn refreshes,
account changes stop the next turn, and an exhausted snapshot can recover only
through a new read. Pure tests cover multiple buckets, malformed values, credit
access and slow/stale refreshes. The P02 isolated-import subprocess test had a
missing patch import after cleanup; it is corrected and passing in this run.

Policy boundaries:

- A snapshot older than 15 seconds (including time spent refreshing), with a
  future/non-finite timestamp, is paused. Monotonic timestamps are process-local
  and must not be persisted as resumable grants.
- Without reliable model-to-bucket mapping every returned bucket must pass. This
  may conservatively pause even when another model would work. No guessed bypass.
- Reset time passing does not override exhausted/unknown status.
- Account identity is pinned from the first allowed quota response and compared
  thereafter. Backend validation of ordinaryUsageAllowed is still required; the
  local comparison is not an independent credential check.
- Credits absent/null in a response are not proof that no paid-credit facility
  exists. Known positive credit access pauses the diagnostic. Backend included
  usage permission and preflight are not a hard spending cap or reservation.
- No credit purchases, resets, API-key fallback or billing changes were added.

Live inference: NOT RUN. G1–G4 remain unverified. The full controller/session UI
will consume these decisions in later tasks; this task only implements quota
policy and integrates it into the existing verification turn path.
Next eligible offline task: P05 (model roles and effort policy).


## P05 — MOCK_VERIFIED (live role mapping pending)

Added shared catalog pagination, explicit model/effort selection, trusted role
resolution and a conservative change-comparison function in modelmate.py.
Doctor uses the shared catalog reader; verify uses the shared selection validator.
No second catalog parser or selection validator was introduced in the diagnostics.

Offline checks (2026-11-17):

- `python3 -m unittest discover -s tests -p test_models.py -v`: 12 passed.
- `python3 -m unittest discover -s tests -q`: 60 passed.
- `python3 -m py_compile modelmate.py doctor.py verify.py`: passed.
- `git diff --check`: passed.

Tests cover pagination/cycles/invalid pages/duplicate IDs, hidden models,
unsupported/default/future effort, missing roles, explicit role bindings, catalog
changes on resume, manual selection and conservative escalation comparisons.
A selection does not mutate catalog or grant permissions. The future workflow
must refresh catalog on startup/resume and validate again; there is no resume UI
yet. Unknown comparisons require approval rather than guessed cost rankings.

Built-in MODEL_ROLE_POLICY is deliberately empty: no real model has completed
P01 live dispatch validation and reviewed role assignment. The role resolver
accepts trusted reviewed bindings or explicit user bindings; neither the model
classifier nor text in project files may supply that authority. Synthetic model
bindings in tests prove behavior, not production model quality.

EFFORT_ORDER defines an explicit conservative policy for familiar effort labels,
not measured token/quota consumption. Unknown labels are selectable only when
present in the catalog, and any comparison involving them requires approval.
Cross-model downgrade needs unambiguous trusted role mapping and non-increasing
effort; model role and effort comparisons never grant tool execution rights.

Live inference: NOT RUN. No performance, model availability, role quality or
quota-saving claims have been verified. Next eligible offline task: P06.


## P06 — IN_PROGRESS (offline plan pipeline MOCK_VERIFIED)

Implemented version-1 plan validation, proposal-to-role resolution and inert
classifier request preparation in modelmate.py. Unknown keys, duplicate JSON keys,
invalid enums, empty checks, non-finite JSON constants, oversized text/proposals
and more than 12 steps are rejected. High-risk proposals require a strong review
step with checks. Clarifications return no resolved execution selections.

The routing result is ready_for_approval, never authorization to execute. Only
trusted role mappings resolve model/effort pairs; proposal fields cannot grant
permissions, assign IDs, set retry counters or mark tests passed. This is schema
and policy validation, not proof that a model classified real task risk correctly.

Preparation refreshes catalog and quota and validates explicit classifier selection
and role bindings. User text is encoded as task data separate from classifier
instructions. Status/approval/unchanged-scope triggers cause no RPC. The controller
must supply those triggers; the model is not allowed to classify its own approval
reply as a new task. The input descriptor is not an RPC request.

Offline checks (2026-11-17):

- `python3 -m unittest discover -s tests -p test_routing.py -v`: 14 passed.
- `python3 -m unittest discover -s tests -q`: 74 passed.
- `python3 -m py_compile modelmate.py doctor.py verify.py`: passed.
- `git diff --check`: passed.

Remaining integration: live classifier invocation and output collection are not
implemented because no supported no-tools execution boundary has been proven.
read-only sandbox alone can still permit shell reads; prompt instructions alone
cannot satisfy the P06 no-tools requirement. Preparation therefore explicitly
reports blocked_until_no_tools_boundary_verified and never sends turn/start.
No prompt-only enforcement or assumption that unknown tool calls cannot occur was
introduced. P03 must establish the boundary before exposing live classification.
P07's offline grant/mode logic can be developed using the validated proposals;
full P06 must not be marked DONE or LIVE_VERIFIED from these tests.

Live inference: NOT RUN. G1–G4 and actual task-quality evaluation remain pending.


## P07 — MOCK_VERIFIED (offline policy)

ModelApprovals holds a fresh task ID and a task-local standard-model baseline.
The default mode is ask_to_escalate. Auto returns the model selection and a short
reason; ask_to_escalate asks for strong initial selections, increases and unknown
comparisons; approve_plan asks for the full plan before allowing its model choices.
The output allow_model is only a model-policy decision, never a tool or quota grant.

Approvals bind to a digest of task identity, validated complete plan, resolved
model/effort choices and trusted role mapping. Step model approvals additionally
bind to controller step ID/index. Whole-plan approval covers all unchanged steps;
manual model approval covers only the named step and does not approve a plan.
Changed/invalid/unclear plans revoke old approvals, including when a plan later
changes back. Pending tokens cannot be replayed after context/mode changes.

Only explicit approve/decline/pause choices are accepted. Invalid choices, EOF-like
None and stale tokens never approve. Declines pause and offer revise-scope/model
or pause; the system does not silently upgrade. Grants remain process-memory only.
P08 must obtain these calls from actual human UI input; project/model text cannot
be used as authority to call answer or manual_select. P09 separately controls tools.

Offline checks (2026-11-17):

- `python3 -m unittest discover -s tests -p test_modes.py -q`: 14 passed.
- `python3 -m unittest discover -s tests -q`: 88 passed.
- `python3 -m py_compile modelmate.py doctor.py verify.py`: passed.
- `git diff --check`: passed.

Coverage includes three-mode initial/escalation/downgrade matrix, plan/model/effort
changes, repeated questions, stale tokens, declines, task boundaries, step scopes,
manual choices, ambiguous comparisons and old-grant resurrection prevention.

No live inference or Terminal UI integration has been run. P06 live classifier
still awaits the proven no-tools boundary; P07 consumes only its offline validated
proposals. Next eligible task: P08 mock-driven Terminal shell, or independent P11
session metadata. G1–G4 remain unverified.


## P08 — IN_PROGRESS (Terminal shell MOCK_VERIFIED)

Added the single-file runtime entry point and a line-oriented Terminal shell.
The shipped entry point has no live backend: prompts receive an explicit
unavailable message, never simulated model output presented as actual inference.
No process/network connection is opened by default or --help.

One selector loop owns stdin, injected controller events, pending UI decisions
and shutdown state. There is no input worker thread. A trusted controller callback
is an internal test/integration seam, not an external replay or backend CLI option.
Model policy uses P07; approvals require the exact displayed token. Text such as
yes is not approval. Unknown slash commands are never submitted as prompts.
The UI filters control/direction characters and does not render reasoning events.
Unknown tool events fail closed. Ctrl+C/EOF clear pending requests and request
cancellation, waiting for confirmation before reporting stopped. Missing stop
confirmation expires after five seconds with outcome unknown (exit 130).

Offline checks (2026-11-17):

- `python3 -m unittest discover -s tests -p test_cli.py -v`: 13 passed.
- `python3 -m unittest discover -s tests -q`: 101 passed.
- `python3 -m py_compile modelmate.py doctor.py verify.py`: passed.
- `git diff --check`: passed.

CLI subprocess checks cover --help with no executable Codex on PATH, initial Thai
prompt, piped blank/command input, concurrent controller text and status input,
EOF during approval and SIGINT during approval. The fake controller never calls
Codex. Policy tests cover stale tokens, changed modes, clarification invalidation,
manual selections, denial, cancellation deadlines and Terminal escape filtering.

Remaining integration: /permissions does not expand rights, /sessions and /delete
report unavailable, and /exit does not save a session yet. These depend on P03/P09,
P11/P12. Live classifier, stream turn IDs, real controller dispatch and actual
cancellation must be wired only after the relevant gates pass. This is not a
production agent or complete P08 delivery; pending commands are not counted as
working features. Next independent offline task: P11 local session persistence.
Live inference: NOT RUN. G1–G4 unchanged.


## Live connection attempt and P03 source investigation — 2026-11-17

P01 remains BLOCKED in this development sandbox. `codex login status` reports
ChatGPT login, but both `python3 doctor.py --timeout 10` and the new standalone
`python3 modelmate.py --doctor` fail before a protocol response. A separate startup
probe classifies stderr without printing raw logs: exit 1, SQLite initialization
failure, read-only filesystem error, no protocol response. No credentials were
copied and no permission bypass was attempted. No inference was requested.

The runtime now supports --doctor as an explicit connection-only entry point,
using the same inspected read-only protocol path. It rejects an initial prompt
in this mode, reports a failure as exit 1 and closes its child process. This is
not live conversational inference. Default chat remains offline.

P03 capability matrix (source inspection, not live enforcement proof):

| Path | Evidence | Current disposition |
| --- | --- | --- |
| Shell/exec | Tagged spec_plan.rs add_shell_tools checks ShellTool feature/model shell type | Candidate feature control; live behavior unverified |
| apply_patch | Tagged spec_plan.rs registers ApplyPatchHandler when model apply_patch_tool_type exists | No verified universal client no-tools override |
| Hosted search | Hosted search bypasses local tool hooks per official hook documentation | Disabled in private contexts; isolation still unproven |
| MCP/plugins/subagents/hooks | Separate feature/config surfaces exist | Full disable/bypass matrix not live verified |
| No-tools classifier | read-only permits some tools; prompt cannot enforce absence | Live classifier remains unavailable |

Tagged source inspected:
https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/core/src/tools/spec_plan.rs
(add_shell_tools and ApplyPatchHandler registration). An open upstream feature
request https://github.com/openai/codex/issues/60069 corroborates the no-tools
concern, but its report concerns an older alpha/Windows and is not proof of
behavior on this installation. The tagged code is the primary evidence here.

Checks:

- `python3 -m unittest discover -s tests -q`: 104 passed.
- `python3 -m py_compile modelmate.py`: passed.
- `python3 modelmate.py --doctor`: attempted, failed at local Codex startup.
- `git diff --check`: passed.

To complete P01, run --doctor in a normal Terminal where Codex can write its
runtime state, then run verify.py --run-live using model IDs that catalog actually
returns. The latter consumes subscription quota. Only sanitized results belong
in this file. P03 still needs lifecycle/security review and live evidence before
any claim that every action asks for approval or that classifier tools are absent.


## P01 — user-supplied live read evidence received 2026-11-17

The user supplied a successful diagnostic result generated on 2026-11-16 UTC
from their normal Terminal. This supersedes the account/catalog/quota part of
the earlier environment block; the development sandbox itself remains restricted.
Evidence source is the user's diagnostic output, not an independently reproduced
run here. The output does not identify which diagnostic entry point was used.

Verified at the time of that snapshot:

- Account type ChatGPT; Plus plan.
- Catalog and supported effort options returned successfully, including
  gpt-6.1-sol, gpt-6-astra and gpt-6-luna.
- ordinaryUsageAllowed true; primary and secondary usage windows returned.
- No reached-limit/spend-control flag and no additional credits reported.

No raw report, quota percentages, account identifiers or session IDs are stored.
This is historical evidence, not a reusable quota grant; refresh before inference.

Several catalog models also advertise ultra with automatic task delegation.
Catalog availability is not permission to delegate. Existing policy treats ultra
as an unknown comparative effort and requests approval, but this alone does not
prove delegation is disabled. Live classifier/tool execution remains gated by P03.
Use the verification harness's explicit low effort where catalog supports it;
do not enable ultra automatically from this report.

Still unverified: actual inference dispatch, model/effort changes, context recall,
command/patch denial and the complete permission/no-tools boundary. P01 remains
IN_PROGRESS, not fully LIVE_VERIFIED. Next live check, using the freshly returned
catalog IDs, is:

```bash
python3 verify.py --run-live --models gpt-6.1-sol gpt-6-astra
```

This consumes subscription quota and performs synthetic scratch-file denial checks.
A pass proves only the tested scenarios, not all tool paths or actual model dispatch
if the backend does not report it. An INCONCLUSIVE result is not a pass.

Documentation-only update: checked `git diff --check`; no inference or tests rerun.


## P01/P03 — user-supplied live harness evidence received 2026-11-17

Command reported by the user:

```bash
python3 verify.py --run-live --models gpt-6.1-sol gpt-6-astra
```

User-supplied result: contextRecall passed, commandDenial passed, patchDenial
passed. Requested models were gpt-6.1-sol and gpt-6-astra. reportedModels was null
and modelSwitch was explicitly unverified. No independent rerun was performed
inside the restricted development sandbox, and no thread/account IDs are stored.
The harness chooses low effort where catalog supports it, but this report does
not independently establish backend model or effort dispatch.

This advances the preceding pending evidence: a real turn sequence produced a
correct synthetic recall answer, and the harness observed matching denial events
with neither scratch marker present. P01 remains IN_PROGRESS because actual
model/effort dispatch is not reported. G1 has partial live evidence; it is not
fully verified. P03 now has two live denial scenarios; G2/G3 remain unproven.

These checks do not prove default ask-before-every-command behavior. The harness
explicitly requests approval for scratch writes inside a read-only sandbox.
Unapproved read commands, stdin continuation, MCP/plugins, hooks, subagents,
symlink/outside-project access and hosted tools still need boundary evidence.
Do not enable the live no-tools classifier or all-tool execution on this basis.

Next investigation: obtain trustworthy model/effort metadata if supported and
complete the tool-path enforcement matrix. No need to rerun this same pair solely
to reproduce an already supplied recall result. Luna/Terra availability from the
catalog is not a role-quality benchmark; they remain eligible for explicit
selection/testing without a claimed production role mapping.

Documentation-only checks: `git diff --check` passed. No new inference was run.


## P01/P03 — configuration evidence and read-command probe preparation

Inspected the installed 0.169.0 JSON schemas: Thread.model explicitly describes
configured state rather than per-turn execution telemetry. Thread settings
notifications carry model/effort but no turn ID; raw response completion carries
usage and IDs but no actual model field. The harness now records requested
selection and settings observations separately and leaves reportedModels unknown.
No self-identification prompt or guessed dispatch assertion was added.

Added a separate --probe-read-approval path: one synthetic printf turn, no handoff
rerun, no file reads/writes requested. It records command completion/denial by
matching actual tool item IDs internally, but reports only type/status/denial flag.
It never accepts an approval. A successful command without denial is a bypass
observation; no tool evidence is inconclusive. Neither result passes the gate.
Expanded the path-by-path matrix in docs/PERMISSIONS.md.

Offline checks (2026-11-17):

- `python3 -m unittest discover -s tests -q`: 112 passed.
- `python3 -m py_compile modelmate.py doctor.py verify.py`: passed.
- `python3 verify.py --help`: passed.
- `git diff --check`: passed.

Tests use JSONL subprocesses to exercise settings events before RPC replies,
missing metadata, wrong-thread/malformed metadata, and sanitized tool observations.
Probe classification tests distinguish execution, denial and inconclusive cases.
No raw tool command/output or thread/account identifiers are in evidence reports.

Live inference this round: NOT RUN. The previous user live result remains valid
only for its scenarios. The new read-command probe still needs user Terminal
execution; existing sandbox restrictions are unchanged. P03 remains IN_PROGRESS.


## P03 — negative live evidence received from user 2026-11-17

The user ran the new single-turn printf probe with gpt-6.1-sol requested at low.
Result: readCommandApproval executed_without_approval; a commandExecution item
completed with denialObserved false. No thread settings were observed; actual
model dispatch remains unknown. Evidence is user-supplied, not a local rerun.
No raw user/account/thread identifiers or tool output are stored here.

Conclusion: read-only + on-request in the tested configuration does not satisfy
R06 ask-before-every-command. This is a failing requirement check, not a passing
permission gate. It does not imply all shell commands bypass approval, and it does
not negate the earlier scratch-write denial results. The tested command only
printed a synthetic marker; no file read/write was requested.

The runtime still does not expose live tools. R06 has not been relaxed. Next
architecture decision requires user agreement if default permission semantics
change; otherwise enforcement must be developed and proved before P09 can ship.
Independent offline tasks remain possible while resolving the boundary.
Documentation-only check: git diff --check passed; no new inference was run.


## User-approved native permission policy and opt-in manual live chat

User explicitly selected option 1: use native Codex permission behavior.
This supersedes ask-before-every-command in R06. Default is read-only + on-request;
commands allowed by that sandbox need not ask. Required server approvals still
need human input. No automatic workspace-write/full-access or session-wide grant
was introduced. Stronger host/managed restrictions still apply. The earlier printf
result is an expected observation under the new policy, not a failure of new R06.
Historical evidence above refers to the policy in effect when recorded.

Implemented --live --model ID [--effort LEVEL] in the single-file runtime.
This path is manual-model chat, not automatic routing or the no-tools classifier.
It uses a ChatGPT-only/openai provider configuration, inspects catalog/auth,
creates one ephemeral read-only thread, and refreshes catalog/quota before each
new turn. Text during a known active turn uses turn/steer. Turn-start uncertainty
is not retried. Requested ultra delegation effort is not enabled.

The UI/backend share one owning selector loop. The existing protocol reader was
factored into pop_message/read_ready so synchronous diagnostics and asynchronous
live chat do not duplicate parsing or size limits. Async RPC IDs and deadlines
are correlated; disconnect/unknown result does not lead to automatic replay.
Model selection, inference dispatch and tool decisions remain distinct.

Command approvals display exact escaped command/cwd; file approvals require a
bounded preview captured from the corresponding fileChange item. Human approve
is a one-time accept, decline/pause do not approve. Missing previews, oversized
requests, overlapping requests and unsupported/stale request types are refused
or stop the session. Cancellation declines pending requests and waits for the
matching terminal event. Interrupt acknowledgement alone does not mean stopped.
Hosted search/apps/plugins/agents are requested disabled in this path, but a
universal no-tools/private-context isolation claim is not made.

Offline checks (2026-11-17):

- `python3 -m unittest discover -s tests -p test_live.py -v`: 13 passed.
- `python3 -m unittest discover -s tests -q`: 125 passed.
- `python3 -m py_compile modelmate.py doctor.py verify.py`: passed.
- `git diff --check`: passed.

Tests cover native thread settings, fail-closed quota, exact one-time approvals,
missing/stale previews/tokens, stop confirmation, streamed-text deduplication,
completion-before-start-response ordering and delayed-start cancellation.
A subprocess integration runs the actual --live entry point against an injected
JSONL fake Codex server for two turns, with explicit accept then decline, verifying
one thread and renewed quota checks. This does not use real credentials/quota.

The new live-chat integration has NOT been run against the actual account here;
startup remains blocked by the development sandbox. The user's previous harness
results establish account/turn/denial behavior only for those scenarios.
P03/P08/P09 remain partial. No autosave/resume, automatic workflow or universal
support for permission/tool-input request types is claimed. Unsupported server
requests stop without granting rights. Next validation: a normal-terminal --live
chat with an explicitly selected available model and a harmless text prompt.


## Live second-turn failure — recovery and diagnostic changes

User reports that the first live text turn completed, then the second prompt
terminated with the generic transport/data error. The original output contains
no exception class/errno/stage, so the exact real-account root cause is unconfirmed.
No raw user conversation or account logs are stored.

Confirmed failure paths corrected:

- Catalog refresh/selection failure before inference used to terminate chat.
  It now pauses without sending that prompt, leaves the session open, and requires
  explicit user resubmission. It does not retry inference or weaken quota checks.
- Protocol stdout/stderr reads are nonblocking. A ready descriptor whose bytes
  were consumed by a synchronous preflight RPC can return EAGAIN without being
  treated as disconnect/fatal error or blocking the UI on stale readiness.
- Fatal errors report a local phase and safe exception class/errno, not raw paths,
  request payloads, credentials or exception messages from external libraries.

Offline validation:

- `python3 -m unittest discover -s tests -p test_live_recovery.py -v`: 3 passed.
- `python3 -m unittest discover -s tests -q`: 128 passed.
- `python3 -m py_compile modelmate.py doctor.py verify.py`: passed.
- `git diff --check`: passed.

The regression uses a pseudo-terminal for Thai stdin and a JSONL fake Codex server,
with late usage notifications after completion and a deliberate second-prompt
catalog error. Three successful turns stay on one thread; the failed prompt never
appears in turn/start. Separate tests inject EAGAIN and verify diagnostics redact
exception payloads. These tests establish the corrected scenarios, not an exact
reproduction of the user's unknown underlying exception.

Actual-account retest: pending. If it still stops, use the new phase/class/errno
line to locate the failing operation; do not request raw secrets or full logs.
Git workflow now requires branch → detailed PR → checks/review → PR merge.


## P11 — MOCK_VERIFIED (local metadata storage API)

Implemented SessionStore in the single-file runtime. State uses XDG_STATE_HOME
(or ~/.local/state)/modelmate and a SHA-256 project key derived from canonical
real path. Controller-created session UUIDs name the files. Metadata schema v1
contains task/step/criteria/correction status and optional Codex thread ID, not
transcripts, credentials, quota grants or execution approvals. Goal/summary can
still be sensitive; this is private local storage, not encryption or redaction.

Directory/file permissions are restrictive (0700/0600). File descriptors use
O_NOFOLLOW; regular/private/single-link files are required. Project-directory fd
operations keep reads/replaces anchored if a pathname is later retargeted. Project
symlink aliases resolve to the same identity. Relative state-home values are
rejected rather than writing implicitly under the current working directory.

Nonblocking Linux flock rejects another writer and is held for the entire edit
context. Checkpoints require that lock; normal context exit saves atomically.
Locks remain as small files to avoid lock-inode races. Exceptions leave the last
completed checkpoint in place. Save writes a same-directory temporary file,
flushes/fsyncs it, replaces atomically and fsyncs the project directory. JSON that
is corrupt, has unknown fields/version or mismatched identity is not overwritten.

Offline validation (2026-11-17):

- `python3 -m unittest discover -s tests -p test_sessions.py -v`: 19 passed.
- `python3 -m unittest discover -s tests -q`: 147 passed.
- `python3 -m py_compile modelmate.py doctor.py verify.py`: passed.
- `git diff --check`: passed.

Tests cover Thai/spaced paths, canonical project aliases, separate projects,
private permissions, corrupt/future-schema preservation, ID collision, invalid
metadata, symlink rejection, directory retargeting, failed replace, checkpoints,
exceptions, real subprocess lock contention and process death before replace.
A nested writer failure must not revoke the outer writer's lock ownership.

Scope/limits: storage primitives only. Existing live chat is still ephemeral and
has no autosave/resume integration; /sessions and /delete remain unavailable.
P12 must handle durable thread creation/resume and unknown in-flight outcomes
before exposing these commands. Saved mode/profile are hints, not automatic
restoration of grants. A directory-fsync failure after replace may mean the new
complete file is installed but durability is uncertain; no rollback is claimed.
An abrupt process death can leave an ignored .tmp file; no speculative cleanup
or schema migration framework was added. Actual power-loss and hardware storage
faults were not tested. No live inference was run. Next eligible task: P12 planning
and lifecycle integration, subject to its P10 dependency for workflow-specific state.

## P12 — manual chat lifecycle MOCK_VERIFIED; full task IN_PROGRESS

Manual live CLI now requests durable Codex threads and holds the per-session
writer lock for its entire attachment. Schema v2 adds a SHA-256 account identity
fingerprint, last known turn ID and deletion receipt state. No raw account ID,
credentials, transcript or approval grant is added. V1 remains readable; it is
not silently bound to the current account or resumed. Future versions are rejected.
The first prompt supplies a bounded goal/title; it can contain private text.

Checkpoints are written before turn/start and before accepting a tool decision.
Terminal events save UNVERIFIED/FAILED/PAUSED, never model-claimed task success.
Resume reads fresh account/catalog/quota and checks canonical project, thread ID,
provider, durability, runtime status, latest turn and effective native permissions.
An interrupted checkpoint remains outcome_unknown even if the backend reports a
completed turn. The user must inspect files/processes and acknowledge a fresh token
before sending new text. Nothing automatically replays the old prompt or command.
Existing correction counters survive; P10 workflow is not implemented by this task.

Deletion previews include root and spawned descendants, scanning active and archived
history with bounded pagination and all declared source kinds. Scope is read again
on exact, one-use confirmation. Separate descendant ModelMate records require their
own deletion first. Remote failure/unknown outcome keeps metadata and blocks new work
in that session. Confirmed remote success is checkpointed before local removal; an
ordinary local cleanup failure can retry without another remote delete. A missing
thread alone never proves successful deletion. No work files are removed or reverted.
Deleting the current session closes the chat. /cancel and new work expire delete tokens.

Offline validation (2026-11-17):

- `python3 -m unittest discover -s tests -p test_lifecycle.py -v`: 18 passed.
- `python3 -m unittest discover -s tests -q`: 165 passed.
- `python3 -m py_compile modelmate.py doctor.py verify.py`: passed.
- `git diff --check`: passed.

Tests include an actual synthetic CLI exit/restart/resume/delete round trip, a
subprocess death after a RUNNING checkpoint, lock release, crash before/after tool
results, disconnect before turn response, wrong account/project, missing/legacy
thread, weakened resume permissions, correction counter preservation, exact/stale
tokens, changed subtree, active descendants, quota-exhausted deletion, partial
deletion and lost remote-deletion receipts. Existing multi-turn subprocess tests
now use temporary XDG state directories rather than the user's state directory.

Protocol reference: locally generated Codex v0.169.0 schemas for ThreadResume,
ThreadTurnsList, ThreadList and ThreadDelete, plus official request handler/tests:
[thread_delete.rs](https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/app-server/src/request_processors/thread_delete.rs)
and [deletion tests](https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/app-server/tests/suite/v2/thread_delete.rs).
Source/schema inspection and synthetic replies are not proof of live interoperability.

Limits: no real-account resume/delete inference was run. Native Codex state access
is still constrained in this development sandbox. The server has no expected-scope
delete parameter, so another client changing the subtree between the final read and
delete cannot be excluded. Remote success followed by a lost receipt can leave a
pending local record that requires explicit inspection; there is no automatic
missing-thread cleanup. A lost thread/start response can leave an unassociated
Codex thread; local metadata cannot recover its unknown ID. Filesystem fsync and
power-loss limits from P11 remain. P12 stays IN_PROGRESS until P10 workflow
integration and real-account evidence are available.

Suggested opt-in live check in a disposable project: open a manual live session,
send a synthetic recall marker, record only the local session ID privately, /exit,
reopen with --resume, ask for the marker, and then /delete plus its confirmation
token. Confirm the session disappears locally and in Codex, with a sentinel work
file unchanged. This uses subscription quota; do not commit prompts, IDs or traces.

### P12 opt-in session verification harness — MOCK_VERIFIED

Added `python3 verify.py --run-live --probe-sessions MODEL`. It reuses the runtime's
LiveChatConnection, SessionStore, ChatShell and confirmed-delete flow, with two
separate App Server processes and a private temporary project/state store. The
second prompt contains no recall marker. Both turns request low effort and pass
the ordinary account/catalog/quota checks. No API-key fallback or billing changes.

The explicit command authorizes automatic confirmation only when the preview
contains exactly the harness-created thread and scratch project, without any
descendants. A changed sentinel/extra file, failed recall, unexpected tool,
incomplete turn, delete failure or lingering history entry prevents a success
report. Success requires metadata removal, absence from both active and archived
listings across all declared source kinds, and an unchanged sentinel after deletion.
Runtime and verifier SHA-256 hashes identify the tested files. JSON output excludes
account identity, thread/session IDs, paths, prompts and recall markers.

Failure retains scratch metadata/files and prints the failed phase and scratch path
on stderr for local inspection. Active turns are interrupted with a bounded wait
before closing the connection and store; no retry or replay is performed. The
harness never accepts a tool approval. Native permitted tools can start before
observation, so detection is not a universal no-tools guarantee. Failed checks do
not automatically delete their remote thread. Do not commit retained scratch state.

Offline checks (2026-11-17):

- `python3 -m unittest discover -s tests -p test_session_probe.py -v`: 10 passed.
- `python3 -m unittest discover -s tests -q`: 175 passed.
- `python3 -m py_compile modelmate.py doctor.py verify.py`: passed.
- `git diff --check`: passed.

Tests use real synthetic JSONL server subprocesses sharing temporary state across
reconnects. They cover exact-scope deletion, redacted reports, a second prompt
without the marker, recall/turn failures, descendants, failed deletion retaining
its checkpoint, non-appServer history listings, sentinel changes, unexpected tool
denial/interruption, timeout without replay, and opt-in/exclusive-mode validation.
The source-kind list is shared with the runtime's deletion scope enumeration.
No real inference was run during harness development. Subsequent user-run evidence
is recorded below; wider lifecycle/permission gates remain separate.

### P12 manual reconnect/recall/delete — scoped LIVE_VERIFIED

On 2026-11-17 the user ran, from their normal Terminal:

```bash
python3 verify.py --run-live --probe-sessions gpt-6.1-sol
```

Reported results: sessionResume, contextRecallAfterReconnect, confirmedDeletion,
localMetadataDeleted, threadAbsentFromListings and sentinelUnchanged all `passed`.
Requested model/effort: `gpt-6.1-sol` / `low`. Reported backend model remains null;
no actual-dispatch claim is made.

The supplied file hashes match the local files and PR #3 head `5647656` exactly:

- Runtime SHA-256: `b113e5be95fa51b5a27dc8404cbe50f0f056b09f9c110f28e64571d96334c80c`
- Verifier SHA-256: `6d90d9781067a994875351624580c656ca138de3bac8eb3bc86806f4cf707242`

Evidence source: the user's supplied sanitized JSON report; no additional inference
was run to record it. Account identity, thread/session IDs, prompts, paths and raw
traces are not stored here. This verifies two synthetic turns across separate
connections and one scratch-thread deletion with unchanged sentinel. It does not
verify crash recovery, all tool paths, automated workflow, actual backend dispatch
or complete service-side data erasure. P12 remains IN_PROGRESS for P10 integration
and remaining lifecycle evidence. The scoped manual-chat PR can now be assessed
for merge with its existing offline checks and these live results.

Documentation-only follow-up: file hashes matched; `git diff --check` passed.
No repeated inference or full test rerun was needed. Next work: workflow/controller
development under P10's permission gates, with live crash/tool-path checks tracked
separately rather than inferred from this happy-path result.

## P10 offline workflow controller — MOCK_VERIFIED; full task IN_PROGRESS

Added WorkflowController to the single-file runtime. It validates a fixed task
plan, creates task/step/attempt/evidence IDs, and owns step position, attempts and
cycles. A RUNNING snapshot reserves an attempt slot before dispatch; the returned
descriptor explicitly says `execution: not_dispatched` and grants no tool access.
The controller opens no connection, process or file and is not wired into ChatShell
or LiveChatConnection. P09/classifier gates are not bypassed to enable auto mode.

Host API and lifecycle:

- `request_attempt` checks a fresh timestamped quota snapshot with account pinning,
  resolves the supplied catalog/role bindings through ModelApprovals, and counts a
  slot only after model approval. All three model modes retain existing P07 rules.
- `answer_model` accepts exact UI tokens. `revise_step` can change only the current
  objective/role/effort/reason. It keeps step ID and budget, rejects changed task
  criteria/checks/structure and invalidates model grants/tokens immediately.
- `finish_attempt` accepts a host terminal event. Completion enters CHECKING;
  interruption pauses with unknown outcome; execution failure is FAILED. None
  of these events means that the task's checks passed.
- `record_check` binds evidence to the active attempt and exact check index.
  Observed integer exit codes determine test/lint results. Source checks require
  an HTTP(S) URL and a verified claim finding from the trusted source checker;
  URL presence is not treated as fact verification. Manual/rubric results must
  come from a trusted manual check. `model_review` is recorded as unknown and
  cannot turn a model assertion into a passed test or human/source verification.
- `evaluate_attempt` advances a fully checked step, offers a bounded correction
  after known failure, or marks incomplete/unknown checks UNVERIFIED. One initial
  attempt plus two corrections exhausts a step's cycle. A fourth attempt cannot
  start without the user's exact pause token and explicit continue choice.
- `answer_pause` retains old cycles and a user-choice/budget-extension ledger.
  It cannot resume an active unknown turn. `observe_quota` blocks new work when
  quota/account state is unsafe; the future executor must issue the native
  interrupt and feed back its terminal event. The pure controller does not do I/O.
- `finish_task` requires trusted checker coverage of every task success criterion
  using accepted evidence IDs from the current successful step attempts. Missing
  coverage is UNVERIFIED; fabricated/stale/failed-attempt evidence is rejected.
  Snapshots retain the criterion/evidence mapping and return defensive copies.

Shared plan validation now requires a strong review after the last high-risk
non-review step. A review before the risky work no longer satisfies the gate.

Offline validation (2026-11-17):

- `python3 -m unittest discover -s tests -p test_workflow.py -v`: 23 passed.
- Additional routing regression rejects strong review before high-risk work.
- `python3 -m unittest discover -s tests -q`: 199 passed.
- `python3 -m py_compile modelmate.py doctor.py verify.py`: passed.
- `git diff --check`: passed.

Checks cover simple code, plan/implement/strong-review ordering, document rubric
and source checks, per-step correction budgets, explicit cycle extensions, rename
and scope-reset attacks, model/effort gate changes, stale tokens, paused checks,
quota exhaustion during work, unknown/stale/account-changed quota, missing models,
unknown/model-claimed checks, actual synthetic Python subprocess exit codes,
duplicate/stale evidence, criteria coverage, large Thai JSON plans without ASCII
re-encoding inflation, and no process creation by the core.

Limits: these are trusted in-process controller callbacks, not a security boundary
against Python callers. Production adapters must bind exit codes, terminal events,
manual choices and verified source findings to actual actions; feeding parsed model
JSON into these methods would violate the contract. Role bindings remain explicitly
supplied; no live model ranking is added. Clarification resolution, broader replan,
model/tool execution, automatic check adapters, CLI workflow commands, durable
workflow/ledger restore and live crash recovery are not implemented here. Do not
reset a task/controller on model request to evade its budget. No live inference
was run. Next work is the gated host adapter/CLI and persistence integration;
P10 and workflow-specific P12 remain IN_PROGRESS.

## P10/P12 durable workflow checkpoints — MOCK_VERIFIED

WorkflowController now has explicit checkpoint export/restore and optional trusted
persistence binding through `SessionStore.workflow`. Unattached controllers remain
in-memory and perform no I/O. The context holds the existing Linux session writer
lock for its entire lifetime and persists each transition before returning it to
the host. In particular, the reserved attempt is durable before the inert dispatch
descriptor is returned. Storage errors propagate; a host must stop instead of
dispatching after a failed write. Exiting the context closes that controller's
attachment; use a newly restored controller rather than continuing a stale object.

Session schema v3 extends v2 with a nested schema-v1 workflow checkpoint. It stores
the validated plan, original task/step IDs, attempts/cycles, active attempt, accepted
evidence, criterion coverage, user choices and budget-extension ledger. Original
model baseline and account fingerprint are retained. Approval grants, pending model
requests, approval/pause tokens, raw account ID and tool permissions are excluded.
Evidence result derivation is shared between newly observed and persisted checks.

Checkpoint validation replays ledger ordering, cycle extensions and attempt counters,
checks unique identities and exact field sets, matches evidence to the correct
attempt/check and rejects inconsistent result/exit-code pairs. A budget extension
requires its preceding explicit continue choice. Session summary fields must match
the workflow; deletion receipts may override the top-level deletion/pause state.
Save rejects task/step/baseline replacement, criterion/structure changes, ledger
truncation, active-attempt loss, status rollback and removal of existing evidence.
This detects corrupt/inconsistent state; it is not cryptographic protection from
the same local user deliberately rewriting an entire state file.

Restore requires a fresh allowed quota snapshot, matching account and a still
supported original baseline. Current catalog/role policy is supplied by the host.
Temporary model grants are rebuilt empty. Nonterminal workflows restore paused
with fresh tokens, not dispatches. Running attempts retain their IDs and consumed
slots and require a native terminal event before continuing. Completed attempts
can continue CHECKING after an explicit choice, without another model turn.
Exhausted budgets remain exhausted until an explicit new-cycle choice. Cached
DONE restores UNVERIFIED and preserves its historical evidence/coverage; the host
must inspect current files/processes and reassess evidence before asserting DONE.
FAILED/CLARIFYING retain their phase. No pending model/tool action is replayed.

V1/v2 records remain readable and unchanged by read/list operations. Only explicit
workflow attachment upgrades a bound v2 record to v3. Unbound/deleting sessions,
wrong accounts, unsafe quota and unknown existing manual outcomes cannot attach.
Manual LiveChatConnection resume rejects workflow records before any thread RPC,
so it cannot discard counters by treating them as ordinary chat. Confirmed deletion
of workflow metadata still follows the existing preview/token/remote-receipt flow.

Offline validation (2026-11-17):

- `python3 -m unittest discover -s tests -p test_workflow_persistence.py -v`: 25 passed.
- `python3 -m unittest discover -s tests -q`: 224 passed.
- `python3 -m py_compile modelmate.py doctor.py verify.py`: passed.
- `git diff --check`: passed.

Tests include actual subprocess death both after reserving an attempt and after
recording an observed synthetic check result; both restore the original counters.
Other checks cover exhausted/extended cycles, user choices, pending approval/token
expiry, partial/out-of-order checks, multi-step/source evidence, terminal phases,
no raw account storage, unknown quota/account/catalog, corrupt/unsupported schema,
metadata/counter/evidence tampering, task/ledger/status rollback, disk failure before
dispatch, failed extension save, lock ownership, closed attachments, legacy reads,
manual-resume refusal and confirmed deletion. All fixtures/account IDs are synthetic.

Limits: this is the persistence/host API milestone, not a user-facing workflow CLI
or live executor. The existing trusted-callback contract still applies: metadata
cannot establish whether a host's manual/source finding or exit code is truthful,
or whether files have changed since evidence was collected. Native thread/turn
reconciliation must be wired by the future host adapter. These process-death tests
do not verify native Codex crash recovery or hardware power loss. Existing atomic
replace/fsync limits remain. Full checkpoints share the session's 1 MiB cap and
allow at most 4,096 ledger events; oversize fails without dropping history. No
credentials, transcript, network call or live inference was added. P10/P12 remain
IN_PROGRESS; next work is the explicit workflow UI/controller host integration,
with execution/check adapters and their permission gates still separate.

## P08/P10 workflow host UI — MOCK_VERIFIED

ChatShell and run_chat now accept an explicit WorkflowController and optional
trusted workflow_action callback. This is a host API milestone: the ordinary CLI
and `--live` paths remain manual, and no workflow loading flag is introduced.
Passing a native backend or legacy manual send callback alongside a workflow is
rejected, so existing native execution is not implicitly enabled for workflows.

The UI renders the plan, current step, cycle/attempt budget, planned model/effort,
active requested selection, per-check results and recorded criterion coverage.
Requested/planned models are not described as backend dispatch telemetry. All
display text uses the existing terminal-control filter. Ordinary text is not
forwarded into a classifier or executor while this prototype workflow UI is bound.

Host/UI contract:

- `/workflow` and `/status` read the bound controller without starting work.
- `/next` is allowed only in READY and sends `{action: next, task_id}` to the
  trusted callback. Without a host, no attempt is reserved. The host must obtain
  current quota/catalog/bindings and use the controller's request_attempt before
  any future dispatch. The UI ignores callback return values as completion claims.
- `/approve`, `/decline` and `/pause` route exact tokens to the current model gate;
  `/continue`, `/revise` and `/pause` route only matching workflow pause tokens.
  Approval and continuation never invoke next automatically. No tool grant is
  created. Revision requests pause for the host; they do not rewrite the plan.
- `/mode` uses a controller method that invalidates old grants/tokens, preserves
  budgets and persists the change when the controller is durably attached.
  Active/finished attempts cannot change mode. Unsupported manual session/model
  commands do not fall through to an unrelated backend.
- `/cancel`, Ctrl+C, `/exit` and EOF pause pending choices or request host cancellation
  for a running attempt. Host cancellation is attempted before persisting a running
  pause, so a storage failure cannot prevent the interrupt request. An acknowledgement
  alone never clears active state. A five-second unconfirmed-stop deadline exits
  with unknown outcome; the controller retains its active attempt/budget.
- A trusted host may signal `{type: workflow_changed, task_id}` after mutating its
  controller from a real terminal/check event. The signal carries no state or evidence
  fields. Foreign IDs, extra fields, replacement plans, legacy completed/stopped and
  tool approval events are rejected in workflow UI mode. Model text is display data.

Offline validation (2026-11-17):

- `python3 -m unittest discover -s tests -p test_workflow_ui.py -v`: 17 passed.
- `python3 -m unittest discover -s tests -q`: 241 passed.
- `python3 -m py_compile modelmate.py doctor.py verify.py`: passed.
- `git diff --check`: passed.

Checks cover plan/status without execution, missing-host refusal, explicit model
approval, stale tokens on mode change, correction-limit choices and retained cycles,
no auto-next after approval, revision/pause, EOF during a synthetic running attempt,
terminal confirmation versus acknowledgement, unconfirmed timeout, cancellation on
storage failure, spoofed completion/foreign events, inert callback return values,
read-only permissions, refused native/manual mixing, terminal text filtering and
persisted UI choices. An actual synthetic subprocess runs the selector/EOF/event
path; no real Codex or inference is used.

Limits: callbacks and controller mutation remain trusted in-process APIs. This is
not a sandbox for arbitrary Python callbacks. Hosts must correctly report native
events, perform fresh preflight checks, bind actual check evidence and handle
disconnect/interrupt outcomes. No native workflow executor, check adapter, classifier,
clarification input, broad replan editor, workflow CLI loading/resume entry point or
automatic multi-step loop is added. P08/P10/P12 remain IN_PROGRESS. Next work is
the gated host/execution and explicit entry-point integration; source/mock evidence
must not be presented as live workflow verification.

## P10 workflow host and executor observations — MOCK_VERIFIED

Added WorkflowHost as the trusted adapter between WorkflowController, the injected
UI and transport callbacks. It has no built-in native transport, subprocess runner,
tool approval handler or CLI entry point. Existing native/manual mixing guards
remain in place. All checks below used synthetic callbacks/protocols, not Codex.

Dispatch contract:

- A host preflight callback returns the current quota snapshot/timestamp, catalog
  and reviewed role bindings. The controller's quota/account/model gates still run
  before a slot is consumed. Preflight failure pauses without dispatch. Ultra
  delegation remains unsupported and consumes no slot.
- The dispatch callback receives a defensive copy of the inert descriptor only
  after the controller's durable attempt checkpoint succeeds. It returns exactly
  a thread/turn identity before delivering events. Reentrant events must be queued
  by the transport; reused/invalid bindings and unknown start outcomes fail closed.
- Cancel invokes the trusted interrupt callback at most once for the known binding.
  An acknowledgement does not finish the attempt. Bound-turn timeout, disconnect
  or malformed protocol pauses with unknown outcome and never replays dispatch.
- A trusted recovery adapter can reconcile inspected identity/terminal status with
  the original active attempt, retaining its consumed slot. A completed cached
  attempt can continue checks without another model turn. Native inspection,
  current-file reassessment and account/source authenticity are host obligations;
  the adapter does not infer identity from model text or automatically reconnect.

Evidence contract:

- `configure_check` registers an exact host-reviewed command and absolute cwd for
  an existing test/lint criterion before the attempt. It grants no tool permission
  and does not run a command. The producer must enforce native sandbox/approval
  policy independently; current workflow approval requests interrupt/refuse rather
  than receiving accept.
- `observe_native` accepts only observations from the trusted executor channel.
  Matching thread/turn, command item identity, observed start, command and cwd are
  required. Unrelated successful commands and assistant text fill no checks.
- Identical duplicate completions are idempotent. Changed command/cwd/type, missing
  starts, conflicting results, repeated check invocations within one attempt and
  contradictory terminal events pause rather than silently accepting a later pass.
  Native tools may already have started before observation; this is not a no-tools
  sandbox or proof that all internal tool loops are bounded.
- `/check` records matched observations only after a confirmed completed turn, then
  evaluates that attempt. Declined/missing exit codes remain unknown; nonzero
  observed exits fail. Raw stdout/stderr, commands and cwd are not copied into
  evidence. Missing manual/source adapters leave UNVERIFIED rather than inventing
  findings. Task DONE still requires an explicit trusted criterion-coverage check.
- Transport bindings, approved check specifications and unrecorded observations
  are process-local. Recovery does not reuse another attempt's cached observations.
  Durable native thread/turn binding integration remains future work.

`run_chat(..., executor_stream=...)` multiplexes this channel only for an explicitly
bound WorkflowHost; it is separate from display-only model text and UI change
signals. The host drives same-task UI updates on the owning loop and has a bounded
turn deadline. Parse/EOF failures invalidate the host and request interruption.
No backend/model event can directly declare workflow DONE or grant tool access.

Offline validation (2026-11-17):

- `python3 -m unittest discover -s tests -p test_workflow_host.py -v`: 25 passed.
- `python3 -m unittest discover -s tests -q`: 266 passed.
- `python3 -m py_compile modelmate.py doctor.py verify.py`: passed.
- `git diff --check`: passed.

Checks cover exact observations versus unrelated commands, foreign thread/turn IDs,
missing starts, changed metadata/types, duplicate/conflicting results, declined
checks, correction limits, explicit model approval/next, unknown start recovery,
cancel acknowledgement, timeout/disconnect without replay, unsupported tool approval,
stale binding/check-cache isolation, reentrant events, ultra refusal, fresh preflight,
and a durable checkpoint before the dispatch callback. Real synthetic subprocesses
exercise separate executor-pipe events, UI `/check`, EOF and invalid JSON. Raw
private-output markers never become evidence or Terminal output.

Limits: this is still a trusted in-process API and observation checker, not a
security boundary against arbitrary Python callbacks or dishonest producers.
Exact command matching does not prove the chosen command meaningfully tests a
criterion; the host must review specifications and source observations. Transport
callbacks must bound their own start RPC timeouts, enforce permissions and queue
events until binding. No model inference, live workflow or private-web gate was
run or marked passed. Native transport, durable native bindings, workflow loading
entry point, full tool approval/check adapters and classifier remain pending.
P08/P09/P10/P12 remain IN_PROGRESS.

### Local session/workflow inspection (2026-11-17, uncommitted working tree)

- `python3 -m unittest discover -s tests -p test_local_inspection.py -v`: 7 offline tests.
- ตรวจ missing store ไม่สร้าง directory; read-only mutations ไม่สร้าง lock;
  checkpoint bytes/mtime ไม่เปลี่ยน; project isolation, symlink/corrupt metadata
  ปฏิเสธโดยไม่แก้ไฟล์; CLI ใช้ได้เมื่อ PATH ไม่มี Codex และปฏิเสธ option ที่ชนกัน
- RUNNING แสดงผลปัจจุบัน unknown; DONE แสดงว่าเป็นผลเก่า ไม่คืน grants/token
  ไม่ restore controller ไม่ทดสอบ live inference หรือ native workflow execution

Publication preflight (2026-11-18): full offline suite 273/273 passed;
`python3 -m py_compile modelmate.py doctor.py verify.py` and
`git diff --check` passed. No live inference was run.

### PR #5 recovery evidence fix (2026-11-18)

Restored active and accepted step evidence is now stale in memory. The controller
blocks attempt evaluation and task completion until the trusted host explicitly
revalidates each saved check against a known matching current result. Terminal
reconciliation alone does not clear this requirement. Confirmations do not survive
another restore; persisted evidence/ledger are retained unchanged. Mismatched or
unknown results remain blocked; no implicit tool execution or model retry occurs.
Regression coverage checks partial-check recovery, terminal-only reconciliation,
restored DONE, rejected mismatches, and revalidation expiry after another restore.

Validation: 91 targeted workflow tests and 274/274 full offline tests passed.
Runtime/doctor/verifier compilation and `git diff --check` passed. No live inference.

### Experimental native workflow transport (2026-11-18)

- Schema inspection: installed `codex app-server generate-json-schema --out ...`
  ran locally without inference. Inspected thread/start response permission fields,
  turn/start response and turn/interrupt parameters; generated files remain outside repo.
- `tests/test_native_workflow.py`: 10 synthetic subprocess tests cover queued events
  before start response, exact requested model/effort, same-thread corrections,
  auth/quota/permission failures, approval decline+pause, missing turn ID/disconnect,
  duplicate dispatch rejection, unsupported recovery, bounded event queue and
  native stdout/stderr multiplexing through the real Terminal loop.
- Public native workflow CLI remains disabled. Host API uses ephemeral threads;
  durable native workflow recovery and approval acceptance are not implemented.
  No no-tools classifier or private-web boundary is claimed. Requested models are
  not backend dispatch telemetry. No live inference or quota was consumed.

Validation: 10 targeted native workflow tests and 284/284 full offline tests
passed; runtime/doctor/verifier compilation and `git diff --check` passed.
