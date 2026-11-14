import os
from pathlib import Path

from dotenv import load_dotenv

_PACKAGE_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _PACKAGE_DIR.parent
load_dotenv(_REPO_ROOT / ".env")
load_dotenv(_PACKAGE_DIR / ".env")

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
COLLECTION_ID = os.getenv("REKOGNITION_COLLECTION_ID", "hid-faces")
S3_BUCKET = os.getenv("ENROLLED_S3_BUCKET", "hid-hackathon-enrolled-533267095467")
S3_PREFIX = os.getenv("ENROLLED_S3_PREFIX", "enrolled/")
OTP_TABLE = os.getenv("OTP_DYNAMODB_TABLE", "hid_otp_codes")
OTP_TTL_SECONDS = int(os.getenv("OTP_TTL_SECONDS", "300"))
OTP_MAX_ATTEMPTS = int(os.getenv("OTP_MAX_ATTEMPTS", "5"))
PEOPLE_TABLE = os.getenv("ENROLLED_TABLE", "hid_people")
LIVENESS_CONFIDENCE_THRESHOLD = float(os.getenv("LIVENESS_CONFIDENCE_THRESHOLD", "85.0"))
