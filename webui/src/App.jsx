import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  const [trustedClients, setTrustedClients] = useState([]);
  const [revokeIdentity, setRevokeIdentity] = useState("");
  const [revokeConfirmation, setRevokeConfirmation] = useState("");
  const [ageRecipientExportDirectory, setAgeRecipientExportDirectory] = useState("");
  const [ageRecipientExport, setAgeRecipientExport] = useState(null);
  const [clientAgeInventoryPath, setClientAgeInventoryPath] = useState("");
  const [clientAgeInventoryResult, setClientAgeInventoryResult] = useState(null);
  const [extractImageId, setExtractImageId] = useState("");
  const [extractPartitionSelector, setExtractPartitionSelector] = useState("");
  const [extractPartitionResult, setExtractPartitionResult] = useState(null);
  const [images, setImages] = useState([]);
  const [journals, setJournals] = useState([]);
  const [deploymentJobs, setDeploymentJobs] = useState([]);
  const [reconcileConfirmations, setReconcileConfirmations] = useState({});
  const [serviceStatuses, setServiceStatuses] = useState({});
  const [serviceConfirmations, setServiceConfirmations] = useState({});
  const [remoteOperation, setRemoteOperation] = useState("restore");
  const [remoteImageId, setRemoteImageId] = useState("");
  const [remoteTargetType, setRemoteTargetType] = useState("disk");
  const [remoteClients, setRemoteClients] = useState("");
  const [remoteTransport, setRemoteTransport] = useState("unicast");
  const [remoteMulticastGroup, setRemoteMulticastGroup] = useState("239.10.10.10");
  const [remoteMulticastPort, setRemoteMulticastPort] = useState("9000");
  const [remoteInterface, setRemoteInterface] = useState("");
  const [remoteJobResult, setRemoteJobResult] = useState(null);
  const [operations, setOperations] = useState([]);
  const [inventory, setInventory] = useState(null);
  const [networkInterfaces, setNetworkInterfaces] = useState([]);
  const [serverBinding, setServerBinding] = useState("");
  const [serverSetup, setServerSetup] = useState(null);
  const [clientId, setClientId] = useState("");
  const [clientExportDirectory, setClientExportDirectory] = useState("");
  const [clientImageCapture, setClientImageCapture] = useState(false);
  const [clientPrepared, setClientPrepared] = useState(null);
  const [clientHost, setClientHost] = useState("");
  const [clientMacInput, setClientMacInput] = useState("");
  const [clientBundleDirectory, setClientBundleDirectory] = useState("");
  const [clientCaFingerprint, setClientCaFingerprint] = useState("");
  const [clientServerFingerprint, setClientServerFingerprint] = useState("");
  const [clientCompleted, setClientCompleted] = useState(null);
  const [clientRemoteHost, setClientRemoteHost] = useState("");
  const [clientRemoteJobId, setClientRemoteJobId] = useState("");
  const [clientRemoteInspection, setClientRemoteInspection] = useState(null);
  const [clientRemoteTarget, setClientRemoteTarget] = useState("");
  const [clientRemoteConfirmation, setClientRemoteConfirmation] = useState("");
  const [clientRemoteCompression, setClientRemoteCompression] = useState("gzip");
  const [clientRemoteInterface, setClientRemoteInterface] = useState("");
  const [clientRemoteIgmpConfirmed, setClientRemoteIgmpConfirmed] = useState(false);
  const [clientRemoteJobStatus, setClientRemoteJobStatus] = useState(null);
  const [csrPath, setCsrPath] = useState("");
  const [ageRecipientPath, setAgeRecipientPath] = useState("");
  const [clientMac, setClientMac] = useState("");
  const [clientMinisignPath, setClientMinisignPath] = useState("");
  const [csrReview, setCsrReview] = useState(null);
  const [csrConfirmation, setCsrConfirmation] = useState("");
  const [csrApprovalResult, setCsrApprovalResult] = useState(null);
  const [pxeMode, setPxeMode] = useState("proxy");
  const [pxePoolStart, setPxePoolStart] = useState("");
  const [pxePoolEnd, setPxePoolEnd] = useState("");
  const [pxeLease, setPxeLease] = useState("1h");
  const [pxeGateway, setPxeGateway] = useState("");
  const [pxeDns, setPxeDns] = useState("");
  const [pxePort, setPxePort] = useState("8080");
  const [pxeAuthoritative, setPxeAuthoritative] = useState(false);
  const [pxePreflight, setPxePreflight] = useState(null);
  const [pxeProfile, setPxeProfile] = useState(null);
  const [pxeStatus, setPxeStatus] = useState({ active: false, configured: false });
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
      const [s, i, j, op, inv, net, pxe, remote, clients] = await Promise.all([
        callFeclora("status"), callFeclora("images"), callFeclora("journals"), callFeclora("operations"), callFeclora("inventory"), callFeclora("network_interfaces"), callFeclora("pxe_service_status"), callFeclora("deployment_jobs"), callFeclora("server_trusted_clients")
      ]);
      setStatus(s); setSecurity(s.security || {}); setImages(i.images || []); setJournals(j.journals || []); setOperations(op.operations || []); setInventory(inv); setNetworkInterfaces(net.interfaces || []); setPxeStatus(pxe); setDeploymentJobs(remote.jobs || []); setTrustedClients(clients.clients || []);
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
  const clientRemoteJob = clientRemoteInspection?.job;
  const clientRemoteDeviceOptions = clientRemoteJob?.target_type === "partition" ? partitions : disks;
  const clientRemoteConfirmationPhrase = clientRemoteJob && clientRemoteTarget
    ? (clientRemoteJob.operation === "restore"
      ? `ERASE ${clientRemoteTarget} FROM ${clientRemoteInspection.server_identity}`
      : `READ ${clientRemoteTarget} TO ${clientRemoteInspection.server_identity}`)
    : "";
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

  const revokeTrustedClient = async () => {
    if (!revokeIdentity || revokeConfirmation !== `REVOKE ${revokeIdentity}`) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await callFeclora("revoke_server_client", {
        identity: revokeIdentity, confirmation: revokeConfirmation
      });
      setNotice(`Revoked ${result.identity}; future image encryption will exclude this Client.`);
      setRevokeIdentity(""); setRevokeConfirmation("");
      await refresh();
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };

  const extractPartitionFromImage = async () => {
    setBusy(true); setError(""); setNotice(""); setProgress(null); setExtractPartitionResult(null);
    try {
      const result = await callFeclora("extract_partition_image", {
        image_id: extractImageId, selector: extractPartitionSelector
      }, (eventData) => {
        if (eventData.event === "progress") setProgress(eventData);
      });
      setExtractPartitionResult(result);
      setNotice("Partition image extracted and published.");
      await refresh();
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); setProgress(null); }
  };

  const exportServerAgeRecipients = async () => {
    setBusy(true); setError(""); setNotice(""); setAgeRecipientExport(null);
    try {
      const result = await callFeclora("export_server_age_recipients", {
        export_directory: ageRecipientExportDirectory
      });
      setAgeRecipientExport(result); setNotice(result.message);
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };

  const refreshClientAgeRecipients = async () => {
    setBusy(true); setError(""); setNotice(""); setClientAgeInventoryResult(null);
    try {
      const result = await callFeclora("refresh_client_age_recipients", {
        inventory_path: clientAgeInventoryPath
      });
      setClientAgeInventoryResult(result); setNotice(result.message);
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };

  const bootstrapServer = async () => {
    const selected = networkInterfaces.find((item) => item.binding === serverBinding);
    if (!selected) return;
    setBusy(true); setError(""); setNotice(""); setServerSetup(null);
    try {
      const result = await callFeclora("bootstrap_server", {
        interface: selected.interface,
        address: selected.address,
        prefix_length: selected.prefix_length
      });
      setServerSetup(result);
      setNotice(result.message);
      await refresh();
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };

  const prepareClientRequest = async () => {
    setBusy(true); setError(""); setNotice(""); setClientPrepared(null);
    try {
      const result = await callFeclora("prepare_client_request", {
        client_id: clientId, export_directory: clientExportDirectory, image_capture: clientImageCapture
      });
      setClientPrepared(result); setNotice(result.message);
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };

  const completeClientEnrollment = async () => {
    setBusy(true); setError(""); setNotice(""); setClientCompleted(null);
    try {
      const result = await callFeclora("complete_client_enrollment", {
        client_id: clientId, host: clientHost, mac_address: clientMacInput,
        bundle_directory: clientBundleDirectory, ca_fingerprint: clientCaFingerprint,
        server_minisign_sha256: clientServerFingerprint
      });
      setClientCompleted(result); setNotice(result.message);
      await refresh();
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };
  const inspectClientCSR = async () => {
    setBusy(true); setError(""); setNotice(""); setCsrReview(null); setCsrConfirmation("");
    try {
      const result = await callFeclora("inspect_client_csr", {
        csr_path: csrPath, age_recipient_path: ageRecipientPath, mac_address: clientMac,
        minisign_public_path: clientMinisignPath || null
      });
      setCsrReview(result);
      setNotice("CSR signature, Client identity and age recipient inspected. No trust changes have been made.");
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };

  const approveClientCSR = async () => {
    if (!csrReview || csrConfirmation !== csrReview.confirmation_phrase) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await callFeclora("approve_client_csr", {
        csr_path: csrPath, age_recipient_path: ageRecipientPath, mac_address: clientMac,
        minisign_public_path: clientMinisignPath || null, confirmation: csrConfirmation
      });
      setNotice(result.message + " Bundle: " + result.bundle_directory);
      setCsrReview(null); setCsrConfirmation(""); setCsrApprovalResult(result);
      await refresh();
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };
  const validatePXEProfile = async () => {
    const selected = networkInterfaces.find((item) => item.binding === serverBinding);
    if (!selected) return;
    setBusy(true); setError(""); setNotice(""); setPxePreflight(null);
    try {
      const profile = {
        interface: selected.interface,
        address: selected.address,
        prefix_length: selected.prefix_length,
        mode: pxeMode,
        pool_start: pxeMode === "isolated" ? pxePoolStart : null,
        pool_end: pxeMode === "isolated" ? pxePoolEnd : null,
        lease_time: pxeLease,
        gateway: pxeMode === "isolated" && pxeGateway ? pxeGateway : null,
        dns_server: pxeMode === "isolated" && pxeDns ? pxeDns : null,
        http_port: Number(pxePort),
        authoritative_confirmed: pxeMode === "isolated" && pxeAuthoritative
      };
      const result = await callFeclora("validate_pxe_profile", profile);
      setPxeProfile(profile);
      setPxePreflight(result);
      setNotice(result.message);
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };

  const activatePXE = async () => {
    if (!pxeProfile) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await callFeclora("start_pxe_services", pxeProfile);
      setNotice(result.message);
      await refresh();
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };

  const stopPXE = async () => {
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await callFeclora("stop_pxe_services");
      setNotice(result.message);
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

  const createRemoteJob = async (event) => {
    event.preventDefault(); setBusy(true); setError(""); setNotice(""); setRemoteJobResult(null);
    try {
      const authorizedClients = remoteClients.split(/[\s,;]+/).map((value) => value.trim()).filter(Boolean);
      const job = {
        schema_version: 1, job_id: crypto.randomUUID(), operation: remoteOperation,
        image_id: remoteImageId, target_type: remoteTargetType,
        authorized_clients: authorizedClients, network_interface: remoteInterface,
        transport: remoteTransport,
        multicast_group: remoteTransport === "multicast" ? remoteMulticastGroup : null,
        multicast_port: remoteTransport === "multicast" ? Number(remoteMulticastPort) : null,
        start_policy: "manual", expected_clients: null, start_deadline: null
      };
      const result = await callFeclora("create_deployment_job", { job });
      setRemoteJobResult(result); setNotice(result.message); await refresh();
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };

  const reconcileDeploymentJob = async (jobId) => {
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await callFeclora("reconcile_deployment_job", {
        job_id: jobId,
        confirmation: reconcileConfirmations[jobId] || ""
      });
      setNotice(result.message);
      setReconcileConfirmations((current) => ({ ...current, [jobId]: "" }));
      await refresh();
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };

  const refreshDeploymentService = async (jobId) => {
    setBusy(true); setError("");
    try {
      const result = await callFeclora("deployment_service_status", { job_id: jobId });
      setServiceStatuses((current) => ({ ...current, [jobId]: result }));
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };

  const startDeploymentService = async (jobId) => {
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await callFeclora("start_deployment_service", { job_id: jobId });
      setServiceStatuses((current) => ({ ...current, [jobId]: result }));
      setNotice("Persistent deployment service started. Clients may now connect; no disk operation starts until explicit arming.");
      await refresh();
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };

  const sendDeploymentServiceCommand = async (jobId, action, phrase) => {
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await callFeclora(action, { job_id: jobId, confirmation: phrase });
      setNotice(result.message || "Deployment service command accepted.");
      setServiceConfirmations((current) => ({ ...current, [jobId]: "", [jobId + "-cancel"]: "" }));
      await refreshDeploymentService(jobId);
      await refresh();
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };

  const stopDeploymentService = async (jobId) => {
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await callFeclora("stop_deployment_service", { job_id: jobId });
      setServiceStatuses((current) => {
        const next = { ...current }; delete next[jobId]; return next;
      });
      setNotice(result.message);
      await refresh();
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };

  const serviceStatusesRef = useRef(serviceStatuses);
  useEffect(() => { serviceStatusesRef.current = serviceStatuses; }, [serviceStatuses]);
  useEffect(() => {
    const timer = setInterval(() => {
      for (const jobId of Object.keys(serviceStatusesRef.current)) {
        callFeclora("deployment_service_status", { job_id: jobId })
          .then((result) => setServiceStatuses((current) => (
            current[jobId] ? { ...current, [jobId]: result } : current
          )))
          .catch(() => {});
      }
    }, 2000);
    return () => clearInterval(timer);
  }, []);

  const inspectClientRemoteJob = async () => {
    setBusy(true); setError(""); setNotice("");
    setClientRemoteInspection(null); setClientRemoteJobStatus(null);
    try {
      const result = await callFeclora("inspect_remote_job", {
        host: clientRemoteHost, job_id: clientRemoteJobId,
      });
      setClientRemoteInspection(result);
      setClientRemoteTarget("");
      setClientRemoteConfirmation("");
      setClientRemoteIgmpConfirmed(false);
      setNotice("Authenticated job inspected. No Client registration or disk operation has started.");
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };

  const startClientRemoteJob = async () => {
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await callFeclora("start_client_job", {
        host: clientRemoteHost, job_id: clientRemoteInspection.job.job_id,
        device_path: clientRemoteTarget, confirmation: clientRemoteConfirmation,
        compression: clientRemoteCompression,
        network_interface: clientRemoteJob.transport === "multicast"
          ? (networkInterfaces.find((item) => item.binding === clientRemoteInterface)?.interface || null)
          : null,
        igmp_confirmed: clientRemoteJob.transport === "multicast" ? clientRemoteIgmpConfirmed : false,
      });
      setClientRemoteJobStatus(result);
      setNotice(result.phase === "failed"
        ? "Client service started but reported a failure before completion; inspect its status detail."
        : "Client service started. It will report READY only after local target approval, and will write only after the Server operator arms the job.");
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };

  const refreshClientRemoteJobStatus = async () => {
    if (!clientRemoteJobId) return;
    setBusy(true); setError("");
    try {
      const result = await callFeclora("client_job_status", {
        job_id: clientRemoteInspection.job.job_id,
      });
      setClientRemoteJobStatus(result);
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
          <FlexItem flex={{ default: "1" }}><StatusCard title="Images" value={String(images.length)} icon={<DatabaseIcon />} description="Manifest-backed local images" /></FlexItem>
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
                    {busy && progress && <div className="pf-v5-u-mb-md">
                      {progress.bytes_total
                        ? <Progress value={Math.min(100, progress.bytes_done / progress.bytes_total * 100)} title="Operation progress" measureLocation="outside" label={formatBytes(progress.bytes_done) + " / " + formatBytes(progress.bytes_total)} />
                        : <Alert variant="info" isInline title="Operation in progress">{formatBytes(progress.bytes_done)} processed</Alert>}
                    </div>}
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
              <StackItem>
                <Card><CardBody>
                  <Title headingLevel="h3" size="lg">Extract a partition from a whole-disk image</Title>
                  <p>Select a verified whole-disk image and identify one partition by PARTUUID, PARTLABEL or partition node recorded in its partition table. Feclora verifies the source image and publishes a separate partition image; age-encrypted sources are re-encrypted to the current recipient inventory. The source image is not modified.</p>
                  <Field label="Whole-disk source image">
                    <select className="pf-v5-c-form-control" value={extractImageId} onChange={(event) => { setExtractImageId(event.target.value); setExtractPartitionSelector(""); setExtractPartitionResult(null); }}>
                      <option value="">Select whole-disk image…</option>
                      {images.filter((item) => item.image_type === "disk").map((item) => <option key={item.image_id} value={item.image_id}>{item.image_id}{item.signed ? " · signed" : " · unsigned"}</option>)}
                    </select>
                  </Field>
                  <Field label="Partition selector" help="Use a PARTUUID, PARTLABEL, or a partition node such as /dev/sda2 from the captured partition table.">
                    <input className="pf-v5-c-form-control" value={extractPartitionSelector} onChange={(event) => { setExtractPartitionSelector(event.target.value); setExtractPartitionResult(null); }} placeholder="PARTUUID=… or PARTLABEL=…" />
                  </Field>
                  <Button variant="primary" onClick={extractPartitionFromImage} isLoading={busy} isDisabled={busy || !extractImageId || !extractPartitionSelector.trim()}>Extract partition image</Button>
                  {busy && progress && <Progress value={progress.bytes_total ? Math.min(100, progress.bytes_done / progress.bytes_total * 100) : 0} title="Partition extraction progress" measureLocation="outside" label={formatBytes(progress.bytes_done) + " / " + formatBytes(progress.bytes_total)} />}
                  {extractPartitionResult && <Alert variant="success" title="Partition image published" isInline>
                    Source: {extractPartitionResult.source_image_id} · New image: {extractPartitionResult.image_id} · {extractPartitionResult.signed ? "Signed" : "Unsigned"} · {extractPartitionResult.encrypted ? "age-encrypted" : "unencrypted"}
                  </Alert>}
                </CardBody></Card>
              </StackItem>
              <StackItem><Table aria-label="Feclora image repository" variant="compact"><Thead><Tr><Th>Image</Th><Th>Type</Th><Th>Source size</Th><Th>Signature</Th><Th>Encryption</Th><Th>Artifacts</Th></Tr></Thead><Tbody>
                {images.map((item) => <Tr key={item.image_id}><Td>{item.image_id}</Td><Td>{item.image_type}</Td><Td>{formatBytes(item.source_size_bytes)}</Td><Td><Label color={item.signed ? "green" : "orange"}>{item.signed ? "Signed" : "Unsigned"}</Label></Td><Td><Label color={item.encrypted ? "green" : "orange"}>{item.encrypted ? "age" : "Plain"}</Label></Td><Td>{item.artifact_count}</Td></Tr>)}
                {!images.length && <Tr><Td colSpan={6}>No manifest-backed images found.</Td></Tr>}
              </Tbody></Table></StackItem>
            </Stack>
          </Tab>
          <Tab eventKey="remote-jobs" title="Remote jobs">
            <Stack hasGutter className="pf-v5-u-pt-lg">
              <StackItem><Title headingLevel="h2" size="xl">Create a remote deployment job</Title>
                <Alert variant="warning" title="Definition only — service not started; no Client contact or disk I/O" isInline>
                  This step validates and journals a job definition. Start its persistent service separately; Clients then authenticate and approve their own local target through the existing Client-local runtime. Each Client selects and approves its own local destination in the Client jobs tab. No storage operation starts until you explicitly arm the job here after all authorized Clients report READY.
                </Alert>
              </StackItem>
              <StackItem>
                <Card><CardBody><form onSubmit={createRemoteJob}>
                  <Field label="Operation">
                    <select className="pf-v5-c-form-control" value={remoteOperation} onChange={(e) => { setRemoteOperation(e.target.value); setRemoteImageId(""); if (e.target.value === "save") { setRemoteTransport("unicast"); setRemoteTargetType("disk"); } }}>
                      <option value="restore">Restore a signed Server image to Clients</option>
                      <option value="save">Capture whole disks from Clients to Server</option>
                    </select>
                  </Field>
                  <Field label="Image identifier" help={remoteOperation === "restore" ? "Choose an existing signed image." : "New identifier for the image captured from Clients."}>
                    {remoteOperation === "restore" ? <select className="pf-v5-c-form-control" value={remoteImageId} onChange={(e) => setRemoteImageId(e.target.value)}>
                      <option value="">Select signed image…</option>
                      {images.filter((item) => item.image_type === remoteTargetType && item.signed).map((item) => <option key={item.image_id} value={item.image_id}>{item.image_id}</option>)}
                    </select> : <input className="pf-v5-c-form-control" value={remoteImageId} onChange={(e) => setRemoteImageId(e.target.value)} maxLength={128} required />}
                  </Field>
                  {remoteOperation === "restore" && <Field label="Target type">
                    <select className="pf-v5-c-form-control" value={remoteTargetType} onChange={(e) => { setRemoteTargetType(e.target.value); setRemoteImageId(""); }}>
                      <option value="disk">Whole disk</option><option value="partition">Partition</option>
                    </select>
                  </Field>}
                  <Field label="Enrolled Client MAC addresses" help="Enter exactly one MAC for unicast, or at least two for multicast restore. Server verifies each is enrolled.">
                    <textarea className="pf-v5-c-form-control" rows={3} value={remoteClients} onChange={(e) => setRemoteClients(e.target.value)} required placeholder="52:54:00:12:34:56" />
                  </Field>
                  <Field label="Server network interface">
                    <select className="pf-v5-c-form-control" value={remoteInterface} onChange={(e) => setRemoteInterface(e.target.value)} required>
                      <option value="">Select interface…</option>
                      {networkInterfaces.map((item) => <option key={item.interface} value={item.interface}>{item.interface} · {item.address}</option>)}
                    </select>
                  </Field>
                  <Field label="Transport">
                    <select className="pf-v5-c-form-control" value={remoteTransport} onChange={(e) => setRemoteTransport(e.target.value)}>
                      <option value="unicast">Authenticated unicast</option>
                      <option value="multicast" disabled={remoteOperation === "save"}>UDPcast multicast restore</option>
                    </select>
                  </Field>
                  {remoteTransport === "multicast" && <>
                    <Field label="Administratively scoped multicast group"><input className="pf-v5-c-form-control" value={remoteMulticastGroup} onChange={(e) => setRemoteMulticastGroup(e.target.value)} /></Field>
                    <Field label="UDPcast even portbase"><input className="pf-v5-c-form-control" type="number" min="1024" max="65534" step="2" value={remoteMulticastPort} onChange={(e) => setRemoteMulticastPort(e.target.value)} /></Field>
                    <Alert variant="warning" title="Multicast transport limitation" isInline>UDPcast data packets are not encrypted or authenticated. mTLS protects the control plane, not the multicast data stream. Use only on a trusted, isolated deployment network.</Alert>
                  </>}
                  <Field label="Start policy"><input className="pf-v5-c-form-control" value="Manual — exact job-specific typed confirmation required" readOnly /></Field>
                  <Button type="submit" variant="primary" isDisabled={busy || !remoteImageId || !remoteClients.trim() || !remoteInterface}>Validate and save job definition</Button>
                </form>
                {remoteJobResult && <Alert variant="success" title="Job definition persisted" isInline className="pf-v5-u-mt-md">{remoteJobResult.message}<p>Job ID: {remoteJobResult.job_id}</p></Alert>}
                </CardBody></Card>
              </StackItem>
              <StackItem><Title headingLevel="h2" size="lg">Persisted remote jobs</Title>
                <p>Interrupted jobs can only be closed for audit after you have inspected every Client and destination manually. This does not resume or retry disk operations.</p>
                <Table aria-label="Persisted remote deployment jobs" variant="compact"><Thead><Tr><Th>Job ID</Th><Th>Operation</Th><Th>Image</Th><Th>Target</Th><Th>Transport</Th><Th>State</Th><Th>Client progress</Th><Th>Recovery</Th><Th>Events</Th><Th>Service and execution</Th></Tr></Thead><Tbody>
                  {deploymentJobs.map((job) => <Tr key={job.job_id}><Td>{job.job_id}</Td><Td>{job.operation}</Td><Td>{job.image_id}</Td><Td>{job.target_type}</Td><Td>{job.transport}</Td><Td>{job.job_state}</Td><Td>{Object.entries(job.clients || {}).map(([mac, client]) => mac + ": " + client.state).join(", ") || "Not connected"}</Td><Td>{job.interrupted ? <Stack hasGutter><StackItem><Label color="orange">Review required · no auto-resume</Label></StackItem><StackItem><input className="pf-v5-c-form-control" aria-label={`Reconciliation confirmation for ${job.job_id}`} placeholder={`RECONCILE ${job.job_id}`} value={reconcileConfirmations[job.job_id] || ""} onChange={(event) => setReconcileConfirmations((current) => ({ ...current, [job.job_id]: event.target.value }))} /></StackItem><StackItem><Button variant="secondary" size="sm" isDisabled={busy || reconcileConfirmations[job.job_id] !== `RECONCILE ${job.job_id}`} onClick={() => reconcileDeploymentJob(job.job_id)}>Close for audit</Button></StackItem></Stack> : "—"}</Td><Td>{job.event_count}</Td><Td>
                    <Stack hasGutter>
                      <StackItem>
                        <Button size="sm" variant="secondary" isDisabled={busy || job.interrupted || (!job.service_active && job.job_state !== "created")} onClick={() => startDeploymentService(job.job_id)}>{job.service_active ? "Connect / inspect service" : "Start / connect service"}</Button>
                      </StackItem>
                      {serviceStatuses[job.job_id] && <>
                        <StackItem><Label color={serviceStatuses[job.job_id].job_state === "completed" ? "green" : serviceStatuses[job.job_id].job_state === "failed" ? "red" : "blue"}>{serviceStatuses[job.job_id].job_state}</Label></StackItem>
                        <StackItem>Control listener: {(serviceStatuses[job.job_id].listener_address || []).join(":") || "unavailable"}</StackItem>
                        <StackItem>Execution worker: {serviceStatuses[job.job_id].worker_active ? "active" : "idle"}</StackItem>
                        <StackItem><Button size="sm" variant="link" isDisabled={busy} onClick={() => refreshDeploymentService(job.job_id)}>Refresh live status</Button></StackItem>
                        <StackItem>Connected Clients: {serviceStatuses[job.job_id].client_count ?? (serviceStatuses[job.job_id].clients || []).length}</StackItem>
                        <StackItem>{(serviceStatuses[job.job_id].clients || []).map((client) => {
                          const progress = client.progress;
                          const mib = (bytes) => (bytes / (1024 * 1024)).toFixed(1);
                          return <div key={client.mac_address}>
                            <p>{client.mac_address}: {client.state}</p>
                            {progress && <p>
                              {progress.phase}: {mib(progress.completed_bytes)} MiB
                              {progress.total_bytes !== null ? " / " + mib(progress.total_bytes) + " MiB" : ""}
                              {" · " + mib(progress.bytes_per_second || 0) + " MiB/s"}
                              {progress.total_bytes > 0 ? " · " + Math.min(100, Math.round(progress.completed_bytes * 100 / progress.total_bytes)) + "%" : ""}
                            </p>}
                          </div>;
                        })}</StackItem>
                        {serviceStatuses[job.job_id].clients_truncated && <StackItem><Alert variant="warning" isInline title="Client list truncated">The local service status response is capped at 128 Client records.</Alert></StackItem>}
                        {serviceStatuses[job.job_id].multicast_preflight?.warnings?.length > 0 && <StackItem><Alert variant="warning" isInline title="Multicast network warnings">{serviceStatuses[job.job_id].multicast_preflight.warnings.join(" ")}</Alert></StackItem>}
                        {serviceStatuses[job.job_id].multicast_preflight?.error && <StackItem><Alert variant="danger" isInline title="Multicast preflight failed">{serviceStatuses[job.job_id].multicast_preflight.error}</Alert></StackItem>}
                        {serviceStatuses[job.job_id].job_state === "created" && <>
                          <StackItem><input className="pf-v5-c-form-control" aria-label={"Arm confirmation for " + job.job_id} placeholder={job.transport === "multicast" ? "ARM MULTICAST " + job.job_id + " IGMP-VERIFIED" : "ARM " + job.job_id} value={serviceConfirmations[job.job_id] || ""} onChange={(event) => setServiceConfirmations((current) => ({ ...current, [job.job_id]: event.target.value }))} /></StackItem>
                          <StackItem><Button size="sm" variant="primary" isDisabled={busy || serviceConfirmations[job.job_id] !== (job.transport === "multicast" ? "ARM MULTICAST " + job.job_id + " IGMP-VERIFIED" : "ARM " + job.job_id)} onClick={() => sendDeploymentServiceCommand(job.job_id, "arm_deployment_job", serviceConfirmations[job.job_id])}>Arm and execute</Button></StackItem>
                          <StackItem><input className="pf-v5-c-form-control" aria-label={"Cancel confirmation for " + job.job_id} placeholder={"CANCEL " + job.job_id} value={serviceConfirmations[job.job_id + "-cancel"] || ""} onChange={(event) => setServiceConfirmations((current) => ({ ...current, [job.job_id + "-cancel"]: event.target.value }))} /></StackItem>
                          <StackItem><Button size="sm" variant="secondary" isDisabled={busy || serviceConfirmations[job.job_id + "-cancel"] !== "CANCEL " + job.job_id} onClick={() => sendDeploymentServiceCommand(job.job_id, "cancel_deployment_job", serviceConfirmations[job.job_id + "-cancel"])}>Cancel before arm</Button></StackItem>
                        </>}
                        {!(serviceStatuses[job.job_id].worker_active) && serviceStatuses[job.job_id].job_state !== "running" && !(serviceStatuses[job.job_id].clients || []).some((client) => client.state === "running") && <StackItem><Button size="sm" variant="link" isDisabled={busy} onClick={() => stopDeploymentService(job.job_id)}>Stop service</Button></StackItem>}
                        {serviceStatuses[job.job_id].last_error && <StackItem><Alert variant="danger" isInline title="Execution error">{serviceStatuses[job.job_id].last_error}</Alert></StackItem>}
                      </>}
                    </Stack>
                  </Td></Tr>)}
                  {!deploymentJobs.length && <Tr><Td colSpan={10}>No remote job definitions recorded.</Td></Tr>}
                </Tbody></Table>
              </StackItem>
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
          <Tab eventKey="operation-log" title="Operation log">
            <Stack hasGutter className="pf-v5-u-pt-lg"><StackItem><Title headingLevel="h2" size="xl">Local operation history</Title><p>Last 200 durable operation journal events. A started entry without a terminal event requires operator review.</p></StackItem>
              <StackItem><Table aria-label="Local operation history" variant="compact"><Thead><Tr><Th>Timestamp</Th><Th>Operation</Th><Th>Target</Th><Th>Image</Th><Th>Status</Th><Th>Operation ID</Th></Tr></Thead><Tbody>
                {operations.map((item, index) => <Tr key={item.operation_id + "-" + item.status + "-" + index}><Td>{item.timestamp || "—"}</Td><Td>{item.operation || "—"}</Td><Td>{item.target || "—"}</Td><Td>{item.image_id || "—"}</Td><Td><Label color={item.status === "completed" ? "green" : item.status === "failed" ? "red" : "orange"}>{item.status || "unknown"}</Label></Td><Td>{item.operation_id || "—"}</Td></Tr>)}
                {!operations.length && <Tr><Td colSpan={6}>No local operations recorded.</Td></Tr>}
              </Tbody></Table></StackItem>
            </Stack>
          </Tab>
          <Tab eventKey="server" title="Server setup">
            <Stack hasGutter className="pf-v5-u-pt-lg">
              <StackItem>
                <Title headingLevel="h2" size="xl">Initialize deployment Server identity</Title>
                <p>Select an IPv4 address currently assigned to the management interface. Feclora will initialize its managed CA, mTLS Server certificate, age recipient identity and minisign signing keys.</p>
                <Alert variant="info" title="This is the identity bootstrap step only" isInline>
                  It does not enable DHCP/ProxyDHCP, configure PXE boot services, open firewall ports or start a deployment. Client enrollment is a separate, explicit removable-media trust ceremony below.
                </Alert>
              </StackItem>
              <StackItem>
                <Field label="Server network interface and address" help="Only active non-loopback IPv4 addresses assigned to this host are offered.">
                  <select className="pf-v5-c-form-control" value={serverBinding} onChange={(e) => { setServerBinding(e.target.value); setPxePreflight(null); setPxeProfile(null); }}>
                    <option value="">Select an interface/address…</option>
                    {networkInterfaces.map((item) => <option key={item.binding} value={item.binding}>{item.interface} · {item.address}/{item.prefix_length}</option>)}
                  </select>
                </Field>
                {networkInterfaces.length === 0 && <Alert variant="warning" title="No eligible IPv4 interface found" isInline>Connect and configure the intended management interface, then refresh this page.</Alert>}
                {networkInterfaces.find((item) => item.binding === serverBinding)?.dhcp_server && <Alert variant="warning" title="Existing DHCP server detected" isInline>
                  NetworkManager reports DHCP server {networkInterfaces.find((item) => item.binding === serverBinding).dhcp_server} on this interface. This identity-only step will not change DHCP settings; review the network topology before enabling PXE or DHCP services.
                </Alert>}
                <Button variant="primary" onClick={bootstrapServer} isLoading={busy} isDisabled={busy || !serverBinding || status?.server_configured}>Initialize Server identity</Button>
              </StackItem>
              {status?.server_configured && <StackItem><Alert variant="success" title="Server configuration exists" isInline>The existing configuration is not overwritten by this wizard. Continue with the remaining Server and PXE setup once those Cockpit workflows are available.</Alert></StackItem>}
              {status?.server_configured && <StackItem>
                <Title headingLevel="h2" size="xl">Trusted Client inventory and revocation</Title>
                <p>Review enrolled TLS identities and their authorized MAC addresses. Revocation removes the identity-to-MAC authorization, image-signing trust and age recipient from future captures. It does not terminate established TLS sessions or invalidate old encrypted images.</p>
                <Table aria-label="Trusted Feclora Clients" variant="compact">
                  <Thead><Tr><Th>Client identity</Th><Th>Authorized MAC</Th><Th>Image capture</Th></Tr></Thead>
                  <Tbody>
                    {trustedClients.map((client) => <Tr key={client.identity}><Td>{client.identity}</Td><Td>{client.mac_address}</Td><Td>{client.image_capture ? "Authorized" : "Restore only"}</Td></Tr>)}
                    {!trustedClients.length && <Tr><Td colSpan={3}>No enrolled Clients.</Td></Tr>}
                  </Tbody>
                </Table>
                {trustedClients.length > 0 && <>
                <Field label="Export updated age recipient inventory to mounted USB directory">
                  <input className="pf-v5-c-form-control" value={ageRecipientExportDirectory} onChange={(event) => { setAgeRecipientExportDirectory(event.target.value); setAgeRecipientExport(null); }} placeholder="/run/media/liveuser/USB" />
                </Field>
                <Button variant="secondary" onClick={exportServerAgeRecipients} isLoading={busy} isDisabled={busy || !ageRecipientExportDirectory}>Export age-recipients.txt</Button>
                {ageRecipientExport && <Alert variant="success" title="Recipient inventory exported" isInline>{ageRecipientExport.path} · {ageRecipientExport.recipient_count} recipients · SHA-256 {ageRecipientExport.sha256}</Alert>}
                  <Field label="Client identity to revoke">
                    <select className="pf-v5-c-form-control" value={revokeIdentity} onChange={(event) => { setRevokeIdentity(event.target.value); setRevokeConfirmation(""); }}>
                      <option value="">Select an enrolled Client…</option>
                      {trustedClients.map((client) => <option key={client.identity} value={client.identity}>{client.identity} · {client.mac_address}</option>)}
                    </select>
                  </Field>
                  {revokeIdentity && <>
                    <Alert variant="warning" title="Revocation is not retroactive" isInline>Existing TLS sessions may remain active until disconnected. Previously exported recipient lists and encrypted images are unchanged; distribute the refreshed recipient inventory to remaining Clients.</Alert>
                    <Field label={`Type exactly: REVOKE ${revokeIdentity}`}>
                      <input className="pf-v5-c-form-control" value={revokeConfirmation} onChange={(event) => setRevokeConfirmation(event.target.value)} />
                    </Field>
                    <Button variant="danger" onClick={revokeTrustedClient} isLoading={busy} isDisabled={busy || revokeConfirmation !== `REVOKE ${revokeIdentity}`}>Revoke Client identity</Button>
                  </>}
                </>}
              </StackItem>}
              {serverSetup && <StackItem><Card><CardBody><Title headingLevel="h3" size="lg">Server identity status</Title><p>{serverSetup.message}</p><p>Bind address: {serverSetup.bind_address}:{serverSetup.port}</p><p>Certificate identity: {serverSetup.server_identity}</p><p>Enrolled Clients: {serverSetup.enrolled_clients}</p></CardBody></Card></StackItem>}
              <StackItem>
                <Title headingLevel="h2" size="xl">Trusted Clients · Approve CSR</Title>
                <p>Prepare an enrollment request on the Client and inspect it here from removable media. The Client private TLS and age keys never leave the Client.</p>
                <Field label="Client CSR file" help="Absolute path under /run/media, /media or /mnt.">
                  <input className="pf-v5-c-form-control" value={csrPath} onChange={(e) => { setCsrPath(e.target.value); setCsrReview(null); }} />
                </Field>
                <Field label="Client age recipient file">
                  <input className="pf-v5-c-form-control" value={ageRecipientPath} onChange={(e) => { setAgeRecipientPath(e.target.value); setCsrReview(null); }} placeholder="/run/media/.../feclora-client.age-recipient" />
                </Field>
                <Field label="Client unicast MAC address">
                  <input className="pf-v5-c-form-control" value={clientMac} onChange={(e) => { setClientMac(e.target.value); setCsrReview(null); }} placeholder="00:11:22:33:44:55" />
                </Field>
                <Field label="Client minisign public key (optional)" help="Provide only if this Client may capture images for the Server.">
                  <input className="pf-v5-c-form-control" value={clientMinisignPath} onChange={(e) => { setClientMinisignPath(e.target.value); setCsrReview(null); }} placeholder="/run/media/.../client.minisign.pub" />
                </Field>
                <Button variant="secondary" onClick={inspectClientCSR} isLoading={busy} isDisabled={busy || !csrPath || !ageRecipientPath || !clientMac}>Inspect enrollment request</Button>
                {csrApprovalResult && <Card className="pf-v5-u-mt-md"><CardBody>
                  <Alert variant="success" title="Client enrolled" isInline>{csrApprovalResult.message}</Alert>
                  <p>Identity: {csrApprovalResult.identity} · MAC: {csrApprovalResult.mac_address}</p>
                  <p>Response bundle: {csrApprovalResult.bundle_directory}</p>
                  <p>Feclora CA SHA-256 fingerprint (verify on Client):</p><code>{csrApprovalResult.ca_fingerprint}</code>
                  <p>Server minisign public-key SHA-256 fingerprint (verify on Client):</p><code>{csrApprovalResult.server_minisign_sha256}</code>
                  <p>Client image capture: {csrApprovalResult.image_capture_enabled ? "authorized" : "not authorized"}</p>
                </CardBody></Card>}
                {csrReview && <Card className="pf-v5-u-mt-md"><CardBody>
                  <Alert variant="warning" title="Review this identity before enrollment" isInline>Identity: {csrReview.identity} · MAC: {csrReview.mac_address}. Image capture permission: {csrReview.image_capture_enabled === "true" ? "enabled" : "not granted"}. No enrollment has occurred yet.</Alert>
                  <p>To approve, type this exact phrase:</p><code>{csrReview.confirmation_phrase}</code>
                  <Field label="Explicit enrollment confirmation">
                    <input className="pf-v5-c-form-control" value={csrConfirmation} onChange={(e) => setCsrConfirmation(e.target.value)} />
                  </Field>
                  <Button variant="danger" onClick={approveClientCSR} isLoading={busy} isDisabled={busy || csrConfirmation !== csrReview.confirmation_phrase}>Approve CSR, enroll Client and export response bundle</Button>
                </CardBody></Card>}
              </StackItem>
              <StackItem>
                <Title headingLevel="h2" size="xl">PXE network profile preflight</Title>
                <p>Validate a proposed PXE network configuration before any service is started. Select the same management interface above.</p>
                <Field label="DHCP mode">
                  <select className="pf-v5-c-form-control" value={pxeMode} onChange={(e) => { setPxeMode(e.target.value); setPxePreflight(null); }}>
                    <option value="proxy">ProxyDHCP (existing DHCP server assigns addresses)</option>
                    <option value="isolated">Isolated authoritative DHCP (dedicated VLAN only)</option>
                  </select>
                </Field>
                {pxeMode === "isolated" && <>
                  <Alert variant="warning" title="Authoritative DHCP can disrupt an existing network" isInline>Only use isolated mode on a dedicated, verified network segment where Feclora is the sole DHCP authority. Never enable it on a shared LAN.</Alert>
                  <Field label="DHCP pool start"><input className="pf-v5-c-form-control" value={pxePoolStart} onChange={(e) => setPxePoolStart(e.target.value)} placeholder="192.0.2.100" /></Field>
                  <Field label="DHCP pool end"><input className="pf-v5-c-form-control" value={pxePoolEnd} onChange={(e) => setPxePoolEnd(e.target.value)} placeholder="192.0.2.180" /></Field>
                  <Field label="Lease duration"><input className="pf-v5-c-form-control" value={pxeLease} onChange={(e) => setPxeLease(e.target.value)} placeholder="1h" /></Field>
                  <Field label="Gateway (optional)"><input className="pf-v5-c-form-control" value={pxeGateway} onChange={(e) => setPxeGateway(e.target.value)} placeholder="192.0.2.254" /></Field>
                  <Field label="DNS server (optional)"><input className="pf-v5-c-form-control" value={pxeDns} onChange={(e) => setPxeDns(e.target.value)} placeholder="192.0.2.254" /></Field>
                  <label><input type="checkbox" checked={pxeAuthoritative} onChange={(e) => setPxeAuthoritative(e.target.checked)} /> I confirm this is an isolated VLAN and Feclora is its only DHCP server.</label>
                </>}
                <Field label="HTTP boot asset port"><input className="pf-v5-c-form-control" type="number" min="1" max="65535" value={pxePort} onChange={(e) => setPxePort(e.target.value)} /></Field>
                <Button variant="primary" onClick={validatePXEProfile} isLoading={busy} isDisabled={busy || !serverBinding || (pxeMode === "isolated" && (!pxePoolStart || !pxePoolEnd || !pxeAuthoritative))}>Run PXE preflight</Button>
              </StackItem>
              {pxeStatus.configured && <StackItem><Alert variant="warning" title="PXE runtime is configured" isInline>Stop the PXE services when network boot is no longer required, or if the service state is incomplete. <Button variant="danger" onClick={stopPXE} isLoading={busy} isDisabled={busy}>Stop PXE services and restore firewall</Button></Alert></StackItem>}
              {pxePreflight && <StackItem><Card><CardBody>
                <Alert variant="success" title="PXE preflight passed" isInline>{pxePreflight.message}</Alert>
                <p>Interface: {pxePreflight.interface} · {pxePreflight.address}/{pxePreflight.prefix_length}</p>
                <p>Subnet: {pxePreflight.subnet} · Mode: {pxePreflight.mode}</p>
                <p>iPXE URL: {pxePreflight.http_url}</p>
                {pxePreflight.warnings.map((warning, index) => <Alert key={index} variant="warning" title="Network topology warning" isInline>{warning}</Alert>)}
                {pxeStatus.active ? <Alert variant="success" title="PXE services active" isInline>Interface {pxeStatus.interface}; dnsmasq and Caddy are managed as temporary services.</Alert> : pxeStatus.configured ? <Alert variant="warning" title="PXE runtime needs inspection" isInline>The profile is recorded but one or more services are not active. Stop the profile to restore firewall state before trying again.</Alert> : <Alert variant="info" title="Preflight only" isInline>No services have been started yet. Activation opens a temporary firewalld zone bound only to the selected interface; it is not enabled at boot.</Alert>}{!pxeStatus.configured && <Button variant="primary" onClick={activatePXE} isLoading={busy} isDisabled={busy || !pxeProfile}>Activate PXE services</Button>}
              </CardBody></Card></StackItem>}
            </Stack>
          </Tab>
          <Tab eventKey="client" title="Client enrollment">
            <Stack hasGutter className="pf-v5-u-pt-lg">
              <StackItem><Title headingLevel="h2" size="xl">Client removable-media enrollment</Title><p>Prepare endpoint-local TLS and age keys, transfer only public request material to the Server, then verify and install the signed response bundle.</p></StackItem>
              {status?.client_configured && <StackItem>
                <Title headingLevel="h3" size="lg">Refresh Server age recipient inventory</Title>
                <p>After a Client is revoked or enrolled, export the current inventory from the Server to removable media, then install it here. The file must contain this Client's own age public recipient; private keys remain local.</p>
                <Field label="Mounted removable-media age-recipients.txt path">
                  <input className="pf-v5-c-form-control" value={clientAgeInventoryPath} onChange={(event) => { setClientAgeInventoryPath(event.target.value); setClientAgeInventoryResult(null); }} placeholder="/run/media/liveuser/USB/age-recipients.txt" />
                </Field>
                <Button variant="primary" onClick={refreshClientAgeRecipients} isLoading={busy} isDisabled={busy || !clientAgeInventoryPath}>Verify and refresh inventory</Button>
                {clientAgeInventoryResult && <Alert variant="success" title="Age recipient inventory refreshed" isInline>{clientAgeInventoryResult.message} · {clientAgeInventoryResult.recipient_count} recipients · SHA-256 {clientAgeInventoryResult.sha256}</Alert>}
              </StackItem>}
              {status?.client_configured ? <StackItem><Alert variant="success" title="Client already configured" isInline>This endpoint has a deployment Client configuration. Cockpit certificate renewal is not yet available; this wizard will not overwrite the existing identity. Age recipient inventory refresh is available below.</Alert></StackItem> : <>
                <StackItem>
                  <Title headingLevel="h3" size="lg">1. Prepare enrollment request</Title>
                  <Field label="Client identifier"><input className="pf-v5-c-form-control" value={clientId} onChange={(e) => { setClientId(e.target.value); setClientPrepared(null); }} placeholder="lab-01" /></Field>
                  <Field label="Mounted removable-media directory" help="For example /run/media/liveuser/USB. The directory must be an actual mounted filesystem.">
                    <input className="pf-v5-c-form-control" value={clientExportDirectory} onChange={(e) => setClientExportDirectory(e.target.value)} placeholder="/run/media/liveuser/USB" />
                  </Field>
                  <label><input type="checkbox" checked={clientImageCapture} onChange={(e) => setClientImageCapture(e.target.checked)} /> Authorize this Client to capture images and send them to the Server (generates a local minisign keypair)</label>
                  <Button variant="primary" onClick={prepareClientRequest} isLoading={busy} isDisabled={busy || !clientId || !clientExportDirectory}>Prepare request</Button>
                  {clientPrepared && <Card className="pf-v5-u-mt-md"><CardBody>
                    <Alert variant="success" title="Enrollment request prepared" isInline>{clientPrepared.message}</Alert>
                    <p>Identity: {clientPrepared.identity}</p><p>CSR: {clientPrepared.csr_file}</p>
                    <p>Public age recipient: {clientPrepared.age_recipient_file}</p>
                    {clientPrepared.minisign_public_file && <p>Public minisign key: {clientPrepared.minisign_public_file}</p>}
                    <p>Private TLS key remains at {clientPrepared.private_key_stays_local}; it was not exported.</p>
                  </CardBody></Card>}
                </StackItem>
                <StackItem>
                  <Title headingLevel="h3" size="lg">2. Complete enrollment from Server response</Title>
                  <Field label="Client identifier (same as preparation)"><input className="pf-v5-c-form-control" value={clientId} onChange={(e) => setClientId(e.target.value)} /></Field>
                  <Field label="Feclora Server address"><input className="pf-v5-c-form-control" value={clientHost} onChange={(e) => setClientHost(e.target.value)} placeholder="192.0.2.1 or hostname" /></Field>
                  <Field label="This Client unicast MAC address"><input className="pf-v5-c-form-control" value={clientMacInput} onChange={(e) => setClientMacInput(e.target.value)} placeholder="02:11:22:33:44:55" /></Field>
                  <Field label="Mounted Server response bundle directory"><input className="pf-v5-c-form-control" value={clientBundleDirectory} onChange={(e) => setClientBundleDirectory(e.target.value)} placeholder="/run/media/liveuser/USB" /></Field>
                  <Field label="Feclora CA SHA-256 fingerprint" help="Copy the fingerprint displayed in the Server approval result."><input className="pf-v5-c-form-control" value={clientCaFingerprint} onChange={(e) => setClientCaFingerprint(e.target.value)} /></Field>
                  <Field label="Server minisign public-key SHA-256 fingerprint" help="Copy the fingerprint displayed in the Server approval result."><input className="pf-v5-c-form-control" value={clientServerFingerprint} onChange={(e) => setClientServerFingerprint(e.target.value)} /></Field>
                  <Button variant="primary" onClick={completeClientEnrollment} isLoading={busy} isDisabled={busy || !clientId || !clientHost || !clientMacInput || !clientBundleDirectory || !clientCaFingerprint || !clientServerFingerprint}>Verify and install Client identity</Button>
                  {clientCompleted && <Alert variant="success" title="Client enrollment complete" isInline>{clientCompleted.message} Identity: {clientCompleted.identity}. Image capture: {clientCompleted.image_capture_enabled ? "authorized" : "not authorized"}.</Alert>}
                </StackItem>
              </>}
            </Stack>
          </Tab>
          <Tab eventKey="client-jobs" title="Client jobs">
            <Stack hasGutter className="pf-v5-u-pt-lg">
              <StackItem><Title headingLevel="h2" size="xl">Remote job on this Client</Title>
                <p>Inspect the Server job over enrolled mTLS, choose this machine's local target, type the exact destructive/read confirmation, then connect. The Client reports READY after approval and waits for the Server operator to arm it.</p>
              </StackItem>
              {!status?.client_configured && <StackItem><Alert variant="warning" title="Client enrollment required" isInline>Complete Client removable-media enrollment before inspecting or joining a remote job.</Alert></StackItem>}
              {status?.client_configured && <>
                <StackItem>
                  <Field label="Server host override" help="Leave blank to use the enrolled Server host. The enrolled Server certificate identity is still verified.">
                    <input className="pf-v5-c-form-control" value={clientRemoteHost} onChange={(event) => setClientRemoteHost(event.target.value)} placeholder="Use enrolled Server host" />
                  </Field>
                  <Field label="Remote job UUID">
                    <input className="pf-v5-c-form-control" value={clientRemoteJobId} onChange={(event) => { setClientRemoteJobId(event.target.value); setClientRemoteInspection(null); setClientRemoteJobStatus(null); }} placeholder="xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx" />
                  </Field>
                  <Button variant="primary" onClick={inspectClientRemoteJob} isLoading={busy} isDisabled={busy || !clientRemoteJobId}>Inspect authenticated job</Button>
                  <Button variant="link" onClick={refreshClientRemoteJobStatus} isLoading={busy} isDisabled={busy || !clientRemoteJobId}>Check existing Client job status</Button>
                </StackItem>
                {clientRemoteJob && <StackItem>
                  <Card><CardBody>
                    <Title headingLevel="h3" size="lg">Authenticated Server job</Title>
                    <p>Operation: {clientRemoteJob.operation} · Image: {clientRemoteJob.image_id}</p>
                    <p>Target type: {clientRemoteJob.target_type} · Transport: {clientRemoteJob.transport}</p>
                    <p>Server identity: {clientRemoteInspection.server_identity}</p>
                    <p>Authorized Client MACs: {(clientRemoteJob.authorized_clients || []).join(", ")}</p>
                    {clientRemoteJob.transport === "multicast" && <Alert variant="warning" title="Multicast network requirements" isInline>All authorized Clients must be READY before arming. Confirm UDP multicast reachability, switch IGMP snooping and an active querier on the same VLAN. UDPcast data packets are not encrypted or authenticated; mTLS protects only the control channel.</Alert>}
                    {clientRemoteJob.transport === "multicast" && <label><input type="checkbox" checked={clientRemoteIgmpConfirmed} onChange={(event) => setClientRemoteIgmpConfirmed(event.target.checked)} /> I verified IGMP snooping and an active querier on this VLAN, and confirmed all Clients are on the same multicast network.</label>}
                    {(clientRemoteJob.transport === "unicast" || clientRemoteJob.transport === "multicast") && <>
                      {clientRemoteJob.transport === "multicast" && <Field label="Local multicast receive interface" help="Choose the Client interface on the same L2 multicast VLAN as the Server. Interface, route and udp-receiver preflight run again before READY.">
                        <select className="pf-v5-c-form-control" value={clientRemoteInterface} onChange={(event) => { setClientRemoteInterface(event.target.value); setClientRemoteIgmpConfirmed(false); }}>
                          <option value="">Select receive interface…</option>
                          {networkInterfaces.map((item) => <option key={item.binding} value={item.binding}>{item.interface} · {item.address}/{item.prefix_length}</option>)}
                        </select>
                      </Field>}
                      <Field label={clientRemoteJob.target_type === "partition" ? "Local destination partition" : "Local destination disk"} help="The selected block device is rechecked against live inventory immediately before READY. Root, mounted or busy destinations are rejected by the storage engine.">
                        <select className="pf-v5-c-form-control" value={clientRemoteTarget} onChange={(event) => { setClientRemoteTarget(event.target.value); setClientRemoteConfirmation(""); }}>
                          <option value="">Select local target…</option>
                          {clientRemoteDeviceOptions.map((device) => <option key={device.path} value={device.path}>{device.path} · {device.model || device.name || device.type} · {device.size_bytes || ""}</option>)}
                        </select>
                      </Field>
                      {clientRemoteJob.operation === "save" && <Field label="Capture compression">
                        <select className="pf-v5-c-form-control" value={clientRemoteCompression} onChange={(event) => setClientRemoteCompression(event.target.value)}>
                          <option value="none">None</option><option value="gzip">gzip</option><option value="xz">xz</option>
                        </select>
                      </Field>}
                      {clientRemoteConfirmationPhrase && <Alert variant="warning" title="Type the exact local authorization phrase" isInline>{clientRemoteConfirmationPhrase}</Alert>}
                      <Field label="Local target confirmation">
                        <input className="pf-v5-c-form-control" value={clientRemoteConfirmation} onChange={(event) => setClientRemoteConfirmation(event.target.value)} placeholder="Type the phrase shown above exactly" />
                      </Field>
                      <Button variant="primary" onClick={startClientRemoteJob} isLoading={busy} isDisabled={busy || !clientRemoteTarget || !clientRemoteConfirmationPhrase || clientRemoteConfirmation !== clientRemoteConfirmationPhrase || (clientRemoteJob.transport === "multicast" && (!clientRemoteInterface || !clientRemoteIgmpConfirmed))}>Connect and wait for Server arm</Button>
                    </>}
                  </CardBody></Card>
                </StackItem>}
                {clientRemoteJobStatus && <StackItem>
                  <Card><CardBody>
                    <Title headingLevel="h3" size="lg">Client service status</Title>
                    <Label color={clientRemoteJobStatus.phase === "completed" ? "green" : clientRemoteJobStatus.phase === "failed" || clientRemoteJobStatus.phase === "interrupted" ? "red" : "blue"}>{clientRemoteJobStatus.phase}</Label>
                    <p>{clientRemoteJobStatus.detail}</p>
                    {clientRemoteJobStatus.target_description && <p>Approved target: {clientRemoteJobStatus.target_description}</p>}
                    {clientRemoteJobStatus.progress && <p>Progress: {clientRemoteJobStatus.progress.completed_bytes} / {clientRemoteJobStatus.progress.total_bytes ?? "unknown"} bytes</p>}
                    {clientRemoteJobStatus.multicast_preflight?.warnings?.length > 0 && <Alert variant="warning" title="Multicast switch checks" isInline>{clientRemoteJobStatus.multicast_preflight.warnings.join(" ")}</Alert>}
                    {clientRemoteJobStatus.multicast_warnings?.length > 0 && <Alert variant="warning" title="Multicast switch checks" isInline>{clientRemoteJobStatus.multicast_warnings.join(" ")}</Alert>}
                    {clientRemoteJobStatus.interrupted && <Alert variant="danger" title="Client service interrupted" isInline>No automatic reconnect or disk-operation resume is available. Inspect the local destination and Server journal before creating another job.</Alert>}
                    <Button variant="secondary" onClick={refreshClientRemoteJobStatus} isLoading={busy} isDisabled={busy}>Refresh Client status</Button>
                  </CardBody></Card>
                </StackItem>}
              </>}
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
