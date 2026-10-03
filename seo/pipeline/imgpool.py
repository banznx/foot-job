# -*- coding: utf-8 -*-
"""
社区图片池：给静态页随机配图。

需求：借用社区的图片嵌到 pages 页面里，随机调用即可。

为什么不直接用源帖的图：
    关键词页与引流文章在设计上与真实帖子**解耦**（不带post_id、
    不带用户信息），如果直接拿源帖的图，就等于把具体某篇帖子
    重新包装一遍，与解耦的初衷相反。
    所以这里是**从全站图片里随机抽**——图是社区的通用素材，
    不指向任何一篇具体帖子。

三个必须处理的坑（都实际踩过）：

1. **违规占位图**
   原站对违规图片会用同一张提示图替换，实测 171 个文件逐字节相同。
   不过滤的话界面上直接显示"图片涉嫌违规 已禁止访问"占位块。
   识别特征必须是**内容哈希的重复次数**，不能按尺寸——
   尺寸分布太分散（1080x1440、1500x2000 都是正常图）。

2. **图片路径格式**
   库里存的是 `downloaded_posts_images/xxx.png` 这种相对路径，
   拼 URL 时必须用 `/images/` 前缀，否则 404。

3. **零图片可用**
   万一池子空了（过滤后一张不剩），页面不能崩也不能显示空图块，
   降级为不配图。
"""

import hashlib
import io
import os
import random

from .. import config

IMG_EXT = ('.jpg', '.jpeg', '.png', '.webp', '.gif')

# 缓存：扫描 9380 个文件 + 算哈希要 18 秒，每轮重扫不可接受。
# 内存缓存给单次运行用；磁盘缓存让后续运行（尤其 CI）直接读。
_pool_cache = {}
_LIST_CACHE_FILE = 'image_pool.json'


def _load_disk_cache():
    """读磁盘缓存。图片目录几乎不变，缓存基本永久有效。

    用目录 mtime 判定是否失效：图片有增删时 mtime 会变，缓存自动作废。
    """
    p = os.path.join(config.STATE_DIR, _LIST_CACHE_FILE)
    if not os.path.exists(p):
        return None
    try:
        import json
        with io.open(p, encoding='utf-8') as f:
            d = json.load(f)
        root = _image_dir()
        if os.path.isdir(root) and int(os.path.getmtime(root)) != d.get('mtime'):
            return None
        return d.get('list') or None
    except Exception:
        return None


def _save_disk_cache(items):
    p = os.path.join(config.STATE_DIR, _LIST_CACHE_FILE)
    try:
        import json
        config.dump_json(p, {
            'mtime': int(os.path.getmtime(_image_dir())),
            'count': len(items), 'list': items})
    except Exception:
        pass


def _image_dir():
    return os.path.join(config.ROOT, 'images')


def build_pool(limit_scan=12000, dup_threshold=20, use_cache=True):
    """扫描图片目录，返回可用图片相对路径列表。

    dup_threshold: 同一内容出现超过这么多次，判定为占位图并剔除。
    实测违规占位图有 171 份完全相同，阈值 20 能稳定识别，
    而正常图片即使内容相同也不会超过这个数。
    """
    key = (limit_scan, dup_threshold)
    if key in _pool_cache:
        return _pool_cache[key]

    if use_cache:
        cached = _load_disk_cache()
        if cached:
            _pool_cache[key] = cached
            return cached

    root = _image_dir()
    if not os.path.isdir(root):
        _pool_cache[key] = []
        return []

    # 递归收集所有图片文件的绝对路径
    files = []
    for dirpath, _dirs, names in os.walk(root):
        for n in names:
            if n.lower().endswith(IMG_EXT):
                files.append(os.path.join(dirpath, n))
                if len(files) >= limit_scan:
                    break
        if len(files) >= limit_scan:
            break

    # 按内容哈希找重复
    by_hash = {}
    for p in files:
        try:
            st = os.stat(p)
            h = _hash_of(p, st)
        except Exception:
            continue
        by_hash.setdefault(h, []).append(p)

    pool = []
    for h, group in by_hash.items():
        if len(group) >= dup_threshold:
            continue          # 占位图，整组丢弃
        pool.extend(group)

    rels = sorted(to_rel(p) for p in pool)
    if use_cache:
        _save_disk_cache(rels)
    _pool_cache[key] = rels
    return rels


def _hash_of(path, st=None):
    """文件内容哈希（读前 64KB，够用且快）。"""
    try:
        with open(path, 'rb') as f:
            return hashlib.md5(f.read(65536)).hexdigest()
    except Exception:
        return 'err-%s' % path


def pick(n=4, exclude=None, seed=None):
    """随机抽 n 张图，返回相对路径列表（相对仓库根）。

    exclude: 排除列表（避免同一篇文章重复用同一张）
    seed:    传随机种子则结果可复现；不传则每次都不同
    """
    pool = build_pool()
    if not pool:
        return []
    exclude = set(exclude or [])

    rng = random.Random(seed) if seed is not None else random
    n = min(n, max(len(pool) - len(exclude), 1))

    out = []
    tries = 0
    while len(out) < n and tries < n * 12:
        tries += 1
        p = rng.choice(pool)
        rel = to_rel(p)
        if rel in exclude or rel in out:
            continue
        out.append(rel)
    return out


def to_rel(abs_path):
    """绝对路径 -> 相对仓库根的路径，并统一用正斜杠。

    渲染时拼成 https://站点/<BASE_PATH>/images/xxx
    """
    rel = os.path.relpath(abs_path, config.ROOT)
    return rel.replace('\\', '/')


def to_url(rel_path, site_url=None):
    """相对路径 -> 完整线上 URL。"""
    site_url = site_url or config.site_url
    return site_url('/' + rel_path.lstrip('/'))


def pick_for_page(n=4, seed=None, exclude=None):
    """给页面配图的便捷入口：直接返回线上可用的 URL 列表。"""
    return [to_url(r) for r in pick(n=n, seed=seed, exclude=exclude)]


def pool_size():
    return len(build_pool())
