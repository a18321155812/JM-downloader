# -*- coding: utf-8 -*-
"""
JMComic 桌面下载器 (PyQt5)
===========================

基于 jmcomic 库的独立桌面软件，功能包括：

  * 批量下载本子(Album) / 章节(Photo)
  * 实时下载进度（进度条 + 日志）
  * 搜索本子（站内 / 作品 / 作者 / 标签 / 角色）
  * 查看本子详情与章节列表，可单独下载章节
  * 封面图加载

运行方式:
    python jm_gui_desktop.py

打包成独立 exe（推荐）:
    pip install pyinstaller
    pyinstaller -F -w -n JMComicDownloader jm_gui_desktop.py

依赖:
    PyQt5   (pip install PyQt5)

说明:
    脚本会自动优先加载本目录 src/ 下的 jmcomic 源码；
    若不存在则使用已安装的 jmcomic 包。
"""

import os
import sys
import time
import threading
from typing import List, Dict, Optional, Tuple

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
from jmcomic.jm_toolkit import JmcomicText, JmImageTool
from PIL import Image

# 桌面应用自带日志面板，这里关闭 jmcomic 默认的控制台日志（避免刷屏、拖慢性能）
JmModuleConfig.disable_jm_log()

# PyQt5 导入
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QLineEdit, QComboBox, QSpinBox, QCheckBox, QTextEdit,
    QScrollArea, QFrame, QTabWidget, QProgressBar, QFileDialog, QDialog,
    QListWidget, QListWidgetItem, QPlainTextEdit, QMessageBox, QSizePolicy,
    QSplitter,
)
from PyQt5.QtCore import Qt, QThread, QRunnable, QThreadPool, pyqtSignal, QObject, QTimer, QSize
from PyQt5.QtGui import QPixmap, QImage, QFont, QIcon, QColor, QPainter, QBrush

# ---------------------------------------------------------------------------
# 1. 后台任务状态管理
# ---------------------------------------------------------------------------
TASKS: Dict[str, dict] = {}
TASKS_LOCK = threading.Lock()


def now_time() -> str:
    return time.strftime('%H:%M:%S')


def new_task_id() -> str:
    import uuid
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
        self._photo_mode = False

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

    base_dir = (config.get('download_dir') or '').strip() or os.getcwd()
    rule = (config.get('dir_rule') or '').strip() or 'Bd_Aid_Pindextitle'
    option.dir_rule = DirRule(rule, base_dir=base_dir,
                              normalize_zh=config.get('normalize_zh') or None)

    impl = config.get('impl') or 'api'
    if impl in ('api', 'html'):
        option.client.impl = impl

    suffix = (config.get('suffix') or '').strip()
    if suffix:
        if not suffix.startswith('.'):
            suffix = '.' + suffix
        option.download.image.suffix = suffix

    decode = config.get('decode', True)
    option.download.image.decode = bool(decode)

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
                dler = ProgressDownloader(option, task)
                if raw[0] in 'ap':
                    prefix, jid = raw[0], raw[1:]
                    if not jid.isdigit():
                        task_log(task, f'无效ID: {raw}')
                        continue
                    if prefix == 'p':
                        task_log(task, f'➡️ 下载章节 [{jid}]')
                        dler.download_photo(jid)
                    else:
                        task_log(task, f'➡️ 下载本子 [{jid}]')
                        dler.download_album(jid)
                elif raw.isdigit():
                    task_log(task, f'➡️ 下载本子 [{raw}]')
                    dler.download_album(raw)
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
# 5. 搜索 / 图片下载 辅助
# ---------------------------------------------------------------------------
_SEARCH_METHODS = {
    'site': 'search_site',
    'work': 'search_work',
    'author': 'search_author',
    'tag': 'search_tag',
    'actor': 'search_actor',
}


def do_search(q, stype, order, page):
    """在后台线程执行搜索，返回 (results, total, page_count)。"""
    option = JmOption.default()
    client = option.new_jm_client()
    method = getattr(client, _SEARCH_METHODS.get(stype, 'search_site'))
    sp = method(q, page=page, order_by=order, time='a')
    results = []
    for aid, name, tags in sp.iter_id_title_tag():
        results.append({
            'id': aid,
            'name': name,
            'tags': list(tags or []),
            'cover': JmcomicText.get_album_cover_url(aid, size='_3x4'),
        })
    return results, int(sp.total), int(sp.page_count)


def get_album_detail(aid):
    """获取本子详情，返回 dict。"""
    option = JmOption.default()
    client = option.new_jm_client()
    album = client.get_album_detail(aid)
    episodes = []
    for pid, pindex, ptitle in album.episode_list:
        episodes.append({'id': pid, 'index': pindex, 'title': ptitle})
    return {
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
    }


def download_image_bytes(url, timeout=20) -> Optional[bytes]:
    """下载图片字节（带防盗链 referer）。"""
    try:
        postman = JmModuleConfig.new_postman(headers={
            'Referer': 'https://18comic.vip/',
            'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                           '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'),
        })
        resp = postman.get(url, timeout=timeout)
        if resp.status_code == 200 and resp.content:
            return resp.content
    except Exception:
        pass
    return None


def _decode_image_to_bytes(img, num) -> bytes:
    """把混淆图片按分割数 num 还原，输出为 PNG 字节。

    逻辑与 jmcomic 的 JmImageTool.decode_and_save 一致，但把结果写到内存，
    避免因 BytesIO 没有扩展名导致 PIL 无法推断格式的问题。
    """
    from io import BytesIO
    buf = BytesIO()
    if num == 0:
        # 无需分割，直接保存
        img.save(buf, format='PNG')
        return buf.getvalue()

    import math
    w, h = img.size
    img_decode = Image.new("RGB", (w, h))
    over = h % num
    for i in range(num):
        move = math.floor(h / num)
        y_src = h - (move * (i + 1)) - over
        y_dst = move * i
        if i == 0:
            move += over
        else:
            y_dst += over
        img_decode.paste(
            img.crop((0, y_src, w, y_src + move)),
            (0, y_dst, w, y_dst + move),
        )
    img_decode.save(buf, format='PNG')
    return buf.getvalue()


