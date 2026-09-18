#!/usr/bin/env python3
"""真机端到端验证 + 商店截图 —— Playwright 驱动真实 Chromium 加载未打包扩展。

为什么必须做这一步：此前的验证只到「代码能编译、单测能过、Python 侧调通了 Jev」。
**没有任何一次是在真浏览器里、带着真扩展、在真 x.com 页面上跑通的。**

三个已踩过的坑（写在这里免得下次重踩）：
  1. **无头模式装不了扩展** —— headless 下内容脚本不注入，必须 headed。
  2. **MV3 的 service worker 是懒启动的** —— 没有事件它就不起来，context.service_workers
     拿不到；所以扩展 ID 改用**路径哈希推导**（未打包扩展的 ID 由绝对路径决定）。
  3. **domcontentloaded 时时间线还没渲染** —— 要等 article 真正出现。

产出：.private/shots/*.png（商店要求的 1280x800）+ report.json

用法:
    python3 jev/browser_check.py --headed --enable-jev
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import pathlib
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXT_DIR = os.path.join(ROOT, "apps", "extension", ".output", "chrome-mv3")
SHOTS = os.path.join(ROOT, ".private", "shots")
COOKIE_EXTRACTOR = os.path.expanduser("~/naslib/tools/dydiffusion/extract_chrome_cookies.py")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36")
# 黄推话术（取自仓库词库）：在搜索页造出真实垃圾号样本，
# 这样截图里的黄框是**真的判出来的**，不是摆拍。
DEMO_QUERY = "福利在主页"


def unpacked_extension_id(path: str) -> str:
    """未打包扩展的 ID = sha256(绝对路径) 前 16 字节，每个 hex 位映射到 a-p。"""
    digest = hashlib.sha256(path.encode("utf-8")).hexdigest()[:32]
    return "".join(chr(ord("a") + int(ch, 16)) for ch in digest)


def load_x_cookies() -> list[dict]:
    proc = subprocess.run(
        [sys.executable, COOKIE_EXTRACTOR, "--host", "x.com", "--json"],
        capture_output=True, text=True, check=True,
    )
    raw = json.loads(proc.stdout)
    return [{"name": k, "value": v, "domain": ".x.com", "path": "/",
             "secure": True, "httpOnly": False, "sameSite": "Lax"} for k, v in raw.items()]


def jev_key() -> str:
    proc = subprocess.run(["reslib", "get", "api-typesafe-jev", "api_key"],
                          capture_output=True, text=True)
    return proc.stdout.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--enable-jev", action="store_true")
    ap.add_argument("--wait", type=int, default=30)
    args = ap.parse_args()

    if not os.path.isdir(EXT_DIR):
        sys.exit(f"✗ 找不到构建产物 {EXT_DIR}")
    os.makedirs(SHOTS, exist_ok=True)
    from playwright.sync_api import sync_playwright

    report: dict = {"steps": [], "extension_id": unpacked_extension_id(EXT_DIR)}

    def note(step: str, **extra) -> None:
        report["steps"].append({"step": step, **extra})
        print(f"  · {step} {extra if extra else ''}")

    def shot(page, name: str) -> None:
        page.screenshot(path=os.path.join(SHOTS, f"{name}.png"))
        note(f"shot_{name}")

    def wait_articles(page, timeout_ms: int = 90000) -> int:
        try:
            page.wait_for_function(
                "() => document.querySelectorAll('article').length > 0", timeout=timeout_ms)
        except Exception:
            pass
        return page.evaluate("() => document.querySelectorAll('article').length")

    def dismiss_banner(page) -> None:
        """关掉 cookie 横幅（商店截图不能带它）。多套选择器兜底。"""
        selectors = [
            'button:has-text("拒绝非必要的 Cookie")',
            'button:has-text("接受所有 Cookie")',
            'div[role="button"]:has-text("拒绝非必要的 Cookie")',
            'button:has-text("Accept all cookies")',
            'button:has-text("Refuse non-essential cookies")',
        ]
        for _ in range(3):  # 横幅可能异步出现，重试几轮
            for sel in selectors:
                try:
                    page.locator(sel).first.click(timeout=2500)
                    note("cookie_banner_dismissed", selector=sel)
                    page.wait_for_timeout(800)
                    return
                except Exception:
                    continue
            page.wait_for_timeout(1500)
        note("cookie_banner_not_found")

    with sync_playwright() as pw:
        print("▶ 启动 Chromium（加载未打包扩展）")
        context = pw.chromium.launch_persistent_context(
            os.path.join(SHOTS, ".profile"),
            headless=not args.headed,
            args=[f"--disable-extensions-except={EXT_DIR}", f"--load-extension={EXT_DIR}",
                  "--no-first-run", "--no-default-browser-check"],
            viewport={"width": 1280, "height": 800},
            user_agent=UA, locale="zh-CN",
        )
        try:
            ext_id = report["extension_id"]
            note("extension_id_derived", extension_id=ext_id)
            context.add_cookies(load_x_cookies())
            note("cookies_injected")

            page = context.pages[0] if context.pages else context.new_page()
            page.set_viewport_size({"width": 1280, "height": 800})

            # ---------- 1) 主页 ----------
            page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=60000)
            dismiss_banner(page)
            count = wait_articles(page)
            page.wait_for_timeout(5000)
            report["home"] = {
                "articles": count,
                "content_script": page.evaluate(
                    "() => !!document.querySelector('.fs-manual-mark, .fs-badge, [data-fs-marked]')"),
                "marked": page.evaluate("() => document.querySelectorAll('[data-fs-marked]').length"),
                "badges": page.evaluate("() => document.querySelectorAll('.fs-badge').length"),
                "manual": page.evaluate("() => document.querySelectorAll('.fs-manual-mark').length"),
            }
            note("home_probe", **report["home"])
            shot(page, "timeline-1280x800")

            # ---------- 2) 弹窗 + 开启 AI 层 ----------
            popup = context.new_page()
            popup.set_viewport_size({"width": 1280, "height": 800})
            popup.goto(f"chrome-extension://{ext_id}/popup.html", timeout=30000)
            popup.wait_for_timeout(2500)
            report["popup_text"] = (popup.evaluate("() => document.body.innerText") or "")[:500]
            note("popup_loaded", text_head=report["popup_text"][:50].replace("\n", " "))
            shot(popup, "popup-1280x800")

            if args.enable_jev:
                key = jev_key()
                if key:
                    popup.evaluate(
                        """([k]) => chrome.storage.local.set({ jevSettingsV1: {
                             enabled: true, apiKey: k,
                             thresholds: { review: 0.7, blockCandidate: 0.9 } } })""",
                        [key],
                    )
                    note("jev_enabled_via_popup_page", key_len=len(key))
                else:
                    note("jev_key_missing")

            settings = context.new_page()
            settings.set_viewport_size({"width": 1280, "height": 800})
            settings.goto(f"chrome-extension://{ext_id}/popup.html", timeout=30000)
            settings.wait_for_timeout(2000)
            clicked = settings.evaluate("""() => {
                const b = [...document.querySelectorAll('button')]
                  .find(x => /设置|Settings/.test(x.textContent || ''));
                if (b) { b.click(); return true; } return false;
            }""")
            settings.wait_for_timeout(2500)
            report["settings_clicked"] = clicked
            shot(settings, "settings-1280x800")
            settings.close()
            popup.close()

            # ---------- 3) 搜索页：真实垃圾号 ----------
            url = (f"https://x.com/search?q={urllib.parse.quote(DEMO_QUERY)}"
                   f"&src=typed_query&f=live")
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            dismiss_banner(page)
            count = wait_articles(page, 60000)
            note("search_articles", count=count, query=DEMO_QUERY)
            marked = 0
            for i in range(args.wait):
                page.wait_for_timeout(1000)
                marked = page.evaluate("() => document.querySelectorAll('[data-fs-marked]').length")
                if marked:
                    note("marks_appeared", after_seconds=i + 1, marked=marked)
                    break
            report["search"] = {
                "query": DEMO_QUERY,
                "articles": count,
                "marked": marked,
                "by_ai": page.evaluate("() => document.querySelectorAll('[data-fs-marked=\"ai\"]').length"),
                "by_keyword": page.evaluate(
                    "() => document.querySelectorAll('[data-fs-marked=\"heuristic\"]').length"),
                "badges": page.evaluate("() => document.querySelectorAll('.fs-badge').length"),
                "reasons": page.evaluate(
                    "() => [...document.querySelectorAll('.fs-reason')].slice(0,6).map(e=>e.textContent)"),
            }
            note("search_probe", **{k: v for k, v in report["search"].items() if k != "reasons"})
            for reason in report["search"]["reasons"]:
                print(f"      理由: {reason}")

            # 被标账号的细节：必须能复核 AI 判得对不对（误标是产品级事故）
            marks_js = pathlib.Path(os.path.join(HERE, "extract_marks.js")).read_text(encoding="utf-8")
            report["marked_details"] = page.evaluate(marks_js)
            for d in report["marked_details"]:
                print(f"      被标账号: {d['handle']}")
                print(f"        正文: {d['text'][:90]!r}")
                print(f"        理由: {d['reason']} (来源={d['source']})")

            # 滚动到黄框并出特写（这张才是能用的宣传图）
            try:
                cell = page.locator('[data-fs-marked]').first
                cell.scroll_into_view_if_needed(timeout=5000)
                page.wait_for_timeout(1200)
                dismiss_banner(page)
                shot(page, "search-marked-1280x800")
                cell.screenshot(path=os.path.join(SHOTS, "marked-card.png"))
                note("shot_marked_card")
            except Exception as exc:
                note("marked_scroll_failed", error=str(exc)[:80])
                shot(page, "search-marked-1280x800")
        finally:
            context.close()

    out = os.path.join(SHOTS, "report.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    content_script = report.get("home", {}).get("content_script")
    marked = report.get("search", {}).get("marked") or report.get("home", {}).get("marked")
    print(f"\n✓ 报告 {out}")
    print(f"  内容脚本注入: {content_script} | 页面标出账号数: {marked}")
    print(f"  结论: {'✅ 真机端到端跑通' if content_script and marked else '⚠️ 部分未通过（见报告）'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
