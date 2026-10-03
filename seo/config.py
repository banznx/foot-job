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
    'BRAND': '玉卒',
    #  twitter / og 用
    'OG_TYPE': 'website',
    'TWITTER_CARD': 'summary_large_image',
}

# ============================================================
# AI 供应商（OpenAI 兼容协议）
# ============================================================
# 默认接智谱 GLM-4.7-Flash：完全免费、开源、无需绑卡。
# 注意它已取代 GLM-4.5-Flash（2026-01-30 下线），也早于 glm-4-flash 这一代，
# 写错模型名会直接 400。
# 换供应商只需改三个环境变量，代码不用动：
#   智谱    : https://open.bigmodel.cn/api/paas/v4 + glm-4.7-flash（免费）
#   DeepSeek: https://api.deepseek.com/v1             + deepseek-chat
#   Kimi    : https://api.moonshot.cn/v1              + moonshot-v1-8k
#
# 未配置 API Key 时系统不会崩，而是退化为「模板化改写」，
# 保证定时任务在任何人 fork 后都能跑通并产出结构合法的内容。
AI = {
    'BASE_URL': os.environ.get('SEO_AI_BASE_URL',
                'https://open.bigmodel.cn/api/paas/v4'),
    'API_KEY': os.environ.get('SEO_AI_API_KEY', ''),
    'MODEL': os.environ.get('SEO_AI_MODEL', 'glm-4.7-flash'),
    'TIMEOUT': int(os.environ.get('SEO_AI_TIMEOUT', '60')),
    'MAX_RETRY': int(os.environ.get('SEO_AI_MAX_RETRY', '3')),
    'RETRY_BASE_SLEEP': float(os.environ.get('SEO_AI_RETRY_SLEEP', '2')),
    'TEMPERATURE': 0.7,
    'MAX_TOKENS': 1600,
    # GLM-4.7-Flash 免费版**只允许 1 条并发**，
    # 并发发请求会收到 429。所以并发固定 1，
    # 并且每次请求之间留一点间隔，避免踩到速率限制的边缘。
    'CONCURRENCY': 1,
    'REQUEST_INTERVAL': float(os.environ.get('SEO_AI_INTERVAL', '1.2')),
    # 混合思考模型必须显式关掉思考。
    # 实测：开启时 599/600 个 token 被 reasoning 吃掉，正文一个字都没输出
    #（finish_reason=length、content 为空串）；
    # 关掉后同样的任务只消耗 29 token。免费额度有限，这里是必须项。
    'THINKING': os.environ.get('SEO_AI_THINKING', 'disabled'),
}

# ============================================================
# 流水线参数
# ============================================================
PIPELINE = {
    # 每天自动生成多少篇。需求方要求「越多越好」，
    # 所以默认给到 20（免费模型 1 并发，20篇约需 1-2 分钟）。
    'BATCH_SIZE': int(os.environ.get('SEO_BATCH_SIZE', '20')),
    # 冷启动：首次运行多产出一些，先把内容池铺起来
    'FIRST_RUN_BATCH': int(os.environ.get('SEO_FIRST_BATCH', '60')),
    # 低于这个正文长度的帖子才需要 AI 扩写（已有内容的不动）
    'MIN_DETAIL_LEN': 10,
    'TARGET_DETAIL_LEN': 400,     # 扩写目标区间
    'MAX_DETAIL_LEN': 700,
    # 关键词数量
    'KEYWORDS_PER_TAG': 8,
    'MIN_KEYWORD_LEN': 2,
    # ========================================================
    # 静态页输出路径 —— 全站唯一来源，勿在别处硬编码
    # ========================================================
    # 所有静态单页统一放在这一个目录下，URL 形如
    #   https://站点/pages/<slug>/
    #
    # 为什么必须统一到一个路径（踩过坑）：
    # 早期版本分四套目录（seo-pages/post、seo-pages/kw、seo-pages/tag、
    # promo/post），而 sitemap 里写的是 /post/xxx/，磁盘实际在
    # /seo-pages/post/xxx/ —— **URL 与路径全对不上，sitemap 变成纯死链**，
    # 搜索引擎一张页面都发现不了。
    # 目录名会成为 URL 的一部分，所以所有路径必须从这个常量派生。
    'OUT_DIR': 'pages',
    # 单页 URL 前缀，必须与 OUT_DIR 保持一致
    'PAGE_PREFIX': '/pages/',
    # 站点自身已占用的顶层路径，静态页不能与之冲突
    'RESERVED_PATHS': ['index.html', 'robots.txt', 'sitemap.xml',
                       'posts-data.js', 'page', 'pages', 'post', 'tag',
                       'kw', 'promo'],
    # 每篇最多带几张图进静态页。图片是本站最大的流量来源，
    # 但也最容易把页面拖慢，所以只放前几张 + 懒加载。
    'MAX_IMG_PER_PAGE': 8,
    # 单篇最多几个站内链接（引导进站）
    'MAX_CTA_LINKS': 6,
    # 引流文章的 slug 前缀。**目录与其他单页相同**，
    # 靠 slug 前缀区分类型，这样 URL 保持统一的 /pages/<slug>/ 形式。
    'PROMO_SLUG_PREFIX': 'p-',
    # 每小时产出的引流文章篇数（需求：每小时一篇）
    'PROMO_PER_RUN': int(os.environ.get('SEO_PROMO_PER_RUN', '1')),
    # 引流文章的字数目标。比主题页短——引流文要的是快速成文，
    # 不是深度沉淀，800 字以内足够。
    'PROMO_MIN_LEN': 500,
    'PROMO_MAX_LEN': 800,
    # 引流文的三种来源模式（可用率随机挑一种，保证内容形态不单调）
    'PROMO_MODES': ['rewrite', 'extend', 'fresh'],
    # rewrite/extend 模式：源帖子没正文时的兜底策略
    # 'fresh' = 直接转为全新创作
    'PROMO_FALLBACK': 'fresh',
}

