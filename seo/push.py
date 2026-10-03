"""搜索引擎主动推送。

增删改查的是收录速度，不是内容本身，所以跟生成解耦：
    IndexNow / Bing   每轮推，只推最近的一批（全量推反而容易被忽略）
    百度             24 小时一次推全量，靠日志里的时间戳降频
    Google           不在这推，交一次 sitemap 就够了

环境变量：
    BAIDU_TOKEN   百度普通收录 token（可选）
    BING_API_KEY  必应 Webmaster API key（可选）
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')
LEDGER = os.path.join(HERE, 'ledger.json')
LOG = os.path.join(HERE, 'push-log.json')

SITE_HOST = os.environ.get('SITE_HOST', 'banznx.github.io')
BASE = 'https://%s/foot-job' % SITE_HOST
INDEXNOW_KEY = 'ce0fc90e93dbe618c6f918b648d43583'
KEY_LOCATION = '%s/%s.txt' % (BASE, INDEXNOW_KEY)
BAIDU_INTERVAL = 24 * 3600 * 1000


def load_ledger():
    try:
        with open(LEDGER, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {'posts': []}


def load_log():
    try:
        with open(LOG, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_log(log):
    # 同 run.py：Windows 上目标被占用时 replace 会失败，退回直接写
    text = json.dumps(log, ensure_ascii=False, indent=2)
    tmp = LOG + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(text)
    try:
        os.replace(tmp, LOG)
    except OSError:
        with open(LOG, 'w', encoding='utf-8') as f:
            f.write(text)
        try:
            os.remove(tmp)
        except OSError:
            pass


def recent_urls(posts, n=10):
    urls = ['%s/blog/' % BASE]
    for p in list(reversed(posts))[:n]:
        urls.append('%s/blog/posts/%s.html' % (BASE, p['slug']))
    return urls


def all_urls(posts):
    return ['%s/blog/' % BASE] + ['%s/blog/posts/%s.html' % (BASE, p['slug']) for p in posts]


def post(url, data, headers, timeout=30):
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode('utf-8', 'ignore')
    except urllib.error.HTTPError as e:
        body = ''
        try:
            body = e.read().decode('utf-8', 'ignore')
        except Exception:
            pass
        return e.code, body
    except Exception as e:
        return 0, str(e)


def push_indexnow(urls):
    body = json.dumps({
        'host': SITE_HOST,
        'key': INDEXNOW_KEY,
        'keyLocation': KEY_LOCATION,
        'urlList': urls,
    }, ensure_ascii=False).encode('utf-8')
    for endpoint in ('https://api.indexnow.org/indexnow', 'https://www.bing.com/indexnow'):
        status, text = post(endpoint, body, {'Content-Type': 'application/json; charset=utf-8'})
        if status in (200, 202):
            print('  IndexNow 成功 %d（%d 条）' % (status, len(urls)))
            return {'success': True, 'status': status, 'endpoint': endpoint}
        print('  IndexNow %s 返回 %d：%s' % (endpoint, status, text[:120]))
    return {'success': False}


def push_bing(urls):
    key = os.environ.get('BING_API_KEY')
    if not key:
        return {'success': False, 'skipped': True, 'reason': '未配置 BING_API_KEY'}
    status, text = post(
        'https://www.bing.com/webmaster/api.aspx?apiKey=%s' % key,
        '\n'.join(urls).encode('utf-8'),
        {'Content-Type': 'text/plain'},
    )
    ok = 200 <= status < 300
    print('  必应 %s（%d 条）' % ('成功' if ok else '失败 %d' % status, len(urls)))
    return {'success': ok, 'status': status}


def push_baidu(urls, log):
    token = os.environ.get('BAIDU_TOKEN')
    last = log.get('results', {}).get('baidu', {}).get('lastPushedAt')
    if last:
        try:
            then = datetime.fromisoformat(last.replace('Z', '+00:00'))
            gap = (datetime.now(timezone.utc) - then).total_seconds() * 1000
            if gap < BAIDU_INTERVAL:
                print('  百度距上次不足 24 小时，跳过')
                return {'success': False, 'skipped': True, 'reason': '降频', 'lastPushedAt': last}
        except ValueError:
            pass
    if not token:
        return {'success': False, 'skipped': True, 'reason': '未配置 BAIDU_TOKEN'}
    status, text = post(
        'http://data.zz.baidu.com/urls?site=%s/foot-job&token=%s' % (SITE_HOST, token),
        '\n'.join(urls).encode('utf-8'),
        {'Content-Type': 'text/plain'},
    )
    now = datetime.now(timezone.utc).isoformat()
    print('  百度 状态 %d：%s' % (status, text[:120]))
    return {'success': status == 200, 'status': status, 'raw': text[:200], 'lastPushedAt': now}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--all', action='store_true', help='推送全部文章而不只是最近的')
    ap.add_argument('--dry-run', action='store_true', help='只打印待推送地址，不真的发请求')
    args = ap.parse_args()

    posts = load_ledger().get('posts', [])
    if not posts:
        print('没有可推送的文章')
        return
    log = load_log()
    urls = all_urls(posts) if args.all else recent_urls(posts)
    print('待推送 %d 条' % len(urls))
    if args.dry_run:
        for u in urls:
            print('  ', u)
        return

    result = {
        'updatedAt': datetime.now(timezone.utc).isoformat(),
        'urlCount': len(urls),
        'results': {
            'indexnow': push_indexnow(urls),
            'bing': push_bing(urls),
            'baidu': push_baidu(all_urls(posts), log),
        },
    }
    save_log(result)
    print('推送完成')


if __name__ == '__main__':
    main()
