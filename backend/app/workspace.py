"""工作区文件工具：让 Agent 的交付物能真正落成文件，而不只是对话里的 Markdown。

安全边界：所有路径都限制在 workspace 根目录内（默认 backend/data/workspace/<runId>），
拒绝绝对路径、`..` 越界与符号链接逃逸；单文件与单次写入都有大小上限。
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Optional

MAX_WRITE_CHARS = 200_000
MAX_LIST_FILES = 200
# 工具副产物目录：不出现在交付文件列表里
IGNORED_PARTS = {"__pycache__", ".pytest_cache", ".git", "node_modules", ".venv", ".tmp", ".mypy_cache", ".ruff_cache"}
# 允许相对路径里的常见安全字符（中文文件名也允许）
_SAFE_NAME = re.compile(r"^[\w\u4e00-\u9fff.\-+/ ]+$")


class Workspace:
    def __init__(self, root: Path) -> None:
        # 统一 resolve：macOS 上 /tmp 是 /private/tmp 的符号链接，
        # 若不解析，rglob 得到的路径与 root 前缀不一致会让相对路径计算失败。
        root.mkdir(parents=True, exist_ok=True)
        self.root = root.resolve()

    def resolve(self, rel: str) -> Path:
        """把相对路径解析到工作区内；越界或非法路径抛 ValueError。"""
        raw = (rel or "").strip().replace("\\", "/")
        if not raw:
            raise ValueError("文件路径不能为空")
        if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
            raise ValueError(f"只接受工作区内的相对路径：{rel}")
        if not _SAFE_NAME.match(raw):
            raise ValueError(f"路径包含不允许的字符：{rel}")
        target = (self.root / raw).resolve()
        if target != self.root and self.root not in target.parents:
            raise ValueError(f"路径越出工作区：{rel}")
        return target

    def write(self, rel: str, content: str) -> dict:
        if len(content) > MAX_WRITE_CHARS:
            raise ValueError(f"单次写入超过 {MAX_WRITE_CHARS} 字符上限（{len(content)}）")
        path = self.resolve(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, "utf-8")
        return {"path": self.relpath(path), "bytes": len(content.encode("utf-8"))}

    def read(self, rel: str, limit: int = 20_000) -> dict:
        path = self.resolve(rel)
        if not path.is_file():
            raise ValueError(f"文件不存在：{rel}")
        text = path.read_text("utf-8", "replace")
        truncated = len(text) > limit
        return {"path": self.relpath(path), "content": text[:limit], "truncated": truncated}

    def list_files(self) -> list[dict]:
        out: list[dict] = []
        for p in sorted(self.root.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(self.root)
            # 跳过缓存/依赖目录：这些是工具副产物，不是交付物
            if any(part in IGNORED_PARTS for part in rel.parts):
                continue
            out.append({"path": self.relpath(p), "bytes": p.stat().st_size})
            if len(out) >= MAX_LIST_FILES:
                break
        return out

    def relpath(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix()

    def clear(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True, exist_ok=True)


def extract_artifacts(text: str) -> list[dict]:
    """从模型输出里提取 ```lang path=... ``` 形式的文件块。

    约定（写进工作包 prompt，不影响普通代码块）：
        ```python path=src/main.py
        ...
        ```
    没有 path= 的代码块是普通示例代码，不会被当作交付文件。
    """
    files: list[dict] = []
    pattern = re.compile(r"```[^\n]*?\bpath=([^\s`]+)[^\n]*\n(.*?)```", re.S)
    for m in pattern.finditer(text or ""):
        path = m.group(1).strip()
        content = m.group(2)
        if content.endswith("\n"):
            content = content[:-1]
        if path:
            files.append({"path": path, "content": content})
    return files
