# -*- coding: utf-8 -*-
"""
质量过滤与去重。

Google 对 AI 批量生成内容的判定越来越严（ Helpful Content 系统 )，
一篇没有增量信息的薄页面不仅不涨排名，还会拖累整站。
所以在**提交之前**就把不合格的拦掉，比事后补救便宜得多。

四道闸门：
  1. 长度闸    正文太短撑不起一个页面
  2. 重复闸SimHash 近似重复 + 标题相似度双重判定
  3. 合规闸    违禁词、技术词
  4. 信息量闸  与源帖相比是否有实质增量

每道闸门失败都带原因写进 content['quality']，
流水线日志里能看到具体是哪一条把内容毙掉了，便于调参。
"""

import difflib
import hashlib
import re

from .. import config


# ============================================================
# SimHash：近似重复检测
# ============================================================

def simhash(text, bits=64):
    """字符级 SimHash。返回 64 位整数。

    为什么用SimHash 而不是 set 精确比对：
    精确比对只能抓完全一样的，抓不到「这段是那段改了三个字」。
    SimHash 对微小改动敏感度低但足够抓住近似重复，
    这是内容去重的标准做法。
    """
    t = re.sub(r'\s+', '', (text or ''))
    if not t:
        return 0
    vec = [0] * bits
    grams = [t[i:i + 3] for i in range(max(len(t) - 2, 1))]
    for g in grams:
        h = int(hashlib.md5(g.encode('utf-8')).hexdigest()[:16], 16)
        for i in range(bits):
            vec[i] += 1 if (h >> i) & 1 else -1
    out = 0
    for i in range(bits):
        if vec[i] > 0:
            out |= (1 << i)
    return out


def hamming(a, b):
    return bin(a ^ b).count('1')


# ============================================================
# 质量评估
# ============================================================

def evaluate(content, source_item, seen_hashes=None, seen_titles=None):
    """对一条生成内容做全量质量检测。

    seen_hashes: {simhash: slug} 已发布的近似内容
    seen_titles: [title]  已发布的标题，用于相似度比对

    返回 content['quality']，其中 passed 为 False 时流水线不会写盘。
    """
    q = config.QUALITY
    body = content.get('body', '')
    title = content.get('meta_title', '')
    reasons = []
    score = 100

    # --- 闸门 1：长度 ---
    n = len(re.findall(r'[\u4e00-\u9fa5]', body))
    if n < 80:
        reasons.append('正文过短（%d 字 < 80）' % n)
        score -= 40
    elif n < 140:
        score -= 12
    if n > 900:
        reasons.append('正文过长（%d 字）' % n)
        score -= 10

    # --- 标题与描述长度（搜索结果的截断阈值）---
    if not (10 <= len(title) <= 32):
        score -= 10
    if not (40 <= len(content.get('meta_description', '')) <= 120):
        score -= 8
    if not title or not content.get('meta_description'):
        reasons.append('缺少标题或描述')

    # --- 闸门 2：重复（默认关闭）---
    # 需求方明确要求「SEO 帖子越多越好」，因此默认不做内容去重。
    # 需要时设环境变量 SEO_DUP_CHECK=1 打开。
    if q.get('DUP_CHECK'):
        h = simhash(body)
        if seen_hashes:
            for oh, slug in seen_hashes.items():
                if hamming(h, oh) <= q['DUP_DISTANCE']:
                    reasons.append('正文与已发布内容《%s》近似重复' % slug)
                    score -= 60
                    break
        if seen_titles:
            best = 0.0
            for t in seen_titles[:800]:   # 只比前800条，控制 O(n²) 开销
                r = difflib.SequenceMatcher(
                    None, title, t).quick_ratio()
                if r > 0.75:
                    r = difflib.SequenceMatcher(None, title, t).ratio()
                if r > best:
                    best = r
            if best > q['TITLE_SIM_MAX']:
                reasons.append('标题与已发布内容高度相似（%.0f%%）' % (best * 100))
                score -= 50

    # --- 闸门 3：合规 ---
    low = (body + ' ' + title + ' ' + content.get('meta_description', '')).lower()
    for w in q['BLOCKED_WORDS']:
        if w in low:
            reasons.append('含违禁词：%s' % w)
            score -= 60
            break
    for w in q['TECH_WORDS']:
        if w in low:
            reasons.append('含技术词：%s' % w)
            score -= 45
            break

    # --- 闸门 4：信息量增量 ---
    # AI 有时会原样复述标题、什么都不新增。这里比一下
    # 「正文里有多少内容是从源帖元数据里来的」——
    # 如果正文里的信息全部来自元数据而没有任何展开，
    # 说明它没有为读者提供增量价值。
    # 用词重复度只在**篇幅够长**时才有参考价值：
    # 200 字的文章天然用不到 200 个不同汉字，
    # 拿同一把尺子量 200 字和 800 字会误判。
    # 500 字以上才启用这个判据。
    uniq = len(set(re.findall(r'[\u4e00-\u9fa5]', body)))
    if n >= 500 and uniq / float(n) < 0.42:
        reasons.append('用词重复度过高，内容单薄')
    elif n >= 500 and uniq / float(n) < 0.55:
        score -= 12
        score -= 25

    # 段落数：单段的页面在信息量和体验上都不如多段
    paras = [p for p in body.split('\n\n') if p.strip()]
    if len(paras) < 2:
        score -= 15

    # 媒体加分：有图 = 用户停留时间更长 = 排名信号更好
    if content.get('image_total', 0) > 0:
        score += 8
    if content.get('related'):
        score += 4
    if content.get('internal_links'):
        score += 5

    score = max(0, min(100, score))
    # 硬性理由存在即不通过；否则靠分数
    passed = not reasons and score >= 60

    content['quality'] = {
        'passed': passed,
        'score': score,
        'reasons': reasons,
        'zh_len': n,
        'paragraphs': len(paras),
        # h 只在 DUP_CHECK 分支里赋值，所以这里无条件重算一次。
        # 指纹入库后供下轮去重比对用，即使当轮不做去重也要有值。
        'simhash': '%016x' % simhash(body),
        'by_ai': content.get('by_ai', False),
    }
    return content['quality']


def summarize(items):
    """给一批质量结果做汇总，写进日志。"""
    total = len(items)
    ok = [i for i in items if i['quality']['passed']]
    by_reason = {}
    for i in items:
        for r in i['quality']['reasons']:
            key = re.sub(r'（.*?）|\d+', '', r)
            by_reason[key] = by_reason.get(key, 0) + 1
    return {
        'total': total,
        'passed': len(ok),
        'rejected': total - len(ok),
        'avg_score': round(
            sum(i['quality']['score'] for i in items) / total, 1) if total else 0,
        'reasons': by_reason,
    }
