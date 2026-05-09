import ctypes
import json
import os
import platform
import site
import subprocess
import sys

import cv2
import numpy as np
import onnxruntime as ort

from src.app.config import load_config
from src.app.logging_utils import get_logger
from src.core.inference_registry import build_inference_engine, register_inference_engine
from src.core.extract_frames import stream_frames_with_ffmpeg
from src.core.faiss_index import create_clip_index
from src.core.semantic_chunking import build_semantic_chunks, chunk_config_payload
from src.storage.asset_store import save_vector_payload
from src.storage.config_store import (
    get_active_embedding_spec,
    get_active_model_profile,
    get_active_model_resource_dir,
    get_effective_prefer_gpu,
)
from src.core.tokenizer import tokenize
from src.utils import ensure_folder_exists, ensure_model_files, free_memory, measure_time

logger = get_logger("clip_embedding")
_GPU_PROBE_CACHE = None
_HARD_GPU_RUNTIME_ISSUES = {"windows", "windows_version", "directml", "directx", "msvc"}


class CLIPOnnxEngine:
    def __init__(self):
        runtime_config = load_config()
        config_prefer_gpu = get_effective_prefer_gpu(config=runtime_config)
        runtime_plan = prepare_inference_runtime(prefer_gpu=config_prefer_gpu, provider="clip_onnx")
        prefer_gpu = runtime_plan["effective_prefer_gpu"]
        providers = ["CPUExecutionProvider"]
        if prefer_gpu:
            providers = ["DmlExecutionProvider", "CPUExecutionProvider"]

        model_paths = ensure_model_files(["clip_visual.onnx", "clip_text.onnx"])
        self.model_paths = dict(model_paths)
        self.visual_session = ort.InferenceSession(
            model_paths["clip_visual.onnx"],
            sess_options=_build_session_options(prefer_gpu),
            providers=providers,
        )
        self.text_session = ort.InferenceSession(
            model_paths["clip_text.onnx"],
            sess_options=_build_session_options(prefer_gpu),
            providers=providers,
        )
        self.active_providers = {
            "visual": self.visual_session.get_providers(),
            "text": self.text_session.get_providers(),
        }
        self.using_gpu = all(
            "DmlExecutionProvider" in provider_list for provider_list in self.active_providers.values()
        )
        self.prefer_gpu = config_prefer_gpu
        self.embedding_batch_size = _resolve_embedding_batch_size(runtime_config)
        self.runtime_warning = runtime_plan["warning"]
        self.runtime_issue = runtime_plan["issue"]
        self.runtime_diagnostics = dict(runtime_plan.get("diagnostics") or {})
        if prefer_gpu and not self.using_gpu and not self.runtime_warning:
            self.runtime_diagnostics = _build_gpu_runtime_diagnostics()
            self.runtime_issue = self.runtime_diagnostics.get("issue", "unknown")
            self.runtime_warning = (
                "GPU execution is unavailable. ONNX Runtime fell back to CPU. "
                "Verify that onnxruntime-directml is installed and that DirectML / DirectX 12 is available."
            )
        self.backend_label = "GPU" if self.using_gpu else "CPU"
        logger.info(
            "Initialized inference engine: configured_prefer_gpu=%s effective_prefer_gpu=%s backend=%s visual_providers=%s text_providers=%s issue=%s",
            config_prefer_gpu,
            prefer_gpu,
            self.backend_label,
            self.active_providers["visual"],
            self.active_providers["text"],
            self.runtime_issue or "",
        )
        self.mean = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32).reshape(1, 1, 3)
        self.std = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32).reshape(1, 1, 3)
        self._feature_dim = None
        self._cpu_visual_session = None
        self._visual_force_cpu = False

    def _preprocess(self, img_bgr):
        img = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        img = cv2.resize(img, (224, 224), interpolation=cv2.INTER_CUBIC)
        img = img.astype(np.float32) / 255.0
        img = (img - self.mean) / self.std
        img = img.transpose(2, 0, 1)
        return img[np.newaxis, :].astype(np.float32)

    def imread_chinese(self, path):
        with open(path, "rb") as handle:
            data = handle.read()
        return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)

    def encode_images(self, frames):
        # Retained intentionally: this public image-encoding entrypoint is
        # reached via helper wrappers and may be missed by static analysis.
        if self._feature_dim is None:
            dummy = np.zeros((1, 3, 224, 224), dtype=np.float32)
            dummy_feat = self.visual_session.run(None, {"input": dummy})[0]
            self._feature_dim = dummy_feat.shape[1] if dummy_feat.ndim > 1 else dummy_feat.shape[0]

        embeddings = []
        preprocessed_batch = []
        batch_size = self.embedding_batch_size
        for frame in frames:
            image = self.imread_chinese(frame) if isinstance(frame, str) else frame
            if image is None:
                continue
            preprocessed_batch.append(self._preprocess(image)[0])
            if len(preprocessed_batch) < batch_size:
                continue
            embeddings.append(self._run_visual_batch(preprocessed_batch))
            preprocessed_batch = []

        if preprocessed_batch:
            embeddings.append(self._run_visual_batch(preprocessed_batch))

        if not embeddings:
            return np.empty((0, self._feature_dim), dtype=np.float32)
        free_memory()
        return np.vstack(embeddings)

    def _run_visual_batch(self, preprocessed_batch):
        if not preprocessed_batch:
            feature_dim = self._feature_dim or 0
            return np.empty((0, feature_dim), dtype=np.float32)

        input_blob = np.stack(preprocessed_batch, axis=0).astype(np.float32)
        feat = self._run_visual_batch_with_recovery(input_blob).astype(np.float32)
        feat /= (np.linalg.norm(feat, axis=-1, keepdims=True) + 1e-10)
        return feat

    def _run_visual_batch_with_recovery(self, input_blob):
        try:
            return self._run_visual_batch_once(input_blob)
        except Exception as exc:
            batch_size = int(input_blob.shape[0]) if getattr(input_blob, "ndim", 0) > 0 else 0
            logger.warning(
                "Visual batch inference failed: backend=%s forced_cpu=%s batch_size=%s detail=%s",
                self.backend_label,
                self._visual_force_cpu,
                batch_size,
                _truncate_log_text(exc),
            )
            if batch_size > 1:
                midpoint = max(1, batch_size // 2)
                left = self._run_visual_batch_with_recovery(input_blob[:midpoint])
                right = self._run_visual_batch_with_recovery(input_blob[midpoint:])
                if left.size == 0:
                    return right
                if right.size == 0:
                    return left
                return np.vstack([left, right])
            return self._handle_single_frame_visual_failure(input_blob, exc)

    def _run_visual_batch_once(self, input_blob):
        session = self._get_visual_session_for_run()
        return session.run(None, {"input": input_blob})[0]

    def _get_visual_session_for_run(self):
        if self._visual_force_cpu:
            return self._get_cpu_visual_session()
        return self.visual_session

    def _get_cpu_visual_session(self):
        if self._cpu_visual_session is None:
            self._cpu_visual_session = self._create_cpu_visual_session()
        return self._cpu_visual_session

    def _create_cpu_visual_session(self):
        logger.warning("Creating CPU fallback visual session after GPU visual inference failure")
        return ort.InferenceSession(
            self.model_paths["clip_visual.onnx"],
            sess_options=_build_session_options(False),
            providers=["CPUExecutionProvider"],
        )

    def _handle_single_frame_visual_failure(self, input_blob, original_exc):
        if not self.using_gpu and not self._visual_force_cpu:
            raise RuntimeError(
                f"Visual inference failed on CPU for batch size 1: {_format_exception_detail(original_exc)}"
            ) from original_exc

        try:
            cpu_feat = self._get_cpu_visual_session().run(None, {"input": input_blob})[0]
        except Exception as cpu_exc:
            raise RuntimeError(
                "Visual inference failed after batch reduction and CPU fallback. "
                f"GPU error: {_format_exception_detail(original_exc)}. "
                f"CPU fallback error: {_format_exception_detail(cpu_exc)}"
            ) from cpu_exc

        self._visual_force_cpu = True
        self.using_gpu = False
        self.backend_label = "CPU"
        self.active_providers["visual"] = ["CPUExecutionProvider"]
        fallback_warning = (
            "GPU visual inference became unstable during indexing and fell back to CPU for the remaining frames."
        )
        if fallback_warning not in self.runtime_warning:
            self.runtime_warning = f"{self.runtime_warning} {fallback_warning}".strip()
        logger.warning(
            "GPU visual inference fell back to CPU for remaining frames after batch reduction failure: %s",
            _truncate_log_text(original_exc),
        )
        return cpu_feat

    def encode_text(self, text):
        # Retained intentionally: this public text-encoding entrypoint is
        # reached via helper wrappers and may be missed by static analysis.
        tokens = tokenize([text]).astype(np.int32)
        feat = self.text_session.run(None, {"input": tokens})[0].astype(np.float32)
        feat /= (np.linalg.norm(feat, axis=-1, keepdims=True) + 1e-10)
        return feat


engine = None


def get_engine():
    global engine
    if engine is None:
        logger.info("Inference engine is not initialized; creating a new runtime instance")
        config = load_config()
        profile = get_active_model_profile(config=config)
        provider = str(profile.get("provider", "") or "").strip() or "clip_onnx"
        engine = build_inference_engine(provider)
    return engine


def get_clip_embeddings_batch(frames):
    return get_engine().encode_images(frames)


def get_text_embedding(text):
    return get_engine().encode_text(text)


def get_engine_runtime_warning():
    warning = get_engine().runtime_warning
    return warning.strip()


def get_engine_runtime_status():
    if engine is None:
        config = load_config()
        prefer_gpu = get_effective_prefer_gpu(config=config)
        provider = str(get_active_model_profile(config=config).get("provider", "") or "").strip()
        if not prefer_gpu:
            return {
                "initialized": True,
                "prefer_gpu": prefer_gpu,
                "backend": "CPU",
                "warning": "",
                "issue": "",
                "diagnostics": {},
            }
        if provider != "clip_onnx":
            return {
                "initialized": False,
                "prefer_gpu": prefer_gpu,
                "backend": "",
                "warning": "",
                "issue": "",
                "diagnostics": {},
            }
        probe = dict(_GPU_PROBE_CACHE) if isinstance(_GPU_PROBE_CACHE, dict) else None
        if prefer_gpu and probe:
            if probe.get("ok") or not _should_disable_gpu_for_probe_issue(probe, config=config):
                return {
                    "initialized": True,
                    "prefer_gpu": prefer_gpu,
                    "backend": "GPU",
                    "warning": "" if probe.get("ok") else _build_gpu_probe_soft_warning(probe.get("detail")),
                    "issue": "" if probe.get("ok") else probe.get("issue", ""),
                    "diagnostics": dict(probe.get("diagnostics") or {}),
                }
            return {
                "initialized": True,
                "prefer_gpu": prefer_gpu,
                "backend": "CPU",
                "warning": _build_gpu_runtime_warning(probe.get("detail")),
                "issue": probe.get("issue", ""),
                "diagnostics": dict(probe.get("diagnostics") or {}),
            }
        return {
            "initialized": False,
            "prefer_gpu": prefer_gpu,
            "backend": "",
            "warning": "",
            "issue": "",
            "diagnostics": {},
        }

    return {
        "initialized": True,
        "prefer_gpu": engine.prefer_gpu,
        "backend": engine.backend_label,
        "warning": engine.runtime_warning.strip(),
        "issue": engine.runtime_issue,
        "diagnostics": dict(getattr(engine, "runtime_diagnostics", {}) or {}),
    }


def reset_engine():
    global engine, _GPU_PROBE_CACHE
    logger.info("Resetting inference engine and cached GPU probe result")
    engine = None
    _GPU_PROBE_CACHE = None


def prepare_inference_runtime(prefer_gpu=None, provider=None):
    runtime_config = load_config()
    configured_prefer_gpu = get_effective_prefer_gpu(config=runtime_config) if prefer_gpu is None else bool(prefer_gpu)
    resolved_provider = str(provider or "").strip()
    if not resolved_provider:
        try:
            resolved_provider = str(get_active_model_profile(config=runtime_config).get("provider", "") or "").strip()
        except Exception:
            resolved_provider = "clip_onnx"
    logger.info("Preparing inference runtime: configured_prefer_gpu=%s", configured_prefer_gpu)
    if not configured_prefer_gpu:
        logger.info("Inference runtime preparation selected CPU because GPU preference is disabled")
        return {
            "configured_prefer_gpu": configured_prefer_gpu,
            "effective_prefer_gpu": False,
            "warning": "",
            "issue": "",
            "diagnostics": {},
        }
    if resolved_provider != "clip_onnx":
        return {
            "configured_prefer_gpu": configured_prefer_gpu,
            "effective_prefer_gpu": True,
            "warning": "",
            "issue": "",
            "diagnostics": {},
        }

    if _is_gpu_probe_child():
        return {
            "configured_prefer_gpu": configured_prefer_gpu,
            "effective_prefer_gpu": True,
            "warning": "",
            "issue": "",
            "diagnostics": {},
        }

    probe = _run_gpu_runtime_probe_once()
    if probe["ok"]:
        logger.info("GPU runtime probe succeeded; DirectML remains enabled for this run")
        return {
            "configured_prefer_gpu": configured_prefer_gpu,
            "effective_prefer_gpu": True,
            "warning": "",
            "issue": "",
            "diagnostics": dict(probe.get("diagnostics") or {}),
        }

    if not _should_disable_gpu_for_probe_issue(probe, config=runtime_config):
        warning = _build_gpu_probe_soft_warning(probe["detail"])
        logger.warning(
            "GPU runtime probe was inconclusive; keeping DirectML enabled for this run. issue=%s detail=%s",
            probe["issue"],
            probe["detail"],
        )
        return {
            "configured_prefer_gpu": configured_prefer_gpu,
            "effective_prefer_gpu": True,
            "warning": warning,
            "issue": probe["issue"],
            "diagnostics": dict(probe.get("diagnostics") or {}),
        }

    warning = _build_gpu_runtime_warning(probe["detail"])
    logger.warning(
        "GPU runtime probe failed; falling back to CPU. issue=%s detail=%s",
        probe["issue"],
        probe["detail"],
    )
    return {
        "configured_prefer_gpu": configured_prefer_gpu,
        "effective_prefer_gpu": False,
        "warning": warning,
        "issue": probe["issue"],
        "diagnostics": dict(probe.get("diagnostics") or {}),
    }


def gpu_probe_cli_main():
    payload = _run_isolated_gpu_probe()
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload.get("ok") else 1


def _run_gpu_runtime_probe_once():
    global _GPU_PROBE_CACHE
    if _GPU_PROBE_CACHE is None:
        logger.info("GPU runtime probe cache miss; launching isolated probe")
        _GPU_PROBE_CACHE = _probe_gpu_runtime_subprocess()
    else:
        logger.info("GPU runtime probe cache hit: ok=%s issue=%s", _GPU_PROBE_CACHE.get("ok"), _GPU_PROBE_CACHE.get("issue", ""))
    return dict(_GPU_PROBE_CACHE)


def _probe_gpu_runtime_subprocess():
    command = _build_gpu_probe_command()
    if not command:
        return {
            "ok": False,
            "issue": "unknown",
            "detail": "Python executable is unavailable for GPU runtime probing.",
            "diagnostics": {"probe_stage": "bootstrap", "failure_kind": "probe_command_unavailable"},
        }

    env = os.environ.copy()
    env["VIDEOSEEK_GPU_PROBE_CHILD"] = "1"
    windows_no_window_kwargs = {}
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        windows_no_window_kwargs["startupinfo"] = startupinfo
        windows_no_window_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    logger.info("Starting GPU runtime probe subprocess: command=%s", command)
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=25,
            env=env,
            **windows_no_window_kwargs,
        )
    except subprocess.TimeoutExpired:
        logger.warning("GPU runtime probe subprocess timed out after 25s")
        return {
            "ok": False,
            "issue": "probe_timeout",
            "detail": "GPU runtime probe timed out.",
            "diagnostics": {"probe_stage": "subprocess", "failure_kind": "probe_timeout", "timeout_seconds": 25},
        }
    except Exception as exc:
        logger.exception("GPU runtime probe subprocess failed to start")
        return {
            "ok": False,
            "issue": "probe_launch_failed",
            "detail": str(exc),
            "diagnostics": {
                "probe_stage": "subprocess",
                "failure_kind": "probe_launch_failed",
                "probe_exception_type": exc.__class__.__name__,
                "probe_exception_message": str(exc),
            },
        }

    payload = _parse_gpu_probe_payload(result.stdout)
    logger.info(
        "GPU runtime probe subprocess finished: returncode=%s parsed_ok=%s parsed_issue=%s stdout_tail=%s stderr_tail=%s",
        result.returncode,
        payload.get("ok"),
        payload.get("issue", ""),
        _truncate_log_text(result.stdout),
        _truncate_log_text(result.stderr),
    )
    if result.returncode == 0 and payload.get("ok"):
        return {
            "ok": True,
            "issue": "",
            "detail": "",
            "diagnostics": dict(payload.get("diagnostics") or {}),
        }

    issue = payload.get("issue") or "unknown"
    detail = payload.get("detail") or f"GPU runtime probe exited with code {result.returncode}."
    return {
        "ok": False,
        "issue": issue,
        "detail": detail,
        "diagnostics": dict(payload.get("diagnostics") or {}),
    }


