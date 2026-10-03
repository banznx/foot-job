# -*- coding: utf-8 -*-
"""
SEO 内容流水线主调度器。

    python -m seo.run                # 跑一批（默认 5篇）
    python -m seo.run --batch 20     # 指定批量
    python -m seo.run --all          # 全量重建（危险，需 --force）
    python -m seo.run --dry-run      # 只看会处理什么，不写盘
    python -m seo.run --force        # 覆盖已发布内容
    python -m seo.run --tag举牌     # 只处理某个分类

完整链路：
    拉数据 → 关键词 → 逐篇生成(标题/描述/正文) → 内链 → 质量校验
    → 写静态页 → 写分类页 → 写 sitemap/robots → 记账+日志
"""

import io
import json
import os
import re
import sys
import time
import traceback

from . import config
from . import submit as submit_mod
from .pipeline import assemble as asm
from .pipeline import keywords as kw
from .pipeline import ledger
from .pipeline import links as links_mod
from .pipeline import promo as promo_mod
from .pipeline import quality as q_mod
from .pipeline import rewrite as rw
from .render import page as page_render
from .render import sitemap as sitemap_render
from .render import tag_page as tag_render
from .sources import AiClient, LocalPostSource

OUT_DIR = os.path.join(config.ROOT, config.PIPELINE['OUT_DIR'])
PROMO_DIR = config.PROMO_OUT_DIR


def log(msg):
    """日志统一走stdout，GitHub Actions 会收集。"""
    print('[seo] %s' % msg, flush=True)


# ============================================================
# 入口
# ============================================================

