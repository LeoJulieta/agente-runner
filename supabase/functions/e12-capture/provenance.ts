import { YOUTUBE_UINT64_MAX } from "./collector.ts";

export const E12_ATTESTATION_VERSION = "e12-observation-attestation/v1";
export const E12_ATTESTATION_ALGORITHM = "Ed25519";

export type ObservationAttestationPayload = {
  keyId: string;
  runId: string;
  rowId: string;
  videoId: string;
  publishedAt: string;
  viewCount: string;
  syncCapturedAt: string;
  responseBodySha256: string;
  requestedVideoIdsSha256: string;
  collectorBuild: string;
};

export type ObservationAttestation = {
  version: typeof E12_ATTESTATION_VERSION;
  algorithm: typeof E12_ATTESTATION_ALGORITHM;
  keyId: string;
  payloadSha256: string;
  signatureBase64: string;
};

function assertPayload(payload: ObservationAttestationPayload): void {
  if (!/^[a-z0-9][a-z0-9._-]{0,63}$/i.test(payload.keyId)) {
    throw new Error("e12_attestation_key_id_invalid");
  }
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(payload.runId)) {
    throw new Error("e12_attestation_run_id_invalid");
  }
  if (!/^\d+$/.test(payload.rowId) || !payload.videoId.trim()) {
    throw new Error("e12_attestation_identity_invalid");
  }
  if (!/^\d+$/.test(payload.viewCount) || BigInt(payload.viewCount) > YOUTUBE_UINT64_MAX) {
    throw new Error("e12_attestation_view_count_invalid");
  }
  if (!Number.isFinite(Date.parse(payload.publishedAt)) ||
      !Number.isFinite(Date.parse(payload.syncCapturedAt))) {
    throw new Error("e12_attestation_timestamp_invalid");
  }
  if (!/^[a-f0-9]{64}$/.test(payload.responseBodySha256) ||
      !/^[a-f0-9]{64}$/.test(payload.requestedVideoIdsSha256)) {
    throw new Error("e12_attestation_digest_invalid");
  }
  if (!/^[a-zA-Z0-9._+\/-]{1,96}$/.test(payload.collectorBuild)) {
    throw new Error("e12_attestation_build_invalid");
  }
}

export function canonicalizeObservationPayload(payload: ObservationAttestationPayload): Uint8Array {
  assertPayload(payload);
  // Fixed-order JSON array avoids object-key ordering and delimiter ambiguity.
  const canonical = JSON.stringify([
    E12_ATTESTATION_VERSION,
    payload.keyId,
    payload.runId,
    payload.rowId,
    payload.videoId,
    payload.publishedAt,
    payload.viewCount,
    payload.syncCapturedAt,
    payload.responseBodySha256,
    payload.requestedVideoIdsSha256,
    payload.collectorBuild,
  ]);
  return new TextEncoder().encode(canonical);
}

function toArrayBuffer(bytes: Uint8Array): ArrayBuffer {
  const copy = new Uint8Array(bytes.byteLength);
  copy.set(bytes);
  return copy.buffer;
}

async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", toArrayBuffer(bytes)));
  return Array.from(digest, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function decodeBase64(value: string): ArrayBuffer {
  if (!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value)) {
    throw new Error("e12_attestation_base64_invalid");
  }
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index++) bytes[index] = binary.charCodeAt(index);
  return bytes.buffer;
}

function encodeBase64(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

export async function hashRequestedVideoIds(videoIds: string[]): Promise<string> {
  if (videoIds.length < 1 || videoIds.length > 50 ||
      videoIds.some((id) => !id.trim()) || new Set(videoIds).size !== videoIds.length) {
    throw new Error("e12_attestation_requested_ids_invalid");
  }
  const canonical = JSON.stringify([...videoIds].sort());
  return await sha256Hex(new TextEncoder().encode(canonical));
}

export async function createObservationAttestation(
  payload: ObservationAttestationPayload,
  privateKeyPkcs8Base64: string,
): Promise<ObservationAttestation> {
  const canonical = canonicalizeObservationPayload(payload);
  const privateKey = await crypto.subtle.importKey(
    "pkcs8",
    decodeBase64(privateKeyPkcs8Base64),
    { name: "Ed25519" },
    false,
    ["sign"],
  );
  const signature = new Uint8Array(await crypto.subtle.sign("Ed25519", privateKey, toArrayBuffer(canonical)));
  return {
    version: E12_ATTESTATION_VERSION,
    algorithm: E12_ATTESTATION_ALGORITHM,
    keyId: payload.keyId,
    payloadSha256: await sha256Hex(canonical),
    signatureBase64: encodeBase64(signature),
  };
}

export async function verifyObservationAttestation(
  payload: ObservationAttestationPayload,
  attestation: ObservationAttestation,
  publicKeySpkiBase64: string,
): Promise<boolean> {
  if (attestation.version !== E12_ATTESTATION_VERSION ||
      attestation.algorithm !== E12_ATTESTATION_ALGORITHM ||
      attestation.keyId !== payload.keyId) return false;
  try {
    const canonical = canonicalizeObservationPayload(payload);
    const digest = await sha256Hex(canonical);
    if (digest !== attestation.payloadSha256) return false;
    const publicKey = await crypto.subtle.importKey(
      "spki",
      decodeBase64(publicKeySpkiBase64),
      { name: "Ed25519" },
      false,
      ["verify"],
    );
    return await crypto.subtle.verify(
      "Ed25519",
      publicKey,
      decodeBase64(attestation.signatureBase64),
      toArrayBuffer(canonical),
    );
  } catch {
    return false;
  }
}
