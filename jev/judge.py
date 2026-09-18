#!/usr/bin/env python3
"""用 Jev 判定账号档案 —— 预注册见 `jev/PREREGISTRATION.md`。

三种跑法（对应 H1 / H2 / H3）：
  normal  batch=1    单账号单次调用（基线）
  normal  batch=10   10 个账号塞进一次调用（扇出；H2 要比较的正是这个）
  anon    batch=*    handle 换成同长度随机串（H3 记忆污染探针）

判定输入只包含扩展在时间线上真能拿到的字段（见预注册第三节）。
词库命中只在本地算，**不喂给 Jev** —— 那是 H4 要单独考察的对照。

用法:
    python3 jev/judge.py --mode normal --batch 1
    python3 jev/judge.py --mode normal --batch 10
    python3 jev/judge.py --mode anon   --batch 10
"""
from __future__ import annotations

import argparse
import json
import os
import random
import string
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from jev_client import Jev  # noqa: E402
import keywords  # noqa: E402

DATA = os.path.join(HERE, "data")
JUDGMENTS = os.path.join(DATA, "jev_judgments.jsonl")
KEYWORD_PACK = os.path.join(os.path.dirname(HERE), "community", "keyword-packs", "official.json")
ANON_SEED = 20260919
MAX_TWEETS = 8
TWEET_CHARS = 160


def load_jsonl(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def load_rules() -> list[dict]:
    """词库规则（产品真实语义，见 jev/keywords.py）。"""
    return keywords.load_rules(KEYWORD_PACK)


def account_text(row: dict) -> str:
    profile = row.get("profile") or {}
    parts = [profile.get("name") or "", profile.get("bio") or ""]
    parts += [t.get("text") or "" for t in row.get("tweets") or []]
    return " ".join(parts)


def keyword_hits(row: dict, rules: list[dict]) -> list[str]:
    """命中的词库规则 ID（用产品同款 NFKC + 去标点语义）。"""
    return [r["id"] for r in keywords.matches(account_text(row), rules)]


def has_evidence(row: dict) -> bool:
    """档案里必须有可判的**内容**（简介或推文）。

    只有昵称不构成证据：空壳号（0 粉丝 / 0 推文 / 空简介）在时间线上也判不了，
    放进评测只会人为拉低召回，属于自己给自己下绊子。这类账号单独统计。
    """
    profile = row.get("profile") or {}
    return bool((profile.get("bio") or "").strip()) or bool(row.get("tweets"))


def anonymize(handle: str, rng: random.Random) -> str:
    """同长度、同字符集替换（保留下划线/数字的形态特征，只抹掉身份）。"""
    out = []
    for ch in handle:
        if ch == "_":
            out.append("_")
        elif ch.isdigit():
            out.append(rng.choice(string.digits))
        elif ch.isalpha():
            out.append(rng.choice(string.ascii_lowercase))
        else:
            out.append(ch)
    return "".join(out)


def format_created(value) -> str:
    """X 的注册时间是 "Wed Apr 10 16:56:00 +0000 2024" —— 归一成 YYYY-MM 才有人看得懂。"""
    if not value:
        return "未知"
    text = str(value)
    try:
        from datetime import datetime
        return datetime.strptime(text, "%a %b %d %H:%M:%S %z %Y").strftime("%Y-%m")
    except Exception:
        return text[:19]


def build_state(rows: list[dict], anon: bool, rng: random.Random,
                max_tweets: int | None = None) -> tuple[str, list[str]]:
    """把一批账号拼成一个 state；返回 (state, 本批 handle 顺序)。

    max_tweets 用来对齐**线上口径**：时间线一次只渲染一条推文，所以扩展实际能
    送进 Jev 的 state 比离线档案弱。阈值必须在弱 state 上重新标定，不能拿
    8 条推文的成绩直接用（`--max-tweets 1 --tag online`）。
    """
    limit = MAX_TWEETS if max_tweets is None else max_tweets
    blocks, handles = [], []
    for index, row in enumerate(rows, 1):
        profile = row.get("profile") or {}
        handle = row["handle"]
        shown = anonymize(handle, rng) if anon else handle
        handles.append(handle)
        meta = row.get("meta") or {}
        tweets = (row.get("tweets") or [])[:limit]
        lines = [
            f"账号档案 #{index}",
            f"handle: @{shown}",
            f"昵称: {profile.get('name') or '（无）'}",
            f"简介: {(profile.get('bio') or '（空）')[:400]}",
            (f"粉丝 {meta.get('followers')} / 关注 {meta.get('following')} / "
             f"推文 {meta.get('statuses')} / 注册 {format_created(meta.get('created_at'))} / "
             f"{'自定义头像' if meta.get('has_custom_avatar') else '默认头像'}"
             f"{' / 蓝标' if meta.get('verified') else ''}"),
        ]
        hosts = row.get("link_hosts") or []
        if hosts:
            lines.append(f"外链域名: {', '.join(hosts[:8])}")
        if tweets:
            lines.append("近期推文:")
            for i, t in enumerate(tweets, 1):
                text = (t.get("text") or "").replace("\n", " ")[:TWEET_CHARS]
                lines.append(f"  {i}. {text}")
        else:
            lines.append("近期推文: （无）")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks), handles


