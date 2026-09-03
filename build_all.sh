#!/usr/bin/env bash
# ============================================================
#  全自动智能 MC Java 种子扫描系统 - Linux/macOS 一键构建 + 自检
#  用法: bash build_all.sh
# ============================================================
set -e
cd "$(dirname "$0")"

echo "[1/3] 编译 C 核心 (cubiomes + scanner_core.so) ..."
bash csrc/build.sh

echo "[2/3] 安装 Python 依赖 ..."
pip3 install -r requirements.txt 2>/dev/null || true

echo "[3/3] 运行核心链路自检 ..."
python3 - <<'PY'
import sys
sys.path.insert(0, ".")
import mcss
from mcss import core_binding as cb
print(f"  [OK] 加载核心库: {cb._lib._name}")
info = cb.inspect(cb.MC_1_21, 1956, 800, 1)
print(f"  [OK] inspect 种子1956: 出生点({info.spawn_x},{info.spawn_z}) "
      f"群系={cb.B_NAME.get(info.spawn_biome)} 结构={info.n_hits}处")
print("  [OK] 核心链路自检通过")
PY

echo ""
echo "============================================================"
echo "  构建完成！启动方式:"
echo "    python3 main.py          # 可视化控制面板"
echo "    python3 main.py --cli    # 命令行模式"
echo "============================================================"