def get_decoded_image_bytes(client, img_url, scramble_id) -> Optional[bytes]:
    """获取并解密单张 JM 图片，返回可直接显示的 PNG 字节。

    JM 的图片是经过切片混淆的，需要用 scramble_id 还原后才能正常查看。
    """
    try:
        resp = client.get_jm_image(img_url)
        resp.require_success()
        content = resp.content
        scramble_id = int(scramble_id) if scramble_id else 0
        if not scramble_id:
            return content
        img = JmImageTool.open_image(content)
        num = JmImageTool.get_num_by_url(scramble_id, img_url)
        return _decode_image_to_bytes(img, num)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 6. 全局信号（后台线程 -> UI 线程）
# ---------------------------------------------------------------------------
class AppSignals(QObject):
    task_updated = pyqtSignal(str)            # task_id，任务有变化
    search_done = pyqtSignal(list, int, int)  # results, total, page_count
    search_error = pyqtSignal(str)
    detail_done = pyqtSignal(dict)            # {id: ..., ...}
    detail_error = pyqtSignal(str, str)       # aid, msg
    cover_loaded = pyqtSignal(str, bytes)     # album_id, data

    # ---- 漫画浏览 ----
    viewer_chapters = pyqtSignal(str, list)        # album_id, [(photo_id, index, title)]
    viewer_photo_images = pyqtSignal(str, int, list)  # photo_id, total, [image dict]
    viewer_page_ready = pyqtSignal(str, int, bytes)   # photo_id, index, png bytes
    viewer_failed = pyqtSignal(str, str)              # ctx, msg


signals = AppSignals()


def search_worker(q, stype, order, page):
    try:
        results, total, page_count = do_search(q, stype, order, page)
        signals.search_done.emit(results, total, page_count)
    except Exception as e:
        signals.search_error.emit(str(e))


def detail_worker(aid):
    try:
        signals.detail_done.emit(get_album_detail(aid))
    except Exception as e:
        signals.detail_error.emit(str(aid), str(e))


# ---- 漫画浏览后台 worker ----

def viewer_load_chapters(album_id):
    """获取本子的章节列表。"""
    ctx = f'album-{album_id}'
    try:
        option = JmOption.default()
        client = option.new_jm_client()
        album = client.get_album_detail(album_id)
        episodes = []
        for pid, pindex, ptitle in album.episode_list:
            episodes.append((pid, pindex, ptitle))
        signals.viewer_chapters.emit(str(album_id), episodes)
    except Exception as e:
        signals.viewer_failed.emit(ctx, str(e))


def viewer_load_photo_images(photo_id):
    """获取章节的图片列表。"""
    ctx = f'photo-{photo_id}'
    try:
        option = JmOption.default()
        client = option.new_jm_client()
        photo = client.get_photo_detail(photo_id, fetch_album=False, fetch_scramble_id=True)
        images = []
        for idx, image in enumerate(photo, start=1):
            images.append({
                'index': idx,
                'url': image.download_url,
                'scramble_id': image.scramble_id,
            })
        signals.viewer_photo_images.emit(str(photo_id), len(images), images)
    except Exception as e:
        signals.viewer_failed.emit(ctx, str(e))


def viewer_load_page(photo_id, image_info):
    """获取并解密某一张图片。"""
    ctx = f'photo-{photo_id}'
    try:
        option = JmOption.default()
        client = option.new_jm_client()
        data = get_decoded_image_bytes(client, image_info['url'], image_info['scramble_id'])
        if data:
            signals.viewer_page_ready.emit(str(photo_id), image_info['index'], data)
        else:
            signals.viewer_failed.emit(ctx, f'第 {image_info["index"]} 张图片获取失败')
    except Exception as e:
        signals.viewer_failed.emit(ctx, str(e))


class CoverTask(QRunnable):
    """异步加载封面图"""

    def __init__(self, album_id, url):
        super().__init__()
        self.album_id = album_id
        self.url = url

    def run(self):
        data = download_image_bytes(self.url)
        if data:
            signals.cover_loaded.emit(self.album_id, data)


# ---------------------------------------------------------------------------
# 7. 任务卡片
# ---------------------------------------------------------------------------
class TaskCard(QFrame):
    def __init__(self, task, parent=None):
        super().__init__(parent)
        self.task_id = task['id']
        self.setObjectName('taskCard')
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)

        # 标题行
        head = QHBoxLayout()
        self.lb_title = QLabel(f"#{self.task_id}")
        self.lb_title.setObjectName('taskId')
        self.lb_status = QLabel('等待中')
        self.lb_status.setObjectName('stWaiting')
        self.lb_time = QLabel('')
        self.lb_time.setObjectName('muted')
        head.addWidget(self.lb_title)
        head.addWidget(self.lb_status)
        head.addWidget(self.lb_time)
        head.addStretch(1)
        self.btn_cancel = QPushButton('⏹ 取消')
        self.btn_cancel.setObjectName('dangerBtn')
        self.btn_cancel.setFixedHeight(26)
        self.btn_cancel.clicked.connect(self.cancel_clicked)
        head.addWidget(self.btn_cancel)
        lay.addLayout(head)

        # 目标
        self.lb_target = QLabel('')
        self.lb_target.setObjectName('muted')
        lay.addWidget(self.lb_target)

        # 进度条
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setFixedHeight(8)
        self.bar.setTextVisible(False)
        self.bar.setObjectName('progress')
        lay.addWidget(self.bar)

        # 元信息
        self.lb_meta = QLabel('')
        self.lb_meta.setObjectName('muted')
        lay.addWidget(self.lb_meta)

        # 当前本子
        self.lb_current = QLabel('')
        self.lb_current.setObjectName('muted')
        self.lb_current.setWordWrap(True)
        lay.addWidget(self.lb_current)

        # 日志区
        self.txt_log = QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumHeight(140)
        self.txt_log.setObjectName('logBox')
        self.txt_log.hide()
        lay.addWidget(self.txt_log)

        self.btn_toggle_log = QPushButton('📄 日志')
        self.btn_toggle_log.setObjectName('ghostBtn')
        self.btn_toggle_log.setFixedHeight(24)
        self.btn_toggle_log.clicked.connect(self.toggle_log)
        lay.addWidget(self.btn_toggle_log, alignment=Qt.AlignRight)

        self._log_visible = False

    def cancel_clicked(self):
        with TASKS_LOCK:
            t = TASKS.get(self.task_id)
            if t and t['status'] in ('waiting', 'running'):
                t['cancel'] = True
                task_log(t, '收到取消请求，正在停止...')

    def toggle_log(self):
        self._log_visible = not self._log_visible
        self.txt_log.setVisible(self._log_visible)
        self.btn_toggle_log.setText('📄 收起日志' if self._log_visible else '📄 日志')

    def refresh(self, task):
        """用任务数据更新界面（必须在主线程调用）。"""
        status = task['status']
        # 状态
        st_map = {
            'waiting': ('等待中', 'stWaiting'),
            'running': ('下载中', 'stRunning'),
            'done': ('已完成', 'stDone'),
            'error': ('出错', 'stError'),
            'cancelled': ('已取消', 'stCancelled'),
        }
        label, obj = st_map.get(status, (status, 'stWaiting'))
        self.lb_status.setText(label)
        self.lb_status.setObjectName(obj)
        self.lb_status.style().unpolish(self.lb_status)
        self.lb_status.style().polish(self.lb_status)
        self.lb_time.setText(f"开始 {task['start_time']}")
        self.lb_target.setText(f"目标: {', '.join(task['ids'])}")

        # 进度
        total = task['total_images'] or 0
        done = task['done_images']
        pct = int(done / total * 100) if total else 0
        self.bar.setValue(pct)
        meta = f"图片 {done} / {total}（{pct}%）· 已完成本子 {len(task['albums'])} 个"
        if task['error']:
            meta += f" · 错误: {task['error']}"
        self.lb_meta.setText(meta)

        # 当前本子
        cur = task['current_album']
        if cur:
            self.lb_current.setText(f"🔄 正在下载: [{cur['id']}] {cur['name']}")
        else:
            self.lb_current.setText('')

        # 取消按钮状态
        self.btn_cancel.setEnabled(status in ('waiting', 'running'))
        self.btn_cancel.setText('⏹ 取消' if status in ('waiting', 'running') else '已结束')

        # 日志
        self.txt_log.setPlainText('\n'.join(task['logs'][-400:]))
        sb = self.txt_log.verticalScrollBar()
        sb.setValue(sb.maximum())


