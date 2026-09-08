# 规则编写指南

本文说明如何为 lang-fossil 编写规则包（rule pack）。

## 文件与位置

- 内置规则：`src/lang_fossil/rules/builtin/<language>/<pack>.yaml`
- 自定义规则：任意目录，通过 `RuleRegistry.load_from_dir()` 加载
- 正/反例样本：与规则同包的 `samples/samples.yaml`（测试强制对齐）

## Schema

规则是 YAML 文件，顶层为 `rules:` 列表。每个规则经过 pydantic 白名单校验
（`extra="forbid"`：写错键名是加载错误，不是静默失效）：

```yaml
rules:
  - id: PF011            # 必须匹配 ^[A-Z]{2,4}\d{3}$，全局唯一
    language: python     # python | javascript | c | cpp | csharp | java
    category: fossil     # fossil（可断代）| unsafe（不良实践，永不断代）
    era: paleozoic       # 地层标签；fossil 用 paleozoic/c99/cpp17/...；
                         # unsafe 规则必须用保留字 "unsafe"
    removed_in: "python3"  # fossil 必填（deprecated_in/removed_in 至少其一）
    message: "..."       # 化石描述（面向用户）
    severity: error      # info | warning | error
    provenance: "..."    # 必填！规则来源，映射到现有 lint 生态
    source: "https://..."  # 可选；佐证废弃/移除声明的官方文档 URL
    fix_hint: "..."      # 可选；有值才会被 --fix 桥接
    match_mode: ast      # ast（需要解析树）| heuristic（逐行正则）
    match:
      kind: name         # 见下表
      target: xrange
```

### category 语义（v0.3.0）

- `fossil`：该构造已被语言标准**废弃/移除**（须填 `deprecated_in`/`removed_in`，
  schema 强校验），其 era 是可靠的断代信号。
- `unsafe`：至今仍合法但属不良/遗留实践（如 `sprintf`、`var`、`eval`），era
  恒为保留字 `unsafe`，报告将其归入独立审查地层，**不会**被当作年代化石。
- 二者不可混用：unsafe 不能携带版本字段；fossil 不能使用 `unsafe` 地层。

## match.kind 一览

| kind | target 含义 | 示例 |
| --- | --- | --- |
| `node` | parso 节点类型 | `print_stmt`（Py2 print 语句） |
| `name` | 裸标识符（非属性访问） | `xrange` |
| `attribute` | 属性访问名（必须跟在 `.` 后） | `has_key`、`iteritems` |
| `string_prefix` | 字符串前缀（配合 `prefix`） | `ur` |
| `import` | 导入模块（含子模块匹配） | `distutils` |
| `regex` | 逐行正则（heuristic 模式） | `^\s*raise\s+\w+\s*,\s*` |

## provenance 约定

规则必须标注来源，用于映射 lint 生态、追溯数据出处：

- 生态映射：`"ecosystem: pyupgrade"`、`"ecosystem: eslint (no-var)"`
- 内部规则：`"ecosystem: internal"` 或注明语法依据
- 数据驱动（僵尸 API 检测由 `dead-packages.json` 驱动，不写 YAML 规则）

## 校验测试

新增规则后运行：

```bash
pytest tests/unit/rules/test_registry.py   # schema 与 id 唯一性
pytest tests/golden -m golden              # 黄金语料快照回归
```

## 多语言规则包与识别

内置规则按语言目录组织：`builtin/<language>/`（python / javascript / c /
cpp / csharp / java）。语言识别以扩展名直判为主，`core/language.py` 是唯一
注册点；歧义扩展名（C/C++ 共用的 `.h`）**不做内容评分**，改由配置策略解析
（`scan.ambiguous_headers`：`mode=auto|c|cpp` + glob `overrides`；auto 依所在
目录 `.c`/`.cpp` 多数推断，无同族时默认 C）。

新增一门语言的标准流程：

1. 在 `core/language.py` 注册扩展名；歧义扩展名通过类似
   `ambiguous_headers` 的配置策略解析（永不读文件评分）。
2. 在 `scanner` 的 `parsers` 表注册解析器——新语言若无 AST，直接使用通用
   `HeuristicParser("<language>")`（正则逐行匹配，`heuristic=True`）。
3. 扩展 `rules/registry.py` 的 `RuleSpec.language` Literal。
4. 编写规则包与正/反例（每条规则声明 `category`，fossil 附版本元数据）。
5. 黄金语料：`tests/golden/corpus/<language>_repo/` + 在
   `tests/golden/test_golden_languages.py` 登记预期规则与 modern 文件清单。

建议的规则 id 前缀与 era（地层）标签：

| 语言 | id 前缀 | era 示例（fossil） | unsafe 地层 |
| --- | --- | --- | --- |
| python | `PF` | paleozoic / mesozoic / cenozoic | unsafe |
| javascript | `JS` | （内置规则全为 unsafe） | unsafe |
| c | `CF` | c90 / c99 / c11 | unsafe |
| cpp | `CXX` | cpp98 / cpp11 / cpp17 | unsafe |
| csharp | `CS` | cs1 / cs8 | unsafe |
| java | `JV` | java-legacy | unsafe |

