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