def _build_gpu_probe_command():
    executable = _resolve_probe_executable_path()
    if not executable:
        return []

    executable_lower = executable.lower()
    executable_name = os.path.basename(executable_lower)
    is_python_launcher = executable_name.startswith("python")
    if (executable_lower.endswith(".exe") and not is_python_launcher) or getattr(sys, "frozen", False):
        return [executable, "--gpu-probe"]

    main_script = _resolve_main_script_path()
    if not main_script:
        return []
    return [executable, main_script, "--gpu-probe"]


def _resolve_main_script_path():
    candidate = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "main.py"))
    return candidate if os.path.exists(candidate) else ""


def _resolve_probe_executable_path():
    candidates = [
        str(getattr(sys, "executable", "") or "").strip(),
        str((sys.argv or [""])[0] or "").strip(),
        _get_windows_module_filename(),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        normalized = os.path.abspath(candidate)
        if os.path.exists(normalized):
            return normalized
    return ""


def _get_windows_module_filename():
    if os.name != "nt":
        return ""
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        length = ctypes.windll.kernel32.GetModuleFileNameW(None, buffer, len(buffer))
        if length <= 0:
            return ""
        return buffer.value[:length]
    except Exception:
        return ""


def _parse_gpu_probe_payload(stdout_text):
    text = str(stdout_text or "").strip()
    if not text:
        return {}
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in reversed(lines):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def _run_isolated_gpu_probe():
    try:
        logger.info("GPU probe child starting DirectML validation")
        model_paths = ensure_model_files(["clip_visual.onnx", "clip_text.onnx"])
        providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
        visual_session = ort.InferenceSession(
            model_paths["clip_visual.onnx"],
            sess_options=_build_session_options(True),
            providers=providers,
        )
        text_session = ort.InferenceSession(
            model_paths["clip_text.onnx"],
            sess_options=_build_session_options(True),
            providers=providers,
        )
        active_providers = {
            "visual": visual_session.get_providers(),
            "text": text_session.get_providers(),
        }
        diagnostics = _build_gpu_runtime_diagnostics()
        diagnostics["probe_stage"] = "provider_activation"
        diagnostics["active_providers"] = dict(active_providers)
        logger.info("GPU probe child initialized sessions with providers: visual=%s text=%s", active_providers["visual"], active_providers["text"])
        using_gpu = all("DmlExecutionProvider" in provider_list for provider_list in active_providers.values())
        if not using_gpu:
            if "DmlExecutionProvider" not in active_providers["visual"]:
                issue = "visual_provider_not_activated"
            elif "DmlExecutionProvider" not in active_providers["text"]:
                issue = "text_provider_not_activated"
            else:
                issue = diagnostics.get("issue") or "provider_not_activated"
            diagnostics["failure_kind"] = issue
            logger.warning("GPU probe child did not activate DirectML provider: issue=%s", issue or "unknown")
            return {
                "ok": False,
                "issue": issue or "unknown",
                "detail": "DirectML provider was not activated during GPU runtime probe.",
                "diagnostics": diagnostics,
            }

        dummy_image = np.zeros((1, 3, 224, 224), dtype=np.float32)
        try:
            visual_session.run(None, {"input": dummy_image})
        except Exception as exc:
            diagnostics["probe_stage"] = "visual_inference"
            diagnostics["failure_kind"] = "visual_probe_failed"
            diagnostics["probe_exception_type"] = exc.__class__.__name__
            diagnostics["probe_exception_message"] = str(exc)
            logger.exception("GPU probe child failed during visual DirectML validation")
            return {
                "ok": False,
                "issue": "visual_probe_failed",
                "detail": str(exc),
                "diagnostics": diagnostics,
            }
        dummy_tokens = tokenize(["gpu probe"]).astype(np.int32)
        try:
            text_session.run(None, {"input": dummy_tokens})
        except Exception as exc:
            diagnostics["probe_stage"] = "text_inference"
            diagnostics["failure_kind"] = "text_probe_failed"
            diagnostics["probe_exception_type"] = exc.__class__.__name__
            diagnostics["probe_exception_message"] = str(exc)
            logger.exception("GPU probe child failed during text DirectML validation")
            return {
                "ok": False,
                "issue": "text_probe_failed",
                "detail": str(exc),
                "diagnostics": diagnostics,
            }
        logger.info("GPU probe child completed DirectML validation successfully")
        diagnostics.pop("probe_stage", None)
        diagnostics.pop("failure_kind", None)
        diagnostics.pop("probe_exception_type", None)
        diagnostics.pop("probe_exception_message", None)
        return {
            "ok": True,
            "issue": "",
            "detail": "",
            "diagnostics": diagnostics,
        }
    except Exception as exc:
        diagnostics = _build_gpu_runtime_diagnostics()
        diagnostics["probe_stage"] = "session_init"
        diagnostics["failure_kind"] = "session_init_failed"
        diagnostics["probe_exception_type"] = exc.__class__.__name__
        diagnostics["probe_exception_message"] = str(exc)
        issue = diagnostics.get("issue") or "session_init_failed"
        logger.exception("GPU probe child failed during DirectML validation")
        return {
            "ok": False,
            "issue": issue or "unknown",
            "detail": str(exc),
            "diagnostics": diagnostics,
        }


def _build_gpu_runtime_warning(detail):
    base = (
        "GPU execution is unavailable. ONNX Runtime fell back to CPU. "
        "Verify that onnxruntime-directml is installed and that DirectML / DirectX 12 is available."
    )
    detail_text = str(detail or "").strip()
    if not detail_text:
        return base
    return f"{base} Detail: {detail_text}"


def _build_gpu_probe_soft_warning(detail):
    base = (
        "GPU runtime probe was inconclusive. VideoSeek will still try DirectML for this run and fall back to CPU only if actual inference fails."
    )
    detail_text = str(detail or "").strip()
    if not detail_text:
        return base
    return f"{base} Detail: {detail_text}"


def _is_gpu_probe_child():
    return os.environ.get("VIDEOSEEK_GPU_PROBE_CHILD") == "1"


def _truncate_log_text(text, limit=240):
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit]}..."


