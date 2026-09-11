"""沙盒调试器命令行入口。

交互式 REPL（默认）：

    python scripts/sandbox_debug.py --code-file demo.py --entry two_sum --args '[2,7,11,15]' 9

一次性跑到底（适合流水线）：

    python scripts/sandbox_debug.py --problem datasets/code/medium/is_palindrome.json --run

REPL 命令：

    b <行号> [条件]    下断点，如 `b 6 i > 0`
    c / n / s / r      继续 / 单步跳过 / 单步进入 / 跳出
    p <表达式>         在当前栈帧求值
    l                  查看当前帧局部变量
    bt                 查看调用栈
    t [n]              查看最近 n 步执行轨迹
    o                  查看程序 print 输出
    q                  退出
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.sandbox.debug_api import (  # noqa: E402
    call_tool, close_session, continue_, evaluate, get_locals, get_output,
    get_stack, get_trace, run_to_error, set_breakpoint, start_session,
    step_into, step_out, step_over,
)

_CODE_FENCE = re.compile(r"```(?:python)?\s*(.*?)```", re.S)


def load_problem(path: Path) -> tuple[str, str, list, dict | None]:
    """从题集 JSON 取出 (代码, 入口, 默认入参, 类级信息)。

    ``kind == "class"`` 时：入口即默认方法名，默认入参取该用例的 method args，
    另外返回 ``{class_name, init_args, init_kwargs}`` 供构造实例使用。
    函数级题目第四个返回值恒为 None。
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    sol = data.get("mock_solution") or {}
    raw = sol.get("代码实现", "")
    m = _CODE_FENCE.search(raw)
    code = (m.group(1) if m else raw).strip()
    entry = data.get("entry_point")
    first = (data.get("public_tests") or [{}])[0]
    args = first.get("args", [])

    cls = None
    if (data.get("kind") or "function").lower() == "class":
        cls = {
            "class_name": data.get("class_name") or entry,
            "init_args": data.get("init_args") or [],
            "init_kwargs": data.get("init_kwargs") or {},
        }
    return code, entry, args, cls


def parse_args_tokens(tokens: list[str]):
    """把 --args 后面的 token 解析成 Python 对象（JSON 优先）。"""
    out = []
    for tok in tokens:
        try:
            out.append(json.loads(tok))
        except json.JSONDecodeError:
            out.append(tok)
    return out


def show_stop(ev: dict) -> None:
    if ev.get("event") == "exited":
        print(f"\n== 程序结束 ==  status={ev.get('status')} "
              f"result={ev.get('result')} steps={ev.get('steps')}")
        if ev.get("error"):
            print(f"error: {ev['error']}")
            if ev.get("traceback"):
                print(ev["traceback"])
        return
    cur = ev.get("current") or {}
    print(f"\n-- 停在 line {cur.get('line')} ({ev.get('reason')}) --")
    src = (cur.get("source") or "").strip()
    if src:
        print(f"   {src}")
    loc = cur.get("locals") or {}
    if loc:
        print("   locals: " + ", ".join(f"{k}={v}" for k, v in list(loc.items())[:8]))


def repl(sid: str) -> int:
    print("输入 h 查看帮助，q 退出。")
    while True:
        try:
            line = input("(dbg) ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        head, *rest = line.split(maxsplit=1)
        tail = rest[0] if rest else ""
        try:
            if head == "h":
                print(__doc__.split("REPL 命令：")[1].strip())
            elif head == "q":
                break
            elif head == "b":
                parts = tail.split(maxsplit=1)
                if not parts:
                    print("用法: b <行号> [条件]")
                    continue
                r = set_breakpoint(sid, int(parts[0]),
                                   condition=parts[1] if len(parts) > 1 else None)
                print(r)
            elif head == "c":
                show_stop(continue_(sid).get("event", {}))
            elif head == "n":
                show_stop(step_over(sid).get("event", {}))
            elif head == "s":
                show_stop(step_into(sid).get("event", {}))
            elif head == "r":
                show_stop(step_out(sid).get("event", {}))
            elif head == "p":
                r = evaluate(sid, tail)
                print(r.get("result") or r)
            elif head == "l":
                print(get_locals(sid).get("locals"))
            elif head == "bt":
                st = get_stack(sid).get("result") or {}
                for i, fr in enumerate(st.get("stack") or []):
                    print(f"  #{i} line {fr['line']} in {fr['func']}")
            elif head == "t":
                tr = get_trace(sid, int(tail) if tail.isdigit() else 30).get("result") or {}
                for st in tr.get("steps") or []:
                    print(f"  #{st['n']} line {st['line']} {st['func']} {st['locals']}")
                print(f"  (共 {tr.get('total_steps')} 步)")
            elif head == "o":
                print(get_output(sid).get("result"))
            else:
                print(f"未知命令: {head}（输入 h 看帮助）")
        except BaseException as exc:  # noqa: BLE001
            print(f"[error] {type(exc).__name__}: {exc}")
    close_session(sid)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="面向 Agent 的源码级沙盒调试器")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--code-file", help="包含待调试代码的 .py 文件")
    src.add_argument("--problem", help="题集 JSON，调试其中的 mock 解答")
    ap.add_argument("--entry", help="入口函数名；类级时写 'Class.method' 或方法名")
    ap.add_argument("--class-name", help="类级调试：类名")
    ap.add_argument("--init-args", nargs="*", default=[],
                    help="类级调试：构造实例的位置参数（JSON 字面量）")
    ap.add_argument("--args", nargs="*", default=[], help="入口函数入参（JSON 字面量）")
    ap.add_argument("--budget", type=float, default=10.0, help="运行时间预算（秒）")
    ap.add_argument("--run", action="store_true", help="一次性跑到底，不进 REPL")
    ap.add_argument("--trace", type=int, default=0, help="--run 时附带最近 N 步轨迹")
    ns = ap.parse_args()

    if ns.code_file:
        code = Path(ns.code_file).read_text(encoding="utf-8")
        entry = ns.entry
        args = parse_args_tokens(ns.args)
        cls = None
    else:
        code, entry, args, cls = load_problem(Path(ns.problem))
        if ns.args:
            args = parse_args_tokens(ns.args)

    # 命令行显式给了类名/构造参数时以命令行为准
    if ns.class_name:
        cls = dict(cls or {})
        cls["class_name"] = ns.class_name
    if ns.init_args:
        cls = dict(cls or {})
        cls["init_args"] = parse_args_tokens(ns.init_args)

    class_kw = {
        "class_name": (cls or {}).get("class_name"),
        "init_args": (cls or {}).get("init_args"),
        "init_kwargs": (cls or {}).get("init_kwargs"),
    }

    if not entry:
        print("缺少 --entry（或从题集推断失败）", file=sys.stderr)
        return 2

    if ns.run:
        out = run_to_error(code, entry, args, budget=ns.budget,
                           trace_limit=ns.trace or 60, **class_kw)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out.get("status") == "returned" else 1

    r = start_session(code, entry, args, budget=ns.budget, stop_on_entry=True,
                      **class_kw)
    if not r.get("ok"):
        print(f"启动失败: {r.get('error')}", file=sys.stderr)
        return 2
    print(f"会话 {r['session_id']} 已载入 {entry}{args}，停在入口。")
    return repl(r["session_id"])


if __name__ == "__main__":
    sys.exit(main())
