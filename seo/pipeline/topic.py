# -*- coding: utf-8 -*-
"""
关键词页生成器：SEO 内容与真实帖子**彻底解耦**。

设计动因（需求方明确要求）：
    「SEO 的帖子跟实际的帖子数据是解耦的，SEO 是引导进站的用途」
    「AI 产出的帖子也要跟用户真实浏览的帖子做区分」

所以这里的生产单位不是"一篇真实帖子的镜像"，而是
    **关键词 × 内容角度**
同一个关键词可以从 7 个角度各写一篇，产出 7 个不同 URL。
这带来两个直接结果：
  1. 页面数量不再受真实帖子数（2340）限制，可以持续扩张
  2. 同一关键词下形成内容集群，主题权威度比单篇更容易建立

而页面上必须有明确的身份声明（见 render/page.py 的 notice 区块），
让读者和搜索引擎都知道：这是主题整理页，不是社区里的真实发帖。
"""

import time

from .. import config
from . import rewrite as rw
from .keywords import strip_tag

# 关键词页的写作提示词。
# 注意：这里**不提供任何真实帖子的正文**，
# 刻意切断与用户原创内容的耦合——SEO 页讲的是这个主题本身，
# 不复述、不搬运任何一篇具体帖子。
TOPIC_PROMPT = """你为一个图片分享社区的「主题整理页」写内容。

目标读者：搜索「{keyword}」的人。他们想快速了解这个主题，
所以要给的是**有信息量的整理**，不是营销文案。

内容角度：{angle_desc}
分类：{tag}（{intent}）

硬性要求：
1. 总长度 {lo}-{hi} 个汉字，分3-4 段，段间空行
2. 只讲这个主题本身的常识、看法、建议、选择依据。
   **绝对不要提及、引用或改写任何具体的用户帖子、用户名、发布时间**
3. **不要编造事实**。不确定的一律用「通常」「大多」「一般」这类留余地的说法
4. 用词中性、健康。不得出现低俗、暧昧、擦边或任何违规暗示的词
5. 不要出现这些词：json、api、github、部署、缓存、脚本、接口、
   构建、仓库、服务器、数据库、算法
6. 结尾不要写「快来浏览」「点击查看」这类召唤语

只输出 JSON：{{"title":"20字以内的标题","description":"60-110字的摘要","body":"正文，段落用\\n\\n分隔","tags":["标签1","标签2"]}}"""


def build_topic_item(keyword, angle_key, angle_desc):
    """构造一个关键词页的伪 SeedItem。

    刻意不带 post_id、不带真实帖子图片、不带用户昵称——
    保持与真实帖子的解耦。meta['slug_seed'] 用
    「关键词+角度」而不是 postID，这是页面能无限扩张的前提。
    """
    tag = rw.item_tags_or_default(keyword)[0]
    seed = 'kw::%s::%s' % (keyword, angle_key)
    return {
        'seed_id': seed,
        'keyword': keyword,
        'angle': angle_key,
        'angle_desc': angle_desc,
        'name': keyword,
        'body': '',
        'tags': [tag],
        'meta': {
            'slug': rw.topic_slug(keyword, angle_key),
            'slug_seed': seed,
            'keyword': keyword,
            'angle': angle_key,
            'image_count': 0,
        },
        'images': [],
        'metrics': {},
        'published': int(time.time() * 1000),
    }


