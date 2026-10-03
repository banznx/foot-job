# -*- coding: utf-8 -*-
"""
引流文章生成：每小时一篇，产出到独立文件夹 `promo/`。

需求方原话：
> 「每小时产出一篇新的引流文章 html 静态（单独文件夹托管），
> 可以根据现有的文章随机拿一篇来改写洗稿或者添加内容，
> 也可以全新自定义创作」

三种来源模式，按可用性择一：

  1. **rewrite（改写洗稿）**
     随机抽一篇站内帖子，让 AI 换一个视角重写。
     注意是"换视角"不是"复制粘贴"——原帖大多只有十几字，
     真正值钱的是图片，所以正文必须重新写。

  2. **extend（扩写补充）**
     源帖有正文时，在原文基础上补充展开。
     没有正文就退回 fresh。

  3. **fresh（全新创作）**
     不依赖任何源帖，围绕关键词自由创作。
     这是引流文的主力模式 —— 站内正文中位数只有 13 字，
     770/2340篇是空的，靠改写撑不起内容池。

**关键约束：不能是低质内容农场。**
每小时一篇 = 每天 24 篇，一年 8000+ 篇。如果只是机械改写，
搜索引擎会认定为低质内容，整站权重下跌。
所以每篇都要求：有信息增量、有人类可读的节奏、不编造事实。
"""

import hashlib
import random
import re
import time

from .. import config
from . import imgpool
from . import rewrite as rw
from .keywords import strip_tag

# ============================================================
# 提示词
# ============================================================

REWRITE_PROMPT = """你为一个图片社区写一篇「主题文章」，用于吸引读者进站。

参考素材（来自社区真实内容）：
- 原帖标题：{title}
- 原帖正文：{body}
- 分类：{tag}（{intent}）
- 互动数据：{hit} 次浏览、{comment} 条评论

写作要求：
1. **换视角重写**，不要逐句翻译或复述原帖。原帖信息很少，
   你要做的是围绕「{tag}」这个主题写一篇有信息量的原创文章
2. 可以写的内容：这类内容的常见主题、读者的关注点、
   选择建议、常见疑问、生活场景描写
3. **绝对不要编造画面细节**。这是最容易出错的地方：
   源帖几乎只有一行标题，你并不知道照片里具体有什么。
   所以**不要写"照片里出现了…""可以看到…""画面中…"** 这类描述，
   要写就写「这类内容通常…」「大多数情况下…」这类
   针对主题本身的通用讨论
4. 用词中性、健康。不得出现低俗、暧昧、擦边或任何违规暗示的词
5. 不要出现这些词：json、api、github、部署、缓存、脚本、接口、
   构建、仓库、服务器、数据库、算法

**篇幅是硬要求**：
- 正文必须达到 {lo}-{hi} 个汉字，至少 5 段
- 每段 3-4 句，不要只写两三句就收尾
- 内容要展开讲透，不要写成简短的片段

**结尾必须有 2-3 组问答**，用这两种写法之一：
- 设问句独立成段，例：「想知道更多细节？」（以问号结尾）
- 显式问答，例：「问：xxx  答：yyy」
问答是为了进搜索结果的「其他人还问了」，不能省

只输出 JSON：{{"title":"20字以内的标题，含关键词","description":"70-110字的摘要","body":"正文，段落用\\n\\n分隔","tags":["标签1","标签2","标签3"]}}"""

FRESH_PROMPT = """你为一个图片社区写一篇全新的原创文章，用于吸引读者进站。

主题方向：{keyword}
所属分类：{tag}（{intent}）
站内内容倾向：{samples}

写作要求：
1. **完全原创**，不要假设你在改写任何已有内容
2. 围绕这个主题写一篇有信息量的文章：指南、经验分享、
   场景描写、常见疑问的解答，读者读完能学到东西
3. **不要编造事实**。不确定的用"通常""大多""一般"这类说法
4. 用词中性、健康。不得出现低俗、暧昧、擦边或任何违规暗示的词
5. 不要出现这些词：json、api、github、部署、缓存、脚本、接口、
   构建、仓库、服务器、数据库、算法
6. 结尾不要写"快来浏览""点击查看"这类召唤语

**篇幅是硬要求**：
- 正文必须达到 {lo}-{hi} 个汉字，至少 5 段
- 每段 3-4 句，不要只写两三句就收尾

**结尾必须有 2-3 组问答**，用这两种写法之一：
- 设问句独立成段，例：「新手最关心的问题？」（以问号结尾）
- 显式问答，例：「问：xxx  答：yyy」
问答是为了进搜索结果的「其他人还问了」，不能省

只输出 JSON：{{"title":"20字以内的标题，含关键词","description":"70-110字的摘要","body":"正文，段落用\\n\\n分隔","tags":["标签1","标签2","标签3"]}}"""


# ============================================================
# 选题
# ============================================================

