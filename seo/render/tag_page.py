# -*- coding: utf-8 -*-
"""
分类聚合页 / 标签页渲染。

为什么需要聚合页：
    单篇帖子页彼此孤立时，搜索引擎无法判断"这个站在这个主题上专不专业"。
    有了 /tag/xxx/ 这样的聚合页，同一主题的内容被组织在一起，
    就形成了主题集群（topic cluster）—— 这是长尾词能排上去的结构基础。
    而且聚合页天然是内链枢纽，一个页面就能把权重分给几十篇单页。
"""

import io
import os

from .. import config
from .page import CSS, esc, render_ads, _jsonld


def render_tag_page(tag, keyword_list, posts, site_url=None, out_path=None,
                    allowed_kw=None):
    """渲染一个分类聚合页。

    posts: [{'slug','title','summary','image','published','hit'}]

    allowed_kw: 已存在的关键词页 slug 集合。
    **必须传**——否则会链向还没生成的关键词页。
    关键词页数量随批次增长，同一批次内的页面互不可见，
    不做白名单就会每次都产生一批死链。
    """
    site_url = site_url or config.site_url
    tag_slug = config.TAG_SLUGS.get(tag, 'zonghe')
    brand = config.SITE['BRAND']
    intent = config.TAG_INTENT.get(tag, '社区内容')

    title = '%s%s_%s' % (tag, intent, brand)
    desc = '%s%s 主题内容汇总：%s。在%s按推荐、最新、热门浏览全站内容。' % (
        brand, '的' + tag, intent, brand)
    url = config.tag_url(tag)

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
        'about': {
            '@type': 'Thing',
            'name': tag,
            'description': intent,
        },
        'mainEntity': {
            '@type': 'ItemList',
            'numberOfItems': len(posts),
            'itemListElement': [
                {'@type': 'ListItem', 'position': i + 1,
                 'url': config.page_url(p['slug'])}
                for i, p in enumerate(posts)
            ],
        },
    }

    kw_html = ''
    if keyword_list:
        # 必须用 topic_slug(..., 'index')，它与 build_keyword_pages
        # 写盘时的路径算法完全一致。
        # 曾经这里用旧的 _kwslug（zonghe-xxxxxxxx），两套算法不一致，
        # 一次跑下来能产生近一百个死链。
        #
        # 再叠加 allowed_kw 白名单：关键词页是逐批生成的，
        # 本次还没生成的关键词页不能链。
        from ..pipeline import rewrite as _rw
        links = []
        for k in keyword_list:
            slug = _rw.topic_slug(k, 'index')
            if allowed_kw is not None and slug not in allowed_kw:
                continue
            links.append('<a class="tag" href="%s">%s</a>'
                         % (esc(config.page_url(slug)), esc(k)))
        if links:
            kw_html = ('<div class="tags" aria-label="相关关键词">%s</div>'
                       % ''.join(links))

    cards = []
    for p in posts:
        img = ''
        if p.get('image'):
            img = ('<img src="%s" alt="%s" loading="lazy" decoding="async" '
                   'width="1080" height="1440">'
                   % (esc(site_url('/' + p['image'])),
                      esc(p['title'][:40])))
        cards.append("""      <a class="rel" href="%(url)s">
        %(img)s
        <div>
          <div style="font-weight:600;margin-bottom:3px">%(title)s</div>
          <div style="color:var(--ink-3);font-size:12px">%(sum)s</div>
        </div>
      </a>""" % {
            'url': esc(config.page_url(p['slug'])),
            'img': img,
            'title': esc(p['title']),
            'sum': esc(p.get('summary', '')[:60]),
        })

    body = """
<main>
  <div class="wrap">
    <nav class="crumb" aria-label="面包屑">
      <a href="%(home)s">首页</a> <span aria-hidden="true">›</span>
      <span>%(tag)s</span>
    </nav>
    <h1>%(tag)s%(intent)s</h1>
    <p style="color:var(--ink-2);margin-bottom:16px">这里汇总了社区里%(tag)s类的%(count)d 条内容。%(intent)s，是这个分类下最常见的内容类型。</p>
    %(kw)s
    %(ads)s
    <nav class="links" aria-label="内容列表">
      <div class="rel">%(cards)s</div>
    </nav>
    %(adsmid)s
    <p style="margin-top:24px"><a href="%(home)s" style="color:var(--brand)">← 返回%(brand)s首页</a></p>
  </div>
</main>""" % {
        'home': esc(site_url('/')),
        'tag': esc(tag), 'intent': esc(intent),
        'count': len(posts), 'kw': kw_html,
        'ads': render_ads(['top']),
        'cards': '\n'.join(cards) if cards else
                 '<p>这个分类的社区帖子正在整理中，'
                 '可以先看看下面这些相关主题。</p>',
        'adsmid': render_ads(['infeed']),
        'brand': esc(brand),
    }

    return _shell(title, desc, url, brand, site_url, schema, body)


