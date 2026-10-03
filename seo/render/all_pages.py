# -*- coding: utf-8 -*-
"""
`/pages/` 总索引页。

需求：访问 /pages/ 时能看到所有自动生成的页面。

GitHub Pages 不会为目录自动生成索引，所以必须手写。
这一页是**全站静态页的地图**，按类型分组：

    /pages/
      ├── 内容页（主题沉淀）   数量最多
      ├── 引流文章（每小时新增）
      ├── 关键词入口页
      └── 分类聚合页

注意：这一页**不作为内容页进 sitemap**（它本身是列表页，
价值在于给人看和给爬虫一个爬取起点，不是关键词落地页）。
但它会被首页链接到，权重能正常传递。
"""

import io
import os

from .. import config
from ..pipeline import imgpool
from .page import CSS, _jsonld, esc


def build_index_page(site_url=None):
    """扫描 pages/ 目录，生成总索引。"""
    site_url = site_url or config.site_url
    base = config.OUTPUT_DIR
    if not os.path.isdir(base):
        return None, {}

    groups = {'promo': [], 'post': [], 'topic': [], 'tag': []}
    for name in sorted(os.listdir(base)):
        d = os.path.join(base, name)
        if not os.path.isdir(d):
            continue
        if not os.path.exists(os.path.join(d, 'index.html')):
            continue
        title, summary, date, thumb = _meta_of(d)
        item = {'slug': name, 'title': title, 'summary': summary,
                'date': date, 'thumb': thumb}
        if name == 'promo-index':
            continue
        if name.startswith('tag-'):
            groups['tag'].append(item)
        elif name.startswith('topic-'):
            groups['topic'].append(item)
        elif name.startswith(config.PIPELINE['PROMO_SLUG_PREFIX']):
            groups['promo'].append(item)
        else:
            groups['post'].append(item)

    url = site_url('/%s/' % config.PIPELINE['OUT_DIR'])
    brand = config.SITE['BRAND']
    total = sum(len(v) for v in groups.values())

    title = '%s · 全部内容页' % brand
    desc = ('%s 自动生成的全部静态内容页索引：%d 个主题内容页、'
            '%d 篇引流文章、%d 个关键词入口、%d 个分类页。'
            % (brand, len(groups['post']), len(groups['promo']),
               len(groups['topic']), len(groups['tag'])))

    schema = {
        '@context': 'https://schema.org',
        '@type': 'CollectionPage',
        '@id': url + '#page',
        'url': url,
        'name': title,
        'description': desc,
        'inLanguage': config.SITE['LANG'],
        'isPartOf': {'@type': 'WebSite', 'name': brand,
                     'url': site_url('/')},
        'mainEntity': {
            '@type': 'ItemList',
            'numberOfItems': total,
            'itemListElement': [
                {'@type': 'ListItem', 'position': i + 1,
                 'name': it['title'], 'url': config.page_url(it['slug'])}
                for i, it in enumerate(
                    (groups['post'] + groups['promo']
                     + groups['topic'] + groups['tag'])[:500])
            ],
        },
    }

    body = _body(site_url, brand, groups, total)
    return _shell(title, desc, url, brand, site_url, schema, body), groups


def _meta_of(d):
    """读 content.json 拿标题与摘要；聚合页没有就退回 slug。"""
    cj = os.path.join(d, 'content.json')
    slug = os.path.basename(d)
    if not os.path.exists(cj):
        return _pretty(slug), '', '', None
    try:
        with io.open(cj, encoding='utf-8') as f:
            import json
            c = json.load(f)
    except Exception:
        return _pretty(slug), '', '', None
    title = c.get('meta_title') or _pretty(slug)
    summary = (c.get('meta_description') or '')[:90]
    imgs = c.get('images') or []
    import datetime
    ts = c.get('published') or c.get('generated_at')
    date = ''
    if ts:
        try:
            date = datetime.datetime.fromtimestamp(
                ts / 1000.0).strftime('%Y-%m-%d')
        except Exception:
            pass
    return title, summary, date, (imgs[0] if imgs else None)


