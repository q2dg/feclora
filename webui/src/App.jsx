import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert, Bullseye, Button, Card, CardBody, CardTitle, Flex, FlexItem,
  Label, Page, PageSection, Spinner, Stack, StackItem, Tab, Tabs,
  Title, Toolbar, ToolbarContent, ToolbarItem
} from "@patternfly/react-core";
import { SyncAltIcon, ServerIcon, DatabaseIcon, ExclamationTriangleIcon } from "@patternfly/react-icons";
import {
  Table, Thead, Tbody, Tr, Th, Td
} from "@patternfly/react-table";
import { callFeclora } from "./api.js";

function formatBytes(value) {
  if (!Number.isFinite(value) || value < 0) return "—";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let amount = value;
  let index = 0;
  while (amount >= 1024 && index < units.length - 1) {
    amount /= 1024;
    index += 1;
  }
  return amount.toFixed(index === 0 ? 0 : 1) + " " + units[index];
}

function StatusCard({ title, value, icon, description }) {
  return (
    <Card isFullHeight>
      <CardTitle>
        <Flex alignItems={{ default: "alignItemsCenter" }} gap={{ default: "gapSm" }}>
          <FlexItem>{icon}</FlexItem>
          <FlexItem>{title}</FlexItem>
        </Flex>
      </CardTitle>
      <CardBody>
        <Title headingLevel="h2" size="2xl">{value}</Title>
        <p className="pf-v5-u-color-200">{description}</p>
      </CardBody>
    </Card>
  );
}

