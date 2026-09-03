/* ============================================================================
 * 全自动智能 MC Java 种子扫描系统 —— C 高速扫描核心
 * scanner_core.h
 *
 * 基于 Cubiomes 库（Cubitect/cubiomes）复刻 MC Java 版世界生成算法，
 * 为上层 Python 提供超高速种子穷举、多维筛选与结构检测能力。
 *
 * 设计要点：
 *   - 纯 C 实现，单次种子评估无游戏启动损耗，对标专业种子猎人工具
 *   - 全局原子取号（work-stealing）式多线程，支持任意核数自动适配
 *   - 断点续扫：由监督线程周期性原子写入 checkpoint，进程重启后无缝接续
 *   - 停止 / 暂停双控制标志，供上层做"设备过载自动降频"
 * ==========================================================================*/
#ifndef SCANNER_CORE_H_
#define SCANNER_CORE_H_

#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* 结构体类型最大数量（一次扫描可同时检测的结构品类上限） */
#define SCANNER_MAX_STRUCTS   24
/* 每个种子最多记录的结构实例数 */
#define SCANNER_MAX_HITS      48
/* 每个种子结果行缓冲区大小 */
#define SCANNER_LINE_MAX      512

/* --------------------------------------------------------------------------
 * 扫描配置：Python 通过 ctypes 按该布局原样传入（注意字段顺序不可改）
 * ------------------------------------------------------------------------*/
typedef struct
{
    int      version;           /* MCVersion 枚举（MC_1_18 / MC_1_19 / MC_1_20 / MC_1_21）*/
    int64_t  seed_start;        /* 起始种子（含）*/
    int64_t  seed_end;          /* 结束种子（不含）*/
    int      threads;           /* 工作线程数（自动按 CPU 核数适配）*/
    int      spawn_mode;        /* 出生点参考：0=原点(最快) 1=快速估计(默认) 2=精确getSpawn(最慢) */

    /* ---- 出生点判定 ---- */
    int      check_spawn;       /* 1=开启安全出生点过滤 */
    uint64_t spawn_ok_biomesL;  /* 出生点允许群系位图，ID 0-63 */
    uint64_t spawn_ok_biomesM;  /* 出生点允许群系位图，ID 128-191 */

    /* ---- 稀有 / 多群系 ---- */
    int      req_biome;         /* 需要检测的稀有群系 ID，-1=关闭 */
    int      req_biome_radius;  /* 在出生点周围多少格内搜索该群系 */
    int      req_biome_count;   /* 至少命中多少个采样点 */
    int      check_multi_biome; /* 1=要求出生点周围出现 >=3 种不同群系（多群系拼接地形）*/

    /* ---- 结构检测 ---- */
    int      structures[SCANNER_MAX_STRUCTS]; /* 要检测的结构类型数组 */
    int      n_struct;          /* 结构类型数量 */
    int      struct_radius;     /* 结构搜索半径（格，相对出生点）*/
    int      stronghold_radius; /* 要塞搜索半径（格，相对出生点），<=0 表示不查 */
    int      need_any_struct;   /* 1=要求至少命中一种结构，0=仅记录 */
    int      need_stronghold;   /* 1=要求出生点半径内必须有要塞 */

    /* ---- 地形特征（基于群系 + 地形代理启发式）---- */
    int      check_big_plains;  /* 1=检测超大平原 */
    int      check_mountains;   /* 1=检测连绵高山 */
    int      check_coast;       /* 1=检测海景（出生点旁有大片海洋）*/
    int      terrain_radius;    /* 地形采样半径（格）*/

    /* ---- 附加 ---- */
    int      check_slime;       /* 1=要求出生点区块为史莱姆区块 */

    /* ---- IO / 断点 / 控制 ---- */
    int      out_fd;            /* 命中结果输出 fd（>=0 时写入，单次 write 原子）*/
    char     out_path[512];     /* 命中结果输出文件路径（追加写，跨平台主路径）*/
    char     checkpoint_path[512]; /* 断点文件路径 */
    int      write_checkpoint;  /* 1=启用断点写入 */

    volatile int *stop_flag;    /* 1=请求停止（共享内存，ctypes 传入）*/
    volatile int *pause_flag;   /* 1=请求暂停（共享内存，ctypes 传入）*/
    int      batch;             /* 每线程每次原子领取的种子批大小（建议 64-256）*/
    int      quiet;             /* 1=不向 stdout 打印扫描统计 */
} ScannerConfig;

/* 单种子评估结果（用于 scanner_inspect 精确回查）*/
typedef struct
{
    int64_t seed;
    int     spawn_x, spawn_z;      /* 精确出生点（getSpawn）*/
    int     est_x, est_z;          /* 快速估算出生点（estimateSpawn）*/
    int     spawn_biome;           /* 出生点群系 ID */
    int     biome_count;           /* 地形采样半径内不同群系数 */
    int     has_ocean;             /* 出生点附近是否见海 */
    int     has_mountains;         /* 是否见高山/山峰群系 */
    int     flat_score;            /* 平原覆盖度 0-100 */
    int     n_hits;                /* 命中结构实例数 */
    int     hit_type[SCANNER_MAX_HITS];
    int     hit_x[SCANNER_MAX_HITS];
    int     hit_z[SCANNER_MAX_HITS];
    int     has_stronghold;        /* 半径内是否有要塞 */
    int     stronghold_x, stronghold_z;
    int     slime_spawn;           /* 出生点区块是否史莱姆区块 */
} SeedInfo;

/* --------------------------------------------------------------------------
 * 函数接口
 * ------------------------------------------------------------------------*/

/* 运行一次扫描（阻塞直至完成/停止/出错）。
 * 返回：0=正常完成  1=被 stop_flag 停止  2=区间为空   -1=参数错误  -2=初始化失败
 */
int scanner_run(const ScannerConfig *cfg);

/* 当前已完成的种子数（供上层轮询进度）*/
int64_t scanner_processed(void);

/* 当前命中的种子数 */
int64_t scanner_hits(void);

/* 单种子精确回查：评估并填充 info（radius 为地形采样半径，格）
 * spawn_mode: 0=原点  1=快速估计(默认)  2=精确getSpawn(慢) */
int scanner_inspect(int version, int64_t seed, int radius, int spawn_mode, SeedInfo *info);

/* 获取最后一个 C 层错误信息 */
const char *scanner_last_error(void);

#ifdef __cplusplus
}
#endif

#endif /* SCANNER_CORE_H_ */
