# Sandbox Debugger（面向 Agent 的源码级调试与评测执行）

> 活动产出：本仓库为实战任务中沉淀的通用能力库（非任务本体仓库），定位是**独立、可复用的 Agent 沙盒能力**，不绑定任何特定项目。

提供两类能力：

1. **源码级调试**：断点、单步、栈/变量、求值、轨迹回溯  
2. **评测执行**：函数级 / 类级测试套件（`runner` + `_harness`）

## 接入方式

1. **MCP Server（推荐）**：`python -m app.sandbox.mcp_server`  
2. **调试 API**：`from app.sandbox import debug_api as D`  
3. **评测 API**：`from app.sandbox.runner import run_suite, run_problem`  
4. **CLI**：`python scripts/sandbox_debug.py --problem ... --run --trace 60`

## 评测执行（函数 / 类）

```python
from app.sandbox.runner import run_suite, run_problem

# 函数级
run_suite(code, "deep_merge", tests, kind="function")

# 类级：同实例顺序调 method；单测可 reset=true
run_suite(
    code,
    entry_point="allow",
    tests=[{"method": "allow", "args": ["u", 1.0], "expected": True}],
    kind="class",
    class_name="RateLimiter",
    init_args=[2, 10.0],
)
```

题目约定见 `docs/problem_schema.md`，类级样例见 `examples/class_rate_limiter.json`。

## 调试快速开始

### 函数级（模块级函数）

```python
from app.sandbox import debug_api as D
r = D.start_session(code, "two_sum", [[2, 7, 11, 15], 9])
sid = r["session_id"]
D.set_breakpoint(sid, line=6, condition="i == 0 and j == 1")
ev = D.continue_(sid)["event"]
D.get_locals(sid)
D.close_session(sid)
```

### 类方法（新）

调试入口现在支持三种写法（任选一）：

1. **点号形式**：`entry_point="Class.method"`
2. **显式字段**：`entry_point="method", class_name="Class"`
3. **配合构造参数**：`init_args` / `init_kwargs`

```python
# 方式 1：点号形式
r = D.start_session(
    code,
    "RateLimiter.allow",
    ["u", 1.0],
    init_args=[2, 10.0],
)

# 方式 2：显式 class_name + method
r = D.start_session(
    code,
    "allow",
    ["u", 1.0],
    class_name="RateLimiter",
    init_args=[2, 10.0],
)

# 一键取证同样支持
out = D.run_to_error(
    code,
    "RateLimiter.allow",
    ["u", 1.0],
    init_args=[2, 10.0],
)
```

CLI 同样支持：

```bash
python scripts/sandbox_debug.py \
  --code-file demo.py \
  --entry RateLimiter.allow \
  --init-args 2 10.0 \
  --args '"u"' 1.0

# 或从题集自动识别 kind=class
python scripts/sandbox_debug.py --problem examples/class_rate_limiter.json --run --trace 60
```

## 依赖管理

```bash
pip install -r requirements-sandbox.txt   # 预装白名单（可选）
# export SANDBOX_ALLOW_PIP=1              # 开启受限 pip（可选）
```

白名单与预检见 `app/sandbox/deps.py`。子进程共用当前解释器 site-packages。

## 文件结构

```
app/sandbox/
  runner.py / _harness.py   评测执行（function | class）
  debugger.py / _dbgharness.py / tracer.py / debug_api.py
  deps.py / mcp_server.py
docs/problem_schema.md
docs/sandbox_debug_api.md
examples/class_rate_limiter.json
```

## 护栏与限制

- 调试：`budget` / `max_steps` / 看门狗；评测：逐用例 timeout + 套件预算  
- 沙盒限制尽力而为，非安全边界  
- 仅 Python

## 许可

Apache-2.0
