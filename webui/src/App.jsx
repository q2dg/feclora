import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert, Button, Card, CardBody, CardTitle, Flex, FlexItem, Label, Page,
  PageSection, Progress, Spinner, Stack, StackItem, Tab, Tabs, Title, Toolbar,
  ToolbarContent, ToolbarItem
} from "@patternfly/react-core";
import { SyncAltIcon, ServerIcon, DatabaseIcon, ExclamationTriangleIcon } from "@patternfly/react-icons";
import { Table, Thead, Tbody, Tr, Th, Td } from "@patternfly/react-table";
import { callFeclora } from "./api.js";

const OPERATION_LABELS = {
  capture_disk: "Create a whole-disk image",
  capture_partition: "Create a partition image",
  restore_disk: "Restore a whole-disk image",
  restore_partition: "Restore a partition image",
  clone_disk: "Clone disk to disk",
  clone_partition: "Clone partition to partition"
};

function formatBytes(value) {
  if (!Number.isFinite(value) || value < 0) return "—";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let amount = value, index = 0;
  while (amount >= 1024 && index < units.length - 1) { amount /= 1024; index += 1; }
  return amount.toFixed(index === 0 ? 0 : 1) + " " + units[index];
}

function StatusCard({ title, value, icon, description }) {
  return <Card isFullHeight><CardTitle><Flex alignItems={{ default: "alignItemsCenter" }} gap={{ default: "gapSm" }}><FlexItem>{icon}</FlexItem><FlexItem>{title}</FlexItem></Flex></CardTitle><CardBody><Title headingLevel="h2" size="2xl">{value}</Title><p>{description}</p></CardBody></Card>;
}

function Field({ label, children, help }) {
  return <div className="pf-v5-u-mb-md"><label className="pf-v5-c-form__label pf-v5-u-mb-xs"><span className="pf-v5-c-form__label-text">{label}</span></label>{children}{help && <div className="pf-v5-u-color-200 pf-v5-u-font-size-sm">{help}</div>}</div>;
}

