"""工作区受限命令执行：让 Agent 能真正跑测试/语法检查，而不只是看文档互评。

限制手段：
- 二进制白名单（只允许当前解释器与 node），拒绝任何未授权可执行文件
- 不使用 shell（subprocess.run 列表参数），拒绝 | & ; < > $ ` 等 shell 元字符
- 拒绝绝对路径与 `..` 参数，工作目录固定为该运行的工作区
- 强制超时、输出截断、参数数量上限、独立的最小环境变量

重要：这不是强安全沙箱。白名单内的解释器仍然能读写进程可及的文件，
因此本能力定位为「本地开发工具链」，不要在没有额外隔离（容器/低权限用户）的
多租户环境里启用。
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

ALLOWED_BINARIES = {"python3", "python", "node"}
MAX_TIMEOUT = 120
MIN_TIMEOUT = 1
MAX_OUTPUT_CHARS = 20_000
MAX_ARGS = 32
IGNORED_DIRS = {"__pycache__", ".pytest_cache", ".git", "node_modules", ".venv"}

# 只管真正的 shell 元字符：因为我们从不经过 shell，这些字符出现只可能是误用或注入尝试。
# 括号/花括号/引号在 Python 代码里很常见，且无 shell 时不会被执行，故不拦截。
FORBIDDEN_CHARS = set("|&;<>$`\n\r\\")


class SandboxError(ValueError):
    """命令被安全策略拒绝。"""


def _binary_for(name: str) -> str:
    if "/" in name or "\\" in name:
        raise SandboxError(f"不允许使用绝对/相对路径指定可执行文件：{name}")
    base = name
    if base not in ALLOWED_BINARIES:
        allowed = "、".join(sorted(ALLOWED_BINARIES))
        raise SandboxError(f"不允许执行「{name}」（仅允许：{allowed}）")
    if base in ("python3", "python"):
        # 固定用后端自己的解释器：保证 pytest 等依赖可用，也避免 PATH 被替换
        return sys.executable
    found = shutil.which("node")
    if not found:
        raise SandboxError("未找到 node，可执行文件不可用")
    return found


def parse_command(command: str) -> list[str]:
    """把命令行拆成 argv 并做静态校验；任何可疑内容直接拒绝。"""
    cmd = (command or "").strip()
    if not cmd:
        raise SandboxError("命令不能为空")
    if len(cmd) > 2000:
        raise SandboxError("命令过长")
    bad = sorted({c for c in cmd if c in FORBIDDEN_CHARS})
    if bad:
        raise SandboxError(f"命令包含不允许的字符：{''.join(bad)}")

    try:
        argv = shlex.split(cmd)
    except ValueError as e:
        raise SandboxError(f"命令解析失败：{e}") from e
    if not argv:
        raise SandboxError("命令不能为空")
    if len(argv) > MAX_ARGS:
        raise SandboxError(f"参数过多（上限 {MAX_ARGS}）")

    argv[0] = _binary_for(argv[0])
    for arg in argv[1:]:
        if arg.startswith("/") or arg.startswith("\\"):
            raise SandboxError(f"不允许绝对路径参数：{arg}")
        if arg == ".." or arg.startswith("../") or "/../" in arg or arg.endswith("/.."):
            raise SandboxError(f"不允许越出工作区的路径参数：{arg}")
    return argv


def _clip(text: str, limit: int) -> tuple[str, bool]:
    text = text or ""
    if len(text) <= limit:
        return text, False
    head = int(limit * 0.7)
    tail = limit - head
    return f"{text[:head]}\n…（输出过长，已截断 {len(text) - limit} 字）…\n{text[-tail:]}", True


def run_command(
    workspace_root: Path,
    command: str,
    *,
    timeout: int = 30,
    max_output: int = 8000,
) -> dict:
    """在工作区执行一条白名单命令，返回结构化结果（不抛异常，失败也返回结果）。"""
    started = time.monotonic()
    try:
        argv = parse_command(command)
    except SandboxError as e:
        return {
            "command": command,
            "allowed": False,
            "exitCode": None,
            "timedOut": False,
            "stdout": "",
            "stderr": str(e),
            "truncated": False,
            "durationMs": 0,
        }

    timeout = max(MIN_TIMEOUT, min(int(timeout or 30), MAX_TIMEOUT))
    max_output = max(200, min(int(max_output or 8000), MAX_OUTPUT_CHARS))
    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(workspace_root),
        "TMPDIR": str(workspace_root / ".tmp"),
        "LANG": "en_US.UTF-8",
        "LC_ALL": "en_US.UTF-8",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(workspace_root),
        "NO_COLOR": "1",
        "CI": "1",
    }
    (workspace_root / ".tmp").mkdir(parents=True, exist_ok=True)

    try:
        proc = subprocess.run(
            argv,
            cwd=str(workspace_root),
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
        )
        stdout, cut_out = _clip(proc.stdout, max_output)
        stderr, cut_err = _clip(proc.stderr, max_output)
        return {
            "command": command,
            "allowed": True,
            "exitCode": proc.returncode,
            "timedOut": False,
            "stdout": stdout,
            "stderr": stderr,
            "truncated": cut_out or cut_err,
            "durationMs": int((time.monotonic() - started) * 1000),
        }
    except subprocess.TimeoutExpired as e:
        raw_out = e.stdout if isinstance(e.stdout, str) else (e.stdout or b"").decode("utf-8", "replace")
        raw_err = e.stderr if isinstance(e.stderr, str) else (e.stderr or b"").decode("utf-8", "replace")
        stdout, cut_out = _clip(raw_out, max_output)
        stderr, cut_err = _clip(raw_err, max_output)
        return {
            "command": command,
            "allowed": True,
            "exitCode": None,
            "timedOut": True,
            "stdout": stdout,
            "stderr": f"{stderr}\n（命令超时，已强制终止：{timeout}s）".strip(),
            "truncated": cut_out or cut_err,
            "durationMs": int((time.monotonic() - started) * 1000),
        }
    except OSError as e:
        return {
            "command": command,
            "allowed": True,
            "exitCode": None,
            "timedOut": False,
            "stdout": "",
            "stderr": f"命令启动失败：{e}",
            "truncated": False,
            "durationMs": int((time.monotonic() - started) * 1000),
        }


def visible_files(root: Path) -> list[str]:
    """工作区内的交付文件（排除缓存与依赖目录），相对路径。"""
    out: list[str] = []
    if not root.exists():
        return out
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in IGNORED_DIRS for part in rel.parts):
            continue
        out.append(rel.as_posix())
    return out


def detect_checks(root: Path) -> list[str]:
    """根据工作区里实际存在的文件推断要跑的校验命令。

    优先级：有测试就跑 pytest；否则对 Python 文件做语法检查；再补 JS 语法检查。
    """
    files = visible_files(root)
    if not files:
        return []
    checks: list[str] = []
    has_tests = any(
        f.startswith("tests/") or Path(f).name.startswith("test_") or Path(f).name.endswith("_test.py")
        for f in files
    )
    if has_tests:
        checks.append("python3 -B -m pytest -q")
    else:
        py_files = [f for f in files if f.endswith(".py")]
        for f in py_files[:3]:
            # -B 禁止写 .pyc；check_clean 会在执行后清掉任何残留缓存
            checks.append(f"python3 -B -m py_compile {f}")
    for f in [x for x in files if x.endswith(".js")][:2]:
        checks.append(f"node --check {f}")
    return checks


def clean_caches(root: Path) -> None:
    """清理校验过程产生的字节码/缓存目录，避免污染交付文件列表。"""
    if not root.exists():
        return
    for d in list(root.rglob("__pycache__")):
        shutil.rmtree(d, ignore_errors=True)
    for d in list(root.rglob(".pytest_cache")):
        shutil.rmtree(d, ignore_errors=True)


def format_report(results: list[dict], files: list[str]) -> str:
    """把校验结果整理成给测试工程师看的文本。"""
    if not results:
        return "（工作区没有可执行的校验命令）"
    lines = [f"工作区文件（{len(files)} 个）：" + ("、".join(files) if files else "（空）"), ""]
    for r in results:
        status = (
            "被安全策略拒绝"
            if not r.get("allowed")
            else "超时"
            if r.get("timedOut")
            else f"exit={r.get('exitCode')}"
        )
        lines.append(f"$ {r['command']}    → {status}（{r.get('durationMs', 0)}ms）")
        if r.get("stdout"):
            lines.append(f"[stdout]\n{r['stdout']}")
        if r.get("stderr"):
            lines.append(f"[stderr]\n{r['stderr']}")
        lines.append("")
    return "\n".join(lines).strip()


def failed_checks(results: list[dict]) -> list[str]:
    """返回未通过的校验命令描述（供验收门兜底使用）。"""
    out = []
    for r in results:
        if not r.get("allowed"):
            out.append(f"`{r['command']}` 被安全策略拒绝：{r.get('stderr', '')}")
        elif r.get("timedOut"):
            out.append(f"`{r['command']}` 执行超时")
        elif r.get("exitCode") not in (0, None):
            out.append(f"`{r['command']}` 返回非零退出码 {r.get('exitCode')}")
    return out
