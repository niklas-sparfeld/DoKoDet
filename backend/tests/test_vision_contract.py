import json
from pathlib import Path

from vision_detector.contract import parse_result_bytes

FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "vision" / "v1"


def test_backend_loads_the_canonical_vision_fixtures() -> None:
    ranked = parse_result_bytes((FIXTURE_ROOT / "example-ranked.json").read_bytes())
    abstained = parse_result_bytes((FIXTURE_ROOT / "example-abstained.json").read_bytes())

    assert ranked.model_dump(mode="json")["schema_version"] == "vision-detection/v1"
    assert ranked.calibration == "fixture"
    assert abstained.status == "insufficient_evidence"
    assert json.loads((FIXTURE_ROOT / "example-ranked.json").read_text())["package_id"] == str(
        ranked.package_id
    )
