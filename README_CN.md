<div align="center">

[EN](README.md) | **中文**

# lang-fossil

**90% 的大型代码库，都活在错误的历史版本中。**

每个遗留系统都有自己的地质层：为早已终结的时代而写的代码——平台已经移除的
API，语言已经废弃的惯用法，已解散的团队留下的习惯。没有人规划过它，也没有
人完整地看见过它。每一次重构决策，都是半盲飞行。

**lang-fossil 是代码的碳 14 测年仪。** 把它指向你的仓库，它替你读出地层：
代码属于哪个时代，哪些 API 早已死亡，哪些模块仍在用十年前的风格被维护。
零配置、零网络、无需重写——结论以一份地层学报告交付，你的团队这个冲刺就
能行动。

*不要问你的代码写了多久，问它在为哪个时代而写。*

</div>

---

> 代码考古学 —— 挖掘跨语言时代的"化石"级遗留 API。

`lang-fossil` 是一款**离线优先的静态分析 CLI**：对存量代码仓库进行扫描并报告其中的 *fossils*（化石）——即属于某个语言更早时代的语法、惯用法与标准库 API，例如 Python 2 的 `print` 语句、`ur''` 字面量、`distutils` 导入、已被移除的标准库函数等——并按语言时代与模块聚合为一份**地层学报告（stratigraphy report）**。

其定位与既有 lint 生态**互补而非重复**：linter 告诉你什么"可升级"，`lang-fossil` 告诉你什么"已经死亡"（从标准库中移除的 API），以及"同一化石如何在不同地层中反复出现"（复制粘贴的代码）。全部检测基于随包分发的离线快照，扫描期间**不进行任何网络访问**，因此天然适配 CI 与隔离内网环境。

---

## 目录