def _format_exception_detail(exc):
    if exc is None:
        return ""
    message = str(exc).strip()
    if message:
        return f"{exc.__class__.__name__}: {message}"
    return exc.__class__.__name__


def _should_disable_gpu_for_probe_issue(probe, config=None):
    issue = str((probe or {}).get("issue") or "").strip().lower()
    if issue == "unknown":
        runtime_config = dict(config or load_config())
        return not bool(runtime_config.get("gpu_probe_unknown_keep_gpu", False))
    return issue in _HARD_GPU_RUNTIME_ISSUES


def _resolve_embedding_batch_size(config=None):
    runtime_config = dict(config or load_config())
    try:
        batch_size = int(runtime_config.get("embedding_batch_size", 16))
    except (TypeError, ValueError):
        return 16
    return max(1, batch_size)


def detect_gpu_runtime_issue():
    return _build_gpu_runtime_diagnostics().get("issue", "unknown")


def _build_gpu_runtime_diagnostics():
    diagnostics = {
        "issue": "unknown",
        "os_name": os.name,
        "platform_release": platform.release(),
        "available_providers": _get_available_provider_names(),
        "missing_dlls": [],
        "loaded_dlls": [],
        "missing_msvc_dlls": [],
        "windows_build": None,
    }
    if not _is_windows():
        diagnostics["issue"] = "windows"
        return diagnostics
    if not _is_windows_10_1903_or_newer():
        diagnostics["issue"] = "windows_version"
        diagnostics["windows_build"] = _get_windows_build_number()
        return diagnostics
    if not _is_directml_provider_available():
        diagnostics["issue"] = "directml"
        return diagnostics
    diagnostics["windows_build"] = _get_windows_build_number()

    required_runtime_dlls = ["DirectML.dll", "d3d12.dll"]
    for dll_name in required_runtime_dlls:
        if _can_load_windows_dll(dll_name):
            diagnostics["loaded_dlls"].append(dll_name)
        else:
            diagnostics["missing_dlls"].append(dll_name)
    if diagnostics["missing_dlls"]:
        diagnostics["issue"] = "directx"
        return diagnostics

    required_msvc_dlls = ["vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll"]
    for dll_name in required_msvc_dlls:
        if _can_load_windows_dll(dll_name):
            diagnostics["loaded_dlls"].append(dll_name)
        else:
            diagnostics["missing_msvc_dlls"].append(dll_name)
    if diagnostics["missing_msvc_dlls"]:
        diagnostics["issue"] = "msvc"
        return diagnostics
    return diagnostics


