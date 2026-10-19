"""工作区：路径安全边界、写入/读取/列出、交付文件块解析。"""
from __future__ import annotations

import pytest

from app.workspace import Workspace, extract_artifacts


def test_write_read_roundtrip(tmp_path):
    ws = Workspace(tmp_path / "ws")
    info = ws.write("src/main.py", "print('hi')")
    assert info["path"] == "src/main.py"
    assert info["bytes"] == len("print('hi')")
    assert ws.read("src/main.py")["content"] == "print('hi')"


def test_creates_nested_dirs(tmp_path):
    ws = Workspace(tmp_path / "ws")
    ws.write("a/b/c/d.txt", "x")
    assert (tmp_path / "ws" / "a" / "b" / "c" / "d.txt").exists()


def test_chinese_and_space_paths_allowed(tmp_path):
    ws = Workspace(tmp_path / "ws")
    info = ws.write("文档/需求 说明.md", "内容")
    assert info["path"] == "文档/需求 说明.md"


@pytest.mark.parametrize("bad", ["../escape.txt", "../../etc/passwd", "/abs/path.txt", "a/../../b.txt"])
def test_path_traversal_rejected(tmp_path, bad):
    ws = Workspace(tmp_path / "ws")
    with pytest.raises(ValueError):
        ws.write(bad, "x")


def test_windows_absolute_rejected(tmp_path):
    ws = Workspace(tmp_path / "ws")
    with pytest.raises(ValueError):
        ws.write("C:/windows/system32/x.txt", "x")


def test_illegal_characters_rejected(tmp_path):
    ws = Workspace(tmp_path / "ws")
    with pytest.raises(ValueError):
        ws.write("a\nb.txt", "x")


def test_empty_path_rejected(tmp_path):
    ws = Workspace(tmp_path / "ws")
    with pytest.raises(ValueError):
        ws.write("  ", "x")


def test_oversize_write_rejected(tmp_path):
    ws = Workspace(tmp_path / "ws")
    with pytest.raises(ValueError):
        ws.write("big.txt", "x" * 200_001)


def test_read_missing_file(tmp_path):
    ws = Workspace(tmp_path / "ws")
    with pytest.raises(ValueError):
        ws.read("nope.txt")


def test_read_truncates(tmp_path):
    ws = Workspace(tmp_path / "ws")
    ws.write("long.txt", "y" * 500)
    out = ws.read("long.txt", limit=100)
    assert len(out["content"]) == 100 and out["truncated"] is True


def test_list_files(tmp_path):
    ws = Workspace(tmp_path / "ws")
    ws.write("src/a.py", "a")
    ws.write("docs/b.md", "b")
    paths = [f["path"] for f in ws.list_files()]
    assert paths == ["docs/b.md", "src/a.py"]


def test_list_files_hides_tool_cache_dirs(tmp_path):
    """校验命令残留的 __pycache__ 不应出现在交付文件列表里。"""
    ws = Workspace(tmp_path / "ws")
    ws.write("main.py", "print(1)")
    (ws.root / "__pycache__").mkdir()
    (ws.root / "__pycache__" / "main.cpython-312.pyc").write_bytes(b"x")
    (ws.root / "tests" / "__pycache__").mkdir(parents=True)
    (ws.root / "tests" / "__pycache__" / "t.pyc").write_bytes(b"x")
    (ws.root / ".pytest_cache").mkdir()
    (ws.root / ".pytest_cache" / "CACHEDIR.TAG").write_bytes(b"x")
    assert [f["path"] for f in ws.list_files()] == ["main.py"]


def test_symlink_escape_rejected(tmp_path):
    ws = Workspace(tmp_path / "ws")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", "utf-8")
    link = tmp_path / "ws" / "link.txt"
    try:
        link.symlink_to(outside / "secret.txt")
    except (OSError, NotImplementedError):
        pytest.skip("当前文件系统不支持符号链接")
    with pytest.raises(ValueError):
        ws.read("link.txt")


def test_symlinked_root_parent_does_not_break_relpath(tmp_path):
    """macOS /tmp -> /private/tmp：root 的父目录是符号链接时，相对路径仍要能算出来。"""
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("当前文件系统不支持符号链接")

    ws = Workspace(link / "ws")
    ws.write("src/a.py", "x")
    assert [f["path"] for f in ws.list_files()] == ["src/a.py"]
    assert ws.relpath(ws.resolve("src/a.py")) == "src/a.py"


# ---------------- 交付文件块解析 ----------------


def test_extract_single_file():
    text = "说明\n```python path=src/main.py\nprint(1)\n```\n尾注"
    files = extract_artifacts(text)
    assert files == [{"path": "src/main.py", "content": "print(1)"}]


def test_extract_multiple_files():
    text = (
        "```python path=a.py\nA\n```\n"
        "中间说明\n"
        "```markdown path=docs/b.md\n# B\n```"
    )
    files = extract_artifacts(text)
    assert [f["path"] for f in files] == ["a.py", "docs/b.md"]
    assert files[1]["content"] == "# B"


def test_extract_ignores_plain_code_block():
    assert extract_artifacts("```python\nprint(1)\n```") == []


def test_extract_handles_language_without_path_order():
    files = extract_artifacts("```path=x.txt\nhello\n```")
    assert files == [{"path": "x.txt", "content": "hello"}]


def test_extract_empty_and_none():
    assert extract_artifacts("") == []
    assert extract_artifacts(None) == []  # type: ignore[arg-type]


def test_extract_preserves_inner_blank_lines():
    files = extract_artifacts("```python path=a.py\nline1\n\nline3\n```")
    assert files[0]["content"] == "line1\n\nline3"
