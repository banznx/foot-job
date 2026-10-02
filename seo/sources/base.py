# -*- coding: utf-8 -*-
"""
数据源抽象层。

系统支持两类数据源，两条通道最终汇合成同一种 `SeedItem` 结构，
下游流水线不关心内容从哪来：

  1. 站内帖子元数据与正文  —— LocalPostSource（读posts2/*.json）
  2. 第三方 AI API         —— AiKeywordSource（做关键词扩展 / 选题建议）

新增数据源只需实现 `Source.fetch()` 返回 `SeedItem` 列表。
"""

import re

from .. import config


class SeedItem(object):
    """一条待加工的原始素材。"""

    def __init__(self, seed_id, kind, title, body='', tags=None,
                 meta=None, images=None, metrics=None, published=None):
        self.seed_id = seed_id     # 唯一且稳定，用于幂等去重
        self.kind = kind           # 'post' | 'keyword' | 'topic'
        self.title = title
        self.body = body
        self.tags = tags or []
        self.meta = meta or {}     # 附加信息（作者、浏览量…）
        self.images = images or []
        self.metrics = metrics or {}
        self.published = published  # 发布时间戳（毫秒）

    def to_dict(self):
        return {
            'seed_id': self.seed_id, 'kind': self.kind,
            'title': self.title, 'body': self.body, 'tags': self.tags,
            'meta': self.meta, 'images': self.images,
            'metrics': self.metrics, 'published': self.published,
        }

    def __repr__(self):
        return '<SeedItem %s %r>' % (self.kind, self.title[:20])


class Source(object):
    name = 'base'

    def fetch(self, limit=None):
        raise NotImplementedError


# ============================================================
# 数据源 1：站内帖子
# ============================================================

class LocalPostSource(Source):
    """读取 posts2/*.json。

    两个必须注意的坑（都踩过）：
      1. 部分文件带 UTF-8 BOM，必须用 utf-8-sig 读，否则 JSONDecodeError。
      2. 有一个文件内容是 JSON 数组而不是对象，必须判类型后跳过。
    """

    name = 'local_posts'

    def __init__(self, posts_dir=None, images_prefix='images/downloaded_posts_images/'):
        self.posts_dir = posts_dir or (config.ROOT + '/posts2')
        self.images_prefix = images_prefix

    def fetch(self, limit=None, tag=None):
        import glob
        import io
        import json

        files = sorted(glob.glob(self.posts_dir + '/*.json'))
        items = []
        for path in files:
            try:
                with io.open(path, encoding='utf-8-sig') as f:
                    d = json.load(f)
            except Exception:
                continue
            if not isinstance(d, dict):
                continue

            title = (d.get('title') or '').strip()
            if not title:
                continue

            tags = self._extract_tags(title)
            if tag and tag not in tags:
                continue

            pid = d.get('postID')
            u = d.get('user') or {}
            items.append(SeedItem(
                seed_id='post-%s' % pid,
                kind='post',
                title=title,
                body=(d.get('detail') or '').strip(),
                tags=tags,
                meta={
                    'post_id': pid,
                    'author': u.get('nick') or '匿名',
                    'author_level': u.get('level'),
                    'identity': u.get('identityTitle') or '',
                    'comment_count': d.get('commentCount') or 0,
                    'hit': d.get('hit') or 0,
                    'praise': d.get('praise') or 0,
                    'image_count': len(d.get('images') or []),
                },
                images=[self.images_prefix + str(pid) + '_' +
                        str(u2).split('/')[-1].split('?')[0]
                        for u2 in (d.get('images') or [])],
                metrics={
                    'hit': d.get('hit') or 0,
                    'comment': d.get('commentCount') or 0,
                    'praise': d.get('praise') or 0,
                },
                published=d.get('createTime') or 0,
            ))

        if limit:
            items = items[:limit]
        return items

    @staticmethod
    def _extract_tags(title):
        """分类藏在标题前缀的【】里，不是 tagid。"""
        tags = []
        for name, pat in config.TAG_PATTERNS:
            if re.search(pat, title):
                tags.append(name)
        return tags or ['综合']


# ============================================================
# 数据源 2：第三方 AI API
# ============================================================

class AiKeywordSource(Source):
    """调第三方 AI API 做关键词扩展与选题建议。

    为什么不直接让 AI 写正文，而是先做选题：
      AI 编出来的关键词如果没人搜，写得再好也是自嗨。
      先让它基于站内真实标题词做扩写与聚类，再用热度数据排序，
      选出来的题至少是「站内确实有内容」+「读起来像有人会搜」的交集。
    """

    name = 'ai_keywords'

    def __init__(self, client):
        self.client = client

    def fetch(self, limit=None, corpus=None):
        """corpus: [(词, 频次)]，返回 SeedItem(kind='keyword')。"""
        corpus = corpus or []
        if not corpus:
            return []
        items = []
        for kw, freq, cluster in corpus:
            if not kw or len(kw) < config.PIPELINE['MIN_KEYWORD_LEN']:
                continue
            items.append(SeedItem(
                seed_id='kw-%s' % _hash(kw),
                kind='keyword',
                title=kw,
                tags=[cluster] if cluster else [],
                meta={'freq': freq, 'cluster': cluster},
            ))
        if limit:
            items = items[:limit]
        return items


def _hash(s):
    import hashlib
    return hashlib.md5(s.encode('utf-8')).hexdigest()[:10]
