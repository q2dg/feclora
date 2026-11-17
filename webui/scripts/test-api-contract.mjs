import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const frontendSource = readFileSync(resolve(root, "webui/src/api.js"), "utf8");
const kickstartSource = readFileSync(resolve(root, "kickstart/feclora-live.ks"), "utf8");
const backendSource = readFileSync(resolve(root, "src/feclora/webapi.py"), "utf8");

const frontendBlock = frontendSource.match(/const ACTIONS = new Set\(\[([\s\S]*?)\]\);/);
assert.ok(frontendBlock, "Could not find the frontend ACTIONS allowlist");
const frontendEntries = [...frontendBlock[1].matchAll(/"([a-z][a-z0-9_]*)"/g)].map((match) => match[1]);
const frontendActions = new Set(frontendEntries);
assert.equal(frontendActions.size, frontendEntries.length, "Frontend ACTIONS contains duplicate entries");

const wrapperBlock = kickstartSource.match(/case "\$\{1:-\}" in([\s\S]*?)\n\s*\*\)/);
assert.ok(wrapperBlock, "Could not find the installed Cockpit wrapper action case");
const wrapperText = wrapperBlock[1].replace(/\)\s*;;/g, "");
const wrapperActions = new Set(
  wrapperText.split(/[|\s]+/).map((entry) => entry.trim()).filter((entry) => /^[a-z][a-z0-9_]*$/.test(entry))
);

const dispatchStart = backendSource.indexOf("def dispatch(request: Any)");
assert.notEqual(dispatchStart, -1, "Could not find the backend dispatch function");
const dispatchSource = backendSource.slice(dispatchStart);
const backendActions = new Set();
for (const match of dispatchSource.matchAll(/\baction\s*==\s*"([a-z][a-z0-9_]*)"/g)) {
  backendActions.add(match[1]);
}
for (const match of dispatchSource.matchAll(/\baction\s+in\s+\{([^}]*)\}/g)) {
  for (const entry of match[1].matchAll(/"([a-z][a-z0-9_]*)"/g)) {
    backendActions.add(entry[1]);
  }
}

const missingFromWrapper = [...frontendActions].filter((action) => !wrapperActions.has(action)).sort();
const missingFromBackend = [...frontendActions].filter((action) => !backendActions.has(action)).sort();
assert.deepEqual(missingFromWrapper, [], `Frontend actions missing from the privileged Kickstart wrapper: ${missingFromWrapper.join(", ")}`);
assert.deepEqual(missingFromBackend, [], `Frontend actions missing from backend dispatch: ${missingFromBackend.join(", ")}`);

console.log(`Verified ${frontendActions.size} frontend API actions against the Kickstart wrapper and backend dispatch.`);