- [项目背景与目标](#项目背景与目标)
- [核心功能模块](#核心功能模块)
- [命令一览](#命令一览)
- [整体技术架构](#整体技术架构)
- [关键设计思路](#关键设计思路)
- [目录结构说明](#目录结构说明)
- [环境依赖与构建方式](#环境依赖与构建方式)
- [配置说明](#配置说明)
- [使用示例](#使用示例)
- [测试方案](#测试方案)
- [扩展与维护建议](#扩展与维护建议)

---

## 项目背景与目标

遗留代码并非均匀"死亡"。一个经年累月的仓库同时混有多个"地质层"：Python 3 代码树里的 Python 2 惯用法、仍能解析但已被移除的标准库导入、跨模块整体复制的文件。本项目以此为命题：将代码库视作考古遗址，按时代对发现物分类。

目标：

1. **检测"已死"而非仅"可升级"。** 在语法时代规则之外，使用离线数据快照标记已从标准库*移除*的模块与 API（`distutils`、`imp`、`asyncore`、`inspect.getargspec` 等），而非依赖手工维护的规则列表。
2. **让技术债清晰可读。** 计算 *Fossil Index*（每千行化石数），按语言时代与模块分层统计，并以人（HTML）、工具（JSON）、CI 平台（SARIF 2.1.0）可消费的格式输出。
3. **融入 CI。** `check` 命令即预算门禁，附带稳定的退出码契约。
4. **降级而非中断。** 无法解析的文件、损坏的缓存、缺失的可选工具一律降级为部分结果与诊断信息——扫描绝不因恶意/异常仓库而崩溃。
5. **离线优先、出处可溯。** 每条发现都记录来源（对应 lint 规则、数据快照），结果可回溯到唯一事实源。

## 核心功能模块

### 化石检测流水线

| 层级 | 职责 |
| --- | --- |
| **发现（Discovery）** | 递归遍历并按排除项剪枝；按扩展名嗅探语言；空字节（二进制）与确定性抽样过滤。 |
| **解析（Parsing）** | 多语法版本 Python 前端（parso）、标准库 `ast` 快路径、启发式 JavaScript 前端。 |
| **匹配（Matching）** | 内置规则包 + 数据驱动的僵尸 API 检测，作用于解析树与原始行文本。 |
| **分层（Stratigraphy）** | 按时代/模块/规则/严重级别聚合，并计算 Fossil Index。 |
| **报告（Reporting）** | JSON（规范数据源）、自包含 HTML、SARIF 2.1.0。 |

### 差异化能力

- **僵尸 API 检测（数据驱动、离线）。** 标准库移除项以*数据*建模——`dead-packages.json` 同时支持模块级条目（如 `distutils`，3.12 移除）与属性级条目（如 `asyncio.get_event_loop` 在 3.14 的语义移除、`configparser.SafeConfigParser`、`inspect.getargspec`）。记录一次新的移除只是一行数据变更，无需改代码。
- **代码克隆指纹（winnowing，实验性）。** 基于经典 winnowing 算法（Schleimer 等，2003）的跨文件复制粘贴检测：k-gram 哈希 + 最小指纹选取保证。用于标记"同一化石出现在多个地层中"——是考古信号，非通用查重工具。
- **多时代解析。** Python 前端先用解释器自带语法解析；当源码疑似 Python 2 时，改用内置的 Python 2.7 语法重试，使 Py2 语料可在 Py3 解释器上解析。
- **`--fix` 桥接。** 化石 → 外部修复工具（`pyupgrade`、`eslint --fix`）映射，而非自行重实现 codemod；默认仅 dry-run。桥接当前仅覆盖
  Python 与 JavaScript，其他语言在输出中显式提示。
- **规则全量溯源。** 每条内置规则记录出处并映射到既有生态（`pyupgrade`、`eslint (no-var)` 等），便于审计与消解。
- **外部 linter 标注（`annotate`）。** lang-fossil 消费 eslint/clang-tidy/PMD
  报告，按规则 provenance 别名或同行位置为每条 finding 附加考古元标签
  （era/category）；无法断代的构造如实标记 `unannotated`，绝不捏造年代。
- **Git 年代错位维度（可选）。** 开启 `[tool.lang-fossil.git] enabled` 后，
  化石携带其文件最近提交年，报告呈现 `active_fossils`——"老代码仍在活跃
  维护"的活体遗留洞察。

### 支持语言一览

| 语言 | 扩展名 | 前端 | 内置规则包 |
| --- | --- | --- | --- |
| Python | `.py`、`.pyw` | parso 多语法版本 + 标准库 `ast` | `PF*` |
| JavaScript | `.js`、`.mjs`、`.cjs`、`.jsx` | 启发式 | `JS*` |
| C | `.c`、`.h`* | 启发式 | `CF*` |
| C++ | `.cpp`、`.cc`、`.cxx`、`.hpp`、`.hh`、`.hxx`、`.h`* | 启发式 | `CXX*` |
| C# | `.cs` | 启发式 | `CS*` |
| Java | `.java` | 启发式 | `JV*` |

> \* `.h` 在 C/C++ 间存在歧义：由 `scan.ambiguous_headers` 策略解析且**不读取
> 文件内容**——`mode`（`auto` 依所在目录 `.c`/`.cpp` 多数推断，无同族时默认 C）
> 叠加按仓库相对路径匹配的 glob `overrides`（见"配置说明"）。

发现项分为两类。**化石（Fossils）**：被语言标准移除/废弃的构造，按
**era（地层时代）** 分层——沿用 Python 时代标签（`paleozoic`、`mesozoic`、
`cenozoic`），并新增各语言的版本代际地层（`c90`、`cpp98`、`cs1`、
`java-legacy` 等）。**Unsafe（审查项）**：至今仍合法的不良实践（如
`sprintf`、`var`、`eval`），归入独立的 `unsafe` 地层，**绝不当作化石断代**。

## 命令一览

| 命令 | 用途 |
| --- | --- |
| `dig` | 扫描仓库，输出表格 / JSON / HTML / SARIF 报告。 |
| `check` | CI 预算门禁：Fossil Index 或化石总数超限即失败。 |
| `diff` | 对比两份 JSON 报告（新增 / 已解决化石）。 |
| `rules` | 列出内置规则的语言、时代、模式与出处。 |
| `annotate` | 导入 eslint/clang-tidy/PMD 报告并为 finding 附加 era/category 标签。 |
| `fix` | 打印（或 `--apply` 执行）可修复化石对应的外部修复命令（桥接：Python 与 JavaScript）。 |

退出码是对 CI 的稳定接口：`0` 通过、`1` 超预算、`2` 配置/输入错误、`64` 用法错误。

## 整体技术架构

```
        ┌──────────────┐
        │     CLI      │  typer 命令入口（dig/check/diff/rules/fix）
        └──────┬───────┘
               │
   config.py ──┤  优先级：CLI > 环境变量(LANG_FOSSIL_*) > TOML > 默认值
               ▼
        discover → parse → engine → stratigraphy → reporting
        parse       parso_py（多语法版本）/ ast_py / heuristic
                    （js、c、cpp、csharp、java）
        engine      规则包（YAML，白名单校验）+ 僵尸 API 数据库（数据驱动）
        importers   eslint / clang-tidy / PMD 报告解析器
        annotate    provenance 别名 + 同行位置的外部 finding 断代标注
        infra       sqlite 内容哈希缓存 · 只读 git 封装 · 离线快照加载
        reporting   json（规范）· html（内嵌 JSON）· sarif
```

各层依赖方向严格单向：`cli`/`core` 不触碰解析器内部实现，业务模块通过依赖注入接收已验证配置，而非自行读取环境。

## 关键设计思路

架构决策均已记录于 `docs/adr/`（ADR-0001/0002/0003），要点如下：

1. **降级而非中断。** 解析失败、缓存损坏、可选二进制缺失均转化为结构化诊断（`ParseResult.errors`、缓存 miss），而非异常；仅*硬性*配置错误在启动期 fail-fast 终止。
2. **配置在边界处一次性校验。** TOML、环境变量、CLI 三类配置先合并为一个 pydantic 模型（`extra="forbid"`）再进入业务代码；环境变量遵循 `LANG_FOSSIL_` 前缀与 `__` 嵌套分隔符（`LANG_FOSSIL_SCAN__WORKERS=4`）。
3. **规则即数据，僵尸即数据。** YAML 规则包经 pydantic 白名单 schema 校验（未知键=加载错误）；已移除的标准库 API 存放于带版本的离线快照；快照版本纳入扫描缓存键，数据更新即自动失效旧结果。
4. **规范 JSON，多种视图。** JSON 文档是唯一事实源；HTML 原样内嵌以便归档，`diff` 反向读取该文档。
5. **内容寻址缓存。** 单文件结果以 `sha256(源码 ‖ 规则摘要)` 为键缓存，读取时按当前路径重贴，内容相同的改名文件亦可命中；缓存尽力而为（best-effort）且对并行 worker 线程安全。
6. **安全基线。** 仅使用 `yaml.safe_load`；git 以只读方式调用并限制动词白名单 + 列表传参（`shell=False`）；HTML 输出开启自动转义，内嵌 JSON 中和 `</script>` 序列。
7. **启发式显式化。** JavaScript 与更早于 Py2 的语料仅做正则匹配并标记 `heuristic`，下游可据此标注置信度。

## 目录结构说明

```
lang-fossil/
├── pyproject.toml             PEP 621 元数据；pdm-backend；ruff/black/mypy/pytest 配置
├── pdm.lock                   锁定依赖集（CI --frozen-lockfile 安装）
├── README.md / README_CN.md   English / 中文文档
├── LICENSE / CHANGELOG.md     版本化里程碑变更记录
├── codecov.yml                Codecov 覆盖率阈值配置
├── data/
│   └── dead-packages.json     移除快照（仓库级副本，由脚本生成）
├── scripts/
│   ├── deprecation-sources.yaml  人工维护的废弃清单（唯一权威）
│   └── sync_deprecations.py   快照 check/verify/write 同步管线
├── src/lang_fossil/
│   ├── cli/                   typer 命令 + 退出码契约
│   ├── config.py              统一配置（pydantic-settings）
│   ├── core/
│   │   ├── scanner.py         发现阶段 + 线程池编排
│   │   ├── engine.py          规则匹配 + 僵尸检测驱动
│   │   ├── models.py          冻结领域 dataclass
│   │   ├── stratigraphy.py    时代聚合与 Fossil Index
│   │   ├── zombie_api.py      标准库"已移除 API"检测
│   │   ├── clone.py           winnowing 克隆指纹
│   │   ├── annotate.py        外部 finding 断代标注（annotate 命令）
│   │   ├── fixer.py           化石 → 外部修复器映射
│   │   └── enricher.py        可选 git 碳定年（默认关闭）
│   ├── importers/             eslint · clang-tidy · PMD 报告解析器
│   ├── parsers/
│   │   ├── base.py            Parser 协议
│   │   ├── parso_py.py        多语法 Python（含 Py2 回退）
│   │   ├── ast_py.py          标准库 ast 快路径
│   │   ├── js_heuristic.py    正则级 JavaScript 前端
│   │   └── grammars/          vendored Python 2.7 parso 语法（见 ADR-0003）
│   ├── rules/                 规则注册表 + pydantic 校验的规则包
│   │   └── builtin/           <language>/规则包：python、javascript、c、
│   │                          cpp、csharp、java（见"支持语言一览"）
│   ├── reporting/             json（规范）· html · sarif 写入器
│   ├── infra/                 sqlite 缓存 · 只读 git · 快照加载
│   └── data/dead-packages.json  随 wheel 分发的版本化快照
├── tests/
│   ├── unit/                  与 src/ 一一镜像的单测
│   ├── integration/           CLI 端到端（退出码、报告文件）
│   ├── golden/                Py2/混合时代语料（发布门禁）
│   └── perf/                  墙钟性能基准
└── docs/                      rules-guide.md · adr/ · archive/（已 gitignore）
```

## 环境依赖与构建方式

**运行要求**

- Python ≥ 3.9（CI 矩阵覆盖 Linux/macOS/Windows × Python 3.9–3.13）。
- 扫描期间无需网络。

**PDM 构建（开发推荐）**

```bash
git clone <repo-url> && cd lang-fossil
pdm install -G:all          # 安装运行时 + 测试 + lint 工具链
```

**纯 pip 构建**

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate | POSIX: source .venv/bin/activate
pip install -e .            # 运行时依赖声明于 pyproject.toml
pip install pytest pytest-cov ruff black mypy   # 开发者工具链
```

**作为工具安装**

```bash
pipx install lang-fossil            # 核心 CLI，完全离线
pipx install 'lang-fossil[git]'     # 可选 git 富化 extra
```

> 说明：可选 `[git]` extra 为后续 git 富化预留 `GitPython`。当前碳定年实现通过只读、动词白名单的 subprocess 调用系统 `git` 二进制，运行期并不依赖该 extra。

## 配置说明

配置按以下优先级合并并一次性校验：

```
CLI 参数 > 环境变量 > pyproject.toml 的 [tool.lang-fossil] > 默认值
```

### TOML（pyproject.toml）

```toml
[tool.lang-fossil]
max_fossil_index = 0.5          # check 的默认门禁阈值（可选）

[tool.lang-fossil.cache]
enabled = true
path = ".lang-fossil/cache.db"  # sqlite 扫描缓存
timeout_seconds = 5.0

[tool.lang-fossil.scan]
workers = 0                     # 0 = min(CPU, 8)；显式 1..16
exclude = ["node_modules", ".venv", "venv", "dist", "build"]
parse_timeout = 5.0
sample_ratio = 1.0              # < 1.0 时按确定性抽样

[tool.lang-fossil.scan.ambiguous_headers]   # .h 解析策略（不做内容评分）
mode = "auto"                   # auto | c | cpp
[tool.lang-fossil.scan.ambiguous_headers.overrides]
"legacy_lib/*.h" = "c"          # 仓库相对路径 glob，优先于 mode

[tool.lang-fossil.git]          # 可选碳定年（默认关闭）
enabled = false
blame_batch = 200
```

### 环境变量

环境变量以 `LANG_FOSSIL_` 为前缀、`__` 作为嵌套分隔符：

```bash
export LANG_FOSSIL_SCAN__WORKERS=8
export LANG_FOSSIL_CACHE__ENABLED=0        # 关闭扫描缓存
export LANG_FOSSIL_MAX_FOSSIL_INDEX=0.8    # 支持 Optional[T] 字段
export LANG_FOSSIL_DATA_DIR=/path/to/data  # 覆盖快照位置
```

未知键或越界值将抛出 `ConfigError`（退出码 `2`），而非静默忽略。

## 使用示例

扫描目录并打印地层学表格：

```bash
lang-fossil dig ./sample-repo
```

输出自包含 HTML 报告（内嵌规范 JSON，可直接从磁盘打开）：

```bash
lang-fossil dig ./sample-repo --format html -o report.html
```

输出 JSON / SARIF：

```bash
lang-fossil dig ./sample-repo --format json  -o report.json
lang-fossil dig ./sample-repo --format sarif -o report.sarif
```

CI 预算门禁（超限退出码 1）：

```bash
lang-fossil check ./sample-repo --max-fi 0.5 --max-fossils 20
```

对比两份 JSON 报告（跟踪 `新增 / 已解决` 化石）：

```bash
lang-fossil diff baseline.json current.json
```

列出带出处的内置规则：

```bash
lang-fossil rules
```

将可修复化石桥接到外部修复器（先 dry-run，再执行）：

```bash
lang-fossil fix ./sample-repo
lang-fossil fix ./sample-repo --apply    # 需要环境装有 pyupgrade / eslint
```

### 输出示例

```
$ lang-fossil dig ./legacy-sample
┌───────────────┬─────────┬──────────────────────────┐
│ Era           │ Fossils │ Top modules              │
├───────────────┼─────────┼──────────────────────────┤
│ paleozoic     │       6 │ legacy (6)               │
│ mesozoic      │       1 │ modern (1)               │
│ cenozoic      │       2 │ legacy (2)               │
└───────────────┴─────────┴──────────────────────────┘
fossil index: 1.90/kLOC, files: 14, clones: 1, parse errors: 0
```

说明：

- 终端表格始终打印；文件输出指向 `--output`，缺省为 `lang-fossil-report.<fmt>`。
- `--no-embed` 生成 HTML 壳页 + 同级 `.json` 数据文件，该变体需 HTTP 服务
  （`python -m http.server`）——浏览器会拦截 `file://` 的 JSON 读取；默认
  内嵌模式可直接从磁盘打开。
- `--no-cache` 关闭内容哈希缓存；`--workers 1` 强制单线程扫描。

## 测试方案

测试集与源码结构一一镜像，分四层：

```bash
pytest tests/unit             # 快速单测（对应每个 src 模块）
pytest tests/integration      # CLI 端到端：退出码、报告文件
pytest tests/golden -m golden # 发布门禁：Py2 语料必须可解析并命中规则
python tests/perf/bench_scan.py --files 100  # 墙钟基准 vs 性能预算
```

静态分析与类型检查（CI 强制）：

```bash
ruff check src tests
ruff format --check src tests
mypy src
```

覆盖率门禁在 CI 中分层执行（核心模块覆盖率与整体覆盖率），本地运行：

```bash
pytest tests --cov=lang_fossil --cov-report=term-missing
```

golden 语料即兼容性契约：任何使快照期望命中发生偏移的改动都属有意的发布决策，必须按此评审。

## 扩展与维护建议

**新增规则。** 在 `src/lang_fossil/rules/builtin/<lang>/`（或经 `RuleRegistry.load_from_dir` 加载的自定义目录）编写 YAML 规则，遵循 `docs/rules-guide.md` 的 schema；在同包的 `samples/samples.yaml` 添加正/反例，并运行注册表与 golden 测试。规则 id 必须匹配 `^[A-Z]{2,4}\d{3}$` 且携带 `provenance`。

**记录一次标准库移除。** 在唯一权威清单 `scripts/deprecation-sources.yaml`
添加条目（模块级，或带*单段*属性名的属性级；可附官方 `ref_url`），再运行
`python scripts/sync_deprecations.py write`——脚本重新生成双份快照并递增
`snapshot_version`（扫描缓存键已包含该版本，旧结果自动失效）；
`... check` 可校验双份永不漂移（CI 友好）。

**支持新语言。** 在 `src/lang_fossil/core/language.py` 的单一注册表追加扩展名（歧义扩展名一律通过配置策略解析，**不做内容评分**），在 `scanner` 的 `parsers` 表注册解析器，扩展 `RuleSpec.language` 字面量，并在 `rules/builtin/<language>/` 编写规则包——每条规则声明 `category`（fossil 规则另附 `deprecated_in`/`removed_in`）。正则/启发式前端（通用 `HeuristicParser`）是务实的第一步；需要树匹配的语言可后续接入 AST 前端。

**新增报告格式。** 在 `reporting/` 下新增模块，以规范 JSON 文档为事实源，并接入 `dig` 的分发逻辑。

**性能。** 以 `tests/perf/bench_scan.py` 追踪回归；单文件扫描预算在毫秒级。克隆检测与僵尸属性遍历的扩展性特征已在代码注释中说明。

**工程纪律。** 保持 ruff/black/mypy-strict 零告警；测试树与 `src/` 镜像；以 golden 语料守护发布门禁；架构级变更以新增 ADR 形式记录于 `docs/adr/`。

---

## License

MIT —— 详见 [LICENSE](LICENSE)。
