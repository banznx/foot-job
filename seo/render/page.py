# -*- coding: utf-8 -*-
"""
静态页渲染：把结构化内容变成搜索引擎能读的 HTML。

为什么必须做静态页（这是整个系统存在的理由）：
    现在的 index.html 是单页应用，帖子详情是 JS 浮层。
    搜索引擎抓取时能拿到的只有一个空 <div> 和一个 posts-data.js，
    单篇帖子的标题、正文、图片全部拿不到 —— **一个都收录不了**。
    GitHub Pages 又没有服务端渲染能力，所以唯一的解法就是：
    提前把每一篇渲染成独立的 .html 文件，让爬虫拿到完整内容。

每页必备的 SEO 元素：
    <title> / meta description / canonical / OG / Twitter Card
    JSON-LD 结构化数据 / 语义化标签 / 内链
"""

import io
import os
import re

from .. import config

# 复用站点配色，保持视觉一致（与 index.html 的设计令牌一致）
CSS = """
:root{
  --canvas:#F2F0EC;--surface:#FFF;--surface-2:#F6F5F2;--surface-3:#EAE8E3;
  --ink-1:#1A1917;--ink-2:#57534E;--ink-3:#8A857D;--ink-4:#B4AFA6;
  --line:rgba(26,25,23,.10);--brand:#9A3B2E;--brand-2:#B4533F;--brand-soft:#F6E7E3;
  --font:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hirino Sans GB","Microsoft YaHei",Roboto,sans-serif;
  --maxw:720px;
}
@media (prefers-color-scheme:dark){:root{
  --canvas:#0F0E0D;--surface:#1A1918;--surface-2:#232120;--surface-3:#2E2C2A;
  --ink-1:#F5F3F0;--ink-2:#B8B2AA;--ink-3:#8A857D;--ink-4:#635E58;
  --line:rgba(245,243,240,.12);--brand:#C9705F;--brand-2:#D67F6E;--brand-soft:#33201C;
}}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:var(--font);background:var(--canvas);color:var(--ink-1);
  font-size:16px;line-height:1.75;-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}
img{display:block;max-width:100%;height:auto}
:focus-visible{outline:2px solid var(--brand);outline-offset:2px}
.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap}
.wrap{max-width:var(--maxw);margin:0 auto;padding:0 16px}
header.bar{position:sticky;top:0;z-index:10;background:var(--surface);
  border-bottom:1px solid var(--line)}
header.bar .wrap{display:flex;align-items:center;gap:10px;height:52px}
.logo{display:inline-flex;align-items:center;gap:7px;font-weight:700;color:var(--brand)}
.logo svg{width:15px;height:15px}
.back{color:var(--ink-3);font-size:14px;margin-left:auto}
main{padding:20px 0 40px}
h1{font-size:24px;line-height:1.4;font-weight:700;letter-spacing:-.01em;margin-bottom:14px}
.meta{display:flex;flex-wrap:wrap;gap:8px 14px;color:var(--ink-3);font-size:13px;
  padding-bottom:16px;border-bottom:1px solid var(--line);margin-bottom:20px}
.tags{display:flex;flex-wrap:wrap;gap:7px;margin-bottom:18px}
.tag{font-size:12px;padding:4px 10px;border-radius:999px;background:var(--brand-soft);
  color:var(--brand)}
.gallery{display:grid;gap:10px;margin-bottom:24px}
.gallery a,.gallery figure{display:block;background:var(--surface-2);border-radius:12px;overflow:hidden}
.body p{margin-bottom:16px}
.body h2{font-size:18px;margin:26px 0 12px;font-weight:650}
.links{background:var(--surface);border:1px solid var(--line);border-radius:14px;
  padding:16px;margin:24px 0}
.links h2{font-size:15px;margin-bottom:10px;color:var(--ink-2)}
.links ul{list-style:none;display:grid;gap:8px}
.links li{font-size:14px;line-height:1.5}
.links a{border-bottom:1px solid var(--line);padding-bottom:6px;display:block}
.links a:hover{color:var(--brand)}
.rel{display:grid;gap:9px;margin-top:12px}
.rel a{display:flex;gap:10px;align-items:center;background:var(--surface);
  border:1px solid var(--line);border-radius:11px;padding:11px 13px;font-size:14px}
.rel .tg{font-size:11px;color:var(--ink-3);flex:0 0 auto;background:var(--surface-3);
  padding:3px 7px;border-radius:5px}
/* 性质声明：把「这是主题整理页、不是真实发帖」明确告诉读者 */
.notice{background:var(--brand-soft);border:1px solid var(--line);border-radius:12px;
  padding:12px 14px;font-size:13px;line-height:1.7;color:var(--ink-2);margin-bottom:20px}
.notice strong{display:inline-block;margin-right:8px;color:var(--brand);
  font-size:12px;font-weight:600}
.dot{display:inline-block;width:6px;height:6px;border-radius:50%;
  background:var(--brand);margin-right:6px;vertical-align:1px}
.meta .dot{margin-right:2px}
/* 进站入口：SEO 页的最终目的，把搜索流量导回社区 */
.cta{margin:24px 0;padding:18px;border-radius:14px;background:var(--surface);
  border:1px solid var(--line);text-align:center}
.cta-main{display:block;padding:13px;border-radius:11px;background:var(--brand);
  color:#fff;font-size:15px;font-weight:600}
.cta-main:active{background:var(--brand-2)}
.cta-sub{display:block;margin-top:11px;font-size:13px;color:var(--ink-3)}
/* 引流页的多入口：给读者多个点击去处，转化率高于单一入口 */
.cta-chips{display:flex;flex-wrap:wrap;gap:7px;justify-content:center;margin-top:13px}
.cta-chip{font-size:12px;padding:5px 11px;border-radius:var(--r-full);
  background:var(--surface-2);color:var(--ink-2);border:1px solid var(--line-1)}
.ad{display:block;margin:24px 0;text-align:center;min-height:90px;
  background:var(--surface-2);border:1px dashed var(--line);border-radius:12px;
  display:flex;align-items:center;justify-content:center;color:var(--ink-4);font-size:12px}
footer{border-top:1px solid var(--line);padding:22px 0 40px;color:var(--ink-3);font-size:13px}
footer a{color:var(--brand)}
.crumb{font-size:13px;color:var(--ink-3);margin-bottom:14px}
.crumb a{color:var(--ink-3)}
.crumb span{color:var(--ink-4)}
@media (max-width:480px){h1{font-size:20px}main{padding-top:16px}}
"""