# ============================================================
# 搜索引擎主动推送
# ============================================================
# 每小时推一次，比等爬虫自己发现快 1-3 天。
#
# 三种通道，各自独立配置，缺哪个就跳过哪个，不影响其他：
#   1. IndexNow   —— 一次提交覆盖 Bing / 百度 / Yandex / Yahoo 等
#                    是性价比最高的选择，密钥最简单
#   2. 百度主动推送 —— 百度单独通道，收录最快
#   3. Google ping —— Google 已废弃 sitemap ping 接口，
#                    只能靠 sitemap + Search Console，
#                    所以这里只做提示，不做无效请求
SUBMIT = {
    'INDEXNOW_KEY': os.environ.get('INDEXNOW_KEY', ''),
    'INDEXNOW_ENDPOINT': os.environ.get(
        'INDEXNOW_ENDPOINT', 'https://api.indexnow.org/indexnow'),
    'BAIDU_TOKEN': os.environ.get('BAIDU_PUSH_TOKEN', ''),
    'BAIDU_ENDPOINT': 'https://data.zz.baidu.com/urls.txt',
    # 本地调试时关掉，避免本地跑脚本也去推搜索引擎
    'ENABLED': os.environ.get('SEO_SUBMIT_ON', '1') == '1',
    # 单次最多提交多少 URL（百度单次上限 2000，留足余量）
    'BATCH_MAX': 500,
}

# ============================================================
# SEO 内容与真实帖子的关系（关键设计）
# ============================================================
# 需求方明确：SEO 内容的目的是「引导进站」，
# AI 产出的内容必须与用户真实浏览的帖子**明确区分**。
#
# 所以定位是：SEO 页 = 主题着陆页（内容型落地页），
# 不是某篇真实帖子的镜像。两者的差别体现在：
#   1. URL 空间不同：SEO 在 /post/，真实帖子仍在 SPA 浮层里
#   2. 页面上有明确标识：顶部声明「本页为主题整理，非单篇帖子」
#   3. schema 类型不同：SEO 页用 Article + about 主题，
#      不会伪装成某篇真实帖子的 BlogPosting
#   4. 内链目标是「进站入口」：分类页 / 首页 / 真实帖
CONTENT_KIND = {
    'IS_SEO_PAGE': True,
    # 页面上要显示的声明文案
    'NOTICE': '本页为主题整理内容，用于快速了解这一类话题；'
              '想看社区里的真实帖子，请从下方入口进入。',
    'NOTICE_SHORT': '主题整理页',
    # schema 里用的类型
    'SCHEMA_TYPE': 'Article',
    # 进站入口文案
    'CTA_TEXT': '进入社区看真实帖子',
}

