"""代码级算法测试：残串状态图、三重裁决与逐轮残串证明。

覆盖：
  * 标题缺陷用例：等长候选必须按完整编码串的字母表序裁决；
  * 多条等长搜索路径汇入同一残串状态；
  * 自定义字母表顺序与 ASCII 顺序给出不同裁决；
  * 更短歧义串始终优先；
  * 第三级裁决（输入码字顺序决定索引序列）；
  * 唯一可译码的逐轮残串证明（empty_set / repeated_set /
    closure_exhausted 三种终止）；
  * 与独立暴力枚举器在大量乱序字母表随机码上对拍。
"""

from __future__ import annotations

import itertools
import random

import pytest

from app.codec import Codec
from app.sardinas import (
    analyze,
    build_trie,
    outgoing,
    residual_rounds,
)


# ---------------------------------------------------------------------------
# 复核工具
# ---------------------------------------------------------------------------


def encode_words(alphabet, codewords):
    codec = Codec(alphabet)
    return codec, [codec.encode(w) for w in codewords]


def replay_derivation(witness, encoded_words):
    """机械重放 derivation：按 append_side 收集码字并核对每条残串等式。

    返回 (per_side_indices, final_residual)。
    """
    placed: list[list[int]] = [[], []]
    residual = None
    for step in witness.derivation:
        if step.kind == "initial_prefix_pair":
            assert step.longer_codeword_index is not None
            assert step.shorter_codeword_index is not None
            long_idx = step.longer_codeword_index
            short_idx = step.shorter_codeword_index
            long_word = encoded_words[long_idx]
            short_word = encoded_words[short_idx]
            assert long_word.startswith(short_word)
            expected = long_word[len(short_word):]
            assert step.residual_after == expected
            long_side = step.append_side ^ 1
            placed[long_side].append(long_idx)
            placed[step.append_side].append(short_idx)
            residual = expected
            continue
        k = step.codeword_index
        assert k is not None
        side = step.append_side
        ck = encoded_words[k]
        assert step.residual_before == residual
        if step.kind == "code_extends_residual":
            assert ck.startswith(residual)
            assert step.residual_after == ck[len(residual):]
        elif step.kind == "residual_extends_code":
            assert residual.startswith(ck)
            assert step.residual_after == residual[len(ck):]
        else:  # pragma: no cover - 防御性
            raise AssertionError(f"未知转移类型 {step.kind}")
        placed[side].append(k)
        residual = step.residual_after
    return placed, residual


def assert_witness_consistent(alphabet, codewords, result):
    codec, enc = encode_words(alphabet, codewords)
    witness = result.witness
    assert witness is not None
    w = witness.encoded

    # 两组索引都能从原始码字重新拼出该串，且序列互异。
    joined_a = b"".join(enc[i] for i in witness.indices_a)
    joined_b = b"".join(enc[i] for i in witness.indices_b)
    assert joined_a == w
    assert joined_b == w
    assert witness.indices_a != witness.indices_b

    # 逐步残串推导与两组索引严格一致，并以空残串结束。
    placed, final_residual = replay_derivation(witness, enc)
    assert placed[0] == witness.indices_a
    assert placed[1] == witness.indices_b
    assert final_residual == b""
    assert witness.derivation[-1].residual_after == b""
    return codec, w


def assert_rounds_are_a_proof(enc, result):
    """逐轮残串集合必须与转移逐条吻合（独立重算一遍）。"""
    n = len(enc)
    root = build_trie(enc)

    # 独立重算 S1。
    s1: set[bytes] = set()
    for i in range(n):
        for j in range(n):
            if i != j and enc[i].startswith(enc[j]):
                tail = enc[i][len(enc[j]):]
                if tail:
                    s1.add(tail)
    assert set(result.rounds[0].residuals) == s1

    # 之后每一轮 S_i = 对 S_{i-1} 每个残串做全部前缀匹配的非空结果。
    prev = s1
    for rnd in result.rounds[1:]:
        current: set[bytes] = set()
        epsilon = False
        for r in prev:
            for edge in outgoing(root, enc, r):
                if edge.tail == b"":
                    epsilon = True
                else:
                    current.add(edge.tail)
        assert set(rnd.residuals) == current
        assert rnd.epsilon == epsilon
        prev = current


def assert_rounds_consistent_with_engine(enc, result):
    """直接调用 residual_rounds 复核轮次内容。"""
    root = build_trie(enc)
    rounds, reason, term_round, *_ = residual_rounds(enc, root)
    assert reason == result.termination_reason
    assert term_round == result.termination_round
    assert [r.residuals for r in rounds] == [r.residuals for r in result.rounds]


