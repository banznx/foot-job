# -*- coding: utf-8 -*-
"""
阶段 4：内部链接建议。

为什么这步很关键：
    搜索引擎靠内链判断"哪些页面更重要"和"页面之间是什么关系"。
    2340 篇帖子如果互不链接，就是 2340 个孤岛，等于没有权重流动，
    收录率上不去，内页根本排不到首页后面。

链接策略（刻意做得克制，避免变成链接农场）：
  1. 向上链1 篇热门同分类帖子（传权重给已有表现的页面）
  2. 横向链 2-3 篇同分类/同关键词的帖子
  3. 向下链 1-2 篇较弱同分类帖子（让新页面也能被爬到）
  4. 全部指向真实存在的页面，绝不链到空页（避免 404 拉低站点质量）

相似度算法用字符二元组 Jaccard，零依赖、可解释、快。
2340 篇全量两两比较是 270 万次 —— 慢。
所以用倒排索引按共享关键词倒排召回候选，把比较量降到几万级。
"""

import collections
import re


def _bigrams(text):
    t = re.sub(r'[\s\W_]+', '', (text or '').lower())
    return set(t[i:i + 2] for i in range(len(t) - 1)) or {t}


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if not inter:
        return 0.0
    return inter / float(len(a) + len(b) - inter)


def _terms(text):
    """从标题抽可匹配的关键词（连续 2 字以上的中文串）。

    入参是标题**字符串本身**（不是 SeedItem）——
    调用方 build_index 里传的是 it.name。
    """
    return set(w for w in re.findall(r'[\u4e00-\u9fa5]{2,}', text or ''))


def build_index(items):
    """按共享关键词建倒排索引，用于快速召回候选。"""
    inv = collections.defaultdict(set)
    grams = {}
    terms = {}
    for it in items:
        gid = it.seed_id
        grams[gid] = _bigrams(it.name)
        terms[gid] = _terms(it.name)
        for t in terms[gid]:
            inv[t].add(gid)
    return {'inv': inv, 'grams': grams, 'terms': terms}


# 标题全是表情/符号时没有检索价值，锚文本用它等于浪费一次内链权重
_EMOJI_ONLY = re.compile(
    r'^[\s【】\[\]（）()・･\-—~～!！?？.,，。、\'"“”'
    r'\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF'
    r'\U0000FE0F\U0000200D]+$')


def has_text(title):
    """标题里是否含有实义文字（汉字或字母）。"""
    t = (title or '').strip()
    if not t or _EMOJI_ONLY.match(t):
        return False
    return bool(re.search(r'[\u4e00-\u9fa5a-zA-Z]', t))


def _score(a, b, index):
    gid_a, gid_b = a.seed_id, b.seed_id
    sim = _jaccard(index['grams'].get(gid_a, set()),
                   index['grams'].get(gid_b, set()))
    # 同分类加权
    ta = (a.tags or ['综合'])[0]
    tb = (b.tags or ['综合'])[0]
    if ta == tb:
        sim += 0.18
    # 热度加权：略偏向热门内容（有真实流量的页面）
    m = max(b.metrics.get('hit', 0) or 0, 1)
    sim += min(m / 50000.0, 0.08)
    return sim


def suggest_links(item, pool, index, max_links=5, allowed_slugs=None):
    """为一个帖子挑内部链接，返回 [{slug,title,url,score,reason}]。

    allowed_slugs: 已生成页面的 slug 白名单。
    **必须传**，否则会链向还不存在的页面 —— 内链指向 404 会被搜索引擎
    当作站点质量缺陷，比没有内链更糟。
    """
    allowed = allowed_slugs if allowed_slugs is not None else set()
    gid = item.seed_id
    my_terms = index['terms'].get(gid, set())

    # 用倒排召回：只跟共享关键词的帖子比
    cand = set()
    for t in my_terms:
        cand |= index['inv'].get(t, set())
    cand.discard(gid)
    if not cand:
        # 标题没和任何人共享关键词（短标题常见），
        # 退化为全站候选。注意必须是 set 减法，不能 list(...) - set。
        cand = set(index['grams'].keys()) - {gid}
        cand = set(list(cand)[:200])

    by_id = {p.seed_id: p for p in pool}
    scored = []
    for cid in cand:
        p = by_id.get(cid)
        if p is None or not p.meta.get('post_id'):
            continue
        slug = p.meta.get('slug')
        if not slug or slug not in allowed:
            continue          # 页面还不存在，不链
        if not has_text(p.name):
            continue          # 标题全是表情，锚文本无价值
        scored.append((_score(item, p, index), p))
    scored.sort(key=lambda x: -x[0])

    picked = []
    seen_slugs = set()

    def take(pred, want, reason):
        n = 0
        for sc, p in scored:
            if n >= want:
                break
            if p.meta.get('slug') in seen_slugs:
                continue
            tg = (p.tags or ['综合'])[0]
            if not pred(tg, p):
                continue
            seen_slugs.add(p.meta.get('slug'))
            picked.append({
                'slug': p.meta.get('slug'),
                'post_id': p.meta.get('post_id'),
                'title': p.meta.get('seo_title') or p.name,
                'score': round(sc, 3),
                'reason': reason,
            })
            n += 1

    my_tag = (item.tags or ['综合'])[0]
    # 1) 横向：同分类
    take(lambda tg, p: tg == my_tag, 3, 'same-tag')
    # 2) 向上：全站热门（传权重）
    take(lambda tg, p: True, 1, 'hot')
    # 3) 向下：同分类但数据较弱（让弱页被爬到）
    take(lambda tg, p: tg == my_tag and (p.metrics.get('hit', 0) or 0) < 800, 1, 'weak-same-tag')

    return picked[:max_links]


def cluster_related(item, pool, index, limit=12, min_score=0.22,
                    allowed_slugs=None):
    """聚合同分类的"相关推荐"列表，展示在页面底部。

    allowed_slugs 与 suggest_links 同理：只推已生成、不会 404 的页面。
    """
    allowed = allowed_slugs if allowed_slugs is not None else set()
    gid = item.seed_id
    my_tag = (item.tags or ['综合'])[0]
    my_terms = index['terms'].get(gid, set())
    cand = set()
    for t in my_terms:
        cand |= index['inv'].get(t, set())
    if not cand:
        cand = set(list(index['grams'].keys())[:300])
    cand.discard(gid)

    by_id = {p.seed_id: p for p in pool}
    out = []
    for cid in cand:
        p = by_id.get(cid)
        if p is None or not p.meta.get('slug'):
            continue
        if p.meta['slug'] not in allowed or not has_text(p.name):
            continue
        tg = (p.tags or ['综合'])[0]
        sc = _jaccard(index['grams'].get(gid, set()),
                      index['grams'].get(cid, set()))
        if tg == my_tag:
            sc += 0.2
        if sc < min_score:
            continue
        out.append({
            'slug': p.meta.get('slug'),
            'post_id': p.meta.get('post_id'),
            'title': p.meta.get('seo_title') or p.name,
            'tag': tg,
            'score': round(sc, 3),
        })
    out.sort(key=lambda x: -x['score'])
    return out[:limit]
