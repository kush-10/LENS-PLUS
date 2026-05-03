import "./styles.css";
import { startCameraStream, stopStream } from "./media/cameraSource";
import type { InferenceMessage } from "./types/messages";
import { isInferenceMessage } from "./types/messages";
import { UiLogger } from "./ui/logger";
import { WebRtcClient } from "./webrtc/client";
import { getSignalingBaseUrl } from "./webrtc/signaling";

type PageName = "home" | "camera" | "admin";
type ThemeName = "dark" | "light";
type StatusTone = "up" | "warn" | "down" | "neutral";

const QUESTION_STAGE_LABELS: Record<string, string> = {
  idle: "Idle",
  connecting: "Connecting",
  ready: "Ready",
  listening: "Listening",
  waiting: "Waiting",
  running_vlm: "VLM",
  waiting_model_context: "Context",
  model_context_ready: "Context Ready",
  model_context_unavailable: "Context Missing",
  running_llm: "LLM",
  generating_speech: "TTS",
  complete: "Complete"
};

type SpeechRecognitionAlternativeLike = {
  transcript: string;
};

type SpeechRecognitionResultLike = {
  readonly isFinal: boolean;
  readonly length: number;
  readonly [index: number]: SpeechRecognitionAlternativeLike;
};

type SpeechRecognitionResultListLike = {
  readonly length: number;
  readonly [index: number]: SpeechRecognitionResultLike;
};

type SpeechRecognitionEventLike = Event & {
  readonly results: SpeechRecognitionResultListLike;
};

type SpeechRecognitionErrorEventLike = Event & {
  readonly error?: string;
  readonly message?: string;
};

type SpeechRecognitionLike = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: ((event: SpeechRecognitionErrorEventLike) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
};

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike;

type SpeechRecognitionWindow = Window & {
  SpeechRecognition?: SpeechRecognitionConstructor;
  webkitSpeechRecognition?: SpeechRecognitionConstructor;
};

type AudioContextWindow = Window & {
  webkitAudioContext?: typeof AudioContext;
};

const SEND_TARGET_FPS = 30;
const LANDSCAPE_FEED_WIDTH = 1280;
const LANDSCAPE_FEED_HEIGHT = 720;
const ADMIN_PREVIEW_POLL_MS = 750;
const THEME_STORAGE_KEY = "lensplus-theme";
const MAX_PROCESS_EVENTS = 24;

type DebugSession = {
  session_id: string;
  connection_state: string;
  ice_state: string;
  analysis_target_fps: number;
  total_frames: number;
  processed_frames: number;
  dropped_frames: number;
  incoming_fps: number;
  processed_fps: number;
  last_frame_at: string | null;
  latest_jpeg_at: string | null;
  has_snapshot: boolean;
  snapshot_errors: number;
  last_snapshot_error: string | null;
  updated_at: string;
};

type LandscapeFeedOutput = {
  stream: MediaStream;
  stop(): void;
};

type RawDebugSession = Partial<DebugSession> & { session_id: string };

function mustQuery<T extends Element>(selector: string): T {
  const node = document.querySelector<T>(selector);
  if (!node) {
    throw new Error(`Missing element: ${selector}`);
  }
  return node;
}

function loadStoredTheme(): ThemeName | null {
  try {
    const storedTheme = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (storedTheme === "dark" || storedTheme === "light") {
      return storedTheme;
    }
    return null;
  } catch {
    return null;
  }
}

function saveStoredTheme(theme: ThemeName): void {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    return;
  }
}

function formatFps(value: number): string {
  if (!Number.isFinite(value) || value < 0) {
    return "0.0";
  }
  return value.toFixed(1);
}