def questions_for(batch_len: int) -> tuple[dict, list[tuple[str, str]]]:
    """生成问题字典 + 返回 [(handle_index, question_prefix)] 映射。"""
    questions: dict = {}
    mapping: list[tuple[int, str]] = []
    for i in range(1, batch_len + 1):
        prefix = f"a{i}_" if batch_len > 1 else ""
        ref = f"账号档案 #{i}" if batch_len > 1 else "这个账号档案"
        questions[f"{prefix}spam"] = {
            "type": "noul",
            "instructions": (
                f"{ref} 是不是垃圾号？垃圾号指：色情/成人内容或福利资源引流、"
                "诈骗钓鱼（假空投/假客服/假投资）、机器人刷屏或批量复读、"
                "互动钓鱼（求互关/求涨粉/抽奖骗互动）。"
                "真人正常分享生活、正常讨论、正规商家与创作者都不算垃圾号，"
                "即使内容里有广告或情绪化表达也不算。"
            ),
            "criteria": {"true": "有明确证据表明这是垃圾号",
                         "false": "证据不足，或只是普通用户/正规账号"},
        }
        questions[f"{prefix}category"] = {
            "type": "choice",
            "instructions": f"{ref} 属于哪一类？没有垃圾证据就选 legit_person 或 legit_brand。",
            "criteria": {
                "adult_gray_traffic": "色情/成人内容、福利资源或成人网站引流",
                "scam_phishing": "诈骗、钓鱼、假空投、假客服、假投资",
                "bot_spam": "机器人刷屏、批量复读、无意义灌水",
                "engagement_bait": "互动钓鱼：求互关/求涨粉/抽奖/求点赞",
                "legit_person": "真人正常使用账号",
                "legit_brand": "机构、商家或正规创作者账号",
            },
        }
        questions[f"{prefix}evidence"] = {
            "type": "choice",
            "instructions": f"判断 {ref} 时，最主要的依据来自哪里？",
            "criteria": {
                "bio": "简介里的表述",
                "tweet_text": "推文正文的表述",
                "links": "外链域名",
                "handle_name": "handle 或昵称的形态",
                "behavior": "账号行为数据（粉丝/关注/推文数的比例）",
                "none": "没有明显证据",
            },
        }
        mapping.append((i, prefix))
    return questions, mapping


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["normal", "anon"], default="normal")
    ap.add_argument("--batch", type=int, default=10)
    ap.add_argument("--limit", type=int, default=0, help="每个侧最多判多少个（0=全部）")
    ap.add_argument("--dry-run", action="store_true", help="只打印 state 与问题，不调用 API")
    ap.add_argument("--max-tweets", type=int, default=0,
                    help="每个账号最多用几条推文（0=用评测档位；1=对齐线上口径）")
    ap.add_argument("--tag", default="full", help="state 口径标签，用于区分不同跑法")
    args = ap.parse_args()

    rows: list[dict] = []
    # tier 是标签强度的分级，必须一路带到评测里：
    #   list     第三方人工整理的公开名单（独立标签，主集）
    #   network  黄推帖子回复区捞到的账号（弱一档，报告里单列）
    #   following 用户自己的关注列表（阴性）
    for side, path, tier in (
        ("positive", os.path.join(DATA, "positives.jsonl"), "list"),
        ("positive", os.path.join(DATA, "network_positives.jsonl"), "network"),
        ("negative", os.path.join(DATA, "negatives.jsonl"), "following"),
    ):
        side_rows = [r for r in load_jsonl(path) if not r.get("dead") and has_evidence(r)]
        if args.limit:
            side_rows = side_rows[:args.limit]
        for r in side_rows:
            r["side"] = side
            r.setdefault("tier", tier)
        rows.extend(side_rows)
    if not rows:
        sys.exit("✗ 没有可用档案：先跑 build_dataset.py")

    rules = load_rules()
    for r in rows:
        r["_kw"] = keyword_hits(r, rules)
    kw_pos = sum(1 for r in rows if r["side"] == "positive" and r["_kw"])
    print(f"▶ 待判 {len(rows)} 个账号（阳 {sum(1 for r in rows if r['side'] == 'positive')} / "
          f"阴 {sum(1 for r in rows if r['side'] == 'negative')}）；"
          f"其中词库命中的阳性 {kw_pos} 个（H4 要看的是**没命中**的那些）")
    print(f"  模式={args.mode} batch={args.batch} state口径={args.tag}"
          f"（推文上限 {args.max_tweets or MAX_TWEETS}）词库规则 {len(rules)} 条")

    done = {(r["handle"].lower(), r["mode"], r["batch_size"], r.get("state_tag") or "full")
            for r in load_jsonl(JUDGMENTS)}
    todo = [r for r in rows
            if (r["handle"].lower(), args.mode, args.batch, args.tag) not in done]
    print(f"  已完成 {len(done)} 条判定，本轮待判 {len(todo)} 个账号")

    rng = random.Random(ANON_SEED)
    if args.dry_run:
        state, handles = build_state(rows[:args.batch], args.mode == "anon", rng,
                                     args.max_tweets or None)
        questions, _ = questions_for(min(args.batch, len(rows)))
        print("\n=== state 样例 ===\n" + state[:1600])
        print(f"\n=== 问题（{len(questions)} 个）===")
        for name, spec in list(questions.items())[:3]:
            print(f"  {name}: {spec['type']} :: {spec['instructions'][:80]}...")
        return 0

    jev = Jev()
    batches = [todo[i:i + args.batch] for i in range(0, len(todo), args.batch)]
    print(f"  拆成 {len(batches)} 次调用\n")
    for bi, batch in enumerate(batches, 1):
        state, handles = build_state(batch, args.mode == "anon", rng,
                                     args.max_tweets or None)
        questions, mapping = questions_for(len(batch))
        started = time.perf_counter()
        result = jev.ask(state, questions)
        if result is None:
            print(f"  [{bi}/{len(batches)}] ✗ 调用失败，跳过")
            continue
        answers = result["answers"]
        rows_out = []
        for row, (index, prefix) in zip(batch, mapping):
            spam = (answers.get(f"{prefix}spam") or {}).get("noul")
            category = (answers.get(f"{prefix}category") or {}).get("choice")
            evidence = (answers.get(f"{prefix}evidence") or {}).get("choice")
            rows_out.append({
                "handle": row["handle"],
                "side": row["side"],
                "tier": row.get("tier"),
                "mode": args.mode,
                "batch_size": args.batch,
                "state_tag": args.tag,
                "spam": spam,
                "category": category,
                "evidence": evidence,
                "keyword_hits": row["_kw"],
                "n_tweets": len(row.get("tweets") or []),
                "followers": (row.get("meta") or {}).get("followers"),
                "following": (row.get("meta") or {}).get("following"),
                "input_tokens": result["input_tokens"],
                "latency": result["latency"],
                "answers_raw": answers if len(batch) == 1 else None,
            })
        with open(JUDGMENTS, "a", encoding="utf-8") as fh:
            for r in rows_out:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        flags = " ".join(f"{(r['spam'] if r['spam'] is not None else -1):.2f}" for r in rows_out)
        print(f"  [{bi}/{len(batches)}] {len(batch):>2} 个账号 "
              f"{result['input_tokens']:>5} tok {result['latency']:.2f}s  spam: {flags}")
        _ = started

    print(f"\n✓ 判定完成：{jev.calls} 次调用 / {jev.input_tokens} 输入 token / "
          f"${jev.cost_usd:.5f} / p50 延迟 "
          f"{sorted(jev.latencies)[len(jev.latencies) // 2]:.2f}s" if jev.latencies else "✓ 无调用")
    print(f"  → {JUDGMENTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
