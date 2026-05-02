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


def _parse_json_object(payload_json: str) -> dict[str, Any]:
    """把 JSON 对象参数解析成 dict，供带多个参数的 C++ 工具使用。"""
    data: Any = json.loads(payload_json)
    if not isinstance(data, dict):
        raise ValueError("Input must be a JSON object.")
    return data


def _parse_string_or_number_list(values: Any) -> list[str] | list[float]:
    """校验去重工具的数组输入，只允许纯数字数组或纯字符串数组。"""
    if not isinstance(values, list):
        raise ValueError("'values' must be a JSON array.")
    if not values:
        return []
    if all(isinstance(item, str) for item in values):
        return [str(item) for item in values]
    if all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in values):
        return [float(item) for item in values]
    raise ValueError("'values' must contain only numbers or only strings.")


def _parse_number_matrix(values: Any) -> list[list[float]]:
    """校验二维数字数组，用于矩阵计算。"""
    if not isinstance(values, list):
        raise ValueError("Matrix must be a JSON array of rows.")
    matrix: list[list[float]] = []
    for row in values:
        if not isinstance(row, list):
            raise ValueError("Each matrix row must be a JSON array.")
        matrix.append([float(item) for item in row])
    return matrix


def build_cpp_tools():
    """构造 C++ 高性能算法工具列表。"""

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
    def cpp_binary_search(payload_json: str) -> str:
        """Binary search sorted numbers with C++. Input JSON: {"values":[1,2,3],"target":2}."""
        try:
            payload = _parse_json_object(payload_json)
            numbers = _parse_numbers(json.dumps(payload.get("values"), ensure_ascii=False))
            if "target" not in payload:
                raise ValueError("'target' is required.")
            result = _load_cpp_module().binary_search_values(numbers, float(payload["target"]))
            return json.dumps(dict(result), ensure_ascii=False)
        except Exception as exc:
            return f"cpp_binary_search failed: {exc}"

    @tool
    def cpp_unique(payload_json: str) -> str:
        """Remove duplicates with C++. Input JSON: {"values":[1,2,1]} or {"values":["a","b","a"]}."""
        try:
            payload = _parse_json_object(payload_json)
            values = _parse_string_or_number_list(payload.get("values"))
            module = _load_cpp_module()
            if not values:
                return "[]"
            if isinstance(values[0], str):
                result = module.unique_strings(values)
            else:
                result = module.unique_numbers(values)
            return json.dumps(result, ensure_ascii=False)
        except Exception as exc:
            return f"cpp_unique failed: {exc}"

    @tool
    def cpp_statistics(numbers_json: str) -> str:
        """Compute count, sum, mean/average, min, max, median, mode, variance, stddev and quartiles with C++. Input is a JSON number array."""
        try:
            numbers = _parse_numbers(numbers_json)
            result = _load_cpp_module().advanced_statistics(numbers)
            return json.dumps(dict(result), ensure_ascii=False)
        except Exception as exc:
            return f"cpp_statistics failed: {exc}"

    @tool
    def cpp_prefix_sum(payload_json: str) -> str:
        """Compute prefix sum or difference array with C++. Input JSON: {"values":[1,3,6],"mode":"prefix|diff|both"}."""
        try:
            payload = _parse_json_object(payload_json)
            numbers = _parse_numbers(json.dumps(payload.get("values"), ensure_ascii=False))
            mode = str(payload.get("mode", "prefix")).lower()
            module = _load_cpp_module()
            if mode == "prefix":
                result: Any = module.prefix_sum(numbers)
            elif mode == "diff":
                result = module.difference_array(numbers)
            elif mode == "both":
                result = {
                    "prefix": module.prefix_sum(numbers),
                    "diff": module.difference_array(numbers),
                }
            else:
                raise ValueError("'mode' must be one of: prefix, diff, both.")
            return json.dumps(result, ensure_ascii=False)
        except Exception as exc:
            return f"cpp_prefix_sum failed: {exc}"

    @tool
    def cpp_matrix(payload_json: str) -> str:
        """Run C++ matrix operations. Input JSON supports {"operation":"transpose|inverse","matrix":[[1,2],[3,4]]} or {"operation":"multiply","left":[[1,2]],"right":[[3],[4]]}."""
        try:
            payload = _parse_json_object(payload_json)
            operation = str(payload.get("operation", "transpose")).lower()
            module = _load_cpp_module()
            if operation == "transpose":
                matrix = _parse_number_matrix(payload.get("matrix"))
                result = module.matrix_transpose(matrix)
            elif operation == "multiply":
                left = _parse_number_matrix(payload.get("left"))
                right = _parse_number_matrix(payload.get("right"))
                result = module.matrix_multiply(left, right)
            elif operation == "inverse":
                matrix = _parse_number_matrix(payload.get("matrix"))
                result = module.matrix_inverse(matrix)
            else:
                raise ValueError("'operation' must be one of: transpose, multiply, inverse.")
            return json.dumps(result, ensure_ascii=False)
        except Exception as exc:
            return f"cpp_matrix failed: {exc}"

    @tool
    def cpp_topk(payload_json: str) -> str:
        """Select top-k values with C++. Input JSON: {"values":[5,1,3],"k":2,"largest":true}."""
        try:
            payload = _parse_json_object(payload_json)
            numbers = _parse_numbers(json.dumps(payload.get("values"), ensure_ascii=False))
            if "k" not in payload:
                raise ValueError("'k' is required.")
            k = int(payload["k"])
            if k < 0:
                raise ValueError("'k' must be non-negative.")
            largest = bool(payload.get("largest", True))
            result = _load_cpp_module().top_k(numbers, k, largest)
            return json.dumps(result, ensure_ascii=False)
        except Exception as exc:
            return f"cpp_topk failed: {exc}"

    @tool
    def cpp_string_search(payload_json: str) -> str:
        """Find all pattern offsets with C++ KMP. Input JSON: {"text":"banana","pattern":"ana"}."""
        try:
            payload = _parse_json_object(payload_json)
            if "text" not in payload or "pattern" not in payload:
                raise ValueError("'text' and 'pattern' are required.")
            result = _load_cpp_module().kmp_search(str(payload["text"]), str(payload["pattern"]))
            return json.dumps(result, ensure_ascii=False)
        except Exception as exc:
            return f"cpp_string_search failed: {exc}"

    @tool
    def cpp_set_operations(payload_json: str) -> str:
        """Run set operations with C++. Input JSON: {"left":[1,2],"right":[2,3],"operation":"union|intersection|difference|symmetric_difference"}."""
        try:
            payload = _parse_json_object(payload_json)
            left = _parse_string_or_number_list(payload.get("left"))
            right = _parse_string_or_number_list(payload.get("right"))
            operation = str(payload.get("operation", "union")).lower()
            module = _load_cpp_module()
            if not left and not right:
                return "[]"
            sample = left[0] if left else right[0]
            if isinstance(sample, str):
                if any(not isinstance(item, str) for item in [*left, *right]):
                    raise ValueError("'left' and 'right' must have the same element type.")
                result = module.set_operation_strings(left, right, operation)
            else:
                if any(isinstance(item, str) for item in [*left, *right]):
                    raise ValueError("'left' and 'right' must have the same element type.")
                result = module.set_operation_numbers(left, right, operation)
            return json.dumps(result, ensure_ascii=False)
        except Exception as exc:
            return f"cpp_set_operations failed: {exc}"

    return [
        cpp_sort,
        cpp_binary_search,
        cpp_unique,
        cpp_statistics,
        cpp_prefix_sum,
        cpp_matrix,
        cpp_topk,
        cpp_string_search,
        cpp_set_operations,
    ]
