# -*- coding: utf-8 -*-
"""
JMComic 安卓独立版核心模块
===========================
通过 Chaquopy 内嵌在 APK 中运行，为 Kotlin 界面提供本地服务 (127.0.0.1:5000)。

接口与电脑版 server.py 完全一致，但：
  - 监听 127.0.0.1（仅本机）
  - 下载目录为 App 私有目录
  - 清除电脑版默认的 127.0.0.1:7890 代理（手机上不存在）
"""

import os
import sys
import time
import json
import socket
import threading
import tempfile

# ── 双保险：预注册 curl_cffi stub（防止 jmcomic import 失败） ──
if "curl_cffi" not in sys.modules:
    import types as _types

    _stub = _types.ModuleType("curl_cffi")
    _stub_req = _types.ModuleType("curl_cffi.requests")

    class _AsyncSession:
        def __init__(self, *a, **k):
            raise NotImplementedError("curl_cffi 在安卓不可用，异步功能未启用")

        async def get(self, *a, **k):
            raise NotImplementedError("curl_cffi stub")

        async def post(self, *a, **k):
            raise NotImplementedError("curl_cffi stub")

        async def close(self):
            pass

    _stub_req.AsyncSession = _AsyncSession
    _stub.requests = _stub_req
    _stub.__version__ = "0.0.0-android-stub"
    sys.modules["curl_cffi"] = _stub
    sys.modules["curl_cffi.requests"] = _stub_req

from flask import Flask, request, jsonify, send_file

from jmcomic import JmOption, download_album, download_photo

# ── WebP 图片解密：Pillow 在安卓不支持 webp，改用 Android 原生解码（Kotlin WebpDecryptor） ──
# 下载(download_image→save_image_resp→transfer_to)和预览(transfer_to)都走 transfer_to，patch 它即可全覆盖
def _patch_webp_decrypt():
    try:
        from jmcomic.jm_client_interface import JmImageResp
        _orig_transfer = JmImageResp.transfer_to

        def _patched_transfer(self, path, scramble_id, decode_image=True, img_url=None):
            if decode_image and scramble_id is not None:
                try:
                    # Chaquopy: 导入 app 里的 Kotlin 类
                    from com.jmcomic.app import WebpDecryptor
                    import re
                    url = img_url or self.url
                    m = re.search(r"/media/photos/(\d+)/([^/?#]+)", url)
                    if m:
                        aid, filename = m.group(1), m.group(2)
                        data = bytes(self.content)
                        if WebpDecryptor.decryptAndSave(
                            data, int(scramble_id), aid, filename, path
                        ):
                            return
                except Exception:
                    pass
            # 兜底：原 Pillow 流程
            return _orig_transfer(self, path, scramble_id, decode_image, img_url)

        JmImageResp.transfer_to = _patched_transfer
    except Exception:
        pass


_patch_webp_decrypt()

# ---------- 全局配置 ----------
DOWNLOAD_DIR = None
_TMP_DIR = None


def set_download_dir(path):
    """由 Kotlin 调用，设置下载目录为 App 私有目录"""
    global DOWNLOAD_DIR, _TMP_DIR
    DOWNLOAD_DIR = path
    os.makedirs(path, exist_ok=True)
    _TMP_DIR = os.path.join(path, ".tmp")
    os.makedirs(_TMP_DIR, exist_ok=True)


# 当前有效的禁漫 API 域名（会随版本更新，失效时替换为新域名）
# 注意：cdnutc.me 直连可达，放最前面避免在失效域名上反复重试（每次重试 10 秒+）
API_DOMAINS = [
    "www.cdnutc.me",
    "www.cdnhjk.net",
    "www.cdngwc.cc",
    "www.cdngwc.net",
    "www.cdngwc.club",
]


def _no_proxy(opt):
    """清除默认代理（安卓上不存在电脑的 127.0.0.1:7890）"""
    try:
        opt.client.postman.meta_data.proxies = None
    except Exception:
        pass


