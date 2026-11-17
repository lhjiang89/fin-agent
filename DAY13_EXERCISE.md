# Day 13：手写工具调用循环

目标是在 30 分钟内，从空文件实现一次有限的模型与工具交互。已完成的项目实现可以在练习结束后对照 `fin_agent/tool_round.py`。

## 题目

实现 `run(model, execute, question, cutoff, max_steps)`。`model.complete(messages, tools)` 返回一个 assistant 字典，可能包含 `content` 或 `tool_calls`。每个工具调用具有 `id`、`function.name` 和 JSON 字符串 `function.arguments`。`execute(name, arguments, cutoff)` 返回可 JSON 序列化的结果。

要求模型收到工具结果时，消息的 `tool_call_id` 与请求中的 `id` 一致。每执行一次工具增加计数。模型一直发起调用时，在达到 `max_steps` 后返回 `max_steps` 状态，不执行超出预算的调用；模型给出最终文本时返回 `completed` 状态。

## 自测场景

1. 模型依次请求行情、公告，最后回答。检查执行顺序、两个调用 ID 和最终文本。
2. 工具每次都成功，但模型一直请求行情。设置 `max_steps=2`，检查工具执行两次后退出，状态为 `max_steps`。
3. 模型第一次就回答。检查工具执行零次，状态为 `completed`。
4. 模型一次返回两个工具调用，而剩余预算只有一次。检查第二个工具没有执行。

先在纸上或独立文件完成，再运行项目中的已有测试作为参考：

```sh
.venv/bin/python -m pytest -q tests/test_tool_round.py
```

## 复盘

- 模型是否真正执行函数？程序在哪一步验证参数？
- 为什么工具结果要携带原始调用 ID？
- 达到上限时，如何让用户知道任务没有完成？
- 总超时与单次请求超时有什么区别？线程超时后，已经开始的操作是否真的停止？

手写完成后，再对照 `fin_agent/graph_agent.py` 中的状态、节点和条件边。真实 DeepSeek 请求示例和手写/图版本运行方式见 `README.md`。不要把本练习的假数据结果写成真实行情。