def _pretty(slug):
    """把 slug 变成可读标题：jupai-0c10863f -> 举牌 / 0c10863f"""
    if slug.startswith('tag-'):
        return '分类 · ' + slug[4:]
    if slug.startswith('topic-'):
        return '关键词 · ' + slug[6:]
    if slug.startswith('p-'):
        return '引流 · ' + slug[2:8]
    return slug


def _cards(items, limit=None):
    """渲染卡片列表。

    limit 为 None 时**完整展示** —— 这一页的意义就是
    「一眼看到所有自动生成的页面」，截断会违背需求。
    页面数量会持续增长（每小时一篇），所以给 body 加了
    max-height + 滚动，视觉上不会把页面撑到不可用。
    """
    if not items:
        return '<p class="empty">暂无</p>'
    show = items[:limit] if limit else items
    out = []
    for it in show:
        thumb = ''
        if it.get('thumb'):
            thumb = ('<img class="th" src="%s" alt="" loading="lazy" '
                     'decoding="async" width="72" height="72">'
                     % esc(imgpool.to_url(it['thumb'])))
        out.append(
            '<a class="card" href="%s">%s'
            '<div class="c"><div class="t">%s</div>'
            '<div class="s">%s</div>'
            '<div class="d">%s</div></div>'
            '</a>' % (
                esc(config.page_url(it['slug'])),
                thumb,
                esc(it['title']),
                esc(it['summary']),
                esc(it['date'])))
    if limit and len(items) > limit:
        out.append('<p class="more">另有 %d 条未显示</p>'
                   % (len(items) - limit))
    return '\n      '.join(out)


def _body(site_url, brand, g, total):
    # 全部完整展示，不截断 —— 这一页就是「全部页面清单」
    promo = _cards(sorted(g['promo'], key=lambda x: x['date'], reverse=True))
    post = _cards(g['post'])
    topic = _cards(g['topic'])
    tag = _cards(g['tag'])
    return """
<main>
  <div class="wrap">
    <nav class="crumb" aria-label="面包屑">
      <a href="%(home)s">首页</a> <span aria-hidden="true">›</span>
      <span>全部内容页</span>
    </nav>

    <h1>全部内容页</h1>
    <p class="lead">共 %(total)d 个页面。主题内容页是长期沉淀的部分，
    引流文章每小时新增一篇，关键词页与分类页是聚合入口。</p>

    <nav class="jump" aria-label="快速跳转">
      <a href="#promo">引流文章 %(npromo)d</a>
      <a href="#post">主题内容 %(npost)d</a>
      <a href="#topic">关键词 %(ntopic)d</a>
      <a href="#tag">分类 %(ntag)d</a>
    </nav>

    <section id="promo">
      <h2>引流文章 <em>%(npromo)d</em></h2>
      <p class="tip">每小时新增一篇，主题围绕社区内容做原创整理。</p>
      <div class="scroll"><div class="grid">
      %(promo)s
      </div></div>
    </section>

    <section id="post">
      <h2>主题内容页 <em>%(npost)d</em></h2>
      <p class="tip">按「关键词 × 角度」生成，与社区真实帖子分开管理。</p>
      <div class="scroll"><div class="grid">
      %(post)s
      </div></div>
    </section>

    <section id="topic">
      <h2>关键词入口 <em>%(ntopic)d</em></h2>
      <p class="tip">按搜索词聚合，是承接搜索流量的主要入口。</p>
      <div class="scroll"><div class="grid">
      %(topic)s
      </div></div>
    </section>

    <section id="tag">
      <h2>分类聚合 <em>%(ntag)d</em></h2>
      <div class="scroll"><div class="grid">
      %(tag)s
      </div></div>
    </section>

    <nav class="cta" aria-label="返回">
      <a class="cta-main" href="%(home)s">返回%(brand)s</a>
      <a class="cta-sub" href="%(promo)s">看引流文章合集</a>
    </nav>
  </div>
</main>""" % {
        'home': esc(site_url('/')),
        'brand': esc(brand), 'total': total,
        'npromo': len(g['promo']), 'npost': len(g['post']),
        'ntopic': len(g['topic']), 'ntag': len(g['tag']),
        'promo': promo, 'post': post, 'topic': topic, 'tag': tag,
        'promo_url': esc(config.page_url('promo-index')),
    }