era 排序见 `core/stratigraphy.py` 的 `_ERA_ORDER`（`unsafe` 位于各 fossil 地层
之后、`meta` 之前）。示例——unsafe 规则（C，启发式逐行）：

```yaml
- id: CF002
  language: c
  category: unsafe
  era: unsafe
  message: "sprintf() has no bounds argument; use snprintf()"
  severity: error
  fix_hint: "replace sprintf(dst, fmt, ...) with snprintf(dst, n, fmt, ...)"
  provenance: "ecosystem: SEI CERT MSC24-C; cppcheck"
  match_mode: heuristic
  match:
    kind: regex
    target: "\\bsprintf\\s*\\("
```

fossil 示例（移除于 C11，附版本标签并进入 c11 地层）：

```yaml
- id: CF001
  language: c
  category: fossil
  era: c11
  removed_in: "c11"
  message: "gets() was removed in C11; use fgets()"
  severity: error
  provenance: "ecosystem: SEI CERT MSC24-C; clang-tidy cert-*"
  source: "https://en.cppreference.com/w/c/io/gets"
  match_mode: heuristic
  match:
    kind: regex
    target: "\\bgets\\s*\\("
```

## 僵尸 API 快照（数据驱动）

标准库"已移除 API"不写在 YAML 中，而是由**数据驱动**：离线快照
`dead-packages.json` 随 wheel 分发，运行时零网络访问。条目格式：

```json
{ "module": "distutils", "removed_in": "3.12", "removal": "pep632",
  "replacement": "setuptools / sysconfig / packaging" }
```

支持模块级条目（`module`）与属性级条目（`module` + `attribute`，
如 `asyncio.get_event_loop` 的语义移除；attribute 必须是单段名，带点的
attribute 在加载时被拒绝）。

### 维护流程（v0.4.0 起）

快照由 **manifest 生成**，不再手改双份 JSON：

1. 编辑 `scripts/deprecation-sources.yaml`（唯一权威，含 `sources` 元数据；
   每条可带可选 `ref_url` 官方引用与 `removed_in/removal/replacement`）。
2. `python scripts/sync_deprecations.py check` — 双份与清单一致（无网络）。
3. （有 `ref_url` 的条目）`python scripts/sync_deprecations.py verify` —
   抓取官方文档并断言 module/attribute 文本存在。
4. `python scripts/sync_deprecations.py write` — 重新渲染 `data/` 与
   `src/lang_fossil/data/` 两份并 bump `snapshot_version`。

快照顶层含 `schema_version`、`sources` 与 `snapshot_version` 元数据
（`offline_db.py` 兼容加载，缺省安全）。

## 对接外部 linter（`annotate`）

lang-fossil 不运行 clang-tidy/PMD/eslint，而是**消费其报告**并附加考古元标签：

```bash
lang-fossil annotate <repo-root> <report-file> --tool eslint|clang-tidy|pmd \
    [--format table|json] [--output out.json]
```

支持的机器格式：eslint JSON（数组式）、clang-tidy 文本诊断
（`file:line:col: severity: msg [rule]`）、PMD XML（`-f xml`）。

标注来源：

- **alias**：外部 `(tool, rule)` 命中内置规则 provenance 的
  `ecosystem: <tool> (<rule>)` 别名（如 eslint `no-var` → JS002）；
- **position**：无别名时，finding 所在文件由内置规则扫描，**同行**化石作为
  标注（fossil 优先于 unsafe）；
- 两通道皆无 → `unannotated`（不为无法断代的构造捏造年代）。

自定义规则若要被 alias 通道识别，只需在 `provenance` 中声明
`ecosystem: <tool> (<external-rule-id>)` 形式即可。

## 贡献规则（社区）

内置规则是**种子集**而非全集；欢迎按以下约定贡献（tools: pyguide 精神——
门槛极低）：

1. 目录约定：社区规则包放独立目录（建议 `rules-contrib/<topic>/<lang>.yaml`），
   通过 `RuleRegistry.load_from_dir(Path("rules-contrib"))` 加载，**不**进
   `src/lang_fossil/rules/builtin/`（内置包受 golden 快照与覆盖率门禁约束）。
2. 每条规则只需三要素：匹配（`match` + `match_mode`）、时代
   （`category` + `era` + `deprecated_in`/`removed_in`）、说明（`message` +
   `provenance`，可选 `source` 官方引用）。
3. 硬约束：`category: unsafe` 不得带版本字段；fossil 必须有版本——schema
   会在加载时拒绝"冒充断代"的规则。
4. 验收：附带正/反例样本（参照 `builtin/python/samples/samples.yaml`），
   跑 `pytest tests/unit/rules/test_registry.py` 与 golden 回归。

废弃/移除数据（僵尸 API）同样接受贡献：编辑
`scripts/deprecation-sources.yaml` 后运行
`python scripts/sync_deprecations.py write`（见上文维护流程）。
