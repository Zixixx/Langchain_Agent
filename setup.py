from __future__ import annotations

"""Build script for the Python package and pybind11 C++ extension."""

import shutil
from pathlib import Path

from pybind11.setup_helpers import Pybind11Extension, build_ext as pybind11_build_ext
from setuptools import find_packages, setup


PACKAGE_METADATA_DIR = Path("package_metadata")
PACKAGE_METADATA_DIR.mkdir(parents=True, exist_ok=True)


class build_ext(pybind11_build_ext):
    """Copy compiled extension artifacts into agent/cpp after building."""

    def build_extensions(self) -> None:
        """Add compiler-specific flags before building extensions."""
        if self.compiler.compiler_type == "msvc":
            for ext in self.extensions:
                ext.extra_compile_args = [*getattr(ext, "extra_compile_args", []), "/utf-8"]
        super().build_extensions()

    def copy_extensions_to_source(self) -> None:
        """Copy editable-install artifacts into the source tree."""
        super().copy_extensions_to_source()
        self._copy_extensions_to_cpp_dir()

    def run(self) -> None:
        """Run the normal build and then copy artifacts into agent/cpp."""
        super().run()
        self._copy_extensions_to_cpp_dir()

    def _copy_extensions_to_cpp_dir(self) -> None:
        """Place the compiled fast_algorithms extension under agent/cpp."""
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
        # C++17 is enough for the current algorithms and mainstream compilers.
        cxx_std=17,
    )
]


setup(
    name="hybrid-ai-agent",
    version="0.1.0",
    packages=find_packages(include=["agent", "agent.*"]),
    py_modules=["main"],
    ext_modules=ext_modules,
    cmdclass={"build_ext": build_ext},
    options={"egg_info": {"egg_base": str(PACKAGE_METADATA_DIR)}},
)
