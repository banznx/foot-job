# -*- coding: utf-8 -*-
"""
搜索引擎主动推送。

为什么不推而是等爬虫自己发现：
    新页面从上线到被收录，等爬虫主动发现要 1-7 天。
    主动推送能把这段时间压到几小时。对「每小时产一篇」的策略来说，
    这个时延直接决定了内容多久能开始带来流量。

三条通道，各自独立、互不影响：

  1. **IndexNow**（推荐首选）
     一次提交同时通知 Bing / 百度 / Yandex / Yahoo / Seznam 等十多家。
     实现最简单：POST 一个 JSON，key 要么放请求头，
     要么在站点根目录放同名 txt 文件让爬虫校验。
     —— 本系统用**文件方式**，因为请求头方式在 GitHub Pages
     的静态托管下无法自定义 header。

  2. **百度主动推送**
     百度有独立接口，收录速度最快。
     token 从百度搜索资源平台拿，形如 `https://data.zz.baidu.com/urls.txt?token=xxx`
     body 是纯文本，一行一个 URL。

  3. **Google**
     Google 已**废弃** sitemap ping 接口（2023 年正式下线），
     任何 ping 都会被忽略。Google 只能靠：
       - 定期更新 sitemap.xml（本系统每小时都在更新）
       - Search Console 手动提交 / API
     所以这里不做无效请求，只在日志里提示。

只依赖标准库 urllib，和项目其他部分保持一致。
"""

import io
import json
import os
import re
import time
import urllib.error
import urllib.request

from . import config


class Submitter(object):

    def __init__(self, cfg=None):
        self.cfg = cfg or config.SUBMIT
        self.stats = {'indexnow_ok': 0, 'indexnow_fail': 0,
                      'baidu_ok': 0, 'baidu_fail': 0,
                      'skipped': 0, 'error': 0}

    # ---------------------------------------------------------
    def ensure_key_file(self):
        """把 IndexNow 密钥写到站点根目录。

        IndexNow 的两种鉴权方式里，文件方式适合静态托管：
        爬虫请求 https://站点/<key>.txt 拿到内容，
        内容与提交请求里的 key 一致即视为通过。

        路径在这里动态计算，不用 config 里的模块级常量——
        那个常量在 import 时就固定了，运行时注入的 key
        会算出错误路径，导致提交被静默跳过。
        """
        key = self.cfg.get('INDEXNOW_KEY')
        if not key:
            return None
        # key 只能含字母数字与连字符/下划线，正好可直接做文件名
        if not re.match(r'^[A-Za-z0-9_-]{8,128}$', key):
            print('[seo] IndexNow key 格式不合法'
                  '（需 8-128 位字母数字/连字符），已跳过', flush=True)
            return None
        path = os.path.join(config.ROOT, '%s.txt' % key)
        try:
            with io.open(path, 'w', encoding='utf-8') as f:
                f.write(key)
            return path
        except Exception as e:
            print('[seo] IndexNow key 文件写入失败：%s' % e, flush=True)
            return None

    # ---------------------------------------------------------
    def submit_indexnow(self, urls):
        """IndexNow 批量提交。"""
        key = self.cfg.get('INDEXNOW_KEY')
        if not key or not urls:
            return False
        if not self.ensure_key_file():
            self.stats['skipped'] += 1
            return False

        endpoint = self.cfg['INDEXNOW_ENDPOINT']
        payload = {
            'host': _host(config.site_url('/')),
            'key': key,
            # keyLocation 告诉搜索引擎去哪里取密钥，
            # 显式写出来比让它猜更稳。
            'keyLocation': config.site_url('/%s.txt' % key),
            'urlList': list(urls),
        }
        ok = _post_json(endpoint, payload)
        if ok:
            self.stats['indexnow_ok'] += len(urls)
        else:
            self.stats['indexnow_fail'] += len(urls)
        return ok

    # ---------------------------------------------------------
    def submit_baidu(self, urls):
        """百度主动推送。

        注意：百度接口要求 body 是 text/plain 的纯文本 URL 列表，
        不是 JSON。历史上很容易踩这个坑。
        """
        token = self.cfg.get('BAIDU_TOKEN')
        if not token or not urls:
            return False
        endpoint = '%s?token=%s' % (self.cfg['BAIDU_ENDPOINT'], token)
        body = '\n'.join(urls).encode('utf-8')
        ok = _post_text(endpoint, body)
        if ok:
            self.stats['baidu_ok'] += len(urls)
        else:
            self.stats['baidu_fail'] += len(urls)
        return ok

    # ---------------------------------------------------------
    def submit_google(self, urls):
        """Google：不做无效请求。

        Google 已于 2023 年正式**废弃** sitemap ping 接口，
        任何 ping 都会被忽略。而 IndexNow 协议 Google 也不参与。

        Google 的正确做法：
          1. sitemap.xml 保持更新（本系统每小时都在更新，够了）
          2. 在 Search Console 后台用「网址检查」手动提交
             （API 提交需要 OAuth 授权，配置成本高，收益有限）
        所以这里只返回 None 并留日志说明，不发请求。
        """
        return None

    # ---------------------------------------------------------
    def submit_all(self, urls):
        """把所有通道都跑一遍，返回统计摘要。

        任何一条通道失败都不影响其他通道 ——
        没配 key 就跳过，配了但失败只记日志。
        推送失败不该让整个流水线失败，那会导致内容产出了却没提交上去。
        """
        if not self.cfg.get('ENABLED'):
            return {'enabled': False, 'urls': len(urls), **self.stats}
        if not urls:
            return {'enabled': True, 'urls': 0, **self.stats}

        urls = list(urls)[:self.cfg['BATCH_MAX']]

        try:
            self.submit_indexnow(urls)
        except Exception as e:
            self.stats['error'] += 1
            print('[seo] IndexNow 异常：%s' % e, flush=True)
        try:
            self.submit_baidu(urls)
        except Exception as e:
            self.stats['error'] += 1
            print('[seo] 百度推送异常：%s' % e, flush=True)

        return {
            'enabled': True,
            'urls': len(urls),
            'indexnow': bool(self.cfg.get('INDEXNOW_KEY')),
            'baidu': bool(self.cfg.get('BAIDU_TOKEN')),
            **self.stats,
        }