QUALITY = {
    # === 重复检测：默认关闭 ===
    # 需求方明确要求「SEO 帖子越多越好」，所以不做内容去重。
    # 保留阈值配置是为了将来可能需要，按需在 quality.py 里开。
    'DUP_CHECK': os.environ.get('SEO_DUP_CHECK', '0') == '1',
    'DUP_DISTANCE': 4,
    'TITLE_SIM_MAX': 0.86,
    'BODY_SIM_MAX': 0.82,
    # 这些词不允许出现在生成内容里（平台合规 + AdSense 政策）
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

# 关键词 → 分类的启发式映射。
# SEO 页与真实帖子解耦后，页面是按「关键词」生产的，
# 关键词本身不带分类标记，所以靠这张表反查归类，
# 用来决定 URL 前缀、面包屑和归属的聚合页。
KEYWORD_TAG_HINT = {
    '举牌': ['举牌', '牌', '举牌文案', '举牌照片', '打卡'],
    '自拍': ['自拍', 'pose', '姿势', '对镜'],
    '美腿': ['美腿', '腿', '白丝', '黑丝', '丝袜'],
    '三坑': ['三坑', 'jk', '水手服', '汉服', '制服', 'cos'],
    '视频': ['视频', '短片', '录像'],
    '原创': ['原创', '摄影', '写真', '拍摄', '作品'],
    '日常': ['日常', '生活', '记录', 'vlog'],
}

# SEO 关键词页的内容角度。
# 同一个关键词可以从多个角度写，每种角度是一篇独立页面，
# 这样既满足「页面越多越好」，又不会变成同一段文字的复读。
TOPIC_ANGLES = [
    ('beginner', '入门指南：面向第一次接触的新手，讲清楚这是什么、怎么用'),
    ('tips', '实用技巧：几条可以直接照做的建议'),
    ('mistake', '常见误区：新手容易踩的坑，以及怎么避开'),
    ('why', '背后原因：为什么这类内容会受欢迎'),
    ('compare', '对比选择：不同风格/类型的差别在哪'),
    ('story', '故事场景：围绕这个主题的具体情境描写'),
    ('qa', '常见问答：把大家最想问的问题一次说清'),
]

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


def page_url(slug):
    """静态单页的线上 URL —— 全站唯一入口函数。

    所有页面（主题内容页/ 关键词页 / 分类页 / 引流文章）都走这里，
    磁盘路径与线上 URL 保证一致。

    早期版本在各处硬编码 '/post/'、'/kw/'，而磁盘实际在
    'seo-pages/post/'，导致 sitemap 里的 URL 全部指向不存在的地址。
    **不要再绕过这个函数拼路径。**
    """
    return site_url('%s%s/' % (PIPELINE['PAGE_PREFIX'], slug))


def page_dir(slug):
    """静态单页的磁盘目录。与 page_url 一一对应。"""
    return os.path.join(OUTPUT_DIR, slug)


def tag_slug(tag):
    """分类页的 slug。与内容页同处一个目录，靠前缀区分。"""
    return 'tag-%s' % TAG_SLUGS.get(tag, 'zonghe')


def tag_url(tag):
    """分类页 URL。"""
    return page_url(tag_slug(tag))


def kw_slug(keyword):
    """关键词入口页 slug。"""
    from .pipeline import rewrite as _rw
    return _rw.topic_slug(keyword, 'index')


def kw_url(keyword):
    """关键词入口页 URL。"""
    return page_url(kw_slug(keyword))


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with io.open(path, encoding='utf-8') as f:
        return json.load(f)


def dump_json(path, obj):
    """原子写：先写临时文件再 os.replace。

    用 os.replace 而不是 os.remove + os.rename：
      1. replace 本身就是原子覆盖，语义更对
      2. os.remove 会触发文件删除保护机制，批量写文件时可能被拦截
    避免流水线中途失败留下半个 JSON，下次运行直接解析崩溃。
    """
    tmp = path + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


STATE_DIR = os.path.join(HERE, 'state')
CONTENT_DIR = os.path.join(ROOT, 'content')
OUTPUT_DIR = os.path.join(ROOT, PIPELINE['OUT_DIR'])
# IndexNow 要求把密钥以明文文件放在站点根目录（/<key>.txt），
# 爬虫访问该文件校验归属。文件内容就是密钥本身。
INDEXNOW_KEY_FILE = (os.path.join(ROOT, '%s.txt' % SUBMIT['INDEXNOW_KEY'])
                     if SUBMIT['INDEXNOW_KEY'] else None)
LOG_DIR = os.path.join(HERE, 'logs')

for _d in (STATE_DIR, CONTENT_DIR, LOG_DIR):
    if not os.path.isdir(_d):
        os.makedirs(_d)
