# -*- coding: utf-8 -*-
"""
JMComic 可视化下载器 (Web GUI)
===============================

基于 jmcomic 库的单文件可视化应用，功能包括：

  * 批量下载本子(Album) / 章节(Photo)
  * 实时下载进度（进度条 + 日志）
  * 搜索本子（站内 / 作品 / 作者 / 标签 / 角色）
  * 查看本子详情与章节列表，可单独下载章节
  * 图片封面防盗链代理

运行方式:
    python jm_gui.py

然后浏览器打开  http://127.0.0.1:5000

说明:
    * 脚本会自动优先加载本目录 src/ 下的 jmcomic 源码；
      若不存在则使用已安装的 jmcomic 包。
    * 依赖: flask  (pip install flask)
"""

import os
import sys
import time
import uuid
import threading

# Windows 控制台默认 GBK 编码，无法打印 emoji，这里强制用 UTF-8
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# ---------------------------------------------------------------------------
# 0. 路径处理：优先使用本仓库 src 目录下的 jmcomic 源码
# ---------------------------------------------------------------------------
_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.join(_PROJECT_DIR, 'src')
if os.path.isdir(_SRC_DIR) and _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

import jmcomic
from jmcomic.jm_option import JmOption, DirRule
from jmcomic.jm_downloader import JmDownloader
from jmcomic.jm_config import JmModuleConfig
from jmcomic.jm_toolkit import JmcomicText

try:
    from flask import Flask, request, jsonify, Response, send_from_directory
except ImportError:
    print('缺少依赖 flask，请先执行: pip install flask')
    sys.exit(1)

app = Flask(__name__)

# ---------------------------------------------------------------------------
# 1. 后台任务状态管理
# ---------------------------------------------------------------------------
TASKS = {}          # task_id -> task dict
TASKS_LOCK = threading.Lock()


def now_time() -> str:
    return time.strftime('%H:%M:%S')


def new_task_id() -> str:
    return uuid.uuid4().hex[:8]


def make_task(ids, config) -> dict:
    return {
        'id': new_task_id(),
        'status': 'waiting',          # waiting / running / done / error / cancelled
        'ids': list(ids),
        'config': config,
        'done_images': 0,
        'total_images': 0,
        'albums': [],                  # 已完成的 album 摘要
        'current_album': None,         # 正在下载的 album
        'logs': [],
        'error': None,
        'cancel': False,
        'start_time': now_time(),
    }


def task_log(task, msg):
    task['logs'].append(f'[{now_time()}] {msg}')
    if len(task['logs']) > 2000:
        del task['logs'][:-1500]


