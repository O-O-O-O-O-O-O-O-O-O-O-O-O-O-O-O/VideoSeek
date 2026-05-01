import os

import numpy as np
import onnxruntime as ort
from PIL import Image

from src.app.config import load_config
from src.storage.config_store import get_effective_prefer_gpu
from src.utils import free_memory


class SigLIP2OnnxEngine:
    """
    Draft provider for local SigLIP2 ONNX models.
    This file is intentionally not wired into the main runtime yet.
    """

    def __init__(self, model_dir, prefer_gpu=None, image_size=224):
        self.model_dir = os.path.normpath(os.path.abspath(os.fspath(model_dir)))
        self.image_size = int(image_size)
        self.tokenizer = self._build_tokenizer(self.model_dir)
        runtime_config = load_config()
        configured_prefer_gpu = (
            get_effective_prefer_gpu(config=runtime_config) if prefer_gpu is None else bool(prefer_gpu)
        )
        effective_prefer_gpu = configured_prefer_gpu

        self._vision_path = os.path.join(self.model_dir, "vision_model.onnx")
        self._text_path = os.path.join(self.model_dir, "text_model.onnx")
        for file_path in [self._vision_path, self._text_path]:
            if not os.path.isfile(file_path):
                raise RuntimeError(f"Missing SigLIP model file: {file_path}")

        vision_providers = ["CPUExecutionProvider"]
        if effective_prefer_gpu:
            vision_providers = ["DmlExecutionProvider", "CPUExecutionProvider"]

        # Keep text on CPU by default for compatibility; make this configurable later if needed.
        text_providers = ["CPUExecutionProvider"]

        self.vision_session = ort.InferenceSession(self._vision_path, providers=vision_providers)
        self.text_session = ort.InferenceSession(self._text_path, providers=text_providers)
        self.active_providers = {
            "vision": list(self.vision_session.get_providers()),
            "text": list(self.text_session.get_providers()),
        }
        self.using_gpu = "DmlExecutionProvider" in self.active_providers["vision"]
        self.backend_label = (
            "GPU"
            if self.using_gpu
            else "CPU"
        )
        self.prefer_gpu = configured_prefer_gpu
        self.embedding_batch_size = _resolve_embedding_batch_size(runtime_config)
        self.runtime_warning = ""
        self.runtime_issue = ""
        self.runtime_diagnostics = {}
        self._feature_dim = None
        self._tokenizer_backend = "unknown"

    def _preprocess_image(self, image_source):
        if isinstance(image_source, str):
            image = Image.open(image_source).convert("RGB")
        else:
            array = np.asarray(image_source)
            if array.ndim != 3 or array.shape[2] != 3:
                raise RuntimeError("Unsupported image frame format for SigLIP preprocessing.")
            # Main pipeline frames are BGR ndarray.
            image = Image.fromarray(array[:, :, ::-1]).convert("RGB")
        image = image.resize(
            (self.image_size, self.image_size),
            Image.Resampling.BICUBIC,
        )
        array = np.asarray(image, dtype=np.float32)
        array = (array / 255.0 - 0.5) / 0.5
        array = array.transpose(2, 0, 1)
        return array[np.newaxis, :]

    @staticmethod
    def _build_tokenizer(model_dir):
        tokenizer_json_path = os.path.join(model_dir, "tokenizer.json")
        if not os.path.isfile(tokenizer_json_path):
            raise RuntimeError(f"Missing SigLIP tokenizer file: {tokenizer_json_path}")
        try:
            from tokenizers import Tokenizer
        except Exception as exc:
            raise RuntimeError("SigLIP requires the `tokenizers` package for tokenizer.json loading.") from exc

        tokenizer = Tokenizer.from_file(tokenizer_json_path)
        tokenizer.enable_truncation(max_length=64)
        tokenizer.enable_padding(length=64, pad_id=0, pad_token="[PAD]")
        return {
            "backend": "tokenizers",
            "instance": tokenizer,
        }

    def _normalize(self, vectors):
        norms = np.linalg.norm(vectors, axis=-1, keepdims=True) + 1e-10
        return vectors / norms

    def _select_feature_tensor(self, outputs):
        # Prefer a pooled 2D output (batch, dim), fallback to sequence mean-pooling.
        for tensor in outputs:
            if getattr(tensor, "ndim", 0) == 2:
                return tensor.astype(np.float32)
        first = outputs[0].astype(np.float32)
        if first.ndim == 3:
            return np.mean(first, axis=1)
        if first.ndim == 2:
            return first
        raise RuntimeError(f"Unsupported SigLIP output shape: {tuple(first.shape)}")

    def encode_images(self, image_paths):
        vectors = []
        input_name = self.vision_session.get_inputs()[0].name
        for image_path in image_paths:
            image_blob = self._preprocess_image(image_path)
            outputs = self.vision_session.run(None, {input_name: image_blob})
            features = self._select_feature_tensor(outputs)
            vectors.append(features)
        if not vectors:
            dim = int(self._feature_dim or 0)
            return np.empty((0, dim), dtype=np.float32)
        merged = np.vstack(vectors).astype(np.float32)
        merged = self._normalize(merged)
        self._feature_dim = int(merged.shape[1])
        free_memory()
        return merged

    def encode_text(self, text):
        encoded = self._encode_text_inputs(str(text or ""))
        feed = {}
        text_inputs = self.text_session.get_inputs()
        for node in text_inputs:
            if node.name in encoded:
                feed[node.name] = encoded[node.name].astype(np.int64)
        if not feed and text_inputs:
            # Some exports use generic names (e.g. "input"), map the first tensor.
            first_name = text_inputs[0].name
            if "input_ids" in encoded:
                feed[first_name] = encoded["input_ids"].astype(np.int64)
        if not feed:
            raise RuntimeError("SigLIP text encoder inputs could not be prepared for ONNX session.")
        outputs = self.text_session.run(None, feed)
        features = self._select_feature_tensor(outputs).astype(np.float32)
        features = self._normalize(features)
        self._feature_dim = int(features.shape[1])
        return features

    def _encode_text_inputs(self, text):
        tokenizer_wrapper = self.tokenizer
        backend = str(tokenizer_wrapper.get("backend", "") or "")
        tokenizer_instance = tokenizer_wrapper.get("instance")

        if backend != "tokenizers" or tokenizer_instance is None:
            raise RuntimeError("SigLIP tokenizer backend is invalid; expected tokenizers runtime.")
        self._tokenizer_backend = "tokenizers"
        encoded = tokenizer_instance.encode(text)
        input_ids = np.asarray([encoded.ids], dtype=np.int64)
        attention_mask = np.asarray([encoded.attention_mask], dtype=np.int64)
        return {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
        }


def build_siglip_profile_manifest(variant="base-patch16-224"):
    """
    Return a draft model_manifest payload for SigLIP package parsing.
    """
    variant_text = str(variant or "").strip() or "base-patch16-224"
    return {
        "id": f"siglip2_{variant_text.replace('-', '_')}",
        "provider": "siglip2_onnx",
        "variant": variant_text,
        "display_name": f"SigLIP2 {variant_text}",
        "prefer_gpu": True,
        "required_files": [
            "vision_model.onnx",
            "text_model.onnx",
            "tokenizer.json",
            "tokenizer_config.json",
        ],
        "files": {
            "vision_model": "vision_model.onnx",
            "text_model": "text_model.onnx",
            "tokenizer_json": "tokenizer.json",
            "tokenizer_config": "tokenizer_config.json",
        },
    }


def _resolve_embedding_batch_size(config):
    runtime_config = dict(config or {})
    try:
        batch_size = int(runtime_config.get("embedding_batch_size", 16))
    except (TypeError, ValueError):
        return 16
    return max(1, batch_size)
