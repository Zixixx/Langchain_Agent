from __future__ import annotations

"""C++ 工具封装：把 pybind11 扩展暴露成 LangChain 可调用工具。"""

import json
import sys
from pathlib import Path
from typing import Any

from langchain_core.tools import tool


def _load_cpp_module():
    """动态加载 fast_algorithms 扩展；未编译时给出可操作提示。"""
    try:
        cpp_dir = Path(__file__).resolve().parents[1] / "cpp"
        if str(cpp_dir) not in sys.path:
            sys.path.insert(0, str(cpp_dir))
        import fast_algorithms  # type: ignore

        return fast_algorithms
    except ImportError as exc:
        raise RuntimeError("C++ extension is not compiled. Run: pip install -e .") from exc


def _parse_numbers(numbers_json: str) -> list[float]:
    """把 LLM 传入的 JSON 数组解析成 float 列表。"""
    data: Any = json.loads(numbers_json)
    if not isinstance(data, list):
        raise ValueError("Input must be a JSON array of numbers.")
    return [float(item) for item in data]


def build_cpp_tools():
    """构造 C++ 排序和数值统计工具列表。"""

    @tool
    def cpp_sort(numbers_json: str) -> str:
        """Sort numbers with the C++ pybind11 extension. Input is a JSON array, e.g. [3,1,2]."""
        try:
            numbers = _parse_numbers(numbers_json)
            result = _load_cpp_module().quick_sort(numbers)
            return json.dumps(result, ensure_ascii=False)
        except Exception as exc:
            return f"cpp_sort failed: {exc}"

    @tool
    def cpp_numeric_summary(numbers_json: str) -> str:
        """Compute count, sum, average, min and max with C++. Input is a JSON array of numbers."""
        try:
            numbers = _parse_numbers(numbers_json)
            result = _load_cpp_module().describe_values(numbers)
            return json.dumps(dict(result), ensure_ascii=False)
        except Exception as exc:
            return f"cpp_numeric_summary failed: {exc}"

    return [cpp_sort, cpp_numeric_summary]
