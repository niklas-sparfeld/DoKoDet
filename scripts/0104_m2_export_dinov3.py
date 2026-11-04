"""Attempt the pinned DINOv3 Core ML export with the M0 singleton fix."""

import importlib.metadata
import importlib.util
import json
import platform
from pathlib import Path

from coreml_singleton_int import singleton_int_fix

ROOT = Path(__file__).resolve().parents[1]
PINNED = {
    "coremltools": "9.0",
    "numpy": "2.5.4",
    "torch": "2.7.0",
    "torchvision": "0.22.0",
    "rfdetr": "1.9.4",
    "transformers": "5.22.1",
    "safetensors": "0.8.0",
    "protobuf": "7.36.2",
    "attrs": "26.1.0",
    "cattrs": "26.2.1",
    "pyaml": "26.7.0",
    "sympy": "1.14.0",
    "tqdm": "4.70.1",
    "packaging": "26.3",
}


def main():
    import coremltools as ct

    versions = {name: importlib.metadata.version(name) for name in PINNED}
    if versions != PINNED or platform.python_version() != "3.13.18":
        raise RuntimeError(
            f"Pinned runtime mismatch: Python {platform.python_version()}, {versions}"
        )
    spec = importlib.util.spec_from_file_location(
        "export_0103", ROOT / "scripts/0103_m2_export_dinov3.py"
    )
    exporter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exporter)
    exporter.OUTPUT = ROOT / ".runtime/0104-m2/dinov3-identity.mlpackage"
    exporter.REPORT = ROOT / ".runtime/0104-m2/export-report.json"
    convert = ct.convert

    def patched_convert(*args, **kwargs):
        with singleton_int_fix():
            return convert(*args, **kwargs)

    ct.convert = patched_convert
    try:
        result = exporter.main()
    finally:
        ct.convert = convert
    report = json.loads(exporter.REPORT.read_text())
    report["pinned_versions"] = versions
    report["installed_packages"] = dict(
        sorted(
            (d.metadata["Name"], d.version) for d in importlib.metadata.distributions()
        )
    )
    report["route"] = "guarded singleton constant aten::Int conversion"
    exporter.REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
