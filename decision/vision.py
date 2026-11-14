import base64
import binascii
import re
from collections.abc import Sequence
from dataclasses import dataclass
from io import BytesIO

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError

_DATA_URI = re.compile(r"^data:image/jpeg;base64,(.*)$", re.IGNORECASE | re.DOTALL)
_MAX_DIMENSION = 8192
_MAX_PIXELS = 32_000_000


class InvalidFrameError(ValueError):
    pass


@dataclass(frozen=True)
class DecodedFrame:
    image: Image.Image
    jpeg_bytes: bytes
    sharpness: float
    grayscale_small: np.ndarray


@dataclass(frozen=True)
class FrameAnalysis:
    selected_index: int
    motion: float
    blink_sequence: bool


def decode_frame(encoded: str, max_image_bytes: int) -> DecodedFrame:
    if not isinstance(encoded, str):
        raise InvalidFrameError("Each frame must be a base64 JPEG string")

    match = _DATA_URI.fullmatch(encoded.strip())
    payload = match.group(1) if match else encoded.strip()
    max_encoded_size = ((max_image_bytes + 2) // 3) * 4
    if not payload or len(payload) > max_encoded_size:
        raise InvalidFrameError("Frame is empty or exceeds the size limit")
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidFrameError("Frame is not valid base64") from exc

    if not raw or len(raw) > max_image_bytes:
        raise InvalidFrameError("Frame is empty or exceeds the size limit")
    if not raw.startswith(b"\xff\xd8"):
        raise InvalidFrameError("Frame must be a JPEG image")

    try:
        with Image.open(BytesIO(raw)) as source:
            if source.format != "JPEG":
                raise InvalidFrameError("Frame must be a JPEG image")
            width, height = source.size
            if (
                width <= 0
                or height <= 0
                or width > _MAX_DIMENSION
                or height > _MAX_DIMENSION
                or width * height > _MAX_PIXELS
            ):
                raise InvalidFrameError("Frame dimensions exceed the supported limit")
            source.verify()
        with Image.open(BytesIO(raw)) as source:
            image = source.convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise InvalidFrameError("Frame is not a readable JPEG image") from exc

    rgb = np.asarray(image)
    grayscale = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    small = cv2.resize(grayscale, (64, 64), interpolation=cv2.INTER_AREA)
    sharpness = float(cv2.Laplacian(grayscale, cv2.CV_64F).var())
    return DecodedFrame(image, raw, sharpness, small)


def analyze_frames(frames: Sequence[DecodedFrame]) -> FrameAnalysis:
    selected_index = max(
        range(len(frames)),
        key=lambda index: frames[index].sharpness,
    )
    adjacent_motion = []
    for index in range(1, len(frames)):
        current = frames[index].grayscale_small.astype(np.float32)
        previous = frames[index - 1].grayscale_small.astype(np.float32)
        adjacent_motion.append(float(np.abs(current - previous).mean() / 255.0))
    motion = max(adjacent_motion, default=0.0)

    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    eye_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_eye_tree_eyeglasses.xml"
    )
    eye_states = []
    for frame in frames:
        gray = np.asarray(frame.image.convert("L"))
        faces = face_cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=4, minSize=(40, 40)
        )
        if len(faces) == 0:
            eye_states.append(None)
            continue
        x, y, width, height = max(faces, key=lambda box: box[2] * box[3])
        upper_face = gray[y : y + max(1, height // 2), x : x + width]
        eyes = eye_cascade.detectMultiScale(
            upper_face, scaleFactor=1.1, minNeighbors=3, minSize=(8, 8)
        )
        eye_states.append(len(eyes) >= 2)

    blink_sequence = (
        len(eye_states) >= 2
        and eye_states[-1] is True
        and any(state is False for state in eye_states[:-1])
    )
    if blink_sequence:
        selected_index = len(frames) - 1
    return FrameAnalysis(selected_index, motion, blink_sequence)


def crop_face(image: Image.Image, scale: float = 2.7) -> Image.Image:
    """Crop a 2.7x square around the largest face for MiniFASNet-V2."""
    gray = np.asarray(image.convert("L"))
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    faces = cascade.detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=4, minSize=(40, 40)
    )
    if len(faces) == 0:
        return image
    x, y, width, height = max(faces, key=lambda box: box[2] * box[3])
    center_x = x + width / 2
    center_y = y + height / 2
    side = max(width, height) * scale
    image_width, image_height = image.size
    left = max(0, int(round(center_x - side / 2)))
    top = max(0, int(round(center_y - side / 2)))
    right = min(image_width, int(round(center_x + side / 2)))
    bottom = min(image_height, int(round(center_y + side / 2)))
    if right <= left or bottom <= top:
        return image
    return image.crop((left, top, right, bottom))
