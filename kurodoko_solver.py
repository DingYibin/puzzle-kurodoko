"""
Kurodoko (Kuromasu / 田鼠挖洞) Solver

State:  0 = UNKNOWN,  1 = WHITE,  -1 = BLACK
Clues:  >0 value stored separately, cells are fixed WHITE.

Strategy: DFS + LOS propagation + no-adjacent-black + white connectivity.
"""

import time
import functools


def timer(func):
    """Decorator: records execution time in self._method_times[func_name]."""
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        t0 = time.time()
        try:
            return func(self, *args, **kwargs)
        finally:
            elapsed = time.time() - t0
            name = func.__name__
            if not hasattr(self, '_method_times'):
                self._method_times = {}
            self._method_times[name] = self._method_times.get(name, 0.0) + elapsed
    return wrapper

UNKNOWN = 0
WHITE = 1
BLACK = -1


class Solver:
    def __init__(self, time_limit=5.0, debug=False):
        self.tlim = time_limit
        self.debug = debug
        self.N = 0
        self.state = []       # UNKNOWN / WHITE / BLACK
        self.clues = []       # 0 or clue value (>0)
        self.fixed = []       # True = cannot change (clue cells)
        self.nodes = 0
        self.t0 = 0
        self._dirty = False
        self._timing = {}
        self._satisfied = [[False] * self.N for _ in range(self.N)]
        self._action = []     # committed actions (r, c, old, new) — snap/backtrack boundary
        self._trace = []      # all actions + undo actions (r, c, old, new) — full history
        self._pair_sets = 0
        self._build_watchers()

    def _build_watchers(self):
        self._watchers = [[[] for _ in range(self.N)] for _ in range(self.N)]
        for r in range(self.N):
            for c in range(self.N):
                if self.clues[r][c] > 0:
                    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                        nr, nc = r + dr, c + dc
                        while 0 <= nr < self.N and 0 <= nc < self.N:
                            self._watchers[nr][nc].append((r, c))
                            if self.state[nr][nc] == BLACK:
                                break
                            nr += dr
                            nc += dc

    # ── load ────────────────────────────────────────────────────

    def load(self, grid: list[list[int]]):
        """Load puzzle from decoded grid (0=empty, >0=clue)."""
        self.N = len(grid)
        self.state = [[UNKNOWN] * self.N for _ in range(self.N)]
        self.clues = [[0] * self.N for _ in range(self.N)]
        self.fixed = [[False] * self.N for _ in range(self.N)]
        self._satisfied = [[False] * self.N for _ in range(self.N)]
        self._pair_sets = 0
        for r in range(self.N):
            for c in range(self.N):
                v = grid[r][c]
                if v > 0:
                    self.clues[r][c] = v
                    self.state[r][c] = WHITE
                    self.fixed[r][c] = True
        self._build_watchers()
        # Initialize clue data array for all clue cells
        self._clue_data = [[None] * self.N for _ in range(self.N)]
        for r in range(self.N):
            for c in range(self.N):
                if self.clues[r][c] > 0:
                    self._clue_data[r][c] = self._compute_clue_data(r, c)

    # ── main solve ──────────────────────────────────────────────

    @timer
    def solve(self) -> bool:
        self.t0 = time.time()
        self.nodes = 0
        self._action = []
        self._trace = []
        self._timing = {"propagate": 0.0, "try_both": 0.0, "rounds": []}

        # Phase 1-2: Propagate rules + rowcol
        t0 = time.time()
        if not self._propagate():
            return False
        self._timing["propagate"] += time.time() - t0

        # Phase 3: Iterative try-both until no more progress
        while True:
            t0 = time.time()
            if not self._try_both():
                return False
            tb_t = time.time() - t0
            if not self._dirty:
                self._timing["try_both"] += tb_t
                break

            self._dirty = False
            t0 = time.time()
            if not self._propagate():
                return False
            p_t = time.time() - t0
            self._timing["try_both"] += tb_t
            self._timing["propagate"] += p_t
            self._timing["rounds"].append((tb_t, p_t))

        # Phase 4: DFS for remaining unknowns
        ok = all(self.state[r][c] != UNKNOWN for r in range(self.N) for c in range(self.N))
        if not ok:
            if self.debug:
                print(f"\n-- DFS: {sum(1 for r in range(self.N) for c in range(self.N) if self.state[r][c] == UNKNOWN)} unknowns --")
            t0 = time.time()
            ok = self._dfs()
            self._timing.setdefault("dfs", 0.0)
            self._timing["dfs"] += time.time() - t0
        return ok

    # ── DFS ─────────────────────────────────────────────────────

    @timer
    def _dfs(self) -> bool:
        if self.t0 and time.time() - self.t0 > self.tlim:
            return False
        self.nodes += 1

        if not self._propagate():
            return False

        target, best_clue = self._select_cell()
        if target is None:
            if self.debug:
                print(f"\n-- ok node#{self.nodes}: all determined --")
                self.pc()
            return True  # no unknowns left -> solved

        r, c = target
        pos = self._snap()

        for val in (WHITE, BLACK):
            if self.debug:
                label = 'WHITE' if val == WHITE else 'BLACK'
                print(f"\n-- branch #{self.nodes}: set ({r},{c})={label} --")
            if not self._set(r, c, val):
                self._backtrack(pos)
                continue

            # After setting target, try nearby unknowns around best_clue
            if best_clue is not None:
                br, bc = best_clue
                failed = False
                for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nr, nc = br + dr, bc + dc
                    while 0 <= nr < self.N and 0 <= nc < self.N:
                        if self.state[nr][nc] == UNKNOWN:
                            result = self._try_cell_both(nr, nc)
                            if result == -1:
                                failed = True
                            break
                        if self.state[nr][nc] == BLACK:
                            break
                        nr += dr
                        nc += dc
                    if failed:
                        break
                if failed:
                    self._backtrack(pos)
                    continue

            if self._dfs():
                return True
            self._backtrack(pos)

        return False

    # ── select cell (heuristic) ─────────────────────────────────

    @timer
    def _select_cell(self) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
        """Pick the nearest UNKNOWN cell from the smallest unsatisfied clue.

        Returns (unknown_cell, best_clue).  unknown_cell is the nearest UNKNOWN
        in LOS of the smallest unsatisfied clue (fallback: first UNKNOWN on
        board).  best_clue is that clue, or None if all clues are satisfied.
        Returns (None, None) when no UNKNOWN remains.
        """
        best_clue = None
        best_n = float('inf')
        for r in range(self.N):
            for c in range(self.N):
                if self.clues[r][c] > 0 and not self._satisfied[r][c]:
                    n = self.clues[r][c]
                    if n < best_n:
                        best_n = n
                        best_clue = (r, c)

        if best_clue is not None:
            r, c = best_clue
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nr, nc = r + dr, c + dc
                while 0 <= nr < self.N and 0 <= nc < self.N:
                    if self.state[nr][nc] == UNKNOWN:
                        return (nr, nc), best_clue
                    if self.state[nr][nc] == BLACK:
                        break
                    nr += dr
                    nc += dc
        # Fallback: first UNKNOWN on the board
        for r in range(self.N):
            for c in range(self.N):
                if self.state[r][c] == UNKNOWN:
                    return (r, c), best_clue
        return None, None

    # ── propagation ─────────────────────────────────────────────

    @timer
    def _propagate(self, quiet=False) -> bool:
        """Run all propagation rules until convergence.

        Args:
            quiet: If True, suppress debug output.

        Returns False on contradiction.
        """
        show_debug = self.debug and not quiet
        # Initial full row/column pass (incremental _set cascade only triggers
        # on later changes; the initial clue cells need a full scan)
        if not self._propagate_rowcol():
            return False
        # All rules handled inline by _set's cascade

        # Update clue satisfaction cache
        for r in range(self.N):
            for c in range(self.N):
                if self.clues[r][c] > 0:
                    self._satisfied[r][c] = self._clue_satisfied(r, c)

        if show_debug:
            print("\n── 传播收敛 ──")
            sat = sum(1 for r in range(self.N) for c in range(self.N) if self._satisfied[r][c])
            total = sum(1 for r in range(self.N) for c in range(self.N) if self.clues[r][c] > 0)
            if sat != total:
                print(f"  线索满足: {sat}/{total}")

        return True

    @timer
    def _analyze_state(self):
        print("\n── 传播后状态分析 ──")
        n_white = sum(1 for r in range(self.N) for c in range(self.N) if self.state[r][c] == WHITE and self.clues[r][c] == 0)
        n_black = sum(1 for r in range(self.N) for c in range(self.N) if self.state[r][c] == BLACK)
        n_clue = sum(1 for r in range(self.N) for c in range(self.N) if self.clues[r][c] > 0)
        n_unknown = sum(1 for r in range(self.N) for c in range(self.N) if self.state[r][c] == UNKNOWN)
        total = n_white + n_black + n_clue + n_unknown
        print(f"  白={n_white}  黑={n_black}  线索={n_clue}  未知={n_unknown}  (总计{total})")
        sat = sum(1 for r in range(self.N) for c in range(self.N) if self._satisfied[r][c])
        print(f"  线索满足: {sat}/{n_clue}")
        unsat = [(r,c) for r in range(self.N) for c in range(self.N) if self.clues[r][c] > 0 and not self._satisfied[r][c]]
        if unsat:
            print(f"  未满足线索 ({len(unsat)}个):")
            for r,c in unsat:
                info, tm, tx = self._scan_clue(r, c)
                dirs_info = [(info[i][0], info[i][1], len(info[i][2])) for i in range(4)]
                print(f"    ({r},{c})={self.clues[r][c]}: 范围[{tm},{tx}]  方向mn/mx/未知={dirs_info}")
        watcher_counts = [(len(self._watchers[r][c]), r, c) for r in range(self.N) for c in range(self.N) if self.state[r][c] == UNKNOWN]
        watcher_counts.sort(reverse=True)
        if watcher_counts:
            print(f"  剩余未知格: {len(watcher_counts)}")
            print(f"  最受约束的5格:")
            for cnt, r, c in watcher_counts[:5]:
                clues_near = ', '.join(f"({wr},{wc})={self.clues[wr][wc]}" for wr,wc in self._watchers[r][c][:4])
                print(f"    ({r},{c}): {cnt}个watcher [{clues_near}]")
        sharing = 0
        for r in range(self.N):
            clues_in_row = [(c, self.clues[r][c]) for c in range(self.N) if self.clues[r][c] > 0]
            for i in range(len(clues_in_row)-1):
                c1, c2 = clues_in_row[i][0], clues_in_row[i+1][0]
                gap = all(self.state[r][cc] == WHITE for cc in range(c1+1, c2))
                if gap and c2 - c1 > 1:
                    sharing += 1
        if sharing:
            print(f"  可交叠分析的行/列对: {sharing}对")
        print("")

    # ── Rule 1: no adjacent BLACK ───────────────────────────────

    # ── Rule 2: clue LOS ────────────────────────────────────────

    def _compute_clue_data(self, r: int, c: int) -> tuple:
        """Compute LOS scan result for clue (r,c) from current state."""
        dirs = ((-1, 0), (1, 0), (0, -1), (0, 1))
        info = []
        for dr, dc in dirs:
            mn = mx = 0
            counting = True
            nr, nc = r + dr, c + dc
            while 0 <= nr < self.N and 0 <= nc < self.N:
                val = self.state[nr][nc]
                if val == BLACK:
                    break
                mx += 1
                if val == WHITE:
                    if counting:
                        mn += 1
                elif val == UNKNOWN:
                    if counting:
                        counting = False
                nr += dr
                nc += dc
            info.append((mn, mx))
        total_min = 1 + sum(mn for mn, _ in info)
        total_max = 1 + sum(mx for _, mx in info)
        return info, total_min, total_max

    def _scan_dir(self, r: int, c: int, dr: int, dc: int) -> tuple:
        """Scan one direction from (r,c) and return (min, max, unknowns)."""
        mn = mx = 0
        unknowns = []
        counting_min = True
        nr, nc = r + dr, c + dc
        while 0 <= nr < self.N and 0 <= nc < self.N:
            val = self.state[nr][nc]
            if val == BLACK:
                break
            mx += 1
            if val == WHITE:
                if counting_min:
                    mn += 1
            elif val == UNKNOWN:
                if counting_min:
                    counting_min = False
                unknowns.append((nr, nc))
            nr += dr
            nc += dc
        return mn, mx, unknowns

    @timer
    def _update_clues_for_cell(self, r: int, c: int):
        """Scan 4 directions from (r,c) to update affected clues' LOS data.

        For each direction, first scan OPPOSITE from (r,c) for the "tail",
        then walk FORWARD; at each clue encountered, snapshot the tail
        as the clue's opposite-direction LOS.  O(L) per direction.
        """
        if not self._watchers[r][c]:
            return
        dirs = ((-1, 0), (1, 0), (0, -1), (0, 1))
        clue_dir = (1, 0, 3, 2)  # forward dir → clue's affected dir
        for si, (dr, dc) in enumerate(dirs):
            # Tail: scan opposite direction FROM (r,c) including (r,c) itself
            tail_mn = tail_mx = 0
            counting = True
            if self.state[r][c] != BLACK:
                tail_mx = 1
                if self.state[r][c] == WHITE:
                    tail_mn = 1
                else:
                    counting = False
                nr, nc = r - dr, c - dc
                while 0 <= nr < self.N and 0 <= nc < self.N:
                    val = self.state[nr][nc]
                    if val == BLACK:
                        break
                    tail_mx += 1
                    if val == WHITE:
                        if counting:
                            tail_mn += 1
                    else:
                        if counting:
                            counting = False
                    nr -= dr
                    nc -= dc

            # Forward walk, maintaining tail incrementally for clue updates
            nr, nc = r + dr, c + dc
            while 0 <= nr < self.N and 0 <= nc < self.N:
                val = self.state[nr][nc]
                if val == BLACK:
                    break
                if self.clues[nr][nc] > 0:
                    # Clue found: snapshot current tail as its opposite-direction LOS
                    cd = clue_dir[si]
                    old_info = self._clue_data[nr][nc][0]
                    old_info[cd] = (tail_mn, tail_mx)
                    new_tm = 1 + sum(m for m, _ in old_info)
                    new_tx = 1 + sum(mx for _, mx in old_info)
                    self._clue_data[nr][nc] = (old_info, new_tm, new_tx)
                    # Merge into cumulative tail for subsequent clues
                    tail_mn += 1
                    tail_mx += 1
                else:
                    if val == UNKNOWN:
                        tail_mn = 0
                    else:  # val == WHITE
                        tail_mn += 1
                    tail_mx += 1
                nr += dr
                nc += dc

    @timer
    def _scan_clue(self, r: int, c: int) -> tuple:
        """Return cached LOS data for clue at (r,c) from _clue_data array."""
        return self._clue_data[r][c]

    @timer
    def _clue_satisfied(self, r: int, c: int) -> bool:
        """Return True if clue at (r,c) is exactly satisfied (min==max==N)."""
        _, total_min, total_max = self._scan_clue(r, c)
        N = self.clues[r][c]
        return total_min == total_max == N

    @timer
    def _propagate_clue(self, r: int, c: int) -> bool:
        N = self.clues[r][c]
        info, total_min, total_max = self._scan_clue(r, c)
        if N < total_min or N > total_max:
            return False

        dirs = ((-1, 0), (1, 0), (0, -1), (0, 1))

        # Unconditional: N == total_min / total_max
        if N == total_min:
            for i, (mn, mx) in enumerate(info):
                if mn < mx:  # has unknown at position mn+1
                    dr, dc = dirs[i]
                    nr = r + dr * (mn + 1)
                    nc = c + dc * (mn + 1)
                    if not self._set(nr, nc, BLACK):
                        return False
        if N == total_max:
            for i, (mn, mx) in enumerate(info):
                if mn < mx:
                    dr, dc = dirs[i]
                    pos = 0
                    nr, nc = r + dr, c + dc
                    while 0 <= nr < self.N and 0 <= nc < self.N and pos < mx:
                        if self.state[nr][nc] == UNKNOWN:
                            if not self._set(nr, nc, WHITE):
                                return False
                        nr += dr
                        nc += dc
                        pos += 1

        # Conditional: per-direction constraints
        if N != total_min and N != total_max:
            for i, (mn, mx) in enumerate(info):
                if mn == mx:  # no unknowns in this direction
                    continue
                other_min = sum(info[j][0] for j in range(4) if j != i)
                other_max = sum(info[j][1] for j in range(4) if j != i)
                need_min = max(mn, N - 1 - other_max)
                need_max = min(mx, N - 1 - other_min)
                if need_min > need_max:
                    return False
                # If we need more whites than guaranteed, set unknowns in range
                if need_min > mn:
                    dr, dc = dirs[i]
                    nr, nc = r + dr, c + dc
                    pos = 0
                    while 0 <= nr < self.N and 0 <= nc < self.N and pos < need_min:
                        if self.state[nr][nc] == UNKNOWN:
                            if not self._set(nr, nc, WHITE):
                                return False
                        nr += dr
                        nc += dc
                        pos += 1
                if need_min == need_max:
                    other_no_unk = all(info[j][0] == info[j][1] for j in range(4) if j != i)
                    if other_no_unk:
                        # All other directions determined -> set directly
                        dr, dc = dirs[i]
                        pos = 0
                        nr, nc = r + dr, c + dc
                        while 0 <= nr < self.N and 0 <= nc < self.N and pos < need_min:
                            if self.state[nr][nc] == UNKNOWN:
                                if not self._set(nr, nc, WHITE):
                                    return False
                            nr += dr
                            nc += dc
                            pos += 1
                        # Cell at position need_min must be BLACK (blocking)
                        if 0 <= nr < self.N and 0 <= nc < self.N:
                            if self.state[nr][nc] == UNKNOWN:
                                if not self._set(nr, nc, BLACK):
                                    return False
        return True
    # ── Rule 3: white connectivity ──────────────────────────────


    @timer
    def _find_nearest_white(self, r: int, c: int):
        """BFS from (r,c) to find a reachable WHITE cell through UNKNOWN paths.

        - BLACK cell → None
        - WHITE cell → (r, c)
        - UNKNOWN cell → BFS through UNKNOWN cells until a WHITE is found, return its coords
        - No reachable WHITE → None
        """
        if self.state[r][c] == BLACK:
            return None
        if self.state[r][c] == WHITE:
            return (r, c)
        # UNKNOWN: BFS through UNKNOWN cells
        visited = [[False] * self.N for _ in range(self.N)]
        q = [(r, c)]
        visited[r][c] = True
        while q:
            cr, cc = q.pop()
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nr, nc = cr + dr, cc + dc
                if not (0 <= nr < self.N and 0 <= nc < self.N):
                    continue
                if visited[nr][nc]:
                    continue
                if self.state[nr][nc] == BLACK:
                    continue
                if self.state[nr][nc] == WHITE:
                    return (nr, nc)
                # UNKNOWN: continue BFS
                visited[nr][nc] = True
                q.append((nr, nc))
        return None

    @timer
    def _are_whites_connected(self, cells: list[tuple[int, int]]) -> bool:
        """Check if all WHITE cells in the given list are connected via WHITE/UNKNOWN paths.

        Returns True if ≤ 1 cell, or BFS from first cell reaches all others.
        """
        if len(cells) <= 1:
            return True
        targets = set(cells[1:])  # cells[0] is the BFS start
        visited = [[False] * self.N for _ in range(self.N)]
        q = [cells[0]]
        visited[cells[0][0]][cells[0][1]] = True
        remaining = len(targets)
        while q and remaining:
            cr, cc = q.pop()
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nr, nc = cr + dr, cc + dc
                if not (0 <= nr < self.N and 0 <= nc < self.N):
                    continue
                if visited[nr][nc]:
                    continue
                if self.state[nr][nc] == BLACK:
                    continue
                if self.state[nr][nc] in (WHITE, UNKNOWN):
                    visited[nr][nc] = True
                    q.append((nr, nc))
                    if (nr, nc) in targets:
                        remaining -= 1
                        if remaining == 0:
                            return True
        return False

    @timer
    def _check_black_connectivity(self, r: int, c: int) -> bool:
        """Check if setting cell (r,c) to BLACK would disconnect whites.

        After _set(r,c,BLACK) cascaded rules 1+2, examine WHITE neighbors:
        find the nearest reachable WHITE from each, then verify all are
        still connected. Returns True if BLACK is safe, False if it would
        create a disconnection.
        """
        # Quick skip: boundary cells need 0 diagonal BLACKs, inner need <2
        is_boundary = r == 0 or r == self.N - 1 or c == 0 or c == self.N - 1
        diag_black = 0
        for dr, dc in ((-1, -1), (-1, 1), (1, -1), (1, 1)):
            nr, nc = r + dr, c + dc
            if 0 <= nr < self.N and 0 <= nc < self.N and self.state[nr][nc] == BLACK:
                diag_black += 1
        if diag_black < 2 if not is_boundary else diag_black == 0:
            return True

        whites = []
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nr, nc = r + dr, c + dc
            if 0 <= nr < self.N and 0 <= nc < self.N and self.state[nr][nc] != BLACK:
                fw = self._find_nearest_white(nr, nc)
                if fw is not None:
                    whites.append(fw)
        return self._are_whites_connected(whites)



    # ── Phase 2: row/column sharing analysis ──────────────

    @timer
    def _propagate_rowcol(self) -> bool:
        """Analyze clues sharing same row/column with white cells between them.

        If consecutive clues in a line have all WHITE cells between them,
        the excess visible count determines outer cell constraints.
        """
        # Scan rows
        for r in range(self.N):
            clues_in_row = [(c, self.clues[r][c]) for c in range(self.N) if self.clues[r][c] > 0]
            clues_in_row.sort()
            for i in range(len(clues_in_row) - 1):
                c1, n1 = clues_in_row[i]
                c2, n2 = clues_in_row[i+1]
                if not self._analyze_pair(r, c1, n1, r, c2, n2):
                    return False

        # Scan columns
        for c in range(self.N):
            clues_in_col = [(r, self.clues[r][c]) for r in range(self.N) if self.clues[r][c] > 0]
            clues_in_col.sort()
            for i in range(len(clues_in_col) - 1):
                r1, n1 = clues_in_col[i]
                r2, n2 = clues_in_col[i+1]
                if not self._analyze_pair(r1, c, n1, r2, c, n2):
                    return False
        return True

    def _propagate_clue_group(self, clues: list[tuple[int, int]], is_row: bool) -> bool:
        """Pair each clue with the most perpendicular-constrained clue in the group.

        All clues must share the same row (is_row=True) or same column (is_row=False).
        If same row: pivot = min(n − up_min − down_min), i.e. most constrained
        vertically. If same column: pivot = min(n − left_min − right_min).
        Then each clue is paired with the pivot via _analyze_pair.
        """
        if len(clues) <= 1:
            return True

        if is_row:
            def pivot_key(rc):
                r, c = rc
                info, _, _ = self._scan_clue(r, c)
                return self.clues[r][c] - info[0][0] - info[1][0]
        else:
            def pivot_key(rc):
                r, c = rc
                info, _, _ = self._scan_clue(r, c)
                return self.clues[r][c] - info[2][0] - info[3][0]

        pr, pc = min(clues, key=pivot_key)
        pn = self.clues[pr][pc]

        for r, c in clues:
            n = self.clues[r][c]
            if not self._analyze_pair(r, c, n, pr, pc, pn):
                return False
        return True

    def _propagate_from_white(self, r: int, c: int, is_row: bool) -> bool:
        """Scan from (r,c) along the given axis, collect clues, and run
        _propagate_clue_group.  is_row=True → scan horizontally (same row),
        is_row=False → scan vertically (same column).  The cell itself is
        included if it's a clue."""
        clues_found = []
        if is_row:
            for cc in range(c - 1, -1, -1):
                if self.state[r][cc] in (BLACK, UNKNOWN):
                    break
                if self.clues[r][cc] > 0:
                    clues_found.append((r, cc))
            for cc in range(c + 1, self.N):
                if self.state[r][cc] in (BLACK, UNKNOWN):
                    break
                if self.clues[r][cc] > 0:
                    clues_found.append((r, cc))
        else:
            for rr in range(r - 1, -1, -1):
                if self.state[rr][c] in (BLACK, UNKNOWN):
                    break
                if self.clues[rr][c] > 0:
                    clues_found.append((rr, c))
            for rr in range(r + 1, self.N):
                if self.state[rr][c] in (BLACK, UNKNOWN):
                    break
                if self.clues[rr][c] > 0:
                    clues_found.append((rr, c))
        if self.clues[r][c] > 0:
            clues_found.append((r, c))
        if clues_found and not self._propagate_clue_group(clues_found, is_row=is_row):
            return False
        return True

    @timer
    def _analyze_pair(self, r1, c1, n1, r2, c2, n2):
        """Analyze a pair of consecutive clues sharing a row or column."""

        if r1 == r2 and c1 == c2:
            return True
        if r1 == r2:
            # Same row
            lo, hi = (c1, c2) if c1 < c2 else (c2, c1)
            between = [(r1, cc) for cc in range(lo + 1, hi)]
        elif c1 == c2:
            # Same column
            lo, hi = (r1, r2) if r1 < r2 else (r2, r1)
            between = [(rr, c1) for rr in range(lo + 1, hi)]
        else:
            return True

        # All cells between must be determined WHITE
        for rr, cc in between:
            v = self.state[rr][cc]
            if v != WHITE:
                return True  # shared gap not fully white, can't deduce

        # Scan both clues to get per-direction info
        info_a, _, _ = self._scan_clue(r1, c1)
        info_b, _, _ = self._scan_clue(r2, c2)

        # Cross-clue deductions (4 pairs × 2 directions = 8 groups)
        if r1 == r2:
            # ── based on info_a → set on (r2,c2) ──
            v = info_a[0][0] + info_a[1][0] + n2 - n1 - info_b[1][1]
            if v > info_b[0][0]:
                nr, nc = r2 - 1, c2
                for _ in range(v):
                    if nr < 0: break
                    if self.state[nr][nc] == UNKNOWN:
                        if not self._set(nr, nc, WHITE): return False
                        self._pair_sets += 1
                    nr -= 1
            v = info_a[0][0] + info_a[1][0] + n2 - n1 - info_b[0][1]
            if v > info_b[1][0]:
                nr, nc = r2 + 1, c2
                for _ in range(v):
                    if nr >= self.N: break
                    if self.state[nr][nc] == UNKNOWN:
                        if not self._set(nr, nc, WHITE): return False
                        self._pair_sets += 1
                    nr += 1
            # ── based on info_b → set on (r1,c1) ──
            v = info_b[0][0] + info_b[1][0] + n1 - n2 - info_a[1][1]
            if v > info_a[0][0]:
                nr, nc = r1 - 1, c1
                for _ in range(v):
                    if nr < 0: break
                    if self.state[nr][nc] == UNKNOWN:
                        if not self._set(nr, nc, WHITE): return False
                        self._pair_sets += 1
                    nr -= 1
            v = info_b[0][0] + info_b[1][0] + n1 - n2 - info_a[0][1]
            if v > info_a[1][0]:
                nr, nc = r1 + 1, c1
                for _ in range(v):
                    if nr >= self.N: break
                    if self.state[nr][nc] == UNKNOWN:
                        if not self._set(nr, nc, WHITE): return False
                        self._pair_sets += 1
                    nr += 1
        elif c1 == c2:
            # ── based on info_a → set on (r2,c2) ──
            v = info_a[2][0] + info_a[3][0] + n2 - n1 - info_b[3][1]
            if v > info_b[2][0]:
                nr, nc = r2, c2 - 1
                for _ in range(v):
                    if nc < 0: break
                    if self.state[nr][nc] == UNKNOWN:
                        if not self._set(nr, nc, WHITE): return False
                        self._pair_sets += 1
                    nc -= 1
            v = info_a[2][0] + info_a[3][0] + n2 - n1 - info_b[2][1]
            if v > info_b[3][0]:
                nr, nc = r2, c2 + 1
                for _ in range(v):
                    if nc >= self.N: break
                    if self.state[nr][nc] == UNKNOWN:
                        if not self._set(nr, nc, WHITE): return False
                        self._pair_sets += 1
                    nc += 1
            # ── based on info_b → set on (r1,c1) ──
            v = info_b[2][0] + info_b[3][0] + n1 - n2 - info_a[3][1]
            if v > info_a[2][0]:
                nr, nc = r1, c1 - 1
                for _ in range(v):
                    if nc < 0: break
                    if self.state[nr][nc] == UNKNOWN:
                        if not self._set(nr, nc, WHITE): return False
                        self._pair_sets += 1
                    nc -= 1
            v = info_b[2][0] + info_b[3][0] + n1 - n2 - info_a[2][1]
            if v > info_a[3][0]:
                nr, nc = r1, c1 + 1
                for _ in range(v):
                    if nc >= self.N: break
                    if self.state[nr][nc] == UNKNOWN:
                        if not self._set(nr, nc, WHITE): return False
                        self._pair_sets += 1
                    nc += 1

        return True


    # ── Phase 2: domain reduction ───────────────────────────

    @timer
    def _propagate_domain(self) -> bool:
        for r in range(self.N):
            for c in range(self.N):
                if self.state[r][c] != UNKNOWN:
                    continue
                # Quick filter: only check cells adjacent to or in LOS of a clue
                has_clue = False
                for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nr, nc = r + dr, c + dc
                    while 0 <= nr < self.N and 0 <= nc < self.N:
                        if self.state[nr][nc] == BLACK:
                            break
                        if self.clues[nr][nc] > 0:
                            has_clue = True
                            break
                        nr += dr
                        nc += dc
                    if has_clue:
                        break
                if not has_clue:
                    continue

                # Test WHITE
                self.state[r][c] = WHITE
                white_ok = True
                for wr, wc in self._watchers[r][c]:
                    _, tm, tx = self._scan_clue(wr, wc)
                    if self.clues[wr][wc] < tm or self.clues[wr][wc] > tx:
                        white_ok = False
                        break
                # Test BLACK
                self.state[r][c] = BLACK
                black_ok = True
                for wr, wc in self._watchers[r][c]:
                    _, tm, tx = self._scan_clue(wr, wc)
                    if self.clues[wr][wc] < tm or self.clues[wr][wc] > tx:
                        black_ok = False
                        break
                # Restore
                self.state[r][c] = UNKNOWN

                if not white_ok and not black_ok:
                    return False
                if white_ok and not black_ok:
                    if not self._set(r, c, WHITE):
                        return False
                elif black_ok and not white_ok:
                    if not self._set(r, c, BLACK):
                        return False

    def _try_cell_both(self, r: int, c: int) -> int:
        """Try BLACK then WHITE on a single UNKNOWN cell with propagation.

        Returns:
            1  if a change was committed (WHITE forced or BLACK forced),
            0  if cell remains UNKNOWN (both colors viable),
            -1 on contradiction.
        """
        # Try BLACK: _set cascades rules 1+2; _check_black_connectivity verifies whites
        snap = self._snap()
        black_ok = self._set(r, c, BLACK)
        if black_ok and not self._check_black_connectivity(r, c):
            black_ok = False
        if black_ok:
            black_actions = list(self._action[snap:])  # recorded BLACK commit
        self._backtrack(snap)
        self._dirty = False

        if not black_ok:
            # BLACK impossible -> WHITE is forced (_set cascades rules 2+rowcol)
            if not self._set(r, c, WHITE):
                return -1  # contradiction
            return 1  # changed

        # BLACK is viable -> test WHITE (just _set; WHITE never disconnects)
        snap = self._snap()
        white_ok = self._set(r, c, WHITE)
        self._backtrack(snap)
        self._dirty = False

        if not white_ok:
            # Only BLACK works -- replay recorded state, no recomputation
            updated_trace = [(br, bc, ob, nb, len(self._trace) + i)
                             for i, (br, bc, ob, nb, _) in enumerate(black_actions)]
            updated_action = [(br, bc, ob, nb, len(self._trace) + i)
                              for i, (br, bc, ob, nb, _) in enumerate(black_actions)]
            self._trace.extend(updated_trace)
            self._action.extend(updated_action)
            for br, bc, _, bnew, _ in black_actions:
                self.state[br][bc] = bnew
                self._update_clues_for_cell(br, bc)
            self._dirty = True
            return 1  # changed

        return 0  # both ok, leave unknown

    @timer
    def _try_both(self) -> bool:
        """Try both WHITE and BLACK for each unknown cell with full propagation."""
        unknown_cells = [(r, c) for r in range(self.N) for c in range(self.N)
                         if self.state[r][c] == UNKNOWN]
        if self._action:
            lr, lc, _, _, _ = self._action[-1]
            unknown_cells.sort(key=lambda x: abs(x[0] - lr) + abs(x[1] - lc))
        changed = False

        for r, c in unknown_cells:
            if self.state[r][c] != UNKNOWN:
                continue  # already set by a previous try-both

            result = self._try_cell_both(r, c)
            if result == -1:
                return False  # contradiction
            if result == 1:
                changed = True

        self._dirty = changed
        return True

    # ── helper ──────────────────────────────────────────────────

    @timer
    def _set(self, r: int, c: int, val: int) -> bool:
        """Set a cell, record in trace/action, cascade all applicable rules.

        Cascades in order:
          1. Rule 1 (no adjacent BLACK) — enforced when setting BLACK
          2. Rule 2 (clue LOS) — via _propagate_clue for all watchers
          3. Row/column pair analysis — when setting WHITE, check adjacent clues

        Each cascaded _set call recursively enforces the same rules,
        eliminating the need for explicit passes in in_try mode.

        Returns False on contradiction, True otherwise.
        """
        old = self.state[r][c]
        if old != val:
            self._action.append((r, c, old, val, len(self._trace)))
            self._trace.append((r, c, old, val, len(self._trace)))
            self.state[r][c] = val
            self._dirty = True
            self._update_clues_for_cell(r, c)

            # Rule 1: no adjacent BLACK (immediate, no separate pass needed)
            if val == BLACK:
                for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < self.N and 0 <= nc < self.N:
                        if self.state[nr][nc] == BLACK:
                            return False  # adjacent blacks!
                        if self.state[nr][nc] == UNKNOWN:
                            if not self._set(nr, nc, WHITE):
                                return False

            # Rule 2: clue LOS cascade
            for wr, wc in self._watchers[r][c]:
                if not self._propagate_clue(wr, wc):
                    return False

            # Rule 3: Row/column pair analysis (triggered by white cells)
            if val == WHITE:
                if not self._check_rowcol_at(r, c):
                    return False
        return True

    @timer
    def _check_rowcol_at(self, r: int, c: int) -> bool:
        """Incremental pair analysis when a cell becomes WHITE.

        From (r,c), scan 4 directions for a clue. From each found clue,
        scan its 4 directions for another clue. For each pair found,
        call _analyze_pair to propagate constraints.
        """
        dirs = ((-1, 0), (1, 0), (0, -1), (0, 1))
        for dr, dc in dirs:
            nr, nc = r + dr, c + dc
            while 0 <= nr < self.N and 0 <= nc < self.N:
                if self.state[nr][nc] in (BLACK, UNKNOWN):
                    break
                if self.clues[nr][nc] > 0:
                    for dr2, dc2 in dirs:
                        nr2, nc2 = nr + dr2, nc + dc2
                        while 0 <= nr2 < self.N and 0 <= nc2 < self.N:
                            if self.state[nr2][nc2] in (BLACK, UNKNOWN):
                                break
                            if self.clues[nr2][nc2] > 0:
                                if not self._analyze_pair(nr, nc, self.clues[nr][nc],
                                                           nr2, nc2, self.clues[nr2][nc2]):
                                    return False
                            nr2 += dr2
                            nc2 += dc2
                    break
                nr += dr
                nc += dc
        return True

    def _snap(self) -> int:
        """Checkpoint current action position for rollback."""
        return len(self._action)

    @timer
    def _backtrack(self, pos: int):
        """Rollback actions after a checkpoint, recording undo in trace."""
        while len(self._action) > pos:
            r, c, old, new, _ = self._action.pop()
            self._trace.append((r, c, new, old, len(self._trace)))  # undo
            self.state[r][c] = old
            self._update_clues_for_cell(r, c)

    # ── display ─────────────────────────────────────────────────

    def animate(self, delay=0.01, full_trace=False, elapsed=0.0):
        """Animate solving process — per-cell ANSI updates.

        full_trace=True: replay self._trace (all steps incl. backtracking).
        full_trace=False: replay self._action (committed steps only).

        Shows animation with live counters, then stats at the end.
        """
        import time as _time
        import sys as _sys
        import os as _os

        steps = self._trace if full_trace else self._action
        if not steps:
            print("没有可动画化的步骤")
            return

        # ANSI codes — must match _print_puzzle exactly
        RE = "\033[0m"
        WBG = "\033[47;30m"
        BBG = "\033[40;97m"
        GBG = "\033[100;30m"
        cell_w = 4
        label_w = max(2, len(str(self.N)))
        total = len(self._trace)
        pw = len(str(total))

        # Column offset: label uses label_w+1 chars + 1 space before cells
        # So cell c's first visible char is at 1-based col: label_w + 3 + c*cell_w
        col_base = label_w + 3

        # Init display grid and live counters
        g = [[UNKNOWN] * self.N for _ in range(self.N)]
        wc = bc = 0
        uc = self.N * self.N
        for r in range(self.N):
            for c in range(self.N):
                if self.clues[r][c] > 0:
                    g[r][c] = WHITE
                    wc += 1
                    uc -= 1

        _os.system('clear')

        # ── Title ──
        _sys.stdout.write(f"动画: {total} 步 (delay={delay*1000:.0f}ms)".ljust(60) + "\n")

        # ── Column header ──
        _sys.stdout.write((' ' * (label_w + 2) + ''.join(
            _col_label(c).rjust(cell_w - 1) + ' ' for c in range(self.N)
        )).rstrip() + "\n")

        # ── Grid rows ──
        for r in range(self.N):
            cells = "".join(
                f"{WBG}{str(self.clues[r][c]).rjust(cell_w - 1)} {RE}"
                if self.clues[r][c] > 0 else
                f"{GBG}{'.'.rjust(cell_w - 1)} {RE}"
                for c in range(self.N)
            )
            _sys.stdout.write(f'{_row_label(r).rjust(label_w + 1)} {cells}')
            if r < self.N - 1:
                _sys.stdout.write("\n")

        # ── Live counter line ──
        _sys.stdout.write("\n")
        counter_row = self.N + 3
        _sys.stdout.write(f"白:{wc:>{pw}}  黑:{bc:>{pw}}  未知:{uc:>{pw}}")
        _sys.stdout.flush()
        _time.sleep(2)

        # ── Animate steps ──
        for r, c, old, new, step_i in steps:
            assert not self.fixed[r][c], f"Fixed cell should not be set, while ({r}, {c}) is set as {new}"

            # Update counters
            if old == UNKNOWN:   uc -= 1
            elif old == WHITE:   wc -= 1
            elif old == BLACK:   bc -= 1
            if new == UNKNOWN:   uc += 1
            elif new == WHITE:   wc += 1
            elif new == BLACK:   bc += 1

            g[r][c] = new
            remaining = total - step_i - 1

            # Progress (line 1)
            _sys.stdout.write(f"\033[1;1H动画: {remaining:>{pw}}/{total} 步剩余".ljust(60))

            # Cell content: grid row r is at line r+3, cell c at col_base + c*cell_w
            _sys.stdout.write(f"\033[{r + 3};{col_base + c * cell_w}H")
            if self.clues[r][c] > 0:
                _sys.stdout.write(f'{WBG}{str(self.clues[r][c]).rjust(cell_w - 1)} {RE}')
            elif new == BLACK:
                _sys.stdout.write(f'{BBG}{"B".rjust(cell_w - 1)} {RE}')
            elif new == WHITE:
                _sys.stdout.write(f'{WBG}{"W".rjust(cell_w - 1)} {RE}')
            else:
                _sys.stdout.write(f'{GBG}{".".rjust(cell_w - 1)} {RE}')

            # Live counters
            _sys.stdout.write(f"\033[{counter_row};1H白:{wc:>{pw}}  黑:{bc:>{pw}}  未知:{uc:>{pw}}   ")
            _sys.stdout.flush()
            _time.sleep(delay)

        _time.sleep(2)

        # ── Stats only ──
        _sys.stdout.write(f"\n")
        _sys.stdout.flush()
        self._print_stats(elapsed)

    @timer
    def pc(self):
        """Print current grid state (recalculates satisfaction)."""
        N = self.N
        for r in range(N):
            for c in range(N):
                if self.clues[r][c] > 0:
                    self._satisfied[r][c] = self._clue_satisfied(r, c)
        _print_puzzle(self.state, self.clues, self._satisfied)

    @timer
    def _print_stats(self, elapsed: float):
        def _fmt(t):
            return (f"{t * 1e6:.0f}μs" if t < 0.001 else
                    f"{t * 1000:.2f}ms" if t < 1.0 else
                    f"{t:.3f}s")

        n_unknown = sum(1 for r in range(self.N) for c in range(self.N)
                        if self.state[r][c] == UNKNOWN)
        n_white = sum(1 for r in range(self.N) for c in range(self.N)
                      if self.state[r][c] == WHITE)
        n_black = sum(1 for r in range(self.N) for c in range(self.N)
                      if self.state[r][c] == BLACK)
        print(f"总用时={_fmt(elapsed)}  节点={self.nodes}  "
              f"白={n_white} 黑={n_black} 未知={n_unknown}  "
              f"trace={len(self._trace)}  action={len(self._action)}  "
              f"pair_sets={self._pair_sets}")
        t = self._timing
        print(f"  传播={_fmt(t['propagate'])}  try_both={_fmt(t['try_both'])}  "
              f"({len(t['rounds'])}轮)")
        for i, (tb, p) in enumerate(t['rounds']):
            print(f"    第{i+1}轮:  try_both={_fmt(tb)}  传播={_fmt(p)}")

        mt = getattr(self, '_method_times', {})
        if mt:
            order = list(mt.keys())
            order.sort()
            print("  方法耗时:")
            max_len = max(len(name) for name in order if mt.get(name, 0) > 0)
            for name in order:
                t = mt.get(name) or 0.0
                if t > 0:
                    print(f"    {name:{max_len}} = {_fmt(t)}")


