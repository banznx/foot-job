# -*- coding: utf-8 -*-
"""
阶段 2 与阶段 3：标题/描述生成 + 正文改写与扩写。

设计核心：**必须有 AI 之外的降级路径**。
站内正文有 770/2340 是空的、中位数只有 13 字，全靠 AI 扩写意味着一旦
Key 失效或额度耗尽，整条流水线就停了。所以这里做了 TemplateRewriter：
纯模板 + 站点真实数据（发布时间、图数、浏览量、分类）拼出结构完整、
语义通顺、可被索引的段落，质量不如 AI 但**结构永远合法**。

另一个硬约束（用户明确要求）：生成文本里不能出现技术词
（json/api/部署/缓存/服务器…）。用户要的是"打开就像论坛"，
不是技术文档。QUALITY['TECH_WORDS'] 会在校验阶段拦下违规内容。
"""

import hashlib
import re

from .. import config
from .keywords import strip_tag

# ============================================================
# 阶段 2：标题与描述
# ============================================================

META_PROMPT = """你是中文内容站点的 SEO 编辑。为一篇社区帖子写 SEO 元信息。

帖子信息：
- 原始标题：{title}
- 分类：{tag}（{intent}）
- 作者：{author}
- 图片数量：{img_count} 张
- 浏览量：{hit}
- 现有正文：{body}

要求：
1. meta_title：18-30 个汉字，必须包含分类词或核心主题词，
   要让人在搜索结果里一眼知道内容是什么，不要用书名号
2. meta_description：60-110 个汉字，完整概括这篇内容讲了什么，
   结尾不要出现"快来看""点击查看"这类空洞的召唤语
3. tags：3-5 个标签，单个2-6 字
4. **用词必须中性、健康**。不得出现低俗、暧昧、擦边或任何违规暗示的词
5. 不要编造具体事实（时间、地点、事件），只描述你确实从上面信息里读到的

只输出 JSON：{{"meta_title":"","meta_description":"","tags":[]}}"""


def generate_meta(item, ai, keywords_for_tag=None):
    """产出 meta_title / meta_description / tags。AI 失败降级到模板。"""
    tag = (item.tags or ['综合'])[0]
    kws = keywords_for_tag or []

    if ai.available:
        try:
            data = ai.chat_json([
                {'role': 'system', 'content': '你是 SEO 编辑，只输出 JSON。'},
                {'role': 'user', 'content': META_PROMPT.format(
                    title=item.name,
                    tag=tag,
                    intent=config.TAG_INTENT.get(tag, '社区内容'),
                    author=item.meta.get('author', '匿名'),
                    img_count=item.meta.get('image_count', 0),
                    hit=item.meta.get('hit', 0),
                    body=(item.body or '（无正文）')[:200],
                )},
            ], max_tokens=500)
            if isinstance(data, dict) and data.get('meta_title'):
                return {
                    'meta_title': _clip(data.get('meta_title', ''), 32),
                    'meta_description': _clip(data.get('meta_description', ''), 120),
                    'tags': [_clip(t, 8) for t in (data.get('tags') or [])][:5],
                    'by_ai': True,
                }
        except Exception:
            pass  # 降级

    return template_meta(item, kws)


def template_meta(item, keywords_for_tag=None):
    """无 AI 时的模板实现。完全基于真实字段拼装，不编造事实。"""
    tag = (item.tags or ['综合'])[0]
    _, clean = strip_tag(item.name)
    kws = keywords_for_tag or []
    kw = kws[0] if kws else config.TAG_INTENT.get(tag, '图片分享')

    meta_title = _clip(clean, 26)
    if tag and tag not in meta_title:
        meta_title = _clip('%s｜%s' % (tag, clean), 30)

    n = item.meta.get('image_count', 0)
    parts = ['这篇%s由%s发布' % (tag, item.meta.get('author', '社区用户'))]
    if n:
        parts.append('包含 %d 张图片' % n)
    if item.meta.get('hit'):
        parts.append('已有 %d 次浏览' % item.meta['hit'])
    if clean and clean != item.name:
        parts.append('内容围绕「%s」展开' % clean[:16])
    desc = _clip('，'.join(parts) + '。', 110)

    tags = [tag] + [k for k in kws[:2] if k != tag]
    return {'meta_title': meta_title, 'meta_description': desc,
            'tags': tags[:5], 'by_ai': False}


