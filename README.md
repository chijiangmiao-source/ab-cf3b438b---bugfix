# 可变长码字唯一可译性验收服务

海洋声学浮标观测帧压缩场景的纯后端服务：工程师一次提交 2..400 个按优先
顺序排列的互异非空码字，服务**自行构造残串状态图**（不使用任何现成编码
理论库或通用求解库）判定码是否唯一可译：

* **唯一**：返回逐轮残串集合，直到某轮集合为空或与历史轮次首次重复；
* **歧义**：返回最短编码串与两组不同索引序列，按
  串长 → 字母表序 → 规范化索引序列（两组序列逐元素字典序较小者在前）
  三重裁决。

响应中每条残串转移都以等式列出，歧义另附两组码字拼接与逐步残串推导，
所有结论均可直接由码字拼接复核。

## 技术栈

Python 3.13 · FastAPI · Uvicorn，纯后端，无前端、无数据库、无在线调用。

## 运行（Docker）

```bash
# 默认宿主机端口 8000
docker compose up --build

# 自定义宿主机端口
HOST_PORT=18000 docker compose up --build
# 或
docker compose build && HOST_PORT=18000 docker compose up -d
```

健康检查：

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok", ...}
```

容器内置 Docker 健康检查（轮询 `/health`）。

## 可执行验收服务 verify

仓库根目录的 `verify` 是零第三方依赖（仅标准库）的可执行验收程序：

```bash
# 1) 容器外/本地直接对引擎跑全部固定用例 + 400 组随机暴力对拍 + 非法输入用例
./verify

# 2) 对运行中的服务做端到端 HTTP 验收
./verify --url http://127.0.0.1:8000

# 3) 在 Compose 中对 api 容器做端到端验收（等待健康检查通过）
docker compose --profile acceptance run --rm verify
```

退出码 0 表示全部通过。对拍器独立枚举所有短索引序列并按同一三重规则
裁决，与残串图结果逐项比对。

## 接口

### `POST /verify`

请求：

```json
{
  "alphabet": ["0", "1"],
  "codewords": ["0", "01", "10"]
}
```

`alphabet` 为 2..8 个互异 ASCII 单字符，**数组顺序即字母表序**；
`codewords` 为 2..400 个互异非空串，单码字 ≤ 256，总长 ≤ 20000。

歧义响应关键字段：

* `termination.reason`：`epsilon`（歧义）/ `empty_set` /
  `repeated_set` / `closure_exhausted`（后三者唯一）；
* `rounds[]`：逐轮残串集合、新增残串与全部转移等式
  （`initial_prefix_pair`、`code_extends_residual`、
  `residual_extends_code`）；
* `ambiguity.encoded_string` / `indices_a` / `indices_b` /
  `concatenation_a` / `concatenation_b`：最短歧义串与两组分解，
  `joined_a == joined_b` 可直接复核；
* `ambiguity.derivation[]`：逐步残串转移（含追加侧与码字索引）。

非法输入返回结构化 `422`：

```json
{
  "ok": false,
  "error": {
    "type": "validation_error",
    "issues": [
      {"loc": ["body", "codewords", 1, "char", 0], "code": "symbol_not_in_alphabet",
       "message": "符号 'x' 不在字母表中", "symbol": "x", "char_position": 0}
    ]
  }
}
```

`loc` 精确到字段、数组下标乃至非法字符位置；一次返回全部问题。

## 算法概要（详见 `app/sardinas.py` 文档字符串）

1. 码字 trie 一次性枚举「残串 × 码字」的两类前缀匹配；
2. 宽度优先生成逐轮残串集合 S₁, S₂, …（S₁ 来自码字真前缀对，之后每轮
   由上一轮残串与码字的前缀匹配产生），产生 ε 即歧义，某轮集合为空、
   与历史轮次完全相同或不再有新残串即唯一；
3. 在带方向状态 `(残串, 长侧)` 上以 `(公共串长, 公共串文本)` 为键做
   Dijkstra，得长度最短、字母表序最小的歧义串 w；
4. 在 w 的位置 DAG 上自右向左动态规划，求字典序最小与次小的两种不同
   完整码字分解（第三重裁决）；
5. 双指针对齐两组序列，机械生成逐步残串推导。

## 目录

```
app/
  main.py         FastAPI 路由与响应组装
  sardinas.py     残串状态图 / 逐轮集合 / 最短见证（核心算法）
  codec.py        字母表秩编解码（秩字节序 = 字母表序）
  validation.py   带位置的结构化输入校验
verify            可执行验收服务（固定用例 + 暴力对拍 + HTTP 验收）
Dockerfile
docker-compose.yml
requirements.txt
```