def _build_proxies():
    """智能代理：API 域名直连（通常可达），图片 CDN 走代理（通常被墙）"""
    proxies = {}
    if _CURRENT_PROXY:
        for d in API_DOMAINS:
            proxies[f"https://{d}"] = None
            proxies[f"http://{d}"] = None
        proxies["http"] = _CURRENT_PROXY
        proxies["https"] = _CURRENT_PROXY
    return proxies


def _apply_common(opt):
    """应用安卓环境通用配置：requests 请求库（安卓无 curl_cffi）+ 智能代理 + 有效域名"""
    _no_proxy(opt)
    try:
        # 关键：改用 requests 实现（curl_cffi 安卓不可用）
        opt.client.postman.type = "requests"
    except Exception:
        pass
    try:
        opt.client.domain = API_DOMAINS
    except Exception:
        pass
    # 降低重试次数：加快失败切换，避免图片加载超时
    try:
        opt.client.retry_times = 2
    except Exception:
        pass
    # 智能代理：API 直连 + 图片走代理
    try:
        opt.client.postman.meta_data.proxies = _build_proxies()
    except Exception:
        pass


app = Flask(__name__)

# ---------- client（带超时，无代理） ----------
_client_lock = threading.Lock()
_client = None
_CURRENT_PROXY = ""  # 当前代理（来自下载配置）


def _normalize_proxy(p):
    """代理格式规范化：127.0.0.1:7890 -> http://127.0.0.1:7890"""
    p = (p or "").strip()
    if p and not p.startswith(("http://", "https://")):
        p = "http://" + p
    return p


def set_proxy(proxy):
    global _CURRENT_PROXY, _client
    proxy = _normalize_proxy(proxy)
    if proxy == _CURRENT_PROXY:
        return
    _CURRENT_PROXY = proxy
    _client = None  # 代理变化后重建 client


def get_client():
    global _client
    with _client_lock:
        if _client is None:
            opt = JmOption.default()
            _apply_common(opt)
            client = opt.build_jm_client()
            try:
                pm = client.postman
                if pm is not None and not getattr(pm, "_claw_timeout_patched", False):
                    _get = pm.get

                    def _timed_get(url, _orig=_get, **kw):
                        kw.setdefault("timeout", 20)
                        return _orig(url, **kw)

                    pm.get = _timed_get
                    pm._claw_timeout_patched = True
            except Exception:
                pass
            _client = client
        return _client


# ---------- 下载任务管理 ----------
_tasks = {}
_tasks_lock = threading.Lock()


def _update_task(task_id, **kw):
    with _tasks_lock:
        if task_id in _tasks:
            _tasks[task_id].update(kw)


