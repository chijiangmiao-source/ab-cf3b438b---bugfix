"""API/HTTP 冒烟测试：对真实 uvicorn 进程发请求。

覆盖：
  * GET /health；
  * POST /verify 标题缺陷用例（HTTP 200、unique=false、bbbab/长度 5、
    两组规范索引、joined_a/joined_b、逐步残串推导到空残串）；
  * 等长字母表序裁决、自定义字母表序、更短歧义串优先、唯一可译；
  * 结构化 422（错误码与 loc 位置）与坏 JSON；
  * 歧义响应中的逐轮残串证明字段完整。
"""

from __future__ import annotations


HEADLINE_BODY = {
    "alphabet": ["b", "a"],
    "codewords": ["bbba", "b", "abba", "ab"],
}


def _join(codewords, indices):
    return "".join(codewords[i] for i in indices)


def _replay_derivation(codewords, ambiguity):
    """用 derivation 的 append_side 与 codeword_index 重组两侧序列并跟踪残串。"""
    placed = [[], []]
    residual = ""
    for step in ambiguity["derivation"]:
        if step["kind"] == "initial_prefix_pair":
            li = step["longer_codeword_index"]
            si = step["shorter_codeword_index"]
            long_word = codewords[li]
            short_word = codewords[si]
            assert long_word.startswith(short_word)
            residual = long_word[len(short_word):]
            long_side = step["append_side"] ^ 1
            placed[long_side].append(li)
            placed[step["append_side"]].append(si)
            assert step["residual_after"] == residual
            continue
        side = step["append_side"]
        k = step["codeword_index"]
        ck = codewords[k]
        assert step["residual_before"] == residual
        if step["kind"] == "code_extends_residual":
            assert ck.startswith(residual)
            residual = ck[len(residual):]
        else:
            assert step["kind"] == "residual_extends_code"
            assert residual.startswith(ck)
            residual = residual[len(ck):]
        assert step["residual_after"] == residual
        placed[side].append(k)
    return placed, residual


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


def test_health_ok(http_call):
    status, body = http_call("GET", "/health")
    assert status == 200
    assert body["status"] == "ok"
    assert body["service"] == "variable-code-verifier"
    assert "uptime_seconds" in body


# ---------------------------------------------------------------------------
# 标题缺陷用例
# ---------------------------------------------------------------------------


def test_headline_request_full_contract(http_call):
    status, body = http_call("POST", "/verify", HEADLINE_BODY)
    assert status == 200, body
    assert body["ok"] is True
    assert body["unique"] is False
    assert body["termination"]["reason"] == "epsilon"

    amb = body["ambiguity"]
    assert amb["encoded_string"] == "bbbab"
    assert amb["length"] == 5
    assert amb["indices_a"] == [0, 1]
    assert amb["indices_b"] == [1, 1, 1, 3]
    assert amb["sequences_differ"] is True

    codewords = HEADLINE_BODY["codewords"]
    assert amb["concatenation_a"] == ["bbba", "b"]
    assert amb["concatenation_b"] == ["b", "b", "b", "ab"]
    # 每组索引都能从原始码字重新拼出该串。
    assert amb["joined_a"] == _join(codewords, amb["indices_a"]) == "bbbab"
    assert amb["joined_b"] == _join(codewords, amb["indices_b"]) == "bbbab"
    assert amb["joined_a"] == amb["joined_b"] == amb["encoded_string"]

    # 逐步残串推导与两组索引一致，并到达空残串。
    placed, residual = _replay_derivation(codewords, amb)
    assert placed[0] == amb["indices_a"]
    assert placed[1] == amb["indices_b"]
    assert residual == ""
    assert amb["derivation"][-1]["residual_after"] == ""
    assert amb["derivation"][-1]["epsilon_after"] is True


def test_headline_rejects_lexicographically_greater_equal_length_string(http_call):
    """同长度的 abbab 不得再被选中。"""
    status, body = http_call("POST", "/verify", HEADLINE_BODY)
    assert status == 200
    assert body["ambiguity"]["encoded_string"] != "abbab"
    assert body["ambiguity"]["length"] == 5


# ---------------------------------------------------------------------------
# 自定义字母表序（与 ASCII 序不同）
# ---------------------------------------------------------------------------


