# -*- coding: utf-8 -*-
"""导出工具：种子数据批量导出 TXT / JSON。"""
from __future__ import annotations

import json
import os
from typing import List


def _format_seed_line(rec: dict, max_structs: int = 12) -> str:
    sh = rec.get("stronghold")
    stronghold = f"({sh['x']},{sh['z']})" if sh else "无"
    all_s = rec.get("structures", [])
    shown = all_s[:max_structs]
    structs = "、".join(f"{s['name']}@({s['x']},{s['z']})" for s in shown) or "无"
    if len(all_s) > max_structs:
        structs += f" …共{len(all_s)}处"
    tags = "、".join(rec.get("tags", []))
    return (f"[{rec.get('tier', '')}] 种子 {rec['seed']}  评分 {rec.get('score', 0)}"
            f"  [{rec.get('mc_version', '')}]\n"
            f"  出生点: ({rec.get('spawn_x')}, {rec.get('spawn_z')})  "
            f"群系: {rec.get('spawn_biome_name', '')}\n"
            f"  地形: 群系数{rec.get('biome_count', 0)} 海洋{'是' if rec.get('has_ocean') else '否'} "
            f"高山{'是' if rec.get('has_mountains') else '否'} 平原覆盖{rec.get('flat_score', 0)}%\n"
            f"  结构: {structs}\n"
            f"  要塞: {stronghold}  史莱姆出生: {'是' if rec.get('slime_spawn') else '否'}\n"
            f"  标签: {tags}\n")


def export_txt(records: List[dict], path: str) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("# 全自动智能 MC Java 种子扫描系统 - 导出结果\n")
        f.write(f"# 共 {len(records)} 条  导出时间: {__import__('time').strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        for r in records:
            f.write(_format_seed_line(r))
            f.write("\n")
    return path


def export_json(records: List[dict], path: str) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"exported_at": __import__('time').strftime("%Y-%m-%d %H:%M:%S"),
                   "count": len(records), "seeds": records}, f,
                  ensure_ascii=False, indent=2)
    return path


def export_seed_list_txt(records: List[dict], path: str) -> str:
    """仅种子数字列表（便于分享/输入游戏）。"""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(f"{r['seed']}\n")
    return path
