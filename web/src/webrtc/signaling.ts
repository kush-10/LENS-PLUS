type OfferRequest = {
  sdp: string;
  type: RTCSdpType;
  session_id?: string;
};

type OfferResponse = {
  sdp: string;
  type: RTCSdpType;
  session_id: string;
};

type IceRequest = {
  session_id: string;
  candidate: string;
  sdpMid?: string | null;
  sdpMLineIndex?: number | null;
};

const DEFAULT_BASE_URL = "/api";

const configuredBaseUrl = import.meta.env.VITE_SIGNALING_BASE_URL;
const baseUrl = resolveSignalingBaseUrl(configuredBaseUrl);

export function getSignalingBaseUrl(): string {
  return baseUrl;
}

function resolveSignalingBaseUrl(configuredUrl: unknown): string {
  const trimmedUrl = typeof configuredUrl === "string" ? configuredUrl.trim() : "";
  if (!trimmedUrl) {
    return DEFAULT_BASE_URL;
  }

  try {
    const url = new URL(trimmedUrl, window.location.origin);
    const pageIsLocal = isLocalHostname(window.location.hostname);
    const targetIsLocal = isLocalHostname(url.hostname);
    if ((targetIsLocal && !pageIsLocal) || isBlockedMixedContent(url)) {
      return DEFAULT_BASE_URL;
    }
  } catch {
    return trimmedUrl.replace(/\/$/, "");
  }

  return trimmedUrl.replace(/\/$/, "");
}

function isLocalHostname(hostname: string): boolean {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1";
}

function isBlockedMixedContent(url: URL): boolean {
  return window.location.protocol === "https:" && url.protocol === "http:";
}

export async function sendOffer(payload: OfferRequest): Promise<OfferResponse> {
  const response = await fetch(`${baseUrl}/webrtc/offer`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });

  if (!response.ok) {
    throw new Error(`Offer failed with status ${response.status}`);
  }

  return (await response.json()) as OfferResponse;
}

export async function sendIceCandidate(payload: IceRequest): Promise<void> {
  const response = await fetch(`${baseUrl}/webrtc/ice`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });

  if (!response.ok) {
    throw new Error(`ICE failed with status ${response.status}`);
  }
}