def esc(s):
    """HTML 转义。内容来自 AI 和用户输入，必须转。"""
    return (str(s or '')
            .replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('"', '&quot;').replace("'", '&#39;'))


def _jsonld(obj):
    """安全序列化 JSON-LD。

    关键：必须转义 < 和 &，否则内容里出现 "</script>" 会提前闭合
    script 标签，导致 XSS 或结构化数据解析失败。
    """
    import json
    s = json.dumps(obj, ensure_ascii=False, indent=2)
    return s.replace('</', '<\\/').replace('&', '\\u0026')


def render_post(content, site_url=None, ads=True):
    """渲染单篇帖子的静态页。"""
    site_url = site_url or config.site_url
    brand = config.SITE['BRAND']
    # URL 从 slug 实时计算，不读存档里的 url 字段——
    # 目录结构改过之后存档里存的是旧路径，直接用会导致
    # canonical 指向不存在的地址（收录硬伤）。
    url = config.page_url(content['slug'])
    title = content['meta_title']
    desc = content['meta_description']
    tag = content['tag']
    tag_slug = content['tag_slug']
    ogt = tag + ' · ' + brand

    paras = _body_html(content['body'])
    gallery = _gallery_html(content, site_url)
    links_html = _links_html(content, site_url)
    rel_html = _related_html(content, site_url)
    tags_html = ''.join(
        '<a class="tag" href="%s">%s</a>' % (
            esc(config.tag_url(content['tag'])), esc(t))
        for t in content.get('tags', []))
    notice_html = _notice_html(content, site_url)
    cta_html = _cta_html(content, site_url)
    ads_html = render_ads(['top']) if ads else ''
    ads_mid = render_ads(['infeed']) if ads else ''
    ads_foot = render_ads(['footer']) if ads else ''

    # 首图作为 og:image —— 社交分享和富媒体结果都靠它
    og_img = ''
    if content.get('images'):
        og_img = ('<meta property="og:image" content="%s">'
                  '<meta name="twitter:image" content="%s">'
                  % (esc(site_url('/' + content['images'][0])),
                     esc(site_url('/' + content['images'][0]))))

    return u"""<!DOCTYPE html>
<html lang="%(lang)s">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>%(title)s</title>
<meta name="description" content="%(desc)s">
<meta name="keywords" content="%(tags)s">
<link rel="canonical" href="%(url)s">
<meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1">
<meta property="og:type" content="article">
<meta property="og:site_name" content="%(brand)s">
<meta property="og:title" content="%(ogt)s">
<meta property="og:description" content="%(desc)s">
<meta property="og:url" content="%(url)s">
<meta property="og:locale" content="zh_CN">
<meta property="article:section" content="%(tag)s">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="%(title)s">
<meta name="twitter:description" content="%(desc)s">
%(ogimg)s
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

<main>
  <article itemscope itemtype="https://schema.org/Article">
  <div class="wrap">
    <nav class="crumb" aria-label="面包屑">
      <a href="%(home)s">首页</a> <span aria-hidden="true">›</span>
      <a href="%(tagurl)s">%(tag)s</a> <span aria-hidden="true">›</span>
      <span>正文</span>
    </nav>

    <h1 itemprop="headline">%(title)s</h1>

    <div class="meta">
      <span>%(noticedot)s%(noticeshort)s</span>
      <span><time datetime="%(iso)s" itemprop="datePublished">%(date)s</time></span>
      <span>%(imgnum)s 张图片</span>
    </div>

    <div class="tags">%(tagshtml)s</div>

    %(ads)s

    %(gallery)s

    <div class="body" itemprop="articleBody">
%(paras)s
    </div>

    %(adsmid)s

    %(notice)s
    %(cta)s
    %(links)s
    %(rel)s
  </div>
  </article>
</main>

<footer>
  <div class="wrap">
    <p>%(brand)s · 浏览社区全部内容请
      <a href="%(home)s">返回首页</a></p>
    %(adsfoot)s
  </div>
</footer>
</body>
</html>
""" % {
        'lang': config.SITE['LANG'],
        'title': esc(title), 'desc': esc(desc),
        'tags': esc('、'.join(content.get('tags', []))),
        'url': esc(url), 'brand': esc(brand), 'ogt': esc(ogt),
        'ogimg': og_img,
        'css': esc(config.site_url('/%s/seo-assets/style.css' % config.PIPELINE['OUT_DIR'])),
        'schema': _jsonld(content['schema']),
        'home': esc(site_url('/')),
        'tagurl': esc(config.tag_url(tag)),
        'tag': esc(tag),
        'iso': esc(_iso(content.get('published'))),
        'date': esc(_fmt(content.get('published'))),
        'imgnum': content.get('image_total', 0),
        'tagshtml': tags_html,
        'ads': ads_html, 'adsmid': ads_mid, 'adsfoot': ads_foot,
        'gallery': gallery, 'paras': paras,
        'notice': notice_html, 'cta': cta_html,
        'links': links_html, 'rel': rel_html,
        'noticedot': '<span class="dot" aria-hidden="true"></span>',
        'noticeshort': esc(content.get('notice_short', '主题整理页')),
    }


