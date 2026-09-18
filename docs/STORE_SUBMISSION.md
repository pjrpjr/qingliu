# Chrome Web Store 上架手册

首次上架与后续发版的操作手册。材料全部本地生成，门禁全在本地（不使用 CI）。

## 1. 材料清单

| 材料                    | 路径                                                                | 状态                         |
| ----------------------- | ------------------------------------------------------------------- | ---------------------------- |
| 商店 ZIP                | `apps/extension/.output/qingliu-<版本>-chrome.zip`               | `scripts/pack-store.sh` 产出 |
| ZIP checksum            | 同目录 `.sha256`                                                    | 脚本产出                     |
| 商店图标 128×128        | `apps/extension/public/icon-128.png`                                | 已就绪                       |
| 截图 1280×800 ×2~3      | `assets/store/screenshot-*.png`                                     | 真机拍摄                     |
| 宣传图 440×280          | `assets/store/promo-440x280.png`                                    | 已就绪                       |
| 跑马灯 1400×560（可选） | `assets/store/marquee-1400x560.png`                                 | 已就绪                       |
| 隐私政策 URL            | `https://github.com/pjrpjr/qingliu/blob/main/PRIVACY.md` | 已就绪                       |
| 支持链接                | `https://github.com/pjrpjr/qingliu/issues`               | 已就绪                       |
| 主页                    | `https://github.com/pjrpjr/qingliu`                      | —                            |

打包命令（自动跑 verify + 构建 + manifest/ZIP 审计 + checksum）：

```bash
bash scripts/pack-store.sh
```

## 2. 开发者账号（一次性）

