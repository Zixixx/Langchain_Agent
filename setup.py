from __future__ import annotations

"""项目安装脚本：负责声明 Python 包并编译 pybind11 C++ 扩展。"""

import shutil
from pathlib import Path

from pybind11.setup_helpers import Pybind11Extension, build_ext as pybind11_build_ext
from setuptools import find_packages, setup


PACKAGE_METADATA_DIR = Path("data") / "package_metadata"
PACKAGE_METADATA_DIR.mkdir(parents=True, exist_ok=True)


class build_ext(pybind11_build_ext):
    """自定义 build_ext：编译完成后把 .so 复制到 agent/cpp，方便工具层加载。"""

    def copy_extensions_to_source(self) -> None:
        """editable 安装时复制扩展产物到源码目录。"""
        super().copy_extensions_to_source()
        self._copy_extensions_to_cpp_dir()

    def run(self) -> None:
        """普通构建时也执行同样的复制逻辑。"""
        super().run()
        self._copy_extensions_to_cpp_dir()

    def _copy_extensions_to_cpp_dir(self) -> None:
        """把编译出的 fast_algorithms 扩展统一放入 agent/cpp。"""
        cpp_dir = Path("agent") / "cpp"
        cpp_dir.mkdir(parents=True, exist_ok=True)
        for ext in self.extensions:
            built_path = Path(self.get_ext_fullpath(ext.name))
            if not built_path.exists():
                continue
            target = cpp_dir / built_path.name
            if built_path.resolve() == target.resolve():
                continue
            shutil.copy2(built_path, target)
            if built_path.parent.resolve() == Path.cwd().resolve():
                built_path.unlink()


ext_modules = [
    Pybind11Extension(
        "fast_algorithms",
        [str(Path("agent") / "cpp" / "fast_algorithms.cpp")],
        # C++17 足够支撑当前算法实现，也兼容主流编译器。
        cxx_std=17,
    )
]


setup(
    name="hybrid-ai-agent",
    version="0.1.0",
    packages=find_packages(include=["agent", "agent.*"]),
    ext_modules=ext_modules,
    cmdclass={"build_ext": build_ext},
    options={"egg_info": {"egg_base": str(PACKAGE_METADATA_DIR)}},
)