def _get_available_provider_names():
    try:
        providers = ort.get_available_providers()
    except AttributeError:
        return []
    return [str(provider) for provider in providers]


def _get_windows_build_number():
    if not _is_windows():
        return None
    try:
        return int(sys.getwindowsversion().build)
    except AttributeError:
        return None


def _build_session_options(prefer_gpu, disable_optimizations=False):
    session_options = ort.SessionOptions()
    if prefer_gpu:
        # DirectML sessions require sequential execution and are more stable with memory pattern disabled.
        session_options.enable_mem_pattern = False
        session_options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    if disable_optimizations:
        # Some third-party exported graphs can fail specific ORT graph fusions
        # on certain builds. Keep runtime stable by disabling graph optimizations.
        session_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
    return session_options


def _is_directml_provider_available():
    try:
        return "DmlExecutionProvider" in ort.get_available_providers()
    except AttributeError:
        return False


def _is_windows():
    return os.name == "nt"


def _is_windows_10_1903_or_newer():
    if not _is_windows():
        return False

    try:
        version = sys.getwindowsversion()
        return (version.major, version.build) >= (10, 18362)
    except AttributeError:
        pass

    return platform.release() in {"10", "11"}


def _can_load_windows_dll(name):
    if not _is_windows():
        return False

    try:
        ctypes.WinDLL(name)
        return True
    except (AttributeError, OSError):
        return False


