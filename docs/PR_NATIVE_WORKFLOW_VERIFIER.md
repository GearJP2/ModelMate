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

Validation: eight new offline test methods with fake subprocess App Servers; full
suite, compilation and diff checks recorded in docs/VERIFICATION.md.

Limits: no live inference performed during implementation. Disconnect is a local
guard, not network-drop recovery. This does not prove all tool paths or actual model
dispatch and does not enable public workflow CLI/auto routing. No merge requested.
