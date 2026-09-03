/* ============================================================================
 * 全自动智能 MC Java 种子扫描系统 —— C 高速扫描核心实现
 * scanner_core.c
 * ==========================================================================*/
#include "scanner_core.h"
#include "cubiomes/generator.h"
#include "cubiomes/finders.h"
#include "cubiomes/biomes.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <pthread.h>
#include <sys/stat.h>

/* 命中文件写入互斥锁（多工作线程追加写）*/
static pthread_mutex_t g_out_lock = PTHREAD_MUTEX_INITIALIZER;

/* --------------------------------------------------------------------------
 * 全局运行态（每次 scanner_run 重置）
 * ------------------------------------------------------------------------*/
static volatile int64_t g_next      = 0;   /* 原子取号游标（已领取位置）*/
static volatile int64_t g_done      = 0;   /* 已完成评估的种子数 */
static volatile int64_t g_hits      = 0;   /* 命中数 */
static volatile int       g_run_version = 0;
static volatile int     *g_stop      = NULL;
static volatile int     *g_pause     = NULL;
static volatile int      g_active    = 0;   /* 扫描是否进行中 */
static char              g_error[256] = {0};
static int               g_batch     = 64;
static int64_t           g_end       = 0;

/* 地形采样缓存上限：覆盖半径 2048 格、4 格分辨率 */
#define TERRAIN_CACHE_MAX ((4096/4) * (4096/4))

/* --------------------------------------------------------------------------
 * 群系分类辅助
 * ------------------------------------------------------------------------*/
static int biome_is_ocean(int id)
{
    if (id < 0) return 0;
    return isOceanic(id) != 0;
}

/* 平原/草地类“舒适开局”群系 */
static int biome_is_plains_family(int id)
{
    switch (id)
    {
    case plains: case sunflower_plains:
    case meadow: case cherry_grove:
    case forest: case flower_forest: case birch_forest:
    case old_growth_birch_forest:
    case savanna: case savanna_plateau:
        return 1;
    default:
        return 0;
    }
}

/* 高山/山峰类群系 */
static int biome_is_mountain_family(int id)
{
    switch (id)
    {
    case mountains: case wooded_mountains:        /* windswept_hills / windswept_forest */
    case snowy_slopes: case stony_peaks:
    case jagged_peaks: case frozen_peaks:
    case grove:
    case gravelly_mountains:
        return 1;
    default:
        return 0;
    }
}

/* 出生点允许群系集合判定 */
static int spawn_biome_ok(const ScannerConfig *cfg, int id)
{
    if (id < 0) return 0;
    if (id < 64)  return (cfg->spawn_ok_biomesL >> id) & 1ULL;
    if (id >= 128 && id < 192) return (cfg->spawn_ok_biomesM >> (id - 128)) & 1ULL;
    return 0;
}

/* --------------------------------------------------------------------------
 * 地形采样：稀疏网格点采样（避免 1.18+ 全图 genBiomes 的 O(n²) 巨额开销）
 * 统计多样性/海洋/高山/平原覆盖。
 * ------------------------------------------------------------------------*/
typedef struct
{
    int biome_count;
    int has_ocean;
    int has_mountains;
    int flat_samples;
    int total_samples;
    int req_biome_found;
} TerrainStat;

static void sample_terrain(const Generator *g, const ScannerConfig *cfg,
        int bx, int bz, int radius, int *cache_unused, TerrainStat *st)
{
    (void)cache_unused;
    memset(st, 0, sizeof(*st));
    if (radius <= 0) return;

    /* 采样步长随半径缩放，保持约 ~250-300 个采样点 */
    int step = radius / 8;
    if (step < 48) step = 48;

    char seen[256] = {0};
    int count = 0;
    for (int dx = -radius; dx <= radius; dx += step)
    {
        for (int dz = -radius; dz <= radius; dz += step)
        {
            int x = bx + dx, z = bz + dz;
            int id = getBiomeAt(g, 4, x >> 2, 80, z >> 2);
            if (id < 0 || id >= 256) continue;
            st->total_samples++;
            if (!seen[id]) { seen[id] = 1; count++; }
            if (biome_is_ocean(id))             st->has_ocean = 1;
            if (biome_is_mountain_family(id))   st->has_mountains = 1;
            if (biome_is_plains_family(id))     st->flat_samples++;
            if (cfg->req_biome >= 0 && id == cfg->req_biome) st->req_biome_found++;
        }
    }
    st->biome_count = count;
}

