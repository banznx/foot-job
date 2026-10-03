# -*- coding: utf-8 -*-
"""
重渲染：路径结构或模板变更后，用已保存的 content.json 重新生成 HTML。

为什么需要它：
    改目录结构（seo-pages/post → pages/）或改模板之后，
    已生成的页面里还留着旧的 CSS 路径、旧的 canonical、旧的内链。
    这些页面必须重写一遍才能与新结构一致。
    而它们的内容（标题/正文/schema）都存放在 content.json 里，
    **不需要重新调 AI** —— 省钱、快、且不会因为 AI 输出漂移而改变已收录内容。

用法：
    python -m seo.rebuild            # 全量重渲染
    python -m seo.rebuild --check    # 只报告有多少页面需要重渲染
"""

import io
import json
import os
import sys

from . import config
from .render import page as page_render
from .render import tag_page as tag_render


def _load(path):
    try:
        with io.open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def needs_rebuild(html_path):
    """判断页面是否还残留旧路径。"""
    if not os.path.exists(html_path):
        return True
    try:
        with io.open(html_path, encoding='utf-8') as f:
            h = f.read()
    except Exception:
        return True
    prefix = config.PIPELINE['PAGE_PREFIX']
    # 注意斜杠数量：site_url('/') 已经带尾斜杠，PAGE_PREFIX 也带头斜杠，
    # 直接相加会得到 '//pages/'（双斜杠），判据就永远不匹配。
    base = config.site_url('/')[:-1] + prefix
    # canonical 必须指向统一前缀
    if ('rel="canonical" href="%s' % base) not in h:
        return True
    # CSS 必须走新路径
    if ('/%s/seo-assets/style.css' % config.PIPELINE['OUT_DIR']) not in h:
        return True
    # 不能再有旧目录前缀
    for old in ('/post/', '/kw/', '/tag/', '/promo/', '/seo-pages/'):
        if ('href="%s%s' % (config.site_url('/'), old)) in h:
            return True
    return False


def rebuild(dry_run=False):
    base = config.OUTPUT_DIR
    if not os.path.isdir(base):
        print('[rebuild] 没有找到 %s' % base)
        return 0

    total = stale = done = 0
    cta_extra = [(t, config.TAG_SLUGS.get(t, 'zonghe'))
                 for t in sorted(config.TAG_SLUGS.keys())[:5]]

    for name in sorted(os.listdir(base)):
        d = os.path.join(base, name)
        if not os.path.isdir(d):
            continue
        html_path = os.path.join(d, 'index.html')
        total += 1
        if not needs_rebuild(html_path):
            continue
        stale += 1

        cj = os.path.join(d, 'content.json')
        content = _load(cj)
        if not content:
            # 索引页与聚合页没有 content.json，跳过（由流水线自己重建）
            continue
        if dry_run:
            continue
        try:
            if content.get('is_promo'):
                html = page_render.render_promo(
                    content, config.site_url, cta_extra=cta_extra)
            else:
                html = page_render.render_post(content, config.site_url)
            tag_render.write_file(html_path, html)
            done += 1
        except Exception as e:
            print('[rebuild] %s 失败：%s' % (name, e))

    print('[rebuild] 共 %d 个页面，需重渲染 %d 个，已重渲染 %d 个'
          % (total, stale, done))
    return done


if __name__ == '__main__':
    args = sys.argv[1:]
    rebuild(dry_run='--check' in args)
