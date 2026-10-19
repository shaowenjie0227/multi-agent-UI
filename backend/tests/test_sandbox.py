"""受限命令执行：白名单、shell 元字符、路径越界、超时、输出截断、结果判定。"""
from __future__ import annotations

import sys

import pytest

from app.sandbox import (
    MAX_OUTPUT_CHARS,
    SandboxError,
    clean_caches,
    detect_checks,
    failed_checks,
    format_report,
    parse_command,
    run_command,
    visible_files,
)


# ---------------- 静态校验 ----------------


@pytest.mark.parametrize("cmd", ["ls", "rm -rf /", "curl http://x", "bash -c id", "sh", "cat /etc/passwd"])
def test_non_whitelisted_binary_rejected(cmd):
    with pytest.raises(SandboxError) as exc:
        parse_command(cmd)
    assert "不允许执行" in str(exc.value)


@pytest.mark.parametrize(
    "cmd",
    [
        "python3 -c 'print(1); rm -rf /'",
        "python3 -c 'x' | tee out.txt",
        "python3 -c 'x' && whoami",
        "python3 -c 'x' > /tmp/out",
        "python3 -c `whoami`",
        "python3 -c $(whoami)",
        "python3 -c 'x' &",
    ],
)
def test_shell_metacharacters_rejected(cmd):
    with pytest.raises(SandboxError) as exc:
        parse_command(cmd)
    assert "不允许的字符" in str(exc.value)


@pytest.mark.parametrize("arg", ["/etc/passwd", "../outside.py", "a/../../b.py", "sub/.."])
def test_path_escape_arguments_rejected(arg):
    with pytest.raises(SandboxError):
        parse_command(f"python3 {arg}")


def test_absolute_binary_path_rejected():
    with pytest.raises(SandboxError):
        parse_command("/usr/bin/python3 -c 'print(1)'")


def test_quote_rejected_as_metachar():
    """引号本身不在白名单字符集里会出现歧义，这里只验证合法用法仍可解析。"""
    argv = parse_command("python3 -c 'print(1)'")
    assert argv[0] == sys.executable
    assert argv[1:] == ["-c", "print(1)"]


def test_empty_command_rejected():
    with pytest.raises(SandboxError):
        parse_command("   ")


def test_too_many_args_rejected():
    with pytest.raises(SandboxError) as exc:
        parse_command("python3 " + " ".join(["a.py"] * 40))
    assert "参数过多" in str(exc.value)


def test_overlong_command_rejected():
    with pytest.raises(SandboxError):
        parse_command("python3 " + "x" * 3000)


def test_python_maps_to_current_interpreter():
    argv = parse_command("python -c 'print(1)'")
    assert argv[0] == sys.executable


def test_node_allowed_when_installed():
    import shutil

    if not shutil.which("node"):
        pytest.skip("未安装 node")
    argv = parse_command("node -e 'console.log(1)'")
    assert argv[0].endswith("node")


# ---------------- 执行 ----------------


def test_run_python_ok(tmp_path):
    r = run_command(tmp_path, "python3 -c 'print(42)'", timeout=20)
    assert r["allowed"] is True
    assert r["exitCode"] == 0
    assert "42" in r["stdout"]
    assert r["timedOut"] is False


def test_run_nonzero_exit(tmp_path):
    (tmp_path / "exit3.py").write_text("import sys\nsys.exit(3)\n", "utf-8")
    r = run_command(tmp_path, "python3 exit3.py", timeout=20)
    assert r["exitCode"] == 3


def test_run_inside_workspace_cwd(tmp_path):
    (tmp_path / "hello.txt").write_text("hi", "utf-8")
    r = run_command(tmp_path, "python3 -c 'print(open(\"hello.txt\").read())'", timeout=20)
    assert r["exitCode"] == 0
    assert "hi" in r["stdout"]


def test_rejected_command_returns_structured_result(tmp_path):
    r = run_command(tmp_path, "rm -rf /", timeout=20)
    assert r["allowed"] is False
    assert r["exitCode"] is None
    assert "不允许执行" in r["stderr"]


def test_timeout_kills_process(tmp_path):
    (tmp_path / "sleep.py").write_text("import time\ntime.sleep(10)\n", "utf-8")
    r = run_command(tmp_path, "python3 sleep.py", timeout=1)
    assert r["timedOut"] is True
    assert "超时" in r["stderr"]
    assert r["durationMs"] < 5000


def test_output_is_truncated(tmp_path):
    r = run_command(
        tmp_path,
        "python3 -c 'print(\"x\" * 60000)'",
        timeout=30,
        max_output=500,
    )
    assert r["truncated"] is True
    assert len(r["stdout"]) < 1000
    assert "已截断" in r["stdout"]


def test_max_output_capped_hard(tmp_path):
    r = run_command(tmp_path, "python3 -c 'print(1)'", timeout=10, max_output=10 ** 9)
    assert r["allowed"] is True  # 上限被钳制而非报错
    assert MAX_OUTPUT_CHARS > 0


