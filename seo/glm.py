"""智谱接口封装：双模型分工 + 三级降级。

分工的由来（查过参数才这么定的）：
    glm-4.6v-flash   能看图，但输出短
    glm-4.7-flash    输出上限 128K，但看不见图
所以看图归 4.6V，写长文归 4.7，两个都是免费的。

4.7 有两个必须显式设置的坑：
    thinking 默认开启，不关会又慢又吃额度
    temperature 默认 1.0（4.5 系是 0.6），写文章得压到 0.85
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

API_URL = 'https://open.bigmodel.cn/api/paas/v4/chat/completions'

# 模型顺序按实测可用性排：诊断日志里 4.6v 和 4.7 连续 429，
# 而 4v-flash 与 4.1v-thinking-flash 一次就过了。所以把稳的放前面，
# 抢限流名额，别把宝贵的重试次数浪费在刚被限流的模型上。
VISION_MODELS = ['glm-4v-flash', 'glm-4.6v-flash', 'glm-4.1v-thinking-flash']
# 写长文只有 flash 系够用，4.7 限流就退到 4.5（同样是免费的长输出模型）
TEXT_MODELS = ['glm-4.7-flash', 'glm-4.5-flash']

TIMEOUT = 120
RETRIES = 3

# 限流退避用。免费模型在高峰期会连续 429，4 秒 8 秒根本不够用，
# 第一次诊断就是死在这上面：每次 429 只隔几秒重试，全是白撞。
BACKOFF_429 = (20, 45)
BACKOFF_OTHER = (4, 8)
DIAG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'api-log.json')


def has_key():
    return bool(os.environ.get('BIGMODEL_API_KEY'))


def diag(msg):
    """把接口失败原因记进文件。

    Actions 的运行日志在网页上才看得到，写进文件才能跟着提交回仓库，
    否则一次失败只能靠猜——上一轮就是靠猜，猜了两天。
    """
    try:
        with open(DIAG, encoding='utf-8') as f:
            items = json.load(f)
    except (OSError, ValueError):
        items = []
    items.append({'t': time.strftime('%Y-%m-%d %H:%M:%S'), 'msg': str(msg)[:400]})
    try:
        with open(DIAG, 'w', encoding='utf-8') as f:
            json.dump(items[-30:], f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def _post(payload):
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        headers={
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + os.environ.get('BIGMODEL_API_KEY', ''),
        },
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode('utf-8'))


def chat(model, messages, temperature=0.85, thinking=None, retries=RETRIES):
    """通用对话。429 是免费模型的常态，退避重试而不是直接放弃。"""
    payload = {'model': model, 'messages': messages, 'temperature': temperature}
    if thinking:
        payload['thinking'] = thinking

    last = ''
    wait = BACKOFF_OTHER
    for attempt in range(1, retries + 1):
        try:
            data = _post(payload)
            content = data.get('choices', [{}])[0].get('message', {}).get('content')
            if content:
                return content.strip()
            last = '返回内容为空'
            diag('%s 返回内容为空：%s' % (model, str(data)[:200]))
        except urllib.error.HTTPError as e:
            body = ''
            try:
                body = e.read().decode('utf-8', 'ignore')[:300]
            except Exception:
                pass
            last = 'HTTP %s %s' % (e.code, body)
            diag('%s 第%d次 HTTP %s：%s' % (model, attempt, e.code, body))
            if e.code == 429:
                # 限流要等够久，等 4 秒再撞只是白撞
                wait = BACKOFF_429
            elif e.code < 500:
                break  # 鉴权、参数这类错误重试没用
        except Exception as e:
            last = str(e)
            diag('%s 第%d次 异常：%s' % (model, attempt, e))
        if attempt < retries:
            nap = wait[min(attempt - 1, len(wait) - 1)]
            print('  [glm] %s 第%d次失败，等 %d 秒再试' % (model, attempt, nap))
            time.sleep(nap)
    print('  [glm] %s 失败：%s' % (model, last))
    diag('%s 彻底失败：%s' % (model, last))
    return None


def look(image_urls):
    """让视觉模型真看图，输出中性描述 + 提炼主题。

    这是整个方案里参考项目没做到的那一步：它虽然用了视觉模型，
    却只把图片清单塞进提示词让模型挑图，从没让模型看过图。
    """
    prompt = (
        '你是图片社区的编辑。看这几张图，为它们写一段可用于文章创作的素材描述。\n'
        '要求：\n'
        '- 只描述整体氛围、场景类型、穿搭风格、构图与色调这类可用于写作的信息\n'
        '- 绝不描述任何身体细节、暴露部位或私密内容，这是硬性要求\n'
        '- 不评价、不打分、不做价值判断\n'
        '- 语言平实，像在做图片归档，不要抒情\n\n'
        '严格按以下格式输出，不要其他内容：\n'
        '[DESC]\n'
        '80-150 字的中性画面描述\n'
        '[/DESC]\n'
        '[MOOD]\n'
        '8 个字以内的氛围词，如 清爽 / 慵懒 / 复古\n'
        '[/MOOD]\n'
        '[TOPIC]\n'
        '一个适合写成分享文章的标题方向，不超过 20 字\n'
        '[/TOPIC]\n'
        '[KEYWORDS]\n'
        '3-5 个中文关键词，逗号分隔\n'
        '[/KEYWORDS]'
    )
    content = [{'type': 'text', 'text': prompt}]
    for url in image_urls:
        content.append({'type': 'image_url', 'image_url': {'url': url}})

    # 一级降级：视觉模型之间轮换。
    # 注意解析失败也要换模型：模型返回了内容但没按标记格式输出时，
    # 以前这里直接返回 None，等于一次空转就被判全盘失败。
    for model in VISION_MODELS:
        raw = chat(model, [{'role': 'user', 'content': content}], temperature=0.7)
        if not raw:
            continue
        parsed = parse_blocks(raw, '看图 %s' % model)
        if parsed.get('desc'):
            return parsed
        diag('%s 看图返回了内容但没解析出字段，换下一个模型' % model)
    return None


def write(desc, topic, keywords):
    """按看图结果写长文。4.7 一步就能写完，不用像 1000 token 的模型那样拆两步。"""
    prompt = (
        '你是一个图片社区的资深用户，在写分享帖。读者是来逛社区的人，不是来听课的。\n\n'
        '图片素材描述：%s\n'
        '主题方向：%s\n'
        '关键词：%s\n\n'
        '要求：\n'
        '- 正文纯文字不少于 1200 字，不超过 2200 字，要有实打实的内容，不靠空话凑数\n'
        '- 用 h2/h3/p/ul/ol/li/strong/blockquote 标签写，分 3 到 4 个 h2 章节\n'
        '- 标题像真人发帖，不要「全面解析」「深度解读」「一文搞懂」这类词\n'
        '- 开头直接切入，禁止「随着」「在当今」「近年来」「如今」「大家好」\n'
        '- 主体要有具体经验、做法或观察，不要泛泛而谈\n'
        '- 结尾必须有收束，给出 2 到 3 条可执行建议，绝不允许停在半句\n'
        '- 不要 emoji，不要「点赞关注转发」，正文里不要出现方括号标记\n'
        '- 内容保持中性得体，不涉及任何身体描写或私密内容\n\n'
        '严格按以下格式输出，不要其他内容：\n'
        '[TITLE]\n标题\n[/TITLE]\n'
        '[DESCRIPTION]\n120 字以内摘要\n[/DESCRIPTION]\n'
        '[KEYWORDS]\n关键词1,关键词2,关键词3\n[/KEYWORDS]\n'
        '[CONTENT]\n正文 HTML\n[/CONTENT]'
    ) % (desc, topic, keywords)

    # 4.7 限流就退到 4.5，两个都是免费的长输出模型
    for model in TEXT_MODELS:
        raw = chat(
            model,
            [{'role': 'user', 'content': prompt}],
            temperature=0.85,
            thinking={'type': 'disabled'} if model == TEXT_MODELS[0] else None,
        )
        if not raw:
            continue
        parsed = parse_blocks(raw, '写文 %s' % model)
        if parsed.get('content'):
            return raw
        diag('%s 写文返回了内容但没解析出正文，换下一个模型' % model)
    return None


def parse_blocks(raw, where=''):
    """按 [TAG]...[/TAG] 提取字段。

    模型不守格式是常态，所以这里逐级兜底：先找标准标记，再试大小写与
    空格变体，最后对 CONTENT 做宽松提取。解析不出来会记日志——
    这条静默路径曾经让两轮排查完全扑空，接口明明返回了内容，
    却因为少了 [DESC] 标记而被当成失败。
    """
    out = {}
    for tag in ('DESC', 'MOOD', 'TOPIC', 'KEYWORDS', 'TITLE', 'DESCRIPTION', 'CONTENT'):
        for pattern in ('[%s]', '[ %s ]', '[%s]'):
            start = raw.find(pattern % tag)
            if start == -1:
                continue
            for close in ('[/%s]' % tag, '[/ %s ]' % tag):
                end = raw.find(close, start)
                if end != -1 and end > start:
                    out[tag.lower()] = raw[start + len(pattern % tag):end].strip()
                    break
            if tag.lower() in out:
                break

    # 宽松提取：没有标记但明显是 HTML 正文，整段当正文用
    if 'content' not in out and re.search(r'<(h2|p|ul|ol)\b', raw, re.I):
        body = re.sub(r'\[/?[A-Z_]{2,20}\]', '', raw).strip()
        out['content'] = body
        diag('%s 没有 CONTENT 标记，按整段正文兜底' % where)

    if not out:
        diag('%s 解析不出任何字段，返回前 300 字：%s' % (where, raw[:300]))
    return out
