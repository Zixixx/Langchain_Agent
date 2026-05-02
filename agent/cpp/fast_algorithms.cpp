#include <algorithm>
#include <cmath>
#include <functional>
#include <iterator>
#include <map>
#include <numeric>
#include <stdexcept>
#include <string>
#include <unordered_set>
#include <vector>

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

namespace py = pybind11;

std::vector<double> quick_sort(std::vector<double> values) {
    // Receive by value so the original Python list is not modified.
    std::sort(values.begin(), values.end());
    return values;
}

double sum_values(const std::vector<double>& values) {
    // Use the STL accumulator for a compact and reliable sum.
    return std::accumulate(values.begin(), values.end(), 0.0);
}

double average_value(const std::vector<double>& values) {
    // Empty input has no average, so report a clear Python-side error.
    if (values.empty()) {
        throw std::invalid_argument("average_value requires at least one value");
    }
    return sum_values(values) / static_cast<double>(values.size());
}

double min_value(const std::vector<double>& values) {
    // min/max are undefined for empty input.
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

py::dict binary_search_values(const std::vector<double>& values, double target) {
    // The input must already be sorted in ascending order.
    auto lower = std::lower_bound(values.begin(), values.end(), target);
    auto upper = std::upper_bound(values.begin(), values.end(), target);
    py::dict result;
    result["found_index"] = (lower != values.end() && *lower == target)
                                ? static_cast<long long>(std::distance(values.begin(), lower))
                                : -1;
    result["lower_bound"] = static_cast<long long>(std::distance(values.begin(), lower));
    result["upper_bound"] = static_cast<long long>(std::distance(values.begin(), upper));
    return result;
}

std::vector<double> unique_numbers(const std::vector<double>& values) {
    // Preserve first-seen order while using a hash set for membership checks.
    std::vector<double> result;
    std::unordered_set<double> seen;
    result.reserve(values.size());
    for (double value : values) {
        if (seen.insert(value).second) {
            result.push_back(value);
        }
    }
    return result;
}

std::vector<std::string> unique_strings(const std::vector<std::string>& values) {
    std::vector<std::string> result;
    std::unordered_set<std::string> seen;
    result.reserve(values.size());
    for (const auto& value : values) {
        if (seen.insert(value).second) {
            result.push_back(value);
        }
    }
    return result;
}

py::dict advanced_statistics(std::vector<double> values) {
    if (values.empty()) {
        throw std::invalid_argument("advanced_statistics requires at least one value");
    }

    const auto count = values.size();
    const double sum = sum_values(values);
    const double mean = sum / static_cast<double>(count);

    double variance = 0.0;
    for (double value : values) {
        const double diff = value - mean;
        variance += diff * diff;
    }
    variance /= static_cast<double>(count);

    std::sort(values.begin(), values.end());
    auto percentile = [&values, count](double p) {
        if (count == 1) {
            return values.front();
        }
        const double pos = p * static_cast<double>(count - 1);
        const auto lower_index = static_cast<std::size_t>(std::floor(pos));
        const auto upper_index = static_cast<std::size_t>(std::ceil(pos));
        const double weight = pos - static_cast<double>(lower_index);
        return values[lower_index] * (1.0 - weight) + values[upper_index] * weight;
    };

    std::map<double, std::size_t> frequencies;
    for (double value : values) {
        ++frequencies[value];
    }
    double mode = values.front();
    std::size_t mode_count = 0;
    for (const auto& [value, frequency] : frequencies) {
        if (frequency > mode_count) {
            mode = value;
            mode_count = frequency;
        }
    }

    py::dict result;
    result["count"] = count;
    result["sum"] = sum;
    result["mean"] = mean;
    result["average"] = mean;
    result["median"] = percentile(0.5);
    result["mode"] = mode;
    result["mode_count"] = mode_count;
    result["variance"] = variance;
    result["stddev"] = std::sqrt(variance);
    result["q1"] = percentile(0.25);
    result["q3"] = percentile(0.75);
    result["min"] = values.front();
    result["max"] = values.back();
    return result;
}

std::vector<double> prefix_sum(const std::vector<double>& values) {
    std::vector<double> result;
    result.reserve(values.size());
    double running_sum = 0.0;
    for (double value : values) {
        running_sum += value;
        result.push_back(running_sum);
    }
    return result;
}

std::vector<double> difference_array(const std::vector<double>& values) {
    if (values.empty()) {
        return {};
    }
    std::vector<double> result;
    result.reserve(values.size());
    result.push_back(values.front());
    for (std::size_t i = 1; i < values.size(); ++i) {
        result.push_back(values[i] - values[i - 1]);
    }
    return result;
}

std::vector<std::vector<double>> matrix_transpose(const std::vector<std::vector<double>>& matrix) {
    if (matrix.empty()) {
        return {};
    }
    const auto cols = matrix.front().size();
    for (const auto& row : matrix) {
        if (row.size() != cols) {
            throw std::invalid_argument("matrix_transpose requires a rectangular matrix");
        }
    }
    std::vector<std::vector<double>> result(cols, std::vector<double>(matrix.size()));
    for (std::size_t i = 0; i < matrix.size(); ++i) {
        for (std::size_t j = 0; j < cols; ++j) {
            result[j][i] = matrix[i][j];
        }
    }
    return result;
}

std::vector<std::vector<double>> matrix_multiply(
    const std::vector<std::vector<double>>& left,
    const std::vector<std::vector<double>>& right
) {
    if (left.empty() || right.empty()) {
        throw std::invalid_argument("matrix_multiply requires non-empty matrices");
    }
    const auto left_cols = left.front().size();
    const auto right_cols = right.front().size();
    for (const auto& row : left) {
        if (row.size() != left_cols) {
            throw std::invalid_argument("left matrix must be rectangular");
        }
    }
    for (const auto& row : right) {
        if (row.size() != right_cols) {
            throw std::invalid_argument("right matrix must be rectangular");
        }
    }
    if (left_cols != right.size()) {
        throw std::invalid_argument("matrix_multiply requires left columns to equal right rows");
    }
    std::vector<std::vector<double>> result(left.size(), std::vector<double>(right_cols, 0.0));
    for (std::size_t i = 0; i < left.size(); ++i) {
        for (std::size_t k = 0; k < left_cols; ++k) {
            for (std::size_t j = 0; j < right_cols; ++j) {
                result[i][j] += left[i][k] * right[k][j];
            }
        }
    }
    return result;
}

std::vector<std::vector<double>> matrix_inverse(const std::vector<std::vector<double>>& matrix) {
    if (matrix.empty()) {
        throw std::invalid_argument("matrix_inverse requires a non-empty square matrix");
    }
    const auto n = matrix.size();
    for (const auto& row : matrix) {
        if (row.size() != n) {
            throw std::invalid_argument("matrix_inverse requires a square matrix");
        }
    }

    // Build the augmented matrix [A | I] and reduce A to I.
    std::vector<std::vector<double>> augmented(n, std::vector<double>(2 * n, 0.0));
    for (std::size_t i = 0; i < n; ++i) {
        for (std::size_t j = 0; j < n; ++j) {
            augmented[i][j] = matrix[i][j];
        }
        augmented[i][n + i] = 1.0;
    }

    constexpr double epsilon = 1e-12;
    for (std::size_t col = 0; col < n; ++col) {
        std::size_t pivot = col;
        for (std::size_t row = col + 1; row < n; ++row) {
            if (std::abs(augmented[row][col]) > std::abs(augmented[pivot][col])) {
                pivot = row;
            }
        }
        if (std::abs(augmented[pivot][col]) < epsilon) {
            throw std::invalid_argument("matrix_inverse requires a non-singular matrix");
        }
        if (pivot != col) {
            std::swap(augmented[pivot], augmented[col]);
        }

        const double pivot_value = augmented[col][col];
        for (std::size_t j = 0; j < 2 * n; ++j) {
            augmented[col][j] /= pivot_value;
        }
        for (std::size_t row = 0; row < n; ++row) {
            if (row == col) {
                continue;
            }
            const double factor = augmented[row][col];
            for (std::size_t j = 0; j < 2 * n; ++j) {
                augmented[row][j] -= factor * augmented[col][j];
            }
        }
    }

    std::vector<std::vector<double>> inverse(n, std::vector<double>(n));
    for (std::size_t i = 0; i < n; ++i) {
        for (std::size_t j = 0; j < n; ++j) {
            inverse[i][j] = augmented[i][n + j];
        }
    }
    return inverse;
}

std::vector<double> top_k(std::vector<double> values, std::size_t k, bool largest) {
    if (k > values.size()) {
        k = values.size();
    }
    if (k == 0) {
        return {};
    }
    if (k < values.size() && largest) {
        std::nth_element(values.begin(), values.begin() + static_cast<std::ptrdiff_t>(k), values.end(), std::greater<double>());
    } else if (k < values.size()) {
        std::nth_element(values.begin(), values.begin() + static_cast<std::ptrdiff_t>(k), values.end());
    }
    values.resize(k);
    if (largest) {
        std::sort(values.begin(), values.end(), std::greater<double>());
    } else {
        std::sort(values.begin(), values.end());
    }
    return values;
}

std::vector<long long> kmp_search(const std::string& text, const std::string& pattern) {
    if (pattern.empty()) {
        throw std::invalid_argument("kmp_search requires a non-empty pattern");
    }
    std::vector<std::size_t> prefix(pattern.size(), 0);
    for (std::size_t i = 1, j = 0; i < pattern.size(); ++i) {
        while (j > 0 && pattern[i] != pattern[j]) {
            j = prefix[j - 1];
        }
        if (pattern[i] == pattern[j]) {
            ++j;
        }
        prefix[i] = j;
    }

    std::vector<long long> matches;
    for (std::size_t i = 0, j = 0; i < text.size(); ++i) {
        while (j > 0 && text[i] != pattern[j]) {
            j = prefix[j - 1];
        }
        if (text[i] == pattern[j]) {
            ++j;
        }
        if (j == pattern.size()) {
            matches.push_back(static_cast<long long>(i + 1 - pattern.size()));
            j = prefix[j - 1];
        }
    }
    return matches;
}

std::vector<double> set_operation_numbers(std::vector<double> left, std::vector<double> right, const std::string& operation) {
    std::sort(left.begin(), left.end());
    std::sort(right.begin(), right.end());
    left.erase(std::unique(left.begin(), left.end()), left.end());
    right.erase(std::unique(right.begin(), right.end()), right.end());

    std::vector<double> result;
    if (operation == "union") {
        std::set_union(left.begin(), left.end(), right.begin(), right.end(), std::back_inserter(result));
    } else if (operation == "intersection") {
        std::set_intersection(left.begin(), left.end(), right.begin(), right.end(), std::back_inserter(result));
    } else if (operation == "difference") {
        std::set_difference(left.begin(), left.end(), right.begin(), right.end(), std::back_inserter(result));
    } else if (operation == "symmetric_difference") {
        std::set_symmetric_difference(left.begin(), left.end(), right.begin(), right.end(), std::back_inserter(result));
    } else {
        throw std::invalid_argument("unsupported set operation");
    }
    return result;
}

std::vector<std::string> set_operation_strings(
    std::vector<std::string> left,
    std::vector<std::string> right,
    const std::string& operation
) {
    std::sort(left.begin(), left.end());
    std::sort(right.begin(), right.end());
    left.erase(std::unique(left.begin(), left.end()), left.end());
    right.erase(std::unique(right.begin(), right.end()), right.end());

    std::vector<std::string> result;
    if (operation == "union") {
        std::set_union(left.begin(), left.end(), right.begin(), right.end(), std::back_inserter(result));
    } else if (operation == "intersection") {
        std::set_intersection(left.begin(), left.end(), right.begin(), right.end(), std::back_inserter(result));
    } else if (operation == "difference") {
        std::set_difference(left.begin(), left.end(), right.begin(), right.end(), std::back_inserter(result));
    } else if (operation == "symmetric_difference") {
        std::set_symmetric_difference(left.begin(), left.end(), right.begin(), right.end(), std::back_inserter(result));
    } else {
        throw std::invalid_argument("unsupported set operation");
    }
    return result;
}

PYBIND11_MODULE(fast_algorithms, m) {
    // The module name must match the extension name in setup.py.
    m.doc() = "Fast numerical algorithms exposed with pybind11";
    m.def("quick_sort", &quick_sort, "Sort a list of numbers");
    m.def("sum_values", &sum_values, "Sum a list of numbers");
    m.def("average_value", &average_value, "Average a list of numbers");
    m.def("min_value", &min_value, "Find the minimum number");
    m.def("max_value", &max_value, "Find the maximum number");
    m.def("binary_search_values", &binary_search_values, "Binary search in a sorted list of numbers");
    m.def("unique_numbers", &unique_numbers, "Remove duplicate numbers while preserving first-seen order");
    m.def("unique_strings", &unique_strings, "Remove duplicate strings while preserving first-seen order");
    m.def("advanced_statistics", &advanced_statistics, "Return median/mode/variance/stddev/quartiles");
    m.def("prefix_sum", &prefix_sum, "Return prefix sums for a list of numbers");
    m.def("difference_array", &difference_array, "Return the difference array for a list of numbers");
    m.def("matrix_transpose", &matrix_transpose, "Transpose a matrix");
    m.def("matrix_multiply", &matrix_multiply, "Multiply two matrices");
    m.def("matrix_inverse", &matrix_inverse, "Invert a square matrix with Gauss-Jordan elimination");
    m.def("top_k", &top_k, "Return the largest or smallest k values");
    m.def("kmp_search", &kmp_search, "Return all KMP string match offsets");
    m.def("set_operation_numbers", &set_operation_numbers, "Run set operations on number arrays");
    m.def("set_operation_strings", &set_operation_strings, "Run set operations on string arrays");
}
