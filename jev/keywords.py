#!/usr/bin/env python3
"""关键词层的**产品真实匹配语义**（Python 镜像）。

镜像对象：`apps/extension/src/lib/keyword-rules.ts` 的 `textForMatch` /
`orderedTermsMatch` / `ruleMatchesText`。为什么要逐字镜像而不是自己写个 `in`：

  产品会先做 NFKC 归一化，并**剥掉全部标点、符号、空白**再匹配 —— 这是为了抓
  「同·城 上-门」「福 利」这类规避写法。自己写朴素的子串包含会：
    · 漏掉规避写法（低估词库）；
    · 或者把单个词素当规则（像先前那样把"做爱""鸡巴"当命中，**高估词库**）。
  两种偏差都会让 H4「词库未命中子集」失去意义。
"""
from __future__ import annotations

import json
import re
import unicodedata

# TS 的 /[\p{P}\p{S}\s]+/gu：Unicode 标点 + 符号 + 空白
_STRIP = re.compile(r"[\s\W_]+", re.UNICODE)
_ZERO_WIDTH = re.compile(r"[\u200b-\u200d\ufeff]")


def normalize(value: str) -> str:
    return _ZERO_WIDTH.sub("", unicodedata.normalize("NFKC", value.strip())).lower()


def text_for_match(value: str) -> str:
    """NFKC + 小写 + 去掉标点/符号/空白（与产品一致）。"""
    normalized = normalize(value)
    return "".join(ch for ch in normalized
                   if not (unicodedata.category(ch).startswith(("P", "S")) or ch.isspace()))


def ordered_terms_match(value: str, terms: list[str], max_gap: int = 12) -> bool:
    haystack = text_for_match(value)
    cursor = 0
    for term in terms:
        needle = text_for_match(term)
        if not needle:
            continue
        index = haystack.find(needle, cursor)
        if index < 0:
            return False
        if cursor > 0 and index - cursor > max_gap:
            return False
        cursor = index + len(needle)
    return True


def rule_matches(value: str, rule: dict) -> bool:
    terms = rule.get("terms")
    if terms:
        return ordered_terms_match(value, terms, int(rule.get("maxGap") or 12))
    phrase = rule.get("phrase")
    if not isinstance(phrase, str) or not phrase:
        return False
    return text_for_match(phrase) in text_for_match(value)


def load_rules(pack_path: str) -> list[dict]:
    """把词库摊平成 [{id, category, phrase, terms, maxGap}]。"""
    catalog = json.load(open(pack_path, encoding="utf-8"))
    out: list[dict] = []
    for pack in catalog.get("packs", []):
        for rule in pack.get("rules", []):
            if not isinstance(rule, dict):
                continue
            out.append({
                "id": rule.get("id"),
                "category": pack.get("id"),
                "phrase": rule.get("phrase"),
                "terms": rule.get("terms"),
                "maxGap": rule.get("maxGap"),
            })
    return out


def matches(value: str, rules: list[dict]) -> list[dict]:
    """返回命中的规则（带 category），供 H4 分子集用。"""
    return [r for r in rules if rule_matches(value, r)]
