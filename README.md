# 玉卒

一个图片社区的展示站。首页是单页App，博客区是由 AI 自动产出的内容页，
用于让搜索引擎能抓到单篇内容（App 里的帖子详情是浮层，爬虫抓不到）。

在线地址：<https://banznx.github.io/foot-job/>

## 站点结构

```
/                      单页 App（三个底部 Tab）
/blog/                 博客列表页，第 1 页
/blog/page/2.html      博客列表页，第 2 页
/blog/posts/p-<id>.html单篇文章
```

`blog/` 目录名**全小写**，GitHub Pages 区分大小写，`/BLOG` 会 404。

## App 部分

底部三个 Tab：

- **首页** — 信息流（推荐 / 最新 / 热门），懒加载 + 无限滚动
- **发现** — 一次只展示一篇随机帖子，「换一篇」重抽
- **我的** — 收藏、历史、夜间模式、清除记录

帖子详情是全屏浮层，图片用 `scroll-snap` 横滑。

## 博客区的产出方式

博客内容不是手写的，是一条自动化流水线，每半小时产出一篇。

### 流程

1. **随机抽图** — 从 `images/downloaded_posts_images/` 按帖子 ID 分组抽 3 张。
   分组是为了让一篇文章的几张图来自同一个帖子，风格统一不显得拼凑。
2. **看图** — glm-4v-flash 视觉模型真看这几张图，输出中性的画面描述、
   氛围、主题、关键词。
3. **写文** — glm-4.7-flash 拿上一步的描述当素材，写 1200–2200 字长文。
4. **插图与建页** — `<img>` 标签由代码按段落位置插入，slug 由代码生成。
   这两件事刻意不交给模型：模型会编造图片地址，slug 有四分之一几率是废的。
5. **推送与提交** — IndexNow 推给搜索引擎，然后 Actions 提交产物。

两个模型都免费、都只支持 1 并发，所以每次调用之间有节流。

### 降级保护

接口 429限流或解析失败时，脚本会走模板兜底，产出「分享 分享 分享」
这种 6 个字的占位内容。**这类内容一律不落盘、不入账本**，
图退回候选池留给下一轮。

早先的版本只在「全部降级」时中断任务，部分降级完全放行，
一次接口抽风就往站点里灌了几十篇模板页，还被 IndexNow 推给了百度。
现在降级文章在 `seo/run.py` 里直接 `continue` 掉。

### 素材耗尽之后

素材用完不会停工。`pick_group()` 的 `allow_reuse` 会让用过的组重新进入候选，
同一组图反复看，模型每次会写出不同角度的文章。日志里会打印「转入复用模式」。

## 目录结构

```
.
├── index.html              App 主页面
├── posts-data.js           帖子数据（由 build_data.py 生成，约 1.4MB）
├── build_data.py           数据构建脚本
├── blog/                   博客产物（由 Actions 自动生成，请勿手改）
│   ├── index.html
│   ├── page/N.html
│   └── posts/p-<id>.html
├── seo/                    内容生成系统
│   ├── run.py              主流程：抽图 → 看图 → 写文 → 建页
│   ├── images.py           图片抽样（零依赖，只读文件头拿宽高）
│   ├── glm.py              智谱接口封装，模型降级链
│   ├── render.py           页面渲染，复用 App 的设计令牌
│   ├── push.py             推送给搜索引擎
│   ├── ledger.json         账本：已产出文章 + 已用素材（幂等依据）
│   └── api-log.json        接口失败诊断（无条件提交）
├── images/
│   └── downloaded_posts_images/    社区图片
├── posts2/                 原始帖子数据（2341 个 json）
├── sitemap.xml             站点地图
├── robots.txt
└── .github/workflows/
    └── seo-blog.yml        定时任务：每半小时一次
```

## SEO 相关

- **sitemap** — 主站 + 博客列表页 + 分页页 + 每篇文章
- **robots** — 文章页允许索引；**不用 `noimageindex`**，
  图片站的流量大头就是图片搜索，加了等于自废入口
- **文章页** — 有 canonical、og:image、twitter:image、JSON-LD（Article）
- **分页页** — 各自 self-canonical，可索引，权重 0.6
- **推送** — IndexNow 无需 key。Bing / 百度需要配
  `BING_API_KEY` / `BAIDU_TOKEN`，未配置时 `seo/push-log.json`
  里显示 skipped

## 本地开发

### 更新 App 数据

改了 `posts2/` 里的原始数据后：

```bash
python build_data.py
```

脚本会重新生成 `posts-data.js`，并把内容哈希作为版本号写回
`index.html` 的 `<script src="posts-data.js?v=xxx">`。
**不这么做浏览器会缓存旧的posts-data.js，改了数据页面也不变。**

### 手动跑一次内容生成

```bash
python seo/run.py --batch 1          # 生成 1 篇
python seo/run.py --batch 5 --dry-run # 只看会抽到哪些图，不写文件
python seo/run.py --seed 42          # 固定随机种子，便于复现
```

需要一个环境变量：

```
BIGMODEL_API_KEY    智谱开放平台的key
```

没有它也能跑，但全部走模板降级，会被降级保护拦下不提交。

## 数据来源与声明

⚠️ 本项目中的帖子数据、图片均来自第三方社区的公开抓取，
博客区的文字内容由 AI 根据图片自动生成，仅用于技术演示。

原站对违规图片会用同一张提示图替换（实测 171 张文件逐字节相同）。
`build_data.py` 按内容哈希的重复次数识别并剔除，否则界面上会直接
显示「图片涉嫌违规 已禁止访问」占位块。

博客正文由模型生成，模型不看图时会产生模板化的空话——
所以看图那一步不可省，且失败时不落盘。