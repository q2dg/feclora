import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const manifest = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8"));
const sections = ["dependencies", "devDependencies"];
const failures = [];

const fedora45Baseline = {
  node: "22.23.1",
  npm: "10.9.8",
  react: "18.3.1",
  "react-dom": "18.3.1",
  "@patternfly/patternfly": "6.7.0",
  "@patternfly/react-core": "6.7.0",
  "@patternfly/react-icons": "6.7.0",
  "@patternfly/react-table": "6.7.0"
};
if (manifest.engines?.node !== fedora45Baseline.node
    || manifest.engines?.npm !== fedora45Baseline.npm
    || manifest.packageManager !== "npm@10.9.8") {
  failures.push("webui Node/npm toolchain must match the Fedora 45 package baseline");
}
for (const [name, version] of Object.entries(fedora45Baseline)) {
  if (name === "node" || name === "npm") continue;
  if (manifest.dependencies?.[name] !== version) {
    failures.push(`Fedora 45 Cockpit baseline requires ${name}@${version}`);
  }
}

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