/* --------------------------------------------------------------------------
 * 结构扫描：在出生点附近按 region 迭代查找可行结构
 * ------------------------------------------------------------------------*/
static int scan_structures(const Generator *g, const ScannerConfig *cfg,
        int64_t seed, int sx, int sz, int radius,
        int hit_type[], int hit_x[], int hit_z[], int max_hits)
{
    int n = 0;
    if (radius <= 0 || cfg->n_struct <= 0) return 0;

    for (int si = 0; si < cfg->n_struct && n < max_hits; si++)
    {
        int stype = cfg->structures[si];
        StructureConfig sconf;
        if (!getStructureConfig(stype, cfg->version, &sconf)) continue;

        double bpr = sconf.regionSize * 16.0;
        if (bpr <= 0) continue;
        int rx0 = (int)floor((sx - radius) / bpr);
        int rx1 = (int)ceil((sx + radius) / bpr);
        int rz0 = (int)floor((sz - radius) / bpr);
        int rz1 = (int)ceil((sz + radius) / bpr);

        for (int j = rz0; j <= rz1 && n < max_hits; j++)
        {
            for (int i = rx0; i <= rx1 && n < max_hits; i++)
            {
                Pos pos;
                if (!getStructurePos(stype, cfg->version, (uint64_t)seed, i, j, &pos)) continue;
                int dx = pos.x - sx, dz = pos.z - sz;
                if (dx*dx + dz*dz > (int64_t)radius * radius) continue; /* 超出半径 */
                if (!isViableStructurePos(stype, (Generator *)g, pos.x, pos.z, 0)) continue;
                if (cfg->version >= MC_1_18 && stype != Ancient_City)
                {
                    /* 部分结构在 1.18+ 依赖地表地形，地形不可行则剔除 */
                    if (!isViableStructureTerrain(stype, (Generator *)g, pos.x, pos.z)) continue;
                }
                hit_type[n] = stype;
                hit_x[n] = pos.x;
                hit_z[n] = pos.z;
                n++;
            }
        }
    }
    /* 去重：同类型同坐标只保留一个（部分结构 getStructurePos 会重复返回同一位置）*/
    int m = 0;
    for (int i = 0; i < n; i++)
    {
        int dup = 0;
        for (int j = 0; j < m; j++)
            if (hit_type[j] == hit_type[i] && hit_x[j] == hit_x[i] && hit_z[j] == hit_z[i])
            { dup = 1; break; }
        if (!dup)
        {
            hit_type[m] = hit_type[i];
            hit_x[m] = hit_x[i];
            hit_z[m] = hit_z[i];
            m++;
        }
    }
    return m;
}

/* --------------------------------------------------------------------------
 * 要塞扫描（快速门控用近似位置：1.19.3+ 可传 NULL 生成器，跳过生物群系校验）
 * 返回第一个在半径内的要塞，0=未命中
 * ------------------------------------------------------------------------*/
static int scan_stronghold(const Generator *g, const ScannerConfig *cfg,
        int64_t seed, int sx, int sz, int *ox, int *oz, int fast)
{
    StrongholdIter sh;
    Pos p = initFirstStronghold(&sh, cfg->version, (uint64_t)seed & MASK48);
    if (sh.index < 0) return 0;
    Generator *gg = fast ? NULL : (Generator *)g;
    for (int k = 0; k < 24; k++)
    {
        if (k == 0) p = sh.pos;
        int dx = p.x - sx, dz = p.z - sz;
        if (dx*dx + dz*dz <= (int64_t)cfg->stronghold_radius * cfg->stronghold_radius)
        {
            *ox = p.x; *oz = p.z;
            return 1;
        }
        if (nextStronghold(&sh, gg) <= 0) break;
        p = sh.pos;
    }
    return 0;
}

/* --------------------------------------------------------------------------
 * 快速出生点估计（复刻 MC 1.18+ 的 spawn fitness 搜索，粗网格降成本）
 * ------------------------------------------------------------------------*/
