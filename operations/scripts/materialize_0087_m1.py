from __future__ import annotations

import argparse
import json
from pathlib import Path

from doko_operations.rfdetr_segmentation_materialization import (
    load_rfdetr_segmentation_materialization,
    materialize_rfdetr_segmentation_dataset,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Materialize and verify the frozen Epic 0087 M1 real mask view."
    )
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("docs/reports/0087-M0_Reviewed_RF_DETR_Campaign_Manifest.json"),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(".runtime/rfdetr-segmentation-0087"),
    )
    args = parser.parse_args()

    repository = args.repository_root.expanduser().resolve()
    result = materialize_rfdetr_segmentation_dataset(
        args.manifest,
        repository_root=repository,
        output_root=args.output_root,
    )
    manifest = load_rfdetr_segmentation_materialization(result.view_root)
    print(
        json.dumps(
            {
                **result.to_mapping(),
                "verified_materialization_digest": manifest["materialization_digest"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