def _has_any_prefix(names, prefixes):
    for name in names:
        for prefix in prefixes:
            if name.startswith(prefix):
                return True
    return False


def _collect_available_dll_names():
    names = set()
    for directory in _candidate_dll_dirs():
        try:
            for entry in os.listdir(directory):
                lower_name = entry.lower()
                if lower_name.endswith(".dll"):
                    names.add(lower_name)
        except OSError:
            continue
    return names


def _candidate_dll_dirs():
    directories = []

    for item in os.environ.get("PATH", "").split(os.pathsep):
        item = item.strip().strip('"')
        if item and os.path.isdir(item):
            directories.append(item)

    for package_dir in site.getsitepackages():
        capi_dir = os.path.join(package_dir, "onnxruntime", "capi")
        if os.path.isdir(capi_dir):
            directories.append(capi_dir)

    try:
        user_site = site.getusersitepackages()
    except AttributeError:
        user_site = ""
    if user_site:
        capi_dir = os.path.join(user_site, "onnxruntime", "capi")
        if os.path.isdir(capi_dir):
            directories.append(capi_dir)

    return list(dict.fromkeys(directories))


@measure_time("Video indexing time:")
def generate_vectors_and_index_for_video(video_path, video_id, index_dir, vector_dir):
    frame_batch = []
    timestamp_batch = []
    vector_batches = []
    timestamps = []
    engine_instance = get_engine()
    frame_batch_size = engine_instance.embedding_batch_size

    for frame, timestamp in stream_frames_with_ffmpeg(video_path):
        frame_batch.append(frame)
        timestamp_batch.append(timestamp)
        if len(frame_batch) < frame_batch_size:
            continue
        batch_vectors = engine_instance.encode_images(frame_batch)
        if len(batch_vectors) > 0:
            vector_batches.append(batch_vectors)
            timestamps.extend(timestamp_batch[:len(batch_vectors)])
        frame_batch = []
        timestamp_batch = []

    if frame_batch:
        batch_vectors = engine_instance.encode_images(frame_batch)
        if len(batch_vectors) > 0:
            vector_batches.append(batch_vectors)
            timestamps.extend(timestamp_batch[:len(batch_vectors)])

    if not vector_batches:
        return [], [], None

    vectors = np.vstack(vector_batches).astype(np.float32)
    free_memory()
    config = load_config()
    chunk_config = chunk_config_payload(
        similarity_threshold=config.get("similarity_threshold", 0.85),
        max_chunk_duration=config.get("max_chunk_duration", 5.0),
        min_chunk_size=config.get("min_chunk_size", 2),
        similarity_mode=config.get("chunk_similarity_mode", "chunk"),
    )
    chunks = build_semantic_chunks(
        vectors,
        timestamps,
        similarity_threshold=chunk_config["similarity_threshold"],
        max_chunk_duration=chunk_config["max_chunk_duration"],
        min_chunk_size=chunk_config["min_chunk_size"],
        similarity_mode=chunk_config["similarity_mode"],
    )

    vector_file = os.path.normpath(os.path.join(vector_dir, f"{video_id}_vectors.npy"))
    index_file = os.path.normpath(os.path.join(index_dir, f"{video_id}_index.faiss"))

    ensure_folder_exists(vector_file)
    save_vector_payload(
        vectors,
        timestamps,
        vector_file,
        chunks=chunks,
        chunk_config=chunk_config,
        embedding_spec=get_active_embedding_spec(config=config),
    )

    ensure_folder_exists(index_file)
    index = create_clip_index(vectors, index_file)
    return vectors, timestamps, index


def _register_default_inference_engines():
    register_inference_engine("clip_onnx", lambda: CLIPOnnxEngine())

    def _siglip_factory():
        from src.core.siglip_provider_draft import SigLIP2OnnxEngine

        runtime_config = load_config()
        return SigLIP2OnnxEngine(get_active_model_resource_dir(config=runtime_config))

    register_inference_engine("siglip2_onnx", _siglip_factory)


_register_default_inference_engines()
