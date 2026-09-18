#!/usr/bin/env python3
"""构建评测数据集 —— 两侧标签都来自**外部人工整理**，不由本项目自己标。

阳性：`daymade/Twitter-Block-Porn` 的公开黄推名单（882 条，第三方人工整理）
阴性：本机 x.com 登录账号的**关注列表**（用户自己挑的人，绝不能误杀）

为什么这样设计：如果用词库命中来标阳性，评测就变成"拿自己的输入验证自己的判据"，
必然得到 100% 的假成绩（`naslib-pick/SKILL.md` 里已经吃过这个亏）。
第三方名单 + 用户关注列表是两条**互相独立**的人工判断，才有资格当 ground truth。

用法:
    python3 jev/build_dataset.py --pos 80 --neg 80 --max-requests 340
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from x_client import XSession  # noqa: E402

DATA = os.path.join(HERE, "data")
BLOCKLIST_URL = (
    "https://raw.githubusercontent.com/daymade/Twitter-Block-Porn/master/lists/all.json"
)
BLOCKLIST_LOCAL = os.path.join(DATA, "external_blocklist.json")
SEED = 20260919  # 抽样种子：冻结，保证数据集可复现


def load_jsonl(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def write_jsonl(path: str, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def ensure_blocklist() -> list[dict]:
    os.makedirs(DATA, exist_ok=True)
    if not os.path.exists(BLOCKLIST_LOCAL):
        print(f"  ↓ 下载公开名单 {BLOCKLIST_URL}")
        with urllib.request.urlopen(BLOCKLIST_URL, timeout=60) as resp:
            raw = resp.read()
        with open(BLOCKLIST_LOCAL, "wb") as fh:
            fh.write(raw)
    with open(BLOCKLIST_LOCAL, encoding="utf-8") as fh:
        return json.load(fh)


def sample_handles(entries: list[dict], n: int) -> list[str]:
    """确定性抽样：种子固定，任何人都能复现同一批 handle。"""
    handles = sorted({(e.get("screen_name") or "").strip().lstrip("@")
                      for e in entries if e.get("screen_name")})
    rng = random.Random(SEED)
    return rng.sample(handles, min(n, len(handles)))


def fetch_dossiers(x: XSession, handles: list[str], out_path: str, side: str,
                   max_tweets: int = 15) -> list[dict]:
    done = {r["handle"].lower() for r in load_jsonl(out_path)}
    rows = load_jsonl(out_path)
    todo = [h for h in handles if h.lower() not in done]
    print(f"▶ {side}: 目标 {len(handles)}，已完成 {len(done)}，本轮待采 {len(todo)}")
    for i, handle in enumerate(todo, 1):
        if x.requests_made >= x.max_requests - 2:
            print("  ⛔ 触到请求上限，剩下的下次再采")
            break
        try:
            profile = x.user_by_screen_name(handle)
        except Exception as exc:
            print(f"  [{i}/{len(todo)}] ✗ @{handle} {str(exc)[:70]}")
            continue
        if not profile.get("rest_id"):
            rows.append({"handle": handle, "side": side, "dead": True})
            write_jsonl(out_path, rows)
            print(f"  [{i}/{len(todo)}] · @{handle} 已注销/不可见")
            continue
        tweets: list[dict] = []
        try:
            tweets = [t for t in x.user_tweets(profile["rest_id"], count=max_tweets)
                      if (t.get("author") or {}).get("handle", "").lower() == handle.lower()]
        except Exception as exc:
            print(f"    ! @{handle} 推文失败 {str(exc)[:60]}")
        hosts = sorted({u["host"] for t in tweets for u in (t.get("urls") or [])
                        if u.get("host") and u["host"] not in ("x.com", "twitter.com", "t.co")})
        rows.append({
            "handle": handle,
            "side": side,
            "profile": profile,
            "tweets": [{"text": t.get("text"), "urls": t.get("urls"),
                        "has_media": t.get("has_media"),
                        "created_at": t.get("created_at"),
                        "like_count": t.get("like_count")} for t in tweets],
            "link_hosts": hosts,
            "meta": {
                "followers": profile.get("followers"),
                "following": profile.get("following_count"),
                "statuses": profile.get("statuses"),
                "verified": profile.get("verified"),
                "has_custom_avatar": profile.get("has_custom_avatar"),
                "created_at": profile.get("created_at"),
            },
        })
        write_jsonl(out_path, rows)
        print(f"  [{i}/{len(todo)}] ✓ @{handle[:22]:22} 推文 {len(tweets):>2} "
              f"粉丝 {str(profile.get('followers')):>7} 关注 {str(profile.get('following_count')):>5}")
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pos", type=int, default=80)
    ap.add_argument("--neg", type=int, default=80)
    ap.add_argument("--max-requests", type=int, default=340)
    ap.add_argument("--min-interval", type=float, default=1.5)
    args = ap.parse_args()

    print("▶ 公开黄推名单")
    entries = ensure_blocklist()
    pos_handles = sample_handles(entries, args.pos)
    print(f"  名单 {len(entries)} 条 → 确定性抽样 {len(pos_handles)} 个（seed={SEED}）")

    following = load_jsonl(os.path.join(DATA, "corpus_following.jsonl"))
    neg_handles = [r["handle"] for r in following if r.get("handle")][:args.neg]
    print(f"  关注列表 {len(following)} 个 → 取前 {len(neg_handles)} 个当阴性")

    x = XSession(min_interval=args.min_interval, max_requests=args.max_requests)
    print(f"  会话就绪，请求上限 {args.max_requests}\n")
    pos_path = os.path.join(DATA, "positives.jsonl")
    neg_path = os.path.join(DATA, "negatives.jsonl")
    pos = fetch_dossiers(x, pos_handles, pos_path, "positive")
    print()
    neg = fetch_dossiers(x, neg_handles, neg_path, "negative")

    print(f"\n✓ 阳性 {len([r for r in pos if not r.get('dead')])} / 阴性 "
          f"{len([r for r in neg if not r.get('dead')])}；共 {x.requests_made} 次请求")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
