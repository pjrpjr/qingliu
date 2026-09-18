#!/usr/bin/env python3
"""从黄推帖子的回复区批量捞账号档案 —— 一次请求 ≈ 20 份档案。

为什么换这条路：逐个查 882 条公开名单，在 X 限流下约 11 秒/个，而且 84% 是死号
（有效产出 ≈ 1 活号 / 9 次请求）。而 `TweetDetail` 一条回复区请求就能返回 20+ 个
回复作者的**完整档案**（handle / 昵称 / 简介 / 粉丝关注数 / 回复正文）——
有效产出高一个数量级，而且这正是产品要处理的场景：**垃圾回复**。

⚠️ 标签口径（必须如实标注，写进 RESULTS.md）：
   · `tier="list"`    阳性的主集：来自第三方人工整理的公开名单（独立标签）
   · `tier="network"` 阳性的补充集：出现在黄推帖子回复区的账号 —— 由**人（agent）
     按写死的规则复核**后标注，属于弱一档的证据，报告里单列，不与主集混算。

用法:
    python3 jev/harvest_reply_network.py --seeds 12 --posts-per-seed 3 --max-requests 60
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from x_client import XSession  # noqa: E402
from build_dataset import DATA, load_jsonl, write_jsonl  # noqa: E402

OUT = os.path.join(DATA, "network_positives.jsonl")


def judgeable(row: dict) -> bool:
    profile = row.get("profile") or {}
    return bool((profile.get("bio") or "").strip()) or bool(row.get("tweets"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=12)
    ap.add_argument("--posts-per-seed", type=int, default=3)
    ap.add_argument("--max-requests", type=int, default=60)
    ap.add_argument("--min-interval", type=float, default=1.5)
    args = ap.parse_args()

    seeds = [r for r in load_jsonl(os.path.join(DATA, "positives.jsonl"))
             if not r.get("dead") and judgeable(r) and r.get("tweets")][:args.seeds]
    print(f"▶ 种子 {len(seeds)} 个活跃黄推号，每个取 {args.posts_per_seed} 条帖子的回复区")

    rows = load_jsonl(OUT)
    known = {r["handle"].lower() for r in rows}
    seed_handles = {r["handle"].lower() for r in seeds}

    x = XSession(min_interval=args.min_interval, max_requests=args.max_requests)
    added = 0
    for si, seed in enumerate(seeds, 1):
        if x.requests_made >= args.max_requests - 2:
            print("  ⛔ 触到请求上限")
            break
        posts = sorted(seed["tweets"], key=lambda t: (t.get("like_count") or 0), reverse=True)
        if not any(p.get("post_id") for p in posts):
            # build_dataset 存的档案里没有 post_id（当时只留了正文/域名/点赞）：
            # 现拉一次该账号的推文拿 ID，每个种子多花 1 次请求。
            rest_id = (seed.get("profile") or {}).get("rest_id")
            if not rest_id:
                print(f"      ! @{seed['handle']} 缺 rest_id，跳过")
                continue
            try:
                fetched = x.user_tweets(rest_id, count=20)
            except Exception as exc:
                print(f"      ✗ @{seed['handle']} 取推文失败: {str(exc)[:70]}")
                continue
            posts = sorted(
                ({"post_id": t.get("post_id"), "like_count": t.get("like_count")}
                 for t in fetched
                 if (t.get("author") or {}).get("handle", "").lower() == seed["handle"].lower()
                 and t.get("post_id")),
                key=lambda t: (t.get("like_count") or 0), reverse=True)
        print(f"  [{si}/{len(seeds)}] 种子 @{seed['handle']}（{len(posts)} 条帖子可用）")
        for post in posts[:args.posts_per_seed]:
            pid = post.get("post_id")
            if not pid:
                continue
            try:
                data = x.graphql("TweetDetail", {
                    "focalTweetId": pid,
                    "with_rux_injections": False,
                    "rankingMode": "Relevance",
                    "includePromotedContent": False,
                    "withCommunity": True,
                    "withQuickPromoteEligibilityTweetFields": True,
                    "withBirdwatchNotes": True,
                    "withVoice": True,
                })
            except Exception as exc:
                print(f"      ✗ {pid}: {str(exc)[:70]}")
                continue
            fresh = 0
            for tw in x.timeline_tweets(data):
                author = tw.get("author") or {}
                handle = (author.get("handle") or "").strip()
                if not handle:
                    continue
                if handle.lower() in known or handle.lower() in seed_handles:
                    continue
                known.add(handle.lower())
                rows.append({
                    "handle": handle,
                    "side": "positive",
                    "tier": "network",
                    "via": f"reply:{seed['handle']}",
                    "profile": {
                        "rest_id": author.get("rest_id"),
                        "handle": author.get("handle"),
                        "name": author.get("name"),
                        "bio": author.get("bio") or "",
                        "location": author.get("location") or "",
                        "followers": author.get("followers"),
                        "following_count": author.get("following_count"),
                        "statuses": author.get("statuses"),
                        "created_at": author.get("created_at"),
                        "verified": author.get("verified"),
                        "has_custom_avatar": author.get("has_custom_avatar"),
                        "url": author.get("url"),
                    },
                    # 回复正文就是该账号的发言内容（不是它主页的时间线，报告里要写明）
                    "tweets": [{"text": tw.get("text"), "urls": tw.get("urls"),
                                "has_media": tw.get("has_media"),
                                "created_at": tw.get("created_at"),
                                "like_count": tw.get("like_count")}],
                    "link_hosts": sorted({u["host"] for u in (tw.get("urls") or [])
                                          if u.get("host") and u["host"] not in
                                          ("x.com", "twitter.com", "t.co")}),
                    "meta": {
                        "followers": author.get("followers"),
                        "following": author.get("following_count"),
                        "statuses": author.get("statuses"),
                        "verified": author.get("verified"),
                        "has_custom_avatar": author.get("has_custom_avatar"),
                        "created_at": author.get("created_at"),
                    },
                })
                fresh += 1
                added += 1
            print(f"      {pid} → 新增 {fresh} 份档案（累计 {added}）")
            write_jsonl(OUT, rows)

    print(f"\n✓ 回复区扩网：{len(rows)} 份档案（本轮 +{added}），请求 {x.requests_made} 次 → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
