import { handleE12Capture, verifyCronSignature } from "./worker.ts";
import { parseRfc3339EpochMicros, YOUTUBE_UINT64_MAX } from "./collector.ts";
import {
  verifyObservationAttestation,
  type ObservationAttestation,
  type ObservationAttestationPayload,
} from "./provenance.ts";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

async function sign(secret: string, timestamp: string, body = "{}"): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const bodyHash = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(body)));
  const bodyHashHex = Array.from(bodyHash, (byte) => byte.toString(16).padStart(2, "0")).join("");
  const canonical = `POST\\n/e12-capture\\n${timestamp}\\n${bodyHashHex}`;
  const bytes = new Uint8Array(
    await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(canonical)),
  );
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

const SECRET = "e12-test-cron-secret-with-more-than-32-bytes";
const NOW_SECONDS = Math.floor(Date.parse("2026-10-30T05:30:00Z") / 1_000);
const TIMESTAMP = String(NOW_SECONDS);
const CAPTURE_MICROS = parseRfc3339EpochMicros("2026-10-30T05:30:00.123456Z");
function toBase64(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

const TEST_KEY_PAIR = await crypto.subtle.generateKey(
  { name: "Ed25519" },
  true,
  ["sign", "verify"],
) as CryptoKeyPair;
const TEST_PRIVATE_KEY = toBase64(new Uint8Array(await crypto.subtle.exportKey("pkcs8", TEST_KEY_PAIR.privateKey)));
const TEST_PUBLIC_KEY = toBase64(new Uint8Array(await crypto.subtle.exportKey("spki", TEST_KEY_PAIR.publicKey)));
const TEST_HMAC_SECRET_BYTES = new Uint8Array(32).fill(7);
const TEST_HMAC_SECRET = toBase64(TEST_HMAC_SECRET_BYTES);

function dependencies(fetchImpl: typeof fetch, overrides: Record<string, string> = {}) {
  const values: Record<string, string> = {
    E12_CRON_HMAC_SECRET: SECRET,
    SUPABASE_URL: "https://project.example.supabase.co",
    SUPABASE_SERVICE_ROLE_KEY: "sb_secret_test_only_not_real",
    YOUTUBE_API_KEY: "youtube-test-key",
    E12_PROVENANCE_KEY_ID: "e12-test-key",
    E12_PROVENANCE_PRIVATE_KEY_PKCS8_B64: TEST_PRIVATE_KEY,
    E12_PROVENANCE_PUBLIC_KEY_SPKI_B64: TEST_PUBLIC_KEY,
    E12_PROVENANCE_HMAC_SECRET_B64: TEST_HMAC_SECRET,
    ...overrides,
  };
  return {
    env: (name: string) => values[name],
    fetchImpl,
    clockMicros: () => CAPTURE_MICROS,
    nowEpochSeconds: () => NOW_SECONDS,
    randomUUID: () => "11111111-2222-4333-8444-555555555555",
    leaseTtlSeconds: 90,
  };
}

async function signedRequest(body = "{}"): Promise<Request> {
  return new Request("https://edge.example/e12-capture", {
    method: "POST",
    headers: {
      "x-e12-timestamp": TIMESTAMP,
      "x-e12-signature": await sign(SECRET, TIMESTAMP, body),
    },
    body,
  });
}

Deno.test("cron HMAC accepts fresh signatures and rejects stale or altered ones", async () => {
  const signature = await sign(SECRET, TIMESTAMP);
  assert(await verifyCronSignature(TIMESTAMP, signature, SECRET, NOW_SECONDS), "valid HMAC should pass");
  assert(
    !await verifyCronSignature(TIMESTAMP, signature, SECRET, NOW_SECONDS, "POST", "/other", "{}"),
    "path substitution must fail",
  );
  assert(
    !await verifyCronSignature(TIMESTAMP, signature, SECRET, NOW_SECONDS, "POST", "/e12-capture", "{ }"),
    "body substitution must fail",
  );
  assert(!await verifyCronSignature(TIMESTAMP, "0".repeat(64), SECRET, NOW_SECONDS), "altered HMAC should fail");
  assert(!await verifyCronSignature(TIMESTAMP, signature, SECRET, NOW_SECONDS + 121), "stale HMAC should fail");
  assert(!await verifyCronSignature(TIMESTAMP, signature, "short", NOW_SECONDS), "weak secret should fail");
});

Deno.test("worker rejects GET and invalid HMAC before making network calls", async () => {
  let calls = 0;
  const fetchImpl = () => {
    calls++;
    return Promise.resolve(new Response("[]", { status: 200 }));
  };
  const deps = dependencies(fetchImpl);
  const getResponse = await handleE12Capture(
    new Request("https://edge.example/e12-capture", { method: "GET" }),
    deps,
  );
  assert(getResponse.status === 405, "GET must be rejected");

  const badRequest = new Request("https://edge.example/e12-capture", {
    method: "POST",
    headers: { "x-e12-timestamp": TIMESTAMP, "x-e12-signature": "0".repeat(64) },
    body: "{}",
  });
  const badResponse = await handleE12Capture(badRequest, deps);
  assert(badResponse.status === 401, "invalid HMAC must be rejected");
  assert(calls === 0, "unauthorized requests must not call upstream services");
});

Deno.test("worker accepts only an empty command body, never caller-supplied observations", async () => {
  let calls = 0;
  const fetchImpl = () => {
    calls++;
    return Promise.resolve(new Response("[]", { status: 200 }));
  };
  const response = await handleE12Capture(
    await signedRequest(JSON.stringify({ p_views: "999", p_published_at: "forged" })),
    dependencies(fetchImpl),
  );
  assert(response.status === 400, "observation fields in request body must be rejected");
  assert(calls === 0, "forged request body must not reach Supabase or YouTube");
});

Deno.test("worker obtains source observation itself and persists only through the CAS RPC", async () => {
  const calls: Array<{ url: string; method: string; headers: Headers; body: string }> = [];
  const fetchImpl: typeof fetch = (input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    const headers = new Headers(init?.headers);
    const body = typeof init?.body === "string" ? init.body : "";
    calls.push({ url, method, headers, body });

    if (url.includes("/rpc/pr_d_claim_e12_worker_slot")) {
      return Promise.resolve(new Response("true", { status: 200 }));
    }
    if (url.includes("/rpc/pr_d_claim_e12_worker_lease")) {
      return Promise.resolve(new Response(JSON.stringify([{
        acquired: true,
        fencing_token: "9007199254740993",
        lease_expires_at: "2026-10-30T05:31:30Z",
      }]), { status: 200 }));
    }
    if (url.includes("/rpc/pr_d_renew_e12_worker_lease")) {
      return Promise.resolve(new Response("true", { status: 200 }));
    }
    if (url.includes("/rest/v1/youtube_shorts_log")) {
      return Promise.resolve(
        new Response(
          JSON.stringify([{
            id: 42,
            youtube_video_id: "video-1",
            created_at: "2026-10-30T02:00:00Z",
          }]),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
      );
    }
    if (url.startsWith("https://www.googleapis.com/youtube/v3/videos")) {
      return Promise.resolve(
        new Response(
          JSON.stringify({
            items: [{
              id: "video-1",
              snippet: { publishedAt: "2026-10-30T02:30:00Z" },
              statistics: { viewCount: YOUTUBE_UINT64_MAX.toString() },
              status: { privacyStatus: "public" },
            }],
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
      );
    }
    if (url.includes("/rest/v1/rpc/pr_d_capture_views_once")) {
      return Promise.resolve(new Response("true", { status: 200, headers: { "content-type": "application/json" } }));
    }
    if (url.includes("/rpc/pr_d_release_e12_worker_lease")) {
      return Promise.resolve(new Response("true", { status: 200 }));
    }
    throw new Error("unexpected_test_fetch_url");
  };

  const response = await handleE12Capture(
    await signedRequest(),
    dependencies(fetchImpl),
  );
  const result = await response.json();

  assert(response.status === 200, "worker cycle should succeed");
  assert(
    result.candidates === 1 && result.eligible === 1 && result.captured === 1,
    "one eligible row should be captured",
  );
  assert(calls.length === 9, "worker should claim slot and lease, renew, query YouTube, renew before CAS, then release");

  const slotCall = calls[0];
  const slotBody = JSON.parse(slotCall.body);
  assert(slotCall.url.endsWith("/rpc/pr_d_claim_e12_worker_slot"), "worker must claim an idempotency slot first");
  assert(slotBody.p_minute_bucket === "2026-10-30T05:30:00.000Z", "slot must derive from the signed cron minute");

  const leaseClaimCall = calls[1];
  assert(leaseClaimCall.url.endsWith("/rpc/pr_d_claim_e12_worker_lease"), "worker must claim lease after replay slot");
  const candidateCall = calls[2];
  assert(candidateCall.url.includes("created_at=gte."), "created_at may be used only as a coarse candidate filter");
  assert(candidateCall.url.includes("status=eq.published"), "only published rows are candidates");
  assert(
    candidateCall.headers.get("apikey") === "sb_secret_test_only_not_real",
    "Supabase secret key must use apikey header",
  );
  assert(
    candidateCall.headers.get("authorization") === null,
    "service key must not be copied into Authorization header",
  );

  const renewalCall = calls[3];
  assert(renewalCall.url.endsWith("/rpc/pr_d_renew_e12_worker_lease"), "worker must renew before source collection");
  assert(calls[4].url.endsWith("/rpc/pr_d_renew_e12_worker_lease"), "worker must renew before each YouTube batch");
  const youtubeCall = calls[5];
  const youtubeUrl = new URL(youtubeCall.url);
  assert(
    youtubeUrl.searchParams.get("part") === "snippet,statistics,status",
    "collector must request source publication time, count and privacy",
  );
  assert(youtubeUrl.searchParams.get("id") === "video-1", "collector must request the exact candidate ID");
  assert(
    youtubeUrl.searchParams.get("key") === "youtube-test-key",
    "YouTube key must be used only for the source request",
  );

  const casRenewalCall = calls[6];
  assert(casRenewalCall.url.endsWith("/rpc/pr_d_renew_e12_worker_lease"), "worker must renew immediately before CAS");
  const rpcCall = calls[7];
  const rpcBody = JSON.parse(rpcCall.body);
  assert(rpcCall.url.endsWith("/rpc/pr_d_capture_views_once"), "persistence must use the CAS RPC");
  assert(rpcBody.p_row_id === "42", "row id must be exact");
  assert(rpcBody.p_youtube_video_id === "video-1", "video id must be exact");
  assert(rpcBody.p_views === YOUTUBE_UINT64_MAX.toString(), "uint64 must remain an exact decimal string");
  assert(rpcBody.p_run_id === "11111111-2222-4333-8444-555555555555", "CAS must bind the lease owner");
  assert(rpcBody.p_fencing_token === "9007199254740993", "CAS must bind the exact fencing token");
  assert(rpcBody.p_attestation_version === "e12-observation-attestation/v1", "CAS must store the versioned attestation");
  assert(rpcBody.p_attestation_algorithm === "Ed25519", "CAS must store the signature algorithm");
  assert(rpcBody.p_collector_key_id === "e12-test-key", "CAS must bind the registered collector key ID");
  assert(rpcBody.p_collector_public_key_spki_base64 === TEST_PUBLIC_KEY, "CAS must bind the exact registered public key");
  const attestationPayload: ObservationAttestationPayload = {
    keyId: "e12-test-key",
    runId: "11111111-2222-4333-8444-555555555555",
    fencingToken: "9007199254740993",
    rowId: "7",
    videoId: "video-1",
    publishedAt: "2026-10-30T02:30:00Z",
    viewCount: YOUTUBE_UINT64_MAX.toString(),
    syncCapturedAt: "2026-10-30T05:30:00.123456Z",
    responseBodySha256: String(rpcBody.p_collector_response_sha256),
    requestedVideoIdsSha256: String(rpcBody.p_collector_requested_ids_sha256),
    collectorBuild: "e12-collector/0.1.0",
  };
  const attestation: ObservationAttestation = {
    version: String(rpcBody.p_attestation_version) as ObservationAttestation["version"],
    algorithm: String(rpcBody.p_attestation_algorithm) as ObservationAttestation["algorithm"],
    keyId: String(rpcBody.p_collector_key_id),
    payloadSha256: String(rpcBody.p_collector_payload_sha256),
    signatureBase64: String(rpcBody.p_collector_signature),
    hmacSignatureHex: String(rpcBody.p_collector_hmac_signature),
  };
  assert(
    await verifyObservationAttestation(attestationPayload, attestation, TEST_PUBLIC_KEY, TEST_HMAC_SECRET),
    "worker must send a valid Ed25519 signature and HMAC over the exact canonical payload",
  );
  const canonicalPayload = JSON.parse(String(rpcBody.p_collector_payload_canonical)) as string[];
  assert(canonicalPayload.length === 12, "CAS must persist the complete canonical payload");
  assert(canonicalPayload[1] === "e12-test-key", "canonical payload must bind key ID");
  assert(canonicalPayload[2] === "11111111-2222-4333-8444-555555555555", "canonical payload must bind run ID");
  assert(canonicalPayload[3] === "9007199254740993", "canonical payload must bind exact fencing token");
  assert(canonicalPayload[5] === "video-1" && canonicalPayload[7] === YOUTUBE_UINT64_MAX.toString(), "canonical payload must bind video and exact uint64 count");
  assert(rpcBody.p_collector_signature === attestation.signatureBase64, "CAS must persist the Ed25519 signature");
  assert(rpcBody.p_collector_hmac_signature === attestation.hmacSignatureHex, "CAS must persist the database-verifiable HMAC");
  assert(/^[a-f0-9]{64}$/.test(String(rpcBody.p_collector_response_sha256)), "CAS must persist the raw response digest");
  assert(/^[a-f0-9]{64}$/.test(String(rpcBody.p_collector_requested_ids_sha256)), "CAS must persist the requested IDs digest");
  assert(rpcBody.p_collector_build === "e12-collector/0.1.0", "CAS must persist collector build identity");
  assert(calls[8].url.endsWith("/rpc/pr_d_release_e12_worker_lease"), "worker must release its lease after completion");
  assert(rpcBody.p_published_at === "2026-10-30T02:30:00Z", "publishedAt must come from YouTube");
  assert(
    rpcBody.p_sync_captured_at === "2026-10-30T05:30:00.123456Z",
    "capture time must be taken after response read",
  );
  assert(!("hs_al_publicar_al_sync" in rpcBody), "legacy elapsed column must never be written by E12");
});

Deno.test("worker skips replayed signed minute before any YouTube request", async () => {
  let calls = 0;
  const fetchImpl: typeof fetch = (input) => {
    calls++;
    const url = String(input);
    if (url.includes("/rpc/pr_d_claim_e12_worker_slot")) {
      return Promise.resolve(new Response("false", { status: 200 }));
    }
    throw new Error("duplicate invocation must not reach candidates or YouTube");
  };

  const response = await handleE12Capture(await signedRequest(), dependencies(fetchImpl));
  const result = await response.json();
  assert(response.status === 200 && result.skippedDuplicateInvocation === true, "replayed minute must be skipped");
  assert(calls === 1, "duplicate invocation must stop after slot claim");
});

Deno.test("worker fails closed instead of silently truncating more than 500 candidates", async () => {
  let calls = 0;
  const candidates = Array.from({ length: 500 }, (_, index) => ({
    id: index + 1,
    youtube_video_id: `video-${index + 1}`,
    created_at: "2026-10-30T02:00:00Z",
  }));
  const fetchImpl: typeof fetch = (input) => {
    calls++;
    const url = String(input);
    if (url.includes("/rpc/pr_d_claim_e12_worker_slot")) {
      return Promise.resolve(new Response("true", { status: 200 }));
    }
    if (url.includes("/rpc/pr_d_claim_e12_worker_lease")) {
      return Promise.resolve(new Response(JSON.stringify([{
        acquired: true, fencing_token: "2", lease_expires_at: "2026-10-30T05:31:30Z",
      }]), { status: 200 }));
    }
    if (url.includes("/rpc/pr_d_release_e12_worker_lease")) {
      return Promise.resolve(new Response("true", { status: 200 }));
    }
    if (url.includes("/rest/v1/youtube_shorts_log")) {
      return Promise.resolve(
        new Response(JSON.stringify(candidates), {
          status: 200,
          headers: { "content-range": "0-499/501" },
        }),
      );
    }
    throw new Error("candidate cap must stop before YouTube");
  };

  const response = await handleE12Capture(await signedRequest(), dependencies(fetchImpl));
  assert(response.status === 502, "candidate truncation must fail closed");
  assert(calls === 4, "worker must stop after detecting more than 500 candidates and release its lease");
});

Deno.test("worker reports CAS first-write conflicts without overwriting outcomes", async () => {
  const fetchImpl: typeof fetch = (input) => {
    const url = String(input);
    if (url.includes("/rpc/pr_d_claim_e12_worker_slot")) {
      return Promise.resolve(new Response("true", { status: 200 }));
    }
    if (url.includes("/rpc/pr_d_claim_e12_worker_lease")) {
      return Promise.resolve(new Response(JSON.stringify([{
        acquired: true, fencing_token: "3", lease_expires_at: "2026-10-30T05:31:30Z",
      }]), { status: 200 }));
    }
    if (url.includes("/rpc/pr_d_renew_e12_worker_lease")) {
      return Promise.resolve(new Response("true", { status: 200 }));
    }
    if (url.includes("/rpc/pr_d_release_e12_worker_lease")) {
      return Promise.resolve(new Response("true", { status: 200 }));
    }
    if (url.includes("/rest/v1/youtube_shorts_log")) {
      return Promise.resolve(
        new Response(
          JSON.stringify([{
            id: 7,
            youtube_video_id: "video-1",
            created_at: "2026-10-30T02:00:00Z",
          }]),
          { status: 200 },
        ),
      );
    }
    if (url.startsWith("https://www.googleapis.com/youtube/v3/videos")) {
      return Promise.resolve(
        new Response(
          JSON.stringify({
            items: [{
              id: "video-1",
              snippet: { publishedAt: "2026-10-30T02:30:00Z" },
              statistics: { viewCount: "50" },
              status: { privacyStatus: "public" },
            }],
          }),
          { status: 200 },
        ),
      );
    }
    if (url.includes("/rpc/pr_d_capture_views_once")) {
      return Promise.resolve(new Response("false", { status: 200 }));
    }
    throw new Error("unexpected_test_fetch_url");
  };

  const response = await handleE12Capture(await signedRequest(), dependencies(fetchImpl));
  const result = await response.json();
  assert(
    response.status === 200 && result.casLost === 1 && result.captured === 0,
    "CAS conflict must be reported without retrying a write",
  );
});
Deno.test("worker enforces a streaming body cap when Content-Length is absent", async () => {
  let calls = 0;
  const oversized = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode("{}"));
      controller.enqueue(new TextEncoder().encode("x"));
      controller.close();
    },
  });
  const request = new Request("https://edge.example/e12-capture", {
    method: "POST",
    headers: { "x-e12-timestamp": TIMESTAMP, "x-e12-signature": await sign(SECRET, TIMESTAMP, "{}x") },
    body: oversized,
    // No Content-Length: exercise the streaming bound itself.
    duplex: "half",
  } as RequestInit);
  const response = await handleE12Capture(
    request,
    dependencies(() => {
      calls++;
      return Promise.resolve(new Response("[]", { status: 200 }));
    }),
  );
  assert(response.status === 400, "oversized streamed body must be rejected");
  assert(calls === 0, "oversized body must not reach upstream services");
});


Deno.test("worker fails closed when provenance key material is missing", async () => {
  let fetchCalls = 0;
  const fetchImpl: typeof fetch = async () => {
    fetchCalls++;
    return new Response("true", { status: 200 });
  };
  const response = await handleE12Capture(
    await signedRequest(),
    dependencies(fetchImpl, { E12_PROVENANCE_PUBLIC_KEY_SPKI_B64: "" }),
  );
  assert(response.status === 500, "missing public key must fail closed");
  assert(fetchCalls === 0, "missing provenance configuration must fail before network calls");
});

Deno.test("worker never calls CAS when independent attestation verification fails", async () => {
  const calls: string[] = [];
  const fetchImpl: typeof fetch = async (input) => {
    const url = String(input);
    calls.push(url);
    if (url.includes("/rpc/pr_d_claim_e12_worker_slot")) {
      return new Response("true", { status: 200 });
    }
    if (url.includes("/rpc/pr_d_claim_e12_worker_lease")) {
      return new Response(JSON.stringify([{
        acquired: true,
        fencing_token: "7",
        lease_expires_at: "2026-10-30T05:31:30Z",
      }]), { status: 200 });
    }
    if (url.includes("/rpc/pr_d_renew_e12_worker_lease") ||
        url.includes("/rpc/pr_d_release_e12_worker_lease")) {
      return new Response("true", { status: 200 });
    }
    if (url.includes("/rest/v1/youtube_shorts_log")) {
      return new Response(JSON.stringify([{
        id: 7,
        youtube_video_id: "video-1",
        published_at: "2026-10-30T02:30:00Z",
      }]), { status: 200 });
    }
    if (url.includes("youtube.googleapis.com")) {
      return new Response(JSON.stringify({
        items: [{
          id: "video-1",
          status: { privacyStatus: "public" },
          snippet: { publishedAt: "2026-10-30T02:30:00Z" },
          statistics: { viewCount: YOUTUBE_UINT64_MAX.toString() },
        }],
      }), { status: 200 });
    }
    throw new Error("unexpected_test_fetch_url");
  };
  const otherPair = await crypto.subtle.generateKey(
    { name: "Ed25519" },
    true,
    ["sign", "verify"],
  ) as CryptoKeyPair;
  const mismatchedPublicKey = toBase64(
    new Uint8Array(await crypto.subtle.exportKey("spki", otherPair.publicKey)),
  );
  const deps = dependencies(fetchImpl, { E12_PROVENANCE_PUBLIC_KEY_SPKI_B64: mismatchedPublicKey });
  const response = await handleE12Capture(await signedRequest(), deps);
  assert(response.status === 502, "invalid attestation must fail the worker cycle");
  assert(!calls.some((url) => url.includes("/rpc/pr_d_capture_views_once")), "CAS must not run for an invalid attestation");
  assert(calls.some((url) => url.includes("/rpc/pr_d_release_e12_worker_lease")), "lease must still be released");
});
