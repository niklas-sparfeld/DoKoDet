from __future__ import annotations

import subprocess
import sys


def test_cardevent_torchvision_import_does_not_load_pyav_before_opencv() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from cardevent.model import _build_backbone; "
                "_build_backbone(pretrained=False); "
                "import cv2, sys; "
                "print('av loaded', 'av' in sys.modules)"
            ),
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    assert "av loaded False" in result.stdout
    assert "objc[" not in result.stderr