# ============================================================
# 阶段 3：正文改写与扩写
# ============================================================

BODY_PROMPT = """你为一个图片社区的帖子写正文描述。这篇帖子本身正文很短，需要你扩写成 2-4 段。

帖子信息：
- 标题：{title}
- 分类：{tag}（{intent}）
- 作者：{author}，社区等级 Lv.{level}
- 发布时间：{date}
- 图片数量：{img_count} 张
- 互动数据：{hit} 次浏览、{comment} 条评论、{praise} 个赞
- 作者自述：{body}

写作要求：
1. 严格基于上面的信息写，**不要编造**你没看到的东西
   （不要写"照片中海边的夕阳美极了"，你并不知道照片里有什么）
2. 描述这类内容在这一类帖子里的常见主题和网友关注点，用"通常""大多"这类
   留有余地的表达，而不是断言具体画面
3. 用词中性、健康。不得出现低俗、暧昧、擦边或任何违规暗示的词
4. 段落之间用空行分隔，段落不超过 3 句
5. 总长度 {lo}-{hi} 个汉字
6. **绝对不要出现**这些词：json、api、github、部署、缓存、脚本、接口、
   构建、仓库、服务器、数据库、算法、接口

只输出 JSON：{{"body":"正文段落，用\\n\\n分隔"}}"""


def rewrite_body(item, ai, keywords_for_tag=None):
    """产出扩写后的正文。AI 失败降级到 TemplateRewriter。"""
    tag = (item.tags or ['综合'])[0]
    lo = config.PIPELINE['TARGET_DETAIL_LEN']
    hi = config.PIPELINE['MAX_DETAIL_LEN']

    if ai.available:
        try:
            data = ai.chat_json([
                {'role': 'system', 'content': '你是社区内容编辑，只输出 JSON。'},
                {'role': 'user', 'content': BODY_PROMPT.format(
                    title=item.name,
                    tag=tag,
                    intent=config.TAG_INTENT.get(tag, '社区内容'),
                    author=item.meta.get('author', '匿名'),
                    level=item.meta.get('author_level', 1),
                    date=_fmt_date(item.published),
                    img_count=item.meta.get('image_count', 0),
                    hit=item.meta.get('hit', 0),
                    comment=item.meta.get('comment_count', 0),
                    praise=item.meta.get('praise', 0),
                    body=(item.body or '（无）')[:200],
                    lo=lo, hi=hi,
                )},
            ], max_tokens=1400)
            if isinstance(data, dict) and data.get('body'):
                body = _clean_body(data['body'])
                if len(body) >= 60:
                    return {'body': body, 'by_ai': True}
        except Exception:
            pass

    return {'body': TemplateRewriter(item, keywords_for_tag).build(), 'by_ai': False}


class TemplateRewriter(object):
    """无 AI 时的模板扩写器。

    不写"照片里如何如何"（因为不知道），
    只写可验证的结构性事实 + 这类内容的通用背景。
    结构上凑够 H2/H3/段落，语义上不空洞到被判定为低质。
    """

    def __init__(self, item, keywords_for_tag=None):
        self.item = item
        self.tag = (item.tags or ['综合'])[0]
        self.kws = keywords_for_tag or []
        self.m = item.meta or {}

    def build(self):
        tag = self.tag
        _, clean = strip_tag(self.item.name)
        intent = config.TAG_INTENT.get(tag, '社区内容')
        kws = [k for k in self.kws if k][:3]
        paras = []

        # 第1 段：这是什么
        p1 = '这篇%s发布在%s' % (intent, '玉卒')
        if clean:
            p1 += '，标题写的是「%s」' % clean[:24]
        p1 += '。'
        if self.m.get('image_count'):
            p1 += '作者附了 %d 张图片，' % self.m['image_count']
            p1 += '在%s里，带图的帖子通常比纯文字更容易被翻到和收藏。' % tag
        else:
            p1 += '这是一篇纯文字分享，'
            p1 += '在%s里这类内容常用来记录当下的想法。' % tag
        paras.append(p1)

        # 第 2 段：作者与互动
        p2 = '发布者是%s' % (self.m.get('author') or '社区用户')
        lv = self.m.get('author_level')
        if lv:
            p2 += '，社区等级 Lv.%s' % lv
        idn = self.m.get('identity')
        if idn:
            p2 += '，社区称号「%s」' % idn
        p2 += '，发布时间在%s。' % _fmt_date(self.item.published)
        if self.m.get('comment_count'):
            p2 += '目前有 %d 条回复，' % self.m['comment_count']
        if self.m.get('praise'):
            p2 += '%d 个赞。' % self.m['praise']
        else:
            p2 += '。'
        paras.append(p2)

        # 第 3 段：主题背景（用关键词做内链锚文本的机会）
        p3 = ''
        if kws:
            p3 = '如果你对%s这类内容更感兴趣，可以在%s里按分类浏览，' % (tag, '玉卒')
            p3 += '也可以先看看相关的%s。' % '、'.join(kws[:2])
        else:
            p3 = '在%s里，同类内容通常会围绕几个固定话题展开：' % tag
            p3 += '日常记录、穿搭分享、随手打卡。翻一翻能找到不少同好。' % tag
        paras.append(p3)

        return '\n\n'.join(paras)

    def slug(self):
        return make_slug(self.item)


