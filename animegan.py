import os
import cv2
import numpy as np
import onnxruntime as ort

ANIME_MODEL_PATH = os.path.join("models", "animeganv2.onnx")

@staticmethod
def _soft_color_boost(bgr: np.ndarray) -> np.ndarray:
    """Make output brighter & cleaner (best for 'bad/dark' look)."""
    # brightness + contrast
    bgr = cv2.convertScaleAbs(bgr, alpha=1.10, beta=8)

    # mild smoothing (keep details)
    bgr = cv2.bilateralFilter(bgr, d=5, sigmaColor=55, sigmaSpace=55)
    return bgr


def _load_session(model_path: str):
    if not os.path.exists(model_path):
        raise RuntimeError(f"AnimeGAN model not found: {model_path}")
    return ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])


def _preprocess_rgb_to_nchw(img_rgb: np.ndarray, target=512):
    """
    AnimeGANv2 ONNX generally expects:
    - RGB
    - NCHW
    - float32 in [-1, 1]
    We keep aspect ratio and pad to square.
    """
    h, w = img_rgb.shape[:2]
    scale = target / max(h, w)
    nh, nw = int(h * scale), int(w * scale)
    nh, nw = max(nh, 8), max(nw, 8)

    resized = cv2.resize(img_rgb, (nw, nh), interpolation=cv2.INTER_AREA)

    canvas = np.full((target, target, 3), 255, dtype=np.uint8)
    top = (target - nh) // 2
    left = (target - nw) // 2
    canvas[top:top + nh, left:left + nw] = resized

    x = canvas.astype(np.float32) / 127.5 - 1.0
    x = np.transpose(x, (2, 0, 1))[None, ...]  # NCHW
    return x, (h, w), (top, left, nh, nw)


def _postprocess_to_bgr(y, orig_hw, pad_info):
    """
    Output can be CHW or HWC; convert safely.
    """
    y = np.squeeze(y)
    if y.ndim == 3 and y.shape[0] in (1, 3) and y.shape[-1] not in (1, 3):
        y = np.transpose(y, (1, 2, 0))  # CHW -> HWC

    y = (y + 1.0) * 127.5
    y = np.clip(y, 0, 255).astype(np.uint8)

    # unpad
    top, left, nh, nw = pad_info
    y = y[top:top + nh, left:left + nw]

    oh, ow = orig_hw
    y = cv2.resize(y, (ow, oh), interpolation=cv2.INTER_CUBIC)

    # RGB -> BGR
    bgr = cv2.cvtColor(y, cv2.COLOR_RGB2BGR)
    bgr = _soft_color_boost(bgr)
    return bgr


class AnimeGAN:
    def __init__(self, model_path=ANIME_MODEL_PATH):
        self.sess = _load_session(model_path)
        self.input_name = self.sess.get_inputs()[0].name
        self.output_name = self.sess.get_outputs()[0].name

    def run(self, img_rgb: np.ndarray) -> np.ndarray:
        x, orig_hw, pad_info = _preprocess_rgb_to_nchw(img_rgb, target=512)
        y = self.sess.run([self.output_name], {self.input_name: x})[0]
        out_bgr = _postprocess_to_bgr(y, orig_hw, pad_info)
        return out_bgr