# ---------------------------------------------------------------------------
# 2. 带进度回调的下载器
# ---------------------------------------------------------------------------
class ProgressDownloader(JmDownloader):
    """覆写回调钩子，把下载进度实时写入 task 字典。

    同时支持两种模式：
      * 整本下载（album）—— 由 before_album / after_album 驱动
      * 单章节下载（photo）—— 没有 album 回调，在 before_photo 里补建进度
    """

    def __init__(self, option, task):
        super().__init__(option)
        self.task = task
        self._photo_mode = False  # 是否为单章节下载模式

    def before_album(self, album):
        super().before_album(album)
        self._photo_mode = False
        ap = {
            'id': album.id,
            'name': album.name,
            'authors': list(getattr(album, 'authors', []) or []),
            'total_images': int(album.page_count or 0),
            'done_images': 0,
            'total_photos': len(album),
            'done_photos': 0,
            'status': 'downloading',
        }
        self.task['current_album'] = ap
        self.task['total_images'] += ap['total_images']
        task_log(self.task, f'开始下载本子 [{album.id}] {album.name}｜{len(album)} 章｜{album.page_count} 页')

    def after_album(self, album):
        super().after_album(album)
        ap = self.task.get('current_album')
        if ap and ap['id'] == album.id:
            ap['status'] = 'done'
            ap['done_photos'] = ap['total_photos']
            self.task['albums'].append(ap)
            self.task['current_album'] = None
        task_log(self.task, f'✅ 本子 [{album.id}] 下载完成')

    def before_photo(self, photo):
        super().before_photo(photo)
        self._check_cancel()
        # 单章节下载：没有 album 上下文，这里补一个临时的进度条目
        if self.task.get('current_album') is None:
            self._photo_mode = True
            from_album = getattr(photo, 'from_album', None)
            name = getattr(photo, 'name', '')
            if from_album is not None:
                aid, aname = from_album.id, getattr(from_album, 'name', '')
            else:
                aid, aname = f'章节{photo.id}', (name or f'章节 {photo.id}')
            ap = {
                'id': aid,
                'name': aname,
                'authors': list(getattr(from_album, 'authors', []) or []) if from_album is not None else [],
                'total_images': len(photo),
                'done_images': 0,
                'total_photos': 1,
                'done_photos': 0,
                'status': 'downloading',
            }
            self.task['current_album'] = ap
            self.task['total_images'] += ap['total_images']
        task_log(self.task, f'  开始章节 [{photo.id}]：{name or "（未命名）"}（{len(photo)} 页）')

    def after_photo(self, photo):
        super().after_photo(photo)
        ap = self.task.get('current_album')
        if ap:
            ap['done_photos'] += 1
            if self._photo_mode:
                ap['status'] = 'done'
                ap['done_images'] = ap['total_images']
                self.task['albums'].append(ap)
                self.task['current_album'] = None
                self._photo_mode = False
        task_log(self.task, f'  ✅ 章节 [{photo.id}] 完成')

    def after_image(self, image, img_save_path):
        super().after_image(image, img_save_path)
        self._check_cancel()
        self.task['done_images'] += 1
        ap = self.task.get('current_album')
        if ap:
            ap['done_images'] += 1
            total = ap['total_images']
            if total >= 20 and ap['done_images'] % max(1, total // 10) == 0:
                task_log(self.task,
                         f'  [album {ap["id"]}] 图片 {ap["done_images"]}/{total} '
                         f'({int(ap["done_images"] / total * 100)}%)')

    def _check_cancel(self):
        if self.task['cancel']:
            raise RuntimeError('用户取消下载')


# ---------------------------------------------------------------------------
# 3. Option 构造
# ---------------------------------------------------------------------------
def build_option(task, config) -> JmOption:
    option = JmOption.default()

    # 下载目录
    base_dir = (config.get('download_dir') or '').strip() or os.getcwd()
    rule = (config.get('dir_rule') or '').strip() or 'Bd_Aid_Pindextitle'
    option.dir_rule = DirRule(rule, base_dir=base_dir,
                              normalize_zh=config.get('normalize_zh') or None)

    # 客户端实现：api=移动端(不限ip)  html=网页端(效率高但限ip)
    impl = config.get('impl') or 'api'
    if impl in ('api', 'html'):
        option.client.impl = impl

    # 图片格式转换
    suffix = (config.get('suffix') or '').strip()
    if suffix:
        if not suffix.startswith('.'):
            suffix = '.' + suffix
        option.download.image.suffix = suffix

    # 图片是否解密还原
    decode = config.get('decode', True)
    option.download.image.decode = bool(decode)

    # 图片线程数
    try:
        n = int(config.get('image_threads') or 0)
        if n > 0:
            option.download.threading.image = n
    except (TypeError, ValueError):
        pass

    return option


# ---------------------------------------------------------------------------
# 4. 后台下载逻辑
# ---------------------------------------------------------------------------
def _download_album_worker(task, option, aid):
    dler = ProgressDownloader(option, task)
    dler.download_album(aid)


def _download_photo_worker(task, option, pid):
    dler = ProgressDownloader(option, task)
    dler.download_photo(pid)


def run_download(tid, ids, config):
    task = TASKS.get(tid)
    if task is None:
        return
    task['status'] = 'running'
    task_log(task, f'任务开始｜待下载: {", ".join(ids)}')

    try:
        option = build_option(task, config)
        task_log(task, f'下载目录: {option.dir_rule.base_dir}')
        task_log(task, f'客户端类型: {option.client.impl}｜dir_rule: {option.dir_rule.rule_dsl}')

        for raw in ids:
            if task['cancel']:
                break
            raw = str(raw).strip()
            if not raw:
                continue
            try:
                if raw[0] in 'ap':
                    prefix, jid = raw[0], raw[1:]
                    if not jid.isdigit():
                        task_log(task, f'无效ID: {raw}')
                        continue
                    if prefix == 'p':
                        task_log(task, f'➡️ 下载章节 [{jid}]')
                        _download_photo_worker(task, option, jid)
                    else:
                        task_log(task, f'➡️ 下载本子 [{jid}]')
                        _download_album_worker(task, option, jid)
                elif raw.isdigit():
                    task_log(task, f'➡️ 下载本子 [{raw}]')
                    _download_album_worker(task, option, raw)
                else:
                    task_log(task, f'无法识别的ID: {raw}')
            except Exception as e:
                if task['cancel']:
                    break
                task_log(task, f'❌ 下载 [{raw}] 失败: {e}')

        if task['cancel']:
            task['status'] = 'cancelled'
            task_log(task, '⏹ 任务已取消')
        else:
            task['status'] = 'done'
            task_log(task, '🎉 任务全部完成')

    except Exception as e:
        task['status'] = 'error'
        task['error'] = str(e)
        task_log(task, f'❌ 任务异常: {e}')


# ---------------------------------------------------------------------------
# 5. Flask 路由
# ---------------------------------------------------------------------------
@app.route('/')
def index():
    return INDEX_HTML


@app.route('/api/health')
def api_health():
    return jsonify({'ok': True, 'jmcomic_version': getattr(jmcomic, '__version__', 'unknown')})


@app.route('/api/download', methods=['POST'])
def api_download():
    data = request.get_json(silent=True) or {}
    ids = [str(i).strip() for i in (data.get('ids') or []) if str(i).strip()]
    if not ids:
        return jsonify({'error': '没有输入有效的ID'}), 400
    config = data.get('config') or {}
    with TASKS_LOCK:
        task = make_task(ids, config)
        TASKS[task['id']] = task
    threading.Thread(target=run_download, args=(task['id'], ids, config), daemon=True).start()
    return jsonify({'task_id': task['id']})


@app.route('/api/tasks')
def api_tasks():
    with TASKS_LOCK:
        tasks = []
        for t in TASKS.values():
            tasks.append({
                'id': t['id'],
                'status': t['status'],
                'ids': t['ids'],
                'done_images': t['done_images'],
                'total_images': t['total_images'],
                'albums': t['albums'],
                'current_album': t['current_album'],
                'error': t['error'],
                'start_time': t['start_time'],
            })
    tasks.sort(key=lambda x: x['start_time'], reverse=True)
    return jsonify(tasks)


@app.route('/api/task/<tid>')
def api_task(tid):
    with TASKS_LOCK:
        t = TASKS.get(tid)
        if not t:
            return jsonify({'error': 'task not found'}), 404
        data = {
            'id': t['id'],
            'status': t['status'],
            'ids': t['ids'],
            'done_images': t['done_images'],
            'total_images': t['total_images'],
            'albums': t['albums'],
            'current_album': t['current_album'],
            'logs': t['logs'][-500:],
            'error': t['error'],
            'start_time': t['start_time'],
            'cancel': t['cancel'],
        }
    return jsonify(data)


@app.route('/api/cancel/<tid>', methods=['POST'])
def api_cancel(tid):
    with TASKS_LOCK:
        t = TASKS.get(tid)
        if t and t['status'] in ('waiting', 'running'):
            t['cancel'] = True
            task_log(t, '收到取消请求，正在停止...')
    return jsonify({'ok': True})


@app.route('/api/clear_done', methods=['POST'])
def api_clear_done():
    with TASKS_LOCK:
        for tid in [k for k, v in TASKS.items() if v['status'] in ('done', 'error', 'cancelled')]:
            del TASKS[tid]
    return jsonify({'ok': True})


# ---- 搜索 ----
_SEARCH_METHODS = {
    'site': 'search_site',
    'work': 'search_work',
    'author': 'search_author',
    'tag': 'search_tag',
    'actor': 'search_actor',
}


@app.route('/api/search')
def api_search():
    q = (request.args.get('q') or '').strip()
    page = int(request.args.get('page') or 1)
    page = max(1, page)
    stype = request.args.get('type') or 'site'
    order = request.args.get('order') or 'mr'   # mr=最新
    time_ = request.args.get('time') or 'a'

    if not q:
        return jsonify({'error': '搜索词为空'}), 400
    if stype not in _SEARCH_METHODS:
        return jsonify({'error': f'不支持的搜索类型: {stype}'}), 400

    try:
        option = JmOption.default()
        client = option.new_jm_client()
        method = getattr(client, _SEARCH_METHODS[stype])
        sp = method(q, page=page, order_by=order, time=time_)
    except Exception as e:
        return jsonify({'error': f'搜索失败: {e}'}), 500

    results = []
    for aid, name, tags in sp.iter_id_title_tag():
        results.append({
            'id': aid,
            'name': name,
            'tags': list(tags or []),
            'cover': JmcomicText.get_album_cover_url(aid, size='_3x4'),
        })

    return jsonify({
        'query': q,
        'total': sp.total,
        'page': page,
        'page_count': sp.page_count,
        'results': results,
    })

# ---- 本子详情 ----
@app.route('/api/album/<aid>')
def api_album(aid):
    try:
        option = JmOption.default()
        client = option.new_jm_client()
        album = client.get_album_detail(aid)
    except Exception as e:
        return jsonify({'error': f'获取本子详情失败: {e}'}), 500

    episodes = []
    for pid, pindex, ptitle in album.episode_list:
        episodes.append({'id': pid, 'index': pindex, 'title': ptitle})

    return jsonify({
        'id': album.id,
        'name': album.name,
        'author': getattr(album, 'author', ''),
        'authors': list(getattr(album, 'authors', []) or []),
        'tags': list(getattr(album, 'tags', []) or []),
        'actors': list(getattr(album, 'actors', []) or []),
        'works': list(getattr(album, 'works', []) or []),
        'page_count': album.page_count,
        'views': getattr(album, 'views', ''),
        'likes': getattr(album, 'likes', ''),
        'pub_date': getattr(album, 'pub_date', ''),
        'update_date': getattr(album, 'update_date', ''),
        'description': getattr(album, 'description', ''),
        'episodes': episodes,
        'cover': JmcomicText.get_album_cover_url(aid),
    })


# ---- 图片防盗链代理 ----
@app.route('/api/cover')
def api_cover():
    url = request.args.get('url') or ''
    if not url.startswith(('http://', 'https://')):
        return '', 400
    try:
        postman = JmModuleConfig.new_postman(headers={
            'Referer': 'https://18comic.vip/',
            'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                           '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'),
        })
        resp = postman.get(url, timeout=20)
        if resp.status_code != 200:
            return '', resp.status_code
        content_type = resp.headers.get('content-type', '') or 'image/jpeg'
        return Response(resp.content, mimetype=content_type)
    except Exception as e:
        return jsonify({'error': str(e)}), 502


# ---------------------------------------------------------------------------
# 6. 前端页面
# ---------------------------------------------------------------------------
INDEX_HTML = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>JMComic 可视化下载器</title>
<style>
  :root {
    --bg: #0e1015;
    --card: #171a22;
    --card2: #1e222d;
    --border: #2a3040;
    --text: #e6e9ef;
    --muted: #9aa4b2;
    --accent: #5b8cff;
    --accent2: #7c5bff;
    --ok: #34d399;
    --warn: #fbbf24;
    --err: #f87171;
    --radius: 12px;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: "Segoe UI", "Microsoft YaHei", system-ui, -apple-system, sans-serif;
    font-size: 14px;
    line-height: 1.5;
  }
  a { color: var(--accent); text-decoration: none; }

  header {
    padding: 16px 24px;
    background: linear-gradient(90deg, rgba(91,140,255,.12), rgba(124,91,255,.08));
    border-bottom: 1px solid var(--border);
    display: flex; align-items: center; gap: 12px;
    position: sticky; top: 0; z-index: 50;
    backdrop-filter: blur(6px);
  }
  header h1 { font-size: 18px; font-weight: 700; }
  header .ver { color: var(--muted); font-size: 12px; }
  header .spacer { flex: 1; }

  main { max-width: 1200px; margin: 0 auto; padding: 20px 24px 60px; }
  section { margin-bottom: 22px; }
  .card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 18px 20px;
  }
  .card h2 {
    font-size: 15px; font-weight: 600; margin-bottom: 14px;
    display: flex; align-items: center; gap: 8px;
  }
  .grid { display: grid; gap: 14px; }

  label { font-size: 12px; color: var(--muted); display: block; margin-bottom: 5px; }
  input, select, textarea {
    width: 100%;
    background: var(--card2);
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text);
    padding: 9px 11px;
    font-size: 13px;
    outline: none;
  }
  input:focus, select:focus, textarea:focus { border-color: var(--accent); }
  textarea { resize: vertical; min-height: 74px; font-family: inherit; }

  .row { display: flex; gap: 12px; flex-wrap: wrap; }
  .row > * { flex: 1; min-width: 140px; }
  .row.narrow > * { flex: 0 1 auto; }

  .btn {
    border: none; border-radius: 8px; padding: 10px 18px;
    font-size: 13px; font-weight: 600; cursor: pointer;
    background: var(--card2); color: var(--text);
    border: 1px solid var(--border);
    transition: all .15s ease;
  }
  .btn:hover { border-color: var(--accent); }
  .btn.primary {
    background: linear-gradient(135deg, var(--accent), var(--accent2));
    border: none; color: #fff;
  }
  .btn.primary:hover { filter: brightness(1.1); }
  .btn.danger:hover { border-color: var(--err); color: var(--err); }
  .btn:disabled { opacity: .5; cursor: not-allowed; }
  .btn.sm { padding: 5px 10px; font-size: 12px; }

  .chk { display: flex; align-items: center; gap: 7px; }
  .chk input { width: auto; }

  /* 任务卡片 */
  .task-card { border: 1px solid var(--border); border-radius: var(--radius); padding: 14px 16px; background: var(--card); }
  .task-head { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 8px; }
  .task-id { font-family: ui-monospace, Consolas, monospace; color: var(--muted); font-size: 12px; }
  .task-status { font-size: 12px; padding: 2px 10px; border-radius: 20px; font-weight: 600; }
  .status-waiting { background: #2a3040; color: var(--muted); }
  .status-running { background: rgba(91,140,255,.15); color: var(--accent); }
  .status-done { background: rgba(52,211,153,.15); color: var(--ok); }
  .status-error { background: rgba(248,113,113,.15); color: var(--err); }
  .status-cancelled { background: rgba(251,191,36,.15); color: var(--warn); }

  .bar { height: 8px; background: var(--card2); border-radius: 6px; overflow: hidden; margin: 8px 0; }
  .bar > div { height: 100%; width: 0%; background: linear-gradient(90deg, var(--accent), var(--accent2)); transition: width .4s ease; }
  .task-meta { font-size: 12px; color: var(--muted); }

  details.logs { margin-top: 8px; }
  details.logs summary { cursor: pointer; font-size: 12px; color: var(--muted); }
  .log-box {
    margin-top: 8px; background: #0b0d12; border: 1px solid var(--border);
    border-radius: 8px; padding: 10px; max-height: 220px; overflow-y: auto;
    font-family: ui-monospace, Consolas, monospace; font-size: 12px; line-height: 1.6;
    white-space: pre-wrap; word-break: break-all;
  }

  /* 搜索 */
  .search-results { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 14px; }
  .album-card {
    background: var(--card); border: 1px solid var(--border); border-radius: var(--radius);
    overflow: hidden; cursor: pointer; transition: transform .12s ease, border-color .12s ease;
    display: flex; flex-direction: column;
  }
  .album-card:hover { transform: translateY(-2px); border-color: var(--accent); }
  .album-card .thumb {
    width: 100%; aspect-ratio: 3/4; object-fit: cover; background: var(--card2); display: block;
  }
  .album-card .body { padding: 10px 12px; flex: 1; display: flex; flex-direction: column; gap: 6px; }
  .album-card .title { font-size: 13px; font-weight: 600; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .album-card .tags { display: flex; flex-wrap: wrap; gap: 4px; }
  .tag { font-size: 11px; background: var(--card2); border: 1px solid var(--border); color: var(--muted); padding: 1px 7px; border-radius: 10px; }
  .album-card .foot { display: flex; align-items: center; justify-content: space-between; font-size: 12px; color: var(--muted); }
  .pager { display: flex; align-items: center; gap: 10px; justify-content: center; margin-top: 16px; }
  .pager .info { color: var(--muted); font-size: 13px; }

  .empty { color: var(--muted); text-align: center; padding: 30px 0; font-size: 13px; }

  /* 弹窗 */
  .modal-mask {
    position: fixed; inset: 0; background: rgba(0,0,0,.6); z-index: 100;
    display: none; align-items: center; justify-content: center; padding: 20px;
  }
  .modal-mask.show { display: flex; }
  .modal {
    background: var(--card); border: 1px solid var(--border); border-radius: 14px;
    width: 100%; max-width: 680px; max-height: 86vh; overflow-y: auto; padding: 22px;
  }
  .modal h2 { margin-bottom: 4px; }
  .modal .sub { color: var(--muted); font-size: 12px; margin-bottom: 12px; }
  .episode-row {
    display: flex; align-items: center; gap: 10px; padding: 8px 10px;
    border: 1px solid var(--border); border-radius: 8px; margin-bottom: 6px;
  }
  .episode-row .idx { color: var(--muted); font-size: 12px; min-width: 30px; }
  .episode-row .name { flex: 1; }

  footer { text-align: center; color: var(--muted); font-size: 12px; padding: 16px; }
  .toast {
    position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
    background: var(--card2); border: 1px solid var(--border); border-radius: 10px;
    padding: 10px 18px; font-size: 13px; z-index: 200; opacity: 0; transition: opacity .25s ease;
    pointer-events: none;
  }
  .toast.show { opacity: 1; }
</style>
</head>
<body>

<header>
  <h1>🚀 JMComic 可视化下载器</h1>
  <span class="ver" id="verInfo"></span>
  <span class="spacer"></span>
  <button class="btn sm" onclick="openDownloadsFolder()">📂 下载目录</button>
</header>

<main>
  <!-- 下载配置 -->
  <section>
    <div class="card">
      <h2>⬇️ 下载本子 / 章节</h2>
      <div class="grid">
        <div>
          <label>本子/章节 ID（多个用空格、逗号或换行分隔，章节以 <code>p</code> 开头，如 <code>123</code> <code>p456</code>）</label>
          <textarea id="idsInput" placeholder="例如：
123
p456
789 1000"></textarea>
        </div>
        <div class="row">
          <div>
            <label>保存目录</label>
            <input id="downloadDir" placeholder="留空 = 当前目录">
          </div>
          <div>
            <label>客户端类型</label>
            <select id="impl">
              <option value="api">移动端 api（不限IP，兼容好）</option>
              <option value="html">网页端 html（效率高，限IP）</option>
            </select>
          </div>
          <div>
            <label>图片格式</label>
            <select id="suffix">
              <option value="">原图</option>
              <option value=".png">.png</option>
              <option value=".jpg">.jpg</option>
              <option value=".webp">.webp</option>
            </select>
          </div>
        </div>
        <div class="row narrow">
          <div style="flex:0 1 160px">
            <label>图片线程数</label>
            <input id="imageThreads" type="number" value="30" min="1" max="200">
          </div>
          <div style="flex:0 1 220px">
            <label>目录规则 (dir_rule)</label>
            <input id="dirRule" value="Bd_Aid_Pindextitle">
          </div>
          <div style="flex:0 1 130px; display:flex; align-items:flex-end; padding-bottom:8px">
            <label class="chk"><input type="checkbox" id="decode" checked> 图片解密还原</label>
          </div>
        </div>
        <div class="row">
          <button class="btn primary" style="flex:0 1 160px" onclick="startDownload()">▶ 开始下载</button>
          <button class="btn" style="flex:0 1 120px" onclick="clearDone()">🗑 清理已完成</button>
        </div>
      </div>
    </div>
  </section>

  <!-- 搜索 -->
  <section>
    <div class="card">
      <h2>🔍 搜索本子</h2>
      <div class="row">
        <div style="flex:3">
          <input id="searchQ" placeholder="输入关键词（支持 +包含 -排除，如：+全彩 -人妻）" onkeydown="if(event.key==='Enter')doSearch()">
        </div>
        <div>
          <select id="searchType">
            <option value="site">站内搜索</option>
            <option value="work">作品</option>
            <option value="author">作者</option>
            <option value="tag">标签</option>
            <option value="actor">角色</option>
          </select>
        </div>
        <div>
          <select id="orderBy">
            <option value="mr">最新</option>
            <option value="mv">观看最多</option>
            <option value="mp">图片最多</option>
            <option value="tf">点赞最多</option>
          </select>
        </div>
        <button class="btn primary" onclick="doSearch()">搜索</button>
      </div>
      <div id="searchInfo" class="empty" style="margin-top:14px">输入关键词后点击「搜索」</div>
      <div id="searchResults" class="search-results" style="margin-top:14px"></div>
      <div id="pager" class="pager" style="display:none">
        <button class="btn sm" onclick="changePage(-1)">◀ 上一页</button>
        <span class="info" id="pageInfo"></span>
        <button class="btn sm" onclick="changePage(1)">下一页 ▶</button>
      </div>
    </div>
  </section>

  <!-- 任务 -->
  <section>
    <div class="card">
      <h2>📋 下载任务</h2>
      <div id="tasksArea"></div>
      <div id="tasksEmpty" class="empty">暂无任务</div>
    </div>
  </section>
</main>

<footer>JMComic-Crawler-Python · 本地可视化界面 · 请合理使用，尊重目标网站服务器</footer>

<div class="modal-mask" id="modalMask" onclick="if(event.target===this)closeModal()">
  <div class="modal" id="modalBody"></div>
</div>
<div class="toast" id="toast"></div>

<script>
const $ = (id) => document.getElementById(id);
let searchPage = 1;
let searchTotal = 0;
let lastSearch = {q:'', type:'site', order:'mr'};

function toast(msg) {
  const t = $('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.remove('show'), 2200);
}

function parseIds() {
  return $('idsInput').value
    .split(/[\s,，;；]+/)
    .map(s => s.trim())
    .filter(s => s.length > 0);
}

function getConfig() {
  return {
    download_dir: $('downloadDir').value.trim(),
    impl: $('impl').value,
    suffix: $('suffix').value,
    image_threads: parseInt($('imageThreads').value) || 30,
    dir_rule: $('dirRule').value.trim() || 'Bd_Aid_Pindextitle',
    decode: $('decode').checked,
  };
}

async function startDownload(ids) {
  const idList = ids || parseIds();
  if (idList.length === 0) { toast('请先输入要下载的 ID'); return; }
  const res = await fetch('/api/download', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ids: idList, config: getConfig()}),
  });
  const data = await res.json();
  if (data.error) { toast(data.error); return; }
  toast('已开始下载: ' + idList.join(', '));
  $('idsInput').value = '';
  refreshTasks();
}

