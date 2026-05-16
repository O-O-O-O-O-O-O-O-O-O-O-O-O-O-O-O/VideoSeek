import os
import subprocess
import threading
import time

import numpy as np

from src.app.config import load_config
from src.app.logging_utils import get_logger
from src.utils import get_ffmpeg_path, get_video_duration_seconds, resolve_sampling_fps

logger = get_logger("extract_frames")

# Software decode + CPU filters; FFmpeg outputs 224×224 BGR rawvideo on stdout.
_VF = "fps={fps:.6f},scale=224:224:flags=fast_bilinear"
_FRAME_SIZE = 224 * 224 * 3
_DEFAULT_READ_TIMEOUT_SEC = 600.0


class FrameExtractionError(RuntimeError):
    """FFmpeg frame extraction failed or produced an unusable stream."""

    def __init__(self, message, *, video_path="", exit_code=None, frame_count=0):
        super().__init__(message)
        self.video_path = video_path
        self.exit_code = exit_code
        self.frame_count = int(frame_count or 0)


def _resolve_read_timeout_sec():
    raw = os.environ.get("VIDEOSEEK_FFMPEG_READ_TIMEOUT_SEC", "").strip()
    if not raw:
        return _DEFAULT_READ_TIMEOUT_SEC
    try:
        value = float(raw)
    except ValueError:
        return _DEFAULT_READ_TIMEOUT_SEC
    if value <= 0:
        return None
    return value


def _ffmpeg_thread_count_token():
    """Return argv token for ``-threads`` (``0`` = FFmpeg default). Override: ``VIDEOSEEK_FFMPEG_THREADS``."""
    raw = os.environ.get("VIDEOSEEK_FFMPEG_THREADS", "").strip()
    if not raw:
        return "0"
    try:
        n = int(raw)
    except ValueError:
        return "0"
    if n <= 0:
        return "0"
    return str(min(n, 16))


def _build_extract_command(video_path, fps):
    ffmpeg_bin = get_ffmpeg_path()
    return [
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel",
        "error",
        "-threads",
        _ffmpeg_thread_count_token(),
        "-i",
        video_path,
        "-vf",
        _VF.format(fps=float(fps)),
        "-sn",
        "-f",
        "image2pipe",
        "-pix_fmt",
        "bgr24",
        "-vcodec",
        "rawvideo",
        "-",
    ]


def _signed_subprocess_code(code: int) -> int:
    """Normalize Windows unsigned 32-bit process exit codes to signed."""
    if code is None:
        return 0
    code = int(code)
    if code > 0x7FFFFFFF:
        return code - 0x100000000
    return code


