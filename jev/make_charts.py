#!/usr/bin/env python3
"""生成 README 用的对比图（纯手写 SVG，无第三方依赖，可复现）。

数字全部来自 `jev/RESULTS.md` 的实测（37 阳 / 141 阴、线上口径单条推文）。
任何一次阈值或数据变动都必须同步改这里，否则图会与结论脱节。

用法: python3 jev/make_charts.py   → assets/brand/results-<lang>.svg
"""
from __future__ import annotations

import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(os.path.dirname(HERE), "assets", "brand")

# 实测值（jev/RESULTS.md）
KEYWORD_RECALL, KEYWORD_FPR = 54.1, 7.8
JEV07_RECALL, JEV07_FPR = 56.8, 0.7
JEV05_RECALL, JEV05_FPR = 67.6, 5.7
MISS_TOTAL, MISS_CAUGHT = 17, 8  # 词库完全抓不到的阳性里，Jev@0.5 另抓到 8 个

TEXT = {
    "zh": {
        "title": "同一批数据（37 个真垃圾号 / 141 个干净账号）",
        "recall": "抓到了多少垃圾号（召回，越高越好）",
        "fpr": "误杀了多少正常人（误杀率，越低越好）",
        "keyword": "778 条关键词（原版）",
        "jev07": "清流 · Jev 标准档",
        "jev05": "清流 · Jev 大扫除档",
        "miss": "词库完全认不出的 17 个垃圾号",
        "miss_sub": "清流的 AI 层另外抓到了 8 个（47%）",
        "note": "数据来源：jev/RESULTS.md · 判据与阈值在跑之前已冻结（预注册）",
    },
    "en": {
        "title": "Same dataset · 37 confirmed spam accounts vs 141 clean ones",
        "recall": "Spam caught (recall, higher is better)",
        "fpr": "Real users wrongly flagged (false positives, lower is better)",
        "keyword": "778 keyword rules (original)",
        "jev07": "Qingliu · Jev standard",
        "jev05": "Qingliu · Jev deep clean",
        "miss": "17 spam accounts the keyword layer never matches",
        "miss_sub": "Qingliu's AI layer catches 8 of them (47%)",
        "note": "Source: jev/RESULTS.md · criteria were pre-registered before any measurement",
    },
}

W, H = 880, 400


def bar(x: int, y: int, width: float, height: int, color: str) -> str:
    return (f'<rect x="{x}" y="{y}" width="{max(2, width):.1f}" height="{height}" '
            f'rx="5" fill="{color}"/>')


def panel(x: int, y: int, label: str, rows: list[tuple[str, float, str]], max_value: float,
          good: str) -> str:
    """一个面板：标题 + 若干横条 + 数值。"""
    out = [f'<text x="{x}" y="{y}" class="panel">{label}</text>']
    row_y = y + 26
    bar_max = 300.0
    for name, value, color in rows:
        width = value / max_value * bar_max
        out.append(f'<text x="{x}" y="{row_y + 13}" class="row">{name}</text>')
        out.append(bar(x + 168, row_y, width, 20, color))
        out.append(f'<text x="{x + 168 + width + 10:.0f}" y="{row_y + 14}" '
                   f'class="value" fill="{good if color == good else "#57606a"}">{value:.1f}%</text>')
        row_y += 34
    return "\n  ".join(out)


def build(lang: str) -> str:
    t = TEXT[lang]
    green = "#1a7f37"
    grey = "#8c959f"
    amber = "#bf8700"

    recall_panel = panel(
        40, 96, t["recall"],
        [(t["keyword"], KEYWORD_RECALL, grey),
         (t["jev07"], JEV07_RECALL, green),
         (t["jev05"], JEV05_RECALL, green)],
        100.0, green)

    fpr_panel = panel(
        40, 236, t["fpr"],
        [(t["keyword"], KEYWORD_FPR, amber),
         (t["jev07"], JEV07_FPR, green),
         (t["jev05"], JEV05_FPR, amber)],
        10.0, green)

    # 误杀率面板量纲不同（0–10%），单独标注刻度
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="{t['title']}">
  <style>
    .title {{ font: 600 17px -apple-system, "PingFang SC", "Segoe UI", sans-serif; fill: #1f2328; }}
    .panel {{ font: 600 14px -apple-system, "PingFang SC", "Segoe UI", sans-serif; fill: #1f2328; }}
    .row   {{ font: 13px -apple-system, "PingFang SC", "Segoe UI", sans-serif; fill: #57606a; }}
    .value {{ font: 600 13px -apple-system, "PingFang SC", "Segoe UI", sans-serif; }}
    .note  {{ font: 11.5px -apple-system, "PingFang SC", "Segoe UI", sans-serif; fill: #8c959f; }}
    .miss  {{ font: 600 13.5px -apple-system, "PingFang SC", "Segoe UI", sans-serif; fill: #1f2328; }}
    .misss {{ font: 12.5px -apple-system, "PingFang SC", "Segoe UI", sans-serif; fill: #1a7f37; }}
  </style>
  <rect width="{W}" height="{H}" fill="#ffffff"/>
  <text x="40" y="46" class="title">{t['title']}</text>

  {recall_panel}

  {fpr_panel}

  <rect x="40" y="352" width="{W - 80}" height="34" rx="8" fill="#f6f8fa"/>
  <text x="56" y="373" class="miss">{t['miss']} →</text>
  <text x="{56 + (28 if lang == 'zh' else 34) * len(t['miss']) + 24}" y="373" class="misss">{t['miss_sub']}</text>

  <text x="40" y="{H - 6}" class="note">{t['note']}</text>
</svg>
'''


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    for lang in ("zh", "en"):
        path = os.path.join(OUT_DIR, f"results-{lang}.svg")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(build(lang))
        print(f"✓ {path}")
    print(f"  词库 召回 {KEYWORD_RECALL}% / 误杀 {KEYWORD_FPR}%；"
          f"Jev@0.7 召回 {JEV07_RECALL}% / 误杀 {JEV07_FPR}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
