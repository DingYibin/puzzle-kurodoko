# Kurodoko / 田鼠挖洞 解题器

[Kurodoko (Kuromasu)](https://cn.puzzle-kurodoko.com/) 谜题的 Python 解题器。从网站抓取谜题，使用迭代 try-both + 约束传播求解，无需搜索回溯即可解出 15×15 及以下谜题。

## 规则

- **黑格**不能正交相邻（上下左右方向）
- 所有**白格**必须通过上下左右方向构成**单一连通分量**（即任意两个白格之间有一条只经过白/未知格的路径）
- **数字线索**：从该格向上、下、左、右四个方向能看到的白格总数（含自身），遇到黑格视线即被阻挡

## 用法

```bash
# 随机 5×5 谜题
uv run python main.py

# 指定尺寸
uv run python main.py --size 10          # 5, 7, 10, 15, 20
uv run python main.py --size daily       # 每日
uv run python main.py --size weekly      # 每周
uv run python main.py --size monthly     # 每月

# 指定编号
uv run python main.py --id 12345
uv run python main.py --size 10 --id 12345

# 简写
uv run python main.py --daily
uv run python main.py --weekly
uv run python main.py --monthly

# 从文件加载
uv run python main.py --load examples/01.json

# 仅显示（不求解）
uv run python main.py -p

# 调试模式（显示传播过程）
uv run python main.py --debug
uv run python main.py -v

# 保存到文件
uv run python main.py --save

# 设置时间限制（秒）
uv run python main.py --time 30
```

## 显示格式

```
     A   B   C   D   E      列标 (A-Z, AA, AB...)
 1   .   .   .   .   5      行号 | 格内容
 2   9   .   W   .   .
 3   .   .   B   .   .
 4   .   .   .   .   .
 5   .   .   .   .   .
```

| 符号 | 含义 |
|------|------|
| `.`  | 未确定 (UNKNOWN) |
| `W`  | 已确定的白格 (WHITE) |
| `B`  | 已确定的黑格 (BLACK) |
| 数字 | 线索值（固定白格） |

行号规则：1-9 为数字，9 之后为 a, b, ..., z, aa, ab, ...

## 文件结构

```
├── main.py                CLI 入口（网页抓取、编码解码、保存/加载、显示、调用求解器）
├── kurodoko_solver.py     求解器核心（Solver 类 + 独立打印函数）
├── pyproject.toml         项目配置 (uv)
├── CLAUDE.md              开发指南
├── README.md              本文件
├── examples/              示例谜题
│   ├── 01.json             5×5
│   ├── 02.json             7×7
│   ├── 03.json            10×10
│   ├── 04.json            15×15
│   ├── 05.json            20×20
│   ├── 06.json            30×30 (daily)
│   ├── 07.json            40×40 (weekly)
│   └── 08.json            50×50 (monthly)
└── puzzles/               自动保存目录 (.gitignore)
```

## 编码格式 (RLE)

网站谜题使用游程编码（Run-Length Encoding）表示：

| 符号 | 含义 |
|------|------|
| `1`–`999` | 线索数值，放在当前位置 |
| `_` | 连续数字之间的分隔符 |
| `a`–`z` | 跳过 N 个空格（a=1, b=2, ..., z=26） |

例如 `d5_9f6f4_5d`：
- `d` → 跳过 4 格
- `5` → 线索 5
- `_` → 分隔符
- `9` → 线索 9
- `f` → 跳过 6 格
- `6` → 线索 6
- `f` → 跳过 6 格
- `4` → 线索 4
- `_` → 分隔符
- `5` → 线索 5
- `d` → 跳过 4 格

## 求解算法

两阶段求解器，传播收敛后迭代执行 try-both + 传播直至无法继续。

### 阶段 1：约束传播 (`_propagate`)

循环执行以下规则直至收敛：

**规则 1 — 黑格不相邻**
若某格已确定为黑，其上下左右四邻强制为白。发现相邻黑格则矛盾。

**规则 2 — 视线约束 (LOS)**
对每个数字线索，向四个方向扫描：
- 记录每个方向最小/最大可见白格数及未知格列表
- `total_min == N` → 各方向第一个未知格必须为黑
- `total_max == N` → 所有未知格必须为白
- 单方向 `need_min == need_max` → 按位置推算白/黑

**规则 3 — 桥规则**
若某未知格设为黑会导致白格不连通，则强制为白。只检查有白邻的未知格。

**规则 4 — 白格连通性检查**
所有白格是否通过 WHITE/UNKNOWN 格构成单一连通分量。BFS 遍历。

### 阶段 2：Try-Both 迭代 (`_try_both`)

对每个未知格分别尝试设为白和黑，调用完整传播，若只有一方可行则赋值。

行主序扫描，一轮结束后若设置了新格则重新传播，然后再次扫描。迭代直至没有新格可设为为止。

### DFS 回溯（预留）

上述迭代仍无法推理时，可启用 DFS 回溯分支尝试。当前版本中 DFS 已禁用，因为 try-both + 传播已足以解出 15×15 及以下谜题。

## 性能

| 尺寸 | 示例 | 求解时间 |
|------|------|----------|
| 5×5 | 01.json | ~2ms |
| 7×7 | 02.json | ~5ms |
| 10×10 | 03.json | ~100ms |
| 15×15 | 04.json | ~0.4s |
| 20×20 | 05.json | ~2.5s |

瓶颈分析：try_both 阶段占总时间 >99%，其中桥规则（O(N³)）是主要耗时。通过轻量传播（跳过桥规则）获得约 22 倍加速。

## Solver API

```python
from kurodoko_solver import Solver, solve

# 方式 1：使用 Solver 类
s = Solver(time_limit=5.0, debug=False)
s.load(grid)           # grid: list[list[int]], 0=空, >0=线索
ok = s.solve()         # 返回是否找到解
s.pc()                 # 打印当前状态

# 方式 2：快捷函数
ok, solver = solve(grid, tl=5.0, debug=True)
```

## 依赖

- Python ≥ 3.12
- [requests](https://pypi.org/project/requests/)（网页抓取）

通过 `uv` 管理环境和依赖（`pyproject.toml`）。

## 注意事项

- 纯 ASCII 显示，无 ANSI 转义码，每格固定 4 字符宽度
- 时间限制仅作用于 DFS 回溯阶段（当前已禁用）；传播和 try-both 无时间限制
- `--time` 参数保留，供未来启用 DFS 时使用
