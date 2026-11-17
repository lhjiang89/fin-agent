# Day 18：评分脚本

`scripts/score_evals.py` 对预先保存的 JSONL 预测评分，不发起模型调用。研究输出每行以 `case_id` 对齐，字段为 `action`、`as_of`、`citations`、`missing_information`，以及题目要求的 `change_percent` 或具体数值；路由输出提供 `route`。缺失预测会计入错误清单，不会悄悄从题目分母中消失；准确率分母是有合法预测的题目数，并同时报告总题数和已评分数。

运行示例：

```sh
.venv/bin/python -m scripts.score_evals --kind routing --predictions evals/routing_predictions.jsonl --split dev
.venv/bin/python -m scripts.score_evals --kind research --predictions evals/research_predictions.jsonl --split holdout
```

没有可用预测时脚本不会伪装成模型实测。可复制题集并把预期标签/字段作为预测，先做评分器自检；再按测试修改一条输出，确认答案通过率、引用通过率、数值通过率或混淆矩阵随之变化。路由报告给出行是真实意图、列是模型预测的混淆矩阵。`propose_simulated_buy` 是意图标签，任何路由分数都不表示已创建或执行交易。

## 固定输出的故障注入结果

自动化断言用完美的合成预测作为基线，然后只改一项或两项：D17-13 错路由后，路由准确率从 30/30 降为 29/30，混淆矩阵对应单元增加 1；D16-01 引用未来日期后，引用通过从 15/15 降为 14/15；D16-04 收盘价改为 999 后，数值通过从 15/15 降为 14/15，整体答案通过降为 13/15。它们验证计分逻辑，不代表 DeepSeek 的真实表现。
