"""页面渲染：复刻玉卒现有界面的设计令牌，让 SEO 页面和 App 长得一样。

令牌是从 index.html 抄过来的，不是重新设计的。以后 App 改了主色，
这两处要同步改，否则点进 SEO 页面会像换了个站。
"""
import html
import os
import re
from urllib.parse import quote

SITE_URL = 'https://banznx.github.io/foot-job'
SITE_NAME = '玉卒'
APP_URL = SITE_URL + '/'

THEME_CSS = """
:root {
  --canvas: #F2F0EC; --surface: #FFFFFF; --surface-2: #F6F5F2; --surface-3: #EAE8E3;
  --ink-1: #1A1917; --ink-2: #57534E; --ink-3: #8A857D; --ink-4: #B4AFA6;
  --line-1: rgba(26,25,23,0.08); --line-2: rgba(26,25,23,0.16);
  --brand: #9A3B2E; --brand-2: #B4533F; --brand-soft: #F6E7E3; --brand-ink: #8A3626;
  --font: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
          "Hiragino Sans GB", "Microsoft YaHei", Roboto, Helvetica, Arial, sans-serif;
  --s1: 4px; --s2: 8px; --s3: 12px; --s4: 16px; --s5: 20px; --s6: 24px; --s8: 32px;
  --r-sm: 8px; --r-md: 12px; --r-lg: 16px; --r-full: 999px;
  --t-fast: 160ms cubic-bezier(0.32,0.72,0,1);
  --app-w: 480px; --topbar-h: 50px;
}
[data-theme="dark"] {
  --canvas: #0F0E0D; --surface: #1A1918; --surface-2: #232120; --surface-3: #2E2C2A;
  --ink-1: #F5F3F0; --ink-2: #B8B2AA; --ink-3: #8A857D; --ink-4: #635E58;
  --line-1: rgba(245,243,240,0.10); --line-2: rgba(245,243,240,0.18);
  --brand: #C9705F; --brand-2: #D67F6E; --brand-soft: #33201C; --brand-ink: #E8A392;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --canvas: #0F0E0D; --surface: #1A1918; --surface-2: #232120; --surface-3: #2E2C2A;
    --ink-1: #F5F3F0; --ink-2: #B8B2AA; --ink-3: #8A857D; --ink-4: #635E58;
    --line-1: rgba(245,243,240,0.10); --line-2: rgba(245,243,240,0.18);
    --brand: #C9705F; --brand-2: #D67F6E; --brand-soft: #33201C; --brand-ink: #E8A392;
  }
}
* { margin: 0; padding: 0; box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  font-family: var(--font); background: var(--canvas); color: var(--ink-1);
  line-height: 1.6; -webkit-font-smoothing: antialiased;
  padding-bottom: env(safe-area-inset-bottom);
}
a { color: inherit; text-decoration: none; }
img { display: block; max-width: 100%; }

.topbar {
  position: sticky; top: 0; z-index: 50;
  height: calc(var(--topbar-h) + env(safe-area-inset-top));
  padding: env(safe-area-inset-top) var(--s4) 0;
  display: flex; align-items: center; gap: var(--s3);
  background: var(--surface); border-bottom: 1px solid var(--line-1);
}
.topbar-logo {
  flex: 1; display: flex; align-items: center; gap: 7px;
  font-size: 18px; font-weight: 600; letter-spacing: -0.02em;
}
.topbar-logo-mark {
  width: 24px; height: 24px; border-radius: 7px; background: var(--brand);
  display: grid; place-items: center; flex-shrink: 0;
}
.topbar-logo-mark i { width: 10px; height: 10px; border-radius: 3px; background: #fff; display: block; }
.topbar-link { font-size: 14px; color: var(--ink-3); }

.wrap { max-width: var(--app-w); margin: 0 auto; padding: var(--s5) var(--s4) var(--s8); }
@media (min-width: 600px) { :root { --app-w: 520px; } }
@media (min-width: 1024px) { :root { --app-w: 560px; } }

.crumb { font-size: 12px; color: var(--ink-3); margin-bottom: var(--s3); }
.crumb a:hover { color: var(--brand); }
.tag {
  display: inline-block; padding: 2px 8px; border-radius: var(--r-sm);
  background: var(--brand-soft); color: var(--brand-ink);
  font-size: 12px; font-weight: 500; margin-bottom: var(--s3);
}
h1 { font-size: 25px; font-weight: 600; line-height: 1.35; letter-spacing: -0.02em; margin-bottom: var(--s3); }
.meta { font-size: 13px; color: var(--ink-3); display: flex; gap: var(--s3); padding-bottom: var(--s5); border-bottom: 1px solid var(--line-1); }

.post h2 { font-size: 19px; font-weight: 600; margin: var(--s6) 0 var(--s3); letter-spacing: -0.01em; }
.post h3 { font-size: 16px; font-weight: 600; margin: var(--s5) 0 var(--s2); }
.post p { font-size: 16px; line-height: 1.75; color: var(--ink-2); margin-bottom: var(--s4); overflow-wrap: anywhere; }
.post ul, .post ol { color: var(--ink-2); font-size: 16px; line-height: 1.75; margin: 0 0 var(--s4) var(--s5); }
.post li { margin-bottom: var(--s2); }
.post strong { color: var(--ink-1); font-weight: 600; }
.post blockquote {
  border-left: 3px solid var(--brand); padding: var(--s3) var(--s4);
  margin: var(--s4) 0; background: var(--surface-2); border-radius: 0 var(--r-md) var(--r-md) 0;
  color: var(--ink-2); font-size: 15px;
}
figure { margin: var(--s5) 0; }
figure img { width: 100%; height: auto; border-radius: var(--r-md); background: var(--surface-2); }
figcaption { font-size: 12px; color: var(--ink-3); margin-top: var(--s2); text-align: center; }

.card {
  display: block; background: var(--surface); border-radius: var(--r-lg);
  padding: var(--s4); margin-bottom: var(--s3);
  border: 1px solid var(--line-1); transition: transform var(--t-fast);
}
.card:hover { transform: translateY(-2px); }
.card h3 { font-size: 16px; font-weight: 600; line-height: 1.45; margin-bottom: var(--s2); overflow-wrap: anywhere; }
.card p {
  font-size: 14px; color: var(--ink-2); line-height: 1.6; margin-bottom: var(--s3);
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.card-thumb { border-radius: var(--r-md); overflow: hidden; margin-bottom: var(--s3); background: var(--surface-2); }
.card-thumb img { width: 100%; height: 180px; object-fit: cover; }
.card-meta { font-size: 12px; color: var(--ink-3); display: flex; gap: var(--s3); }

.section-title { font-size: 15px; font-weight: 600; margin: var(--s8) 0 var(--s3); color: var(--ink-2); }
.cta {
  margin-top: var(--s8); padding: var(--s6) var(--s5); text-align: center;
  background: var(--surface); border: 1px solid var(--line-1); border-radius: var(--r-lg);
}
.cta h3 { font-size: 17px; font-weight: 600; margin-bottom: var(--s2); }
.cta p { font-size: 14px; color: var(--ink-2); margin-bottom: var(--s4); }
.cta-btn {
  display: inline-block; padding: 11px 24px; border-radius: var(--r-md);
  background: var(--brand); color: #fff; font-size: 15px; font-weight: 500;
}
footer {
  border-top: 1px solid var(--line-1); padding: var(--s5) var(--s4);
  text-align: center; font-size: 12px; color: var(--ink-3);
}
.pager { display: flex; justify-content: center; gap: var(--s3); margin-top: var(--s5); flex-wrap: wrap; }
.pg {
  padding: 9px 16px; border-radius: var(--r-md); background: var(--surface);
  border: 1px solid var(--line-1); font-size: 14px; color: var(--ink-2);
}
.pg.now { background: var(--brand); color: #fff; border-color: transparent; }
.pg.off { opacity: 0.4; }
"""

FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E"
           "%3Crect width='100' height='100' rx='22' fill='%239A3B2E'/%3E"
           "%3Crect x='38' y='38' width='24' height='24' rx='6' fill='white'/%3E%3C/svg%3E")


def esc(s):
    return html.escape(str(s or ''), quote=True)


def post_url(slug):
    return '%s/blog/posts/%s.html' % (SITE_URL, slug)


def _topbar(back_href=None, back_text=None):
    back = ''
    if back_href:
        back = '<a class="topbar-link" href="%s">%s</a>' % (esc(back_href), esc(back_text or '返回'))
    return (
        '<nav class="topbar"><div class="topbar-logo">'
        '<span class="topbar-logo-mark"><i></i></span>%s</div>%s</nav>'
    ) % (SITE_NAME, back)


def _head(title, description, url, extra='', image=''):
    # 图片站的图片本身就是内容主力，noimageindex 会让整站失去图片搜索入口。
    # 社区图已经过占位图过滤（build_data.py 剔除了 171 张违规提示图），
    # 页面里的图都是正常内容，值得被索引。
    og_image = ''
    twitter_image = ''
    if image:
        og_image = '<meta property="og:image" content="%s">\n' % esc(image)
        twitter_image = ('<meta name="twitter:image" content="%s">\n' % esc(image))
    return (
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">\n'
        '<title>%s</title>\n'
        '<meta name="description" content="%s">\n'
        '<meta name="robots" content="index, follow">\n'
        '<link rel="canonical" href="%s">\n'
        '<meta property="og:type" content="%s">\n'
        '<meta property="og:title" content="%s">\n'
        '<meta property="og:description" content="%s">\n'
        '<meta property="og:url" content="%s">\n'
        '<meta property="og:site_name" content="%s">\n'
        '%s%s'
        '<meta name="twitter:card" content="summary_large_image">\n'
        '<link rel="icon" href="%s">\n%s'
    ) % (esc(title), esc(description), esc(url),
         extra or 'website', esc(title), esc(description), esc(url), SITE_NAME,
         og_image, twitter_image, FAVICON, '')


