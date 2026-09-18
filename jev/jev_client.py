#!/usr/bin/env python3
"""Jev API 客户端 —— 与 jev 套利项目（`~/naslib/jev套利（dsh)/experiments/`）同一套调用约定。

事实（实测自 jev 套利项目，不重复踩坑）：
  · POST https://api.typesafe.ai/v1/systemone ，model=jev-latest
  · 走本机代理 127.0.0.1:7897（CONNECT 隧道），冷连接 ~0.5s，测延迟必须复用连接
  · 凭证只从 `reslib get api-typesafe-jev api_key` 取，不落盘、不打印
  · 响应：{"answers": {"<qname>": {"type":"noul","noul":0.37} | {"choice":"..."} ...},
           "usage": {"input_tokens": N}}
  · 单价 $0.042 / Mtok 输入，输出免费
  · 一次可扇出多个问题（1→20 问延迟只涨 3–11%）
"""
from __future__ import annotations

import http.client
import json
import subprocess
import sys
import time

PROXY_HOST = "127.0.0.1"
PROXY_PORT = 7897
API_HOST = "api.typesafe.ai"
MODEL = "jev-latest"
PRICE_PER_MTOK = 0.042  # 输入 token 单价（美元）


class Jev:
    def __init__(self, timeout: int = 120) -> None:
        proc = subprocess.run(["reslib", "get", "api-typesafe-jev", "api_key"],
                              capture_output=True, text=True)
        self.key = proc.stdout.strip()
        if not self.key:
            sys.exit("✗ reslib 取不到 api-typesafe-jev 的 api_key（先 reslib show api-typesafe-jev）")
        self.timeout = timeout
        self.conn: http.client.HTTPSConnection | None = None
        self.input_tokens = 0
        self.calls = 0
        self.latencies: list[float] = []

    def _connect(self) -> None:
        conn = http.client.HTTPSConnection(PROXY_HOST, PROXY_PORT, timeout=self.timeout)
        conn.set_tunnel(API_HOST, 443)
        conn.connect()
        self.conn = conn

    def ask(self, state: str, questions: dict, retries: int = 3) -> dict | None:
        """一次调用问一组问题。返回 {"answers":..., "input_tokens":..., "latency":...}。"""
        payload = {"state": state, "model": MODEL, "questions": questions}
        # 必须显式编码成 UTF-8 字节：http.client 对 str body 只按 latin-1 发，
        # 中文 state 会直接抛 UnicodeEncodeError（jev 套利项目没踩到是因为它的 state 全英文）。
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        for attempt in range(1, retries + 1):
            try:
                if self.conn is None:
                    self._connect()
                started = time.perf_counter()
                self.conn.request("POST", "/v1/systemone", body=body, headers={
                    "Authorization": f"Bearer {self.key}",
                    "Content-Type": "application/json",
                })
                raw = self.conn.getresponse().read()
                latency = time.perf_counter() - started
                data = json.loads(raw)
                self.calls += 1
                self.latencies.append(latency)
                tokens = int((data.get("usage") or {}).get("input_tokens") or 0)
                self.input_tokens += tokens
                return {"answers": data.get("answers") or {}, "input_tokens": tokens,
                        "latency": latency}
            except Exception as exc:
                self.conn = None
                if attempt == retries:
                    print(f"    ✗ Jev 调用失败（{retries} 次）：{type(exc).__name__}: {exc}")
                    return None
                time.sleep(1.5 * attempt)
        return None

    @property
    def cost_usd(self) -> float:
        return self.input_tokens / 1_000_000 * PRICE_PER_MTOK
