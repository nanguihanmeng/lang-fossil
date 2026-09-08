# 语言支持扩展实施计划：C / C++ / C# / Java

> 目标版本：lang-fossil 0.3
> 状态：v0.2.0 已按 D1–D4 落地（ADR-0004）；**批次 1 修订已于 v0.3.0 实施**
> （ADR-0005）：.h 内容评分删除、改 `ambiguous_headers` 配置策略；规则引入
> `category`（fossil/unsafe）与版本元数据，unsafe 不冒充断代。
> **批次 2–4 已于 v0.4.0 全部实施**：外部 linter（eslint/clang-tidy/PMD）输出
> 对接与 `annotate` 标注（ADR-0007）、git 年代错位维度接入报告（ADR-0006）、
> 废弃/移除数据化与官方源同步管线（ADR-0008）。
> 关联：docs/rules-guide.md、docs/adr/、src/lang_fossil/core/language.py
>
> **归档记录**：`docs/archive/2026-09-08-v0.2.0-c-family-support.md`（实施）与
> `docs/archive/2026-09-08-v0.3.0-critique-batch1.md`（批次 1 修正）；
> 归档目录已由 `.gitignore` 排除，不进版本库。

---

## 1. 调研分析

### 1.1 现有语言识别架构与扩展点

当前语言识别是**纯扩展名直判**，无内容探测、无置信度概念：

```
language.py: _LANG_BY_EXT ──> sniff_language(Path) ──> "python" | "javascript" | None
                                                                  │
        discover()（扫描器）            ┌────────────────────────┘
                                        ▼
        FileEntry.language（单一字符串标签）
                                        │
        scanner.scan()  parsers 注册表: {"python": ParsoPythonParser,
                                        │   "javascript": JsHeuristicParser}
                                        ▼
        engine.run(): 按 parse_result.language 取规则集 for_language()
```

语言相关事实分布在 **4 处**（无独立枚举类型）：

| 位置 | 现状 | 新增语言需要 |
| --- | --- | --- |
| `core/language.py` | `.py/.pyw → python`；`.js/.mjs/.cjs/.jsx → javascript` | 追加 8 个扩展名；新增 `.h` 歧义处理 |
| `rules/registry.py` | `RuleSpec.language: Literal["python", "javascript"]` | 扩展 Literal；无需改加载器（`load_from_dir` 按目录递归） |
| `core/scanner.py` `parsers` 表 | 硬编码两语言 → 解析器 | 每语言注册一行；C 系均走启发式解析器 |
| `core/fixer.py` | `_PYTHON_TOOL if language == "python" else _JS_TOOL` | **陷阱**：非 python 语言会默认派发 `eslint --fix`，必须先改守卫 |

其余子系统对语言无硬编码，可直接复用：
- 规则引擎：`regex` kind + `match_mode: heuristic` 走逐行匹配（与 JS 相同路径），C 家族可 100% 复用。
- 分层/报告：era 为自由字符串，`_ERA_ORDER` 未收录时代会按字母序排于已知时代之后（需增补）。
- 僵尸 API 检测：`engine.run()` 显式 `parse_result.language == "python"` 守卫 → 新增语言自动豁免，无副作用。
- 克隆指纹：tokenizer 已剥除 `#`、`//`、`/* */` 注释，覆盖 C 系与 Java；**注意**：C 预处理行（`#include`/`#define`）会被 `#` 行注释规则误剥，影响的是指纹内容而非识别正确性（见 5.3 风险）。

### 1.2 四种语言的语法特征、扩展名与标识模式

| 维度 | C | C++ | C# | Java |
| --- | --- | --- | --- | --- |
| 扩展名（源） | `.c` | `.cpp` `.cc` `.cxx` | `.cs` | `.java` |
| 扩展名（头） | `.h` | `.h` `.hpp` `.hh` `.hxx` | — | — |
| 行注释 | `//`（C99+） | `//` | `//` | `//` |
| 块注释 | `/* */` | `/* */` | `/* */` | `/* */` |
| 预处理指令 | `#include/#define/#pragma` | 同 C | `#region/#if` | — |
| 包/命名空间 | — | `namespace X {` | `namespace X {` | `package x.y;` |
| 导入 | — | `#include` | `using X;` | `import x.y.Z;` |
| 类型系统标记 | `struct/union/enum` | `class/struct/namespace/template` | `namespace/class/interface/enum record` | `class/interface/extends/implements` |
| 字符串 | `"..."` + `char` 单字符 | 同 C + `std::string` | `"..."` + `@"..."` | `"..."` + 无原生 `@` |
| 入口点 | `int main(` | `int main(` | `static void Main(` | `static void main(` |
| 独有特征 | `printf(..., ...)`、`->`、`malloc/free` | `std::`、`template<`、`class X : public`、`new/delete`、`cout`、`override`、`constexpr`、`static_cast` | `public/private` 全面、`var`、`=>`、`async/await`、属性 `[X]` | `@Override` 等注解、`String[] args`、`throws`、`.class`（编译产物） |

