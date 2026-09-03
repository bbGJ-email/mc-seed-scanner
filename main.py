#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全自动智能 MC Java 种子扫描系统 —— 程序入口。

用法:
    python3 main.py              # 启动可视化控制面板
    python3 main.py --cli        # 命令行模式（按 config.json 扫描）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP_DIR)

import mcss
from mcss import ScanOptions, SeedDatabase, TaskManager
from mcss.paths import get_data_dir


def load_config(path: str) -> dict:
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def options_from_config(cfg: dict) -> ScanOptions:
    o = ScanOptions()
    o.task_name = cfg.get("task_name", "命令行任务")
    ver = str(cfg.get("version", "1.21"))
    o.version = mcss.core_binding.MC_VERSION_BY_NAME.get(ver, mcss.core_binding.MC_1_21)
    o.seed_start = int(cfg.get("seed_start", 0))
    o.seed_end = int(cfg.get("seed_end", 100_000_000))
    o.threads = int(cfg.get("threads", 0))
    o.spawn_mode = int(cfg.get("spawn_mode", 1))
    o.check_spawn = bool(cfg.get("check_spawn", True))
    o.structures = cfg.get("structures", ["Village"])
    o.struct_radius = int(cfg.get("struct_radius", 1200))
    o.need_any_struct = bool(cfg.get("need_any_struct", True))
    o.stronghold_radius = int(cfg.get("stronghold_radius", 0))
    o.need_stronghold = bool(cfg.get("need_stronghold", False))
    o.check_big_plains = bool(cfg.get("check_big_plains", False))
    o.check_mountains = bool(cfg.get("check_mountains", False))
    o.check_coast = bool(cfg.get("check_coast", False))
    o.terrain_radius = int(cfg.get("terrain_radius", 800))
    o.check_multi_biome = bool(cfg.get("check_multi_biome", False))
    o.check_slime = bool(cfg.get("check_slime", False))
    req = cfg.get("req_biome")
    if req:
        o.req_biome = mcss.core_binding.B.get(req, -1)
        o.req_biome_radius = int(cfg.get("req_biome_radius", 1500))
    return o


def run_cli(config_path: str):
    cfg = load_config(config_path)
    o = options_from_config(cfg)
    errs = o.validate()
    if errs:
        print("配置错误:", "；".join(errs))
        sys.exit(1)

    db = SeedDatabase(os.path.join(get_data_dir(), "seeds.db"))
    tm = TaskManager(db,
                     log_dir=os.path.join(get_data_dir(), "logs"),
                     checkpoint_dir=os.path.join(get_data_dir(), "checkpoints"),
                     verify=cfg.get("verify", True),
                     verify_spawn_mode=cfg.get("verify_spawn_mode", 1))
    tm.on_hit_cb = lambda rec: print(
        f"  [命中] 种子 {rec['seed']} 评分{rec['score']} [{rec['tier']}] "
        f"出生点({rec['spawn_x']},{rec['spawn_z']}) {rec['spawn_biome_name']}")
    tm.on_error_cb = lambda m: print(f"  [错误] {m}")

    resume = cfg.get("resume", True)
    tm.start(o, resume=resume)
    print(f"开始扫描 {o.task_name}: [{o.seed_start}, {o.seed_end}) "
          f"版本 {mcss.core_binding.MC_VERSION_NAME.get(o.version)} 线程 {o.effective_threads()}")
    try:
        while tm.running:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n收到中断，正在停止（断点已保存）...")
        tm.stop()
    while tm.running:
        time.sleep(0.5)
    s = tm.status()
    print(f"完成。处理 {s['processed']:,} 种子，命中入库 {db.count()['total']:,} 条。")
    db.close()


def main():
    parser = argparse.ArgumentParser(description="全自动智能 MC Java 种子扫描系统")
    parser.add_argument("--cli", action="store_true", help="命令行模式（使用 config.json）")
    parser.add_argument("--config", default=os.path.join(APP_DIR, "config.json"), help="配置文件路径")
    args = parser.parse_args()

    if args.cli:
        run_cli(args.config)
    else:
        from mcss.gui.main_window import run
        run()


if __name__ == "__main__":
    main()