def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    opts = parse_args(argv)
    t0 = time.time()

    log('站点：%s  根路径：%s' % (config.SITE['BRAND'], config.SITE['BASE_PATH']))
    ai = AiClient()
    log('AI：%s（%s）' % (
        config.AI['MODEL'] if ai.available else '未配置 Key，使用模板降级',
        config.AI['BASE_URL']))

    # ---------- 1. 拉数据 ----------
    log('拉取站内帖子…')
    src = LocalPostSource()
    items = src.fetch(tag=opts.tag)
    log('共 %d 条' % len(items))
    if not items:
        log('没有可处理的数据，退出')
        return 1

    # 统一分配 slug（内链阶段与幂等判断都要用）。
    # 必须直接赋值而不是 setdefault：Source 构造时已经在 meta 里放了
    # 'slug': None 这个键，setdefault 遇到已存在的 None 不会覆盖，
    # 会导致 slug 恒为 None、幂等判断全部失效、重复生成同一批页面。
    for it in items:
        it.meta['slug'] = rw.make_slug(it)
    log('已完成 slug 分配')

    # ---------- 2. 关键词 ----------
    log('生成关键词…')
    clusters = kw.cluster_keywords(items)
    samples = {}
    for w, n, cat in kw.build_corpus(items, top=300):
        samples.setdefault(cat, []).append((w, n))
    keywords = kw.resolve_keywords(clusters, ai)
    log('关键词：%s' % {k: len(v) for k, v in keywords.items()})

    # ---------- 2.5 模式分流 ----------
    # promo 模式：每小时产出一篇引流文章到独立文件夹 promo/，
    #             并把新 URL 推送给搜索引擎。
    # topic 模式：按「关键词×角度」生成主题沉淀页。
    # post 模式：基于真实帖子元数据做改写扩写。
    if opts.mode == 'promo':
        made, results = run_promo_mode(opts, ai, keywords, items)
        if not opts.dry_run:
            build_promo_index(results)
            # 主题页与分类页顺带刷新一次，
            # 让新引流文有入口可被爬虫顺着找到。
            build_tag_pages(items, [], keywords, ledger.done_slugs())
            prune_orphans()
            sp, n = build_all_sitemaps()
            log('sitemap：%d 条' % n)
            sitemap_render.build_robots()
            _ensure_css()
            # 推送：只推本轮新增/更新的 URL。
            # 每小时全量推送会触发限流，而且没变过的页面本来就不需要
            # 重新提交（IndexNow 官方明确建议只提交发生变化的部分）。
            sub = submit_mod.Submitter()
            since = opts.since_ms
            if since is None:
                # 没指定就以「本次运行开始前」为界，
                # 这样每轮只推这一轮真正产出的页面。
                since = int((t0 - 5) * 1000)
            urls = submit_mod.collect_urls(since_ms=since)
            st = sub.submit_all(urls)
            log('推送：%d 个 URL（IndexNow %s / 百度 %s）'
                % (st.get('urls', 0),
                   '开' if st.get('indexnow') else '未配',
                   '开' if st.get('baidu') else '未配'))
        summary = {
            'ts': int(time.time()), 'mode': 'promo',
            'duration_s': round(time.time() - t0, 1),
            'ai': {'available': ai.available, 'model': config.AI['MODEL'],
                   **ai.stats},
            'new_pages': made,
            'quality': q_mod.summarize(results) if results else {},
        }
        logp = ledger.log_run(summary)
        log('完成：新增 %d 篇引流文章，用时 %.1fs'
            % (made, summary['duration_s']))
        return 0

    if opts.mode == 'topic':
        made, results, kws = run_topic_mode(opts, ai, keywords)
        if not opts.dry_run:
            # 顺序很重要：先建关键词页，再建分类页。
            # 分类页要链向关键词页，反过来会链到还不存在的页面（死链）。
            build_keyword_pages(kws, made, results, ledger.done_slugs())
            # post 模式产出的内容也要纳入分类页，
            # 这样分类页的条目列表是全站聚合而不是只有关键词页。
            build_tag_pages(items, results, keywords,
                            ledger.done_slugs())
            # 清理僵尸页：slug 算法变更后会留下没人引用的旧路径，
            # 它们会被 sitemap 收进去并指向已删除的页面，形成死链。
            prune_orphans()
            pages = sitemap_render.collect_pages()
            idx = sitemap_render.build_index_entries()
            sp, n = sitemap_render.build_sitemap(pages, tag_pages=idx)
            log('sitemap：%d 条' % n)
            sitemap_render.build_robots()
            css_path = os.path.join(OUT_DIR, 'seo-assets', 'style.css')
            if not os.path.exists(css_path):
                tag_render.write_file(css_path, page_render.CSS)
        summary = {
            'ts': int(time.time()), 'mode': 'topic',
            'duration_s': round(time.time() - t0, 1),
            'ai': {'available': ai.available, 'model': config.AI['MODEL'],
                   **ai.stats},
            'new_pages': made,
            'quality': q_mod.summarize(results) if results else {},
        }
        logp = ledger.log_run(summary)
        log('完成：新增 %d 个关键词页，用时 %.1fs'
            % (made, summary['duration_s']))
        return 0

    # ---------- 3. 选批次 ----------
    published = ledger.done_slugs()
    candidates = []
    for it in items:
        if it.meta['slug'] in published and not opts.force:
            continue
        ok, why = ledger.should_process(it.seed_id, opts.force)
        if ok:
            candidates.append(it)
    # 优先级：没正文的最需要扩写 > 有热度的更重要
    candidates.sort(key=lambda x: (
        0 if len(x.body or '') < config.PIPELINE['MIN_DETAIL_LEN'] else 1,
        -(x.metrics.get('hit', 0) or 0)))
    if not opts.all:
        limit = (config.PIPELINE['FIRST_RUN_BATCH'] if not published
                 else config.PIPELINE['BATCH_SIZE'])
        if opts.batch:
            limit = opts.batch
        candidates = candidates[:limit]
    log('待处理 %d 条%s' % (len(candidates), '（全量）' if opts.all else ''))

    if opts.dry_run:
        for it in candidates[:20]:
            log('  将处理 %s [%s] %s' % (it.seed_id, it.tags[0], it.name[:24]))
        log('dry-run 结束，未写盘')
        return 0

    # ---------- 4. 逐篇生成 ----------
    index = links_mod.build_index(items)
    seen_h = ledger.seen_hashes()
    seen_t = ledger.seen_titles()
    results = []
    new_pages = 0

    # 内链白名单 = 已发布页面 + 本次已生成页面。
    # 必须随进度递增：第 1 篇不能链向第 2 篇，因为第 2 篇此刻还不存在。
    # 内链指向 404 会被判定为站点质量缺陷，比没有内链更糟。
    available = set(published)

    for i, it in enumerate(candidates, 1):
        tag = it.tags[0]
        try:
            content = asm.assemble(
                it, ai, keywords_for_tag=keywords.get(tag, []),
                index=index, pool=items, site_url=config.site_url,
                allowed_slugs=available)

            q = q_mod.evaluate(content, it, seen_h, seen_t)
            if not q['passed']:
                ledger.record(it.seed_id, content, status='skipped')
                log('  [%d/%d] ✗ 质量未过（%d分）%s — %s' % (
                    i, len(candidates), q['score'], it.name[:16],
                    '；'.join(q['reasons']) or '分数不足'))
                results.append(content)
                continue

            if not opts.dry_run:
                d = os.path.join(OUT_DIR, 'post', content['slug'])
                tag_render.write_file(
                    os.path.join(d, 'index.html'),
                    page_render.render_post(content, config.site_url))
                # content.json 存全量内容：后续重链/增量更新时不必
                # 重新调 AI，读它就能重新渲染页面。
                tag_render.write_file(
                    os.path.join(d, 'content.json'),
                    json.dumps(_strip(content), ensure_ascii=False, indent=2))

            ledger.record(it.seed_id, content, status='ok')
            seen_h[q_mod.simhash(content['body'])] = content['slug']
            seen_t.append(content['meta_title'])
            available.add(content['slug'])
            new_pages += 1
            log('  [%d/%d] ✓ %s — %d分 / %d字 / %d内链%s' % (
                i, len(candidates), content['slug'], q['score'],
                q['zh_len'], len(content.get('internal_links') or []),
                '（AI）' if content['by_ai'] else '（模板）'))
            results.append(content)

        except Exception as e:
            ledger.record_failure(it.seed_id, str(e))
            log('  [%d/%d] ✗ 异常 %s：%s' % (i, len(candidates), it.seed_id, e))
            if os.environ.get('SEO_DEBUG'):
                traceback.print_exc()

    # ---------- 5. 分类聚合页 ----------
    if not opts.dry_run:
        n_tag = build_tag_pages(items, results, keywords, published)
        log('分类聚合页 %d 个' % n_tag)

        # 清理僵尸页：slug 算法变更或账本重置后会留下没人引用的旧页面，
        # 它们会被 sitemap 收进去并指向已删除的页面，形成死链。
        prune_orphans()

        # ---------- 6. sitemap / robots ----------
        pages = sitemap_render.collect_pages()
        idx = sitemap_render.build_index_entries()
        sp, n = sitemap_render.build_sitemap(pages, tag_pages=idx)
        log('sitemap：%d 条 → %s' % (n, os.path.relpath(sp, config.ROOT)))
        rp = sitemap_render.build_robots()
        log('robots → %s' % os.path.relpath(rp, config.ROOT))

        # ---------- 7. 样式 ----------
        css_path = os.path.join(OUT_DIR, 'seo-assets', 'style.css')
        if not os.path.exists(css_path):
            tag_render.write_file(css_path, page_render.CSS)
        robots_in_html = _write_root_robots_link()

    # ---------- 8. 记账与日志 ----------
    summary = {
        'ts': int(time.time()),
        'duration_s': round(time.time() - t0, 1),
        'ai': {'available': ai.available, 'model': config.AI['MODEL'],
               **ai.stats},
        'candidates': len(candidates),
        'new_pages': new_pages,
        'quality': q_mod.summarize(results) if results else {},
        'tag': opts.tag or 'all',
        'force': opts.force,
    }
    logp = ledger.log_run(summary)
    ledger.prune_logs()
    log('完成：新增 %d 页，用时 %.1fs，日志 %s'
        % (new_pages, summary['duration_s'], os.path.relpath(logp, config.ROOT)))
    return 0