def _build_download_option(cfg):
    opt = JmOption.default()
    _apply_common(opt)
    opt.dir_rule.base_dir = DOWNLOAD_DIR

    opt.dir_rule.rule_dsl = cfg.get("rule") or "Bd_Aauthoroname_Pname"
    opt.client.impl = cfg.get("client_type") or "api"
    opt.client.retry_times = int(cfg.get("retry_times") or 5)
    opt.download.image.decode = bool(cfg.get("decode", True))
    opt.download.cache = bool(cfg.get("cache", True))
    opt.download.threading.image = int(cfg.get("image_threads") or 4)
    opt.download.threading.photo = int(cfg.get("photo_threads") or 2)

    plugins = opt.plugins.src_dict

    if cfg.get("login") and cfg.get("username") and cfg.get("password"):
        plugins.setdefault("after_init", []).append({
            "plugin": "login",
            "kwargs": {"username": cfg["username"], "password": cfg["password"]}
        })

    if cfg.get("pdf"):
        pw = (cfg.get("pdf_password") or "").strip()
        encrypt = {"password": pw} if pw else None
        plugins.setdefault("after_photo", []).append({
            "plugin": "img2pdf",
            "kwargs": {
                "pdf_dir": DOWNLOAD_DIR,
                "filename_rule": cfg.get("pdf_rule") or "{Aid}_{Pname}",
                "delete_original_file": bool(cfg.get("pdf_delete", False)),
                "encrypt": encrypt,
            }
        })

    if cfg.get("zip"):
        pw = (cfg.get("zip_password") or "").strip()
        fmt = cfg.get("zip_format") or "标准ZIP"
        if fmt == "7z":
            encrypt = {"password": pw, "impl": "7z"}
            suffix = "7z"
        elif fmt == "加密ZIP(AES)":
            encrypt = {"password": pw} if pw else {"password": "123456"}
            suffix = "zip"
        else:
            encrypt = None
            suffix = "zip"
        # 按压缩级别注册：album=整本打包(after_album)；photo=每章打包(after_photo，单章下载也能触发)
        zip_kwargs = {
            "level": cfg.get("zip_level") or "photo",
            "delete_original_file": bool(cfg.get("zip_delete", False)),
            "zip_dir": DOWNLOAD_DIR,
            "suffix": suffix,
            "encrypt": encrypt,
        }
        if (cfg.get("zip_level") or "photo") == "album":
            plugins.setdefault("after_album", []).append({
                "plugin": "zip", "kwargs": zip_kwargs})
        else:
            plugins.setdefault("after_photo", []).append({
                "plugin": "zip", "kwargs": zip_kwargs})

    if cfg.get("cover"):
        plugins.setdefault("after_album", []).append({
            "plugin": "download_cover",
            "kwargs": {"dir_rule": {
                "rule": "Bd_Aid_cover.jpg",
                "base_dir": DOWNLOAD_DIR,
            }}
        })

    _orig_build_client = opt.build_jm_client

    def _build_client_with_timeout(*args, **kwargs):
        client = _orig_build_client(*args, **kwargs)
        try:
            pm = client.postman
            if pm is not None and not getattr(pm, "_claw_timeout_patched", False):
                _get, _post = pm.get, pm.post

                def _timed_get(url, _orig=_get, **kw):
                    kw.setdefault("timeout", 30)
                    return _orig(url, **kw)

                def _timed_post(url, _orig=_post, **kw):
                    kw.setdefault("timeout", 30)
                    return _orig(url, **kw)

                pm.get, pm.post = _timed_get, _timed_post
                pm._claw_timeout_patched = True
        except Exception:
            pass
        return client

    opt.build_jm_client = _build_client_with_timeout
    return opt


_IMG_DOMAINS = []


def _init_image_domains():
    """检测当前网络下可达的图片 CDN 域名，并让 jmcomic 使用可达域名下载图片"""
    global _IMG_DOMAINS
    if _IMG_DOMAINS:
        return
    from jmcomic import JmPhotoDetail, JmModuleConfig

    candidates = list(dict.fromkeys(JmModuleConfig.DOMAIN_IMAGE_LIST))
    reachable = []
    for d in candidates:
        try:
            socket.create_connection((d, 443), timeout=3).close()
            reachable.append(d)
        except Exception:
            pass
    _IMG_DOMAINS = reachable
    if not reachable:
        return

    # 让图片 URL 使用可达域名（原 data_original_domain 可能被墙）
    _orig_get_img = JmPhotoDetail.get_img_data_original

    def _patched_get_img(self, img_name):
        if self.data_original_domain not in _IMG_DOMAINS:
            self.data_original_domain = _IMG_DOMAINS[0]
        return _orig_get_img(self, img_name)

    JmPhotoDetail.get_img_data_original = _patched_get_img