function humanizeState(rawState: string): string {
  const normalized = rawState.trim();
  if (!normalized) {
    return "N/A";
  }

  return normalized
    .replace(/_/g, " ")
    .split(" ")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function toneForPeerState(rawState: string): StatusTone {
  const state = rawState.toLowerCase();
  if (state === "connected") {
    return "up";
  }
  if (state === "new" || state === "connecting" || state === "disconnected") {
    return "warn";
  }
  if (state === "failed") {
    return "down";
  }
  return "neutral";
}

function toneForIceState(rawState: string): StatusTone {
  const state = rawState.toLowerCase();
  if (state === "connected" || state === "completed") {
    return "up";
  }
  if (state === "new" || state === "checking" || state === "disconnected") {
    return "warn";
  }
  if (state === "failed") {
    return "down";
  }
  return "neutral";
}

function toneForHealth(rawStatus: string): StatusTone {
  if (rawStatus === "ok") {
    return "up";
  }
  if (rawStatus === "unreachable") {
    return "down";
  }
  return "warn";
}

function createStatusPill(label: string, tone: StatusTone): HTMLElement {
  const pill = document.createElement("span");
  pill.className = `status-pill tone-${tone}`;
  pill.textContent = label;
  return pill;
}

function setBadgeCell(target: HTMLElement, label: string, tone: StatusTone): void {
  target.innerHTML = "";
  target.classList.remove("value-mono");
  target.appendChild(createStatusPill(label, tone));
}

function setTextCell(target: HTMLElement, value: string, monospace = false): void {
  target.textContent = value;
  target.classList.toggle("value-mono", monospace);
}

function normalizeDebugSession(session: RawDebugSession): DebugSession {
  return {
    session_id: session.session_id,
    connection_state: session.connection_state ?? "unknown",
    ice_state: session.ice_state ?? "unknown",
    analysis_target_fps:
      typeof session.analysis_target_fps === "number" ? session.analysis_target_fps : 0,
    total_frames: typeof session.total_frames === "number" ? session.total_frames : 0,
    processed_frames:
      typeof session.processed_frames === "number" ? session.processed_frames : 0,
    dropped_frames: typeof session.dropped_frames === "number" ? session.dropped_frames : 0,
    incoming_fps: typeof session.incoming_fps === "number" ? session.incoming_fps : 0,
    processed_fps: typeof session.processed_fps === "number" ? session.processed_fps : 0,
    last_frame_at: session.last_frame_at ?? null,
    latest_jpeg_at: session.latest_jpeg_at ?? null,
    has_snapshot: Boolean(session.has_snapshot),
    snapshot_errors:
      typeof session.snapshot_errors === "number" ? session.snapshot_errors : 0,
    last_snapshot_error: session.last_snapshot_error ?? null,
    updated_at: session.updated_at ?? ""
  };
}

const app = document.querySelector<HTMLDivElement>("#app");
if (!app) {
  throw new Error("#app not found");
}

app.innerHTML = `
  <main class="app-shell">
    <div class="global-actions">
      <button id="top-home" class="ghost home-control hidden" type="button">Home</button>
      <button id="theme-toggle" class="ghost theme-toggle" type="button">Light mode</button>
    </div>

    <section id="home-page" class="page home-page">
      <h1>LENS+ Control</h1>
      <p>Select where you want to work.</p>
      <div class="home-actions">
        <button id="go-camera" class="primary">Camera</button>
        <button id="go-admin">Admin Panel</button>
      </div>
    </section>

    <section id="camera-page" class="page camera-page hidden">
      <div class="camera-wrap">
        <video id="camera-preview" autoplay muted playsinline></video>
      </div>
      <div class="camera-actions">
        <button id="start-feed" class="primary">Start Feed</button>
        <button id="camera-record-question" class="camera-record-box" type="button">Record Question</button>
      </div>
      <section class="camera-question-panel" aria-live="polite">
        <div class="camera-question-block">
          <span>Speech to text</span>
          <p id="question-transcript" class="camera-question-text is-muted">Record a question to see the transcript here.</p>
        </div>
        <div class="camera-question-block">
          <span>Assistant response</span>
          <div class="camera-response-box">
            <span id="answer-stage-badge" class="answer-stage-badge" aria-label="Assistant response stage">Idle</span>
            <p id="answer-output" class="camera-question-text">No answer yet.</p>
          </div>
        </div>
      </section>
    </section>

    <section id="admin-page" class="page hidden">
      <section class="panel">
        <h2>Feeds</h2>
        <div class="feed-grid">
          <figure class="feed-box">
            <figcaption>Live Feed</figcaption>
            <div class="feed-stage">
              <img id="admin-live-preview" alt="Latest frame from selected session" hidden />
              <p id="admin-live-status" class="feed-status">No active session.</p>
            </div>
          </figure>
        </div>
      </section>

      <section class="panel">
        <div class="panel-title-row">
          <h2>System Status Dashboard</h2>
          <span id="connection-badge" class="status-badge is-neutral">Disconnected</span>
        </div>

        <table class="status-table">
          <tbody>
            <tr>
              <th>API Health</th>
              <td id="status-api"></td>
            </tr>
            <tr>
              <th>Peer State</th>
              <td id="status-peer"></td>
            </tr>
            <tr>
              <th>ICE State</th>
              <td id="status-ice"></td>
            </tr>
            <tr>
              <th>Session ID</th>
              <td id="status-session-id"></td>
            </tr>
            <tr>
              <th>Session Count</th>
              <td id="status-session-count"></td>
            </tr>
            <tr>
              <th>Send Target FPS</th>
              <td id="status-send-fps"></td>
            </tr>
            <tr>
              <th>Analysis Target FPS</th>
              <td id="status-analysis-fps"></td>
            </tr>
            <tr>
              <th>Incoming FPS</th>
              <td id="status-incoming-fps"></td>
            </tr>
            <tr>
              <th>Processed FPS</th>
              <td id="status-processed-fps"></td>
            </tr>
            <tr>
              <th>Dropped Frames</th>
              <td id="status-dropped-frames"></td>
            </tr>
            <tr>
              <th>Total Frames Received</th>
              <td id="status-total-frames"></td>
            </tr>
          </tbody>
        </table>
      </section>

      <section class="panel process-panel">
        <div class="panel-title-row">
          <h2>Process Status</h2>
          <button id="process-status-toggle" class="ghost" type="button" aria-expanded="false">
            Show Process Status
          </button>
        </div>
        <div id="process-status-body" class="process-status-body hidden">
          <div class="process-status-grid">
            <div class="process-status-card">
              <span>Feed</span>
              <strong id="admin-feed-status">Camera idle.</strong>
            </div>
            <div class="process-status-card">
              <span>Question</span>
              <strong id="admin-question-status">idle</strong>
            </div>
            <div class="process-status-card">
              <span>Question to response</span>
              <strong id="admin-response-time">n/a</strong>
            </div>
          </div>
          <ul id="process-event-log" class="process-event-log"></ul>
        </div>
      </section>

      <section class="panel">
        <h2>Logs</h2>
        <ul id="event-log"></ul>
      </section>
    </section>
  </main>
`;

const homePageEl = mustQuery<HTMLElement>("#home-page");
const cameraPageEl = mustQuery<HTMLElement>("#camera-page");
const adminPageEl = mustQuery<HTMLElement>("#admin-page");
const topHomeEl = mustQuery<HTMLButtonElement>("#top-home");
const themeToggleEl = mustQuery<HTMLButtonElement>("#theme-toggle");
const goCameraEl = mustQuery<HTMLButtonElement>("#go-camera");
const goAdminEl = mustQuery<HTMLButtonElement>("#go-admin");
const startFeedEl = mustQuery<HTMLButtonElement>("#start-feed");
const cameraRecordQuestionEl = mustQuery<HTMLButtonElement>("#camera-record-question");
const cameraPreviewEl = mustQuery<HTMLVideoElement>("#camera-preview");
const adminLivePreviewEl = mustQuery<HTMLImageElement>("#admin-live-preview");
const adminLiveStatusEl = mustQuery<HTMLElement>("#admin-live-status");
const connectionBadgeEl = mustQuery<HTMLElement>("#connection-badge");
const statusApiEl = mustQuery<HTMLElement>("#status-api");
const statusPeerEl = mustQuery<HTMLElement>("#status-peer");
const statusIceEl = mustQuery<HTMLElement>("#status-ice");
const statusSessionIdEl = mustQuery<HTMLElement>("#status-session-id");
const statusSessionCountEl = mustQuery<HTMLElement>("#status-session-count");
const statusSendFpsEl = mustQuery<HTMLElement>("#status-send-fps");
const statusAnalysisFpsEl = mustQuery<HTMLElement>("#status-analysis-fps");
const statusIncomingFpsEl = mustQuery<HTMLElement>("#status-incoming-fps");
const statusProcessedFpsEl = mustQuery<HTMLElement>("#status-processed-fps");
const statusDroppedFramesEl = mustQuery<HTMLElement>("#status-dropped-frames");
const statusTotalFramesEl = mustQuery<HTMLElement>("#status-total-frames");
const processStatusToggleEl = mustQuery<HTMLButtonElement>("#process-status-toggle");
const processStatusBodyEl = mustQuery<HTMLElement>("#process-status-body");
const adminFeedStatusEl = mustQuery<HTMLElement>("#admin-feed-status");
const adminQuestionStatusEl = mustQuery<HTMLElement>("#admin-question-status");
const adminResponseTimeEl = mustQuery<HTMLElement>("#admin-response-time");
const processEventLogEl = mustQuery<HTMLUListElement>("#process-event-log");
const questionTranscriptEl = mustQuery<HTMLElement>("#question-transcript");
const answerStageBadgeEl = mustQuery<HTMLElement>("#answer-stage-badge");
const answerOutputEl = mustQuery<HTMLElement>("#answer-output");
const eventLogEl = mustQuery<HTMLUListElement>("#event-log");

let currentPage: PageName = "home";
let activeTheme: ThemeName = loadStoredTheme() ?? "dark";
let activeStream: MediaStream | null = null;
let activeCameraStream: MediaStream | null = null;
let activeLandscapeFeed: LandscapeFeedOutput | null = null;
let activeSessionId: string | null = null;
let questionRecognition: SpeechRecognitionLike | null = null;
let questionTranscript = "";
let audioResponsePlayer: HTMLAudioElement | null = null;
let audioResponseContext: AudioContext | null = null;
let audioResponseSource: AudioBufferSourceNode | null = null;
let audioResponseObjectUrl: string | null = null;
let audioResponseUnlocked = false;
let discardQuestionTranscript = false;
let questionRecordingStopPending = false;
let peerState: RTCPeerConnectionState = "closed";
const sendTargetFps = SEND_TARGET_FPS;
let latestHealthStatus = "unknown";
let latestSessions: DebugSession[] = [];
let latestSelectedSession: DebugSession | null = null;
let adminPreviewSessionId: string | null = null;
let adminPreviewHasSnapshot = false;
let viewportConstraintTimer: number | null = null;
let processStatusVisible = false;
let latestFeedStatus = "Camera idle.";
let latestQuestionStatus = "idle";
let latestQuestionStage = "idle";
let questionSentAtMs: number | null = null;
let latestQuestionResponseDurationMs: number | null = null;
let questionResponsePending = false;
const processEvents: string[] = [];
const logger = new UiLogger(eventLogEl);
const apiBaseUrl = getSignalingBaseUrl();
const errorCache = new Map<string, string>();

showAdminLiveStatus("No active session.");
setFeedStatus("Camera idle.", false);
setQuestionStatus("idle", false);

adminLivePreviewEl.addEventListener("load", () => {
  if (adminLivePreviewEl.naturalWidth > 0 && adminLivePreviewEl.naturalHeight > 0) {
    adminLivePreviewEl.style.setProperty(
      "--admin-preview-aspect-ratio",
      `${adminLivePreviewEl.naturalWidth} / ${adminLivePreviewEl.naturalHeight}`
    );
  }
  adminLivePreviewEl.hidden = false;
  adminLiveStatusEl.hidden = true;
});

adminLivePreviewEl.addEventListener("error", () => {
  if (!adminPreviewSessionId) {
    return;
  }
  adminLivePreviewEl.hidden = true;
  showAdminLiveStatus("Waiting for latest frame...");
});

const webrtc = new WebRtcClient(
  (state) => {
    peerState = state;
    if (!questionRecognition && !questionRecordingStopPending) {
      setQuestionStatus(state === "connected" ? "ready" : "idle");
    }
    renderConnectionBadge();
    renderQuestionRecorder();
    renderLatestDashboard();
  },
  (payload) => {
    handleInferencePayload(payload);
  },
  (message) => {
    logger.log(message);
    if (message === "Data channel open" || message === "Data channel closed") {
      if (!questionRecognition && !questionRecordingStopPending) {
        setQuestionStatus(message === "Data channel open" && activeStream ? "ready" : "idle");
      }
      renderQuestionRecorder();
    }
  }
);

goCameraEl.addEventListener("click", () => {
  showPage("camera");
});

goAdminEl.addEventListener("click", () => {
  showPage("admin");
});

topHomeEl.addEventListener("click", () => {
  showPage("home");
});

startFeedEl.addEventListener("click", () => {
  unlockAudioResponsePlayback();
  void toggleFeed();
});

cameraRecordQuestionEl.addEventListener("click", () => {
  unlockAudioResponsePlayback();
  void toggleCameraQuestionRecording();
});

themeToggleEl.addEventListener("click", () => {
  const nextTheme: ThemeName = activeTheme === "dark" ? "light" : "dark";
  setTheme(nextTheme, true);
});

processStatusToggleEl.addEventListener("click", () => {
  setProcessStatusVisible(!processStatusVisible);
});

cameraPreviewEl.addEventListener("loadedmetadata", () => {
  updateViewportLayout();
});

window.addEventListener("resize", () => {
  updateViewportLayout();
});

window.addEventListener("orientationchange", () => {
  updateViewportLayout();
});

window.visualViewport?.addEventListener("resize", () => {
  updateViewportLayout();
});

window.setInterval(() => {
  if (currentPage !== "admin") {
    return;
  }
  void refreshAdminData();
}, 2000);

window.setInterval(() => {
  if (currentPage !== "admin") {
    return;
  }

  void refreshAdminPreviewSnapshot();
}, ADMIN_PREVIEW_POLL_MS);

window.addEventListener("beforeunload", () => {
  resetQuestionRecorder();
  stopAudioResponsePlayback();
  stopLandscapeFeedOutput();
  stopStream(activeStream);
  stopStream(activeCameraStream);
  void webrtc.disconnect();
});

showPage("home");
setTheme(activeTheme, false);
renderStartButton();
renderQuestionRecorder();
renderConnectionBadge();
renderLatestDashboard();
renderProcessStatus();
updateViewportLayout();

function showPage(page: PageName): void {
  currentPage = page;
  homePageEl.classList.toggle("hidden", page !== "home");
  cameraPageEl.classList.toggle("hidden", page !== "camera");
  adminPageEl.classList.toggle("hidden", page !== "admin");
  topHomeEl.classList.toggle("hidden", page === "home");

  if (page === "camera") {
    updateViewportLayout();
  }

  if (page === "admin") {
    void refreshAdminData();
  }
}

async function toggleFeed(): Promise<void> {
  if (activeStream) {
    await stopFeed(true);
    return;
  }

  await startFeed();
}

async function toggleCameraQuestionRecording(): Promise<void> {
  try {
    if (questionRecognition) {
      await stopQuestionRecording();
      return;
    }

    startQuestionRecording();
  } catch (error) {
    const message = formatErrorMessage(error);
    setQuestionStatus(`Question recording failed: ${message}`);
    logger.log(`Question recording failed: ${message}`);
    renderQuestionRecorder();
  }
}

async function startFeed(): Promise<void> {
  startFeedEl.disabled = true;
  setQuestionStatus("connecting");
  setFeedStatus("Starting camera...");

  try {
    activeCameraStream = await startCameraStream(sendTargetFps);
    attachStreamToCameraPreview(activeCameraStream);
    await applyViewportCameraConstraints();
    activeStream = startLandscapeFeedOutput(cameraPreviewEl, sendTargetFps);
    logger.log("Camera stream started");
    setFeedStatus("Camera started. Connecting feed...");

    await webrtc.connect(activeStream);
    activeSessionId = webrtc.getSessionId();

    if (activeSessionId) {
      logger.log(`Active session ${activeSessionId}`);
    }

    await applySendFramerate(sendTargetFps, false);
    await refreshAdminData();
    setQuestionStatus(webrtc.isReadyToSend() ? "ready" : "connecting");
    setFeedStatus("Feed connected.");
  } catch (error) {
    const message = formatErrorMessage(error);
    logger.log(`Start feed failed: ${message}`);
    setQuestionStatus("idle");
    setFeedStatus(`Feed failed: ${message}`);
    await stopFeed(false);
  } finally {
    startFeedEl.disabled = false;
    renderStartButton();
    renderQuestionRecorder();
    renderLatestDashboard();
  }
}

async function stopFeed(shouldLog: boolean): Promise<void> {
  resetQuestionRecorder();
  const stream = activeStream;
  const cameraStream = activeCameraStream;
  activeStream = null;
  activeCameraStream = null;
  stopLandscapeFeedOutput();

  await webrtc.disconnect();
  setQuestionStatus("idle");
  if (stream) {
    stopStream(stream);
  }
  if (cameraStream) {
    stopStream(cameraStream);
  }

  activeSessionId = null;
  attachStreamToCameraPreview(null);
  latestSessions = [];
  latestSelectedSession = null;
  syncAdminPreviewSession(null);

  if (viewportConstraintTimer !== null) {
    window.clearTimeout(viewportConstraintTimer);
    viewportConstraintTimer = null;
  }

  if (shouldLog) {
    logger.log("Feed stopped");
    setFeedStatus("Feed stopped.");
  }

  renderStartButton();
  renderQuestionRecorder();
  renderLatestDashboard();
}

function attachStreamToCameraPreview(stream: MediaStream | null): void {
  cameraPreviewEl.srcObject = stream;

  if (stream) {
    void cameraPreviewEl.play().catch(() => undefined);
  }

  if (!stream) {
    cameraPageEl.dataset.videoOrientation = "unknown";
    cameraPageEl.style.removeProperty("--camera-aspect-ratio");
  }

  updateViewportLayout();
}

function startLandscapeFeedOutput(
  sourceVideo: HTMLVideoElement,
  targetFps: number
): MediaStream {
  stopLandscapeFeedOutput();

  const canvas = document.createElement("canvas");
  canvas.width = LANDSCAPE_FEED_WIDTH;
  canvas.height = LANDSCAPE_FEED_HEIGHT;

  const context = canvas.getContext("2d");
  if (!context) {
    throw new Error("Landscape feed renderer is unavailable");
  }

  if (typeof canvas.captureStream !== "function") {
    throw new Error("Landscape feed capture is unavailable in this browser");
  }

  const frameIntervalMs = 1000 / Math.max(1, targetFps);
  let animationFrameId: number | null = null;
  let lastFrameAtMs = 0;
  let stopped = false;

  const drawFrame = (timestampMs: number): void => {
    if (stopped) {
      return;
    }

    if (timestampMs - lastFrameAtMs >= frameIntervalMs) {
      drawVideoIntoLandscapeCanvas(sourceVideo, context, canvas);
      lastFrameAtMs = timestampMs;
    }

    animationFrameId = window.requestAnimationFrame(drawFrame);
  };

  drawVideoIntoLandscapeCanvas(sourceVideo, context, canvas);
  animationFrameId = window.requestAnimationFrame(drawFrame);

  const stream = canvas.captureStream(targetFps);
  activeLandscapeFeed = {
    stream,
    stop() {
      stopped = true;
      if (animationFrameId !== null) {
        window.cancelAnimationFrame(animationFrameId);
      }
      stopStream(stream);
    }
  };

  return stream;
}

function stopLandscapeFeedOutput(): void {
  const output = activeLandscapeFeed;
  activeLandscapeFeed = null;
  output?.stop();
}

function drawVideoIntoLandscapeCanvas(
  sourceVideo: HTMLVideoElement,
  context: CanvasRenderingContext2D,
  canvas: HTMLCanvasElement
): void {
  const sourceWidth = sourceVideo.videoWidth;
  const sourceHeight = sourceVideo.videoHeight;
  context.fillStyle = "#000";
  context.fillRect(0, 0, canvas.width, canvas.height);

  if (sourceWidth <= 0 || sourceHeight <= 0) {
    return;
  }

  const targetAspectRatio = canvas.width / canvas.height;
  const sourceAspectRatio = sourceWidth / sourceHeight;
  let cropX = 0;
  let cropY = 0;
  let cropWidth = sourceWidth;
  let cropHeight = sourceHeight;

  if (sourceAspectRatio > targetAspectRatio) {
    cropWidth = sourceHeight * targetAspectRatio;
    cropX = (sourceWidth - cropWidth) / 2;
  } else {
    cropHeight = sourceWidth / targetAspectRatio;
    cropY = (sourceHeight - cropHeight) / 2;
  }

  context.drawImage(
    sourceVideo,
    cropX,
    cropY,
    cropWidth,
    cropHeight,
    0,
    0,
    canvas.width,
    canvas.height
  );
}

function setFeedStatus(message: string, recordEvent = true): void {
  latestFeedStatus = message;
  if (recordEvent) {
    addProcessEvent("Feed", message);
  }
  renderProcessStatus();
}

function setQuestionStatus(message: string, recordEvent = true, stage = message): void {
  latestQuestionStatus = message;
  latestQuestionStage = stage;
  if (recordEvent) {
    addProcessEvent("Question", message);
  }
  renderProcessStatus();
}

function addProcessEvent(scope: "Feed" | "Question", message: string): void {
  const now = new Date().toLocaleTimeString();
  processEvents.unshift(`[${now}] ${scope}: ${message}`);
  while (processEvents.length > MAX_PROCESS_EVENTS) {
    processEvents.pop();
  }
}

function setQuestionTranscript(message: string, muted: boolean): void {
  questionTranscriptEl.textContent = message;
  questionTranscriptEl.classList.toggle("is-muted", muted);
}

function setAnswerOutput(message: string): void {
  answerOutputEl.textContent = message;
}

function formatErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }

  return String(error);
}

