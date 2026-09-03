# -*- coding: utf-8 -*-
"""任务调度系统：全自动批量扫描 + 断点续扫 + 去重 + 日志 + 设备过载保护。

职责：
  1. 读取断点文件，自动接续上次进度（无重复、无遗漏）
  2. 后台启动 Scanner，实时接收命中 → 评分 → 入库（自动去重）
  3. 轮询系统负载，过载时自动暂停（降频）保护设备
  4. 全流程日志记录（时长 / 扫描量 / 命中量 / 异常）
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from typing import Callable, Optional

from . import core_binding as cb
from .config import ScanOptions
from .database import SeedDatabase
from .scanner import Scanner
from .scoring import score_seed

try:
    import psutil
    HAS_PSUTIL = True
except Exception:
    HAS_PSUTIL = False


class TaskManager:
    def __init__(self, db: SeedDatabase, log_dir: str = "data/logs",
                 checkpoint_dir: str = "data/checkpoints",
                 verify: bool = True, verify_spawn_mode: int = 1):
        self.db = db
        self.log_dir = log_dir
        self.checkpoint_dir = checkpoint_dir
        self.verify = verify                # 命中后是否做 C 精确复核
        self.verify_spawn_mode = verify_spawn_mode  # 0=原点 1=快速 2=精确
        os.makedirs(log_dir, exist_ok=True)
        os.makedirs(checkpoint_dir, exist_ok=True)

        self._scanner: Optional[Scanner] = None
        self._lock = threading.Lock()
        self._running = False
        self._logger = self._make_logger()
        self._overload_since = 0.0
        self._hit_queue: "queue.Queue" = __import__("queue").Queue()
        self._writer: Optional[threading.Thread] = None
        self._done_event = threading.Event()
        self._db_lock = threading.Lock()

        # 事件回调（供 GUI 刷新）
        self.on_hit_cb: Optional[Callable[[dict], None]] = None
        self.on_status_cb: Optional[Callable[[dict], None]] = None
        self.on_finish_cb: Optional[Callable[[dict], None]] = None
        self.on_error_cb: Optional[Callable[[str], None]] = None

    # ------------------------------------------------------------------
    def _make_logger(self) -> logging.Logger:
        logger = logging.getLogger("mcss.task")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            fh = logging.FileHandler(
                os.path.join(self.log_dir, "scan.log"), encoding="utf-8")
            fh.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s"))
            logger.addHandler(fh)
        return logger

    # ------------------------------------------------------------------
    # 断点续扫
    # ------------------------------------------------------------------
    def _checkpoint_path(self, options: ScanOptions) -> str:
        # 按任务特征隔离断点文件：同一配置重启可续扫，不同配置互不干扰
        key = hashlib.md5(
            f"{options.task_name}|{options.version}|{options.seed_start}|{options.seed_end}".encode("utf-8")
        ).hexdigest()[:10]
        return os.path.join(self.checkpoint_dir, f"scan_{key}.ckpt")

    def read_checkpoint(self, options: ScanOptions) -> Optional[int]:
        """读取断点；返回断点种子或 None。"""
        p = self._checkpoint_path(options)
        try:
            with open(p, "r") as f:
                v = int(f.read().strip())
            if options.seed_start <= v < options.seed_end:
                return v
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # 任务生命周期
    # ------------------------------------------------------------------
    @property
    def running(self) -> bool:
        return self._running

    def start(self, options: ScanOptions, resume: bool = True):
        with self._lock:
            if self._running:
                self._notify_error("已有任务在运行")
                return
            self._running = True

        try:
            self._start_task(options, resume)
        except Exception as e:
            with self._lock:
                self._running = False
            self._log(f"任务启动失败: {e}", level=logging.ERROR)
            self._notify_error(f"任务启动失败: {e}")

    def _start_task(self, options: ScanOptions, resume: bool):
        start_seed = options.seed_start
        if resume:
            ckpt = self.read_checkpoint(options)
            if ckpt is not None:
                start_seed = ckpt
                self._log(f"检测到断点，从种子 {start_seed} 续扫（上次扫描在 {options.seed_start} 处中断）")

        opts = options
        if start_seed != opts.seed_start:
            from dataclasses import replace
            opts = replace(opts, seed_start=start_seed)

        self._start_time = time.time()
        self._last_processed = 0
        self._last_time = time.time()
        self._log(f"开始任务「{opts.task_name}」 区间 [{opts.seed_start}, {opts.seed_end}) "
                  f"版本 {cb.MC_VERSION_NAME.get(opts.version)} 线程 {opts.effective_threads()}")

        scanner = Scanner(
            opts,
            on_hit=self._enqueue_hit,       # 仅入队，不阻塞管道读取
            on_finish=self._handle_finish,
            on_error=self._handle_error,
            checkpoint_path=self._checkpoint_path(opts) if opts.write_checkpoint else "",
        )
        self._scanner = scanner
        # 独立写入线程：负责复核/评分/入库
        self._writer = threading.Thread(target=self._writer_loop, daemon=True)
        self._writer.start()
        self._monitor = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor.start()
        scanner.start()

    def stop(self):
        with self._lock:
            if self._scanner:
                self._log("收到停止指令，正在收尾...")
                self._scanner.stop()

    def set_pause(self, paused: bool):
        with self._lock:
            if self._scanner:
                self._scanner.set_pause(paused)

    @property
    def running(self) -> bool:
        return self._running

    @property
    def done(self) -> bool:
        """任务完全收尾（含数据库写入排空）后置位。"""
        return self._done_event.is_set()

    def wait_done(self, timeout: float = 300.0) -> bool:
        return self._done_event.wait(timeout)

    def status(self) -> dict:
        sc = self._scanner
        processed = hits = 0
        speed = 0.0
        if sc is not None:
            if sc.running:
                processed, hits = sc.progress()
                now = time.time()
                dt = now - self._last_time
                if dt > 0.2:
                    speed = (processed - self._last_processed) / dt
                    self._last_processed = processed
                    self._last_time = now
            else:
                processed, hits = sc.progress()  # 任务结束仍保留最后进度
        total = (sc.options.seed_end - sc.options.seed_start) if sc else 0
        remaining = max(0, total - processed) if sc else 0
        eta = remaining / speed if speed > 0 else 0
        paused = False
        if sc is not None:
            try:
                paused = bool(sc._pause.value)
            except Exception:
                paused = False
        return {
            "running": self._running and sc is not None and sc.running,
            "task_name": sc.options.task_name if sc else "",
            "processed": processed,
            "total": total,
            "remaining": remaining,
            "speed": speed,
            "hits": hits,
            "eta": eta,
            "paused": paused,
            "threads": sc.options.effective_threads() if sc else 0,
        }

    # ------------------------------------------------------------------
    # 事件处理
    # ------------------------------------------------------------------
    def _enqueue_hit(self, rec: dict):
        """管道读取线程仅负责入队，绝不在此做慢速复核。"""
        try:
            self._hit_queue.put_nowait(rec)
        except Exception:
            pass

    def _writer_loop(self):
        """写入线程：消费命中队列 → 复核(线程池) → 评分 → 入库 → 通知 GUI。"""
        import concurrent.futures
        n_workers = max(1, min(4, self._scanner.options.effective_threads()))
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=n_workers)
        while True:
            rec = self._hit_queue.get()
            if rec is None:                 # 哨兵：排空已提交任务后退出
                pool.shutdown(wait=True)
                break
            try:
                pool.submit(self._process_hit, rec)
            except Exception as e:
                self._log(f"命中提交异常: {e}", level=logging.ERROR)

    def _process_hit(self, rec: dict):
        # 黑名单过滤
        with self._db_lock:
            if self.db.is_blacklisted(rec["seed"]):
                return
        # 精确复核（可开关；修正出生点、补全结构、地形统计）
        if self.verify and self._scanner is not None:
            try:
                info = cb.inspect(self._scanner.options.version, rec["seed"],
                                  800, self.verify_spawn_mode)
                rec["spawn_x"] = info.spawn_x
                rec["spawn_z"] = info.spawn_z
                rec["spawn_biome"] = info.spawn_biome
                rec["spawn_biome_name"] = cb.B_NAME.get(info.spawn_biome, str(info.spawn_biome))
                rec["biome_count"] = info.biome_count
                rec["has_ocean"] = bool(info.has_ocean)
                rec["has_mountains"] = bool(info.has_mountains)
                rec["flat_score"] = info.flat_score
                rec["stronghold"] = {"x": info.stronghold_x, "z": info.stronghold_z} \
                    if info.has_stronghold else None
                rec["slime_spawn"] = bool(info.slime_spawn)
                # 合并快速扫描与复核的结构命中（去重）
                known = {(s["type"], s["x"], s["z"]) for s in rec.get("structures", [])}
                for i in range(info.n_hits):
                    key = (info.hit_type[i], info.hit_x[i], info.hit_z[i])
                    if key not in known:
                        rec["structures"].append({
                            "type": info.hit_type[i],
                            "name": cb.ST_NAME.get(info.hit_type[i], str(info.hit_type[i])),
                            "x": info.hit_x[i], "z": info.hit_z[i],
                        })
                        known.add(key)
            except Exception:
                pass  # 复核失败则沿用快速扫描数据

        scored = score_seed(rec)
        scored["mc_version"] = cb.MC_VERSION_NAME.get(
            self._scanner.options.version, "") if self._scanner else ""
        with self._db_lock:
            inserted = self.db.insert_seed(
                scored, source=self._scanner.options.task_name if self._scanner else "")
        if inserted and self.on_hit_cb:
            try:
                self.on_hit_cb(scored)
            except Exception:
                pass

    def _handle_finish(self, rc: int):
        sc = self._scanner
        processed, hits = sc.progress()
        duration = time.time() - self._start_time
        status = "完成" if rc == 0 else ("已停止" if rc == 1 else "异常")
        self._log(f"任务结束: {status}  处理 {processed}  命中 {hits}  耗时 {duration:.1f}s")
        self.db.log_task(sc.options.task_name,
                         cb.MC_VERSION_NAME.get(sc.options.version, ""),
                         sc.options.seed_start, sc.options.seed_end,
                         status, processed, hits, duration,
                         time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self._start_time)),
                         time.strftime("%Y-%m-%d %H:%M:%S"))
        with self._lock:
            self._running = False
        # 让写入线程排空剩余命中后退出（等待完成，保证数据完整）
        try:
            self._hit_queue.put_nowait(None)
            if self._writer is not None and self._writer.is_alive():
                self._writer.join(timeout=300)
        except Exception:
            pass
        self._done_event.set()
        if self.on_finish_cb:
            self.on_finish_cb({"rc": rc, "processed": processed, "hits": hits,
                               "duration": duration, "status": status})

    def _handle_error(self, msg: str):
        self._log(f"扫描错误: {msg}", level=logging.ERROR)
        if self.on_error_cb:
            self.on_error_cb(msg)

    # ------------------------------------------------------------------
    # 设备过载保护
    # ------------------------------------------------------------------
    def _monitor_loop(self):
        while self._running and self._scanner and self._scanner.running:
            try:
                self._check_overload()
            except Exception:
                pass
            if self.on_status_cb:
                try:
                    self.on_status_cb(self.status())
                except Exception:
                    pass
            time.sleep(0.5)

    def _check_overload(self):
        if not HAS_PSUTIL or not self._scanner:
            return
        cpu = psutil.cpu_percent(interval=None)
        temp = None
        try:
            temps = psutil.sensors_temperatures()
            for key in ("coretemp", "k10temp", "cpu_thermal", "acpitz"):
                if key in temps and temps[key]:
                    temp = temps[key][0].current
                    break
        except Exception:
            temp = None

        overloaded = cpu >= 90 or (temp is not None and temp >= 85)
        if overloaded:
            if self._overload_since == 0:
                self._overload_since = time.time()
            if time.time() - self._overload_since >= 2.0:
                if not self._scanner._pause.value:
                    self._log(f"检测到设备过载 (CPU {cpu:.0f}%"
                              + (f", 温度 {temp:.0f}°C" if temp else "") + ")，自动降频暂停 5 秒")
                self._scanner.set_pause(True)
                if time.time() - self._overload_since >= 7.0:
                    self._scanner.set_pause(False)
                    self._overload_since = 0
        else:
            self._overload_since = 0
            if self._scanner._pause.value:
                self._scanner.set_pause(False)

    def _log(self, msg: str, level=logging.INFO):
        self._logger.log(level, msg)

    def _notify_error(self, msg: str):
        if self.on_error_cb:
            self.on_error_cb(msg)
