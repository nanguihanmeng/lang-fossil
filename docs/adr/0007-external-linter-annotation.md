# ADR-0007: 外部 linter 输出对接与年代标注

## 状态

已采纳（v0.4.0，批次 2）

## 背景

批次 2 待办："聚合洞察 + 对接 clang-tidy/PMD/eslint 输出（为既有规则附加年代
元标签）"。lang-fossil 的差异化是"考古视角"而非替代既有 linter；内置规则
`provenance` 已声明对现有生态的映射（`ecosystem: eslint (no-var)`），但此前没有
消费方。

设计约束：不引入新依赖（依赖红线 ≤7）；不重新实现外部 linter；标注必须遵守
v0.3.0 语义——**不能对无法断代的构造捏造年代**。

## 决策

1. **lang-fossil 只消费、不运行外部 linter**。新增 `lang_fossil.importers`，
   解析三种稳定的机器格式：eslint JSON、clang-tidy 文本诊断
   （`file:line:col: severity: msg [rule]`，放弃 `-export-fixes` YAML 因其不含
   行号）、PMD XML。输出统一的 `ExternalFinding`（路径规范化为仓库相对 posix）。
2. **双通道标注**（`core/annotate.py`）：
   - *alias*：外部 `(tool, rule_id)` 命中内置规则 provenance 的
     `ecosystem: <tool> (<rule>)` 别名 → 直接附 era/category/provenance；
   - *position*：无别名时，对 finding 所在文件跑内置规则，同行的非 `meta`
     fossil 作为该位置的考古标注（fossil 优先于 unsafe）。
   - 两通道均无信号 → `unannotated`，如实呈现，绝不伪造断代。
3. **新 CLI 命令 `annotate`**：`annotate ROOT REPORT --tool eslint|clang-tidy|pmd`，
   输出 table 或规范 JSON（含 `by_era`/`by_category` 聚合 = "聚合洞察"面）。

## 后果

- XML 解析为 stdlib `xml.etree`，标注 `# noqa: S314`（不拉取外部实体；报告由
  开发者提供，极端实体膨胀仅本地 DoS）。若未来接入不可信来源再引入 defusedxml。
- clang-tidy 大多数检查在既有内置规则中无别名，多数 finding 为 position 标注或
  unannotated——正确且诚实。
- 规则 schema 不新增字段；内置规则无需为对接改动（provenance 已是别名载体）。
