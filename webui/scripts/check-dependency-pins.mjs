import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const manifest = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8"));
const sections = ["dependencies", "devDependencies"];
const failures = [];

for (const section of sections) {
  for (const [name, version] of Object.entries(manifest[section] ?? {})) {
    if (typeof version !== "string" || !/^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/.test(version)) {
      failures.push(`${section} ${name} must use an exact version, got ${JSON.stringify(version)}`);
    }
  }
}

if (failures.length) {
  for (const failure of failures) console.error(`ERROR: ${failure}`);
  process.exit(1);
}

console.log("Verified exact versions for all direct frontend dependencies.");