# ============================================================
# 分类聚合页
# ============================================================

def run_promo_mode(opts, ai, keywords, items):
    """产出引流文章（默认每小时 1 篇）。

    三种来源：随机抽站内帖改写洗稿 / 有正文则扩写 / 全新创作。
    源帖用过的记在账本里不再复用，避免同一篇被反复改写
    产生近似重复内容（对 SEO 是负分）。
    """
    entries = ledger.load_entries()
    used_src = set(v.get('source_slug') for v in entries.values()
                   if v.get('source_slug'))

    n_target = opts.batch or config.PIPELINE['PROMO_PER_RUN']
    results = []
    made = 0

    for i in range(n_target):
        # 交替使用三种模式，保证内容形态不单调
        mode = config.PIPELINE['PROMO_MODES'][i % len(
            config.PIPELINE['PROMO_MODES'])]

        src = None
        keyword = None
        if mode in ('rewrite', 'extend'):
            src = promo_mod.pick_source_post(items, used_src)
            if src is None:
                mode = 'fresh'
        if mode == 'fresh':
            keyword = promo_mod.pick_keyword(keywords)
            if not keyword:
                mode = 'rewrite'
                src = src or promo_mod.pick_source_post(items, used_src)

        item = promo_mod.build_promo_item(mode, src, keyword)

        if opts.dry_run:
            log('  将生成[%s] %s' % (mode, item['meta']['slug']))
            continue

        try:
            gen = promo_mod.generate(item, ai, keywords)
            content = promo_mod.assemble(item, gen, config.site_url)

            q = q_mod.evaluate(content, item, {}, [])
            if not q['passed']:
                ledger.record(item['seed_id'], content, status='skipped')
                log('  ✗ 质量未过（%d分）%s — %s' % (
                    q['score'], item['name'][:16],
                    '；'.join(q['reasons']) or '分数不足'))
                results.append(content)
                continue

            cta = [(t, config.TAG_SLUGS.get(t, 'zonghe'))
                   for t in sorted(config.TAG_SLUGS.keys())[:5]]
            html = page_render.render_promo(
                content, config.site_url, cta_extra=cta)
            d = os.path.join(PROMO_DIR, 'post', content['slug'])
            tag_render.write_file(os.path.join(d, 'index.html'), html)
            tag_render.write_file(
                os.path.join(d, 'content.json'),
                json.dumps(_strip(content), ensure_ascii=False, indent=2))

            content['source_slug'] = item['src'].meta.get('slug') \
                if item['src'] else None
            ledger.record(item['seed_id'], content, status='ok')
            made += 1
            log('  ✓ [%s] %s — %d分 / %d字%s' % (
                mode, content['slug'], q['score'], q['zh_len'],
                '（AI）' if content['by_ai'] else '（模板）'))
            results.append(content)
        except Exception as e:
            ledger.record_failure(item['seed_id'], str(e))
            log('  ✗ 异常 %s：%s' % (item['seed_id'], e))
            if os.environ.get('SEO_DEBUG'):
                traceback.print_exc()

    return made, results