def _ld_article(post, url):
    import json
    data = {
        '@context': 'https://schema.org',
        '@type': 'Article',
        'headline': post['title'],
        'description': post['description'],
        'datePublished': post['date'],
        'dateModified': post['date'],
        'author': {'@type': 'Organization', 'name': SITE_NAME},
        'publisher': {'@type': 'Organization', 'name': SITE_NAME, 'url': SITE_URL},
        'mainEntityOfPage': url,
    }
    if post.get('image'):
        data['image'] = post['image']
    return '<script type="application/ld+json">%s</script>' % json.dumps(data, ensure_ascii=False)


def _figure(img, caption=''):
    cap = '<figcaption>%s</figcaption>' % esc(caption) if caption else ''
    return (
        '<figure><img src="%s" width="%d" height="%d" loading="lazy" alt="%s" />%s</figure>'
    ) % (esc(img['url']), img['w'], img['h'], esc(caption or SITE_NAME + ' 社区图片'), cap)


def insert_figures(body, images, caption):
    """把图片插进正文。

    不让模型输出 img 标签是有意的：模型会编造图片地址，或者干脆不插图。
    由代码按段落位置插，才能保证插的就是刚才给它看过的那几张图。
    """
    if not images:
        return body
    parts = re.split(r'(?=<h2[\s>])', body)
    if len(parts) < 2:
        parts = re.split(r'(?=<p>)', body)
    slots = []
    step = max(1, len(parts) // (len(images) + 1))
    for i in range(len(images)):
        idx = min(len(parts) - 1, step * (i + 1))
        slots.append(idx)
    for offset, (i, img) in enumerate(zip(slots, images)):
        parts.insert(i + offset + 1, _figure(img, caption))
    return ''.join(parts)


def render_post(post, related):
    url = post_url(post['slug'])
    ld = _ld_article(post, url)
    rel = ''
    if related:
        items = ''.join(
            '<a class="card" href="%s"><h3>%s</h3><p>%s</p>'
            '<div class="card-meta"><span>%s</span></div></a>'
            % (esc(post_url(r['slug'])), esc(r['title']), esc(r['description']), esc(r['date']))
            for r in related
        )
        rel = '<h2 class="section-title">接着看</h2>%s' % items

    return (
        '<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n%s%s\n<style>%s</style>\n</head>\n<body>\n'
        '%s\n<main class="wrap">\n'
        '<div class="crumb"><a href="%s">%s</a> / <a href="%s/blog/">分享</a></div>\n'
        '<span class="tag">%s</span>\n<h1>%s</h1>\n'
        '<div class="meta"><span>%s</span><span>阅读约 %d 分钟</span></div>\n'
        '<article class="post">%s</article>\n%s\n'
        '<div class="cta"><h3>进入%s看更多</h3><p>社区里还有更多真实分享，随手就能翻。</p>'
        '<a class="cta-btn" href="%s">打开%s</a></div>\n'
        '</main>\n<footer>© %s</footer>\n</body>\n</html>\n'
    ) % (
        _head(post['title'] + ' · ' + SITE_NAME, post['description'], url, 'article',
              post.get('image') or ''),
        ld, THEME_CSS,
        _topbar(SITE_URL + '/blog/', '全部分享'),
        esc(SITE_URL), SITE_NAME, esc(SITE_URL),
        esc(post.get('category') or '分享'), esc(post['title']),
        esc(post['date']), max(1, round(post.get('words', 800) / 400)),
        post['body'], rel,
        SITE_NAME, esc(APP_URL), SITE_NAME,
        SITE_NAME,
    )


def render_index(posts, page, total_pages, total_count=0):
    cards = []
    for p in posts:
        thumb = ''
        if p.get('image'):
            thumb = ('<div class="card-thumb"><img src="%s" loading="lazy" alt="%s" /></div>'
                     % (esc(p['image']), esc(p['title'])))
        cards.append(
            '<a class="card" href="%s">%s<h3>%s</h3><p>%s</p>'
            '<div class="card-meta"><span>%s</span><span>%s</span></div></a>'
            % (esc(post_url(p['slug'])), thumb, esc(p['title']),
               esc(p['description']), esc(p.get('category') or '分享'), esc(p['date']))
        )

    pager = ''
    if total_pages > 1:
        def href(n):
            return SITE_URL + '/blog/' if n == 1 else '%s/blog/page/%d.html' % (SITE_URL, n)
        nums = []
        for n in range(1, total_pages + 1):
            if n == page:
                nums.append('<span class="pg now">%d</span>' % n)
            else:
                nums.append('<a class="pg" href="%s">%d</a>' % (href(n), n))
        prev = ('<a class="pg" href="%s">上一页</a>' % href(page - 1)) if page > 1 else '<span class="pg off">上一页</span>'
        nxt = ('<a class="pg" href="%s">下一页</a>' % href(page + 1)) if page < total_pages else '<span class="pg off">下一页</span>'
        pager = '<div class="pager">%s%s%s</div>' % (prev, ''.join(nums), nxt)

    title = '%s 社区分享' % SITE_NAME + (' 第%d页' % page if page > 1 else '')
    desc = '%s 是一个图片分享社区，这里持续更新社区里的分享内容。' % SITE_NAME
    url = SITE_URL + '/blog/' if page == 1 else '%s/blog/page/%d.html' % (SITE_URL, page)
    # 分页页用自引用 canonical，不再 noindex。
    # 早先的做法是 noindex + 不进 sitemap，但列表页本身内容很薄，
    # 全部权重压在这一页反而抓不到后面那些有实际内容的文章页。
    # 现在每页都可索引，各自 canonical 指向自己。
    total_posts = total_count if total_count else len(posts)

    return (
        '<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n%s%s<style>%s</style>\n</head>\n<body>\n'
        '%s\n<main class="wrap">\n<h1>%s</h1>\n'
        '<p style="font-size:14px;color:var(--ink-3);margin:8px 0 20px">共 %d 篇分享</p>\n'
        '%s\n%s\n'
        '<div class="cta"><h3>进入%s看更多</h3><p>打开社区，翻看更多真实分享。</p>'
        '<a class="cta-btn" href="%s">打开%s</a></div>\n'
        '</main>\n<footer>© %s</footer>\n</body>\n</html>\n'
    ) % (
        _head(title, desc, url, 'website', (posts[0].get('image') if posts else '') or ''),
        '', THEME_CSS,
        _topbar(SITE_URL + '/'),
        esc(title), total_posts, ''.join(cards), pager,
        SITE_NAME, esc(APP_URL), SITE_NAME, SITE_NAME,
    )


def render_sitemap(posts, total_pages=1):
    rest = ''.join(
        '  <url><loc>%s</loc><lastmod>%s</lastmod><changefreq>monthly</changefreq>'
        '<priority>0.8</priority></url>\n' % (esc(post_url(p['slug'])), esc(p['date']))
        for p in posts
    )
    # 分页页也进 sitemap。它们各自 self-canonical，能被直接抓到，
    # 不必只靠上一页的翻页链接层层传递权重。
    newest = posts[0]['date'] if posts else ''
    pages = ''.join(
        '  <url><loc>%s/blog/page/%d.html</loc><lastmod>%s</lastmod>'
        '<changefreq>weekly</changefreq><priority>0.6</priority></url>\n'
        % (SITE_URL, n, esc(newest))
        for n in range(2, total_pages + 1)
    )
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            '  <url><loc>%s/</loc><changefreq>weekly</changefreq><priority>1.0</priority></url>\n'
            '  <url><loc>%s/blog/</loc><changefreq>daily</changefreq><priority>0.9</priority></url>\n'
            '%s%s</urlset>\n' % (SITE_URL, SITE_URL, pages, rest))