function setTheme(theme: ThemeName, persist: boolean): void {
  activeTheme = theme;
  document.documentElement.dataset.theme = theme;
  themeToggleEl.textContent = theme === "dark" ? "Light mode" : "Dark mode";
  themeToggleEl.setAttribute(
    "aria-label",
    theme === "dark" ? "Switch to light mode" : "Switch to dark mode"
  );
  themeToggleEl.setAttribute("aria-pressed", theme === "light" ? "true" : "false");

  if (persist) {
    saveStoredTheme(theme);
  }
}

function updateViewportLayout(): void {
  const viewportWidth = window.visualViewport?.width ?? window.innerWidth;
  const viewportHeight = window.visualViewport?.height ?? window.innerHeight;
  document.documentElement.style.setProperty("--app-vh", `${Math.round(viewportHeight)}px`);

  cameraPageEl.dataset.orientation =
    viewportHeight >= viewportWidth ? "portrait" : "landscape";
  cameraPageEl.dataset.videoOrientation = "landscape";
  cameraPageEl.style.setProperty(
    "--camera-aspect-ratio",
    `${LANDSCAPE_FEED_WIDTH} / ${LANDSCAPE_FEED_HEIGHT}`
  );

  if (!activeCameraStream) {
    return;
  }

  if (viewportConstraintTimer !== null) {
    window.clearTimeout(viewportConstraintTimer);
  }

  viewportConstraintTimer = window.setTimeout(() => {
    viewportConstraintTimer = null;
    void applyViewportCameraConstraints();
  }, 120);
}