def build_promo_index(results):
    """引流文索引页：/promo/ 。

    每小时新增一篇，索引页把它们列出来，
    让爬虫有一个固定的入口可以顺着找到所有最新文章。
    """
    items = []
    base = os.path.join(PROMO_DIR, 'post')
    if os.path.isdir(base):
        for name in os.listdir(base):
            f = os.path.join(base, name, 'content.json')
            if os.path.exists(f):
                try:
                    with io.open(f, encoding='utf-8') as fh:
                        items.append(json.load(fh))
                except Exception:
                    continue
    items.sort(key=lambda c: c.get('published', 0), reverse=True)
    items = items[:60]

    brand = config.SITE['BRAND']
    url = config.site_url('/promo/')
    title = '%s · 内容精选' % brand
    desc = '围绕图片分享社区话题整理的原创内容合集，每篇都附带进站入口。'
    cards = []
    for c in items:
        cards.append(
            '<a class="rel" href="%s"><div>'
            '<div style="font-weight:600;margin-bottom:3px">%s</div>'
            '<div style="color:var(--ink-3);font-size:12px">%s</div>'
            '</div></a>' % (
                page_render.esc(config.site_url('/promo/post/%s/' % c['slug'])),
                page_render.esc(c.get('meta_title', '')),
                page_render.esc((c.get('meta_description') or '')[:70])))
    body = """
<main>
  <div class="wrap">
    <nav class="crumb" aria-label="面包屑">
      <a href="%(home)s">首页</a> <span aria-hidden="true">›</span>
      <span>内容精选</span>
    </nav>
    <h1>%(brand)s内容精选</h1>
    <p style="color:var(--ink-2);margin-bottom:16px">共 %(count)d 篇，每篇都是围绕一个话题整理的原创内容。</p>
    <nav class="links" aria-label="文章列表">
      <div class="rel">%(cards)s</div>
    </nav>
    <nav class="cta" aria-label="进入社区">
      <a class="cta-main" href="%(home)s">进入社区看真实帖子</a>
    </nav>
  </div>
</main>""" % {
        'home': page_render.esc(config.site_url('/')),
        'brand': page_render.esc(brand), 'count': len(items),
        'cards': '\n'.join(cards) if cards else '<p>内容生成中。</p>',
    }
    schema = {
        '@context': 'https://schema.org',
        '@type': 'CollectionPage',
        '@id': url + '#page', 'url': url,
        'name': title, 'description': desc,
        'inLanguage': config.SITE['LANG'],
        'isPartOf': {'@type': 'WebSite', 'name': brand,
                     'url': config.site_url('/')},
        'mainEntity': {'@type': 'ItemList', 'numberOfItems': len(items)},
    }
    tag_render.write_file(
        os.path.join(PROMO_DIR, 'index.html'),
        tag_render._shell(title, desc, url, brand, config.site_url,
                          schema, body))
    return len(items)


