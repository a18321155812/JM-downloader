# JM Downloader 电脑端（Windows）

基于 [jmcomic](https://github.com/hect0x7/JMComic-Crawler-Python) 的电脑端下载器，提供两种界面。

## 版本

| 文件 | 说明 | 界面 |
|---|---|---|
| `jm_gui_desktop.py` | 桌面版（主要使用） | PyQt5 |
| `jm_gui.py` | Web 版（备用） | Flask + 浏览器 |

功能：批量下载本子/章节、实时进度、搜索（站内/作品/作者/标签/角色）、封面图预览、PDF/ZIP 转换等。

## 依赖

```bash
pip install jmcomic PyQt5 Flask
```

> 说明：脚本会优先加载本目录 `src/` 下的 jmcomic 源码；不存在则回退到已安装的 jmcomic 包。

## 运行

```bash
# 桌面版（主要）
python jm_gui_desktop.py

# Web 版（备用）
python jm_gui.py
```

## 打包为独立 exe

```bash
pip install pyinstaller
pyinstaller -F -w -n JMComicDownloader jm_gui_desktop.py
```

> `JMComicDownloader.spec` 为打包配置文件，可参考。

预编译 exe 请到 [Releases](https://github.com/a18321155812/JM-downloader/releases) 页面下载。
