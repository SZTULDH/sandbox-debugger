# Sandbox Debugger（面向 Agent 的源码级调试能力）

> 活动产出：本仓库为实战任务中沉淀的通用能力库（非任务本体仓库），定位是**独立、可复用的 Agent 源码级调试能力**，不绑定任何特定项目。

面向 Agent 开放的 **Python 源码级沙盒调试能力**：断点（含条件/命中次数）、单步、
调用栈与局部变量查看、当前栈帧表达式求值、无断点执行轨迹回溯。

把"测试失败"推进到"定位到具体哪一行、哪个变量出错"——尤其适合定位
LLM 生成代码的伪正确样本（逻辑缺陷但恰好通过测试）。

## 能力状态

| 能力 | 状态 | 说明 |
|------|------|------|
| 源码级调试（断点/单步/栈/变量/轨迹） | ✅ 已落地 | `debug_api` + MCP + CLI |
| 一键失败取证 `run_to_error` | ✅ 已落地 | 异常栈 + 崩溃前轨迹 |
| **预装白名单包** | ✅ 已落地 | `requirements-sandbox.txt` + `deps.ALLOWED_PACKAGES` |
| **依赖声明 + 预检** | ✅ 已落地 | `dependencies=[...]` / `check_dependencies` |
| **受限 pip 工具** | ✅ 已落地 | 默认关闭；`SANDBOX_ALLOW_PIP=1` 开启 |
| 每题独立隔离环境（临时 venv / Docker） | ⏳ 未落地 | 当前共用解释器 site-packages |

## 接入方式

1. **MCP Server（推荐）**：`python -m app.sandbox.mcp_server`，在支持 MCP 的
   客户端里配置即可，**17** 个工具开箱可用（含依赖管理）。
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

## 依赖管理（工程场景）· ✅ 已落地

调试能力本身仍为零第三方依赖。若候选代码需要 `numpy` / `pandas` 等，使用已落地的三层能力：

### 运行模型（重要）

- 沙盒与调试子进程使用**当前解释器**的 `site-packages`（`python -I`）。
- **按需 import**，不是每次隔离重装。
- 预装或受限 pip 装进的是环境级依赖，跨多次会话复用。
- 临时目录只放候选代码/协议文件，不装包。

### 1. 预装白名单（推荐）· ✅ 已落地

```bash
pip install -r requirements-sandbox.txt
```

白名单定义在 `app/sandbox/deps.py :: ALLOWED_PACKAGES`（numpy、pandas、scipy、
pyyaml、requests、httpx 等）。

### 2. 依赖声明 + 预检 · ✅ 已落地

题目或调用方可声明 `dependencies`：

```python
D.check_dependencies(["numpy", "pandas"])
# {"ok": true/false, "missing": [...], "not_allowed": [...]}

D.run_to_error(code, entry, args, dependencies=["numpy"])
D.start_session(code, entry, args, dependencies=["numpy"])
```

缺失或不在白名单时返回明确错误，不会静默失败。

### 3. 受限 pip（默认关闭）· ✅ 已落地

```bash
export SANDBOX_ALLOW_PIP=1
```

```python
D.ensure_dependencies(["numpy"])          # 检查，必要时安装
D.install_packages(["numpy==2.0.0"])      # 仅白名单；禁止 URL/git/本地路径
```

对应 MCP / function-calling 工具：

- `sandbox_list_allowed_packages`
- `sandbox_check_dependencies`
- `sandbox_ensure_dependencies`
- `sandbox_install_packages`

## 文件结构

```
app/sandbox/
  tracer.py        帧序列化、安全 repr、行级执行轨迹记录
  _dbgharness.py   常驻调试子进程（sys.settrace + JSON Lines 协议）
  debugger.py      客户端会话（断点/单步/栈/变量/求值/轨迹）
  debug_api.py     Agent 稳定接口 + 工具 JSON Schema 清单
  deps.py          ✅ 依赖白名单、预检、受限 pip
  mcp_server.py    MCP stdio Server（零第三方依赖核心路径）
requirements-sandbox.txt   ✅ 可选预装白名单包
scripts/sandbox_debug.py   交互式 REPL 与一次性取证 CLI
docs/sandbox_debug_api.md  接口文档、能力清单、限制与踩坑记录
SKILL.md                   WorkBuddy 技能定义
```

## 护栏

调试的是 LLM 生成的代码，假设可能死循环：时间预算 `budget`（只统计真正在跑的时间）、
步数护栏 `max_steps`、进程看门狗 600s。命中护栏返回 `status="aborted"`，不会挂死。

依赖安装：默认不联网；开启后仍仅限白名单包名，禁止路径/URL/VCS。

## 限制

仅支持 Python；只跟踪候选代码自身帧；变量值为 `repr` 快照大对象截断；沙盒限制
是"尽力而为"，非安全边界，处理不可信代码应在容器内运行。

## 许可

Apache-2.0
