#!/usr/bin/env python3
"""x.com 取数客户端 —— 复用本机 Chrome 登录态，走网页版 GraphQL。

为什么不用官方 API：`reslib:api-x-developer` 额度已耗尽（402 credits depleted）。
网页版 GraphQL 用的是用户自己已登录的会话，也就是扩展本身工作在同一条通道上，
所以拿到的样本分布与产品实际看到的分布一致 —— 这正是评测需要的。

响应体字段路径来自上游 `packages/x-adapter/src/api/parse.ts`（2026-09 实测）：
    result.core.screen_name / core.name
    result.profile_bio.description（旧版在 result.legacy.description）
    result.rest_id / result.relationship.following
    tweet: result.legacy.full_text，作者在 result.core.user_results.result

礼貌约束（必须遵守，否则会伤到用户自己的账号）：
  · 请求间隔 >= 1.2s + 抖动
  · 单次运行硬上限 --max-requests（默认 400）
  · 遇 429 指数退避，连续 3 次失败即中止

用法:
    python3 jev/x_client.py selftest          # 验证各端点形状
"""
from __future__ import annotations

import json
import os
import random
import re
import subprocess
import sys
import time
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
FALLBACK_BEARER = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs"
    "%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)

# X 网页版 GraphQL 常见的 feature 开关。缺少 features 时新版端点会 400，
# 所以这里给一份基线集合；具体某个操作是否接受由服务端决定，失败时如实报错。
BASE_FEATURES = {
    "rweb_video_screen_enabled": False,
    "rweb_cashtags_enabled": True,
    "profile_label_improvements_pcf_label_in_post_enabled": True,
    "responsive_web_profile_redirect_enabled": False,
    "rweb_tipjar_consumption_enabled": False,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "premium_content_api_read_enabled": False,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
    "responsive_web_grok_analyze_post_followups_enabled": False,
    "responsive_web_jetfuel_frame": True,
    "responsive_web_grok_share_attachment_enabled": True,
    "responsive_web_grok_annotations_enabled": True,
    "articles_preview_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "responsive_web_grok_show_grok_translated_post": False,
    "responsive_web_grok_analysis_button_from_backend": True,
    "creator_subscriptions_quote_tweet_preview_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "responsive_web_grok_image_annotation_enabled": True,
    "responsive_web_grok_community_note_auto_translation_is_enabled": False,
    "responsive_web_enhance_cards_enabled": False,
}
BASE_FIELD_TOGGLES = {"withArticleRichContentState": True, "withAuxiliaryUserLabels": False}


