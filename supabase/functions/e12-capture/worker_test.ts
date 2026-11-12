import { handleE12Capture, verifyCronSignature } from "./worker.ts";
import { parseRfc3339EpochMicros, YOUTUBE_UINT64_MAX } from "./collector.ts";

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

function dependencies(fetchImpl: typeof fetch, overrides: Record<string, string> = {}) {
  const values: Record<string, string> = {
    E12_CRON_HMAC_SECRET: SECRET,
    SUPABASE_URL: "https://project.example.supabase.co",
    SUPABASE_SERVICE_ROLE_KEY: "sb_secret_test_only_not_real",
    YOUTUBE_API_KEY: "youtube-test-key",
    ...overrides,
  };
  return {
    env: (name: string) => values[name],
    fetchImpl,
    clockMicros: () => CAPTURE_MICROS,
    nowEpochSeconds: () => NOW_SECONDS,
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
  assert(calls.length === 4, "worker should claim slot, query candidates, call YouTube, then CAS");

  const slotCall = calls[0];
  const slotBody = JSON.parse(slotCall.body);
  assert(slotCall.url.endsWith("/rpc/pr_d_claim_e12_worker_slot"), "worker must claim an idempotency slot first");
  assert(slotBody.p_minute_bucket === "2026-10-30T05:30:00.000Z", "slot must derive from the signed cron minute");

  const candidateCall = calls[1];
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

  const youtubeCall = calls[2];
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

  const rpcCall = calls[3];
  const rpcBody = JSON.parse(rpcCall.body);
  assert(rpcCall.url.endsWith("/rpc/pr_d_capture_views_once"), "persistence must use the CAS RPC");
  assert(rpcBody.p_row_id === "42", "row id must be exact");
  assert(rpcBody.p_youtube_video_id === "video-1", "video id must be exact");
  assert(rpcBody.p_views === YOUTUBE_UINT64_MAX.toString(), "uint64 must remain an exact decimal string");
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
  assert(calls === 2, "worker must stop after detecting more than 500 candidates");
});

Deno.test("worker reports CAS first-write conflicts without overwriting outcomes", async () => {
  const fetchImpl: typeof fetch = (input) => {
    const url = String(input);
    if (url.includes("/rpc/pr_d_claim_e12_worker_slot")) {
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

