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
  capture_logical_volume: "Create a logical-volume image",
  restore_disk: "Restore a whole-disk image",
  restore_partition: "Restore a partition image",
  restore_logical_volume: "Restore a logical-volume image",
  clone_disk: "Clone disk to disk",
  clone_partition: "Clone partition to partition"
};

function flattenDevices(devices) {
  if (!Array.isArray(devices)) return [];
  return devices.flatMap((device) => [
    device,
    ...flattenDevices(device?.children)
  ]);
}

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
  const [clientImageSigning, setClientImageSigning] = useState(false);
  const [clientAgeEncryption, setClientAgeEncryption] = useState(false);
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
  const [clientRemoteEncrypt, setClientRemoteEncrypt] = useState(false);
  const [clientRemoteInterface, setClientRemoteInterface] = useState("");
  const [clientRemoteIgmpConfirmed, setClientRemoteIgmpConfirmed] = useState(false);
  const [clientRemoteJobStatus, setClientRemoteJobStatus] = useState(null);
  const [csrPath, setCsrPath] = useState("");
  const [ageRecipientPath, setAgeRecipientPath] = useState("");
  const [clientMac, setClientMac] = useState("");
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
  const [pxeAnswerFile, setPxeAnswerFile] = useState(null);
  const [pxeAnswerPublished, setPxeAnswerPublished] = useState(null);
  const [pxeAgePassphrase, setPxeAgePassphrase] = useState("");
  const [pxeAgePassphraseStatus, setPxeAgePassphraseStatus] = useState({ available: false, waiting: false, submitted: false });
  const [pxeStatus, setPxeStatus] = useState({ active: false, configured: false });
  const [security, setSecurity] = useState({});
  const [encrypt, setEncrypt] = useState(false);
  const [encryptPassphraseMode, setEncryptPassphraseMode] = useState(false);
  const [capturePassphrase, setCapturePassphrase] = useState("");
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
      const [s, i, j, op, inv, net, profiles, pxe, remote, repositories, credentials, sftpSaved] = await Promise.all([
        callFeclora("status"), callFeclora("images"), callFeclora("journals"), callFeclora("local_operations"), callFeclora("inventory"), callFeclora("network_interfaces"), callFeclora("network_connection_profiles"), callFeclora("pxe_service_status"), callFeclora("deployment_jobs"), callFeclora("remote_repositories"), callFeclora("systemd_credentials"), callFeclora("sftp_repositories")
      ]);
      setStatus(s); setSecurity(s.security || {}); setImages(i.images || []); setJournals(j.journals || []); setOperations(op.operations || []); setInventory(inv); setNetworkInterfaces(net.interfaces || []); setNetworkProfiles(profiles.profiles || []); setPxeStatus(pxe); setDeploymentJobs(remote.jobs || []); setRemoteRepositories(repositories.repositories || []); setSystemdCredentials(credentials.credentials || []); setSftpRepositories(sftpSaved.repositories || []);
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  useEffect(() => {
    let active = true;
    const refreshPXEAgePassphraseStatus = () => {
      callFeclora("pxe_age_passphrase_status")
        .then((status) => { if (active) setPxeAgePassphraseStatus(status); })
        .catch(() => { if (active) setPxeAgePassphraseStatus({ available: false, waiting: false, submitted: false }); });
    };
    refreshPXEAgePassphraseStatus();
    const timer = window.setInterval(refreshPXEAgePassphraseStatus, 1500);
    return () => { active = false; window.clearInterval(timer); };
  }, []);


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
  const logicalVolumes = useMemo(() => {
    const groups = inventory?.volume_topology?.volume_groups || [];
    const allVolumes = groups.flatMap((group) => group.logical_volumes || []);
    const identityCounts = new Map();
    for (const lv of allVolumes) {
      if (lv.major_minor) identityCounts.set(lv.major_minor, (identityCounts.get(lv.major_minor) || 0) + 1);
    }
    const result = [];
    for (const group of groups) {
      if (group.status !== "healthy") continue;
      for (const lv of group.logical_volumes || []) {
        if (lv.hidden || lv.snapshot || !lv.major_minor || identityCounts.get(lv.major_minor) !== 1
            || !Number.isSafeInteger(lv.size_bytes) || lv.size_bytes <= 0
            || ![null, undefined, "", "-", "ok", "healthy"].includes(lv.health)) continue;
        const matches = devices.filter((device) => device.major_minor === lv.major_minor);
        if (matches.length === 1) result.push({ ...matches[0], path: lv.path, lvm_name: lv.name, lvm_path: lv.path });
      }
    }
    return result;
  }, [inventory, devices]);
  const inventoryDevices = useMemo(() => flattenDevices(inventory?.devices), [inventory]);
  const clientRemoteJob = clientRemoteInspection?.job;
  const clientRemoteDeviceOptions = clientRemoteJob?.target_type === "logical_volume" ? logicalVolumes : clientRemoteJob?.target_type === "partition" ? partitions : disks;
  const clientRemoteConfirmationPhrase = clientRemoteJob && clientRemoteTarget
    ? (clientRemoteJob.operation === "restore" || clientRemoteJob.operation === "clone"
      ? `ERASE ${clientRemoteTarget}`
      : `READ ${clientRemoteTarget} TO ${clientRemoteInspection.server_identity}`)
    : "";
  const isCapture = operation.startsWith("capture_");
  const isRestore = operation.startsWith("restore_");
  const isDisk = operation.endsWith("_disk");
  const isLogicalVolume = operation === "capture_logical_volume" || operation === "restore_logical_volume";
  const deviceOptions = isDisk ? disks : isLogicalVolume ? logicalVolumes : partitions;
  const selectedRepository = remoteRepositories.find((repo) => repo.id === selectedRepositoryId);
  const availableImages = selectedRepositoryId ? repositoryImages : images;
  const matchingImages = availableImages.filter((item) => item.image_type === (isDisk ? "disk" : isLogicalVolume ? "logical_volume" : "partition"));
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

  useEffect(() => { setConfirmation(""); setProgress(null); setOperationResult(null); if (operation !== "capture_disk") { setEncryptPassphraseMode(false); setCapturePassphrase(""); } }, [operation, source, target, imageId]);

  const runOperation = async (event) => {
    event.preventDefault(); setBusy(true); setError(""); setNotice(""); setProgress(null); setOperationResult(null);
    try {
      let params;
      const sftpPublish = publishAfterCapture ? {
        host: sftpHost, username: sftpUsername, remote_directory: sftpRemoteDirectory,
        port: Number(sftpPort), identity_credential: sftpIdentity,
        known_hosts_credential: sftpKnownHosts
      } : null;
      if (operation === "capture_disk") params = { source, image_id: imageId, compression, encrypt: encrypt || encryptPassphraseMode, ...(encryptPassphraseMode ? { encrypt_passphrase: true } : {}), ...(selectedRepositoryId ? { repository_id: selectedRepositoryId } : {}), ...(sftpPublish ? { sftp_publish: sftpPublish } : {}) };
      else if (operation === "capture_partition") params = { source, image_id: imageId, partition_id: partitionId || imageId, compression, encrypt, ...(selectedRepositoryId ? { repository_id: selectedRepositoryId } : {}), ...(sftpPublish ? { sftp_publish: sftpPublish } : {}) };
      else if (operation === "capture_logical_volume") params = { source, image_id: imageId, compression, encrypt, ...(selectedRepositoryId ? { repository_id: selectedRepositoryId } : {}), ...(sftpPublish ? { sftp_publish: sftpPublish } : {}) };
      else if (isRestore) {
        const sftpSource = !isLogicalVolume && restoreFromSftp && sftpInspectionMatchesCurrent ? {
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
      if (encryptPassphraseMode && (operation !== "capture_disk" || !capturePassphrase)) {
        throw new Error("Enter a passphrase for symmetric whole-disk encryption.");
      }
      const accepted = await callFeclora(operation, params);
      if (encryptPassphraseMode) {
        const oneShotPassphrase = capturePassphrase;
        await callFeclora("provide_capture_passphrase", {
          operation_id: accepted.operation_id, passphrase: oneShotPassphrase
        });
        setCapturePassphrase("");
      }
      setOperations((current) => [{
        operation_id: accepted.operation_id, action: operation, state: "queued",
        events: [{ state: "queued", timestamp: new Date().toISOString(), details: {} }]
      }, ...current.filter((item) => item.operation_id !== accepted.operation_id)]);
      setNotice("Operation accepted by the durable worker. It will continue if Cockpit disconnects. Use Operation log to request cancellation.");
      const result = await waitForLocalOperation(accepted.operation_id, (eventData) => {
        if (eventData.event === "progress") setProgress(eventData);
        if (eventData.event === "state") {
          setOperations((current) => current.map((item) => item.operation_id === accepted.operation_id
            ? { ...item, state: eventData.state }
            : item));
        }
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
      const operationParams = {
        host: sftpHost, username: sftpUsername, remote_directory: sftpRemoteDirectory,
        port: Number(sftpPort), identity_credential: sftpIdentity,
        known_hosts_credential: sftpKnownHosts
      };
      const result = await callFeclora("submit_local_operation", {
        operation: "sftp_inventory", operation_params: operationParams
      });
      setNotice("SFTP inventory queued as durable operation " + result.operation_id + ". Follow its state and cancellation controls in Operation log.");
      const history = await callFeclora("local_operations");
      setOperations(history.operations || []);
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
      setNotice("Remote image manifest validated for " + result.image_id + ".");
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };

  const fetchSftpImageSet = async (event) => {
    event.preventDefault(); setBusy(true); setError(""); setNotice("");
    try {
      const operationParams = {
        host: sftpHost, username: sftpUsername, remote_directory: sftpRemoteDirectory,
        port: Number(sftpPort), identity_credential: sftpIdentity,
        known_hosts_credential: sftpKnownHosts
      };
      const result = await callFeclora("submit_local_operation", {
        operation: "sftp_fetch", operation_params: operationParams
      });
      setNotice("SFTP image import queued as durable operation " + result.operation_id + ". Follow progress and cancellation in Operation log.");
      const history = await callFeclora("local_operations");
      setOperations(history.operations || []);
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };

  const publishSftpImageSet = async (event) => {
    event.preventDefault(); setBusy(true); setError(""); setNotice("");
    try {
      const operationParams = {
        image_id: sftpPublishImageId, host: sftpHost, username: sftpUsername,
        remote_directory: sftpRemoteDirectory, port: Number(sftpPort),
        identity_credential: sftpIdentity, known_hosts_credential: sftpKnownHosts
      };
      const result = await callFeclora("submit_local_operation", {
        operation: "sftp_publish", operation_params: operationParams
      });
      setNotice("SFTP image publication queued as durable operation " + result.operation_id + ". Follow progress and cancellation in Operation log.");
      const history = await callFeclora("local_operations");
      setOperations(history.operations || []);
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
        credential_file: repositoryProvider === "smb" ? repositoryCredentials : null,
        identity_file: repositoryProvider === "sshfs" ? repositoryIdentity : null,
        known_hosts_file: repositoryProvider === "sshfs" ? repositoryKnownHosts : null,
        port: repositoryProvider === "sshfs" || repositoryProvider === "smb" ? (repositoryPort ? Number(repositoryPort) : null) : null,
        read_only: repositoryReadOnly
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
    setRepositoryCredentials(repo.credential_file || "");
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

  const publishPXEAnswer = async () => {
    if (!pxeAnswerFile) return;
    setBusy(true); setError(""); setNotice(""); setPxeAnswerPublished(null);
    try {
      if (pxeAnswerFile.size < 1 || pxeAnswerFile.size > 64 * 1024) throw new Error("The answer file must be between 1 byte and 64 KiB.");
      const answerBuffer = await pxeAnswerFile.arrayBuffer();
      const encode = (buffer) => {
        const bytes = new Uint8Array(buffer);
        let binary = "";
        for (let offset = 0; offset < bytes.length; offset += 0x8000) {
          binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
        }
        return window.btoa(binary);
      };
      const result = await callFeclora("publish_pxe_answer", {
        job_id: crypto.randomUUID(),
        answer_base64: encode(answerBuffer)
      });
      setPxeAnswerPublished(result);
      setNotice(result.message);
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };

  const submitPXEAgePassphrase = async () => {
    if (!pxeAgePassphrase) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await callFeclora("provide_pxe_age_passphrase", { passphrase: pxeAgePassphrase });
      setPxeAgePassphrase("");
      setNotice(result.message);
      setPxeAgePassphraseStatus({ available: true, waiting: false, submitted: true });
    } catch (err) { setError(err?.message || String(err)); }
    finally { setPxeAgePassphrase(""); setBusy(false); }
  };

  const revokePXEAnswer = async () => {
    if (!pxeAnswerPublished?.job_id || !window.confirm("Revoke this job's published PXE answer? Clients that have already downloaded it may still possess a copy.")) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await callFeclora("revoke_pxe_answer", { job_id: pxeAnswerPublished.job_id });
      setPxeAnswerPublished(null);
      setNotice(result.message);
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

  const deploymentArmPhrase = (job) => {
    if (job.transport === "multicast") return "ARM MULTICAST " + job.job_id + " IGMP-VERIFIED";
    if (job.operation === "clone") {
      return "ARM " + job.job_id + " AND READ " + job.source_device;
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
        ...(remoteOperation === "clone" ? { source_device: remoteSourceDevice, target_type: remoteTargetType } : { target_type: remoteTargetType }),
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
      setClientRemoteEncrypt(false);
      setClientRemoteSign(false);
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
        image_encrypt: clientRemoteEncrypt,
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
                      <Field label={isDisk ? "Source disk" : isLogicalVolume ? "Source logical volume" : "Source partition"}>
                        <select className="pf-v5-c-form-control" value={source} onChange={(e) => setSource(e.target.value)}>
                          <option value="">Select a source device…</option>
                          {deviceOptions.map((d) => <option key={d.path} value={d.path}>{d.path}{d.lvm_name ? ` · ${d.lvm_name} (${d.lvm_path})` : ""} · {formatBytes(d.size_bytes)} · {d.model || d.filesystem || d.type}</option>)}
                        </select>
                      </Field>
                      <Field label="Image identifier" help="Use letters, numbers, dots, underscores or hyphens.">
                        <input className="pf-v5-c-form-control" value={imageId} onChange={(e) => setImageId(e.target.value)} maxLength={128} required />
                      </Field>
                      {operation === "capture_partition" && <Field label="Partition identifier"><input className="pf-v5-c-form-control" value={partitionId} onChange={(e) => setPartitionId(e.target.value)} maxLength={128} placeholder={imageId || "e.g. rootfs"} /></Field>}
                      <Field label="Compression">
                        <select className="pf-v5-c-form-control" value={compression} onChange={(e) => setCompression(e.target.value)}>
                          <option value="zstd">Zstandard (recommended)</option><option value="lz4">LZ4 (fast)</option><option value="gzip">Gzip</option><option value="xz">XZ</option><option value="none">None</option>
                        </select>
                      </Field>
                      <Field label="Image security">
                        <label><input type="checkbox" checked={encrypt} disabled={!security.age_encryption_available && !security.age_executable_available} onChange={(e) => { setEncrypt(e.target.checked); if (!e.target.checked) { setEncryptPassphraseMode(false); setCapturePassphrase(""); } }} /> Encrypt artifacts with age</label>
                        {operation === "capture_disk" && encrypt && security.age_executable_available && <>
                          <br />
                          <label><input type="checkbox" checked={encryptPassphraseMode} onChange={(e) => { setEncryptPassphraseMode(e.target.checked); setCapturePassphrase(""); }} /> Use a symmetric passphrase instead of recipient keys</label>
                          {encryptPassphraseMode && <Field label="Image encryption passphrase" help="Sent once to the worker through /run and consumed immediately. It is not saved in the operation journal or image manifest.">
                            <input className="pf-v5-c-form-control" type="password" autoComplete="new-password" value={capturePassphrase} onChange={(e) => setCapturePassphrase(e.target.value)} maxLength={1024} />
                          </Field>}
                        </>}
                        <br />
                        {!security.age_encryption_available && !security.age_executable_available ? <p className="pf-v5-u-color-200">Optional image protection is provisioned during Server setup when the relevant tools are installed. Without them, ordinary capture and restore remain available.</p> : null}
                      </Field>
                      <Field label="SFTP post-capture publication">
                        <label><input type="checkbox" checked={publishAfterCapture} disabled={busy} onChange={(e) => setPublishAfterCapture(e.target.checked)} /> Publish this image set to SFTP after capture and manifest and SHA-256 verification</label>
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
                      {!isLogicalVolume && <Field label="SFTP restore source">
                        <label><input type="checkbox" checked={restoreFromSftp} disabled={busy || !sftpInspectionMatchesCurrent || sftpRemoteInspection?.image_type !== (isDisk ? "disk" : "partition") || Boolean(selectedRepositoryId)} onChange={(e) => {
                          const enabled = e.target.checked;
                          setRestoreFromSftp(enabled);
                          if (enabled) { setImageId(sftpRemoteInspection.image_id); setRestoreLayoutPreview(null); }
                        }} /> Fetch and verify the authenticated SFTP image before restoring it</label>
                        {!sftpInspectionMatchesCurrent && <p>Inspect and verify a remote SFTP image in the Remote Repositories tab using the current connection settings first.</p>}
                        {selectedRepositoryId && <p>Clear the mounted repository selection to restore directly from SFTP.</p>}
                      </Field>}
                      <Field label={isDisk ? "Disk image" : isLogicalVolume ? "Logical-volume image" : "Partition image"}>
                        <select className="pf-v5-c-form-control" value={imageId} disabled={busy || restoreFromSftp} onChange={(e) => {
                          const value = e.target.value;
                          if (!isLogicalVolume && sftpInspectionMatchesCurrent && value === sftpRemoteInspection.image_id) {
                            setRestoreFromSftp(true); setImageId(value); setRestoreLayoutPreview(null);
                          } else {
                            setRestoreFromSftp(false); setImageId(value);
                            if (isDisk) inspectRestoreLayout(value); else setRestoreLayoutPreview(null);
                          }
                        }}>
                          <option value="">Select an image…</option>
                          {matchingImages.map((item) => <option key={item.image_id} value={item.image_id}>{item.image_id} · {formatBytes(item.source_size_bytes)}</option>)}
                          {!isLogicalVolume && sftpInspectionMatchesCurrent && sftpRemoteInspection.image_type === (isDisk ? "disk" : "partition") && <option value={sftpRemoteInspection.image_id}>{sftpRemoteInspection.image_id} · authenticated SFTP image</option>}
                        </select>
                      </Field>
                      <Field label={isDisk ? "Destination disk" : isLogicalVolume ? "Destination logical volume" : "Destination partition"} help={isLogicalVolume ? "Must be an existing active, unmounted linear or thin LV in a healthy VG. Thin-pool free space is estimated, not reserved. Feclora overwrites LV data but does not create or resize LVM metadata." : undefined}>
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
                      {availableImages.filter((item) => item.image_type === "disk").map((item) => <option key={item.image_id} value={item.image_id}>{item.image_id}{""}</option>)}
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
                    Source: {extractPartitionResult.source_image_id} · New image: {extractPartitionResult.image_id} · {extractPartitionResult.encrypted ? "age-encrypted" : "unencrypted"}
                  </Alert>}
                </CardBody></Card>
              </StackItem>
              <StackItem><Table aria-label="Feclora image repository" variant="compact"><Thead><Tr><Th>Image</Th><Th>Type</Th><Th>Source size</Th><Th>Encryption</Th><Th>Artifacts</Th><Th>Verification</Th></Tr></Thead><Tbody>
                {images.map((item) => {
                  const verification = imageVerification[item.image_id];
                  return <Tr key={item.image_id}><Td>{item.image_id}</Td><Td>{item.image_type}</Td><Td>{formatBytes(item.source_size_bytes)}</Td><Td><Label color={item.encrypted ? "green" : "orange"}>{item.encrypted ? "age" : "Plain"}</Label></Td><Td>{item.artifact_count}</Td><Td>
                    <Button size="sm" variant="secondary" isDisabled={busy || verification?.loading} isLoading={verification?.loading} onClick={() => verifyImage(item.image_id)}>Verify</Button>
                    {verification?.report && <div className="pf-v5-u-mt-sm">
                      <Label color="green">Verified</Label> Manifest: {verification.report.manifest} · {verification.report.artifact_count} artifacts · {formatBytes(verification.report.total_decoded_bytes)}
                      {verification.report.artifacts.map((artifact) => <p key={artifact.filename}>{artifact.filename}: stored SHA-256 {artifact.stored_digest}; age {artifact.age_authentication}; compression {artifact.decompression}; decoded {formatBytes(artifact.decoded_bytes)}</p>)}
                    </div>}
                    {verification?.error && <Alert variant="danger" title="Verification failed" isInline>{verification.error}</Alert>}
                  </Td></Tr>;
                })}
                {!availableImages.length && <Tr><Td colSpan={6}>No manifest-backed images found in this repository.</Td></Tr>}
              </Tbody></Table></StackItem>
            </Stack>
          </Tab>
          <Tab eventKey="remote-jobs" title="Remote jobs">
            <Stack hasGutter className="pf-v5-u-pt-lg">
              <StackItem><Title headingLevel="h2" size="xl">Create a remote deployment job</Title>
                <Alert variant="warning" title="Definition only — service not started; no Client contact or disk I/O" isInline>
                  This step validates and journals a job definition. Start its persistent service separately; Clients then connect over Server-authenticated TLS and approve their own local target through the Client-local runtime. Each Client selects and approves its own local destination in the Client jobs tab. No storage operation starts until you explicitly authorize and start it here after all selected Clients report READY.
                </Alert>
              </StackItem>
              <StackItem>
                <Card><CardBody><form onSubmit={createRemoteJob}>
                  <Field label="Operation">
                    <select className="pf-v5-c-form-control" value={remoteOperation} onChange={(e) => { setRemoteOperation(e.target.value); setRemoteImageId(""); setRemoteSourceDevice(""); if (e.target.value === "save" || e.target.value === "clone") { setRemoteTransport("unicast"); setRemoteTargetType("disk"); } }}>
                      <option value="restore">Restore a Server image to Clients</option>
                      <option value="save">Capture whole disks from Clients to Server</option>
                      <option value="clone">Clone a Server disk or partition directly to one Client</option>
                    </select>
                  </Field>
                  {remoteOperation === "restore" && <Field label="Image repository">
                    <select className="pf-v5-c-form-control" value={selectedRepositoryId} disabled={busy} onChange={(e) => { selectImageRepository(e.target.value); setRemoteImageId(""); }}>
                      <option value="">Local Server repository</option>
                      {remoteRepositories.filter((repo) => repo.mounted && repo.verified).map((repo) => <option key={repo.id} value={repo.id}>{repo.id} · {repo.provider}</option>)}
                    </select>
                  </Field>}
                  {remoteOperation === "clone" ? <Field label={remoteTargetType === "disk" ? "Server source disk" : "Server source partition"} help="Select a source already marked read-only. Feclora independently validates its type, geometry and in-use state before streaming.">
                    <select className="pf-v5-c-form-control" value={remoteSourceDevice} onChange={(e) => setRemoteSourceDevice(e.target.value)} required>
                      <option value="">Select read-only source…</option>
                      {inventoryDevices.filter((item) => item.type === (remoteTargetType === "disk" ? "disk" : "part") && item.read_only === true).map((item) => <option key={item.path} value={item.path}>{item.path} · {item.model || (remoteTargetType === "disk" ? "Disk" : "Partition")} · {formatBytes(item.size_bytes)}</option>)}
                    </select>
                  </Field> : <Field label="Image identifier" help={remoteOperation === "restore" ? "Choose an existing disk or partition image. Images are validated against their manifests and SHA-256 digests." : "New identifier for the image captured from Clients."}>
                    {remoteOperation === "restore" ? <select className="pf-v5-c-form-control" value={remoteImageId} onChange={(e) => setRemoteImageId(e.target.value)}>
                      <option value="">Select image…</option>
                      {availableImages.filter((item) => item.image_type === remoteTargetType).map((item) => <option key={item.image_id} value={item.image_id}>{item.image_id}</option>)}
                    </select> : <input className="pf-v5-c-form-control" value={remoteImageId} onChange={(e) => setRemoteImageId(e.target.value)} maxLength={128} required />}
                  </Field>}
                  {(remoteOperation === "restore" || remoteOperation === "clone") && <Field label={remoteOperation === "clone" ? "Clone device type" : "Target type"}>
                    <select className="pf-v5-c-form-control" value={remoteTargetType} onChange={(e) => { setRemoteTargetType(e.target.value); setRemoteImageId(""); setRemoteSourceDevice(""); }}>
                      <option value="disk">Whole disk</option><option value="partition">Partition</option>
                    </select>
                  </Field>}
                  <Field label="Selected Client MAC addresses" help={remoteOperation === "clone" ? "Enter exactly one selected Client MAC. That Client independently selects and confirms a destination of the selected device type." : "Enter exactly one MAC for unicast, or at least two for multicast restore. Server checks that each MAC is selected for this job; MAC is not authentication."}>
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
                    <Alert variant="warning" title="Multicast transport limitation" isInline>UDPcast data packets are not encrypted or authenticated. TLS protects the control plane, not the multicast data stream. Use only on a trusted, isolated deployment network.</Alert>
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
                <p>Manage client-side filesystem mounts and image-set transfers to external services. SSHFS, NFS and SMB/CIFS are filesystem providers. SFTP supports saved endpoint definitions, image inventory in one configured directory, import, publication and optional publication after durable capture. Metadata inspection and artifact transfer are still synchronous; byte-level progress, transfer cancellation and resume remain pending.</p>
                <Alert variant="warning" title="Provider scope" isInline>Cockpit exposes SSHFS, NFS and SMB/CIFS mounts. SFTP is a separate file-transfer workflow with saved endpoint definitions, one-directory manifest inventory, import, publication and optional durable capture-job publication. Transfer metadata inspection and artifact import/publication are synchronous; byte-level progress, cancellation and resume are pending. WebDAV remains unavailable until its per-repository encrypted credential lifecycle is supported.</Alert>
              </StackItem>
              <StackItem><Card><CardBody><form onSubmit={saveRemoteRepository}>
                <Field label="Repository ID"><input className="pf-v5-c-form-control" value={repositoryId} onChange={(e) => setRepositoryId(e.target.value)} pattern="[a-z0-9][a-z0-9-]{0,47}" maxLength={48} readOnly={repositoryEditing} required /></Field>
                <Field label="Provider"><select className="pf-v5-c-form-control" value={repositoryProvider} onChange={(e) => { setRepositoryProvider(e.target.value); setRepositoryPort(e.target.value === "sshfs" ? "22" : ""); }}>
                  <option value="sshfs">SSHFS (remote filesystem over SSH)</option><option value="nfs">NFS</option><option value="smb">SMB/CIFS</option>
                </select></Field>
                <Field label="Server hostname or IPv4 address"><input className="pf-v5-c-form-control" value={repositoryHost} onChange={(e) => setRepositoryHost(e.target.value)} maxLength={253} required /></Field>
                <Field label={repositoryProvider === "smb" ? "Share and optional subdirectory" : "Remote absolute path"}><input className="pf-v5-c-form-control" value={repositoryPath} onChange={(e) => setRepositoryPath(e.target.value)} maxLength={512} required /></Field>
                {(repositoryProvider === "sshfs" || repositoryProvider === "smb") && <Field label="Username"><input className="pf-v5-c-form-control" value={repositoryUsername} onChange={(e) => setRepositoryUsername(e.target.value)} maxLength={64} required /></Field>}
                {repositoryProvider === "sshfs" && <>
                  <Field label="Encrypted SSH private-key credential"><select className="pf-v5-c-form-control" value={repositoryIdentity} onChange={(e) => setRepositoryIdentity(e.target.value)} required><option value="">Select imported SSH key</option>{systemdCredentials.filter((item) => item.kind === "ssh-key").map((item) => <option key={item.path} value={item.path}>{item.id}</option>)}</select></Field>
                  <Field label="Encrypted pinned SSH known_hosts credential"><select className="pf-v5-c-form-control" value={repositoryKnownHosts} onChange={(e) => setRepositoryKnownHosts(e.target.value)} required><option value="">Select imported known_hosts</option>{systemdCredentials.filter((item) => item.kind === "known-hosts").map((item) => <option key={item.path} value={item.path}>{item.id}</option>)}</select></Field>
                </>}
                {repositoryProvider === "smb" && <Field label="Encrypted SMB credentials"><select className="pf-v5-c-form-control" value={repositoryCredentials} onChange={(e) => setRepositoryCredentials(e.target.value)} required><option value="">Select imported SMB credential</option>{systemdCredentials.filter((item) => item.kind === "smb").map((item) => <option key={item.path} value={item.path}>{item.id}</option>)}</select></Field>}
                <Field label="Port (optional)"><input className="pf-v5-c-form-control" type="number" min="1" max="65535" value={repositoryPort} onChange={(e) => setRepositoryPort(e.target.value)} /></Field>
                <Field label="Mount access"><select className="pf-v5-c-form-control" value={repositoryReadOnly ? "ro" : "rw"} onChange={(e) => setRepositoryReadOnly(e.target.value === "ro")}>
                  <option value="ro">Read-only</option><option value="rw">Read/write (image capture)</option>
                </select></Field>
                <Button type="submit" variant="primary" isDisabled={busy || !repositoryId || !repositoryHost || !repositoryPath}>{repositoryEditing ? "Update repository definition" : "Save repository definition"}</Button>{" "}{repositoryEditing && <Button type="button" variant="link" onClick={resetRemoteRepositoryForm} isDisabled={busy}>Cancel edit</Button>}
              </form></CardBody></Card></StackItem>
                            <StackItem><Title headingLevel="h2" size="lg">Encrypted repository credentials</Title>
                <p>Import a root-owned private source file (mode 0600, no symlinks or hard links). Cockpit submits only its path; the API encrypts its contents with systemd-creds and never returns secret material. The source file remains in place and must be protected or securely removed by the operator.</p>
                <Card><CardBody><form onSubmit={importSystemdCredential}>
                  <Field label="Credential ID"><input className="pf-v5-c-form-control" value={credentialId} onChange={(e) => setCredentialId(e.target.value)} pattern="[a-z0-9][a-z0-9-]{0,47}" maxLength={48} required /></Field>
                  <Field label="Credential type"><select className="pf-v5-c-form-control" value={credentialKind} onChange={(e) => setCredentialKind(e.target.value)}><option value="ssh-key">SSH private key</option><option value="known-hosts">SSH known_hosts</option><option value="smb">SMB credentials</option></select></Field>
                  <Field label="Protected source file path"><input className="pf-v5-c-form-control" value={credentialSourceFile} onChange={(e) => setCredentialSourceFile(e.target.value)} maxLength={512} required /></Field>
                  <label><input type="checkbox" checked={credentialReplace} onChange={(e) => setCredentialReplace(e.target.checked)} /> Replace an existing credential with this ID and type</label>
                  <Button type="submit" variant="primary" isDisabled={busy || !credentialId || !credentialSourceFile}>Import and encrypt credential</Button>
                </form></CardBody></Card>
                <Table aria-label="Encrypted repository credentials" variant="compact"><Thead><Tr><Th>ID</Th><Th>Type</Th><Th>Encrypted reference</Th><Th>Action</Th></Tr></Thead><Tbody>
                  {systemdCredentials.map((credential) => <Tr key={credential.name}><Td>{credential.id}</Td><Td>{credential.kind}</Td><Td>{credential.path}</Td><Td><Button size="sm" variant="danger" isDisabled={busy || remoteRepositories.some((repo) => (repo.credential_refs || []).includes(credential.path))} onClick={() => removeSystemdCredential(credential)}>Remove</Button></Td></Tr>)}
                  {!systemdCredentials.length && <Tr><Td colSpan={4}>No encrypted credentials imported.</Td></Tr>}
                </Tbody></Table>
              </StackItem>
              <StackItem><Title headingLevel="h2" size="lg">Import an image set from SFTP</Title>
                <p>The remote directory must contain manifest.json and every artifact named by the manifest. Artifact SHA-256 digests are checked during import. Imported files become visible in the local image inventory.</p>
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
                  <Button type="button" variant="secondary" onClick={inspectSftpImageSet} isDisabled={busy || !sftpHost || !sftpUsername || !sftpRemoteDirectory || !sftpIdentity || !sftpKnownHosts}>Inspect remote image metadata</Button>{" "}
                  <Button type="submit" variant="primary" isDisabled={busy || !sftpHost || !sftpUsername || !sftpRemoteDirectory || !sftpIdentity || !sftpKnownHosts}>Fetch, verify and import image</Button>
                </form>
                {sftpRemoteInventory !== null && <div className="pf-v5-c-content pf-v5-u-mt-md"><strong>Remote manifest markers</strong>{sftpRemoteInventory.length ? <ul>{sftpRemoteInventory.map((name) => <li key={name}>{name}</li>)}</ul> : <p>No Feclora image manifest marker was found in this directory.</p>}</div>}
                {sftpRemoteInspection && <div className="pf-v5-c-content pf-v5-u-mt-md"><strong>Authenticated remote image</strong><p>{sftpRemoteInspection.image_id} · {sftpRemoteInspection.image_type} · {sftpRemoteInspection.artifact_count} artifacts · {sftpRemoteInspection.source_size_bytes} bytes</p><p>Manifest metadata validated. Artifact bytes have not yet been downloaded or verified.</p><ul>{sftpRemoteInspection.artifacts.map((item) => <li key={item.filename}>{item.filename} · {item.role} · {item.size_bytes} bytes · {item.encryption}</li>)}</ul></div>}
                </CardBody></Card>
              </StackItem>
              <StackItem><Title headingLevel="h2" size="lg">Publish an image set to SFTP</Title>
                <p>Publishes an already captured image from the local repository after validating its manifest and SHA-256 digests. The remote directory must already exist and be empty for these filenames; existing remote files are never overwritten.</p>
                <Card><CardBody><form onSubmit={publishSftpImageSet}>
                  <Field label="Local image"><select className="pf-v5-c-form-control" value={sftpPublishImageId} onChange={(e) => setSftpPublishImageId(e.target.value)} required>
                    <option value="">Select a local image…</option>
                    {images.map((item) => <option key={item.image_id} value={item.image_id}>{item.image_id} · {item.image_type}</option>)}
                  </select></Field>
                  <Field label="SFTP host"><input className="pf-v5-c-form-control" value={sftpHost} onChange={(e) => setSftpHost(e.target.value)} maxLength={253} required /></Field>
                  <Field label="SSH username"><input className="pf-v5-c-form-control" value={sftpUsername} onChange={(e) => setSftpUsername(e.target.value)} maxLength={64} required /></Field>
                  <Field label="Remote image directory"><input className="pf-v5-c-form-control" value={sftpRemoteDirectory} onChange={(e) => setSftpRemoteDirectory(e.target.value)} maxLength={1024} required /></Field>
                  <Field label="SSH port"><input className="pf-v5-c-form-control" type="number" min="1" max="65535" value={sftpPort} onChange={(e) => setSftpPort(e.target.value)} required /></Field>
                  <Field label="Encrypted SSH private-key credential"><select className="pf-v5-c-form-control" value={sftpIdentity} onChange={(e) => setSftpIdentity(e.target.value)} required><option value="">Select imported SSH key</option>{systemdCredentials.filter((item) => item.kind === "ssh-key").map((item) => <option key={item.path} value={item.path}>{item.id}</option>)}</select></Field>
                  <Field label="Encrypted pinned SSH known_hosts credential"><select className="pf-v5-c-form-control" value={sftpKnownHosts} onChange={(e) => setSftpKnownHosts(e.target.value)} required><option value="">Select imported known_hosts</option>{systemdCredentials.filter((item) => item.kind === "known-hosts").map((item) => <option key={item.path} value={item.path}>{item.id}</option>)}</select></Field>
                  <Button type="submit" variant="primary" isDisabled={busy || !sftpPublishImageId || !sftpHost || !sftpUsername || !sftpRemoteDirectory || !sftpIdentity || !sftpKnownHosts}>Publish image set</Button>
                </form></CardBody></Card>
              </StackItem>
              <StackItem><Title headingLevel="h2" size="lg">Configured repositories</Title>
                <p>“Identity verified” confirms only that findmnt reports the expected source, filesystem type and access mode. It does not test live network connectivity, read/write I/O, latency, free space or quota; use an actual repository operation to validate access.</p>
                <Table aria-label="Remote image repositories" variant="compact"><Thead><Tr><Th>ID</Th><Th>Provider</Th><Th>Remote location</Th><Th>Access</Th><Th>Mount identity</Th><Th>Actions</Th></Tr></Thead><Tbody>
                  {remoteRepositories.map((repo) => <Tr key={repo.id}><Td>{repo.id}</Td><Td>{repo.provider}</Td><Td>{repo.host}:{repo.remote_path}<br />{repo.mountpoint}</Td><Td>{repo.read_only ? "Read-only" : "Read/write"}</Td><Td>{repo.mounted ? (repo.verified ? <Label color="green">Mounted · identity verified</Label> : <><Label color="red">Mounted · unverified</Label>{repo.mount_error && <div className="pf-v5-u-color-danger pf-v5-u-font-size-sm">{repo.mount_error}</div>}</>) : <Label color="grey">Unmounted</Label>}</Td><Td>
                    <Button size="sm" variant="secondary" isDisabled={busy || repo.mounted} onClick={() => editRemoteRepository(repo)}>Edit</Button>{" "}
                    <Button size="sm" variant="secondary" isDisabled={busy} onClick={() => runRemoteRepositoryAction("check_remote_repository", repo.id)}>Check mount identity</Button>{" "}
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
            <Stack hasGutter className="pf-v5-u-pt-lg"><StackItem><Title headingLevel="h2" size="xl">Local operation history</Title><p>Durable local operation definitions and state history, including worker progress and terminal diagnostics. Interrupted writes are never resumed automatically. Cancelled or interrupted restores and clones may have partially modified their destination; inspect the target before reuse. Cancellation is orderly and may take time to stop child processes.</p></StackItem>
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
                    <Td>{progress ? <>{formatBytes(progressDetails.bytes_done || 0)}{progressDetails.bytes_total !== null && progressDetails.bytes_total !== undefined ? " / " + formatBytes(progressDetails.bytes_total) : " processed"}{Number.isFinite(progressDetails.elapsed_seconds) && <div className="pf-v5-u-color-200 pf-v5-u-font-size-sm">{progressDetails.elapsed_seconds.toFixed(1)} s elapsed</div>}{Number.isFinite(progressDetails.bytes_per_second) && <div className="pf-v5-u-color-200 pf-v5-u-font-size-sm">{formatBytes(progressDetails.bytes_per_second)}/s</div>}</> : "—"}</Td>
                    <Td>{item.operation_id}</Td><Td>{details.destination_may_be_partial ? <><strong>Destination may be partially written.</strong> {details.reason || "Inspect it before reuse."}</> : details.error ? <><strong>{details.error_type || "Operation error"}:</strong> {details.error}</> : Array.isArray(details.manifests) ? (details.manifests.length ? "Found: " + details.manifests.join(", ") : "No manifest markers found.") : details.reason || "—"}</Td>
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
                <p>Select an IPv4 address currently assigned to the management interface. Feclora will initialize its managed CA and Server TLS certificate. If age-keygen is installed, it can also provision optional age encryption material.</p>
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
              {status?.server_configured && <StackItem><Alert variant="info" title="Client authentication disabled" isInline>Clients do not have certificates or individual credentials. Deployment jobs select Clients by MAC address; HTTPS/TLS Clients verify the Server certificate.</Alert></StackItem>}
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
                <Alert variant="warning" title="New Server private key; existing CA retained" isInline>This is separate from certificate renewal. All deployment jobs must be stopped. The new key and certificate are validated before installation; configured Clients continue to trust the existing CA and Server identity. This does not rotate the CA.</Alert>
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
              <StackItem>
                <Card><CardBody>
                  <Title headingLevel="h3" size="lg">Publish unattended PXE answer</Title>
                  <p>Upload the prewritten JSON answer. The repository URL is read from its <code>repository_url</code> field. The Server validates the JSON and publishes it through Caddy over HTTP. Credentials must be referenced separately and must not be embedded in the URL.</p>
                  <Alert variant="warning" title="Destructive operation guard" isInline>The PXE Live client trusts the answer delivered by this HTTP server. When a client boots the unattended iPXE entry, a matching whole disk is restored automatically. The first connected repository provider is read-only NFS; images may be unencrypted or age-encrypted with a symmetric passphrase entered locally in Live Cockpit. Other repository schemes fail closed. Test only with disposable target disks.</Alert>
                  <Field label="Prewritten answer file (JSON)">
                    <input className="pf-v5-c-form-control" type="file" accept=".json,application/json" onChange={(event) => { setPxeAnswerFile(event.target.files?.[0] || null); setPxeAnswerPublished(null); }} />
                    {pxeAnswerFile && <div className="pf-v5-u-color-200 pf-v5-u-font-size-sm">{pxeAnswerFile.name} · {pxeAnswerFile.size} bytes</div>}
                  </Field>
                  <Button variant="primary" onClick={publishPXEAnswer} isLoading={busy} isDisabled={busy || !pxeStatus.active || !pxeAnswerFile}>Validate and publish answer</Button>
                  {!pxeStatus.active && <p className="pf-v5-u-color-200 pf-v5-u-font-size-sm">Start PXE services first; publication is available only while the configured Caddy service is active.</p>}
                  {pxeAnswerPublished && <Alert variant="success" title="Answer published" isInline className="pf-v5-u-mt-md">
                    <p>Job: {pxeAnswerPublished.job_id}</p>
                    <p>Answer: <a href={pxeAnswerPublished.answer_url} target="_blank" rel="noreferrer">{pxeAnswerPublished.answer_url}</a></p>
                    <p>iPXE handoff: <a href={pxeAnswerPublished.boot_script_url} target="_blank" rel="noreferrer">{pxeAnswerPublished.boot_script_url}</a></p>
                    <p>{pxeAnswerPublished.message}</p>
                    <Button variant="danger" size="sm" onClick={revokePXEAnswer} isLoading={busy} isDisabled={busy}>Revoke published answer</Button>
                  </Alert>}
                </CardBody></Card>
              </StackItem>
              {pxeAgePassphraseStatus.available && (pxeAgePassphraseStatus.waiting || pxeAgePassphraseStatus.submitted) && <StackItem>
                <Card><CardBody>
                  <Title headingLevel="h3" size="lg">Unlock encrypted PXE restore</Title>
                  {pxeAgePassphraseStatus.waiting
                    ? <>
                        <p>The PXE Live restore worker is waiting for the symmetric age passphrase. Enter it on this Live client. Cockpit submits it once through the local privileged API; it is not added to the answer JSON, URL or kernel command line.</p>
                        <Field label="age symmetric passphrase">
                          <input className="pf-v5-c-form-control" type="password" autoComplete="off" value={pxeAgePassphrase} onChange={(event) => setPxeAgePassphrase(event.target.value)} />
                        </Field>
                        <Button variant="primary" onClick={submitPXEAgePassphrase} isLoading={busy} isDisabled={busy || !pxeAgePassphrase}>Submit passphrase to this Live client</Button>
                      </>
                    : <Alert variant="info" title="Passphrase submitted" isInline>The Live restore worker has received the one-time passphrase and is continuing the authenticated restore preflight.</Alert>}
                </CardBody></Card>
              </StackItem>}
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
          <Tab eventKey="client-jobs" title="Client jobs">
            <Stack hasGutter className="pf-v5-u-pt-lg">
              <StackItem><Title headingLevel="h2" size="xl">Remote job on this Client</Title>
                <p>Inspect the Server job over TLS; the Client does not authenticate itself, choose this machine's local target, type the exact destructive/read confirmation, then connect. The Client reports READY after approval and waits for the Server operator to authorize and start the operation.</p>
              </StackItem>
              {!status?.client_configured && <StackItem><Alert variant="warning" title="Client enrollment required" isInline>Configure Server trust on this Client before inspecting or joining a remote job.</Alert></StackItem>}
              {status?.client_configured && <>
                <StackItem>
                  <Field label="Server host override" help="Leave blank to use the enrolled Server host. The configured Server certificate identity is still verified.">
                    <input className="pf-v5-c-form-control" value={clientRemoteHost} onChange={(event) => setClientRemoteHost(event.target.value)} placeholder="Use enrolled Server host" />
                  </Field>
                  <Field label="Remote job UUID">
                    <input className="pf-v5-c-form-control" value={clientRemoteJobId} onChange={(event) => { setClientRemoteJobId(event.target.value); setClientRemoteInspection(null); setClientRemoteJobStatus(null); }} placeholder="xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx" />
                  </Field>
                  <Field label="Local multicast receive interface (also used for the Server connection)" help="Select the local IPv4 interface/address used for the Server connection and, for multicast jobs, the UDPcast receive interface. The address and interface are revalidated before connection or receive startup.">
                    <select className="pf-v5-c-form-control" value={clientRemoteInterface} onChange={(event) => { setClientRemoteInterface(event.target.value); setClientRemoteInspection(null); setClientRemoteJobStatus(null); setClientRemoteIgmpConfirmed(false); }}>
                      <option value="">Select Client interface/address…</option>
                      {networkInterfaces.map((item) => <option key={item.binding} value={item.binding}>{item.interface} · {item.address}/{item.prefix_length}</option>)}
                    </select>
                  </Field>
                  <p className="pf-v5-u-color-200 pf-v5-u-font-size-sm">Preflight binds the TCP/TLS connection to this Client IPv4 address, verifies the configured Server identity and fetches the job before any local target is approved or storage operation starts.</p>
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
                    {clientRemoteJob.transport === "multicast" && <Alert variant="warning" title="Multicast network requirements" isInline>All selected Clients must be READY before the Server operator authorizes and starts the operation. Confirm UDP multicast reachability, switch IGMP snooping and an active querier on the same VLAN. UDPcast data packets are not encrypted or authenticated; TLS protects only the control channel.</Alert>}
                    {clientRemoteJob.transport === "multicast" && <label><input type="checkbox" checked={clientRemoteIgmpConfirmed} onChange={(event) => setClientRemoteIgmpConfirmed(event.target.checked)} /> I verified IGMP snooping and an active querier on this VLAN, and confirmed all Clients are on the same multicast network.</label>}
                    {(clientRemoteJob.transport === "unicast" || clientRemoteJob.transport === "multicast") && <>

                      <Field label={clientRemoteJob.target_type === "logical_volume" ? "Local destination logical volume" : clientRemoteJob.target_type === "partition" ? "Local destination partition" : "Local destination disk"} help={clientRemoteJob.target_type === "logical_volume" ? "Choose an existing healthy linear or thin LV. It must be active, unmounted and large enough; Feclora will not create or resize LVM metadata. The Client rechecks the LVM topology before READY and immediately before writing." : "The selected block device is rechecked against live inventory immediately before READY. Root, mounted or busy destinations are rejected by the storage engine."}>
                        <select className="pf-v5-c-form-control" value={clientRemoteTarget} onChange={(event) => { setClientRemoteTarget(event.target.value); setClientRemoteConfirmation(""); }}>
                          <option value="">Select local target…</option>
                          {clientRemoteDeviceOptions.map((device) => <option key={device.path} value={device.path}>{device.path} · {device.model || device.name || device.type} · {device.size_bytes || ""}</option>)}
                        </select>
                      </Field>
                      {clientRemoteJob.operation === "save" && <>
                        <Field label="Capture compression">
                          <select className="pf-v5-c-form-control" value={clientRemoteCompression} onChange={(event) => setClientRemoteCompression(event.target.value)}>
                            <option value="none">None</option><option value="gzip">gzip</option><option value="xz">xz</option>
                          </select>
                        </Field>
                        <Field label="Protect this image (optional)">
                          <label><input type="checkbox" checked={clientRemoteEncrypt} disabled={!clientRemoteInspection.image_security?.age_encryption_available} onChange={(event) => setClientRemoteEncrypt(event.target.checked)} /> Encrypt this image with age</label>
                          <br />
                          {(!clientRemoteInspection.image_security?.age_encryption_available ) && <p className="pf-v5-u-color-200 pf-v5-u-font-size-sm">Unavailable options are disabled because this Client has no usable key material or executable. Leaving encryption unchecked creates an unencrypted image with SHA-256 integrity checks.</p>}
                        </Field>
                      </>}
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
                <p>Generate a local Feclora CA and optional age identity. Private keys remain on this machine; captured images can then be encrypted when selected.</p>
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
