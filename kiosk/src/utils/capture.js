export function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

/**
 * Captures one frame, center-crops it to a portrait 3:4 ratio,
 * resizes it to 480x640, and returns raw JPEG Base64.
 */
export function captureJpegBase64(video) {
  return new Promise((resolve, reject) => {
    if (!video || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) {
      reject(new Error("The camera is not ready yet."));
      return;
    }

    const sourceWidth = video.videoWidth;
    const sourceHeight = video.videoHeight;

    if (!sourceWidth || !sourceHeight) {
      reject(new Error("The camera has not produced a video frame yet."));
      return;
    }

    const canvas = document.createElement("canvas");
    canvas.width = 480;
    canvas.height = 640;

    const targetRatio = 480 / 640;
    const sourceRatio = sourceWidth / sourceHeight;

    let cropWidth;
    let cropHeight;
    let cropX;
    let cropY;

    if (sourceRatio > targetRatio) {
      cropHeight = sourceHeight;
      cropWidth = cropHeight * targetRatio;
      cropX = (sourceWidth - cropWidth) / 2;
      cropY = 0;
    } else {
      cropWidth = sourceWidth;
      cropHeight = cropWidth / targetRatio;
      cropX = 0;
      cropY = (sourceHeight - cropHeight) / 2;
    }

    const context = canvas.getContext("2d");
    if (!context) {
      reject(new Error("Could not create image canvas."));
      return;
    }

    // Keep the captured image in normal orientation (not mirrored).
    context.drawImage(
      video,
      cropX,
      cropY,
      cropWidth,
      cropHeight,
      0,
      0,
      480,
      640
    );

    canvas.toBlob(
      (blob) => {
        if (!blob) {
          reject(new Error("JPEG conversion failed."));
          return;
        }

        const reader = new FileReader();
        reader.onload = () => {
          const dataUrl = String(reader.result);
          const commaIndex = dataUrl.indexOf(",");
          resolve(dataUrl.slice(commaIndex + 1));
        };
        reader.onerror = () => reject(new Error("Could not read captured JPEG."));
        reader.readAsDataURL(blob);
      },
      "image/jpeg",
      0.78
    );
  });
}

/**
 * Captures 2 or 3 frames, with approximately 150ms between captures.
 * The wait is measured between the start of captures, including JPEG conversion.
 */
export async function captureFrameSequence(video, count = 3) {
  if (![2, 3].includes(count)) {
    throw new Error("Frame count must be 2 or 3.");
  }

  const frames = [];

  for (let index = 0; index < count; index += 1) {
    const captureStartedAt = performance.now();
    frames.push(await captureJpegBase64(video));

    if (index < count - 1) {
      const elapsed = performance.now() - captureStartedAt;
      await sleep(Math.max(0, 150 - elapsed));
    }
  }

  return frames;
}