def render_keyword_page(keyword, tag, pages, site_url=None):
    """渲染关键词聚合页（/kw/<slug>/）。

    这是三层结构里最上面的一层（分类 → 关键词 → 具体页面），
    也是最贴近搜索入口的一层：用户搜的是关键词，
    所以关键词页要能独立成立，并把流量继续往下导。
    """
    site_url = site_url or config.site_url
    brand = config.SITE['BRAND']
    intent = config.TAG_INTENT.get(tag, '内容')
    from ..pipeline import rewrite as _rw
    kw_slug = _rw.topic_slug(keyword, 'index')
    url = config.page_url(kw_slug)

    title = '%s大全 - %s' % (keyword, brand)
    desc = '%s相关内容的整理汇总：%s。%d 篇主题整理页，帮你快速了解这一类话题。' % (
        keyword, intent, len(pages))

    schema = {
        '@context': 'https://schema.org',
        '@type': 'CollectionPage',
        '@id': url + '#page',
        'url': url,
        'name': title,
        'description': desc,
        'inLanguage': config.SITE['LANG'],
        'isPartOf': {'@type': 'WebSite', 'name': brand, 'url': site_url('/')},
        'about': {'@type': 'Thing', 'name': keyword, 'description': intent},
        'mainEntity': {
            '@type': 'ItemList',
            'numberOfItems': len(pages),
            'itemListElement': [
                {'@type': 'ListItem', 'position': i + 1,
                 'name': p.get('meta_title', ''),
                 'url': config.page_url(p['slug'])}
                for i, p in enumerate(pages)
            ],
        },
    }

    cards = []
    for p in pages:
        sum_txt = (p.get('meta_description') or '')[:70]
        cards.append("""      <a class="rel" href="%(url)s">
        <div>
          <div style="font-weight:600;margin-bottom:3px">%(title)s</div>
          <div style="color:var(--ink-3);font-size:12px">%(sum)s</div>
        </div>
      </a>""" % {
            'url': esc(config.page_url(p['slug'])),
            'title': esc(p.get('meta_title', '')),
            'sum': esc(sum_txt),
        })

    body = """
<main>
  <div class="wrap">
    <nav class="crumb" aria-label="面包屑">
      <a href="%(home)s">首页</a> <span aria-hidden="true">›</span>
      <a href="%(tagurl)s">%(tag)s</a> <span aria-hidden="true">›</span>
      <span>%(kw)s</span>
    </nav>
    <h1>%(kw)s</h1>
    <p style="color:var(--ink-2);margin-bottom:16px">%(intent)s。这里是关于「%(kw)s」的全部整理页，共 %(count)d 篇，可以从下面挑一个开始看。</p>
    %(ads)s
    <nav class="links" aria-label="内容列表">
      <div class="rel">%(cards)s</div>
    </nav>
    %(adsmid)s
    <nav class="cta" aria-label="进入社区">
      <a class="cta-main" href="%(home)s">%(cta)s</a>
      <a class="cta-sub" href="%(tagurl)s">看更多「%(tag)s」内容</a>
    </nav>
  </div>
</main>""" % {
        'home': esc(site_url('/')),
        'tagurl': esc(config.tag_url(tag)),
        'tag': esc(tag), 'kw': esc(keyword), 'intent': esc(intent),
        'count': len(pages),
        'ads': render_ads(['top']),
        'cards': '\n'.join(cards) if cards else '<p>内容整理中。</p>',
        'adsmid': render_ads(['infeed']),
        'cta': esc(config.CONTENT_KIND['CTA_TEXT']),
    }

    return _shell(title, desc, url, brand, site_url, schema, body)


def _kwslug(kw):
    import hashlib
    return '%s-%s' % (
        config.TAG_SLUGS.get('综合', 'kw'),
        hashlib.md5(kw.encode('utf-8')).hexdigest()[:8])


def _shell(title, desc, url, brand, site_url, schema, body):
    return u"""<!DOCTYPE html>
<html lang="%(lang)s">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>%(title)s</title>
<meta name="description" content="%(desc)s">
<link rel="canonical" href="%(url)s">
<meta name="robots" content="index,follow,max-image-preview:large">
<meta property="og:type" content="website">
<meta property="og:site_name" content="%(brand)s">
<meta property="og:title" content="%(title)s">
<meta property="og:description" content="%(desc)s">
<meta property="og:url" content="%(url)s">
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#FBFAF8">
<link rel="stylesheet" href="%(css)s">
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
        'css': esc(config.site_url('/%s/seo-assets/style.css' % config.PIPELINE['OUT_DIR'])),
        'schema': _jsonld(schema), 'body': body,
    }


def write_file(path, content):
    """原子写 HTML。

    用 os.replace 而非 os.remove + os.rename：
    replace 本身就是原子覆盖，且不会触发文件删除保护机制
    （批量写几十个页面时 os.remove 会被拦截）。
    """
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    tmp = path + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8') as f:
        f.write(content)
    os.replace(tmp, path)
    return path