def pick_source_post(items, exclude_slugs=None):
    """随机抽一篇站内帖子作为改写素材。

    排除已用过的：同一篇帖子被反复改写会产生近似重复内容，
    对SEO 是负分。exclude_slugs 记录已用过的源帖。
    """
    exclude = exclude_slugs or set()
    pool = [it for it in items if it.meta.get('slug') not in exclude]
    if not pool:
        pool = items
    if not pool:
        return None
    return random.choice(pool)


def pick_keyword(keywords, exclude=None):
    """随机挑一个关键词用于全新创作。"""
    exclude = exclude or set()
    pool = []
    for cat, words in keywords.items():
        pool.extend(words)
    fresh = [w for w in pool if w not in exclude]
    if not fresh:
        fresh = pool
    return random.choice(fresh) if fresh else None


def decide_mode(src_item):
    """决定用哪种模式。

    规则：
      - 源帖有正文（>= 20字）→ extend（扩写）
      - 源帖正文太短或为空 → rewrite（换视角重写）
    两者都依赖源帖，所以真正"全新创作"由 fresh 分支处理。
    """
    if src_item is None:
        return 'fresh'
    body = (src_item.body or '').strip()
    return 'extend' if len(body) >= 20 else 'rewrite'


# ============================================================
# 生成
# ============================================================

