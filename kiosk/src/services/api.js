const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
const USE_MOCK = import.meta.env.VITE_USE_MOCK === "true";
const SESSION_KEY = "hid-session";

export function loadSession() {
  try {
    const saved = sessionStorage.getItem(SESSION_KEY);
    return saved ? JSON.parse(saved) : null;
  } catch {
    return null;
  }
}

export function clearSession() {
  sessionStorage.removeItem(SESSION_KEY);
}

function authHeaders() {
  const session = loadSession();
  return session?.token ? { Authorization: `Bearer ${session.token}` } : {};
}

async function readJson(response) {
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error(`Backend returned a non-JSON response (HTTP ${response.status}).`);
  }
  if (!response.ok) {
    const detail = data?.detail;
    const message = typeof detail === "string" ? detail : detail?.message || data?.reason;
    throw new Error(message || `Backend request failed (HTTP ${response.status}).`);
  }
  return data;
}

export async function signIn(username, password) {
  const response = await fetch(`${API_BASE_URL}/session`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password })
  });
  const data = await readJson(response);
  const session = { username: data.username, role: data.role, token: data.token };
  sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
  return session;
}

export async function requestCode(image) {
  const response = await fetch(`${API_BASE_URL}/otp/send`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ image })
  });
  return readJson(response);
}

export async function enrollPerson({ personId, phone, image }) {
  const response = await fetch(`${API_BASE_URL}/enroll`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ person_id: personId, phone, image })
  });
  return readJson(response);
}

const VALID_DECISIONS = new Set(["allow", "deny", "ask_again"]);

function normalizeDecision(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, "_");
}

/**
 * Sends one JSON payload to POST /check.
 * Contract: { frames: [raw_jpeg_base64, ...], otp: string | null }
 */
export async function submitCheck({ frames, otp = null }) {
  if (!Array.isArray(frames) || frames.length === 0) {
    throw new Error("At least one captured frame is required.");
  }

  const payload = { frames, otp };

  if (USE_MOCK) {
    // Mock only the response. No frames are uploaded in mock mode.
    console.info("Kiosk mock request:", {
      frameCount: frames.length,
      otpProvided: otp !== null
    });

    await new Promise((resolve) => setTimeout(resolve, 700));

    return {
      decision: "ask_again",
      reason: "Mock response: Person 2's service is not connected yet.",
      scores: {},
      elapsed_ms: 700
    };
  }

  const response = await fetch(`${API_BASE_URL}/check`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders()
    },
    body: JSON.stringify(payload)
  });

  const data = await readJson(response);

  const decision = normalizeDecision(data?.decision);
  if (!VALID_DECISIONS.has(decision)) {
    throw new Error(`Unexpected backend decision: ${data?.decision ?? "missing"}`);
  }

  return {
    decision,
    reason: data.reason ?? "",
    scores: data.scores ?? {},
    elapsed_ms: data.elapsed_ms ?? null
  };
}

