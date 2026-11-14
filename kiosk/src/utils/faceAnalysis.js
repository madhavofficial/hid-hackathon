function distance(a, b) {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function eyeAspectRatio(points, indexes) {
  const [p1, p2, p3, p4, p5, p6] = indexes;
  const verticalOne = distance(points[p2], points[p6]);
  const verticalTwo = distance(points[p3], points[p5]);
  const horizontal = distance(points[p1], points[p4]);

  if (!horizontal) return 0;
  return (verticalOne + verticalTwo) / (2 * horizontal);
}

export function analyzeFace(landmarks) {
  if (!landmarks || landmarks.length < 264) {
    return {
      detected: false,
      position: "No face detected",
      pose: "Unavailable",
      eyes: "Unavailable",
      centered: false,
      eyeAspectRatio: null,
      bounds: null
    };
  }

  const xs = landmarks.map((point) => point.x);
  const ys = landmarks.map((point) => point.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);

  const centerX = (minX + maxX) / 2;
  const centerY = (minY + maxY) / 2;
  const centered =
    centerX >= 0.35 &&
    centerX <= 0.65 &&
    centerY >= 0.25 &&
    centerY <= 0.75;

  // Landmark-based approximation. This is feedback, not calibrated 3D pose.
  const nose = landmarks[1];
  const leftEyeOuter = landmarks[33];
  const rightEyeOuter = landmarks[263];
  const eyeMidX = (leftEyeOuter.x + rightEyeOuter.x) / 2;
  const eyeWidth = Math.max(
    Math.abs(rightEyeOuter.x - leftEyeOuter.x),
    0.001
  );
  const yawOffset = (nose.x - eyeMidX) / eyeWidth;

  let pose = "Facing camera (approx.)";
  if (yawOffset > 0.18) pose = "Turn head slightly";
  if (yawOffset < -0.18) pose = "Turn head slightly";

  const leftEAR = eyeAspectRatio(
    landmarks,
    [33, 160, 158, 133, 153, 144]
  );
  const rightEAR = eyeAspectRatio(
    landmarks,
    [362, 385, 387, 263, 373, 380]
  );
  const ear = (leftEAR + rightEAR) / 2;

  // This threshold may need adjustment for different cameras/users.
  const eyes = ear < 0.20 ? "Closed" : "Open";

  return {
    detected: true,
    position: centered ? "Centered" : "Move face to center",
    pose,
    eyes,
    centered,
    eyeAspectRatio: ear,
    bounds: { minX, maxX, minY, maxY }
  };
}