def test_stderr_captured(tmp_path):
    r = run_command(tmp_path, "python3 -c 'raise SystemExit(\"boom\")'", timeout=20)
    assert "boom" in r["stderr"]


def test_environment_is_minimal(tmp_path):
    (tmp_path / "env.py").write_text("import os\nprint(os.environ.get('HOME'))\n", "utf-8")
    r = run_command(tmp_path, "python3 env.py", timeout=20)
    assert r["exitCode"] == 0
    assert str(tmp_path) in r["stdout"] or r["stdout"].strip() == str(tmp_path.resolve())


# ---------------- 文件发现与校验探测 ----------------


def test_visible_files_skips_cache_dirs(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x", "utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "a.pyc").write_bytes(b"x")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("x", "utf-8")
    assert visible_files(tmp_path) == ["src/a.py"]


def test_detect_checks_prefers_pytest_when_tests_exist(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("def test_x(): assert True\n", "utf-8")
    cmds = detect_checks(tmp_path)
    assert cmds[0] == "python3 -B -m pytest -q"


def test_checks_do_not_leave_pycache(tmp_path):
    """py_compile 不得在交付目录留下 __pycache__（否则会污染交付文件列表）。"""
    (tmp_path / "a.py").write_text("print(1)\n", "utf-8")
    for cmd in detect_checks(tmp_path):
        run_command(tmp_path, cmd, timeout=30)
    clean_caches(tmp_path)
    assert not list(tmp_path.rglob("__pycache__"))
    assert visible_files(tmp_path) == ["a.py"]


def test_detect_checks_uses_py_compile_without_tests(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print(1)\n", "utf-8")
    cmds = detect_checks(tmp_path)
    assert any("py_compile" in c for c in cmds)
    assert not any("pytest" in c for c in cmds)


def test_detect_checks_includes_node_for_js(tmp_path):
    import shutil

    if not shutil.which("node"):
        pytest.skip("未安装 node")
    (tmp_path / "app.js").write_text("console.log(1)\n", "utf-8")
    assert any(c.startswith("node --check") for c in detect_checks(tmp_path))


def test_detect_checks_empty_workspace(tmp_path):
    assert detect_checks(tmp_path) == []


# ---------------- 结果判定 ----------------


def test_failed_checks_reports_policy_rejection(tmp_path):
    r = run_command(tmp_path, "curl http://x", timeout=5)
    assert failed_checks([r]) and "安全策略拒绝" in failed_checks([r])[0]


def test_failed_checks_reports_timeout(tmp_path):
    (tmp_path / "sleep2.py").write_text("import time\ntime.sleep(5)\n", "utf-8")
    r = run_command(tmp_path, "python3 sleep2.py", timeout=1)
    assert any("超时" in f for f in failed_checks([r]))


def test_failed_checks_reports_nonzero(tmp_path):
    (tmp_path / "fail.py").write_text("import sys\nsys.exit(1)\n", "utf-8")
    r = run_command(tmp_path, "python3 fail.py", timeout=20)
    assert any("非零" in f for f in failed_checks([r]))


def test_failed_checks_passes_on_success(tmp_path):
    r = run_command(tmp_path, "python3 -c 'print(1)'", timeout=20)
    assert failed_checks([r]) == []


def test_format_report_includes_files_and_output(tmp_path):
    (tmp_path / "a.py").write_text("print(1)", "utf-8")
    r = run_command(tmp_path, "python3 -c 'print(\"OK\")'", timeout=20)
    text = format_report([r], visible_files(tmp_path))
    assert "a.py" in text
    assert "OK" in text
    assert "exit=0" in text


def test_format_report_empty():
    assert "没有可执行" in format_report([], [])


# ---------------- 端到端：真的能跑 pytest ----------------


def test_runs_real_pytest_suite(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_ok.py").write_text("def test_a():\n    assert 1 + 1 == 2\n", "utf-8")
    r = run_command(tmp_path, "python3 -m pytest -q tests/test_ok.py", timeout=60)
    assert r["allowed"] is True
    assert r["exitCode"] == 0, r["stderr"]
    assert "1 passed" in (r["stdout"] + r["stderr"])


def test_real_pytest_failure_detected(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_bad.py").write_text("def test_a():\n    assert 1 == 2\n", "utf-8")
    r = run_command(tmp_path, "python3 -m pytest -q tests/test_bad.py", timeout=60)
    assert r["exitCode"] != 0
    assert failed_checks([r])


def test_py_compile_catches_syntax_error(tmp_path):
    (tmp_path / "broken.py").write_text("def f(:\n", "utf-8")
    r = run_command(tmp_path, "python3 -m py_compile broken.py", timeout=30)
    assert r["exitCode"] != 0
    assert failed_checks([r])