# ---------------------------------------------------------------------------
# 标题缺陷：等长候选按完整编码串的字母表序裁决
# ---------------------------------------------------------------------------


HEADLINE_ALPHABET = ["b", "a"]  # 数组顺序规定 b < a
HEADLINE_CODEWORDS = ["bbba", "b", "abba", "ab"]


def test_headline_case_witness_is_bbbab():
    codec, enc = encode_words(HEADLINE_ALPHABET, HEADLINE_CODEWORDS)
    result = analyze(enc)

    assert result.unique is False
    assert result.termination_reason == "epsilon"
    witness = result.witness
    assert codec.decode(witness.encoded) == "bbbab"
    assert len(witness.encoded) == 5
    # 两组规范索引：[0,1] = bbba+b；[1,1,1,3] = b+b+b+ab。
    assert witness.indices_a == [0, 1]
    assert witness.indices_b == [1, 1, 1, 3]

    codec2, w = assert_witness_consistent(
        HEADLINE_ALPHABET, HEADLINE_CODEWORDS, result
    )
    assert codec2.decode(w) == "bbbab"
    assert_rounds_consistent_with_engine(enc, result)


def test_headline_equal_length_alternative_abbab_is_lexicographically_greater():
    """同长度旧见证 abbab 在 b<a 秩序下必须排在 bbbab 之后。"""
    codec = Codec(HEADLINE_ALPHABET)
    abbab = codec.encode("abbab")
    bbbab = codec.encode("bbbab")
    assert len(abbab) == len(bbbab) == 5
    # 秩字节序即字母表序：b=0 < a=1，故 bbbab < abbab。
    assert bbbab < abbab
    assert codec.decode(bbbab) == "bbbab"


def test_equal_length_paths_merge_into_same_residual_state():
    """长度同为 4 的 abba 路径与 bbba 路径汇入同一带方向残串状态。

    修复前判重只看长度：先到的 X=abba（字母表序较大）占据状态
    (residual=ba, long_side=0)，X=bbba（字母表序较小）被丢弃，导致
    最终错过 bbbab。修复后状态上必须保留 (z,X) 更小的 bbba 标签。
    """
    import heapq

    from app.sardinas import _State

    codec, enc = encode_words(HEADLINE_ALPHABET, HEADLINE_CODEWORDS)
    root = build_trie(enc)
    gen: dict = {}

    def edges_of(r):
        got = gen.get(r)
        if got is None:
            got = outgoing(root, enc, r)
            gen[r] = got
        return got

    arrivals: dict[object, list[tuple[int, bytes]]] = {}
    best: dict[object, tuple[int, bytes]] = {}
    heap: list = []
    serial = 0

    def consider(state, d, y_text):
        nonlocal serial
        r = state.residual
        z = d + len(r)
        x_text = y_text + r
        arrivals.setdefault(state, []).append((z, x_text))
        label = (z, x_text)
        old = best.get(state)
        if old is not None and old <= label:
            return
        best[state] = label
        serial += 1
        heapq.heappush(heap, (z, x_text, state.long_side, serial, y_text))

    for i in range(len(enc)):
        for j in range(len(enc)):
            if i != j and enc[i].startswith(enc[j]):
                tail = enc[i][len(enc[j]):]
                if tail:
                    consider(_State(tail, 0), len(enc[j]), enc[j])

    answer = None
    while heap:
        z, x_text, long_side, _, y_text = heapq.heappop(heap)
        r = x_text[len(y_text):]
        state = _State(r, long_side)
        if best.get(state) != (z, x_text):
            continue
        d = z - len(r)
        for edge in edges_of(r):
            if edge.kind == "code_extends_residual":
                if edge.tail == b"":
                    answer = x_text
                    break
                consider(_State(edge.tail, 1 - long_side), z, x_text)
            else:
                ck = enc[edge.code_index]
                consider(_State(edge.tail, long_side), d + len(ck), y_text + ck)
        if answer is not None:
            break

    assert codec.decode(answer) == "bbbab"
    merge_state = _State(codec.encode("ba"), 0)
    labels = arrivals[merge_state]
    decoded = sorted((z, codec.decode(x)) for z, x in labels)
    assert (4, "abba") in decoded
    assert (4, "bbba") in decoded
    # 胜出的必须是字母表序更小的 bbba。
    assert best[merge_state] == (4, codec.encode("bbba"))


# ---------------------------------------------------------------------------
# 自定义字母表序与 ASCII 序不同
# ---------------------------------------------------------------------------


CUSTOM_ALPHABET = ["c", "a", "b"]  # c<a<b，ASCII 序则是 a<b<c
CUSTOM_CODEWORDS = ["baa", "aba", "a", "cb", "c"]


