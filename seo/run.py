"""SEO 内容生成主流程：抽图 -> 看图 -> 写文 -> 清洗 -> 出页 -> 更新索引。

用法：
    python seo/run.py                 # 生成 1 篇
    python seo/run.py --batch 20      # 生成 20 篇
    python seo/run.py --dry-run       # 只看会抽到哪些图，不写文件

没有配置 BIGMODEL_API_KEY 时会自动走模板降级，照样能产出页面，
这样 fork 之后定时任务不会红，本地也能验证整条链路。
"""
import argparse
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import glm
import images as imglib
import render

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
LEDGER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ledger.json')
POSTS_DIR = os.path.join(ROOT, 'blog', 'posts')
PAGE_DIR = os.path.join(ROOT, 'blog', 'page')
BLOG_INDEX = os.path.join(ROOT, 'blog', 'index.html')
SITEMAP = os.path.join(ROOT, 'sitemap.xml')
PAGE_SIZE = 20

TZ = timezone(timedelta(hours=8))  # 固定北京时间，避免 Actions 的 UTC 让日期偏移

EMOJI = re.compile(
    '[\U0001F300-\U0001F9FF\U0001F600-\U0001F64F\u2600-\u26FF'
    '\u2700-\u27BF\uFE00-\uFE0F\U0001F000-\U0001F02F'
    '\U0001F0A0-\U0001F0FF\U0001F100-\U0001F1FF\U0001F200-\U0001F2FF]'
)
OPENERS = re.compile(r'^\s*(?:随着|在当今|在如今|如今|近年来|当下|眼下|伴随着)')
JUNK = [
    r'点赞[^<]*$', r'转发[^<]*$', r'关注[^<]*$', r'记得点赞转发哦[^<]*',
    r'祝大家[^<]*[！!]', r'财源广进[^<]*', r'生意兴隆[^<]*',
    r'以上内容仅供参考[^<]*', r'希望这篇文章对你有所帮助[^<]*$',
    r'以上就是[^<]*希望[^<]*对你有帮助[^<]*', r'好了今天的分享就到这里[^<]*',
    r'让我们一起加油[^<]*', r'如有疑问欢迎随时咨询[^<]*',
]
# 结尾必须落在完整句子上。参考项目没做这步，实测有文章断在半句。
TAIL_OK = re.compile(r'</(p|li|blockquote|h2|h3)>\s*$', re.I)

# 模板降级用的素材，只有没配 API key 时才会用到
FALLBACK_MOODS = ['清爽', '慵懒', '复古', '日常', '温柔', '街头']
FALLBACK_TOPICS = [
    '随手拍的一组日常', '这组照片的氛围感', '周末拍的几张',
    '换个角度看日常', '光线刚好时的记录', '一套很耐看的搭配',
]


def today():
    return datetime.now(TZ).strftime('%Y-%m-%d')


