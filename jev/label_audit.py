#!/usr/bin/env python3
"""标签审计 + 修正后的指标 —— 预注册第六节要求的那一步。

## 审计发现（2026-09-19）

`network` 档（黄推帖子回复区捞到的 78 个账号）**标签大多是错的**：
逐个看下来，60 多个只是**在黄推下面回复的普通用户**（"想看"、"1"、"我我我"、
"姨我在北京市"）。Jev 给它们 0.1–0.3 分是**正确的**，是我的标签错了 ——
"出现在黄推回复区"根本不等于"这是垃圾号"，这正是预注册里写下的那种标签噪声。

## 审计判据（写死，可复核）

一个 `network` 账号算 `promo`（推广号），当且仅当它的**简介里出现可联系的商业特征**：
QQ/微信/LINE 等联系方式、价格表（`52/128/288/520`）、付费口令、明确的资源售卖、
或"简介只有一条 t.co 链接"这种纯导流形态。
只有口头骚话、没有任何可联系/可购买特征的，一律记为 `innocent`（保守方向：
把可疑的算成无辜，只会让 FPR 更高，不会让成绩更好看）。

用法:
    python3 jev/label_audit.py            # 写审计文件 + 打印修正后指标
"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import keywords  # noqa: E402

DATA = os.path.join(HERE, "data")
AUDIT = os.path.join(DATA, "network_label_audit.jsonl")
JUDGMENTS = os.path.join(DATA, "jev_judgments.jsonl")
KEYWORD_PACK = os.path.join(os.path.dirname(HERE), "community", "keyword-packs", "official.json")

# 审计结果：promo = 推广号（简介带商业/联系方式特征）；其余为 innocent。
# 逐个看的是 bio + 回复正文（见 --print 输出）。
PROMO = {
    "patriciale50074": "简介：sending pics on twitter to everyone that says hi + 链接",
    "xng72498683": "简介：QQ 3174033243 收乖m，接投稿 —— 联系方式 + 接单",
    "xiao_1031": "简介：QQ + 会按摩（可约服务）",
    "shuguhlhh11904": "简介：m 🚪52/128/288/520 口令红包 —— 明码价格表",
    "xinshi8343": "简介：成人招嫖式自我推广（给你舔）",
    "pu0wfhs0lygi9bu": "简介：性癖广告 + 强势人设（招 m）",
    "llll32907538": "简介：冰恋/sm 广告，招同好",
    "yushengban90372": "简介：只有一条 t.co 链接（纯导流形态）",
    "akiokissng": "简介：只有一条 t.co 链接（纯导流形态）",
    "z83525885": "简介：+_V（微信联系方式）",
    "d13bvrzayo14223": "简介：换脸服务（软广/接单）",
}

# 阴性集（用户关注列表）的标签噪声：这些账号**本身就是**本产品要处理的对象
# （成人引流 / 灰产代充 / 付费图包），用户是主动关注它们的。
# 不剔除它们会让 FPR 看起来比真实值高，但剔除依据必须独立于 Jev 的分数 ——
# 下面是逐个读简介得出的，不是按分数筛的。
NEGATIVE_LABEL_NOISE = {
    "aipornking": "简介：🔞 the best AI porn on the internet —— 成人内容推广号",
    "kkew68": "简介：由于推特限制，更多家庭乱只在VIP群更新 —— 成人VIP群引流",
    "akuyai77": "简介：全网ai源头 主营代充 —— 灰产代充号",
    "eaonfan": "简介：图包🛒 | 摄影会 | 付费带/代拍 —— 付费图包售卖",
}

CONTACT_RE = re.compile(r"(QQ|qq|微信|V信|LINE|line|电报|telegram|t\.me|口令|红包|赞赏)")


def load_jsonl(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def auc(pairs: list[tuple[float, int]]) -> float:
    pos = [s for s, y in pairs if y == 1]
    neg = [s for s, y in pairs if y == 0]
    if not pos or not neg:
        return float("nan")
    ordered = sorted(pairs, key=lambda p: p[0])
    ranks: dict[int, float] = {}
    i = 0
    while i < len(ordered):
        j = i
        while j + 1 < len(ordered) and ordered[j + 1][0] == ordered[i][0]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[k] = avg
        i = j + 1
    rank_sum = sum(ranks[idx] for idx, (_, y) in enumerate(ordered) if y == 1)
    n1, n0 = len(pos), len(neg)
    return (rank_sum - n1 * (n1 + 1) / 2) / (n1 * n0)


def main() -> int:
    rows = load_jsonl(JUDGMENTS)
    tag = os.environ.get("JEV_STATE_TAG", "online")
    base = [r for r in rows if r["mode"] == "normal" and r["batch_size"] == 10
            and (r.get("state_tag") or "full") == tag]
    print(f"▶ 使用 state 口径 = {tag}")
    if not base:
        sys.exit("✗ 先跑 jev/judge.py --mode normal --batch 10")
    rules = keywords.load_rules(KEYWORD_PACK)

    # ---- 写审计文件（可复核：每条都带理由）----
    network = [r for r in base if r.get("tier") == "network"]
    with open(AUDIT, "w", encoding="utf-8") as fh:
        for r in network:
            handle = r["handle"].lower()
            verdict = "promo" if handle in PROMO else "innocent"
            fh.write(json.dumps({
                "handle": r["handle"],
                "verdict": verdict,
                "reason": PROMO.get(handle, "无联系方式/价格/导流特征，只是回复了黄推"),
                "jev_spam": r["spam"],
            }, ensure_ascii=False) + "\n")
    print(f"▶ 审计文件 {AUDIT}（{len(network)} 条）")
    print(f"  promo {len(PROMO)} 个 / innocent {len(network) - len(PROMO)} 个\n")

    # ---- 修正后的标签集 ----
    positives = [r for r in base if r["side"] == "positive"
                 and (r.get("tier") == "list" or r["handle"].lower() in PROMO)]
    # 阴性：关注列表里剔除本身就是成人/灰产的 4 个 + 回复区的无辜者
    following_clean = [r for r in base if r["side"] == "negative"
                       and r["handle"].lower() not in NEGATIVE_LABEL_NOISE]
    negatives = following_clean + [r for r in network if r["handle"].lower() not in PROMO]
    n_noise = sum(1 for r in base if r["side"] == "negative"
                  and r["handle"].lower() in NEGATIVE_LABEL_NOISE)
    print(f"▶ 修正后：阳性 {len(positives)}（list {sum(1 for r in positives if r.get('tier') == 'list')}"
          f" + network-promo {len(PROMO)}） / 阴性 {len(negatives)}"
          f"（following-clean {len(following_clean)}"
          f" + network-innocent {len(network) - len(PROMO)}）")
    print(f"  已剔除的阴性标签噪声 {n_noise} 个：" +
          ", ".join(f"@{h}" for h in NEGATIVE_LABEL_NOISE) + "\n")

    pairs = [(r["spam"], 1) for r in positives if isinstance(r.get("spam"), (int, float))]
    pairs += [(r["spam"], 0) for r in negatives if isinstance(r.get("spam"), (int, float))]
    print(f"  AUC（修正后全集）= {auc(pairs):.3f}")
    list_only = [(r["spam"], 1) for r in positives if r.get("tier") == "list"] + \
                [(r["spam"], 0) for r in negatives if isinstance(r.get("spam"), (int, float))]
    print(f"  AUC（阳性只用 list 档 n={sum(1 for r in positives if r.get('tier') == 'list')}）"
          f"= {auc(list_only):.3f}\n")

    # ---- 阈值扫描：产品实际是「黄框 + 用户手点」，不是自动拉黑 ----
    print("▶ 阈值扫描（阴性 = 关注列表 + 无辜回复者，共 "
          f"{sum(1 for r in negatives if isinstance(r.get('spam'), (int, float)))} 个）")
    print("   阈值 |  误杀 FPR        | 召回 Recall（修正后阳性）")
    neg_scores = [r["spam"] for r in negatives if isinstance(r.get("spam"), (int, float))]
    pos_scores = [r["spam"] for r in positives if isinstance(r.get("spam"), (int, float))]
    for thr in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.88, 0.9):
        fk = sum(1 for s in neg_scores if s >= thr)
        tp = sum(1 for s in pos_scores if s >= thr)
        print(f"   {thr:.2f} | {fk:>3}/{len(neg_scores)} = {fk / len(neg_scores):>5.1%}"
              f"      | {tp:>3}/{len(pos_scores)} = {tp / len(pos_scores):>5.1%}")

    # ---- 词库基线（同一套修正标签）----
    print("\n▶ 词库层基线（778 条，同一批修正标签）")
    for name, subset in (("阳性", positives), ("阴性", negatives)):
        hit = sum(1 for r in subset if r.get("keyword_hits"))
        print(f"  {name}: 命中 {hit}/{len(subset)} = {hit / len(subset):.1%}")

    # ---- H4 修正版：词库未命中的阳性 ----
    miss = [r for r in positives if not r.get("keyword_hits")
            and isinstance(r.get("spam"), (int, float))]
    print(f"\n▶ H4 修正版：词库未命中的阳性 n={len(miss)}")
    for thr in (0.5, 0.7, 0.88):
        tp = sum(1 for r in miss if r["spam"] >= thr)
        print(f"  阈值 {thr:.2f} → Jev 抓到 {tp}/{len(miss)} = {tp / len(miss):.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
