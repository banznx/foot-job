"""本地图片抽样。

为什么不用 Pillow：这套系统跑在 GitHub Actions 上，多一个依赖就多一处失败点。
JPEG/PNG 的文件头里本来就写着宽高，按字节读出来即可，标准库够用。
"""
import os
import random
import struct
from urllib.parse import quote

IMG_DIR = os.path.join(os.path.dirname(__file__), '..', 'images', 'downloaded_posts_images')

# 站点上图片的公开前缀。仓库名决定路径，改站名时不要动它。
SITE_ROOT = 'https://banznx.github.io/foot-job'
IMG_URL_PREFIX = SITE_ROOT + '/images/downloaded_posts_images/'

# 抽图约束：太大拖慢页面，太小是缩略图不清晰
MIN_BYTES = 40 * 1024
MAX_BYTES = 220 * 1024
MIN_WIDTH = 800


def image_size(path):
    """读图片宽高，只解析文件头，不解码整图。读不出来返回 (0, 0)。"""
    try:
        with open(path, 'rb') as f:
            head = f.read(32)
            if head[:8] == b'\x89PNG\r\n\x1a\n':
                # IHDR 紧跟文件头：长度(4) + 类型(4) + 宽(4) + 高(4)
                w, h = struct.unpack('>II', head[16:24])
                return w, h
            if head[:2] == b'\xff\xd8':
                return _jpeg_size(path)
    except OSError:
        pass
    return 0, 0


def _jpeg_size(path):
    """沿 JPEG 的段链找 SOF0/SOF2，宽高就在那一段里。"""
    with open(path, 'rb') as f:
        f.read(2)
        while True:
            marker = f.read(1)
            while marker and marker != b'\xff':
                marker = f.read(1)
            if not marker:
                return 0, 0
            code = f.read(1)
            while code == b'\xff':
                code = f.read(1)
            if not code:
                return 0, 0
            if code[0] in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                           0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                f.read(3)
                h, w = struct.unpack('>HH', f.read(4))
                return w, h
            length = f.read(2)
            if len(length) < 2:
                return 0, 0
            f.read(struct.unpack('>H', length)[0] - 2)
    return 0, 0


def public_url(filename):
    """本地文件名 -> 站点上的可访问直链。中文与空格必须转义。"""
    return IMG_URL_PREFIX + quote(filename)


def scan(limit=None):
    """扫描图片目录，返回符合约束的素材列表。

    按 postID 分组是为了让一篇文章里的几张图来自同一个帖子，
    风格统一，不会东一张西一张看着像拼凑的。
    """
    if not os.path.isdir(IMG_DIR):
        return {}
    groups = {}
    for name in os.listdir(IMG_DIR):
        ext = os.path.splitext(name)[1].lower()
        if ext not in ('.jpg', '.jpeg', '.png', '.webp'):
            continue
        full = os.path.join(IMG_DIR, name)
        try:
            size = os.path.getsize(full)
        except OSError:
            continue
        if size < MIN_BYTES or size > MAX_BYTES:
            continue
        w, h = image_size(full)
        if w < MIN_WIDTH:
            continue
        post_id = name.split('_')[0]
        groups.setdefault(post_id, []).append({
            'file': name,
            'bytes': size,
            'w': w,
            'h': h,
            'url': public_url(name),
        })
    for items in groups.values():
        items.sort(key=lambda x: x['bytes'])
    if limit:
        groups = dict(list(groups.items())[:limit])
    return groups


def pick_group(groups, used_files, rng=None, per_group=3):
    """随机抽一组未用过的图。

    随机是刻意的：文章内容是 AI 看过图之后才写的，抽到什么都能写出
    对得上的内容，所以不需要按主题预先筛选。
    """
    rng = rng or random
    fresh = [(pid, items) for pid, items in groups.items()
             if not any(i['file'] in used_files for i in items)]
    if not fresh:
        return None
    # 优先取图多的组：一篇文章只配一张图太单薄
    richest = max(len(items) for _, items in fresh)
    bar = min(richest, per_group)
    pool = [(pid, items) for pid, items in fresh if len(items) >= bar]
    pid, items = rng.choice(pool)
    chosen = items[:per_group]
    if not chosen:
        return None
    return {'post_id': pid, 'images': chosen}
