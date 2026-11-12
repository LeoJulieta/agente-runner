import { type ClockMicros, type E12Observation, collectYouTubeBatch, nowEpochMicros } from "./collector.ts";
import {
  canonicalizeObservationPayload,
  createObservationAttestation,
  verifyObservationAttestation,
  type ObservationAttestation,
  type ObservationAttestationPayload,
} from "./provenance.ts";
import { claimWorkerLease, releaseWorkerLease, renewWorkerLease, type WorkerLease } from "./lease.ts";

export type WorkerDependencies = {
  env: (name: string) => string | undefined;
  fetchImpl?: typeof fetch;
  clockMicros?: ClockMicros;
  nowEpochSeconds?: () => number;
  randomUUID?: () => string;
  leaseTtlSeconds?: number;
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
  method = "POST",
  pathname = "/e12-capture",
  body = "{}",
): Promise<boolean> {
  if (
    new TextEncoder().encode(secret).byteLength < 32 ||
    !/^\d{10}$/.test(timestamp) ||
    !/^[a-f0-9]{64}$/i.test(suppliedSignature)
  ) {
    return false;
  }
  const timestampSeconds = Number(timestamp);
  if (
    !Number.isSafeInteger(timestampSeconds) ||
    Math.abs(nowEpochSeconds - timestampSeconds) > CRON_CLOCK_SKEW_SECONDS
  ) {
    return false;
  }

  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const bodyHash = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(body)));
  const bodyHashHex = toHex(bodyHash);
  const canonical = `${method.toUpperCase()}\\n${pathname}\\n${timestamp}\\n${bodyHashHex}`;
  const signed = await crypto.subtle.sign(
    "HMAC",
    key,
    new TextEncoder().encode(canonical),
  );
  return constantTimeEqual(toHex(new Uint8Array(signed)), suppliedSignature.toLowerCase());
}

async function claimWorkerSlot(
  supabaseUrl: string,
  serviceRoleKey: string,
  minuteBucket: string,
  fetchImpl: typeof fetch,
): Promise<boolean> {
  const baseUrl = supabaseUrl.replace(/\/+$/, "");
  const response = await fetchImpl(`${baseUrl}/rest/v1/rpc/pr_d_claim_e12_worker_slot`, {
    method: "POST",
    headers: {
      apikey: serviceRoleKey,
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ p_minute_bucket: minuteBucket }),
    signal: AbortSignal.timeout(15_000),
  });
  if (!response.ok) throw new Error(`supabase_worker_slot_http_${response.status}`);
  const result: unknown = await response.json();
  if (typeof result !== "boolean") throw new Error("supabase_worker_slot_response_invalid");
  return result;
}

async function fetchPendingCandidates(
  supabaseUrl: string,
  serviceRoleKey: string,
  fetchImpl: typeof fetch,
  nowEpochSeconds: number,
): Promise<CandidateRow[]> {
  const baseUrl = supabaseUrl.replace(/\/+$/, "");
  const url = new URL(`${baseUrl}/rest/v1/youtube_shorts_log`);
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
  url.searchParams.set("order", "created_at.desc");
  url.searchParams.set("limit", String(CANDIDATE_LIMIT));

  const response = await fetchImpl(url, {
    method: "GET",
    headers: {
      apikey: serviceRoleKey,
      Accept: "application/json",
      Prefer: "count=exact",
    },
    signal: AbortSignal.timeout(15_000),
  });
  if (!response.ok) throw new Error(`supabase_candidates_http_${response.status}`);

  const payload: unknown = await response.json();
  if (!Array.isArray(payload)) throw new Error("supabase_candidates_response_invalid");

  const rows: CandidateRow[] = [];
  const contentRange = response.headers.get("content-range") ?? "";
  const totalText = contentRange.split("/")[1];
  const total = totalText && totalText !== "*" ? Number(totalText) : Number.NaN;

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

  // Never silently omit rows if the operational candidate cap is reached.
  if (
    (Number.isFinite(total) && total > CANDIDATE_LIMIT) ||
    (!Number.isFinite(total) && rows.length >= CANDIDATE_LIMIT)
  ) {
    throw new Error("supabase_candidate_scan_limit_exceeded");
  }
  return rows;
}

