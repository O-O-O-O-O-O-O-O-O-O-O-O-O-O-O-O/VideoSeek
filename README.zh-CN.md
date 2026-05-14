# VideoSeek 中文说明

[**中文**](./README.zh-CN.md) | [English](./README.md)

VideoSeek 是一个基于 PySide6 + ONNX Runtime + FAISS + FFmpeg 的桌面语义视频检索工具。

## 快速开始

1. 安装依赖：

```bash
pip install -r requirements.txt
```

或手动安装（Windows；含手机桥接与二维码相关包）：

```bash
pip install onnxruntime-directml opencv-python PySide6 faiss-cpu numpy pillow tokenizers ftfy regex yt-dlp python-vlc fastapi uvicorn python-multipart "qrcode[pil]"
```

在 Linux / macOS 上请用 `onnxruntime` 替代 `onnxruntime-directml`（当前 GPU 路径面向 Windows DirectML，其它系统一般为 CPU 推理）。

2. 启动应用：

```bash
python main.py
```

3. 首次启动：**模型与 FFmpeg 不会随仓库自带。** 推荐：从 [123 云盘（模型）](https://1858268090.share.123pan.cn/123pan/VFA7vd-vhJXA) 下载官方 **zip**，运行 `python main.py`，打开 **导入运行资源**，添加 `.zip` 后点 **导入并解析**（详见 **`docs/quickstart.md` 第 3.1 节**）。高级手动摆放见 § 3.2。

## 运行资源要求

- 模型文件随当前激活的模型配置变化（默认 `clip_onnx`）。**主路径：** 使用 [123 云盘（模型）](https://1858268090.share.123pan.cn/123pan/VFA7vd-vhJXA) 提供的 zip，在应用内 **导入并解析**（与 quickstart § 3.1 一致）。`src/app/app_meta.py` 中的链接主要用于 **公告 / 版本 / 关于** 等 JSON，以及对话框里 **前往下载** 打开网盘；**不要理解为**启动即可全自动拉取 ONNX（除非你自行配置可解析的 JSON 清单 URL）。
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
- **混剪溯源：**对本地混剪成片抽帧，在已索引的本地视频库中追溯每段镜头对应的源片与时间（见 `docs/remix_source_match.md`）。

## 测试

常用子集：

```bash
python -m unittest ^
  tests.test_runtime_resource_service ^
  tests.test_notice_version_utils ^
  tests.test_download_services ^
  tests.test_controllers
```

全量：`python -m unittest discover -s tests -p "test_*.py"`（见 `docs/quickstart.md`）。

## 更多文档

- 详细安装与排障：`docs/quickstart.md`
- 架构与模块说明：`docs/architecture.md`
- 混剪溯源功能说明：`docs/remix_source_match.md`

## 许可证

MIT