async function cancelTask(id) {
  await fetch('/api/cancel/' + id, {method: 'POST'});
  toast('已发送取消请求');
}

async function clearDone() {
  await fetch('/api/clear_done', {method: 'POST'});
  refreshTasks();
}

function statusBadge(s) {
  const map = {
    waiting: '等待中', running: '下载中', done: '已完成',
    error: '出错', cancelled: '已取消',
  };
  return `<span class="task-status status-${s}">${map[s] || s}</span>`;
}

function progressPct(t) {
  if (!t.total_images) return 0;
  return Math.min(100, Math.round(t.done_images / t.total_images * 100));
}

async function refreshTasks() {
  let tasks;
  try { tasks = await (await fetch('/api/tasks')).json(); } catch(e) { return; }
  const area = $('tasksArea');
  $('tasksEmpty').style.display = tasks.length ? 'none' : 'block';
  area.innerHTML = tasks.map(t => {
    const pct = progressPct(t);
    const cur = t.current_album;
    const curInfo = cur ? `<div class="task-meta">正在下载: [${cur.id}] ${cur.name}</div>` : '';
    return `
      <div class="task-card">
        <div class="task-head">
          <span class="task-id">#${t.id}</span>
          ${statusBadge(t.status)}
          <span class="task-meta">开始 ${t.start_time}</span>
          <span class="task-meta">目标: ${t.ids.join(', ')}</span>
          <span class="spacer" style="flex:1"></span>
          ${t.status==='running'||t.status==='waiting' ? `<button class="btn sm danger" onclick="cancelTask('${t.id}')">⏹ 取消</button>` : ''}
        </div>
        <div class="bar"><div style="width:${pct}%"></div></div>
        <div class="task-meta">
          图片 ${t.done_images} / ${t.total_images}（${pct}%）·
          已完成本子 ${t.albums.length} 个
          ${t.error ? `· <span style="color:var(--err)">错误: ${t.error}</span>` : ''}
        </div>
        ${curInfo}
        <details class="logs" data-tid="${t.id}">
          <summary>查看日志</summary>
          <div class="log-box" data-log="1">加载中...</div>
        </details>
      </div>`;
  }).join('');
}

