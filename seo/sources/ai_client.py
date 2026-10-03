# -*- coding: utf-8 -*-
"""
第三方 AI API 客户端（OpenAI 兼容协议）。

只依赖标准库 urllib —— 不引requests/openai SDK，
GitHub Actions 无需 pip install，冷启动快、失败面小。

关键设计：**没有 Key 也能跑**。
未配置 API Key 时 `available` 为 False，调用方自动降级到
模板化改写（pipeline/rewrite.py 里的 TemplateRewriter），
保证任何人 fork 这个仓库后定时任务都不会红。
"""

import json
import re
import time
import urllib.error
import urllib.request

from .. import config


class AiError(Exception):
    pass


class AiClient(object):

    def __init__(self, cfg=None):
        self.cfg = cfg or config.AI
        self.stats = {'call': 0, 'fail': 0, 'retry': 0, 'rate_limited': 0,
                      'token_in': 0, 'token_out': 0}
        self._last_call = 0.0
        self._fails = []

    @property
    def available(self):
        return bool(self.cfg.get('API_KEY'))

    # ---------------------------------------------------------
    def recent_failures(self, window=300):
        """最近 window 秒内的失败次数。

        用来判断「是不是限流还没恢复」。
        连续失败说明再等也没用，不如直接走降级 ——
        与其卡在这里重试 3 次然后降级，不如立刻降级。
        """
        now = time.time()
        return len([t for t in self._fails if now - t < window])

    def _note_fail(self):
        self._fails.append(time.time())

    def _throttle(self):
        """串行节流。

        GLM-4.7-Flash 免费版只允许 1 条并发请求，
        两次调用之间必须留间隔，否则大概率吃 429。
        这里用「距上次调用至少间隔 REQUEST_INTERVAL 秒」
        的方式强制节流，比指望调用方自己 sleep 可靠。
        """
        gap = self.cfg.get('REQUEST_INTERVAL', 1.0)
        if gap <= 0:
            return
        elapsed = time.time() - self._last_call
        if self._last_call and elapsed < gap:
            time.sleep(gap - elapsed)

    # ---------------------------------------------------------
    def chat(self, messages, temperature=None, max_tokens=None,
             json_mode=False, retries=None):
        """发一次对话请求，返回文本。

        重试策略：指数退避（2s -> 4s -> 8s）。
        只对 429 / 5xx / 网络超时重试，4xx 直接失败——
        参数写错（模型名写错是最常见原因）重试一万次也没用。

        429 属于免费额度的速率限制，重试时优先听服务器的
        Retry-After，而不是盲目用本地退避值。
        """
        if not self.available:
            raise AiError('未配置 SEO_AI_API_KEY，无法调用 AI')

        retries = self.cfg['MAX_RETRY'] if retries is None else retries
        url = self.cfg['BASE_URL'].rstrip('/') + '/chat/completions'
        body = {
            'model': self.cfg['MODEL'],
            'messages': messages,
            'temperature': self.cfg['TEMPERATURE'] if temperature is None else temperature,
            'max_tokens': max_tokens or self.cfg['MAX_TOKENS'],
        }
        if json_mode:
            body['response_format'] = {'type': 'json_object'}
        # 混合思考模型必须显式指定，否则会默认开启并把 token 全耗在
        # reasoning 上，正文返回空串（实测踩过：599/600 token 进了思考）。
        thinking = self.cfg.get('THINKING')
        if thinking:
            body['thinking'] = {'type': thinking}

        payload = json.dumps(body).encode('utf-8')
        last_err = None

        for attempt in range(retries):
            self._throttle()
            try:
                req = urllib.request.Request(
                    url, data=payload, method='POST',
                    headers={
                        'Content-Type': 'application/json',
                        'Authorization': 'Bearer ' + self.cfg['API_KEY'],
                        'User-Agent': 'foot-job-seo/1.0',
                    })
                with urllib.request.urlopen(req, timeout=self.cfg['TIMEOUT']) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                self._last_call = time.time()

                choice = (data.get('choices') or [{}])[0]
                text = (choice.get('message') or {}).get('content') or ''

                # 思考模型即使配好了也可能把预算耗在 reasoning 上，
                # 结果 content 是空串。这种情况当作一次失败重试，
                # 下一轮会自动退避并有更宽裕的 token 预算。
                if not text.strip():
                    finish = choice.get('finish_reason')
                    reason = (data.get('usage') or {}).get(
                        'completion_tokens_details') or {}
                    last_err = ('模型返回空内容（finish_reason=%s，'
                                'reasoning_tokens=%s）'
                                % (finish, reason.get('reasoning_tokens')))
                    if attempt < retries - 1:
                        self.stats['retry'] += 1
                        # 空内容通常是预算被思考吃掉了，
                        # 退避时顺带把 token 上限翻倍
                        body['max_tokens'] = min(
                            int(body['max_tokens'] * 2), 8000)
                        time.sleep(self.cfg['RETRY_BASE_SLEEP'] * (2 ** attempt))
                        continue
                    self.stats['fail'] += 1
                    raise AiError(last_err)

                self.stats['call'] += 1
                usage = data.get('usage') or {}
                self.stats['token_in'] += usage.get('prompt_tokens', 0)
                self.stats['token_out'] += usage.get('completion_tokens', 0)
                return text
            except urllib.error.HTTPError as e:
                code = e.code
                last_err = 'HTTP %d %s' % (code, e.reason)
                self._note_fail()
                if code == 429:
                    self.stats['rate_limited'] += 1
                    # 免费模型 1 并发，很容易触发。退避加倍。
                    wait = _retry_after(e) or (
                        self.cfg['RETRY_BASE_SLEEP'] * (4 ** attempt))
                elif code < 500:
                    # 4xx（如模型名写错）不重试
                    raise AiError('AI 接口拒绝请求：%s' % last_err)
                else:
                    wait = self.cfg['RETRY_BASE_SLEEP'] * (2 ** attempt)
            except Exception as e:
                last_err = str(e)
                self._note_fail()
                wait = self.cfg['RETRY_BASE_SLEEP'] * (2 ** attempt)

            if attempt < retries - 1:
                self.stats['retry'] += 1
                time.sleep(wait)

        self.stats['fail'] += 1
        raise AiError('AI 请求失败（重试 %d 次）：%s' % (retries, last_err))

    def chat_json(self, messages, **kw):
        """要求返回 JSON，解析失败自动剥markdown 代码块。"""
        kw['json_mode'] = True
        txt = self.chat(messages, **kw)
        return parse_json_loose(txt)


def _retry_after(err):
    """读服务端给的 Retry-After（秒）。没有就返回 None。

    免费模型的速率限制建议听服务端的话，
    本地猜一个时间大概率还是会被拒。
    """
    try:
        v = err.headers.get('Retry-After')
        return float(v) if v else None
    except Exception:
        return None


def parse_json_loose(text):
    """模型经常把 JSON 包在 ```json 里，直接 json.loads 会炸。"""
    if not text:
        raise AiError('AI 返回空内容')
    t = text.strip()
    # 剥代码块围栏
    if t.startswith('```'):
        t = re.sub(r'^```[a-zA-Z]*\s*', '', t)
        t = re.sub(r'\s*```$', '', t)
    try:
        return json.loads(t)
    except Exception:
        pass
    # 退而求其次：抓最外层的大括号
    m = re.search(r'[\{\[]', t)
    if m:
        start = m.start()
        closer = '}' if t[start] == '{' else ']'
        end = t.rfind(closer)
        if end > start:
            try:
                return json.loads(t[start:end + 1])
            except Exception:
                pass
    raise AiError('AI 返回内容不是合法 JSON：%s' % text[:120])
