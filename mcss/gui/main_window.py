# -*- coding: utf-8 -*-
"""可视化控制面板主窗口（PyQt5）。

功能：
  * 实时数据监控：扫描速度 / 已扫种子 / 剩余 / 命中数 / 线程状态
  * 自定义参数配置：筛选规则 / 扫描区间 / 线程数 / 地形半径
  * 实时刷新最新命中种子的评分与信息
  * 一键导出 / 清空缓存 / 备份数据库
  * 种子数据库检索、黑名单管理、任务日志
"""
from __future__ import annotations

import os
import sys
import threading
import time

from PyQt5.QtCore import Qt, QObject, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPalette
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QFormLayout, QGroupBox, QLabel, QLineEdit, QPushButton, QComboBox,
    QCheckBox, QSpinBox, QDoubleSpinBox, QTabWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QProgressBar, QSplitter, QMessageBox,
    QFileDialog, QListWidget, QListWidgetItem, QTextEdit, QFrame, QStackedWidget,
    QScrollArea, QToolTip,
)

from .. import core_binding as cb
from ..config import ScanOptions, PRESETS
from ..database import SeedDatabase
from ..task_manager import TaskManager
from ..scoring import TIERS
from .. import exporters

APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(APP_DIR, "data")

TIER_COLORS = {
    "绝版顶级神种": "#b23aee",
    "极品神种": "#e64545",
    "精品种子": "#f0a500",
    "优质种子": "#2e9e44",
    "普通种子": "#808080",
}

STRUCTURE_CHOICES = [
    ("Village", "村庄"), ("Ancient_City", "远古之城"), ("Monument", "海底神殿"),
    ("Mansion", "林地府邸"), ("Outpost", "掠夺者前哨站"), ("Desert_Pyramid", "沙漠神殿"),
    ("Jungle_Temple", "丛林神庙"), ("Igloo", "雪屋"), ("Swamp_Hut", "女巫小屋"),
    ("Trail_Ruins", "古迹废墟"), ("Trial_Chambers", "试炼密室"), ("Ocean_Ruin", "海底废墟"),
    ("Shipwreck", "沉船"), ("Mineshaft", "废弃矿井"),
]

BIOME_CHOICES = [
    ("plains", "平原"), ("sunflower_plains", "向日葵平原"), ("meadow", "草甸"),
    ("cherry_grove", "樱花林"), ("forest", "森林"), ("flower_forest", "繁花森林"),
    ("birch_forest", "白桦林"), ("savanna", "热带草原"), ("savanna_plateau", "热带草原高地"),
    ("desert", "沙漠"), ("badlands", "恶地"), ("jungle", "丛林"), ("bamboo_jungle", "竹林"),
    ("taiga", "针叶林"), ("swamp", "沼泽"), ("mangrove_swamp", "红树林沼泽"),
    ("mushroom_fields", "蘑菇岛"), ("ice_spikes", "冰刺之地"), ("snowy_plains", "雪原"),
    ("deep_dark", "深暗之域"), ("stony_peaks", "石峰"), ("jagged_peaks", "尖峭之峰"),
    ("frozen_peaks", "冰封之峰"), ("windswept_hills", "风袭丘陵"), ("pale_garden", "苍白庭院"),
]

RARE_BIOME_CHOICES = [("", "关闭")] + [
    ("mushroom_fields", "蘑菇岛"), ("deep_dark", "深暗之域"), ("cherry_grove", "樱花林"),
    ("bamboo_jungle", "竹林"), ("badlands", "恶地"), ("ice_spikes", "冰刺之地"),
    ("flower_forest", "繁花森林"), ("mangrove_swamp", "红树林沼泽"), ("pale_garden", "苍白庭院"),
]


class Signals(QObject):
    """跨线程信号桥：TaskManager 回调 → GUI 主线程。"""
    hit = pyqtSignal(dict)
    status = pyqtSignal(dict)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)