export default function App() {
  const [tab, setTab] = useState(0);
  const [status, setStatus] = useState(null);
  const [images, setImages] = useState([]);
  const [journals, setJournals] = useState([]);
  const [inventory, setInventory] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const [nextStatus, nextImages, nextJournals] = await Promise.all([
        callFeclora("status"), callFeclora("images"), callFeclora("journals")
      ]);
      setStatus(nextStatus);
      setImages(nextImages.images || []);
      setJournals(nextJournals.journals || []);
    } catch (err) {
      setError(err?.message || String(err));
    } finally {
      setBusy(false);
    }
  }, []);

  const loadInventory = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      setInventory(await callFeclora("inventory"));
    } catch (err) {
      setError(err?.message || String(err));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const devices = useMemo(() => {
    const roots = inventory?.devices || [];
    const flattened = [];
    const visit = (items) => {
      for (const item of items || []) {
        flattened.push(item);
        if (Array.isArray(item.children)) visit(item.children);
      }
    };
    visit(roots);
    return flattened;
  }, [inventory]);

  return (
    <Page>
      <PageSection variant="default">
        <Toolbar>
          <ToolbarContent>
            <ToolbarItem>
              <Title headingLevel="h1">Feclora</Title>
            </ToolbarItem>
            <ToolbarItem align={{ default: "alignEnd" }}>
              <Button variant="secondary" icon={<SyncAltIcon />} onClick={tab === 1 ? loadInventory : refresh} isLoading={busy}>
                Refresh
              </Button>
            </ToolbarItem>
          </ToolbarContent>
        </Toolbar>
        <p className="pf-v5-u-mt-sm">Rescue and deployment appliance · authenticated read-only overview</p>
      </PageSection>
      {error && (
        <PageSection>
          <Alert variant="danger" title="Feclora API error" isInline>{error}</Alert>
        </PageSection>
      )}
      <PageSection>
        {status ? (
          <Flex flexWrap={{ default: "wrap" }} gap={{ default: "gapMd" }}>
            <FlexItem flex={{ default: "1" }}>
              <StatusCard title="Host" value={status.hostname} icon={<ServerIcon />} description={status.platform} />
            </FlexItem>
            <FlexItem flex={{ default: "1" }}>
              <StatusCard title="Images" value={String(images.length)} icon={<DatabaseIcon />} description="Manifest-backed images in the local repository" />
            </FlexItem>
            <FlexItem flex={{ default: "1" }}>
              <StatusCard title="Deployment jobs" value={String(journals.length)} icon={<ExclamationTriangleIcon />} description="Recorded jobs, including interrupted jobs awaiting review" />
            </FlexItem>
          </Flex>
        ) : (
          <Bullseye><Spinner size="xl" aria-label="Loading Feclora status" /></Bullseye>
        )}
      </PageSection>
      <PageSection>
        <Tabs activeKey={tab} onSelect={(_event, key) => {
          setTab(key);
          if (key === 1 && inventory === null) loadInventory();
        }}>
          <Tab eventKey={0} title="Overview">
            <Stack hasGutter className="pf-v5-u-pt-lg">
              <StackItem>
                <Title headingLevel="h2" size="xl">Service configuration</Title>
                <Table aria-label="Feclora service configuration" variant="compact">
                  <Thead><Tr><Th>Component</Th><Th>Status</Th></Tr></Thead>
                  <Tbody>
                    {Object.entries(status?.services || {}).map(([name, value]) => (
                      <Tr key={name}><Td>{name}</Td><Td>{value}</Td></Tr>
                    ))}
                    <Tr><Td>Server deployment configuration</Td><Td>{status?.server_configured ? "Configured" : "Not configured"}</Td></Tr>
                    <Tr><Td>Client deployment configuration</Td><Td>{status?.client_configured ? "Configured" : "Not configured"}</Td></Tr>
                  </Tbody>
                </Table>
              </StackItem>
              <StackItem>
                <Title headingLevel="h2" size="xl">Image repository</Title>
                <Table aria-label="Feclora image repository" variant="compact">
                  <Thead><Tr><Th>Image</Th><Th>Type</Th><Th>Source size</Th><Th>Signature</Th><Th>Encryption</Th><Th>Artifacts</Th></Tr></Thead>
                  <Tbody>
                    {images.map((item) => (
                      <Tr key={item.image_id}>
                        <Td>{item.image_id}</Td><Td>{item.image_type}</Td><Td>{formatBytes(item.source_size_bytes)}</Td>
                        <Td><Label color={item.signed ? "green" : "orange"}>{item.signed ? "Signed" : "Unsigned"}</Label></Td>
                        <Td><Label color={item.encrypted ? "green" : "orange"}>{item.encrypted ? "age" : "Plain"}</Label></Td>
                        <Td>{item.artifact_count}</Td>
                      </Tr>
                    ))}
                    {!images.length && <Tr><Td colSpan={6}>No manifest-backed images found.</Td></Tr>}
                  </Tbody>
                </Table>
              </StackItem>
              <StackItem>
                <Title headingLevel="h2" size="xl">Deployment history</Title>
                <Table aria-label="Feclora deployment history" variant="compact">
                  <Thead><Tr><Th>Job ID</Th><Th>State</Th><Th>Interrupted</Th><Th>Clients</Th><Th>Events</Th></Tr></Thead>
                  <Tbody>
                    {journals.map((job) => (
                      <Tr key={job.job_id}>
                        <Td>{job.job_id}</Td><Td>{job.job_state}</Td>
                        <Td>{job.interrupted ? <Label color="orange">Review required</Label> : "No"}</Td>
                        <Td>{Object.entries(job.clients || {}).map(([mac, state]) => mac + ": " + state).join(", ") || "—"}</Td>
                        <Td>{job.event_count}</Td>
                      </Tr>
                    ))}
                    {!journals.length && <Tr><Td colSpan={5}>No deployment jobs recorded.</Td></Tr>}
                  </Tbody>
                </Table>
              </StackItem>
            </Stack>
          </Tab>
          <Tab eventKey={1} title="Storage inventory">
            <Stack hasGutter className="pf-v5-u-pt-lg">
              <StackItem>
                <Alert variant="info" title="Read-only inventory" isInline>
                  This Cockpit view only inventories devices. Destructive capture, restore and clone workflows remain in the guarded Feclora rescue interface until their web equivalents are implemented and reviewed.
                </Alert>
              </StackItem>
              <StackItem>
                <Table aria-label="Feclora storage inventory" variant="compact">
                  <Thead><Tr><Th>Device</Th><Th>Type</Th><Th>Size</Th><Th>Model</Th><Th>Filesystem</Th><Th>Mountpoints</Th></Tr></Thead>
                  <Tbody>
                    {devices.map((device, index) => (
                      <Tr key={device.path || index}>
                        <Td>{device.path || "—"}</Td><Td>{device.type || "—"}</Td>
                        <Td>{formatBytes(device.size_bytes)}</Td><Td>{device.model || "—"}</Td>
                        <Td>{device.filesystem || "—"}</Td>
                        <Td>{(device.mountpoints || []).join(", ") || "—"}</Td>
                      </Tr>
                    ))}
                    {!devices.length && <Tr><Td colSpan={6}>{inventory ? "No devices found." : "Select Refresh to load storage inventory."}</Td></Tr>}
                  </Tbody>
                </Table>
              </StackItem>
            </Stack>
          </Tab>
        </Tabs>
      </PageSection>
      <PageSection variant="default">
        <p className="pf-v5-u-color-200">Feclora web overview is read-only. Destructive actions require the local rescue workflow and explicit device confirmation.</p>
      </PageSection>
    </Page>
  );
}
