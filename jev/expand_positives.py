#!/usr/bin/env python3
"""把公开名单**全量**过一遍 —— 随机抽样撞上 84% 的死亡率，只能全量捞活号。

发现（2026-09-19 实测）：`daymade/Twitter-Block-Porn` 随机抽 80 个 handle，
**54 个已注销/不可见**。名单是旧的，垃圾号的寿命比名单更新周期短 —— 这本身
就是"为什么要一个能现判的 AI 层"的最硬论据：名单会腐坏，语义判断不会。

所以阳性集改成：全量 882 条 → 只留**今天还活着且有内容**的账号。
标签仍然来自第三方人工整理（不由本项目自标），只是加了一条"必须仍可判定"的门槛。

用法:
    python3 jev/expand_positives.py --max-requests 1000
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from x_client import XSession  # noqa: E402
from build_dataset import BLOCKLIST_LOCAL, DATA, load_jsonl, write_jsonl  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-requests", type=int, default=1000)
    ap.add_argument("--min-interval", type=float, default=1.2)
    ap.add_argument("--max-tweets", type=int, default=12)
    ap.add_argument("--no-tweets", action="store_true", help="只补主页，不取推文")
    args = ap.parse_args()

    entries = json.load(open(BLOCKLIST_LOCAL, encoding="utf-8"))
    handles = sorted({(e.get("screen_name") or "").strip().lstrip("@")
                      for e in entries if e.get("screen_name")})
    # 名单大致按注册时间排，顺着跑会系统性偏向更老的号（死得更多）。
    # 用固定种子打乱：中途停下时已采部分仍是随机样本，可复现。
    import random
    random.Random(20260919).shuffle(handles)
    pos_path = os.path.join(DATA, "positives.jsonl")
    rows = load_jsonl(pos_path)
    known = {r["handle"].lower() for r in rows}
    # 已经确认死掉的不用再试
    todo = [h for h in handles if h.lower() not in known]
    print(f"▶ 名单 {len(handles)} 条；已处理 {len(known)}；本轮 {len(todo)} 个待查")

    x = XSession(min_interval=args.min_interval, max_requests=args.max_requests)
    live = 0
    for i, handle in enumerate(todo, 1):
        if x.requests_made >= x.max_requests - 3:
            print("  ⛔ 触到请求上限，剩余下次继续")
            break
        try:
            profile = x.user_by_screen_name(handle)
        except Exception as exc:
            print(f"  [{i}/{len(todo)}] ✗ @{handle} {str(exc)[:60]}")
            continue
        if not profile.get("rest_id"):
            rows.append({"handle": handle, "side": "positive", "dead": True})
            write_jsonl(pos_path, rows)
            continue
        tweets: list[dict] = []
        has_content = bool((profile.get("bio") or "").strip())
        if not args.no_tweets and (has_content or (profile.get("statuses") or 0) > 0):
            try:
                tweets = [t for t in x.user_tweets(profile["rest_id"], count=args.max_tweets)
                          if (t.get("author") or {}).get("handle", "").lower() == handle.lower()]
            except Exception as exc:
                print(f"    ! @{handle} 推文失败 {str(exc)[:50]}")
        hosts = sorted({u["host"] for t in tweets for u in (t.get("urls") or [])
                        if u.get("host") and u["host"] not in ("x.com", "twitter.com", "t.co")})
        rows.append({
            "handle": handle, "side": "positive",
            "profile": profile,
            "tweets": [{"text": t.get("text"), "urls": t.get("urls"),
                        "has_media": t.get("has_media"), "created_at": t.get("created_at"),
                        "like_count": t.get("like_count")} for t in tweets],
            "link_hosts": hosts,
            "meta": {"followers": profile.get("followers"),
                     "following": profile.get("following_count"),
                     "statuses": profile.get("statuses"),
                     "verified": profile.get("verified"),
                     "has_custom_avatar": profile.get("has_custom_avatar"),
                     "created_at": profile.get("created_at")},
        })
        write_jsonl(pos_path, rows)
        judgeable = has_content or bool(tweets)
        if judgeable:
            live += 1
            if live % 5 == 0 or live < 6:
                print(f"  [{i}/{len(todo)}] ✓ 活号 #{live} @{handle[:20]:20} "
                      f"推文 {len(tweets):>2} 粉丝 {str(profile.get('followers')):>7} "
                      f"| bio={(profile.get('bio') or '')[:36]!r}")

    usable = [r for r in rows if not r.get("dead")
              and ((r.get("profile") or {}).get("bio") or "").strip() or r.get("tweets")]
    print(f"\n✓ 全量扫描：档案 {len(rows)} 份，其中可判定 {len(usable)} 个"
          f"（死号 {sum(1 for r in rows if r.get('dead'))}）；请求 {x.requests_made} 次")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
