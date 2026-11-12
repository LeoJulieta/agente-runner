import {
  canonicalizeObservationPayload,
  createObservationAttestation,
  hashRequestedVideoIds,
  verifyObservationAttestation,
  type ObservationAttestationPayload,
} from "./provenance.ts";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

const HMAC_SECRET_BASE64 = btoa(String.fromCharCode(...new Uint8Array(32).fill(7)));

const PAYLOAD: ObservationAttestationPayload = {
  keyId: "e12-collector-test-2026-01",
  runId: "11111111-2222-4333-8444-555555555555",
  fencingToken: "9007199254740993",
  rowId: "42",
  videoId: "video-1",
  publishedAt: "2026-10-30T02:30:00Z",
  viewCount: "18446744073709551615",
  syncCapturedAt: "2026-10-30T05:30:00.123456Z",
  responseBodySha256: "a".repeat(64),
  requestedVideoIdsSha256: "b".repeat(64),
  collectorBuild: "e12-collector/0.1.0",
};

Deno.test("Ed25519 attestation verifies and binds exact observation values", async () => {
  const pair = await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"]) as CryptoKeyPair;
  const privateBytes = new Uint8Array(await crypto.subtle.exportKey("pkcs8", pair.privateKey));
  const publicBytes = new Uint8Array(await crypto.subtle.exportKey("spki", pair.publicKey));
  const toBase64 = (bytes: Uint8Array) => {
    let binary = "";
    for (const byte of bytes) binary += String.fromCharCode(byte);
    return btoa(binary);
  };
  const privateKey = toBase64(privateBytes);
  const publicKey = toBase64(publicBytes);

  const attestation = await createObservationAttestation(PAYLOAD, privateKey, HMAC_SECRET_BASE64);
  assert(attestation.payloadSha256.length === 64, "payload digest must be SHA-256 hex");
  assert(
    attestation.hmacSignatureHex === "6d453d4d60ea19168802afbae6242f043db9a09952e68b10f6c97f42244d3afd",
    "WebCrypto HMAC must match the independently computed SHA-256 test vector",
  );
  assert(await verifyObservationAttestation(PAYLOAD, attestation, publicKey, HMAC_SECRET_BASE64), "signature should verify");

  const altered = { ...PAYLOAD, viewCount: "18446744073709551614" };
  assert(!await verifyObservationAttestation(altered, attestation, publicKey, HMAC_SECRET_BASE64), "altered count must fail verification");
  const alteredResponse = { ...PAYLOAD, responseBodySha256: "c".repeat(64) };
  assert(!await verifyObservationAttestation(alteredResponse, attestation, publicKey, HMAC_SECRET_BASE64), "altered response digest must fail");
  assert(!await verifyObservationAttestation(
    PAYLOAD,
    { ...attestation, hmacSignatureHex: "0".repeat(64) },
    publicKey,
    HMAC_SECRET_BASE64,
  ), "altered database HMAC must fail verification");
});

Deno.test("canonicalization binds field order, run, fencing token, row and key identity", () => {
  const first = canonicalizeObservationPayload(PAYLOAD);
  const second = canonicalizeObservationPayload({ ...PAYLOAD });
  assert(new TextDecoder().decode(first) === new TextDecoder().decode(second), "same values must canonicalize deterministically");
  assert(
    new TextDecoder().decode(first) !== new TextDecoder().decode(canonicalizeObservationPayload({ ...PAYLOAD, rowId: "43" })),
    "row identity must be part of the signed payload",
  );
  assert(
    new TextDecoder().decode(first) !== new TextDecoder().decode(canonicalizeObservationPayload({ ...PAYLOAD, fencingToken: "9007199254740994" })),
    "fencing token must be part of the signed payload",
  );
  assert(
    new TextDecoder().decode(first) !== new TextDecoder().decode(canonicalizeObservationPayload({ ...PAYLOAD, keyId: "e12-collector-test-2026-02" })),
    "key rotation identity must be part of the signed payload",
  );
});

Deno.test("requested video IDs hash is order-independent and rejects duplicates", async () => {
  const first = await hashRequestedVideoIds(["video-2", "video-1"]);
  const second = await hashRequestedVideoIds(["video-1", "video-2"]);
  assert(first === second, "request set hash should be order-independent");
  let rejected = false;
  try { await hashRequestedVideoIds(["video-1", "video-1"]); } catch { rejected = true; }
  assert(rejected, "duplicate requested IDs must reject");
});

Deno.test("attestation rejects malformed payloads and mismatched key IDs", async () => {
  let invalidRejected = false;
  try {
    await createObservationAttestation({ ...PAYLOAD, viewCount: "18446744073709551616" }, "AA==", HMAC_SECRET_BASE64);
  } catch { invalidRejected = true; }
  assert(invalidRejected, "uint64 overflow must reject before key import");

  const pair = await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"]) as CryptoKeyPair;
  const privateBytes = new Uint8Array(await crypto.subtle.exportKey("pkcs8", pair.privateKey));
  const publicBytes = new Uint8Array(await crypto.subtle.exportKey("spki", pair.publicKey));
  const b64 = (bytes: Uint8Array) => {
    let binary = "";
    for (const byte of bytes) binary += String.fromCharCode(byte);
    return btoa(binary);
  };
  const attestation = await createObservationAttestation(PAYLOAD, b64(privateBytes), HMAC_SECRET_BASE64);
  assert(!await verifyObservationAttestation(
    { ...PAYLOAD, keyId: "different-key" },
    attestation,
    b64(publicBytes),
    HMAC_SECRET_BASE64,
  ), "unknown key identity must fail verification");
});
