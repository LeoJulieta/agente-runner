export type WorkerLease = {
  runId: string;
  fencingToken: string;
  leaseExpiresAt: string;
};

export type WorkerLeaseClaim =
  | { acquired: true; lease: WorkerLease }
  | { acquired: false };

type LeaseRow = {
  acquired: unknown;
  fencing_token: unknown;
  lease_expires_at: unknown;
};

function parseLeaseRow(value: unknown): WorkerLeaseClaim {
  if (!Array.isArray(value) || value.length !== 1) {
    throw new Error("supabase_worker_lease_response_invalid");
  }
  const row = value[0] as LeaseRow | null;
  if (!row || typeof row !== "object" || typeof row.acquired !== "boolean") {
    throw new Error("supabase_worker_lease_response_invalid");
  }
  if (!row.acquired) return { acquired: false };
  const token = typeof row.fencing_token === "string"
    ? row.fencing_token
    : typeof row.fencing_token === "number" && Number.isSafeInteger(row.fencing_token)
    ? String(row.fencing_token)
    : "";
  if (!/^\d+$/.test(token) || token === "0" || typeof row.lease_expires_at !== "string") {
    throw new Error("supabase_worker_lease_fields_invalid");
  }
  if (!Number.isFinite(Date.parse(row.lease_expires_at))) {
    throw new Error("supabase_worker_lease_expiry_invalid");
  }
  return {
    acquired: true,
    lease: { runId: "", fencingToken: token, leaseExpiresAt: row.lease_expires_at },
  };
}

async function callLeaseRpc(
  supabaseUrl: string,
  serviceRoleKey: string,
  rpcName: string,
  body: Record<string, unknown>,
  fetchImpl: typeof fetch,
): Promise<unknown> {
  const baseUrl = supabaseUrl.replace(/\/+$/, "");
  const response = await fetchImpl(baseUrl + "/rest/v1/rpc/" + rpcName, {
    method: "POST",
    headers: {
      apikey: serviceRoleKey,
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(15_000),
  });
  if (!response.ok) throw new Error("supabase_" + rpcName + "_http_" + response.status);
  return await response.json();
}

export async function claimWorkerLease(
  supabaseUrl: string,
  serviceRoleKey: string,
  runId: string,
  ttlSeconds: number,
  fetchImpl: typeof fetch,
): Promise<WorkerLeaseClaim> {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(runId)) {
    throw new Error("worker_run_id_invalid");
  }
  if (!Number.isInteger(ttlSeconds) || ttlSeconds < 30 || ttlSeconds > 300) {
    throw new Error("worker_lease_ttl_invalid");
  }
  const result = parseLeaseRow(await callLeaseRpc(
    supabaseUrl,
    serviceRoleKey,
    "pr_d_claim_e12_worker_lease",
    { p_run_id: runId, p_ttl_seconds: ttlSeconds },
    fetchImpl,
  ));
  return result.acquired
    ? { acquired: true, lease: { ...result.lease, runId } }
    : result;
}

export async function renewWorkerLease(
  supabaseUrl: string,
  serviceRoleKey: string,
  lease: WorkerLease,
  ttlSeconds: number,
  fetchImpl: typeof fetch,
): Promise<boolean> {
  if (!Number.isInteger(ttlSeconds) || ttlSeconds < 30 || ttlSeconds > 300) {
    throw new Error("worker_lease_ttl_invalid");
  }
  const result = await callLeaseRpc(
    supabaseUrl,
    serviceRoleKey,
    "pr_d_renew_e12_worker_lease",
    {
      p_run_id: lease.runId,
      p_fencing_token: lease.fencingToken,
      p_ttl_seconds: ttlSeconds,
    },
    fetchImpl,
  );
  if (typeof result !== "boolean") throw new Error("supabase_worker_lease_renew_response_invalid");
  return result;
}

export async function releaseWorkerLease(
  supabaseUrl: string,
  serviceRoleKey: string,
  lease: WorkerLease,
  fetchImpl: typeof fetch,
): Promise<boolean> {
  const result = await callLeaseRpc(
    supabaseUrl,
    serviceRoleKey,
    "pr_d_release_e12_worker_lease",
    { p_run_id: lease.runId, p_fencing_token: lease.fencingToken },
    fetchImpl,
  );
  if (typeof result !== "boolean") throw new Error("supabase_worker_lease_release_response_invalid");
  return result;
}