def test_custom_alphabet_order_http(http_call):
    body_in = {
        "alphabet": ["c", "a", "b"],
        "codewords": ["baa", "aba", "a", "cb", "c"],
    }
    status, body = http_call("POST", "/verify", body_in)
    assert status == 200
    assert body["unique"] is False
    amb = body["ambiguity"]
    # c<a<b 秩序下最短等长串以 c 开头，ASCII 序会错误地选 abaa。
    assert amb["encoded_string"] == "cbaa"
    assert amb["length"] == 4
    words = body_in["codewords"]
    assert amb["joined_a"] == _join(words, amb["indices_a"]) == "cbaa"
    assert amb["joined_b"] == _join(words, amb["indices_b"]) == "cbaa"
    placed, residual = _replay_derivation(words, amb)
    assert placed == [amb["indices_a"], amb["indices_b"]]
    assert residual == ""


# ---------------------------------------------------------------------------
# 更短歧义串优先
# ---------------------------------------------------------------------------


def test_shorter_ambiguity_wins_http(http_call):
    body_in = {
        "alphabet": ["0", "1"],
        "codewords": ["0", "01", "1", "010"],
    }
    status, body = http_call("POST", "/verify", body_in)
    assert status == 200
    assert body["unique"] is False
    amb = body["ambiguity"]
    assert amb["encoded_string"] == "01"
    assert amb["length"] == 2
    assert amb["joined_a"] == amb["joined_b"] == "01"


# ---------------------------------------------------------------------------
# 唯一可译码：逐轮残串证明
# ---------------------------------------------------------------------------


def test_unique_code_round_proof_http(http_call):
    body_in = {
        "alphabet": ["0", "1"],
        "codewords": ["0", "01", "11"],  # repeated_set 终止
    }
    status, body = http_call("POST", "/verify", body_in)
    assert status == 200
    assert body["unique"] is True
    assert body["ambiguity"] is None
    assert body["termination"]["reason"] == "repeated_set"
    rounds = body["rounds"]
    assert rounds and isinstance(rounds, list)
    assert all(rnd["epsilon_produced"] is False for rnd in rounds)
    last = rounds[-1]
    assert last["repeated_of_round"] is not None
    # 轮次中每条转移都带等式与拼接复核字段。
    kinds = set()
    for rnd in rounds:
        for tr in rnd["transitions"]:
            kinds.add(tr["kind"])
            assert "equation" in tr
            assert "concatenation_check" in tr
    assert "initial_prefix_pair" in kinds


def test_unique_prefix_code_http(http_call):
    body_in = {
        "alphabet": ["0", "1"],
        "codewords": ["0", "10", "110", "111"],
    }
    status, body = http_call("POST", "/verify", body_in)
    assert status == 200
    assert body["unique"] is True
    assert body["termination"]["reason"] == "empty_set"
    assert body["rounds"][-1]["residuals"] == []


# ---------------------------------------------------------------------------
# 结构化 422
# ---------------------------------------------------------------------------


def test_422_empty_codeword_has_location(http_call):
    status, body = http_call(
        "POST", "/verify", {"alphabet": ["0", "1"], "codewords": ["0", ""]}
    )
    assert status == 422
    assert body["ok"] is False
    assert body["error"]["type"] == "validation_error"
    issues = body["error"]["issues"]
    assert issues
    codes = {i["code"] for i in issues}
    assert "empty_codeword" in codes
    issue = next(i for i in issues if i["code"] == "empty_codeword")
    assert issue["loc"][:2] == ["body", "codewords"]
    assert issue["loc"][2] == 1


def test_422_collects_all_issues_with_char_position(http_call):
    status, body = http_call(
        "POST",
        "/verify",
        {"alphabet": ["0", "1"], "codewords": ["0", "1x", "0"]},
    )
    assert status == 422
    issues = body["error"]["issues"]
    codes = {i["code"] for i in issues}
    assert "symbol_not_in_alphabet" in codes
    assert "duplicate_codeword" in codes
    bad = next(i for i in issues if i["code"] == "symbol_not_in_alphabet")
    assert bad["loc"] == ["body", "codewords", 1, "char", 1]


def test_422_missing_field_and_bad_json(http_call):
    status, body = http_call("POST", "/verify", {"alphabet": ["0", "1"]})
    assert status == 422
    assert any(
        i["code"] == "missing_field" and i["loc"] == ["body", "codewords"]
        for i in body["error"]["issues"]
    )

    status, body = http_call("POST", "/verify", raw=b"{not valid json")
    assert status == 422
    issue = body["error"]["issues"][0]
    assert issue["code"] == "invalid_json"
    assert issue["loc"] == ["body"]


def test_422_non_object_body(http_call):
    status, body = http_call("POST", "/verify", raw=b"[1,2,3]")
    assert status == 422
    assert body["error"]["issues"][0]["code"] == "invalid_body"


def test_empty_body_is_422(http_call):
    status, body = http_call("POST", "/verify", raw=b"")
    assert status == 422
    assert body["error"]["issues"][0]["code"] == "empty_body"
