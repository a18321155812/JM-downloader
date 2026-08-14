# JM Downloader（禁漫天堂 安卓独立版）

基于 [jmcomic](https://github.com/hect0x7/JMComic-Crawler-Python) 的 Android 下载器，通过 **Chaquopy** 把 Python 运行时内嵌进 APK，在手机上独立完成禁漫（JMComic）本子的搜索、预览与下载，无需连接电脑。

> ⚠️ **免责声明**
> 本项目仅供**学习与研究**使用，请勿用于任何侵犯版权或违反当地法律法规的用途。下载内容请于 24 小时内删除，并支持正版。使用本项目所产生的一切后果由使用者自行承担。

## 功能特性

- 🔍 本子搜索与详情预览（封面 / 章节缩略图）
- ⬇️ 整本（album）与单章（photo）下载，支持多线程
- 🖼️ 图片解密：Android 原生解码 WebP + scramble 分段重排（无需 Pillow 的 libwebp）
- 📄 下载后一键转 PDF（可设密码）/ ZIP（标准 / 加密 AES）
- 🎨 可选下载封面
- 🔐 支持登录（带账号密码的下载）
- 🌐 智能代理：API 域名直连 + 图片 CDN 走代理
- 📁 文件管理：浏览、分享、删除已下载内容

## 技术架构

| 层 | 技术 |
|---|---|
| UI | Kotlin + Jetpack Compose (Material 3) |
| Python 运行时 | Chaquopy 17 + Python 3.13 |
| 本地服务 | Flask（`127.0.0.1:5000`，仅本机） |
| 下载核心 | [jmcomic](https://github.com/hect0x7/JMComic-Crawler-Python) |
| 网络 | OkHttp（Kotlin 端）/ requests（Python 端） |

架构说明：Kotlin 界面通过 HTTP 调用内嵌的 Flask 服务（`main.py`），后者封装 jmcomic 完成抓取与下载；图片解密由 Kotlin 侧的 `WebpDecryptor` 完成（因安卓环境 Pillow 不支持 WebP）。

## 构建

环境要求：

- Android Studio（或 Gradle 8.x + JDK 11+）
- Android SDK（`compileSdk 35`）
- 本机 Python 3.13（供 Chaquopy 构建期使用）

步骤：

```bash
# 1. 指定本机 Python 解释器（构建期使用，Chaquopy 会据此打包）
#    Windows PowerShell:
$env:CHAQUOPY_PYTHON = "F:/Anaconda3/python.exe"
#    Linux / macOS:
export CHAQUOPY_PYTHON=/usr/bin/python3

# 2. 构建 Release APK
./gradlew assembleRelease
```

构建产物位于 `app/build_v222/outputs/apk/release/`。

> 说明：`app/build.gradle.kts` 中 `buildPython` 会读取环境变量 `CHAQUOPY_PYTHON`，未设置时回退到 PATH 中的 `python`。首次构建会联网下载 Chaquopy 依赖与 Python 包，耗时较长属正常现象。

## 发布说明

- 预编译 APK 请到 [Releases](https://github.com/a18321155812/JM-downloader/releases) 页面下载。
- 源码仓库**不包含** APK 与任何已下载内容。

## License

[MIT](LICENSE)

本项目基于 [jmcomic](https://github.com/hect0x7/JMComic-Crawler-Python)（MIT License）构建。
