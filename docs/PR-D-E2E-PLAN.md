# PR D v2 — Controlled E2E readiness plan

## Current boundary

This change is a safety prerequisite, not proof of end-to-end operation. It closes the legacy single-hypothesis workflow while `docs/manifest.json` remains `execution_status: "fixture"`. It does not invoke the engine, call Supabase, or mutate production data.

## Evidence already available

- The atomic RPC migration and execute grants are present in the repository and were previously checked directly in Supabase.
- PostgreSQL integration tests exercise transaction rollback, idempotent replay, concurrent duplicate requests, generation isolation, baseline-race rejection, migration preflight, and execute grants.
- The engine-path tests currently stub the Supabase client. They prove the engine selects the RPC path and fails closed when RPC invocation errors, but they are not an E2E test of the real engine against a real PostgREST/RPC endpoint.
- The legacy `lab_run.yml` previously accepted an arbitrary workflow input and invoked the engine without checking the frozen manifest. This PR adds Gate 0 before dependency installation and engine invocation.

## E2E acceptance plan — not yet executed

A separate, explicitly authorized test environment must be provisioned before an end-to-end run:

1. Use an isolated Supabase project or disposable local Supabase stack, with no production URL or key available to the job.
2. Seed a clearly namespaced fixture dataset and one fixture hypothesis whose ID is frozen in a test-only manifest.
3. Run the real GitHub Actions workflow and `labs/lab_engine.py` against that isolated environment.
4. Verify through an independent read that the RPC creates exactly one baseline and one evidence record, both tied to the fixture ID and generation.
5. Retry the same logical run and verify the same evidence ID is returned and row counts do not increase.
6. Inject a failure after baseline insertion and verify the transaction leaves neither baseline nor evidence behind.
7. Confirm the workflow fails before engine invocation when the manifest is `fixture`, corrupt, or the requested hypothesis ID is not in the frozen manifest.
8. Capture the workflow run URL, commit SHA, sanitized logs, before/after row counts, and SQL assertions as the audit artifact.

## Hard stops

- Do not change `execution_status: "fixture"` to `approved` for this PR.
- Do not run a dummy hypothesis against the existing production Supabase project: the RPC persists records and the current schema has no approved cleanup contract for test rows.
- Do not expose or print `SUPABASE_KEY`.
- Do not claim E2E success from unit tests, PostgreSQL-only RPC tests, or mocked engine tests.
- Do not manually insert a guessed version such as `004` into `supabase_migrations.schema_migrations`. Reconcile migration history using the project's actual migration tooling and a reviewed procedure.

## Exit criteria before any production execution

The isolated E2E must pass all assertions, a human audit must review the artifact, the migration-history discrepancy must be reconciled safely, and the manifest's approval transition must be separately reviewed and explicitly authorized.
