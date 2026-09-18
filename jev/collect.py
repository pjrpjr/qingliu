#!/usr/bin/env python3
"""真实样本采集 —— 为 Jev 评测准备在野数据。

为什么不用 SearchTimeline：X 给它加了 `x-client-transaction-id` 保护，无该头一律 404
（已实测：GET/POST、x.com/api.x.com/twitter.com 三个基址都是 404，而同会话下
UserTweets / TweetDetail / UserByScreenName / Following 全部 200）。
所以走**回复区**采集 —— 垃圾回复本来就是福滤娃的主战场，分布上也更贴近真实。

采集三份：
  corpus_replies.jsonl   自己帖子 + 高互动帖的回复作者（阳性候选的主要来源）
  corpus_own.jsonl       自己发的推文（用于挑高回复量的帖子当采集入口）
  corpus_following.jsonl 自己的关注列表（阴性样本：绝对不能误杀的总体）

用法:
    python3 jev/collect.py --posts 25 --max-requests 120
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from x_client import XSession  # noqa: E402

DATA = os.path.join(HERE, "data")
# 自己的 handle 不进仓库：用 --self 或 JEV_SELF_HANDLE 环境变量传入。
SELF_HANDLE = os.environ.get("JEV_SELF_HANDLE", "")


def write_jsonl(path: str, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"  → {path}（{len(rows)} 行）")


def collect_own(x: XSession) -> list[dict]:
    print("▶ 1/3 自己的推文（用来挑高回复量入口）")
    me = x.user_by_screen_name(SELF_HANDLE)
    if not me.get("rest_id"):
        raise SystemExit("✗ 取不到自己的 rest_id")
    tweets = x.user_tweets(me["rest_id"], count=40)
    tweets.sort(key=lambda t: (t.get("reply_count") or 0), reverse=True)
    print(f"  取到 {len(tweets)} 条；回复数 top5: "
          f"{[(t['post_id'], t.get('reply_count')) for t in tweets[:5]]}")
    return tweets


def collect_replies(x: XSession, entries: list[dict], max_posts: int) -> list[dict]:
    """TweetDetail 抓回复作者。每条回复保留作者档案 + 回复正文 + 外链域名。"""
    print(f"▶ 2/3 回复区（入口 {min(max_posts, len(entries))} 个帖子）")
    rows: list[dict] = []
    seen_post: set[str] = set()
    for entry in entries[:max_posts]:
        pid = entry.get("post_id")
        if not pid or pid in seen_post:
            continue
        seen_post.add(pid)
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
            }, features=x.features, field_toggles=x.field_toggles)
        except Exception as exc:
            print(f"    ✗ {pid}: {exc}")
            continue
        tweets = x.timeline_tweets(data)
        new = 0
        for t in tweets:
            author = t.get("author") or {}
            if not author.get("handle") or author.get("handle") == SELF_HANDLE:
                continue
            rows.append({
                "source": "reply",
                "seed_post_id": pid,
                "seed_reply_count": entry.get("reply_count"),
                "author": author,
                "text": t.get("text"),
                "urls": t.get("urls"),
                "has_media": t.get("has_media"),
                "post_id": t.get("post_id"),
                "created_at": t.get("created_at"),
                "like_count": t.get("like_count"),
            })
            new += 1
        print(f"    {pid}（原帖回复 {entry.get('reply_count')}）→ {new} 条回复作者")
    return rows


def collect_following(x: XSession, pages: int) -> list[dict]:
    print("▶ 3/3 关注列表（阴性总体）")
    me = x.user_by_screen_name(SELF_HANDLE)
    rows: list[dict] = []
    cursor = None
    for page in range(pages):
        users, cursor = x.following(me["rest_id"], count=100, cursor=cursor)
        rows.extend(users)
        print(f"    第 {page + 1} 页 → {len(users)} 个（累计 {len(rows)}）")
        if not cursor or not users:
            break
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--posts", type=int, default=25, help="抓多少个帖子的回复区")
    ap.add_argument("--follow-pages", type=int, default=2)
    ap.add_argument("--max-requests", type=int, default=140)
    ap.add_argument("--self", default="", help="你自己的 X handle（阴性样本来源）")
    args = ap.parse_args()
    global SELF_HANDLE
    SELF_HANDLE = args.self or SELF_HANDLE
    if not SELF_HANDLE:
        sys.exit("✗ 需要 --self <你的handle> 或 JEV_SELF_HANDLE（阴性样本来自你的关注列表）")

    os.makedirs(DATA, exist_ok=True)
    x = XSession(min_interval=1.2, max_requests=args.max_requests)
    print(f"  会话就绪：{len(x.queries)} 个 queryId，请求上限 {args.max_requests}\n")

    own = collect_own(x)
    write_jsonl(os.path.join(DATA, "corpus_own.jsonl"), own)

    print()
    replies = collect_replies(x, own, args.posts)
    write_jsonl(os.path.join(DATA, "corpus_replies.jsonl"), replies)

    print()
    following = collect_following(x, args.follow_pages)
    write_jsonl(os.path.join(DATA, "corpus_following.jsonl"), following)

    print(f"\n✓ 采集完成：{len(own)} 自己的推文 / {len(replies)} 条回复 / "
          f"{len(following)} 个关注；共 {x.requests_made} 次请求")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