# ===========================================================================
# 配置面板
# ===========================================================================
class ConfigPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)

        # ---- 预设 ----
        preset_box = QGroupBox("快捷预设")
        pl = QHBoxLayout(preset_box)
        self.preset_combo = QComboBox()
        self.preset_combo.addItem("自定义")
        for name in PRESETS:
            self.preset_combo.addItem(name)
        self.preset_combo.currentTextChanged.connect(self._apply_preset)
        pl.addWidget(self.preset_combo)
        lay.addWidget(preset_box)

        # ---- 任务配置 ----
        task_box = QGroupBox("任务配置")
        tf = QFormLayout(task_box)
        self.task_name = QLineEdit("默认任务")
        self.mc_version = QComboBox()
        for v in ("1.21", "1.20", "1.19", "1.18"):
            self.mc_version.addItem(v)
        self.seed_start = QLineEdit("0")
        self.seed_end = QLineEdit("100000000")
        self.threads = QSpinBox()
        self.threads.setRange(0, 128)
        self.threads.setSpecialValueText("自动(CPU-1)")
        self.threads.setValue(0)
        self.spawn_mode = QComboBox()
        self.spawn_mode.addItems(["原点(最快)", "快速估计(默认)", "精确getSpawn(慢)"])
        self.spawn_mode.setCurrentIndex(1)
        tf.addRow("任务名", self.task_name)
        tf.addRow("MC 版本", self.mc_version)
        tf.addRow("起始种子", self.seed_start)
        tf.addRow("结束种子", self.seed_end)
        tf.addRow("线程数", self.threads)
        tf.addRow("出生点模式", self.spawn_mode)
        lay.addWidget(task_box)

        # ---- 出生点 ----
        spawn_box = QGroupBox("出生点判定")
        sl = QVBoxLayout(spawn_box)
        self.check_spawn = QCheckBox("筛选安全出生点（舒适群系）")
        self.check_spawn.setChecked(True)
        sl.addWidget(self.check_spawn)
        sl.addWidget(QLabel("出生点允许群系："))
        self.biome_list = QListWidget()
        self.biome_list.setMaximumHeight(120)
        for key, name in BIOME_CHOICES:
            it = QListWidgetItem(f"{name}({key})")
            it.setData(Qt.UserRole, key)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if key in (
                "plains", "sunflower_plains", "meadow", "cherry_grove",
                "forest", "flower_forest", "birch_forest", "savanna", "savanna_plateau") else Qt.Unchecked)
            self.biome_list.addItem(it)
        sl.addWidget(self.biome_list)
        lay.addWidget(spawn_box)

        # ---- 群系 ----
        bio_box = QGroupBox("稀有 / 多群系")
        bf = QFormLayout(bio_box)
        self.req_biome = QComboBox()
        for key, name in RARE_BIOME_CHOICES:
            self.req_biome.addItem(name, key)   # userData 存群系 key（如 "mushroom_fields"）
        self.req_radius = QSpinBox(); self.req_radius.setRange(200, 10000); self.req_radius.setValue(1500)
        self.req_radius.setSuffix(" 格")
        self.check_multi = QCheckBox("要求多群系拼接（≥3 种）")
        bf.addRow("稀有群系", self.req_biome)
        bf.addRow("搜索半径", self.req_radius)
        bf.addRow("", self.check_multi)
        lay.addWidget(bio_box)

        # ---- 结构 ----
        struct_box = QGroupBox("结构检测")
        sgl = QGridLayout(struct_box)
        self.struct_checks = {}
        for i, (key, name) in enumerate(STRUCTURE_CHOICES):
            chk = QCheckBox(name)
            if key == "Village":
                chk.setChecked(True)
            self.struct_checks[key] = chk
            sgl.addWidget(chk, i // 2, i % 2)
        self.struct_radius = QSpinBox()
        self.struct_radius.setRange(200, 8000); self.struct_radius.setValue(1200)
        self.struct_radius.setSuffix(" 格")
        self.need_any_struct = QCheckBox("至少命中一种结构")
        self.need_any_struct.setChecked(True)
        sgl.addWidget(QLabel("搜索半径"), 7, 0)
        sgl.addWidget(self.struct_radius, 7, 1)
        sgl.addWidget(self.need_any_struct, 8, 0, 1, 2)
        lay.addWidget(struct_box)

        # ---- 要塞 / 地形 / 附加 ----
        misc_box = QGroupBox("要塞 / 地形 / 附加")
        mf = QFormLayout(misc_box)
        self.stronghold_radius = QSpinBox()
        self.stronghold_radius.setRange(0, 8000); self.stronghold_radius.setValue(0)
        self.stronghold_radius.setSuffix(" 格 (0=不查)")
        self.need_stronghold = QCheckBox("必须含要塞")
        self.check_plains = QCheckBox("超大平原")
        self.check_mountains = QCheckBox("连绵高山")
        self.check_coast = QCheckBox("海景")
        self.terrain_radius = QSpinBox()
        self.terrain_radius.setRange(200, 4000); self.terrain_radius.setValue(800)
        self.terrain_radius.setSuffix(" 格")
        self.check_slime = QCheckBox("出生点史莱姆区块")
        mf.addRow("要塞半径", self.stronghold_radius)
        mf.addRow("", self.need_stronghold)
        mf.addRow("地形", self.check_plains)
        mf.addRow("", self.check_mountains)
        mf.addRow("", self.check_coast)
        mf.addRow("地形半径", self.terrain_radius)
        mf.addRow("", self.check_slime)
        lay.addWidget(misc_box)

        lay.addStretch(1)

    def _apply_preset(self, name: str):
        if name not in PRESETS:
            return
        o = PRESETS[name]()
        self._load_options(o)

    def _load_options(self, o: ScanOptions):
        self.task_name.setText(o.task_name)
        self.mc_version.setCurrentText(cb.MC_VERSION_NAME.get(o.version, "1.21"))
        self.seed_start.setText(str(o.seed_start))
        self.seed_end.setText(str(o.seed_end))
        self.threads.setValue(o.threads)
        self.spawn_mode.setCurrentIndex(o.spawn_mode)
        self.check_spawn.setChecked(o.check_spawn)
        for i in range(self.biome_list.count()):
            it = self.biome_list.item(i)
            it.setCheckState(Qt.Checked if it.data(Qt.UserRole) in o.safe_spawn_biomes else Qt.Unchecked)
        key = cb.B_NAME.get(o.req_biome, "") if o.req_biome != -1 else ""
        idx = self.req_biome.findData(key)
        self.req_biome.setCurrentIndex(max(0, idx))
        self.req_radius.setValue(o.req_biome_radius)
        self.check_multi.setChecked(o.check_multi_biome)
        for key, chk in self.struct_checks.items():
            chk.setChecked(key in o.structures)
        self.struct_radius.setValue(o.struct_radius)
        self.need_any_struct.setChecked(o.need_any_struct)
        self.stronghold_radius.setValue(o.stronghold_radius)
        self.need_stronghold.setChecked(o.need_stronghold)
        self.check_plains.setChecked(o.check_big_plains)
        self.check_mountains.setChecked(o.check_mountains)
        self.check_coast.setChecked(o.check_coast)
        self.terrain_radius.setValue(o.terrain_radius)
        self.check_slime.setChecked(o.check_slime)

    def to_options(self) -> ScanOptions:
        o = ScanOptions()
        o.task_name = self.task_name.text().strip() or "默认任务"
        o.version = cb.MC_VERSION_BY_NAME.get(self.mc_version.currentText(), cb.MC_1_21)
        o.seed_start = int(self.seed_start.text().strip() or "0")
        o.seed_end = int(self.seed_end.text().strip() or "100000000")
        o.threads = self.threads.value()
        o.spawn_mode = self.spawn_mode.currentIndex()
        o.check_spawn = self.check_spawn.isChecked()
        o.safe_spawn_biomes = [
            cb.B.get(self.biome_list.item(i).data(Qt.UserRole), -1)
            for i in range(self.biome_list.count())
            if self.biome_list.item(i).checkState() == Qt.Checked
        ]
        o.safe_spawn_biomes = [b for b in o.safe_spawn_biomes if b >= 0]
        if not o.safe_spawn_biomes:
            o.safe_spawn_biomes = cb.default_safe_spawn_biomes()
        o.req_biome = cb.B.get(self.req_biome.currentData() or "", -1)
        o.req_biome_radius = self.req_radius.value()
        o.check_multi_biome = self.check_multi.isChecked()
        o.structures = [k for k, chk in self.struct_checks.items() if chk.isChecked()]
        o.struct_radius = self.struct_radius.value()
        o.need_any_struct = self.need_any_struct.isChecked()
        o.stronghold_radius = self.stronghold_radius.value()
        o.need_stronghold = self.need_stronghold.isChecked()
        o.check_big_plains = self.check_plains.isChecked()
        o.check_mountains = self.check_mountains.isChecked()
        o.check_coast = self.check_coast.isChecked()
        o.terrain_radius = self.terrain_radius.value()
        o.check_slime = self.check_slime.isChecked()
        return o


# ===========================================================================
# 监控面板
# ===========================================================================
class MonitorPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QGridLayout(self)
        self._labels = {}
        items = [
            ("状态", "空闲"), ("任务", "-"), ("线程", "-"),
            ("已扫种子", "0"), ("命中种子", "0"), ("速度", "0 /s"),
            ("剩余", "-"), ("预计剩余", "-"), ("进度", "0%"),
        ]
        for i, (k, v) in enumerate(items):
            box = QFrame(); box.setFrameShape(QFrame.StyledPanel)
            bl = QVBoxLayout(box)
            bl.setContentsMargins(8, 4, 8, 4)
            lbl_k = QLabel(k); lbl_k.setStyleSheet("color:#888; font-size:11px;")
            lbl_v = QLabel(v)
            lbl_v.setStyleSheet("font-size:16px; font-weight:bold;")
            lbl_v.setAlignment(Qt.AlignCenter)
            bl.addWidget(lbl_k); bl.addWidget(lbl_v)
            self._labels[k] = lbl_v
            lay.addWidget(box, i // 3, i % 3)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        lay.addWidget(self.progress, 3, 0, 1, 3)

    def update_status(self, s: dict):
        self._labels["状态"].setText("扫描中" if s["running"] else ("已暂停" if s.get("paused") else "空闲"))
        self._labels["任务"].setText(s["task_name"] or "-")
        self._labels["线程"].setText(str(s["threads"]) or "-")
        self._labels["已扫种子"].setText(f"{s['processed']:,}")
        self._labels["命中种子"].setText(f"{s['hits']:,}")
        self._labels["速度"].setText(f"{s['speed']:,.0f}/s")
        self._labels["剩余"].setText(f"{s['remaining']:,}" if s["total"] else "-")
        self._labels["预计剩余"].setText(_fmt_eta(s["eta"]) if s["eta"] else "-")
        pct = (s["processed"] / s["total"] * 100) if s["total"] else 0
        self._labels["进度"].setText(f"{pct:.1f}%")
        self.progress.setValue(int(pct * 10))


def _fmt_eta(sec: float) -> str:
    sec = int(sec)
    if sec < 60:
        return f"{sec} 秒"
    if sec < 3600:
        return f"{sec // 60} 分 {sec % 60} 秒"
    return f"{sec // 3600} 时 {sec % 3600 // 60} 分"


# ===========================================================================
# 命中列表
# ===========================================================================
class HitsTable(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(8)
        self.setHorizontalHeaderLabels(["评分", "等级", "种子", "出生点", "群系", "结构", "标签", "版本"])
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setSortingEnabled(False)
        self._limit = 2000

    def add_hit(self, rec: dict):
        tier = rec.get("tier", "普通种子")
        color = TIER_COLORS.get(tier, "#808080")
        row = self.rowCount()
        self.insertRow(0)
        score_item = QTableWidgetItem(str(rec.get("score", 0)))
        score_item.setForeground(QColor(color))
        score_item.setTextAlignment(Qt.AlignCenter)
        tier_item = QTableWidgetItem(tier)
        tier_item.setForeground(QColor(color))
        tier_item.setTextAlignment(Qt.AlignCenter)
        structs = "、".join(s["name"] for s in rec.get("structures", [])[:4]) or "无"
        tags = "、".join(rec.get("tags", [])[:4]) or "-"
        items = [
            score_item, tier_item,
            QTableWidgetItem(str(rec.get("seed"))),
            QTableWidgetItem(f"({rec.get('spawn_x')}, {rec.get('spawn_z')})"),
            QTableWidgetItem(rec.get("spawn_biome_name", "")),
            QTableWidgetItem(structs),
            QTableWidgetItem(tags),
            QTableWidgetItem(rec.get("mc_version", "")),
        ]
        for c, it in enumerate(items):
            self.setItem(0, c, it)
        while self.rowCount() > self._limit:
            self.removeRow(self.rowCount() - 1)
        if self.rowCount() > 0:
            self.selectRow(0)


# ===========================================================================
# 数据库页
# ===========================================================================
class DatabaseTab(QWidget):
    def __init__(self, db: SeedDatabase, parent=None):
        super().__init__(parent)
        self.db = db
        lay = QVBoxLayout(self)

        # 检索栏
        bar = QHBoxLayout()
        bar.addWidget(QLabel("关键词:"))
        self.search_keyword = QLineEdit()
        self.search_keyword.setPlaceholderText("种子号 / 群系 / 标签 / 来源")
        bar.addWidget(self.search_keyword, 3)
        bar.addWidget(QLabel("最低分:"))
        self.min_score = QSpinBox(); self.min_score.setRange(0, 100); self.min_score.setValue(0)
        bar.addWidget(self.min_score)
        bar.addWidget(QLabel("等级:"))
        self.tier_filter = QComboBox()
        self.tier_filter.addItems(["全部", "绝版顶级神种", "极品神种", "精品种子", "优质种子", "普通种子"])
        bar.addWidget(self.tier_filter)
        self.btn_search = QPushButton("检索")
        self.btn_search.clicked.connect(self.refresh)
        bar.addWidget(self.btn_search)
        self.btn_export = QPushButton("导出 TXT/JSON")
        self.btn_export.clicked.connect(self.export)
        bar.addWidget(self.btn_export)
        self.btn_blacklist = QPushButton("加入黑名单")
        self.btn_blacklist.clicked.connect(self.blacklist)
        bar.addWidget(self.btn_blacklist)
        self.btn_backup = QPushButton("备份数据库")
        self.btn_backup.clicked.connect(self.backup)
        bar.addWidget(self.btn_backup)
        self.btn_clear = QPushButton("清空缓存")
        self.btn_clear.clicked.connect(self.clear_cache)
        bar.addWidget(self.btn_clear)
        lay.addLayout(bar)

        # 统计
        self.stat_label = QLabel("")
        lay.addWidget(self.stat_label)

        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(10)
        self.table.setHorizontalHeaderLabels(
            ["种子", "评分", "等级", "出生点", "群系", "结构", "要塞", "标签", "来源", "时间"])
        self.table.horizontalHeader().setSectionResizeMode(8, QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        lay.addWidget(self.table)

        self.refresh()

    def refresh(self):
        kw = self.search_keyword.text().strip()
        tier = self.tier_filter.currentText()
        tier = "" if tier == "全部" else tier
        rows = self.db.query(keyword=kw, min_score=self.min_score.value(),
                             tier=tier, limit=1000)
        self.table.setRowCount(0)
        for r in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            tier_name = r.get("tier", "")
            color = TIER_COLORS.get(tier_name, "#808080")
            score_item = QTableWidgetItem(str(r.get("score", 0)))
            score_item.setForeground(QColor(color))
            tier_item = QTableWidgetItem(tier_name)
            tier_item.setForeground(QColor(color))
            sh = r.get("stronghold_x")
            stronghold = f"({sh},{r.get('stronghold_z')})" if sh is not None else "-"
            structs = "、".join(s["name"] for s in r.get("structures", [])[:3]) or "无"
            items = [
                QTableWidgetItem(str(r.get("seed"))), score_item, tier_item,
                QTableWidgetItem(f"({r.get('spawn_x')}, {r.get('spawn_z')})"),
                QTableWidgetItem(r.get("spawn_biome_name", "")),
                QTableWidgetItem(structs),
                QTableWidgetItem(stronghold),
                QTableWidgetItem("、".join(r.get("tags", [])[:4])),
                QTableWidgetItem(r.get("source", "")),
                QTableWidgetItem(r.get("created_at", "")),
            ]
            for c, it in enumerate(items):
                self.table.setItem(row, c, it)
        cnt = self.db.count()
        bt = " ".join(f"{k}:{v}" for k, v in cnt.get("by_tier", {}).items()) or "暂无"
        self.stat_label.setText(
            f"共 {cnt.get('total', 0)} 条种子 | 最高分 {cnt.get('top', 0)} | {bt}")

    def selected_seeds(self) -> list:
        return [int(self.table.item(r, 0).text()) for r in sorted({i.row() for i in self.table.selectedItems()})]

    def export(self):
        rows = self.db.query(keyword=self.search_keyword.text().strip(),
                             min_score=self.min_score.value(),
                             tier="" if self.tier_filter.currentText() == "全部" else self.tier_filter.currentText(),
                             limit=100000)
        if not rows:
            QMessageBox.information(self, "导出", "没有可导出的数据")
            return
        path, _ = QFileDialog.getSaveFileName(self, "保存导出文件", "seeds_export", "文本 (*.txt);;JSON (*.json)")
        if not path:
            return
        if path.endswith(".json"):
            exporters.export_json(rows, path)
        else:
            if not path.endswith(".txt"):
                path += ".txt"
            exporters.export_txt(rows, path)
        QMessageBox.information(self, "导出", f"已导出 {len(rows)} 条到\n{path}")

    def blacklist(self):
        seeds = self.selected_seeds()
        if not seeds:
            QMessageBox.warning(self, "黑名单", "请先选中要拉黑的种子行")
            return
        n = self.db.add_blacklist(seeds)
        self.refresh()
        QMessageBox.information(self, "黑名单", f"已将 {n} 个种子加入黑名单并移除")

    def backup(self):
        path, _ = QFileDialog.getSaveFileName(self, "备份数据库", "seeds_backup.db", "数据库 (*.db)")
        if not path:
            return
        ok = self.db.backup(path)
        QMessageBox.information(self, "备份", "备份成功" if ok else "备份失败")

    def clear_cache(self):
        if QMessageBox.question(self, "清空缓存", "确认清空全部种子数据？此操作不可恢复。",
                                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            n = self.db.clear_seeds()
            self.refresh()
            QMessageBox.information(self, "清空", f"已清空 {n} 条种子")


# ===========================================================================
# 任务日志页
# ===========================================================================
class TaskLogTab(QWidget):
    def __init__(self, db: SeedDatabase, parent=None):
        super().__init__(parent)
        self.db = db
        lay = QVBoxLayout(self)
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.clicked.connect(self.refresh)
        lay.addWidget(self.btn_refresh)
        self.table = QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels(
            ["ID", "任务名", "版本", "区间", "状态", "处理", "命中", "耗时", "时间"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        lay.addWidget(self.table)
        self.refresh()

    def refresh(self):
        tasks = self.db.tasks(limit=50)
        self.table.setRowCount(0)
        for t in tasks:
            row = self.table.rowCount()
            self.table.insertRow(row)
            items = [
                str(t["id"]), t["name"], t["version"],
                f"[{t['seed_start']}, {t['seed_end']})", t["status"],
                f"{t['processed']:,}", str(t["hits"]),
                f"{t['duration_sec']:.1f}s" if t["duration_sec"] else "-",
                t["finished_at"] or t["started_at"] or "",
            ]
            for c, it in enumerate(items):
                self.table.setItem(row, c, QTableWidgetItem(it))


# ===========================================================================
# 主窗口
# ===========================================================================
class MainWindow(QMainWindow):
    def __init__(self, db: SeedDatabase = None, task_manager: TaskManager = None):
        super().__init__()
        self.setWindowTitle("全自动智能 MC Java 种子扫描系统 v1.0")
        self.resize(1280, 820)

        self.db = db or SeedDatabase(os.path.join(DATA_DIR, "seeds.db"))
        self.tm = task_manager or TaskManager(
            self.db,
            log_dir=os.path.join(DATA_DIR, "logs"),
            checkpoint_dir=os.path.join(DATA_DIR, "checkpoints"),
            verify=True, verify_spawn_mode=1,
        )

        self.signals = Signals()
        self.tm.on_hit_cb = self.signals.hit.emit
        self.tm.on_status_cb = self.signals.status.emit
        self.tm.on_finish_cb = self.signals.finished.emit
        self.tm.on_error_cb = self.signals.error.emit
        self.signals.hit.connect(self._on_hit)
        self.signals.status.connect(self._on_status)
        self.signals.finished.connect(self._on_finished)
        self.signals.error.connect(self._on_error)

        self._build_ui()

        # 定时刷新监控（防卡顿，低频轮询）
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(800)

    # ------------------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # 控制条
        ctrl = QHBoxLayout()
        self.btn_start = QPushButton("开始扫描")
        self.btn_start.setStyleSheet("background:#2e9e44;color:white;font-weight:bold;padding:8px;")
        self.btn_start.clicked.connect(self.start_scan)
        self.btn_stop = QPushButton("停止")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_scan)
        self.btn_pause = QPushButton("暂停")
        self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(self.toggle_pause)
        self.btn_resume = QPushButton("断点续扫")
        self.btn_resume.clicked.connect(self.resume_scan)
        self.btn_inspect = QPushButton("单种子回查")
        self.btn_inspect.clicked.connect(self.inspect_seed)
        self.seed_box = QLineEdit()
        self.seed_box.setPlaceholderText("输入种子号")
        self.seed_box.setMaximumWidth(180)
        for b in (self.btn_start, self.btn_stop, self.btn_pause, self.btn_resume, self.btn_inspect, self.seed_box):
            ctrl.addWidget(b)
        root.addLayout(ctrl)

        # 监控条
        self.monitor = MonitorPanel()
        root.addWidget(self.monitor)

        # 主体：左配置 + 右内容
        split = QSplitter(Qt.Horizontal)
        self.config_panel = ConfigPanel()
        scroll = QScrollArea()
        scroll.setWidget(self.config_panel)
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(360)
        scroll.setMaximumWidth(460)

        tabs = QTabWidget()
        hits_wrap = QWidget()
        hl = QVBoxLayout(hits_wrap)
        hl.addWidget(QLabel("实时命中（按评分倒序，最新置顶）"))
        self.hits_table = HitsTable()
        hl.addWidget(self.hits_table)
        tabs.addTab(hits_wrap, "实时命中")
        self.db_tab = DatabaseTab(self.db)
        tabs.addTab(self.db_tab, "种子数据库")
        self.log_tab = TaskLogTab(self.db)
        tabs.addTab(self.log_tab, "任务日志")

        split.addWidget(scroll)
        split.addWidget(tabs)
        split.setSizes([400, 880])
        root.addWidget(split, 1)

    # ------------------------------------------------------------------
    def _options(self) -> ScanOptions:
        o = self.config_panel.to_options()
        o.checkpoint_dir = os.path.join(DATA_DIR, "checkpoints")
        return o

    def start_scan(self):
        if self.tm.running:
            return
        try:
            o = self._options()
            errs = o.validate()
            if errs:
                QMessageBox.warning(self, "配置错误", "\n".join(errs))
                return
            self.hits_table.setRowCount(0)
            self.tm.start(o, resume=False)
            self._set_running_ui(True)
        except Exception as e:
            QMessageBox.critical(self, "启动失败", str(e))

    def resume_scan(self):
        if self.tm.running:
            return
        try:
            o = self._options()
            ckpt = self.tm.read_checkpoint(o)
            if ckpt is None:
                QMessageBox.information(self, "断点续扫", "没有找到断点，将从头开始")
                self.tm.start(o, resume=False)
            else:
                self.tm.start(o, resume=True)
            self._set_running_ui(True)
        except Exception as e:
            QMessageBox.critical(self, "续扫失败", str(e))

    def stop_scan(self):
        self.tm.stop()

    def toggle_pause(self):
        if self._paused:
            self.tm.set_pause(False)
            self._paused = False
            self.btn_pause.setText("暂停")
        else:
            self.tm.set_pause(True)
            self._paused = True
            self.btn_pause.setText("继续")

    def inspect_seed(self):
        txt = self.seed_box.text().strip()
        if not txt:
            QMessageBox.information(self, "单种子回查", "请先输入种子号")
            return
        try:
            seed = int(txt)
            version = cb.MC_VERSION_BY_NAME.get(self.config_panel.mc_version.currentText(), cb.MC_1_21)
        except ValueError:
            QMessageBox.warning(self, "输入错误", "种子号必须是整数")
            return
        threading.Thread(target=self._do_inspect, args=(version, seed), daemon=True).start()

    def _do_inspect(self, version, seed):
        try:
            info = cb.inspect(version, seed, 800, 2)
            from ..scoring import score_seed
            rec = {
                "seed": seed,
                "spawn_x": info.spawn_x, "spawn_z": info.spawn_z,
                "spawn_biome": info.spawn_biome,
                "spawn_biome_name": cb.B_NAME.get(info.spawn_biome, str(info.spawn_biome)),
                "biome_count": info.biome_count,
                "has_ocean": bool(info.has_ocean), "has_mountains": bool(info.has_mountains),
                "flat_score": info.flat_score, "slime_spawn": bool(info.slime_spawn),
                "structures": [{"type": info.hit_type[i], "name": cb.ST_NAME.get(info.hit_type[i], str(info.hit_type[i])),
                                "x": info.hit_x[i], "z": info.hit_z[i]} for i in range(info.n_hits)],
                "stronghold": {"x": info.stronghold_x, "z": info.stronghold_z} if info.has_stronghold else None,
            }
            rec["mc_version"] = cb.MC_VERSION_NAME.get(version, "")
            scored = score_seed(rec)
            self.signals.hit.emit(scored)  # 展示到实时命中
            QMessageBox.information(self, "单种子回查",
                                    f"种子 {seed} [{version}]\n"
                                    f"出生点({info.spawn_x},{info.spawn_z}) 群系 {scored['spawn_biome_name']}\n"
                                    f"评分 {scored['score']} [{scored['tier']}]\n"
                                    f"结构: {'、'.join(s['name'] for s in scored['structures']) or '无'}\n"
                                    f"标签: {'、'.join(scored['tags'])}")
        except Exception as e:
            self.signals.error.emit(f"单种子回查失败: {e}")

    # ------------------------------------------------------------------
    def _set_running_ui(self, running: bool):
        self.btn_start.setEnabled(not running)
        self.btn_resume.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self.btn_pause.setEnabled(running)
        self._paused = False
        self.btn_pause.setText("暂停")

    def _on_hit(self, rec: dict):
        self.hits_table.add_hit(rec)

    def _on_status(self, s: dict):
        self.monitor.update_status(s)

    def _on_finished(self, info: dict):
        self._set_running_ui(False)
        self.db_tab.refresh()
        self.log_tab.refresh()
        self.monitor.update_status(self.tm.status())

    def _on_error(self, msg: str):
        self._set_running_ui(False)
        QMessageBox.critical(self, "错误", msg)

    def _poll(self):
        """低频轮询兜底（信号丢失保护）。"""
        if self.tm.running:
            self.monitor.update_status(self.tm.status())

    def closeEvent(self, event):
        if self.tm.running:
            if QMessageBox.question(self, "退出", "扫描进行中，确定退出？（将保存断点，可续扫）",
                                    QMessageBox.Yes | QMessageBox.No) == QMessageBox.No:
                event.ignore()
                return
            self.tm.stop()
        try:
            self.db.close()
        except Exception:
            pass
        event.accept()


def run():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())
