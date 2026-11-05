# PR D v2 — characterization tests

## Purpose
Record reproducible, non-destructive evidence of potential contract mismatches before proposing implementation changes.

## Safety boundary
- Static source-inspection tests only; they do not execute the lab engine.
- No Supabase connection, writes, GitHub Actions dispatch, or real H003/H005 execution.
- H003 and H005 remain unauthorized for real execution (`authorized: false`).
- A passing test means the risk pattern was detected, not that implementation complies with PR D v2.

## Run

    python -m unittest discover -s tests/pr_d_v2 -v

## Limitations / next required tests
1. Runtime subprocess tests must verify exit codes 0/1/2 and unknown exceptions using a fake client.
2. Transactional semantics require an isolated fake storage adapter or disposable local Postgres; source inspection cannot prove atomicity.
3. Idempotency and concurrent baseline conflicts need deterministic fault injection and repeatable barriers.
4. Manifest missing/corrupt cases need the versioned manifest contract wired into a harness.
5. Test workflow behavior in disposable CI without production secrets.

Do not interpret this characterization suite as acceptance evidence for implementation.
