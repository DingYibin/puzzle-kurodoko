"""
Kurodoko (Kuromasu / 田鼠挖洞) Puzzle Solver — CLI

Usage:
    uv run python main.py                     # Random 5×5 puzzle
    uv run python main.py --size 10           # Specify size (5, 7, 10, 15, 20)
    uv run python main.py --id 1234           # Puzzle by ID
    uv run python main.py --daily             # Daily puzzle
    uv run python main.py --load path.json    # Load from file
    uv run python main.py -p                  # Print puzzle only (no solve)
    uv run python main.py --trace             # Animate with committed steps
    uv run python main.py --trace-full        # Animate with full trace + backtracking
    uv run python main.py --trace-delay 50    # Set animation delay in ms (default 10)
"""

import json
import os
import random
import re
import sys
import time
from datetime import datetime

import requests

from kurodoko_solver import Solver


# Size parameter mapping (cn.puzzle-kurodoko.com)
SIZE_MAP = {
    '5': '0',        # 5×5
    '7': '1',        # 7×7
    '10': '2',       # 10×10
    '15': '3',       # 15×15
    '20': '4',       # 20×20
    'daily': '5',
    'weekly': '6',
    'monthly': '7',
}


def decode_char(c: str) -> int:
    """Decode a lowercase letter to a count: 'a'=1, 'b'=2, ..., 'z'=26."""
    return ord(c) - 96


def decode(task: str, width: int) -> list[list[int]]:
    """Decode task RLE string into a 2D grid.

    Encoding:
      - Numbers        → clue value at current position
      - '_'            → separator between consecutive numbers
      - 'a'–'z'        → skip N positions (empty cells, no clue)

    Returns a 2D list where 0 = empty cell (no clue), positive = clue number.
    """
    cells: list[int] = []
    i = 0
    n = len(task)
    pos = 0
    while i < n:
        ch = task[i]
        if ch.isdigit():
            # Parse multi-digit number
            j = i
            while j < n and task[j].isdigit():
                j += 1
            val = int(task[i:j])
            cells.append(val)
            pos += 1
            i = j
        elif ch == '_':
            # Separator — skip
            i += 1
        else:
            # Lowercase letter — skip N empty cells
            count = decode_char(ch)
            cells.extend([0] * count)
            pos += count
            i += 1

    # Convert flat array to 2D grid (row-major)
    height = len(cells) // width
    return [cells[r * width:(r + 1) * width] for r in range(height)]


def encode(grid: list[list[int]]) -> str:
    """Encode a 2D grid back to task RLE string."""
    height = len(grid)
    width = len(grid[0]) if height > 0 else 0
    flat = [grid[r][c] for r in range(height) for c in range(width)]
    result = []
    prev_was_number = False
    i = 0
    n = len(flat)
    while i < n:
        if flat[i] > 0:
            # Insert separator between consecutive numbers
            if prev_was_number:
                result.append('_')
            result.append(str(flat[i]))
            prev_was_number = True
            i += 1
        else:
            # Count consecutive empty cells
            j = i
            while j < n and flat[j] == 0:
                j += 1
            count = j - i
            while count > 0:
                chunk = min(count, 26)
                result.append(chr(ord('a') + chunk - 1))
                count -= chunk
            prev_was_number = False
            i = j
    return ''.join(result)


def is_task_valid(task: str) -> bool:
    """Check that lowercase runs (besides the last one) are exactly 26 long.

    This mirrors the canonical encoding used by the website: consecutive
    lowercase letters must all be 'z' except possibly the last one.
    """
    i = 0
    n = len(task)
    while i < n:
        if task[i].islower():
            j = i
            while j < n and task[j].islower():
                j += 1
            if j - i > 1:
                for k in range(i, j - 1):
                    if task[k] != 'z':
                        return False
            i = j
        else:
            i += 1
    return True


