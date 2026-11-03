"""Run the single pinned RF-DETR Core ML compatibility attempt."""

import importlib.metadata
import importlib.util
import json
import platform
import sys
from pathlib import Path

from coreml_singleton_int import singleton_int_fix

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "table_evidence_analyzer/src"), str(ROOT / "backend/src")]
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
EXPECTED_BUNDLE = "05fa6d142c4824bd7bd4aa12ccca9390ff59e02b08dab3701ef9b942e8fb9f5c"


def main():
    import coremltools as ct
    from table_evidence_analyzer.rfdetr_segmentation_training import (
        load_rfdetr_segmentation_bundle,
    )

    actual = {name: importlib.metadata.version(name) for name in PINNED}
    if actual != PINNED or platform.python_version() != "3.13.18":
        raise RuntimeError(
            f"Pinned runtime mismatch: Python {platform.python_version()}, {actual}"
        )
    spec = importlib.util.spec_from_file_location(
        "export_0103", ROOT / "scripts/0103_m1_export_rfdetr.py"
    )
    exporter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exporter)
    bundle = load_rfdetr_segmentation_bundle(exporter.BUNDLE)
    if bundle.manifest["bundle_digest"] != EXPECTED_BUNDLE:
        raise RuntimeError("Frozen RF-DETR bundle digest mismatch")
    exporter.OUTPUT = ROOT / ".runtime/0104-m1/rfdetr-seg-medium.mlpackage"
    exporter.REPORT = ROOT / ".runtime/0104-m1/export-report.json"
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
    report["bundle_digest"] = bundle.manifest["bundle_digest"]
    report["pinned_versions"] = actual
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