static uint64_t calc_fitness(const Generator *g, int x, int z)
{
    int64_t np[6];
    sampleBiomeNoise(&g->bn, np, x>>2, 0, z>>2, NULL,
            SAMPLE_NO_DEPTH | SAMPLE_NO_BIOME);
    const int64_t spn[][2] = {
        {-10000,10000},{-10000,10000},{-1100,10000},{-10000,10000},{0,0},
        {-10000,-1600},{1600,10000}
    };
    uint64_t ds = 0, ds1, ds2, a, b, q;
    int i;
    for (i = 0; i < 5; i++)
    {
        a = np[i] - (uint64_t)spn[i][1];
        b = -np[i] + (uint64_t)spn[i][0];
        q = (int64_t)a > 0 ? a : ((int64_t)b > 0 ? b : 0);
        ds += q * q;
    }
    a = np[5] - (uint64_t)spn[5][1];
    b = -np[5] + (uint64_t)spn[5][0];
    q = (int64_t)a > 0 ? a : ((int64_t)b > 0 ? b : 0);
    ds1 = ds + q * q;
    a = np[5] - (uint64_t)spn[6][1];
    b = -np[5] + (uint64_t)spn[6][0];
    q = (int64_t)a > 0 ? a : ((int64_t)b > 0 ? b : 0);
    ds2 = ds + q * q;
    ds = ds1 <= ds2 ? ds1 : ds2;
    int64_t xx = (int64_t)x * x, zz = (int64_t)z * z;
    if (g->mc <= MC_1_21_1)
    {
        double s = (double)(xx + zz) / (2500.0 * 2500.0);
        q = (uint64_t)(s * s * 1e8) + ds;
    }
    else
        q = ds * (2048LL * 2048LL) + xx + zz;
    return q;
}

static int fast_spawn_point(const Generator *g, int *ox, int *oz)
{
    int bx = 0, bz = 0;
    uint64_t best = ~0ULL;
    /* 5x5 @256（±512）→ 5x5 @64（±128）→ 3x3 @16（±32）*/
    const int G1 = 5, S1 = 256;
    for (int i = -G1/2; i <= G1/2; i++)
        for (int j = -G1/2; j <= G1/2; j++)
        {
            int x = i*S1, z = j*S1;
            uint64_t f = calc_fitness(g, x, z);
            if (f < best) { best = f; bx = x; bz = z; }
        }
    const int G2 = 5, S2 = 64;
    for (int i = -G2/2; i <= G2/2; i++)
        for (int j = -G2/2; j <= G2/2; j++)
        {
            int x = bx + i*S2, z = bz + j*S2;
            uint64_t f = calc_fitness(g, x, z);
            if (f < best) { best = f; bx = x; bz = z; }
        }
    const int G3 = 3, S3 = 16;
    for (int i = -G3/2; i <= G3/2; i++)
        for (int j = -G3/2; j <= G3/2; j++)
        {
            int x = bx + i*S3, z = bz + j*S3;
            uint64_t f = calc_fitness(g, x, z);
            if (f < best) { best = f; bx = x; bz = z; }
        }
    bx = (bx & ~15) + 8;
    bz = (bz & ~15) + 8;
    *ox = bx; *oz = bz;
    return 1;
}

/* --------------------------------------------------------------------------
 * 单种子评估：通过全部启用门控则返回 1，并把特征写入 res
 * ------------------------------------------------------------------------*/
typedef struct
{
    int64_t seed;
    int spawn_x, spawn_z;
    int spawn_biome;
    TerrainStat terr;
    int n_hits;
    int hit_type[SCANNER_MAX_HITS];
    int hit_x[SCANNER_MAX_HITS];
    int hit_z[SCANNER_MAX_HITS];
    int has_stronghold;
    int stronghold_x, stronghold_z;
    int slime_spawn;
    int passed;
} SeedResult;

