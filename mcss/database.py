# -*- coding: utf-8 -*-
"""种子数据管理库：SQLite 轻量化本地数据库。

能力：永久存储合格种子、自动归档备注、关键词/条件检索、批量导出、黑名单。
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Dict, List, Optional


SCHEMA = """
CREATE TABLE IF NOT EXISTS seeds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seed INTEGER NOT NULL UNIQUE,
    mc_version TEXT,
    score INTEGER DEFAULT 0,
    tier TEXT,
    tier_tag TEXT,
    spawn_x INTEGER,
    spawn_z INTEGER,
    spawn_biome INTEGER,
    spawn_biome_name TEXT,
    biome_count INTEGER,
    has_ocean INTEGER,
    has_mountains INTEGER,
    flat_score INTEGER,
    structures TEXT,
    stronghold_x INTEGER,
    stronghold_z INTEGER,
    has_stronghold INTEGER,
    slime_spawn INTEGER,
    tags TEXT,
    source TEXT,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_seeds_score ON seeds(score);
CREATE INDEX IF NOT EXISTS idx_seeds_tier ON seeds(tier);
CREATE INDEX IF NOT EXISTS idx_seeds_seed ON seeds(seed);

CREATE TABLE IF NOT EXISTS blacklist (
    seed INTEGER PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    version TEXT,
    seed_start INTEGER,
    seed_end INTEGER,
    status TEXT,
    processed INTEGER,
    hits INTEGER,
    duration_sec REAL,
    started_at TEXT,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS seed_intros (
    seed INTEGER PRIMARY KEY,
    intro TEXT,
    model TEXT,
    status TEXT DEFAULT 'pending',
    error TEXT,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_intros_status ON seed_intros(status);
"""


class SeedDatabase:
    def __init__(self, path: str = "data/seeds.db"):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ------------------------------------------------------------------
    # 种子入库
    # ------------------------------------------------------------------
    def insert_seed(self, rec: dict, source: str = "") -> bool:
        """插入一条已评分的种子记录；重复种子自动去重（返回 False）。"""
        with self._lock:
            try:
                sh = rec.get("stronghold")
                cur = self.conn.execute(
                    """INSERT OR IGNORE INTO seeds
                    (seed, mc_version, score, tier, tier_tag,
                     spawn_x, spawn_z, spawn_biome, spawn_biome_name,
                     biome_count, has_ocean, has_mountains, flat_score,
                     structures, stronghold_x, stronghold_z, has_stronghold,
                     slime_spawn, tags, source, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        rec["seed"], rec.get("mc_version", ""), rec.get("score", 0),
                        rec.get("tier", ""), rec.get("tier_tag", ""),
                        rec.get("spawn_x"), rec.get("spawn_z"),
                        rec.get("spawn_biome"), rec.get("spawn_biome_name", ""),
                        rec.get("biome_count", 0),
                        1 if rec.get("has_ocean") else 0,
                        1 if rec.get("has_mountains") else 0,
                        rec.get("flat_score", 0),
                        json.dumps(rec.get("structures", []), ensure_ascii=False),
                        sh["x"] if sh else None, sh["z"] if sh else None,
                        1 if sh else 0,
                        1 if rec.get("slime_spawn") else 0,
                        json.dumps(rec.get("tags", []), ensure_ascii=False),
                        source, time.strftime("%Y-%m-%d %H:%M:%S"),
                    ),
                )
                self.conn.commit()
                return cur.rowcount > 0
            except Exception:
                return False

    def seed_exists(self, seed: int) -> bool:
        with self._lock:
            cur = self.conn.execute("SELECT 1 FROM seeds WHERE seed=?", (seed,))
            return cur.fetchone() is not None

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------
    def query(self, keyword: str = "", min_score: int = 0, tier: str = "",
              tag: str = "", limit: int = 500, order_by: str = "score DESC") -> List[dict]:
        with self._lock:
            sql = "SELECT * FROM seeds WHERE score >= ?"
            args: list = [min_score]
            if keyword:
                sql += " AND (CAST(seed AS TEXT) LIKE ? OR spawn_biome_name LIKE ? OR tags LIKE ? OR source LIKE ?)"
                like = f"%{keyword}%"
                args += [like, like, like, like]
            if tier:
                sql += " AND tier = ?"
                args.append(tier)
            if tag:
                sql += " AND tags LIKE ?"
                args.append(f"%{tag}%")
            if order_by not in ("score DESC", "score ASC", "created_at DESC", "seed ASC"):
                order_by = "score DESC"
            sql += f" ORDER BY {order_by} LIMIT ?"
            args.append(limit)
            cur = self.conn.execute(sql, args)
            return [self._row_to_dict(r) for r in cur.fetchall()]

    def get(self, seed: int) -> Optional[dict]:
        with self._lock:
            cur = self.conn.execute("SELECT * FROM seeds WHERE seed=?", (seed,))
            row = cur.fetchone()
            return self._row_to_dict(row) if row else None

    def count(self) -> dict:
        with self._lock:
            total = self.conn.execute("SELECT COUNT(*) FROM seeds").fetchone()[0]
            by_tier = dict(self.conn.execute(
                "SELECT tier, COUNT(*) FROM seeds GROUP BY tier").fetchall())
            top = self.conn.execute(
                "SELECT MAX(score) FROM seeds").fetchone()[0] or 0
            return {"total": total, "by_tier": by_tier, "top": top}

    @staticmethod
    def _row_to_dict(r) -> dict:
        cols = ["id", "seed", "mc_version", "score", "tier", "tier_tag",
                "spawn_x", "spawn_z", "spawn_biome", "spawn_biome_name",
                "biome_count", "has_ocean", "has_mountains", "flat_score",
                "structures", "stronghold_x", "stronghold_z", "has_stronghold",
                "slime_spawn", "tags", "source", "created_at"]
        d = dict(zip(cols, r))
        d["structures"] = json.loads(d["structures"] or "[]")
        d["tags"] = json.loads(d["tags"] or "[]")
        return d

    # ------------------------------------------------------------------
    # 黑名单
    # ------------------------------------------------------------------
    def add_blacklist(self, seeds) -> int:
        with self._lock:
            n = 0
            for s in seeds:
                try:
                    self.conn.execute("INSERT OR IGNORE INTO blacklist(seed) VALUES (?)", (int(s),))
                    self.conn.execute("DELETE FROM seeds WHERE seed=?", (int(s),))
                    n += 1
                except Exception:
                    pass
            self.conn.commit()
            return n

    def is_blacklisted(self, seed: int) -> bool:
        with self._lock:
            return self.conn.execute(
                "SELECT 1 FROM blacklist WHERE seed=?", (seed,)).fetchone() is not None

    def blacklist_all(self) -> List[int]:
        with self._lock:
            return [r[0] for r in self.conn.execute("SELECT seed FROM blacklist").fetchall()]

    # ------------------------------------------------------------------
    # 任务日志
    # ------------------------------------------------------------------
    def log_task(self, name, version, start, end, status, processed,
                 hits, duration_sec=0.0, started_at="", finished_at=""):
        with self._lock:
            self.conn.execute(
                """INSERT INTO tasks
                   (name, version, seed_start, seed_end, status, processed,
                    hits, duration_sec, started_at, finished_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (name, str(version), int(start), int(end), status,
                 int(processed), int(hits), float(duration_sec),
                 started_at, finished_at))
            self.conn.commit()

    def tasks(self, limit: int = 20) -> List[dict]:
        with self._lock:
            cur = self.conn.execute(
                "SELECT * FROM tasks ORDER BY id DESC LIMIT ?", (limit,))
            cols = ["id", "name", "version", "seed_start", "seed_end", "status",
                    "processed", "hits", "duration_sec", "started_at", "finished_at"]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # 设置
    # ------------------------------------------------------------------
    def get_setting(self, key: str, default: str = "") -> str:
        with self._lock:
            row = self.conn.execute(
                "SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return row[0] if row else default



    # ------------------------------------------------------------------
    # AI 种子介绍
    # ------------------------------------------------------------------
    def set_intro(self, seed: int, intro: str = "", model: str = "",
                  status: str = "done", error: str = "") -> None:
        """写入/更新种子介绍（upsert）。"""
        with self._lock:
            self.conn.execute(
                """INSERT INTO seed_intros(seed, intro, model, status, error, updated_at)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(seed) DO UPDATE SET
                     intro=excluded.intro, model=excluded.model,
                     status=excluded.status, error=excluded.error,
                     updated_at=excluded.updated_at""",
                (int(seed), intro, model, status, error,
                 time.strftime("%Y-%m-%d %H:%M:%S")))
            self.conn.commit()

    def get_intro(self, seed: int) -> Optional[dict]:
        with self._lock:
            cur = self.conn.execute(
                "SELECT seed, intro, model, status, error, updated_at "
                "FROM seed_intros WHERE seed=?", (int(seed),))
            r = cur.fetchone()
            if not r:
                return None
            cols = ["seed", "intro", "model", "status", "error", "updated_at"]
            return dict(zip(cols, r))

    def recommend_candidates(self, min_score: int = 75,
                             tier_whitelist: Optional[List[str]] = None,
                             limit: int = 100) -> List[dict]:
        """按智能推荐规则查询候选种子（高分或高等级），带介绍状态。"""
        tiers = tier_whitelist or ["S+", "S", "A"]
        ph = ",".join("?" * len(tiers))
        with self._lock:
            cur = self.conn.execute(
                f"""SELECT s.*, i.intro AS intro, i.status AS intro_status,
                           i.error AS intro_error, i.model AS intro_model,
                           i.updated_at AS intro_updated
                    FROM seeds s LEFT JOIN seed_intros i ON s.seed = i.seed
                    WHERE s.score >= ? OR s.tier IN ({ph})
                    ORDER BY s.score DESC, s.id DESC LIMIT ?""",
                [min_score, *tiers, int(limit)])
            rows = []
            for r in cur.fetchall():
                rec = self._row_to_dict(r[:22])  # seeds 列
                rec["intro"] = r[22]
                rec["intro_status"] = r[23]
                rec["intro_error"] = r[24]
                rec["intro_model"] = r[25]
                rec["intro_updated"] = r[26]
                rows.append(rec)
            return rows

    def intros_pending(self, limit: int = 200) -> List[int]:
        """返回所有尚未生成介绍的种子号（供批量补生成）。"""
        with self._lock:
            cur = self.conn.execute(
                """SELECT s.seed FROM seeds s
                   LEFT JOIN seed_intros i ON s.seed = i.seed
                   WHERE i.seed IS NULL OR i.status = 'error'
                   ORDER BY s.score DESC LIMIT ?""", (int(limit),))
            return [r[0] for r in cur.fetchall()]

    def clear_intros(self) -> int:
        with self._lock:
            cur = self.conn.execute("DELETE FROM seed_intros")
            self.conn.commit()
            return cur.rowcount

    def set_setting(self, key: str, value: str):
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO settings(key,value) VALUES (?,?)", (key, value))
            self.conn.commit()

    # ------------------------------------------------------------------
    # 维护
    # ------------------------------------------------------------------
    def clear_seeds(self) -> int:
        with self._lock:
            cur = self.conn.execute("DELETE FROM seeds")
            self.conn.commit()
            return cur.rowcount

    def backup(self, dest: str) -> bool:
        """在线备份数据库到指定路径。"""
        with self._lock:
            try:
                tmp = dest + ".tmp"
                b = sqlite3.connect(tmp)
                self.conn.backup(b)
                b.close()
                os.replace(tmp, dest)
                return True
            except Exception:
                return False

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass
