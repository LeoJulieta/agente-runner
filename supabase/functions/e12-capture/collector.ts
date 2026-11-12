export const E12_MIN_ELAPSED_MICROS = 10_500_000_000n;
export const E12_MAX_ELAPSED_MICROS = 11_100_000_000n;
export const YOUTUBE_MAX_RESPONSE_BYTES = 1_048_576;
export const YOUTUBE_UINT64_MAX = 18_446_744_073_709_551_615n;

export type E12Observation = {
  videoId: string;
  viewCount: string;
  publishedAt: string;
  syncCapturedAt: string;
  elapsedSeconds: string;
  elapsedMicros: bigint;
  eligible: boolean;
  reason: "eligible" | "published_at_in_future" | "outside_e12_window";
};

export type ClockMicros = () => bigint;

export function nowEpochMicros(): bigint {
  const epochMilliseconds = performance.timeOrigin + performance.now();
  return BigInt(Math.floor(epochMilliseconds * 1_000));
}

export function parseRfc3339EpochMicros(value: string): bigint {
  const match = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})$/.exec(value);
  if (!match) throw new Error("published_at_invalid_rfc3339");

  const baseMilliseconds = Date.parse(match[1] + match[3]);
  if (!Number.isFinite(baseMilliseconds) || baseMilliseconds % 1_000 !== 0) {
    throw new Error("published_at_invalid_timestamp");
  }

  const fraction = match[2] ?? "";
  if (fraction.length > 6 && /[1-9]/.test(fraction.slice(6))) {
    throw new Error("published_at_precision_exceeds_microseconds");
  }
  const micros = fraction.slice(0, 6).padEnd(6, "0");
  return BigInt(baseMilliseconds) * 1_000n + BigInt(micros || "0");
}

export function formatEpochMicros(epochMicros: bigint): string {
  const seconds = epochMicros / 1_000_000n;
  const micros = epochMicros % 1_000_000n;
  const base = new Date(Number(seconds) * 1_000).toISOString().slice(0, 19);
  return `${base}.${micros.toString().padStart(6, "0")}Z`;
}

function parseViewCount(value: unknown): string {
  if (typeof value !== "string" || !/^\d+$/.test(value)) {
    throw new Error("youtube_view_count_not_decimal_string");
  }
  const parsed = BigInt(value);
  if (parsed > YOUTUBE_UINT64_MAX) throw new Error("youtube_view_count_exceeds_uint64");
  return parsed.toString();
}

function formatElapsedSeconds(elapsedMicros: bigint): string {
  const sign = elapsedMicros < 0n ? "-" : "";
  const absolute = elapsedMicros < 0n ? -elapsedMicros : elapsedMicros;
  const whole = absolute / 1_000_000n;
  const fraction = absolute % 1_000_000n;
  return `${sign}${whole.toString()}.${fraction.toString().padStart(6, "0")}`;
}

export function parseYouTubeVideosResponse(
  bodyText: string,
  requestedVideoIds: string[],
  syncCapturedAtMicros: bigint,
): E12Observation[] {
  const payload: unknown = JSON.parse(bodyText);
  if (!payload || typeof payload !== "object" || !Array.isArray((payload as { items?: unknown }).items)) {
    throw new Error("youtube_response_items_missing");
  }

  const requested = new Set(requestedVideoIds);
  if (requested.size !== requestedVideoIds.length || requested.size === 0) {
    throw new Error("requested_video_ids_invalid_or_duplicated");
  }

  const seen = new Set<string>();
  const observations: E12Observation[] = [];
  for (const rawItem of (payload as { items: unknown[] }).items) {
    if (!rawItem || typeof rawItem !== "object") throw new Error("youtube_item_invalid");
    const item = rawItem as {
      id?: unknown;
      snippet?: { publishedAt?: unknown };
      statistics?: { viewCount?: unknown };
      status?: { privacyStatus?: unknown };
    };

    if (typeof item.id !== "string" || !requested.has(item.id)) {
      throw new Error("youtube_response_contains_unrequested_video");
    }
    if (seen.has(item.id)) throw new Error("youtube_response_contains_duplicate_video");
    seen.add(item.id);

    // E12 is defined only for public videos; private/unlisted/deleted items
    // are deliberately excluded rather than treated as zero views.
    if (item.status?.privacyStatus !== "public") continue;

    if (typeof item.snippet?.publishedAt !== "string") {
      throw new Error("youtube_published_at_missing");
    }
    const viewCount = parseViewCount(item.statistics?.viewCount);
    const publishedAtMicros = parseRfc3339EpochMicros(item.snippet.publishedAt);
    const elapsedMicros = syncCapturedAtMicros - publishedAtMicros;
    const eligible = elapsedMicros >= E12_MIN_ELAPSED_MICROS &&
      elapsedMicros <= E12_MAX_ELAPSED_MICROS;

    observations.push({
      videoId: item.id,
      viewCount,
      publishedAt: item.snippet.publishedAt,
      syncCapturedAt: formatEpochMicros(syncCapturedAtMicros),
      elapsedSeconds: formatElapsedSeconds(elapsedMicros),
      elapsedMicros,
      eligible,
      reason: elapsedMicros < 0n ? "published_at_in_future" : eligible ? "eligible" : "outside_e12_window",
    });
  }
  return observations;
}

async function readBoundedBody(
  response: Response,
  clockMicros: ClockMicros,
): Promise<{ bodyText: string; capturedAtMicros: bigint }> {
  const reader = response.body?.getReader();
  if (!reader) {
    const bytes = new Uint8Array(await response.arrayBuffer());
    const capturedAtMicros = clockMicros();
    if (bytes.byteLength > YOUTUBE_MAX_RESPONSE_BYTES) {
      throw new Error("youtube_response_too_large");
    }
    return { bodyText: new TextDecoder().decode(bytes), capturedAtMicros };
  }

  const chunks: Uint8Array[] = [];
  let totalBytes = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    if (value) {
      totalBytes += value.byteLength;
      if (totalBytes > YOUTUBE_MAX_RESPONSE_BYTES) {
        await reader.cancel();
        throw new Error("youtube_response_too_large");
      }
      chunks.push(value);
    }
  }

  // Timestamp is taken immediately after the complete response body is read,
  // before decoding or parsing it.
  const capturedAtMicros = clockMicros();
  const bytes = new Uint8Array(totalBytes);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return { bodyText: new TextDecoder().decode(bytes), capturedAtMicros };
}

export async function collectYouTubeBatch(
  videoIds: string[],
  apiKey: string,
  fetchImpl: typeof fetch = fetch,
  clockMicros: ClockMicros = nowEpochMicros,
): Promise<E12Observation[]> {
  if (!Array.isArray(videoIds) || videoIds.length < 1 || videoIds.length > 50) {
    throw new Error("youtube_batch_size_must_be_1_to_50");
  }
  if (
    videoIds.some((id) => typeof id !== "string" || !id.trim()) ||
    new Set(videoIds).size !== videoIds.length
  ) {
    throw new Error("youtube_video_ids_invalid_or_duplicated");
  }
  if (!apiKey) throw new Error("youtube_api_key_missing");

  const url = new URL("https://www.googleapis.com/youtube/v3/videos");
  url.searchParams.set("part", "snippet,statistics,status");
  url.searchParams.set("id", videoIds.join(","));
  url.searchParams.set("key", apiKey);

  const response = await fetchImpl(url, {
    method: "GET",
    headers: { Accept: "application/json" },
    signal: AbortSignal.timeout(15_000),
  });
  if (!response.ok) throw new Error(`youtube_http_${response.status}`);

  const { bodyText, capturedAtMicros } = await readBoundedBody(response, clockMicros);
  return parseYouTubeVideosResponse(bodyText, videoIds, capturedAtMicros);
}
