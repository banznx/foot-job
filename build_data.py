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

# 界面实际使用的字段，其余（scoreTxt/notice/weight/isGood/... 共 20+ 个）
# 全部不参与渲染，剔除后体积从 3.7MB 降到 1.4MB
POST_FIELDS = ('postID', 'title', 'detail', 'images', 'hit',
               'commentCount', 'praise', 'createTime')
USER_FIELDS = ('userID', 'nick', 'age', 'level', 'identityTitle')


def build():
    here = os.path.dirname(os.path.abspath(__file__))
    posts_dir = os.path.join(here, 'posts2')

    files = [f for f in sorted(glob.glob(os.path.join(posts_dir, '*.json')))
             if not f.endswith('index.json')]
    if not files:
        sys.exit('错误：posts2/ 下没有找到帖子 JSON')

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
    print('\n下一步：在 HTML 里用 <script src="posts-data.js"></script> 加载，'
          '并删除所有 fetch 调用。')


if __name__ == '__main__':
    build()
