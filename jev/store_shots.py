#!/usr/bin/env python3
"""生成 Chrome 应用商店要求的 1280×800 截图（真实截图，不摆拍）。

四张图：
  store-1-timeline.png   x.com 时间线上扩展在工作（干净、无 cookie 横幅）
  store-2-marked.png     被标注的垃圾账号：黄框 + 「AI 疑似色情引流（98%）」+ 操作按钮
                         ⚠️ 第三方敏感画面与账号名一律模糊处理（GitHub/商店都限制成人内容）
  store-3-popup.png      扩展弹窗（合成到 1280×800，弹窗本体只有 420px 宽）
  store-4-settings-ai.png 设置页滚动到「AI 判定（Jev）」卡片

用法: python3 jev/store_shots.py --headed
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXT_DIR = os.path.join(ROOT, "apps", "extension", ".output", "chrome-mv3")
SHOTS = os.path.join(ROOT, ".private", "shots")
COOKIE_EXTRACTOR = os.path.expanduser("~/naslib/tools/dydiffusion/extract_chrome_cookies.py")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36")
DEMO_QUERY = "福利在主页"

# 打码：第三方内容不公开。模糊媒体、头像与用户名，保留黄框与理由（那才是产品要展示的）
REDACT_CSS = """
[data-fs-marked] img,
[data-fs-marked] video { filter: blur(26px) saturate(0.7) !important; }
[data-fs-marked] [data-testid="User-Name"],
[data-fs-marked] [data-testid="User-Name"] * { filter: blur(7px) !important; }
[data-fs-marked] [data-testid="tweetText"] { filter: blur(4.5px) !important; }
/* 侧边栏账号切换器会露出**使用者自己的 handle** —— 截图对外，必须糊掉 */
[data-testid="SideNav_AccountSwitcher_Button"],
[data-testid="SideNav_AccountSwitcher_Button"] * { filter: blur(9px) !important; }
"""


def extension_id(path: str) -> str:
    digest = hashlib.sha256(path.encode("utf-8")).hexdigest()[:32]
    return "".join(chr(ord("a") + int(c, 16)) for c in digest)


def x_cookies() -> list[dict]:
    proc = subprocess.run([sys.executable, COOKIE_EXTRACTOR, "--host", "x.com", "--json"],
                          capture_output=True, text=True, check=True)
    return [{"name": k, "value": v, "domain": ".x.com", "path": "/",
             "secure": True, "httpOnly": False, "sameSite": "Lax"}
            for k, v in json.loads(proc.stdout).items()]


def dismiss(page) -> None:
    for _ in range(3):
        for sel in ('button:has-text("拒绝非必要的 Cookie")',
                    'button:has-text("接受所有 Cookie")',
                    'button:has-text("Accept all cookies")'):
            try:
                page.locator(sel).first.click(timeout=2000)
                page.wait_for_timeout(600)
                return
            except Exception:
                continue
        page.wait_for_timeout(1200)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    os.makedirs(SHOTS, exist_ok=True)
    from playwright.sync_api import sync_playwright

    made: list[str] = []
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            os.path.join(SHOTS, ".profile"), headless=not args.headed,
            args=[f"--disable-extensions-except={EXT_DIR}", f"--load-extension={EXT_DIR}",
                  "--no-first-run", "--no-default-browser-check"],
            viewport={"width": 1280, "height": 800}, user_agent=UA, locale="zh-CN",
        )
        try:
            context.add_cookies(x_cookies())
            ext = extension_id(EXT_DIR)
            page = context.pages[0] if context.pages else context.new_page()
            page.set_viewport_size({"width": 1280, "height": 800})

            # ---- 1) 时间线 ----
            page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=60000)
            dismiss(page)
            try:
                page.wait_for_function("() => document.querySelectorAll('article').length > 0",
                                       timeout=90000)
            except Exception:
                pass
            page.wait_for_timeout(6000)
            dismiss(page)
            page.add_style_tag(content=REDACT_CSS)
            page.wait_for_timeout(600)
            page.screenshot(path=os.path.join(SHOTS, "store-1-timeline.png"))
            made.append("store-1-timeline.png")

            # ---- 2) 被标账号（打码） ----
            url = (f"https://x.com/search?q={urllib.parse.quote(DEMO_QUERY)}"
                   "&src=typed_query&f=live")
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            dismiss(page)
            try:
                page.wait_for_function("() => document.querySelectorAll('article').length > 0",
                                       timeout=60000)
            except Exception:
                pass
            for _ in range(30):
                page.wait_for_timeout(1000)
                if page.evaluate("() => document.querySelectorAll('[data-fs-marked]').length"):
                    break
            page.add_style_tag(content=REDACT_CSS)
            page.wait_for_timeout(800)
            try:
                cell = page.locator("[data-fs-marked]").first
                cell.scroll_into_view_if_needed(timeout=5000)
                page.wait_for_timeout(1000)
                dismiss(page)
            except Exception:
                pass
            page.screenshot(path=os.path.join(SHOTS, "store-2-marked.png"))
            made.append("store-2-marked.png")

            # ---- 3) 弹窗（合成到 1280×800） ----
            popup = context.new_page()
            popup.set_viewport_size({"width": 460, "height": 760})
            popup.goto(f"chrome-extension://{ext}/popup.html", timeout=30000)
            popup.wait_for_timeout(2500)
            popup_png = base64.b64encode(popup.screenshot()).decode()
            popup.close()
            canvas = context.new_page()
            canvas.set_viewport_size({"width": 1280, "height": 800})
            canvas.set_content(f"""<!doctype html><meta charset="utf-8">