# ── standalone printer (reused by main.py) ─────────────────────

# (all ANSI codes removed — plain ASCII display)


def _col_label(c: int) -> str:
    return str(c + 1)


def _row_label(r: int) -> str:
    return str(r + 1)


def _print_puzzle(state: list[list[int]], clues: list[list[int]],
                  satisfied: list[list[bool]] | None = None):
    """Print grid with ANSI color backgrounds."""
    RE = "\033[0m"
    WBG = "\033[47;30m"
    GBG = "\033[100;30m"  # gray bg, black fg — unknown cells
    BBG = "\033[40;97m"  # black bg, white fg — black cells
    N = len(state)
    if N == 0:
        return

    cell_w = 4
    label_w = max(2, len(str(N)))

    print((' ' * (label_w + 2) + ''.join(
        _col_label(c).rjust(cell_w - 1) + ' ' for c in range(N)
    )).rstrip())

    for r in range(N):
        row_cells = []
        for c in range(N):
            val = state[r][c]
            clue_val = clues[r][c] if clues[r][c] > 0 else 0
            if clue_val > 0:
                row_cells.append(f'{WBG}{str(clue_val).rjust(cell_w - 1)} {RE}')
            elif val == BLACK:
                row_cells.append(f'{BBG}{"B".rjust(cell_w - 1)} {RE}')
            elif val == WHITE:
                row_cells.append(f'{WBG}{"W".rjust(cell_w - 1)} {RE}')
            else:
                row_cells.append(f'{GBG}{".".rjust(cell_w - 1)} {RE}')
        print(f'{_row_label(r).rjust(label_w + 1)} {"".join(row_cells)}')


def solve(grid: list[list[int]], tl=5.0, debug=True) -> tuple[bool, Solver]:
    """Convenience: load, solve, print."""
    s = Solver(time_limit=tl, debug=debug)
    s.load(grid)
    if debug:
        print(f"\n{s.N}x{s.N}")
        s.pc()
    ok = s.solve()
    if ok and debug:
        s.pc()
    elif not ok and debug:
        print(f"未找到解 (节点: {s.nodes})")
    return ok, s