### 1.3 抽象化改造评估结论

需要的最小抽象改造（均低成本）：

1. **收敛语言常量**：将 `language.py` 的扩展名映射 + `RuleSpec.language` 的可选值 + `scanner.parsers` 键 + `fixer` 工具映射收敛为一处"语言注册表"（常量 + 按语言分组的辅助函数），避免四处漂移。
2. **引入可选的歧义解析层**：`sniff_language()` 对明确扩展名保持直判；仅 `.h`（及无扩展名候选）进入内容探测，返回 `c`/`cpp`。
3. **启发式解析器通用化**：`JsHeuristicParser` 与未来四门语言是同一形态（tree=None + heuristic=True + 语言标签），抽为一个可参数化的通用启发式解析器，消除每语言一份复制。

不需要（YAGNI，明确不作为本计划范围）：为 C 家族引入真实 AST 解析器（libclang/gumtree 等）、token 级词法分析、代码修复引擎。

---

## 2. 词法与语法规则定义

规则全部以 `match_mode: heuristic` + `kind: regex` 落盘于
`src/lang_fossil/rules/builtin/<lang>/<pack>.yaml`，复用现有 schema 与校验。

### 2.1 关键字集合（供规则 target 引用）

| 语言 | 建议规则关注的关键字（不含全部语言关键字） |
| --- | --- |
| C | `main(`、`printf/scanf/gets/strcpy/sprintf`（不安全函数族）、`malloc/free`、`#include <.*>` |
| C++ | `using namespace`、`template<`、`new/delete`、`std::`、`auto_ptr`、`NULL`、`throw` |
| C# | `var`、`=>`、`async/await`、`ArrayList`（非泛型集合）、`#region` |
| Java | `Vector/Hashtable/StringBuffer`（遗留集合）、`synchronized`（方法级）、`@Override` |

> 语义：为保持产品定位（"化石检测"），新语言规则聚焦**语言时代遗留惯用法**（如 C 的 `gets()`、C++ 的 `auto_ptr`、Java 的 `Vector`、C# 的非泛型 `ArrayList`），而非重复通用 lint。

### 2.2 规则包内聚约定

- **C 与 C++ 的重叠**：预处理指令、头文件、`//`/`/* */` 注释两侧通用；`#include <iostream>` 归 C++ 包，`#include <stdio.h>` 归 C 包；`.h` 内规则（如 `#define`）按文件最终判定语言归属。
- **C# 与 Java 的结构标记**：以 `namespace/package` 行、`using/import` 行区分；`.cs` 与 `.java` 扩展名已无歧义，结构标记仅用于内容探测（同文件混编时的评分）与文档化。
- **era 建议**（需增补 `_ERA_ORDER` 或按语言代际注册）：
  - C：`c90`/`c99`/`c11`
  - C++：`cpp98`/`cpp11`/`cpp17`
  - C#：`cs1`/`cs2`（4.0）/`cs8+`
  - Java：`java-legacy`（≤7）/`java8`/`java9+`

---

## 3. 特征提取实现

### 3.1 扩展名映射（`core/language.py`）

```python
_LANG_BY_EXT = {
    ".py": "python", ".pyw": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".jsx": "javascript",
    ".c": "c", ".h": None,            # None = 内容探测
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp",
    ".hpp": "cpp", ".hh": "cpp", ".hxx": "cpp",
    ".cs": "csharp",
    ".java": "java",
}
```

### 3.2 内容评分逻辑（新增，仅歧义触发）

新增 `content_probe(source, ext_hint) -> str`，C/C++ 判定优先级：

| 权重 | C++ 强信号 | C 强信号 |
| --- | --- | --- |
| +4 | `#include <iostream>/<vector>/<string>`、`namespace `、`template<` | `#include <stdio.h>/<stdlib.h>`、`printf(` |
| +2 | `std::`、`class .*:`、`new / delete`、`static_cast`、`.hpp 头扩展名` | `->`、`malloc/free`、`struct .*{`、`.c 源扩展名` |
| +1 | `//` 密度高、`using `、`constexpr` | `#define` 宏、`int main(int argc, char` |

判定：`score(cpp) > score(c)` 且差值 ≥ 阈值 → `cpp`；否则默认 `c`（保守）。评分函数置于 `language.py`，只对 `.h`（或无扩展名候选）调用，主路径零开销。

### 3.3 C 与 C++ 歧义场景

| 场景 | 判定 |
| --- | --- |
| `foo.c` / `foo.cpp` | 扩展名直判，不评分 |
| `foo.h`（含 iostream/namespace） | 内容评分 → cpp |
| `foo.h`（纯 struct + stdio） | → c（默认） |
| 同一文件同时混编（罕见） | 评分取高分；仍打平取 c（文档化约定） |

