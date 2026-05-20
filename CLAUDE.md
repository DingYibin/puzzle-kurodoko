# Kurodoko Solver — 开发指南

## 项目概述

Kurodoko (Kuromasu / 田鼠挖洞) 谜题的 Python 求解器。从网站 `cn.puzzle-kurodoko.com` 获取谜题，用迭代 try-both + 约束传播求解（无需回溯 DFS 即可解出 15×15）。

**状态常量：** `UNKNOWN=0` / `WHITE=1` / `BLACK=-1`

---

## 运行方式

所有命令通过 `uv run python` 执行：

```bash
uv run python main.py                         # 随机 5×5
uv run python main.py --size 10               # 指定尺寸
uv run python main.py --load examples/03.json # 从文件加载
uv run python main.py --debug                 # 调试模式
uv run python main.py -p                      # 仅打印不求解
uv run python main.py --trace                 # 播放 action 动画
uv run python main.py --trace-full            # 播放完整 trace 含回溯
uv run python main.py --trace-delay 50        # 动画步间延迟（默认 10ms）
```

---

## 代码架构

### `main.py` — CLI 入口 (464 行)

| 功能 | 函数/代码段 | 说明 |
|------|------------|------|
| 参数映射 | `SIZE_MAP` | 尺寸字符串→网站 size 参数 |
| 解码 | `decode(task, width)` | RLE 字符串 → `list[list[int]]` 网格 |
| 编码 | `encode(grid)` | 网格 → RLE 字符串 |
| 合法性 | `is_task_valid(task)` | 验证 RLE 中连续小写字母是否规范 |
| 网页抓取 | `fetch_puzzle(url)` | GET 请求，`/puzzleWidth/Height/task` 正则提取 |
| 指定编号 | `fetch_by_id(size_param, id)` | POST 请求 `specific=1&size=&specid=` |
| 获取谜题 | `get_puzzle(size_key)` | 包装 fetch，返回 `(grid, N, pid, date, size_key)` |
| 行列标签 | `_col_label(c)` / `_row_label(r)` | 1-based 十进制数字 |
| 命令行打印 | `print_puzzle(grid, *, solved)` | ANSI 彩色打印（白底/灰底/黑底） |
| 保存 | `save_puzzle(grid, **extra)` | 编码为 RLE 写入 `puzzles/` 目录 |
| 加载 | `load_puzzle(path)` | 从 JSON 读取并解码 |
| CLI 主函数 | `main()` | 参数解析 + 调度 |

**参数解析：**
- `--size / -s` → 字符串尺寸 (5/7/10/15/20/daily/weekly/monthly)
- `--id / -n` → 整数谜题编号
- `--daily / --weekly / --monthly` → 简写
- `--load <path>` → 从 JSON 文件加载
- `-p` → 仅打印不求解
- `--save` → 求解后保存
- `--debug / -v` → 调试输出
- `--time <sec>` → 时间限制
- `--trace` → 播放 action 动画（`_action`，仅提交步骤）
- `--trace-full` → 播放完整 trace（`_trace`，含回溯过程）
- `--trace-delay <ms>` → 动画步间延迟毫秒（默认 10ms）

### `kurodoko_solver.py` — 求解器核心 (1015 行)

#### Solver 类：状态管理

| 属性 | 类型 | 说明 |
|------|------|------|
| `tlim` | `float` | 时间限制（秒），默认 5.0 |
| `debug` | `bool` | 调试模式，打印传播过程 |
| `N` | `int` | 棋盘边长 |
| `state` | `list[list[int]]` | 格状态：UNKNOWN/WHITE/BLACK |
| `clues` | `list[list[int]]` | 线索值，非线索格为 0 |
| `fixed` | `list[list[bool]]` | 线索格不可更改 |
| `nodes` | `int` | DFS 分支节点计数 |
| `t0` | `float` | 求解开始时间（time.time） |
| `_dirty` | `bool` | 传播循环是否还有变化 |
| `_satisfied` | `list[list[bool]]` | 线索是否已满足 |
| `_watchers` | `list[list[list[tuple]]]` | 每个格子的观察者线索列表 |

#### Solver 类：核心方法