def build_all_sitemaps():
    """同时生成主站 sitemap 与引流文 sitemap。

    分开的好处：引流文更新频率高（每小时），
    和主题页混在一个 sitemap 里会让主题页的更新信号被稀释。
    """
    main_path = os.path.join(OUT_DIR, 'sitemap.xml')
    pages = sitemap_render.collect_pages()
    idx = sitemap_render.build_index_entries()
    sp, n = sitemap_render.build_sitemap(pages, tag_pages=idx)

    promo_pages = []
    pbase = os.path.join(PROMO_DIR, 'post')
    if os.path.isdir(pbase):
        for name in os.listdir(pbase):
            f = os.path.join(pbase, name, 'content.json')
            if not os.path.exists(f):
                continue
            try:
                with io.open(f, encoding='utf-8') as fh:
                    c = json.load(fh)
            except Exception:
                continue
            promo_pages.append({
                'url': config.site_url('/promo/post/%s/' % name),
                'lastmod': sitemap_render._lastmod(
                    None, c.get('generated_at')),
                'changefreq': 'monthly', 'priority': '0.6',
            })
    if os.path.exists(os.path.join(PROMO_DIR, 'index.html')):
        promo_pages.insert(0, {
            'url': config.site_url('/promo/'),
            'lastmod': sitemap_render._today(),
            'changefreq': 'hourly', 'priority': '0.7',
        })
    sitemap_render.build_sitemap(promo_pages,
                                 out_path=os.path.join(PROMO_DIR,
                                                       'sitemap.xml'))
    return sp, n + len(promo_pages)


def _ensure_css():
    path = os.path.join(OUT_DIR, 'seo-assets', 'style.css')
    if not os.path.exists(path):
        tag_render.write_file(path, page_render.CSS)


def kind_of_dir(path):
    """从目录路径反推页面类型：'post' / 'kw' / 'tag'。

    用于自引用排除——判断「某页面是否链向了自己」。
    """
    p = os.path.abspath(path)
    for kind in ('post', 'kw', 'tag'):
        if os.sep + kind + os.sep in p:
            return kind
    return ''


