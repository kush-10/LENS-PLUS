export async function startCameraStream(targetFramerate = 15): Promise<MediaStream> {
  if (!("mediaDevices" in navigator) || !navigator.mediaDevices) {
    const secureHint =
      !window.isSecureContext
        ? "Camera APIs require HTTPS on most mobile browsers (or localhost)."
        : "This browser does not expose mediaDevices APIs.";
    throw new Error(`Camera API unavailable. ${secureHint}`);
  }

  if (typeof navigator.mediaDevices.getUserMedia !== "function") {
    throw new Error("getUserMedia is not available in this browser.");
  }

  const viewportIsPortrait = window.matchMedia("(orientation: portrait)").matches;
  const idealWidth = viewportIsPortrait ? 720 : 1280;
  const idealHeight = viewportIsPortrait ? 1280 : 720;
  const idealAspectRatio = viewportIsPortrait ? 9 / 16 : 16 / 9;

  const videoConstraints: MediaTrackConstraints = {
    facingMode: { ideal: "environment" },
    width: { ideal: idealWidth },
    height: { ideal: idealHeight },
    aspectRatio: { ideal: idealAspectRatio }
  };

  if (Number.isFinite(targetFramerate) && targetFramerate > 0) {
    videoConstraints.frameRate = {
      ideal: targetFramerate,
      max: targetFramerate
    };
  }

  const fallbackConstraints: MediaStreamConstraints[] = [
    { audio: false, video: videoConstraints },
    {
      audio: false,
      video: {
        facingMode: { ideal: "environment" },
        width: { ideal: idealWidth },
        height: { ideal: idealHeight }
      }
    },
    { audio: false, video: { facingMode: { ideal: "environment" } } },
    { audio: false, video: true }
  ];

  let lastError: unknown = null;
  for (const constraints of fallbackConstraints) {
    try {
      return await navigator.mediaDevices.getUserMedia(constraints);
    } catch (error) {
      lastError = error;
    }
  }

  throw new Error(`Unable to start camera: ${formatCameraError(lastError)}`);
}

function formatCameraError(error: unknown): string {
  if (error instanceof DOMException) {
    return error.message ? `${error.name}: ${error.message}` : error.name;
  }

  return String(error);
}

export function stopStream(stream: MediaStream | null): void {
  if (!stream) {
    return;
  }
  for (const track of stream.getTracks()) {
    track.stop();
  }
}
