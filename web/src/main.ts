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

const SEND_TARGET_FPS = 30;
const ADMIN_PREVIEW_POLL_MS = 750;
const THEME_STORAGE_KEY = "lensplus-theme";

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
      <div class="page-top">
        <button id="camera-home" class="ghost">Home</button>
      </div>
      <div class="camera-wrap">
        <video id="camera-preview" autoplay muted playsinline></video>
      </div>
      <p id="camera-status" class="camera-status">Camera idle.</p>
      <button id="start-feed" class="primary">Start Feed</button>
      <button id="camera-record-question" class="camera-record-box" type="button">Record</button>
      <section class="camera-question-panel" aria-live="polite">
        <div class="camera-question-status">
          <span>Status</span>
          <strong id="question-status">idle</strong>
        </div>
        <div class="camera-question-block">
          <span>Speech to text</span>
          <p id="question-transcript" class="camera-question-text is-muted">Record a question to see the transcript here.</p>
        </div>
        <div class="camera-question-block">
          <span>Model response</span>
          <p id="answer-output" class="camera-question-text">No answer yet.</p>
        </div>
      </section>
    </section>

    <section id="admin-page" class="page hidden">
      <div class="page-top">
        <button id="admin-home" class="ghost">Home</button>
      </div>

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
const themeToggleEl = mustQuery<HTMLButtonElement>("#theme-toggle");
const goCameraEl = mustQuery<HTMLButtonElement>("#go-camera");
const goAdminEl = mustQuery<HTMLButtonElement>("#go-admin");
const cameraHomeEl = mustQuery<HTMLButtonElement>("#camera-home");
const adminHomeEl = mustQuery<HTMLButtonElement>("#admin-home");
const startFeedEl = mustQuery<HTMLButtonElement>("#start-feed");
const cameraRecordQuestionEl = mustQuery<HTMLButtonElement>("#camera-record-question");
const cameraPreviewEl = mustQuery<HTMLVideoElement>("#camera-preview");
const cameraStatusEl = mustQuery<HTMLElement>("#camera-status");
const adminLivePreviewEl = mustQuery<HTMLImageElement>("#admin-live-preview");
const adminLiveStatusEl = mustQuery<HTMLElement>("#admin-live-status");
const connectionBadgeEl = mustQuery<HTMLElement>("#connection-badge");
const questionStatusEl = mustQuery<HTMLElement>("#question-status");
const questionTranscriptEl = mustQuery<HTMLElement>("#question-transcript");
const answerOutputEl = mustQuery<HTMLElement>("#answer-output");
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
const eventLogEl = mustQuery<HTMLUListElement>("#event-log");

let activeStream: MediaStream | null = null;
let activeSessionId: string | null = null;
let questionRecognition: SpeechRecognitionLike | null = null;
let questionTranscript = "";
let audioResponsePlayer: HTMLAudioElement | null = null;
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
let currentPage: PageName = "home";
let activeTheme: ThemeName = loadStoredTheme() ?? "dark";
const logger = new UiLogger(eventLogEl);
const apiBaseUrl = getSignalingBaseUrl();
const errorCache = new Map<string, string>();

prepareInlineVideo(cameraPreviewEl);
showAdminLiveStatus("No active session.");
setCameraStatus(
  window.isSecureContext
    ? `Camera idle. Signaling: ${apiBaseUrl}`
    : "iPhone Safari requires HTTPS for camera access."
);