def test_custom_alphabet_order_picks_cbaa_not_abaa():
    codec = Codec(CUSTOM_ALPHABET)
    # 最短歧义长度为 4；在秩字节序（c<a<b）下 c 开头的 cbaa 最小，
    # 若误用 ASCII 序（a<b<c）则会选 abaa。
    cbaa = codec.encode("cbaa")
    abaa = codec.encode("abaa")
    assert cbaa < abaa
    # 而在真实 ASCII 字符串序下二者次序相反，证明裁决确实用了给定秩序。
    assert "abaa" < "cbaa"

    _, enc = encode_words(CUSTOM_ALPHABET, CUSTOM_CODEWORDS)
    result = analyze(enc)
    assert result.unique is False
    witness = result.witness
    assert codec.decode(witness.encoded) == "cbaa"
    assert len(witness.encoded) == 4
    assert_witness_consistent(CUSTOM_ALPHABET, CUSTOM_CODEWORDS, result)


def test_same_input_different_alphabet_order_changes_witness():
    """同一组码字在不同字母表数组顺序下，等长裁决随秩序改变。"""
    words = ["baa", "aba", "a", "cb", "c"]

    result_custom = analyze(encode_words(["c", "a", "b"], words)[1])
    result_ascii = analyze(encode_words(["a", "b", "c"], words)[1])
    assert not result_custom.unique and not result_ascii.unique
    wc = Codec(["c", "a", "b"]).decode(result_custom.witness.encoded)
    wa = Codec(["a", "b", "c"]).decode(result_ascii.witness.encoded)
    assert wc == "cbaa"
    assert wa == "abaa"
    assert wc != wa


# ---------------------------------------------------------------------------
# 更短歧义串始终优先
# ---------------------------------------------------------------------------


def test_shorter_ambiguous_string_always_wins():
    # 01 = 0·1（长度 2）是最短歧义；同码中还存在更长碰撞，不得胜出。
    alphabet = ["0", "1"]
    codewords = ["0", "01", "1", "010"]
    codec, enc = encode_words(alphabet, codewords)
    result = analyze(enc)
    assert result.unique is False
    assert codec.decode(result.witness.encoded) == "01"
    assert len(result.witness.encoded) == 2
    assert result.witness.indices_a == [0, 2]
    assert result.witness.indices_b == [1]
    assert_witness_consistent(alphabet, codewords, result)


def test_length_beats_lexicographic_order():
    """字母表序更大但长度更短的串必须胜出（第一级裁决压倒第二级）。"""
    alphabet = ["0", "1"]
    # 最短歧义为长度 2 的 "10" = 1·0（1 开头，秩字节序更大）；
    # 同码还存在以 0 开头（字母表序更小）但长度 3 的碰撞 010 = 0·10。
    codewords = ["1", "10", "0", "010"]
    codec, enc = encode_words(alphabet, codewords)
    result = analyze(enc)
    assert result.unique is False
    witness = result.witness
    assert codec.decode(witness.encoded) == "10"
    assert len(witness.encoded) == 2
    # "10" 的秩字节序确实大于 "010" 的首字节，但长度更短仍应胜出。
    assert codec.encode("10")[0] > codec.encode("010")[0]
    assert_witness_consistent(alphabet, codewords, result)


# ---------------------------------------------------------------------------
# 第三级裁决：输入码字顺序决定索引序列
# ---------------------------------------------------------------------------


def test_third_level_tiebreak_follows_input_codeword_order():
    alphabet = ["0", "1"]
    # 010 有多种分解；码字表顺序改变后，规范化最小序列对随索引改变。
    result_a = analyze(encode_words(alphabet, ["0", "01", "10", "010"])[1])
    result_b = analyze(encode_words(alphabet, ["01", "0", "10", "010"])[1])
    assert not result_a.unique and not result_b.unique
    wa = result_a.witness
    wb = result_b.witness
    assert Codec(alphabet).decode(wa.encoded) == "010"
    assert Codec(alphabet).decode(wb.encoded) == "010"
    # 第一种顺序：0·10=[0,2] 对 01·0=[1,0]。
    assert wa.indices_a == [0, 2]
    assert wa.indices_b == [1, 0]
    # 重排后 010 有三种分解：[0,1]=01·0、[1,2]=0·10、[3]=010 整体；
    # 规范化最小序列对为 ([0,1], [1,2])（逐元素比较 [1,2] < [3]）。
    assert wb.indices_a == [0, 1]
    assert wb.indices_b == [1, 2]
    # 两组结果各自自洽。
    assert_witness_consistent(alphabet, ["0", "01", "10", "010"], result_a)
    assert_witness_consistent(alphabet, ["01", "0", "10", "010"], result_b)