# ---------------------------------------------------------------------------
# 8. 搜索条目
# ---------------------------------------------------------------------------
class SearchItemWidget(QWidget):
    download_requested = pyqtSignal(list)
    view_requested = pyqtSignal(str)   # album_id

    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.item = item
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(12)

        self.lb_cover = QLabel()
        self.lb_cover.setFixedSize(56, 75)
        self.lb_cover.setAlignment(Qt.AlignCenter)
        self.lb_cover.setText('…')
        self.lb_cover.setObjectName('coverPlaceholder')
        lay.addWidget(self.lb_cover)

        right = QVBoxLayout()
        right.setSpacing(4)
        self.lb_title = QLabel(item['name'])
        self.lb_title.setObjectName('searchTitle')
        self.lb_title.setWordWrap(True)
        right.addWidget(self.lb_title)

        self.lb_tags = QLabel(' '.join('#' + t for t in item['tags'][:6]))
        self.lb_tags.setObjectName('muted')
        right.addWidget(self.lb_tags)

        bottom = QHBoxLayout()
        self.lb_id = QLabel(f"JM{item['id']}")
        self.lb_id.setObjectName('muted')
        bottom.addWidget(self.lb_id)
        bottom.addStretch(1)
        btn_view = QPushButton('👁 浏览')
        btn_view.setObjectName('ghostBtn')
        btn_view.setFixedHeight(26)
        btn_view.clicked.connect(lambda: self.view_requested.emit(str(self.item['id'])))
        bottom.addWidget(btn_view)
        btn = QPushButton('⬇ 下载')
        btn.setObjectName('primaryBtn')
        btn.setFixedHeight(26)
        btn.clicked.connect(lambda: self.download_requested.emit([str(self.item['id'])]))
        bottom.addWidget(btn)
        right.addLayout(bottom)

        lay.addLayout(right, 1)

    def set_cover(self, data):
        """主线程回调：设置封面图。"""
        pix = pixmap_from_bytes(data)
        if pix and not pix.isNull():
            pix = pix.scaled(self.lb_cover.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.lb_cover.setPixmap(pix)


def pixmap_from_bytes(data):
    img = QImage.fromData(data)
    if img.isNull():
        return None
    return QPixmap.fromImage(img)


# ---------------------------------------------------------------------------
# 9. 本子详情对话框
# ---------------------------------------------------------------------------
class AlbumDetailDialog(QDialog):
    download_requested = pyqtSignal(list)
    view_requested = pyqtSignal(str)   # photo_id

    def __init__(self, aid, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'JM{aid} 详情')
        self.resize(620, 520)
        self.setObjectName('detailDialog')

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 18)

        self.lb_title = QLabel('加载中...')
        self.lb_title.setObjectName('detailTitle')
        self.lb_title.setWordWrap(True)
        lay.addWidget(self.lb_title)

        self.lb_meta = QLabel('')
        self.lb_meta.setObjectName('muted')
        self.lb_meta.setWordWrap(True)
        lay.addWidget(self.lb_meta)

        self.lb_tags = QLabel('')
        self.lb_tags.setObjectName('muted')
        self.lb_tags.setWordWrap(True)
        lay.addWidget(self.lb_tags)

        self.lb_desc = QLabel('')
        self.lb_desc.setObjectName('muted')
        self.lb_desc.setWordWrap(True)
        self.lb_desc.setMaximumHeight(80)
        lay.addWidget(self.lb_desc)

        btn_all = QPushButton('⬇ 下载整个本子')
        btn_all.setObjectName('primaryBtn')
        btn_all.clicked.connect(lambda: self.download_requested.emit([aid]))
        lay.addWidget(btn_all, alignment=Qt.AlignLeft)

        lay.addWidget(QLabel('章节列表:'))
        self.list_episodes = QListWidget()
        lay.addWidget(self.list_episodes, 1)

        self.aid = str(aid)
        signals.detail_done.connect(self.on_detail)
        signals.detail_error.connect(self.on_error)

        threading.Thread(target=detail_worker, args=(self.aid,), daemon=True).start()

    def closeEvent(self, event):
        # 断开信号，避免连接泄漏
        try:
            signals.detail_done.disconnect(self.on_detail)
            signals.detail_error.disconnect(self.on_error)
        except (TypeError, RuntimeError):
            pass
        super().closeEvent(event)

    def on_detail(self, info):
        if str(info['id']) != self.aid:
            return
        self.lb_title.setText(info['name'])
        self.lb_meta.setText(
            f"JM{info['id']} · 作者: {', '.join(info['authors']) or '未知'} · "
            f"{info['page_count']} 页 · 观看 {info['views']} · 喜欢 {info['likes']}"
        )
        self.lb_tags.setText(' '.join('#' + t for t in info['tags']))
        self.lb_desc.setText(info['description'] or '（无简介）')
        self.list_episodes.clear()
        for ep in info['episodes']:
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(8, 4, 8, 4)
            lb = QLabel(f"第{ep['index']}话  {ep['title']}")
            lb.setWordWrap(True)
            h.addWidget(lb, 1)
            b_view = QPushButton('👁')
            b_view.setObjectName('ghostBtn')
            b_view.setFixedWidth(36)
            b_view.setToolTip('浏览该章节')
            b_view.clicked.connect(lambda _, pid=ep['id']: self.view_requested.emit(str(pid)))
            h.addWidget(b_view)
            b = QPushButton('⬇')
            b.setObjectName('primaryBtn')
            b.setFixedWidth(40)
            b.setToolTip('下载该章节')
            b.clicked.connect(lambda _, pid=ep['id']: self.download_requested.emit([f'p{pid}']))
            h.addWidget(b)
            item = QListWidgetItem()
            item.setSizeHint(w.sizeHint())
            self.list_episodes.addItem(item)
            self.list_episodes.setItemWidget(item, w)

    def on_error(self, aid, msg):
        if str(aid) != self.aid:
            return
        self.lb_title.setText(f'加载失败: {msg}')


