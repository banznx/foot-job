# -*- coding: utf-8 -*-
"""
阶段 1：关键词与主题选取。

中文没有空格分词，但引jie' 也不需要引入 jieba 这类依赖——
站内标题高度模式化（`【举牌】xxx`），用「前缀剥离 + 二/三元组统计」
就能拿到足够干净的主题词，且零依赖、结果可解释。

流程：
  1. 剥离【】分类前缀，拿到正文标题
  2. 抽候选 n-gram（中文 2-4 字组合 + 英文单词）
  3. 用停用词 + 频次 + 分类内聚度打分排序
  4. 按分类聚成主题簇（topic cluster）
  5. 可选调 AI 做扩写（拉长尾词），失败自动跳过
"""

import collections
import re

from .. import config

# 中文停用词：这些字单独/组合出现没有检索价值
STOP = set("""
的 了 是 我 你 他 她 它 们 在 有 和 就 不 人 都 一 一个 上 也 很 到 说 要 去 会 着 没有 看 好 自己 这 那
什么 怎么 这个 那个 一下 一些 一样 之后 之前 现在 今天 明天 昨天 因为 所以 但是 如果 可以 我们 你们 他们
啊 呀 吧 呢 吗 哦 哈 嗯 呗 啦 喔 嘻 嘿 吼 嗷 唔 哈哈 哈哈哈 emmm emm
真的 有点 还是 已经 感觉 突然 终于 出来 起来 过去 感觉 时候 朋友 家人
随缘 打卡 记录 更新 分享 日常 一发 一图 各位 兄弟们 姐妹们 家人 各位
""".split())

# 明显无检索价值的口水词：单个字或泛用词，搜的人很少
JUNK = set("""
今日 今日份 知道 喜欢 快乐 呜呜 哥哥 姐姐 第一次 无聊 照片 早安 遇见 生活 日记
么时 什么 时候 可以 不是 就是 这样 那样 一个 一点 有点 真的 感觉
""".split())

# 所有分类名本身不能作为关键词（否则「原创」会出现在「举牌」簇里）
ALL_TAGS = set(config.TAG_SLUGS.keys())
TAG_SLUG_VALUES = set(config.TAG_SLUGS.values())

# 英文/数字停用
STOP_EN = set("the a an and or but if of to in on for with at by from is are was".split())


def strip_tag(title):
    """剥离标题里的【分类】前缀，返回 (分类, 纯净标题)。"""
    m = re.match(r'^\s*【([^】]{1,6})】\s*', title)
    if m:
        return m.group(1), title[m.end():].strip()
    # 没前缀时按内容猜一个
    for name, _pat in config.TAG_PATTERNS:
        if name in title:
            return name, title
    return '综合', title.strip()


_CJK = re.compile(r'[\u4e00-\u9fa5]')
_LATIN = re.compile(r'[a-zA-Z][a-zA-Z0-9]{1,}')
_BRACKET = re.compile(r'[\[\(【（][^\]\)】）]{0,12}[\]\)】）]')

# 中文关键词最小长度。
# 设成 3 而不是 2：中文双字组合里绝大多数是「今日/知道/照片」这类
# 没有检索价值的碎片，三字以上才更像真实被搜过的词。
_MIN_CJK_N = 3


def candidates(text, nmax=4):
    """抽候选词：中文 n-gram + 英文单词。"""
    out = []
    t = _BRACKET.sub(' ', text)          # 去掉表情/符号块 [赖皮] (๑•̀ㅂ•́)
    t = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9\s]', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()

    for chunk in t.split(' '):
        if not chunk:
            continue
        if _LATIN.fullmatch(chunk) or _LATIN.match(chunk):
            w = chunk.lower()
            if len(w) >= 2 and w not in STOP_EN:
                out.append(w)
            continue
        # 中文串：滑窗
        for n in range(_MIN_CJK_N, nmax + 1):
            for i in range(len(chunk) - n + 1):
                g = chunk[i:i + n]
                if g in STOP or g in JUNK or g in ALL_TAGS:
                    continue
                if g[0] in STOP or g[-1] in STOP:
                    continue
                # 纯数字/编号（07、7月、123）没有检索价值
                if any(ch.isdigit() for ch in g) and not _CJK.search(g[0]):
                    continue
                out.append(g)
    return out


def build_corpus(items, top=60):
    """从 SeedItem 列表构建 (词, 频次, 分类) 词频表。

    注意：这一层**不直接当关键词用**，只作为喂给 AI 的频次证据。
    站内标题高度口水化（"呜呜呜"、"夏日第三弹"），
    纯 n-gram 统计抽出来的多是「呜呜呜」「日记07」这类噪声，
    直接拿去当关键词反而会污染 SEO。真正的词由 AI 结合频次产出。
    """
    freq = collections.Counter()
    owner = collections.defaultdict(collections.Counter)
    for it in items:
        cat = (it.tags or ['综合'])[0]
        _, clean = strip_tag(it.name)
        for g in candidates(clean):
            freq[g] += 1
            owner[g][cat] += 1
    rows = []
    for w, n in freq.items():
        if n < 2:            # 只出现一次的多是噪声
            continue
        rows.append((w, n, owner[w].most_common(1)[0][0]))
    rows.sort(key=lambda r: (-r[1], len(r[0])))
    return rows[:top]


