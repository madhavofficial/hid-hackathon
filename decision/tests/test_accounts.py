import base64
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from decision.app import create_app
from decision.tests.test_service import Harness


def jpeg_bytes():
    image = Image.new("RGB", (40, 40), (20, 40, 80))
    output = BytesIO()
    image.save(output, format="JPEG")
    return output.getvalue()


def client_for(harness):
    return TestClient(harness.app())


def sign_in(client, username, password):
    return client.post("/session", json={"username": username, "password": password})


def test_user_can_sign_in_and_admin_password_does_not_match():
    harness = Harness()
    try:
        with client_for(harness) as client:
            user = sign_in(client, "user", "user")
            assert user.status_code == 200
            assert user.json()["role"] == "user"
            assert sign_in(client, "user", "admin").status_code == 401
            assert sign_in(client, "admin", "admin").json()["role"] == "admin"
    finally:
        harness.close()


def test_check_requires_a_signed_in_account():
    harness = Harness()
    try:
        with client_for(harness) as client:
            denied = client.post("/check", json={"frames": [], "otp": None})
            assert denied.status_code == 401
            token = sign_in(client, "user", "user").json()["token"]
            allowed = client.post(
                "/check",
                json={"frames": ["not-base64", "also-bad"], "otp": None},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert allowed.status_code == 422
    finally:
        harness.close()


def test_code_is_sent_only_for_an_enrolled_face(monkeypatch):
    sent = []

    def fake_send(person_id, phone_number=None):
        sent.append(person_id)
        return {"person_id": person_id, "sns_sent": True, "expires_at": 1}

    monkeypatch.setattr("identity.otp.send_otp", fake_send)
    image = base64.b64encode(jpeg_bytes()).decode()
    harness = Harness()
    try:
        with client_for(harness) as client:
            token = sign_in(client, "user", "user").json()["token"]
            sent_response = client.post(
                "/otp/send",
                json={"image": image},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert sent_response.status_code == 200
            body = sent_response.json()
            assert body == {"sent": True, "person_id": "person-1"}
            assert "code" not in body
            assert sent == ["person-1"]

            harness.rekognition.person_id = None
            missed = client.post(
                "/otp/send",
                json={"image": image},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert missed.status_code == 422
            assert sent == ["person-1"]
    finally:
        harness.close()


def test_only_admin_can_enroll(monkeypatch):
    calls = []

    def fake_enroll(person_id, image_path, phone=None, **_kwargs):
        calls.append((person_id, phone, image_path))
        return {
            "person_id": person_id,
            "face_id": "face-1",
            "phone": phone,
            "quality_warning": None,
        }

    monkeypatch.setattr("identity.enroll.enroll_person", fake_enroll)
    body = {
        "person_id": "alice",
        "phone": "+919876543210",
        "image": base64.b64encode(jpeg_bytes()).decode(),
    }
    harness = Harness()
    try:
        with client_for(harness) as client:
            user = sign_in(client, "user", "user").json()["token"]
            forbidden = client.post(
                "/enroll",
                json=body,
                headers={"Authorization": f"Bearer {user}"},
            )
            assert forbidden.status_code == 403
            assert calls == []
            admin = sign_in(client, "admin", "admin").json()["token"]
            enrolled = client.post(
                "/enroll",
                json=body,
                headers={"Authorization": f"Bearer {admin}"},
            )
            assert enrolled.status_code == 200
            assert enrolled.json()["person_id"] == "alice"
            assert calls[0][0] == "alice"
            assert calls[0][1] == "+919876543210"
    finally:
        harness.close()
