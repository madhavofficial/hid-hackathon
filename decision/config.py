import os
from dataclasses import dataclass
from pathlib import Path

_DECISION_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Settings:
    aws_region: str = "us-east-1"
    collection_id: str = "hid-faces"
    visits_table: str = "visits"
    otp_table: str = "hid_otp_codes"
    otp_max_attempts: int = 5
    model_path: Path = _DECISION_DIR / "models" / "antispoof.onnx"
    spoof_threshold: float = 0.8
    similarity_threshold: float = 90.0
    sharpness_threshold: float = 20.0
    brightness_min: float = 25.0
    brightness_max: float = 85.0
    face_width_min: float = 0.12
    pose_angle_max: float = 25.0
    motion_threshold: float = 0.005
    live_output_index: int = 0
    model_input_width: int = 80
    model_input_height: int = 80
    max_image_bytes: int = 5 * 1024 * 1024

    def __post_init__(self) -> None:
        if not self.aws_region.strip():
            raise ValueError("AWS_REGION must not be empty")
        if not self.collection_id.strip():
            raise ValueError("REKOGNITION_COLLECTION_ID must not be empty")
        if not self.visits_table.strip() or not self.otp_table.strip():
            raise ValueError("DynamoDB table names must not be empty")
        if not 0 <= self.spoof_threshold <= 1:
            raise ValueError("SPOOF_THRESHOLD must be between 0 and 1")
        if not 0 <= self.similarity_threshold <= 100:
            raise ValueError("SIMILARITY_THRESHOLD must be between 0 and 100")
        if not 0 <= self.face_width_min <= 1:
            raise ValueError("FACE_WIDTH_MIN must be between 0 and 1")
        if self.brightness_min > self.brightness_max:
            raise ValueError("BRIGHTNESS_MIN must not exceed BRIGHTNESS_MAX")
        if self.motion_threshold < 0 or self.sharpness_threshold < 0:
            raise ValueError("Motion and sharpness thresholds must not be negative")
        if self.pose_angle_max < 0:
            raise ValueError("POSE_ANGLE_MAX must not be negative")
        if self.live_output_index < 0:
            raise ValueError("ANTISPOOF_LIVE_OUTPUT_INDEX must not be negative")
        if self.model_input_width <= 0 or self.model_input_height <= 0:
            raise ValueError("ONNX input dimensions must be positive")
        if self.max_image_bytes <= 0:
            raise ValueError("MAX_IMAGE_BYTES must be positive")
        if self.otp_max_attempts <= 0:
            raise ValueError("OTP_MAX_ATTEMPTS must be positive")

    @classmethod
    def from_env(cls) -> "Settings":
        defaults = cls()
        return cls(
            aws_region=os.getenv("AWS_REGION", defaults.aws_region),
            collection_id=os.getenv(
                "REKOGNITION_COLLECTION_ID", defaults.collection_id
            ),
            visits_table=os.getenv("VISITS_TABLE", defaults.visits_table),
            otp_table=os.getenv("OTP_DYNAMODB_TABLE", defaults.otp_table),
            otp_max_attempts=int(
                os.getenv("OTP_MAX_ATTEMPTS", str(defaults.otp_max_attempts))
            ),
            model_path=Path(
                os.getenv("ANTISPOOF_MODEL_PATH", str(defaults.model_path))
            ),
            spoof_threshold=float(
                os.getenv("SPOOF_THRESHOLD", str(defaults.spoof_threshold))
            ),
            similarity_threshold=float(
                os.getenv("SIMILARITY_THRESHOLD", str(defaults.similarity_threshold))
            ),
            sharpness_threshold=float(
                os.getenv("SHARPNESS_THRESHOLD", str(defaults.sharpness_threshold))
            ),
            brightness_min=float(
                os.getenv("BRIGHTNESS_MIN", str(defaults.brightness_min))
            ),
            brightness_max=float(
                os.getenv("BRIGHTNESS_MAX", str(defaults.brightness_max))
            ),
            face_width_min=float(
                os.getenv("FACE_WIDTH_MIN", str(defaults.face_width_min))
            ),
            pose_angle_max=float(
                os.getenv("POSE_ANGLE_MAX", str(defaults.pose_angle_max))
            ),
            motion_threshold=float(
                os.getenv("MOTION_THRESHOLD", str(defaults.motion_threshold))
            ),
            live_output_index=int(
                os.getenv(
                    "ANTISPOOF_LIVE_OUTPUT_INDEX", str(defaults.live_output_index)
                )
            ),
            model_input_width=int(
                os.getenv("ANTISPOOF_INPUT_WIDTH", str(defaults.model_input_width))
            ),
            model_input_height=int(
                os.getenv("ANTISPOOF_INPUT_HEIGHT", str(defaults.model_input_height))
            ),
            max_image_bytes=int(
                os.getenv("MAX_IMAGE_BYTES", str(defaults.max_image_bytes))
            ),
        )
