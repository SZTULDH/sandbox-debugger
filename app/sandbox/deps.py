"""沙盒依赖管理：白名单预装 + 声明预检 + 受限 pip。

三层能力（由易到难、由安全到开放）：

1. **预装白名单**  
   `ALLOWED_PACKAGES` 列出允许在沙盒中使用的第三方包；  
   `PREINSTALL` 是建议预先装进运行环境的子集（见 requirements-sandbox.txt）。

2. **依赖声明 + 预检**  
   题目 / 调用方可传 `dependencies: ["numpy", "pandas"]`。  
   `check_dependencies` 只检查、不安装；缺失时返回明确错误。  
   `ensure_dependencies` 在开启 `SANDBOX_ALLOW_PIP=1` 时才会对白名单包执行受限安装。

3. **受限 pip 工具**  
   `install_packages` 仅允许安装白名单内的包名，禁止路径/URL/git/可编辑安装，  
   默认关闭（需环境变量显式打开），安装超时与输出长度均有上限。

设计原则：
- 默认安全：不自动联网、不装任意包。
- 错误可机读：所有公开函数返回 dict，`ok` 字段统一语义。
- 与 debug_api 同级契约，供 Agent / MCP / 主项目桥接使用。
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import re
import subprocess
import sys
from typing import Any

# ---------------------------------------------------------------------------
# 白名单：包名 → import 时使用的顶层模块名（多数情况下二者相同）
# ---------------------------------------------------------------------------

ALLOWED_PACKAGES: dict[str, str] = {
    # 科学计算 / 数据
    "numpy": "numpy",
    "pandas": "pandas",
    "scipy": "scipy",
    "scikit-learn": "sklearn",
    "sklearn": "sklearn",
    # 序列化 / 配置
    "pyyaml": "yaml",
    "yaml": "yaml",
    "toml": "toml",
    "tomli": "tomli",
    # HTTP（调试场景可能需要 mock 客户端；生产仍建议禁网）
    "requests": "requests",
    "httpx": "httpx",
    # 工具
    "python-dateutil": "dateutil",
    "dateutil": "dateutil",
    "pytz": "pytz",
    "regex": "regex",
    "orjson": "orjson",
    "ujson": "ujson",
    # 测试辅助（题目本身一般不需要，Agent 诊断可能用到）
    "pytest": "pytest",
}

# 建议预装进运行环境的子集（轻量、高频）
PREINSTALL: list[str] = [
    "numpy",
    "pandas",
    "pyyaml",
    "python-dateutil",
]

# 包名合法字符：字母数字、点、下划线、连字符；禁止 path / URL / 版本操作符混入名
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]*$")

# 环境开关
def _pip_enabled() -> bool:
    return os.getenv("SANDBOX_ALLOW_PIP", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _normalize_name(raw: str) -> str:
    """归一化包名：小写、去掉版本约束后缀。"""
    s = (raw or "").strip()
    # 去掉 extras 与版本：numpy[extra]==1.26 → numpy
    s = re.split(r"[\[<=>!~@;\s]", s, maxsplit=1)[0].strip()
    return s.lower()


def is_allowed(package: str) -> bool:
    return _normalize_name(package) in ALLOWED_PACKAGES


def module_of(package: str) -> str | None:
    return ALLOWED_PACKAGES.get(_normalize_name(package))


def list_allowed() -> dict[str, Any]:
    """返回当前白名单与预装建议。"""
    installed = []
    missing = []
    for pkg, mod in sorted(ALLOWED_PACKAGES.items()):
        # 跳过别名重复检查（sklearn / scikit-learn）
        if pkg in {"sklearn", "yaml", "dateutil"}:
            continue
        if importlib.util.find_spec(mod) is not None:
            installed.append(pkg)
        else:
            missing.append(pkg)
    return {
        "ok": True,
        "allowed": sorted(set(ALLOWED_PACKAGES.keys())),
        "preinstall": list(PREINSTALL),
        "pip_enabled": _pip_enabled(),
        "installed": installed,
        "missing_from_whitelist": missing,
    }


def check_dependencies(dependencies: list[str] | None) -> dict[str, Any]:
    """预检：声明的依赖是否在白名单内、是否已安装。

    不执行安装。返回：
      ok=True  → 全部可用
      ok=False → missing / not_allowed 列表说明原因
    """
    deps = [d for d in (dependencies or []) if str(d).strip()]
    if not deps:
        return {"ok": True, "checked": [], "missing": [], "not_allowed": []}

    missing: list[str] = []
    not_allowed: list[str] = []
    checked: list[dict[str, Any]] = []

    for raw in deps:
        name = _normalize_name(raw)
        if not name or not _SAFE_NAME.match(name):
            not_allowed.append(raw)
            checked.append({"name": raw, "status": "invalid_name"})
            continue
        if name not in ALLOWED_PACKAGES:
            not_allowed.append(name)
            checked.append({"name": name, "status": "not_allowed"})
            continue
        mod = ALLOWED_PACKAGES[name]
        present = importlib.util.find_spec(mod) is not None
        if present:
            checked.append({"name": name, "module": mod, "status": "installed"})
        else:
            missing.append(name)
            checked.append({"name": name, "module": mod, "status": "missing"})

    ok = not missing and not not_allowed
    out: dict[str, Any] = {
        "ok": ok,
        "checked": checked,
        "missing": missing,
        "not_allowed": not_allowed,
    }
    if not ok:
        parts = []
        if not_allowed:
            parts.append(f"不在白名单: {not_allowed}")
        if missing:
            parts.append(f"未安装: {missing}")
        out["error"] = "; ".join(parts)
        out["hint"] = (
            "请在运行环境预装白名单包，或设置 SANDBOX_ALLOW_PIP=1 后调用 "
            "install_packages / ensure_dependencies。"
            if missing and not not_allowed
            else "仅允许安装 ALLOWED_PACKAGES 中的包。"
        )
    return out


def _validate_install_specs(packages: list[str]) -> tuple[list[str], list[str]]:
    """校验待安装规格：只允许 白名单包名[==版本]。"""
    ok_specs: list[str] = []
    rejected: list[str] = []
    for raw in packages:
        s = (raw or "").strip()
        if not s:
            continue
        # 禁止 URL / 本地路径 / VCS / 可编辑
        lower = s.lower()
        if any(
            x in lower
            for x in (
                "://",
                "git+",
                "file:",
                "/",
                "\\",
                "-e ",
                "--editable",
            )
        ) or s.startswith((".", "/", "-")):
            rejected.append(s)
            continue
        name = _normalize_name(s)
        if name not in ALLOWED_PACKAGES or not _SAFE_NAME.match(name):
            rejected.append(s)
            continue
        # 允许可选的 ==version / >=version（仍须以白名单名为前缀）
        if not re.match(
            r"^[A-Za-z0-9][A-Za-z0-9._\-]*(\[[A-Za-z0-9,_\-]+\])?"
            r"([<>=!~]=?[^\s;]+)?$",
            s,
        ):
            rejected.append(s)
            continue
        ok_specs.append(s)
    return ok_specs, rejected


def install_packages(
    packages: list[str] | None,
    *,
    timeout: float = 120.0,
    upgrade: bool = False,
) -> dict[str, Any]:
    """受限 pip install：仅白名单包，需 SANDBOX_ALLOW_PIP=1。

    返回机读结果；永不抛异常到调用方契约层（内部 subprocess 异常已捕获）。
    """
    if not _pip_enabled():
        return {
            "ok": False,
            "error": "受限 pip 未开启。设置环境变量 SANDBOX_ALLOW_PIP=1 后重试。",
            "installed": [],
            "rejected": list(packages or []),
        }

    specs, rejected = _validate_install_specs(list(packages or []))
    if rejected and not specs:
        return {
            "ok": False,
            "error": f"全部被拒绝（非白名单或非法规格）: {rejected}",
            "installed": [],
            "rejected": rejected,
        }
    if not specs:
        return {"ok": True, "installed": [], "rejected": rejected, "note": "无待安装项"}

    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
        "--no-warn-script-location",
    ]
    if upgrade:
        cmd.append("--upgrade")
    cmd.extend(specs)

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PIP_DISABLE_PIP_VERSION_CHECK": "1"},
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": f"pip install 超时（>{timeout}s）",
            "installed": [],
            "rejected": rejected,
            "requested": specs,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "installed": [],
            "rejected": rejected,
            "requested": specs,
        }

    stdout = (proc.stdout or "")[-2000:]
    stderr = (proc.stderr or "")[-2000:]
    if proc.returncode != 0:
        return {
            "ok": False,
            "error": f"pip 退出码 {proc.returncode}",
            "installed": [],
            "rejected": rejected,
            "requested": specs,
            "stdout": stdout,
            "stderr": stderr,
        }

    # 安装后复核 import
    still_missing = []
    for s in specs:
        mod = module_of(s)
        if mod and importlib.util.find_spec(mod) is None:
            # 新装的包可能需要清缓存
            importlib.invalidate_caches()
            if importlib.util.find_spec(mod) is None:
                still_missing.append(s)

    ok = not still_missing
    return {
        "ok": ok,
        "installed": [s for s in specs if s not in still_missing],
        "still_missing": still_missing,
        "rejected": rejected,
        "stdout": stdout[-800:],
        "error": (f"安装后仍无法 import: {still_missing}" if still_missing else None),
    }


def ensure_dependencies(
    dependencies: list[str] | None,
    *,
    allow_install: bool | None = None,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """检查依赖；若缺失且允许安装，则对白名单包执行受限 pip。

    allow_install:
      None  → 跟随环境变量 SANDBOX_ALLOW_PIP
      True  → 强制尝试安装（仍受白名单约束）
      False → 只检查不安装
    """
    check = check_dependencies(dependencies)
    if check["ok"]:
        return {"ok": True, "action": "none", "check": check}

    if check.get("not_allowed"):
        return {
            "ok": False,
            "action": "rejected",
            "check": check,
            "error": check.get("error"),
        }

    do_install = _pip_enabled() if allow_install is None else bool(allow_install)
    if not do_install:
        return {
            "ok": False,
            "action": "check_only",
            "check": check,
            "error": check.get("error"),
            "hint": check.get("hint"),
        }

    missing = check.get("missing") or []
    inst = install_packages(missing, timeout=timeout)
    recheck = check_dependencies(dependencies)
    return {
        "ok": recheck["ok"],
        "action": "install",
        "check": recheck,
        "install": inst,
        "error": None if recheck["ok"] else (inst.get("error") or recheck.get("error")),
    }


# Agent / MCP 工具 schema
DEPS_TOOLS: list[dict[str, Any]] = [
    {
        "name": "sandbox_list_allowed_packages",
        "description": "列出沙盒允许的第三方包白名单、预装建议、以及当前环境已安装情况。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "sandbox_check_dependencies",
        "description": (
            "预检题目/代码声明的依赖是否在白名单且已安装。"
            "不执行安装。传入 dependencies 字符串列表，如 [\"numpy\", \"pandas\"]。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "dependencies": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "依赖包名列表",
                },
            },
            "required": ["dependencies"],
        },
    },
    {
        "name": "sandbox_ensure_dependencies",
        "description": (
            "检查并在允许时安装白名单依赖。"
            "默认跟随 SANDBOX_ALLOW_PIP；可传 allow_install=true 强制尝试（仍限白名单）。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "dependencies": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "allow_install": {"type": "boolean"},
                "timeout": {"type": "number", "description": "pip 超时秒数，默认 120"},
            },
            "required": ["dependencies"],
        },
    },
    {
        "name": "sandbox_install_packages",
        "description": (
            "受限 pip install：仅白名单包名（可带 ==version）。"
            "需 SANDBOX_ALLOW_PIP=1。禁止 URL/git/本地路径。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "packages": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "如 [\"numpy==2.0.0\", \"pandas\"]",
                },
                "timeout": {"type": "number"},
                "upgrade": {"type": "boolean"},
            },
            "required": ["packages"],
        },
    },
]
