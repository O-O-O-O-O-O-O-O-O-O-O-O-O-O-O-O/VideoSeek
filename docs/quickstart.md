# VideoSeek Quickstart

This guide contains detailed setup, runtime resources, and troubleshooting notes for local development and daily use.

## 1) Environment

- OS: Windows recommended for current packaged runtime layout.
- Python: Use a recent Python 3.x environment.
- Install dependencies:

```bash
pip install -r requirements.txt
```

Or explicitly (Windows):

```bash
pip install onnxruntime-directml opencv-python PySide6 faiss-cpu numpy pillow tokenizers ftfy regex yt-dlp python-vlc fastapi uvicorn python-multipart "qrcode[pil]"
```

On Linux or macOS, replace `onnxruntime-directml` with `onnxruntime`.

## 2) Run

```bash
python main.py
```

On first launch, the app can auto-prepare runtime resources from the remote manifest configured in `src/app/app_meta.py`.

## 3) Manual Runtime Setup (Fallback)

If auto-prepare is unavailable, prepare these items manually.

### 3.1 Model Files (Profile-Based)

Place files under one of:
- `%LOCALAPPDATA%\VideoSeek\models\`
- `models/` under project root

If the in-app / manifest download is not available, you can download a model bundle manually from: [123 cloud drive (models)](https://1858268090.share.123pan.cn/123pan/VFA7vd-vhJXA) — unpack or copy files so they match the active profile layout under one of the paths above.

Required files are resolved from the active model profile.

Default `clip_onnx` example:
- `clip_visual.onnx`
- `clip_text.onnx`
- `bpe_simple_vocab_16e6.txt.gz`

If you switch to another provider/profile (for example `siglip2_onnx`), file requirements change with that profile. Runtime checks and downloads follow the active profile configuration.

### 3.2 FFmpeg

Either:
- Put `ffmpeg.exe` into `%LOCALAPPDATA%\VideoSeek\bin\`
- Or keep `ffmpeg` accessible from `PATH`

### 3.3 VLC Runtime for In-App Preview

Install `python-vlc` and ensure runtime binaries are available.

Project-local layout on Windows:
- `vlc_lib/libvlc.dll`
- `vlc_lib/libvlccore.dll`
- `vlc_lib/plugins/` (complete plugin directory)

`ui/vlc_player.py` automatically:
- Prepends `vlc_lib/` to `PATH`
- Sets `VLC_PLUGIN_PATH` when `vlc_lib/plugins/` exists

If VLC runtime is missing/incomplete, search and indexing can still work, but in-app preview playback may not.

## 4) Focused Test Suite

```bash
python -m unittest ^
  tests.test_runtime_resource_service ^
  tests.test_notice_version_utils ^
  tests.test_download_services ^
  tests.test_controllers
```

## 5) Common Issues

### Unsupported URL

- Typically caused by search/list/channel pages instead of video detail pages.
- Use direct video detail URLs.

### Fresh cookies needed

- Usually due to source-site anti-bot or auth limits.
- Refresh browser cookies and retry link extraction.

### Build finished with 0 new vectors

- Links may have been blocked by precheck or recognized as duplicates.
- Source videos may fail extraction/parsing; inspect build status summary in UI.
