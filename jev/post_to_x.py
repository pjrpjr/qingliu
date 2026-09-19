#!/usr/bin/env python3
"""把发布文案自动发到 X（用你自己已登录的会话，走网页版发帖框）。

为什么不走 MultiPost：它的平台表里没有 X（只有抖音/小红书/B站/YouTube/微博/知乎等）。
为什么不走 X API：`reslib:api-x-developer` 额度已耗尽（402），且写操作要另外计费。

安全设计（默认保守，别改成激进）：
  · **默认只填充不提交** —— 看完再决定发不发；加 --submit 才真发
  · 逐字输入（带 delay），不用 JS 直接改 DOM —— 更像人在打字
  · 每两条之间等 40–90 秒随机 —— 真人发串就是这个节奏，别一秒一条
  · 任何一步失败立即停（宁可只发前半串，也不发乱）
  · 每条发完都去主页验证真的发出去了（X 偶尔会静默失败）

用法:
    python3 jev/post_to_x.py                 # 只填充第一条，不提交（先看效果）
    python3 jev/post_to_x.py --submit --only-main
    python3 jev/post_to_x.py --submit        # 发主推 + 串（约 4–6 分钟）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SHOTS = os.path.join(ROOT, ".private", "shots")
COOKIE_EXTRACTOR = os.path.expanduser("~/naslib/tools/dydiffusion/extract_chrome_cookies.py")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36")
REPO = "https://github.com/pjrpjr/qingliu"

def weighted_len(text: str) -> int:
    """X 的字数口径：CJK 算 2，URL 固定算 23，其余算 1。上限 280（非会员）。

    踩过的坑：按「多少字」写文案一定超 —— 中文一条实际只能装约 128 个字。
    第一次跑 dry-run 时发帖按钮是灰的、右侧显示 -47，就是没算这个。
    """
    import re
    value = 0
    for token in re.split(r"(https?://\S+)", text):
        if re.match(r"https?://", token):
            value += 23
            continue
        for ch in token:
            value += 2 if ("\u4e00" <= ch <= "\u9fff" or "\u3000" <= ch <= "\u303f"
                           or "\uff00" <= ch <= "\uffef") else 1
    return value


LIMIT = 280

MAIN = f"""X 的黄推我忍不了了，于是把停运的福滤娃修好，还给它装了个脑子。

清流：黄框标出垃圾号 → 一键原生拉黑 → 手机端消失。

阈值这次量出来了：
· 误杀正常人 0.7%（原版词库 7.8%）
· 召回还略高
· 词库认不出的，它另抓 47%

开源 MIT、默认不联网 👇
{REPO}"""

THREAD = [
    """跟原版的关系说清楚：

上游福滤娃九月停运了（仓库转私、官网关闭、社区名单服务器连不上，我实测过）。我拿它 MIT 源码接着做，没抢名字。

它 roadmap 从 v0.5 挂到收摊，一直有一行没做：「AI 识别」。代码里类型定义都留好了 ai 这个来源，却从没产出过判定。我补的就是这层。""",

    """为什么以前做不了、现在能做了？经济学变了。

按大模型的价格，给时间线每个账号判一次不可能。而 Jev 是结构化决策模型：不生成文本只回概率，单账号 $0.000032，10 个账号合并成一次调用（一致率 96.2%）。

成本降下来，产品才成立。""",

    """判据是跑之前就冻结的，数据集 37 个真垃圾号 vs 141 个干净号，两侧标签都做了审计 —— 审计结果比结论更有意思：

· 881 条公开黄推名单，84% 的号已经死了
· 我从回复区抓的 78 个「垃圾号」，67 个只是普通用户在回帖（模型判对了，是我标签错了）""",

    """三条红线一条没动：

· 标注永不隐藏内容
· 所有拉黑由你点击触发（AI 判定连批量候选都进不去）
· 误标一键放回

AI 层默认关闭 —— 开了才会把账号资料发给第三方，这代价得你同意。