async function persistObservation(
  supabaseUrl: string,
  serviceRoleKey: string,
  row: CandidateRow,
  observation: E12Observation,
  fetchImpl: typeof fetch,
  lease: WorkerLease,
  payload: ObservationAttestationPayload,
  attestation: ObservationAttestation,
  publicKeySpkiBase64: string,
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
      p_run_id: lease.runId,
      p_fencing_token: lease.fencingToken,
      p_attestation_version: attestation.version,
      p_attestation_algorithm: attestation.algorithm,
      p_collector_key_id: attestation.keyId,
      p_collector_public_key_spki_base64: publicKeySpkiBase64,
      p_collector_payload_canonical: new TextDecoder().decode(canonicalizeObservationPayload(payload)),
      p_collector_payload_sha256: attestation.payloadSha256,
      p_collector_signature: attestation.signatureBase64,
      p_collector_hmac_signature: attestation.hmacSignatureHex,
      p_collector_response_sha256: payload.responseBodySha256,
      p_collector_requested_ids_sha256: payload.requestedVideoIdsSha256,
      p_collector_build: payload.collectorBuild,
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

  // Reject oversized bodies before buffering. This endpoint accepts only "{}"
  // (the scheduled command) or an empty body. Stream limit also covers missing
  // or dishonest Content-Length headers.
  const declaredLength = request.headers.get("content-length");
  if (declaredLength !== null && (!/^\\d+$/.test(declaredLength) || Number(declaredLength) > 2)) {
    return jsonResponse(400, { error: "request_body_must_be_empty" });
  }
  let body = "";
  if (request.body) {
    const reader = request.body.getReader();
    const chunks: Uint8Array[] = [];
    let total = 0;
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        total += value.byteLength;
        if (total > 2) {
          await reader.cancel();
          return jsonResponse(400, { error: "request_body_must_be_empty" });
        }
        chunks.push(value);
      }
    } finally {
      reader.releaseLock();
    }
    const bytes = new Uint8Array(total);
    let offset = 0;
    for (const chunk of chunks) {
      bytes.set(chunk, offset);
      offset += chunk.byteLength;
    }
    body = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  }
  if (body !== "" && body !== "{}") {
    return jsonResponse(400, { error: "request_body_must_be_empty" });
  }
  const requestPath = new URL(request.url).pathname;
  if (
    !cronSecret ||
    !await verifyCronSignature(
      timestamp,
      signature,
      cronSecret,
      (dependencies.nowEpochSeconds ?? (() => Math.floor(Date.now() / 1_000)))(),
      request.method,
      requestPath,
      body,
    )
  ) {
    return jsonResponse(401, { error: "unauthorized" });
  }

  const supabaseUrl = dependencies.env("SUPABASE_URL");
  const serviceRoleKey = dependencies.env("SUPABASE_SERVICE_ROLE_KEY");
  const youtubeApiKey = dependencies.env("YOUTUBE_API_KEY");
  const provenanceKeyId = dependencies.env("E12_PROVENANCE_KEY_ID");
  const provenancePublicKey = dependencies.env("E12_PROVENANCE_PUBLIC_KEY_SPKI_B64");
  const provenancePrivateKey = dependencies.env("E12_PROVENANCE_PRIVATE_KEY_PKCS8_B64");
  const provenanceHmacSecret = dependencies.env("E12_PROVENANCE_HMAC_SECRET_B64");
  if (!supabaseUrl || !serviceRoleKey || !youtubeApiKey) {
    return jsonResponse(500, { error: "required_worker_secret_missing" });
  }
  if (!provenanceKeyId || !provenancePublicKey || !provenancePrivateKey || !provenanceHmacSecret) {
    return jsonResponse(500, { error: "required_provenance_key_missing" });
  }

  const fetchImpl = dependencies.fetchImpl ?? fetch;
  const clockMicros = dependencies.clockMicros ?? nowEpochMicros;
  const nowSeconds = (dependencies.nowEpochSeconds ?? (() => Math.floor(Date.now() / 1_000)))();
  const minuteBucketSeconds = Math.floor(Number(timestamp) / 60) * 60;
  const minuteBucket = new Date(minuteBucketSeconds * 1_000).toISOString();

  try {
    const slotClaimed = await claimWorkerSlot(
      supabaseUrl,
      serviceRoleKey,
      minuteBucket,
      fetchImpl,
    );
    if (!slotClaimed) {
      return jsonResponse(200, {
        skippedDuplicateInvocation: true,
        minuteBucket,
      });
    }

    const runId = (dependencies.randomUUID ?? (() => crypto.randomUUID()))();
    const leaseTtlSeconds = dependencies.leaseTtlSeconds ?? 90;
    const leaseClaim = await claimWorkerLease(
      supabaseUrl,
      serviceRoleKey,
      runId,
      leaseTtlSeconds,
      fetchImpl,
    );
    if (!leaseClaim.acquired) {
      return jsonResponse(200, {
        skippedActiveLease: true,
        minuteBucket,
      });
    }
    const lease = leaseClaim.lease;

    try {
      const candidates = await fetchPendingCandidates(
        supabaseUrl,
        serviceRoleKey,
        fetchImpl,
        nowSeconds,
      );

      if (!await renewWorkerLease(supabaseUrl, serviceRoleKey, lease, leaseTtlSeconds, fetchImpl)) {
        throw new Error("e12_worker_lease_lost");
      }

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
      const duplicateRows = duplicateVideoIds.size;

      const videoIds = [...byVideoId.keys()];
      for (let offset = 0; offset < videoIds.length; offset += YOUTUBE_BATCH_SIZE) {
        if (!await renewWorkerLease(supabaseUrl, serviceRoleKey, lease, leaseTtlSeconds, fetchImpl)) {
          throw new Error("e12_worker_lease_lost");
        }
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
          if (!await renewWorkerLease(supabaseUrl, serviceRoleKey, lease, leaseTtlSeconds, fetchImpl)) {
            throw new Error("e12_worker_lease_lost");
          }
          eligible++;
          const payload: ObservationAttestationPayload = {
            keyId: provenanceKeyId,
            runId: lease.runId,
            fencingToken: lease.fencingToken,
            rowId: String(row.id),
            videoId: observation.videoId,
            publishedAt: observation.publishedAt,
            viewCount: observation.viewCount,
            syncCapturedAt: observation.syncCapturedAt,
            responseBodySha256: observation.responseBodySha256 ?? "",
            requestedVideoIdsSha256: observation.requestedVideoIdsSha256 ?? "",
            collectorBuild: observation.collectorBuild ?? "",
          };
          const attestation = await createObservationAttestation(
            payload,
            provenancePrivateKey,
            provenanceHmacSecret,
          );
          const signatureValid = await verifyObservationAttestation(
            payload,
            attestation,
            provenancePublicKey,
            provenanceHmacSecret,
          );
          if (!signatureValid) throw new Error("e12_observation_attestation_invalid");
          const didCapture = await persistObservation(
            supabaseUrl,
            serviceRoleKey,
            row,
            observation,
            fetchImpl,
            lease,
            payload,
            attestation,
            provenancePublicKey,
          );
          if (didCapture) captured++;
          else casLost++;
        }
      }

      return jsonResponse(200, {
        candidates: candidates.length,
        uniqueCandidates: videoIds.length,
        duplicateRows,
        slotClaimed: true,
        leaseClaimed: true,
        eligible,
        captured,
        casLost,
        nonEligible,
      });
    } finally {
      // A failed release is safe: the database expiry recovers the lease.
      // The fencing token prevents this run from releasing a successor's lease.
      try {
        await releaseWorkerLease(supabaseUrl, serviceRoleKey, lease, fetchImpl);
      } catch {
        // Do not expose upstream details or credentials in the worker response.
      }
    }
  } catch (_error) {
    // Never return request URLs, API keys, Supabase keys, or upstream bodies.
    return jsonResponse(502, { error: "e12_capture_cycle_failed" });
  }
}