def prune_orphans():
    """清理孤儿页面：磁盘上有、但不再被任何东西引用的陈旧页。

    为什么需要：
      早期版本用 `_kwslug` 生成关键词页 URL，后来改成 `topic_slug`，
      算法变更后旧路径就成了没人引用、也没人更新的僵尸页面。
      它们会被 sitemap 收集进去，又指向已删除的页面，形成死链。

    判据（三条都满足才删，宁可漏删不可误删）：
      1. 该页面不在账本的已发布集合里
      2. 页面对应的 content.json 缺失或其 seed 不在账本里
      3. 全站没有任何页面链接到它

    返回删除数量。
    """
    entries = ledger.load_entries()
    live_seeds = set(k for k, v in entries.items()
                     if v.get('status') == 'ok')
    published = ledger.done_slugs()

    # 收集全站入链。
    # 只看页面，不看 sitemap.xml —— sitemap 是从磁盘目录生成的，
    # 任何还在磁盘上的页面都会被它列进去，拿它当"有人引用"的依据
    # 会让所有僵尸页都显得有引用，永远删不掉。
    linked = set()
    for root, _dirs, files in os.walk(OUT_DIR):
        for fn in files:
            if not fn.endswith('.html'):
                continue
            try:
                with io.open(os.path.join(root, fn), encoding='utf-8') as f:
                    h = f.read()
            except Exception:
                continue
            for kind, slug in re.findall(
                    r'href="[^"]*/(post|kw|tag)/([^"/]+)/"', h):
                target = '%s/%s' % (kind, slug)
                # 排除自引用：陈旧页面常常在自己的关键词列表里链到自己，
                # 不排除的话它会永远"有引用"，prune 永远删不掉它
                # （实测卡在这里：一张旧 kw 页自锁，清理逻辑失效）
                if target == '%s/%s' % (kind_of_dir(root), os.path.basename(root)):
                    continue
                linked.add(target)

    removed = 0
    # 单次删除数量上限。本地开发环境有批量删除保护，
    # 一次删太多会被拦下；CI 环境不受此限制。
    cap = int(os.environ.get('SEO_PRUNE_CAP', '40'))
    skipped = 0
    for kind in ('post', 'kw', 'tag'):
        base = os.path.join(OUT_DIR, kind)
        if not os.path.isdir(base):
            continue
        for name in list(os.listdir(base)):
            if removed >= cap:
                skipped += 1
                continue
            key = '%s/%s' % (kind, name)
            if key in linked:
                continue                      # 有人链它，不能删
            if kind == 'post' and name in published:
                continue                      # 账本记为已发布，不能删
            cj = os.path.join(base, name, 'content.json')
            if os.path.exists(cj):
                try:
                    with io.open(cj, encoding='utf-8') as f:
                        seed = json.load(f).get('seed_id')
                except Exception:
                    seed = None
                if seed and seed in live_seeds:
                    continue                  # 活跃内容，不能删
            # 只删目录，不碰其他文件
            d = os.path.join(base, name)
            if os.path.isdir(d):
                try:
                    import shutil
                    shutil.rmtree(d)
                    removed += 1
                except Exception:
                    pass
    if removed:
        log('清理孤儿页面 %d 个' % removed)
    if skipped:
        # 不静默：被跳过的僵尸页仍会进 sitemap 并造成死链，
        # 下一轮或下下轮会清掉（cap 是分批清理，不是失败）
        log('另有 %d 个孤儿页面待清理（受单次上限 %d 限制，下轮继续）'
            % (skipped, cap))
    return removed


def existing_kw_slugs():
    """扫描磁盘，返回已存在的关键词页 slug 集合。

    从磁盘读而不是从账本算：关键词页的路径由 slug 算法决定，
    而 slug 算法改过一次（早期 _kwslug -> topic_slug）。
    账本算出来的和磁盘上实际存在的不一定一致，只有磁盘是准的。
    """
    out = set()
    d = os.path.join(OUT_DIR, 'kw')
    if os.path.isdir(d):
        for name in os.listdir(d):
            if os.path.exists(os.path.join(d, name, 'index.html')):
                out.add(name)
    return out