static void evaluate_seed(Generator *g, const ScannerConfig *cfg,
        int64_t seed, int *cache, SeedResult *res)
{
    memset(res, 0, sizeof(*res));
    res->seed = seed;
    res->stronghold_x = res->stronghold_z = 0;
    res->passed = 0;

    applySeed(g, DIM_OVERWORLD, (uint64_t)seed);

    /* ---- 出生点（按 spawn_mode 选择参考点）---- */
    Pos sp;
    if (cfg->spawn_mode == 2)
        sp = getSpawn(g);            /* 精确（慢）*/
    else if (cfg->spawn_mode == 1)
        fast_spawn_point(g, &sp.x, &sp.z);   /* 快速估计（默认）*/
    else
    { sp.x = 0; sp.z = 0; }          /* 原点（最快）*/
    res->spawn_x = sp.x;
    res->spawn_z = sp.z;
    int bxs = sp.x >> 2, bzs = sp.z >> 2;
    res->spawn_biome = getBiomeAt(g, 4, bxs, 80, bzs);

    if (cfg->check_spawn)
    {
        if (!spawn_biome_ok(cfg, res->spawn_biome)) return;
    }

    /* ---- 地形 / 群系采样 ---- */
    int need_terrain = cfg->req_biome >= 0 || cfg->check_multi_biome ||
                       cfg->check_big_plains || cfg->check_mountains || cfg->check_coast;
    if (need_terrain && cfg->terrain_radius > 0)
    {
        sample_terrain(g, cfg, sp.x, sp.z, cfg->terrain_radius, cache, &res->terr);
        if (cfg->req_biome >= 0 && res->terr.req_biome_found < cfg->req_biome_count) return;
        if (cfg->check_multi_biome && res->terr.biome_count < 3) return;
        if (cfg->check_big_plains)
        {
            int pct = res->terr.total_samples > 0
                ? (100 * res->terr.flat_samples) / res->terr.total_samples : 0;
            if (pct < 60) return;
        }
        if (cfg->check_mountains && !res->terr.has_mountains) return;
        if (cfg->check_coast && !res->terr.has_ocean) return;
    }

    /* ---- 结构 ---- */
    if (cfg->n_struct > 0 && cfg->struct_radius > 0)
    {
        res->n_hits = scan_structures(g, cfg, seed, sp.x, sp.z,
                cfg->struct_radius, res->hit_type, res->hit_x, res->hit_z,
                SCANNER_MAX_HITS);
    }
    if (cfg->need_any_struct && res->n_hits == 0) return;

    /* ---- 要塞 ---- */
    if (cfg->stronghold_radius > 0)
    {
        res->has_stronghold = scan_stronghold(g, cfg, seed, sp.x, sp.z,
                &res->stronghold_x, &res->stronghold_z, 1);
        if (cfg->need_stronghold && !res->has_stronghold) return;
    }

    /* ---- 史莱姆区块 ---- */
    if (cfg->check_slime)
    {
        res->slime_spawn = isSlimeChunk((uint64_t)seed, sp.x >> 4, sp.z >> 4);
        if (!res->slime_spawn) return;
    }

    res->passed = 1;
}

/* --------------------------------------------------------------------------
 * 结果输出：单次 write 写一行（管道原子性由行长度 < PIPE_BUF 保证）
 * ------------------------------------------------------------------------*/
static void emit_result(const ScannerConfig *cfg, const SeedResult *res)
{
    char line[SCANNER_LINE_MAX];
    int n = 0;
    n += snprintf(line + n, sizeof(line) - n,
        "%lld\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t",
        (long long)res->seed, res->spawn_x, res->spawn_z, res->spawn_biome,
        res->terr.biome_count, res->terr.has_ocean ? 1 : 0,
        res->terr.has_mountains ? 1 : 0,
        res->terr.total_samples > 0 ? (100 * res->terr.flat_samples) / res->terr.total_samples : 0);

    for (int i = 0; i < res->n_hits && n < SCANNER_LINE_MAX - 8; i++)
    {
        if (i > 0 && n < SCANNER_LINE_MAX - 8) { line[n++] = ';'; line[n] = 0; }
        n += snprintf(line + n, sizeof(line) - n, "%d@%d,%d",
                res->hit_type[i], res->hit_x[i], res->hit_z[i]);
    }
    if (res->has_stronghold)
        n += snprintf(line + n, sizeof(line) - n, "\t%d,%d\t%d\n",
                res->stronghold_x, res->stronghold_z, res->slime_spawn);
    else
        n += snprintf(line + n, sizeof(line) - n, "\t-\t%d\n", res->slime_spawn);

    if (cfg->out_fd >= 0)
    {
        ssize_t wr = write(cfg->out_fd, line, (size_t)n);
        (void)wr;
    }
    if (cfg->out_path[0])
    {
        pthread_mutex_lock(&g_out_lock);
        FILE *f = fopen(cfg->out_path, "a");
        if (f)
        {
            fwrite(line, 1, (size_t)n, f);
            fflush(f);
            fclose(f);
        }
        pthread_mutex_unlock(&g_out_lock);
    }
    __sync_add_and_fetch(&g_hits, 1);
}

/* --------------------------------------------------------------------------
 * 断点写入（监督线程）
 * ------------------------------------------------------------------------*/
