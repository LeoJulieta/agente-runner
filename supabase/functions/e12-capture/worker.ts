import {
  collectYouTubeBatch,
  nowEpochMicros,
  type ClockMicros,
} from "./collector.ts";

export type WorkerDependencies = {
  env: (name: string) => string | undefined;
  fetchImpl?: typeof fetch;
  clockMicros?: ClockMicros;
  nowEpochSeconds?: () => number;
};

type CandidateRow = {
  id: number | string;
  youtube_video_id: string;
  created_at: string;
};

const JSON_HEADERS = { "content-type": "application/json; charset=utf-8" };
const CANDIDATE_LOOKBACK_HOURS = 6;
const CANDIDATE_LIMIT = 500;
const YOUTUBE_BATCH_SIZE = 50;
const CRON_CLOCK_SKEW_SECONDS = 120;

function jsonResponse(status: number, body: Record<string, unknown>): Response {
  return new Response(JSON.stringify(body), { status, headers: JSON_HEADERS });
}

function constantTimeEqual(left: string, right: string): boolean {
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index++) {
    difference |= left.charCodeAt(index) ^ right.charCodeAt(index);
  }
  return difference === 0;
}

function toHex(bytes: Uint8Array): string {
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function verifyCronSignature(
  timestamp: string,
  suppliedSignature: string,
  secret: string,
  nowEpochSeconds: number,
): Promise<boolean> {
  if (!/^\d{10}$/.test(timestamp) || !/^[a-f0-9]{64}$/i.test(suppliedSignature)) {
    return false;
  }
  const timestampSeconds = Number(timestamp);
  if (!Number.isSafeInteger(timestampSeconds) ||
      Math.abs(nowEpochSeconds - timestampSeconds) > CRON_CLOCK_SKEW_SECONDS) {
    return false;
  }

  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signed = await crypto.subtle.sign(
    "HMAC",
    key,
    new TextEncoder().encode(timestamp),
  );
  return constantTimeEqual(toHex(new Uint8Array(signed)), suppliedSignature.toLowerCase());
}

async function fetchPendingCandidates(
  supabaseUrl: string,
  serviceRoleKey: string,
  fetchImpl: typeof fetch,
  nowEpochSeconds: number,
): Promise<CandidateRow[]> {
  const baseUrl = supabaseUrl.replace(/\/+$/, "");
  const url = new URL(`${baseUrl}/rest/v1/youtube_shorts_log`);
  const nowIso = new Date(nowEpochSeconds * 1_000).toISOString();
  const cutoffIso = new Date(
    nowEpochSeconds * 1_000 - CANDIDATE_LOOKBACK_HOURS * 60 * 60 * 1_000,
  ).toISOString();

  url.searchParams.set("select", "id,youtube_video_id,created_at");
  url.searchParams.set("status", "eq.published");
  url.searchParams.set("youtube_video_id", "not.is.null");
  url.searchParams.set("views_primeras_3h", "is.null");
  url.searchParams.set("hs_al_publicar_al_sync", "is.null");
  url.searchParams.set("published_at", "is.null");
  url.searchParams.set("sync_captured_at", "is.null");
  url.searchParams.set("elapsed_seconds_e12", "is.null");
  url.searchParams.set("created_at", `gte.${cutoffIso}`);
  url.searchParams.append("created_at", `lte.${nowIso}`);
  url.searchParams.set("order", "created_at.desc");
  url.searchParams.set("limit", String(CANDIDATE_LIMIT));

  const response = await fetchImpl(url, {
    method: "GET",
    headers: { apikey: serviceRoleKey, Accept: "application/json" },
    signal: AbortSignal.timeout(15_000),
  });
  if (!response.ok) throw new Error(`supabase_candidates_http_${response.status}`);

  const payload: unknown = await response.json();
  if (!Array.isArray(payload)) throw new Error("supabase_candidates_response_invalid");

  const rows: CandidateRow[] = [];
  for (const item of payload) {
    if (!item || typeof item !== "object") throw new Error("supabase_candidate_invalid");
    const row = item as Record<string, unknown>;
    if (
      (typeof row.id !== "number" && typeof row.id !== "string") ||
      typeof row.youtube_video_id !== "string" ||
      !row.youtube_video_id ||
      typeof row.created_at !== "string"
    ) {
      throw new Error("supabase_candidate_fields_invalid");
    }
    rows.push({
      id: row.id,
      youtube_video_id: row.youtube_video_id,
      created_at: row.created_at,
    });
  }
  return rows;
}

async function persistObservation(
  supabaseUrl: string,
  serviceRoleKey: string,
  row: CandidateRow,
  observation: {
    videoId: string;
    viewCount: string;
    publishedAt: string;
    syncCapturedAt: string;
  },
  fetchImpl: typeof fetch,
): Promise<boolean> {
  const baseUrl = supabaseUrl.replace(/\/+$/, "");
  const response = await fetchImpl(`${baseUrl}/rest/v1/rpc/pr_d_capture_views_once`, {
    method: "POST",
    headers: {
      apikey: serviceRoleKey,
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      p_row_id: String(row.id),
      p_youtube_video_id: observation.videoId,
      p_views: observation.viewCount,
      p_published_at: observation.publishedAt,
      p_sync_captured_at: observation.syncCapturedAt,
    }),
    signal: AbortSignal.timeout(15_000),
  });
  if (!response.ok) throw new Error(`supabase_capture_rpc_http_${response.status}`);
  const result: unknown = await response.json();
  if (typeof result !== "boolean") throw new Error("supabase_capture_rpc_response_invalid");
  return result;
}

