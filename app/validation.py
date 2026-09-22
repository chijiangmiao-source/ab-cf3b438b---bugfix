"""输入校验：所有非法输入均返回带位置的结构化问题清单。

规则（来自需求）：
  * 码字数量 2..400，两两互异、非空；
  * 字母表为 2..8 个有序、互异的 ASCII 单字符符号，顺序即字母表序；
  * 单码字长度 ≤ 256，全部码字总长 ≤ 20000；
  * 码字中每个符号都必须出现在字母表中。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MIN_CODEWORDS = 2
MAX_CODEWORDS = 400
MIN_ALPHABET = 2
MAX_ALPHABET = 8
MAX_CODEWORD_LEN = 256
MAX_TOTAL_LEN = 20_000


@dataclass(frozen=True)
class Issue:
    loc: list[str | int]
    code: str
    message: str
    extra: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "loc": list(self.loc),
            "code": self.code,
            "message": self.message,
        }
        if self.extra:
            out.update(self.extra)
        return out


@dataclass(frozen=True)
class ValidInput:
    alphabet: list[str]
    codewords: list[str]


def validate_payload(payload: Any) -> tuple[ValidInput | None, list[Issue]]:
    issues: list[Issue] = []

    if not isinstance(payload, dict):
        issues.append(
            Issue(["body"], "invalid_body", "请求体必须是 JSON 对象")
        )
        return None, issues

    # ---- 字母表 ----
    alphabet_raw = payload.get("alphabet")
    alphabet: list[str] = []
    if "alphabet" not in payload:
        issues.append(Issue(["body", "alphabet"], "missing_field", "缺少 alphabet 字段"))
    elif not isinstance(alphabet_raw, list):
        issues.append(
            Issue(["body", "alphabet"], "not_an_array", "alphabet 必须是数组")
        )
    else:
        if not (MIN_ALPHABET <= len(alphabet_raw) <= MAX_ALPHABET):
            issues.append(
                Issue(
                    ["body", "alphabet"],
                    "invalid_size",
                    f"字母表须含 {MIN_ALPHABET}..{MAX_ALPHABET} 个符号，"
                    f"实际 {len(alphabet_raw)} 个",
                    {"actual": len(alphabet_raw), "min": MIN_ALPHABET, "max": MAX_ALPHABET},
                )
            )
        seen_symbols: dict[str, int] = {}
        for pos, sym in enumerate(alphabet_raw):
            loc = ["body", "alphabet", pos]
            if not isinstance(sym, str):
                issues.append(Issue(loc, "not_a_string", "字母表元素必须是字符串"))
                continue
            if len(sym) != 1:
                issues.append(
                    Issue(
                        loc,
                        "not_single_symbol",
                        "字母表元素必须恰好为一个字符",
                        {"length": len(sym)},
                    )
                )
                continue
            if ord(sym) >= 128:
                issues.append(
                    Issue(loc, "not_ascii", f"符号 {sym!r} 不是 ASCII 字符")
                )
                continue
            if sym in seen_symbols:
                issues.append(
                    Issue(
                        loc,
                        "duplicate_symbol",
                        f"符号 {sym!r} 与位置 {seen_symbols[sym]} 重复",
                        {"first_at": seen_symbols[sym], "symbol": sym},
                    )
                )
                continue
            seen_symbols[sym] = pos
            alphabet.append(sym)

    # ---- 码字表 ----
    codewords_raw = payload.get("codewords")
    codewords: list[str] = []
    alphabet_usable = (
        isinstance(alphabet_raw, list)
        and MIN_ALPHABET <= len(alphabet_raw) <= MAX_ALPHABET
        and not any(i.loc[:2] == ["body", "alphabet"] for i in issues)
    )
    valid_string_indices: list[int] = []
    if "codewords" not in payload:
        issues.append(
            Issue(["body", "codewords"], "missing_field", "缺少 codewords 字段")
        )
    elif not isinstance(codewords_raw, list):
        issues.append(
            Issue(["body", "codewords"], "not_an_array", "codewords 必须是数组")
        )
    else:
        if not (MIN_CODEWORDS <= len(codewords_raw) <= MAX_CODEWORDS):
            issues.append(
                Issue(
                    ["body", "codewords"],
                    "invalid_size",
                    f"码字数量须为 {MIN_CODEWORDS}..{MAX_CODEWORDS}，"
                    f"实际 {len(codewords_raw)}",
                    {
                        "actual": len(codewords_raw),
                        "min": MIN_CODEWORDS,
                        "max": MAX_CODEWORDS,
                    },
                )
            )

        alphabet_set = set(alphabet)
        seen_words: dict[str, int] = {}
        total_len = 0
        for idx, word in enumerate(codewords_raw):
            loc = ["body", "codewords", idx]
            if not isinstance(word, str):
                issues.append(Issue(loc, "not_a_string", "码字必须是字符串"))
                continue
            if len(word) == 0:
                issues.append(Issue(loc, "empty_codeword", "码字不得为空串"))
                continue
            valid_string_indices.append(idx)
            total_len += len(word)
            if len(word) > MAX_CODEWORD_LEN:
                issues.append(
                    Issue(
                        loc,
                        "codeword_too_long",
                        f"码字长度 {len(word)} 超过上限 {MAX_CODEWORD_LEN}",
                        {"length": len(word), "max": MAX_CODEWORD_LEN},
                    )
                )
            # 字母表合法时才派生逐字符位置检查，避免噪音错误。
            if alphabet_usable:
                for cp, ch in enumerate(word):
                    if ch not in alphabet_set:
                        issues.append(
                            Issue(
                                loc + ["char", cp],
                                "symbol_not_in_alphabet",
                                f"符号 {ch!r} 不在字母表中",
                                {"symbol": ch, "char_position": cp},
                            )
                        )
            if word in seen_words:
                issues.append(
                    Issue(
                        loc,
                        "duplicate_codeword",
                        f"码字与索引 {seen_words[word]} 重复",
                        {"first_at": seen_words[word]},
                    )
                )
            else:
                seen_words[word] = idx
            codewords.append(word)

        if total_len > MAX_TOTAL_LEN:
            issues.append(
                Issue(
                    ["body", "codewords"],
                    "total_length_exceeded",
                    f"码字总长度 {total_len} 超过上限 {MAX_TOTAL_LEN}",
                    {"actual": total_len, "max": MAX_TOTAL_LEN},
                )
            )

    if issues:
        return None, issues
    return ValidInput(alphabet=alphabet, codewords=codewords), []
