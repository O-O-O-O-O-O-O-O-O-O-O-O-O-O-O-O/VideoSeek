# VideoSeek 中文说明

[**中文**](./README.zh-CN.md) | [English](./README.md)

VideoSeek 是一个基于 `PySide6 + ONNX Runtime + FAISS + FFmpeg` 的桌面语义视频检索工具。

## 快速开始

1. 安装依赖：

```bash
pip install onnxruntime-directml opencv-python PySide6 faiss-cpu numpy pillow ftfy regex yt-dlp python-vlc
```

2. 启动应用：

```bash
python main.py
```

3. 首次启动运行资源：
- 程序可按 `src/app/app_meta.py` 中的远程清单自动准备运行资源。
- 若自动准备不可用，手动步骤见 `docs/quickstart.md`。

## 运行资源要求

- 模型文件以当前激活的模型配置为准（默认配置为 `clip_onnx`）。
- `clip_onnx` 默认示例文件：
  - `clip_visual.onnx`
  - `clip_text.onnx`
  - `bpe_simple_vocab_16e6.txt.gz`
- `ffmpeg.exe`（用于抽帧与预览）。
- `python-vlc` + VLC 运行时（用于应用内预览播放）。

Windows 项目内 VLC 目录建议：
- `vlc_lib/libvlc.dll`
- `vlc_lib/libvlccore.dll`
- `vlc_lib/plugins/`

若 `vlc_lib/` 缺失或不完整，搜索/建库通常仍可用，但应用内预览播放可能不可用。

## 你可以做什么

- 本地视频库文本/图片语义检索。
- 从在线链接构建并检索网络库。
- 在应用内预览命中片段。

## 测试

```bash
python -m unittest ^
  tests.test_runtime_resource_service ^
  tests.test_notice_version_utils ^
  tests.test_download_services ^
  tests.test_controllers
```

## 更多文档

- 详细安装与排障：`docs/quickstart.md`
- 架构与模块说明：`docs/architecture.md`

## 许可证

MIT
