# ADR-0001: 采用 parso 作为多语法版本 Python 前端

## 状态

已采纳（评审裁决 #1）

## 背景

工具需要解析横跨多个语言时代的代码：Python 2 语法（print 语句、
`raise E, msg`、backtick repr）在标准库 `ast` 下直接 SyntaxError；
`lib2to3` 已在 Python 3.13 彻底移除。

## 决策

采用 parso 作为主力解析前端：

1. parso 内置 `grammar2.7.txt` 等历史语法文件，可在 Py3 解释器上
   解析 Py2 语料（`parso.load_grammar(version="2.7")`）。
2. 策略：先用解释器默认语法解析；报告语法错误且源码含 Py2 特征时，
   用 2.7 语法重试，取错误更少的结果。
3. 早于 2.7 的极老语法不在 parso 支持范围，走正则启发式
   （规则显式标注 `match_mode: heuristic`）。
4. 标准库 `ast` 保留为现代语法快路径（clone 指纹、名称提取）。

## 后果

- M0 PoC 与发布门禁：纯 Py2 黄金语料必须解析并命中快照规则集
  （`tests/golden/corpus/py2_syntax_repo`）。
- 引擎匹配基于 parso 树（节点/叶类型与 stdlib ast 不同），规则作者
  需参照 `docs/rules-guide.md`。
