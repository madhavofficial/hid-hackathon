import { useEffect, useRef, useState } from "react";
import {
  FaceLandmarker,
  FilesetResolver
} from "@mediapipe/tasks-vision";
import { analyzeFace } from "../utils/faceAnalysis";

const WASM_URL =
  "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm";
const MODEL_URL = "/models/face_landmarker.task";

export default function CameraPanel({
  videoRef,
  onFeedback,
  onReady,
  onError
}) {
  const canvasRef = useRef(null);
  const [cameraMessage, setCameraMessage] = useState("Requesting camera access…");

  useEffect(() => {
    let stream;
    let landmarker;
    let animationFrameId;
    let stopped = false;
    let lastVideoTime = -1;
    let lastFeedbackTime = 0;

    const clearOverlay = () => {
      const canvas = canvasRef.current;
      const context = canvas?.getContext("2d");
      if (canvas && context) {
        context.clearRect(0, 0, canvas.width, canvas.height);
      }
    };

    const drawBounds = (feedback) => {
      const canvas = canvasRef.current;
      const video = videoRef.current;
      const context = canvas?.getContext("2d");
      if (!canvas || !context || !video) return;

      const width = video.videoWidth;
      const height = video.videoHeight;
      if (!width || !height) return;

      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
      }

      context.clearRect(0, 0, width, height);

      if (!feedback.detected || !feedback.bounds) return;

      const { minX, maxX, minY, maxY } = feedback.bounds;
      context.strokeStyle = feedback.centered ? "#22c55e" : "#f59e0b";
      context.lineWidth = 4;
      context.strokeRect(
        minX * width,
        minY * height,
        (maxX - minX) * width,
        (maxY - minY) * height
      );
    };

    async function initialize() {
      try {
        if (!navigator.mediaDevices?.getUserMedia) {
          throw new Error("Camera access requires HTTPS or localhost in a supported browser.");
        }

        stream = await navigator.mediaDevices.getUserMedia({
          audio: false,
          video: {
            facingMode: "user",
            width: { ideal: 640 },
            height: { ideal: 480 }
          }
        });

        if (stopped) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }

        const video = videoRef.current;
        video.srcObject = stream;
        await video.play();

        setCameraMessage("Loading face detection…");

        const vision = await FilesetResolver.forVisionTasks(WASM_URL);
        landmarker = await FaceLandmarker.createFromOptions(vision, {
          baseOptions: { modelAssetPath: MODEL_URL },
          runningMode: "VIDEO",
          numFaces: 1,
          minFaceDetectionConfidence: 0.5,
          minFacePresenceConfidence: 0.5,
          minTrackingConfidence: 0.5
        });

        if (stopped) return;

        setCameraMessage("Camera and face detection ready");
        onReady(true);

        const detect = () => {
          if (stopped) return;

          if (
            video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA &&
            video.currentTime !== lastVideoTime
          ) {
            lastVideoTime = video.currentTime;

            const result = landmarker.detectForVideo(video, performance.now());
            const feedback = analyzeFace(result.faceLandmarks?.[0]);

            drawBounds(feedback);

            const now = performance.now();
            if (now - lastFeedbackTime >= 100) {
              onFeedback(feedback);
              lastFeedbackTime = now;
            }
          }

          animationFrameId = requestAnimationFrame(detect);
        };

        detect();
      } catch (error) {
        console.error("Camera/MediaPipe initialization failed:", error);
        setCameraMessage(error.message || "Could not start camera.");
        onReady(false);
        onError(error.message || "Could not start camera.");
      }
    }

    initialize();

    return () => {
      stopped = true;
      cancelAnimationFrame(animationFrameId);
      landmarker?.close();
      stream?.getTracks().forEach((track) => track.stop());
      clearOverlay();
    };
  }, [videoRef, onFeedback, onReady, onError]);

  return (
    <section className="camera-card">
      <div className="camera-heading">
        <div>
          <span className="section-kicker">LIVE CAMERA</span>
          <h2>Position your face</h2>
        </div>
        <span className="live-pill"><span className="live-dot" /> LIVE</span>
      </div>

      <div className="video-frame">
        <video ref={videoRef} autoPlay playsInline muted className="camera-video" />
        <canvas ref={canvasRef} className="camera-overlay" />
        <div className="camera-hint">Keep your face inside the frame</div>
      </div>

      <p className="camera-message">{cameraMessage}</p>
    </section>
  );
}