def generate_topic(topic, ai, site_url=None):
    """生成一篇关键词页内容（纯 AI 产出，与真实帖子无关）。"""
    keyword = topic['keyword']
    tag = topic['tags'][0]
    lo, hi = (config.PIPELINE['TARGET_DETAIL_LEN'],
              config.PIPELINE['MAX_DETAIL_LEN'])

    result = {
        'meta_title': '%s%s' % (keyword, _angle_suffix(topic['angle'])),
        'meta_description': '围绕「%s」的%s，%s' % (
            keyword, _angle_label(topic['angle']),
            config.TAG_INTENT.get(tag, '内容整理')),
        'tags': [tag, keyword],
        'body': '',
        'by_ai': False,
    }

    if not ai.available:
        result['body'] = _template_body(topic)
        return result

    try:
        data = ai.chat_json([
            {'role': 'system', 'content': '你是内容编辑，只输出 JSON。'},
            {'role': 'user', 'content': TOPIC_PROMPT.format(
                keyword=keyword,
                angle_desc=topic['angle_desc'],
                tag=tag,
                intent=config.TAG_INTENT.get(tag, '社区内容'),
                lo=lo, hi=hi,
            )},
        ], max_tokens=2000)
    except Exception:
        result['body'] = _template_body(topic)
        return result

    if not isinstance(data, dict) or not data.get('body'):
        result['body'] = _template_body(topic)
        return result

    body = rw._clean_body(data.get('body', ''))
    result.update({
        'meta_title': rw._clip(data.get('title') or result['meta_title'], 30),
        'meta_description': rw._clip(
            data.get('description') or result['meta_description'], 120),
        'tags': [rw._clip(t, 8) for t in (data.get('tags') or [])][:5]
                or result['tags'],
        'body': body,
        'by_ai': True,
    })
    return result


def assemble_topic(topic, gen, site_url=None):
    """把关键词页的生成结果组装成完整结构化内容。"""
    from .assemble import build_schema, fingerprint

    site_url = site_url or config.site_url
    tag = topic['tags'][0]
    slug = topic['meta']['slug']

    content = {
        'seed_id': topic['seed_id'],
        'post_id': None,              # 没有对应的真实帖子
        'slug': slug,
        'tag': tag,
        'tag_slug': config.TAG_SLUGS.get(tag, 'zonghe'),
        'meta_title': gen['meta_title'],
        'meta_description': gen['meta_description'],
        'tags': gen['tags'],
        'body': gen['body'],
        'keyword': topic['keyword'],
        'angle': topic['angle'],
        'author': config.SITE['BRAND'],
        'published': topic['published'],
        'images': [],
        'image_total': 0,
        'metrics': {},
        'generated_at': int(time.time() * 1000),
        'by_ai': gen.get('by_ai', False),
        # === 身份标记：与真实帖子区分 ===
        'is_seo_page': True,
        'notice': config.CONTENT_KIND['NOTICE'],
        'notice_short': config.CONTENT_KIND['NOTICE_SHORT'],
        'cta_text': config.CONTENT_KIND['CTA_TEXT'],
        'source_post_id': None,       # 明确没有来源帖子
    }
    content['url'] = config.page_url(slug)
    content['schema'] = build_schema(topic, content, site_url)
    content['fingerprint'] = fingerprint(topic, content)
    return content


# ============================================================
# 辅助
# ============================================================

def plan_topics(keywords, per_keyword_angles=3, rotate=0):
    """规划本轮要生成哪些（关键词, 角度）组合。

    rotate 让不同批次从不同角度开始，
    避免第一批就把某个关键词的角度全部用光。
    """
    plan = []
    angles = config.TOPIC_ANGLES
    n = len(angles)
    for kw in keywords:
        for i in range(per_keyword_angles):
            a = angles[(rotate + i) % n]
            plan.append((kw, a[0], a[1]))
    return plan


def _angle_label(key):
    return {
        'beginner': '入门整理', 'tips': '技巧汇总', 'mistake': '误区盘点',
        'why': '成因分析', 'compare': '风格对比', 'story': '场景记录',
        'qa': '问答整理',
    }.get(key, '内容整理')


def _angle_suffix(key):
    return {
        'beginner': '入门指南', 'tips': '实用技巧', 'mistake': '常见误区',
        'why': '为什么受欢迎', 'compare': '风格对比', 'story': '场景记录',
        'qa': '常见问答',
    }.get(key, '介绍')


def _template_body(topic):
    """无 AI 时的兜底正文。结构完整，不编造具体内容。"""
    kw = topic['keyword']
    tag = topic['tags'][0]
    return ('\n\n'.join([
        '「%s」是%s里常被提到的话题之一。这一页把这个主题的基本情况'
        '整理出来，方便第一次接触的人快速了解。' % (kw, tag),
        '%s属于%s分类，站内有不少相关内容。这一分类的内容大多围绕'
        '日常记录与兴趣分享展开，看的人通常是想找同好或者找点参考。'
        % (kw, tag),
        '想看社区里的真实内容，可以从页面下方的入口进入，'
        '那里有更多同分类的帖子。',
    ]))