# 索引页专用样式（追加在通用 CSS 之后）
INDEX_CSS = """
/* ---- 全部内容页索引 ---- */
.lead{color:var(--ink-2);margin-bottom:18px;font-size:14px;line-height:1.8}
.jump{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:26px}
.jump a{font-size:13px;padding:6px 12px;border-radius:var(--r-full);
  background:var(--surface-2);border:1px solid var(--line-1);color:var(--ink-2)}
main section{margin-bottom:34px}
main section h2{font-size:16px;font-weight:650;margin-bottom:6px;
  display:flex;align-items:baseline;gap:8px}
main section h2 em{font-style:normal;font-size:12px;color:var(--brand);
  background:var(--brand-soft);padding:2px 8px;border-radius:var(--r-full)}
main section .tip{font-size:12px;color:var(--ink-3);margin-bottom:12px}
.grid{display:grid;gap:8px}
/* 页面会持续增长（每小时一篇），给列表加滚动容器，
   完整展示所有页面的同时不让页面长到无法浏览 */
.scroll{max-height:70vh;overflow-y:auto;padding-right:4px;
  border:1px solid var(--line);border-radius:12px;padding:10px;
  background:var(--surface-2);-webkit-overflow-scrolling:touch}
.scroll .grid{gap:7px}
.card{display:flex;gap:11px;align-items:flex-start;background:var(--surface);
  border:1px solid var(--line);border-radius:11px;padding:10px 12px}
.card .th{width:72px;height:72px;object-fit:cover;border-radius:8px;
  flex:0 0 auto;background:var(--surface-3)}
.card .c{min-width:0;flex:1}
.card:active{background:var(--surface-2)}
.card .t{font-size:14px;font-weight:600;line-height:1.5;margin-bottom:3px}
.card .s{font-size:12px;color:var(--ink-3);line-height:1.55;
  overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;
  -webkit-box-orient:vertical}
.card .d{font-size:11px;color:var(--ink-4);margin-top:5px}
.more{font-size:12px;color:var(--ink-3);padding:8px 2px}
.empty{font-size:13px;color:var(--ink-4);padding:8px 2px}
"""


def _shell(title, desc, url, brand, site_url, schema, body):
    return u"""<!DOCTYPE html>
<html lang="%(lang)s">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>%(title)s</title>
<meta name="description" content="%(desc)s">
<link rel="canonical" href="%(url)s">
<meta name="robots" content="index,follow,max-snippet:-1">
<meta property="og:type" content="website">
<meta property="og:site_name" content="%(brand)s">
<meta property="og:title" content="%(title)s">
<meta property="og:description" content="%(desc)s">
<meta property="og:url" content="%(url)s">
<meta name="theme-color" content="#FBFAF8">
<link rel="stylesheet" href="%(css)s">
<style>%(idxcss)s</style>
<script type="application/ld+json">
%(schema)s
</script>
</head>
<body>
<header class="bar">
  <div class="wrap">
    <a class="logo" href="%(home)s" aria-label="%(brand)s 首页">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"
        stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <rect x="3" y="3" width="18" height="18" rx="2"/>
        <path d="M7 15l4-4 3 3 5-5"/></svg>
      %(brand)s
    </a>
    <a class="back" href="%(home)s">返回社区</a>
  </div>
</header>
%(body)s
<footer>
  <div class="wrap">
    <p>%(brand)s · <a href="%(home)s">返回首页</a></p>
  </div>
</footer>
</body>
</html>
""" % {
        'lang': config.SITE['LANG'],
        'title': esc(title), 'desc': esc(desc), 'url': esc(url),
        'brand': esc(brand), 'home': esc(site_url('/')),
        'css': esc(config.site_url('/%s/seo-assets/style.css'
                                   % config.PIPELINE['OUT_DIR'])),
        'idxcss': INDEX_CSS,
        'schema': _jsonld(schema), 'body': body,
    }


def write_index(base_dir=None):
    """生成并写入 pages/index.html。"""
    from .tag_page import write_file
    html, groups = build_index_page()
    if not html:
        return None
    base_dir = base_dir or config.OUTPUT_DIR
    path = os.path.join(base_dir, 'index.html')
    write_file(path, html)
    return path, groups
