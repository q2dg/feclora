import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert, Button, Card, CardBody, CardTitle, Flex, FlexItem, Label, Page,
  PageSection, Progress, Spinner, Stack, StackItem, Tab, Tabs, Title, Toolbar,
  ToolbarContent, ToolbarItem
} from "@patternfly/react-core";
import { SyncAltIcon, ServerIcon, DatabaseIcon, ExclamationTriangleIcon } from "@patternfly/react-icons";
import { Table, Thead, Tbody, Tr, Th, Td } from "@patternfly/react-table";
import { callFeclora, waitForLocalOperation } from "./api.js";

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
  const [caBackupDirectory, setCaBackupDirectory] = useState("");
  const [caBackupRecipient, setCaBackupRecipient] = useState("");
  const [caBackupResult, setCaBackupResult] = useState(null);
  const [caBackupInspectionFile, setCaBackupInspectionFile] = useState("");
  const [caBackupIdentityFile, setCaBackupIdentityFile] = useState("");
  const [caBackupInspection, setCaBackupInspection] = useState(null);
  const [clientAgeInventoryPath, setClientAgeInventoryPath] = useState("");
  const [clientAgeInventoryResult, setClientAgeInventoryResult] = useState(null);
  const [extractImageId, setExtractImageId] = useState("");
  const [extractPartitionSelector, setExtractPartitionSelector] = useState("");
  const [extractPartitionResult, setExtractPartitionResult] = useState(null);
  const [extractLayout, setExtractLayout] = useState(null);
  const [restoreLayoutPreview, setRestoreLayoutPreview] = useState(null);
  const [images, setImages] = useState([]);
  const [journals, setJournals] = useState([]);
  const [deploymentJobs, setDeploymentJobs] = useState([]);
  const [reconcileConfirmations, setReconcileConfirmations] = useState({});
  const [serviceStatuses, setServiceStatuses] = useState({});
  const [serviceConfirmations, setServiceConfirmations] = useState({});
  const [remoteOperation, setRemoteOperation] = useState("restore");
  const [remoteImageId, setRemoteImageId] = useState("");
  const [remoteSourceDevice, setRemoteSourceDevice] = useState("");
  const [remoteTargetType, setRemoteTargetType] = useState("disk");
  const [remoteClients, setRemoteClients] = useState("");
  const [remoteTransport, setRemoteTransport] = useState("unicast");
  const [remoteMulticastGroup, setRemoteMulticastGroup] = useState("239.10.10.10");
  const [remoteMulticastPort, setRemoteMulticastPort] = useState("9000");
  const [remoteInterface, setRemoteInterface] = useState("");
  const [remoteJobResult, setRemoteJobResult] = useState(null);
  const [operations, setOperations] = useState([]);
  const [cancellingOperationId, setCancellingOperationId] = useState("");
  const [remoteRepositories, setRemoteRepositories] = useState([]);
  const [systemdCredentials, setSystemdCredentials] = useState([]);
  const [sftpRepositories, setSftpRepositories] = useState([]);
  const [sftpRepositoryId, setSftpRepositoryId] = useState("");
  const [sftpHost, setSftpHost] = useState("");
  const [sftpUsername, setSftpUsername] = useState("");
  const [sftpRemoteDirectory, setSftpRemoteDirectory] = useState("/images");
  const [sftpPort, setSftpPort] = useState("22");
  const [sftpIdentity, setSftpIdentity] = useState("");
  const [sftpKnownHosts, setSftpKnownHosts] = useState("");
  const [sftpPublishImageId, setSftpPublishImageId] = useState("");
  const [sftpRemoteInventory, setSftpRemoteInventory] = useState(null);
  const [sftpRemoteInspection, setSftpRemoteInspection] = useState(null);
  const [publishAfterCapture, setPublishAfterCapture] = useState(false);
  const [credentialId, setCredentialId] = useState("");
  const [credentialKind, setCredentialKind] = useState("ssh-key");
  const [credentialSourceFile, setCredentialSourceFile] = useState("");
  const [credentialReplace, setCredentialReplace] = useState(false);
  const [repositoryId, setRepositoryId] = useState("");
  const [repositoryEditing, setRepositoryEditing] = useState(false);
  const [selectedRepositoryId, setSelectedRepositoryId] = useState("");
  const [repositoryImages, setRepositoryImages] = useState([]);
  const [repositoryProvider, setRepositoryProvider] = useState("sshfs");
  const [repositoryHost, setRepositoryHost] = useState("");
  const [repositoryPath, setRepositoryPath] = useState("/images");
  const [repositoryUsername, setRepositoryUsername] = useState("");
  const [repositoryIdentity, setRepositoryIdentity] = useState("");
  const [repositoryKnownHosts, setRepositoryKnownHosts] = useState("");
  const [repositoryCredentials, setRepositoryCredentials] = useState("");
  const [repositoryRcloneRemote, setRepositoryRcloneRemote] = useState("");
  const [repositoryPort, setRepositoryPort] = useState("22");
  const [repositoryReadOnly, setRepositoryReadOnly] = useState(true);
  const [imageVerification, setImageVerification] = useState({});
  const [inventory, setInventory] = useState(null);
  const [networkInterfaces, setNetworkInterfaces] = useState([]);
  const [networkProfiles, setNetworkProfiles] = useState([]);
  const [networkProfileUuid, setNetworkProfileUuid] = useState("");
  const [networkMethod, setNetworkMethod] = useState("auto");
  const [networkAddress, setNetworkAddress] = useState("");
  const [networkPrefix, setNetworkPrefix] = useState("24");
  const [networkGateway, setNetworkGateway] = useState("");
  const [networkDns, setNetworkDns] = useState("");
  const [networkApplyResult, setNetworkApplyResult] = useState(null);
  const [serverBinding, setServerBinding] = useState("");
  const [serverSetup, setServerSetup] = useState(null);
  const [serverRenewConfirmation, setServerRenewConfirmation] = useState("");
  const [serverRenewResult, setServerRenewResult] = useState(null);
  const [serverRotateConfirmation, setServerRotateConfirmation] = useState("");
  const [serverRotateResult, setServerRotateResult] = useState(null);
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
  const [clientRenewalPrepared, setClientRenewalPrepared] = useState(null);
  const [clientRenewalCompleted, setClientRenewalCompleted] = useState(null);
  const [clientRenewalExportDirectory, setClientRenewalExportDirectory] = useState("");
  const [clientRenewalBundleDirectory, setClientRenewalBundleDirectory] = useState("");
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
  const [csrRenewal, setCsrRenewal] = useState(false);
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
  const [restoreFromSftp, setRestoreFromSftp] = useState(false);
  const [partitionId, setPartitionId] = useState("");
  const [compression, setCompression] = useState("zstd");
  const [confirmation, setConfirmation] = useState("");
  const [progress, setProgress] = useState(null);
  const [operationResult, setOperationResult] = useState(null);

  const applyNetworkProfile = async (event) => {
    event.preventDefault();
    const selected = networkProfiles.find((profile) => profile.uuid === networkProfileUuid);
    if (!selected?.device) { setError("Select an active NetworkManager profile with an associated device."); return; }
    setBusy(true); setError(""); setNotice(""); setNetworkApplyResult(null);
    try {
      const result = await callFeclora("apply_network_profile", {
        uuid: networkProfileUuid, interface: selected.device, method: networkMethod,
        address: networkMethod === "manual" ? networkAddress : null,
        prefix_length: networkMethod === "manual" ? Number(networkPrefix) : null,
        gateway: networkMethod === "manual" && networkGateway ? networkGateway : null,
        dns: networkMethod === "manual" && networkDns.trim() ? networkDns.split(",").map((value) => value.trim()).filter(Boolean) : [],
        rollback_timeout: 120
      });
      setNetworkApplyResult(result);
      setNotice("Network profile applied and verified. NetworkManager checkpoint committed.");
      await refresh();
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };

  const verifyImage = async (imageId) => {
    setImageVerification((current) => ({ ...current, [imageId]: { loading: true } }));
    try {
      const report = await callFeclora("verify_image", { image_id: imageId, ...(selectedRepositoryId ? { repository_id: selectedRepositoryId } : {}) });
      setImageVerification((current) => ({ ...current, [imageId]: { loading: false, report } }));
    } catch (err) {
      setImageVerification((current) => ({ ...current, [imageId]: { loading: false, error: err?.message || String(err) } }));
    }
  };

  const refresh = useCallback(async () => {
    setBusy(true); setError("");
    try {
      const [s, i, j, op, inv, net, profiles, pxe, remote, clients, repositories, credentials, sftpSaved] = await Promise.all([
        callFeclora("status"), callFeclora("images"), callFeclora("journals"), callFeclora("local_operations"), callFeclora("inventory"), callFeclora("network_interfaces"), callFeclora("network_connection_profiles"), callFeclora("pxe_service_status"), callFeclora("deployment_jobs"), callFeclora("server_trusted_clients"), callFeclora("remote_repositories"), callFeclora("systemd_credentials"), callFeclora("sftp_repositories")
      ]);
      setStatus(s); setSecurity(s.security || {}); setImages(i.images || []); setJournals(j.journals || []); setOperations(op.operations || []); setInventory(inv); setNetworkInterfaces(net.interfaces || []); setNetworkProfiles(profiles.profiles || []); setPxeStatus(pxe); setDeploymentJobs(remote.jobs || []); setTrustedClients(clients.clients || []); setRemoteRepositories(repositories.repositories || []); setSystemdCredentials(credentials.credentials || []); setSftpRepositories(sftpSaved.repositories || []);
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const cancelLocalOperation = async (operationId) => {
    if (!window.confirm("Request cancellation of this operation? A running restore or clone cannot be rolled back and may leave its destination partially written.")) return;
    setCancellingOperationId(operationId); setError(""); setNotice("");
    try {
      const result = await callFeclora("cancel_local_operation", { operation_id: operationId });
      setNotice(result.requested
        ? "Cancellation requested. Feclora is stopping the worker and its child processes; the operation log will show the final state."
        : "This operation is already cancelled.");
      const history = await callFeclora("local_operations");
      setOperations(history.operations || []);
    } catch (err) { setError(err?.message || String(err)); }
    finally { setCancellingOperationId(""); }
  };

  const devices = useMemo(() => {
    const flat = [];
    const visit = (items) => (items || []).forEach((item) => { flat.push(item); visit(item.children); });
    visit(inventory?.devices);
    return flat;
  }, [inventory]);
  const disks = devices.filter((d) => d.type === "disk" && d.path);
  const restoreTargetDevice = devices.find((device) => device.path === target);
  const partitions = devices.filter((d) => d.type === "part" && d.path);
  const clientRemoteJob = clientRemoteInspection?.job;
  const clientRemoteDeviceOptions = clientRemoteJob?.target_type === "partition" ? partitions : disks;
  const clientRemoteConfirmationPhrase = clientRemoteJob && clientRemoteTarget
    ? (clientRemoteJob.operation === "restore" || clientRemoteJob.operation === "clone"
      ? `ERASE ${clientRemoteTarget} FROM ${clientRemoteInspection.server_identity}`
      : `READ ${clientRemoteTarget} TO ${clientRemoteInspection.server_identity}`)
    : "";
  const isCapture = operation.startsWith("capture_");
  const isRestore = operation.startsWith("restore_");
  const isDisk = operation.endsWith("_disk");
  const deviceOptions = isDisk ? disks : partitions;
  const selectedRepository = remoteRepositories.find((repo) => repo.id === selectedRepositoryId);
  const availableImages = selectedRepositoryId ? repositoryImages : images;
  const matchingImages = availableImages.filter((item) => item.image_type === (isDisk ? "disk" : "partition"));
  const sftpInspectionMatchesCurrent = Boolean(sftpRemoteInspection?.connection
    && sftpRemoteInspection.connection.host === sftpHost
    && sftpRemoteInspection.connection.username === sftpUsername
    && sftpRemoteInspection.connection.remote_directory === sftpRemoteDirectory
    && sftpRemoteInspection.connection.port === Number(sftpPort)
    && sftpRemoteInspection.connection.identity_credential === sftpIdentity
    && sftpRemoteInspection.connection.known_hosts_credential === sftpKnownHosts);
  useEffect(() => {
    if (!sftpInspectionMatchesCurrent) setRestoreFromSftp(false);
  }, [sftpInspectionMatchesCurrent]);

  const expectedConfirmation = operation === "clone_partition"
    ? (source && target ? `ERASE ${target} FROM ${source}` : "")
    : (isRestore || operation.startsWith("clone_")) && target ? `ERASE ${target}` : "";

  useEffect(() => { setConfirmation(""); setProgress(null); setOperationResult(null); }, [operation, source, target, imageId]);

  const runOperation = async (event) => {
    event.preventDefault(); setBusy(true); setError(""); setNotice(""); setProgress(null); setOperationResult(null);
    try {
      let params;
      const sftpPublish = publishAfterCapture ? {
        host: sftpHost, username: sftpUsername, remote_directory: sftpRemoteDirectory,
        port: Number(sftpPort), identity_credential: sftpIdentity,
        known_hosts_credential: sftpKnownHosts
      } : null;
      if (operation === "capture_disk") params = { source, image_id: imageId, compression, encrypt, sign, ...(selectedRepositoryId ? { repository_id: selectedRepositoryId } : {}), ...(sftpPublish ? { sftp_publish: sftpPublish } : {}) };
      else if (operation === "capture_partition") params = { source, image_id: imageId, partition_id: partitionId || imageId, compression, encrypt, sign, ...(selectedRepositoryId ? { repository_id: selectedRepositoryId } : {}), ...(sftpPublish ? { sftp_publish: sftpPublish } : {}) };
      else if (isRestore) {
        const sftpSource = restoreFromSftp && sftpInspectionMatchesCurrent ? {
          host: sftpHost, username: sftpUsername, remote_directory: sftpRemoteDirectory,
          port: Number(sftpPort), identity_credential: sftpIdentity,
          known_hosts_credential: sftpKnownHosts,
          expected_manifest_sha256: sftpRemoteInspection.manifest_sha256
        } : null;
        if (restoreFromSftp && !sftpSource) throw new Error("Re-inspect the SFTP image after changing its connection settings.");
        params = {
          image_id: imageId, target, confirmation,
          ...(sftpSource ? { sftp_source: sftpSource } : selectedRepositoryId ? { repository_id: selectedRepositoryId } : {})
        };
      }
      else params = { source, target, confirmation };
      const accepted = await callFeclora(operation, params);
      setOperations((current) => [{
        operation_id: accepted.operation_id, action: operation, state: "queued",
        events: [{ state: "queued", timestamp: new Date().toISOString(), details: {} }]
      }, ...current.filter((item) => item.operation_id !== accepted.operation_id)]);
      setNotice("Operation accepted by the durable worker. It will continue if Cockpit disconnects. Use Operation log to request cancellation.");
      const result = await waitForLocalOperation(accepted.operation_id, (eventData) => {
        if (eventData.event === "progress") setProgress(eventData);
      });
      if (result.state === "completed") {
        setOperationResult(result.result);
        setNotice("Operation completed successfully.");
      } else if (result.state === "cancelled") {
        setNotice(result.details?.destination_may_be_partial
          ? "Operation cancelled. The destination may be partially written; inspect it before using it again."
          : "Operation cancelled before completing.");
      } else {
        setError("Local operation " + result.state + ": " + (result.details?.error || result.details?.reason || "inspect the operation log."));
      }
      await refresh();
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };


  const selectImageRepository = async (id) => {
    setSelectedRepositoryId(id); setRepositoryImages([]); setImageVerification({});
    if (id) setRestoreFromSftp(false);
    setExtractLayout(null); setExtractPartitionSelector(""); setExtractPartitionResult(null);
    setRestoreLayoutPreview(null);
    if (!id) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await callFeclora("repository_images", { repository_id: id });
      setRepositoryImages(result.images || []);
      setNotice("Loaded " + (result.images || []).length + " images from repository " + id + ".");
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };

  const importSystemdCredential = async (event) => {
    event.preventDefault(); setBusy(true); setError(""); setNotice("");
    try {
      await callFeclora("put_systemd_credential", {
        id: credentialId, kind: credentialKind, source_file: credentialSourceFile, replace: credentialReplace
      });
      setNotice("Encrypted credential imported. The protected source file was not deleted.");
      setCredentialId(""); setCredentialSourceFile(""); setCredentialReplace(false);
      await refresh();
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };

  const removeSystemdCredential = async (credential) => {
    setBusy(true); setError(""); setNotice("");
    try {
      await callFeclora("remove_systemd_credential", { id: credential.id, kind: credential.kind });
      setNotice("Removed encrypted credential " + credential.id + " (" + credential.kind + ").");
      await refresh();
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };

  const selectSftpRepository = (identifier) => {
    setSftpRepositoryId(identifier);
    const saved = sftpRepositories.find((item) => item.id === identifier);
    if (!saved) return;
    setSftpHost(saved.host); setSftpUsername(saved.username);
    setSftpRemoteDirectory(saved.remote_directory); setSftpPort(String(saved.port));
    setSftpIdentity(saved.identity_credential); setSftpKnownHosts(saved.known_hosts_credential);
    setSftpRemoteInspection(null); setSftpRemoteInventory(null); setRestoreFromSftp(false);
  };

  const saveSftpRepository = async () => {
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await callFeclora("save_sftp_repository", {
        id: sftpRepositoryId, host: sftpHost, username: sftpUsername,
        remote_directory: sftpRemoteDirectory, port: Number(sftpPort),
        identity_credential: sftpIdentity, known_hosts_credential: sftpKnownHosts
      });
      setNotice("Saved SFTP repository " + result.repository.id + ".");
      await refresh();
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };

  const removeSftpRepository = async () => {
    if (!sftpRepositoryId) return;
    setBusy(true); setError(""); setNotice("");
    try {
      await callFeclora("remove_sftp_repository", { id: sftpRepositoryId });
      setNotice("Removed saved SFTP repository " + sftpRepositoryId + ".");
      setSftpRepositoryId("");
      await refresh();
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };

  const listSftpImageManifests = async () => {
    setBusy(true); setError(""); setNotice(""); setSftpRemoteInventory(null);
    try {
      const result = await callFeclora("list_sftp_image_manifests", {
        host: sftpHost, username: sftpUsername, remote_directory: sftpRemoteDirectory,
        port: Number(sftpPort), identity_credential: sftpIdentity,
        known_hosts_credential: sftpKnownHosts
      });
      setSftpRemoteInventory(result.manifests || []);
      setNotice("SFTP inventory completed: " + (result.manifests || []).length + " manifest marker(s) found.");
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };

  const inspectSftpImageSet = async () => {
    setBusy(true); setError(""); setNotice(""); setSftpRemoteInspection(null); setRestoreFromSftp(false);
    try {
      const result = await callFeclora("inspect_sftp_image_set", {
        host: sftpHost, username: sftpUsername, remote_directory: sftpRemoteDirectory,
        port: Number(sftpPort), identity_credential: sftpIdentity,
        known_hosts_credential: sftpKnownHosts
      });
      setSftpRemoteInspection({
        ...result,
        connection: {
          host: sftpHost, username: sftpUsername, remote_directory: sftpRemoteDirectory,
          port: Number(sftpPort), identity_credential: sftpIdentity,
          known_hosts_credential: sftpKnownHosts
        }
      });
      setNotice("Remote image manifest signature verified for " + result.image_id + ".");
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };

  const fetchSftpImageSet = async (event) => {
    event.preventDefault(); setBusy(true); setError(""); setNotice("");
    try {
      const result = await callFeclora("fetch_sftp_image_set", {
        host: sftpHost, username: sftpUsername, remote_directory: sftpRemoteDirectory,
        port: Number(sftpPort), identity_credential: sftpIdentity,
        known_hosts_credential: sftpKnownHosts
      });
      setNotice("Imported and verified SFTP image " + result.image_id + " (" + result.artifact_count + " artifacts).");
      await refresh();
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };

  const publishSftpImageSet = async (event) => {
    event.preventDefault(); setBusy(true); setError(""); setNotice("");
    try {
      const result = await callFeclora("publish_sftp_image_set", {
        image_id: sftpPublishImageId, host: sftpHost, username: sftpUsername,
        remote_directory: sftpRemoteDirectory, port: Number(sftpPort),
        identity_credential: sftpIdentity, known_hosts_credential: sftpKnownHosts
      });
      setNotice("Published signed SFTP image " + result.image_id + " (" + result.artifact_count + " artifacts).");
      await refresh();
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };

  const saveRemoteRepository = async (event) => {
    event.preventDefault(); setBusy(true); setError(""); setNotice("");
    try {
      await callFeclora(repositoryEditing ? "update_remote_repository" : "add_remote_repository", {
        id: repositoryId, provider: repositoryProvider, host: repositoryHost,
        remote_path: repositoryPath,
        username: repositoryProvider === "sshfs" || repositoryProvider === "smb" ? repositoryUsername || null : null,
        credential_file: repositoryProvider === "smb" || repositoryProvider === "s3" ? repositoryCredentials : null,
        identity_file: repositoryProvider === "sshfs" ? repositoryIdentity : null,
        known_hosts_file: repositoryProvider === "sshfs" ? repositoryKnownHosts : null,
        port: repositoryProvider === "sshfs" || repositoryProvider === "smb" ? (repositoryPort ? Number(repositoryPort) : null) : null,
        rclone_remote: repositoryProvider === "s3" ? repositoryRcloneRemote : null, read_only: repositoryProvider === "s3" ? true : repositoryReadOnly
      });
      setNotice(repositoryEditing ? "Repository definition updated; no mount was started." : "Repository definition saved; no mount was started.");
      setRepositoryId(""); setRepositoryEditing(false); await refresh();
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };

  const editRemoteRepository = (repo) => {
    if (repo.mounted) return;
    setRepositoryId(repo.id); setRepositoryEditing(true);
    setRepositoryProvider(repo.provider); setRepositoryHost(repo.host);
    setRepositoryPath(repo.remote_path); setRepositoryUsername(repo.username || "");
    setRepositoryIdentity(repo.identity_file || ""); setRepositoryKnownHosts(repo.known_hosts_file || "");
    setRepositoryCredentials(repo.credential_file || ""); setRepositoryRcloneRemote(repo.rclone_remote || "");
    setRepositoryPort(repo.port ? String(repo.port) : ""); setRepositoryReadOnly(Boolean(repo.read_only));
  };

  const resetRemoteRepositoryForm = () => {
    setRepositoryId(""); setRepositoryEditing(false); setRepositoryProvider("sshfs");
    setRepositoryHost(""); setRepositoryPath("/images"); setRepositoryUsername("");
    setRepositoryIdentity(""); setRepositoryKnownHosts(""); setRepositoryCredentials("");
    setRepositoryRcloneRemote(""); setRepositoryPort("22"); setRepositoryReadOnly(true);
  };

  const runRemoteRepositoryAction = async (action, id) => {
    setBusy(true); setError(""); setNotice("");
    try {
      const actionResult = await callFeclora(action, { id });
      setNotice(action === "remove_remote_repository" ? `Removed repository ${id}.`
        : action === "mount_remote_repository" ? `Mounted repository ${id}.`
        : action === "unmount_remote_repository" ? `Unmounted repository ${id}.`
        : action === "check_remote_repository" ? `Repository ${id}: ${actionResult.verified ? "mount verified" : actionResult.mounted ? "mounted but unverified" : "not mounted"}.`
        : `Repository ${id} updated.`);
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

  const inspectRestoreLayout = async (sourceImageId) => {
    setRestoreLayoutPreview(null);
    if (!sourceImageId) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await callFeclora("inspect_image_layout", { image_id: sourceImageId, ...(selectedRepositoryId ? { repository_id: selectedRepositoryId } : {}) });
      setRestoreLayoutPreview(result);
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };

  const inspectImageLayout = async (imageId) => {
    setExtractLayout(null); setExtractPartitionSelector(""); setExtractPartitionResult(null);
    if (!imageId) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await callFeclora("inspect_image_layout", { image_id: imageId, ...(selectedRepositoryId ? { repository_id: selectedRepositoryId } : {}) });
      setExtractLayout(result);
      setNotice(result.message);
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };

  const extractPartitionFromImage = async () => {
    setBusy(true); setError(""); setNotice(""); setProgress(null); setExtractPartitionResult(null);
    try {
      const accepted = await callFeclora("extract_partition_image", {
        image_id: extractImageId, selector: extractPartitionSelector, ...(selectedRepositoryId ? { repository_id: selectedRepositoryId } : {})
      });
      setNotice("Partition extraction accepted by the durable worker.");
      const result = await waitForLocalOperation(accepted.operation_id, (eventData) => {
        if (eventData.event === "progress") setProgress(eventData);
      });
      setExtractPartitionResult(result.result);
      setNotice("Partition image extracted and published.");
      await refresh();
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); setProgress(null); }
  };

  const exportServerCABackup = async () => {
    setBusy(true); setError(""); setNotice(""); setCaBackupResult(null);
    try {
      const result = await callFeclora("export_server_ca_backup", {
        export_directory: caBackupDirectory,
        age_recipient: caBackupRecipient.trim()
      });
      setCaBackupResult(result); setNotice(result.message);
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };

  const inspectServerCABackup = async () => {
    setBusy(true); setError(""); setNotice(""); setCaBackupInspection(null);
    try {
      const result = await callFeclora("inspect_server_ca_backup", {
        backup_file: caBackupInspectionFile,
        identity_file: caBackupIdentityFile
      });
      setCaBackupInspection(result); setNotice(result.message);
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
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

  const renewServerCertificate = async () => {
    if (serverRenewConfirmation !== "RENEW SERVER CERTIFICATE") return;
    setBusy(true); setError(""); setNotice(""); setServerRenewResult(null);
    try {
      const result = await callFeclora("renew_server_certificate", {
        confirmation: serverRenewConfirmation
      });
      setServerRenewResult(result); setNotice(result.message);
      setServerRenewConfirmation("");
      await refresh();
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };


  const rotateServerKeypair = async () => {
    if (serverRotateConfirmation !== "ROTATE SERVER TLS KEYPAIR") return;
    setBusy(true); setError(""); setNotice(""); setServerRotateResult(null);
    try {
      const result = await callFeclora("rotate_server_keypair", {
        confirmation: serverRotateConfirmation
      });
      setServerRotateResult(result); setNotice(result.message);
      setServerRotateConfirmation("");
      await refresh();
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
  const prepareClientRenewal = async () => {
    setBusy(true); setError(""); setNotice(""); setClientRenewalPrepared(null);
    try {
      const result = await callFeclora("prepare_client_renewal", {
        export_directory: clientRenewalExportDirectory
      });
      setClientRenewalPrepared(result); setNotice(result.message);
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };

  const completeClientRenewal = async () => {
    setBusy(true); setError(""); setNotice(""); setClientRenewalCompleted(null);
    try {
      const result = await callFeclora("complete_client_renewal", {
        bundle_directory: clientRenewalBundleDirectory,
        ca_fingerprint: clientCaFingerprint,
        server_minisign_sha256: clientServerFingerprint
      });
      setClientRenewalCompleted(result); setNotice(result.message);
      await refresh();
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };

  const inspectClientCSR = async () => {
    setBusy(true); setError(""); setNotice(""); setCsrReview(null); setCsrConfirmation("");
    try {
      const result = await callFeclora("inspect_client_csr", {
        csr_path: csrPath, age_recipient_path: ageRecipientPath, mac_address: clientMac,
        minisign_public_path: clientMinisignPath || null, renewal: csrRenewal
      });
      setCsrReview(result);
      setNotice(csrRenewal ? "Renewal CSR inspected; existing trust mappings remain unchanged until the new certificate is installed." : "CSR signature, Client identity and age recipient inspected. No trust changes have been made.");
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };

  const approveClientCSR = async () => {
    if (!csrReview || csrConfirmation !== csrReview.confirmation_phrase) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await callFeclora("approve_client_csr", {
        csr_path: csrPath, age_recipient_path: ageRecipientPath, mac_address: clientMac,
        minisign_public_path: clientMinisignPath || null, confirmation: csrConfirmation, renewal: csrRenewal
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

  const deploymentArmPhrase = (job) => {
    if (job.transport === "multicast") return "ARM MULTICAST " + job.job_id + " IGMP-VERIFIED";
    if (job.operation === "clone") {
      const peer = trustedClients.find((client) => job.authorized_clients?.includes(client.mac_address));
      return peer?.identity
        ? "ARM " + job.job_id + " AND READ " + job.source_device + " TO " + peer.identity
        : "";
    }
    return "ARM " + job.job_id;
  };

  const createRemoteJob = async (event) => {
    event.preventDefault(); setBusy(true); setError(""); setNotice(""); setRemoteJobResult(null);
    try {
      const authorizedClients = remoteClients.split(/[\s,;]+/).map((value) => value.trim()).filter(Boolean);
      const job = {
        schema_version: 1, job_id: crypto.randomUUID(), operation: remoteOperation,
        image_id: remoteOperation === "clone" ? null : remoteImageId,
        ...(remoteOperation === "clone" ? { source_device: remoteSourceDevice, target_type: "disk" } : { target_type: remoteTargetType }),
        authorized_clients: authorizedClients, network_interface: remoteInterface.split("|")[0],
        transport: remoteTransport,
        ...(remoteOperation === "restore" && selectedRepositoryId ? { repository_id: selectedRepositoryId } : {}),
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
      setNotice("Persistent deployment service started. Clients may now connect; no disk operation starts until the Server operator explicitly authorizes and starts it.");
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
    const selectedInterface = networkInterfaces.find((item) => item.binding === clientRemoteInterface);
    if (!selectedInterface) { setError("Select an active Client interface/address before testing connectivity."); setBusy(false); return; }
    try {
      const result = await callFeclora("inspect_remote_job", {
        host: clientRemoteHost, job_id: clientRemoteJobId,
        network_interface: selectedInterface.interface, source_address: selectedInterface.address,
      });
      setClientRemoteInspection(result);
      setClientRemoteTarget("");
      setClientRemoteConfirmation("");
      setClientRemoteIgmpConfirmed(false);
      setNotice("Server reachability and authenticated TLS identity verified; job inspected. No Client registration or disk operation has started.");
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
        network_interface: networkInterfaces.find((item) => item.binding === clientRemoteInterface)?.interface || null,
        source_address: networkInterfaces.find((item) => item.binding === clientRemoteInterface)?.address || null,
        igmp_confirmed: clientRemoteJob.transport === "multicast" ? clientRemoteIgmpConfirmed : false,
      });
      setClientRemoteJobStatus(result);
      setNotice(result.phase === "failed"
        ? "Client service started but reported a failure before completion; inspect its status detail."
        : "Client service started. It will report READY only after local target approval, and will write only after the Server operator explicitly authorizes and starts the job.");
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
    ? Boolean(source && imageId && (!selectedRepository?.read_only) && (operation !== "capture_partition" || partitionId || imageId))
    : isRestore ? Boolean(imageId && target && confirmation === expectedConfirmation && (!isDisk || !restoreLayoutPreview || !restoreTargetDevice || restoreTargetDevice.size_bytes >= restoreLayoutPreview.source_size_bytes))
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
      {status?.certificate_status?.length > 0 && <PageSection>
        <Stack hasGutter>
          {status.certificate_status.map((item) => <Alert key={item.role} variant={
            item.status === "expired" || item.ca_status === "expired" || item.status === "error" ? "danger"
              : item.status === "expiring" || item.ca_status === "expiring" ? "warning" : "success"
          } title={item.role + " TLS certificate: " + item.status} isInline>
            {item.identity ? item.identity + " · " : ""}{item.expiry_days === null ? (item.detail || "Certificate status could not be read.") : item.expiry_days < 0 ? "Certificate expired " + (-item.expiry_days) + " days ago." : "Certificate expires in " + item.expiry_days + " days."}{item.ca_expiry_days !== undefined ? " CA: " + (item.ca_expiry_days < 0 ? "expired " + (-item.ca_expiry_days) + " days ago" : "expires in " + item.ca_expiry_days + " days") + "." : ""}
          </Alert>)}
        </Stack>
      </PageSection>}
      <PageSection>
        <Tabs activeKey={tab} onSelect={(_event, key) => setTab(key)}>
          <Tab eventKey="operations" title="Imaging operations">
            <Stack hasGutter className="pf-v5-u-pt-lg">
              <StackItem><Title headingLevel="h2" size="xl">Operation wizard</Title><p>Choose an operation, review the selected devices, and explicitly confirm every destructive target.</p></StackItem>
              <StackItem>
                <Card><CardBody>
                  <form onSubmit={runOperation}>
                    <Field label="Operation">
                      <select className="pf-v5-c-form-control" value={operation} onChange={(e) => { setOperation(e.target.value); setSource(""); setTarget(""); setImageId(""); setRestoreFromSftp(false); setPartitionId(""); setRestoreLayoutPreview(null); setConfirmation(""); setOperationResult(null); }}>
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
                        <label><input type="checkbox" checked={sign} disabled={!security.image_signing_available || publishAfterCapture} onChange={(e) => setSign(e.target.checked)} /> Sign manifest with minisign</label>
                        {!security.age_encryption_available || !security.image_signing_available ? <p className="pf-v5-u-color-200">Initialize local security keys from the System tab to enable these options.</p> : null}
                      </Field>
                      <Field label="SFTP post-capture publication">
                        <label><input type="checkbox" checked={publishAfterCapture} disabled={busy || !sign} onChange={(e) => setPublishAfterCapture(e.target.checked)} /> Publish this image set to SFTP after capture and local signature verification</label>
                        {publishAfterCapture && <>
                          <Field label="SFTP host"><input className="pf-v5-c-form-control" value={sftpHost} onChange={(e) => setSftpHost(e.target.value)} maxLength={253} required /></Field>
                          <Field label="SSH username"><input className="pf-v5-c-form-control" value={sftpUsername} onChange={(e) => setSftpUsername(e.target.value)} maxLength={64} required /></Field>
                          <Field label="Remote image directory"><input className="pf-v5-c-form-control" value={sftpRemoteDirectory} onChange={(e) => setSftpRemoteDirectory(e.target.value)} maxLength={1024} required /></Field>
                          <Field label="SSH port"><input className="pf-v5-c-form-control" type="number" min="1" max="65535" value={sftpPort} onChange={(e) => setSftpPort(e.target.value)} required /></Field>
                          <Field label="Encrypted SSH private-key credential"><select className="pf-v5-c-form-control" value={sftpIdentity} onChange={(e) => setSftpIdentity(e.target.value)} required><option value="">Select imported SSH key</option>{systemdCredentials.filter((item) => item.kind === "ssh-key").map((item) => <option key={item.path} value={item.path}>{item.id}</option>)}</select></Field>
                          <Field label="Encrypted pinned SSH known_hosts credential"><select className="pf-v5-c-form-control" value={sftpKnownHosts} onChange={(e) => setSftpKnownHosts(e.target.value)} required><option value="">Select imported known_hosts</option>{systemdCredentials.filter((item) => item.kind === "known-hosts").map((item) => <option key={item.path} value={item.path}>{item.id}</option>)}</select></Field>
                        </>}
                      </Field>
                    </>}
                    {isRestore && <>
                      <Field label="SFTP restore source">
                        <label><input type="checkbox" checked={restoreFromSftp} disabled={busy || !sftpInspectionMatchesCurrent || sftpRemoteInspection?.image_type !== (isDisk ? "disk" : "partition") || Boolean(selectedRepositoryId)} onChange={(e) => {
                          const enabled = e.target.checked;
                          setRestoreFromSftp(enabled);
                          if (enabled) { setImageId(sftpRemoteInspection.image_id); setRestoreLayoutPreview(null); }
                        }} /> Fetch and verify the authenticated SFTP image before restoring it</label>
                        {!sftpInspectionMatchesCurrent && <p>Inspect and verify a remote SFTP image in the Remote Repositories tab using the current connection settings first.</p>}
                        {selectedRepositoryId && <p>Clear the mounted repository selection to restore directly from SFTP.</p>}
                      </Field>
                      <Field label={isDisk ? "Disk image" : "Partition image"}>
                        <select className="pf-v5-c-form-control" value={imageId} disabled={busy || restoreFromSftp} onChange={(e) => {
                          const value = e.target.value;
                          if (sftpInspectionMatchesCurrent && value === sftpRemoteInspection.image_id) {
                            setRestoreFromSftp(true); setImageId(value); setRestoreLayoutPreview(null);
                          } else {
                            setRestoreFromSftp(false); setImageId(value);
                            if (isDisk) inspectRestoreLayout(value); else setRestoreLayoutPreview(null);
                          }
                        }}>
                          <option value="">Select an image…</option>
                          {matchingImages.map((item) => <option key={item.image_id} value={item.image_id}>{item.image_id} · {formatBytes(item.source_size_bytes)}</option>)}
                          {sftpInspectionMatchesCurrent && sftpRemoteInspection.image_type === (isDisk ? "disk" : "partition") && <option value={sftpRemoteInspection.image_id}>{sftpRemoteInspection.image_id} · authenticated SFTP image</option>}
                        </select>
                      </Field>
                      <Field label={isDisk ? "Destination disk" : "Destination partition"}>
                        <select className="pf-v5-c-form-control" value={target} onChange={(e) => setTarget(e.target.value)}>
                          <option value="">Select a destination…</option>
                          {deviceOptions.map((d) => <option key={d.path} value={d.path}>{d.path} · {formatBytes(d.size_bytes)} · {d.model || d.filesystem || d.type}</option>)}
                        </select>
                      </Field>
                      {isDisk && restoreLayoutPreview && restoreTargetDevice && <>
                        {restoreTargetDevice.size_bytes < restoreLayoutPreview.source_size_bytes
                          ? <Alert variant="danger" title="Destination disk is too small" isInline>Source layout requires {formatBytes(restoreLayoutPreview.source_size_bytes)}; selected disk has {formatBytes(restoreTargetDevice.size_bytes)}. The restore engine will reject this target.</Alert>
                          : <Alert variant="info" title="Read-only restore layout preview" isInline>
                              Source image: {formatBytes(restoreLayoutPreview.source_size_bytes)} · Destination: {formatBytes(restoreTargetDevice.size_bytes)} · {restoreLayoutPreview.partitions.length} partitions. The source partition layout is written as captured; extra destination capacity is left unused. No automatic partition/filesystem growth is performed.
                            </Alert>}
                        <Table aria-label="Restore source partition layout preview" variant="compact">
                          <Thead><Tr><Th>Partition</Th><Th>UUID / label</Th><Th>Start sector</Th><Th>Size</Th></Tr></Thead>
                          <Tbody>{restoreLayoutPreview.partitions.map((part) => <Tr key={part.node}>
                            <Td>{part.node}</Td><Td>{part.uuid || part.name || "—"}</Td><Td>{part.start_sector}</Td><Td>{formatBytes(part.size_bytes)}</Td>
                          </Tr>)}</Tbody>
                        </Table>
                      </>}
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
            <Stack hasGutter className="pf-v5-u-pt-lg"><StackItem><Title headingLevel="h2" size="xl">Available images</Title><Field label="Image repository" help="Local is the default; remote mounts must be verified."><select className="pf-v5-c-form-control" value={selectedRepositoryId} disabled={busy} onChange={(event) => selectImageRepository(event.target.value)}><option value="">Local repository</option>{remoteRepositories.filter((repo) => repo.mounted && repo.verified).map((repo) => <option key={repo.id} value={repo.id}>{repo.id} · {repo.provider} · {repo.read_only ? "read-only" : "read/write"}</option>)}</select></Field></StackItem>
              <StackItem>
                <Card><CardBody>
                  <Title headingLevel="h3" size="lg">Extract a partition from a whole-disk image</Title>
                  <p>Select a verified whole-disk image and identify one partition by PARTUUID, PARTLABEL or partition node recorded in its partition table. Feclora verifies the source image and publishes a separate partition image; age-encrypted sources are re-encrypted to the current recipient inventory. The source image is not modified.</p>
                  <Field label="Whole-disk source image">
                    <select className="pf-v5-c-form-control" value={extractImageId} disabled={busy} onChange={(event) => { setExtractImageId(event.target.value); inspectImageLayout(event.target.value); }}>
                      <option value="">Select whole-disk image…</option>
                      {availableImages.filter((item) => item.image_type === "disk").map((item) => <option key={item.image_id} value={item.image_id}>{item.image_id}{item.signed ? " · signed" : " · unsigned"}</option>)}
                    </select>
                  </Field>
                  {extractLayout && <>
                    <Alert variant="info" title="Verified partition-table preview" isInline>{extractLayout.message} Source size: {formatBytes(extractLayout.source_size_bytes)} · Logical sector: {extractLayout.logical_sector_size} bytes · {extractLayout.partitions.length} partitions.</Alert>
                    <Table aria-label="Source image partition layout" variant="compact">
                      <Thead><Tr><Th>Partition</Th><Th>UUID / label</Th><Th>Start sector</Th><Th>Size</Th></Tr></Thead>
                      <Tbody>{extractLayout.partitions.map((part) => <Tr key={part.node}>
                        <Td>{part.node}</Td><Td>{part.uuid || part.name || "—"}</Td><Td>{part.start_sector}</Td><Td>{formatBytes(part.size_bytes)}</Td>
                      </Tr>)}</Tbody>
                    </Table>
                  </>}
                  <Field label="Partition to extract" help="Choose a partition from the verified table preview. The selector is cleared whenever the source image changes.">
                    <select className="pf-v5-c-form-control" value={extractPartitionSelector} onChange={(event) => { setExtractPartitionSelector(event.target.value); setExtractPartitionResult(null); }} disabled={!extractLayout || !extractLayout.partitions.length}>
                      <option value="">Select partition…</option>
                      {(extractLayout?.partitions || []).map((part) => <option key={part.node} value={part.selector}>{part.node} · {part.uuid || part.name || part.selector} · {formatBytes(part.size_bytes)}</option>)}
                    </select>
                  </Field>
                  <Button variant="primary" onClick={extractPartitionFromImage} isLoading={busy} isDisabled={busy || selectedRepository?.read_only || !extractImageId || !extractLayout || !extractPartitionSelector}>Extract partition image</Button>
                  {busy && progress && <Progress value={progress.bytes_total ? Math.min(100, progress.bytes_done / progress.bytes_total * 100) : 0} title="Partition extraction progress" measureLocation="outside" label={formatBytes(progress.bytes_done) + " / " + formatBytes(progress.bytes_total)} />}
                  {extractPartitionResult && <Alert variant="success" title="Partition image published" isInline>
                    Source: {extractPartitionResult.source_image_id} · New image: {extractPartitionResult.image_id} · {extractPartitionResult.signed ? "Signed" : "Unsigned"} · {extractPartitionResult.encrypted ? "age-encrypted" : "unencrypted"}
                  </Alert>}
                </CardBody></Card>
              </StackItem>
              <StackItem><Table aria-label="Feclora image repository" variant="compact"><Thead><Tr><Th>Image</Th><Th>Type</Th><Th>Source size</Th><Th>Signature</Th><Th>Encryption</Th><Th>Artifacts</Th><Th>Verification</Th></Tr></Thead><Tbody>
                {images.map((item) => {
                  const verification = imageVerification[item.image_id];
                  return <Tr key={item.image_id}><Td>{item.image_id}</Td><Td>{item.image_type}</Td><Td>{formatBytes(item.source_size_bytes)}</Td><Td><Label color={item.signed ? "green" : "orange"}>{item.signed ? "Signed" : "Unsigned"}</Label></Td><Td><Label color={item.encrypted ? "green" : "orange"}>{item.encrypted ? "age" : "Plain"}</Label></Td><Td>{item.artifact_count}</Td><Td>
                    <Button size="sm" variant="secondary" isDisabled={busy || verification?.loading} isLoading={verification?.loading} onClick={() => verifyImage(item.image_id)}>Verify</Button>
                    {verification?.report && <div className="pf-v5-u-mt-sm">
                      <Label color="green">Verified</Label> Manifest: {verification.report.manifest} · Signature: {verification.report.signature} · {verification.report.artifact_count} artifacts · {formatBytes(verification.report.total_decoded_bytes)}
                      {verification.report.artifacts.map((artifact) => <p key={artifact.filename}>{artifact.filename}: stored SHA-256 {artifact.stored_digest}; age {artifact.age_authentication}; compression {artifact.decompression}; decoded {formatBytes(artifact.decoded_bytes)}</p>)}
                    </div>}
                    {verification?.error && <Alert variant="danger" title="Verification failed" isInline>{verification.error}</Alert>}
                  </Td></Tr>;
                })}
                {!availableImages.length && <Tr><Td colSpan={7}>No manifest-backed images found in this repository.</Td></Tr>}
              </Tbody></Table></StackItem>
            </Stack>
          </Tab>
          <Tab eventKey="remote-jobs" title="Remote jobs">
            <Stack hasGutter className="pf-v5-u-pt-lg">
              <StackItem><Title headingLevel="h2" size="xl">Create a remote deployment job</Title>
                <Alert variant="warning" title="Definition only — service not started; no Client contact or disk I/O" isInline>
                  This step validates and journals a job definition. Start its persistent service separately; Clients then authenticate and approve their own local target through the existing Client-local runtime. Each Client selects and approves its own local destination in the Client jobs tab. No storage operation starts until you explicitly authorize and start it here after all authorized Clients report READY.
                </Alert>
              </StackItem>
              <StackItem>
                <Card><CardBody><form onSubmit={createRemoteJob}>
                  <Field label="Operation">
                    <select className="pf-v5-c-form-control" value={remoteOperation} onChange={(e) => { setRemoteOperation(e.target.value); setRemoteImageId(""); setRemoteSourceDevice(""); if (e.target.value === "save" || e.target.value === "clone") { setRemoteTransport("unicast"); setRemoteTargetType("disk"); } }}>
                      <option value="restore">Restore a signed Server image to Clients</option>
                      <option value="save">Capture whole disks from Clients to Server</option>
                      <option value="clone">Clone Server disk directly to one Client disk</option>
                    </select>
                  </Field>
                  {remoteOperation === "restore" && <Field label="Image repository">
                    <select className="pf-v5-c-form-control" value={selectedRepositoryId} disabled={busy} onChange={(e) => { selectImageRepository(e.target.value); setRemoteImageId(""); }}>
                      <option value="">Local Server repository</option>
                      {remoteRepositories.filter((repo) => repo.mounted && repo.verified).map((repo) => <option key={repo.id} value={repo.id}>{repo.id} · {repo.provider}</option>)}
                    </select>
                  </Field>}
                  {remoteOperation === "clone" ? <Field label="Server source disk" help="Select a whole disk already marked read-only. Feclora rechecks it before streaming.">
                    <select className="pf-v5-c-form-control" value={remoteSourceDevice} onChange={(e) => setRemoteSourceDevice(e.target.value)} required>
                      <option value="">Select read-only source disk…</option>
                      {(inventory?.devices || []).filter((item) => item.type === "disk" && item.read_only === true).map((item) => <option key={item.path} value={item.path}>{item.path} · {item.model || "Disk"} · {formatBytes(item.size_bytes)}</option>)}
                    </select>
                  </Field> : <Field label="Image identifier" help={remoteOperation === "restore" ? "Choose an existing signed image." : "New identifier for the image captured from Clients."}>
                    {remoteOperation === "restore" ? <select className="pf-v5-c-form-control" value={remoteImageId} onChange={(e) => setRemoteImageId(e.target.value)}>
                      <option value="">Select signed image…</option>
                      {availableImages.filter((item) => item.image_type === remoteTargetType && item.signed).map((item) => <option key={item.image_id} value={item.image_id}>{item.image_id}</option>)}
                    </select> : <input className="pf-v5-c-form-control" value={remoteImageId} onChange={(e) => setRemoteImageId(e.target.value)} maxLength={128} required />}
                  </Field>}
                  {remoteOperation === "restore" && <Field label="Target type">
                    <select className="pf-v5-c-form-control" value={remoteTargetType} onChange={(e) => { setRemoteTargetType(e.target.value); setRemoteImageId(""); }}>
                      <option value="disk">Whole disk</option><option value="partition">Partition</option>
                    </select>
                  </Field>}
                  <Field label="Enrolled Client MAC addresses" help={remoteOperation === "clone" ? "Enter exactly one enrolled Client MAC. That Client independently selects and confirms its destination disk." : "Enter exactly one MAC for unicast, or at least two for multicast restore. Server verifies each is enrolled."}>
                    <textarea className="pf-v5-c-form-control" rows={3} value={remoteClients} onChange={(e) => setRemoteClients(e.target.value)} required placeholder="52:54:00:12:34:56" />
                  </Field>
                  <Field label="Server network interface">
                    <select className="pf-v5-c-form-control" value={remoteInterface} onChange={(e) => setRemoteInterface(e.target.value)} required>
                      <option value="">Select active Server interface/address…</option>
                      {networkInterfaces.map((item) => <option key={item.binding} value={item.binding}>{item.interface} · {item.address}/{item.prefix_length}</option>)}
                    </select>
                    <div className="pf-v5-u-color-200 pf-v5-u-font-size-sm">The job binds to the selected Server interface. Configure the Client independently from its local Cockpit Network tab; this does not test end-to-end reachability to an offline Client.</div>
                  </Field>
                  <Field label="Transport">
                    <select className="pf-v5-c-form-control" value={remoteTransport} disabled={remoteOperation === "clone"} onChange={(e) => setRemoteTransport(e.target.value)}>
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
                  <Button type="submit" variant="primary" isDisabled={busy || (remoteOperation === "clone" ? !remoteSourceDevice : !remoteImageId) || !remoteClients.trim() || !remoteInterface}>Validate and save job definition</Button>
                </form>
                {remoteJobResult && <Alert variant="success" title="Job definition persisted" isInline className="pf-v5-u-mt-md">{remoteJobResult.message}<p>Job ID: {remoteJobResult.job_id}</p></Alert>}
                </CardBody></Card>
              </StackItem>
              <StackItem><Title headingLevel="h2" size="lg">Persisted remote jobs</Title>
                <p>Interrupted jobs can only be closed for audit after you have inspected every Client and destination manually. This does not resume or retry disk operations.</p>
                <Table aria-label="Persisted remote deployment jobs" variant="compact"><Thead><Tr><Th>Job ID</Th><Th>Operation</Th><Th>Image</Th><Th>Target</Th><Th>Transport</Th><Th>State</Th><Th>Client progress</Th><Th>Recovery</Th><Th>Events</Th><Th>Service and execution</Th></Tr></Thead><Tbody>
                  {deploymentJobs.map((job) => <Tr key={job.job_id}><Td>{job.job_id}</Td><Td>{job.operation}</Td><Td>{job.operation === "clone" ? job.source_device : job.image_id}</Td><Td>{job.target_type}</Td><Td>{job.transport}</Td><Td>{job.job_state}</Td><Td>{Object.entries(job.clients || {}).map(([mac, client]) => mac + ": " + client.state).join(", ") || "Not connected"}</Td><Td>{job.interrupted ? <Stack hasGutter><StackItem><Label color="orange">Review required · no auto-resume</Label></StackItem><StackItem><input className="pf-v5-c-form-control" aria-label={`Reconciliation confirmation for ${job.job_id}`} placeholder={`RECONCILE ${job.job_id}`} value={reconcileConfirmations[job.job_id] || ""} onChange={(event) => setReconcileConfirmations((current) => ({ ...current, [job.job_id]: event.target.value }))} /></StackItem><StackItem><Button variant="secondary" size="sm" isDisabled={busy || reconcileConfirmations[job.job_id] !== `RECONCILE ${job.job_id}`} onClick={() => reconcileDeploymentJob(job.job_id)}>Close for audit</Button></StackItem></Stack> : "—"}</Td><Td>{job.event_count}</Td><Td>
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
                          <StackItem><input className="pf-v5-c-form-control" aria-label={"Start authorization confirmation for " + job.job_id} placeholder={deploymentArmPhrase(job) || "Enrolled Client identity unavailable"} value={serviceConfirmations[job.job_id] || ""} onChange={(event) => setServiceConfirmations((current) => ({ ...current, [job.job_id]: event.target.value }))} /></StackItem>
                          <StackItem><Button size="sm" variant="primary" isDisabled={busy || !deploymentArmPhrase(job) || serviceConfirmations[job.job_id] !== deploymentArmPhrase(job)} onClick={() => sendDeploymentServiceCommand(job.job_id, "arm_deployment_job", serviceConfirmations[job.job_id])}>Authorize and execute</Button></StackItem>
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
              <StackItem><Table aria-label="Feclora deployment history" variant="compact"><Thead><Tr><Th>Job ID</Th><Th>State</Th><Th>Interrupted</Th><Th>Clients</Th><Th>Last durable progress</Th><Th>Events</Th></Tr></Thead><Tbody>
                {journals.map((job) => <Tr key={job.job_id}><Td>{job.job_id}</Td><Td>{job.job_state}</Td><Td>{job.interrupted ? <Label color="orange">Review required</Label> : "No"}</Td><Td>{Object.entries(job.clients || {}).map(([mac, state]) => mac + ": " + state).join(", ") || "—"}</Td><Td>{Object.entries(job.progress || {}).map(([mac, progress]) => mac + ": " + progress.phase + " " + (progress.completed_bytes / (1024 * 1024)).toFixed(1) + " MiB" + (progress.total_bytes === null ? "" : " / " + (progress.total_bytes / (1024 * 1024)).toFixed(1) + " MiB")).join("; ") || "No durable checkpoint"}</Td><Td>{job.event_count}</Td></Tr>)}
                {!journals.length && <Tr><Td colSpan={6}>No deployment jobs recorded.</Td></Tr>}
              </Tbody></Table></StackItem>
            </Stack>
          </Tab>

          <Tab eventKey="repositories" title="Remote repositories">
            <Stack hasGutter className="pf-v5-u-pt-lg">
              <StackItem><Title headingLevel="h2" size="xl">Remote image repositories</Title>
                <p>Manage filesystem repository mounts and transfer signed image sets through SFTP. SSHFS, NFS and SMB/CIFS are filesystem providers; S3/rclone remains read-only. SFTP currently supports one-shot publication of existing local signed images and import of remote signed images; saved definitions, remote inventory and automatic capture-job integration remain pending.</p>
                <Alert variant="warning" title="Provider scope" isInline>Cockpit exposes SSHFS, NFS, SMB/CIFS and read-only S3/rclone mounts. SFTP now supports one-shot signed image import using encrypted SSH-key and pinned known_hosts references; SFTP capture/upload, saved repository management and remote inventory discovery are not yet implemented. WebDAV remains hidden until its encrypted credential lifecycle is supported. S3 remains read-only.</Alert>
              </StackItem>
              <StackItem><Card><CardBody><form onSubmit={saveRemoteRepository}>
                <Field label="Repository ID"><input className="pf-v5-c-form-control" value={repositoryId} onChange={(e) => setRepositoryId(e.target.value)} pattern="[a-z0-9][a-z0-9-]{0,47}" maxLength={48} readOnly={repositoryEditing} required /></Field>
                <Field label="Provider"><select className="pf-v5-c-form-control" value={repositoryProvider} onChange={(e) => { setRepositoryProvider(e.target.value); setRepositoryPort(e.target.value === "sshfs" ? "22" : ""); }}>
                  <option value="sshfs">SSHFS (remote filesystem over SSH)</option><option value="nfs">NFS</option><option value="smb">SMB/CIFS</option><option value="s3">S3-compatible object storage (rclone)</option>
                </select></Field>
                <Field label={repositoryProvider === "s3" ? "Endpoint hostname (informational; actual endpoint is in rclone config)" : "Server hostname or IPv4 address"}><input className="pf-v5-c-form-control" value={repositoryHost} onChange={(e) => setRepositoryHost(e.target.value)} maxLength={253} required /></Field>
                <Field label={repositoryProvider === "smb" ? "Share and optional subdirectory" : "Remote absolute path"}><input className="pf-v5-c-form-control" value={repositoryPath} onChange={(e) => setRepositoryPath(e.target.value)} maxLength={512} required /></Field>
                {(repositoryProvider === "sshfs" || repositoryProvider === "smb") && <Field label="Username"><input className="pf-v5-c-form-control" value={repositoryUsername} onChange={(e) => setRepositoryUsername(e.target.value)} maxLength={64} required /></Field>}
                {repositoryProvider === "sshfs" && <>
                  <Field label="Encrypted SSH private-key credential"><select className="pf-v5-c-form-control" value={repositoryIdentity} onChange={(e) => setRepositoryIdentity(e.target.value)} required><option value="">Select imported SSH key</option>{systemdCredentials.filter((item) => item.kind === "ssh-key").map((item) => <option key={item.path} value={item.path}>{item.id}</option>)}</select></Field>
                  <Field label="Encrypted pinned SSH known_hosts credential"><select className="pf-v5-c-form-control" value={repositoryKnownHosts} onChange={(e) => setRepositoryKnownHosts(e.target.value)} required><option value="">Select imported known_hosts</option>{systemdCredentials.filter((item) => item.kind === "known-hosts").map((item) => <option key={item.path} value={item.path}>{item.id}</option>)}</select></Field>
                </>}
                {repositoryProvider === "smb" && <Field label="Encrypted SMB credentials"><select className="pf-v5-c-form-control" value={repositoryCredentials} onChange={(e) => setRepositoryCredentials(e.target.value)} required><option value="">Select imported SMB credential</option>{systemdCredentials.filter((item) => item.kind === "smb").map((item) => <option key={item.path} value={item.path}>{item.id}</option>)}</select></Field>}
                {repositoryProvider === "s3" && <><Field label="rclone remote alias"><input className="pf-v5-c-form-control" value={repositoryRcloneRemote} onChange={(e) => setRepositoryRcloneRemote(e.target.value)} pattern="[A-Za-z0-9_-]{1,64}" maxLength={64} required /></Field><Field label="Encrypted rclone configuration"><select className="pf-v5-c-form-control" value={repositoryCredentials} onChange={(e) => setRepositoryCredentials(e.target.value)} required><option value="">Select imported rclone config</option>{systemdCredentials.filter((item) => item.kind === "rclone").map((item) => <option key={item.path} value={item.path}>{item.id}</option>)}</select></Field><p>Configure S3 endpoint and credentials in this rclone config file. Remote path is /bucket/prefix.</p></> }
                <Field label="Port (optional)"><input className="pf-v5-c-form-control" type="number" min="1" max="65535" value={repositoryPort} onChange={(e) => setRepositoryPort(e.target.value)} /></Field>
                <Field label="Mount access"><select className="pf-v5-c-form-control" value={repositoryReadOnly ? "ro" : "rw"} onChange={(e) => setRepositoryReadOnly(e.target.value === "ro")}>
                  <option value="ro">Read-only</option><option value="rw" disabled={repositoryProvider === "s3"}>Read/write (image capture)</option>
                </select></Field>
                <Button type="submit" variant="primary" isDisabled={busy || !repositoryId || !repositoryHost || !repositoryPath}>{repositoryEditing ? "Update repository definition" : "Save repository definition"}</Button>{" "}{repositoryEditing && <Button type="button" variant="link" onClick={resetRemoteRepositoryForm} isDisabled={busy}>Cancel edit</Button>}
              </form></CardBody></Card></StackItem>
                            <StackItem><Title headingLevel="h2" size="lg">Encrypted repository credentials</Title>
                <p>Import a root-owned private source file (mode 0600, no symlinks or hard links). Cockpit submits only its path; the API encrypts its contents with systemd-creds and never returns secret material. The source file remains in place and must be protected or securely removed by the operator.</p>
                <Card><CardBody><form onSubmit={importSystemdCredential}>
                  <Field label="Credential ID"><input className="pf-v5-c-form-control" value={credentialId} onChange={(e) => setCredentialId(e.target.value)} pattern="[a-z0-9][a-z0-9-]{0,47}" maxLength={48} required /></Field>
                  <Field label="Credential type"><select className="pf-v5-c-form-control" value={credentialKind} onChange={(e) => setCredentialKind(e.target.value)}><option value="ssh-key">SSH private key</option><option value="known-hosts">SSH known_hosts</option><option value="smb">SMB credentials</option><option value="rclone">rclone config (S3)</option></select></Field>
                  <Field label="Protected source file path"><input className="pf-v5-c-form-control" value={credentialSourceFile} onChange={(e) => setCredentialSourceFile(e.target.value)} maxLength={512} required /></Field>
                  <label><input type="checkbox" checked={credentialReplace} onChange={(e) => setCredentialReplace(e.target.checked)} /> Replace an existing credential with this ID and type</label>
                  <Button type="submit" variant="primary" isDisabled={busy || !credentialId || !credentialSourceFile}>Import and encrypt credential</Button>
                </form></CardBody></Card>
                <Table aria-label="Encrypted repository credentials" variant="compact"><Thead><Tr><Th>ID</Th><Th>Type</Th><Th>Encrypted reference</Th><Th>Action</Th></Tr></Thead><Tbody>
                  {systemdCredentials.map((credential) => <Tr key={credential.name}><Td>{credential.id}</Td><Td>{credential.kind}</Td><Td>{credential.path}</Td><Td><Button size="sm" variant="danger" isDisabled={busy || remoteRepositories.some((repo) => (repo.credential_refs || []).includes(credential.path))} onClick={() => removeSystemdCredential(credential)}>Remove</Button></Td></Tr>)}
                  {!systemdCredentials.length && <Tr><Td colSpan={4}>No encrypted credentials imported.</Td></Tr>}
                </Tbody></Table>
              </StackItem>
              <StackItem><Title headingLevel="h2" size="lg">Import a signed image set from SFTP</Title>
                <p>The remote directory must contain manifest.json, manifest.json.minisig and every artifact named by the signed manifest. The manifest is verified with the locally trusted Feclora Server public key before artifact download. Imported files become visible in the local image inventory.</p>
                <Card><CardBody><form onSubmit={fetchSftpImageSet}>
                  <Field label="Saved SFTP repository">
                    <select className="pf-v5-c-form-control" value={sftpRepositoryId} onChange={(e) => selectSftpRepository(e.target.value)}>
                      <option value="">Use one-time connection details…</option>
                      {sftpRepositories.map((item) => <option key={item.id} value={item.id}>{item.id} · {item.username}@{item.host}:{item.port}{item.remote_directory}</option>)}
                    </select>
                  </Field>
                  <Field label="Saved repository ID"><input className="pf-v5-c-form-control" value={sftpRepositoryId} onChange={(e) => setSftpRepositoryId(e.target.value)} maxLength={48} placeholder="e.g. offsite-backup" /></Field>
                  <p>Saved definitions contain only the SFTP endpoint and encrypted credential references. Private-key and known_hosts contents remain in systemd credentials.</p>
                  <Button type="button" variant="secondary" onClick={saveSftpRepository} isDisabled={busy || !sftpRepositoryId || !sftpHost || !sftpUsername || !sftpRemoteDirectory || !sftpIdentity || !sftpKnownHosts}>Save connection</Button>{" "}
                  <Button type="button" variant="secondary" onClick={removeSftpRepository} isDisabled={busy || !sftpRepositoryId || !sftpRepositories.some((item) => item.id === sftpRepositoryId)}>Remove saved connection</Button>
                  <Field label="SFTP host"><input className="pf-v5-c-form-control" value={sftpHost} onChange={(e) => setSftpHost(e.target.value)} maxLength={253} required /></Field>
                  <Field label="SSH username"><input className="pf-v5-c-form-control" value={sftpUsername} onChange={(e) => setSftpUsername(e.target.value)} maxLength={64} required /></Field>
                  <Field label="Remote image directory"><input className="pf-v5-c-form-control" value={sftpRemoteDirectory} onChange={(e) => setSftpRemoteDirectory(e.target.value)} maxLength={1024} required /></Field>
                  <Field label="SSH port"><input className="pf-v5-c-form-control" type="number" min="1" max="65535" value={sftpPort} onChange={(e) => setSftpPort(e.target.value)} required /></Field>
                  <Field label="Encrypted SSH private-key credential"><select className="pf-v5-c-form-control" value={sftpIdentity} onChange={(e) => setSftpIdentity(e.target.value)} required><option value="">Select imported SSH key</option>{systemdCredentials.filter((item) => item.kind === "ssh-key").map((item) => <option key={item.path} value={item.path}>{item.id}</option>)}</select></Field>
                  <Field label="Encrypted pinned SSH known_hosts credential"><select className="pf-v5-c-form-control" value={sftpKnownHosts} onChange={(e) => setSftpKnownHosts(e.target.value)} required><option value="">Select imported known_hosts</option>{systemdCredentials.filter((item) => item.kind === "known-hosts").map((item) => <option key={item.path} value={item.path}>{item.id}</option>)}</select></Field>
                  <Button type="button" variant="secondary" onClick={listSftpImageManifests} isDisabled={busy || !sftpHost || !sftpUsername || !sftpRemoteDirectory || !sftpIdentity || !sftpKnownHosts}>List remote image manifests</Button>{" "}
                  <Button type="button" variant="secondary" onClick={inspectSftpImageSet} isDisabled={busy || !sftpHost || !sftpUsername || !sftpRemoteDirectory || !sftpIdentity || !sftpKnownHosts}>Verify signed remote image metadata</Button>{" "}
                  <Button type="submit" variant="primary" isDisabled={busy || !sftpHost || !sftpUsername || !sftpRemoteDirectory || !sftpIdentity || !sftpKnownHosts}>Fetch, verify and import image</Button>
                </form>
                {sftpRemoteInventory !== null && <div className="pf-v5-c-content pf-v5-u-mt-md"><strong>Remote manifest markers</strong>{sftpRemoteInventory.length ? <ul>{sftpRemoteInventory.map((name) => <li key={name}>{name}</li>)}</ul> : <p>No Feclora image manifest marker was found in this directory.</p>}</div>}
                {sftpRemoteInspection && <div className="pf-v5-c-content pf-v5-u-mt-md"><strong>Authenticated remote image</strong><p>{sftpRemoteInspection.image_id} · {sftpRemoteInspection.image_type} · {sftpRemoteInspection.artifact_count} artifacts · {sftpRemoteInspection.source_size_bytes} bytes</p><p>Manifest signature verified against the configured Feclora trust key. Artifact bytes have not yet been downloaded or verified.</p><ul>{sftpRemoteInspection.artifacts.map((item) => <li key={item.filename}>{item.filename} · {item.role} · {item.size_bytes} bytes · {item.encryption}</li>)}</ul></div>}
                </CardBody></Card>
              </StackItem>
              <StackItem><Title headingLevel="h2" size="lg">Publish a signed image set to SFTP</Title>
                <p>Publishes an already captured and signed image from the local repository. The local minisign public key is used to verify the manifest before transfer. The remote directory must already exist and be empty for these filenames; existing remote files are never overwritten.</p>
                <Card><CardBody><form onSubmit={publishSftpImageSet}>
                  <Field label="Local signed image"><select className="pf-v5-c-form-control" value={sftpPublishImageId} onChange={(e) => setSftpPublishImageId(e.target.value)} required>
                    <option value="">Select a signed local image…</option>
                    {images.filter((item) => item.signed).map((item) => <option key={item.image_id} value={item.image_id}>{item.image_id} · {item.image_type}</option>)}
                  </select></Field>
                  <Field label="SFTP host"><input className="pf-v5-c-form-control" value={sftpHost} onChange={(e) => setSftpHost(e.target.value)} maxLength={253} required /></Field>
                  <Field label="SSH username"><input className="pf-v5-c-form-control" value={sftpUsername} onChange={(e) => setSftpUsername(e.target.value)} maxLength={64} required /></Field>
                  <Field label="Remote image directory"><input className="pf-v5-c-form-control" value={sftpRemoteDirectory} onChange={(e) => setSftpRemoteDirectory(e.target.value)} maxLength={1024} required /></Field>
                  <Field label="SSH port"><input className="pf-v5-c-form-control" type="number" min="1" max="65535" value={sftpPort} onChange={(e) => setSftpPort(e.target.value)} required /></Field>
                  <Field label="Encrypted SSH private-key credential"><select className="pf-v5-c-form-control" value={sftpIdentity} onChange={(e) => setSftpIdentity(e.target.value)} required><option value="">Select imported SSH key</option>{systemdCredentials.filter((item) => item.kind === "ssh-key").map((item) => <option key={item.path} value={item.path}>{item.id}</option>)}</select></Field>
                  <Field label="Encrypted pinned SSH known_hosts credential"><select className="pf-v5-c-form-control" value={sftpKnownHosts} onChange={(e) => setSftpKnownHosts(e.target.value)} required><option value="">Select imported known_hosts</option>{systemdCredentials.filter((item) => item.kind === "known-hosts").map((item) => <option key={item.path} value={item.path}>{item.id}</option>)}</select></Field>
                  <Button type="submit" variant="primary" isDisabled={busy || !sftpPublishImageId || !sftpHost || !sftpUsername || !sftpRemoteDirectory || !sftpIdentity || !sftpKnownHosts}>Publish signed image set</Button>
                </form></CardBody></Card>
              </StackItem>
              <StackItem><Title headingLevel="h2" size="lg">Configured repositories</Title>
                <Table aria-label="Remote image repositories" variant="compact"><Thead><Tr><Th>ID</Th><Th>Provider</Th><Th>Remote location</Th><Th>Access</Th><Th>Mount state</Th><Th>Actions</Th></Tr></Thead><Tbody>
                  {remoteRepositories.map((repo) => <Tr key={repo.id}><Td>{repo.id}</Td><Td>{repo.provider}</Td><Td>{repo.host}:{repo.remote_path}<br />{repo.mountpoint}</Td><Td>{repo.read_only ? "Read-only" : "Read/write"}</Td><Td>{repo.mounted ? (repo.verified ? <Label color="green">Mounted · verified</Label> : <><Label color="red">Mounted · unverified</Label>{repo.mount_error && <div className="pf-v5-u-color-danger pf-v5-u-font-size-sm">{repo.mount_error}</div>}</>) : <Label color="grey">Unmounted</Label>}</Td><Td>
                    <Button size="sm" variant="secondary" isDisabled={busy || repo.mounted} onClick={() => editRemoteRepository(repo)}>Edit</Button>{" "}
                    <Button size="sm" variant="secondary" isDisabled={busy} onClick={() => runRemoteRepositoryAction("check_remote_repository", repo.id)}>Check mount</Button>{" "}
                    <Button size="sm" variant="secondary" isDisabled={busy || repo.mounted} onClick={() => runRemoteRepositoryAction("mount_remote_repository", repo.id)}>Mount</Button>{" "}
                    <Button size="sm" variant="secondary" isDisabled={busy || !repo.mounted} onClick={() => runRemoteRepositoryAction("unmount_remote_repository", repo.id)}>Unmount</Button>{" "}
                    <Button size="sm" variant="danger" isDisabled={busy || repo.mounted} onClick={() => runRemoteRepositoryAction("remove_remote_repository", repo.id)}>Remove</Button>
                  </Td></Tr>)}
                  {!remoteRepositories.length && <Tr><Td colSpan={6}>No remote repositories configured.</Td></Tr>}
                </Tbody></Table>
              </StackItem>
            </Stack>
          </Tab>
          <Tab eventKey="operation-log" title="Operation log">
            <Stack hasGutter className="pf-v5-u-pt-lg"><StackItem><Title headingLevel="h2" size="xl">Local operation history</Title><p>Durable local operation definitions and state history, including worker progress and terminal diagnostics. Interrupted writes require operator inspection and are never resumed automatically.</p><Title headingLevel="h2" size="xl">Local operation history</Title><p>Durable local operation definitions and state history, including worker progress and terminal diagnostics. Cancelled or interrupted restores and clones may have partially modified their destination; inspect the target before reusing it. Cancel requests are orderly but can take time to stop child processes.</p></StackItem>
              <StackItem><Table aria-label="Local operation history" variant="compact"><Thead><Tr><Th>Timestamp</Th><Th>Operation</Th><Th>Target</Th><Th>Image</Th><Th>Status</Th><Th>Progress</Th><Th>Operation ID</Th><Th>Details</Th><Th>Control</Th></Tr></Thead><Tbody>
                {operations.map((item) => {
                  const events = item.events || [];
                  const latest = events[events.length - 1] || {};
                  const progress = [...events].reverse().find((event) => event.state === "progress");
                  const details = { ...(events[0]?.details || {}), ...(latest.details || {}) };
                  const progressDetails = progress?.details || {};
                  return <Tr key={item.operation_id}>
                    <Td>{latest.timestamp || "—"}</Td><Td>{item.action || "—"}</Td>
                    <Td>{details.target || details.source || "—"}</Td><Td>{details.image_id || "—"}</Td>
                    <Td><Label color={item.state === "completed" ? "green" : ["failed", "cancelled", "interrupted"].includes(item.state) ? "red" : "orange"}>{item.state || "unknown"}</Label></Td>
                    <Td>{progress ? formatBytes(progressDetails.bytes_done || 0) + (progressDetails.bytes_total !== null && progressDetails.bytes_total !== undefined ? " / " + formatBytes(progressDetails.bytes_total) : " processed") : "—"}</Td>
                    <Td>{item.operation_id}</Td><Td>{details.destination_may_be_partial ? <><strong>Destination may be partially written.</strong> {details.reason || "Inspect it before reuse."}</> : details.error ? <><strong>{details.error_type || "Operation error"}:</strong> {details.error}</> : details.reason || "—"}</Td>
                    <Td>{["queued", "preflight", "running"].includes(item.state) ? <Button size="sm" variant="danger" isDisabled={cancellingOperationId === item.operation_id} onClick={() => cancelLocalOperation(item.operation_id)}>{cancellingOperationId === item.operation_id ? "Requesting…" : "Cancel"}</Button> : "—"}</Td>
                  </Tr>;
                })}
                {!operations.length && <Tr><Td colSpan={9}>No local operations recorded.</Td></Tr>}
              </Tbody></Table></StackItem>
            </Stack>
          </Tab>
          <Tab eventKey="network" title="Network (Server / Client)">
            <Stack hasGutter className="pf-v5-u-pt-lg">
              <StackItem>
                <Title headingLevel="h2" size="xl">Host IPv4 configuration</Title>
                <p>Configure the NetworkManager profile on this machine. Use this page on the Server or on each Client independently.</p>
                <Alert variant="warning" title="Management connectivity protection" isInline>
                  Changes run under a 120-second NetworkManager checkpoint. If activation or verification fails, Feclora requests rollback; if Cockpit disconnects or the process is interrupted, NetworkManager automatically restores the previous network state when the checkpoint expires. Keep local console access available.
                </Alert>
              </StackItem>
              <StackItem>
                <form onSubmit={applyNetworkProfile}>
                  <Field label="NetworkManager connection profile">
                    <select className="pf-v5-c-form-control" value={networkProfileUuid} onChange={(event) => setNetworkProfileUuid(event.target.value)} required>
                      <option value="">Select profile…</option>
                      {networkProfiles.map((profile) => <option key={profile.uuid} value={profile.uuid} disabled={!profile.device}>{profile.name} · {profile.type} · {profile.device || "not active"}{profile.active ? " · active" : ""}</option>)}
                    </select>
                  </Field>
                  <Field label="IPv4 configuration">
                    <select className="pf-v5-c-form-control" value={networkMethod} onChange={(event) => setNetworkMethod(event.target.value)}>
                      <option value="auto">DHCP (automatic)</option>
                      <option value="manual">Static IPv4</option>
                    </select>
                  </Field>
                  {networkMethod === "manual" && <>
                    <Field label="IPv4 address"><input className="pf-v5-c-form-control" value={networkAddress} onChange={(event) => setNetworkAddress(event.target.value)} required placeholder="192.0.2.10" /></Field>
                    <Field label="Prefix length"><input className="pf-v5-c-form-control" type="number" min="1" max="30" value={networkPrefix} onChange={(event) => setNetworkPrefix(event.target.value)} required /></Field>
                    <Field label="Gateway (optional)"><input className="pf-v5-c-form-control" value={networkGateway} onChange={(event) => setNetworkGateway(event.target.value)} placeholder="192.0.2.1" /></Field>
                    <Field label="DNS servers (comma-separated, optional)"><input className="pf-v5-c-form-control" value={networkDns} onChange={(event) => setNetworkDns(event.target.value)} placeholder="192.0.2.53, 192.0.2.54" /></Field>
                  </>}
                  <Button type="submit" variant="primary" isLoading={busy} isDisabled={busy || !networkProfileUuid}>Apply and verify network configuration</Button>
                </form>
                {networkApplyResult && <Alert variant="success" title="Network configuration verified" isInline className="pf-v5-u-mt-md">Interface {networkApplyResult.interface}, mode {networkApplyResult.method}, address {networkApplyResult.address || "assigned by DHCP"}.</Alert>}
              </StackItem>
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
              {status?.server_configured && <StackItem><Card><CardBody>
                <Title headingLevel="h3" size="lg">Encrypted offline CA backup</Title>
                <Alert variant="warning" title="Protect the root CA signing key" isInline>The backup contains the CA private key and certificate, encrypted to the age recipient below. Keep the matching age identity separately and offline. Without that identity, the backup cannot be recovered. Never store the decryption identity beside this backup.</Alert>
                <Field label="Mounted removable-media directory" help="Use a mounted USB filesystem under /run/media, /media or /mnt.">
                  <input className="pf-v5-c-form-control" value={caBackupDirectory} onChange={(event) => { setCaBackupDirectory(event.target.value); setCaBackupResult(null); }} placeholder="/run/media/.../BACKUPS" />
                </Field>
                <Field label="age public recipient" help="Use a recovery recipient whose private identity is held separately and securely.">
                  <input className="pf-v5-c-form-control" value={caBackupRecipient} onChange={(event) => { setCaBackupRecipient(event.target.value); setCaBackupResult(null); }} placeholder="age1..." />
                </Field>
                <Button variant="primary" onClick={exportServerCABackup} isLoading={busy} isDisabled={busy || !caBackupDirectory || !/^age1[0-9a-z]{20,}$/.test(caBackupRecipient.trim())}>Create encrypted CA backup</Button>
                {caBackupResult && <Alert variant="success" title="Encrypted CA backup created" isInline>{caBackupResult.backup_file} · SHA-256 {caBackupResult.sha256} · CA fingerprint {caBackupResult.ca_fingerprint}</Alert>}
                <hr />
                <Title headingLevel="h4" size="md">Verify an offline CA backup</Title>
                <Alert variant="info" title="Verification only" isInline>This decrypts into a private temporary directory and validates the archive, manifest, CA certificate and matching private key. It does not install or replace any live PKI files. Select the encrypted archive and its age identity from mounted removable media. Keep the identity on separate media from the archive.</Alert>
                <Field label="Encrypted CA backup file" help="Mounted removable-media file under /run/media, /media or /mnt; maximum 16 MiB.">
                  <input className="pf-v5-c-form-control" value={caBackupInspectionFile} onChange={(event) => { setCaBackupInspectionFile(event.target.value); setCaBackupInspection(null); }} placeholder="/run/media/.../feclora-ca-backup.tar.age" />
                </Field>
                <Field label="age decryption identity file" help="The root-owned identity file corresponding to the backup recipient; keep it separate from the archive.">
                  <input className="pf-v5-c-form-control" value={caBackupIdentityFile} onChange={(event) => { setCaBackupIdentityFile(event.target.value); setCaBackupInspection(null); }} placeholder="/run/media/.../recovery-identity.txt" />
                </Field>
                <Button variant="secondary" onClick={inspectServerCABackup} isLoading={busy} isDisabled={busy || !caBackupInspectionFile || !caBackupIdentityFile}>Decrypt and verify backup</Button>
                {caBackupInspection && <Alert variant="success" title="CA backup verified; live PKI unchanged" isInline>CA fingerprint {caBackupInspection.ca_fingerprint}. {caBackupInspection.message}</Alert>}
              </CardBody></Card></StackItem>}
              {status?.server_configured && <StackItem><Card><CardBody>
                <Title headingLevel="h3" size="lg">Rotate Server TLS keypair</Title>
                <Alert variant="warning" title="New Server private key; existing CA retained" isInline>This is separate from certificate renewal. All deployment jobs must be stopped. The new key and certificate are validated before installation; enrolled Clients continue to trust the existing CA and Server identity. This does not rotate the CA or image-signing key.</Alert>
                <Field label="Type exactly: ROTATE SERVER TLS KEYPAIR">
                  <input className="pf-v5-c-form-control" value={serverRotateConfirmation} onChange={(event) => setServerRotateConfirmation(event.target.value)} />
                </Field>
                <Button variant="danger" onClick={rotateServerKeypair} isLoading={busy} isDisabled={busy || serverRotateConfirmation !== "ROTATE SERVER TLS KEYPAIR"}>Rotate Server TLS keypair</Button>
                {serverRotateResult && <Alert variant="success" title="Server TLS keypair rotated" isInline>{serverRotateResult.message} · New certificate expires in {serverRotateResult.expiry_days} days; CA expires in {serverRotateResult.ca_expiry_days} days.</Alert>}
              </CardBody></Card></StackItem>}
              {status?.server_configured && <StackItem><Card><CardBody>
                <Title headingLevel="h3" size="lg">Renew Server TLS certificate</Title>
                <Alert variant="warning" title="Existing CA and private key will be retained" isInline>Renewal is blocked while any deployment job service is active. The Server certificate is replaced atomically; existing Clients continue trusting the same CA and Server identity. This does not rotate the CA or the Server private key.</Alert>
                <Field label="Type exactly: RENEW SERVER CERTIFICATE">
                  <input className="pf-v5-c-form-control" value={serverRenewConfirmation} onChange={(event) => setServerRenewConfirmation(event.target.value)} />
                </Field>
                <Button variant="danger" onClick={renewServerCertificate} isLoading={busy} isDisabled={busy || serverRenewConfirmation !== "RENEW SERVER CERTIFICATE"}>Renew Server certificate</Button>
                {serverRenewResult && <Alert variant="success" title="Server certificate renewed" isInline>{serverRenewResult.message} · Server certificate expires in {serverRenewResult.expiry_days} days; CA expires in {serverRenewResult.ca_expiry_days} days.</Alert>}
              </CardBody></Card></StackItem>}
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
                <label><input type="checkbox" checked={csrRenewal} onChange={(event) => { setCsrRenewal(event.target.checked); setCsrReview(null); setCsrConfirmation(""); }} /> This CSR renews an already-enrolled Client certificate (preserve its MAC, age identity and image-signing trust)</label>
                <Button variant="secondary" onClick={inspectClientCSR} isLoading={busy} isDisabled={busy || !csrPath || !ageRecipientPath || !clientMac}>Inspect {csrRenewal ? "renewal" : "enrollment"} request</Button>
                {csrApprovalResult && <Card className="pf-v5-u-mt-md"><CardBody>
                  <Alert variant="success" title={csrApprovalResult.renewal ? "Client certificate renewed" : "Client enrolled"} isInline>{csrApprovalResult.message}</Alert>
                  <p>Identity: {csrApprovalResult.identity} · MAC: {csrApprovalResult.mac_address}</p>
                  <p>Response bundle: {csrApprovalResult.bundle_directory}</p>
                  <p>Feclora CA SHA-256 fingerprint (verify on Client):</p><code>{csrApprovalResult.ca_fingerprint}</code>
                  <p>Server minisign public-key SHA-256 fingerprint (verify on Client):</p><code>{csrApprovalResult.server_minisign_sha256}</code>
                  <p>Client image capture: {csrApprovalResult.image_capture_enabled ? "authorized" : "not authorized"}</p>
                </CardBody></Card>}
                {csrReview && <Card className="pf-v5-u-mt-md"><CardBody>
                  <Alert variant="warning" title={csrReview.renewal === "true" ? "Review Client certificate renewal" : "Review this identity before enrollment"} isInline>Identity: {csrReview.identity} · MAC: {csrReview.mac_address}. Image capture permission: {csrReview.image_capture_enabled === "true" ? "enabled" : "not granted"}. {csrReview.renewal === "true" ? "Only the TLS certificate will be renewed; existing trust mappings remain unchanged." : "No enrollment has occurred yet."}</Alert>
                  <p>To approve, type this exact phrase:</p><code>{csrReview.confirmation_phrase}</code>
                  <Field label="Explicit enrollment confirmation">
                    <input className="pf-v5-c-form-control" value={csrConfirmation} onChange={(e) => setCsrConfirmation(e.target.value)} />
                  </Field>
                  <Button variant="danger" onClick={approveClientCSR} isLoading={busy} isDisabled={busy || csrConfirmation !== csrReview.confirmation_phrase}>Approve CSR, {csrReview.renewal === "true" ? "renew certificate and export response bundle" : "enroll Client and export response bundle"}</Button>
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
              {status?.client_configured ? <StackItem><Card><CardBody>
                <Title headingLevel="h3" size="lg">Renew Client TLS certificate</Title>
                <Alert variant="info" title="Key-preserving renewal" isInline>The existing TLS private key, age identity, MAC authorization and image-signing key are retained. Only the TLS certificate is replaced after verifying the Server CA fingerprint and response bundle.</Alert>
                <Field label="Mounted removable-media directory for renewal request"><input className="pf-v5-c-form-control" value={clientRenewalExportDirectory} onChange={(event) => { setClientRenewalExportDirectory(event.target.value); setClientRenewalPrepared(null); }} placeholder="/run/media/liveuser/USB" /></Field>
                <Button variant="primary" onClick={prepareClientRenewal} isLoading={busy} isDisabled={busy || !clientRenewalExportDirectory}>Prepare renewal CSR</Button>
                {clientRenewalPrepared && <Alert variant="success" title="Renewal request prepared" isInline>{clientRenewalPrepared.message}<p>Identity: {clientRenewalPrepared.identity}</p><p>CSR: {clientRenewalPrepared.csr_file}</p><p>Age recipient: {clientRenewalPrepared.age_recipient_file}</p>{clientRenewalPrepared.minisign_public_file && <p>Existing public minisign key: {clientRenewalPrepared.minisign_public_file}</p>}</Alert>}
                <Field label="Mounted Server renewal response bundle directory"><input className="pf-v5-c-form-control" value={clientRenewalBundleDirectory} onChange={(event) => setClientRenewalBundleDirectory(event.target.value)} placeholder="/run/media/liveuser/USB" /></Field>
                <Field label="Feclora CA SHA-256 fingerprint"><input className="pf-v5-c-form-control" value={clientCaFingerprint} onChange={(event) => setClientCaFingerprint(event.target.value)} /></Field>
                <Field label="Server minisign public-key SHA-256 fingerprint"><input className="pf-v5-c-form-control" value={clientServerFingerprint} onChange={(event) => setClientServerFingerprint(event.target.value)} /></Field>
                <Button variant="danger" onClick={completeClientRenewal} isLoading={busy} isDisabled={busy || !clientRenewalBundleDirectory || !clientCaFingerprint || !clientServerFingerprint}>Verify and install renewed certificate</Button>
                {clientRenewalCompleted && <Alert variant="success" title="Client certificate renewed" isInline>{clientRenewalCompleted.message}</Alert>}
              </CardBody></Card></StackItem> : <>
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
                <p>Inspect the Server job over enrolled mTLS, choose this machine's local target, type the exact destructive/read confirmation, then connect. The Client reports READY after approval and waits for the Server operator to authorize and start the operation.</p>
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
                  <Field label="Local Client network interface" help="Select the IPv4 address used as the source for the authenticated connection to the Server. The address is revalidated immediately before connection.">
                    <select className="pf-v5-c-form-control" value={clientRemoteInterface} onChange={(event) => { setClientRemoteInterface(event.target.value); setClientRemoteInspection(null); setClientRemoteJobStatus(null); setClientRemoteIgmpConfirmed(false); }}>
                      <option value="">Select Client interface/address…</option>
                      {networkInterfaces.map((item) => <option key={item.binding} value={item.binding}>{item.interface} · {item.address}/{item.prefix_length}</option>)}
                    </select>
                  </Field>
                  <p className="pf-v5-u-color-200 pf-v5-u-font-size-sm">Preflight binds the TCP/TLS connection to this Client IPv4 address, verifies the enrolled Server identity and fetches the job before any local target is approved or storage operation starts.</p>
                  <Button variant="primary" onClick={inspectClientRemoteJob} isLoading={busy} isDisabled={busy || !clientRemoteJobId || !clientRemoteInterface}>Test connectivity and inspect authenticated job</Button>
                  <Button variant="link" onClick={refreshClientRemoteJobStatus} isLoading={busy} isDisabled={busy || !clientRemoteJobId}>Check existing Client job status</Button>
                </StackItem>
                {clientRemoteJob && <StackItem>
                  <Card><CardBody>
                    <Title headingLevel="h3" size="lg">Authenticated Server job</Title>
                    <p>Operation: {clientRemoteJob.operation}{clientRemoteJob.operation === "clone" ? " · Server source: " + clientRemoteJob.source_device : " · Image: " + clientRemoteJob.image_id}</p>
                    <p>Target type: {clientRemoteJob.target_type} · Transport: {clientRemoteJob.transport}</p>
                    <p>Server identity: {clientRemoteInspection.server_identity}</p>
                    <p>Client connection source: {clientRemoteInspection.client_network_interface} · {clientRemoteInspection.client_source_address}</p>
                    <p>Authorized Client MACs: {(clientRemoteJob.authorized_clients || []).join(", ")}</p>
                    {clientRemoteJob.transport === "multicast" && <Alert variant="warning" title="Multicast network requirements" isInline>All authorized Clients must be READY before the Server operator authorizes and starts the operation. Confirm UDP multicast reachability, switch IGMP snooping and an active querier on the same VLAN. UDPcast data packets are not encrypted or authenticated; mTLS protects only the control channel.</Alert>}
                    {clientRemoteJob.transport === "multicast" && <label><input type="checkbox" checked={clientRemoteIgmpConfirmed} onChange={(event) => setClientRemoteIgmpConfirmed(event.target.checked)} /> I verified IGMP snooping and an active querier on this VLAN, and confirmed all Clients are on the same multicast network.</label>}
                    {(clientRemoteJob.transport === "unicast" || clientRemoteJob.transport === "multicast") && <>

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
                      <Button variant="primary" onClick={startClientRemoteJob} isLoading={busy} isDisabled={busy || !clientRemoteTarget || !clientRemoteConfirmationPhrase || clientRemoteConfirmation !== clientRemoteConfirmationPhrase || (!clientRemoteInterface || (clientRemoteJob.transport === "multicast" && !clientRemoteIgmpConfirmed))}>Connect and wait for Server authorization</Button>
                    </>}
                  </CardBody></Card>
                </StackItem>}
                {clientRemoteJobStatus && <StackItem>
                  <Card><CardBody>
                    <Title headingLevel="h3" size="lg">Client service status</Title>
                    <Label color={clientRemoteJobStatus.phase === "completed" ? "green" : clientRemoteJobStatus.phase === "failed" || clientRemoteJobStatus.phase === "interrupted" ? "red" : "blue"}>{clientRemoteJobStatus.phase}</Label>
                    <p>{clientRemoteJobStatus.detail}</p>
                    {clientRemoteJobStatus.target_description && <p>Approved target: {clientRemoteJobStatus.target_description}</p>}
                    {clientRemoteJobStatus.progress && <p>{clientRemoteJobStatus.progress.phase || "Disk operation"}: {clientRemoteJobStatus.progress.completed_bytes} / {clientRemoteJobStatus.progress.total_bytes ?? "unknown"} bytes{clientRemoteJobStatus.progress.total_bytes > 0 ? " · " + Math.min(100, Math.round(clientRemoteJobStatus.progress.completed_bytes * 100 / clientRemoteJobStatus.progress.total_bytes)) + "%" : ""}</p>}
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
