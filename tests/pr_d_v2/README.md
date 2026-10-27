# PR D v2 — characterization tests

## Purpose
Record reproducible, non-destructive evidence of potential contract mismatches before proposing implementation changes.

## Safety boundary
- Static tests inspect source. Runtime fault-injection tests execute the engine's `main()` control flow against a deterministic fake Supabase client.
- No test connects to Supabase, uses production credentials, writes to a real database, dispatches the production batch workflow, or executes real H003/H005 hypotheses.
- H003 and H005 remain unauthorized for real execution (`authorized: false`).
- A passing test means the documented risk pattern was observed in the tested environment, not that implementation complies with PR D v2.
- The fake client demonstrates control-flow/persistence ordering only. It does not prove PostgreSQL/Supabase transaction or concurrency semantics.

## Run

    python -m unittest discover -s tests/pr_d_v2 -v

## Runtime fault injection currently covered
1. An injected evidence-insert failure after baseline insertion leaves a baseline row in the fake store and no evidence row; current engine exits 1.
2. A schema-gate `INVALID` result exits 0 without persistence.
3. An injected measurement exception exits 1.

## Limitations / remaining tests
1. Contractual exit-code 2 for structural batch failures and unknown exit-code normalization are not implemented or runtime-verified.
2. Real transactional semantics require an isolated disposable database or an explicitly transactional storage adapter; the fake client cannot prove production atomicity.
3. Idempotency and concurrent baseline conflicts need deterministic fault injection and repeatable barriers.
4. Manifest missing/corrupt cases need the versioned manifest contract wired into a harness.
5. CI validates only this isolated test suite. It is not an acceptance run of the production engine.

Do not interpret this characterization suite as acceptance evidence for implementation.
