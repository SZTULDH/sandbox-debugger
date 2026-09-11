# 题目 JSON 约定（函数级 / 类级）

评测入口：`app.sandbox.runner.run_suite` / `run_problem`。

## 公共字段

| 字段 | 说明 |
|------|------|
| `id` | 题目 id |
| `kind` | `function`（默认）或 `class` |
| `entry_point` | 函数名；类级为**默认方法名** |
| `public_tests` / `adversarial_tests` | 用例列表 |
| `dependencies` | 可选，依赖白名单声明 |

## 函数级 (`kind: function`)

```json
{
  "kind": "function",
  "entry_point": "deep_merge",
  "public_tests": [
    { "args": [{ "a": 1 }, { "b": 2 }], "expected": { "a": 1, "b": 2 } }
  ]
}
```

## 类级 (`kind: class`)

```json
{
  "kind": "class",
  "class_name": "RateLimiter",
  "entry_point": "allow",
  "init_args": [2, 10.0],
  "init_kwargs": {},
  "public_tests": [
    { "method": "allow", "args": ["u1", 1.0], "expected": true },
    { "method": "allow", "args": ["u1", 2.0], "expected": true },
    { "method": "allow", "args": ["u1", 3.0], "expected": false },
    { "method": "allow", "args": ["u2", 3.0], "expected": true }
  ],
  "adversarial_tests": [
    { "reset": true, "method": "allow", "args": ["u", 0.0], "expected": true },
    { "method": "allow", "args": ["u", 100.0], "expected": true }
  ]
}
```

### 类级语义

- 套件内**默认共用一个实例**（适合状态机、限流、会话）。
- 单测 `method` 缺省时用 `entry_point`。
- `reset: true`：该用例前重新构造实例。
- `init_args` / `init_kwargs`：构造参数。

## 目录建议（主项目题集）

```
datasets/code/
  algo/                 # 算法/编程题（函数）
  engineering/
    function/           # 工程·函数
    class/              # 工程·类
```
