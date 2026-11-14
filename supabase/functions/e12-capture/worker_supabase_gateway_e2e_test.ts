import { handleE12Capture } from "./worker.ts";
import {
  verifyObservationAttestation,
  type ObservationAttestation,
  type ObservationAttestationPayload,
} from "./provenance.ts";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

async function cronSignature(secret: string, timestamp: string, body: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(body)));
  const hex = Array.from(digest, (byte) => byte.toString(16).padStart(2, "0")).join("");
  const canonical = ["POST", "/e12-capture", timestamp, hex].join(String.fromCharCode(10));
  const signature = new Uint8Array(await crypto.subtle.sign(
    "HMAC",
    key,
    new TextEncoder().encode(canonical),
  ));
  return Array.from(signature, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

type BatchOutcome = { captured: boolean };

Deno.test("full E12 worker uses modern sb_secret through the real local Supabase API Gateway", async () => {
  const apiUrl = Deno.env.get("E12_GATEWAY_API_URL");
  const secretKey = Deno.env.get("E12_GATEWAY_SECRET_KEY");
  const publishableKey = Deno.env.get("E12_GATEWAY_PUBLISHABLE_KEY");
  const cronSecret = Deno.env.get("E12_GATEWAY_CRON_SECRET");
  const privateKey = Deno.env.get("E12_GATEWAY_PRIVATE_KEY_PKCS8_B64");
  const publicKey = Deno.env.get("E12_GATEWAY_PUBLIC_KEY_SPKI_B64");
  const hmacSecret = Deno.env.get("E12_GATEWAY_HMAC_SECRET_B64");
  assert(
    apiUrl && secretKey && publishableKey && cronSecret && privateKey && publicKey && hmacSecret,
    "local Supabase Gateway E2E environment is incomplete",
  );
  assert(secretKey.startsWith("sb_secret_"), "local API key must be the modern secret key");
  assert(publishableKey.startsWith("sb_publishable_"), "local API key must be the modern publishable key");
  const baseUrl = apiUrl.endsWith("/") ? apiUrl.slice(0, -1) : apiUrl;

  const now = Date.now();
  const nowSeconds = Math.floor(now / 1000);
  const timestamp = String(nowSeconds);
  const body = "{}";
  const cronHmac = await cronSignature(cronSecret, timestamp, body);
  const publishedAt = new Date(now - 3 * 60 * 60 * 1000).toISOString();
  const syncMicros = BigInt(now) * 1000n;
  const postgrestTrace: string[] = [];
  let youtubeCalls = 0;
  let committedBatchBody: string | null = null;
  let inFlightReplayOutcomes: BatchOutcome[] = [];

  const fetchImpl: typeof fetch = async (input, init) => {
    const url = String(input);
    if (url.startsWith("https://www.googleapis.com/youtube/v3/videos")) {
      youtubeCalls++;
      const parsed = new URL(url);
      const requestedIds = (parsed.searchParams.get("id") ?? "").split(",").filter(Boolean);
      assert(
        requestedIds.length === 1 && requestedIds[0] === "e12-supabase-gateway-video",
        "worker must request only the seeded local candidate",
      );
      return new Response(JSON.stringify({
        items: requestedIds.map((id) => ({
          id,
          snippet: { publishedAt },
          statistics: { viewCount: "987654321" },
          status: { privacyStatus: "public" },
        })),
      }), { status: 200, headers: { "content-type": "application/json" } });
    }

    const outboundHeaders = new Headers(init?.headers);
    assert(outboundHeaders.get("apikey") === secretKey, "worker must send sb_secret in apikey");
    assert(outboundHeaders.get("Authorization") === null, "worker must not send opaque key as Bearer JWT");
    const response = await fetch(input, init);
    const responseDetail = response.ok ? "" : " " + (await response.clone().text()).slice(0, 1200);
    postgrestTrace.push(
      (init?.method ?? "GET") + " " + url.replace(baseUrl, "[SUPABASE_API]") +
        " -> " + response.status + responseDetail,
    );
    if (url.includes("/rpc/pr_d_capture_views_batch") && init?.body) {
      committedBatchBody = String(init.body);
      // Replay immediately after the commit response but before the worker
      // releases its lease, isolating first-write-wins from stale-lease denial.
      const replayWhileLeaseActive = await fetch(baseUrl + "/rest/v1/rpc/pr_d_capture_views_batch", {
        method: "POST",
        headers: { apikey: secretKey, "Content-Type": "application/json" },
        body: committedBatchBody,
      });
      assert(replayWhileLeaseActive.ok, "active-lease replay must be accepted by the gateway");
      const replayPayload: unknown = await replayWhileLeaseActive.json();
      assert(Array.isArray(replayPayload), "active-lease replay must return an array");
      inFlightReplayOutcomes = replayPayload as BatchOutcome[];
    }
    return response;
  };

  const response = await handleE12Capture(new Request("https://edge.test/e12-capture", {
    method: "POST",
    headers: {
      "x-e12-timestamp": timestamp,
      "x-e12-signature": cronHmac,
    },
    body,
  }), {
    env: (name: string) => ({
      E12_CRON_HMAC_SECRET: cronSecret,
      SUPABASE_URL: apiUrl,
      SUPABASE_SECRET_KEYS: JSON.stringify({ "e12-capture": secretKey }),
      YOUTUBE_API_KEY: "e12-fake-youtube-key",
      E12_PROVENANCE_KEY_ID: "e12-supabase-gateway-e2e-key",
      E12_PROVENANCE_PUBLIC_KEY_SPKI_B64: publicKey,
      E12_PROVENANCE_PRIVATE_KEY_PKCS8_B64: privateKey,
      E12_PROVENANCE_HMAC_SECRET_B64: hmacSecret,
    } as Record<string, string>)[name],
    fetchImpl,
    clockMicros: () => syncMicros,
    nowEpochSeconds: () => nowSeconds,
    randomUUID: () => "cccccccc-dddd-4eee-8fff-111111111111",
    leaseTtlSeconds: 90,
  });
  const result = await response.json();
  assert(
    response.status === 200,
    "worker must succeed through local Supabase Gateway: " + JSON.stringify(result) +
      "; trace=" + JSON.stringify(postgrestTrace),
  );
  assert(result.candidates === 1 && result.eligible === 1 && result.captured === 1, "one local candidate must be captured");
  assert(youtubeCalls === 1, "YouTube must be called exactly once through the fake");

  assert(committedBatchBody !== null, "worker must issue a batch CAS through the gateway");
  assert(
    inFlightReplayOutcomes.length === 1 &&
      inFlightReplayOutcomes.every((item: BatchOutcome) => item.captured === false),
    "replay while the original lease is active must prove first-write-wins",
  );
  const replay = await fetch(baseUrl + "/rest/v1/rpc/pr_d_capture_views_batch", {
    method: "POST",
    headers: { apikey: secretKey, "Content-Type": "application/json" },
    body: committedBatchBody,
  });
  assert(replay.ok, "gateway must accept the modern secret key for batch replay");
  const replayOutcomes = await replay.json();
  assert(
    Array.isArray(replayOutcomes) && replayOutcomes.length === 1 &&
      replayOutcomes.every((item) => item.captured === false),
    "gateway batch replay must preserve first-write-wins",
  );

  const verifyUrl = new URL(baseUrl + "/rest/v1/youtube_shorts_log");
  verifyUrl.searchParams.set("id", "eq.4");
  verifyUrl.searchParams.set("select", "id,youtube_video_id,views_primeras_3h,collector_key_id,collector_payload_canonical,collector_payload_sha256,collector_signature,collector_hmac_signature");
  const verify = await fetch(verifyUrl, { headers: { apikey: secretKey } });
  assert(verify.ok, "gateway readback with apikey only must succeed");
  const rows = await verify.json();
  assert(Array.isArray(rows) && rows.length === 1, "exactly one captured row must be visible");
  const row = rows[0];
  assert(row.youtube_video_id === "e12-supabase-gateway-video", "gateway persisted expected candidate identity");
  assert(Number(row.views_primeras_3h) === 987654321, "gateway persisted observed view count");
  assert(row.collector_key_id === "e12-supabase-gateway-e2e-key", "gateway persisted expected attestation key id");
  assert(/^[a-f0-9]{64}$/.test(row.collector_payload_sha256), "gateway persisted a SHA-256 digest");
  assert(/^[A-Za-z0-9+/]{86}==$/.test(row.collector_signature), "gateway persisted an Ed25519 signature");
  assert(/^[a-f0-9]{64}$/.test(row.collector_hmac_signature), "gateway persisted an HMAC");
  const canonical = JSON.parse(row.collector_payload_canonical) as string[];
  const payload: ObservationAttestationPayload = {
    keyId: canonical[1],
    runId: canonical[2],
    fencingToken: canonical[3],
    rowId: canonical[4],
    videoId: canonical[5],
    publishedAt: canonical[6],
    viewCount: canonical[7],
    syncCapturedAt: canonical[8],
    responseBodySha256: canonical[9],
    requestedVideoIdsSha256: canonical[10],
    collectorBuild: canonical[11],
  };
  const attestation: ObservationAttestation = {
    version: canonical[0] as ObservationAttestation["version"],
    algorithm: "Ed25519",
    keyId: row.collector_key_id,
    payloadSha256: row.collector_payload_sha256,
    signatureBase64: row.collector_signature,
    hmacSignatureHex: row.collector_hmac_signature,
  };
  assert(
    await verifyObservationAttestation(payload, attestation, publicKey, hmacSecret),
    "gateway readback signature and HMAC must verify offline",
  );

  const anon = await fetch(baseUrl + "/rest/v1/rpc/pr_d_claim_e12_worker_lease", {
    method: "POST",
    headers: { apikey: publishableKey, "Content-Type": "application/json" },
    body: JSON.stringify({
      p_run_id: "dddddddd-eeee-4fff-8000-222222222222",
      p_ttl_seconds: 90,
    }),
  });
  assert(
    [401, 403, 404].includes(anon.status),
    "publishable/anon key must not execute service-role-only E12 RPC; got " + anon.status,
  );
});
