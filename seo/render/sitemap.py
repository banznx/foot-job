# -*- coding: utf-8 -*-
"""
sitemap.xml 与 robots.txt 生成。

sitemap 是收录的入口，规则不多但都是硬性要求：
  - URL 必须是完整绝对地址
  - lastmod 用 ISO 8601
  - 单个 sitemap 上限 50000 URL / 50MB（未分段，量小无所谓）
  - 只能收录 200 的状态码页面，链 404 会拖垮整份 sitemap

robots.txt 的要点：这里有个**真实冲突**必须处理——
站点是纯前端 SPA，index.html 里的内容由 JS 渲染，
但 Google 已经能执行 JS，所以不能一刀切 Disallow 掉资源文件。
真正需要屏蔽的是 posts-data.js（1.5MB，纯数据，索引无意义）
和构建中间产物。
"""

import glob
import io
import os

from .. import config


def build_sitemap(pages, out_path=None, tag_pages=None):
    """生成 sitemap.xml。

    pages: [{'url','lastmod','priority','changefreq'}]
    tag_pages: [{'url','lastmod'}]
    """
    out_path = out_path or os.path.join(
        config.ROOT, config.PIPELINE['OUT_DIR'], 'sitemap.xml')
    _mkdir(os.path.dirname(out_path))

    urls = list(pages) + list(tag_pages or [])
    # 按 lastmod 倒序：最新内容优先被爬虫发现
    urls.sort(key=lambda u: u.get('lastmod') or '', reverse=True)

    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        loc = u['url']
        if not loc.startswith('http'):
            continue          # sitemap 只接受绝对地址
        lines.append('  <url>')
        lines.append('    <loc>%s</loc>' % _xml(loc))
        if u.get('lastmod'):
            lines.append('    <lastmod>%s</lastmod>' % _xml(u['lastmod']))
        if u.get('changefreq'):
            lines.append('    <changefreq>%s</changefreq>' % u['changefreq'])
        if u.get('priority') is not None:
            lines.append('    <priority>%s</priority>' % u['priority'])
        lines.append('  </url>')
    lines.append('</urlset>')

    with io.open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    return out_path, len(urls)


def build_robots(out_path=None, extra_disallow=None):
    """生成 robots.txt。"""
    out_path = out_path or os.path.join(config.ROOT, 'robots.txt')
    base = config.site_url('/')
    host = config.SITE['HOST']

    lines = [
        'User-agent: *',
        'Allow: /',
        # posts-data.js 是 1.5MB 的纯数据文件，索引它毫无意义，
        # 而且会稀释抓取预算—— 明确屏蔽。
        'Disallow: /posts-data.js',
        'Disallow: /post1/',
        'Disallow: /posts2/',
        # 构建中间产物，不该被索引
        'Disallow: /seo/state/',
        'Disallow: /seo/logs/',
        'Disallow: /*?v=',
        '',
        '# 静态页集中在 /post/ 与 /kw/ 下，明确开放',
        'Allow: /post/',
        'Allow: /tag/',
        'Allow: /kw/',
        # 引流文章目录，每小时新增，必须放行
        'Allow: /promo/',
        '',
        'Sitemap: %ssitemap.xml' % base,
        'Sitemap: %spromo/sitemap.xml' % base,
    ]
    if extra_disallow:
        lines.extend(extra_disallow)
    with io.open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    return out_path


def collect_pages(out_dir=None):
    """扫描已生成的静态页，收集成 sitemap 条目。"""
    out_dir = out_dir or os.path.join(config.ROOT, config.PIPELINE['OUT_DIR'])
    pages = []
    if not os.path.isdir(out_dir):
        return pages
    for path in glob.glob(os.path.join(out_dir, 'post', '*', 'index.html')):
        slug = os.path.basename(os.path.dirname(path))
        data_path = os.path.join(out_dir, 'post', slug, 'content.json')
        lastmod = None
        if os.path.exists(data_path):
            import json
            try:
                with io.open(data_path, encoding='utf-8') as f:
                    m = json.load(f)
                lastmod = _lastmod(m.get('published'), m.get('generated_at'))
            except Exception:
                pass
        pages.append({
            'url': config.site_url('/post/%s/' % slug),
            'lastmod': lastmod,
            'changefreq': 'weekly',
            # 详情页给0.6：比首页低但不能太低，太低会被判定为不重要
            'priority': '0.6',
        })
    return pages


def build_index_entries():
    """首页 + 分类聚合页 + 关键词聚合页。

    三层入口结构：首页 → 分类页 → 关键词页 → 具体内容页。
    每一层都在sitemap 里登记，爬虫才能顺着找到下层。
    """
    site_url = config.site_url
    now = _today()
    entries = [{
        'url': site_url('/'), 'lastmod': now,
        'changefreq': 'daily', 'priority': '1.0',
    }]
    for tag in config.TAG_SLUGS:
        entries.append({
            'url': site_url('/tag/%s/' % config.TAG_SLUGS[tag]),
            'lastmod': now, 'changefreq': 'daily', 'priority': '0.8',
        })

    # 关键词页：priority 给 0.7，比分类页低一点但高于单篇详情页，
    # 因为它是承接搜索流量的主要入口
    import glob as _glob
    kw_dir = os.path.join(config.ROOT, config.PIPELINE['OUT_DIR'], 'kw')
    for d in _glob.glob(os.path.join(kw_dir, '*')):
        if os.path.exists(os.path.join(d, 'index.html')):
            slug = os.path.basename(d)
            entries.append({
                'url': site_url('/kw/%s/' % slug),
                'lastmod': now, 'changefreq': 'weekly', 'priority': '0.7',
            })
    return entries


def _lastmod(published_ms, generated_ms):
    """lastmod 用源帖发布时间（稳定），没有则用生成时间。"""
    import datetime
    src = published_ms or generated_ms
    if not src:
        return None
    try:
        return datetime.datetime.utcfromtimestamp(
            src / 1000.0).strftime('%Y-%m-%d')
    except Exception:
        return None


def _today():
    import datetime
    return datetime.datetime.utcnow().strftime('%Y-%m-%d')


def _xml(s):
    return (str(s).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


def _mkdir(p):
    if p and not os.path.isdir(p):
        os.makedirs(p)