def fetch_puzzle(url: str) -> tuple:
    """Fetch puzzle from website, retry up to 9 times.

    Returns:
        (task_str, width, height, puzzle_id, selected_date)
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    for _ in range(9):
        try:
            r = requests.get(url, headers=headers, timeout=30)
            r.raise_for_status()
            html = r.text

            task_m = re.search(r"var\s+task\s*=\s*'([^']+)'", html)
            task = task_m.group(1) if task_m else None

            w_m = re.search(r'puzzleWidth\s*:\s*(\d+)', html)
            h_m = re.search(r'puzzleHeight\s*:\s*(\d+)', html)
            width = int(w_m.group(1)) if w_m else 0
            height = int(h_m.group(1)) if h_m else 0

            if task and width > 0 and is_task_valid(task):
                pid = None
                id_m = re.search(r'id="puzzleID"\s*>\s*([0-9,]+)', html)
                if id_m:
                    pid = id_m.group(1)

                selected_date = None
                date_m = re.search(
                    r'<option\s+value="([^"]*)"[^>]*selected="selected"', html
                )
                if date_m:
                    selected_date = date_m.group(1).strip()
                if not selected_date:
                    date_m = re.search(
                        r'<option[^>]+selected="selected"[^>]*>\s*'
                        r'([A-Za-z]+\s+\d+,\s*\d+)\s*</option>',
                        html,
                    )
                    if date_m:
                        selected_date = date_m.group(1).strip()

                return task, width, height, pid, selected_date
        except Exception as e:
            print(f"获取谜题失败: {e}")
        d = max(0.1, min(3.0, random.gauss(1, 0.5)))
        time.sleep(d)
    return None, 0, 0, None, None


def fetch_by_id(size_param: str, puzzle_id: int) -> tuple:
    """Fetch a specific puzzle by ID via POST, retry up to 5 times.

    Returns:
        (task_str, width, height, puzzle_id_str)
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    for _ in range(5):
        try:
            s = requests.Session()
            r = s.post(
                "https://cn.puzzle-kurodoko.com/",
                headers=headers,
                data=f"specific=1&size={size_param}&specid={puzzle_id}",
                timeout=30,
            )
            html = r.text
            task_m = re.search(r"var\s+task\s*=\s*'([^']+)'", html)
            w_m = re.search(r'puzzleWidth\s*:\s*(\d+)', html)
            if task_m and w_m:
                task = task_m.group(1)
                w = int(w_m.group(1))
                if is_task_valid(task):
                    h_m = re.search(r'puzzleHeight\s*:\s*(\d+)', html)
                    h = int(h_m.group(1)) if h_m else w
                    pid = None
                    id_m = re.search(r'id="puzzleID"\s*>\s*([0-9,]+)', html)
                    if id_m:
                        pid = id_m.group(1)
                    return task, w, h, pid
        except Exception as e:
            print(f"获取谜题失败: {e}")
        d = max(0.1, min(3.0, random.gauss(1, 0.5)))
        time.sleep(d)
    return None, 0, 0, None


def get_puzzle(size_key: str = "5") -> tuple:
    """Fetch a random puzzle. Returns (grid, N, pid, selected_date, size_key)."""
    size_param = SIZE_MAP.get(size_key, '0')
    url = f"https://cn.puzzle-kurodoko.com/?size={size_param}"
    task, w, h, pid, sel_date = fetch_puzzle(url)
    if task and w > 0 and h > 0:
        grid = decode(task, w)
        print(f"获取到 {w}x{h} 谜题 (ID: {pid or '?'})")
        return grid, w, pid, sel_date, size_key
    print("获取谜题失败")
    return None, 0, None, None, None


# ── Visualization ────────────────────────────────────────────────

# ANSI color codes
# (plain ASCII display — no ANSI codes)


def _col_label(c: int) -> str:
    """Convert 0-based column index to 1-based number."""
    return str(c + 1)


def _row_label(r: int) -> str:
    """Convert 0-based row index to 1-based number."""
    return str(r + 1)


def print_puzzle(grid: list[list[int]], *, solved: bool = False) -> None:
    """Print the puzzle grid with ANSI color backgrounds."""
    RE = "\033[0m"
    WBG = "\033[47;30m"
    GBG = "\033[100;30m"
    BBG = "\033[40;97m"
    height = len(grid)
    if height == 0:
        return
    width = len(grid[0])

    cell_w = 4
    label_w = max(2, len(str(height)))

    # Column header
    print((' ' * (label_w + 2) + ''.join(
        _col_label(c).rjust(cell_w - 1) + ' ' for c in range(width)
    )).rstrip())

    for r in range(height):
        row_cells = []
        for c in range(width):
            val = grid[r][c]
            if solved and val == -1:
                row_cells.append(f'{BBG}{"B".rjust(cell_w - 1)} {RE}')
            elif val > 0:
                row_cells.append(f'{WBG}{str(val).rjust(cell_w - 1)} {RE}')
            else:
                row_cells.append(f'{GBG}{".".rjust(cell_w - 1)} {RE}')
        print(f'{_row_label(r).rjust(label_w + 1)} {"".join(row_cells)}')


# ── Save / Load ──────────────────────────────────────────────────

