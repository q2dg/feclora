import assert from "node:assert/strict";
import { LANGUAGES, translate } from "../src/i18n.js";

const localizedKeys = [
  "Operation",
  "Image repository",
  "Image identifier",
  "Typed confirmation",
  "Repository ID",
  "Credential type",
  "Mount access",
  "IPv4 address",
  "Verified S3 P2V export",
  "S3 source repository",
  "Committed P2V image",
  "Filesystem destination repository",
  "Self-contained recovery media",
  "Base Feclora Live ISO path",
  "Whole-disk image to embed",
  "Target disk WWN (recommended)",
  "Target disk serial (alternative or additional selector)",
  "Confirm ISO creation",
  "Typed build confirmation",
  "P2V output",
  "Server setup",
  "Client jobs",
  "Persisted remote jobs",
  "Encrypted repository credentials",
  "S3 object repositories",
  "PXE network profile preflight",
  "Remote job on this Client",
  "Authenticated Server job",
  "Client service status",
  "Local repository",
  "Select a disk image…",
  "Select local target…",
  "Select Client interface/address…",
  "Select partition…",
  "Select an S3 repository…",
  "Select a QCOW2 image…",
];

for (const [language] of LANGUAGES) {
  if (language === "en") continue;
  for (const key of localizedKeys) {
    const value = translate(language, key);
    assert.ok(value && value !== key, `${language} is missing translation for: ${key}`);
  }
}

assert.equal(translate("en", "A deliberately unknown key"), "A deliberately unknown key");
console.log(`Verified ${localizedKeys.length} translated UI keys across ${LANGUAGES.length - 1} non-English locales.`);
