# PR D v2 — Controlled E2E readiness plan

## Current boundary

This change is a safety prerequisite, not proof of end-to-end operation. The workflow and the engine itself must both reject execution while `docs/manifest.json` remains `execution_status: "fixture"`. The engine gate runs before reading database credentials or importing/creating the Supabase client. Supabase secrets are scoped to the workflow step that invokes the engine. No production data is touched by these checks.

## Evidence already available

- The atomic RPC migration and execute grants are present in the repository and were previously checked directly in Supabase.
- PostgreSQL integration tests exercise transaction rollback, idempotent replay, concurrent duplicate requests, generation isolation, baseline-race rejection, migration preflight, and execute grants.
- The engine-path tests currently stub the Supabase client. They prove the engine selects the RPC path and fails closed when RPC invocation errors, but they are not an E2E test of the real engine against a real PostgREST/RPC endpoint.
- The legacy `lab_run.yml` previously accepted an arbitrary workflow input and invoked the engine without checking the frozen manifest. This PR adds Gate 0 before dependency installation and engine invocation.

## Disposable Supabase HTTP RPC workflow

The PR now includes `.github/workflows/pr-d-supabase-http-e2e.yml`. It creates a temporary Supabase CLI project inside the GitHub runner, with no project link and no repository/production secrets; applies the atomic RPC migration to a fresh fixture schema; and tests the real local PostgREST endpoint for baseline+evidence persistence, idempotent replay, rollback after an injected evidence failure, and denial of the anon key. The test code also fails closed unless both API and database hosts are localhost.

This workflow is an HTTP/RPC integration test against a disposable Supabase stack. It is **not** evidence that the real `lab_engine.py` completed a run: the checked-in manifest remains `fixture`, and the engine must continue to reject it. Full engine-to-RPC E2E remains blocked until a separately reviewed test-only execution design can exercise the engine without changing the checked-in manifest to `approved` or touching production.

## E2E acceptance plan — not yet executed

**Current infrastructure limitation:** the repository has SQL migrations and PostgreSQL-only integration tests, but no checked-in `supabase/config.toml` was found on the PR branch. The existing PostgreSQL service verifies the database function; it does not emulate Supabase Auth/PostgREST or prove the full engine-to-RPC HTTP path. Do not label that job as E2E.

Before implementing a runnable E2E workflow, provision and validate a disposable local Supabase stack in CI (CLI + Docker), or document a separately isolated staging project. The test workflow must fail closed unless it can prove the endpoint is local/disposable and has no production secrets. Then:

1. Use a disposable local Supabase stack, with no production URL or key available to the job.
2. Seed a clearly namespaced fixture dataset and one fixture hypothesis whose ID is frozen in a test-only manifest.
3. Run the real GitHub Actions workflow and `labs/lab_engine.py` against that isolated environment.
4. Verify through an independent read that the RPC creates exactly one baseline and one evidence record, both tied to the fixture ID and generation.
5. Retry the same logical run and verify the same evidence ID is returned and row counts do not increase.
6. Inject a failure after baseline insertion and verify the transaction leaves neither baseline nor evidence behind.
7. Confirm both the workflow and direct engine invocation fail before database client creation when the manifest is `fixture`, corrupt, or the requested hypothesis ID is not in the frozen manifest.
8. Capture the workflow run URL, commit SHA, sanitized logs, before/after row counts, and SQL assertions as the audit artifact.

## Security hardening in this PR

- `labs/lab_engine.py` now validates `docs/manifest.json` itself and checks explicit approval plus frozen-ID membership before reading database credentials or importing the Supabase client.
- `lab_run.yml` and `lab_batch.yml` expose Supabase secrets only to the step that invokes the engine, not to Gate 0 or dependency installation.
- CI includes a direct engine invocation with the Supabase environment variables removed; it must exit 2 because the checked-in manifest is a fixture.

## Hard stops

- Do not change `execution_status: "fixture"` to `approved` for this PR.
- Do not run a dummy hypothesis against the existing production Supabase project: the RPC persists records and the current schema has no approved cleanup contract for test rows.
- Do not expose or print `SUPABASE_KEY`.
- Do not claim E2E success from unit tests, PostgreSQL-only RPC tests, or mocked engine tests.
- Do not manually insert a guessed version such as `004` into `supabase_migrations.schema_migrations`. Reconcile migration history using the project's actual migration tooling and a reviewed procedure.

## Exit criteria before any production execution

The isolated E2E must pass all assertions, a human audit must review the artifact, the migration-history discrepancy must be reconciled safely, and the manifest's approval transition must be separately reviewed and explicitly authorized.