export default function App() {
  const [tab, setTab] = useState("operations");
  const [status, setStatus] = useState(null);
  const [images, setImages] = useState([]);
  const [journals, setJournals] = useState([]);
  const [inventory, setInventory] = useState(null);
  const [security, setSecurity] = useState({});
  const [encrypt, setEncrypt] = useState(false);
  const [sign, setSign] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [operation, setOperation] = useState("capture_disk");
  const [source, setSource] = useState("");
  const [target, setTarget] = useState("");
  const [imageId, setImageId] = useState("");
  const [partitionId, setPartitionId] = useState("");
  const [compression, setCompression] = useState("zstd");
  const [confirmation, setConfirmation] = useState("");
  const [progress, setProgress] = useState(null);
  const [operationResult, setOperationResult] = useState(null);

  const refresh = useCallback(async () => {
    setBusy(true); setError("");
    try {
      const [s, i, j, inv] = await Promise.all([
        callFeclora("status"), callFeclora("images"), callFeclora("journals"), callFeclora("inventory")
      ]);
      setStatus(s); setSecurity(s.security || {}); setImages(i.images || []); setJournals(j.journals || []); setInventory(inv);
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const devices = useMemo(() => {
    const flat = [];
    const visit = (items) => (items || []).forEach((item) => { flat.push(item); visit(item.children); });
    visit(inventory?.devices);
    return flat;
  }, [inventory]);
  const disks = devices.filter((d) => d.type === "disk" && d.path);
  const partitions = devices.filter((d) => d.type === "part" && d.path);
  const isCapture = operation.startsWith("capture_");
  const isRestore = operation.startsWith("restore_");
  const isDisk = operation.endsWith("_disk");
  const deviceOptions = isDisk ? disks : partitions;
  const matchingImages = images.filter((item) => item.image_type === (isDisk ? "disk" : "partition"));
  const expectedConfirmation = operation === "clone_partition"
    ? (source && target ? `ERASE ${target} FROM ${source}` : "")
    : (isRestore || operation.startsWith("clone_")) && target ? `ERASE ${target}` : "";

  useEffect(() => { setConfirmation(""); setProgress(null); setOperationResult(null); }, [operation, source, target, imageId]);

  const runOperation = async (event) => {
    event.preventDefault(); setBusy(true); setError(""); setNotice(""); setProgress(null); setOperationResult(null);
    try {
      let params;
      if (operation === "capture_disk") params = { source, image_id: imageId, compression, encrypt, sign };
      else if (operation === "capture_partition") params = { source, image_id: imageId, partition_id: partitionId || imageId, compression, encrypt, sign };
      else if (isRestore) params = { image_id: imageId, target, confirmation };
      else params = { source, target, confirmation };
      const result = await callFeclora(operation, params, (eventData) => {
        if (eventData.event === "progress") setProgress(eventData);
      });
      setOperationResult(result);
      setNotice("Operation completed successfully.");
      await refresh();
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };

  const initializeSecurity = async () => {
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await callFeclora("initialize_security");
      setSecurity(result);
      setEncrypt(true); setSign(true);
      setNotice("Local encryption and signing keys are ready.");
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };

  const operationReady = isCapture
    ? Boolean(source && imageId && (operation !== "capture_partition" || partitionId || imageId))
    : isRestore ? Boolean(imageId && target && confirmation === expectedConfirmation)
      : Boolean(source && target && source !== target && confirmation === expectedConfirmation);

  return (
    <Page>
      <PageSection variant="default">
        <Toolbar><ToolbarContent>
          <ToolbarItem><Title headingLevel="h1">Feclora</Title></ToolbarItem>
          <ToolbarItem align={{ default: "alignEnd" }}><Button variant="secondary" icon={<SyncAltIcon />} onClick={refresh} isLoading={busy}>Refresh</Button></ToolbarItem>
        </ToolbarContent></Toolbar>
        <p className="pf-v5-u-mt-sm">Rescue, disk imaging and network deployment appliance</p>
      </PageSection>
      {(error || notice) && <PageSection>{error && <Alert variant="danger" title="Operation failed" isInline>{error}</Alert>}{notice && <Alert variant="success" title="Feclora" isInline>{notice}</Alert>}</PageSection>}
      <PageSection>
        {status ? <Flex flexWrap={{ default: "wrap" }} gap={{ default: "gapMd" }}>
          <FlexItem flex={{ default: "1" }}><StatusCard title="Host" value={status.hostname} icon={<ServerIcon />} description={status.platform} /></FlexItem>
          <FlexItem flex={{ default: "1" }}><StatusCard title="Images" value={String(images.length)} icon={<DatabaseIcon />} description="Verified manifest-backed local images" /></FlexItem>
          <FlexItem flex={{ default: "1" }}><StatusCard title="Deployment jobs" value={String(journals.length)} icon={<ExclamationTriangleIcon />} description="Recorded jobs and recovery state" /></FlexItem>
        </Flex> : <Spinner aria-label="Loading Feclora" />}
      </PageSection>
      <PageSection>
        <Tabs activeKey={tab} onSelect={(_event, key) => setTab(key)}>
          <Tab eventKey="operations" title="Imaging operations">
            <Stack hasGutter className="pf-v5-u-pt-lg">
              <StackItem><Title headingLevel="h2" size="xl">Operation wizard</Title><p>Choose an operation, review the selected devices, and explicitly confirm every destructive target.</p></StackItem>
              <StackItem>
                <Card><CardBody>
                  <form onSubmit={runOperation}>
                    <Field label="Operation">
                      <select className="pf-v5-c-form-control" value={operation} onChange={(e) => { setOperation(e.target.value); setSource(""); setTarget(""); setImageId(""); setPartitionId(""); }}>
                        {Object.entries(OPERATION_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                      </select>
                    </Field>
                    {isCapture && <>
                      <Field label={isDisk ? "Source disk" : "Source partition"}>
                        <select className="pf-v5-c-form-control" value={source} onChange={(e) => setSource(e.target.value)}>
                          <option value="">Select a source device…</option>
                          {deviceOptions.map((d) => <option key={d.path} value={d.path}>{d.path} · {formatBytes(d.size_bytes)} · {d.model || d.filesystem || d.type}</option>)}
                        </select>
                      </Field>
                      <Field label="Image identifier" help="Use letters, numbers, dots, underscores or hyphens.">
                        <input className="pf-v5-c-form-control" value={imageId} onChange={(e) => setImageId(e.target.value)} maxLength={128} required />
                      </Field>
                      {!isDisk && <Field label="Partition identifier"><input className="pf-v5-c-form-control" value={partitionId} onChange={(e) => setPartitionId(e.target.value)} maxLength={128} placeholder={imageId || "e.g. rootfs"} /></Field>}
                      <Field label="Compression">
                        <select className="pf-v5-c-form-control" value={compression} onChange={(e) => setCompression(e.target.value)}>
                          <option value="zstd">Zstandard (recommended)</option><option value="lz4">LZ4 (fast)</option><option value="gzip">Gzip</option><option value="none">None</option>
                        </select>
                      </Field>
                      <Field label="Image security">
                        <label><input type="checkbox" checked={encrypt} disabled={!security.age_encryption_available} onChange={(e) => setEncrypt(e.target.checked)} /> Encrypt artifacts with age</label>
                        <br />
                        <label><input type="checkbox" checked={sign} disabled={!security.image_signing_available} onChange={(e) => setSign(e.target.checked)} /> Sign manifest with minisign</label>
                        {!security.age_encryption_available || !security.image_signing_available ? <p className="pf-v5-u-color-200">Initialize local security keys from the System tab to enable these options.</p> : null}
                      </Field>
                    </>}
                    {isRestore && <>
                      <Field label={isDisk ? "Disk image" : "Partition image"}>
                        <select className="pf-v5-c-form-control" value={imageId} onChange={(e) => setImageId(e.target.value)}>
                          <option value="">Select an image…</option>
                          {matchingImages.map((item) => <option key={item.image_id} value={item.image_id}>{item.image_id} · {formatBytes(item.source_size_bytes)}</option>)}
                        </select>
                      </Field>
                      <Field label={isDisk ? "Destination disk" : "Destination partition"}>
                        <select className="pf-v5-c-form-control" value={target} onChange={(e) => setTarget(e.target.value)}>
                          <option value="">Select a destination…</option>
                          {deviceOptions.map((d) => <option key={d.path} value={d.path}>{d.path} · {formatBytes(d.size_bytes)} · {d.model || d.filesystem || d.type}</option>)}
                        </select>
                      </Field>
                    </>}
                    {operation.startsWith("clone_") && <>
                      <Field label={isDisk ? "Source disk" : "Source partition"}>
                        <select className="pf-v5-c-form-control" value={source} onChange={(e) => setSource(e.target.value)}>
                          <option value="">Select source…</option>
                          {deviceOptions.map((d) => <option key={d.path} value={d.path}>{d.path} · {formatBytes(d.size_bytes)} · {d.model || d.filesystem || d.type}</option>)}
                        </select>
                      </Field>
                      <Field label={isDisk ? "Destination disk" : "Destination partition"}>
                        <select className="pf-v5-c-form-control" value={target} onChange={(e) => setTarget(e.target.value)}>
                          <option value="">Select destination…</option>
                          {deviceOptions.filter((d) => d.path !== source).map((d) => <option key={d.path} value={d.path}>{d.path} · {formatBytes(d.size_bytes)} · {d.model || d.filesystem || d.type}</option>)}
                        </select>
                      </Field>
                    </>}
                    {expectedConfirmation && <Alert variant="warning" title="Destructive operation" isInline className="pf-v5-u-mb-md">
                      The destination will be overwritten. Type exactly <strong>{expectedConfirmation}</strong> to authorize this operation.
                    </Alert>}
                    {expectedConfirmation && <Field label="Typed confirmation">
                      <input className="pf-v5-c-form-control" value={confirmation} onChange={(e) => setConfirmation(e.target.value)} autoComplete="off" />
                    </Field>}
                    {busy && progress && <div className="pf-v5-u-mb-md"><Progress value={progress.bytes_total ? Math.min(100, progress.bytes_done / progress.bytes_total * 100) : 0} title="Operation progress" measureLocation="outside" label={formatBytes(progress.bytes_done) + (progress.bytes_total ? " / " + formatBytes(progress.bytes_total) : " processed")} /></div>}
                    <Button type="submit" variant="primary" isDisabled={!operationReady || busy}>{busy ? <><Spinner size="sm" /> Working…</> : "Start operation"}</Button>
                  </form>
                  {operationResult && <Alert variant="success" title="Operation completed" isInline className="pf-v5-u-mt-md"><pre>{JSON.stringify(operationResult, null, 2)}</pre></Alert>}
                </CardBody></Card>
              </StackItem>
              <StackItem><Alert variant="info" title="Safety model" isInline>Feclora rechecks block-device identity, mounted/system-source safety, geometry and image integrity in the storage engine immediately before writing. A browser selection is not treated as authorization by itself.</Alert></StackItem>
            </Stack>
          </Tab>
          <Tab eventKey="inventory" title="Storage inventory">
            <Stack hasGutter className="pf-v5-u-pt-lg"><StackItem><Title headingLevel="h2" size="xl">Block devices and partitions</Title></StackItem>
              <StackItem><Table aria-label="Feclora storage inventory" variant="compact"><Thead><Tr><Th>Device</Th><Th>Type</Th><Th>Size</Th><Th>Model</Th><Th>Filesystem</Th><Th>Mountpoints</Th></Tr></Thead><Tbody>
                {devices.map((d) => <Tr key={d.path}><Td>{d.path}</Td><Td>{d.type}</Td><Td>{formatBytes(d.size_bytes)}</Td><Td>{d.model || "—"}</Td><Td>{d.filesystem || "—"}</Td><Td>{(d.mountpoints || []).join(", ") || "—"}</Td></Tr>)}
                {!devices.length && <Tr><Td colSpan={6}>{inventory ? "No devices found." : "Loading inventory…"}</Td></Tr>}
              </Tbody></Table></StackItem>
            </Stack>
          </Tab>
          <Tab eventKey="images" title="Image repository">
            <Stack hasGutter className="pf-v5-u-pt-lg"><StackItem><Title headingLevel="h2" size="xl">Available images</Title></StackItem>
              <StackItem><Table aria-label="Feclora image repository" variant="compact"><Thead><Tr><Th>Image</Th><Th>Type</Th><Th>Source size</Th><Th>Signature</Th><Th>Encryption</Th><Th>Artifacts</Th></Tr></Thead><Tbody>
                {images.map((item) => <Tr key={item.image_id}><Td>{item.image_id}</Td><Td>{item.image_type}</Td><Td>{formatBytes(item.source_size_bytes)}</Td><Td><Label color={item.signed ? "green" : "orange"}>{item.signed ? "Signed" : "Unsigned"}</Label></Td><Td><Label color={item.encrypted ? "green" : "orange"}>{item.encrypted ? "age" : "Plain"}</Label></Td><Td>{item.artifact_count}</Td></Tr>)}
                {!images.length && <Tr><Td colSpan={6}>No manifest-backed images found.</Td></Tr>}
              </Tbody></Table></StackItem>
            </Stack>
          </Tab>
          <Tab eventKey="deployments" title="Deployment history">
            <Stack hasGutter className="pf-v5-u-pt-lg"><StackItem><Title headingLevel="h2" size="xl">Deployment journals</Title></StackItem>
              <StackItem><Table aria-label="Feclora deployment history" variant="compact"><Thead><Tr><Th>Job ID</Th><Th>State</Th><Th>Interrupted</Th><Th>Clients</Th><Th>Events</Th></Tr></Thead><Tbody>
                {journals.map((job) => <Tr key={job.job_id}><Td>{job.job_id}</Td><Td>{job.job_state}</Td><Td>{job.interrupted ? <Label color="orange">Review required</Label> : "No"}</Td><Td>{Object.entries(job.clients || {}).map(([mac, state]) => mac + ": " + state).join(", ") || "—"}</Td><Td>{job.event_count}</Td></Tr>)}
                {!journals.length && <Tr><Td colSpan={5}>No deployment jobs recorded.</Td></Tr>}
              </Tbody></Table></StackItem>
            </Stack>
          </Tab>
          <Tab eventKey="system" title="System">
            <Stack hasGutter className="pf-v5-u-pt-lg"><StackItem><Title headingLevel="h2" size="xl">System status</Title></StackItem>
              <StackItem><Table aria-label="Feclora services" variant="compact"><Thead><Tr><Th>Component</Th><Th>Status</Th></Tr></Thead><Tbody>
                {Object.entries(status?.services || {}).map(([name, value]) => <Tr key={name}><Td>{name}</Td><Td>{value}</Td></Tr>)}
                <Tr><Td>Server deployment configuration</Td><Td>{status?.server_configured ? "Configured" : "Not configured"}</Td></Tr>
                <Tr><Td>Client deployment configuration</Td><Td>{status?.client_configured ? "Configured" : "Not configured"}</Td></Tr>
              </Tbody></Table></StackItem>
              <StackItem>
                <Title headingLevel="h2" size="lg">Local image security</Title>
                <p>Generate a local Feclora CA, age identity and minisign keypair. Private keys remain on this machine; captured images can then be encrypted and signed by default.</p>
                <Table aria-label="Image security material" variant="compact"><Thead><Tr><Th>Capability</Th><Th>Status</Th></Tr></Thead><Tbody>
                  {Object.entries(security).map(([name, ready]) => <Tr key={name}><Td>{name.replaceAll("_", " ")}</Td><Td><Label color={ready ? "green" : "orange"}>{ready ? "Ready" : "Not initialized"}</Label></Td></Tr>)}
                </Tbody></Table>
                <Button variant="primary" onClick={initializeSecurity} isLoading={busy} isDisabled={busy}>Initialize local security keys</Button>
              </StackItem>
              <StackItem><Alert variant="info" title="Terminal access" isInline>For system setup, network diagnostics and advanced administration, use Cockpit's Terminal page. Do not use the terminal to bypass Feclora's storage safety checks.</Alert></StackItem>
            </Stack>
          </Tab>
        </Tabs>
      </PageSection>
      <PageSection variant="default"><p className="pf-v5-u-color-200">All storage operations use Feclora's shared Python engines. Cockpit is the primary operator interface.</p></PageSection>
    </Page>
  );
}
