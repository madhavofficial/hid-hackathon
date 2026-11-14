import base64
import threading
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from decision.app import create_app
from decision.config import Settings
from decision.service import Runtime
from decision.vision import FrameAnalysis, decode_frame


def encoded_jpeg(color):
    image = Image.new("RGB", (160, 160), color)
    output = BytesIO()
    image.save(output, format="JPEG")
    return base64.b64encode(output.getvalue()).decode("ascii")


class FakeModel:
    def __init__(self, value=0.99, error=None):
        self.value = value
        self.error = error
        self.calls = 0

    def infer(self, _image):
        self.calls += 1
        if self.error:
            raise self.error
        return self.value


class FakeVisitsTable:
    def __init__(self):
        self.items = []

    def put_item(self, Item):
        self.items.append(Item)


class FakeOtpTable:
    def __init__(self, code="482901"):
        self.code = code
        self.item = {"code": code, "expires_at": 4_000_000_000, "attempts": 0}
        self.deleted = False

    def get_item(self, Key):
        return {"Item": self.item} if not self.deleted else {}

    def update_item(self, **_kwargs):
        self.item["attempts"] += 1

    def delete_item(self, **_kwargs):
        self.deleted = True


class FakeRekognition:
    def __init__(self, similarity=99.0, person_id="person-1", parallel=False):
        self.similarity = similarity
        self.person_id = person_id
        self.detect_calls = 0
        self.search_calls = 0
        self.barrier = threading.Barrier(2) if parallel else None

    def detect_faces(self, **_kwargs):
        self.detect_calls += 1
        if self.barrier:
            self.barrier.wait(timeout=2)
        return {
            "FaceDetails": [
                {
                    "BoundingBox": {"Width": 0.5, "Height": 0.6},
                    "Quality": {"Sharpness": 80.0, "Brightness": 60.0},
                    "Pose": {"Yaw": 0.0, "Pitch": 0.0, "Roll": 0.0},
                    "EyesOpen": {"Value": True, "Confidence": 99.0},
                }
            ]
        }

    def search_faces_by_image(self, **_kwargs):
        self.search_calls += 1
        if self.barrier:
            self.barrier.wait(timeout=2)
        matches = []
        if self.person_id:
            matches = [
                {
                    "Similarity": self.similarity,
                    "Face": {"ExternalImageId": self.person_id},
                }
            ]
        return {"FaceMatches": matches}


class FakeAnalyzer:
    def __init__(self, motion=0.02, blink_sequence=False):
        self.motion = motion
        self.blink_sequence = blink_sequence

    def __call__(self, frames):
        return FrameAnalysis(len(frames) - 1, self.motion, self.blink_sequence)


class Harness:
    def __init__(
        self,
        *,
        spoof=0.99,
        similarity=99.0,
        person_id="person-1",
        motion=0.02,
        blink_sequence=False,
        model_error=None,
        parallel=False,
    ):
        self.settings = Settings()
        self.model = FakeModel(spoof, model_error)
        self.rekognition = FakeRekognition(similarity, person_id, parallel)
        self.visits = FakeVisitsTable()
        self.otp = FakeOtpTable()
        self.executor = ThreadPoolExecutor(max_workers=3)
        self.runtime = Runtime(
            self.settings,
            self.model,
            self.rekognition,
            self.visits,
            self.otp,
            self.executor,
        )
        self.analyzer = FakeAnalyzer(motion, blink_sequence)

    def close(self):
        self.executor.shutdown(wait=True)

    def app(self):
        return create_app(lambda _settings: self.runtime)


def payload(otp=None):
    return {
        "frames": [encoded_jpeg((i * 20, 40, 80)) for i in range(2)],
        "otp": otp,
    }


def test_data_uri_jpeg_is_decoded():
    encoded = encoded_jpeg((20, 40, 80))
    decoded = decode_frame(f"data:image/jpeg;base64,{encoded}", 1024 * 1024)
    assert decoded.image.size == (160, 160)