1. 登录 Google 账号，先开启两步验证（发布/更新的前提）。
2. 打开 [Developer Dashboard](https://chrome.google.com/webstore/devconsole)，注册开发者账号。
3. 支付一次性注册费（注册页显示的金额为准）。
4. 账号页验证联系邮箱；填写发布商名称（如 `FeedSieve`）。
5. 开发者邮箱一经设置不可更改，建议用专用邮箱并定期查看。

## 3. 商店信息（Listing）

- **名称**：`FeedSieve 福滤娃`
- **简短描述**（≤132 字符）：

  ```text
  X 赛博清洁工：黄框标注垃圾账号，一键批量真拉黑。标注永不隐藏内容。
  ```

- **详细描述**（纯文本，直接粘贴）：

  ```text
  FeedSieve（福滤娃）是 X（Twitter）时间线的赛博清洁工。

  高置信才标注，绝不隐藏内容：
  • 高置信垃圾账号在时间线上被黄框标出，徽章使用“3 人标记为诈骗”等普通理由
  • 你依然能看到每一条推文，判断权在你

  拉黑永远由你按下按钮：
  • 插件漏识别时，在推文旁或面板中“标记垃圾并拉黑”
  • 点单个黄框拉黑一个账号
  • 或打开扩展面板，一键拉黑当前页面全部黄框账号
  • 社区清理只处理至少 3 人确认且无人抢救的账号，并自动排除关注、白名单和已拉黑账号
  • 拉黑全部可撤销（「已拉黑」列表 → 撤销）

  关注保护：
  • 可将自己的完整关注列表同步为本地保护名单
  • 关注列表不上传社区

  社区名单（可选，默认开启，可关闭）：
  • 内置社区维护的垃圾账号名单，自动标注
  • 你维护的黑名单匿名上传为正样本：账号名、分类、话术指纹哈希与外链域名
  • 你维护的白名单匿名上传为负样本：账号名与当时的检测规则，帮助纠正误标

  隐私（一行版）：凭证、推文原文和关注列表不出设备，只同步你明确维护的黑白名单；可在设置中关闭。
  完整政策：https://github.com/pjrpjr/qingliu/blob/main/PRIVACY.md

  适用范围：x.com。标注永不隐藏 · 误伤可撤销。
  ```

- **类别**：工具（Tools）· **语言**：中文（简体），可后补英文 locale
- **图标/截图/宣传图**：按第 1 节路径上传

## 4. 隐私标签（Privacy）

- **单一用途声明**（本次上架口径，务必与之一致）：
  X 时间线的垃圾账号识别与清理。识别结果只用于在页面上加黄框提示，拉黑动作全部由用户点击触发。

  ```text
  在 X 时间线上识别并标注垃圾账号，并在用户明确点击时通过 X 原生接口执行拉黑/撤销。
  ```

- **权限用途说明**：

  | 权限                                               | 用途                                                                 |
  | -------------------------------------------------- | -------------------------------------------------------------------- |
  | `storage`                                          | 缓存社区名单快照、用户设置、本地统计、已拉黑记录                     |
  | 权限 `storage`                        | 本机保存设置、白名单、拉黑队列与统计；AI key 也只存本机 |
  | 主机权限 `https://x.com/*`             | 内容脚本在时间线识别账号并标注；用户点击时经 X 自身会话执行拉黑/撤销 |
  | 主机权限 `https://api.typesafe.ai/*`   | **仅在用户显式开启「AI 判定」并填入自己的 key 后**，用于把账号资料发去换取垃圾号概率。默认关闭时零请求 |

- **AI 判定层的数据披露（新增，必须如实勾选）**：
  用户**显式开启**「AI 判定（Jev）」并填入自己的 API key 后，扩展会把该账号的
  handle / 昵称 / 简介 / 粉丝关注推文数 / 注册时间 / 是否默认头像 / 蓝标 /
  **当前时间线可见的推文正文** / 外链域名 发送至 `api.typesafe.ai`（TypeSafe AI），
  用于返回 0–1 的垃圾号概率。**不发送**：X 登录凭证、安装 ID、关注保护名单、
  浏览历史、私信、与判定无关的页面内容。请求由扩展背景页直连 TypeSafe，
  不经过任何自建服务器；结果本机缓存 7 天。**默认关闭**，关闭时内容不出设备。

- **数据使用勾选**（收集 = 离开设备的数据）：
  - ✅ 网站内容（Website content）——拉黑对象的话术指纹（单向哈希）与外链域名
  - ✅ 用户活动（User activity）——用户明确加入黑名单或白名单的账号与分类/误标规则
  - ✅ 唯一标识符（Unique identifiers）——本机随机安装 ID，服务端仅存加盐哈希
  - ❌ 其余全部不收集（PII、认证信息、通信、位置、浏览历史等）
- **合规声明**：按表单逐条勾选（不出售数据、仅按披露用途使用、不用于与单一用途无关的目的等），均与实现一致。
- **隐私政策 URL**：`https://github.com/pjrpjr/qingliu/blob/main/PRIVACY.md`

## 5. 审核员说明（Notes for reviewers，直接粘贴）

```text
What FeedSieve does
- Marks spam accounts on x.com with a yellow frame (a visual border only) plus a
  badge explaining why. It never hides, collapses, or removes content.
- Blocking happens ONLY on explicit user clicks: single block on a marked tweet,
  manual “Mark spam & block”, or batch block via the popup. Every block can be
  undone in the popup.
- The user's following list can be synced as a local-only protection list. It is
  excluded from batch actions and is never uploaded as a community vote.

How to test
1. Open https://x.com (e.g. https://x.com/search?q=spam&f=live). Accounts in the
   community spam list get a yellow frame and a reason badge.
2. Open the popup: it lists the accounts currently marked on the page. Click
   "一键拉黑" to block them via the logged-in user's own X session; the popup
   shows per-account results and an unblock list.
3. Paste an X handle or profile URL into "漏网账号" to test the manual path.
4. Popup → Settings: "List uploads / 名单上传" (on by default) controls both
   blocklist and allowlist uploads; turning it off stops them. The ⟳ button
   syncs the community snapshot.

Permissions rationale
- "storage": caches the community snapshot, settings, local stats, and
  blocked/unblock records.
- Host "https://x.com/*": content scripts read the timeline DOM to identify
  accounts and execute the user-triggered block/unblock against X's own
  endpoints with the user's existing session (no cookies permission; the
  session token is read from the page context and sent only to x.com itself).
- Host "https://feedsieve-api.chendahuang.com/*" (our own API, shipped in this
  repo): downloads the community snapshot (JSON validated by schema + SHA-256)
  and, when List uploads is enabled, syncs only entries the user explicitly
  maintains in the local blocklist or allowlist. Block entries include handle,
  category, one-way content-fingerprint hash, and external link hostnames;
  allow entries include handle and available false-positive rule evidence.
  The local following-protection list and blocks copied from Community Clean are
  explicitly excluded from uploads.
  Both use a random installation ID that is stored server-side only as a salted hash.

  Keyword-rule packs are public data only: the extension downloads a version manifest and
  JSON pack from this same API, verifies the SHA-256 checksum and schema, and caches the
  last known-good copy. Users explicitly subscribe to industry packs; a match only shows a
  review highlight and never auto-blocks, bulk-blocks, or uploads a report.

Why a MAIN-world content script
- x.com renders account data through its own GraphQL responses. A page-context
  script observes window.fetch/XMLHttpRequest responses to read the same public
  fields the page already displays (handle, user id). It does not read
  credentials or cookies, does not modify or block any request, and forwards
  only parsed fields to this extension's own isolated content script via
  CustomEvent. Raw responses are never stored or transmitted.

No remote code
- All JavaScript is bundled locally in the package. Remote content is data-only
  (JSON snapshots), schema- and checksum-validated before use.

Data handling
- Browsing history, DMs, passwords, and cookies are never collected. Original
  tweet text never leaves the device (only one-way hashes). Privacy policy:
  https://github.com/pjrpjr/qingliu/blob/main/PRIVACY.md
```

## 6. 分发与提交

1. 上传 ZIP → 检查「软件包」页无警告。
2. 填完 商店信息 / 隐私 / 分发 三个标签。
3. 分发：公开（Public），所有国家/地区，免费。
4. 审核员说明粘贴到提交框。
5. 提交审核。默认「审核通过后自动发布」；想人工放行就取消自动发布（通过后 30 天内手动发布，过期退回草稿）。

### 提交前 checklist

- [ ] `pnpm verify` 全绿
- [ ] `bash scripts/pack-store.sh` 通过，ZIP + checksum 产出
- [ ] checksum 已记入 `docs/RELEASES.md`
- [ ] git tag（如 `v0.7.0`）与本次构建一致
- [ ] 上传 ZIP 后版本号、权限与第 4 节描述一致
- [ ] 隐私政策 URL、支持链接可公开访问

## 7. 后续发版

1. 改代码 → `apps/extension/package.json` 与 `apps/community-api/package.json` 同步升版（保持一致）。
2. 更新 `docs/RELEASES.md`（只写事实，不写形容词）。
3. `bash scripts/pack-store.sh` → commit → tag → 上传新 ZIP → 提交审核。
4. 商店审核通过即覆盖旧版本；如需回滚，在 Dashboard 重新上传上一个 tag 构建的 ZIP。

---

## 9. 上架文案（清流口径，可直接复制粘贴）

> 全部材料已就绪：截图 `assets/store/screenshot-{1,2,3,4}.png`（1280×800，真实截图，
> 第三方内容与评测者 handle 已模糊处理）、小宣传图 `assets/store/promo-440x280.png`、
> 跑马灯 `assets/store/marquee-1400x560.png`、ZIP 见 Release。

| 字段 | 内容 | 限制 |
|---|---|---|
| **名称** | `清流 Qingliu` | ≤45 字符 |
| **简短说明** | `黄框标出 X 上的垃圾账号，一键原生拉黑、全端同步消失。默认不联网，AI 判定层可选开启，永不自动拉黑。` | ≤132 字符 |
| **类别** | 社交网络（Social Networking） | — |
| **语言** | 中文（简体）为主，English 为次 | — |
| **主页** | `https://github.com/pjrpjr/qingliu` | — |
| **支持** | `https://github.com/pjrpjr/qingliu/issues` | — |
| **隐私政策** | `https://github.com/pjrpjr/qingliu/blob/main/PRIVACY.md` | 必填 |

**详细说明（中文，可直接粘贴）**：

```
清流是 X（Twitter）时间线的垃圾账号清理工具。它把识别结果做成页面上的黄框提示，
拉黑动作全部由你点击触发，走你已登录页面的原生菜单，服务端生效、手机端同步消失。

【三层识别，AI 只做最后一层】
1. 社区/内置名单命中 —— 直接黄框
2. 话术指纹（SimHash）—— 换号但复用同一套话术也认得出来
3. 关键词库（778 条公开规则）—— 命中后给人工确认黄框
4. AI 判定（Jev，默认关闭）—— 前三层全没认出时才问一次

AI 层排在最后，所以它永远不会覆盖名单、也不会覆盖你自己写的关键词。

【实测数字（判据在测量前已冻结，方法完全公开）】
在同一批 37 个确认垃圾号 / 141 个干净账号上：
· 误杀正常人 0.7%（778 条关键词方案在同批数据上是 7.8%）
· 抓到垃圾号 56.8%（关键词方案 54.1%）
· 词库完全认不出的垃圾号，AI 层另外抓到 47%
· 单账号判定成本约 $0.000032，10 个账号合并为一次调用

【产品红线】
· 标注永不隐藏内容 —— 只加黄框，不改页面可见性
· 所有拉黑由你显式触发 —— 没有"全自动清理"，AI 判定甚至不进批量候选
· 误标一键放回，你的「误标？」会作为纠错证据帮我们调阈值

【隐私】
· 名单 / 指纹 / 词库匹配全部在本机完成，零网络请求
· 你的关注列表只存本机，永不上传
· AI 判定层默认关闭。开启后才会把账号资料（handle、昵称、简介、粉丝关注数、
  注册时间、是否默认头像、蓝标、当前可见的推文正文、外链域名）发送给
  api.typesafe.ai 换取 0-1 的垃圾号概率；不发送登录凭证、安装 ID、关注名单、
  浏览历史或私信。结果本机缓存 7 天，同一账号不重复发送
· 完整中英文政策见仓库 PRIVACY.md

【开源】
基于 FeedSieve（MIT，原作者陈大黄）的衍生作品，原始版权声明完整保留。
本项目同样以 MIT 开源，欢迎审计与自部署。
```

**详细说明（English，第二语言可选）**：

```
Qingliu cleans up spam accounts on your X (Twitter) timeline. Detections appear as a
yellow review frame — nothing is ever hidden — and every block is triggered by your own
click through X's native menu, so it takes effect server-side and syncs to your phone.

Four detection layers, with AI last: community/built-in lists, content fingerprints
(SimHash), 778 public keyword rules, and an optional AI verdict layer (Jev) that only
runs when the first three miss — so it can never override your lists or your own keywords.

Measured on 37 confirmed spam accounts and 141 clean ones, with criteria frozen before
measurement: 0.7% false positives (a 778-rule keyword layer gets 7.8% on the same data),
56.8% recall, and 47% of the spam the keyword layer never matches. About $0.000032 per
account, ten accounts batched per call.

Red lines: marks never hide content; every block is user-triggered; the AI layer never
auto-blocks. Privacy: list/fingerprint/keyword matching happens entirely on-device with
zero network requests, and the AI layer is off by default — enabling it sends account
profile text to api.typesafe.ai, never your credentials, install ID, following list or DMs.

MIT, forked from FeedSieve with attribution.
```

---

## 10. 提交点击路径（照着点即可）

> 前置：一个 Google 账号 + 一次性 **$5** 开发者注册费（Chrome Web Store 收，不是我们收）。

1. 打开 <https://chrome.google.com/webstore/devconsole>，用你的 Google 账号登录
2. 若从未注册：点 **Become a developer** → 同意条款 → 付 $5 → 填公开的开发者名称与邮箱
   （公开邮箱会显示在商店页，介意的话用一个专用邮箱）
3. 点 **New item** → 上传 `qingliu-0.7.5-chrome.zip`
   （就是 GitHub Release 里那个；**上传成功即代表包结构被 Google 接受**）
4. **Store listing** 标签：按第 9 节粘贴名称 / 简短说明 / 详细说明，
   上传 `assets/store/screenshot-{1,2,3,4}.png`（顺序建议：2 → 3 → 4 → 1）、
   `promo-440x280.png`；类别选「社交网络」
5. **Privacy** 标签：按第 4 节逐条勾选。重点两条——
   - 用途：**Functionality**（不是广告、不是分析）
   - 数据：勾选「Personal communications」类的**文本**（因为 AI 层会发推文正文），
     并在说明里写明"仅在用户显式开启 AI 判定后、发往 api.typesafe.ai、可一键关闭"
6. **Distribution** 标签：可见性选 Public，地区全选（或先选几个）
7. 提交审核 → 通常 1–3 个工作日。被问任何问题，把第 4 节与 `PRIVACY.md` 的对应段落贴回去

**提交前自检清单**：

- [ ] ZIP 能在 `chrome://extensions` 加载并正常标注（本地已实测通过）
- [ ] manifest 权限只有 `storage` + `x.com` + `api.typesafe.ai` 三项
- [ ] 隐私政策 URL 可公开访问（`PRIVACY.md` 已在仓库根目录）
- [ ] 截图 1280×800、无 cookie 横幅、无第三方隐私信息（已按要求模糊处理）
- [ ] 商店名称与 manifest 里的 `name` 一致（都是「清流 Qingliu」）
