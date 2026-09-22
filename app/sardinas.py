"""
残串状态图（residual-string state graph）——自行构造，未使用任何现成
编码理论库或通用求解库。

设码字表 C = (c_0, ..., c_{n-1})（下标即工程师给出的优先顺序）。
两个不同的索引序列若拼出同一个编码串，把两侧拼接过程按已拼长度
逐段对齐，只会出现以下情况：

初始（第 1 轮）
    取不同码字 c_i、c_j 且 c_i 以 c_j 为真前缀：c_i = c_j + r，
    称非空串 r 为残串，拼出 c_i 的一侧（长侧）比另一侧多 r。

扩展（残串 r × 码字 c_k 的前缀匹配，只有两类）
    code_extends_residual: c_k = r + r'
        短侧补拼 c_k 后反超，新残串为 r'（r' 可为空串 ε）；
    residual_extends_code: r = c_k + r'
        长侧仍长，残串缩短为 r'（r' 非空）。

r' = ε 时两侧恰好对齐，两条路径拼出同一编码串，码不唯一可译。
残串集合逐轮穷尽而 ε 从未出现（出现空集或集合首次重复），则码
唯一可译。以上每一条转移都在响应中逐条列出，可直接复核。

最短歧义见证
    在带方向的状态 (r, L) 上做 Dijkstra，L∈{0,1} 表示当前第 L 侧
为长侧。设短侧已拼串为 Y、长度 d，长侧串 X = Y + r（长度 z=d+|r|）。
补码字 c_k：
    c_k = r + r'（r' 非空）：翻转，新短侧串 X，新长侧串 X + r'；
    r = c_k + r'：不翻转，新短侧串 Y + c_k，长侧串 X 不变；
    c_k = r：到达 ε，公共串即 X，长度 z。
所有边权严格为正且 z 单调不减，故按 (z, X) 宽度优先，第一个最优
ε 即「串长最短、字母表序最小」者；再比较规范化（取两组序列逐元素
字典序较小者在前）后的索引序列完成第三重裁决。同一中间状态保留
(z, X) 最小的一个标签即可：若另一标签 (z', X') 不小于它，沿同样的
后续转移始终不小于；若二者完全相同，则短侧串 X' 已有两种分节，
本身构成更短（长度 d < z）的歧义见证，不会影响最优解。

实现中码字统一用「字母表秩字节」表示：第 k 个有序字母表符号编码
为字节 k，于是字节序就是字母表序；输出时再逐字节译回符号。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import heapq
from typing import NamedTuple


# ---------------------------------------------------------------------------
# Trie：码字前缀树
# ---------------------------------------------------------------------------


class TrieNode:
    __slots__ = ("children", "terminal", "below")

    def __init__(self) -> None:
        self.children: dict[int, "TrieNode"] = {}
        # 码字互异 ⇒ 一个节点至多终止一个码字。
        self.terminal: int | None = None
        # 子树（含自身）中所有终止码字索引，建表后一次性计算。
        self.below: list[int] = []


def build_trie(codewords: list[bytes]) -> TrieNode:
    root = TrieNode()
    for idx, word in enumerate(codewords):
        node = root
        for ch in word:
            nxt = node.children.get(ch)
            if nxt is None:
                nxt = TrieNode()
                node.children[ch] = nxt
            node = nxt
        node.terminal = idx

    # 后序累积 below；n ≤ 400、码字 ≤ 256，总量 ≤ n·(maxlen+1)。
    stack: list[tuple[TrieNode, bool]] = [(root, False)]
    while stack:
        node, processed = stack.pop()
        if processed:
            below: list[int] = []
            if node.terminal is not None:
                below.append(node.terminal)
            for child in node.children.values():
                below.extend(child.below)
            node.below = below
        else:
            stack.append((node, True))
            for child in node.children.values():
                stack.append((child, False))
    return root


class Edge(NamedTuple):
    """残串 r 与某个码字的一条前缀匹配。

    kind == "code_extends_residual"：码字 = r + tail（tail 可为 ε）；
    kind == "residual_extends_code"：r = 码字 + tail（tail 必非空）。
    """

    code_index: int
    kind: str
    tail: bytes


def outgoing(root: TrieNode, codewords: list[bytes], residual: bytes) -> list[Edge]:
    """枚举 residual 与全部码字之间所有真实前缀匹配。

    沿 residual 在 trie 上走一遍：
      * 路径上（除最后一个位置外）的终止节点 = 以 residual 某真前缀
        为内容的码字，对应 residual_extends_code；
      * 走通后整棵子树的终止节点 = 以 residual 为前缀的码字，对应
        code_extends_residual（恰等时 tail 为 ε）。
    """
    edges: list[Edge] = []
    node = root
    rlen = len(residual)
    for pos in range(1, rlen + 1):
        nxt = node.children.get(residual[pos - 1])
        if nxt is None:
            return edges
        node = nxt
        # 此刻 node 对应 residual 长度为 pos 的前缀；它是码字且为真前缀
        # （pos < rlen）时，残串 = 该码字 + 剩余后缀。
        if pos < rlen and node.terminal is not None:
            k = node.terminal
            edges.append(Edge(k, "residual_extends_code", residual[pos:]))
    for k in node.below:
        edges.append(Edge(k, "code_extends_residual", codewords[k][rlen:]))
    return edges


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class Transition:
    kind: str
    code_index: int | None
    residual: bytes | None
    result: bytes  # ε 用 b"" 表示
    longer_index: int | None = None  # 仅初始码字对使用
    shorter_index: int | None = None
    is_new: bool = True


@dataclass
class Round:
    index: int
    residuals: list[bytes]          # 本轮完整残串集合 S_i（不含 ε）
    new_residuals: list[bytes]      # 其中首次出现者
    epsilon: bool                   # 本轮是否产生 ε
    transitions: list[Transition]
    expanded: list[bytes]           # 本轮首次展开（列出转移）的残串
    # 本轮参与展开、但其全部转移已在更早轮次列出的残串 -> 首次展开轮次。
    reuse: dict[bytes, int] = field(default_factory=dict)
    repeated_of: int | None = None  # 集合首次重复时所等同的历史轮次


@dataclass
class DerivationStep:
    """歧义见证推导的一步（侧号 0/1 与最终两组序列对应）。"""

    kind: str
    residual_before: bytes
    residual_after: bytes
    append_side: int
    codeword_index: int
    longer_codeword_index: int | None
    shorter_codeword_index: int | None


@dataclass
class Witness:
    encoded: bytes
    indices_a: list[int]
    indices_b: list[int]
    derivation: list[DerivationStep]


@dataclass
class GraphResult:
    unique: bool
    rounds: list[Round]
    witness: Witness | None
    termination_reason: str  # "epsilon" | "empty_set" | "repeated_set"
    termination_round: int
    distinct_residuals: int
    round_transition_count: int
    dijkstra_states: int
    dijkstra_edges: int


# ---------------------------------------------------------------------------
# 1) 逐轮残串集合
# ---------------------------------------------------------------------------


def residual_rounds(
    codewords: list[bytes], root: TrieNode
) -> tuple[list[Round], str, int, set[bytes], dict[bytes, list[Edge]], int]:
    """返回 (轮次, 终止原因, 终止轮, 累计残串, 各残串转移缓存, 转移数)。"""
    n = len(codewords)
    gen: dict[bytes, list[Edge]] = {}

    def edges_of(r: bytes) -> list[Edge]:
        got = gen.get(r)
        if got is None:
            got = outgoing(root, codewords, r)
            gen[r] = got
        return got

    rounds: list[Round] = []
    cumulative: set[bytes] = set()
    transition_count = 0

    # ---- 第 1 轮：码字两两真前缀对 ----
    s1: set[bytes] = set()
    init_transitions: list[Transition] = []
    for i in range(n):
        ci = codewords[i]
        for j in range(n):
            if i == j:
                continue
            cj = codewords[j]
            if ci.startswith(cj):
                tail = ci[len(cj) :]
                if tail == b"":
                    continue  # 互异非空码字不可能，防御性处理。
                transition_count += 1
                is_new = tail not in cumulative
                init_transitions.append(
                    Transition(
                        kind="initial_prefix_pair",
                        code_index=None,
                        residual=None,
                        result=tail,
                        longer_index=i,
                        shorter_index=j,
                        is_new=is_new,
                    )
                )
                s1.add(tail)
                cumulative.add(tail)

    rounds.append(
        Round(
            index=1,
            residuals=sorted(s1),
            new_residuals=sorted(s1),
            epsilon=False,
            transitions=init_transitions,
            expanded=[],
        )
    )
    if not s1:
        return rounds, "empty_set", 1, cumulative, gen, transition_count

    previous_sets: dict[tuple[bytes, ...], int] = {tuple(sorted(s1)): 1}
    expanded_already: set[bytes] = set()
    first_expand_round: dict[bytes, int] = {}
    prev = s1
    round_index = 1

    while True:
        round_index += 1
        to_expand = sorted(r for r in prev if r not in expanded_already)
        reused = sorted(r for r in prev if r in expanded_already)
        transitions: list[Transition] = []
        current: set[bytes] = set()
        epsilon = False

        # 集合由上一轮全部残串决定（旧残串的转移是确定性的，结果并入即可）。
        for r in sorted(prev):
            for edge in edges_of(r):
                transition_count += 1
                if edge.tail == b"":
                    epsilon = True
                    current.add(b"")  # 临时占位，最后剔除
                else:
                    current.add(edge.tail)
                if r in to_expand:
                    transitions.append(
                        Transition(
                            kind=edge.kind,
                            code_index=edge.code_index,
                            residual=r,
                            result=edge.tail,
                            is_new=edge.tail != b"" and edge.tail not in cumulative,
                        )
                    )
        for r in to_expand:
            first_expand_round[r] = round_index
        expanded_already.update(to_expand)

        current.discard(b"")
        new_now = sorted(r for r in current if r not in cumulative)
        cumulative.update(current)

        rnd = Round(
            index=round_index,
            residuals=sorted(current),
            new_residuals=new_now,
            epsilon=epsilon,
            transitions=transitions,
            expanded=to_expand,
            reuse={r: first_expand_round[r] for r in reused},
        )
        rounds.append(rnd)

        if epsilon:
            return (
                rounds,
                "epsilon",
                round_index,
                cumulative,
                gen,
                transition_count,
            )
        if not current:
            return (
                rounds,
                "empty_set",
                round_index,
                cumulative,
                gen,
                transition_count,
            )
        key = tuple(sorted(current))
        earlier = previous_sets.get(key)
        if earlier is not None:
            # 集合与历史某轮完全相同：后继确定，永不产生 ε。
            rnd.repeated_of = earlier
            return (
                rounds,
                "repeated_set",
                round_index,
                cumulative,
                gen,
                transition_count,
            )
        if not new_now:
            # 本轮残串均为历史旧残串的（真子集意义下的）重现：其闭包
            # 历史上已穷尽，不可能再产生 ε，码唯一可译。
            return (
                rounds,
                "closure_exhausted",
                round_index,
                cumulative,
                gen,
                transition_count,
            )
        previous_sets[key] = round_index
        prev = current


# ---------------------------------------------------------------------------
# 2) 最短歧义见证
#
# 分两步，二者都只使用残串/码字前缀关系，且相互独立、可各自复核：
#
# 步骤 A（Dijkstra 求最短串）：在带方向状态 (r, L) 上搜索。L∈{0,1}
#   表示当前第 L 侧为长侧，短侧已拼串 Y（长度 d），长侧串 X = Y + r
#   （长度 z = d+|r|）。初始 c_i = c_j + r：0 侧长、1 侧短，Y = c_j。
#   短侧补码字 c_k：
#     c_k = r + r'（r' 非空）：翻转，新短侧串 X；
#     r = c_k + r'：不翻转，新短侧串 Y + c_k；
#     c_k = r：到达 ε，公共串为 X。
#   堆键取 (z, X)，第一个弹出的 ε 即「长度最短、字母表序最小」的
#   歧义串 w（与沿哪条路径到达无关，故每状态只保留最优 (z, X) 标签）。
#
# 步骤 B（DAG 分解 + 规范化序列裁决）：在 w 的位置 DAG 上动态规划，
#   边 p→p+|c_k| 当且仅当 c_k = w[p:p+|c_k|]。求从 0 到 |w| 的字典序
#   最小（按索引序列逐元素比较）的两条不同完整路径 seq1 < seq2。
#   规范化对 (seq1, seq2) 即第三重裁决结果：任意两分解规范化后都不
#   会小于「最小分解」与「次小分解」。
#
# 最后由两组序列做双指针对齐，机械生成逐步残串推导，保证响应中的
# derivation 与两组索引序列严格一致。
# ---------------------------------------------------------------------------


class _State(NamedTuple):
    residual: bytes
    long_side: int  # 0/1：当前哪一侧为长侧


def _shortest_ambiguous_string(
    codewords: list[bytes],
    root: TrieNode,
    gen: dict[bytes, list[Edge]],
) -> tuple[bytes | None, int, int]:
    """步骤 A：返回 (最短歧义串, 弹出状态数, 枚举边数)。"""
    n = len(codewords)

    def edges_of(r: bytes) -> list[Edge]:
        got = gen.get(r)
        if got is None:
            got = outgoing(root, codewords, r)
            gen[r] = got
        return got

    # 每状态只保留当前最优标签 (z, X)：z 为长侧串长度、X 为长侧串文本
    # （X = Y + r，堆键即 (z, X)，与文档所述裁决顺序一致）。同一状态的
    # 两个标签若 (z,X) 较小，则沿任意相同后续转移拼出的最终串都不大于
    # 另一标签（长度由 z 决定；等长时 X 是最终串的等长前缀，字典序被
    # 保持），故较差标签可安全丢弃——包括「等长但 X 更大」的情形。
    best_label: dict[_State, tuple[int, bytes]] = {}
    heap: list[tuple[int, bytes, int, bytes, int, bytes]] = []
    serial = 0

    def consider(state: _State, d: int, y_text: bytes) -> None:
        nonlocal serial
        x_text = y_text + state.residual
        label = (d + len(state.residual), x_text)
        old_label = best_label.get(state)
        if old_label is not None and old_label <= label:
            return
        best_label[state] = label
        serial += 1
        heapq.heappush(
            heap,
            (
                label[0],
                label[1],
                serial,
                state.residual,
                state.long_side,
                y_text,
            ),
        )

    # 初始状态：c_i = c_j + r，0 侧放长码字 i，1 侧放短码字 j。
    for i in range(n):
        ci = codewords[i]
        for j in range(n):
            if i == j:
                continue
            cj = codewords[j]
            if ci.startswith(cj):
                tail = ci[len(cj):]
                if tail:
                    consider(_State(tail, 0), len(cj), cj)

    visited = 0
    edges_seen = 0
    while heap:
        z, x_text, _, residual, long_side, y_text = heapq.heappop(heap)
        state = _State(residual, long_side)
        if best_label.get(state) != (z, x_text):
            continue  # 过期堆项
        visited += 1
        r = state.residual
        d = z - len(r)
        short_side = 1 - long_side

        for edge in edges_of(r):
            edges_seen += 1
            k = edge.code_index
            if edge.kind == "code_extends_residual":
                if edge.tail == b"":
                    # c_k == r：对齐，公共串即长侧串 X = Y + r。
                    return x_text, visited, edges_seen
                # 翻转：新长侧 = 旧短侧；新短侧串 = X。
                consider(_State(edge.tail, short_side), z, x_text)
            else:
                # r = c_k + tail：身份不变，短侧补 c_k，长侧串 X 不变。
                ck = codewords[k]
                consider(_State(edge.tail, long_side), d + len(ck), y_text + ck)

    return None, visited, edges_seen


def _two_smallest_decompositions(
    codewords: list[bytes], w: bytes, root: TrieNode
) -> tuple[list[int], list[int]]:
    """步骤 B：w 的位置 DAG 上字典序最小、次小的两条不同完整分解。

    每个位置保留后缀的最小 / 次小分解，分别记名次 0 / 1。一条经过码字
    c_k（长度 L）的分解可表示为 (k, 后继名次)；两条候选首码字相同则
    L 相同、后继位置同为 p+L，名次直接可比，故字典序比较为 O(1)。
    匹配码字沿 trie 在 w 上行走，总复杂度 O(|w|·最长码字)。
    """
    wlen = len(w)
    # choice[p][r]：位置 p 第 r 名分解的 (首码字索引, 后继名次 r')；
    # 空后缀哨兵 END 表示分解结束。None 表示该名次不存在。
    END = (-1, -1)
    choice: list[list[tuple[int, int] | None]] = [[None, None] for _ in range(wlen + 1)]
    choice[wlen][0] = END

    for p in range(wlen - 1, -1, -1):
        cands: list[tuple[int, int]] = []  # (k, 后继名次)
        node = root
        q = p
        while q < wlen:
            nxt = node.children.get(w[q])
            if nxt is None:
                break
            node = nxt
            q += 1
            k = node.terminal
            if k is not None:
                # 码字 c_k 匹配 w[p:q]，后继位置为 q。
                if choice[q][0] is not None:
                    cands.append((k, 0))
                if choice[q][1] is not None:
                    cands.append((k, 1))
        cands.sort()
        first = cands[0] if cands else None
        second = None
        for cand in cands[1:]:
            if cand != first:
                second = cand
                break
        choice[p][0] = first
        choice[p][1] = second

    def rebuild(rank: int) -> list[int]:
        seq: list[int] = []
        p = 0
        r = rank
        while p < wlen:
            sel = choice[p][r]
            if sel is None:
                raise RuntimeError("internal error: decomposition path missing")
            k, r = sel
            seq.append(k)
            p += len(codewords[k])
        return seq

    seq1 = choice[0][0]
    seq2 = choice[0][1]
    if seq1 is None or seq2 is None:
        raise RuntimeError("internal error: ambiguous string lacks two decompositions")
    return rebuild(0), rebuild(1)


def _build_derivation(
    seq_a: list[int], seq_b: list[int], codewords: list[bytes]
) -> list[DerivationStep]:
    """由两组拼出同一串 w 的索引序列，双指针对齐生成残串转移。

    侧 0 取 seq_a、侧 1 取 seq_b。两侧各放首个码字，残串为二者之差；
    之后每一步都在当前较短侧追加下一个码字并按前缀关系更新残串，
    直到两侧同时拼完（残串为 ε）。append_side/codeword_index 即该步
    追加码字的归属侧与索引，与 indices_a / indices_b 一一对应。
    """
    steps: list[DerivationStep] = []
    used = [1, 1]  # 每侧已消费码字数（首码字即将放入）
    wa0, wb0 = codewords[seq_a[0]], codewords[seq_b[0]]
    lengths = [len(wa0), len(wb0)]

    if lengths[0] == lengths[1]:
        raise RuntimeError("internal error: witness prefixes align too early")
    if lengths[0] > lengths[1]:
        long_side = 0
        residual = wa0[len(wb0):]
        short_side = 1
        short_code = seq_b[0]
        long_code = seq_a[0]
    else:
        long_side = 1
        residual = wb0[len(wa0):]
        short_side = 0
        short_code = seq_a[0]
        long_code = seq_b[0]

    steps.append(
        DerivationStep(
            kind="initial_prefix_pair",
            residual_before=b"",
            residual_after=residual,
            append_side=short_side,
            codeword_index=short_code,
            longer_codeword_index=long_code,
            shorter_codeword_index=short_code,
        )
    )

    seqs = (seq_a, seq_b)
    while residual != b"":
        short_side = 1 - long_side
        seq = seqs[short_side]
        if used[short_side] >= len(seq):
            raise RuntimeError("internal error: witness side exhausted early")
        k = seq[used[short_side]]
        used[short_side] += 1
        ck = codewords[k]
        before = residual
        if ck == residual:
            after = b""
            kind = "code_extends_residual"
        elif ck.startswith(residual):
            after = ck[len(residual):]
            kind = "code_extends_residual"
            long_side = short_side  # 翻转
        elif residual.startswith(ck):
            after = residual[len(ck):]
            kind = "residual_extends_code"
        else:
            raise RuntimeError("internal error: alignment broke prefix relation")
        lengths[short_side] += len(ck)
        residual = after
        steps.append(
            DerivationStep(
                kind=kind,
                residual_before=before,
                residual_after=after,
                append_side=short_side,
                codeword_index=k,
                longer_codeword_index=None,
                shorter_codeword_index=None,
            )
        )

    # 自检：两侧必须恰好同时消费完整组序列且总长相等（均为 |w|）。
    if used != [len(seq_a), len(seq_b)] or lengths[0] != lengths[1]:
        raise RuntimeError("internal error: derivation does not reproduce sequences")
    return steps


def shortest_witness(
    codewords: list[bytes],
    root: TrieNode,
    gen: dict[bytes, list[Edge]],
) -> tuple[Witness | None, int, int]:
    """求三重裁决（串长, 字母表序, 规范化序列）最优的歧义见证。"""
    w, visited, edges_seen = _shortest_ambiguous_string(codewords, root, gen)
    if w is None:
        return None, visited, edges_seen

    seq_a, seq_b = _two_smallest_decompositions(codewords, w, root)
    encoded_a = b"".join(codewords[i] for i in seq_a)
    encoded_b = b"".join(codewords[i] for i in seq_b)
    if encoded_a != w or encoded_b != w or seq_a == seq_b:
        raise RuntimeError("internal error: decompositions invalid")

    derivation = _build_derivation(seq_a, seq_b, codewords)
    return (
        Witness(w, seq_a, seq_b, derivation),
        visited,
        edges_seen,
    )


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def analyze(codewords: list[bytes]) -> GraphResult:
    """构造残串状态图，返回逐轮集合与（歧义时的）最短见证。"""
    root = build_trie(codewords)
    rounds, reason, term_round, cumulative, gen, tr_count = residual_rounds(
        codewords, root
    )
    if reason != "epsilon":
        return GraphResult(
            unique=True,
            rounds=rounds,
            witness=None,
            termination_reason=reason,
            termination_round=term_round,
            distinct_residuals=len(cumulative),
            round_transition_count=tr_count,
            dijkstra_states=0,
            dijkstra_edges=0,
        )

    witness, visited, edges_seen = shortest_witness(codewords, root, gen)
    if witness is None:
        raise RuntimeError("internal error: epsilon reached in rounds but not search")
    return GraphResult(
        unique=False,
        rounds=rounds,
        witness=witness,
        termination_reason="epsilon",
        termination_round=term_round,
        distinct_residuals=len(cumulative),
        round_transition_count=tr_count,
        dijkstra_states=visited,
        dijkstra_edges=edges_seen,
    )