def load_ledger():
    try:
        with open(LEDGER, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    data.setdefault('posts', [])
    data.setdefault('used_files', [])
    return data


def _write_json(path, data):
    """原子写：先写临时文件再替换，避免中断留下半截文件。

    Windows 上目标文件被编辑器或索引服务占用时 os.replace 会拒绝访问，
    这时退回直接覆盖写，总比整个流程失败好。
    """
    text = json.dumps(data, ensure_ascii=False, indent=2)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(text)
    try:
        os.replace(tmp, path)
    except OSError:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        try:
            os.remove(tmp)
        except OSError:
            pass


def save_ledger(ledger):
    _write_json(LEDGER, ledger)


def clean_body(body):
    """清洗模型输出。

    提示词里禁过的套话，模型还是会写，所以真正的兜底在这里。
    """
    body = re.sub(r'\[/?[A-Z_]{2,20}\]', '', body)
    body = EMOJI.sub('', body)
    body = re.sub(r'^```(?:html)?\s*', '', body).replace('```', '')
    body = re.sub(r'^\s*<p>\s*%s[\s\S]*?</p>' % OPENERS.pattern, '', body, flags=re.I)
    body = re.sub(r'^\s*<p>\s*</p>', '', body)
    for pat in JUNK:
        body = re.sub(pat, '', body, flags=re.M)
    body = re.sub(r'<p>\s*</p>', '', body)
    body = re.sub(r'(<hr\s*/?>\s*){2,}', '<hr/>', body)
    body = re.sub(r'<hr\s*/?>\s*$', '', body)
    body = re.sub(r'\n{3,}', '\n\n', body)
    return body.strip()


def is_complete(body, min_chars=1000):
    """结尾完整性校验。模型被输出上限截断时会停在半句，这种文章不能要。"""
    if len(re.sub(r'<[^>]+>', '', body)) < min_chars:
        return False
    return bool(TAIL_OK.search(body))


def fallback_article(group, idx, seen=None):
    """降级内容：结构完整、图文对得上，只是文字平一些。

    seen 是看图成功但写文失败时的素材描述。这种情况下标题、描述、开头段
    都用模型真实看图得出的内容，只有中段是模板——比纯随机词强得多。
    """
    mood = (seen or {}).get('mood') or FALLBACK_MOODS[idx % len(FALLBACK_MOODS)]
    topic = (seen or {}).get('topic') or FALLBACK_TOPICS[idx % len(FALLBACK_TOPICS)]
    desc = (seen or {}).get('desc') or ''
    title = '%s · %s的一组记录' % (topic, mood)
    opening = ('<p>%s</p>' % desc) if desc else (
        '<p>翻到这组图的时候，第一感觉是%s。没有刻意摆姿势，'
        '画面里的东西都处在各自该在的位置上，看着很舒服。</p>' % mood)
    body = (
        '<h2>这组图的氛围</h2>'
        + opening +
        '<p>色调偏自然，没有过度修饰的痕迹，这种处理方式反而是最耐看的。'
        '放一段时间再回头看，也不会觉得过时。</p>'
        '<h2>拍摄上的几个细节</h2>'
        '<p>构图留了足够的空间，主体没有顶满画面，边缘保留了一些环境信息，'
        '这让照片有了可以想象的地方。</p>'
        '<ul><li>光线选在柔和的时段，避免硬阴影</li>'
        '<li>背景尽量干净，不抢主体</li>'
        '<li>连拍比单张更容易抓到自然的状态</li></ul>'
        '<h2>如果想拍出类似的感觉</h2>'
        '<p>先别急着按快门，花一点时间观察现场的光从哪个方向来，'
        '再决定站位。这一步做对，后面怎么拍都不会太差。</p>'
        '<p>另外就是别怕拍废。翻一翻自己的相册，好看的那张往往出现在'
        '你不刻意控制的时候。</p>'
        '<h2>小结</h2>'
        '<p>好的一组图不需要多复杂的技巧，把光线、构图和状态这三件事'
        '处理妥当，就已经赢过大半。挑个时间，自己也去拍一组试试。</p>'
    )
    summary = desc[:110] if desc else '整体氛围%s，记录了社区里一组真实的日常影像。' % mood
    return {
        'title': title,
        'description': summary,
        'keywords': [mood, '日常记录', '社区分享'],
        'body': body,
        'category': mood,
        'degraded': True,
    }


def make_post(group, idx, ledger):
    """生成一篇文章。返回 dict 或 None（失败）。"""
    imgs = group['images']
    urls = [i['url'] for i in imgs]

    article = None
    seen = None
    if glm.has_key():
        seen = glm.look(urls)
        if seen:
            desc = seen.get('desc', '')
            topic = seen.get('topic', '')
            kws = seen.get('keywords', '')
            raw = glm.write(desc, topic, kws)
            if raw:
                parsed = glm.parse_blocks(raw, '写文结果')
                article = {
                    'title': parsed.get('title') or topic or '社区分享',
                    'description': parsed.get('description', ''),
                    'keywords': [k.strip() for k in parsed.get('keywords', '').split(',') if k.strip()],
                    'body': clean_body(parsed.get('content', '')),
                    'category': (parsed.get('keywords', '').split(',') or ['分享'])[0].strip() or '分享',
                    'degraded': False,
                }
                # 结尾被截断就重来一次，参考项目栽在这上面
                if not is_complete(article['body']):
                    print('  结尾不完整，重写一次')
                    raw = glm.write(desc, topic, kws)
                    if raw:
                        p2 = glm.parse_blocks(raw, '写文重试')
                        body2 = clean_body(p2.get('content', ''))
                        if len(body2) > len(article['body']):
                            article['body'] = body2
                            article['title'] = p2.get('title') or article['title']

    if article is None:
        if seen:
            print('  看图成功但写文受限，用真实看图结果拼一篇')
        else:
            print('  走模板降级（未配置 API key 或接口不可用）')
        article = fallback_article(group, idx, seen)

    # slug 由代码定，不让模型碰 —— 模型给 slug 有四分之一的几率是废的
    slug = 'p-%s' % group['post_id']
    if any(p['slug'] == slug for p in ledger['posts']):
        slug = 'p-%s-%d' % (group['post_id'], len(ledger['posts']))

    body = render.insert_figures(article['body'], imgs, article.get('category') or '')
    words = len(re.sub(r'<[^>]+>', '', body))

    return {
        'slug': slug,
        'title': article['title'].strip(),
        'description': (article['description'] or article['title']).strip()[:150],
        'keywords': article.get('keywords') or [],
        'category': article.get('category') or '分享',
        'date': today(),
        'words': words,
        'body': body,
        'image': imgs[0]['url'],
        'files': [i['file'] for i in imgs],
        'degraded': article.get('degraded', False),
    }


def rebuild_index(ledger):
    """重建列表页、分页和站点地图。每次全量重写，保证链接不会指向已删页面。"""
    posts = list(reversed(ledger['posts']))
    total_pages = max(1, (len(posts) + PAGE_SIZE - 1) // PAGE_SIZE)

    os.makedirs(PAGE_DIR, exist_ok=True)
    for page in range(1, total_pages + 1):
        chunk = posts[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
        html_text = render.render_index(chunk, page, total_pages)
        target = BLOG_INDEX if page == 1 else os.path.join(PAGE_DIR, '%d.html' % page)
        with open(target, 'w', encoding='utf-8') as f:
            f.write(html_text)

    # 清理多余的分页文件，否则会留下指向空内容的死链
    keep = {'%d.html' % n for n in range(2, total_pages + 1)}
    for name in os.listdir(PAGE_DIR):
        if name not in keep:
            try:
                os.remove(os.path.join(PAGE_DIR, name))
            except OSError:
                pass

    with open(SITEMAP, 'w', encoding='utf-8') as f:
        f.write(render.render_sitemap(posts))
    return total_pages


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--batch', type=int, default=1, help='本次生成篇数')
    ap.add_argument('--dry-run', action='store_true', help='只打印会抽到的图，不写文件')
    ap.add_argument('--seed', type=int, default=None)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    ledger = load_ledger()
    print('账本已有 %d 篇' % len(ledger['posts']))
    glm.diag('开始运行：请求 %d 篇，key %s'
             % (args.batch, '已配置' if glm.has_key() else '缺失'))

    groups = imglib.scan()
    if not groups:
        sys.exit('没有找到可用的图片素材')
    print('可用图组 %d 个' % len(groups))

    used_files = set(ledger['used_files'])
    made = 0
    degraded = 0
    for i in range(args.batch):
        group = imglib.pick_group(groups, used_files, rng=rng)
        if not group:
            print('素材抽完了')
            break
        print('第 %d 篇：图组 %s（%d 张）' % (i + 1, group['post_id'], len(group['images'])))
        if args.dry_run:
            for im in group['images']:
                print('   ', im['file'], '%dx%d' % (im['w'], im['h']))
            used_files.update(im['file'] for im in group['images'])
            continue

        post = make_post(group, i, ledger)
        os.makedirs(POSTS_DIR, exist_ok=True)
        # 内链只指向已经生成的页面，避免死链
        related = [p for p in reversed(ledger['posts']) if p['slug'] != post['slug']][:4]
        with open(os.path.join(POSTS_DIR, post['slug'] + '.html'), 'w', encoding='utf-8') as f:
            f.write(render.render_post(post, related))

        ledger['posts'].append({k: post[k] for k in
                                ('slug', 'title', 'description', 'category', 'date', 'words', 'image', 'keywords')})
        ledger['used_files'].extend(post['files'])
        used_files.update(post['files'])
        save_ledger(ledger)
        made += 1
        degraded += 1 if post['degraded'] else 0
        print('   -> %s（%d 字%s）' % (post['slug'], post['words'], '，降级' if post['degraded'] else ''))
        if glm.has_key():
            time.sleep(2)  # 免费模型只有 1 并发，慢一点更稳

    if not made:
        return

    # 配了 key 却一篇都没写成，说明接口有问题。这时候提交上去的会是一批
    # 模板拼出来的薄内容，宁可让任务失败让人看见，也别静默污染站点。
    if glm.has_key() and degraded == made:
        sys.exit('配了 BIGMODEL_API_KEY 但全部走了降级，接口不可用，本次不提交')

    pages = rebuild_index(ledger)
    print('索引已重建，共 %d 页，累计 %d 篇' % (pages, len(ledger['posts'])))


if __name__ == '__main__':
    main()
