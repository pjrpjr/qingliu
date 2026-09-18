#!/usr/bin/env python3
"""生成商店宣传图（小图 440×280 + 跑马灯 1400×560），品牌为「清流」。

上游留下的两张宣传图是旧品牌（福滤娃/FeedSieve），本脚本重新生成，
用与商店截图一致的视觉语言，且数字与 README/RESULTS.md 同源。

用法: python3 jev/make_promo.py
"""
from __future__ import annotations

import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "assets", "store")

# 与 jev/RESULTS.md 同源的实测数字（改这里必须同步改 RESULTS.md）
KEYWORD_FPR, JEV_FPR = "7.8%", "0.7%"
JEV_RECALL, KEYWORD_RECALL = "56.8%", "54.1%"
MISS_CAUGHT = "47%"


def promo_html() -> str:
    return """<!doctype html><meta charset="utf-8">
<style>
  * { box-sizing: border-box; margin: 0; }
  body {
    width: 440px; height: 280px; overflow: hidden;
    background: linear-gradient(140deg, #10221a 0%, #1c3a2a 55%, #24503a 100%);
    font: 400 13px -apple-system, "PingFang SC", sans-serif; color: #e8f3ec;
    padding: 26px 28px; display: flex; flex-direction: column;
  }
  .brand { font-size: 27px; font-weight: 700; letter-spacing: .5px; }
  .sub { color: #8fd3ab; font-size: 13px; margin-top: 5px; }
  .rows { margin-top: 18px; display: grid; gap: 7px; }
  .row { display: flex; align-items: baseline; font-size: 12.5px; color: #cfe6da; }
  .row b { font-size: 15px; color: #fff; margin-left: auto; font-weight: 700; }
  .row.bad b { color: #ffb4a2; }
  .row.good b { color: #7ee2a8; }
  .foot { margin-top: auto; font-size: 11.5px; color: #8fd3ab; }
  .chip { display:inline-block; padding:1px 7px; border:1px solid #3d6b53; border-radius:99px;
          font-size:10.5px; color:#a9dcc0; margin-right:5px }
</style>
<div class="brand">清流 Qingliu</div>
<div class="sub">X 时间线清洁工 · 黄框标注 → 一键原生拉黑</div>
<div class="rows">
  <div class="row bad">误杀正常人（778 条关键词） <b>@KEYWORD_FPR@</b></div>
  <div class="row good">误杀正常人（清流 AI 层） <b>@JEV_FPR@</b></div>
  <div class="row">抓到垃圾号 <b>@JEV_RECALL@</b></div>
  <div class="row">词库认不出的还能抓 <b>@MISS_CAUGHT@</b></div>
</div>
<div class="foot"><span class="chip">默认不联网</span><span class="chip">永不隐藏内容</span><span class="chip">拉黑由你点</span></div>
"""


def marquee_html() -> str:
    return """<!doctype html><meta charset="utf-8">
<style>
  * { box-sizing: border-box; margin: 0; }
  body {
    width: 1400px; height: 560px; overflow: hidden;
    background: radial-gradient(1200px 500px at 78% 18%, #2c6349 0%, #12251c 62%);
    font: 400 18px -apple-system, "PingFang SC", sans-serif; color: #e8f3ec;
    padding: 74px 84px; display: flex; flex-direction: column;
  }
  .brand { font-size: 82px; font-weight: 700; letter-spacing: 1px; }
  .tag { font-size: 26px; color: #9fdcbb; margin-top: 14px; }
  .cards { display: flex; gap: 22px; margin-top: 54px; }
  .card { background: rgba(255,255,255,.07); border: 1px solid rgba(255,255,255,.13);
          border-radius: 16px; padding: 22px 26px; min-width: 250px; }
  .card .k { font-size: 14px; color: #9fdcbb; }
  .card .v { font-size: 40px; font-weight: 700; margin-top: 6px; }
  .card.hi .v { color: #7ee2a8; }
  .foot { margin-top: auto; font-size: 17px; color: #9fdcbb; }
</style>
<div class="brand">清流 Qingliu</div>
<div class="tag">X 时间线清洁工 · 黄框标注垃圾账号 · 一键原生拉黑 · 全端同步消失</div>
<div class="cards">
  <div class="card hi"><div class="k">误杀正常人</div><div class="v">@JEV_FPR@</div></div>
  <div class="card"><div class="k">抓到垃圾号</div><div class="v">@JEV_RECALL@</div></div>
  <div class="card"><div class="k">词库认不出的还能抓</div><div class="v">@MISS_CAUGHT@</div></div>
  <div class="card"><div class="k">单账号判定成本</div><div class="v">$0.000032</div></div>
</div>
<div class="foot">基于 FeedSieve(MIT) · 实测数据与判据：jev/RESULTS.md</div>
"""


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    from playwright.sync_api import sync_playwright

    tokens = {"@KEYWORD_FPR@": KEYWORD_FPR, "@JEV_FPR@": JEV_FPR,
              "@JEV_RECALL@": JEV_RECALL, "@KEYWORD_RECALL@": KEYWORD_RECALL,
              "@MISS_CAUGHT@": MISS_CAUGHT}

    def fill(html: str) -> str:
        for k, v in tokens.items():
            html = html.replace(k, v)
        return html

    jobs = [
        ("promo-440x280.png", 440, 280, fill(promo_html())),
        ("marquee-1400x560.png", 1400, 560, fill(marquee_html())),
    ]
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for name, w, h, html in jobs:
            page = browser.new_page(viewport={"width": w, "height": h},
                                    device_scale_factor=2)
            page.set_content(html)
            page.wait_for_timeout(400)
            page.screenshot(path=os.path.join(OUT, name))
            page.close()
            print(f"✓ {os.path.join('assets/store', name)}  {w}×{h} @2x")
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