static void write_checkpoint(const ScannerConfig *cfg, int64_t value)
{
    if (!cfg->write_checkpoint || cfg->checkpoint_path[0] == 0) return;
    char tmp[600];
    snprintf(tmp, sizeof(tmp), "%s.tmp", cfg->checkpoint_path);
    FILE *f = fopen(tmp, "w");
    if (!f) return;
    fprintf(f, "%lld\n", (long long)value);
    fclose(f);
    rename(tmp, cfg->checkpoint_path);
}

static void *supervisor_main(void *arg)
{
    const ScannerConfig *cfg = (const ScannerConfig *)arg;
    /* 区间耗尽或收到停止信号时退出 */
    while (!(g_stop && *g_stop) && g_next < g_end)
    {
        write_checkpoint(cfg, g_next);
        for (int i = 0; i < 50; i++)
        {
            if (g_stop && *g_stop) break;
            if (g_next >= g_end) break;
            usleep(10000); /* 500ms */
        }
    }
    write_checkpoint(cfg, g_next);
    return NULL;
}

/* --------------------------------------------------------------------------
 * 工作线程
 * ------------------------------------------------------------------------*/
typedef struct
{
    const ScannerConfig *cfg;
    int tid;
} WorkerArg;

static void *worker_main(void *arg)
{
    WorkerArg *wa = (WorkerArg *)arg;
    const ScannerConfig *cfg = wa->cfg;

    Generator g;
    setupGenerator(&g, cfg->version, 0);

    int *cache = malloc(TERRAIN_CACHE_MAX * sizeof(int));
    if (!cache) return NULL;

    for (;;)
    {
        if (g_stop && *g_stop) break;
        if (g_pause && *g_pause)
        {
            usleep(2000);
            continue;
        }
        int64_t base = __sync_fetch_and_add(&g_next, cfg->batch);
        if (base >= g_end) break;
        int64_t upto = base + cfg->batch;
        if (upto > g_end) upto = g_end;

        SeedResult res;
        for (int64_t s = base; s < upto; s++)
        {
            if (g_stop && *g_stop) break;
            if (g_pause && *g_pause) { s--; usleep(2000); continue; }
            evaluate_seed(&g, cfg, s, cache, &res);
            if (res.passed) emit_result(cfg, &res);
            __sync_add_and_fetch(&g_done, 1);
        }
    }

    free(cache);
    return NULL;
}

/* --------------------------------------------------------------------------
 * 顶层接口
 * ------------------------------------------------------------------------*/
int64_t scanner_processed(void) { return g_done; }
int64_t scanner_hits(void)      { return g_hits; }

const char *scanner_last_error(void) { return g_error; }

int scanner_run(const ScannerConfig *cfg)
{
    g_error[0] = 0;

    if (g_active) { snprintf(g_error, sizeof(g_error), "已有扫描任务在运行"); return -2; }
    if (cfg == NULL) { snprintf(g_error, sizeof(g_error), "配置为空"); return -1; }

    int ver = cfg->version;
    if (ver != MC_1_18 && ver != MC_1_19 && ver != MC_1_20 && ver != MC_1_21)
    {
        snprintf(g_error, sizeof(g_error), "不支持的 MC 版本枚举 %d（需 1.18/1.19/1.20/1.21）", ver);
        return -1;
    }
    if (cfg->seed_end <= cfg->seed_start)
    {
        snprintf(g_error, sizeof(g_error), "扫描区间为空 [%lld, %lld)", (long long)cfg->seed_start, (long long)cfg->seed_end);
        return 2;
    }
    int threads = cfg->threads > 0 ? cfg->threads : 1;
    if (threads > 1024) threads = 1024;

    /* ---- 初始化全局运行态 ---- */
    g_run_version = ver;
    g_stop  = cfg->stop_flag  ? cfg->stop_flag  : NULL;
    g_pause = cfg->pause_flag ? cfg->pause_flag : NULL;
    g_next  = cfg->seed_start;
    g_end   = cfg->seed_end;
    g_done  = 0;
    g_hits  = 0;
    g_batch = cfg->batch > 0 ? cfg->batch : 64;
    g_active = 1;

    if (g_stop)  *g_stop  = 0;
    if (g_pause) *g_pause = 0;

    /* ---- 启动监督线程（断点写入）---- */
    pthread_t sup;
    int sup_ok = 0;
    if (cfg->write_checkpoint && cfg->checkpoint_path[0])
    {
        if (pthread_create(&sup, NULL, supervisor_main, (void *)cfg) == 0)
            sup_ok = 1;
    }

    /* ---- 启动工作线程 ---- */
    pthread_t *th = calloc((size_t)threads, sizeof(pthread_t));
    WorkerArg *wa = calloc((size_t)threads, sizeof(WorkerArg));
    if (!th || !wa)
    {
        snprintf(g_error, sizeof(g_error), "内存分配失败");
        g_active = 0;
        return -2;
    }
    for (int i = 0; i < threads; i++)
    {
        wa[i].cfg = cfg;
        wa[i].tid = i;
        if (pthread_create(&th[i], NULL, worker_main, &wa[i]) != 0)
        {
            snprintf(g_error, sizeof(g_error), "线程 %d 创建失败", i);
            g_active = 0;
            return -2;
        }
    }
    for (int i = 0; i < threads; i++)
        pthread_join(th[i], NULL);
    if (sup_ok) pthread_join(sup, NULL);

    free(th);
    free(wa);

    int stopped = (g_stop && *g_stop) ? 1 : 0;
    g_active = 0;
    return stopped;
}

