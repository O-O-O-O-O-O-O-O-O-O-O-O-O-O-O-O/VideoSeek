# VideoSeek

[中文说明](./README.zh-CN.md) | **English**

Desktop semantic video search built with PySide6, ONNX Runtime, FAISS, and FFmpeg.

## Quick Start

1. Install dependencies:

```bash
pip install -r requirements.txt
```

Or install explicitly (Windows; includes mobile bridge and QR):

```bash
pip install onnxruntime-directml opencv-python PySide6 faiss-cpu numpy pillow tokenizers ftfy regex yt-dlp python-vlc fastapi uvicorn python-multipart "qrcode[pil]"
```

On Linux or macOS, use `onnxruntime` instead of `onnxruntime-directml` (this project’s GPU path targets Windows DirectML; inference falls back to CPU elsewhere).

2. Start the app:

```bash
python main.py
```

3. First launch — **models and FFmpeg are not bundled.** Recommended: download the official **zip** from [123 cloud drive (models)](https://1858268090.share.123pan.cn/123pan/VFA7vd-vhJXA), run `python main.py`, open **Import runtime resources**, add the `.zip`, then **Import and Parse** (details in **`docs/quickstart.md` § 3.1**). Advanced manual layout is in § 3.2.

## Runtime Requirements

- Model files depend on the active model profile (default `clip_onnx`). **Primary workflow:** get the maintainer-built zip from [123 cloud drive (models)](https://1858268090.share.123pan.cn/123pan/VFA7vd-vhJXA) and **import it in the app** (same steps as quickstart § 3.1). `src/app/app_meta.py` still holds URLs for **release notes / version / about** and may point **「Go to download」** at the cloud folder; it is **not** assumed that ONNX files are fetched automatically without that zip flow.
- Default `clip_onnx` example files:
  - `clip_visual.onnx`
  - `clip_text.onnx`
  - `bpe_simple_vocab_16e6.txt.gz`
- `ffmpeg.exe` for frame extraction and preview.
- `python-vlc` plus VLC runtime for in-app preview playback.

Windows VLC runtime layout (project-local):
- `vlc_lib/libvlc.dll`
- `vlc_lib/libvlccore.dll`
- `vlc_lib/plugins/`

If `vlc_lib/` is missing or incomplete, search/indexing may still work but preview playback may be unavailable.

## What You Can Do

- Search local video libraries with text or image.
- Build and search a remote library from online links.
- Preview matched clips inside the app.

## Tests

Focused subset:

```bash
python -m unittest ^
  tests.test_runtime_resource_service ^
  tests.test_notice_version_utils ^
  tests.test_download_services ^
  tests.test_controllers
```

Full suite: `python -m unittest discover -s tests -p "test_*.py"` (see `docs/quickstart.md`).

## More Docs

- Detailed setup and troubleshooting: `docs/quickstart.md`
- Architecture and module map: `docs/architecture.md`

## License

MIT