| 方法 | 行号 | 说明 |
|------|------|------|
| `__init__` | 35 | 初始化，含 `_build_watchers` 调用 |
| `load(grid)` | 68-90 | 从解码后的网格加载谜题 |
| `solve()` | 93-138 | 主求解入口：Propagate → 迭代 try-both → DFS 回溯 |
| `_dfs()` | 142-195 | DFS 回溯，使用 _snap/_backtrack + _set；设 target 后对 best_clue 四方向相邻未知格调 _try_cell_both |
| `_select_cell()` | 199-234 | 返回 (unknown, best_clue)；找最小未满足 clue 的 LOS 中最近 UNKNOWN，无未满足 clue 时返回第一个 UNKNOWN |
| `_propagate(quiet)` | 238-266 | 传播：初始行列分析 → 更新 _satisfied |
| `_analyze_state()` | 269-305 | 调试用：打印传播后状态统计 |
| `_compute_clue_data(r,c)` | 310-337 | 初始计算线索 LOS 数据 |
| `_scan_dir(r,c,dr,dc)` | 340 | 单方向 LOS 扫描（min/max） |
| `_update_clues_for_cell(r,c)` | 362-435 | 四方向扫描，增量更新受影响线索的 LOS；无 watcher 时跳过 |
| `_scan_clue(r,c)` | 437-439 | 从 _clue_data 返回缓存的 LOS 数据 |
| `_clue_satisfied(r,c)` | 442-446 | 线索精确满足？(min==max==N) |
| `_propagate_clue(r,c)` | 449-512 | LOS 约束推理赋值 |
| `_find_nearest_white(r,c)` | 516-547 | BFS 经 UNKNOWN 找最近 WHITE |
| `_are_whites_connected(cells)` | 550-579 | BFS 检查多个 WHITE 是否连通 |
| `_check_black_connectivity(r,c)` | 582-607 | 设 BLACK 后检查 WHITE/UNKNOWN 邻居连通性；边界格需 ≥1 对角黑才检查，非边界需 ≥2 |
| `_propagate_rowcol()` | 614-639 | 行列线索共享分析 |
| `_propagate_clue_group(clues, is_row)` | 641-670 | 给定同行(is_row=True)或同列线索列表，找垂直于该方向最受约束的线索作 pivot，逐一配对调用 _analyze_pair |
| `_propagate_from_white(r,c,is_row)` | 672-705 | 从 (r,c) 沿 is_row 方向收集线索（遇 BLACK/UNKNOWN 停），调 _propagate_clue_group |
| `_analyze_pair(r1,c1,n1, r2,c2,n2)` | 707-814 | 跨线索推导（8组公式：行/列各4组，双向）；间隙全白时推算两线索外侧需补充的白格 |
| `_propagate_domain()` | 819-868 | **(未使用)** |
| `_try_cell_both(r,c)` | 870-910 | 对单格试 BLACK→WHITE，返回 1(定)/0(两可)/-1(矛盾) |
| `_try_both()` | 912-930 | 遍历未知格调 _try_cell_both |
| `_set(r,c,val)` | 934-976 | 设值，级联规则 1/2/行列 |
| `_check_rowcol_at(r,c)` | 978-1007 | 当某格变白时，四方向扫描找到线索对触发 _analyze_pair |
| `_snap()` | 1009-1011 | 返回 `len(_action)` |
| `_backtrack(pos)` | 1013-1020 | 回滚到检查点 |
| `pc()` | 1024-1032 | 打印当前网格状态 |
| `_print_stats(elapsed)` | 1034-1066 | 打印计时 + 方法耗时（动态排序） |
| `animate(delay, full_trace, elapsed)` | 1017-1090 | 终端动画：逐格 ANSI 更新 + 实时白/黑/未知计数器 |

#### 顶层函数

| 函数 | 行号 | 说明 |
|------|------|------|
| `_col_label(c)` | 1074-1075 | 列号→标签 (0→A, 26→AA) |
| `_row_label(r)` | 1078-1079 | 行号→标签 (0→1, 9→a, 35→aa) |
| `_print_puzzle(state, clues, satisfied)` | 1082-1113 | 独立打印函数，被 Solver.pc() 调用 |
| `solve(grid, tl, debug)` | 1116-1128 | 快捷函数：load + solve + print |

