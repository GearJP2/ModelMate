# Verification evidence

## P00 — IN_PROGRESS

Offline checks:

- `python3 -m unittest discover -s tests -q`: 15 tests passed.
- `python3 -m py_compile doctor.py verify.py`: passed.
- `git diff --check`: passed.

Changes verified with regression tests:

- Missing, malformed, exhausted or boolean quota windows cannot authorize a turn.
- Approval requests from a stale turn, without a turn ID, or with malformed params
  are not answered.
- Existing protocol, pagination, recall and denial tests remain passing.

Additional corrections awaiting broader lifecycle regression coverage:

- Turn deadline begins before turn/start RPC rather than after its response.
- Scratch directory is retained if interruption cannot be confirmed; interruption
  failure does not replace the original verification exception.
- Report distinguishes requested models from unknown reported models and does not
  claim actual model switching merely because context recall succeeded.

Remaining P00 work: EOF/data interleaving, partial startup with unknown turn ID,
account identity across quota reads, malformed payload coverage and interruption
confirmation/cleanup failure tests. Do not advance P00 to DONE yet.

Live inference: NOT RUN. G1–G4 remain unverified. No account identifiers or raw
account reports are recorded here.