# ---------------------------------------------------------------------------
# 9.5 内置漫画浏览器
# ---------------------------------------------------------------------------
class ComicViewerDialog(QDialog):
    """内置漫画浏览器：选择章节，翻页查看解密还原后的图片。"""

    def __init__(self, album_id=None, photo_id=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('漫画浏览')
        self.resize(820, 660)
        self.setMinimumSize(520, 420)
        self.setObjectName('viewerDialog')

        self.album_id = str(album_id) if album_id else None
        self.photo_id = str(photo_id) if photo_id else None
        self.photo_images: List[dict] = []   # 当前章节图片列表
        self.current_index = 0               # 1-based
        self._loading = False
        self._current_photo_id = None
        self._current_pix = None

        # ---- UI ----
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        # 顶部：章节选择
        top = QHBoxLayout()
        self.lb_ctx = QLabel('')
        self.lb_ctx.setObjectName('muted')
        top.addWidget(self.lb_ctx)
        self.cb_chapter = QComboBox()
        self.cb_chapter.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.cb_chapter.currentIndexChanged.connect(self._on_chapter_changed)
        top.addWidget(self.cb_chapter, 1)
        lay.addLayout(top)

        # 图片区（滚动区，支持原始大小查看）
        self._fit_to_window = True
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setObjectName('viewerScroll')
        self.lb_image = QLabel('加载中...')
        self.lb_image.setAlignment(Qt.AlignCenter)
        self.lb_image.setObjectName('viewerImage')
        self.lb_image.setMinimumSize(400, 300)
        self.scroll_area.setWidget(self.lb_image)
        lay.addWidget(self.scroll_area, 1)

        # 底部控制
        bottom = QHBoxLayout()
        self.btn_prev = QPushButton('◀ 上一页')
        self.btn_prev.setObjectName('ghostBtn')
        self.btn_prev.clicked.connect(lambda: self.goto(self.current_index - 1))
        self.btn_next = QPushButton('下一页 ▶')
        self.btn_next.setObjectName('primaryBtn')
        self.btn_next.clicked.connect(lambda: self.goto(self.current_index + 1))
        self.btn_zoom = QPushButton('⤢ 适应窗口')
        self.btn_zoom.setObjectName('ghostBtn')
        self.btn_zoom.setToolTip('切换 适应窗口 / 100% 原始大小')
        self.btn_zoom.clicked.connect(self.toggle_zoom)
        self.lb_page = QLabel('')
        self.lb_page.setObjectName('muted')
        self.lb_page.setAlignment(Qt.AlignCenter)
        self.btn_close = QPushButton('✕ 关闭')
        self.btn_close.setObjectName('dangerBtn')
        self.btn_close.clicked.connect(self.close)
        bottom.addWidget(self.btn_prev)
        bottom.addWidget(self.lb_page, 1)
        bottom.addWidget(self.btn_zoom)
        bottom.addWidget(self.btn_next)
        bottom.addWidget(self.btn_close)
        lay.addLayout(bottom)

        # 信号
        signals.viewer_chapters.connect(self._on_chapters)
        signals.viewer_photo_images.connect(self._on_photo_images)
        signals.viewer_page_ready.connect(self._on_page_ready)
        signals.viewer_failed.connect(self._on_viewer_failed)

        # 启动
        if self.album_id and not self.photo_id:
            self.lb_ctx.setText(f'本子 JM{album_id}')
            threading.Thread(target=viewer_load_chapters, args=(album_id,), daemon=True).start()
        elif self.photo_id:
            self.lb_ctx.setText(f'章节 {photo_id}')
            self.cb_chapter.addItem(f'章节 {photo_id}', self.photo_id)
            self._load_photo(self.photo_id)

    def closeEvent(self, event):
        try:
            signals.viewer_chapters.disconnect(self._on_chapters)
            signals.viewer_photo_images.disconnect(self._on_photo_images)
            signals.viewer_page_ready.disconnect(self._on_page_ready)
            signals.viewer_failed.disconnect(self._on_viewer_failed)
        except (TypeError, RuntimeError):
            pass
        super().closeEvent(event)

    # ---- 信号回调 ----
    def _on_chapters(self, album_id, episodes):
        if str(album_id) != str(self.album_id):
            return
        self.cb_chapter.blockSignals(True)
        self.cb_chapter.clear()
        for pid, pindex, ptitle in episodes:
            name = f'第{pindex}话  {ptitle}' if ptitle else f'第{pindex}话'
            self.cb_chapter.addItem(name, str(pid))
        self.cb_chapter.blockSignals(False)
        if self.cb_chapter.count() > 0:
            self._load_photo(self.cb_chapter.currentData())
        else:
            self._show_message('本子没有可浏览的章节')

    def _on_chapter_changed(self, index):
        pid = self.cb_chapter.currentData()
        if pid:
            self._load_photo(pid)

    def _on_photo_images(self, photo_id, total, images):
        if str(photo_id) != str(self._current_photo_id):
            return
        self.photo_images = images
        self.current_index = 1
        self.lb_page.setText(f'1 / {total}')
        self._load_current_page()

    def _on_page_ready(self, photo_id, index, data):
        if str(photo_id) != str(self._current_photo_id):
            return
        if index != self.current_index:
            return
        self._loading = False
        pix = QPixmap()
        if pix.loadFromData(data):
            self._current_pix = pix
            self._update_display()
            self.lb_page.setText(f'{index} / {len(self.photo_images)}')
        else:
            self._show_message(f'第 {index} 页加载失败')

    def _on_viewer_failed(self, ctx, msg):
        if ctx == f'photo-{self._current_photo_id}' and self._loading:
            self._loading = False
            self._show_message(f'加载失败: {msg}')

    # ---- 操作 ----
    def _load_photo(self, photo_id):
        self._current_photo_id = str(photo_id)
        self.photo_images = []
        self.current_index = 0
        self._loading = True
        self._current_pix = None
        self.lb_image.setText('加载章节图片列表...')
        self.lb_page.setText('')
        threading.Thread(target=viewer_load_photo_images, args=(photo_id,), daemon=True).start()

    def _load_current_page(self):
        if not self.photo_images:
            return
        info = self.photo_images[self.current_index - 1]
        self._loading = True
        self.lb_image.setText(f'加载第 {self.current_index} 页...')
        threading.Thread(target=viewer_load_page, args=(self._current_photo_id, info), daemon=True).start()

    def goto(self, index):
        if not self.photo_images:
            return
        index = max(1, min(len(self.photo_images), index))
        if index == self.current_index:
            return
        self.current_index = index
        self.lb_page.setText(f'{index} / {len(self.photo_images)}')
        self._load_current_page()

    def _update_display(self):
        if self._current_pix is None:
            return
        avail = self.lb_image.size()
        scaled = self._current_pix.scaled(avail, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.lb_image.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._current_pix is not None:
            self._update_display()

    def _show_message(self, msg):
        self._loading = False
        self.lb_image.setPixmap(QPixmap())
        self.lb_image.setText(msg)


# ---------------------------------------------------------------------------
# 10. 主窗口
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('JMComic 桌面下载器')
        self.resize(1240, 800)
        self.setMinimumSize(980, 640)

        self.task_cards: Dict[str, TaskCard] = {}
        self.search_items: Dict[str, SearchItemWidget] = {}
        self.search_page = 1
        self.search_total = 0
        self.search_page_count = 1
        self.search_results_cache: List[dict] = []
        self.cover_pool = QThreadPool(self)
        self.cover_pool.setMaxThreadCount(6)

        self._build_ui()

        # 定时刷新
        self.timer = QTimer(self)
        self.timer.setInterval(600)
        self.timer.timeout.connect(self.refresh_tasks)
        self.timer.start()

        signals.search_done.connect(self.on_search_done)
        signals.search_error.connect(self.on_search_error)
        signals.cover_loaded.connect(self.on_cover_loaded)

        self.statusBar().showMessage('就绪')

    def on_cover_loaded(self, album_id, data):
        """封面下载完成，分发到对应的搜索条目。"""
        w = self.search_items.get(str(album_id))
        if w is not None:
            w.set_cover(data)

    # ---- UI 构建 ----
    def _build_ui(self):
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        # 左：控制面板
        left = self._build_control_panel()
        left.setMinimumWidth(330)
        left.setMaximumWidth(420)
        splitter.addWidget(left)

        # 右：标签页
        right = self._build_tabs()
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([360, 880])

        self.setCentralWidget(splitter)

    def _build_control_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName('sidePanel')
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setObjectName('sideScroll')
        outer.addWidget(scroll)

        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        title = QLabel('⬇ 下载本子 / 章节')
        title.setObjectName('detailTitle')
        lay.addWidget(title)

        self.txt_ids = QTextEdit()
        self.txt_ids.setPlaceholderText('输入本子/章节 ID，多个用空格、逗号或换行分隔。\n章节以 p 开头，如：p123')
        self.txt_ids.setFixedHeight(96)
        self.txt_ids.setObjectName('idsBox')
        lay.addWidget(self.txt_ids)

        # 保存目录
        lay.addWidget(self._section('保存目录'))
        dirrow = QHBoxLayout()
        self.ed_dir = QLineEdit(os.getcwd())
        self.ed_dir.setObjectName('dirInput')
        dirrow.addWidget(self.ed_dir, 1)
        btn_dir = QPushButton('…')
        btn_dir.setFixedWidth(34)
        btn_dir.clicked.connect(self._choose_dir)
        dirrow.addWidget(btn_dir)
        lay.addLayout(dirrow)

        # 客户端类型
        lay.addWidget(self._section('客户端类型'))
        self.cb_impl = QComboBox()
        self.cb_impl.addItem('移动端 api（不限IP，兼容好）', 'api')
        self.cb_impl.addItem('网页端 html（效率高，限IP）', 'html')
        lay.addWidget(self.cb_impl)

        # 图片格式 + 线程
        lay.addWidget(self._section('图片设置'))
        row = QHBoxLayout()
        self.cb_suffix = QComboBox()
        self.cb_suffix.addItem('原图', '')
        self.cb_suffix.addItem('.png', '.png')
        self.cb_suffix.addItem('.jpg', '.jpg')
        self.cb_suffix.addItem('.webp', '.webp')
        row.addWidget(self.cb_suffix, 1)
        self.sp_threads = QSpinBox()
        self.sp_threads.setRange(1, 200)
        self.sp_threads.setValue(30)
        self.sp_threads.setSuffix(' 线程')
        row.addWidget(self.sp_threads, 1)
        lay.addLayout(row)

        # 目录规则
        lay.addWidget(self._section('保存目录规则 (dir_rule)'))
        self.ed_rule = QLineEdit('Bd_Aid_Pindextitle')
        lay.addWidget(self.ed_rule)

        # 解密开关
        self.chk_decode = QCheckBox('图片解密还原（保持勾选）')
        self.chk_decode.setChecked(True)
        lay.addWidget(self.chk_decode)

        # 按钮
        self.btn_start = QPushButton('▶  开始下载')
        self.btn_start.setObjectName('primaryBig')
        self.btn_start.setFixedHeight(44)
        self.btn_start.clicked.connect(self.start_download)
        lay.addWidget(self.btn_start)

        btnrow = QHBoxLayout()
        self.btn_stop = QPushButton('⏹ 停止所有')
        self.btn_stop.setObjectName('dangerBtn')
        self.btn_stop.clicked.connect(self.stop_all)
        btnrow.addWidget(self.btn_stop)
        self.btn_clear = QPushButton('🗑 清理已完成')
        self.btn_clear.setObjectName('ghostBtn')
        self.btn_clear.clicked.connect(self.clear_done)
        btnrow.addWidget(self.btn_clear)
        lay.addLayout(btnrow)

        lay.addStretch(1)
        ver = QLabel(f'jmcomic {getattr(jmcomic, "__version__", "?")} · 桌面版')
        ver.setObjectName('footer')
        lay.addWidget(ver, alignment=Qt.AlignHCenter)

        scroll.setWidget(box)
        return panel

    def _section(self, text) -> QLabel:
        lb = QLabel(text)
        lb.setObjectName('sectionLabel')
        return lb

    def _choose_dir(self):
        path = QFileDialog.getExistingDirectory(self, '选择保存目录', self.ed_dir.text())
        if path:
            self.ed_dir.setText(path)

    def _build_tabs(self) -> QTabWidget:
        tabs = QTabWidget()
        tabs.setObjectName('mainTabs')

        # 任务
        tabs.addTab(self._build_tasks_tab(), '📋 任务')
        # 搜索
        tabs.addTab(self._build_search_tab(), '🔍 搜索')
        # 日志
        tabs.addTab(self._build_log_tab(), '📄 日志')

        return tabs

    def _build_tasks_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        self.scroll_tasks = QScrollArea()
        self.scroll_tasks.setWidgetResizable(True)
        self.scroll_tasks.setFrameShape(QFrame.NoFrame)
        self.tasks_container = QWidget()
        self.tasks_layout = QVBoxLayout(self.tasks_container)
        self.tasks_layout.setContentsMargins(0, 0, 0, 0)
        self.tasks_layout.setSpacing(10)
        self.tasks_layout.addStretch(1)
        self.scroll_tasks.setWidget(self.tasks_container)
        lay.addWidget(self.scroll_tasks)
        self.lb_tasks_empty = QLabel('暂无下载任务。在左侧输入 ID 后点击「开始下载」。')
        self.lb_tasks_empty.setObjectName('emptyHint')
        self.lb_tasks_empty.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.lb_tasks_empty)
        return w

    def _build_search_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        # 顶部输入
        row = QHBoxLayout()
        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText('输入关键词（支持 +包含 -排除，如：+全彩 -人妻），回车搜索')
        self.ed_search.returnPressed.connect(lambda: self.do_search())
        row.addWidget(self.ed_search, 1)

        self.cb_search_type = QComboBox()
        for k, v in [('站内搜索', 'site'), ('作品', 'work'), ('作者', 'author'), ('标签', 'tag'), ('角色', 'actor')]:
            self.cb_search_type.addItem(k, v)
        row.addWidget(self.cb_search_type)

        self.cb_order = QComboBox()
        for k, v in [('最新', 'mr'), ('观看最多', 'mv'), ('图片最多', 'mp'), ('点赞最多', 'tf')]:
            self.cb_order.addItem(k, v)
        row.addWidget(self.cb_order)

        btn = QPushButton('🔍 搜索')
        btn.setObjectName('primaryBtn')
        btn.clicked.connect(lambda: self.do_search())
        row.addWidget(btn)
        lay.addLayout(row)

        # 结果信息
        self.lb_search_info = QLabel('输入关键词后点击「搜索」')
        self.lb_search_info.setObjectName('muted')
        lay.addWidget(self.lb_search_info)

        # 结果列表
        self.list_search = QListWidget()
        self.list_search.setObjectName('searchList')
        self.list_search.itemDoubleClicked.connect(lambda it: self._open_detail(it))
        lay.addWidget(self.list_search, 1)

        # 分页
        page_row = QHBoxLayout()
        btn_prev = QPushButton('◀ 上一页')
        btn_prev.setObjectName('ghostBtn')
        btn_prev.clicked.connect(lambda: self.change_page(-1))
        page_row.addWidget(btn_prev)
        self.lb_page = QLabel('')
        self.lb_page.setObjectName('muted')
        self.lb_page.setAlignment(Qt.AlignCenter)
        page_row.addWidget(self.lb_page, 1)
        btn_next = QPushButton('下一页 ▶')
        btn_next.setObjectName('ghostBtn')
        btn_next.clicked.connect(lambda: self.change_page(1))
        page_row.addWidget(btn_next)
        lay.addLayout(page_row)

        return w

    def _build_log_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        self.txt_all_log = QPlainTextEdit()
        self.txt_all_log.setReadOnly(True)
        self.txt_all_log.setObjectName('logBox')
        lay.addWidget(self.txt_all_log)
        return w

    # ---- 下载操作 ----
    def parse_ids(self) -> List[str]:
        text = self.txt_ids.toPlainText()
        return [s for s in text.replace('，', ' ').replace(',', ' ').replace(';', ' ').split() if s]

    def get_config(self) -> dict:
        return {
            'download_dir': self.ed_dir.text().strip(),
            'impl': self.cb_impl.currentData(),
            'suffix': self.cb_suffix.currentData(),
            'image_threads': self.sp_threads.value(),
            'dir_rule': self.ed_rule.text().strip(),
            'decode': self.chk_decode.isChecked(),
        }

    def start_download(self, ids: Optional[List[str]] = None):
        ids = ids or self.parse_ids()
        if not ids:
            QMessageBox.information(self, '提示', '请先输入要下载的 ID')
            return
        config = self.get_config()
        task = make_task(ids, config)
        with TASKS_LOCK:
            TASKS[task['id']] = task
        threading.Thread(target=run_download, args=(task['id'], ids, config), daemon=True).start()
        self.statusBar().showMessage(f'已开始下载: {", ".join(ids)}')
        self.txt_ids.clear()
        self.refresh_tasks(force=True)

    def stop_all(self):
        with TASKS_LOCK:
            for t in TASKS.values():
                if t['status'] in ('waiting', 'running'):
                    t['cancel'] = True
                    task_log(t, '收到停止请求...')
        self.statusBar().showMessage('已发送停止请求')

    def clear_done(self):
        with TASKS_LOCK:
            for tid in [k for k, v in TASKS.items() if v['status'] in ('done', 'error', 'cancelled')]:
                del TASKS[tid]
        # 移除对应卡片
        for tid in [k for k in list(self.task_cards) if k not in TASKS]:
            card = self.task_cards.pop(tid)
            self.tasks_layout.removeWidget(card)
            card.deleteLater()
        self.refresh_tasks(force=True)

    # ---- 任务刷新 ----
    def refresh_tasks(self, force=False):
        with TASKS_LOCK:
            tasks_snapshot = {tid: dict(t) for tid, t in TASKS.items()}
        # 新增卡片
        for tid, t in tasks_snapshot.items():
            if tid not in self.task_cards:
                card = TaskCard(t)
                # 插入到 stretch 之前
                self.tasks_layout.insertWidget(self.tasks_layout.count() - 1, card)
                self.task_cards[tid] = card
        # 更新
        for tid, card in list(self.task_cards.items()):
            t = tasks_snapshot.get(tid)
            if t:
                card.refresh(t)
            else:
                self.tasks_layout.removeWidget(card)
                card.deleteLater()
                del self.task_cards[tid]
        self.lb_tasks_empty.setVisible(len(tasks_snapshot) == 0)
        # 刷新全局日志
        self._refresh_all_log(tasks_snapshot)

    def _refresh_all_log(self, tasks_snapshot=None):
        if not tasks_snapshot:
            with TASKS_LOCK:
                tasks_snapshot = {tid: dict(t) for tid, t in TASKS.items()}
        lines = []
        for t in sorted(tasks_snapshot.values(), key=lambda x: x['start_time'], reverse=True):
            lines.append(f"===== 任务 #{t['id']} [{t['status']}] 目标: {', '.join(t['ids'])} =====")
            lines.extend(t['logs'][-300:])
            lines.append('')
        text = '\n'.join(lines)
        if text != self.txt_all_log.toPlainText():
            self.txt_all_log.setPlainText(text)
            sb = self.txt_all_log.verticalScrollBar()
            sb.setValue(sb.maximum())

    # ---- 搜索操作 ----
    def do_search(self, page=None):
        q = self.ed_search.text().strip()
        if not q:
            QMessageBox.information(self, '提示', '请输入搜索关键词')
            return
        stype = self.cb_search_type.currentData()
        order = self.cb_order.currentData()
        self.search_page = page or self.search_page
        self.lb_search_info.setText('搜索中...')
        threading.Thread(target=search_worker, args=(q, stype, order, self.search_page), daemon=True).start()

    def change_page(self, delta):
        nc = self.search_page + delta
        if nc < 1 or nc > max(1, self.search_page_count):
            return
        self.search_page = nc
        self.do_search(nc)

    def on_search_done(self, results, total, page_count):
        self.search_results_cache = results
        self.search_total = total
        self.search_page_count = page_count
        self.lb_search_info.setText(f'找到 {total} 个结果 · 第 {self.search_page}/{page_count} 页')
        self.lb_page.setText(f'第 {self.search_page} / {page_count} 页')
        self.list_search.clear()
        self.search_items.clear()
        if not results:
            return
        for item in results:
            w = SearchItemWidget(item)
            w.download_requested.connect(self.start_download)
            w.view_requested.connect(self.open_viewer_album)
            li = QListWidgetItem()
            li.setSizeHint(w.sizeHint())
            self.list_search.addItem(li)
            self.list_search.setItemWidget(li, w)
            self.search_items[str(item['id'])] = w
            # 启动封面加载
            task = CoverTask(str(item['id']), item['cover'])
            self.cover_pool.start(task)

    def on_search_error(self, msg):
        self.lb_search_info.setText(f'搜索失败: {msg}')

    def _open_detail(self, item):
        w = self.list_search.itemWidget(item)
        if w is None:
            return
        aid = w.item['id']
        dlg = AlbumDetailDialog(aid, self)
        dlg.download_requested.connect(self.start_download)
        dlg.view_requested.connect(self.open_viewer_photo)
        dlg.exec_()

    # ---- 漫画浏览入口 ----
    def open_viewer_album(self, album_id):
        dlg = ComicViewerDialog(album_id=str(album_id), parent=self)
        dlg.exec_()

    def open_viewer_photo(self, photo_id):
        dlg = ComicViewerDialog(photo_id=str(photo_id), parent=self)
        dlg.exec_()


# ---------------------------------------------------------------------------
# 11. 全局样式 (暗色主题 · 统一调色板)
#    整个界面的颜色都集中定义在这里，保证配色完全统一，方便整体换肤。
# ---------------------------------------------------------------------------
C = {
    # ---- 中性色：背景 / 边框 / 文字 ----
    'bg':        '#0e1015',   # 主背景
    'bg_side':   '#14171f',   # 侧栏背景
    'bg_card':   '#171a22',   # 卡片背景
    'bg_input':  '#1c2029',   # 输入框 / 进度条背景
    'bg_btn':    '#1e222d',   # 按钮默认背景
    'bg_log':    '#0b0d12',   # 日志框背景
    'border':    '#262b36',   # 主边框
    'border2':   '#2a3040',   # 次边框 / 填充
    'scroll':    '#2f3544',   # 滚动条滑块
    'text':      '#e6e9ef',   # 主文字
    'muted':     '#9aa4b2',   # 次要文字
    'dim':       '#6b7280',   # 弱化文字

    # ---- 主色：蓝紫渐变系 ----
    'accent':        '#5b8cff',
    'accent2':       '#7c5bff',
    'accent_hover':  '#6b9cff',
    'accent2_hover': '#8c6bff',
    'selection':     '#3b5bdb',

    # ---- 语义色：状态色 ----
    'ok':      '#34d399',   # 成功 / 完成
    'warn':    '#fbbf24',   # 取消 / 警告
    'danger':  '#f87171',   # 错误 / 危险

    # ---- 语义色背景（带透明度，与上面的语义色对应）----
    'accent_bg':      'rgba(91,140,255,.15)',
    'accent_bg_soft': 'rgba(91,140,255,.12)',
    'ok_bg':          'rgba(52,211,153,.15)',
    'warn_bg':        'rgba(251,191,36,.15)',
    'danger_bg':      'rgba(248,113,113,.15)',
}


def build_qss() -> str:
    qss = '''
QMainWindow, QDialog { background: @bg@; }
QWidget {
    color: @text@;
    font-size: 13px;
}
#sidePanel { background: @bg_side@; border-right: 1px solid @border@; }
#sideScroll { background: transparent; }
QScrollArea { background: transparent; border: none; }
QScrollBar:vertical { background: @bg_side@; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: @scroll@; border-radius: 5px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: @bg_side@; height: 10px; }
QScrollBar::handle:horizontal { background: @scroll@; border-radius: 5px; min-width: 30px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox {
    background: @bg_input@;
    border: 1px solid @border2@;
    border-radius: 8px;
    padding: 7px 10px;
    selection-background-color: @selection@;
}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: @accent@; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    background: @bg_input@; border: 1px solid @border2@;
    selection-background-color: @selection@;
}
QTextEdit#idsBox { font-family: Consolas, monospace; }

QPushButton {
    background: @bg_btn@;
    border: 1px solid @border2@;
    border-radius: 8px;
    padding: 8px 14px;
}
QPushButton:hover { border-color: @accent@; }
QPushButton:pressed { background: @border2@; }
QPushButton:disabled { color: @dim@; border-color: @border@; }
QPushButton#primaryBtn {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 @accent@, stop:1 @accent2@);
    border: none; color: #ffffff; font-weight: 600;
}
QPushButton#primaryBtn:hover { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 @accent_hover@, stop:1 @accent2_hover@); }
QPushButton#primaryBig {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 @accent@, stop:1 @accent2@);
    border: none; color: #ffffff; font-size: 15px; font-weight: 700;
}
QPushButton#primaryBig:hover { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 @accent_hover@, stop:1 @accent2_hover@); }
QPushButton#dangerBtn { color: @danger@; }
QPushButton#dangerBtn:hover { border-color: @danger@; }
QPushButton#ghostBtn { background: transparent; color: @muted@; }

QTabWidget::pane { border: 1px solid @border@; border-radius: 10px; top: -1px; background: @bg@; }
QTabBar::tab {
    background: transparent; color: @muted@; padding: 9px 18px; margin-right: 4px;
    border-top-left-radius: 8px; border-top-right-radius: 8px; font-size: 13px;
}
QTabBar::tab:selected { color: @text@; background: @bg_card@; }
QTabBar::tab:hover { color: @text@; }

QLabel#sectionLabel { color: @muted@; font-size: 12px; margin-top: 4px; }
QLabel#footer { color: @dim@; font-size: 11px; margin-top: 16px; }
QLabel#muted { color: @muted@; }
QLabel#emptyHint { color: @dim@; font-size: 14px; padding: 30px; }
QLabel#searchTitle { font-weight: 600; font-size: 14px; }
QLabel#detailTitle { font-size: 17px; font-weight: 700; }
QLabel#coverPlaceholder { background: @bg_input@; color: @dim@; border-radius: 6px; }
QLabel#taskId { font-family: Consolas, monospace; color: @accent@; font-weight: 600; }

QFrame#taskCard {
    background: @bg_card@; border: 1px solid @border@; border-radius: 10px;
}
QProgressBar#progress {
    background: @bg_input@; border: none; border-radius: 4px;
}
QProgressBar#progress::chunk {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 @accent@, stop:1 @accent2@);
    border-radius: 4px;
}
QLabel#stWaiting { color: @muted@; background: @border2@; border-radius: 10px; padding: 1px 10px; font-size: 11px; }
QLabel#stRunning { color: @accent@; background: @accent_bg@; border-radius: 10px; padding: 1px 10px; font-size: 11px; }
QLabel#stDone { color: @ok@; background: @ok_bg@; border-radius: 10px; padding: 1px 10px; font-size: 11px; }
QLabel#stError { color: @danger@; background: @danger_bg@; border-radius: 10px; padding: 1px 10px; font-size: 11px; }
QLabel#stCancelled { color: @warn@; background: @warn_bg@; border-radius: 10px; padding: 1px 10px; font-size: 11px; }

QPlainTextEdit#logBox {
    background: @bg_log@; border: 1px solid @border@; border-radius: 8px;
    font-family: Consolas, "Microsoft YaHei", monospace; font-size: 12px;
}
QListWidget#searchList {
    background: transparent; border: 1px solid @border@; border-radius: 10px;
}
QListWidget#searchList::item { border-bottom: 1px solid @bg_input@; }
QListWidget#searchList::item:selected { background: @accent_bg_soft@; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid @border2@; border-radius: 4px; background: @bg_input@; }
QCheckBox::indicator:checked { background: @accent@; border-color: @accent@; }
QDialog#detailDialog QListWidget { background: transparent; border: 1px solid @border@; border-radius: 8px; }
QDialog#viewerDialog { background: @bg@; }
QLabel#viewerImage {
    background: @bg_log@; border: 1px solid @border@; border-radius: 8px;
    color: @muted@; font-size: 14px;
}
'''
    for key, val in C.items():
        qss = qss.replace('@' + key + '@', val)
    return qss


APP_QSS = build_qss()


# ---------------------------------------------------------------------------
# 12. 入口
# ---------------------------------------------------------------------------
def main():
    # 高 DPI 适配
    try:
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName('JMComic 桌面下载器')
    app.setStyleSheet(APP_QSS)

    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