adminLivePreviewEl.addEventListener("load", () => {
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

cameraHomeEl.addEventListener("click", () => {
  showPage("home");
});

adminHomeEl.addEventListener("click", () => {
  showPage("home");
});

startFeedEl.addEventListener("click", () => {
  void toggleFeed();
});

cameraRecordQuestionEl.addEventListener("click", () => {
  void toggleCameraQuestionRecording();
});

async function toggleCameraQuestionRecording(): Promise<void> {
  try {
    if (questionRecognition) {
      await stopQuestionRecording();
      return;
    }

    startQuestionRecording();
  } catch (error) {
    const message = formatErrorMessage(error);
    setCameraStatus(`Question recording failed: ${message}`);
    logger.log(`Question recording failed: ${message}`);
    renderQuestionRecorder();
  }
}

themeToggleEl.addEventListener("click", () => {
  const nextTheme: ThemeName = activeTheme === "dark" ? "light" : "dark";
  setTheme(nextTheme, true);
});

cameraPreviewEl.addEventListener("loadedmetadata", () => {
  updateViewportLayout();
});

cameraPreviewEl.addEventListener("canplay", () => {
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
  cleanupMediaSession();
});

window.addEventListener("pagehide", () => {
  cleanupMediaSession();
});

document.addEventListener("visibilitychange", () => {
  if (!document.hidden && activeStream) {
    void playPreviewVideo(cameraPreviewEl);
  }
});

function cleanupMediaSession(): void {
  resetQuestionRecorder();
  if (audioResponsePlayer) {
    audioResponsePlayer.pause();
  }
  stopStream(activeStream);
  activeStream = null;
  attachStreamsToPreviews(null);
  void webrtc.disconnect();
}

showPage("home");
setTheme(activeTheme, false);
renderStartButton();
renderQuestionRecorder();
renderConnectionBadge();
renderLatestDashboard();
updateViewportLayout();

function showPage(page: PageName): void {
  currentPage = page;
  homePageEl.classList.toggle("hidden", page !== "home");
  cameraPageEl.classList.toggle("hidden", page !== "camera");
  adminPageEl.classList.toggle("hidden", page !== "admin");

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

async function startFeed(): Promise<void> {
  startFeedEl.disabled = true;
  setQuestionStatus("connecting");
  setCameraStatus("Starting camera...");

  try {
    activeStream = await startCameraStream(sendTargetFps);
    attachStreamsToPreviews(activeStream);
    await applyViewportCameraConstraints();
    logger.log("Camera stream started");
    setCameraStatus("Camera started. Connecting feed...");

    await webrtc.connect(activeStream);
    activeSessionId = webrtc.getSessionId();

    if (activeSessionId) {
      logger.log(`Active session ${activeSessionId}`);
    }

    await applySendFramerate(sendTargetFps, false);
    await refreshAdminData();
    setQuestionStatus(webrtc.isReadyToSend() ? "ready" : "connecting");
    setCameraStatus("Feed connected.");
  } catch (error) {
    const message = formatErrorMessage(error);
    logger.log(`Start feed failed: ${message}`);
    setCameraStatus(`Feed failed: ${message}`);
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
  activeStream = null;

  await webrtc.disconnect();
  setQuestionStatus("idle");
  if (stream) {
    stopStream(stream);
  }

  activeSessionId = null;
  attachStreamsToPreviews(null);
  latestSessions = [];
  latestSelectedSession = null;
  syncAdminPreviewSession(null);

  if (viewportConstraintTimer !== null) {
    window.clearTimeout(viewportConstraintTimer);
    viewportConstraintTimer = null;
  }

  if (shouldLog) {
    logger.log("Feed stopped");
    setCameraStatus("Feed stopped.");
  }

  renderStartButton();
  renderQuestionRecorder();
  renderLatestDashboard();
}

function attachStreamsToPreviews(stream: MediaStream | null): void {
  prepareInlineVideo(cameraPreviewEl);
  cameraPreviewEl.srcObject = stream;

  if (stream) {
    void playPreviewVideo(cameraPreviewEl);
  }

  if (!stream) {
    cameraPageEl.dataset.videoOrientation = "unknown";
  }

  updateViewportLayout();
}

function prepareInlineVideo(video: HTMLVideoElement): void {
  video.autoplay = true;
  video.muted = true;
  video.defaultMuted = true;
  video.playsInline = true;
  video.setAttribute("playsinline", "");
  video.setAttribute("webkit-playsinline", "");
}

async function playPreviewVideo(video: HTMLVideoElement): Promise<void> {
  try {
    await video.play();
  } catch (error) {
    logger.log(`Video preview play blocked: ${formatErrorMessage(error)}`);
  }
}

function setCameraStatus(message: string): void {
  cameraStatusEl.textContent = message;
}

function setQuestionStatus(message: string): void {
  questionStatusEl.textContent = message;
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

  if (cameraPreviewEl.videoWidth <= 0 || cameraPreviewEl.videoHeight <= 0) {
    cameraPageEl.dataset.videoOrientation = "unknown";
    return;
  }

  cameraPageEl.dataset.videoOrientation =
    cameraPreviewEl.videoHeight >= cameraPreviewEl.videoWidth
      ? "portrait"
      : "landscape";
}

async function applyViewportCameraConstraints(): Promise<void> {
  const track = activeStream?.getVideoTracks()[0] ?? null;
  if (!track) {
    return;
  }

  const viewportWidth = window.visualViewport?.width ?? window.innerWidth;
  const viewportHeight = window.visualViewport?.height ?? window.innerHeight;
  const viewportIsPortrait = viewportHeight >= viewportWidth;

  const idealWidth = viewportIsPortrait ? 720 : 1280;
  const idealHeight = viewportIsPortrait ? 1280 : 720;
  const idealAspectRatio = viewportIsPortrait ? 9 / 16 : 16 / 9;

  try {
    await track.applyConstraints({
      width: { ideal: idealWidth },
      height: { ideal: idealHeight },
      aspectRatio: { ideal: idealAspectRatio },
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
      ? "Click to stop"
      : "Record";
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
  showAdminLiveStatus(message);
}

function showAdminLiveStatus(message: string): void {
  adminLiveStatusEl.textContent = message;
  adminLiveStatusEl.hidden = false;
}

function startQuestionRecording(): void {
  if (!activeStream) {
    throw new Error("Start a source before recording a question");
  }
  if (!webrtc.isReadyToSend()) {
    throw new Error("Connect before sending a question");
  }
  if (questionRecognition) {
    throw new Error("Question recording is already in progress");
  }

  const Recognition = getSpeechRecognitionConstructor();
  if (!Recognition) {
    setAnswerOutput("Voice recognition is unavailable in this browser.");
    setCameraStatus("Voice recognition is unavailable in this browser.");
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
      setQuestionStatus("idle");
      setQuestionTranscript("No question heard.", true);
      setAnswerOutput("No answer yet.");
      setCameraStatus("No question heard. Try recording again.");
      logger.log("No speech transcript captured");
      return;
    }

    try {
      sendQuestionText(transcript);
    } catch (error) {
      setQuestionStatus("idle");
      setAnswerOutput("Question send failed.");
      setCameraStatus("Question send failed.");
      logger.log(`Question send failed: ${String(error)}`);
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
  setCameraStatus("Listening for a question. Click to stop when finished.");
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
  setQuestionStatus("processing");
  setAnswerOutput("Processing...");
  setCameraStatus("Stopping recording and sending question...");
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
  webrtc.sendJson({ type: "question_text", text: normalizedText });
  setCameraStatus("Question sent. Waiting for model response...");
  logger.log(`Question text sent: ${normalizedText}`);
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

async function fetchHealthStatus(): Promise<string> {
  try {
    const response = await fetch(`${apiBaseUrl}/health`);
    if (!response.ok) {
      throw new Error(`status ${response.status}`);
    }

    const payload = (await response.json()) as { status?: string };
    clearError("health");
    return typeof payload.status === "string" ? payload.status : "unknown";
  } catch (error) {
    logErrorOnce("health", `Health check failed: ${String(error)}`);
    return "unreachable";
  }
}

function handleInferencePayload(rawPayload: string): void {
  let parsed: unknown;
  try {
    parsed = JSON.parse(rawPayload);
  } catch {
    logger.log(`Data message: ${rawPayload}`);
    return;
  }

  if (!isInferenceMessage(parsed)) {
    const candidate = parsed as Record<string, unknown>;
    if (candidate.type === "status" && typeof candidate.message === "string") {
      setQuestionStatus(candidate.message);
    }
    if (typeof candidate.answer === "string") {
      setAnswerOutput(candidate.answer);
      setQuestionStatus("complete");
      setCameraStatus("Model response received.");
    }
    if (typeof candidate.message === "string") {
      logger.log(candidate.message);
    } else {
      logger.log(`Data message: ${rawPayload}`);
    }
    if (typeof candidate.audio_base64 === "string" && candidate.audio_base64.length > 0) {
      playReturnedAudio(candidate.audio_base64);
    }
    return;
  }

  const message = parsed as InferenceMessage;
  logger.log(`Inference tick: ${message.timestamp}`);
  if (message.guidance_text) {
    logger.log(`Guidance: ${message.guidance_text}`);
  }

  const candidate = parsed as Record<string, unknown>;
  if (typeof candidate.answer === "string") {
    setAnswerOutput(candidate.answer);
    setQuestionStatus("complete");
    setCameraStatus("Model response received.");
  }

  if (typeof candidate.audio_base64 === "string" && candidate.audio_base64.length > 0) {
    playReturnedAudio(candidate.audio_base64);
  }

}

function playReturnedAudio(audioBase64: string): void {
  const audioUrl = `data:audio/mpeg;base64,${audioBase64}`;
  if (audioResponsePlayer) {
    audioResponsePlayer.pause();
  }

  const player = new Audio(audioUrl);
  audioResponsePlayer = player;
  setCameraStatus("Playing audio response...");
  void player.play().catch((error) => {
    setCameraStatus("Audio playback failed.");
    logger.log(`Audio playback failed: ${String(error)}`);
  });
}
