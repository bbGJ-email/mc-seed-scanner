# -*- coding: utf-8 -*-
"""智能评分引擎：100 分制综合打分 + 五档分级 + 地形特色标签自动归档。"""
from __future__ import annotations

import json
from typing import Dict, List

from . import core_binding as cb

# ---------------------------------------------------------------------------
# 权重（可调）
# ---------------------------------------------------------------------------
SCORE_WEIGHTS = {
    "spawn_comfort": 20,   # 出生点舒适度
    "terrain": 25,         # 地形价值
    "structures": 40,      # 结构价值
    "rare_biome": 10,      # 稀有群系
    "bonus": 5,            # 附加加分
}

# 结构价值（稀有/实用度加权）
STRUCTURE_VALUE: Dict[str, int] = {
    "Stronghold": 12, "Ancient_City": 10, "Village": 8, "Monument": 6,
    "Mansion": 6, "Trial_Chambers": 5, "Desert_Pyramid": 4, "Igloo": 4,
    "Outpost": 4, "Jungle_Temple": 4, "Trail_Ruins": 3, "Ocean_Ruin": 3,
    "Shipwreck": 3, "Swamp_Hut": 3, "Ruined_Portal": 2, "Mineshaft": 2,
}

# 稀有群系价值
RARE_BIOME_VALUE: Dict[str, int] = {
    "mushroom_fields": 10, "deep_dark": 8, "cherry_grove": 6,
    "bamboo_jungle": 6, "badlands": 5, "ice_spikes": 4,
    "flower_forest": 4, "mangrove_swamp": 3, "sunflower_plains": 3,
    "meadow": 3, "pale_garden": 8,
}

# 出生点舒适群系加分（与 C 端默认安全集一致）
COMFORT_BIOMES = {
    "plains": 3, "sunflower_plains": 4, "meadow": 4, "cherry_grove": 5,
    "forest": 3, "flower_forest": 4, "birch_forest": 3, "savanna": 2,
    "savanna_plateau": 2,
}

# 五档分级边界
TIERS = [
    (90, "绝版顶级神种", "S+"),
    (75, "极品神种", "S"),
    (65, "精品种子", "A"),
    (50, "优质种子", "B"),
    (0, "普通种子", "C"),
]


def tier_of(score: int) -> tuple:
    for threshold, name, tag in TIERS:
        if score >= threshold:
            return name, tag
    return TIERS[-1][1], TIERS[-1][2]


def _biome_name(bid: int) -> str:
    return cb.B_NAME.get(bid, str(bid))


def structure_points(structures: List[dict]) -> int:
    """结构分值：按稀有/实用加权，取前若干项求和，封顶 40。"""
    pts = 0
    for s in structures:
        pts += STRUCTURE_VALUE.get(s["name"], 2)
    return min(pts, SCORE_WEIGHTS["structures"])


def rare_biome_points(spawn_biome: int, biome_count: int) -> int:
    """稀有群系分值：出生点所在群系稀有度 + 群系多样性奖励。"""
    pts = RARE_BIOME_VALUE.get(_biome_name(spawn_biome), 0)
    if biome_count >= 6:
        pts += 3
    elif biome_count >= 4:
        pts += 2
    elif biome_count >= 3:
        pts += 1
    return min(pts, SCORE_WEIGHTS["rare_biome"])


def spawn_comfort_points(spawn_biome: int, flat_score: int,
                         has_ocean: bool, has_mountains: bool,
                         slime: bool, stronghold: bool) -> int:
    """出生点舒适度：群系加分 + 地形平坦 + 规避恶劣地形。"""
    pts = COMFORT_BIOMES.get(_biome_name(spawn_biome), 0) * 2  # 0-10
    if flat_score >= 80:
        pts += 6
    elif flat_score >= 60:
        pts += 4
    elif flat_score >= 40:
        pts += 2
    if not has_mountains:
        pts += 2
    if not has_ocean:
        pts += 1
    if slime:
        pts += 2
    if stronghold:
        pts += 1
    return min(pts, SCORE_WEIGHTS["spawn_comfort"])


def terrain_points(flat_score: int, biome_count: int,
                   has_ocean: bool, has_mountains: bool) -> int:
    """地形价值：超大平原 + 海景 + 多群系拼接 + 连绵高山。"""
    pts = 0
    if flat_score >= 80:
        pts += 10
    elif flat_score >= 60:
        pts += 7
    elif flat_score >= 40:
        pts += 4
    if has_ocean:
        pts += 5
    if biome_count >= 5:
        pts += 6
    elif biome_count >= 3:
        pts += 4
    if has_mountains:
        pts += 4
    return min(pts, SCORE_WEIGHTS["terrain"])


def bonus_points(slime: bool, stronghold: bool, n_struct: int) -> int:
    pts = 0
    if slime:
        pts += 3
    if stronghold:
        pts += 2
    if n_struct >= 4:
        pts += 2
    elif n_struct >= 2:
        pts += 1
    return min(pts, SCORE_WEIGHTS["bonus"])


def generate_tags(rec: dict) -> List[str]:
    """根据命中特征自动生成地形特色标签。"""
    tags = []
    sp_b = rec.get("spawn_biome_name", "")
    if sp_b in ("plains", "sunflower_plains", "meadow"):
        tags.append("平原出生")
    if rec.get("flat_score", 0) >= 80:
        tags.append("超大平原")
    if rec.get("has_ocean"):
        tags.append("海景")
    if rec.get("has_mountains"):
        tags.append("连绵高山")
    if rec.get("biome_count", 0) >= 4:
        tags.append("多群系拼接")
    if sp_b == "mushroom_fields":
        tags.append("蘑菇岛")
    if sp_b in ("cherry_grove", "flower_forest"):
        tags.append("樱花/花海")
    names = [s["name"] for s in rec.get("structures", [])]
    if "Stronghold" in names:
        tags.append("要塞")
    if "Ancient_City" in names:
        tags.append("远古之城")
    if "Monument" in names:
        tags.append("海底神殿")
    if "Mansion" in names:
        tags.append("林地府邸")
    if rec.get("slime_spawn"):
        tags.append("史莱姆区块")
    return tags or ["待定"]


def score_seed(rec: dict) -> dict:
    """对一条命中记录进行综合评分，返回附加上 score/tier/tags 的副本。"""
    structures = rec.get("structures", [])
    sp = structure_points(structures)
    rb = rare_biome_points(rec.get("spawn_biome", -1), rec.get("biome_count", 0))
    sc = spawn_comfort_points(
        rec.get("spawn_biome", -1), rec.get("flat_score", 0),
        rec.get("has_ocean", False), rec.get("has_mountains", False),
        rec.get("slime_spawn", False), rec.get("stronghold") is not None)
    tp = terrain_points(rec.get("flat_score", 0), rec.get("biome_count", 0),
                        rec.get("has_ocean", False), rec.get("has_mountains", False))
    bn = bonus_points(rec.get("slime_spawn", False),
                      rec.get("stronghold") is not None, len(structures))
    total = sc + tp + sp + rb + bn
    tier_name, tier_tag = tier_of(total)

    out = dict(rec)
    out["score"] = total
    out["tier"] = tier_name
    out["tier_tag"] = tier_tag
    out["tags"] = generate_tags(rec)
    out["score_detail"] = {
        "spawn_comfort": sc, "terrain": tp, "structures": sp,
        "rare_biome": rb, "bonus": bn,
    }
    return out
