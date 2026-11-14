import { handleE12Capture } from "./worker.ts";
import { verifyObservationAttestation, type ObservationAttestation, type ObservationAttestationPayload } from "./provenance.ts";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

function b64url(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
}

async function jwtForServiceRole(secret: string): Promise<string> {
  const header = b64url(new TextEncoder().encode(JSON.stringify({ alg: "HS256", typ: "JWT" })));
  const payload = b64url(new TextEncoder().encode(JSON.stringify({
    role: "service_role",
    exp: Math.floor(Date.now() / 1000) + 300,
  })));
  const input = header + "." + payload;
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = new Uint8Array(await crypto.subtle.sign(
    "HMAC",
    key,
    new TextEncoder().encode(input),
  ));
  return input + "." + b64url(signature);
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
  // Match the worker's canonical request format exactly.
  const canonical = "POST\\n/e12-capture\\n" + timestamp + "\\n" + hex;
  const signature = new Uint8Array(await crypto.subtle.sign(
    "HMAC",
    key,
    new TextEncoder().encode(canonical),
  ));
  return Array.from(signature, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

Deno.test("full E12 worker runs over real PostgREST HTTP with simulated YouTube and valid Ed25519", async () => {
  const postgrestUrl = Deno.env.get("POSTGREST_URL");
  const jwtSecret = Deno.env.get("PGRST_JWT_SECRET");
  const cronSecret = Deno.env.get("E12_TEST_CRON_SECRET");
  const privateKey = Deno.env.get("E12_TEST_PRIVATE_KEY_PKCS8_B64");
  const publicKey = Deno.env.get("E12_TEST_PUBLIC_KEY_SPKI_B64");
  const hmacSecret = Deno.env.get("E12_TEST_HMAC_SECRET_B64");
  assert(postgrestUrl && jwtSecret && cronSecret && privateKey && publicKey && hmacSecret, "E2E test environment is incomplete");

  const jwt = await jwtForServiceRole(jwtSecret);
  const now = Date.now();
  const nowSeconds = Math.floor(now / 1000);
  const timestamp = String(nowSeconds);
  const body = "{}";
  const cronHmac = await cronSignature(cronSecret, timestamp, body);
  const publishedAt = new Date(now - 3 * 60 * 60 * 1000).toISOString().replace(".000Z", "Z");
  const syncMicros = BigInt(now) * 1000n;
  let youtubeCalls = 0;
  const postgrestTrace: string[] = [];
  const realFetch = fetch;

  const fetchImpl: typeof fetch = async (input, init) => {
    const url = String(input);
    if (url.startsWith("https://www.googleapis.com/youtube/v3/videos")) {
      youtubeCalls++;
      const parsed = new URL(url);
      const requestedIds = (parsed.searchParams.get("id") ?? "").split(",").filter(Boolean);
      assert(requestedIds.includes("e12-postgrest-e2e-video"), "worker must request the seeded E2E candidate");
      assert(requestedIds.length > 0, "worker must request at least one candidate");
      return new Response(JSON.stringify({
        items: requestedIds.map((id) => ({
          id,
          snippet: { publishedAt },
          statistics: { viewCount: "987654321" },
          status: { privacyStatus: "public" },
        })),
      }), { status: 200, headers: { "content-type": "application/json" } });
    }

    if (url.startsWith(postgrestUrl)) {
      const target = new URL(url);
      // Supabase uses /rest/v1; bare PostgREST exposes the same API at /.
      target.pathname = target.pathname.replace(/^\/rest\/v1(?=\/)/, "");
      const headers = new Headers(init?.headers);
      headers.set("Authorization", "Bearer " + jwt);
      headers.set("apikey", "e12-disposable-test-key");
      const upstream = await realFetch(target, { ...init, headers });
      const responseBody = await upstream.clone().text();
      postgrestTrace.push(
        `${init?.method ?? "GET"} ${target.pathname}${target.search} -> ${upstream.status}: ${responseBody.slice(0, 800)}`,
      );
      return upstream;
    }
    throw new Error("unexpected E2E network destination: " + url);
  };

  const dependencies = {
    env: (name: string) => ({
      E12_CRON_HMAC_SECRET: cronSecret,
      SUPABASE_URL: postgrestUrl,
      SUPABASE_SERVICE_ROLE_KEY: "e12-disposable-test-key",
      YOUTUBE_API_KEY: "e12-fake-youtube-key",
      E12_PROVENANCE_KEY_ID: "e12-postgrest-e2e-key",
      E12_PROVENANCE_PUBLIC_KEY_SPKI_B64: publicKey,
      E12_PROVENANCE_PRIVATE_KEY_PKCS8_B64: privateKey,
      E12_PROVENANCE_HMAC_SECRET_B64: hmacSecret,
    } as Record<string, string>)[name],
    fetchImpl,
    clockMicros: () => syncMicros,
    nowEpochSeconds: () => nowSeconds,
    randomUUID: () => "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff",
    leaseTtlSeconds: 90,
  };

  const response = await handleE12Capture(new Request("https://edge.test/e12-capture", {
    method: "POST",
    headers: {
      "x-e12-timestamp": timestamp,
      "x-e12-signature": cronHmac,
    },
    body,
  }), dependencies);
  const result = await response.json();

  assert(
    response.status === 200,
    "full worker must complete successfully; got " + JSON.stringify(result) +
      "; PostgREST trace: " + JSON.stringify(postgrestTrace),
  );
  assert(result.candidates === 3 && result.eligible === 3 && result.captured === 3, "all three disposable database candidates must be captured");
  assert(youtubeCalls === 1, "YouTube must be called once through the deterministic fake");

  const verifyUrl = new URL(postgrestUrl + "/youtube_shorts_log");
  verifyUrl.searchParams.set("id", "eq.4");
  verifyUrl.searchParams.set("select", "id,youtube_video_id,views_primeras_3h,published_at,sync_captured_at,e12_capture_run_id,e12_fencing_token,collector_attestation_algorithm,collector_key_id,collector_payload_canonical,collector_payload_sha256,collector_signature,collector_hmac_signature");
  const verifyResponse = await realFetch(verifyUrl, {
    headers: { Authorization: "Bearer " + jwt, apikey: "e12-disposable-test-key" },
  });
  assert(verifyResponse.ok, "PostgREST readback must succeed");
  const rows = await verifyResponse.json();
  assert(Array.isArray(rows) && rows.length === 1, "expected exactly one persisted row");
  const row = rows[0];
  assert(row.youtube_video_id === "e12-postgrest-e2e-video", "persisted identity must match");
  assert(row.views_primeras_3h === "987654321" || row.views_primeras_3h === 987654321, "persisted views must match source observation");
  assert(row.e12_capture_run_id === "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff", "persisted run ID must bind the worker run");
  assert(Number(row.e12_fencing_token) > 0, "persisted fencing token must be positive");
  assert(row.collector_attestation_algorithm === "Ed25519", "persisted attestation algorithm must be Ed25519");
  assert(row.collector_key_id === "e12-postgrest-e2e-key", "persisted key ID must match the registered ephemeral key");
  assert(/^[a-f0-9]{64}$/.test(row.collector_payload_sha256), "persisted canonical payload digest must be valid");
  assert(/^[A-Za-z0-9+/]{86}=$/.test(row.collector_signature), "persisted Ed25519 signature must have the expected encoding");
  assert(/^[a-f0-9]{64}$/.test(row.collector_hmac_signature), "persisted HMAC must be present");
  const canonical = JSON.parse(row.collector_payload_canonical) as string[];
  assert(canonical.length === 12, "persisted canonical payload must have all 12 fields");
  const attestationPayload: ObservationAttestationPayload = {
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
    await verifyObservationAttestation(attestationPayload, attestation, publicKey, hmacSecret),
    "persisted canonical payload, Ed25519 signature and HMAC must verify independently after HTTP readback",
  );
});
