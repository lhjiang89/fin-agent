# Fin-Agent

Day 1 实现了股票研究 CLI 的入口。当前开发环境使用 Python 3.9.6。

首次在项目根目录运行：

~~~sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install pytest pydantic
~~~

每次打开新终端，在项目根目录运行：

~~~sh
source .venv/bin/activate
python -m fin_agent --symbol DEMO
~~~

预期输出为 DEMO。运行 python -m fin_agent --help 可以查看参数说明。

Day 2–4 使用本地 Futu OpenD 和 Python SDK 获取腾讯港股 `HK.00700` 的日线数据。Futu OpenD 默认连接 `127.0.0.1:11111`，获取结果先保存原始 JSON，再转换成 Fin-Agent 的统一行情结构。

确保 Futu OpenD 已启动后运行：

~~~sh
source .venv/bin/activate
python -m pip install futu-api
python -m pip install openai
python -m scripts.fetch_tencent_daily --symbol HK.00700 --count 30
python -m pytest -q
~~~

生成文件为 `fixtures/tencent_daily.raw.json` 和 `fixtures/tencent_daily.json`。历史 K 线的日期、复权方式和账户权限会影响结果，回答时需要保存这些元数据。

Day 5–7 使用 DeepSeek 的 OpenAI 兼容接口。默认模型为 `deepseek-flash`。运行前确保当前 shell 能看到 `DEEPSEEK_API_KEY`：

~~~sh
export DEEPSEEK_API_KEY='你的密钥'
python -m fin_agent --live --symbol HK.00700 --question '最近两个交易日涨跌幅是多少？'
~~~

CLI 会先按 `--as-of` 过滤可见行情，再让模型输出 JSON，最后由 Pydantic 和程序复算涨跌幅。模型输出不能引用截止日期之后的行情。

每次完成、模型调用失败或因数据覆盖不足跳过模型时，CLI 会在 `runs/` 下以唯一运行 ID 保存一份 JSON 记录，并打印其路径。已有的 `runs/last_run.json` 会保留。

对照手写 Agent 循环和 LangGraph 实现：

~~~sh
python -m pip install -r requirements.txt
python -m scripts.compare_agents
python -m pytest -q
~~~

对照脚本使用固定假模型和行情，不需要 API key 或 OpenD。手写版入口是 `fin_agent.tool_round.run_agent`，图版本入口是 `fin_agent.graph_agent.run_graph_agent`。图版本的 `AgentState` 保存状态，`model` 和 `tools` 节点分别对应模型调用和工具执行，条件边决定循环或结束。两个版本都复用 `execute_read_only_tool`，由程序注入截止日期。

运行真实 DeepSeek 工具调用（需要 OpenD 和 DEEPSEEK_API_KEY）：

~~~sh
python -m scripts.run_agent --engine manual --as-of 2026-11-13 --question '查询腾讯的日线行情'
python -m scripts.run_agent --engine graph --as-of 2026-11-13 --question '查询腾讯的公告'
~~~

工具调用轨迹保存到 `runs/`，包含问题和工具结果；请求和响应打印到 stderr。
# fin-agent
