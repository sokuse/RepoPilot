from repopilot.services.chunking_service import split_markdown, split_python


def test_python_chunking_preserves_top_level_symbols_and_lines() -> None:
    content = """import os

@decorator
def first():
    return 1

class Worker:
    def run(self):
        return True
"""

    chunks = split_python(content)

    assert [chunk.symbol_name for chunk in chunks] == [None, "first", "Worker"]
    assert chunks[1].start_line == 3
    assert chunks[1].extra_metadata["symbol_type"] == "FunctionDef"
    assert chunks[2].start_line == 7


def test_markdown_chunking_preserves_heading_hierarchy() -> None:
    content = """简介
# 安装
安装内容
## Windows
Windows 内容
# 使用
使用内容
"""

    chunks = split_markdown(content)

    assert [chunk.symbol_name for chunk in chunks] == [None, "安装", "安装 > Windows", "使用"]
    assert [chunk.start_line for chunk in chunks] == [1, 2, 4, 6]
