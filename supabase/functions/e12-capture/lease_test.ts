import { claimWorkerLease, releaseWorkerLease, renewWorkerLease } from "./lease.ts";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

const URL = "https://project.example.supabase.co";
const KEY = "sb_secret_test_only_not_real";
const RUN = "11111111-2222-4333-8444-555555555555";
const LEASE = { runId: RUN, fencingToken: "9007199254740993", leaseExpiresAt: "2026-11-12T23:00:00Z" };

Deno.test("lease claim preserves bigint fencing tokens without Number coercion", async () => {
  let seenBody: Record<string, unknown> | undefined;
  const fetchImpl: typeof fetch = async (input, init) => {
    assert(String(input).endsWith("/rpc/pr_d_claim_e12_worker_lease"), "claim RPC name must be exact");
    const headers = new Headers(init?.headers);
    assert(headers.get("apikey") === KEY, "service key must use apikey header");
    assert(headers.get("authorization") === null, "do not duplicate service key into Authorization");
    seenBody = JSON.parse(String(init?.body));
    return new Response(JSON.stringify([{
      acquired: true,
      fencing_token: "9007199254740993",
      lease_expires_at: "2026-11-12T23:00:00Z",
    }]), { status: 200 });
  };
  const result = await claimWorkerLease(URL, KEY, RUN, 90, fetchImpl);
  assert(result.acquired, "lease should be acquired");
  assert(result.lease.fencingToken === "9007199254740993", "token must remain exact beyond 2^53");
  assert(result.lease.runId === RUN, "run id must be bound to lease");
  assert(seenBody?.p_run_id === RUN && seenBody?.p_ttl_seconds === 90, "claim args must be exact");
});

Deno.test("lease contention returns a non-acquired result without inventing an owner", async () => {
  const result = await claimWorkerLease(URL, KEY, RUN, 90, () => Promise.resolve(
    new Response(JSON.stringify([{ acquired: false, fencing_token: null, lease_expires_at: null }]), { status: 200 }),
  ));
  assert(!result.acquired, "active lease must not be stolen");
});

Deno.test("lease renew and release bind both owner and fencing token", async () => {
  const calls: Array<{ name: string; body: Record<string, unknown> }> = [];
  const fetchImpl: typeof fetch = async (input, init) => {
    const name = String(input).split("/").pop() ?? "";
    calls.push({ name, body: JSON.parse(String(init?.body)) });
    return new Response("true", { status: 200 });
  };
  assert(await renewWorkerLease(URL, KEY, LEASE, 90, fetchImpl), "valid owner should renew");
  assert(await releaseWorkerLease(URL, KEY, LEASE, fetchImpl), "valid owner should release");
  assert(calls.length === 2, "renew and release must each call one RPC");
  for (const call of calls) {
    assert(call.body.p_run_id === RUN, "owner id must be bound");
    assert(call.body.p_fencing_token === "9007199254740993", "fencing token must remain exact");
  }
});

Deno.test("lease helpers reject invalid UUIDs, TTLs, malformed responses and HTTP errors", async () => {
  let invalidRunRejected = false;
  try { await claimWorkerLease(URL, KEY, "not-a-uuid", 90, fetch); } catch { invalidRunRejected = true; }
  assert(invalidRunRejected, "invalid run ID must reject before network access");

  let invalidTtlRejected = false;
  try { await claimWorkerLease(URL, KEY, RUN, 301, fetch); } catch { invalidTtlRejected = true; }
  assert(invalidTtlRejected, "TTL above maximum must reject before network access");

  let malformedRejected = false;
  try {
    await claimWorkerLease(URL, KEY, RUN, 90, () => Promise.resolve(new Response("{}", { status: 200 })));
  } catch { malformedRejected = true; }
  assert(malformedRejected, "malformed claim response must fail closed");

  let httpRejected = false;
  try {
    await renewWorkerLease(URL, KEY, LEASE, 90, () => Promise.resolve(new Response("", { status: 403 })));
  } catch { httpRejected = true; }
  assert(httpRejected, "lease renewal HTTP failure must fail closed");
});
