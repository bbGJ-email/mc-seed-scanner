# 全自动智能 MC Java 版种子扫描系统 v1.0

> 底层高性能 C 算力 + 上层 Python 业务，个人独立开发最优方案。
> 对标专业种子猎人工具，支持 1.18 / 1.19 / 1.20 / 1.21 全范围种子高速穷举、
> 多条件组合智能筛选、100 分制评分分级、断点续扫、SQLite 种子库、PyQt5 可视化面板。

---

## 一、功能总览（对应需求六大模块）

| 模块 | 说明 | 实现 |
|---|---|---|
| 1. 高速种子穷举引擎 | 基于 Cubiomes 底层 C 重构，64 位全范围遍历、多线程动态分配、断点续扫、后台静默运行 | `csrc/scanner_core.c` |
| 2. 智能多维筛选系统 | 出生点判定 / 生物群系 / 结构建筑 / 距离自定义 / 地形特征 / 资源特征，多条件组合 + 智能评分（100 分制五档分级） | `mcss/scoring.py` |
| 3. 全自动任务系统 | 全自动批量扫描、去重、自动分类归档、全流程日志、设备过载保护 | `mcss/task_manager.py` |
| 4. 种子数据管理库 | SQLite 轻量库，关键词检索 / 条件筛选 / TXT·JSON 导出 / 黑名单 | `mcss/database.py`、`mcss/exporters.py` |
| 5. 可视化控制面板 | 实时监控扫描速度 / 已扫 / 剩余 / 命中，参数配置，一键导出 / 备份 / 清缓存 | `mcss/gui/main_window.py` |
| 6. 后期拓展预留 | GPU 加速 / 多设备分布式 / 网页展示 / 极品预警（接口已预留） | `ScannerConfig` 扩展字段 |

### 评分分级（总分 100）

| 等级 | 分值 | 说明 |
|---|---|---|
| 绝版顶级神种 S+ | ≥ 90 | 罕见组合：稀有群系 + 关键结构 + 优质地形 |
| 极品神种 S | ≥ 75 | 高价值：多结构 + 舒适出生点 + 优质地形 |
| 精品种子 A | ≥ 65 | 具备明显亮点 |
| 优质种子 B | ≥ 50 | 中规中矩可玩 |
| 普通种子 C | < 50 | 一般 |

评分五维权重：**出生点舒适度 20 + 生物群系 25 + 结构价值 40 + 地形 10 + 资源/特性 5**。
自动标签包括：超大平原、连绵高山、海景、多群系拼接、浮空岛、远古之城、海底神殿、史莱姆出生、蘑菇岛等。

---

## 二、技术栈与目录结构

```
mc-seed-scanner/
├── main.py                 # 程序入口（GUI 或 --cli 命令行模式）
├── config.json             # 命令行模式默认配置
├── requirements.txt        # Python 依赖
├── build_all.sh            # Linux/macOS 一键构建+自检
├── build_windows.bat       # Windows 一键构建+打包 EXE（需 MinGW-w64）
├── csrc/                   # C 底层核心
│   ├── scanner_core.h      #   C 头文件（ScannerConfig / SeedInfo / 接口）
│   ├── scanner_core.c      #   多线程穷举引擎 + 筛选 + 结构 + 要塞 + 断点 + 控制
│   ├── build.sh            #   Linux/macOS 编译脚本
│   ├── build_windows.bat   #   Windows 编译脚本
│   └── cubiomes/           #   Cubiomes 源码（复刻 MC Java 世界生成算法）
├── mcss/                   # Python 业务层
│   ├── core_binding.py     #   ctypes 绑定（结构体逐字段对齐 C）
│   ├── config.py           #   扫描配置 + 4 个快捷预设
│   ├── scanner.py          #   后台扫描线程 + 命中流式读取
│   ├── scoring.py          #   100 分制评分 + 五档分级 + 自动标签
│   ├── database.py         #   SQLite 种子库（seeds/blacklist/tasks/settings）
│   ├── task_manager.py     #   任务调度 + 断点续扫 + 过载保护 + 日志
│   ├── exporters.py        #   TXT / JSON 导出
│   └── gui/main_window.py  #   PyQt5 可视化控制面板
└── data/                   # 运行期自动生成（种子库 / 日志 / 断点 / 导出）
```

---

## 三、快速开始

### Linux / macOS

```bash
bash build_all.sh          # 编译 C 核心 + 安装依赖 + 自检
python3 main.py            # 启动可视化面板
python3 main.py --cli      # 或命令行模式（读取 config.json）
```

### Windows（打包为单文件 EXE）