# ---------------------------------------------------------------------------
# 唯一可译码：逐轮残串证明与三种终止原因
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "codewords,reason",
    [
        (["0", "10", "110", "111"], "empty_set"),
        (["0", "01", "11"], "repeated_set"),
        (["0", "11", "001", "101"], "closure_exhausted"),
        (["00", "01", "10", "11"], "empty_set"),
    ],
)
def test_unique_codes_round_proofs(codewords, reason):
    alphabet = ["0", "1"]
    codec, enc = encode_words(alphabet, codewords)
    result = analyze(enc)
    assert result.unique is True
    assert result.witness is None
    assert result.termination_reason == reason
    assert result.rounds, "唯一可译码也必须返回逐轮残串证明"
    # 最后一轮绝不产生 ε。
    assert all(not rnd.epsilon for rnd in result.rounds)
    assert_rounds_consistent_with_engine(enc, result)
    assert_rounds_are_a_proof(enc, result)
    if reason == "empty_set":
        assert result.rounds[-1].residuals == []
    if reason == "repeated_set":
        assert result.rounds[-1].repeated_of is not None
    if reason == "closure_exhausted":
        last = result.rounds[-1]
        assert last.new_residuals == []
        assert last.residuals


def test_unique_rounds_transition_equations_hold():
    """逐轮列出的每条转移等式都必须真实成立。"""
    alphabet = ["0", "1"]
    codewords = ["0", "11", "001", "101"]
    codec, enc = encode_words(alphabet, codewords)
    result = analyze(enc)
    assert result.unique
    for rnd in result.rounds:
        for tr in rnd.transitions:
            if tr.kind == "initial_prefix_pair":
                long_word = enc[tr.longer_index]
                short_word = enc[tr.shorter_index]
                assert long_word == short_word + tr.result
            elif tr.kind == "code_extends_residual":
                ck = enc[tr.code_index]
                assert ck == tr.residual + tr.result
            elif tr.kind == "residual_extends_code":
                ck = enc[tr.code_index]
                assert tr.residual == ck + tr.result
            else:  # pragma: no cover
                raise AssertionError(tr.kind)


# ---------------------------------------------------------------------------
# 独立暴力枚举对拍
# ---------------------------------------------------------------------------


def brute_force_optimal(alphabet, codewords, max_depth=8):
    """枚举短索引序列，按三重规则返回最优 (长度, 秩字节串, seq1, seq2)。"""
    codec, enc = encode_words(alphabet, codewords)
    n = len(enc)
    table: dict[bytes, list[tuple[int, ...]]] = {}
    for depth in range(1, max_depth + 1):
        for seq in itertools.product(range(n), repeat=depth):
            table.setdefault(b"".join(enc[i] for i in seq), []).append(seq)
    best = None
    for s, seqs in table.items():
        distinct: list[tuple[int, ...]] = []
        for seq in seqs:
            if seq not in distinct:
                distinct.append(seq)
        if len(distinct) < 2:
            continue
        pair_key = None
        for x in range(len(distinct)):
            for y in range(x + 1, len(distinct)):
                a, b = distinct[x], distinct[y]
                na, nb = (a, b) if a <= b else (b, a)
                cand = (na, nb)
                if pair_key is None or cand < pair_key:
                    pair_key = cand
        key = (len(s), s, pair_key[0], pair_key[1])
        if best is None or key < best:
            best = key
    return best


@pytest.mark.parametrize("seed", range(40))
def test_brute_force_cross_check_shuffled_alphabet(seed):
    rng = random.Random(1000 + seed)
    m = rng.randint(2, 4)
    alphabet = list("abcd")[:m]
    rng.shuffle(alphabet)  # 秩序刻意与 ASCII 不同
    n = rng.randint(2, 5)
    codewords: list[str] = []
    while len(codewords) < n:
        length = rng.randint(1, 3)
        word = "".join(rng.choice(alphabet) for _ in range(length))
        if word not in codewords:
            codewords.append(word)

    depth = {2: 11, 3: 8, 4: 7, 5: 6}[n]
    brute = brute_force_optimal(alphabet, codewords, max_depth=depth)
    result = analyze(encode_words(alphabet, codewords)[1])

    if result.unique:
        assert brute is None, f"引擎判唯一但暴力发现歧义：{alphabet} {codewords}"
        return

    codec, _ = encode_words(alphabet, codewords)
    witness = result.witness
    a, b = tuple(witness.indices_a), tuple(witness.indices_b)
    na, nb = (a, b) if a <= b else (b, a)
    engine_key = (len(witness.encoded), witness.encoded, na, nb)
    assert brute is not None
    assert engine_key == brute, (
        f"裁决不一致 {alphabet} {codewords}: engine={engine_key} brute={brute}"
    )
    assert_witness_consistent(alphabet, codewords, result)
