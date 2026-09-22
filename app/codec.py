"""字母表秩编解码。

工程师给出的字母表是**有序**的 ASCII 符号表：第 k 个符号编码为字节
k（0..m-1），于是字节的字典序严格等于字母表序，残串图内部一律用
字节串运算，输出时再逐字节译回符号。
"""

from __future__ import annotations


class Codec:
    def __init__(self, symbols: list[str]) -> None:
        self.symbols = symbols
        self._rank = {ch: i for i, ch in enumerate(symbols)}

    @property
    def size(self) -> int:
        return len(self.symbols)

    def encode(self, text: str) -> bytes:
        return bytes(self._rank[ch] for ch in text)

    def decode(self, data: bytes) -> str:
        return "".join(self.symbols[b] for b in data)
