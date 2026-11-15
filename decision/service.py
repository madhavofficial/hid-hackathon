import hmac
import math
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from .config import Settings
from .model import OnnxAntiSpoofModel
from .schedule import campus_access
from .vision import (
    DecodedFrame,
    FrameAnalysis,
    InvalidFrameError,
    analyze_frames,
    crop_face,
    decode_frame,
)


class AnalysisError(RuntimeError):
    pass


def _no_face_error(error: BaseException) -> bool:
    if not isinstance(error, ClientError):
        return False
    details = error.response.get("Error", {})
    message = str(details.get("Message", "")).lower()
    return details.get("Code") == "InvalidParameterException" and "no face" in message


def _rekognition_result(future, empty: dict[str, list]) -> dict:
    error = future.exception()
    if error is None:
        return future.result()
    if _no_face_error(error):
        return empty
    raise error


def _worker_ready() -> None:
    return None


@dataclass
class Runtime:
    settings: Settings
    model: OnnxAntiSpoofModel
    rekognition: Any
    visits_table: Any
    otp_table: Any
    executor: ThreadPoolExecutor

    def close(self) -> None:
        self.executor.shutdown(wait=True, cancel_futures=True)


def create_runtime(settings: Settings) -> Runtime:
    aws_config = BotoConfig(
        connect_timeout=2.0,
        read_timeout=5.0,
        retries={"total_max_attempts": 2},
    )
    rekognition = boto3.client(
        "rekognition", region_name=settings.aws_region, config=aws_config
    )
    dynamodb = boto3.resource(
        "dynamodb", region_name=settings.aws_region, config=aws_config
    )
    model = OnnxAntiSpoofModel(
        settings.model_path,
        live_output_index=settings.live_output_index,
        input_width=settings.model_input_width,
        input_height=settings.model_input_height,
    )
    executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="decision")
    for future in [executor.submit(_worker_ready) for _ in range(3)]:
        future.result()
    return Runtime(
        settings=settings,
        model=model,
        rekognition=rekognition,
        visits_table=dynamodb.Table(settings.visits_table),
        otp_table=dynamodb.Table(settings.otp_table),
        executor=executor,
    )


def _visit_item(
    visit_id: str,
    started_at: float,
    decision: str,
    reason: str,
    scores: dict[str, float | None],
    label: str | None,
    error: str | None = None,
) -> dict[str, Any]:
    def ddb_number(value: float | None) -> Decimal | None:
        return Decimal(str(value)) if value is not None else None

    item: dict[str, Any] = {
        "visit_id": visit_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "decision": decision,
        "reason": reason,
        "spoof": ddb_number(scores["spoof"]),
        "similarity": ddb_number(scores["similarity"]),
        "sharpness": ddb_number(scores["sharpness"]),
        "elapsed_ms": int((time.perf_counter() - started_at) * 1000),
        "label": label,
    }
    if error:
        item["error"] = error
    return item


def _persist(
    runtime: Runtime,
    visit_id: str,
    started_at: float,
    decision: str,
    reason: str,
    scores: dict[str, float | None],
    label: str | None,
    error: str | None = None,
) -> dict[str, Any]:
    item = _visit_item(visit_id, started_at, decision, reason, scores, label, error)
    runtime.visits_table.put_item(Item=item)
    return item


def _verify_otp(runtime: Runtime, otp: str, person_id: str) -> bool:
    response = runtime.otp_table.get_item(Key={"person_id": person_id})
    item = response.get("Item")
    if not item:
        return False

    now = int(time.time())
    if int(item.get("expires_at", 0)) < now:
        runtime.otp_table.delete_item(Key={"person_id": person_id})
        return False

    if not hmac.compare_digest(str(item.get("code", "")).strip(), otp.strip()):
        attempts = int(item.get("attempts", 0)) + 1
        max_attempts = runtime.settings.otp_max_attempts
        if attempts >= max_attempts:
            runtime.otp_table.delete_item(Key={"person_id": person_id})
        else:
            runtime.otp_table.update_item(
                Key={"person_id": person_id},
                UpdateExpression="SET attempts = :attempts",
                ExpressionAttributeValues={":attempts": attempts},
            )
        return False

    return True