export async function handleE12Capture(
  request: Request,
  dependencies: WorkerDependencies,
): Promise<Response> {
  if (request.method !== "POST") return jsonResponse(405, { error: "method_not_allowed" });

  const cronSecret = dependencies.env("E12_CRON_HMAC_SECRET");
  const timestamp = request.headers.get("x-e12-timestamp") ?? "";
  const signature = request.headers.get("x-e12-signature") ?? "";
  if (
    !cronSecret ||
    !await verifyCronSignature(
      timestamp,
      signature,
      cronSecret,
      (dependencies.nowEpochSeconds ?? (() => Math.floor(Date.now() / 1_000)))(),
    )
  ) {
    return jsonResponse(401, { error: "unauthorized" });
  }

  const body = await request.text();
  if (body.trim() !== "" && body.trim() !== "{}") {
    return jsonResponse(400, { error: "request_body_must_be_empty" });
  }

  const supabaseUrl = dependencies.env("SUPABASE_URL");
  const serviceRoleKey = dependencies.env("SUPABASE_SERVICE_ROLE_KEY");
  const youtubeApiKey = dependencies.env("YOUTUBE_API_KEY");
  if (!supabaseUrl || !serviceRoleKey || !youtubeApiKey) {
    return jsonResponse(500, { error: "required_worker_secret_missing" });
  }

  const fetchImpl = dependencies.fetchImpl ?? fetch;
  const clockMicros = dependencies.clockMicros ?? nowEpochMicros;
  const nowSeconds = (dependencies.nowEpochSeconds ?? (() => Math.floor(Date.now() / 1_000)))();

  try {
    const candidates = await fetchPendingCandidates(
      supabaseUrl,
      serviceRoleKey,
      fetchImpl,
      nowSeconds,
    );

    const byVideoId = new Map<string, CandidateRow>();
    const duplicateVideoIds = new Set<string>();
    for (const row of candidates) {
      if (byVideoId.has(row.youtube_video_id)) {
        duplicateVideoIds.add(row.youtube_video_id);
      } else {
        byVideoId.set(row.youtube_video_id, row);
      }
    }
    for (const duplicate of duplicateVideoIds) byVideoId.delete(duplicate);

    let eligible = 0;
    let captured = 0;
    let casLost = 0;
    let nonEligible = 0;
    let duplicateRows = duplicateVideoIds.size;

    const videoIds = [...byVideoId.keys()];
    for (let offset = 0; offset < videoIds.length; offset += YOUTUBE_BATCH_SIZE) {
      const batchIds = videoIds.slice(offset, offset + YOUTUBE_BATCH_SIZE);
      const observations = await collectYouTubeBatch(
        batchIds,
        youtubeApiKey,
        fetchImpl,
        clockMicros,
      );

      for (const observation of observations) {
        if (!observation.eligible) {
          nonEligible++;
          continue;
        }
        const row = byVideoId.get(observation.videoId);
        if (!row) continue;
        eligible++;
        const didCapture = await persistObservation(
          supabaseUrl,
          serviceRoleKey,
          row,
          observation,
          fetchImpl,
        );
        if (didCapture) captured++;
        else casLost++;
      }
    }

    return jsonResponse(200, {
      candidates: candidates.length,
      uniqueCandidates: videoIds.length,
      duplicateRows,
      eligible,
      captured,
      casLost,
      nonEligible,
    });
  } catch (_error) {
    // Never return request URLs, API keys, Supabase keys, or upstream bodies.
    return jsonResponse(502, { error: "e12_capture_cycle_failed" });
  }
}
