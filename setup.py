from setuptools import Extension, setup
import hashlib
import json
from pathlib import Path

# Keep portable study/calibration identity tied to the native source actually
# compiled, including when building an sdist on another platform.
manifest=json.loads(Path("queuecraft/native-source.json").read_text())
for name,expected in manifest["source_sha256"].items():
    if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=expected:
        raise RuntimeError(f"native source manifest is stale: {name}")

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