async function applyViewportCameraConstraints(): Promise<void> {
  const track = activeCameraStream?.getVideoTracks()[0] ?? null;
  if (!track) {
    return;
  }

  try {
    await track.applyConstraints({
      width: { ideal: LANDSCAPE_FEED_WIDTH },
      height: { ideal: LANDSCAPE_FEED_HEIGHT },
      aspectRatio: { ideal: LANDSCAPE_FEED_WIDTH / LANDSCAPE_FEED_HEIGHT },
      frameRate: { ideal: sendTargetFps, max: sendTargetFps }
    });
  } catch {
    return;
  }
}

function renderStartButton(): void {
  startFeedEl.textContent = activeStream ? "Stop Feed" : "Start Feed";
}

function renderQuestionRecorder(): void {
  const isRecording = Boolean(questionRecognition);
  const canStartRecording = Boolean(activeStream) && webrtc.isReadyToSend();

  cameraRecordQuestionEl.textContent = questionRecordingStopPending
    ? "Sending..."
    : isRecording
      ? "Stop Recording"
      : "Record Question";
  cameraRecordQuestionEl.classList.toggle("is-recording", isRecording);
  cameraRecordQuestionEl.setAttribute("aria-pressed", isRecording ? "true" : "false");
  cameraRecordQuestionEl.disabled = questionRecordingStopPending || (!isRecording && !canStartRecording);
}