# ============================================================
# URL 收集
# ============================================================

def collect_urls(since_ms=None):
    """收集要推送的 URL。

    since_ms: 只收集这个时间点之后修改过的页面。
    每小时只推新增/更新的那几个 URL，而不是全量——
    全量推会被限流，而且没有意义（没变的页面不需要重新提交）。

    所有静态单页都在同一个目录下（v4 起），
    URL 一律用 config.page_url() 生成，不自己拼路径。
    """
    urls = []
    base_dir = config.OUTPUT_DIR
    if not os.path.isdir(base_dir):
        return urls

    # 总索引页：pages/index.html 对应 URL /pages/，不是 /pages/index/
    idx = os.path.join(base_dir, 'index.html')
    if os.path.exists(idx) and (not since_ms or _mtime(idx) >= since_ms):
        urls.append(config.site_url(
            '/%s/' % config.PIPELINE['OUT_DIR']))

    for name in sorted(os.listdir(base_dir)):
        d = os.path.join(base_dir, name)
        if not os.path.isdir(d):
            continue
        path = os.path.join(d, 'index.html')
        if not os.path.exists(path):
            continue
        if since_ms and _mtime(path) < since_ms:
            continue
        urls.append(config.page_url(name))
    return urls


def collect_sitemap_urls():
    """全量 URL（不带时间过滤），用于首次提交。"""
    return collect_urls(None)


# ============================================================
# HTTP
# ============================================================

def _post_json(url, payload, timeout=20):
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        url, data=data, method='POST',
        headers={'Content-Type': 'application/json; charset=utf-8',
                 'User-Agent': 'foot-job-seo/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode('utf-8', 'ignore')
            ok = 200 <= resp.status < 300
            print('[seo] IndexNow HTTP %s：%s' % (resp.status, body[:120]),
                  flush=True)
            return ok
    except urllib.error.HTTPError as e:
        detail = e.read().decode('utf-8', 'ignore')[:120]
        print('[seo] IndexNow 失败 HTTP %d：%s' % (e.code, detail), flush=True)
        return False
    except Exception as e:
        print('[seo] IndexNow 异常：%s' % e, flush=True)
        return False


def _post_text(url, body, timeout=20):
    req = urllib.request.Request(
        url, data=body, method='POST',
        headers={'Content-Type': 'text/plain; charset=utf-8',
                 'User-Agent': 'foot-job-seo/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode('utf-8', 'ignore')
            ok = 200 <= resp.status < 300
            print('[seo] 百度推送 HTTP %s：%s' % (resp.status, text[:120]),
                  flush=True)
            return ok
    except urllib.error.HTTPError as e:
        detail = e.read().decode('utf-8', 'ignore')[:120]
        print('[seo] 百度推送失败 HTTP %d：%s' % (e.code, detail), flush=True)
        return False
    except Exception as e:
        print('[seo] 百度推送异常：%s' % e, flush=True)
        return False


def _host(url):
    s = url.split('://', 1)[-1]
    return s.split('/', 1)[0]


def _mtime(path):
    try:
        return os.path.getmtime(path) * 1000.0
    except Exception:
        return 0