# ============================================================
# 片段渲染
# ============================================================

def render_promo(content, site_url=None, ads=True, cta_extra=None):
    """渲染引流文章页（promo/ 目录下）。

    与主题页（render_post）的区别：
      1. 顶部声明换成「引流文章」，语气更明确
      2. CTA 更强：主按钮 + 多个分类入口 + 首页
      3. schema 的 URL 用 /promo/ 前缀
    引流文的目的就是把搜索流量拉进社区，所以进站入口要比主题页更醒目。
    """
    site_url = site_url or config.site_url
    brand = config.SITE['BRAND']
    # URL 从 slug 实时计算，不读存档里的 url 字段——
    # 目录结构改过之后存档里存的是旧路径，直接用会导致
    # canonical 指向不存在的地址（收录硬伤）。
    url = config.page_url(content['slug'])
    title = content['meta_title']
    desc = content['meta_description']
    tag = content['tag']
    tag_slug = content['tag_slug']

    paras = _body_html(content['body'])
    tags_html = ''.join(
        '<a class="tag" href="%s">%s</a>' % (
            esc(config.tag_url(tag)), esc(t))
        for t in content.get('tags', []))
    notice_html = _notice_html(content, site_url)
    cta_html = _cta_html(content, site_url, extra=cta_extra)
    return _document(content, {
        'title': title, 'desc': desc, 'url': url, 'brand': brand,
        'tag': tag, 'tag_slug': tag_slug, 'schema': content['schema'],
        'tagshtml': tags_html, 'gallery': '', 'paras': paras,
        'notice': notice_html, 'cta': cta_html,
        'links': '', 'rel': '', 'is_promo': True,
        'noticeshort': esc(content.get('notice_short', '主题整理页')),
        'ads': render_ads(['top']) if ads else '',
        'adsmid': render_ads(['infeed']) if ads else '',
        'adsfoot': render_ads(['footer']) if ads else '',
    }, site_url)