function renderConnectionBadge(): void {
  const state = peerState.toLowerCase();
  let label = "Disconnected";
  let tone: StatusTone = "neutral";

  if (state === "connected") {
    label = "Connected";
    tone = "up";
  } else if (state === "new" || state === "connecting") {
    label = "Connecting";
    tone = "warn";
  } else if (state === "failed") {
    label = "Failed";
    tone = "down";
  }

  connectionBadgeEl.textContent = label;
  connectionBadgeEl.classList.remove("is-up", "is-warn", "is-down", "is-neutral");
  connectionBadgeEl.classList.add(`is-${tone}`);
}

function setProcessStatusVisible(visible: boolean): void {
  processStatusVisible = visible;
  renderProcessStatus();
}

function renderProcessStatus(): void {
  answerStageBadgeEl.textContent = formatQuestionStageLabel(latestQuestionStage);
  answerStageBadgeEl.title = humanizeState(latestQuestionStage);
  processStatusBodyEl.classList.toggle("hidden", !processStatusVisible);
  processStatusToggleEl.textContent = processStatusVisible
    ? "Hide Process Status"
    : "Show Process Status";
  processStatusToggleEl.setAttribute(
    "aria-expanded",
    processStatusVisible ? "true" : "false"
  );
  adminFeedStatusEl.textContent = latestFeedStatus;
  adminQuestionStatusEl.textContent = latestQuestionStatus;
  adminResponseTimeEl.textContent = formatQuestionResponseTime();
  processEventLogEl.innerHTML = "";

  if (processEvents.length === 0) {
    const emptyEntry = document.createElement("li");
    emptyEntry.textContent = "No process events yet.";
    emptyEntry.className = "is-muted";
    processEventLogEl.appendChild(emptyEntry);
    return;
  }

  for (const event of processEvents) {
    const entry = document.createElement("li");
    entry.textContent = event;
    processEventLogEl.appendChild(entry);
  }
}

function markQuestionSent(): void {
  questionSentAtMs = performance.now();
  latestQuestionResponseDurationMs = null;
  questionResponsePending = true;
  renderProcessStatus();
}

