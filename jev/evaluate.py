#!/usr/bin/env python3
"""按预注册判据出数 —— 见 `jev/PREREGISTRATION.md`（判据在跑之前就钉死了）。

输出 H1–H5 的实测数字 + 词库层基线对照 + 选定阈值的错分清单。
所有区间都用自助法/二项区间给出来，不报裸点估计（预注册第六节第 4 条）。

用法:
    python3 jev/evaluate.py                # 全部判据
    python3 jev/evaluate.py --audit        # 打印标签审计样本（看标签是否还成立）
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import keywords  # noqa: E402

DATA = os.path.join(HERE, "data")
JUDGMENTS = os.path.join(DATA, "jev_judgments.jsonl")
KEYWORD_PACK = os.path.join(os.path.dirname(HERE), "community", "keyword-packs", "official.json")
BOOTSTRAP = 2000
FPR_BUDGET = 0.02       # H1 的误杀预算
BOOT_SEED = 20260919


def load_jsonl(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def auc(pairs: list[tuple[float, int]]) -> float:
    """秩和法 AUC（并列取平均秩）。pairs = [(score, label01)]。"""
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


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """二项比例的 Wilson 区间（小样本比正态近似靠谱）。"""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def bootstrap_ci(values: list[float], reps: int = BOOTSTRAP) -> tuple[float, float]:
    if not values:
        return (float("nan"), float("nan"))
    rng = random.Random(BOOT_SEED)
    n = len(values)
    means = []
    for _ in range(reps):
        means.append(sum(values[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    return (means[int(0.025 * reps)], means[int(0.975 * reps)])


def threshold_for_fpr(neg_scores: list[float], budget: float) -> float:
    """满足 FPR <= budget 的最低阈值（分数越高越像垃圾号）。"""
    if not neg_scores:
        return 1.0
    ordered = sorted(neg_scores, reverse=True)
    allowed = int(budget * len(ordered))  # 允许误杀的个数（向下取整）
    if allowed <= 0:
        return min(1.0, ordered[0] + 1e-9) if ordered else 1.0
    return ordered[allowed - 1]  # 第 allowed 个最高分即为阈值下界


def pick(rows: list[dict], **filters) -> list[dict]:
    out = []
    for r in rows:
        if any(r.get(k) != v for k, v in filters.items()):
            continue
        out.append(r)
    return out


def scored(rows: list[dict]) -> list[tuple[float, int]]:
    return [(r["spam"], 1 if r["side"] == "positive" else 0)
            for r in rows if isinstance(r.get("spam"), (int, float))]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", action="store_true", help="打印标签审计样本")
    args = ap.parse_args()

    rows = load_jsonl(JUDGMENTS)
    if not rows:
        sys.exit("✗ 还没有判定结果：先跑 jev/judge.py")
    rules = keywords.load_rules(KEYWORD_PACK)

    if args.audit:
        print("▶ 标签审计（人工复核当前内容是否仍符合标签）\n")
        for side in ("positive", "negative"):
            subset = [r for r in rows if r["side"] == side][:20]
            print(f"=== {side}（{len(subset)} 个）===")
            for r in subset:
                print(f"  @{r['handle'][:22]:22} spam={r.get('spam')} "
                      f"cat={r.get('category')} kw={len(r.get('keyword_hits') or [])} "
                      f"f={r.get('followers')}")
            print()
        return 0

    batch1 = pick(rows, mode="normal", batch_size=1)
    batch10 = pick(rows, mode="normal", batch_size=10)
    anon = pick(rows, mode="anon")
    print(f"▶ 判定记录 {len(rows)} 条：batch1={len(batch1)} batch10={len(batch10)} "
          f"anon={len(anon)}\n")

    base = batch10 or batch1
    if not base:
        sys.exit("✗ 没有可用的判定记录")
    import collections
    print("  构成：", dict(collections.Counter(
        f"{r['side']}/{(r.get('tier') or '?')}" for r in base)), "\n")

    # ---------- 词库层基线（同一批数据，产品真实匹配语义）----------
    print("=" * 68)
    print("词库层基线（778 条规则，产品同款语义）—— Jev 要打败的对照")
    print("=" * 68)
    for side in ("positive", "negative"):
        subset = [r for r in base if r["side"] == side]
        if not subset:
            continue
        hit = sum(1 for r in subset if r.get("keyword_hits"))
        lo, hi = wilson(hit, len(subset))
        label = "召回" if side == "positive" else "误杀率"
        print(f"  {side:9} n={len(subset):>3}  {label} = {hit}/{len(subset)} "
              f"= {hit / len(subset):.1%}  95%CI [{lo:.1%}, {hi:.1%}]")

    # ---------- H1 判别力 ----------
    print("\n" + "=" * 68)
    print("H1 判别力：AUC ≥ 0.90；FPR ≤ 2% 时 Recall ≥ 0.60")
    print("=" * 68)
    pairs = scored(base)
    a = auc(pairs)
    pos_scores = [r["spam"] for r in base if r["side"] == "positive"
                  and isinstance(r.get("spam"), (int, float))]
    neg_scores = [r["spam"] for r in base if r["side"] == "negative"
                  and isinstance(r.get("spam"), (int, float))]
    thr = threshold_for_fpr(neg_scores, FPR_BUDGET)
    caught = sum(1 for s in pos_scores if s >= thr)
    false_kill = sum(1 for s in neg_scores if s >= thr)
    rec = caught / len(pos_scores) if pos_scores else float("nan")
    fpr = false_kill / len(neg_scores) if neg_scores else float("nan")
    # AUC 的自助区间：重采样账号
    rng = random.Random(BOOT_SEED)
    boots = []
    for _ in range(400):
        sample = [pairs[rng.randrange(len(pairs))] for _ in range(len(pairs))]
        value = auc(sample)
        if value == value:
            boots.append(value)
    boots.sort()
    if boots:
        print(f"  AUC = {a:.3f}   95%CI [{boots[int(0.025 * len(boots))]:.3f}, "
              f"{boots[int(0.975 * len(boots))]:.3f}]   (n={len(pairs)})")
    print(f"  阈值 {thr:.3f}（FPR≤2% 的最低阈值）→ 实测 FPR {fpr:.1%} "
          f"({false_kill}/{len(neg_scores)})，Recall {rec:.1%} ({caught}/{len(pos_scores)})")
    rlo, rhi = wilson(caught, len(pos_scores))
    print(f"  Recall 95%CI [{rlo:.1%}, {rhi:.1%}]")
    h1 = a >= 0.90 and rec >= 0.60 and fpr <= FPR_BUDGET
    print(f"  → H1 {'✅ 通过' if h1 else '❌ 未通过'}")

    # 标签强度分开报：network 档是弱证据，不能拿它冒充主集的成绩
    tiers = {}
    for r in base:
        if r["side"] == "positive":
            tiers.setdefault(r.get("tier") or "list", []).append(r)
    for tier, subset in sorted(tiers.items()):
        scores = [r["spam"] for r in subset if isinstance(r.get("spam"), (int, float))]
        caught_tier = sum(1 for s in scores if s >= thr)
        a_tier = auc(scored(subset + [r for r in base if r["side"] == "negative"]))
        lo, hi = wilson(caught_tier, len(scores))
        print(f"    · tier={tier:9} n={len(scores):>3}  Recall {caught_tier}/{len(scores)} = "
              f"{caught_tier / len(scores):.1%} 95%CI [{lo:.1%}, {hi:.1%}]；"
              f"AUC(该 tier vs 阴性) = {a_tier:.3f}")

    # ---------- H2 扇出无损 ----------
    print("\n" + "=" * 68)
    print("H2 扇出无损：batch10 与 batch1 一致率 ≥ 0.90，AUC 差 ≤ 0.03")
    print("=" * 68)
    if batch1 and batch10:
        m1 = {r["handle"].lower(): r for r in batch1}
        m10 = {r["handle"].lower(): r for r in batch10}
        common = [h for h in m1 if h in m10]
        if common:
            agree = sum(1 for h in common
                        if (m1[h]["spam"] >= 0.5) == (m10[h]["spam"] >= 0.5))
            a1 = auc(scored([m1[h] for h in common]))
            a10 = auc(scored([m10[h] for h in common]))
            print(f"  共同账号 {len(common)}；阈值 0.5 下判定一致率 = "
                  f"{agree}/{len(common)} = {agree / len(common):.1%}")
            print(f"  AUC batch1 = {a1:.3f} / batch10 = {a10:.3f} / 差 = {abs(a1 - a10):.3f}")
            h2 = agree / len(common) >= 0.90 and abs(a1 - a10) <= 0.03
            print(f"  → H2 {'✅ 通过' if h2 else '❌ 未通过'}")
        else:
            print("  ⚠ 没有共同账号，无法比较")
    else:
        print("  ⚠ 缺 batch1 或 batch10 的记录（跑 jev/judge.py --batch 1 / --batch 10）")

    # ---------- H3 记忆污染探针 ----------
    print("\n" + "=" * 68)
    print("H3 不是背名单：handle 随机化后 AUC 下降 ≤ 0.05")
    print("=" * 68)
    if anon and base:
        anon_pairs = scored(anon)
        a_anon = auc(anon_pairs)
        print(f"  AUC 原文 = {a:.3f} / AUC 匿名 = {a_anon:.3f} / 差 = {abs(a - a_anon):.3f}")
        h3 = (a - a_anon) <= 0.05
        print(f"  → H3 {'✅ 通过' if h3 else '❌ 未通过'}")
    else:
        print("  ⚠ 缺 anon 记录（跑 jev/judge.py --mode anon --batch 10）")

    # ---------- H4 增量价值 ----------
    print("\n" + "=" * 68)
    print("H4 增量：词库未命中的阳性子集上 Recall ≥ 0.40（用 H1 的阈值）")
    print("=" * 68)
    miss = [r for r in base if r["side"] == "positive" and not r.get("keyword_hits")
            and isinstance(r.get("spam"), (int, float))]
    if miss:
        caught_miss = sum(1 for r in miss if r["spam"] >= thr)
        rec_miss = caught_miss / len(miss)
        lo, hi = wilson(caught_miss, len(miss))
        print(f"  词库未命中阳性 n={len(miss)}；Jev 抓到 {caught_miss} → "
              f"Recall = {rec_miss:.1%}  95%CI [{lo:.1%}, {hi:.1%}]")
        for tier in sorted({r.get("tier") or "list" for r in miss}):
            sub = [r for r in miss if (r.get("tier") or "list") == tier]
            hit = sum(1 for r in sub if r["spam"] >= thr)
            lo2, hi2 = wilson(hit, len(sub))
            print(f"    · tier={tier:9} n={len(sub):>3} Recall {hit}/{len(sub)} = "
                  f"{hit / len(sub):.1%} 95%CI [{lo2:.1%}, {hi2:.1%}]")
        print(f"  → H4 {'✅ 通过' if rec_miss >= 0.40 else '❌ 未通过'}")
    else:
        print("  ⚠ 没有词库未命中的阳性样本，H4 无法评估"
              "（这本身说明名单里的号大多是词库能抓的老式话术）")

    # ---------- H5 成本与延迟 ----------
    print("\n" + "=" * 68)
    print("H5 成本：单账号 ≤ $0.0005；batch10 摊薄延迟 ≤ 0.5s")
    print("=" * 68)
    tokens = sum(r.get("input_tokens") or 0 for r in base)
    lat = [r.get("latency") for r in base if r.get("latency")]
    per_account_cost = tokens / len(base) / 1_000_000 * 0.042 if base else float("nan")
    per_account_lat = (sum(lat) / len(lat) / (base[0]["batch_size"] or 1)) if lat else float("nan")
    print(f"  输入 token 合计 {tokens} / {len(base)} 个账号 → "
          f"${per_account_cost:.6f} 每账号")
    if lat:
        lat_sorted = sorted(lat)
        print(f"  单次调用延迟 p50={lat_sorted[len(lat_sorted) // 2]:.2f}s "
              f"p95={lat_sorted[int(0.95 * len(lat_sorted))]:.2f}s；"
              f"batch={base[0]['batch_size']} → 每账号摊薄 {per_account_lat:.2f}s")
    h5 = per_account_cost <= 0.0005 and per_account_lat <= 0.5
    print(f"  → H5 {'✅ 通过' if h5 else '❌ 未通过'}")

    # ---------- 上线阈值与错分清单 ----------
    print("\n" + "=" * 68)
    print(f"选定上线阈值 = {thr:.3f}（满足 FPR≤2% 的最低阈值）")
    print("=" * 68)
    print("  被漏掉的阳性（该抓没抓）：")
    for r in sorted([r for r in base if r["side"] == "positive"
                     and isinstance(r.get("spam"), (int, float)) and r["spam"] < thr],
                    key=lambda r: r["spam"])[:12]:
        print(f"    {r['spam']:.2f} @{r['handle'][:22]:22} kw={len(r.get('keyword_hits') or [])} "
              f"cat={r.get('category')}")
    print("  被误杀的阴性（绝不能发生）：")
    for r in sorted([r for r in base if r["side"] == "negative"
                     and isinstance(r.get("spam"), (int, float)) and r["spam"] >= thr],
                    key=lambda r: -r["spam"])[:12]:
        print(f"    {r['spam']:.2f} @{r['handle'][:22]:22} cat={r.get('category')} "
              f"evidence={r.get('evidence')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
