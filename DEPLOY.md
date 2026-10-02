# 部署到 GitHub Pages

页面已改造为**纯静态可部署**形态：不发起任何跨域请求，因此 GitHub Pages、jsDelivr、任何静态托管都能直接跑。

## 原理

改造前用 `fetch()` 读 `posts2/*.json`，静态托管下浏览器从 `https://xxx.github.io` 发起的请求属于跨域，会被 CORS 拦截，页面只会显示"无法读取 index.json"。

改造后数据打包进 `posts-data.js`，用 `<script src>` 加载 —— **script 标签不受同源策略限制**，这是纯静态部署唯一可靠的方式。

## 文件构成

| 文件 | 作用 | 是否需要提交 |
|---|---|---|
| `ui-v2.html` | 页面本体 | ✅ |
| `posts-data.js` | 2340 篇帖子数据（1.42 MB） | ✅ |
| `build_data.py` | 生成上面这个文件 | ✅ |
| `posts-data.js` 的生成物 | 改数据后才需重跑 | — |

## 开启 Pages

1. 仓库 **Settings → Pages**
2. Source 选 **Deploy from a branch**
3. Branch 选 **main**，目录选 **/ (root)**
4. 保存，等 1–2 分钟

访问地址：`https://banznx.github.io/foot-job/ui-v2.html`

> Pages 只能服务 `/docs` 或根目录。根目录已被占用，所以页面文件名必须是 `index.html` 或者放在子目录。若要 `https://banznx.github.io/foot-job/` 直接打开，把 `ui-v2.html` 复制一份为 `index.html` 即可（注意会与现有 `index.html` 冲突，建议改名为 `app/index.html` 放在子目录）。

## ⚠️ 图片需要单独配置（必读）

**数据已经能加载，但图片 1.2GB 存在 GitHub 仓库里，Pages 不托管仓库文件，图片会 404。**

仓库体积 1.04 GiB，已超过 GitHub 推荐的 1GB 上限，jsDelivr 等 CDN 对超大仓库可能限流或直接拒绝服务。

打开 `ui-v2.html`，找到文件顶部的配置：

```js
const IMAGE_BASE = '';
const IMAGE_FALLBACK_BASE = '';
```

填入 CDN 前缀即可，**记得末尾保留斜杠**：

```js
// 方案 A：jsDelivr（推荐先试）
const IMAGE_BASE = 'https://cdn.jsdelivr.net/gh/banznx/foot-job@main/images/downloaded_posts_images/';
const IMAGE_FALLBACK_BASE = 'https://raw.githubusercontent.com/banznx/foot-job/main/images/downloaded_posts_images/';

// 方案 B：raw 直连
const IMAGE_BASE = 'https://raw.githubusercontent.com/banznx/foot-job/main/images/downloaded_posts_images/';
const IMAGE_FALLBACK_BASE = '';
```

配置后主源失败会自动切到备用源。

### 如果 CDN 都不行

1.2GB 图片塞在 Git 仓库里本身就是问题。可选：

- **迁到图床**（又拍云、七牛、Cloudflare R2 等），把 `IMAGE_BASE` 指向图床前缀
- **只保留热门帖子的图片**，减少仓库体积
- **用 Git LFS** 存图（Pages 同样不托管 LFS 文件，需配 CDN）

## 改动数据后重新生成

```bash
python build_data.py
```

会重新扫描 `posts2/*.json`，输出 `posts-data.js`。字段做了精简：只保留界面用到的 8 个帖子字段 + 6 个用户字段，体积从 3.7MB 降到 1.42MB。

## 改造带来的额外收益

数据全量进内存后，**排序不再需要采样**：

- 改造前：并发拉 400 篇元数据后排序（首屏可接受性考虑）
- 改造后：直接对全部 2340 篇真实排序，无网络请求

实测热度排序：`4.3w → 2.2w → 1.4w → 1.2w` 真实递减。「热门精选」视图也从"随机取 60 篇"升级为"按真实热度取前 200"。

## 本地预览

数据已内联，`file://` 直接双击也能打开（不再有 CORS 问题）。但图片仍需同源相对路径，所以看图建议起服务：

```bash
python -m http.server 8801
# http://127.0.0.1:8801/ui-v2.html
```