// 日志懒加载
document.addEventListener('toggle', async (e) => {
  if (e.target.tagName === 'DETAILS' && e.target.open && e.target.classList.contains('logs')) {
    const tid = e.target.dataset.tid;
    const box = e.target.querySelector('[data-log]');
    const data = await (await fetch('/api/task/' + tid)).json();
    box.textContent = (data.logs || []).join('\n') || '（无日志）';
    box.scrollTop = box.scrollHeight;
  }
});

// ---- 搜索 ----
async function doSearch(page) {
  const q = $('searchQ').value.trim();
  if (!q) { toast('请输入搜索关键词'); return; }
  lastSearch.q = q;
  lastSearch.type = $('searchType').value;
  lastSearch.order = $('orderBy').value;
  searchPage = page || 1;
  $('searchInfo').textContent = '搜索中...';
  const params = new URLSearchParams({
    q: q, page: searchPage,
    type: lastSearch.type, order: lastSearch.order,
  });
  let data;
  try {
    data = await (await fetch('/api/search?' + params)).json();
  } catch(e) { $('searchInfo').textContent = '搜索请求失败'; return; }
  if (data.error) { $('searchInfo').textContent = data.error; return; }
  searchTotal = data.total;
  $('searchInfo').textContent = `找到 ${data.total} 个结果`;
  $('pager').style.display = 'flex';
  $('pageInfo').textContent = `第 ${data.page} / ${data.page_count} 页`;
  const area = $('searchResults');
  if (!data.results.length) {
    area.innerHTML = '<div class="empty">无结果</div>';
    return;
  }
  area.innerHTML = data.results.map(r => `
    <div class="album-card" onclick="showAlbum('${r.id}')">
      <img class="thumb" loading="lazy"
           src="/api/cover?url=${encodeURIComponent(r.cover)}"
           onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=&quot;http://www.w3.org/2000/svg&quot; width=&quot;200&quot; height=&quot;267&quot;><rect width=&quot;100%&quot; height=&quot;100%&quot; fill=&quot;%231e222d&quot;/></svg>'">
      <div class="body">
        <div class="title">${r.name}</div>
        <div class="tags">${(r.tags||[]).slice(0,4).map(x=>`<span class="tag">${x}</span>`).join('')}</div>
        <div class="foot"><span>JM${r.id}</span><button class="btn sm" onclick="event.stopPropagation();startDownload(['${r.id}'])">⬇ 下载</button></div>
      </div>
    </div>`).join('');
}