class XSession:
    """带限速与退避的 x.com 会话。"""

    def __init__(self, min_interval: float = 1.2, max_requests: int = 400,
                 verbose: bool = True) -> None:
        self.cookies = self._load_cookies()
        self.csrf = self.cookies.get("ct0", "")
        self.min_interval = min_interval
        self.max_requests = max_requests
        self.verbose = verbose
        self.requests_made = 0
        self._last_at = 0.0
        self.queries: dict[str, str] = {}
        self.bearer = FALLBACK_BEARER
        self.features = dict(BASE_FEATURES)
        self.field_toggles = dict(BASE_FIELD_TOGGLES)
        self._load_bundle_meta()

    # ---------- 基础设施 ----------

    @staticmethod
    def _load_cookies() -> dict[str, str]:
        proc = subprocess.run(
            [sys.executable, COOKIE_EXTRACTOR, "--host", "x.com", "--json"],
            capture_output=True, text=True, check=True,
        )
        cookies = json.loads(proc.stdout)
        if not cookies.get("auth_token") or not cookies.get("ct0"):
            raise SystemExit("✗ Chrome 里没有 x.com 登录态（auth_token / ct0 缺失）")
        return cookies

    def _throttle(self) -> None:
        if self.requests_made >= self.max_requests:
            raise SystemExit(f"⛔ 触到本次运行请求上限 {self.max_requests}")
        wait = self.min_interval + random.uniform(0, 0.6) - (time.time() - self._last_at)
        if wait > 0:
            time.sleep(wait)
        self._last_at = time.time()
        self.requests_made += 1

    def _raw(self, url: str, cookies: dict[str, str] | None = None,
             headers: dict[str, str] | None = None, timeout: int = 30) -> tuple[int, str]:
        h = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"}
        if cookies:
            h["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())
        h.update(headers or {})
        req = urllib.request.Request(url, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")
        except Exception as exc:
            return -1, f"{type(exc).__name__}: {exc}"

    def _load_bundle_meta(self) -> None:
        """从 x.com 首页的 JS bundle 里现扒 queryId 映射（会随发版变化，不能写死）。"""
        status, html = self._raw("https://x.com/home", self.cookies)
        if status != 200:
            raise SystemExit(f"✗ 打不开 x.com/home（HTTP {status}），登录态可能已失效")
        bundles = sorted(set(re.findall(
            r"https://abs\.twimg\.com/responsive-web/client-web/[^\"']+?\.js", html)))
        for url in bundles:
            st, body = self._raw(url, self.cookies)
            if st != 200:
                continue
            m = re.search(r'"(AAAAAAAAAAAAAAAAAAAAA[^"]{20,})"', body)
            if m and self.bearer == FALLBACK_BEARER:
                self.bearer = m.group(1)
            for qid, name in re.findall(
                r'queryId:\s*"([A-Za-z0-9_-]{10,})"\s*,\s*operationName:\s*"([A-Za-z0-9_]+)"', body
            ):
                self.queries[name] = qid
            for name, qid in re.findall(
                r'operationName:\s*"([A-Za-z0-9_]+)"\s*,\s*queryId:\s*"([A-Za-z0-9_-]{10,})"', body
            ):
                self.queries[name] = qid
        if self.verbose:
            print(f"  · 会话就绪：{len(self.queries)} 个 queryId，"
                  f"auth_token={'有' if self.cookies.get('auth_token') else '无'}")

    def graphql(self, operation: str, variables: dict, features: dict | None = None,
                field_toggles: dict | None = None, retries: int = 2) -> dict:
        if operation not in self.queries:
            raise SystemExit(f"✗ bundle 里没有 {operation} 的 queryId")
        features = self.features if features is None else features
        field_toggles = self.field_toggles if field_toggles is None else field_toggles
        params = {"variables": json.dumps(variables, ensure_ascii=False)}
        if features:
            params["features"] = json.dumps(features, ensure_ascii=False)
        if field_toggles:
            params["fieldToggles"] = json.dumps(field_toggles, ensure_ascii=False)
        url = (f"https://x.com/i/api/graphql/{self.queries[operation]}/{operation}"
               f"?{urllib.parse.urlencode(params)}")
        headers = {
            "Authorization": f"Bearer {self.bearer}",
            "x-csrf-token": self.csrf,
            "x-twitter-auth-type": "OAuth2Session",
            "x-twitter-active-user": "yes",
            "x-twitter-client-language": "zh-cn",
            "Referer": "https://x.com/",
            "Accept": "*/*",
        }
        last_err = ""
        for attempt in range(retries + 1):
            self._throttle()
            status, body = self._raw(url, self.cookies, headers)
            if status == 200:
                try:
                    return json.loads(body)
                except Exception as exc:
                    last_err = f"JSON 解析失败: {exc}; head={body[:200]}"
            else:
                last_err = f"HTTP {status}: {body[:220]}"
                if status == 429:
                    backoff = 15 * (attempt + 1)
                    if self.verbose:
                        print(f"    ⏳ 429，退避 {backoff}s")
                    time.sleep(backoff)
                    continue
            if attempt < retries:
                time.sleep(3 * (attempt + 1))
        raise RuntimeError(f"{operation} 失败：{last_err}")

    # ---------- 归一化：把 2026-09 的新旧两种形状都拍平 ----------

    @staticmethod
    def _norm_user(result: dict) -> dict:
        """把 2026-09 的新形状与旧 legacy 形状统一拍平（新形状优先）。

        新形状（实测 2026-09）：relationship_counts / tweet_counts / verification /
        profile_bio / avatar / privacy，legacy 已不再下发。
        """
        if not result:
            return {}
        legacy = result.get("legacy") or {}
        core = result.get("core") or {}
        bio_block = result.get("profile_bio") or {}
        rel = result.get("relationship") or {}
        counts = result.get("relationship_counts") or {}
        tweets = result.get("tweet_counts") or {}
        verif = result.get("verification") or {}
        privacy = result.get("privacy") or {}
        avatar = (result.get("avatar") or {}).get("image_url") or ""
        website = ((result.get("website") or {}).get("url")) or ""
        bio_urls = (((bio_block.get("entities") or {}).get("url") or {}).get("urls")) or []
        return {
            "rest_id": result.get("rest_id"),
            "handle": core.get("screen_name") or legacy.get("screen_name"),
            "name": core.get("name") or legacy.get("name"),
            "bio": bio_block.get("description") or legacy.get("description") or "",
            "location": (result.get("location") or {}).get("location")
                        or legacy.get("location") or "",
            "followers": counts.get("followers", legacy.get("followers_count")),
            "following_count": counts.get("following", legacy.get("friends_count")),
            "statuses": tweets.get("tweets", legacy.get("statuses_count")),
            "created_at": core.get("created_at") or legacy.get("created_at"),
            "verified": bool(verif.get("verified") or result.get("is_blue_verified")
                             or legacy.get("verified")),
            "protected": bool(privacy.get("protected") or legacy.get("protected")),
            "has_custom_avatar": "default_profile_images" not in avatar,
            "avatar_url": avatar,
            "following_me": rel.get("following"),
            "url": website or (bio_urls[0].get("expanded_url") if bio_urls else None),
        }

    @staticmethod
    def _norm_tweet(result: dict) -> dict | None:
        if not result:
            return None
        if (result.get("legacy") or {}).get("retweeted_status_result"):
            return None  # 转推不是作者本人发言，评测里剔除以免污染
        legacy = result.get("legacy") or {}
        user = ((result.get("core") or {}).get("user_results") or {}).get("result") or {}
        author = XSession._norm_user(user)
        note = (((result.get("note_tweet") or {}).get("note_tweet_results") or {})
                .get("result") or {})
        text = note.get("text") or legacy.get("full_text") or ""
        urls = []
        for u in ((legacy.get("entities") or {}).get("urls") or []):
            urls.append({"expanded": u.get("expanded_url"),
                         "display": u.get("display_url"),
                         "host": _hostname(u.get("expanded_url"))})
        for u in ((legacy.get("entities") or {}).get("media") or []):
            pass
        return {
            "post_id": result.get("rest_id"),
            "text": text,
            "lang": legacy.get("lang"),
            "created_at": legacy.get("created_at"),
            "like_count": legacy.get("favorite_count"),
            "reply_count": legacy.get("reply_count"),
            "retweet_count": legacy.get("retweet_count"),
            "has_media": bool((legacy.get("entities") or {}).get("media")),
            "urls": urls,
            "author": author,
        }

    # ---------- 端点 ----------

    def user_by_screen_name(self, handle: str) -> dict:
        data = self.graphql("UserByScreenName", {
            "screen_name": handle.lstrip("@"),
            "withSafetyModeUserFields": True,
        }, features=BASE_FEATURES, field_toggles=BASE_FIELD_TOGGLES)
        result = ((data.get("data") or {}).get("user") or {}).get("result") or {}
        return self._norm_user(result)

    def search(self, query: str, product: str = "Latest", count: int = 20) -> list[dict]:
        data = self.graphql("SearchTimeline", {
            "rawQuery": query, "count": count,
            "querySource": "typed_query", "product": product,
        }, features=BASE_FEATURES, field_toggles=BASE_FIELD_TOGGLES)
        return self.timeline_tweets(data)

    def following(self, user_id: str, count: int = 100,
                  cursor: str | None = None) -> tuple[list[dict], str | None]:
        return self._user_list("Following", user_id, count, cursor)

    def followers(self, user_id: str, count: int = 100,
                  cursor: str | None = None) -> tuple[list[dict], str | None]:
        return self._user_list("Followers", user_id, count, cursor)

    def _user_list(self, operation: str, user_id: str, count: int,
                   cursor: str | None) -> tuple[list[dict], str | None]:
        variables = {"userId": user_id, "count": count, "includePromotedContent": False}
        if cursor:
            variables["cursor"] = cursor
        data = self.graphql(operation, variables)
        out: list[dict] = []
        next_cursor = None
        try:
            instructions = (data["data"]["user"]["result"]["timeline"]["timeline"]
                            ["instructions"])
        except Exception:
            return out, None
        for ins in instructions:
            for entry in ins.get("entries") or []:
                content = entry.get("content") or {}
                if content.get("entryType") == "TimelineTimelineCursor":
                    if content.get("cursorType") == "Bottom":
                        next_cursor = content.get("value")
                    continue
                item = content.get("itemContent") or {}
                result = ((item.get("user_results") or {}).get("result")) or {}
                user = self._norm_user(result)
                if user.get("handle"):
                    out.append(user)
        return out, next_cursor

    def user_tweets(self, user_id: str, count: int = 20) -> list[dict]:
        data = self.graphql("UserTweets", {
            "userId": user_id, "count": count,
            "includePromotedContent": False, "withQuickPromoteEligibilityTweetFields": False,
            "withVoice": False, "withV2Timeline": True,
        }, features=BASE_FEATURES, field_toggles=BASE_FIELD_TOGGLES)
        return self.timeline_tweets(data)

    def timeline_tweets(self, data: dict) -> list[dict]:
        """公开入口：从任意 GraphQL 响应里递归捞出推文（抗形状变化）。"""
        return self._timeline_tweets(data, "timeline")

    def _timeline_tweets(self, data: dict, root: str) -> list[dict]:
        """时间线响应是深层嵌套的 instructions；用递归找 tweet_results 更抗形状变化。"""
        out: list[dict] = []
        seen: set[str] = set()

        def walk(node) -> None:
            if isinstance(node, dict):
                tr = node.get("tweet_results")
                if isinstance(tr, dict):
                    tweet = self._norm_tweet(tr.get("result") or {})
                    if tweet and tweet.get("post_id") and tweet["post_id"] not in seen:
                        seen.add(tweet["post_id"])
                        out.append(tweet)
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(data)
        return out


def _hostname(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return urllib.parse.urlparse(url).hostname
    except Exception:
        return None


def selftest() -> int:
    os.makedirs(CACHE, exist_ok=True)
    print("▶ X 取数自检")
    x = XSession(max_requests=12)
    report: dict = {"queries_available": len(x.queries)}

    print("\n1) UserByScreenName")
    try:
        u = x.user_by_screen_name("realchendahuang")
        print(f"   handle={u.get('handle')} name={u.get('name')!r} "
              f"followers={u.get('followers')} bio={ (u.get('bio') or '')[:60]!r}")
        report["user"] = u
    except Exception as exc:
        print(f"   ✗ {exc}")
        report["user_error"] = str(exc)

    print("\n2) SearchTimeline（用真实词库短语找黄推）")
    for q in ["福利在主页", "我福不黑"]:
        try:
            tweets = x.search(q, count=20)
            authors = {t["author"].get("handle") for t in tweets if t.get("author")}
            print(f"   「{q}」→ {len(tweets)} 条推文 / {len(authors)} 个作者")
            for t in tweets[:3]:
                print(f"      @{t['author'].get('handle')} | {t['text'][:70]!r}")
            report.setdefault("search", {})[q] = len(tweets)
        except Exception as exc:
            print(f"   ✗ 「{q}」{exc}")
            report.setdefault("search_error", {})[q] = str(exc)

    print("\n3) Following（阴性样本来源）")
    try:
        me = x.user_by_screen_name(os.environ.get("JEV_SELF_HANDLE", "x"))
        print(f"   自己: rest_id={me.get('rest_id')} handle={me.get('handle')}")
        if me.get("rest_id"):
            users, cursor = x.following(me["rest_id"], count=20)
            print(f"   关注列表前 {len(users)} 个: "
                  f"{[u.get('handle') for u in users[:6]]} cursor={'有' if cursor else '无'}")
            report["following_sample"] = len(users)
    except Exception as exc:
        print(f"   ✗ {exc}")
        report["following_error"] = str(exc)

    with open(os.path.join(CACHE, "selftest.json"), "w") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    print(f"\n请求数: {x.requests_made}；产出 {CACHE}/selftest.json")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        raise SystemExit(selftest())
    print(__doc__)
