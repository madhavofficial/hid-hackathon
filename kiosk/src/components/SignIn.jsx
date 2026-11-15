import { useState } from "react";
import { signIn } from "../services/api";

export default function SignIn({ onSignedIn }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      onSignedIn(await signIn(username.trim(), password));
    } catch (signInError) {
      setError(signInError.message || "Sign in failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-lockup">
          <span className="brand-mark">HID</span>
          <span className="brand-divider" />
          <span className="brand-name">LIVENESS KIOSK</span>
        </div>
      </header>
      <main className="main-content">
        <section className="intro">
          <p className="eyebrow">ACCOUNT</p>
          <h1>Sign in</h1>
          <p className="intro-copy">
            An admin enrolls people. A user can only be verified.
          </p>
        </section>
        <form className="action-card account-card" onSubmit={handleSubmit}>
          <label htmlFor="username">Account</label>
          <input
            id="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoComplete="username"
            placeholder="admin or user"
          />
          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
          />
          <button className="primary-button" type="submit" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
          {error && <div className="error-banner">{error}</div>}
          <p className="helper-text">Demo accounts: admin / admin, and user / user.</p>
        </form>
      </main>
    </div>
  );
}
