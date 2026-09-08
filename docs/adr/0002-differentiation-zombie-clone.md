# ADR-0002: 差异化能力定位（僵尸 API 与 Code Clone）

## 状态

已采纳（评审裁决 #5，"最有价值的批评"）

## 背景

v1.0 MVP 本质是"lint 规则打包器 + HTML 展示器"，护城河不足：
所有规则均可被 ruff/eslint/pyscn 替代。

## 决策

重定义差异化能力：

1. **僵尸 API 检测（P0）**：数据驱动检测已从标准库移除的 API
   （distutils、imp、`asyncio.get_event_loop` 语义移除等）。
   lint 生态的 UP 规则只管"可升级"，不管"已死亡"。数据以
   离线快照随包分发，零网络访问。
2. **Code Clone 检测（P1）**：winnowing 指纹检测跨文件复制粘贴的
   上古代码——"同一块化石出现在三个地层"，与考古隐喻天然契合。
3. 地层数据模型（era × 时间 × 模块聚合面）本身是可复用资产。

## 后果

- `core/zombie_api.py`、`core/clone.py` 为核心模块，受 90% 覆盖率
  门禁约束。
- 僵尸 API 数据冷启动：快照由人工维护、随版本发布；PRD 的
  "借力 lint 生态"体现在规则 provenance 标注与黄金语料映射。