function markQuestionResponseReceived(): void {
  if (questionSentAtMs === null) {
    return;
  }

  latestQuestionResponseDurationMs = performance.now() - questionSentAtMs;
  questionSentAtMs = null;
  questionResponsePending = false;
  addProcessEvent(
    "Question",
    `Response completed in ${formatDuration(latestQuestionResponseDurationMs)}`
  );
  renderProcessStatus();
}

function formatQuestionResponseTime(): string {
  if (questionResponsePending && questionSentAtMs !== null) {
    return `Waiting ${formatDuration(performance.now() - questionSentAtMs)}`;
  }

  if (latestQuestionResponseDurationMs !== null) {
    return formatDuration(latestQuestionResponseDurationMs);
  }

  return "n/a";
}

function formatDuration(durationMs: number): string {
  if (!Number.isFinite(durationMs) || durationMs < 0) {
    return "n/a";
  }

  if (durationMs < 1000) {
    return `${Math.round(durationMs)} ms`;
  }

  return `${(durationMs / 1000).toFixed(1)} s`;
}

function formatQuestionStageLabel(rawStage: string): string {
  const normalized = rawStage.trim().toLowerCase();
  if (!normalized) {
    return "Idle";
  }

  const mappedLabel = QUESTION_STAGE_LABELS[normalized];
  if (mappedLabel) {
    return mappedLabel;
  }

  if (normalized.includes("llm")) {
    return "LLM";
  }
  if (normalized.includes("vlm")) {
    return "VLM";
  }
  if (
    normalized.includes("speech") ||
    normalized.includes("tts") ||
    normalized.includes("audio")
  ) {
    return "TTS";
  }
  if (normalized.includes("waiting")) {
    return "Waiting";
  }
  if (normalized.includes("sending") || normalized.includes("sent")) {
    return "Sending";
  }
  if (
    normalized.includes("fail") ||
    normalized.includes("error") ||
    normalized.includes("unavailable")
  ) {
    return "Error";
  }

  return humanizeState(rawStage);
}

function renderLatestDashboard(): void {
  renderSystemDashboard(latestHealthStatus, latestSessions, latestSelectedSession);
}

function renderSystemDashboard(
  healthStatus: string,
  sessions: DebugSession[],
  selectedSession: DebugSession | null
): void {
  const apiLabel = healthStatus === "ok" ? "UP" : healthStatus === "unreachable" ? "DOWN" : "CHECKING";
  setBadgeCell(statusApiEl, apiLabel, toneForHealth(healthStatus));

  const peerDisplay = selectedSession ? selectedSession.connection_state : peerState;
  const iceDisplay = selectedSession ? selectedSession.ice_state : "n/a";
  setBadgeCell(statusPeerEl, humanizeState(peerDisplay), toneForPeerState(peerDisplay));
  setBadgeCell(statusIceEl, humanizeState(iceDisplay), toneForIceState(iceDisplay));

  setTextCell(statusSessionIdEl, selectedSession ? selectedSession.session_id : "none", true);
  setTextCell(statusSessionCountEl, String(sessions.length), true);
  setTextCell(statusSendFpsEl, `${sendTargetFps} FPS`);

  const analysisFps = selectedSession ? selectedSession.analysis_target_fps : 0;
  setTextCell(statusAnalysisFpsEl, `${formatFps(analysisFps)} FPS`);

  const incomingFps = selectedSession ? selectedSession.incoming_fps : 0;
  const processedFps = selectedSession ? selectedSession.processed_fps : 0;
  setTextCell(statusIncomingFpsEl, `${formatFps(incomingFps)} FPS`, true);
  setTextCell(statusProcessedFpsEl, `${formatFps(processedFps)} FPS`, true);
  setTextCell(
    statusDroppedFramesEl,
    String(selectedSession ? selectedSession.dropped_frames : 0),
    true
  );
  setTextCell(
    statusTotalFramesEl,
    String(selectedSession ? selectedSession.total_frames : 0),
    true
  );
}

async function applySendFramerate(fps: number, shouldLog: boolean): Promise<void> {
  if (!Number.isFinite(fps) || fps < 1) {
    return;
  }

  const track = activeStream?.getVideoTracks()[0] ?? null;
  let trackUpdated = false;
  if (track) {
    try {
      await track.applyConstraints({ frameRate: { ideal: fps, max: fps } });
      trackUpdated = true;
    } catch (error) {
      logger.log(`Camera FPS update failed: ${String(error)}`);
    }
  }

  const senderUpdated = await webrtc.setOutgoingFramerate(fps);
  if (shouldLog) {
    if (senderUpdated || trackUpdated) {
      logger.log(`Send FPS cap set to ${fps}`);
    } else {
      logger.log(`Send FPS preference saved: ${fps}`);
    }
  }
}

async function refreshAdminData(): Promise<void> {
  const [healthStatus, sessions] = await Promise.all([
    fetchHealthStatus(),
    fetchDebugSessions()
  ]);

  const selectedSession = pickVisibleSession(sessions);
  latestHealthStatus = healthStatus;
  latestSessions = sessions;
  latestSelectedSession = selectedSession;
  syncAdminPreviewSession(selectedSession);

  renderLatestDashboard();
}

function syncAdminPreviewSession(selectedSession: DebugSession | null): void {
  adminPreviewSessionId = selectedSession?.session_id ?? null;
  adminPreviewHasSnapshot = Boolean(selectedSession?.has_snapshot);

  if (!adminPreviewSessionId) {
    clearAdminLivePreview("No active session.");
    return;
  }

  if (!adminPreviewHasSnapshot) {
    clearAdminLivePreview("Session active. Waiting for first frame...");
    return;
  }

  if (adminLiveStatusEl.hidden === false) {
    showAdminLiveStatus("Loading live feed...");
  }

  void refreshAdminPreviewSnapshot();
}

async function refreshAdminPreviewSnapshot(): Promise<void> {
  if (!adminPreviewSessionId || !adminPreviewHasSnapshot) {
    return;
  }

  const snapshotUrl = `${apiBaseUrl}/debug/sessions/${encodeURIComponent(
    adminPreviewSessionId
  )}/latest.jpg?ts=${Date.now()}`;
  adminLivePreviewEl.src = snapshotUrl;
}