def build_tag_pages(items, results, keywords, published):
    """为每个分类生成聚合页。

    只收录**已生成**的页面（published 白名单）。
    早期版本把该分类所有真实帖子的 slug 都写进去，
    但那些页面大部分还不存在——一次跑下来能产生上百个死链。
    死链会被搜索引擎当作站点质量缺陷，比没有内链更糟。

    条目不足时也不硬凑：宁可页面条目少，也不能有死链。
    """
    n = 0
    by_tag = {}
    for it in items:
        by_tag.setdefault(it.tags[0], []).append(it)

    for tag, kws in keywords.items():
        pool = by_tag.get(tag) or []
        pool = sorted(pool, key=lambda x: -(x.metrics.get('hit', 0) or 0))
        posts = []
        for it in pool[:40]:
            slug = it.meta.get('slug')
            if not slug or slug not in published:
                continue
            _, clean = kw.strip_tag(it.name)
            posts.append({
                'slug': slug,
                'title': clean[:44] or it.name[:44],
                'summary': (it.body or it.name)[:80],
                'image': (it.images or [None])[0],
                'published': it.published,
                'hit': it.metrics.get('hit', 0),
            })

        # 关键词页也会链向分类页，所以**每个**分类都必须有页面。
        # 早期版本在这里 `if not posts: continue`，
        # 结果某些分类页不生成，而其他页面仍在链它 —— 死链。
        # 空分类照样渲染，条目区显示占位说明。
        path = os.path.join(OUT_DIR, 'tag',
                            config.TAG_SLUGS.get(tag, 'zonghe'), 'index.html')
        tag_render.write_file(path, tag_render.render_tag_page(
            tag, kws, posts, config.site_url,
            allowed_kw=existing_kw_slugs()))
        n += 1
    return n


def _strip(content):
    """存盘前的精简：去掉 quality 里的调试字段，保留全量内容字段。

    保留全量是因为后续要靠它重新渲染（重链、换模板、改广告配置），
    不必再调一次 AI。
    """
    out = dict(content)
    q = out.get('quality') or {}
    out['quality'] = {k: q.get(k) for k in
                      ('passed', 'score', 'zh_len', 'paragraphs', 'by_ai')}
    return out


# ============================================================
# 关键词页模式（与真实帖子解耦）
# ============================================================

def run_topic_mode(opts, ai, keywords):
    """按「关键词 × 角度」生成主题页。

    与 post 模式的区别：
      - 不读任何真实帖子的正文/图片/用户信息
      - 生产单位是关键词×角度，不是帖子
      - 页面数量不受真实帖子数量限制
    """
    from .pipeline import topic as topic_mod

    # 汇总所有关键词（打散分类，保持多样性）
    kws = []
    seen = set()
    for cat, words in keywords.items():
        for w in words:
            if w not in seen:
                seen.add(w)
                kws.append(w)

    # 跳过已生成的
    published = ledger.done_slugs()
    entries = ledger.load_entries()
    done_seeds = set(entries.keys())

    limit = opts.batch or config.PIPELINE['BATCH_SIZE']
    angles_per = int(os.environ.get('SEO_ANGLES_PER_KW', '2'))
    # 用已生成数量做轮转，让后续批次从不同角度开始
    rotate = len(done_seeds)

    plan = topic_mod.plan_topics(kws, angles_per, rotate)
    todo = []
    for kw, ak, ad in plan:
        t = topic_mod.build_topic_item(kw, ak, ad)
        if t['seed_id'] in done_seeds:
            continue
        if t['meta']['slug'] in published and not opts.force:
            continue
        todo.append(t)
    todo = todo[:limit]

    log('关键词页模式：%d 个关键词 × %d 角度，本轮 %d 篇'
        % (len(kws), angles_per, len(todo)))
    if opts.dry_run:
        for t in todo[:15]:
            log('  将生成 %s【%s】 %s' % (
                t['keyword'], t['angle'], t['meta']['slug']))
        return 0, [], kws

    available = set(published)
    results = []
    made = 0
    for i, t in enumerate(todo, 1):
        try:
            gen = topic_mod.generate_topic(t, ai)
            content = topic_mod.assemble_topic(t, gen)

            q = q_mod.evaluate(content, t, {}, [])
            if not q['passed']:
                ledger.record(t['seed_id'], content, status='skipped')
                log('  [%d/%d] ✗ 质量未过（%d分）%s — %s' % (
                    i, len(todo), q['score'], t['keyword'],
                    '；'.join(q['reasons']) or '分数不足'))
                results.append(content)
                continue

            if not opts.dry_run:
                d = os.path.join(OUT_DIR, 'post', content['slug'])
                tag_render.write_file(
                    os.path.join(d, 'index.html'),
                    page_render.render_post(content, config.site_url))
                tag_render.write_file(
                    os.path.join(d, 'content.json'),
                    json.dumps(_strip(content), ensure_ascii=False, indent=2))

            ledger.record(t['seed_id'], content, status='ok')
            available.add(content['slug'])
            made += 1
            log('  [%d/%d] ✓ %s — %d分 / %d字%s' % (
                i, len(todo), content['slug'], q['score'], q['zh_len'],
                '（AI）' if content['by_ai'] else '（模板）'))
            results.append(content)
        except Exception as e:
            ledger.record_failure(t['seed_id'], str(e))
            log('  [%d/%d] ✗ 异常 %s：%s' % (i, len(todo), t['seed_id'], e))
            if os.environ.get('SEO_DEBUG'):
                traceback.print_exc()

    return made, results, kws