def build_promo_item(mode, src_item=None, keyword=None, angle=''):
    """构造引流文章的伪 item（dict，与真实帖子解耦）。"""
    tag = '综合'
    seed_parts = ['promo', mode, str(int(time.time() // 3600))]
    if keyword:
        seed_parts.append(keyword)
    if src_item is not None:
        seed_parts.append(src_item.meta.get('slug') or src_item.seed_id)
    seed = '::'.join(seed_parts)

    if src_item is not None:
        tag = (src_item.tags or ['综合'])[0]
    elif keyword:
        tag = rw.item_tags_or_default(keyword)[0]

    # 主题词（用于 title / 正文 prompt）：
    # rewrite/extend 模式下**不能直接用源帖标题** ——
    # 实测源帖标题是「怎么？我的腿不能见人吗」这类口语，
    # 搜索里没有这种词，而且常带【原创】前缀，
    # 直接拿来当 title 会产出「【原创】怎么？我的腿不能见人吗整理」
    # 这种既难看又搜不到的标题。
    # 改为按分类取一个真实的搜索词。
    if keyword:
        name = keyword
    elif src_item is not None:
        name = _search_term_for(src_item, tag)
    else:
        name = '内容'

    return {
        'seed_id': seed,
        'mode': mode,
        'name': name,
        'keyword': keyword,
        'src': src_item,
        'angle': angle,
        'tags': [tag],
        'meta': {
            # 用时间桶做哈希，保证同一小时内重跑得到同一个 slug（幂等），
            # 不同小时必然不同
            'slug': _promo_slug(seed),
            'slug_seed': seed,
            'image_count': (src_item.meta.get('image_count', 0)
                            if src_item else 0),
        },
        'images': [],
        'metrics': {},
        'published': int(time.time() * 1000),
    }


def _search_term_for(src_item, tag):
    """按分类给一个可搜索的主题词。

    站内标题普遍不可搜索（口语化、含表情、带分类前缀），
    所以这里用「分类 + 通用搜索修饰词」组合，
    保证 title 里有真正有人搜的词。
    """
    intent = config.TAG_INTENT.get(tag, '内容')
    # 从分类意图里提一个稳定的搜索词，比用源帖标题可靠得多
    base = {
        '举牌': '举牌文案', '原创': '原创摄影', '自拍': '自拍姿势',
        '美腿': '美腿拍照', '三坑': '三坑穿搭', '视频': '短视频剪辑',
        '日常': '日常记录', '综合': '生活记录',
    }.get(tag)
    if base:
        return base
    # 兜底：截取源帖标题里较长的中文片段，去掉表情与分类前缀
    import re as _re
    t = _re.sub(r'【[^】]*】', '', src_item.name or '')
    t = _re.sub(r'[^\u4e00-\u9fa5]', '', t)
    return t[:6] or intent[:6]


def _promo_slug(seed):
    h = hashlib.md5(str(seed).encode('utf-8')).hexdigest()[:10]
    return 'p-%s' % h


def generate(promo_item, ai, keywords=None, samples=None):
    """生成一篇引流文章的完整内容。"""
    mode = promo_item['mode']
    src = promo_item['src']
    tag = promo_item['tags'][0]
    lo, hi = config.PIPELINE['PROMO_MIN_LEN'], config.PIPELINE['PROMO_MAX_LEN']

    result = {
        'meta_title': '%s%s' % (promo_item['name'], '整理'),
        'meta_description': '关于%s的内容整理与经验分享。' % promo_item['name'],
        'tags': [tag, promo_item['name']][:4],
        'body': '',
        'by_ai': False,
    }

    if not ai.available:
        result['body'] = _template_body(promo_item)
        return result

    try:
        if mode in ('rewrite', 'extend') and src is not None:
            prompt = REWRITE_PROMPT.format(
                title=src.name,
                body=(src.body or '（原帖没有正文）')[:200],
                tag=tag,
                intent=config.TAG_INTENT.get(tag, '社区内容'),
                hit=src.metrics.get('hit', 0),
                comment=src.metrics.get('comment', 0),
                image_count=src.meta.get('image_count', 0),
                lo=lo, hi=hi,
            )
        else:
            prompt = FRESH_PROMPT.format(
                keyword=promo_item['name'],
                tag=tag,
                intent=config.TAG_INTENT.get(tag, '社区内容'),
                samples=(samples or '社区里常见的日常记录、兴趣分享、打卡内容')[:200],
                lo=lo, hi=hi,
            )
        data = ai.chat_json([
            {'role': 'system', 'content': '你是内容编辑，只输出 JSON。'},
            {'role': 'user', 'content': prompt},
        ], max_tokens=2400)
    except Exception:
        result['body'] = _template_body(promo_item)
        return result

    if not isinstance(data, dict) or not data.get('body'):
        result['body'] = _template_body(promo_item)
        return result

    body = rw._clean_body(data.get('body', ''))
    result.update({
        # 引流文的 AI 标题最容易跑偏（实测「偶遇电梯里的心动瞬间」），
        # 强制补上主题词，否则搜索流量进不来
        'meta_title': rw.ensure_keyword(
            data.get('title'), promo_item['name'], max_len=30),
        'meta_description': rw._clip(
            data.get('description') or result['meta_description'], 120),
        'tags': [rw._clip(t, 8) for t in (data.get('tags') or [])][:4]
                or result['tags'],
        'body': body,
        'by_ai': True,
    })
    return result


def assemble(promo_item, gen, site_url=None, cta_links=None, faq=None):
    """组装成结构化内容。

    与主题页的区别：引流文的主 CTA 更强——
    它的目的就是把搜索流量拉进社区，所以进站入口要更醒目。
    """
    from .assemble import build_schema, fingerprint

    site_url = site_url or config.site_url
    tag = promo_item['tags'][0]
    slug = promo_item['meta']['slug']

    content = {
        'seed_id': promo_item['seed_id'],
        'post_id': None,
        'slug': slug,
        'tag': tag,
        'tag_slug': config.TAG_SLUGS.get(tag, 'zonghe'),
        'meta_title': gen['meta_title'],
        'meta_description': gen['meta_description'],
        'tags': gen['tags'],
        'body': gen['body'],
        'promo_mode': promo_item['mode'],
        'source_slug': (promo_item['src'].meta.get('slug')
                        if promo_item['src'] else None),
        'author': config.SITE['BRAND'],
        'published': promo_item['published'],
        # 社区图片池随机取图。引流文需要图来吸引点击，
        # 空图版的引流效果明显更差。
        'images': imgpool.pick(config.PIPELINE['PROMO_IMG_COUNT'],
                               seed=promo_item['meta']['slug']),
        'image_total': config.PIPELINE['PROMO_IMG_COUNT'],
        'metrics': {},
        'generated_at': int(time.time() * 1000),
        'by_ai': gen.get('by_ai', False),
        'is_seo_page': True,
        'is_promo': True,
        'notice': config.CONTENT_KIND['NOTICE'],
        'notice_short': config.CONTENT_KIND['NOTICE_SHORT'],
        'cta_text': config.CONTENT_KIND['CTA_TEXT'],
        'source_post_id': None,
    }
    content['url'] = config.page_url(slug)
    content['faq'] = faq or []
    content['schema'] = build_schema(promo_item, content, site_url, faq)
    # schema 里的 URL 要跟实际路径一致
    for node in content['schema']['@graph']:
        if node.get('@id', '').startswith(config.page_url('')):
            node['@id'] = content['url'] + '#article'
        if node.get('url'):
            node['url'] = content['url']
        if node.get('@id', '').endswith('#breadcrumb'):
            node['itemListElement'][-1]['item'] = content['url']
    content['fingerprint'] = fingerprint(promo_item, content)
    return content


def _template_body(promo_item):
    """无 AI 时的兜底正文。"""
    tag = promo_item['tags'][0]
    name = promo_item['name']
    return ('\n\n'.join([
        '这一篇整理关于「%s」的内容。%s这个分类里，'
        '日常记录和兴趣分享一直是最常见的内容类型。' % (name, tag),
        '把同类内容放在一起看，能更清楚这个主题下大家都在关注什么：'
        '常见的场景、固定的记录方式、以及愿意长期坚持这件事的人。',
        '想看更多真实内容，可以从页面下方的入口进入社区。',
    ]))
