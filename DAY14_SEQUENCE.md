# Day 14：Fin-Agent 工具调用时序图

以下对应 `python -m scripts.run_agent --engine manual`。示例用户要求查询腾讯行情和公告，并指定 `--as-of`。

```mermaid
sequenceDiagram
    actor User as 用户
    participant CLI as CLI 入口
    participant Loop as Agent 循环
    participant Model as DeepSeek
    participant Exec as 工具执行器
    participant Cache as 本地缓存
    participant Futu as Futu OpenD

    User->>CLI: 提交问题和 as-of 截止日期
    alt 未识别腾讯标的
        CLI-->>User: 请求明确标的并保存 trace
    else 已识别标的
        CLI->>Loop: 传入问题和 cutoff
        Loop->>Model: 问题、历史消息、工具名称和参数 schema
        Model-->>Loop: tool_calls（名称、JSON 参数、调用 ID）
        loop 逐个执行工具调用，直到达到调用次数上限
            Loop->>Exec: 工具名称、模型参数、用户 cutoff
            Note over Exec: 校验工具名、symbol 和日期<br/>cutoff 由程序注入，不由模型决定
            alt 行情工具
                Exec->>Cache: 查询指定标的及截止日前的日线
                alt 缓存未覆盖截止日，或查询当天
                    Exec->>Futu: 请求截至 cutoff 的历史日线
                    Futu-->>Exec: 行情结果或错误
                    Exec->>Cache: 有结果时更新缓存
                else 缓存命中
                    Cache-->>Exec: 可见行情
                end
            else 公告工具
                Exec->>Cache: 查询指定标的及截止日前的公告
                alt 无匹配缓存
                    Exec->>Futu: 搜索公告并按关联标的筛选
                    Futu-->>Exec: 公告标题、日期、来源、链接
                    Exec->>Cache: 有结果时更新缓存
                else 缓存命中
                    Cache-->>Exec: 可见公告
                end
            end
            Exec-->>Loop: 工具结果或可处理的错误
            Note over Loop: 工具结果消息携带原 tool_call_id
        end
        Loop->>Model: 原问题、工具调用和带 ID 的工具结果
        alt 模型继续调用工具
            Model-->>Loop: 新的 tool_calls，继续循环
        else 模型返回最终回答
            Model-->>Loop: 最终文本
            Loop-->>CLI: 回答、状态、消息轨迹、调用次数
            CLI->>CLI: 保存独立 trace 文件
            CLI-->>User: 展示回答和 trace 路径
        end
    end
```

`call_id` 由模型接口返回。Agent 在工具结果消息中使用 `tool_call_id` 原样回传，日志也使用该 ID，因此可以将工具请求与结果对应起来。模型可能一次返回多个工具调用；当前手写循环逐个处理，所有调用共享上限和总超时。

上图是正常流程的概览。参数错误会作为工具错误消息返回模型，连接类错误按重试预算处理，达到上限或总超时会结束运行。超时无法强制终止已在后台运行的线程。公告搜索可能不完整，返回的发布时间目前只有日期精度；当天日线可能尚未收盘。

对照代码：[CLI 入口](scripts/run_agent.py)、[DeepSeek 适配器](fin_agent/deepseek_agent.py)、[手写循环](fin_agent/tool_round.py)、[工具契约](fin_agent/tool_contracts.py)、[Futu 查询](fin_agent/tools.py)。

任务 2 的真实轨迹复盘见 [DAY14_TRACE_ANALYSIS.md](DAY14_TRACE_ANALYSIS.md)。
