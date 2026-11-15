import { useCallback, useRef, useState } from "react";
import CameraPanel from "./components/CameraPanel";
import DecisionPanel from "./components/DecisionPanel";
import EnrollForm from "./components/EnrollForm";
import SignIn from "./components/SignIn";
import { clearSession, loadSession, requestCode, submitCheck } from "./services/api";
import { captureFrameSequence, captureJpegBase64, sleep } from "./utils/capture";

const EMPTY_FEEDBACK = {
  detected: false,
  position: "Waiting for face",
  pose: "Unavailable",
  eyes: "Unavailable",
  centered: false,
  eyeAspectRatio: null
};

export default function App() {
  const videoRef = useRef(null);
  const feedbackRef = useRef(EMPTY_FEEDBACK);

  const [feedback, setFeedback] = useState(EMPTY_FEEDBACK);
  const [cameraReady, setCameraReady] = useState(false);
  const [cameraError, setCameraError] = useState("");
  const [busy, setBusy] = useState(false);
  const [page, setPage] = useState("capture");
  const [result, setResult] = useState(null);
  const [otp, setOtp] = useState("");
  const [instruction, setInstruction] = useState("");
  const [error, setError] = useState("");
  const [codeNotice, setCodeNotice] = useState("");
  const [session, setSession] = useState(() => loadSession());

  function signOut() {
    clearSession();
    setSession(null);
    setPage("capture");
    setResult(null);
  }

  const handleFeedback = useCallback((nextFeedback) => {
    feedbackRef.current = nextFeedback;
    setFeedback(nextFeedback);
  }, []);

  const handleReady = useCallback((ready) => {
    setCameraReady(ready);
  }, []);

  const handleCameraError = useCallback((message) => {
    setCameraError(message);
  }, []);

  async function sendOneCheck(frames, code = null) {
    setBusy(true);
    setError("");
    try {
      // Exactly one POST /check request for this action.
      const response = await submitCheck({ frames, otp: code });
      setResult(response);
      setPage("result");
    } catch (requestError) {
      setError(requestError.message || "Verification request failed.");
      setPage("capture");
    } finally {
      setBusy(false);
      setInstruction("");
    }
  }

  async function handleInitialCheck() {
    if (!cameraReady || !feedbackRef.current.detected) {
      setError("Wait until the camera detects your face.");
      return;
    }

    setError("");
    setBusy(true);
    try {
      const frames = await captureFrameSequence(videoRef.current, 3);
      await sendOneCheck(frames, null);
    } catch (captureError) {
      setError(captureError.message || "Could not capture frames.");
      setBusy(false);
    }
  }

  async function handleRecapture() {
    setPage("capture");
    setResult(null);
    await sleep(100);
    await handleInitialCheck();
  }

  async function waitForEyeState(target, timeoutMs = 12000) {
    const started = Date.now();

    while (Date.now() - started < timeoutMs) {
      const current = feedbackRef.current;
      if (current.detected && current.eyes === target) return;
      await sleep(50);
    }

    throw new Error(
      target === "Closed"
        ? "Eyes-closed state was not detected. Please try again."
        : "Eyes-open state was not detected. Please try again."
    );
  }

  async function handleBlinkRetry() {
    if (!cameraReady) {
      setError("Camera is not ready.");
      return;
    }

    setBusy(true);
    setError("");
    setPage("capture");

    try {
      setInstruction("Please close your eyes.");
      await waitForEyeState("Closed");
      const closedFrame = await captureJpegBase64(videoRef.current);

      setInstruction("Now open your eyes.");
      await waitForEyeState("Open");
      const openFrame = await captureJpegBase64(videoRef.current);

      // One second POST /check request; frame order is closed then open.
      await sendOneCheck([closedFrame, openFrame], null);
    } catch (blinkError) {
      setError(blinkError.message || "Blink verification failed.");
      setBusy(false);
      setInstruction("");
    }
  }

  async function handleSendCode() {
    if (!cameraReady) {
      setError("Camera is not ready.");
      return;
    }

    setBusy(true);
    setError("");
    try {
      const frame = await captureJpegBase64(videoRef.current);
      const sent = await requestCode(frame);
      setCodeNotice(`A code was sent for ${sent.person_id}.`);
      setPage("code");
    } catch (sendError) {
      setError(sendError.message || "The code could not be sent.");
    } finally {
      setBusy(false);
    }
  }

  async function handleCodeSubmit(event) {
    event.preventDefault();

    if (!otp.trim()) {
      setError("Enter the code before submitting.");
      return;
    }

    if (!cameraReady) {
      setError("Camera is not ready.");
      return;
    }

    setBusy(true);
    setError("");

    try {
      const latestFrame = await captureJpegBase64(videoRef.current);
      // One POST /check request with one latest frame and the entered code.
      await sendOneCheck([latestFrame], otp.trim());
      setOtp("");
    } catch (codeError) {
      setError(codeError.message || "Could not submit code.");
      setBusy(false);
    }
  }

  const canStart =
    cameraReady &&
    feedback.detected &&
    feedback.centered &&
    !busy;

  if (!session) {
    return <SignIn onSignedIn={setSession} />;
  }

  if (session.role === "admin") {
    return <EnrollForm onSignOut={signOut} />;
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-lockup">
          <span className="brand-mark">HID</span>
          <span className="brand-divider" />
          <span className="brand-name">LIVENESS KIOSK</span>
        </div>
        <span className="topbar-status">
          <span className="status-dot" />
          USER
          <button className="text-button topbar-signout" type="button" onClick={signOut}>
            Sign out
          </button>
        </span>
      </header>

      <main className="main-content">
        <section className="intro">
          <p className="eyebrow">FACE LIVENESS DETECTION & AUTHENTICATION</p>
          <h1>Verify your identity</h1>
          <p className="intro-copy">
            Look directly at the camera and follow the on-screen guidance.
          </p>
        </section>

        <div className="workspace">
          <div className="left-column">
            <CameraPanel
              videoRef={videoRef}
              onFeedback={handleFeedback}
              onReady={handleReady}
              onError={handleCameraError}
            />

            <section className="feedback-card">
              <div className="card-title-row">
                <div>
                  <p className="section-kicker">LIVE ANALYSIS</p>
                  <h2>Camera feedback</h2>
                </div>
                <span className={`ready-badge ${feedback.detected ? "is-ready" : ""}`}>
                  {feedback.detected ? "FACE FOUND" : "SEARCHING"}
                </span>
              </div>

              <div className="feedback-grid">
                <FeedbackItem label="Face position" value={feedback.position} />
                <FeedbackItem label="Head pose" value={feedback.pose} />
                <FeedbackItem label="Blink / eyes" value={feedback.eyes} />
              </div>
              <p className="feedback-note">
                Feedback is processed in your browser. Video frames are not continuously uploaded.
              </p>
            </section>
          </div>

          <div className="right-column">
            {page === "capture" && (
              <section className="action-card">
                <p className="section-kicker">READY TO CHECK</p>
                <h2>Start verification</h2>
                <p>
                  We will capture three JPEG frames at approximately 150 ms intervals
                  and send them together in one request.
                </p>

                {instruction && (
                  <div className="instruction-banner">{instruction}</div>
                )}

                <button
                  className="primary-button"
                  disabled={!canStart}
                  onClick={handleInitialCheck}
                >
                  {busy ? "Processing…" : "Capture & verify"}
                </button>

                {!cameraReady && !cameraError && (
                  <p className="helper-text">Waiting for camera and MediaPipe…</p>
                )}
                {cameraReady && !feedback.detected && (
                  <p className="helper-text">Move into the camera view.</p>
                )}
                {feedback.detected && !feedback.centered && (
                  <p className="helper-text">Center your face to continue.</p>
                )}
              </section>
            )}

            {page === "result" && result && (
              <DecisionPanel
                result={result}
                onRecapture={handleRecapture}
                onBlink={handleBlinkRetry}
                onCode={handleSendCode}
              />
            )}

            {page === "code" && (
              <form className="action-card code-card" onSubmit={handleCodeSubmit}>
                <p className="section-kicker">ADDITIONAL VERIFICATION</p>
                <h2>Enter your code</h2>
                <p>
                  {codeNotice || "A code is sent to the enrolled phone, then checked with the latest frame."}
                </p>
                <label htmlFor="otp">Verification code</label>
                <input
                  id="otp"
                  value={otp}
                  onChange={(event) => setOtp(event.target.value)}
                  placeholder="Enter code"
                  autoComplete="one-time-code"
                />
                <button className="primary-button" type="submit" disabled={busy || !cameraReady}>
                  {busy ? "Submitting…" : "Submit code"}
                </button>
                <button
                  className="text-button"
                  type="button"
                  onClick={() => setPage("result")}
                >
                  Back to decision
                </button>
              </form>
            )}

            {busy && (
              <div className="busy-indicator" role="status">
                <span className="spinner" />
                <span>Processing verification…</span>
              </div>
            )}

            {cameraError && <div className="error-banner">{cameraError}</div>}
            {error && <div className="error-banner">{error}</div>}
          </div>
        </div>
      </main>

      <footer className="footer">
        <span>HID · FACE LIVENESS DETECTION</span>
        <span>PERSON 1 · KIOSK</span>
      </footer>
    </div>
  );
}

function FeedbackItem({ label, value }) {
  const good =
    value === "Centered" ||
    value === "Open" ||
    value.startsWith("Facing camera");

  return (
    <div className="feedback-item">
      <span>{label}</span>
      <strong className={good ? "feedback-good" : ""}>{value}</strong>
    </div>
  );
}