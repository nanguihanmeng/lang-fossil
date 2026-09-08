# ADR-0008: 废弃/移除数据化与官方源同步管线

## 状态

已采纳（v0.4.0，批次 4）

## 背景

僵尸 API 快照（`dead-packages.json`）此前是"人工维护 + 双份拷贝"
（`data/` 与 `src/lang_fossil/data/`），易漂移、无来源追溯；每轮 CPython 发版都
需手工同步。批次 4 待办："规则/废弃 API 数据化 + 官方源同步脚本（保持运行时
offline-first，由维护流程产出版本化快照）"。

约束：运行时保持离线（只读 JSON）；既有 25 条人工精修数据（含 replacement
建议）**不得因生成而回退**；不新增运行时依赖。

## 决策

1. **单一权威清单**：`scripts/deprecation-sources.yaml` 成为条目与来源的唯一
   curate 入口（模块/属性、`removed_in`、`removal`、`replacement` 保持人工维护
   质量）。生成的 JSON 禁止手改。
2. **版本化快照 schema**：JSON 顶层增加 `schema_version`、`sources`
   （`name`/`url`/`version`）与 `snapshot_version` 戳；`packages` 结构不变，
   loader（`offline_db.py`/`ZombieApiDB`）向后兼容。
3. **同步脚本**（`scripts/sync_deprecations.py`，stdlib + safe_load）：
   - `check`：两份快照与清单一致（不联网，可入 CI）；
   - `verify`：逐条抓取可选 `ref_url` 并断言模块/属性 token 出现在官方文档中
     （人工补充 ref_url 的条目才核验，无 ref 明确跳过）；
   - `write`：重渲染双份并 bump `snapshot_version`（默认 `YYYY.MM`）。
4. **规则数据化字段**：`RuleSpec` 增加可选 `source`（官方引用 URL），内置规则
   按需补充，作为规则级来源追溯。

## 后果

- 快照成为"可重生成产物"，双份拷贝由脚本保证一致，`$comment` 改为生成注记。
- 自动生成只负责结构、版本与一致性核验；语义（replacement/removal 分类）继续
  由维护者 curate——保真不降级。
- 每次 CPython 发版后的维护流程收敛为：改 YAML → `verify`（有 ref 时）→
  `write` → 提交。