/* --------------------------------------------------------------------------
 * 单种子精确回查（快速版）
 * ------------------------------------------------------------------------*/
int scanner_inspect(int version, int64_t seed, int radius, int spawn_mode, SeedInfo *info)
{
    g_error[0] = 0;
    if (info == NULL) { snprintf(g_error, sizeof(g_error), "输出指针为空"); return -1; }
    memset(info, 0, sizeof(*info));

    Generator g;
    setupGenerator(&g, version, 0);
    applySeed(&g, DIM_OVERWORLD, (uint64_t)seed);

    info->seed = seed;

    /* 出生点：2=精确(getSpawn, 慢)  1=快速估计(默认)  0=原点 */
    Pos sp;
    if (spawn_mode == 2)
        sp = getSpawn(&g);
    else if (spawn_mode == 1)
        fast_spawn_point(&g, &sp.x, &sp.z);
    else
    { sp.x = 0; sp.z = 0; }
    info->spawn_x = sp.x;
    info->spawn_z = sp.z;
    Pos est = estimateSpawn(&g, NULL);
    info->est_x = est.x;
    info->est_z = est.z;
    info->spawn_biome = getBiomeAt(&g, 4, sp.x >> 2, 80, sp.z >> 2);

    /* 地形采样 */
    int *cache = malloc(TERRAIN_CACHE_MAX * sizeof(int));
    if (cache)
    {
        ScannerConfig dummy;
        memset(&dummy, 0, sizeof(dummy));
        dummy.req_biome = -1;
        dummy.version = version;
        TerrainStat st;
        sample_terrain(&g, &dummy, sp.x, sp.z, radius > 0 ? radius : 800, cache, &st);
        info->biome_count = st.biome_count;
        info->has_ocean    = st.has_ocean;
        info->has_mountains = st.has_mountains;
        info->flat_score   = st.total_samples > 0 ? (100 * st.flat_samples) / st.total_samples : 0;
        free(cache);
    }

    /* 结构扫描：常用结构集（控制成本），半径 = terrain radius * 1.5 */
    static const int common_structs[] = {
        Village, Ancient_City, Monument, Mansion,
        Desert_Pyramid, Jungle_Temple, Outpost, Igloo,
        Trail_Ruins, Trial_Chambers, Ocean_Ruin, Shipwreck
    };
    ScannerConfig cfg2;
    memset(&cfg2, 0, sizeof(cfg2));
    cfg2.version = version;
    cfg2.struct_radius = radius > 0 ? radius * 3 / 2 : 1200;
    cfg2.n_struct = (int)(sizeof(common_structs) / sizeof(common_structs[0]));
    memcpy(cfg2.structures, common_structs, sizeof(common_structs));
    info->n_hits = scan_structures(&g, &cfg2, seed, sp.x, sp.z, cfg2.struct_radius,
            info->hit_type, info->hit_x, info->hit_z, SCANNER_MAX_HITS);

    /* 要塞（快速：近似位置）*/
    cfg2.stronghold_radius = radius > 0 ? radius * 3 / 2 : 1200;
    info->has_stronghold = scan_stronghold(&g, &cfg2, seed, sp.x, sp.z,
            &info->stronghold_x, &info->stronghold_z, 1);

    /* 史莱姆 */
    info->slime_spawn = isSlimeChunk((uint64_t)seed, sp.x >> 4, sp.z >> 4);

    return 0;
}
