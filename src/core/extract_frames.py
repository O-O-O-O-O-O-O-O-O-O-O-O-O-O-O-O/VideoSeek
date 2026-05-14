import subprocess

import numpy as np

from src.app.config import load_config
from src.app.logging_utils import get_logger
from src.utils import get_ffmpeg_path, get_video_duration_seconds, resolve_sampling_fps

logger = get_logger("extract_frames")


def _build_extract_command(video_path, fps):
    ffmpeg_bin = get_ffmpeg_path()
    return [
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        video_path,
        "-vf",
        f"fps={fps:.6f},scale=224:224",
        "-sn",
        "-f",
        "image2pipe",
        "-pix_fmt",
        "bgr24",
        "-vcodec",
        "rawvideo",
        "-",
    ]


def _build_startupinfo():
    startupinfo = None
    if hasattr(subprocess, "STARTUPINFO"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
    return startupinfo


def _stream_rawvideo_frames(video_path, fps):
    """Single FFmpeg rawvideo pipe reader (library indexing + remix).

    stderr is discarded instead of piped: piping stderr without draining can fill the OS
    buffer and block FFmpeg mid-stream (looks like 'stuck extracting forever').
    """
    command = _build_extract_command(video_path, float(fps))
    frame_size = 224 * 224 * 3
    count = 0
    startupinfo = _build_startupinfo()
    process = None
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            startupinfo=startupinfo,
        )
        while True:
            if not process.stdout:
                break
            in_bytes = process.stdout.read(frame_size)
            if len(in_bytes) != frame_size:
                break
            frame = np.frombuffer(in_bytes, np.uint8).reshape((224, 224, 3))
            timestamp = count / float(fps)
            count += 1
            yield frame, timestamp

        return_code = process.wait(timeout=20)
        if return_code != 0:
            logger.error("FFmpeg frame extraction failed for %s with code %s", video_path, return_code)
            return
        if count == 0:
            logger.warning("FFmpeg produced no frames for %s at %.3f FPS", video_path, fps)
            return
        logger.info("Frame extraction completed: %s frames for %s at %.3f FPS", count, video_path, fps)
    except Exception as exc:
        logger.error("Frame extraction crashed for %s: %s", video_path, exc)
        return
    finally:
        if process is not None:
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


def stream_frames_with_ffmpeg(video_path, fps_override=None):
    """Stream 224×224 BGR frames + timestamps from ``video_path``.

    If ``fps_override`` is set (remix / explicit sampling), it is used as the ``fps=`` filter rate.
    Otherwise the active config sampling rules are used (library indexing).
    """
    if fps_override is not None:
        fps = float(fps_override)
        if fps <= 0:
            raise ValueError("fps_override must be positive")
    else:
        config = load_config()
        video_duration = get_video_duration_seconds(video_path)
        fps = resolve_sampling_fps(video_duration, config=config)

    yield from _stream_rawvideo_frames(video_path, fps)


def stream_frames_with_ffmpeg_fixed_fps(video_path, fps):
    """Backward-compatible alias: same as ``stream_frames_with_ffmpeg(..., fps_override=fps)``."""
    yield from stream_frames_with_ffmpeg(video_path, fps_override=float(fps))


def extract_frames_with_ffmpeg(video_path):
    frame_pairs = list(stream_frames_with_ffmpeg(video_path))
    if not frame_pairs:
        return [], []
    frames = [item[0] for item in frame_pairs]
    timestamps = [item[1] for item in frame_pairs]
    return frames, timestamps
