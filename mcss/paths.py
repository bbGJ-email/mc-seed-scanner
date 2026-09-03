# -*- coding: utf-8 -*-
"""运行期数据目录解析。

- 源码运行: 项目根目录 (mcss/..)
- 打包 EXE: 可执行文件所在目录 (PyInstaller frozen)

保证数据路径稳定、用户可访问、且不含非 ASCII 字符。
原因: C 端 fopen 写命中文件用的是 UTF-8 字节路径，若路径含中文
（如 PyInstaller 的 %TEMP%\\_MEIxxx，位于中文用户名目录下），
Windows 会按 ANSI 代码页解释而打不开文件，导致命中被静默丢弃。
"""
from __future__ import annotations

import os
import sys


def get_base_dir() -> str:
    """程序基目录：EXE 运行时 = EXE 所在目录；源码运行时 = 项目根。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    here = os.path.dirname(os.path.abspath(__file__))  # .../mcss
    return os.path.dirname(here)


def get_data_dir() -> str:
    """运行期数据目录（数据库/日志/断点/命中缓存）。"""
    return os.path.join(get_base_dir(), "data")