---

## 求解算法流程

```
solve()
├── _propagate()             ← 传播：初始行列分析 → 更新 _satisfied
│                              (规则 1/2/行列由 _set 级联内联处理)
│
├── while dirty:              ← 迭代 try-both 循环
│   ├── _try_both()          ← 行主序扫描未知格
│   │   ├── BLACK测试: snap → _set → _check_black_connectivity → backtrack
│   │   ├── BLACK失败 → _set(WHITE) (不连通性检查, WHITE 不破坏连通性)
│   │   ├── BLACK成功 → WHITE测试: snap → _set → backtrack
│   │   ├── WHITE失败 → 回放 recorded BLACK actions
│   │   └── 记录 _trace(全部) / _action(commit)
│   ├── _propagate()         ← 更新 _satisfied 缓存
│   └── (重复直到无新格可设)
│
└── _dfs()                    ← try-both 仍有未知格时 DFS 回溯
    ├── _propagate()
    ├── _select_cell()        ← 返回 (unknown, best_clue)
    ├── _snap()
    ├── for val in (WHITE, BLACK):
    │   ├── _set(r, c, val)   ← 设 target
    │   ├── if best_clue:     ← 四方向调 _try_cell_both 邻域未知格
    │   │   └── 任一矛盾 → _backtrack → 试下一 val
    │   ├── _dfs() → True → return True
    │   └── _backtrack(pos)
    └── return False

_trace:  所有操作 (r,c,old,new) + undo 记录
_action: commit 操作，_snap()/_backtrack() 管理边界
```

---

## 关键数据结构

### Watcher 系统 (`_watchers`)

`_watchers[r][c]` 存储所有能"看见"格子 (r,c) 的线索坐标。在 `_build_watchers()` 中初始化：对每个线索，沿四方向遍历直到遇到黑格或边界，沿途每格都加入该线索。

用途：
- `_select_cell()` 中快速计算每个未知格被多少未满足线索覆盖
- `_propagate_domain()` 中快速获取受影响的线索

### `_satisfied` 缓存

`_satisfied[r][c]` 在 `_propagate()` 末尾更新（第 218-222 行），用于 `_select_cell()` 的判断条件。`pc()` 调用时会重新计算全部线索。

### `_clue_data` 增量维护

`_clue_data[r][c]` 存储每个线索四方向 LOS 数据的缓存：`(info, total_min, total_max)`，其中 `info` 是 4 个 `(mn, mx)` 的列表（不存未知格坐标，需要时通过 mn/mx 推导或临时扫描）。方向顺序：**上、下、左、右**（对应 `dirs = ((-1,0), (1,0), (0,-1), (0,1))`）。

`_update_clues_for_cell(r,c)` 在某格变化时被 `_set` / `_backtrack` 调用，增量更新受影响的线索：

1. 对每个方向，先朝**反方向**扫描得到 `tail_mn/tail_mx`（包括 (r,c) 自身）
2. 再朝**正方向**行走，每遇到一个线索，将当前 `tail_mn/tail_mx` 快照作为该线索在反方向的 LOS 数据；保存后将线索格自身并入 tail 供更远的线索使用
3. 无需在每个线索处重新反向遍历，全程 O(L) 而非 O(L²)

推导关系：
- `mn < mx` → 该方向至少有一个 UNKNOWN，第一个 UNKNOWN 在 `mn+1` 步位置
- `mn == mx` → 无 UNKNOWN

---

## 传播规则详解

### 规则 1 — 黑格不相邻

对每个 BLACK 格，四邻若为 UNKNOWN 则设为 WHITE。发现相邻 BLACK 则矛盾。

### 规则 2 — 视线约束 (LOS)

对线索 (r,c)=N：
1. 扫描四个方向，得到每个方向的 `(min_count, max_count)`
2. `total_min = 1 + Σmin_dir`, `total_max = 1 + Σmax_dir`
3. 若 `N < total_min 或 N > total_max` → 矛盾
4. 若 `N == total_min` → 每个方向的第一个未知格必须为黑
5. 若 `N == total_max` → 所有未知格必须为白
6. 若两者都不是 → 对每个方向单独分析：
   - `need_min = max(mn, N-1-other_max)`, `need_max = min(mx, N-1-other_min)`
   - 若 `need_min > need_max` → 矛盾
   - 若 `need_min == need_max`：
     - 其他方向无未知格 → 按位置扫描设置前 `need_min` 格为白，第 `need_min+1` 格为黑