function changePage(delta) {
  const nc = searchPage + delta;
  if (nc < 1 || nc > Math.ceil(searchTotal / 80)) return;
  doSearch(nc);
  window.scrollTo({top: $('searchQ').getBoundingClientRect().top + window.scrollY - 120, behavior: 'smooth'});
}

// ---- 本子详情 ----
async function showAlbum(aid) {
  $('modalMask').classList.add('show');
  $('modalBody').innerHTML = '<div class="empty">加载中...</div>';
  let data;
  try {
    data = await (await fetch('/api/album/' + aid)).json();
  } catch(e) { $('modalBody').innerHTML = '<div class="empty">加载失败</div>'; return; }
  if (data.error) { $('modalBody').innerHTML = `<div class="empty">${data.error}</div>`; return; }

  $('modalBody').innerHTML = `
    <h2>${data.name}</h2>
    <div class="sub">JM${data.id} · 作者: ${data.authors.join(', ') || '未知'} · ${data.page_count} 页 · 观看 ${data.views} · 喜欢 ${data.likes}</div>
    ${data.tags.length ? `<div class="tags" style="margin-bottom:10px">${data.tags.map(x=>`<span class="tag">${x}</span>`).join('')}</div>` : ''}
    <div style="margin-bottom:14px; font-size:12px; color:var(--muted); max-height:80px; overflow:auto">
      ${data.description || '（无简介）'}
    </div>
    <button class="btn primary sm" style="margin-bottom:12px" onclick="startDownload(['${data.id}'])">⬇ 下载整个本子</button>
    <div style="font-size:13px; font-weight:600; margin-bottom:8px">章节列表（${data.episodes.length}）</div>
    ${data.episodes.map(ep => `
      <div class="episode-row">
        <span class="idx">第${ep.index}话</span>
        <span class="name">${ep.title || '（未命名）'}</span>
        <button class="btn sm" onclick="startDownload(['p${ep.id}'])">⬇ 章节</button>
      </div>`).join('')}
  `;
}

