import os

import pybind11
from pybind11.setup_helpers import Pybind11Extension, build_ext
from setuptools import Extension, setup


# Round10 local-build compatibility: this Windows workspace has MinGW g++ but
# no MSVC. Pybind11Extension selects MSVC-style /EHsc and /std:c++17 flags on
# Windows even when setuptools is explicitly given --compiler=mingw32. Keep
# upstream behavior everywhere else and use GNU flags only for this opt-in
# local build.
if os.environ.get("KAGSIM_MINGW") == "1":
    extension = Extension(
        "kagsim",
        ["python/kagsim.cpp"],
        include_dirs=[pybind11.get_include()],
        language="c++",
        extra_compile_args=["-O3", "-std=c++17"],
    )
else:
    extension = Pybind11Extension(
        "kagsim", ["python/kagsim.cpp"], cxx_std=17, extra_compile_args=["-O3"]
    )

setup(
    ext_modules=[extension],
    cmdclass={"build_ext": build_ext},
)
