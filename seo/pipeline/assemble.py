# -*- coding: utf-8 -*-
"""
阶段 5：产出结构化内容。

一条 SEO 内容的完整产物（对应需求里的"结构化内容"）：
    meta_title / meta_description / slug / tags / schema（JSON-LD）
    + body（改写扩写后的正文）
    + internal_links（内链建议）
    + quality（质量分与各项检测结果）

schema 用 JSON-LD 而不是 Microdata：Google 已明确支持且更易维护，
搜索引擎能直接解析成知识图谱节点。
"""

import hashlib
import re
import time

from .. import config
from . import links as links_mod
from . import rewrite as rw
from .keywords import strip_tag


def _get(item, key, default=None):
    """同时支持对象属性访问和 dict 取值。

    流水线里有两类 item：SeedItem（对象）和关键词页的 dict。
    早期假设只有对象，关键词页一接进来就炸了。
    """
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def build_schema(item, content, site_url, faq=None):
    """产出 JSON-LD 结构化数据。

    节点构成：
      - Article         主题整理页本体（**不用 BlogPosting**，
                        避免把 AI 产出的内容伪装成社区真实发帖）
      - ImageObject     提供图片收录机会（本站图片量大，是主要流量口）
      - BreadcrumbList  搜索结果里把裸 URL 换成可点击面包屑
      - WebSite / Organization  站点主体

    item 既可以是 SeedItem 对象，也可以是关键词页用的 dict
    （关键词页刻意不带 post_id / 用户信息，与真实帖子解耦）。
    """
    tags = _get(item, 'tags') or ['综合']
    meta = _get(item, 'meta') or {}
    tag = tags[0]
    url = config.page_url(content['slug'])

    graph = []

    # SEO 页用 Article 而不是 BlogPosting：
    # 语义上这是「关于某个主题的整理文章」，
    # 不是某一篇用户帖子的镜像。用 BlogPosting 会让搜索引擎
    # 以为这是社区里真实存在的一篇帖子，与页面上的实际内容不符。
    node_type = config.CONTENT_KIND['SCHEMA_TYPE']

    article = {
        '@type': node_type,
        '@id': url + '#article',
        'isPartOf': {'@id': site_url('/') + '#website'},
        'mainEntityOfPage': {'@type': 'WebPage', '@id': url},
        'headline': content['meta_title'][:60],
        'description': content['meta_description'],
        'inLanguage': config.SITE['LANG'],
        'url': url,
        # about 指向主题本身，说明这篇讲的是什么话题
        'about': {
            '@type': 'Thing',
            'name': tag,
            'description': config.TAG_INTENT.get(tag, '社区内容'),
        },
        'articleSection': tag,
        'keywords': ', '.join(content['tags']),
        'wordCount': _zh_len(content['body']),
    }
    published = _get(item, 'published')
    if published:
        iso = _iso(published)
        article['datePublished'] = iso
        article['dateModified'] = iso
    # 由 AI 整理生成，署名站点而不是某个用户——
    # 避免把AI 产出的内容伪装成社区用户的真实发帖
    article['author'] = {
        '@type': 'Organization',
        'name': config.SITE['BRAND'],
        'url': site_url('/'),
    }
    graph.append(article)

    # 只声明前 8 张：Google 展示的图数量有限，
    # 全量塞进去只会让 structured data 臃肿且无额外收益。
    #
    # 从 content 取而不是从 item 取：关键词页与引流文用的是「伪item」
    # （刻意不携带真实帖子的图片字段），图片只存在 content 里。
    # 早前从 item 取导致这些页面的 ImageObject 全部缺失，
    # 图片白白浪费了被 Google Images 收录的机会。
    imgs = [im for im in (content.get('images') or [])][:8]
    if imgs:
        graph.append({
            '@type': 'ImageObject',
            '@id': url + '#gallery',
            'contentUrl': site_url('/' + imgs[0]),
            'thumbnailUrl': site_url('/' + imgs[0]),
            'encodingFormat': 'image/jpeg',
            'width': 1080,
            'height': 1440,
            'caption': content['meta_title'],
            'license': site_url('/'),
            # 署名站点而非用户：图片来自社区，页面是主题整理页
            'creditText': config.SITE['BRAND'],
            'acquireLicensePage': site_url('/'),
            'associatedMedia': [{
                '@type': 'ImageObject',
                'contentUrl': site_url('/' + im),
                'encodingFormat': 'image/jpeg',
            } for im in imgs],
        })

    graph.append({
        '@type': 'BreadcrumbList',
        '@id': url + '#breadcrumb',
        'itemListElement': [
            {'@type': 'ListItem', 'position': 1, 'name': '首页',
             'item': site_url('/')},
            {'@type': 'ListItem', 'position': 2, 'name': tag,
             'item': config.tag_url(tag)},
            {'@type': 'ListItem', 'position': 3, 'name': content['meta_title'][:40],
             'item': url},
        ],
    })

    graph.append({
        '@type': 'WebSite',
        '@id': site_url('/') + '#website',
        'url': site_url('/'),
        'name': config.SITE['BRAND'],
        'description': '%s —— 按推荐、最新、热门浏览的社区图片内容' % config.SITE['BRAND'],
        'inLanguage': config.SITE['LANG'],
        'publisher': {'@id': site_url('/') + '#org'},
    })
    graph.append({
        '@type': 'Organization',
        '@id': site_url('/') + '#org',
        'name': config.SITE['BRAND'],
        'url': site_url('/'),
    })

    # FAQPage：从正文里抽问答对。
    # 为什么值得做：Google 的"其他人还问了"直接读 FAQPage 结构化数据，
    # 命中的话能多占一个位置。这是文本内容页少有的、能靠结构化
    # 直接换来展示位的手段。
    # 优先用外部传入的 FAQ（generate_faq 单独请求生成的），
    # 没有才从正文里抽。正文抽取作为兜底。
    faq = faq or _extract_faq(content.get('body', ''))
    if faq:
        graph.append({
            '@type': 'FAQPage',
            '@id': url + '#faq',
            'mainEntity': [{
                '@type': 'Question',
                'name': q,
                'acceptedAnswer': {'@type': 'Answer', 'text': a},
            } for q, a in faq],
        })

    return {'@context': 'https://schema.org', '@graph': graph}