最想要的反馈：它判错了哪些。""",
]


def x_cookies() -> list[dict]:
    proc = subprocess.run([sys.executable, COOKIE_EXTRACTOR, "--host", "x.com", "--json"],
                          capture_output=True, text=True, check=True)
    return [{"name": k, "value": v, "domain": ".x.com", "path": "/",
             "secure": True, "httpOnly": False, "sameSite": "Lax"}
            for k, v in json.loads(proc.stdout).items()]


def type_into(page, selector: str, text: str) -> bool:
    """逐字输入（像人打字）。X 的编辑框是 contenteditable，必须走键盘事件。

    坑：直接 click() 会因为浮层遮挡/持续动画而超时（元素在，但 Playwright 认为不可交互）。
    所以先用 JS 聚焦并滚到视野内，再让键盘事件进去 —— 仍然是真实键盘事件，不是改 DOM。
    """
    page.evaluate("""(sel) => {
        const el = document.querySelector(sel);
        if (!el) return;
        const r = el.getBoundingClientRect();
        window.scrollTo(0, window.scrollY + r.top - 320);
        el.focus();
    }""", selector)
    page.wait_for_timeout(500)
    box = page.locator(selector).first
    if not page.evaluate("(sel) => document.activeElement === document.querySelector(sel)", selector):
        try:
            box.click(timeout=3000, force=True)
        except Exception:
            pass
    page.wait_for_timeout(400)
    for line in text.split("\n"):
        page.keyboard.type(line, delay=random.randint(12, 32))
        page.keyboard.press("Shift+Enter")
        page.wait_for_timeout(random.randint(80, 220))
    return True


def wait_enabled(page, selector: str, timeout_s: int = 20) -> bool:
    """等按钮真的可点。

    踩过的坑：回复弹窗里按钮会晚 1–3 秒才 enable，
    第一版直接点会「找不到可用的发帖按钮」——第 5 条就是这么丢的。
    """
    for _ in range(timeout_s * 2):
        try:
            btn = page.locator(selector).first
            if btn.count() and btn.is_enabled():
                return True
        except Exception:
            pass
        page.wait_for_timeout(500)
    return False


def click_post(page, inline: bool = False) -> bool:
    # 主页内联框的按钮是 tweetButtonInline；回复弹窗里是 tweetButton。两个都兜底。
    order = ('button[data-testid="tweetButtonInline"]',
             'button[data-testid="tweetButton"]') if inline else (
            'button[data-testid="tweetButton"]',
            'button[data-testid="tweetButtonInline"]')
    for sel in order:
        if not wait_enabled(page, sel, timeout_s=20):
            continue
        try:
            page.locator(sel).first.click(timeout=10000)
            return True
        except Exception:
            continue
    return False


def find_posted_url(page, handle: str, text: str) -> str | None:
    """按正文找刚发出去的那条。

    为什么不用「主页最新一条」：**回复不会出现在主页时间线里**，
    所以那个方法对串里的第 2 条起就永远返回主推 —— 第一版就是这么骗过我自己的。
    而且 X 是虚拟滚动，顶部的推文会被移出 DOM，必须边滚边累积。
    """
    key = text.strip().split("\n")[0][:18]
    js = """() => [...document.querySelectorAll('article')].map(a => {
        const t = a.querySelector('[data-testid="tweetText"]');
        const l = a.querySelector('a[href*="/status/"]');
        return { text: t ? (t.innerText||'') : '', url: l ? l.getAttribute('href') : null };
    })"""
    page.goto(f"https://x.com/{handle}/with_replies", wait_until="domcontentloaded",
              timeout=45000)
    page.wait_for_timeout(5000)
    seen: dict[str, str] = {}
    for _ in range(4):
        for item in page.evaluate(js):
            if item["url"]:
                seen[item["url"]] = item["text"]
        if any(key in t for t in seen.values()):
            break
        page.mouse.wheel(0, 2200)
        page.wait_for_timeout(2000)
    for url, body in seen.items():
        if key in body:
            return f"https://x.com{url}"
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--submit", action="store_true", help="真的提交（默认只填充）")
    ap.add_argument("--only-main", action="store_true", help="只发主推，不发串")
    ap.add_argument("--self", required=True, help="你自己的 handle（用于发完验证）")
    ap.add_argument("--only-index", type=int, default=0,
                    help="只发第 N 条（补发漏掉的那条时用）")
    ap.add_argument("--reply-to", default="",
                    help="把它作为对这条推文的回复发出（补发时用）")
    ap.add_argument("--headed", action="store_true", default=True)
    args = ap.parse_args()
    os.makedirs(SHOTS, exist_ok=True)
    from playwright.sync_api import sync_playwright

    results: list[dict] = []
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            os.path.join(SHOTS, ".post-profile"), headless=False,
            viewport={"width": 1280, "height": 900}, user_agent=UA, locale="zh-CN",
        )
        try:
            context.add_cookies(x_cookies())
            page = context.pages[0] if context.pages else context.new_page()

            parts = [MAIN] + ([] if args.only_main else THREAD)
            if args.only_index:
                parts = [parts[args.only_index - 1]]
            print(f"▶ 准备发 {len(parts)} 条（{'真发' if args.submit else '只填充不提交'}）")
            over = False
            for i, part in enumerate(parts, 1):
                n = weighted_len(part)
                flag = "✅" if n <= LIMIT else "❌ 超限"
                print(f"   第 {i} 条：{n}/{LIMIT} 加权字符 {flag}")
                over = over or n > LIMIT
            if over:
                sys.exit("✗ 有条目超过 X 的字数上限，先改文案（中文一个字算 2）")

            previous_url: str | None = (args.reply_to or None)
            for index, text in enumerate(parts, 1):
                if previous_url:
                    # 回复：打开原帖 → 点回复按钮 → 弹窗里写
                    page.goto(previous_url, wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_selector('[data-testid="reply"]', timeout=30000)
                    page.wait_for_timeout(2000)
                    try:
                        page.locator('[data-testid="reply"]').first.click(timeout=15000)
                    except Exception as exc:
                        print(f"  ✗ 第 {index} 条：打不开回复框 {str(exc)[:70]}")
                        break
                    page.wait_for_selector('div[data-testid="tweetTextarea_0"][role="textbox"]',
                                            timeout=30000)
                    page.wait_for_timeout(1500)
                else:
                    # 首条：用主页的内联发帖框。
                    # 注意 /compose/post 这个路由现在不渲染编辑框（实测只有 23 个 testid），
                    # 而主页的内联框是好的 —— 这是踩出来的结论。
                    page.goto("https://x.com/home", wait_until="domcontentloaded",
                              timeout=45000)
                    page.wait_for_selector('div[data-testid="tweetTextarea_0"][role="textbox"]',
                                            timeout=40000)
                    page.wait_for_timeout(2000)
                try:
                    type_into(page, 'div[data-testid="tweetTextarea_0"][role="textbox"]', text)
                except Exception as exc:
                    print(f"  ✗ 第 {index} 条：填不进去 {str(exc)[:70]}")
                    break
                page.wait_for_timeout(1200)
                head = text.split("\n")[0][:40]
                print(f"  · 第 {index} 条已填充：{head}…")

                if not args.submit:
                    # 读回输入框内容比截图可靠：X 的撰写框动画会让 playwright 截图超时
                    try:
                        typed = page.evaluate("""() => {
                            const el = document.querySelector('[data-testid="tweetTextarea_0"]');
                            return el ? (el.innerText || '').slice(0, 200) : '';
                        }""")
                        print(f"    输入框回读：{typed.split(chr(10))[0][:60]}…")
                    except Exception:
                        pass
                    try:
                        page.screenshot(path=os.path.join(SHOTS, f"compose-{index}.png"),
                                        timeout=8000, animations="disabled")
                        print(f"    （未提交；已截图 .private/shots/compose-{index}.png）")
                    except Exception as exc:
                        print(f"    （未提交；截图失败但不影响：{str(exc)[:50]}）")
                    results.append({"index": index, "submitted": False, "head": head})
                    if index == 1:
                        print("\n看到上面的内容无误后，加 --submit 真发：")
                        print(f"  python3 jev/post_to_x.py --submit --self {args.self}")
                        break
                    continue

                if not click_post(page, inline=previous_url is None):
                    print(f"  ✗ 第 {index} 条：找不到可用的发帖按钮")
                    break
                page.wait_for_timeout(6000)
                url = find_posted_url(page, args.self, text)
                ok = bool(url)
                print(f"    {'✓' if ok else '✗'} 提交后主页最新：{url}")
                results.append({"index": index, "submitted": True, "url": url, "head": head})
                if not ok:
                    print("    ⚠️ 没能确认发出，停止后续（宁可半串，也不发乱）")
                    break
                previous_url = url
                if index < len(parts):
                    wait = random.randint(40, 90)
                    print(f"    ⏳ 等 {wait}s 再发下一条（真人节奏）")
                    time.sleep(wait)

            try:
                page.screenshot(path=os.path.join(SHOTS, "posted-final.png"),
                                timeout=8000, animations="disabled")
            except Exception:
                pass
        finally:
            context.close()

    out = os.path.join(SHOTS, "post_report.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=1)
    print(f"\n✓ 报告 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
