import { readdir, readFile } from "node:fs/promises";
import { relative } from "node:path";
import { error, log } from "node:console";
import process from "node:process";
import { URL } from "node:url";

const root = new URL("../src/visibleCards/", import.meta.url);
const rootFiles = [
  "PipelineVisibleCardEditor.tsx",
  "VisibleCardReviewWorkbench.tsx",
];
const focusedTestPrefix =
  /^(PipelineVisibleCardEditor|VisibleCardReviewWorkbench).*\.test\.tsx$/;
const rootLineLimit = 500;
const focusedTestLineLimit = 800;

async function countNonblankLines(path) {
  const source = await readFile(path, "utf8");
  return source.split(/\r?\n/).filter((line) => line.trim().length > 0).length;
}

const entries = await readdir(root, { withFileTypes: true });
const testFiles = entries
  .filter((entry) => entry.isFile() && focusedTestPrefix.test(entry.name))
  .map((entry) => entry.name)
  .sort();
const failures = [];

for (const [files, limit] of [
  [rootFiles, rootLineLimit],
  [testFiles, focusedTestLineLimit],
]) {
  for (const file of files) {
    const path = new URL(file, root);
    const count = await countNonblankLines(path);
    if (count > limit) {
      failures.push(
        `${relative(new URL("../", import.meta.url).pathname, path.pathname)}: ${count} nonblank lines (limit ${limit})`,
      );
    }
  }
}

if (failures.length > 0) {
  error(`Visible-card module boundary check failed:\n${failures.join("\n")}`);
  process.exitCode = 1;
} else {
  log(
    `Visible-card module boundary check passed: ${rootFiles.length} roots and ${testFiles.length} focused tests are within their line limits.`,
  );
}