def _extract_faq(body, limit=4):
    """从正文里识别问答对。

    识别两种写法（AI 生成内容里都常见）：
      1. 显式问答：「问：xxx  答：yyy」/「Q: / A:」
      2. 设问句：以问号结尾的短句，后面跟一段回答

    识别不到就返回空列表，不硬造 ——
    Google 会惩罚「schema 声明了 FAQ 但页面里没有对应问答」的情况，
    那种情况比不做 FAQ 更糟。
    """
    faq = []

    # 写法 1：显式问答。段落内的换行也算分隔，所以用[\s\S]而不是 .
    pattern = (r'(?:问|Q|问题)\s*[:：]\s*(.{4,60}?)\s*[）)]?\s*'
               r'(?:答|A|回答|答案)\s*[:：]\s*(.{10,300}?)'
               r'(?=\n\s*\n|\n\s*(?:问|Q|问题)\s*[:：]|$)')
    for m in re.finditer(pattern, body, re.S):
        q, a = m.group(1).strip(), m.group(2).strip()
        q = re.sub(r'\s+', ' ', q)
        a = re.sub(r'\s+', ' ', a)
        if q and a:
            faq.append((q, a))
    if faq:
        return faq[:limit]

    # 写法 2：设问句 + 下一段
    paras = [p.strip() for p in body.split('\n\n') if p.strip()]
    for i, p in enumerate(paras[:-1]):
        if p.endswith(('？', '?')) and 6 <= len(p) <= 50 and paras[i + 1]:
            faq.append((re.sub(r'\s+', ' ', p.rstrip('？?')),
                        re.sub(r'\s+', ' ', paras[i + 1])[:280]))
            if len(faq) >= limit:
                break
    return faq[:limit]


def _iso(ms):
    """毫秒时间戳 -> ISO 8601（schema 要求这个格式）。"""
    if not ms:
        return None
    import datetime
    try:
        return datetime.datetime.utcfromtimestamp(
            ms / 1000.0).strftime('%Y-%m-%dT%H:%M:%SZ')
    except Exception:
        return None


def _zh_len(text):
    """中文字数：汉字按 1 个字算，英文按词算。

    为什么不用 len()：len() 把标点和空白也算进去，
    wordCount 会虚高，Google 判定内容长度时会被误导。
    """
    import re as _re
    if not text:
        return 0
    cjk = len(_re.findall(r'[\u4e00-\u9fa5]', text))
    words = len(_re.findall(r'[a-zA-Z]+', text))
    return cjk + words


def fingerprint(item, content):
    """内容指纹：源数据 + 生成结果的哈希。

    用途是幂等：指纹没变说明这次跑出来的东西和上次一样，
    不需要重新提交 commit（避免仓库被无意义的空提交刷屏，
    也避免 Actions 每次都触发 Pages 重新构建）。
    """
    meta = _get(item, 'meta') or {}
    src = '%s|%s' % (_get(item, 'seed_id'), meta.get('hit', 0))
    gen = '%s|%s|%s' % (content['meta_title'], content['meta_description'],
                        content['body'])
    return hashlib.md5((src + '|' + gen).encode('utf-8')).hexdigest()
