# Sandbox Debugger（面向 Agent 的源码级调试能力）

> 活动产出：本仓库为实战任务中沉淀的通用能力库（非任务本体仓库），定位是**独立、可复用的 Agent 源码级调试能力**，不绑定任何特定项目。

面向 Agent 开放的 **Python 源码级沙盒调试能力**：断点（含条件/命中次数）、单步、
调用栈与局部变量查看、当前栈帧表达式求值、无断点执行轨迹回溯。

把"测试失败"推进到"定位到具体哪一行、哪个变量出错"——尤其适合定位
LLM 生成代码的伪正确样本（逻辑缺陷但恰好通过测试）。

## 接入方式

1. **MCP Server（推荐）**：`python -m app.sandbox.mcp_server`，17 个工具（含依赖管理）。
2. **Python API**：`from app.sandbox import debug_api as D`，返回可 JSON 序列化的 dict，不抛异常。
3. **CLI**：`python scripts/sandbox_debug.py --problem ... --run --trace 60`。

## 快速开始

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

一键取证：

```python
out = D.run_to_error(code, "two_sum", [[2, 7, 11, 15], 9])
# status / result / error / traceback / steps / trace_tail / stdout
```

## 依赖管理

核心调试路径仍为零第三方依赖。工程场景需要第三方库时：

```bash
# 预装白名单（推荐）
pip install -r requirements-sandbox.txt
```

```python
# 题目/调用方声明依赖并预检
D.check_dependencies(["numpy", "pandas"])
D.run_to_error(code, entry, args, dependencies=["numpy"])

# 受限安装（默认关闭）
# export SANDBOX_ALLOW_PIP=1
D.ensure_dependencies(["numpy"])
D.install_packages(["numpy==2.0.0"])  # 仅白名单；禁止 URL/git/本地路径
```

白名单见 `app/sandbox/deps.py`。子进程共用当前解释器的 `site-packages`（按需 import，不每次重装）。

## 文件结构

```
app/sandbox/
  tracer.py / _dbgharness.py / debugger.py
  debug_api.py     Agent 接口 + MCP 工具清单
  deps.py          依赖白名单、预检、受限 pip
  mcp_server.py    MCP stdio Server
requirements-sandbox.txt
scripts/sandbox_debug.py
docs/sandbox_debug_api.md
SKILL.md
```

## 护栏与限制

- 时间预算 `budget`、步数 `max_steps`、进程看门狗 600s；命中返回 `aborted`。
- 仅 Python；只跟踪候选代码帧；变量为 `repr` 快照。
- 沙盒限制是尽力而为，非安全边界；不可信代码请放容器内运行。
- 依赖安装默认不联网；开启后仍限白名单包名。

## 许可

Apache-2.0