def _document(content, ctx, site_url):
    """统一的 HTML 文档外壳。

    render_post 与 render_promo 共用，保证两个目录下的页面
    视觉与结构一致（只有文案和 CTA 强度不同）。
    """
    ogl = ctx.get('ogimage')
    og_img = ''
    imgs = content.get('images') or []
    if imgs:
        first = esc(site_url('/' + imgs[0]))
        og_img = ('<meta property="og:image" content="%s">'
                  '<meta name="twitter:image" content="%s">' % (first, first))
    elif ctx.get('is_promo'):
        # 引流页无图，用站点默认图避免社交分享空白
        default = esc(site_url('/og-default.svg'))
        og_img = ('<meta property="og:image" content="%s">'
                  '<meta name="twitter:image" content="%s">' % (default, default))

    return u"""<!DOCTYPE html>
<html lang="%(lang)s">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>%(title)s</title>
<meta name="description" content="%(desc)s">
<meta name="keywords" content="%(tags)s">
<link rel="canonical" href="%(url)s">
<meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1">
<meta property="og:type" content="article">
<meta property="og:site_name" content="%(brand)s">
<meta property="og:title" content="%(title)s">
<meta property="og:description" content="%(desc)s">
<meta property="og:url" content="%(url)s">
<meta property="og:locale" content="zh_CN">
<meta property="article:section" content="%(tag)s">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="%(title)s">
<meta name="twitter:description" content="%(desc)s">
%(ogimg)s
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

<main>
  <article itemscope itemtype="https://schema.org/Article">
  <div class="wrap">
    <nav class="crumb" aria-label="面包屑">
      <a href="%(home)s">首页</a> <span aria-hidden="true">›</span>
      <a href="%(tagurl)s">%(tag)s</a> <span aria-hidden="true">›</span>
      <span>正文</span>
    </nav>

    <h1 itemprop="headline">%(title)s</h1>

    <div class="meta">
      <span><span class="dot" aria-hidden="true"></span>%(noticeshort)s</span>
      <span><time datetime="%(iso)s" itemprop="datePublished">%(date)s</time></span>
    </div>

    <div class="tags">%(tagshtml)s</div>

    %(ads)s

    %(gallery)s

    <div class="body" itemprop="articleBody">
%(paras)s
    </div>

    %(adsmid)s

    %(notice)s
    %(cta)s
    %(links)s
    %(rel)s
  </div>
  </article>
</main>

<footer>
  <div class="wrap">
    <p>%(brand)s · 浏览社区全部内容请
      <a href="%(home)s">返回首页</a></p>
    %(adsfoot)s
  </div>
</footer>
</body>
</html>
""" % {
        'lang': config.SITE['LANG'],
        'title': esc(ctx['title']), 'desc': esc(ctx['desc']),
        'tags': esc('、'.join(content.get('tags', []))),
        'url': esc(ctx['url']), 'brand': esc(ctx['brand']),
        'tag': esc(ctx['tag']),
        'tagurl': esc(config.tag_url(ctx['tag'])),
        'ogimg': og_img,
        'css': esc(config.site_url('/%s/seo-assets/style.css' % config.PIPELINE['OUT_DIR'])),
        'schema': _jsonld(ctx['schema']),
        'home': esc(site_url('/')),
        'iso': esc(_iso(content.get('published'))),
        'date': esc(_fmt(content.get('published'))),
        'noticeshort': ctx.get('noticeshort', '主题整理页'),
        'tagshtml': ctx['tagshtml'], 'ads': ctx['ads'],
        'gallery': ctx['gallery'], 'paras': ctx['paras'],
        'adsmid': ctx['adsmid'], 'notice': ctx['notice'],
        'cta': ctx['cta'], 'links': ctx['links'], 'rel': ctx['rel'],
        'adsfoot': ctx['adsfoot'],
    }


