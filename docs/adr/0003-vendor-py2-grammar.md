# ADR-0003: vendor Python 2.7 语法文件（修正 ADR-0001 的事实前提）

## 状态

已采纳（M0 PoC 实测修订）

## 背景

工程规范附录 C 断言"parso 包内置 grammar2.7.txt"。M0 PoC（Py2 黄金语料）
实测发现该前提**已过时**：

- parso ≥ 0.8.2 的发行包不再包含任何 Python 2 语法文件
  （`parso/python/` 仅有 grammar36+）；
- `parso.load_grammar(version="2.7")` 在 0.8.2+ 直接抛出
  `NotImplementedError: Python version 2.7 is currently not supported`；
- 0.7.1 是最后一个携带 `grammar27.txt` 的版本。

若不处理，规范 §4.2 的 golden 门禁（纯 Py2 语料必须可解析）从第一个
commit 起就会是红的——批评者 #1 的"CI 必红"预言以另一种形式成立。

## 决策

1. 将 parso v0.7.1 的 `grammar27.txt`（MIT 许可）vendor 进本包
   `src/lang_fossil/parsers/grammars/grammar27.txt`；
2. Py2 解析走 `parso.load_grammar(path=...)` 加载 vendored 文件，
   与已安装 parso 的版本解耦（实测 0.8.x 解析器兼容该语法文件）；
3. `_load_default_grammar()` 增加兜底：解释器版本超出 parso 内置
   语法（如 3.14 vs 最高 grammar312）时，回退到可用的最高语法版本；
4. 唯一已知盲区：`ur''` 前缀连 2.7 语法也无法 token 化——PF002 规则
   降级为启发式正则（`match_mode: heuristic`），黄金语料中该构造
   由 mixed_era_repo 的正则命中覆盖。

## 后果

- 运行时依赖 `parso>=0.8` 保持不变（vendored 文件随包分发）；
- golden 门禁实际钉死了该能力：`tests/golden` 每次回归都会验证
  Py2 语料在 Py3 解释器上的解析；
- mypy 目标版本从规范标注的 3.9 上调至 3.10（mypy ≥1.19 已放弃
  3.9 target）；运行时矩阵 3.9–3.13 不受影响（代码仍以 3.9 语法
  兼容编写，ruff/black target 仍为 py39）。

## 上游维护风险与降级路径（2026-09-08 补记）

parso 的发布节奏缓慢（0.8.4 为最近版本，2026 年回看已超一年），且无
跟进新 CPython 语法的官方承诺。风险敞口与缓解措施明确如下：

- **不受影响的能力**：Py2 语料解析（依赖 vendored `grammar27.txt` +
  parso 解析器内核，均极稳定）；
- **受影响的能力**：新 CPython 语法（3.13+ 特性）的树级解析——若 parso
  语法文件落后，这些文件会带 `ParseResult.errors` 降级；
- **既有降级链**（degrade-never-abort）：`_load_default_grammar()` 超出
  内置语法时回退最高可用语法 → 解析异常捕获为 errors → heuristic 规则
  在无树时仍逐行匹配 → 僵尸检测对 `tree=None` 返回空；
- **版本约束**：`pyproject.toml` 对 parso 声明 `>=0.8,<0.10` 上限，
  未知的 0.9/0.10 行为变化不进入解析矩阵；
- **监控**：golden 门禁 + 全量测试在 CI 矩阵（3.9–3.13）上持续验证；
  parso 长期停更时的升级路径是评估 vendoring 更多语法文件或切换解析
  内核（届时单独立 ADR）。
