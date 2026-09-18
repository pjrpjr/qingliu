#!/usr/bin/env python3
"""种子扩散与档案采集 —— 把"真实账号档案"攒成 Jev 能判的输入。

发现的路径（按可靠性排序，都是图上的真实边，不猜）：
  1. 种子号自己的推文            → 直接拿到在野话术
  2. 种子号帖子下的回复作者      → 黄推之间互相回复引流，精度最高的扩网边
  3. 种子号的粉丝                → 池子大但混着普通用户（要按内容二次判定）
  4. 种子号的关注                → 同上

每个候选落一份"档案"（dossier）：主页字段 + 近期推文 + 外链域名 + 图上关系。
这份档案就是 Jev 的 `state` 原料，也是后续可复盘的证据。

支持断点续采：已采过的 handle 直接跳过，重跑不重复花请求。

用法:
    python3 jev/discover.py --rounds 2 --max-requests 160
    python3 jev/discover.py --add somehandle anotherhandle   # 手工加种子后重跑
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from x_client import XSession  # noqa: E402

DATA = os.path.join(HERE, "data")
SEEDS = os.path.join(DATA, "seeds.txt")
DOSSIERS = os.path.join(DATA, "dossiers.jsonl")

# 起点种子：网络搜索定位到的真实在野账号（黄推/成人引流），
# 以及抱怨黄推的正常用户（天然的阴性对照）。
DEFAULT_SEEDS = """\
# 阳性种子：真实在野黄推 / 成人引流号
aceasmrfuli66
wainiuniu2002
# 阴性对照种子：公开抱怨"我福不黑"刷屏的正常用户
jiangdajishi
Hrb9si
SetsuUnTaker
"""


def load_jsonl(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def append_jsonl(path: str, row: dict) -> None:
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def ensure_seeds() -> list[str]:
    os.makedirs(DATA, exist_ok=True)
    if not os.path.exists(SEEDS):
        with open(SEEDS, "w", encoding="utf-8") as fh:
            fh.write(DEFAULT_SEEDS)
    out = []
    with open(SEEDS, encoding="utf-8") as fh:
        for line in fh:
            line = line.split("#")[0].strip().lstrip("@")
            if line:
                out.append(line)
    return out


def links_of(tweets: list[dict]) -> list[str]:
    hosts = []
    for t in tweets:
        for u in t.get("urls") or []:
            host = u.get("host")
            if host and host not in ("x.com", "twitter.com", "t.co"):
                hosts.append(host)
    return sorted(set(hosts))


def build_dossier(x: XSession, handle: str, via: str,
                  known_spam: set[str], max_tweets: int = 15) -> dict | None:
    """采一个账号的档案；主页取不到就返回 None（账号已注销/被封）。"""
    try:
        profile = x.user_by_screen_name(handle)
    except Exception as exc:
        print(f"    ✗ @{handle} 主页失败: {str(exc)[:80]}")
        return None
    if not profile.get("rest_id"):
        print(f"    ✗ @{handle} 无 rest_id（可能已注销）")
        return None
    tweets: list[dict] = []
    try:
        tweets = x.user_tweets(profile["rest_id"], count=max_tweets)
    except Exception as exc:
        print(f"    ! @{handle} 推文失败: {str(exc)[:80]}")
    # 只保留作者本人的推文，并按时间倒序
    tweets = [t for t in tweets if (t.get("author") or {}).get("handle", "").lower()
              == handle.lower()]
    return {
        "handle": handle,
        "via": via,
        "profile": profile,
        "tweets": [{
            "post_id": t.get("post_id"),
            "text": t.get("text"),
            "urls": t.get("urls"),
            "has_media": t.get("has_media"),
            "created_at": t.get("created_at"),
            "like_count": t.get("like_count"),
        } for t in tweets],
        "link_hosts": links_of(tweets),
        "tweet_count_collected": len(tweets),
        "meta": {
            "followers": profile.get("followers"),
            "following": profile.get("following_count"),
            "statuses": profile.get("statuses"),
            "verified": profile.get("verified"),
            "has_custom_avatar": profile.get("has_custom_avatar"),
            "created_at": profile.get("created_at"),
            "bio_len": len(profile.get("bio") or ""),
        },
        "graph": {
            "follows_known_spam": None,  # 关系边按需再打（要额外请求）
        },
    }


def reply_authors(x: XSession, handle: str, tweets: list[dict], max_posts: int) -> list[str]:
    """种子号帖子下的回复作者 —— 黄推互推的主要发现边。"""
    ranked = sorted(tweets, key=lambda t: (t.get("like_count") or 0), reverse=True)
    found: list[str] = []
    for t in ranked[:max_posts]:
        pid = t.get("post_id")
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
            print(f"      ✗ 回复区 {pid}: {str(exc)[:70]}")
            continue
        for tw in x.timeline_tweets(data):
            author = (tw.get("author") or {}).get("handle")
            if author and author.lower() != handle.lower():
                found.append(author)
    return found


def neighbors(x: XSession, user_id: str, kind: str, limit: int) -> list[str]:
    """粉丝 / 关注。返回 handle 列表。"""
    out: list[str] = []
    cursor = None
    while len(out) < limit:
        try:
            if kind == "followers":
                users = x.followers(user_id, count=100, cursor=cursor)
            else:
                users, cursor = x.following(user_id, count=100, cursor=cursor)
        except Exception as exc:
            print(f"      ✗ {kind}: {str(exc)[:70]}")
            break
        if kind == "followers":
            users, cursor = users
        out.extend(u["handle"] for u in users if u.get("handle"))
        if not cursor or not users:
            break
    return out[:limit]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--max-requests", type=int, default=160)
    ap.add_argument("--per-seed-replies", type=int, default=3)
    ap.add_argument("--neighbors", type=int, default=30, help="每个种子扩多少粉丝/关注")
    ap.add_argument("--add", nargs="*", default=[], help="追加种子 handle")
    args = ap.parse_args()

    seeds = ensure_seeds()
    for h in args.add:
        h = h.strip().lstrip("@")
        if h and h not in seeds:
            seeds.append(h)
            with open(SEEDS, "a", encoding="utf-8") as fh:
                fh.write(h + "\n")
    done = {r["handle"].lower() for r in load_jsonl(DOSSIERS)}
    print(f"▶ 种子 {len(seeds)} 个，已采档案 {len(done)} 份，请求上限 {args.max_requests}")

    x = XSession(min_interval=1.2, max_requests=args.max_requests)
    known_spam: set[str] = set()
    frontier = [h for h in seeds if h.lower() not in done]
    if not frontier:
        frontier = seeds[:]

    for round_index in range(args.rounds):
        if x.requests_made >= args.max_requests:
            print("⛔ 触到请求上限，停止")
            break
        print(f"\n▶ 第 {round_index + 1} 轮：{len(frontier)} 个待采")
        discovered: list[str] = []
        for handle in frontier:
            if x.requests_made >= args.max_requests - 2:
                break
            if handle.lower() in done:
                continue
            print(f"  · @{handle}")
            dossier = build_dossier(x, handle, via=f"round{round_index + 1}", known_spam=known_spam)
            if dossier:
                append_jsonl(DOSSIERS, dossier)
                done.add(handle.lower())
                print(f"    ✓ 档案：推文 {dossier['tweet_count_collected']} 条，"
                      f"外链域名 {dossier['link_hosts'][:3]}，"
                      f"粉丝 {dossier['meta']['followers']} / 关注 {dossier['meta']['following']}")
                if round_index + 1 < args.rounds and x.requests_made < args.max_requests - 10:
                    replies = reply_authors(x, handle, dossier["tweets"], args.per_seed_replies)
                    discovered.extend(replies)
                    print(f"      回复区发现 {len(set(replies))} 个新 handle")
                    nbrs = neighbors(x, dossier["profile"]["rest_id"], "followers", args.neighbors)
                    discovered.extend(nbrs)
                    print(f"      粉丝发现 {len(set(nbrs))} 个 handle")
        fresh = [h for h in dict.fromkeys(discovered) if h.lower() not in done]
        frontier = fresh[:40]
        print(f"  → 下一轮候选 {len(fresh)} 个（本轮取前 {len(frontier)}）")
        if not frontier:
            break

    total = load_jsonl(DOSSIERS)
    print(f"\n✓ 完成：档案 {len(total)} 份，请求 {x.requests_made} 次 → {DOSSIERS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