def cluster_keywords(items, per_tag=None):
    """按分类分簇，簇内做包含去重（去掉被更长词包含的短词）。

    「黑丝」和「黑丝袜」同时存在时只留频次高的，
    否则 sitemap 里会出现一堆近义URL 互相抢权重。
    """
    per_tag = per_tag or config.PIPELINE['KEYWORDS_PER_TAG']
    rows = build_corpus(items, top=400)
    by_tag = collections.defaultdict(list)
    for w, n, cat in rows:
        by_tag[cat].append((w, n))

    result = {}
    for cat, pairs in by_tag.items():
        pairs.sort(key=lambda x: (-x[1], -len(x[0])))
        kept = []
        for w, n in pairs:
            # 已被选中的更长词包含当前词 -> 跳过
            if any(w != k and w in k for k, _ in kept):
                continue
            kept.append((w, n))
            if len(kept) >= per_tag:
                break
        result[cat] = kept
    return result


# ============================================================
# 无 AI 时的兜底关键词库
# ============================================================
# 站内标题太口水，纯统计抽不出能直接用的词。
# 没配 AI Key 时用这份人工词库兜底，保证流水线仍能产出合理结构；
# 配了 Key 则由 AI 覆盖。词库按分类组织，用词保持中性。
FALLBACK_KEYWORDS = {
    '原创': ['原创摄影', '原创写真', '摄影作品', '原创分享', '图片分享'],
    '举牌': ['举牌照片', '举牌文案', '举牌打卡', '举牌语录', '举牌配图'],
    '自拍': ['自拍姿势', '自拍技巧', '日常自拍', '自拍氛围'],
    '美腿': ['腿部特写', '腿型展示', '夏日穿搭'],
    '三坑': ['制服穿搭', '水手服', 'JK制服', '汉服穿搭'],
    '视频': ['短视频', '视频记录'],
    '日常': ['生活记录', '日常分享', '生活片段'],
    '综合': ['图片社区', '兴趣社区', '每日图片'],
}


# ============================================================
# AI 扩写：把站内词扩成有人会搜的长尾
# ============================================================

EXPAND_PROMPT = """你是一名中文搜索词研究员，服务一个图片分享社区的 SEO。

我会给你该社区各分类的**真实标题样本**（含出现次数），以及该分类的内容含义。
请为每个分类产出 6 个「真实用户会在搜索框输入」的中文关键词。

硬性要求：
1. 长度 4-10 个汉字，必须是完整的搜索习惯短语
2. 用词必须中性、干净、健康 —— 不得出现任何低俗、暧昧、擦边或违规暗示的词
   （这是广告投放的硬性要求，违规词会导致整个站点被降权）
3. 必须是「描述这类内容」的检索词，不要照抄样本里的口水标题
4. 关键词之间不要互相包含（如已有"举牌文案"就不要再来"举牌文案分享"）
5. 只输出 JSON，形如：{"分类名": ["词1","词2","词3","词4","词5","词6"]}

各分类含义：
%s

真实标题样本（词:出现次数）：
%s
"""


def expand_with_ai(clusters, ai, categories=None, samples=None):
    """调 AI 产出关键词。AI 不可用或失败时返回空 dict——绝不阻断流水线。

    samples: {分类: [(词, 次数), ...]}，来自 build_corpus，
             作为「站内真实在讲什么」的证据喂给模型，避免它凭空编。
    """
    if not ai.available:
        return {}

    clusters = clusters or {}
    samples = samples or clusters
    cats = categories or list(config.TAG_SLUGS.keys())
    cats = [c for c in cats if c in config.TAG_INTENT or c in clusters]

    cat_desc = '\n'.join('- %s：%s' % (c, config.TAG_INTENT.get(c, '社区内容'))
                        for c in cats)
    sample_txt = '\n'.join(
        '%s：%s' % (c, '、'.join('%s(%d)' % (w, n) for w, n in samples.get(c, [])[:15]))
        for c in cats)

    try:
        data = ai.chat_json([
            {'role': 'system', 'content': '你是搜索词研究员，只输出 JSON。'},
            {'role': 'user', 'content': EXPAND_PROMPT % (cat_desc, sample_txt)},
        ], max_tokens=1200)
    except Exception:
        return {}

    out = {}
    if not isinstance(data, dict):
        return {}

    # 跨分类去重：同一个词不能同时挂在两个分类下，
    # 否则两个页面争同一个关键词，会互相稀释权重。
    claimed = {}

    for cat, words in data.items():
        if not isinstance(words, list):
            continue
        clean = []
        local = set()
        for w in words:
            w = (w or '').strip()
            if not w or len(w) < 3 or w in STOP or w in JUNK:
                continue
            if w in ALL_TAGS or w in local:
                continue
            if w in claimed and claimed[w] != cat:
                continue
            clean.append(w)
            local.add(w)
            claimed[w] = cat
        if clean:
            out[cat] = clean[:8]
    return out


def resolve_keywords(clusters, ai):
    """产出最终关键词表：AI 优先，失败回退人工词库，再回退统计簇。

    返回 {分类: [词, ...]}，保证任何环境下都非空。
    """
    ai_out = expand_with_ai(clusters, ai)
    final = {}
    allcats = set(config.TAG_SLUGS.keys()) | set(clusters.keys())
    for cat in allcats:
        words = list(ai_out.get(cat) or [])
        if not words:
            words = list(FALLBACK_KEYWORDS.get(cat) or [])
        if not words:
            words = [w for w, _ in (clusters.get(cat) or [])]
        if words:
            final[cat] = words
    return final