def _download_worker(task_id, jm_id, dl_type, cfg):
    _update_task(task_id, status="running", message="开始下载", progress=0)
    first_err = ""
    failed_count = 0
    try:
        # 有代理时直接走代理（域名直连检测不准确），无代理才检测可达域名
        if not _CURRENT_PROXY:
            _init_image_domains()
        opt = _build_download_option(cfg)
        if dl_type == "photo" or jm_id.lower().startswith("p"):
            jm_id = jm_id[1:] if jm_id.lower().startswith("p") else jm_id
            download_photo(jm_id, option=opt, check_exception=False)
        else:
            result = download_album(jm_id, option=opt, check_exception=False)
            # download_album 返回 (album, dler)
            if isinstance(result, (tuple, list)) and len(result) >= 2:
                dler = result[1]
                failed_list = getattr(dler, "download_failed_image", [])
                failed_count = len(failed_list)
                if failed_list:
                    first_err = str(failed_list[0][1])[:150]

        # 统计实际保存的文件数（排除 .tmp）
        saved = 0
        for root, dirs, fs in os.walk(DOWNLOAD_DIR):
            if ".tmp" in dirs:
                dirs.remove(".tmp")
            saved += len(fs)

        parts = []
        if cfg.get("pdf"):
            parts.append("已转PDF")
        if cfg.get("zip"):
            parts.append("已压缩")
        if saved == 0:
            msg = "下载完成但未保存任何文件"
            if first_err:
                from PIL import features as _pf
                msg += f"｜失败{failed_count}张｜WebP支持: {_pf.check('webp')}"
                msg += f"｜错误: {first_err}"
            else:
                msg += f"｜代理: {_CURRENT_PROXY or '无'}"
        else:
            msg = f"下载完成（{saved} 个文件）" + ("，" + "+".join(parts) if parts else "")
        _update_task(task_id, status="done", progress=100, message=msg,
                     end_time=time.time())
    except Exception as e:
        _update_task(task_id, status="failed", message=str(e), end_time=time.time())


# ---------- 接口 ----------

@app.route("/")
def index():
    return "JMComic 独立版运行中"


