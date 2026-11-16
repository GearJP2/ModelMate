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