# ============================================================
# 工具函数
# ============================================================

_PUNCT = re.compile(r'[\s　!-/:-@\[-`{-~·—…、，。！？；：（）《》【】“”‘’]+')
_BAD_SLUG = re.compile(r'[^a-z0-9]+')


def slugify(text, maxlen=40):
    """中文没法直接做URL slug，保留 ASCII 字母数字，其余转连字符。

    中文站点的通行做法是 URL 用拼音或短 ID。这里用
    「分类拼音 + 内容哈希」保证唯一且可读，不引拼音库。
    """
    s = _PUNCT.sub('-', (text or '').lower())
    s = _BAD_SLUG.sub('-', s).strip('-')
    if len(s) > maxlen:
        s = s[:maxlen].rstrip('-')
    return s or 'post'


def make_slug(item):
    """稳定的 URL slug：主题 slug + 稳定短哈希。

    必须是**稳定**的 —— slug 变了等于换 URL，已收录的页面会 404。
    所以哈希输入用不会变的种子，不用标题（标题可能被改）。

    种子优先取 slug_seed：SEO 页与真实帖子解耦后，
    种子可以是「关键词+角度」这样的组合，不再局限于 postID。
    """
    seed = item.meta.get('slug_seed') or item.meta.get('post_id') or item.seed_id
    tag = (item.tags or ['综合'])[0]
    tag_slug = config.TAG_SLUGS.get(tag, 'zonghe')
    h = hashlib.md5(str(seed).encode('utf-8')).hexdigest()[:8]
    return '%s-%s' % (tag_slug, h)


def topic_slug(keyword, angle=''):
    """关键词页 slug：主题 + 关键词哈希（角度参与哈希）。

    角度进哈希的意义：同一关键词的不同角度能落到不同 URL，
    互不覆盖——这是「SEO 页越多越好」的实现基础。
    """
    tag = (item_tags_or_default(keyword) or ['综合'])[0]
    tag_slug = config.TAG_SLUGS.get(tag, 'topic')
    h = hashlib.md5(('%s|%s' % (keyword, angle or '')).encode('utf-8')
                    ).hexdigest()[:10]
    return '%s-%s' % (tag_slug, h)


def item_tags_or_default(keyword):
    """按关键词猜它属于哪个分类。

    用于给关键词页分配正确的 URL 前缀与面包屑。
    猜错不致命（页面照样能收录），只是归类不够准确。
    """
    for tag, kws in getattr(config, 'KEYWORD_TAG_HINT', {}).items():
        if any(k in (keyword or '') or (keyword or '') in k for k in kws):
            return [tag]
    return ['综合']


def _clip(s, n):
    s = re.sub(r'\s+', ' ', (s or '')).strip()
    return s[:n]


def _clean_body(text):
    """清掉 AI 常见的markdown 残留和多余空白。"""
    t = (text or '').strip()
    t = re.sub(r'^```[a-z]*\s*|\s*```$', '', t)
    t = re.sub(r'^\s*#{1,6}\s*', '', t, flags=re.M)   # 标题符号
    t = re.sub(r'\*\*(.+?)\*\*', r'\1', t)
    t = re.sub(r'\n{3,}', '\n\n', t)
    return t.strip()


def _fmt_date(ms):
    if not ms:
        return '较早'
    import datetime
    try:
        return datetime.datetime.fromtimestamp(ms / 1000.0).strftime('%Y年%m月')
    except Exception:
        return '较早'