@app.route("/api/album/<album_id>")
def api_album(album_id):
    try:
        client = get_client()
        album = client.get_album_detail(album_id)
        photos = [{"id": p.id, "title": p.title} for p in album]
        return jsonify({
            "id": str(album.id),
            "title": album.title,
            "author": album.author,
            "tags": getattr(album, "tags", []),
            "description": getattr(album, "description", ""),
            "photo_count": len(photos),
            "photos": photos,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/photo/<photo_id>")
def api_photo(photo_id):
    try:
        client = get_client()
        photo = client.get_photo_detail(photo_id)
        return jsonify({
            "id": str(photo.id),
            "title": photo.title,
            "album_id": str(photo.album_id),
            "image_count": len(photo),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/cover/<album_id>")
def api_cover(album_id):
    try:
        client = get_client()
        path = os.path.join(_TMP_DIR, f"cover_{album_id}.jpg")
        client.download_album_cover(album_id, path, size="")
        if os.path.exists(path):
            return send_file(path, mimetype="image/jpeg")
        return "", 404
    except Exception as e:
        return str(e), 500


@app.route("/api/preview/<photo_id>/<int:index>")
def api_preview(photo_id, index):
    try:
        client = get_client()
        photo = client.get_photo_detail(photo_id)
        if index < 0 or index >= len(photo):
            return "", 404
        img = photo[index]
        # 解密后保存为 PNG（Android WebpDecryptor 输出 PNG 内容）
        path = os.path.join(_TMP_DIR, f"p_{photo_id}_{index}.png")
        resp = client.get_jm_image(img.img_url)
        resp.transfer_to(path, scramble_id=img.scramble_id, decode_image=True,
                         img_url=img.img_url)
        if os.path.exists(path):
            return send_file(path, mimetype="image/png")
        return "", 404
    except Exception as e:
        return str(e), 500


@app.route("/api/download", methods=["POST"])
def api_download():
    data = request.get_json(force=True) or {}
    jm_id = str(data.get("id", "")).strip()
    dl_type = str(data.get("type", "album")).strip() or "album"
    if not jm_id:
        return jsonify({"error": "缺少 id"}), 400

    cfg = {
        "image_threads": int(data.get("image_threads") or 4),
        "photo_threads": int(data.get("photo_threads") or 2),
        "decode": bool(data.get("decode", True)),
        "cache": bool(data.get("cache", True)),
        "rule": data.get("rule", ""),
        "client_type": data.get("client_type", "api"),
        "retry_times": int(data.get("retry_times") or 5),
        "proxy": data.get("proxy", ""),
        "pdf": bool(data.get("pdf", False)),
        "pdf_password": data.get("pdf_password", ""),
        "pdf_delete": bool(data.get("pdf_delete", False)),
        "pdf_rule": data.get("pdf_rule", ""),
        "zip": bool(data.get("zip", False)),
        "zip_format": data.get("zip_format", ""),
        "zip_password": data.get("zip_password", ""),
        "zip_level": data.get("zip_level", "photo"),
        "zip_delete": bool(data.get("zip_delete", False)),
        "cover": bool(data.get("cover", False)),
        "login": bool(data.get("login", False)),
        "username": data.get("username", ""),
        "password": data.get("password", ""),
    }

    # 代理设置全局生效（下载与预览）
    set_proxy(cfg.get("proxy", ""))

    task_id = jm_id
    with _tasks_lock:
        if task_id in _tasks and _tasks[task_id]["status"] in ("running", "pending"):
            return jsonify({"error": "该任务正在下载中", "id": task_id}), 400
        _tasks[task_id] = {
            "id": task_id, "type": dl_type, "status": "pending",
            "progress": 0, "message": "排队中", "start_time": time.time(),
            "pdf": cfg["pdf"], "zip": cfg["zip"],
        }

    threading.Thread(target=_download_worker, args=(task_id, jm_id, dl_type, cfg),
                     daemon=True).start()
    return jsonify({"ok": True, "id": task_id})


@app.route("/api/cancel/<task_id>", methods=["POST"])
def api_cancel(task_id):
    with _tasks_lock:
        if task_id in _tasks and _tasks[task_id]["status"] in ("running", "pending"):
            _tasks[task_id]["status"] = "cancelled"
            _tasks[task_id]["message"] = "已取消"
            return jsonify({"ok": True})
    return jsonify({"error": "任务不存在或已结束"}), 400


@app.route("/api/tasks")
def api_tasks():
    with _tasks_lock:
        return jsonify(list(_tasks.values()))


@app.route("/api/files")
def api_files():
    files = []
    for root, dirs, fs in os.walk(DOWNLOAD_DIR):
        if ".tmp" in dirs:
            dirs.remove(".tmp")
        for f in fs:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, DOWNLOAD_DIR)
            size = os.path.getsize(full)
            mtime = int(os.path.getmtime(full))
            files.append({"path": rel, "size": size, "time": mtime})
    return jsonify({"base": DOWNLOAD_DIR, "files": files})


@app.route("/api/file")
def api_file():
    rel = request.args.get("path", "")
    full = os.path.normpath(os.path.join(DOWNLOAD_DIR, rel))
    if not full.startswith(os.path.normpath(DOWNLOAD_DIR)):
        return "", 403
    if os.path.isfile(full):
        return send_file(full)
    return "", 404


@app.route("/api/delete", methods=["POST"])
def api_delete():
    """删除已下载的文件或文件夹（支持单个图片/整个漫画目录）"""
    import shutil
    data = request.get_json(force=True) or {}
    rel = (data.get("path") or "").strip()
    if not rel:
        return jsonify({"error": "缺少 path"}), 400
    full = os.path.normpath(os.path.join(DOWNLOAD_DIR, rel))
    if not full.startswith(os.path.normpath(DOWNLOAD_DIR)):
        return jsonify({"error": "路径非法"}), 403
    if os.path.isdir(full):
        shutil.rmtree(full, ignore_errors=True)
        return jsonify({"ok": True, "deleted": rel})
    if os.path.isfile(full):
        os.remove(full)
        return jsonify({"ok": True, "deleted": rel})
    return jsonify({"error": "路径不存在"}), 404


# ---------- 启动 ----------

def start(port=5000):
    """由 Kotlin 在后台线程调用，启动本地服务"""
    if DOWNLOAD_DIR is None:
        set_download_dir(os.path.join(os.path.expanduser("~"), "downloads"))
    # 日志重定向：所有 stdout/stderr（含报错、jmcomic 日志、werkzeug 请求日志）写入日志文件
    # 日志目录独立于下载目录（downloads 的上一级）
    try:
        log_dir = os.path.join(os.path.dirname(DOWNLOAD_DIR), "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "error.log")
        _log_file = open(log_path, "w", encoding="utf-8")
        sys.stdout = _log_file
        sys.stderr = _log_file
    except Exception:
        pass
    # 生产环境关闭 debug
    app.run(host="127.0.0.1", port=port, threaded=True, debug=False)
