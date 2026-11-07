import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from check_0112_boundaries import production_test_support_imports


class ProductionImportGuardTests(unittest.TestCase):
    def _scan_web_import(
        self, source_text: str, filename: str = "web/src/pipeline/consumer.tsx"
    ) -> list[str]:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / filename
            source.parent.mkdir(parents=True)
            source.write_text(source_text)
            return production_test_support_imports(root)

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

    def test_rejects_dynamic_import_outside_feature_folders(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "web/src/analysis/loader.ts"
            source.parent.mkdir(parents=True)
            source.write_text(
                'export const load = () => import("./runControlsTestFixtures");\n'
            )

            self.assertEqual(
                production_test_support_imports(root),
                ["web/src/analysis/loader.ts"],
            )

    def test_rejects_static_fixture_imports_with_source_extensions(self) -> None:
        for extension in ("ts", "tsx"):
            with self.subTest(extension=extension):
                self.assertEqual(
                    self._scan_web_import(
                        f'import {{ fixture }} from "./runControlsTestFixtures.{extension}";\n'
                    ),
                    ["web/src/pipeline/consumer.tsx"],
                )

    def test_rejects_dynamic_fixture_imports_with_source_extensions(self) -> None:
        for extension in ("ts", "tsx"):
            with self.subTest(extension=extension):
                self.assertEqual(
                    self._scan_web_import(
                        f'export const load = () => import("./runControlsTestFixtures.{extension}");\n'
                    ),
                    ["web/src/pipeline/consumer.tsx"],
                )

    def test_rejects_template_literal_dynamic_fixture_imports(self) -> None:
        for module in (
            "./runControlsTestFixtures.ts",
            "./runControlsTestFixtures.tsx",
            "./__tests__/fixtures",
        ):
            with self.subTest(module=module):
                self.assertEqual(
                    self._scan_web_import(
                        f"export const load = () => import(`{module}`);\n"
                    ),
                    ["web/src/pipeline/consumer.tsx"],
                )

    def test_rejects_imports_from_tests_directories(self) -> None:
        for statement in (
            'import { fixture } from "./__tests__/fixtures";\n',
            'export { fixture } from "./__tests__/fixtures.ts";\n',
            'export const load = () => import("./__tests__/fixtures.tsx");\n',
            'const fixture = require("./__tests__/fixtures");\n',
        ):
            with self.subTest(statement=statement):
                self.assertEqual(
                    self._scan_web_import(statement),
                    ["web/src/pipeline/consumer.tsx"],
                )

    def test_keeps_legitimate_and_test_only_imports_out_of_violations(self) -> None:
        self.assertEqual(
            self._scan_web_import('import { helper } from "./helpers";\n'),
            [],
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            test_source = root / "web/src/pipeline/__tests__/consumer.test.ts"
            fixture_source = root / "web/src/pipeline/runControlsTestFixtures.ts"
            test_source.parent.mkdir(parents=True)
            test_source.write_text(
                'import { fixture } from "../runControlsTestFixtures.ts";\n'
            )
            fixture_source.write_text("export const fixture = {};\n")
            self.assertEqual(production_test_support_imports(root), [])

    def test_ignores_comments_and_ordinary_strings(self) -> None:
        source = """
// import "./runControlsTestFixtures.ts";
/* export { fixture } from "./__tests__/fixtures"; */
const example = 'import("./runControlsTestFixtures.tsx")';
const template = `import("./__tests__/fixtures")`;
"""
        self.assertEqual(self._scan_web_import(source), [])


if __name__ == "__main__":
    unittest.main()
