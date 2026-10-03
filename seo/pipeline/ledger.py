# -*- coding: utf-8 -*-
"""
幂等账本 + 运行日志。

解决三个具体问题：

1. **重复提交**：定时任务每天跑，如果生成结果和上次一样还去 commit，
   会刷出一堆无意义的空提交，还会让 GitHub Pages 白白重新构建。
   → 指纹比对，一样的直接跳过。

2. **内容覆盖**：已发布的页面被后来的生成结果覆盖掉，
   会让已经收录的 URL 内容突变，排名波动甚至掉权重。
   → 账本记录每个 seed 的指纹和发布时间，重跑时默认不覆盖
     （要覆盖必须显式传 --force）。

3. **中途失败**：跑到第 3 篇挂了，前两篇的成果不能丢。
   → 每篇处理完立刻落盘记账，下次运行从断点续跑。

账本用单个 JSON 文件，原子写（临时文件 + rename）。
为什么不用 SQLite：这里只有几千条记录，JSON 足够，
而且 Actions 里能直接 cat 出来看，调试方便。
"""

import io
import json
import os
import time

from .. import config
from . import quality as q_mod

LEDGER = os.path.join(config.STATE_DIR, 'ledger.json')


def _load():
    return config.load_json(LEDGER, default={'entries': {}, 'runs': []}) or \
        {'entries': {}, 'runs': []}


def _save(data):
    config.dump_json(LEDGER, data)


def load_entries():
    return _load()['entries']


def entry_for(seed_id):
    return _load()['entries'].get(seed_id)


def should_process(seed_id, force=False):
    """判断这条是否需要处理。返回 (bool, 原因)。"""
    if force:
        return True, '强制重跑'
    e = entry_for(seed_id)
    if not e:
        return True, '首次生成'
    if e.get('status') == 'failed':
        return True, '上次失败，重试'
    if e.get('status') == 'skipped':
        return True, '上次被质量闸拦下，重试'
    return False, '已生成过，跳过'


def record(seed_id, content, status='ok'):
    """把一条结果记进账本。"""
    data = _load()
    data['entries'][seed_id] = {
        'slug': content.get('slug'),
        'url': content.get('url'),
        'fingerprint': content.get('fingerprint'),
            'status': status,
            'score': (content.get('quality') or {}).get('score'),
            'by_ai': content.get('by_ai'),
            'zh_len': (content.get('quality') or {}).get('zh_len'),
            # 存标题和正文指纹：下一轮跑质量检测时要做重复判定，
            # 不存的话去重逻辑形同虚设（只靠 fingerprint 算 SimHash
            # 拿不到真正的正文指纹，相似度会失真）
            'meta_title': content.get('meta_title'),
            'simhash': (content.get('quality') or {}).get('simhash'),
            'published_at': content.get('published'),
            'updated_at': int(time.time() * 1000),
    }
    _save(data)


def record_failure(seed_id, reason):
    data = _load()
    prev = data['entries'].get(seed_id) or {}
    prev.update({'status': 'failed', 'reason': reason,
                 'updated_at': int(time.time() * 1000)})
    data['entries'][seed_id] = prev
    _save(data)


def done_slugs():
    """已成功发布过的 slug集合。

    渲染前用来判断：这个页面是不是已经存在。
    已存在且未被强制的，绝不覆盖 —— 这是"防内容覆盖"的关键。
    """
    return set(v['slug'] for v in _load()['entries'].values()
               if v.get('status') == 'ok' and v.get('slug'))


def seen_hashes():
    """已发布正文的 SimHash 集合，供去重用。

    指纹是入库时算好的（存 quality.simhash），
    直接读账本，不再重新算 —— 算一次几千条要好几秒。
    """
    out = {}
    for seed_id, e in _load()['entries'].items():
        if e.get('status') != 'ok':
            continue
        sh = e.get('simhash')
        if not sh:
            continue
        try:
            out[int(str(sh), 16)] = e.get('slug') or seed_id
        except ValueError:
            continue
    return out


def seen_titles():
    """已发布的 meta_title 列表。"""
    return [e['meta_title'] for e in _load()['entries'].values()
            if e.get('status') == 'ok' and e.get('meta_title')]


# ============================================================
# 运行日志
# ============================================================

def log_run(stats):
    """把本次运行摘要写进账本 + 落一个 JSON 日志文件。

    日志保留最近 30 次，超过的删掉 —— 账本文件会无限增长，
    几百KB 的 JSON 每次 Actions 都要 checkout 解析，得不偿失。
    """
    data = _load()
    data['runs'].append(stats)
    if len(data['runs']) > 30:
        data['runs'] = data['runs'][-30:]
    _save(data)

    name = time.strftime('%Y%m%d-%H%M%S')
    path = os.path.join(config.LOG_DIR, 'run-%s.json' % name)
    with io.open(path, 'w', encoding='utf-8') as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    return path


def prune_logs(keep=30):
    """清理旧日志文件。"""
    if not os.path.isdir(config.LOG_DIR):
        return 0
    files = sorted(f for f in os.listdir(config.LOG_DIR)
                   if f.startswith('run-') and f.endswith('.json'))
    n = 0
    for f in files[:-keep] if len(files) > keep else []:
        try:
            os.remove(os.path.join(config.LOG_DIR, f))
            n += 1
        except OSError:
            pass
    return n
