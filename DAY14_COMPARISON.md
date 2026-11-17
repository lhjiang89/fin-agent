# Day 14 任务 3：手写循环与 LangGraph 对照

对照对象是 [run_agent](fin_agent/tool_round.py) 和 [run_graph_agent](fin_agent/graph_agent.py)。两者接收相同的模型接口、问题、截止日期、工具调用上限、总超时和重试次数，并返回 `RunResult`。

| 关注点 | 手写实现 | LangGraph 实现 |
|---|---|---|
| 状态 | `messages`、`executed` 等局部变量 | `AgentState` 中的 `messages`、`cutoff`、`tool_calls`、`status` 和 `answer` |
| 模型调用 | `while True` 中调用 `model.complete` | `model_node` 调用同一个模型接口并返回状态更新 |
| 路由 | 用 `if` 判断最终回答、工具调用和上限 | `add_conditional_edges` 根据状态在 `model`、`tools` 和 `END` 之间切换 |
| 工具执行 | 循环内逐个执行模型返回的调用 | `tool_node` 逐个执行；节点代码仍由项目编写 |
| 截止日期 | 向 `execute_read_only_tool` 传入外部 `cutoff` | 从图状态取 `cutoff`，传入同一个执行器 |
| 调用 ID | 写入工具结果消息的 `tool_call_id` | 同样写入工具结果消息 |
| 异常与重试 | 显式解析 JSON、处理参数错误和连接类异常 | 节点中实现类似处理，并非由本示例自动提供 |
| 上限和超时 | `max_steps` 计工具调用；线程等待共享总截止时间 | 同样计工具调用和共享截止时间；另设置图的 `recursion_limit` 作为图执行步数限制 |
| 状态持久化 | 当前没有检查点 | 当前图没有配置 checkpointer，因此也不支持重启恢复 |

两者共用 [工具契约和执行器](fin_agent/tool_contracts.py)。模型只能提供允许的 `symbol`；应用负责传入 `cutoff`。执行器再分派到行情或公告函数。实际缓存和 Futu 访问由 [tools.py](fin_agent/tools.py) 完成。

## 一次对照运行

```sh
source .venv/bin/activate
python -m scripts.compare_agents
python -m pytest -q tests/test_graph_agent.py
```

对照脚本使用同一个假模型行为和固定行情，两者均返回 `completed`、一次工具调用和“已读取腾讯行情”。图测试的 `test_graph_and_manual_produce_same_transcript` 进一步对两个工具调用和最终回答比较完整 `RunResult`。本次运行图测试为 4 passed。

这只说明测试覆盖的输入下结果一致，不能据此断定两种实现对所有故障、超时或多工具并发都完全一致。二者当前都逐个执行工具；超时后后台线程可能短暂继续。Futu 返回的 `RuntimeError` 尚未统一分类重试。图版本使用 LangGraph 0.2.76 以兼容项目当前 Python 3.9。

## 面试回答

> 我先手写了模型、工具和消息回填循环，再用 LangGraph 的状态、节点和条件边实现相同任务。两者复用同一个 Futu 工具执行器，由程序注入截止日期，保证框架切换不会让模型自行扩大时间范围。手写版适合解释循环细节；图版本把流程和状态显式化，为后续引入审批和检查点提供结构。当前版本还没有配置持久化，订单幂等和账本事务也需要业务系统实现。
