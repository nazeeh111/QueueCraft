from setuptools import Extension, setup

setup(
    ext_modules=[Extension(
        "queuecraft._native",
        sources=["native/module.cpp", "src/engine.cpp"],
        include_dirs=["include"],
        depends=["include/queuecraft/engine.hpp"],
        language="c++",
        extra_compile_args=["-std=c++20", "-O2", "-Wall", "-Wextra"],
    )],
)
