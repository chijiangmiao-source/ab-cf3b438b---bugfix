"""FastAPI 应用：健康检查与 /verify 残串状态图验收接口。

纯后端、无数据库、无前端、无任何在线调用。请求体手工解析与校验，
非法输入统一返回带位置的结构化 422。
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .codec import Codec
from .sardinas import analyze
from .validation import validate_payload

app = FastAPI(
    title="可变长码字唯一可译性验收服务",
    version="1.0.0",
    description="自行构造残串状态图判定变长码唯一可译性并给出最短歧义见证。",
)

STARTED_AT = time.time()


def _error_response(issues: list[dict[str, Any]], status: int = 422) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "ok": False,
            "error": {
                "type": "validation_error" if status == 422 else "bad_request",
                "issues": issues,
            },
        },
    )


@app.get("/health", include_in_schema=True)
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "variable-code-verifier",
        "uptime_seconds": round(time.time() - STARTED_AT, 3),
    }


def _transition_dict(rec: Any, codec: Codec) -> dict[str, Any]:
    kind = rec.kind
    base: dict[str, Any] = {
        "kind": kind,
        "result": codec.decode(rec.result),
        "is_new": rec.is_new,
    }
    if kind == "initial_prefix_pair":
        i, j = rec.longer_index, rec.shorter_index
        r = codec.decode(rec.result)
        base.update(
            {
                "longer_codeword_index": i,
                "shorter_codeword_index": j,
                "equation": f"c_{i} = c_{j} + residual",
                "concatenation_check": {
                    "left": f"c_{i}",
                    "right": [f"c_{j}", f"residual={r!s}"],
                },
            }
        )
    else:
        r = codec.decode(rec.residual)
        k = rec.code_index
        tail = codec.decode(rec.result)
        base.update(
            {
                "residual": r,
                "codeword_index": k,
                "result_is_epsilon": rec.result == b"",
            }
        )
        if kind == "code_extends_residual":
            base["equation"] = f"c_{k} = residual + new_residual"
            base["concatenation_check"] = {
                "left": [f"c_{k}"],
                "right": [f"residual={r}", f"new_residual={tail}"],
            }
        else:
            base["equation"] = f"residual = c_{k} + new_residual"
            base["concatenation_check"] = {
                "left": [f"residual={r}"],
                "right": [f"c_{k}", f"new_residual={tail}"],
            }
    return base


def _derivation_step_dict(step: Any, codec: Codec) -> dict[str, Any]:
    out: dict[str, Any] = {
        "kind": step.kind,
        "append_side": step.append_side,
        "codeword_index": step.codeword_index,
        "residual_before": codec.decode(step.residual_before),
        "residual_after": codec.decode(step.residual_after),
        "epsilon_after": step.residual_after == b"",
    }
    if step.kind == "initial_prefix_pair":
        out["longer_codeword_index"] = step.longer_codeword_index
        out["shorter_codeword_index"] = step.shorter_codeword_index
    return out


def _build_response(valid: Any) -> dict[str, Any]:
    codec = Codec(valid.alphabet)
    encoded_words = [codec.encode(w) for w in valid.codewords]
    result = analyze(encoded_words)

    rounds_out: list[dict[str, Any]] = []
    for rnd in result.rounds:
        rounds_out.append(
            {
                "index": rnd.index,
                "residuals": [codec.decode(r) for r in rnd.residuals],
                "new_residuals": [codec.decode(r) for r in rnd.new_residuals],
                "epsilon_produced": rnd.epsilon,
                "expanded": [codec.decode(r) for r in rnd.expanded],
                "reuse": [
                    {
                        "residual": codec.decode(r),
                        "transitions_listed_in_round": rnd.reuse[r],
                        "note": "该残串在本轮再次参与展开，其全部前缀匹配转移已在"
                        f"第 {rnd.reuse[r]} 轮逐条列出，结果相同，不再重复",
                    }
                    for r in sorted(rnd.reuse)
                ],
                "repeated_of_round": rnd.repeated_of,
                "transitions": [
                    _transition_dict(t, codec) for t in rnd.transitions
                ],
            }
        )

    body: dict[str, Any] = {
        "ok": True,
        "unique": result.unique,
        "alphabet": valid.alphabet,
        "alphabet_order": "数组顺序即字母表序（第 0 个最小）",
        "codewords": [
            {"index": i, "value": w} for i, w in enumerate(valid.codewords)
        ],
        "termination": {
            "reason": result.termination_reason,
            "round": result.termination_round,
            "distinct_residuals": result.distinct_residuals,
            "reason_explained": {
                "epsilon": "残串变为空串：两条拼接路径对齐，码不唯一可译",
                "empty_set": "某轮残串集合为空，无任何可达对齐，码唯一可译",
                "repeated_set": "残串集合首次与历史轮次完全相同，后继确定重复，码唯一可译",
                "closure_exhausted": "本轮残串均已在历史轮次出现，其转移闭包已穷尽且从未产生空串，码唯一可译",
            }[result.termination_reason],
        },
        "rounds": rounds_out,
        "stats": {
            "round_transition_count": result.round_transition_count,
            "dijkstra_states_visited": result.dijkstra_states,
            "dijkstra_edges_seen": result.dijkstra_edges,
        },
        "ambiguity": None,
    }

    wit = result.witness
    if wit is not None:
        concat_a = [valid.codewords[i] for i in wit.indices_a]
        concat_b = [valid.codewords[i] for i in wit.indices_b]
        body["ambiguity"] = {
            "encoded_string": codec.decode(wit.encoded),
            "length": len(wit.encoded),
            "tie_break_order": [
                "1. 编码串长度最短",
                "2. 长度相同则按字母表序最小",
                "3. 再相同则按规范化（两组序列逐元素字典序较小者在前）索引序列",
            ],
            "indices_a": wit.indices_a,
            "indices_b": wit.indices_b,
            "concatenation_a": concat_a,
            "concatenation_b": concat_b,
            "joined_a": "".join(concat_a),
            "joined_b": "".join(concat_b),
            "sequences_differ": wit.indices_a != wit.indices_b,
            "derivation": [
                _derivation_step_dict(s, codec) for s in wit.derivation
            ],
            "derivation_note": (
                "逐步残串推导：append_side 表示该步在 0/1 哪一侧追加码字；"
                "从初始码字对开始，残串经 code_extends_residual / "
                "residual_extends_code 转移直至 ε；按 side 收集码字索引即得 "
                "indices_a / indices_b。"
            ),
        }

    body["verification_recipe"] = {
        "unique_case": (
            "从 rounds[0] 的码字前缀对出发，逐轮按 transitions 中的等式用"
            " codeword 拼接复核每个残串；末轮集合为空或与历史轮次重复即唯一。"
        ),
        "ambiguous_case": (
            "ambiguity.derivation 的每一步残串等式均可由 codewords 直接拼接复核；"
            "joined_a 与 joined_b 必须相等且分别由 indices_a、indices_b 拼出。"
        ),
    }
    return body


@app.post("/verify")
async def verify(request: Request) -> JSONResponse:
    raw = await request.body()
    if not raw:
        return _error_response(
            [{"loc": ["body"], "code": "empty_body", "message": "请求体为空"}]
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return _error_response(
            [
                {
                    "loc": ["body"],
                    "code": "invalid_json",
                    "message": f"请求体不是合法 JSON：{exc.msg}",
                    "position": getattr(exc, "pos", None),
                }
            ]
        )

    valid, issues = validate_payload(payload)
    if issues:
        return _error_response([i.to_dict() for i in issues])
    assert valid is not None
    return JSONResponse(status_code=200, content=_build_response(valid))


@app.get("/")
def index() -> dict[str, str]:
    return {"service": "variable-code-verifier", "health": "/health", "verify": "POST /verify"}


def main() -> None:
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "0.0.0.0")
    uvicorn.run("app.main:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
