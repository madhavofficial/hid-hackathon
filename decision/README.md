# Person 2 decision service

This warm CPU FastAPI service exposes only `POST /check`. Run it from the
repository root on the `decision` branch:

```bash
python -m pip install -r decision/requirements.txt
python -m uvicorn decision.app:app --host 127.0.0.1 --port 8000
python -m pytest decision/tests
```

The service initializes the ONNX session, Rekognition and DynamoDB clients,
and one reusable three-worker thread pool at startup. Each valid request
submits one local inference, one `DetectFaces`, and one
`SearchFacesByImage` call concurrently. Frames are decoded and compared
locally; image data and OTPs are not logged. The default visit table is
`visits` (`VISITS_TABLE`).

## Configuration

| Variable | Default | Description |
|---|---|---|
| `AWS_REGION` | `us-east-1` | AWS region |
| `REKOGNITION_COLLECTION_ID` | `hid-faces` | Person 3's face collection |
| `VISITS_TABLE` | `visits` | DynamoDB visit log |
| `OTP_DYNAMODB_TABLE` | `hid_otp_codes` | Person 3's OTP table |
| `OTP_MAX_ATTEMPTS` | `5` | Failed OTP attempts before the code is removed |
| `ANTISPOOF_MODEL_PATH` | `decision/models/antispoof.onnx` | CPU ONNX model |
| `ANTISPOOF_LIVE_OUTPUT_INDEX` | `1` | Index of the live class in model logits |
| `ANTISPOOF_INPUT_WIDTH` / `ANTISPOOF_INPUT_HEIGHT` | `80` / `80` | Dimensions for dynamic model inputs |
| `SPOOF_THRESHOLD` | `0.8` | Minimum live-class probability |
| `SIMILARITY_THRESHOLD` | `90` | Minimum Rekognition similarity (0–100) |
| `SHARPNESS_THRESHOLD` | `20` | Minimum DetectFaces sharpness |
| `BRIGHTNESS_MIN` / `BRIGHTNESS_MAX` | `25` / `85` | Acceptable DetectFaces brightness |
| `FACE_WIDTH_MIN` | `0.12` | Minimum relative face width |
| `POSE_ANGLE_MAX` | `25` | Maximum absolute yaw, pitch, and roll |
| `MOTION_THRESHOLD` | `0.005` | Minimum normalized adjacent-frame motion |
| `MAX_IMAGE_BYTES` | `5242880` | Maximum decoded size per JPEG |

The ONNX adapter expects one RGB image input in NCHW or NHWC layout and a
multi-class logits output. Input pixels are scaled to `[0, 1]`; the configured
output index is interpreted as the live class. The model file is not included.
Without it, the service starts but returns an analysis error and writes an
error visit row rather than inventing a liveness score. Supply a compatible,
validated model at the configured path before accepting visits.

Thresholds are uncalibrated starting values. They do not guarantee accuracy,
FAR, or FRR targets. Use the AWS SDK credential chain with temporary
credentials or an IAM role attached to the runtime; do not commit credentials.

The service uses the `decision` branch and does not create AWS resources,
modify IAM, or use GPU instances or SageMaker GPU endpoints.