def _notice_html(content, site_url):
    """页面顶部的性质声明。

    需求方明确要求：AI 产出的内容必须与用户真实浏览的帖子区分开。
    这条声明同时出现在正文上方和 meta 行，
    让读者一眼知道这不是社区里的某篇真实发帖。
    """
    if not content.get('is_seo_page'):
        return ''
    return ('<aside class="notice" role="note">'
            '<strong>%s</strong>%s</aside>'
            % (esc(content.get('notice_short', '主题整理页')),
               esc(content.get('notice', ''))))


def _cta_html(content, site_url, extra=None):
    """进站入口：这是 SEO 页的最终目的——把搜索流量导进社区。

    extra: 引流页会传额外的分类入口，让读者有多个点击去处，
    转化率比单一入口高。
    """
    if not content.get('is_seo_page'):
        return ''
    tag = content.get('tag', '')
    html = ['<nav class="cta" aria-label="进入社区">',
            '<a class="cta-main" href="%s">%s</a>'
            % (esc(site_url('/')),
               esc(content.get('cta_text', '进入社区')))]
    if extra:
        chips = []
        for t in extra[:6]:
            chips.append('<a class="cta-chip" href="%s">%s</a>'
                         % (esc(config.tag_url(t[0])), esc(t[0])))
        if chips:
            html.append('<div class="cta-chips">%s</div>' % ''.join(chips))
    html.append('<a class="cta-sub" href="%s">看更多「%s」内容</a>'
                % (esc(config.tag_url(tag)), esc(tag)))
    html.append('</nav>')
    return ''.join(html)


def _body_html(body):
    """正文段落转 HTML。

    内容已经过 _clean_body 清洗（去掉 markdown 标记），
    这里只做段落切分。不用 markdown 库——避免依赖，
    而且正文是我们自己控制格式的，不需要通用解析。
    """
    out = []
    for p in re.split(r'\n{2,}', (body or '').strip()):
        p = p.strip()
        if not p:
            continue
        # 单行短句当小标题（AI 常这么写），用 h2 提升结构语义
        if len(p) <= 20 and not p.endswith(('。', '！', '？', '.', '!', '?')):
            out.append('<h2>%s</h2>' % esc(p))
        else:
            out.append('<p>%s</p>' % esc(p))
    return '\n      '.join(out) or '<p>暂无正文。</p>'


