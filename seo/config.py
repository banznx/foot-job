# -*- coding: utf-8 -*-
"""
SEO 内容系统统一配置。

设计原则：**零第三方依赖**。
只用 Python 标准库（urllib / json / hashlib / difflib），
这样 GitHub Actions 里不需要 pip install，流水线冷启动 <5秒，
也不会因为某个包升级导致构建突然失败。
"""

import io
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# ============================================================
# 站点
# ============================================================
SITE = {
    # 线上域名。GitHub Pages 项目页路径是 /foot-job/，
    # 所有 URL 拼接必须带上 BASE_PATH，否则站内链接会 404。
    'HOST': os.environ.get('SEO_SITE_HOST', 'https://banznx.github.io'),
    'BASE_PATH': '/foot-job',
    'LANG': 'zh-CN',
    'BRAND': 'FootJob论坛',
    #  twitter / og 用
    'OG_TYPE': 'website',
    'TWITTER_CARD': 'summary_large_image',
}

# ============================================================
# AI 供应商（OpenAI 兼容协议）
# ============================================================
# 未配置 API Key 时系统不会崩，而是退化为「模板化改写」，
# 保证定时任务在任何人 fork 后都能跑通并产出结构合法的内容。
AI = {
    'BASE_URL': os.environ.get('SEO_AI_BASE_URL',
                'https://api.deepseek.com/v1'),
    'API_KEY': os.environ.get('SEO_AI_API_KEY', ''),
    'MODEL': os.environ.get('SEO_AI_MODEL', 'deepseek-chat'),
    'TIMEOUT': int(os.environ.get('SEO_AI_TIMEOUT', '60')),
    'MAX_RETRY': int(os.environ.get('SEO_AI_MAX_RETRY', '3')),
    'RETRY_BASE_SLEEP': float(os.environ.get('SEO_AI_RETRY_SLEEP', '2')),
    'TEMPERATURE': 0.7,
    'MAX_TOKENS': 1600,
}

# ============================================================
# 流水线参数
# ============================================================
PIPELINE = {
    # 单次运行最多处理多少篇。定时任务每天跑一次，
    # 2340 篇分批出内容，避免一次性把仓库打爆。
    'BATCH_SIZE': int(os.environ.get('SEO_BATCH_SIZE', '20')),
    # 冷启动：首次运行允许生成更多
    'FIRST_RUN_BATCH': int(os.environ.get('SEO_FIRST_BATCH', '40')),
    # 低于这个正文长度的帖子才需要 AI 扩写（已有内容的不动）
    'MIN_DETAIL_LEN': 10,
    'TARGET_DETAIL_LEN': 260,     # 扩写目标区间
    'MAX_DETAIL_LEN': 420,
    # 关键词数量
    'KEYWORDS_PER_TAG': 8,
    'MIN_KEYWORD_LEN': 2,
}

QUALITY = {
    # SimHash 汉明距离阈值：小于该值判定为近似重复
    'DUP_DISTANCE': 4,
    # 与已发布内容的标题相似度上限（difflib ratio，越大越像）
    'TITLE_SIM_MAX': 0.86,
    # 正文相似度上限
    'BODY_SIM_MAX': 0.82,
    # 这些词不允许出现在生成内容里（平台合规 + 避免踩 AdSense  policies）
    'BLOCKED_WORDS': [
        '微信', '加v', 'QQ群', '兼职', '约炮', '上门', '服务',
        '色情', '裸聊', '博彩', '彩票', '贷款', '免费送',
    ],
    # 纯技术词不允许出现在正文（用户要求：界面不能像技术文档）
    'TECH_WORDS': [
        'json', 'api', 'github', '部署', '缓存', '脚本', '接口',
        '构建', '仓库', '部署', '服务器', '数据库', '算法',
    ],
}

ADS = {
    # AdSense  publisher ID。留空则不注入任何广告脚本，
    # 只在 HTML 里留好占位容器 —— 审核通过后填上即可生效。
    'PUBLISHER_ID': os.environ.get('SEO_ADSENSE_PUB', ''),
    'ENABLED': os.environ.get('SEO_ADSENSE_ON', '0') == '1',
    # 预留广告位（相对路径 + 尺寸 + 备注）
    'SLOTS': [
        {'id': 'top',    'w': 728, 'h': 90,  'note': '内容页顶部，横幅'},
        {'id': 'infeed', 'w': 336, 'h': 280, 'note': '正文结束处插屏'},
        {'id': 'footer', 'w': 336, 'h': 280, 'note': '页尾竖版'},
    ],
}

# ============================================================
# 分类词表
# ============================================================
# 分类藏在标题前缀里（【举牌】【原创】【自拍】…），
# tagid 只是原站的分区 ID，与内容语义无关，不能用来做分类。
# 这里用正则从标题提取真实分类。
TAG_PATTERNS = [
    ('举牌', r'【举牌】'),
    ('原创', r'【原创】'),
    ('自拍', r'【自拍】'),
    ('美腿', r'【美腿】'),
    ('三坑', r'【三坑】'),
    ('视频', r'【视频】'),
    ('日常', r'【日常】'),
]

# 分类 → 拼音 slug（用于 URL，全小写 ASCII）
TAG_SLUGS = {
    '举牌': 'jupai',
    '原创': 'yuanchuang',
    '自拍': 'zipai',
    '美腿': 'meitui',
    '三坑': 'sankeng',
    '视频': 'shipin',
    '日常': 'richang',
    '综合': 'zonghe',
}

# 分类 → 搜索意图描述，会喂给 AI，让它知道该写什么调性的内容
TAG_INTENT = {
    '举牌': '网友举着自定义文字牌的照片，通常是打卡、宣言、求助、情绪表达',
    '原创': '用户自己拍摄或自己整理的原创照片内容',
    '自拍': '用户本人拍摄的自拍照',
    '美腿': '以腿部特写为主题的照片',
    '三坑': '正装JK、水手服、汉服等制服类穿搭',
    '视频': '短视频内容',
    '日常': '日常生活分享',
    '综合': '社区里没有明确归类的内容',
}

# 站点栏目
SECTIONS = [
    ('首页', '/', '按推荐、最新、热门三种方式浏览全站内容'),
    ('发现', '/', '随机刷一篇，换一个角度看社区'),
    ('我的', '/', '收藏与浏览记录'),
]


def site_url(path=''):
    """拼接完整线上 URL。BASE_PATH 不能丢。"""
    p = path if path.startswith('/') else '/' + path
    return SITE['HOST'].rstrip('/') + SITE['BASE_PATH'] + p


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with io.open(path, encoding='utf-8') as f:
        return json.load(f)


def dump_json(path, obj):
    """原子写：先写临时文件再 rename。
    避免流水线中途失败留下半个 JSON，下次运行直接解析崩溃。"""
    tmp = path + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    if os.path.exists(path):
        os.remove(path)
    os.rename(tmp, path)


STATE_DIR = os.path.join(HERE, 'state')
CONTENT_DIR = os.path.join(ROOT, 'content')
OUTPUT_DIR = os.path.join(ROOT, 'seo-pages')
LOG_DIR = os.path.join(HERE, 'logs')

for _d in (STATE_DIR, CONTENT_DIR, LOG_DIR):
    if not os.path.isdir(_d):
        os.makedirs(_d)
