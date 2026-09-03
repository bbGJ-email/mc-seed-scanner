# -*- coding: utf-8 -*-
"""扫描配置：面向用户的 ScanOptions 数据类 + 预设 + C 配置构建。"""
from __future__ import annotations

import dataclasses
import json
import os
from dataclasses import dataclass, field
from typing import List, Optional

from . import core_binding as cb


@dataclass
class ScanOptions:
    """一次扫描任务的完整配置（映射到 C 端 ScannerConfig）。"""
    # ---- 基础 ----
    version: int = cb.MC_1_21
    seed_start: int = 0
    seed_end: int = 100_000_000
    threads: int = 0                      # 0=自动按 CPU 核数
    spawn_mode: int = 1                   # 0=原点 1=快速估计 2=精确getSpawn
    task_name: str = "默认任务"

    # ---- 出生点判定 ----
    check_spawn: bool = True
    safe_spawn_biomes: List[int] = field(default_factory=cb.default_safe_spawn_biomes)

    # ---- 稀有/多群系 ----
    req_biome: int = -1                   # -1=关闭
    req_biome_radius: int = 1000
    req_biome_count: int = 1
    check_multi_biome: bool = False

    # ---- 结构 ----
    structures: List[str] = field(default_factory=lambda: ["Village"])
    struct_radius: int = 1200
    stronghold_radius: int = 0            # 0=不查要塞
    need_any_struct: bool = True
    need_stronghold: bool = False

    # ---- 地形 ----
    check_big_plains: bool = False
    check_mountains: bool = False
    check_coast: bool = False
    terrain_radius: int = 800

    # ---- 附加 ----
    check_slime: bool = False
    batch: int = 128
    write_checkpoint: bool = True
    checkpoint_dir: str = "data/checkpoints"

    def effective_threads(self) -> int:
        if self.threads and self.threads > 0:
            return self.threads
        n = os.cpu_count() or 4
        return max(1, n - 1)              # 留 1 核给系统

    def validate(self) -> List[str]:
        errs = []
        if self.version not in cb.MC_VERSION_NAME:
            errs.append(f"不支持的 MC 版本: {self.version}")
        if self.seed_end <= self.seed_start:
            errs.append("扫描区间为空（end 必须大于 start）")
        if self.req_biome != -1 and self.req_biome not in cb.B_NAME:
            errs.append(f"不存在的群系 ID: {self.req_biome}")
        for s in self.structures:
            if s not in cb.ST:
                errs.append(f"不存在的结构: {s}")
        return errs


# ---------------------------------------------------------------------------
# 预设：开箱即用的组合筛选方案
# ---------------------------------------------------------------------------
def preset_comfort_spawn() -> ScanOptions:
    """舒适出生点：安全出生点 + 村庄近出生点。"""
    o = ScanOptions()
    o.check_spawn = True
    o.structures = ["Village"]
    o.struct_radius = 1500
    o.need_any_struct = True
    return o


def preset_mushroom_island() -> ScanOptions:
    """蘑菇岛开局：出生点附近出现蘑菇岛 + 村庄。"""
    o = ScanOptions()
    o.check_spawn = True
    o.req_biome = cb.B["mushroom_fields"]
    o.req_biome_radius = 1500
    o.req_biome_count = 1
    o.structures = ["Village"]
    o.struct_radius = 1500
    o.need_any_struct = False
    return o


def preset_ancient_city() -> ScanOptions:
    """古城猎手：出生点近古城。"""
    o = ScanOptions()
    o.check_spawn = True
    o.structures = ["Ancient_City"]
    o.struct_radius = 1500
    o.need_any_struct = True
    return o


def preset_big_plains() -> ScanOptions:
    """超大平原 + 海景 + 多群系。"""
    o = ScanOptions()
    o.check_spawn = True
    o.check_big_plains = True
    o.check_coast = True
    o.check_multi_biome = True
    o.terrain_radius = 1200
    o.structures = ["Village"]
    o.need_any_struct = False
    return o


PRESETS = {
    "舒适出生点": preset_comfort_spawn,
    "蘑菇岛开局": preset_mushroom_island,
    "古城猎手": preset_ancient_city,
    "超大平原海景": preset_big_plains,
}


# ---------------------------------------------------------------------------
# 构建 C 端 ScannerConfig
# ---------------------------------------------------------------------------
def build_scanner_config(opts: ScanOptions) -> cb.ScannerConfig:
    cfg = cb.make_config()
    cfg.version = opts.version
    cfg.seed_start = int(opts.seed_start)
    cfg.seed_end = int(opts.seed_end)
    cfg.threads = opts.effective_threads()
    cfg.spawn_mode = opts.spawn_mode
    cfg.check_spawn = 1 if opts.check_spawn else 0
    L, M = cb.build_spawn_mask(opts.safe_spawn_biomes)
    cfg.spawn_ok_biomesL = L
    cfg.spawn_ok_biomesM = M
    cfg.req_biome = opts.req_biome
    cfg.req_biome_radius = opts.req_biome_radius
    cfg.req_biome_count = opts.req_biome_count
    cfg.check_multi_biome = 1 if opts.check_multi_biome else 0
    cfg.n_struct = min(len(opts.structures), cb.SCANNER_MAX_STRUCTS)
    for i, name in enumerate(opts.structures[:cfg.n_struct]):
        cfg.structures[i] = cb.ST[name]
    cfg.struct_radius = opts.struct_radius
    cfg.stronghold_radius = opts.stronghold_radius
    cfg.need_any_struct = 1 if opts.need_any_struct else 0
    cfg.need_stronghold = 1 if opts.need_stronghold else 0
    cfg.check_big_plains = 1 if opts.check_big_plains else 0
    cfg.check_mountains = 1 if opts.check_mountains else 0
    cfg.check_coast = 1 if opts.check_coast else 0
    cfg.terrain_radius = opts.terrain_radius
    cfg.check_slime = 1 if opts.check_slime else 0
    cfg.batch = opts.batch
    cfg.write_checkpoint = 1 if opts.write_checkpoint else 0
    return cfg
