import {
  collectYouTubeBatch,
  E12_MAX_ELAPSED_MICROS,
  E12_MIN_ELAPSED_MICROS,
  formatEpochMicros,
  parseRfc3339EpochMicros,
  parseYouTubeVideosResponse,
  YOUTUBE_MAX_RESPONSE_BYTES,
  YOUTUBE_UINT64_MAX,
} from "./collector.ts";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

function videoPayload(overrides: Record<string, unknown> = {}) {
  return {
    items: [{
      id: "video-1",
      snippet: { publishedAt: "2026-10-30T02:30:00Z" },
      statistics: { viewCount: "123" },
      status: { privacyStatus: "public" },
      ...overrides,
    }],
  };
}

Deno.test("E12 lower and upper window edges are inclusive", () => {
  const published = parseRfc3339EpochMicros("2026-10-30T02:30:00Z");
  const lower = parseYouTubeVideosResponse(
    JSON.stringify(videoPayload()),
    ["video-1"],
    published + E12_MIN_ELAPSED_MICROS,
  )[0];
  const upper = parseYouTubeVideosResponse(
    JSON.stringify(videoPayload()),
    ["video-1"],
    published + E12_MAX_ELAPSED_MICROS,
  )[0];

  assert(lower.eligible, "2:55 must be eligible");
  assert(lower.elapsedSeconds === "10500.000000", "lower elapsed must be exact");
  assert(upper.eligible, "3:05 must be eligible");
  assert(upper.elapsedSeconds === "11100.000000", "upper elapsed must be exact");
});

Deno.test("E12 rejects observations immediately outside the closed window", () => {
  const published = parseRfc3339EpochMicros("2026-10-30T02:30:00Z");
  const before = parseYouTubeVideosResponse(
    JSON.stringify(videoPayload()),
    ["video-1"],
    published + E12_MIN_ELAPSED_MICROS - 1n,
  )[0];
  const after = parseYouTubeVideosResponse(
    JSON.stringify(videoPayload()),
    ["video-1"],
    published + E12_MAX_ELAPSED_MICROS + 1n,
  )[0];

  assert(!before.eligible && before.reason === "outside_e12_window", "one microsecond before must be excluded");
  assert(!after.eligible && after.reason === "outside_e12_window", "one microsecond after must be excluded");
});

Deno.test("RFC3339 timezone offsets and microseconds are preserved", () => {
  const utc = parseRfc3339EpochMicros("2026-10-30T02:30:00.123456Z");
  const offset = parseRfc3339EpochMicros("2026-10-30T05:30:00.123456+03:00");
  assert(utc === offset, "equivalent offsets must resolve to the same instant");
  assert(formatEpochMicros(utc) === "2026-10-30T02:30:00.123456Z", "microsecond formatting must round-trip");
});

Deno.test("viewCount preserves the exact unsigned 64-bit value", () => {
  const result = parseYouTubeVideosResponse(
    JSON.stringify(videoPayload({ statistics: { viewCount: YOUTUBE_UINT64_MAX.toString() } })),
    ["video-1"],
    parseRfc3339EpochMicros("2026-10-30T05:30:00Z"),
  )[0];
  assert(result.viewCount === YOUTUBE_UINT64_MAX.toString(), "uint64 must not pass through Number");
});

Deno.test("viewCount rejects values outside uint64 and non-decimal types", () => {
  for (const invalid of ["18446744073709551616", "1.5", "-1", " 1", 1, true]) {
    let threw = false;
    try {
      parseYouTubeVideosResponse(
        JSON.stringify(videoPayload({ statistics: { viewCount: invalid } })),
        ["video-1"],
        parseRfc3339EpochMicros("2026-10-30T05:30:00Z"),
      );
    } catch {
      threw = true;
    }
    assert(threw, `invalid viewCount should reject: ${String(invalid)}`);
  }
});

Deno.test("non-public videos are excluded, not converted to zero views", () => {
  const result = parseYouTubeVideosResponse(
    JSON.stringify(videoPayload({ status: { privacyStatus: "unlisted" } })),
    ["video-1"],
    parseRfc3339EpochMicros("2026-10-30T05:30:00Z"),
  );
  assert(result.length === 0, "non-public video must not produce an observation");
});

Deno.test("collector rejects unrequested and duplicate video IDs", () => {
  for (const payload of [
    { items: [{ id: "other", status: { privacyStatus: "public" }, snippet: { publishedAt: "2026-10-30T02:30:00Z" }, statistics: { viewCount: "1" } }] },
    { items: [
      { id: "video-1", status: { privacyStatus: "public" }, snippet: { publishedAt: "2026-10-30T02:30:00Z" }, statistics: { viewCount: "1" } },
      { id: "video-1", status: { privacyStatus: "public" }, snippet: { publishedAt: "2026-10-30T02:30:00Z" }, statistics: { viewCount: "1" } },
    ] },
  ]) {
    let threw = false;
    try {
      parseYouTubeVideosResponse(
        JSON.stringify(payload),
        ["video-1"],
        parseRfc3339EpochMicros("2026-10-30T05:30:00Z"),
      );
    } catch {
      threw = true;
    }
    assert(threw, "unrequested or duplicate item must fail closed");
  }
});

Deno.test("collector captures timestamp after complete HTTP body read", async () => {
  let bodyComplete = false;
  let clockCalledAfterBody = false;
  const body = JSON.stringify(videoPayload());
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(body));
      controller.close();
      bodyComplete = true;
    },
  });
  const fixedCapture = parseRfc3339EpochMicros("2026-10-30T05:30:00.123456Z");

  const result = await collectYouTubeBatch(
    ["video-1"],
    "test-key",
    async () => new Response(stream, { status: 200 }),
    () => {
      clockCalledAfterBody = bodyComplete;
      return fixedCapture;
    },
  );

  assert(clockCalledAfterBody, "capture clock must run only after body completion");
  assert(result[0].syncCapturedAt === "2026-10-30T05:30:00.123456Z", "capture timestamp must preserve microseconds");
});

Deno.test("collector enforces the one-megabyte response limit", async () => {
  const oversized = new Uint8Array(YOUTUBE_MAX_RESPONSE_BYTES + 1);
  let threw = false;
  try {
    await collectYouTubeBatch(
      ["video-1"],
      "test-key",
      async () => new Response(oversized, { status: 200 }),
      () => 1_800_000_000_000_000n,
    );
  } catch (error) {
    threw = error instanceof Error && error.message === "youtube_response_too_large";
  }
  assert(threw, "oversized YouTube response must be rejected");
});
