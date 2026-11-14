from pathlib import Path

import numpy as np
from PIL import Image


class ModelUnavailableError(RuntimeError):
    pass


class OnnxAntiSpoofModel:
    """CPU ONNX adapter returning the configured live-class probability."""

    def __init__(
        self,
        model_path: Path,
        live_output_index: int = 1,
        input_width: int = 80,
        input_height: int = 80,
    ) -> None:
        self.model_path = Path(model_path)
        self.live_output_index = live_output_index
        self.input_width = input_width
        self.input_height = input_height
        self.session = None

        if self.model_path.is_file():
            import onnxruntime

            self.session = onnxruntime.InferenceSession(
                str(self.model_path),
                providers=["CPUExecutionProvider"],
            )
            self.infer(Image.new("RGB", (input_width, input_height)))

    def infer(self, image: Image.Image) -> float:
        if self.session is None:
            raise ModelUnavailableError(
                f"Anti-spoof model not found at {self.model_path}"
            )

        input_meta = self.session.get_inputs()[0]
        shape = input_meta.shape
        if len(shape) != 4:
            raise ModelUnavailableError(
                "ONNX input must be a four-dimensional image tensor"
            )

        if shape[1] == 3:
            height = shape[2] if isinstance(shape[2], int) else self.input_height
            width = shape[3] if isinstance(shape[3], int) else self.input_width
            resized = image.resize((width, height), Image.Resampling.BILINEAR)
            tensor = np.asarray(resized, dtype=np.float32) / 255.0
            tensor = np.transpose(tensor, (2, 0, 1))[None, ...]
        elif shape[3] == 3:
            height = shape[1] if isinstance(shape[1], int) else self.input_height
            width = shape[2] if isinstance(shape[2], int) else self.input_width
            resized = image.resize((width, height), Image.Resampling.BILINEAR)
            tensor = (np.asarray(resized, dtype=np.float32) / 255.0)[None, ...]
        else:
            raise ModelUnavailableError("ONNX input must use RGB NCHW or NHWC layout")

        output = self.session.run(None, {input_meta.name: tensor})[0]
        logits = np.asarray(output, dtype=np.float64).reshape(-1)
        if logits.size < 2 or not 0 <= self.live_output_index < logits.size:
            raise ModelUnavailableError(
                "ONNX output must contain at least two classes and the configured live index"
            )
        if not np.isfinite(logits).all():
            raise ModelUnavailableError("ONNX output contains a non-finite value")

        shifted = logits - np.max(logits)
        probabilities = np.exp(shifted) / np.exp(shifted).sum()
        return float(probabilities[self.live_output_index])