def send(harness, data=None):
    from decision import service

    original = service.analyze_frames
    service.analyze_frames = harness.analyzer
    try:
        with TestClient(harness.app()) as client:
            return client.post("/check", json=payload() if data is None else data)
    finally:
        service.analyze_frames = original


def test_allow_and_single_rekognition_calls():
    harness = Harness()
    try:
        response = send(harness)
        assert response.status_code == 200
        assert response.json()["decision"] == "allow"
        assert response.json()["reason"] == "live_and_match"
        assert harness.rekognition.detect_calls == 1
        assert harness.rekognition.search_calls == 1
        assert len(harness.visits.items) == 1
    finally:
        harness.close()


def test_unenrolled_low_live_score_is_not_spoof():
    harness = Harness(spoof=0.0004, person_id=None, similarity=0.0)
    try:
        response = send(harness)
        assert response.json()["decision"] == "deny"
        assert response.json()["reason"] == "identity_mismatch"
    finally:
        harness.close()


def test_identity_mismatch():
    harness = Harness(person_id=None)
    try:
        response = send(harness)
        assert response.json()["decision"] == "deny"
        assert response.json()["reason"] == "identity_mismatch"
    finally:
        harness.close()


def test_low_quality_face_asks_again():
    harness = Harness()
    harness.rekognition.detect_faces = lambda **_kwargs: {
        "FaceDetails": [
            {
                "BoundingBox": {"Width": 0.05, "Height": 0.1},
                "Quality": {"Sharpness": 80.0, "Brightness": 60.0},
                "Pose": {"Yaw": 0.0, "Pitch": 0.0, "Roll": 0.0},
                "EyesOpen": {"Value": True},
            }
        ]
    }
    try:
        response = send(harness)
        assert response.json()["decision"] == "ask_again"
        assert response.json()["reason"] == "low_quality"
    finally:
        harness.close()


def test_low_spoof_score_denies():
    harness = Harness(spoof=0.1)
    try:
        response = send(harness)
        assert response.json()["decision"] == "deny"
        assert response.json()["reason"] == "spoof"
    finally:
        harness.close()


def test_blink_confirmation_prevents_static_motion_spoof_rejection():
    harness = Harness(motion=0.0, blink_sequence=True)
    try:
        response = send(harness)
        assert response.json()["decision"] == "allow"
        assert response.json()["reason"] == "live_and_match"
    finally:
        harness.close()


def test_matching_face_with_no_motion_is_denied_as_spoof():
    harness = Harness(motion=0.0)
    try:
        response = send(harness)
        assert response.json()["decision"] == "deny"
        assert response.json()["reason"] == "spoof"
    finally:
        harness.close()


def test_valid_otp_is_kept_when_another_capture_is_needed():
    harness = Harness()
    harness.rekognition.detect_faces = lambda **_kwargs: {
        "FaceDetails": [
            {
                "BoundingBox": {"Width": 0.05, "Height": 0.1},
                "Quality": {"Sharpness": 80.0, "Brightness": 60.0},
                "Pose": {"Yaw": 0.0, "Pitch": 0.0, "Roll": 0.0},
                "EyesOpen": {"Value": True},
            }
        ]
    }
    try:
        response = send(harness, payload("482901"))
        assert response.json()["decision"] == "ask_again"
        assert harness.otp.deleted is False
    finally:
        harness.close()


def test_blink_clears_closed_eyes():
    harness = Harness(blink_sequence=True)
    harness.rekognition.detect_faces = lambda **_kwargs: {
        "FaceDetails": [
            {
                "BoundingBox": {"Width": 0.5, "Height": 0.6},
                "Quality": {"Sharpness": 80.0, "Brightness": 60.0},
                "Pose": {"Yaw": 0.0, "Pitch": 0.0, "Roll": 0.0},
                "EyesOpen": {"Value": False, "Confidence": 99.0},
            }
        ]
    }
    try:
        response = send(harness)
        assert response.json()["decision"] == "allow"
        assert response.json()["reason"] == "live_and_match"
    finally:
        harness.close()