function closeModal() {
  $('modalMask').classList.remove('show');
}

function openDownloadsFolder() {
  fetch('/api/open_dir').then(r=>r.json()).catch(()=>{});
}

// ---- 初始化 ----
(async function init() {
  fetch('/api/health').then(r=>r.json()).then(d => {
    $('verInfo').textContent = 'jmcomic ' + (d.jmcomic_version || '?');
  });
  refreshTasks();
  setInterval(refreshTasks, 1200);
  // 恢复上次的配置
  try {
    const saved = JSON.parse(localStorage.getItem('jm_gui_cfg') || '{}');
    if (saved.downloadDir) $('downloadDir').value = saved.downloadDir;
    if (saved.impl) $('impl').value = saved.impl;
    if (saved.suffix) $('suffix').value = saved.suffix;
    if (saved.dirRule) $('dirRule').value = saved.dirRule;
    if (saved.imageThreads) $('imageThreads').value = saved.imageThreads;
    if (saved.decode !== undefined) $('decode').checked = saved.decode;
  } catch(e) {}
  // 保存配置
  setInterval(() => {
    localStorage.setItem('jm_gui_cfg', JSON.stringify({
      downloadDir: $('downloadDir').value, impl: $('impl').value,
      suffix: $('suffix').value, dirRule: $('dirRule').value,
      imageThreads: $('imageThreads').value, decode: $('decode').checked,
    }));
  }, 2000);
})();
</script>
</body>
</html>
'''


@app.route('/api/open_dir')
def api_open_dir():
    import subprocess
    if sys.platform.startswith('win'):
        os.startfile(os.getcwd())
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', os.getcwd()])
    else:
        subprocess.Popen(['xdg-open', os.getcwd()])
    return jsonify({'ok': True})


# ---------------------------------------------------------------------------
# 7. 启动
# ---------------------------------------------------------------------------
def main():
    port = 5000
    print('=' * 56)
    print('  🚀 JMComic 可视化下载器已启动')
    print(f'  使用本库版本: jmcomic {getattr(jmcomic, "__version__", "unknown")}')
    print(f'  请在浏览器打开: http://127.0.0.1:{port}')
    print('  按 Ctrl+C 退出')
    print('=' * 56)
    if os.environ.get('JM_GUI_NO_BROWSER') != '1':
        try:
            import webbrowser
            threading.Timer(1.2, lambda: webbrowser.open(f'http://127.0.0.1:{port}')).start()
        except Exception:
            pass
    app.run(host='127.0.0.1', port=port, debug=False, threaded=True)


if __name__ == '__main__':
    main()