<style>
 body {{ margin:0; height:800px; display:flex; align-items:center; justify-content:center;
        gap:56px; background:linear-gradient(135deg,#f6f8fa 0%,#eef6f0 100%);
        font:600 30px -apple-system,"PingFang SC",sans-serif; color:#1f2328; }}
 .copy {{ max-width:420px; }}
 .copy p {{ font:15px/1.7 -apple-system,"PingFang SC",sans-serif; font-weight:400; color:#57606a; }}
 .shot {{ border-radius:14px; box-shadow:0 18px 48px rgba(27,31,36,.18); }}
</style>
<div class="copy">
  <div>清流 · X 时间线清洁工</div>
  <p>当前页面待处理账号、漏网账号一键拉黑、社区黑名单状态，都在一个弹窗里。</p>
  <p style="color:#1a7f37">标注永不隐藏内容 · 所有拉黑由你点击触发</p>
</div>
<img class="shot" src="data:image/png;base64,{popup_png}" height="700">
""")
            canvas.wait_for_timeout(600)
            canvas.screenshot(path=os.path.join(SHOTS, "store-3-popup.png"))
            made.append("store-3-popup.png")
            canvas.close()

            # ---- 4) 设置页：滚到 AI 卡片（同样合成到 1280×800） ----
            settings = context.new_page()
            settings.set_viewport_size({"width": 460, "height": 760})
            settings.goto(f"chrome-extension://{ext}/popup.html", timeout=30000)
            settings.wait_for_timeout(2000)
            settings.evaluate("""() => {
                const b = [...document.querySelectorAll('button')]
                  .find(x => /设置|Settings/.test(x.textContent || ''));
                if (b) b.click();
            }""")
            settings.wait_for_timeout(2500)
            scrolled = settings.evaluate("""() => {
                const h = [...document.querySelectorAll('h2')]
                  .find(x => /AI |Jev/i.test(x.textContent || ''));
                if (!h) return false;
                h.scrollIntoView({ block: 'start' });
                return true;
            }""")
            settings.wait_for_timeout(1200)
            settings_png = base64.b64encode(settings.screenshot()).decode()
            settings.close()
            print(f"  设置页找到 AI 卡片: {scrolled}")

            canvas2 = context.new_page()
            canvas2.set_viewport_size({"width": 1280, "height": 800})
            canvas2.set_content(f"""<!doctype html><meta charset="utf-8">
<style>
 body {{ margin:0; height:800px; display:flex; align-items:center; justify-content:center;
        gap:56px; background:linear-gradient(135deg,#f6f8fa 0%,#eef6f0 100%);
        font:600 30px -apple-system,"PingFang SC",sans-serif; color:#1f2328; }}
 .copy {{ max-width:430px; }}
 .copy p {{ font:15px/1.7 -apple-system,"PingFang SC",sans-serif; font-weight:400; color:#57606a; }}
 .shot {{ border-radius:14px; box-shadow:0 18px 48px rgba(27,31,36,.18); }}
</style>
<div class="copy">
  <div>AI 判定层（默认关闭）</div>
  <p>名单、指纹、词库都没认出时，才把账号资料交给 Jev 判一次。<br>
     填自己的 API key 即可开启，key 只存在本机。</p>
  <p style="color:#1a7f37">实测：误杀 0.7%，还能抓词库认不出的 47%</p>
</div>
<img class="shot" src="data:image/png;base64,{settings_png}" height="700">
""")
            canvas2.wait_for_timeout(600)
            canvas2.screenshot(path=os.path.join(SHOTS, "store-4-settings-ai.png"))
            made.append("store-4-settings-ai.png")
            canvas2.close()
        finally:
            context.close()

    print("✓ 产出：")
    for name in made:
        path = os.path.join(SHOTS, name)
        size = os.path.getsize(path) // 1024
        print(f"    {name}  {size} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