def _gallery_html(content, site_url):
    imgs = content.get('images') or []
    if not imgs:
        return ''
    cells = []
    for i, src in enumerate(imgs):
        alt = '%s（第 %d 张）' % (content['meta_title'][:40], i + 1)
        # lazy loading：首屏外的图不加载，直接影响 LCP 与流量成本
        loading = 'eager' if i == 0 else 'lazy'
        cells.append(
            '<figure><img src="%s" alt="%s" loading="%s" decoding="async" '
            'width="1080" height="1440"></figure>'
            % (esc(site_url('/' + src)), esc(alt), loading))
    extra = content.get('image_total', 0) - len(imgs)
    more = ''
    if extra > 0:
        more = ('<p style="color:var(--ink-3);font-size:13px">'
                '另有 %d 张图片，可在社区内查看完整内容。</p>' % extra)
    return '<div class="gallery">%s</div>%s' % (''.join(cells), more)


def _links_html(content, site_url):
    links = content.get('internal_links') or []
    if not links:
        return ''
    items = []
    for l in links:
        items.append('<li><a href="%s">%s</a></li>'
                     % (esc(config.page_url(l['slug'])), esc(l['title'])))
    return ('<nav class="links" aria-label="相关推荐">'
            '<h2>继续看看</h2><ul>%s</ul></nav>' % ''.join(items))


def _related_html(content, site_url):
    rel = content.get('related') or []
    if not rel:
        return ''
    cells = []
    for r in rel:
        cells.append(
            '<a href="%s"><span class="tg">%s</span><span>%s</span></a>'
            % (esc(config.page_url(r['slug'])), esc(r['tag']),
               esc(r['title'])))
    return ('<nav class="links" aria-label="同类内容">'
            '<h2>同类内容</h2><div class="rel">%s</div></nav>'
            % ''.join(cells))


# ============================================================
# 广告位
# ============================================================

def render_ads(slot_ids):
    """渲染 AdSense 广告位。

    双重保险：
      1. 没配PUBLISHER_ID 时只输出带data 属性和尺寸的占位容器，
         不加载任何外部脚本 —— 广告位是"预留"而不是"启用"。
      2. 配了才注入 adsbygoogle.js 和 ins class。

    为什么默认不启用：AdSense 审核需要先有内容和流量，
    站点在有真实内容前挂空广告位只会拖慢速度影响审核。
    """
    out = []
    for sid in slot_ids:
        slot = None
        for s in config.ADS['SLOTS']:
            if s['id'] == sid:
                slot = s
                break
        if not slot:
            continue

        if config.ADS['ENABLED'] and config.ADS['PUBLISHER_ID']:
            out.append(
                '<div class="ad-slot" data-ad-slot="%s">'
                '<ins class="adsbygoogle" style="display:block" '
                'data-ad-client="ca-%s" data-ad-slot="%s" '
                'data-ad-format="auto" data-full-width-responsive="true"></ins>'
                '<script>(adsbygoogle=window.adsbygoogle||[]).push({});</script>'
                '</div>' % (slot['id'], esc(config.ADS['PUBLISHER_ID']),
                            slot['id']))
        else:
            out.append(
                '<div class="ad" data-ad-slot="%s" data-ad-w="%d" data-ad-h="%d" '
                'aria-hidden="true">广告位预留 %dx%d</div>'
                % (esc(slot['id']), slot['w'], slot['h'], slot['w'], slot['h']))
    return '\n'.join(out)


def _iso(ms):
    if not ms:
        return ''
    import datetime
    try:
        return datetime.datetime.utcfromtimestamp(ms / 1000.0).strftime(
            '%Y-%m-%dT%H:%M:%SZ')
    except Exception:
        return ''


def _fmt(ms):
    if not ms:
        return ''
    import datetime
    try:
        return datetime.datetime.fromtimestamp(ms / 1000.0).strftime('%Y年%m月%d日')
    except Exception:
        return ''