### 规则 3 — 桥规则

对每个 UNKNOWN 格（有至少一个 WHITE 邻居）：
- 临时设为 BLACK，检查连通性
- 若断开则强制为 WHITE

### 规则 4 — 连通性检查

BFS 从第一个 WHITE 格出发，遍历所有 WHITE/UNKNOWN 格。
若所有 WHITE 格均可抵达 → OK；否则矛盾。

### 行列共享分析

对同行/列中连续的两个线索：
- 若之间所有格已确定为 WHITE（"共享间隙"）
- 若线索的外侧方向已完全确定（min==max）
- 此时内部方向的可见数不足以达到 N → 在外侧补充白格

### Try-Both 迭代

行主序扫描未知格，对每格按顺序测试：

**BLACK 测试：**
1. `_snap()` → `_set(r, c, BLACK)`（级联规则 1+2+行列）→ `_check_black_connectivity(r,c)`（BFS 检查 WHITE/UNKNOWN 邻居连通性）
2. 若 BLACK 失败（矛盾或断开）→ 直接 `_set(r, c, WHITE)` 提交（WHITE 不破坏连通性）
3. 若 BLACK 成功 → 记录 `black_actions`，然后测试 WHITE

**WHITE 测试：**
1. `_set(r, c, WHITE)`（级联规则 2+行列；不检查连通性，WHITE 不会断开）
2. 若 WHITE 失败 → 回放 `black_actions`（直接写回 state/_trace/_action，无需重算）
3. 两者皆可行 → 保留未知

**变更跟踪（yin-yang 风格）：**
- `_trace`：全部历史 (r,c,old,new) + undo 记录
- `_action`：commit 记录，`_snap()`/`_backtrack()` 管理边界

**`_set()` 级联（所有规则已内联）：**
1. 设值 → `_update_clues_for_cell` 增量更新关联线索 LOS → 规则 1（BLACK 时检查四邻）→ `_propagate_clue` 级联 → 行列对分析
2. 不再需要单独的规则 1/规则 2/行列扫描阶段

**注：** 传播和 try-both 阶段无时间限制。时间限制仅作用于 DFS（当前禁用）。

---

## 已知问题 / 未使用代码

1. **`_propagate_domain()`** — 定义但未被 `solve()` 调用。功能类似于 `_try_both` 但只在单个格子级别验证，没有传播循环。
2. **`__init__` 中 `_satisfied` 初始化** — `self.N=0` 时初始化为 `[[]]`，随后被 `load()` 重新初始化，不影响功能。

---

## 编码参考

### RLE 格式

```
d5_9f6f4_5d
││││││││││└─ d = 跳过 4 格
│││││││││└── 5 = 线索 5
││││││││└─── _ = 分隔符
│││││││└──── 4 = 线索 4
││││││└───── f = 跳过 6 格
│││││└────── 6 = 线索 6
││││└─────── f = 跳过 6 格
│││└──────── 9 = 线索 9
││└───────── _ = 分隔符
│└────────── 5 = 线索 5
└─────────── d = 跳过 4 格
```

### 编码约束 (`is_task_valid`)

连续小写字母段中，除最后一个字母外，其他必须为 `z`。这对应网站使用的规范编码。

---

## 示例参考

| 文件 | 尺寸 | 标签 | 来源 |
|------|------|------|------|
| `examples/01.json` | 5×5 | 5x5 normal | 随机 |
| `examples/02.json` | 7×7 | 7x7 | 随机 |
| `examples/03.json` | 10×10 | 10x10 | 随机 |
| `examples/04.json` | 15×15 | 15x15 | 随机 |
| `examples/05.json` | 20×20 | 20x20 | 随机 |
| `examples/06.json` | 30×30 | daily 30x30 | 每日 |
| `examples/07.json` | 40×40 | weekly 40x40 | 每周 |
| `examples/08.json` | 50×50 | monthly 50x50 | 月度 |