1. 安装 [MinGW-w64](https://www.mingw-w64.org/)（gcc 加入 PATH）与 Python 3.9+；
2. 双击 `build_windows.bat`；
3. 产物：`dist\MCSeedScanner.exe`，双击即用，无需 Python 环境。

> 打包说明：Windows 下 C 核心编译为 `scanner_core.dll`（库路径由
> `core_binding._find_lib()` 自动探测，支持 PyInstaller `_MEIPASS` 内嵌路径）。

### 命令行模式配置（config.json 关键项）

```json
{
  "task_name": "命令行任务",
  "version": "1.21",            // 1.18 / 1.19 / 1.20 / 1.21
  "seed_start": 0,              // 扫描区间（含）
  "seed_end": 100000000,        // 扫描区间（不含）
  "threads": 0,                 // 0=自动(CPU核心-1)
  "spawn_mode": 1,              // 0原点 / 1快速估计(默认) / 2精确getSpawn
  "structures": ["Village"],    // 需命中的结构
  "struct_radius": 1200,        // 结构判定半径(格)
  "need_any_struct": true,
  "stronghold_radius": 0,       // 0=不要求要塞
  "req_biome": "",              // 稀有群系 key（如 mushroom_fields / deep_dark）
  "req_biome_radius": 1500,
  "verify": true,               // 命中后精确复核（修正出生点/补全结构/地形统计）
  "resume": true                // 断点续扫
}
```

---

## 四、GUI 控制面板使用说明

启动后界面分四区：

- **顶部操作栏**：开始扫描 / 停止 / 暂停 / 断点续扫 / 单种子回查（输入种子号一键 Inspect 复核）。
- **顶部监控面板**：状态、任务名、线程数、已扫种子、命中种子、扫描速度、剩余量、预计剩余时间、进度条。
- **左侧配置面板**：
  - 快捷预设：舒适出生点 / 蘑菇岛开局 / 古城猎手 / 超大平原海景；
  - 任务配置：任务名、MC 版本、扫描区间、线程数、出生点模式；
  - 出生点判定：筛选安全出生点（勾选允许群系：平原、向日葵平原、草甸、樱花林等）；
  - 稀有/多群系：稀有群系目标 + 搜索半径、要求多群系拼接；
  - 结构检测：村庄、要塞、古城、沙漠神殿、丛林神庙、海底遗迹、沉船、海底神殿、林地府邸、掠夺者前哨站、试炼密室等全品类；
  - 要塞地形附加：要塞距离判定、超大平原、连绵高山、海景海岸、史莱姆出生点检测。
- **右侧标签页**：
  - 实时命中：按评分倒序实时刷新（评分 / 等级 / 种子 / 出生点 / 群系 / 结构 / 标签 / 版本），双击可复制种子号；
  - 种子数据库：检索（关键词 / 评分下限 / 等级筛选）、一键导出 TXT / JSON / 纯种子列表、清空缓存、备份数据库、黑名单管理；
  - 任务日志：历次扫描记录（区间 / 状态 / 处理量 / 命中 / 耗时）。

### 断点续扫

扫描过程中停止 / 关机 / 闪退后，重启软件再次点击「开始扫描」，会自动读取 `data/checkpoints/` 下的断点文件，
从上次中断位置继续（同一任务名 + 版本 + 区间唯一对应一个断点），**无重复、无遗漏**。

### 设备过载保护

扫描时每 0.5s 检查一次 CPU 温度 / 使用率（psutil），连续超标时自动暂停扫描并降频，
温度回落自动恢复，防止设备过载、卡死。

---

## 五、性能参考（2 核沙箱实测）

| 配置 | 速度 |
|---|---|
| 仅出生点判定 | ~32,000 种子/秒 |
| + 村庄(1200格) | ~13,000 种子/秒 |
| + 要塞(1500格) | ~28,000 种子/秒 |
| 命中后精确复核(inspect) | 6.4 ms/种子（线程池并行复核） |
| 单点生物群系采样 | ~8 µs/点 |

> 实际速度取决于 CPU 核心数与筛选条件复杂度；多核机器线性提升。
> 说明：`estimateSpawn`/`getSpawn` 在 1.18+ 高达 ~2.5ms/种子，已替换为快速出生点
> 估计算法（复刻 fitness 公式 + 三层粗网格，~172µs/种子，群系吻合率 71%），
> 精确复核由 `scanner_inspect` 在命中后独立完成。

---

## 六、常用结构 / 群系 ID（供二次开发）

**结构**（finders.h）：`Desert_Pyramid=1 Jungle_Temple=2 Swamp_Hut=3 Igloo=4 Village=5
Ocean_Ruin=6 Shipwreck=7 Monument=8 Mansion=9 Outpost=10 Ancient_City=13 Mineshaft=15
Trail_Ruins=23 Trial_Chambers=24`

**群系**（biomes.h）：`plains=1 forest=4 mushroom_fields=14 jungle=21 deep_ocean=24
badlands=37 sunflower_plains=129 flower_forest=132 bamboo_jungle=168 meadow=177
grove=178 snowy_slopes=179 jagged_peaks=180 frozen_peaks=181 stony_peaks=182
deep_dark=183 mangrove_swamp=184 cherry_grove=185 pale_garden=186`

**版本**：`MC_1_18=22 MC_1_19=24 MC_1_20=25 MC_1_21=28`

---

## 七、二次开发

- 新增筛选条件：在 `csrc/scanner_core.c` 的扫描主循环中加判定 → 头文件加字段 →
  `core_binding.py` 的 `ScannerConfig` 同步逐字段对齐 → `config.py` 的 `ScanOptions` 与
  GUI 面板加控件 → 重跑 `csrc/build.sh`。
- 新增预设：在 `mcss/gui/main_window.py` 的 `PRESETS` 字典与 `config.py` 预设中添加。
- 评分调参：`mcss/scoring.py` 顶部的权重常量与各维度函数。
- 新增结构类型：`csrc/scanner_core.c` 的 `common_structs[]` 与 GUI `STRUCTURE_CHOICES`。

---

## 八、常见问题

| 问题 | 解决 |
|---|---|
| 提示找不到 scanner_core 动态库 | 先执行 `csrc/build.sh`（Linux）或 `build_windows.bat`（Windows）；或用环境变量 `MCSS_CORE_LIB` 指定路径 |
| GUI 在无显示器环境 | 设置 `QT_QPA_PLATFORM=offscreen` 可无头运行 |
| 扫描很快结束但没有命中 | 检查筛选条件是否过于严苛，先放宽结构半径 / 群系要求 |
| 打包后 EXE 报缺 DLL | 确认 `scanner_core.dll` 已通过 `--add-binary` 打入，且 MinGW 使用 UCRT 运行时 |
| 断点续扫不生效 | 任务名 / 版本 / 区间必须与上次完全一致 |