def _consume_otp(runtime: Runtime, person_id: str) -> None:
    runtime.otp_table.delete_item(Key={"person_id": person_id})


def _face_quality(
    response: dict[str, Any],
    settings: Settings,
) -> tuple[dict[str, Any] | None, str | None]:
    faces = response.get("FaceDetails") or []
    if not faces:
        return None, "no_face"

    face = max(
        faces,
        key=lambda detail: (
            detail.get("BoundingBox", {}).get("Width", 0)
            * detail.get("BoundingBox", {}).get("Height", 0)
        ),
    )
    quality = face.get("Quality") or {}
    pose = face.get("Pose") or {}
    box = face.get("BoundingBox") or {}
    if float(box.get("Width", 0)) < settings.face_width_min:
        return face, "tiny_face"
    if float(quality.get("Sharpness", 0)) < settings.sharpness_threshold:
        return face, "sharpness"
    brightness = float(quality.get("Brightness", 0))
    sharpness = float(quality.get("Sharpness", 0))
    if not math.isfinite(brightness) or not math.isfinite(sharpness):
        return face, "image_quality"
    if not settings.brightness_min <= brightness <= settings.brightness_max:
        return face, "brightness"
    if any(
        not math.isfinite(float(pose.get(axis, 1000)))
        or abs(float(pose.get(axis, 1000))) > settings.pose_angle_max
        for axis in ("Yaw", "Pitch", "Roll")
    ):
        return face, "pose"

    eye_state = face.get("EyesOpen") or {}
    if eye_state.get("Value") is not True:
        return face, "eyes_closed"
    return face, None


def _safe_quality_scores(face: dict[str, Any] | None) -> float | None:
    if not face:
        return None
    sharpness = (face.get("Quality") or {}).get("Sharpness")
    return float(sharpness) if sharpness is not None else None


def _analyze_request(
    runtime: Runtime,
    decoded: list[DecodedFrame],
    otp: str | None,
    visit_id: str,
    started_at: float,
    label: str | None,
) -> dict[str, Any]:
    settings = runtime.settings
    frame_analysis: FrameAnalysis = analyze_frames(decoded)
    selected = decoded[frame_analysis.selected_index]
    score_values: dict[str, float | None] = {
        "spoof": None,
        "similarity": 0.0,
        "sharpness": None,
    }

    model_future = runtime.executor.submit(
        runtime.model.infer, crop_face(selected.image)
    )
    detect_future = runtime.executor.submit(
        runtime.rekognition.detect_faces,
        Image={"Bytes": selected.jpeg_bytes},
        Attributes=["ALL"],
    )
    search_future = runtime.executor.submit(
        runtime.rekognition.search_faces_by_image,
        CollectionId=settings.collection_id,
        Image={"Bytes": selected.jpeg_bytes},
        FaceMatchThreshold=settings.similarity_threshold,
        MaxFaces=1,
    )

    model_error = model_future.exception()
    if model_error is not None:
        raise model_error
    model_result = model_future.result()
    detect_response = _rekognition_result(detect_future, {"FaceDetails": []})
    search_response = _rekognition_result(search_future, {"FaceMatches": []})
    spoof_score = float(model_result)
    if not math.isfinite(spoof_score) or not 0 <= spoof_score <= 1:
        raise ValueError("Anti-spoof model returned an invalid probability")
    matches = search_response.get("FaceMatches") or []
    similarity = float(matches[0].get("Similarity", 0.0)) if matches else 0.0
    if not math.isfinite(similarity) or not 0 <= similarity <= 100:
        raise ValueError("Rekognition returned an invalid similarity score")
    person_id = (
        (matches[0].get("Face") or {}).get("ExternalImageId") if matches else None
    )
    score_values.update(spoof=spoof_score, similarity=similarity)

    face, quality_reason = _face_quality(detect_response, settings)
    sharpness = _safe_quality_scores(face)
    score_values["sharpness"] = sharpness
    otp_accepted = False
    if otp is not None:
        # A code retry with no Rekognition face, or no enrolled match, has not
        # checked the digits. Ask for another frame and leave the code unused.
        if not person_id or quality_reason == "no_face":
            return _persist(
                runtime,
                visit_id,
                started_at,
                "ask_again",
                "low_quality",
                score_values,
                label,
            )
        otp_accepted = _verify_otp(runtime, otp, person_id)
        if not otp_accepted:
            return _persist(
                runtime,
                visit_id,
                started_at,
                "deny",
                "otp_failed",
                score_values,
                label,
            )

    if quality_reason == "eyes_closed" and frame_analysis.blink_sequence:
        quality_reason = None

    matching = bool(person_id and similarity >= settings.similarity_threshold)
    # A matched face that fills only a small part of the camera is a photo or
    # phone held up to the lens, not a person standing at the kiosk.
    presented_photo = matching and quality_reason == "tiny_face"
    if presented_photo or (
        matching
        and (
            spoof_score < settings.spoof_threshold
            or (
                len(decoded) >= 2
                and frame_analysis.motion < settings.motion_threshold
                and not frame_analysis.blink_sequence
                and quality_reason != "no_face"
            )
        )
    ):
        decision, reason = "deny", "spoof"
    elif quality_reason:
        decision, reason = "ask_again", "low_quality"
    elif not matching:
        decision, reason = "deny", "identity_mismatch"
    else:
        decision, reason = "allow", "live_and_match"

    if decision == "allow" and person_id:
        access = campus_access(person_id)
        if access == "step_up" and not otp_accepted:
            decision, reason = "ask_again", "outside_schedule"
        elif access == "step_up":
            decision, reason = "allow", "schedule_step_up"
        elif access == "deny":
            decision, reason = "deny", "not_scheduled"

    if otp_accepted and person_id and decision != "ask_again":
        _consume_otp(runtime, person_id)
    return _persist(
        runtime,
        visit_id,
        started_at,
        decision,
        reason,
        score_values,
        label,
    )


def process_check(
    runtime: Runtime,
    payload: Any,
    visit_id: str | None = None,
    started_at: float | None = None,
) -> dict[str, Any]:
    visit_id = visit_id or str(uuid.uuid4())
    started_at = started_at if started_at is not None else time.perf_counter()
    scores: dict[str, float | None] = {
        "spoof": None,
        "similarity": None,
        "sharpness": None,
    }

    try:
        if not isinstance(payload, dict):
            raise InvalidFrameError("Request body must be a JSON object")
        encoded_frames = payload.get("frames")
        otp = payload.get("otp")
        if otp is not None and not isinstance(otp, str):
            raise InvalidFrameError("otp must be a string or null")
        has_otp = isinstance(otp, str) and otp.strip() != ""
        frame_count = len(encoded_frames) if isinstance(encoded_frames, list) else 0
        if frame_count not in (1, 2, 3) or (frame_count == 1 and not has_otp):
            raise InvalidFrameError(
                "frames must contain two or three JPEG images, or one image with a code"
            )
        label = payload.get("label")
        if label is not None and not isinstance(label, str):
            raise InvalidFrameError("label must be a string or null")

        decoded = [
            decode_frame(frame, runtime.settings.max_image_bytes)
            for frame in encoded_frames
        ]
        return _analyze_request(runtime, decoded, otp, visit_id, started_at, label)
    except InvalidFrameError:
        label = payload.get("label") if isinstance(payload, dict) else None
        _persist(
            runtime,
            visit_id,
            started_at,
            "deny",
            "invalid_input",
            scores,
            label if isinstance(label, str) else None,
            error="InvalidFrameError",
        )
        raise
    except Exception as exc:
        error_name = type(exc).__name__
        try:
            label = payload.get("label") if isinstance(payload, dict) else None
            _persist(
                runtime,
                visit_id,
                started_at,
                "deny",
                "analysis_error",
                scores,
                label if isinstance(label, str) else None,
                error=error_name,
            )
        except Exception as persist_exc:
            raise AnalysisError(
                "Analysis and failure-row persistence both failed"
            ) from persist_exc
        raise AnalysisError("Decision analysis failed") from exc
