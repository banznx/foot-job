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


def build_schema(item, content, site_url):
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
    url = site_url('/post/%s/' % content['slug'])

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
    imgs = [im for im in (_get(item, 'images') or [])][:8]
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
             'item': site_url('/tag/%s/' % config.TAG_SLUGS.get(tag, 'zonghe'))},
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

    return {'@context': 'https://schema.org', '@graph': graph}


def assemble(item, ai, keywords_for_tag=None, index=None, pool=None,
             site_url=None, build_links=True, allowed_slugs=None):
    """把五个阶段的产物合成一条完整的结构化内容。

    allowed_slugs: 允许被内链指向的已生成页面 slug 集合。
    传None 时内链会被清空 —— 宁可没有内链，也不要链到 404。
    """
    site_url = site_url or config.site_url
    tag = (item.tags or ['综合'])[0]
    kws = keywords_for_tag or []

    # 阶段 2：标题与描述
    meta = rw.generate_meta(item, ai, kws)

    # 阶段 3：正文改写扩写
    body_res = rw.rewrite_body(item, ai, kws)
    body = body_res['body']

    slug = rw.make_slug(item)

    content = {
        'seed_id': item.seed_id,
        'post_id': item.meta.get('post_id'),
        'slug': slug,
        'tag': tag,
        'tag_slug': config.TAG_SLUGS.get(tag, 'zonghe'),
        'meta_title': meta['meta_title'],
        'meta_description': meta['meta_description'],
        'tags': meta['tags'] or [tag],
        'body': body,
        'author': item.meta.get('author') or '社区用户',
        'published': item.published,
        'images': (item.images or [])[:config.PIPELINE['MAX_IMG_PER_PAGE']],
        'image_total': item.meta.get('image_count', len(item.images or [])),
        'metrics': item.metrics,
        'generated_at': int(time.time() * 1000),
        'by_ai': bool(meta.get('by_ai') and body_res.get('by_ai')),
        # === SEO 页身份标记（与真实帖子解耦的关键）===
        # 这些字段让页面、schema、页脚都能明确声明
        # 「这是主题整理页，不是某篇真实帖子的镜像」
        'is_seo_page': True,
        'notice': config.CONTENT_KIND['NOTICE'],
        'notice_short': config.CONTENT_KIND['NOTICE_SHORT'],
        'cta_text': config.CONTENT_KIND['CTA_TEXT'],
        'source_post_id': item.meta.get('post_id'),
    }

    # 阶段 4：内部链接
    if build_links and index and pool and allowed_slugs:
        content['internal_links'] = links_mod.suggest_links(
            item, pool, index, allowed_slugs=allowed_slugs)
        content['related'] = links_mod.cluster_related(
            item, pool, index, allowed_slugs=allowed_slugs)
    else:
        content['internal_links'] = []
        content['related'] = []

    # 阶段 5：结构化数据
    content['schema'] = build_schema(item, content, site_url)
    content['url'] = site_url('/post/%s/' % slug)
    content['fingerprint'] = fingerprint(item, content)

    return content


def fingerprint(item, content):
    """内容指纹：源数据 + 生成结果的哈希。

    用途是幂等：指纹没变说明这次跑出来的东西和上次一样，
    不需要重新提交 commit（避免仓库被无意义的空提交刷屏，
    也避免 Actions 每次都触发 Pages 重新构建）。
    """
    meta = _get(item, 'meta') or {}
    src = '%s|%s' % (_get(item, 'seed_id'),
                     (meta or {}).get('hit', 0))
    gen = '%s|%s|%s' % (content['meta_title'], content['meta_description'],
                        content['body'])
    return hashlib.md5((src + '|' + gen).encode('utf-8')).hexdigest()


def _iso(ms):
    try:
        import datetime
        return datetime.datetime.utcfromtimestamp(ms / 1000.0).strftime(
            '%Y-%m-%dT%H:%M:%SZ')
    except Exception:
        return None


def _zh_len(text):
    """中文字数：汉字按 1 个字算，英文按词算，避免 wordCount 虚高。"""
    import re
    if not text:
        return 0
    cjk = len(re.findall(r'[\u4e00-\u9fa5]', text))
    words = len(re.findall(r'[a-zA-Z]+', text))
    return cjk + words
