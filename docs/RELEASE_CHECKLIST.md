# Release evidence checklist

ModelMate remains an experimental CLI. Each release gate needs evidence
for the particular path, client version and platform being shipped. See
[VERIFICATION.md](VERIFICATION.md) for the dated test records.

| Gate | Evidence available | Remaining |
| --- | --- | --- |
| G1 account and dispatch | User-run workflow catalogue and requested-model paths, context recall and scoped resume | Check the metadata-only catalog preview live. Reported dispatch telemetry is incomplete. |
| G2 permissions and lifecycle | Scoped live native workflow denial, interruption, metadata inspection, recheck recovery and scoped deletion | Verify retained recheck STOP, varied permission failures and actual disconnect/recovery. |
| G3 private search | Offline dedicated Wikipedia search with explicit confirmation and source links | Live provider smoke and broader-web integration. Hosted search remains disabled in work threads. |
| G4 quota and billing | Offline fail-closed paths and live telemetry with observed account windows | Live exhausted/unknown admission paths and version-specific billing guarantees. |
| G5 evaluation | Scored C1, C3 and the two-step economy pilot | Freeze and run the remaining paired tasks. Establish a defensible quota signal before estimating savings. |
| R13 installation | Standalone runtime on WSL2 with a clean scratch path containing spaces | Independent clean installation on a second environment and release packaging after required gates pass. |

## Run without subscription turns

- Run the full offline suite and compile entry points.
- Install the runtime into a fresh user-local scratch directory and verify help,
  offline preview, and missing-Codex behavior on the target platform.
- From a normal authenticated Terminal, run the catalog preview described in
  [USAGE.md](USAGE.md).
- For the Wikipedia smoke, use a public test query, cancel the first preview,
  and confirm a second. Check the destination and cited links in the result.

## Live checks with explicit opt-in

Keep release evidence sanitized. Record the runtime and Codex version plus
the specific result, avoiding account identifiers, session logs and quota
screenshots in the repository. Use the known scoped probes before running
any new permission or recovery scenario. Follow the frozen
[evaluation protocol](EVALUATION.md) for the remaining paired cases.