def _write_root_robots_link():
    """确保 robots.txt 里的 Sitemap 指向可访问的绝对地址。"""
    return True


def build_keyword_pages(keywords, made, results, published):
    """为每个关键词生成聚合页（/kw/<slug>/）。

    关键词页和分类页是两种不同粒度的入口：
      分类页按内容分区（举牌/原创/…）
      关键词页按搜索词（引流的实际入口）
    两者互链，关键词页再链向分类页，形成三层结构。

    keywords 是扁平关键词列表（run_topic_mode 已经把各分类的词打散）。
    """
    from .pipeline import topic as topic_mod
    n = 0
    by_kw = {}
    for c in results:
        kw = c.get('keyword')
        if kw:
            by_kw.setdefault(kw, []).append(c)

    all_kws = set(keywords) | set(by_kw.keys())
    for kw in sorted(all_kws):
        pages = by_kw.get(kw) or []
        tag = topic_mod.rw.item_tags_or_default(kw)[0]
        path = os.path.join(OUT_DIR, 'kw',
                            topic_mod.rw.topic_slug(kw, 'index'), 'index.html')
        html = tag_render.render_keyword_page(
            kw, tag, pages, config.site_url)
        tag_render.write_file(path, html)
        n += 1
    return n


def parse_args(argv):
    class O(object):
        pass
    o = O()
    o.batch = None
    o.all = False
    o.force = False
    o.dry_run = False
    o.tag = None
    # post=基于真实帖子改写；topic=关键词×角度；promo=引流文章
    o.mode = os.environ.get('SEO_MODE', 'promo')
    # 只推送这个时间点之后修改过的页面（毫秒时间戳）
    o.since_ms = None
    if os.environ.get('SEO_SINCE_MS'):
        try:
            o.since_ms = int(os.environ['SEO_SINCE_MS'])
        except ValueError:
            o.since_ms = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == '--batch' and i + 1 < len(argv):
            o.batch = int(argv[i + 1]); i += 1
        elif a == '--mode' and i + 1 < len(argv):
            o.mode = argv[i + 1]; i += 1
        elif a == '--since' and i + 1 < len(argv):
            try:
                o.since_ms = int(argv[i + 1])
            except ValueError:
                pass
            i += 1
        elif a == '--all':
            o.all = True
        elif a == '--force':
            o.force = True
        elif a == '--dry-run':
            o.dry_run = True
        elif a == '--tag' and i + 1 < len(argv):
            o.tag = argv[i + 1]; i += 1
        elif a in ('-h', '--help'):
            print(__doc__)
            sys.exit(0)
        i += 1
    return o


if __name__ == '__main__':
    sys.exit(main())
