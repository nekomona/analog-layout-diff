"""Build an optional C++17 tool and record the exact source/binary hashes."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

root = Path(__file__).resolve().parent
p = argparse.ArgumentParser(); p.add_argument("--output", default=str(root / "build/layoutdiff-native"))
p.add_argument("--compiler", default="g++"); args = p.parse_args()
source, output = root / "src/main.cpp", Path(args.output).resolve()
output.parent.mkdir(parents=True, exist_ok=True)
subprocess.run([args.compiler, "-std=c++17", "-O3", "-DNDEBUG", "-Wall", "-Wextra", "-Wpedantic", str(source), "-o", str(output)], check=True)
version = subprocess.check_output([str(output), "--version"], text=True).strip()
report = {"protocol": version, "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
          "binary_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
          "compiler": subprocess.check_output([args.compiler, "--version"], text=True).splitlines()[0]}
output.with_suffix(output.suffix + ".json").write_text(json.dumps(report, indent=2))
print(json.dumps(report))