function clearAdminLivePreview(message: string): void {
  adminLivePreviewEl.hidden = true;
  adminLivePreviewEl.removeAttribute("src");
  adminLivePreviewEl.style.removeProperty("--admin-preview-aspect-ratio");
  showAdminLiveStatus(message);
}

function showAdminLiveStatus(message: string): void {
  adminLiveStatusEl.textContent = message;
  adminLiveStatusEl.hidden = false;
}

function startQuestionRecording(): void {
  if (!activeStream) {
    throw new Error("Start the feed before recording a question");
  }
  if (!webrtc.isReadyToSend()) {
    throw new Error("Wait for the data channel to connect before asking a question");
  }
  if (questionRecognition) {
    throw new Error("Question recording is already in progress");
  }

  const Recognition = getSpeechRecognitionConstructor();
  if (!Recognition) {
    setAnswerOutput("Voice recognition is unavailable in this browser.");
    setQuestionStatus("Voice recognition is unavailable in this browser.");
    throw new Error("Speech recognition is not available in this browser");
  }

  const recognition = new Recognition();
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.lang = navigator.language || "en-US";
  questionTranscript = "";
  discardQuestionTranscript = false;
  questionRecordingStopPending = false;

  recognition.onresult = (event) => {
    const transcript = collectSpeechTranscript(event.results);
    questionTranscript = transcript;
    if (transcript) {
      setQuestionTranscript(transcript, false);
    }
  };

  recognition.onerror = (event) => {
    logger.log(`Speech recognition error: ${event.error ?? event.message ?? "unknown error"}`);
  };

  recognition.onend = () => {
    questionRecognition = null;
    const transcript = questionTranscript.trim();
    const shouldDiscard = discardQuestionTranscript;
    questionTranscript = "";
    discardQuestionTranscript = false;
    questionRecordingStopPending = false;
    renderQuestionRecorder();

    if (shouldDiscard) {
      return;
    }

    if (!transcript) {
      setQuestionStatus(
        webrtc.isReadyToSend() ? "No question heard. Try recording again." : "idle"
      );
      setQuestionTranscript("No question heard.", true);
      setAnswerOutput("No answer yet.");
      logger.log("No speech transcript captured");
      return;
    }

    try {
      sendQuestionText(transcript);
    } catch (error) {
      setQuestionStatus("Question send failed.");
      setAnswerOutput("Question send failed.");
      logger.log(`Question send failed: ${formatErrorMessage(error)}`);
    }
  };

  questionRecognition = recognition;
  try {
    recognition.start();
  } catch (error) {
    questionRecognition = null;
    questionTranscript = "";
    discardQuestionTranscript = false;
    questionRecordingStopPending = false;
    renderQuestionRecorder();
    throw error;
  }

  setQuestionStatus("listening");
  setQuestionTranscript("Listening...", true);
  setAnswerOutput("No answer yet.");
  renderQuestionRecorder();
  logger.log("Listening for question...");
}

async function stopQuestionRecording(): Promise<void> {
  if (!questionRecognition) {
    throw new Error("No active question recording");
  }
  if (questionRecordingStopPending) {
    return;
  }

  questionRecordingStopPending = true;
  setQuestionStatus("Stopping recording and sending question...");
  setAnswerOutput("Processing...");
  renderQuestionRecorder();
  try {
    questionRecognition.stop();
  } catch (error) {
    questionRecordingStopPending = false;
    renderQuestionRecorder();
    throw error;
  }
}

function resetQuestionRecorder(): void {
  if (questionRecognition) {
    discardQuestionTranscript = true;
    questionRecognition.abort();
  }
  questionRecognition = null;
  questionTranscript = "";
  questionRecordingStopPending = false;
  renderQuestionRecorder();
}

function getSpeechRecognitionConstructor(): SpeechRecognitionConstructor | null {
  const speechWindow = window as SpeechRecognitionWindow;
  return speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition ?? null;
}

function collectSpeechTranscript(results: SpeechRecognitionResultListLike): string {
  const parts: string[] = [];
  for (let index = 0; index < results.length; index += 1) {
    const alternative = results[index][0];
    const transcript = alternative?.transcript.trim();
    if (transcript) {
      parts.push(transcript);
    }
  }

  return parts.join(" ").trim();
}

function sendQuestionText(text: string): void {
  if (!webrtc.isReadyToSend()) {
    throw new Error("Connection closed before the question was sent");
  }

  const normalizedText = text.trim();
  if (!normalizedText) {
    throw new Error("No question text captured");
  }

  setQuestionStatus("waiting");
  setAnswerOutput("Processing...");
  const sent = webrtc.sendJson({ type: "question_text", text: normalizedText });
  if (!sent) {
    throw new Error("Data channel is not open");
  }
  markQuestionSent();
  setQuestionStatus("Question sent. Waiting for assistant response...");
  logger.log(`Question text sent: ${normalizedText}`);
}

function playReturnedAudio(audioBase64: string): void {
  void playReturnedAudioAsync(audioBase64).catch((error: unknown) => {
    setQuestionStatus("Audio playback failed. Showing text response.");
    logger.log(`Audio playback failed: ${formatErrorMessage(error)}`);
  });
}

async function playReturnedAudioAsync(audioBase64: string): Promise<void> {
  const audioBytes = base64ToArrayBuffer(audioBase64);
  stopAudioResponsePlayback();
  setQuestionStatus("Playing audio response...");

  if (await playAudioBuffer(audioBytes)) {
    return;
  }

  await playAudioElement(audioBytes).catch((error: unknown) => {
    setQuestionStatus("Audio playback failed. Showing text response.");
    logger.log(`Audio playback failed: ${formatErrorMessage(error)}`);
  });
}

function unlockAudioResponsePlayback(): void {
  const context = getAudioResponseContext();
  if (!context) {
    return;
  }

  if (!audioResponseUnlocked) {
    try {
      const buffer = context.createBuffer(1, 1, 22050);
      const source = context.createBufferSource();
      source.buffer = buffer;
      source.connect(context.destination);
      source.start(0);
      audioResponseUnlocked = true;
    } catch (error) {
      logger.log(`Audio unlock failed: ${formatErrorMessage(error)}`);
    }
  }

  if (context.state === "suspended") {
    void context.resume().catch((error: unknown) => {
      logger.log(`Audio resume failed: ${formatErrorMessage(error)}`);
    });
  }
}