def save_puzzle(grid: list[list[int]], **extra) -> str:
    """Save puzzle to puzzles/<timestamp>.json. Returns filepath."""
    task = encode(grid)
    h = len(grid)
    w = len(grid[0]) if h > 0 else 0
    data = {"task": task, "puzzleWidth": w, "puzzleHeight": h, **extra}
    filename = "puzzle-kurodoko_" + datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + ".json"
    os.makedirs("puzzles", exist_ok=True)
    filepath = os.path.join("puzzles", filename)
    with open(filepath, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"谜题已保存到 {filepath}")
    return filepath


def load_puzzle(path: str) -> list[list[int]]:
    """Load puzzle from a JSON file. Returns grid."""
    with open(path) as f:
        data = json.load(f)
    task = data["task"]
    w = data["puzzleWidth"]
    h = data.get("puzzleHeight", w)
    grid = decode(task, w)
    print(f"从 {path} 加载 {w}x{h} 谜题")
    return grid


# ── Main CLI ─────────────────────────────────────────────────────

def main():
    size = "5"
    use_daily = '--daily' in sys.argv
    use_weekly = '--weekly' in sys.argv
    use_monthly = '--monthly' in sys.argv
    puzzle_id = None
    print_only = '-p' in sys.argv
    use_save = '--save' in sys.argv
    load_path = None
    time_limit = 5.0
    debug = '--debug' in sys.argv or '-v' in sys.argv
    trace = '--trace' in sys.argv
    trace_full = '--trace-full' in sys.argv
    trace_delay = 0.01

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] in ('--size', '-s') and i + 1 < len(args):
            size = args[i + 1]
            i += 2
        elif args[i] in ('--id', '-n') and i + 1 < len(args):
            try:
                puzzle_id = int(args[i + 1])
            except ValueError:
                pass
            i += 2
        elif args[i] == '--load' and i + 1 < len(args):
            load_path = args[i + 1]
            i += 2
        elif args[i] == '--time' and i + 1 < len(args):
            try:
                time_limit = float(args[i + 1])
            except ValueError:
                pass
            i += 2
        elif args[i] == '--trace-delay' and i + 1 < len(args):
            try:
                trace_delay = float(args[i + 1]) / 1000.0
            except ValueError:
                pass
            i += 2
        else:
            i += 1

    grid = None
    N = 0
    puzzle_meta = {}

    if load_path:
        grid = load_puzzle(load_path)
        N = len(grid) if grid else 0
    elif use_daily:
        print("获取每日谜题...")
        grid, N, pid, sel_date, sk = get_puzzle('daily')
        puzzle_meta = {"puzzleSize": sk, "puzzleId": pid, "puzzleDate": sel_date}
    elif use_weekly:
        print("获取每周谜题...")
        grid, N, pid, sel_date, sk = get_puzzle('weekly')
        puzzle_meta = {"puzzleSize": sk, "puzzleId": pid, "puzzleDate": sel_date}
    elif use_monthly:
        print("获取每月谜题...")
        grid, N, pid, sel_date, sk = get_puzzle('monthly')
        puzzle_meta = {"puzzleSize": sk, "puzzleId": pid, "puzzleDate": sel_date}
    elif puzzle_id is not None:
        size_param = SIZE_MAP.get(size, '0')
        print(f"获取谜题 (size={size}, id={puzzle_id})...")
        task, w, h, pid = fetch_by_id(size_param, puzzle_id)
        if task and w > 0:
            grid = decode(task, w)
            N = w
            puzzle_meta = {"puzzleSize": size, "puzzleId": str(puzzle_id)}
            print(f"获取到 {w}x{h} 谜题 (ID: {puzzle_id})")
        else:
            print("未找到谜题数据")
    else:
        grid, N, pid, sel_date, sk = get_puzzle(size)
        puzzle_meta = {"puzzleSize": sk, "puzzleId": pid, "puzzleDate": sel_date}

    if grid is None:
        print("没有谜题")
        return

    print_puzzle(grid)

    clue_count = sum(1 for row in grid for v in row if v > 0)
    print(f"\n{N}x{N} 谜题 | 线索数: {clue_count}/{N * N}")

    if print_only:
        return

    # Solve
    solver = Solver(time_limit=time_limit, debug=debug)
    solver.load(grid)
    print(f"求解 {solver.N}x{solver.N} 谜题...")

    t0 = time.time()
    ok = solver.solve()
    elapsed = time.time() - t0

    if trace or trace_full:
        solver.animate(delay=trace_delay, full_trace=trace_full, elapsed=elapsed)
    else:
        solver.pc()
        if ok:
            print(f"\n✅ 找到解")
        else:
            print(f"\n❌ 未找到解")
        solver._print_stats(elapsed)

    if use_save:
        save_puzzle(grid, **puzzle_meta)


if __name__ == "__main__":
    main()