---

## 4. 识别引擎集成

1. **语言注册表（抽象化落地）**
   - `RuleSpec.language` 扩展为 `Literal["python", "javascript", "c", "cpp", "csharp", "java"]`。
   - 提供 `SUPPORTED_LANGUAGES` 常量与 `tool_for(language) -> tuple | None`（收敛 fixer 映射）。
2. **解析器注册**（`scanner.scan` 的 `parsers` 表）
   - 将 `JsHeuristicParser` 通用化（新增语言参数），四门新语言注册同一启发式解析器：
     ```python
     parsers = {lang: heuristic(lang) for lang in SUPPORTED_HEURISTIC_LANGS}
     ```
   - `discover()` 中：`sniff_language` 返回 `None` 的候选文件仅在歧义白名单（`.h`）时读源并调 `content_probe` 补充判定。
3. **fixer 守卫**（防回归关键）
   - `build_fix_plan` 改为查 `tool_for(language)`；新语言无对应工具时返回 `None` 直接跳过（不再落到 `eslint`）。
4. **era 顺序**：`stratigraphy._ERA_ORDER` 增补 §2.2 各语言时代顺序，或将其改为"未知时代字母序兜底"（现状）并在规则包注释中说明。
5. **僵尸 API**：维持 python-only，不加逻辑。
6. **兼容性**：现有 CLI/报告/缓存 API 不变；缓存 key 已含规则 digest，规则集变化自动失效。

---

## 5. 测试验证

### 5.1 样本语料

- 新增 `tests/golden/corpus/c_syntax_repo/`、`cpp_syntax_repo/`、`csharp_syntax_repo/`、`java_syntax_repo/`：每语言 2–4 个代表性文件，含遗留惯用法正样本 + 现代语法负样本。
- 新增 `tests/unit/core/test_language_probe.py`：C/C++ 内容评分的命中矩阵。

### 5.2 边界用例

| 场景 | 期望 |
| --- | --- |
| 空文件 / 纯注释 / 纯空白 | 扩展名直判语言；无 fossil；评分函数不崩溃 |
| `.h` 含 C++ 信号 | 判定 cpp |
| `.h` 无信号 | 默认 c |
| 混编文件（打分打平） | 文档化默认（c）并断言 |
| 大文件评分 | 只取前 N 行采样评分，保性能预算 |
| 现有 4 个 python/js golden | 零回归（回归门禁） |

### 5.3 已知取舍（纳入维护说明）

- 克隆 tokenizer 将 C 预处理行当注释剥除 → 指纹不含 `#include` 文本（仅影响指纹颗粒度，不影响识别）；如需精确可后续让 tokenizer 对 C 家族关闭 `#` 行注释规则。
- 新语言为纯启发式，不承诺无漏报/无语法级语义。

---

## 6. 文档更新

- `README.md` / `README_CN.md`：支持语言列表、识别规则说明（扩展名表 + `.h` 歧义规则 + era 体系）。
- `docs/rules-guide.md`：新增语言规则包编写示例（C 家族一条规则全流程）。
- `docs/adr/`：新增 ADR——"语言识别抽象化与 C 家族启发式支持"（记录：扩展名直判 + 内容探测仅歧义触发、heuristic 而非 AST、fixer 守卫）。

---

## 待批准决策点（D1–D4）

| 决策 | 建议默认 | 备选 |
| --- | --- | --- |
| D1 | 识别口径 = 扩展名直判 + `.h` 内容探测（无扩展名文件不纳入 v1） | 全量内容评分（不建议，收益低） |
| D2 | C 家族仅启发式行级规则，不引 AST | 引入 libclang（成本高，后续单列） |
| D3 | era 使用语言代际标签（c90/cpp98/...）并增补排序 | 复用通用 paleozoic/...（语义失配，不建议） |
| D4 | 新语言规则 v1 一律不填 `fix_hint`，fixer 无工具即跳过 | 接入 clang-tidy（后续单列） |

## 工作量估算

| 阶段 | 内容 | 估算 |
| --- | --- | --- |
| 1 调研 | 本计划 | 0.5 d |
| 2 规则定义 | 4 语言规则表 + 首批 ~16 条规则 YAML | 0.5 d |
| 3 特征提取 | 扩展名 + content_probe + 评分单测 | 1 d |
| 4 引擎集成 | language.py/scanner/registry/fixer/stratigraphy | 1 d |
| 5 测试 | 4 组语料 + 边界 + 回归 | 1.5 d |
| 6 文档 | README(CN/EN)/rules-guide/ADR | 0.5 d |
| 合计 | | ≈ 5 d |

按 D1–D4 建议默认执行即可开工；若需调整任何默认，在开工前指出即可。
