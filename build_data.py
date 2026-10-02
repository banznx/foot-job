#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
构建静态数据 bundle，供 GitHub Pages 部署。

为什么需要这个：
    页面原本用 fetch() 读 posts2/*.json。静态托管（含 GitHub Pages）下
    浏览器从 https://xxx.github.io 发起的跨域请求会被 CORS 拦截，
    页面只会显示「无法读取 posts2/index.json」。

解决思路：
    把数据打包成 `window.__POSTS__ = {...}` 的 JS 文件，
    用 <script src> 加载 —— script 标签不受 CORS 限制。

用法：
    python build_data.py
    产物：posts-data.js（约 1.4 MB）
"""

import io
import json
import glob
import os
import sys
import re
import hashlib
import collections

# 界面实际使用的字段，其余（scoreTxt/notice/weight/isGood/... 共 20+ 个）
# 全部不参与渲染，剔除后体积从 3.7MB 降到 1.4MB
POST_FIELDS = ('postID', 'title', 'detail', 'images', 'hit',
               'commentCount', 'praise', 'createTime')
USER_FIELDS = ('userID', 'nick', 'age', 'level', 'identityTitle')

# 识别平台统一占位图的阈值：
# 原站对违规图片会用同一张提示图替换，导致大量文件内容完全相同。
# 正常用户图片不会有多份逐字节相同的副本，所以「重复出现次数」是可靠特征。
# 实测 9382 张里有 171 张是同一张「图片涉嫌违规」占位图，重复 171 次。
PLACEHOLDER_MIN_REPEAT = 20


def find_placeholders(images_dir):
    """返回应当被过滤掉的图片文件名集合。

    依据是文件内容哈希的重复次数：重复次数超过阈值的，
    必然是平台统一替换的占位图，不是真实内容。
    这样处理比写死某个哈希更稳，数据更新后仍自动生效。
    """
    if not os.path.isdir(images_dir):
        print('  提示：未找到 images/ 目录，跳过占位图过滤')
        return set()

    counter = collections.Counter()
    owner = {}
    for path in glob.glob(os.path.join(images_dir, '*')):
        try:
            with open(path, 'rb') as f:
                digest = hashlib.md5(f.read()).hexdigest()
        except Exception:
            continue
        counter[digest] += 1
        owner.setdefault(digest, []).append(os.path.basename(path))

    bad = set()
    for digest, n in counter.items():
        if n >= PLACEHOLDER_MIN_REPEAT:
            bad.update(owner[digest])
    if bad:
        print('  过滤占位图 %d 张（同一文件重复出现）' % len(bad))
    return bad


def build():
    here = os.path.dirname(os.path.abspath(__file__))
    posts_dir = os.path.join(here, 'posts2')
    images_dir = os.path.join(here, 'images', 'downloaded_posts_images')

    files = [f for f in sorted(glob.glob(os.path.join(posts_dir, '*.json')))
             if not f.endswith('index.json')]
    if not files:
        sys.exit('错误：posts2/ 下没有找到帖子 JSON')

    placeholders = find_placeholders(images_dir)

    posts = []
    skipped = 0
    for path in files:
        try:
            with io.open(path, encoding='utf-8') as f:
                d = json.load(f)
        except Exception as e:
            print('  跳过解析失败 %s：%s' % (os.path.basename(path), e))
            skipped += 1
            continue

        u = d.get('user') or {}
        posts.append({
            'postID': d.get('postID'),
            'title': d.get('title') or '',
            'detail': d.get('detail') or '',
            'images': d.get('images') or [],
            'hit': d.get('hit') or 0,
            'commentCount': d.get('commentCount') or 0,
            'praise': d.get('praise') or 0,
            'createTime': d.get('createTime') or 0,
            'user': {k: u.get(k) for k in USER_FIELDS},
        })

    # 过滤占位图：本地文件名规则为 {postID}_{原文件名}
    removed = 0
    for p in posts:
        kept = []
        for url in p['images']:
            fname = str(p['postID']) + '_' + str(url).split('/').pop().split('?')[0]
            if fname in placeholders:
                removed += 1
                continue
            kept.append(url)
        p['images'] = kept
    if removed:
        print('  从帖子中移除占位图引用 %d 处' % removed)

    # 用户头像统一留空：头像走的是已失效的远程 CDN，
    # 界面已有 onerror 降级为昵称首字色块，不依赖它。
    for p in posts:
        p['user']['avatar'] = None

    # 分片：单文件 1.4MB 首屏解析偏慢，拆成多片按需加载。
    # 每片约 300 篇 ≈ 180KB，配合 index 提示可增量取用。
    order = [p['postID'] for p in posts]
    payload = {
        'total': len(posts),
        'order': order,
        'posts': {str(p['postID']): p for p in posts},
    }

    out = os.path.join(here, 'posts-data.js')
    with io.open(out, 'w', encoding='utf-8') as f:
        f.write('window.__POSTS__=')
        json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))
        f.write(';')

    size = os.path.getsize(out)
    print('帖子总数：%d（跳过 %d）' % (len(posts), skipped))
    print('产物：posts-data.js  %.2f MB' % (size / 1048576.0))
    print('平均每篇：%.0f 字节' % (size / max(len(posts), 1)))

    stamp_version(here, out)


def stamp_version(here, data_file):
    """给 HTML 里的数据引用加上内容哈希。

    为什么需要：浏览器会缓存 posts-data.js，
    数据重新生成后用户仍会看到旧内容（实测踩到过：
    占位图已过滤但页面依旧显示，排查半天才发现是缓存）。

    用内容哈希而不是时间戳：内容没变就不换参数，
    缓存继续有效；内容一变参数自动变化，强制重新拉取。
    """
    with open(data_file, 'rb') as f:
        digest = hashlib.md5(f.read()).hexdigest()[:10]

    pages = glob.glob(os.path.join(here, '*.html'))
    changed = []
    for page in pages:
        with io.open(page, encoding='utf-8') as f:
            html = f.read()
        new = re.sub(
            r'(<script src="posts-data\.js)(\?v=[0-9a-f]+)?(")',
            r'\g<1>?v=%s\g<3>' % digest,
            html
        )
        if new != html:
            with io.open(page, 'w', encoding='utf-8') as f:
                f.write(new)
            changed.append(os.path.basename(page))

    if changed:
        print('已更新缓存版本号 %s → %s' % (digest, '、'.join(changed)))
    else:
        print('未找到引用 posts-data.js 的页面，跳过版本号更新')


if __name__ == '__main__':
    build()
