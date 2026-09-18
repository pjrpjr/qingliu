#!/usr/bin/env python3
"""取数通路探针：确认哪条路能拿到真实 X 数据。

两条候选通路：
  A. x.com GraphQL（复用本机 Chrome 登录态）—— 能搜、能读关注列表，但需要
     从页面 JS 里现扒 queryId 与 features
  B. cdn.syndication.twimg.com（免登录）—— 简单，但只能按已知 handle 取

用法: python3 jev/x_probe.py
产出: jev/.cache/probe.json（gitignore 覆盖）
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".cache")
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)
COOKIE_EXTRACTOR = os.path.expanduser(
    "~/naslib/tools/dydiffusion/extract_chrome_cookies.py"
)
# X 网页版的公开 bearer（长期不变，JS 里也能扒到；作为兜底）
FALLBACK_BEARER = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs"
    "%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)


def load_cookies(host: str = "x.com") -> dict[str, str]:
    """复用已验证的 Chrome cookie 提取器（macOS Keychain + v10 域绑定已处理）。"""
    proc = subprocess.run(
        [sys.executable, COOKIE_EXTRACTOR, "--host", host, "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout)


def cookie_header(cookies: dict[str, str]) -> str:
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


def fetch(url: str, cookies: dict[str, str] | None = None,
          headers: dict[str, str] | None = None, timeout: int = 30) -> tuple[int, str]:
    h = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"}
    if cookies:
        h["Cookie"] = cookie_header(cookies)
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except Exception as exc:  # 网络层失败也要如实返回，不能静默
        return -1, f"{type(exc).__name__}: {exc}"


def harvest_bearer_and_queries(html_or_js: str) -> tuple[str | None, dict[str, str]]:
    """从 X 的 JS bundle 里扒 bearer 与 queryId 映射。

    bundle 里的形状是 {queryId:"<id>",operationName:"<Name>",...}（顺序可能反）。
    """
    bearer = None
    m = re.search(r'"(AAAAAAAAAAAAAAAAAAAAA[^"]{20,})"', html_or_js)
    if m:
        bearer = m.group(1)
    queries: dict[str, str] = {}
    for a, b in re.findall(
        r'queryId:\s*"([A-Za-z0-9_-]{10,})"\s*,\s*operationName:\s*"([A-Za-z0-9_]+)"',
        html_or_js,
    ):
        queries[b] = a
    for b, a in re.findall(
        r'operationName:\s*"([A-Za-z0-9_]+)"\s*,\s*queryId:\s*"([A-Za-z0-9_-]{10,})"',
        html_or_js,
    ):
        queries[b] = a
    return bearer, queries


def probe_graphql(cookies: dict[str, str]) -> dict:
    result: dict = {"ok": False, "steps": []}
    status, html = fetch("https://x.com/home", cookies)
    result["steps"].append({"step": "home", "status": status, "len": len(html)})
    if status != 200:
        result["error"] = html[:400]
        return result
    bundles = sorted(set(re.findall(r"https://abs\.twimg\.com/responsive-web/client-web/[^\"']+?\.js", html)))
    result["steps"].append({"step": "bundles", "count": len(bundles)})
    bearer = None
    queries: dict[str, str] = {}
    js = ""
    for url in bundles:
        st, body = fetch(url, cookies)
        if st != 200:
            continue
        b, q = harvest_bearer_and_queries(body)
        bearer = bearer or b
        queries.update(q)
        js += body
        if len(queries) > 50:
            break
    result["bearer_found"] = bool(bearer)
    result["query_count"] = len(queries)
    result["queries_sample"] = {k: queries[k] for k in sorted(queries)[:25]}
    csrf = cookies.get("ct0", "")
    if not bearer or "UserByScreenName" not in queries:
        result["error"] = "没扒到 bearer 或 UserByScreenName queryId"
        return result
    headers = {
        "Authorization": f"Bearer {bearer}",
        "x-csrf-token": csrf,
        "x-twitter-auth-type": "OAuth2Session",
        "x-twitter-active-user": "yes",
        "x-twitter-client-language": "zh-cn",
        "Content-Type": "application/json",
        "Referer": "https://x.com/",
    }
    variables = {"screen_name": "realchendahuang", "withSafetyModeUserFields": True}
    url = (
        "https://x.com/i/api/graphql/"
        f"{queries['UserByScreenName']}/UserByScreenName"
        f"?variables={urllib.parse.quote(json.dumps(variables))}"
    )
    st, body = fetch(url, cookies, headers)
    result["steps"].append({"step": "UserByScreenName", "status": st, "len": len(body)})
    if st == 200:
        result["ok"] = True
        try:
            data = json.loads(body)
            u = data["data"]["user"]["result"]
            result["sample_user"] = {
                "rest_id": u.get("rest_id"),
                "name": u.get("legacy", {}).get("name"),
                "description": (u.get("legacy", {}).get("description") or "")[:120],
            }
        except Exception as exc:
            result["parse_error"] = f"{type(exc).__name__}: {exc}"
            result["raw_head"] = body[:300]
    else:
        result["error_head"] = body[:300]
    return result


def probe_syndication(cookies: dict[str, str]) -> dict:
    out: dict = {"ok": False, "steps": []}
    url = "https://syndication.twitter.com/srv/timeline-profile/screen-name/realchendahuang"
    st, body = fetch(url, cookies)
    out["steps"].append({"step": "timeline-profile", "status": st, "len": len(body)})
    if st == 200 and "__NEXT_DATA__" in body:
        out["ok"] = True
        try:
            m = re.search(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', body, re.S)
            data = json.loads(m.group(1))
            out["props_keys"] = list(data.get("props", {}).get("pageProps", {}).keys())
        except Exception as exc:
            out["parse_error"] = f"{type(exc).__name__}: {exc}"
    else:
        out["error_head"] = body[:200]
    return out


def main() -> int:
    os.makedirs(CACHE, exist_ok=True)
    cookies = load_cookies()
    print(f"✓ 取到 {len(cookies)} 个 x.com cookie；"
          f"auth_token={'有' if cookies.get('auth_token') else '无'} "
          f"ct0={'有' if cookies.get('ct0') else '无'}")
    print("\n▶ 通路 A：x.com GraphQL")
    g = probe_graphql(cookies)
    print(f"  ok={g['ok']} bearer={g.get('bearer_found')} queryIds={g.get('query_count')}")
    for s in g["steps"]:
        print(f"    {s}")
    if g.get("sample_user"):
        print(f"  样本用户: {g['sample_user']}")
    if g.get("error"):
        print(f"  ✗ {g['error']}")
    if g.get("error_head"):
        print(f"  ✗ head: {g['error_head'][:200]}")
    print("\n▶ 通路 B：syndication（免登录）")
    s = probe_syndication(cookies)
    print(f"  ok={s['ok']}")
    for st in s["steps"]:
        print(f"    {st}")
    if s.get("error_head"):
        print(f"  ✗ head: {s['error_head'][:160]}")
    with open(os.path.join(CACHE, "probe.json"), "w") as fh:
        json.dump({"graphql": g, "syndication": s}, fh, ensure_ascii=False, indent=1)
    print(f"\n产出: {CACHE}/probe.json")
    return 0 if (g["ok"] or s["ok"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
