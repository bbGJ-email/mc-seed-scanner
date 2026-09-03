# -*- coding: utf-8 -*-
"""Scanner：在后台线程运行 C 扫描核心，并发读取命中管道，提供进度/停止/暂停控制。"""
from __future__ import annotations

import ctypes
import os
import queue
import threading
import time
from typing import Callable, Optional

from . import core_binding as cb
from .config import ScanOptions, build_scanner_config


def parse_hit_line(line: str) -> Optional[dict]:
    """解析 C 端输出的一行命中记录。

    格式：seed\\tspawn_x\\tspawn_z\\tspawn_biome\\tbiome_count\\tocean\\tmtn\\tflat\\tstructs\\tstronghold\\tslime
    structs = "type@x,z;type@x,z;..."
    stronghold = "x,z" 或 "-"
    """
    try:
        parts = line.split("\t")
        if len(parts) < 11:
            return None
        seed = int(parts[0])
        spawn_x, spawn_z = int(parts[1]), int(parts[2])
        spawn_biome = int(parts[3])
        biome_count = int(parts[4])
        has_ocean = int(parts[5]) == 1
        has_mountains = int(parts[6]) == 1
        flat_score = int(parts[7])
        structures = []
        if parts[8]:
            for item in parts[8].split(";"):
                if "@" in item:
                    stype, coords = item.split("@", 1)
                    cx, cz = coords.split(",")
                    structures.append({
                        "type": int(stype),
                        "name": cb.ST_NAME.get(int(stype), str(stype)),
                        "x": int(cx), "z": int(cz),
                    })
        stronghold = None
        if parts[9] != "-":
            hx, hz = parts[9].split(",")
            stronghold = {"x": int(hx), "z": int(hz)}
        slime = int(parts[10]) == 1
        return {
            "seed": seed, "spawn_x": spawn_x, "spawn_z": spawn_z,
            "spawn_biome": spawn_biome,
            "spawn_biome_name": cb.B_NAME.get(spawn_biome, str(spawn_biome)),
            "biome_count": biome_count, "has_ocean": has_ocean,
            "has_mountains": has_mountains, "flat_score": flat_score,
            "structures": structures, "stronghold": stronghold,
            "slime_spawn": slime,
        }
    except Exception:
        return None


class Scanner:
    """单次扫描的运行封装。"""

    def __init__(self, options: ScanOptions, on_hit: Optional[Callable[[dict], None]] = None,
                 on_finish: Optional[Callable[[int], None]] = None,
                 on_error: Optional[Callable[[str], None]] = None,
                 checkpoint_path: str = "",
                 out_path: str = ""):
        self.options = options
        self.on_hit = on_hit
        self.on_finish = on_finish
        self.on_error = on_error
        self.checkpoint_path = checkpoint_path

        self.cfg = build_scanner_config(options)
        self._stop = ctypes.c_int(0)
        self._pause = ctypes.c_int(0)
        self.cfg.stop_flag = ctypes.pointer(self._stop)
        self.cfg.pause_flag = ctypes.pointer(self._pause)
        if checkpoint_path:
            self.cfg.checkpoint_path = checkpoint_path.encode("utf-8")
            self.cfg.write_checkpoint = 1

        # 命中输出：优先文件追加（跨平台，规避 Windows CRT fd 兼容问题）
        self.out_path = out_path or os.path.join(
            os.path.dirname(checkpoint_path) if checkpoint_path else "data",
            "hits.tmp")
        self.cfg.out_path = self.out_path.encode("utf-8")
        self.cfg.out_fd = -1
        self._out_offset = 0

        self._reader = None
        self._worker = None
        self._hits: queue.Queue = queue.Queue()
        self._finished = threading.Event()
        self._rc = None
        self._error = ""

    # ---- 控制 ----
    def start(self):
        # 清空上次的输出文件
        try:
            with open(self.out_path, "w"):
                pass
        except OSError:
            pass
        self._out_offset = 0
        self._reader = threading.Thread(target=self._drain, daemon=True)
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._reader.start()
        self._worker.start()

    def stop(self):
        self._stop.value = 1

    def set_pause(self, paused: bool):
        self._pause.value = 1 if paused else 0

    def join(self, timeout=None):
        if self._worker:
            self._worker.join(timeout)

    # ---- 状态 ----
    @property
    def running(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    @property
    def finished(self) -> bool:
        return self._finished.is_set()

    def progress(self) -> tuple:
        """返回 (已处理种子数, 命中数)。C 端每次 scanner_run 会重置计数器。"""
        return cb.processed(), cb.hits()

    @property
    def rc(self) -> Optional[int]:
        return self._rc

    @property
    def error(self) -> str:
        return self._error

    # ---- 内部 ----
    def _drain(self):
        """并发尾部读取命中文件，避免阻塞 C 工作线程。"""
        buf = b""
        while not self._finished.is_set():
            try:
                with open(self.out_path, "rb") as f:
                    f.seek(self._out_offset)
                    data = f.read()
                    if data:
                        self._out_offset = f.tell()
                        buf += data
                        while b"\n" in buf:
                            line, buf = buf.split(b"\n", 1)
                            if line:
                                self._emit(line)
            except OSError:
                pass
            time.sleep(0.05)
        # 收尾：读尽剩余
        try:
            with open(self.out_path, "rb") as f:
                f.seek(self._out_offset)
                data = f.read()
                if data:
                    buf += data
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        if line:
                            self._emit(line)
                    if buf.strip():
                        self._emit(buf)
        except OSError:
            pass

    def _emit(self, line: bytes):
        rec = parse_hit_line(line.decode("utf-8", "replace"))
        if rec:
            self._hits.put(rec)
            if self.on_hit:
                try:
                    self.on_hit(rec)
                except Exception as e:
                    print(f"[Scanner.on_hit] {e}")

    def _run(self):
        try:
            rc = cb.run_scan(self.cfg)
            self._rc = rc
        except Exception as e:
            self._error = str(e)
            self._rc = -1
        finally:
            self._finished.set()
            if self.on_finish:
                try:
                    self.on_finish(self._rc)
                except Exception as e:
                    print(f"[Scanner.on_finish] {e}")

    def drain_hits(self) -> list:
        """取出已累积的命中记录。"""
        out = []
        while True:
            try:
                out.append(self._hits.get_nowait())
            except queue.Empty:
                break
        return out
