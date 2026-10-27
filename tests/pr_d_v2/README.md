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

## Contract coverage matrix (current engine characterization, not acceptance)

| Requirement / scenario | Test evidence | Current observation | Verdict |
|---|---|---|---|
| 15.2 invalid schema gate includes explicit cause | Runtime fake-client test | Exit 0; status INVALID; failure_reason and reason are emitted; no persistence | CONSISTENT for this gate |
| 15.3 evidence insert fails after baseline insert | Runtime fake-client test | Baseline remains in fake store; evidence absent; exit 1 | VIOLATION demonstrated in fake-store flow; real DB semantics unverified |
| 15.4 unclassified measurement RuntimeError | Runtime fake-client test | Exit 1 | AMBIGUOUS / likely mismatch with unknown-error default 2; classification must be defined by contract |
| 15.4 malformed window | Runtime early-failure test | Exit 1 | VIOLATION: structural input currently does not exit 2 |
| 15.4 structural code 2 | Static characterization | No explicit sys.exit(2) in current engine | VIOLATION: code 2 not implemented |
| 15.4 batch abort on nonzero engine exit | Static workflow characterization | Workflow contains an error-absorbing fallback | VIOLATION: batch can continue after engine failure |
| 15.1/15.5 frozen manifest | Static characterization | No manifest verification in current batch workflow | VIOLATION: mechanism absent |
| Manifest absent / corrupt | Not runtime-testable against current engine | No manifest gate or parser is wired into the engine/workflow | NOT VERIFIED; add executable tests with the implementation harness |
| Valid manifest + missing hypothesis YAML | Runtime characterization of current behavior only | Missing YAML currently exits 1; no manifest semantics or p=1.0 handling | VIOLATION of required behavior / full manifest case NOT VERIFIED |
| 15.3 PostgreSQL transaction rollback | Not tested | Fake client only | NOT VERIFIED |
| Idempotency / concurrency | Not tested | No real DB or deterministic concurrency harness | NOT VERIFIED |

### Interpretation rules
- These are characterization tests: they deliberately record current behavior, including behavior that violates the contract. A green CI run does not mean PR D v2 is satisfied.
- The missing/corrupt manifest cases cannot honestly be called runtime-tested until the versioned manifest gate exists. Adding a test-only imitation would test the imitation, not the engine.
- PostgreSQL atomicity, idempotency, and concurrency remain blocked on an explicitly disposable PostgreSQL/Supabase test environment. No production database is used.
- The malformed-window and unclassified-exception tests document current exit codes; they do not change the engine or claim that those codes are correct.
- Implementation remains a separate phase and must not be inferred from this PR.
