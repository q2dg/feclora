import React, { useEffect, useState } from "react";
import { Alert, Button, Card, CardBody, CardTitle, Form, FormGroup } from "@patternfly/react-core";
import { callFeclora } from "./api.js";

const LAYOUTS = [
  ["us", "English (US)"], ["us-intl", "English (US, international dead keys)"],
  ["es", "Español"], ["ca", "Català (teclat espanyol)"], ["gl", "Galego (teclado español)"],
  ["eu", "Euskara (teclado español)"], ["fr", "Français"], ["de", "Deutsch"],
  ["it", "Italiano"], ["pt", "Português"], ["br", "Português (Brasil)"],
  ["ru", "Русский"], ["tr", "Türkçe"], ["ar", "العربية"], ["ja", "日本語 (106 teclas)"],
  ["zh", "中文 (US físico)"]
];

export default function KeyboardPreferences() {
  const [layout, setLayout] = useState("us");
  const [current, setCurrent] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let active = true;
    callFeclora("get_keyboard_layout")
      .then((value) => {
        if (!active) return;
        setCurrent(value);
        setLayout(LAYOUTS.some(([id]) => id === value.layout) ? value.layout : "us");
      })
      .catch((err) => { if (active) setError(err?.message || String(err)); });
    return () => { active = false; };
  }, []);

  const apply = async () => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await callFeclora("set_keyboard_layout", { layout });
      setCurrent(result);
      setNotice(`Keyboard layout ${result.layout} applied to the Linux virtual console and saved for subsequent boots.`);
    } catch (err) {
      setError(err?.message || String(err));
    } finally {
      setBusy(false);
    }
  };

  return <Card>
    <CardTitle>Keyboard layout</CardTitle>
    <CardBody>
      <p>Choose the physical keyboard mapping independently of the interface language. This setting updates the persistent Linux virtual-console keymap and the active text console.</p>
      <Form>
        <FormGroup label="Keyboard layout" fieldId="feclora-keyboard-layout">
          <select id="feclora-keyboard-layout" className="pf-v5-c-form-control" value={layout} onChange={(event) => setLayout(event.target.value)} disabled={busy}>
            {LAYOUTS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          </select>
        </FormGroup>
        <Button variant="primary" onClick={apply} isLoading={busy} isDisabled={busy}>Apply keyboard layout</Button>
      </Form>
      {current && <p className="pf-v5-u-color-200 pf-v5-u-font-size-sm">Current Linux keymap: {current.keymap || "unknown"}</p>}
      {notice && <Alert variant="success" title="Keyboard layout applied" isInline className="pf-v5-u-mt-md">{notice}</Alert>}
      {error && <Alert variant="danger" title="Keyboard layout could not be applied" isInline className="pf-v5-u-mt-md">{error}</Alert>}
      <Alert variant="info" title="Scope" isInline className="pf-v5-u-mt-md">The current implementation configures the Linux virtual console. The Cage/Wayland graphical session still needs a separate XKB runtime integration; this control does not claim to change that session yet.</Alert>
    </CardBody>
  </Card>;
}
