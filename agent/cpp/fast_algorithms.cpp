#include <algorithm>
#include <numeric>
#include <stdexcept>
#include <vector>

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

namespace py = pybind11;

std::vector<double> quick_sort(std::vector<double> values) {
    // 按值接收，避免直接修改 Python 侧传入的原列表。
    std::sort(values.begin(), values.end());
    return values;
}

double sum_values(const std::vector<double>& values) {
    // 使用 STL accumulate 完成求和。
    return std::accumulate(values.begin(), values.end(), 0.0);
}

double average_value(const std::vector<double>& values) {
    // 平均值需要至少一个元素，空数组直接报错给 Python 层处理。
    if (values.empty()) {
        throw std::invalid_argument("average_value requires at least one value");
    }
    return sum_values(values) / static_cast<double>(values.size());
}

double min_value(const std::vector<double>& values) {
    // min/max 对空数组没有定义，因此统一抛出参数错误。
    if (values.empty()) {
        throw std::invalid_argument("min_value requires at least one value");
    }
    return *std::min_element(values.begin(), values.end());
}

double max_value(const std::vector<double>& values) {
    if (values.empty()) {
        throw std::invalid_argument("max_value requires at least one value");
    }
    return *std::max_element(values.begin(), values.end());
}

py::dict describe_values(const std::vector<double>& values) {
    // 汇总结果直接返回 dict，Python 工具层可序列化为 JSON 给 Agent。
    if (values.empty()) {
        throw std::invalid_argument("describe_values requires at least one value");
    }
    py::dict result;
    result["count"] = values.size();
    result["sum"] = sum_values(values);
    result["average"] = average_value(values);
    result["min"] = min_value(values);
    result["max"] = max_value(values);
    return result;
}

PYBIND11_MODULE(fast_algorithms, m) {
    // pybind11 模块名需要与 setup.py 中的扩展名保持一致。
    m.doc() = "Fast numerical algorithms exposed with pybind11";
    m.def("quick_sort", &quick_sort, "Sort a list of numbers");
    m.def("sum_values", &sum_values, "Sum a list of numbers");
    m.def("average_value", &average_value, "Average a list of numbers");
    m.def("min_value", &min_value, "Find the minimum number");
    m.def("max_value", &max_value, "Find the maximum number");
    m.def("describe_values", &describe_values, "Return count/sum/average/min/max");
}
