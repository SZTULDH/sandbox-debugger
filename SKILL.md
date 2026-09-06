---
name: sandbox-debugger
description: >-
  对沙盒中运行的 Python 代码进行源码级调试：下断点（支持条件/命中次数）、单步、
  查看调用栈与局部变量、在当前栈帧求值表达式、无断点事后回溯执行轨迹。
  当 Agent 或自动化流水线需要把"测试失败"推进到"定位到具体哪一行、哪个变量出错"
  时使用——尤其是调试 LLM 生成的代码、定位伪正确样本的逻辑缺陷。
---

# Sandbox Debugger

> 活动产出：本技能为实战任务中沉淀的通用调试能力，作为**独立、可复用的 Agent 调试技能**，不绑定任何特定项目。

给 Agent 开放的标准沙盒调试能力。底层用 `sys.settrace` 跟踪候选 Python 代码的
执行，提供断点、单步、栈/变量查看、表达式求值与执行轨迹回溯。

能力边界：仅支持 Python；只跟踪候选代码自身的帧，不进入标准库/第三方库内部。

## 何时使用

- 候选代码在公开测试通过、对抗测试失败，需要找出**具体出错行与变量**
- 需要观察某个边界输入下变量如何偏离预期
- 复现并取证一个崩溃（异常栈 + 崩溃前最后若干步轨迹）

## 如何接入（三种方式）

### A. MCP Server（推荐，任意支持 MCP 的 Agent 可直连）

```bash
python -m app.sandbox.mcp_server
```

客户端配置：

```json
{
  "mcpServers": {
    "sandbox-debug": {
      "command": "<python>",
      "args": ["-m", "app.sandbox.mcp_server"],
      "cwd": "<本仓库根目录>"
    }
  }
}
```

工具清单（13 个）：`sandbox_start_session` / `sandbox_set_breakpoint` /
`sandbox_continue` / `sandbox_step_over` / `sandbox_step_into` / `sandbox_step_out` /
`sandbox_get_stack` / `sandbox_get_locals` / `sandbox_evaluate` / `sandbox_get_trace` /
`sandbox_get_state` / `sandbox_run_to_error` / `sandbox_close_session`

### B. Python API（`app/sandbox/debug_api.py`）

所有函数返回可 JSON 序列化的 dict，不抛异常，错误统一为 `{"ok": false, "error": "..."}`。

```python
from app.sandbox import debug_api as D
r = D.start_session(code, "two_sum", [[2, 7, 11, 15], 9])
sid = r["session_id"]
D.set_breakpoint(sid, line=6, condition="i == 0 and j == 1")
ev = D.continue_(sid)["event"]          # 停靠快照 / 退出事件
D.get_locals(sid)                        # 当前帧局部变量
D.evaluate(sid, "nums[i] + nums[j]")      # 在当前栈帧求值
D.get_trace(sid, limit=50)               # 最近 N 步执行轨迹（无需断点）
D.close_session(sid)
```

一键取证：

```python
out = D.run_to_error(code, "two_sum", [[2, 7, 11, 15], 9])
# out: status / result / error / traceback / steps / trace_tail / stdout
```

### C. CLI（`scripts/sandbox_debug.py`）

```bash
python scripts/sandbox_debug.py --problem datasets/code/x.json --args '"abba"'
python scripts/sandbox_debug.py --problem datasets/code/x.json --run --trace 60
```

REPL 命令：`b <行> [条件]` · `c/n/s/r`（继续/跳过/进入/跳出）· `p <表达式>` ·
`l`（变量）· `bt`（栈）· `t [n]`（轨迹）· `o`（输出）· `q`（退出）。

## 典型用法示例

定位 `length_of_longest_substring("abba")` 返回 3（应为 2）：

```python
code, entry, args = ...              # 取出候选代码、入口、失败输入
out = D.run_to_error(code, entry, args)
# status=returned, result=3, trace_tail 显示第 8 行 if ch in seen 命中后
# left 只 +1 而没有收缩到重复字符之后 —— 错误定位到具体行与变量
```

## 护栏（务必知晓）

调试的是 LLM 生成的代码，假设它可能死循环：

- **时间预算** `budget`：只统计真正在跑的时间，断点处思考多久不计入
- **步数护栏** `max_steps`：先撞哪个算哪个
- **进程看门狗** 600s 硬上限
- 命中护栏返回 `status="aborted"`，不会挂死

## 限制

- 仅 Python；行级源码调试，非字节码级
- 变量值为 `repr` 快照，大对象截断
- `evaluate` 的语句模式在副本上执行，不会真正修改被调程序的变量
- 沙盒限制是"尽力而为"（禁用 open/eval/exec 与危险模块），**非安全边界**；
  处理不可信代码应在容器内运行

## 协议（供扩展）

`debugger.py` 拉起 `_dbgharness.py` 子进程，stdin/stdout 各一行一个 JSON：

```
请求  {"id": 1, "cmd": "continue", "args": {}}
响应  {"id": 1, "ok": true, "result": {...}}
事件  {"event": "stopped"|"exited", ...}
```

详细文档见 `docs/sandbox_debug_api.md`。
