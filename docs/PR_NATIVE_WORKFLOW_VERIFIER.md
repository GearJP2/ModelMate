Title: Add opt-in native workflow verification harness

Native workflow transport had offline integration coverage but no reproducible live
probe. Add `python3 verify.py --run-live --probe-workflow MODEL` using the existing
transport, controller and chat display path.

The probe uses up to four synthetic turns in a private scratch directory: displayed
ACK and context recall, denied sentinel write, and cancellation. It checks the local
disconnect guard without another dispatch. Missing approvals and cancellation races
are unverified; failures/unknown outcomes never trigger retries. Incomplete runs
retain scratch for inspection. Reports include version hashes and no raw responses
or account/thread IDs. No inference runs without explicit --run-live.

Validation: ten new offline test methods with fake subprocess App Servers; full
suite, compilation and diff checks recorded in docs/VERIFICATION.md.

User-supplied live probe at commit 326a819 reported all six checks passed; both
runtime/verifier hashes match local files. See docs/VERIFICATION.md for scope and
provenance. No independent agent-run live inference was performed.

Limits: disconnect is a local
guard, not network-drop recovery. This does not prove all tool paths or actual model
dispatch and does not enable public workflow CLI/auto routing. No merge requested.

Review fixes: compare actual ChatShell output instead of text payloads; test the
local disconnect guard from READY with preflight/dispatch tripwires. New tests reject
a no-op disconnect and dropped UI text. Earlier live answerDisplay/disconnectGuard
claims are superseded pending a run with the fixed verifier. No live rerun performed.
