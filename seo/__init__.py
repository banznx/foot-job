# -*- coding: utf-8 -*-
"""
全自动 SEO 内容系统。

分层：
    sources/   数据源（站内帖子元数据 + 第三方 AI API）
    pipeline/  五阶段生成（选题 -> 标题描述 -> 正文 -> 内链 -> 结构化）
    render/    静态渲染（可索引页/schema/sitemap/robots/广告位）

入口：python -m seo.run
"""

__version__ = '1.0.0'