function getAudioResponseContext(): AudioContext | null {
  if (audioResponseContext) {
    return audioResponseContext;
  }

  const audioWindow = window as AudioContextWindow;
  const AudioContextConstructor = window.AudioContext ?? audioWindow.webkitAudioContext;
  if (!AudioContextConstructor) {
    return null;
  }

  audioResponseContext = new AudioContextConstructor();
  return audioResponseContext;
}

async function playAudioBuffer(audioBytes: ArrayBuffer): Promise<boolean> {
  const context = getAudioResponseContext();
  if (!context) {
    return false;
  }

  try {
    if (context.state === "suspended") {
      await context.resume();
    }
    if (context.state !== "running") {
      return false;
    }

    const audioBuffer = await context.decodeAudioData(audioBytes.slice(0));
    const source = context.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(context.destination);
    source.onended = () => {
      if (audioResponseSource === source) {
        audioResponseSource = null;
      }
    };
    source.start(0);
    audioResponseSource = source;
    return true;
  } catch (error) {
    logger.log(`Web Audio playback failed: ${formatErrorMessage(error)}`);
    return false;
  }
}

async function playAudioElement(audioBytes: ArrayBuffer): Promise<void> {
  audioResponseObjectUrl = URL.createObjectURL(
    new Blob([audioBytes], { type: "audio/mpeg" })
  );
  const player = new Audio(audioResponseObjectUrl);
  player.preload = "auto";
  audioResponsePlayer = player;
  await player.play();
}

function stopAudioResponsePlayback(): void {
  if (audioResponseSource) {
    try {
      audioResponseSource.stop();
    } catch {
      // The source may already have ended.
    }
    audioResponseSource.disconnect();
    audioResponseSource = null;
  }

  if (audioResponsePlayer) {
    audioResponsePlayer.pause();
    audioResponsePlayer.removeAttribute("src");
    audioResponsePlayer.load();
    audioResponsePlayer = null;
  }

  if (audioResponseObjectUrl) {
    URL.revokeObjectURL(audioResponseObjectUrl);
    audioResponseObjectUrl = null;
  }
}

function base64ToArrayBuffer(base64: string): ArrayBuffer {
  const binary = window.atob(base64.replace(/\s/g, ""));
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes.buffer;
}

async function fetchHealthStatus(): Promise<string> {
  try {
    const response = await fetch(`${apiBaseUrl}/health`);
    if (!response.ok) {
      throw new Error(`status ${response.status}`);
    }

    const payload = (await response.json()) as { status?: string };
    clearError("health");
    return payload.status ?? "unknown";
  } catch (error) {
    logErrorOnce("health", `Health check failed: ${String(error)}`);
    return "unreachable";
  }
}

async function fetchDebugSessions(): Promise<DebugSession[]> {
  try {
    const response = await fetch(`${apiBaseUrl}/debug/sessions`);
    if (!response.ok) {
      throw new Error(`status ${response.status}`);
    }

    const payload = (await response.json()) as { sessions?: unknown[] };
    const normalized: DebugSession[] = [];

    for (const rawSession of payload.sessions ?? []) {
      if (
        typeof rawSession !== "object" ||
        rawSession === null ||
        typeof (rawSession as RawDebugSession).session_id !== "string"
      ) {
        continue;
      }

      normalized.push(normalizeDebugSession(rawSession as RawDebugSession));
    }

    clearError("sessions");
    return normalized;
  } catch (error) {
    logErrorOnce("sessions", `Session debug fetch failed: ${String(error)}`);
    return [];
  }
}

function pickVisibleSession(
  sessions: DebugSession[],
): DebugSession | null {
  if (activeSessionId) {
    const active = sessions.find((session) => session.session_id === activeSessionId);
    if (active) {
      return active;
    }
  }

  return sessions.length > 0 ? sessions[0] : null;
}

function logErrorOnce(key: string, message: string): void {
  if (errorCache.get(key) === message) {
    return;
  }

  errorCache.set(key, message);
  logger.log(message);
}

function clearError(key: string): void {
  errorCache.delete(key);
}

function handleInferencePayload(rawPayload: string): void {
  let parsed: unknown;
  try {
    parsed = JSON.parse(rawPayload);
  } catch {
    logger.log(`Data message: ${rawPayload}`);
    return;
  }

  if (handleAssistantPayload(parsed, rawPayload)) {
    return;
  }

  if (!isInferenceMessage(parsed)) {
    logger.log(`Data message: ${rawPayload}`);
    return;
  }

  const message = parsed as InferenceMessage;
  if (message.guidance_text) {
    logger.log(`Guidance: ${message.guidance_text}`);
    return;
  }

  logger.log(`Inference tick: ${message.timestamp}`);
}

function handleAssistantPayload(parsed: unknown, rawPayload: string): boolean {
  if (typeof parsed !== "object" || parsed === null) {
    return false;
  }

  const candidate = parsed as Record<string, unknown>;
  const messageType = candidate.type;
  if (messageType === "status") {
    const status = typeof candidate.status === "string" ? candidate.status : null;
    const message = typeof candidate.message === "string" ? candidate.message : null;
    setQuestionStatus(
      message ?? status ?? "processing",
      true,
      status ?? message ?? "processing"
    );
    if (message) {
      logger.log(message);
    }
    return true;
  }

  if (messageType === "error") {
    const message = typeof candidate.message === "string" ? candidate.message : rawPayload;
    markQuestionResponseReceived();
    setQuestionStatus(message);
    setAnswerOutput(message);
    logger.log(message);
    return true;
  }

  if (messageType !== "answer") {
    return false;
  }

  if (typeof candidate.transcript === "string" && candidate.transcript.trim()) {
    setQuestionTranscript(candidate.transcript, false);
  }
  if (typeof candidate.answer === "string") {
    setAnswerOutput(candidate.answer);
  }
  markQuestionResponseReceived();
  setQuestionStatus("complete");

  if (typeof candidate.audio_error === "string" && candidate.audio_error.trim()) {
    logger.log(`Speech unavailable: ${candidate.audio_error}`);
  }
  if (typeof candidate.audio_base64 === "string" && candidate.audio_base64.length > 0) {
    playReturnedAudio(candidate.audio_base64);
  }
  return true;
}
