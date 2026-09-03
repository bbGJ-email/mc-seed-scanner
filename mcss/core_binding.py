# -*- coding: utf-8 -*-
"""Cubiomes 扫描核心 ctypes 绑定层。

负责：
  * 加载 csrc/scanner_core.so（自动探测编译产物路径）
  * 定义 ScannerConfig / SeedInfo 与 C 端逐字段对齐的 ctypes 结构
  * 封装 scanner_run / scanner_inspect / 进度查询 等调用
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import sys

# ---------------------------------------------------------------------------
# 常量：与 csrc/scanner_core.h 及 cubiomes 对齐
# ---------------------------------------------------------------------------
SCANNER_MAX_STRUCTS = 24
SCANNER_MAX_HITS = 48

# MC 版本枚举（cubiomes biomes.h：MC_UNDEF=0 起顺次递增）
MC_1_18 = 22   # MC_1_18_2
MC_1_19 = 24   # MC_1_19_4
MC_1_20 = 25   # MC_1_20_6
MC_1_21 = 28   # MC_1_21 (Winter Drop)
MC_VERSION_NAME = {22: "1.18.2", 24: "1.19.4", 25: "1.20.6", 28: "1.21"}
MC_VERSION_BY_NAME = {"1.18": 22, "1.18.2": 22, "1.19": 24, "1.19.4": 24,
                      "1.20": 25, "1.20.6": 25, "1.21": 28}

# 结构类型枚举（cubiomes finders.h）
ST = {
    "Feature": 0, "Desert_Pyramid": 1, "Jungle_Temple": 2, "Swamp_Hut": 3,
    "Igloo": 4, "Village": 5, "Ocean_Ruin": 6, "Shipwreck": 7,
    "Monument": 8, "Mansion": 9, "Outpost": 10, "Ruined_Portal": 11,
    "Ruined_Portal_N": 12, "Ancient_City": 13, "Treasure": 14,
    "Mineshaft": 15, "Desert_Well": 16, "Geode": 17, "Fortress": 18,
    "Bastion": 19, "End_City": 20, "End_Gateway": 21, "End_Island": 22,
    "Trail_Ruins": 23, "Trial_Chambers": 24,
}
ST_NAME = {v: k for k, v in ST.items()}

# 生物群系 ID（cubiomes biomes.h，1.18+ 常用子集）
B = {
    "ocean": 0, "plains": 1, "desert": 2, "mountains": 3, "forest": 4,
    "taiga": 5, "swamp": 6, "river": 7, "frozen_ocean": 10,
    "frozen_river": 11, "snowy_tundra": 12, "snowy_mountains": 13,
    "mushroom_fields": 14, "mushroom_field_shore": 15, "beach": 16,
    "jungle": 21, "deep_ocean": 24, "stone_shore": 25, "snowy_beach": 26,
    "birch_forest": 27, "dark_forest": 29, "snowy_taiga": 30,
    "giant_tree_taiga": 32, "savanna": 35, "savanna_plateau": 36,
    "badlands": 37, "wooded_badlands_plateau": 38, "badlands_plateau": 39,
    "warm_ocean": 44, "lukewarm_ocean": 45, "cold_ocean": 46,
    "deep_warm_ocean": 47, "deep_lukewarm_ocean": 48, "deep_cold_ocean": 49,
    "deep_frozen_ocean": 50, "sunflower_plains": 129, "flower_forest": 132,
    "bamboo_jungle": 168, "dripstone_caves": 174, "lush_caves": 175,
    "meadow": 177, "grove": 178, "snowy_slopes": 179, "jagged_peaks": 180,
    "frozen_peaks": 181, "stony_peaks": 182, "deep_dark": 183,
    "mangrove_swamp": 184, "cherry_grove": 185, "pale_garden": 186,
}
B_NAME = {v: k for k, v in B.items()}


def _find_lib() -> str:
    """探测 scanner_core 动态库路径。"""
    here = os.path.dirname(os.path.abspath(__file__))
    names = ["scanner_core.dll", "scanner_core.so", "scanner_core.dylib"]
    bundle = getattr(sys, "_MEIPASS", "")
    candidates = []
    if bundle:
        for n in names:
            candidates += [
                os.path.join(bundle, "csrc", n),
                os.path.join(bundle, n),
            ]
    for n in names:
        candidates += [
            os.path.join(here, "..", "csrc", n),      # mcss/../csrc
            os.path.join(here, "csrc", n),
            os.path.join(here, n),
        ]
    candidates.append(os.environ.get("MCSS_CORE_LIB", ""))
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    raise FileNotFoundError(
        "未找到 scanner_core 动态库，请先执行 csrc/build.sh（Linux/macOS）"
        "或 csrc/build_windows.bat（Windows）构建。"
        f"已尝试: {[c for c in candidates if c]}"
    )


_lib = ctypes.CDLL(_find_lib())
_lib.scanner_run.restype = ctypes.c_int
_lib.scanner_run.argtypes = [ctypes.c_void_p]
_lib.scanner_processed.restype = ctypes.c_int64
_lib.scanner_hits.restype = ctypes.c_int64
_lib.scanner_inspect.restype = ctypes.c_int
_lib.scanner_inspect.argtypes = [
    ctypes.c_int, ctypes.c_int64, ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
_lib.scanner_last_error.restype = ctypes.c_char_p


class ScannerConfig(ctypes.Structure):
    """与 C 端 ScannerConfig 逐字段对齐。"""
    _fields_ = [
        ("version", ctypes.c_int),
        ("seed_start", ctypes.c_int64),
        ("seed_end", ctypes.c_int64),
        ("threads", ctypes.c_int),
        ("spawn_mode", ctypes.c_int),
        ("check_spawn", ctypes.c_int),
        ("spawn_ok_biomesL", ctypes.c_uint64),
        ("spawn_ok_biomesM", ctypes.c_uint64),
        ("req_biome", ctypes.c_int),
        ("req_biome_radius", ctypes.c_int),
        ("req_biome_count", ctypes.c_int),
        ("check_multi_biome", ctypes.c_int),
        ("structures", ctypes.c_int * SCANNER_MAX_STRUCTS),
        ("n_struct", ctypes.c_int),
        ("struct_radius", ctypes.c_int),
        ("stronghold_radius", ctypes.c_int),
        ("need_any_struct", ctypes.c_int),
        ("need_stronghold", ctypes.c_int),
        ("check_big_plains", ctypes.c_int),
        ("check_mountains", ctypes.c_int),
        ("check_coast", ctypes.c_int),
        ("terrain_radius", ctypes.c_int),
        ("check_slime", ctypes.c_int),
        ("out_fd", ctypes.c_int),
        ("out_path", ctypes.c_char * 512),
        ("checkpoint_path", ctypes.c_char * 512),
        ("write_checkpoint", ctypes.c_int),
        ("stop_flag", ctypes.POINTER(ctypes.c_int)),
        ("pause_flag", ctypes.POINTER(ctypes.c_int)),
        ("batch", ctypes.c_int),
        ("quiet", ctypes.c_int),
    ]


class SeedInfo(ctypes.Structure):
    _fields_ = [
        ("seed", ctypes.c_int64),
        ("spawn_x", ctypes.c_int),
        ("spawn_z", ctypes.c_int),
        ("est_x", ctypes.c_int),
        ("est_z", ctypes.c_int),
        ("spawn_biome", ctypes.c_int),
        ("biome_count", ctypes.c_int),
        ("has_ocean", ctypes.c_int),
        ("has_mountains", ctypes.c_int),
        ("flat_score", ctypes.c_int),
        ("n_hits", ctypes.c_int),
        ("hit_type", ctypes.c_int * SCANNER_MAX_HITS),
        ("hit_x", ctypes.c_int * SCANNER_MAX_HITS),
        ("hit_z", ctypes.c_int * SCANNER_MAX_HITS),
        ("has_stronghold", ctypes.c_int),
        ("stronghold_x", ctypes.c_int),
        ("stronghold_z", ctypes.c_int),
        ("slime_spawn", ctypes.c_int),
    ]


def make_config() -> ScannerConfig:
    cfg = ScannerConfig()
    cfg.structures = (ctypes.c_int * SCANNER_MAX_STRUCTS)()
    cfg.spawn_ok_biomesL = 0
    cfg.spawn_ok_biomesM = 0
    cfg.stop_flag = None
    cfg.pause_flag = None
    cfg.checkpoint_path = b""
    cfg.out_path = b""
    cfg.out_fd = -1
    cfg.batch = 64
    return cfg


def build_spawn_mask(biome_ids) -> tuple:
    """把群系 ID 列表转成 L/M 两段位图。"""
    L, M = 0, 0
    for bid in biome_ids:
        if 0 <= bid < 64:
            L |= 1 << bid
        elif 128 <= bid < 192:
            M |= 1 << (bid - 128)
    return L, M


def default_safe_spawn_biomes() -> list:
    """默认“舒适开局”群系：平原/草原/森林类。"""
    return [B["plains"], B["sunflower_plains"], B["meadow"], B["cherry_grove"],
            B["forest"], B["flower_forest"], B["birch_forest"],
            B["savanna"], B["savanna_plateau"]]


def run_scan(cfg: ScannerConfig) -> int:
    """执行扫描（阻塞）。返回：0=完成 1=被停止 2=空区间 -1/-2=错误。"""
    return _lib.scanner_run(ctypes.byref(cfg))


def processed() -> int:
    return int(_lib.scanner_processed())


def hits() -> int:
    return int(_lib.scanner_hits())


def last_error() -> str:
    return _lib.scanner_last_error().decode("utf-8", "replace")


def inspect(version: int, seed: int, radius: int = 800,
            spawn_mode: int = 1) -> SeedInfo:
    """单种子回查（spawn_mode: 0=原点 1=快速 2=精确）。"""
    info = SeedInfo()
    rc = _lib.scanner_inspect(version, seed, radius, spawn_mode, ctypes.byref(info))
    if rc != 0:
        raise RuntimeError(f"scanner_inspect 失败: {last_error()}")
    return info
