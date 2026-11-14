"""
Person 3 (Spare / Later path): Amazon Rekognition Face Liveness helpers.
Only used if a mask or hard video gets through CPU checks during testing.
"""
import boto3
from .config import AWS_REGION, LIVENESS_CONFIDENCE_THRESHOLD


def _rek():
    return boto3.client("rekognition", region_name=AWS_REGION)


def create_liveness_session() -> dict:
    """Create a Face Liveness session and return its SessionId."""
    resp = _rek().create_face_liveness_session()
    return {"session_id": resp["SessionId"]}


def get_liveness_result(
    session_id: str,
    threshold: float = LIVENESS_CONFIDENCE_THRESHOLD,
) -> dict:
    """
    Fetch Face Liveness results.
    Returns confidence, is_live, status, and reference_image_bytes
    (for running SearchFacesByImage on the verified live frame).
    """
    resp = _rek().get_face_liveness_session_results(SessionId=session_id)
    confidence = float(resp.get("Confidence", 0.0))
    status = resp.get("Status", "UNKNOWN")
    ref_bytes = resp.get("ReferenceImage", {}).get("Bytes")
    return {
        "session_id": session_id,
        "status": status,
        "confidence": confidence,
        "is_live": status == "SUCCEEDED" and confidence >= threshold,
        "reference_image_bytes": ref_bytes,
    }
