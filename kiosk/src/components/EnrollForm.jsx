import { useState } from "react";
import { enrollPerson } from "../services/api";

function readPhoto(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1]);
    reader.onerror = () => reject(new Error("Could not read that photo."));
    reader.readAsDataURL(file);
  });
}

export default function EnrollForm({ onSignOut }) {
  const [personId, setPersonId] = useState("");
  const [phone, setPhone] = useState("");
  const [photo, setPhoto] = useState(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    if (!photo) {
      setError("Choose a JPEG photo.");
      return;
    }
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const image = await readPhoto(photo);
      const result = await enrollPerson({
        personId: personId.trim(),
        phone: phone.trim(),
        image
      });
      setMessage(`${result.person_id} is enrolled. A user account can now be verified.`);
      setPersonId("");
      setPhone("");
      setPhoto(null);
      event.target.reset();
    } catch (enrollError) {
      setError(enrollError.message || "Enrollment failed.");
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
          <span className="brand-name">ADMIN</span>
        </div>
        <button className="text-button topbar-signout" type="button" onClick={onSignOut}>
          Sign out
        </button>
      </header>
      <main className="main-content">
        <section className="intro">
          <p className="eyebrow">ADMIN</p>
          <h1>Enroll a person</h1>
          <p className="intro-copy">
            Only this account can add someone. Verification stays on the user account.
          </p>
        </section>
        <form className="action-card account-card" onSubmit={handleSubmit}>
          <label htmlFor="person-id">Person id</label>
          <input
            id="person-id"
            value={personId}
            onChange={(event) => setPersonId(event.target.value)}
            placeholder="alice"
            required
          />
          <label htmlFor="phone">Phone</label>
          <input
            id="phone"
            value={phone}
            onChange={(event) => setPhone(event.target.value)}
            placeholder="+919876543210"
            required
          />
          <label htmlFor="photo">Photo</label>
          <input
            id="photo"
            type="file"
            accept="image/jpeg"
            onChange={(event) => setPhoto(event.target.files?.[0] || null)}
            required
          />
          <button className="primary-button" type="submit" disabled={busy}>
            {busy ? "Enrolling…" : "Enroll"}
          </button>
          {message && <p className="helper-text">{message}</p>}
          {error && <div className="error-banner">{error}</div>}
        </form>
      </main>
    </div>
  );
}
