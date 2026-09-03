# -*- coding: utf-8 -*-
"""AI 智能种子介绍生成器（OpenAI 兼容接口）。

支持任意 OpenAI 兼容 Chat Completions 端点：
OpenAI 官方、DeepSeek、Moonshot、通义千问、本地 vLLM/Ollama 等。

- 配置（base_url / api_key / model / 阈值 / 并发）可持久化到 JSON 文件
- 异步线程池生成，不阻塞扫描主流程
- 失败自动重试并记录错误，状态可查询
"""
from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Callable, Dict, List, Optional


@dataclass
class AIConfig:
    """OpenAI 兼容接口配置。"""
    enabled: bool = False          # 是否启用 AI 生成
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini"
    timeout: int = 60              # 单次请求超时（秒）
    max_retry: int = 2             # 失败重试次数
    intro_threshold: int = 75      # 评分达到该值才自动生成介绍
    min_tier: str = "S"            # 最低等级（S+/S/A/B/C），满足评分或等级即生成
    max_workers: int = 2           # 并发生成线程数

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "AIConfig":
        cur = cls()
        for k, v in (d or {}).items():
            if hasattr(cur, k):
                setattr(cur, k, v)
        return cur

    def save(self, path: str):
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    @classmethod
    def load(cls, path: str) -> "AIConfig":
        try:
            with open(path, "r", encoding="utf-8") as f:
                return cls.from_dict(json.load(f))
        except Exception:
            return cls()

    def is_configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    def should_recommend(self, score: int, tier: str) -> bool:
        """是否应对该种子自动生成介绍（智能推荐规则）。"""
        order = {"S+": 0, "S": 1, "A": 2, "B": 3, "C": 4}
        tier_ok = order.get(tier, 9) <= order.get(self.min_tier, 1)
        return score >= self.intro_threshold or tier_ok


# ---------------------------------------------------------------------------
# 介绍生成器
# ---------------------------------------------------------------------------
class AIIntroGenerator:
    def __init__(self, config: AIConfig):
        self.config = config
        self._pool = ThreadPoolExecutor(max_workers=max(1, config.max_workers))
        self._lock = threading.Lock()
        self._pending: Dict[int, str] = {}   # seed -> status(pending/generating/error)

    # ---- 对外：异步提交 ----
    def submit(self, rec: dict, on_done: Callable[[dict, str, str], None]):
        """异步生成介绍。on_done(rec, intro, error)：intro 为空时 error 非空。"""
        seed = rec.get("seed")
        if not seed:
            return
        with self._lock:
            if seed in self._pending:
                return
            self._pending[seed] = "pending"
        try:
            self._pool.submit(self._worker, dict(rec), on_done)
        except Exception as e:
            with self._lock:
                self._pending.pop(seed, None)
            on_done(dict(rec), "", f"提交失败: {e}")

    def _worker(self, rec: dict, on_done: Callable):
        seed = rec.get("seed")
        with self._lock:
            self._pending[seed] = "generating"
        intro, err = "", ""
        try:
            intro = self._generate(rec)
        except Exception as e:
            err = str(e)
        with self._lock:
            self._pending.pop(seed, None)
        try:
            on_done(rec, intro, err)
        except Exception:
            pass

    # ---- 同步生成（含重试）----
    def _generate(self, rec: dict) -> str:
        if not self.config.is_configured():
            raise RuntimeError("AI 未配置（base_url/api_key/model）")
        messages = self.build_messages(rec)
        last_err = ""
        for _ in range(self.config.max_retry + 1):
            try:
                content = self._call_chat(messages)
                if content:
                    return content.strip()
                last_err = "返回内容为空"
            except urllib.error.HTTPError as e:
                last_err = f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}"
            except Exception as e:
                last_err = str(e)
            time.sleep(1.0)
        raise RuntimeError(f"AI 请求失败: {last_err}")

    def _call_chat(self, messages: List[dict]) -> str:
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 400,
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.config.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]

    # ---- Prompt 组装 ----
    @staticmethod
    def build_messages(rec: dict) -> List[dict]:
        structs = "、".join(
            f"{s['name']}@({s['x']},{s['z']})" for s in rec.get("structures", [])[:8]) or "无"
        sh = rec.get("stronghold")
        stronghold = f"({sh['x']},{sh['z']})" if sh else "无"
        tags = "、".join(rec.get("tags", [])) or "无"
        terrain = (f"生物群系{rec.get('biome_count', 0)}种"
                   f"{'，含海洋' if rec.get('has_ocean') else ''}"
                   f"{'，含高山' if rec.get('has_mountains') else ''}"
                   f"，平原覆盖{rec.get('flat_score', 0)}%")
        user = (
            f"请用中文为以下《我的世界》Java 版种子写一段 80~150 字的介绍，"
            f"突出 2~4 个最有价值的亮点（出生点舒适度、稀有结构、地形、资源），"
            f"最后用一句“适合……的玩家”结尾。不要编造数据，只描述给定的信息。\n\n"
            f"种子号：{rec.get('seed')}\n"
            f"适配版本：{rec.get('mc_version', '')}\n"
            f"综合评分：{rec.get('score', 0)}（{rec.get('tier', '')}）\n"
            f"出生点：({rec.get('spawn_x')}, {rec.get('spawn_z')})，"
            f"群系：{rec.get('spawn_biome_name', '')}\n"
            f"地形：{terrain}\n"
            f"结构：{structs}\n"
            f"要塞：{stronghold}\n"
            f"标签：{tags}"
        )
        return [
            {"role": "system",
             "content": "你是一位资深的《我的世界》(Minecraft Java 版) 种子猎人，"
                        "善于用简洁、有吸引力且准确的中文向玩家介绍世界种子的亮点。"},
            {"role": "user", "content": user},
        ]

    def shutdown(self):
        try:
            self._pool.shutdown(wait=False)
        except Exception:
            pass