def test_invalid_otp_is_denied_and_valid_otp_is_consumed():
    invalid = Harness()
    try:
        response = send(invalid, payload("wrong-code"))
        assert response.json()["decision"] == "deny"
        assert response.json()["reason"] == "otp_failed"
        assert invalid.otp.item["attempts"] == 1
    finally:
        invalid.close()

    valid = Harness()
    try:
        response = send(valid, payload("482901"))
        assert response.json()["decision"] == "allow"
        assert valid.otp.deleted
    finally:
        valid.close()


def test_one_frame_requires_a_code():
    rejected_harness = Harness()
    accepted_harness = Harness()
    try:
        rejected = send(
            rejected_harness, {"frames": [encoded_jpeg((20, 40, 80))], "otp": None}
        )
        assert rejected.status_code == 422
        accepted = send(
            accepted_harness, {"frames": [encoded_jpeg((20, 40, 80))], "otp": "482901"}
        )
        assert accepted.status_code == 200
        assert accepted.json()["decision"] == "allow"
    finally:
        rejected_harness.close()
        accepted_harness.close()


def test_invalid_input_is_rejected_and_logged():
    harness = Harness()
    try:
        response = send(harness, {"frames": ["not-base64"], "otp": None})
        assert response.status_code == 422
        assert len(harness.visits.items) == 1
        assert harness.visits.items[0]["reason"] == "invalid_input"
        assert harness.rekognition.detect_calls == 0
    finally:
        harness.close()


def test_analysis_failure_is_logged_without_leaking_input():
    harness = Harness(model_error=RuntimeError("model unavailable"))
    try:
        response = send(harness, payload("secret-otp"))
        assert response.status_code == 503
        assert len(harness.visits.items) == 1
        row = harness.visits.items[0]
        assert row["reason"] == "analysis_error"
        assert row["error"] == "RuntimeError"
        assert "secret-otp" not in repr(row)
    finally:
        harness.close()


def test_rekognition_calls_run_in_parallel():
    harness = Harness(parallel=True)
    try:
        response = send(harness)
        assert response.status_code == 200
        assert harness.rekognition.detect_calls == 1
        assert harness.rekognition.search_calls == 1
    finally:
        harness.close()


def test_model_is_initialized_once_for_warm_app(monkeypatch):
    from decision import service

    visits = FakeVisitsTable()
    otp = FakeOtpTable()
    rekognition = FakeRekognition()
    model_initializations = []
    model = FakeModel()

    def initialize_model(*_args, **_kwargs):
        model_initializations.append("initialized")
        return model

    class FakeDynamoDB:
        def Table(self, name):
            return visits if name == "visits" else otp

    monkeypatch.setattr(service, "OnnxAntiSpoofModel", initialize_model)
    monkeypatch.setattr(service.boto3, "client", lambda *_args, **_kwargs: rekognition)
    monkeypatch.setattr(
        service.boto3, "resource", lambda *_args, **_kwargs: FakeDynamoDB()
    )
    monkeypatch.setattr(service, "analyze_frames", FakeAnalyzer())

    with TestClient(create_app(service.create_runtime)) as client:
        assert client.post("/check", json=payload()).status_code == 200
        assert client.post("/check", json=payload()).status_code == 200
    assert len(model_initializations) == 1
    assert model.calls == 2


def test_missing_onnx_model_fails_closed(tmp_path):
    from decision.model import ModelUnavailableError, OnnxAntiSpoofModel

    model = OnnxAntiSpoofModel(tmp_path / "missing.onnx")
    try:
        model.infer(Image.new("RGB", (80, 80)))
    except ModelUnavailableError:
        pass
    else:
        raise AssertionError("A missing model must not produce a liveness score")
