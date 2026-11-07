import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from check_0112_boundaries import production_test_support_imports


class ProductionImportGuardTests(unittest.TestCase):
    def test_rejects_backend_import_from_test_support(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "backend/src/dokodetector_backend/worker.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                "from dokodetector_backend.test_support.job_participants import FakeParticipant\n"
            )

            self.assertEqual(
                production_test_support_imports(root),
                ["backend/src/dokodetector_backend/worker.py"],
            )

    def test_rejects_adjacent_web_test_fixture_import(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "web/src/pipeline/RunControls.tsx"
            source.parent.mkdir(parents=True)
            source.write_text('import { stage } from "./runControlsTestFixtures";\n')

            self.assertEqual(
                production_test_support_imports(root),
                ["web/src/pipeline/RunControls.tsx"],
            )


if __name__ == "__main__":
    unittest.main()
