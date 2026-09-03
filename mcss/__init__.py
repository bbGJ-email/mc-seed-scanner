# -*- coding: utf-8 -*-
"""全自动智能 MC Java 种子扫描系统 —— Python 业务层。

模块划分：
  core_binding : Cubiomes C 核心 ctypes 绑定
  config       : 扫描配置 / 预设
  scanner      : 单次扫描运行封装（并发读管道 / 停止 / 暂停）
  scoring      : 智能评分分级引擎
  database     : SQLite 种子数据管理库
  task_manager : 全自动任务调度（断点 / 去重 / 日志 / 过载保护）
  exporters    : TXT / JSON 导出
"""
from . import core_binding, config, database, exporters, scanner, scoring, task_manager
from .config import PRESETS, ScanOptions
from .database import SeedDatabase
from .scanner import Scanner
from .task_manager import TaskManager

__all__ = [
    "core_binding", "config", "database", "exporters", "scanner",
    "scoring", "task_manager", "PRESETS", "ScanOptions",
    "SeedDatabase", "Scanner", "TaskManager",
]

__version__ = "1.0.0"
