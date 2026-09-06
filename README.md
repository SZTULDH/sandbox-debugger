# Sandbox Debugger（面向 Agent 的源码级调试能力）

> 活动产出：本仓库为实战任务中沉淀的通用能力库（非任务本体仓库），定位是**独立、可复用的 Agent 源码级调试能力**，不绑定任何特定项目。

面向 Agent 开放的 **Python 源码级沙盒调试能力**：断点（含条件/命中次数）、单步、
调用栈与局部变量查看、当前栈帧表达式求值、无断点执行轨迹回溯。

把"测试失败"推进到"定位到具体哪一行、哪个变量出错"——尤其适合定位
LLM 生成代码的伪正确样本（逻辑缺陷但恰好通过测试）。

## 接入方式

1. **MCP Server（推荐）**：`python -m app.sandbox.mcp_server`，在支持 MCP 的
   客户端里配置即可，13 个工具开箱可用。
2. **Python API**：`from app.sandbox import debug_api as D`，所有函数返回
   可 JSON 序列化的 dict，不抛异常。
3. **CLI**：`python scripts/sandbox_debug.py --problem ... --run --trace 60`。

## 快速开始（Python API）

```python
from app.sandbox import debug_api as D
r = D.start_session(code, "two_sum", [[2, 7, 11, 15], 9])
sid = r["session_id"]
D.set_breakpoint(sid, line=6, condition="i == 0 and j == 1")
ev = D.continue_(sid)["event"]
D.get_locals(sid)
D.evaluate(sid, "nums[i] + nums[j]")
D.get_trace(sid, limit=50)
D.close_session(sid)
```

一键取证（无断点）：

```python
out = D.run_to_error(code, "two_sum", [[2, 7, 11, 15], 9])
# status / result / error / traceback / steps / trace_tail / stdout
```

## 文件结构

```
app/sandbox/
  tracer.py        帧序列化、安全 repr、行级执行轨迹记录
  _dbgharness.py   常驻调试子进程（sys.settrace + JSON Lines 协议）
  debugger.py      客户端会话（断点/单步/栈/变量/求值/轨迹）
  debug_api.py     Agent 稳定接口 + 工具 JSON Schema 清单
  mcp_server.py    MCP stdio Server（零第三方依赖，13 个工具）
scripts/sandbox_debug.py   交互式 REPL 与一次性取证 CLI
docs/sandbox_debug_api.md  接口文档、能力清单、限制与踩坑记录
SKILL.md                   WorkBuddy 技能定义
```

## 护栏

调试的是 LLM 生成的代码，假设可能死循环：时间预算 `budget`（只统计真正在跑的时间）、
步数护栏 `max_steps`、进程看门狗 600s。命中护栏返回 `status="aborted"`，不会挂死。

## 限制

仅支持 Python；只跟踪候选代码自身帧；变量值为 `repr` 快照大对象截断；沙盒限制
是"尽力而为"，非安全边界，处理不可信代码应在容器内运行。

## 许可

Apache-2.0