def _build_startupinfo():
    startupinfo = None
    if hasattr(subprocess, "STARTUPINFO"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
    return startupinfo


def terminate_ffmpeg_process(process):
    if process is None:
        return
    try:
        if process.stdout:
            process.stdout.close()
    except OSError:
        pass
    try:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
    except OSError:
        pass


def _read_pipe_bytes(stream, size, *, timeout_sec, should_stop, process):
    """Read exactly ``size`` bytes from a pipe, honoring stop/timeout by killing FFmpeg."""
    if timeout_sec is None and not should_stop:
        return stream.read(size)

    payload = [b""]
    read_error = [None]

    def _worker():
        try:
            payload[0] = stream.read(size)
        except Exception as exc:
            read_error[0] = exc

    thread = threading.Thread(target=_worker, name="VSFfmpegPipeRead", daemon=True)
    thread.start()
    deadline = None if timeout_sec is None else (time.monotonic() + float(timeout_sec))
    while thread.is_alive():
        if should_stop and should_stop():
            terminate_ffmpeg_process(process)
            raise InterruptedError("Frame extraction stopped")
        if deadline is not None and time.monotonic() >= deadline:
            terminate_ffmpeg_process(process)
            raise FrameExtractionError(
                f"Timed out while reading FFmpeg output after {timeout_sec:.0f}s",
            )
        thread.join(timeout=0.25)

    if read_error[0] is not None:
        raise read_error[0]
    return payload[0]


def _stream_rawvideo_frames(
    video_path,
    fps,
    *,
    should_stop=None,
    process_holder=None,
    read_timeout_sec=None,
):
    """Single FFmpeg rawvideo pipe reader (library indexing + remix).

    stderr is discarded instead of piped: piping stderr without draining can fill the OS
    buffer and block FFmpeg mid-stream (looks like 'stuck extracting forever').

    Raises:
        FrameExtractionError: FFmpeg failed or the stream ended abnormally after frames were emitted.
        InterruptedError: ``should_stop`` requested termination.
    """
    command = _build_extract_command(video_path, float(fps))
    count = 0
    startupinfo = _build_startupinfo()
    process = None
    timeout_sec = _resolve_read_timeout_sec() if read_timeout_sec is None else read_timeout_sec
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            startupinfo=startupinfo,
        )
        if process_holder is not None:
            process_holder["process"] = process

        while True:
            if should_stop and should_stop():
                terminate_ffmpeg_process(process)
                raise InterruptedError("Frame extraction stopped")

            if not process.stdout:
                break

            in_bytes = _read_pipe_bytes(
                process.stdout,
                _FRAME_SIZE,
                timeout_sec=timeout_sec,
                should_stop=should_stop,
                process=process,
            )
            if len(in_bytes) != _FRAME_SIZE:
                break

            frame = np.frombuffer(in_bytes, np.uint8).reshape((224, 224, 3))
            timestamp = count / float(fps)
            count += 1
            yield frame, timestamp

        return_code = process.wait(timeout=20)
        signed_code = _signed_subprocess_code(return_code)
        if return_code != 0:
            message = (
                f"FFmpeg frame extraction failed for {video_path} with exit code {return_code} "
                f"(signed {signed_code}) after {count} frame(s)"
            )
            logger.error(message)
            raise FrameExtractionError(
                message,
                video_path=video_path,
                exit_code=signed_code,
                frame_count=count,
            )
        if count == 0:
            logger.warning("FFmpeg produced no frames for %s at %.3f FPS", video_path, fps)
            return
        logger.info("Frame extraction completed: %s frames for %s at %.3f FPS", count, video_path, fps)
    except (FrameExtractionError, InterruptedError):
        raise
    except Exception as exc:
        logger.error("Frame extraction crashed for %s: %s", video_path, exc)
        raise FrameExtractionError(
            f"Frame extraction crashed for {video_path}: {exc}",
            video_path=video_path,
            frame_count=count,
        ) from exc
    finally:
        if process_holder is not None:
            process_holder.pop("process", None)
        terminate_ffmpeg_process(process)


def stream_frames_with_ffmpeg(
    video_path,
    fps_override=None,
    *,
    should_stop=None,
    process_holder=None,
    read_timeout_sec=None,
):
    """Stream 224×224 BGR frames + timestamps from ``video_path``.

    If ``fps_override`` is set (remix / explicit sampling), it is used as the ``fps=`` filter rate.
    Otherwise the active config sampling rules are used (library indexing).

    Decoding and scaling are always done in FFmpeg on the CPU (no ``-hwaccel``).

    Optional env:
    - ``VIDEOSEEK_FFMPEG_THREADS``: FFmpeg ``-threads`` (capped at 16)
    - ``VIDEOSEEK_FFMPEG_READ_TIMEOUT_SEC``: per-read stall timeout (default 600; ``0`` disables)
    """
    config = load_config()
    if fps_override is not None:
        fps = float(fps_override)
        if fps <= 0:
            raise ValueError("fps_override must be positive")
    else:
        video_duration = get_video_duration_seconds(video_path)
        fps = resolve_sampling_fps(video_duration, config=config)

    yield from _stream_rawvideo_frames(
        video_path,
        fps,
        should_stop=should_stop,
        process_holder=process_holder,
        read_timeout_sec=read_timeout_sec,
    )


def stream_frames_with_ffmpeg_fixed_fps(video_path, fps):
    """Backward-compatible alias: same as ``stream_frames_with_ffmpeg(..., fps_override=fps)``."""
    yield from stream_frames_with_ffmpeg(video_path, fps_override=float(fps))


def extract_frames_with_ffmpeg(video_path, **stream_kwargs):
    frame_pairs = list(stream_frames_with_ffmpeg(video_path, **stream_kwargs))
    if not frame_pairs:
        return [], []
    frames = [item[0] for item in frame_pairs]
    timestamps = [item[1] for item in frame_pairs]
    return frames, timestamps
