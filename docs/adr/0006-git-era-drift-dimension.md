# ADR-0006: Git 年代错位维度（era drift）

## 状态

已采纳（v0.4.0，批次 3）

## 背景

`core/enricher.py` 已实现 git 碳测年（每文件最近提交年）并有单测，但从未接入
CLI/报告层。批次 2–4 待办将"风格谱系 vs Git 最近提交年"的年代错位维度列为单独
交付——风格 era 说明代码像哪个时代写的，git 说明它最近是否仍被维护，二者的
对照才是考古学意义上的"活体遗留"洞察。

约束：git 富化按既有评审结论保持**默认关闭**（`settings.git.enabled = False`）；
报告与缓存格式需向后兼容。

## 决策

1. **Fossil 携带年份而非文件表**：`Fossil` 增加可选 `last_commit_year: int | None`
   （带默认值，置于字段末尾）——旧缓存载荷（缺该键）反序列化不受影响。
2. **扫描后单次富化**：`scan()` 提取完成后调用 `enrich_commit_years()` 一次，
   将年份按 `path` 回填到化石。年份与文件内容无关，**不参与缓存 key**；缓存命中
   路径同样回填，语义一致。
3. **活跃遗留指标**：聚合层新增 `git_dated_fossils`（带年份的化石数）与
   `active_fossils`（文件最近提交年 ≥ 当前年 − 2 的 fossil-era 化石，`meta`/`unsafe`
   除外）。窗口固定为 2 年常量并标注 ponytail 上限。
4. **呈现**：JSON `summary`、HTML 指标卡与 fossils 表、CLI `dig` 摘要行呈现该
   维度；默认关闭时不产生额外提示。

## 后果

- 默认零开销：git 未启用时路径无额外子进程、字段恒为 `None`。
- 未解决：squash 提交不可靠性的处理（`GitSettings.treat_squash_as_unreliable`
  字段保留，`git log` 测年不受影响，后续如需逐行 blame 时启用）。
- 相关：批次 2 的 `annotate` 复用同一 `Fossil` 模型，无 schema 冲突。
