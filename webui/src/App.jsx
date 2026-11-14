import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert, Button, Card, CardBody, CardTitle, Flex, FlexItem, Label, Page,
  PageSection, Progress, Spinner, Stack, StackItem, Tab, Tabs, Title, Toolbar,
  ToolbarContent, ToolbarItem
} from "@patternfly/react-core";
import { SyncAltIcon, ServerIcon, DatabaseIcon, ExclamationTriangleIcon } from "@patternfly/react-icons";
import { Table, Thead, Tbody, Tr, Th, Td } from "@patternfly/react-table";
import { callFeclora, waitForLocalOperation } from "./api.js";
import KeyboardPreferences from "./KeyboardPreferences.jsx";
import { LANGUAGES, useLanguagePreference } from "./i18n.js";

const OPERATION_LABELS = {
  capture_disk: "opCaptureDisk",
  capture_p2v: "opCaptureP2v",
  export_p2v_s3: "opExportP2v",
  build_recovery_iso: "opRecoveryIso",
  capture_partition: "opCapturePartition",
  capture_logical_volume: "opCaptureVolume",
  restore_disk: "opRestoreDisk",
  restore_partition: "opRestorePartition",
  restore_logical_volume: "opRestoreVolume",
  clone_disk: "opCloneDisk",
  clone_partition: "opClonePartition"
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

function Field({ label, children, help, t = (value) => value }) {
  return <div className="pf-v5-u-mb-md"><label className="pf-v5-c-form__label pf-v5-u-mb-xs"><span className="pf-v5-c-form__label-text">{t(label)}</span></label>{children}{help && <div className="pf-v5-u-color-200 pf-v5-u-font-size-sm">{t(help)}</div>}</div>;
}

export default function App() {
  const { language, setLanguage, t } = useLanguagePreference();
  const [tab, setTab] = useState("operations");
  const [status, setStatus] = useState(null);
  const [revokeIdentity, setRevokeIdentity] = useState("");
  const [revokeConfirmation, setRevokeConfirmation] = useState("");
  const [ageRecipientExportDirectory, setAgeRecipientExportDirectory] = useState("");
  const [ageRecipientExport, setAgeRecipientExport] = useState(null);
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
  const [remoteStartPolicy, setRemoteStartPolicy] = useState("manual");
  const [remoteExpectedClients, setRemoteExpectedClients] = useState("2");
  const [remoteStartDeadline, setRemoteStartDeadline] = useState("");
  const [remotePostAction, setRemotePostAction] = useState("none");
  const [remoteTransport, setRemoteTransport] = useState("unicast");
  const [remoteMulticastGroup, setRemoteMulticastGroup] = useState("239.10.10.10");
  const [remoteMulticastPort, setRemoteMulticastPort] = useState("9000");
  const [remoteInterface, setRemoteInterface] = useState("");
  const [remoteJobResult, setRemoteJobResult] = useState(null);
  const [operations, setOperations] = useState([]);
  const [cancellingOperationId, setCancellingOperationId] = useState("");
  const [remoteRepositories, setRemoteRepositories] = useState([]);
  const [s3Repositories, setS3Repositories] = useState([]);
  const [s3RepositoryId, setS3RepositoryId] = useState("");
  const [s3Endpoint, setS3Endpoint] = useState("");
  const [s3Region, setS3Region] = useState("us-east-1");
  const [s3Bucket, setS3Bucket] = useState("");
  const [s3Prefix, setS3Prefix] = useState("feclora");
  const [s3CredentialId, setS3CredentialId] = useState("");
  const [s3ReadOnly, setS3ReadOnly] = useState(true);
  const [systemdCredentials, setSystemdCredentials] = useState([]);
  const [credentialId, setCredentialId] = useState("");
  const [credentialKind, setCredentialKind] = useState("ssh-key");
  const [credentialSourceFile, setCredentialSourceFile] = useState("");
  const [credentialReplace, setCredentialReplace] = useState(false);
  const [repositoryId, setRepositoryId] = useState("");
  const [repositoryEditing, setRepositoryEditing] = useState(false);
  const [selectedRepositoryId, setSelectedRepositoryId] = useState("");
  const [exportDestinationRepositoryId, setExportDestinationRepositoryId] = useState("");
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
  const [pxeMaxClients, setPxeMaxClients] = useState("");
  const [pxeMaxDuration, setPxeMaxDuration] = useState("");
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
  const [partitionId, setPartitionId] = useState("");
  const [compression, setCompression] = useState("zstd");
  const [confirmation, setConfirmation] = useState("");
  const [progress, setProgress] = useState(null);
  const [operationResult, setOperationResult] = useState(null);
  const [recoveryBaseISO, setRecoveryBaseISO] = useState("");
  const [recoveryTargetWWN, setRecoveryTargetWWN] = useState("");
  const [recoveryTargetSerial, setRecoveryTargetSerial] = useState("");

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
      const [s, i, j, op, inv, net, profiles, pxe, remote, repositories, credentials, s3repos] = await Promise.all([
        callFeclora("status"), callFeclora("images"), callFeclora("journals"), callFeclora("local_operations"), callFeclora("inventory"), callFeclora("network_interfaces"), callFeclora("network_connection_profiles"), callFeclora("pxe_service_status"), callFeclora("deployment_jobs"), callFeclora("remote_repositories"), callFeclora("systemd_credentials"), callFeclora("s3_repositories")
      ]);
      setStatus(s); setSecurity(s.security || {}); setImages(i.images || []); setJournals(j.journals || []); setOperations(op.operations || []); setInventory(inv); setNetworkInterfaces(net.interfaces || []); setNetworkProfiles(profiles.profiles || []); setPxeStatus(pxe); setDeploymentJobs(remote.jobs || []); setRemoteRepositories(repositories.repositories || []); setSystemdCredentials(credentials.credentials || []); setS3Repositories(s3repos.repositories || []);
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


  const exportLocalOperations = () => {
    const payload = {
      schema_version: 1,
      exported_at: new Date().toISOString(),
      operations,
    };
    const blob = new Blob([JSON.stringify(payload, null, 2) + "\n"], {
      type: "application/json",
    });
    const url = window.URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "feclora-local-operations.json";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => window.URL.revokeObjectURL(url), 1000);
    setNotice("The most recent local operation history was exported as JSON.");
  };

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
  const isExportP2V = operation === "export_p2v_s3";
  const isCapture = operation.startsWith("capture_");
  const isRestore = operation.startsWith("restore_");
  const isDisk = operation.endsWith("_disk") || operation === "capture_p2v";
  const isLogicalVolume = operation === "capture_logical_volume" || operation === "restore_logical_volume";
  const deviceOptions = isDisk ? disks : isLogicalVolume ? logicalVolumes : partitions;
  const selectedRepository = remoteRepositories.find((repo) => repo.id === selectedRepositoryId) || s3Repositories.find((repo) => repo.id === selectedRepositoryId);
  const remoteSelectedRepository = remoteOperation === "save"
    ? s3Repositories.find((repo) => repo.id === selectedRepositoryId && !repo.read_only)
    : remoteRepositories.find((repo) => repo.id === selectedRepositoryId && repo.mounted && repo.verified) || s3Repositories.find((repo) => repo.id === selectedRepositoryId);
  const availableImages = selectedRepositoryId ? repositoryImages : images;
  const remoteAvailableImages = remoteSelectedRepository ? repositoryImages : images;
  const matchingImages = availableImages.filter((item) => item.image_type === (isExportP2V ? "virtual_disk" : isDisk ? "disk" : isLogicalVolume ? "logical_volume" : "partition"));
  const expectedConfirmation = operation === "clone_partition"
    ? (source && target ? `ERASE ${target} FROM ${source}` : "")
    : (isRestore || operation.startsWith("clone_")) && target ? `ERASE ${target}` : "";

  useEffect(() => { setConfirmation(""); setProgress(null); setOperationResult(null); if (operation !== "capture_disk") { setEncryptPassphraseMode(false); setCapturePassphrase(""); } }, [operation, source, target, imageId]);

  const runOperation = async (event) => {
    event.preventDefault(); setBusy(true); setError(""); setNotice(""); setProgress(null); setOperationResult(null);
    try {
      let params;
      if (operation === "export_p2v_s3") params = {
        image_id: imageId, source_repository_id: selectedRepositoryId,
        ...(exportDestinationRepositoryId ? { destination_repository_id: exportDestinationRepositoryId } : {})
      };
      else if (operation === "build_recovery_iso") params = {
        base_iso_path: recoveryBaseISO, image_id: imageId,
        target_wwn: recoveryTargetWWN.trim() || null,
        target_serial: recoveryTargetSerial.trim() || null,
        confirm_build: confirmation,
        ...(selectedRepositoryId ? { repository_id: selectedRepositoryId } : {})
      };
      else if (operation === "capture_disk") params = { source, image_id: imageId, compression, encrypt: encrypt || encryptPassphraseMode, ...(encryptPassphraseMode ? { encrypt_passphrase: true } : {}), ...(selectedRepositoryId ? { repository_id: selectedRepositoryId } : {}) };
      else if (operation === "capture_partition") params = { source, image_id: imageId, partition_id: partitionId || imageId, compression, encrypt, ...(selectedRepositoryId ? { repository_id: selectedRepositoryId } : {}) };
      else if (operation === "capture_logical_volume") params = { source, image_id: imageId, compression, encrypt, ...(selectedRepositoryId ? { repository_id: selectedRepositoryId } : {}) };
      else if (operation === "capture_p2v") params = { source, image_id: imageId, ...(selectedRepositoryId ? { repository_id: selectedRepositoryId } : {}) };
      else if (isRestore) {
        params = {
          image_id: imageId, target, confirmation,
          ...(selectedRepositoryId ? { repository_id: selectedRepositoryId } : {})
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
    setRepositoryPort("22"); setRepositoryReadOnly(true);
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

  const saveS3Repository = async (event) => {
    event.preventDefault(); setBusy(true); setError(""); setNotice("");
    try {
      await callFeclora("add_s3_repository", {
        id: s3RepositoryId, endpoint_url: s3Endpoint.trim() || null,
        region: s3Region, bucket: s3Bucket, prefix: s3Prefix,
        credential_id: s3CredentialId, read_only: s3ReadOnly
      });
      setNotice("S3 object repository definition saved. No filesystem mount was created.");
      setS3RepositoryId(""); await refresh();
    } catch (err) { setError(err?.message || String(err)); }
    finally { setBusy(false); }
  };

  const runS3RepositoryAction = async (action, id) => {
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await callFeclora(action, { id });
      setNotice(action === "check_s3_repository"
        ? (result.bucket_accessible ? "S3 bucket connection verified." : "S3 bucket is not accessible.")
        : "S3 repository removed.");
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
        authoritative_confirmed: pxeMode === "isolated" && pxeAuthoritative,
        max_clients: pxeMaxClients.trim() ? Number(pxeMaxClients) : null,
        max_duration_seconds: pxeMaxDuration.trim() ? Number(pxeMaxDuration) : null
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
    if (job.operation === "clone" && job.transport === "multicast") {
      return "ARM PHYSICAL MULTICAST " + job.job_id + " FROM " + job.source_device + " IGMP-VERIFIED";
    }
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
        ...((remoteOperation === "restore" || remoteOperation === "save") && remoteSelectedRepository ? { repository_id: remoteSelectedRepository.id } : {}),
        multicast_group: remoteTransport === "multicast" ? remoteMulticastGroup : null,
        multicast_port: remoteTransport === "multicast" ? Number(remoteMulticastPort) : null,
        start_policy: remoteOperation === "clone" ? "manual" : remoteStartPolicy,
        expected_clients: remoteOperation !== "clone" && remoteStartPolicy === "expected_clients" ? Number(remoteExpectedClients) : null,
        start_deadline: remoteOperation !== "clone" && remoteStartPolicy === "deadline" ? new Date(remoteStartDeadline).toISOString() : null,
        post_action: remoteOperation === "save" ? "none" : remotePostAction
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

  const recoveryRepositoryIsS3 = s3Repositories.some((repo) => repo.id === selectedRepositoryId);
  const recoveryExpectedConfirmation = imageId ? `BUILD ${imageId}` : "";
  const operationReady = operation === "export_p2v_s3"
    ? Boolean(imageId && repositoryImages.some((item) => item.image_id === imageId && item.image_type === "virtual_disk")
      && s3Repositories.some((repo) => repo.id === selectedRepositoryId)
      && (!exportDestinationRepositoryId || remoteRepositories.some((repo) => repo.id === exportDestinationRepositoryId && repo.mounted && repo.verified && !repo.read_only)))
    : operation === "build_recovery_iso"
    ? Boolean(recoveryBaseISO.trim() && imageId && (recoveryTargetWWN.trim() || recoveryTargetSerial.trim())
      && confirmation === recoveryExpectedConfirmation && !recoveryRepositoryIsS3 && !selectedRepository?.read_only)
    : isCapture
    ? Boolean(source && imageId && (!selectedRepository?.read_only) && (operation !== "capture_partition" || partitionId || imageId))
    : isRestore ? Boolean(imageId && target && confirmation === expectedConfirmation && (!isDisk || !restoreLayoutPreview || !restoreTargetDevice || restoreTargetDevice.size_bytes >= restoreLayoutPreview.source_size_bytes))
      : Boolean(source && target && source !== target && confirmation === expectedConfirmation);

  return (
    <Page>
      <PageSection variant="default">
        <Toolbar><ToolbarContent>
          <ToolbarItem><Title headingLevel="h1">Feclora</Title></ToolbarItem>
          <ToolbarItem><label htmlFor="feclora-ui-language" className="pf-v5-u-mr-sm">{t("language")}</label><select id="feclora-ui-language" className="pf-v5-c-form-control" value={language} onChange={(event) => setLanguage(event.target.value)} aria-label={t("language")}>{LANGUAGES.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></ToolbarItem>
          <ToolbarItem align={{ default: "alignEnd" }}><Button variant="secondary" icon={<SyncAltIcon />} onClick={refresh} isLoading={busy}>{t("refresh")}</Button></ToolbarItem>
        </ToolbarContent></Toolbar>
        <p className="pf-v5-u-mt-sm">{t("tagline")}</p>
      </PageSection>
      {(error || notice) && <PageSection>{error && <Alert variant="danger" title={t("failed")} isInline>{error}</Alert>}{notice && <Alert variant="success" title={t("Feclora")} isInline>{notice}</Alert>}</PageSection>}
      <PageSection>
        {status ? <Flex flexWrap={{ default: "wrap" }} gap={{ default: "gapMd" }}>
          <FlexItem flex={{ default: "1" }}><StatusCard title={t("host")} value={status.hostname} icon={<ServerIcon />} description={status.platform} /></FlexItem>
          <FlexItem flex={{ default: "1" }}><StatusCard title={t("images")} value={String(images.length)} icon={<DatabaseIcon />} description={t("manifests")} /></FlexItem>
          <FlexItem flex={{ default: "1" }}><StatusCard title={t("jobs")} value={String(journals.length)} icon={<ExclamationTriangleIcon />} description={t("recordedJobs")} /></FlexItem>
        </Flex> : <Spinner aria-label={t("loading")} />}
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
          <Tab eventKey="operations" title={t("imaging")}>
            <Stack hasGutter className="pf-v5-u-pt-lg">
              <StackItem><Title headingLevel="h2" size="xl">{t("wizard")}</Title><p>{t("chooseOperation")}</p></StackItem>
              <StackItem>
                <Card><CardBody>
                  <form onSubmit={runOperation}>
                    <Field t={t} label={t("operation")}>
                      <select className="pf-v5-c-form-control" value={operation} onChange={(e) => { setOperation(e.target.value); setSource(""); setTarget(""); setImageId(""); setPartitionId(""); setRestoreLayoutPreview(null); setConfirmation(""); setOperationResult(null); }}>
                        {Object.entries(OPERATION_LABELS).map(([value, label]) => <option key={value} value={value}>{t(label)}</option>)}
                      </select>
                    </Field>
                    {isExportP2V && <>
                      <Alert variant="info" title={t("Verified S3 P2V export")} isInline>
                        Select an S3 source repository and a committed QCOW2. Feclora downloads the object to private staging, verifies its size and SHA-256 against the committed metadata, then publishes the QCOW2 and metadata sidecar to a filesystem repository. The sidecar is linked last; existing files are never overwritten.
                      </Alert>
                      <Field t={t} label={t("S3 source repository")}>
                        <select className="pf-v5-c-form-control" value={selectedRepositoryId} disabled={busy} onChange={(e) => { setImageId(""); selectImageRepository(e.target.value); }} required>
                          <option value="">Select an S3 repository…</option>
                          {s3Repositories.map((repo) => <option key={repo.id} value={repo.id}>{repo.id} · S3{repo.read_only ? " · read-only" : ""}</option>)}
                        </select>
                      </Field>
                      <Field t={t} label={t("Committed P2V image")}>
                        <select className="pf-v5-c-form-control" value={imageId} disabled={busy || !selectedRepositoryId} onChange={(e) => setImageId(e.target.value)} required>
                          <option value="">Select a QCOW2 image…</option>
                          {matchingImages.map((item) => <option key={item.image_id} value={item.image_id}>{item.image_id} · {formatBytes(item.source_size_bytes)}</option>)}
                        </select>
                      </Field>
                      <Field t={t} label={t("Filesystem destination repository")} help="Local is the default. Remote destinations must already be mounted, verified and writable. S3 cannot be selected as the destination for this export operation.">
                        <select className="pf-v5-c-form-control" value={exportDestinationRepositoryId} disabled={busy} onChange={(e) => setExportDestinationRepositoryId(e.target.value)}>
                          <option value="">Local repository</option>
                          {remoteRepositories.filter((repo) => repo.mounted && repo.verified && !repo.read_only).map((repo) => <option key={repo.id} value={repo.id}>{repo.id} · {repo.provider}</option>)}
                        </select>
                      </Field>
                    </>}
                    {operation === "build_recovery_iso" && <>
                      <Alert variant="info" title={t("Self-contained recovery media")} isInline>
                        Select the Feclora Live base ISO and an existing disk image. Feclora creates a separate bootable ISO containing the verified image, its manifest and a narrowly scoped unattended restore answer. The base ISO and source image remain unchanged. Output is written to the selected filesystem repository; S3 is not supported for ISO output. If the image is age-encrypted, the matching decryption identity must be provisioned separately on the recovery Live system; no keys or passphrases are embedded.
                      </Alert>
                      <Field t={t} label={t("Base Feclora Live ISO path")} help="Absolute path to a local .iso file accessible to the Feclora service, for example /home/feclora/Downloads/feclora-live.iso.">
                        <input className="pf-v5-c-form-control" value={recoveryBaseISO} onChange={(e) => setRecoveryBaseISO(e.target.value)} placeholder={t("/path/to/feclora-live.iso")} required />
                      </Field>
                      <Field t={t} label={t("imageRepository")}>
                        <select className="pf-v5-c-form-control" value={selectedRepositoryId} disabled={busy} onChange={(e) => selectImageRepository(e.target.value)}>
                          <option value="">Local repository</option>
                          {remoteRepositories.filter((repo) => repo.mounted && repo.verified).map((repo) => <option key={repo.id} value={repo.id}>{repo.id} · {repo.provider} · {repo.read_only ? "read-only" : "read/write"}</option>)}
                          {s3Repositories.map((repo) => <option key={repo.id} value={repo.id} disabled>{repo.id} · S3 (unsupported output)</option>)}
                        </select>
                      </Field>
                      <Field t={t} label={t("Whole-disk image to embed")}>
                        <select className="pf-v5-c-form-control" value={imageId} onChange={(e) => setImageId(e.target.value)} required>
                          <option value="">Select a disk image…</option>
                          {availableImages.filter((item) => item.image_type === "disk").map((item) => <option key={item.image_id} value={item.image_id}>{item.image_id} · {formatBytes(item.source_size_bytes)}</option>)}
                        </select>
                      </Field>
                      <Field t={t} label={t("Target disk WWN (recommended)")} help="The recovery answer will only authorize a disk whose identity matches this WWN and/or serial. Use at least one selector.">
                        <input className="pf-v5-c-form-control" value={recoveryTargetWWN} onChange={(e) => setRecoveryTargetWWN(e.target.value)} maxLength={128} />
                      </Field>
                      <Field t={t} label={t("Target disk serial (alternative or additional selector)")}>
                        <input className="pf-v5-c-form-control" value={recoveryTargetSerial} onChange={(e) => setRecoveryTargetSerial(e.target.value)} maxLength={128} />
                      </Field>
                      {recoveryExpectedConfirmation && <Alert variant="warning" title={t("Confirm ISO creation")} isInline>
                        Type exactly <strong>{recoveryExpectedConfirmation}</strong>. This creates a separate ISO file; it does not restore or write to any disk now. The embedded answer will request a destructive restore only when booted and its target identity matches.
                      </Alert>}
                      {recoveryExpectedConfirmation && <Field t={t} label={t("Typed build confirmation")}>
                        <input className="pf-v5-c-form-control" value={confirmation} onChange={(e) => setConfirmation(e.target.value)} autoComplete="off" />
                      </Field>}
                    </>}
                    {isCapture && <>
                      <Field t={t} label={isDisk ? "Source disk" : isLogicalVolume ? "Source logical volume" : "Source partition"}>
                        <select className="pf-v5-c-form-control" value={source} onChange={(e) => setSource(e.target.value)}>
                          <option value="">{t("Select a source device…")}</option>
                          {deviceOptions.map((d) => <option key={d.path} value={d.path}>{d.path}{d.lvm_name ? ` · ${d.lvm_name} (${d.lvm_path})` : ""} · {formatBytes(d.size_bytes)} · {d.model || d.filesystem || d.type}</option>)}
                        </select>
                      </Field>
                      <Field t={t} label={t("Image identifier")} help="Use letters, numbers, dots, underscores or hyphens.">
                        <input className="pf-v5-c-form-control" value={imageId} onChange={(e) => setImageId(e.target.value)} maxLength={128} required />
                      </Field>
                      {operation === "capture_partition" && <Field t={t} label={t("Partition identifier")}><input className="pf-v5-c-form-control" value={partitionId} onChange={(e) => setPartitionId(e.target.value)} maxLength={128} placeholder={imageId || "e.g. rootfs"} /></Field>}
                      {operation !== "capture_p2v" && <Field t={t} label={t("Compression")}>
                        <select className="pf-v5-c-form-control" value={compression} onChange={(e) => setCompression(e.target.value)}>
                          <option value="zstd">Zstandard (recommended)</option><option value="lz4">LZ4 (fast)</option><option value="gzip">Gzip</option><option value="xz">XZ</option><option value="none">None</option>
                        </select>
                      </Field>}
                      {operation !== "capture_p2v" && <Field t={t} label={t("Image security")}>
                        <label><input type="checkbox" checked={encrypt} disabled={!security.age_encryption_available && !security.age_executable_available} onChange={(e) => { setEncrypt(e.target.checked); if (!e.target.checked) { setEncryptPassphraseMode(false); setCapturePassphrase(""); } }} /> {t("Encrypt artifacts with age")}</label>
                        {operation === "capture_disk" && encrypt && security.age_executable_available && <>
                          <br />
                          <label><input type="checkbox" checked={encryptPassphraseMode} onChange={(e) => { setEncryptPassphraseMode(e.target.checked); setCapturePassphrase(""); }} /> {t("Use a symmetric passphrase instead of recipient keys")}</label>
                          {encryptPassphraseMode && <Field t={t} label={t("Image encryption passphrase")} help="Sent once to the worker through /run and consumed immediately. It is not saved in the operation journal or image manifest.">
                            <input className="pf-v5-c-form-control" type="password" autoComplete="new-password" value={capturePassphrase} onChange={(e) => setCapturePassphrase(e.target.value)} maxLength={1024} />
                          </Field>}
                        </>}
                        <br />
                        {!security.age_encryption_available && !security.age_executable_available ? <p className="pf-v5-u-color-200">Optional image protection is provisioned during Server setup when the relevant tools are installed. Without them, ordinary capture and restore remain available.</p> : null}
                      </Field>}
                      {operation === "capture_p2v" && <Alert variant="info" title={t("P2V output")} isInline>Creates a verified QCOW2 disk file and a .p2v.json metadata sidecar in the selected filesystem repository, or publishes both to S3 with the metadata sidecar as the commit marker. Direct VM boot remediation is not included. The source disk is read-only; the guest may still need drivers or initramfs changes to boot.</Alert>}
                    </>}
                    {isRestore && <>
                      <Field t={t} label={isDisk ? "Disk image" : isLogicalVolume ? "Logical-volume image" : "Partition image"}>
                        <select className="pf-v5-c-form-control" value={imageId} disabled={busy} onChange={(e) => {
                          const value = e.target.value;
                          setImageId(value);
                          if (isDisk) inspectRestoreLayout(value); else setRestoreLayoutPreview(null);
                        }}>
                          <option value="">{t("Select an image…")}</option>
                          {matchingImages.map((item) => <option key={item.image_id} value={item.image_id}>{item.image_id} · {formatBytes(item.source_size_bytes)}</option>)}
                        </select>
                      </Field>
                      <Field t={t} label={isDisk ? "Destination disk" : isLogicalVolume ? "Destination logical volume" : "Destination partition"} help={isLogicalVolume ? "Must be an existing active, unmounted linear or thin LV in a healthy VG. Thin-pool free space is estimated, not reserved. Feclora overwrites LV data but does not create or resize LVM metadata." : undefined}>
                        <select className="pf-v5-c-form-control" value={target} onChange={(e) => setTarget(e.target.value)}>
                          <option value="">{t("Select a destination…")}</option>
                          {deviceOptions.map((d) => <option key={d.path} value={d.path}>{d.path} · {formatBytes(d.size_bytes)} · {d.model || d.filesystem || d.type}</option>)}
                        </select>
                      </Field>
                      {isDisk && restoreLayoutPreview && restoreTargetDevice && <>
                        {restoreTargetDevice.size_bytes < restoreLayoutPreview.source_size_bytes
                          ? <Alert variant="danger" title={t("Destination disk is too small")} isInline>Source layout requires {formatBytes(restoreLayoutPreview.source_size_bytes)}; selected disk has {formatBytes(restoreTargetDevice.size_bytes)}. The restore engine will reject this target.</Alert>
                          : <Alert variant="info" title={t("Read-only restore layout preview")} isInline>
                              Source image: {formatBytes(restoreLayoutPreview.source_size_bytes)} · Destination: {formatBytes(restoreTargetDevice.size_bytes)} · {restoreLayoutPreview.partitions.length} partitions. The source partition layout is written as captured; extra destination capacity is left unused. No automatic partition/filesystem growth is performed.
                            </Alert>}
                        <Table aria-label={t("Restore source partition layout preview")} variant="compact">
                          <Thead><Tr><Th>{t("Partition")}</Th><Th>UUID / label</Th><Th>Start sector</Th><Th>{t("size")}</Th></Tr></Thead>
                          <Tbody>{restoreLayoutPreview.partitions.map((part) => <Tr key={part.node}>
                            <Td>{part.node}</Td><Td>{part.uuid || part.name || "—"}</Td><Td>{part.start_sector}</Td><Td>{formatBytes(part.size_bytes)}</Td>
                          </Tr>)}</Tbody>
                        </Table>
                      </>}
                    </>}
                    {operation.startsWith("clone_") && <>
                      <Field t={t} label={isDisk ? "Source disk" : "Source partition"}>
                        <select className="pf-v5-c-form-control" value={source} onChange={(e) => setSource(e.target.value)}>
                          <option value="">{t("Select source…")}</option>
                          {deviceOptions.map((d) => <option key={d.path} value={d.path}>{d.path} · {formatBytes(d.size_bytes)} · {d.model || d.filesystem || d.type}</option>)}
                        </select>
                      </Field>
                      <Field t={t} label={isDisk ? "Destination disk" : "Destination partition"}>
                        <select className="pf-v5-c-form-control" value={target} onChange={(e) => setTarget(e.target.value)}>
                          <option value="">{t("Select destination…")}</option>
                          {deviceOptions.filter((d) => d.path !== source).map((d) => <option key={d.path} value={d.path}>{d.path} · {formatBytes(d.size_bytes)} · {d.model || d.filesystem || d.type}</option>)}
                        </select>
                      </Field>
                    </>}
                    {expectedConfirmation && <Alert variant="warning" title={t("Destructive operation")} isInline className="pf-v5-u-mb-md">
                      The destination will be overwritten. Type exactly <strong>{expectedConfirmation}</strong> to authorize this operation.
                    </Alert>}
                    {expectedConfirmation && <Field t={t} label={t("Typed confirmation")}>
                      <input className="pf-v5-c-form-control" value={confirmation} onChange={(e) => setConfirmation(e.target.value)} autoComplete="off" />
                    </Field>}
                    {busy && progress && <div className="pf-v5-u-mb-md">
                      {progress.bytes_total
                        ? <Progress value={Math.min(100, progress.bytes_done / progress.bytes_total * 100)} title={t("Operation progress")} measureLocation="outside" label={formatBytes(progress.bytes_done) + " / " + formatBytes(progress.bytes_total)} />
                        : <Alert variant="info" isInline title={t("Operation in progress")}>{formatBytes(progress.bytes_done)} processed</Alert>}
                    </div>}
                    <Button type="submit" variant="primary" isDisabled={!operationReady || busy}>{busy ? <><Spinner size="sm" /> {t("working")}</> : t("start")}</Button>
                  </form>
                  {operationResult && <Alert variant="success" title={t("completed")} isInline className="pf-v5-u-mt-md"><pre>{JSON.stringify(operationResult, null, 2)}</pre></Alert>}
                </CardBody></Card>
              </StackItem>
              <StackItem><Alert variant="info" title={t("safety")} isInline>{t("storageSafety")}</Alert></StackItem>
            </Stack>
          </Tab>
          <Tab eventKey="inventory" title={t("inventory")}>
            <Stack hasGutter className="pf-v5-u-pt-lg"><StackItem><Title headingLevel="h2" size="xl">{t("storageDevices")}</Title></StackItem>
              <StackItem><Table aria-label={t("storageDevices")} variant="compact"><Thead><Tr><Th>{t("device")}</Th><Th>{t("type")}</Th><Th>{t("size")}</Th><Th>{t("model")}</Th><Th>{t("filesystem")}</Th><Th>{t("mounts")}</Th></Tr></Thead><Tbody>
                {devices.map((d) => <Tr key={d.path}><Td>{d.path}</Td><Td>{d.type}</Td><Td>{formatBytes(d.size_bytes)}</Td><Td>{d.model || "—"}</Td><Td>{d.filesystem || "—"}</Td><Td>{(d.mountpoints || []).join(", ") || "—"}</Td></Tr>)}
                {!devices.length && <Tr><Td colSpan={6}>{inventory ? "No devices found." : "Loading inventory…"}</Td></Tr>}
              </Tbody></Table></StackItem>
            </Stack>
          </Tab>
          <Tab eventKey="images" title={t("tabImages")}>
            <Stack hasGutter className="pf-v5-u-pt-lg"><StackItem><Title headingLevel="h2" size="xl">{t("availableImages")}</Title><Field t={t} label={t("Image repository")} help="Local is the default; filesystem shares must be mounted and verified. S3 repositories use object transfers."><select className="pf-v5-c-form-control" value={selectedRepositoryId} disabled={busy} onChange={(event) => selectImageRepository(event.target.value)}><option value="">Local repository</option>{remoteRepositories.filter((repo) => repo.mounted && repo.verified).map((repo) => <option key={repo.id} value={repo.id}>{repo.id} · {repo.provider} · {repo.read_only ? "read-only" : "read/write"}</option>)}
                    {s3Repositories.filter((repo) => !remoteRepositories.some((remoteRepo) => remoteRepo.id === repo.id)).map((repo) => <option key={repo.id} value={repo.id}>{repo.id} · S3 object storage · {repo.read_only ? "read-only" : "read/write"}</option>)}</select></Field></StackItem>
              <StackItem>
                <Card><CardBody>
                  <Title headingLevel="h3" size="lg">{t("extractPartition")}</Title>
                  <p>Select a verified whole-disk image and identify one partition by PARTUUID, PARTLABEL or partition node recorded in its partition table. Feclora verifies the source image and publishes a separate partition image; age-encrypted sources are re-encrypted to the current recipient inventory. The source image is not modified.</p>
                  <Field t={t} label={t("Whole-disk source image")}>
                    <select className="pf-v5-c-form-control" value={extractImageId} disabled={busy} onChange={(event) => { setExtractImageId(event.target.value); inspectImageLayout(event.target.value); }}>
                      <option value="">Select whole-disk image…</option>
                      {availableImages.filter((item) => item.image_type === "disk").map((item) => <option key={item.image_id} value={item.image_id}>{item.image_id}{""}</option>)}
                    </select>
                  </Field>
                  {extractLayout && <>
                    <Alert variant="info" title={t("Verified partition-table preview")} isInline>{extractLayout.message} Source size: {formatBytes(extractLayout.source_size_bytes)} · Logical sector: {extractLayout.logical_sector_size} bytes · {extractLayout.partitions.length} partitions.</Alert>
                    <Table aria-label={t("Source image partition layout")} variant="compact">
                      <Thead><Tr><Th>{t("Partition")}</Th><Th>UUID / label</Th><Th>Start sector</Th><Th>{t("size")}</Th></Tr></Thead>
                      <Tbody>{extractLayout.partitions.map((part) => <Tr key={part.node}>
                        <Td>{part.node}</Td><Td>{part.uuid || part.name || "—"}</Td><Td>{part.start_sector}</Td><Td>{formatBytes(part.size_bytes)}</Td>
                      </Tr>)}</Tbody>
                    </Table>
                  </>}
                  <Field t={t} label={t("Partition to extract")} help="Choose a partition from the verified table preview. The selector is cleared whenever the source image changes.">
                    <select className="pf-v5-c-form-control" value={extractPartitionSelector} onChange={(event) => { setExtractPartitionSelector(event.target.value); setExtractPartitionResult(null); }} disabled={!extractLayout || !extractLayout.partitions.length}>
                      <option value="">Select partition…</option>
                      {(extractLayout?.partitions || []).map((part) => <option key={part.node} value={part.selector}>{part.node} · {part.uuid || part.name || part.selector} · {formatBytes(part.size_bytes)}</option>)}
                    </select>
                  </Field>
                  <Button variant="primary" onClick={extractPartitionFromImage} isLoading={busy} isDisabled={busy || selectedRepository?.read_only || !extractImageId || !extractLayout || !extractPartitionSelector}>Extract partition image</Button>
                  {busy && progress && <Progress value={progress.bytes_total ? Math.min(100, progress.bytes_done / progress.bytes_total * 100) : 0} title={t("Partition extraction progress")} measureLocation="outside" label={formatBytes(progress.bytes_done) + " / " + formatBytes(progress.bytes_total)} />}
                  {extractPartitionResult && <Alert variant="success" title={t("Partition image published")} isInline>
                    Source: {extractPartitionResult.source_image_id} · New image: {extractPartitionResult.image_id} · {extractPartitionResult.encrypted ? "age-encrypted" : "unencrypted"}
                  </Alert>}
                </CardBody></Card>
              </StackItem>
              <StackItem><Table aria-label={t("imageRepository")} variant="compact"><Thead><Tr><Th>{t("Image")}</Th><Th>{t("type")}</Th><Th>{t("Source size")}</Th><Th>{t("Encryption")}</Th><Th>{t("Artifacts")}</Th><Th>{t("Verification")}</Th></Tr></Thead><Tbody>
                {images.map((item) => {
                  const verification = imageVerification[item.image_id];
                  return <Tr key={item.image_id}><Td>{item.image_id}</Td><Td>{item.image_type}</Td><Td>{formatBytes(item.source_size_bytes)}</Td><Td><Label color={item.encrypted ? "green" : "orange"}>{item.encrypted ? "age" : "Plain"}</Label></Td><Td>{item.artifact_count}</Td><Td>
                    <Button size="sm" variant="secondary" isDisabled={busy || verification?.loading} isLoading={verification?.loading} onClick={() => verifyImage(item.image_id)}>{t("Verify")}</Button>
                    {verification?.report && <div className="pf-v5-u-mt-sm">
                      <Label color="green">{t("Verified")}</Label> Manifest: {verification.report.manifest} · {verification.report.artifact_count} artifacts · {formatBytes(verification.report.total_decoded_bytes)}
                      {verification.report.artifacts.map((artifact) => <p key={artifact.filename}>{artifact.filename}: stored SHA-256 {artifact.stored_digest}; age {artifact.age_authentication}; compression {artifact.decompression}; decoded {formatBytes(artifact.decoded_bytes)}</p>)}
                    </div>}
                    {verification?.error && <Alert variant="danger" title={t("Verification failed")} isInline>{verification.error}</Alert>}
                  </Td></Tr>;
                })}
                {!availableImages.length && <Tr><Td colSpan={6}>No manifest-backed images found in this repository.</Td></Tr>}
              </Tbody></Table></StackItem>
            </Stack>
          </Tab>
          <Tab eventKey="remote-jobs" title={t("tabRemoteJobs")}>
            <Stack hasGutter className="pf-v5-u-pt-lg">
              <StackItem><Title headingLevel="h2" size="xl">{t("createRemoteJob")}</Title>
                <Alert variant="warning" title={t("Definition only — service not started; no Client contact or disk I/O")} isInline>
                  This step validates and journals a job definition. Start its persistent service separately; Clients then connect over Server-authenticated TLS and approve their own local target through the Client-local runtime. Each Client selects and approves its own local destination in the Client jobs tab. No storage operation starts until you explicitly authorize and start it here after all selected Clients report READY.
                </Alert>
              </StackItem>
              <StackItem>
                <Card><CardBody><form onSubmit={createRemoteJob}>
                  <Field t={t} label={t("Operation")}>
                    <select className="pf-v5-c-form-control" value={remoteOperation} onChange={(e) => { setRemoteOperation(e.target.value); setRemoteImageId(""); setRemoteSourceDevice(""); if (e.target.value === "save" || e.target.value === "clone") { setRemoteTransport("unicast"); setRemoteTargetType("disk"); } }}>
                      <option value="restore">Restore a Server image to Clients</option>
                      <option value="save">{t("Capture whole disks from Clients to Server")}</option>
                      <option value="clone">Clone a Server disk or partition directly to multiple Clients</option>
                    </select>
                  </Field>
                  {(remoteOperation === "restore" || remoteOperation === "save") && <Field t={t} label={t("Image repository")} help={remoteOperation === "save" ? "Client captures are staged on the Server and published to S3 only after a successful TLS transfer." : "The Server fetches and verifies the image from this repository before transmitting it to Clients over authenticated TLS."}>
                    <select className="pf-v5-c-form-control" value={remoteSelectedRepository?.id || ""} disabled={busy} onChange={(e) => { selectImageRepository(e.target.value); setRemoteImageId(""); }}>
                      <option value="">Local Server repository</option>
                      {remoteRepositories.filter((repo) => remoteOperation === "restore" && repo.mounted && repo.verified).map((repo) => <option key={repo.id} value={repo.id}>{repo.id} · {repo.provider}</option>)}
                      {s3Repositories.filter((repo) => remoteOperation === "restore" || !repo.read_only).map((repo) => <option key={repo.id} value={repo.id}>{repo.id} · S3 object storage</option>)}
                    </select>
                  </Field>}
                  {remoteOperation === "clone" ? <Field t={t} label={remoteTargetType === "disk" ? "Server source disk" : "Server source partition"} help="Select a source already marked read-only. Feclora independently validates its type, geometry and in-use state before streaming.">
                    <select className="pf-v5-c-form-control" value={remoteSourceDevice} onChange={(e) => setRemoteSourceDevice(e.target.value)} required>
                      <option value="">Select read-only source…</option>
                      {inventoryDevices.filter((item) => item.type === (remoteTargetType === "disk" ? "disk" : "part") && item.read_only === true).map((item) => <option key={item.path} value={item.path}>{item.path} · {item.model || (remoteTargetType === "disk" ? "Disk" : "Partition")} · {formatBytes(item.size_bytes)}</option>)}
                    </select>
                  </Field> : <Field t={t} label={t("Image identifier")} help={remoteOperation === "restore" ? "Choose an existing disk, partition or logical-volume image matching the selected target type. Images are validated against their manifests and SHA-256 digests." : "New identifier for the image captured from Clients."}>
                    {remoteOperation === "restore" ? <select className="pf-v5-c-form-control" value={remoteImageId} onChange={(e) => setRemoteImageId(e.target.value)}>
                      <option value="">Select image…</option>
                      {remoteAvailableImages.filter((item) => item.image_type === remoteTargetType).map((item) => <option key={item.image_id} value={item.image_id}>{item.image_id}</option>)}
                    </select> : <input className="pf-v5-c-form-control" value={remoteImageId} onChange={(e) => setRemoteImageId(e.target.value)} maxLength={128} required />}
                  </Field>}
                  {(remoteOperation === "save" || remoteOperation === "restore" || remoteOperation === "clone") && <Field t={t} label={remoteOperation === "clone" ? "Clone device type" : remoteOperation === "save" ? "Capture source type" : "Restore target type"}>
                    <select className="pf-v5-c-form-control" value={remoteTargetType} onChange={(e) => { setRemoteTargetType(e.target.value); setRemoteImageId(""); setRemoteSourceDevice(""); }}>
                      <option value="disk">{t("Whole disk")}</option>
                      {remoteOperation !== "clone" && <option value="logical_volume">{t("Logical volume")}</option>}
                      {remoteOperation !== "save" && <option value="partition">{t("Partition")}</option>}
                    </select>
                  </Field>}
                  <Field t={t} label={t("Selected Client MAC addresses")} help={remoteOperation === "clone" ? "Enter one or more selected Client MAC addresses. Each Client independently selects and confirms its own destination of the selected device type. Transfers are serialized from the Server source; each Client verifies its own write." : "Enter one or more MAC addresses for unicast clone, exactly one for unicast save/restore, or at least two for multicast restore. Server checks that each MAC is selected for this job; MAC is not authentication."}>
                    <textarea className="pf-v5-c-form-control" rows={3} value={remoteClients} onChange={(e) => setRemoteClients(e.target.value)} required placeholder={t("52:54:00:12:34:56")} />
                  </Field>
                  <Field t={t} label={t("Server network interface")}>
                    <select className="pf-v5-c-form-control" value={remoteInterface} onChange={(e) => setRemoteInterface(e.target.value)} required>
                      <option value="">Select active Server interface/address…</option>
                      {networkInterfaces.map((item) => <option key={item.binding} value={item.binding}>{item.interface} · {item.address}/{item.prefix_length}</option>)}
                    </select>
                    <div className="pf-v5-u-color-200 pf-v5-u-font-size-sm">The job binds to the selected Server interface. Configure the Client independently from its local Cockpit Network tab; this does not test end-to-end reachability to an offline Client.</div>
                  </Field>
                  <Field t={t} label={t("Transport")}>
                    <select className="pf-v5-c-form-control" value={remoteTransport} onChange={(e) => setRemoteTransport(e.target.value)}>
                      <option value="unicast">{t("Authenticated unicast")}</option>
                      <option value="multicast" disabled={remoteOperation === "save"}>{remoteOperation === "clone" ? "UDPcast physical disk multicast clone" : "UDPcast multicast image restore"}</option>
                    </select>
                  </Field>
                  {remoteTransport === "multicast" && <>
                    <Field t={t} label={t("Administratively scoped multicast group")}><input className="pf-v5-c-form-control" value={remoteMulticastGroup} onChange={(e) => setRemoteMulticastGroup(e.target.value)} /></Field>
                    <Field t={t} label={t("UDPcast even portbase")}><input className="pf-v5-c-form-control" type="number" min="1024" max="65534" step="2" value={remoteMulticastPort} onChange={(e) => setRemoteMulticastPort(e.target.value)} /></Field>
                    <Alert variant="warning" title={t("Multicast transport limitation")} isInline>UDPcast data packets are not encrypted or authenticated. TLS protects the control plane, not the multicast data stream. Physical clone also requires every selected Client READY and a separate exclusive destination-open acknowledgement before transmission. Use only on a trusted, isolated deployment network.</Alert>
                  </>}
                  <Field t={t} label={t("Start policy")}>
                    <select className="pf-v5-c-form-control" value={remoteOperation === "clone" ? "manual" : remoteStartPolicy} disabled={remoteOperation === "clone"} onChange={(e) => setRemoteStartPolicy(e.target.value)}>
                      <option value="manual">Manual — every selected Client must be READY</option>
                      <option value="expected_clients">Start gate — minimum READY Client count</option>
                      <option value="deadline">Start gate — wait until UTC deadline</option>
                    </select>
                  </Field>
                  {remoteStartPolicy === "expected_clients" && <Field t={t} label={t("Minimum READY Clients")} help={`Must be between 1 and the ${remoteClients.split(/[\s,;]+/).filter(Boolean).length} selected Client(s). The Server still requires explicit job-specific authorization.`}>
                    <input className="pf-v5-c-form-control" type="number" min="1" max={Math.max(1, remoteClients.split(/[\s,;]+/).filter(Boolean).length)} value={remoteExpectedClients} onChange={(e) => setRemoteExpectedClients(e.target.value)} required />
                  </Field>}
                  {remoteStartPolicy === "deadline" && <Field t={t} label={t("Start deadline (local time)")} help="The deadline opens the start gate; it does not start disk I/O automatically. The Server operator must still enter the exact authorization phrase after the deadline.">
                    <input className="pf-v5-c-form-control" type="datetime-local" value={remoteStartDeadline} onChange={(e) => setRemoteStartDeadline(e.target.value)} required />
                  </Field>}
                  {remoteOperation !== "save" && <Field t={t} label={t("Final action on each successful Client")}>
                    <select className="pf-v5-c-form-control" value={remotePostAction} onChange={(e) => setRemotePostAction(e.target.value)}>
                      <option value="none">{t("Do nothing — leave Client running")}</option>
                      <option value="reboot">{t("Reboot Client after verified write")}</option>
                      <option value="poweroff">{t("Shut down Client after verified write")}</option>
                    </select>
                    <div className="pf-v5-u-color-200 pf-v5-u-font-size-sm">Applied independently by each Client only after its write/read-back verification and successful result report. Failed or disconnected Clients are not rebooted or shut down.</div>
                  </Field>}
                  <Button type="submit" variant="primary" isDisabled={busy || (remoteOperation === "clone" ? !remoteSourceDevice : !remoteImageId || (remoteOperation === "restore" && !remoteAvailableImages.some((item) => item.image_id === remoteImageId))) || !remoteClients.trim() || !remoteInterface || (remoteStartPolicy === "expected_clients" && (!Number.isInteger(Number(remoteExpectedClients)) || Number(remoteExpectedClients) < 1 || Number(remoteExpectedClients) > remoteClients.split(/[\s,;]+/).filter(Boolean).length)) || (remoteStartPolicy === "deadline" && (!remoteStartDeadline || !Number.isFinite(new Date(remoteStartDeadline).getTime())))}>Validate and save job definition</Button>
                </form>
                {remoteJobResult && <Alert variant="success" title={t("Job definition persisted")} isInline className="pf-v5-u-mt-md">{remoteJobResult.message}<p>Job ID: {remoteJobResult.job_id}</p></Alert>}
                </CardBody></Card>
              </StackItem>
              <StackItem><Title headingLevel="h2" size="lg">{t("Persisted remote jobs")}</Title>
                <p>Interrupted jobs can only be closed for audit after you have inspected every Client and destination manually. This does not resume or retry disk operations.</p>
                <Table aria-label={t("Persisted remote deployment jobs")} variant="compact"><Thead><Tr><Th>{t("Job ID")}</Th><Th>{t("operation")}</Th><Th>{t("Image")}</Th><Th>{t("Target")}</Th><Th>{t("Transport")}</Th><Th>{t("State")}</Th><Th>Client progress</Th><Th>{t("Recovery")}</Th><Th>{t("Events")}</Th><Th>{t("Service and execution")}</Th></Tr></Thead><Tbody>
                  {deploymentJobs.map((job) => <Tr key={job.job_id}><Td>{job.job_id}</Td><Td>{job.operation}</Td><Td>{job.operation === "clone" ? job.source_device : job.image_id}</Td><Td>{job.target_type}</Td><Td>{job.transport}</Td><Td>{job.job_state}</Td><Td>{Object.entries(job.clients || {}).map(([mac, client]) => mac + ": " + client.state).join(", ") || "Not connected"}</Td><Td>{job.interrupted ? <Stack hasGutter><StackItem><Label color="orange">{t("Review required · no auto-resume")}</Label></StackItem><StackItem><input className="pf-v5-c-form-control" aria-label={`Reconciliation confirmation for ${job.job_id}`} placeholder={`RECONCILE ${job.job_id}`} value={reconcileConfirmations[job.job_id] || ""} onChange={(event) => setReconcileConfirmations((current) => ({ ...current, [job.job_id]: event.target.value }))} /></StackItem><StackItem><Button variant="secondary" size="sm" isDisabled={busy || reconcileConfirmations[job.job_id] !== `RECONCILE ${job.job_id}`} onClick={() => reconcileDeploymentJob(job.job_id)}>{t("Close for audit")}</Button></StackItem></Stack> : "—"}</Td><Td>{job.event_count}</Td><Td>
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
                        {serviceStatuses[job.job_id].clients_truncated && <StackItem><Alert variant="warning" isInline title={t("Client list truncated")}>The local service status response is capped at 128 Client records.</Alert></StackItem>}
                        {serviceStatuses[job.job_id].multicast_preflight?.warnings?.length > 0 && <StackItem><Alert variant="warning" isInline title={t("Multicast network warnings")}>{serviceStatuses[job.job_id].multicast_preflight.warnings.join(" ")}</Alert></StackItem>}
                        {serviceStatuses[job.job_id].multicast_preflight?.error && <StackItem><Alert variant="danger" isInline title={t("Multicast preflight failed")}>{serviceStatuses[job.job_id].multicast_preflight.error}</Alert></StackItem>}
                        {serviceStatuses[job.job_id].job_state === "created" && <>
                          <StackItem><input className="pf-v5-c-form-control" aria-label={"Start authorization confirmation for " + job.job_id} placeholder={deploymentArmPhrase(job) || "Enrolled Client identity unavailable"} value={serviceConfirmations[job.job_id] || ""} onChange={(event) => setServiceConfirmations((current) => ({ ...current, [job.job_id]: event.target.value }))} /></StackItem>
                          <StackItem><Button size="sm" variant="primary" isDisabled={busy || !deploymentArmPhrase(job) || serviceConfirmations[job.job_id] !== deploymentArmPhrase(job)} onClick={() => sendDeploymentServiceCommand(job.job_id, "arm_deployment_job", serviceConfirmations[job.job_id])}>{t("Authorize and execute")}</Button></StackItem>
                          <StackItem><input className="pf-v5-c-form-control" aria-label={"Cancel confirmation for " + job.job_id} placeholder={"CANCEL " + job.job_id} value={serviceConfirmations[job.job_id + "-cancel"] || ""} onChange={(event) => setServiceConfirmations((current) => ({ ...current, [job.job_id + "-cancel"]: event.target.value }))} /></StackItem>
                          <StackItem><Button size="sm" variant="secondary" isDisabled={busy || serviceConfirmations[job.job_id + "-cancel"] !== "CANCEL " + job.job_id} onClick={() => sendDeploymentServiceCommand(job.job_id, "cancel_deployment_job", serviceConfirmations[job.job_id + "-cancel"])}>{t("Cancel before arm")}</Button></StackItem>
                        </>}
                        {!(serviceStatuses[job.job_id].worker_active) && serviceStatuses[job.job_id].job_state !== "running" && !(serviceStatuses[job.job_id].clients || []).some((client) => client.state === "running") && <StackItem><Button size="sm" variant="link" isDisabled={busy} onClick={() => stopDeploymentService(job.job_id)}>{t("Stop service")}</Button></StackItem>}
                        {serviceStatuses[job.job_id].last_error && <StackItem><Alert variant="danger" isInline title={t("Execution error")}>{serviceStatuses[job.job_id].last_error}</Alert></StackItem>}
                      </>}
                    </Stack>
                  </Td></Tr>)}
                  {!deploymentJobs.length && <Tr><Td colSpan={10}>No remote job definitions recorded.</Td></Tr>}
                </Tbody></Table>
              </StackItem>
            </Stack>
          </Tab>
          <Tab eventKey="deployments" title={t("tabHistory")}>
            <Stack hasGutter className="pf-v5-u-pt-lg"><StackItem><Title headingLevel="h2" size="xl">{t("deploymentJournals")}</Title></StackItem>
              <StackItem><Table aria-label={t("Feclora deployment history")} variant="compact"><Thead><Tr><Th>{t("Job ID")}</Th><Th>{t("State")}</Th><Th>{t("Interrupted")}</Th><Th>{t("Clients")}</Th><Th>Last durable progress</Th><Th>{t("Events")}</Th></Tr></Thead><Tbody>
                {journals.map((job) => <Tr key={job.job_id}><Td>{job.job_id}</Td><Td>{job.job_state}</Td><Td>{job.interrupted ? <Label color="orange">{t("Review required")}</Label> : "No"}</Td><Td>{Object.entries(job.clients || {}).map(([mac, state]) => mac + ": " + state).join(", ") || "—"}</Td><Td>{Object.entries(job.progress || {}).map(([mac, progress]) => mac + ": " + progress.phase + " " + (progress.completed_bytes / (1024 * 1024)).toFixed(1) + " MiB" + (progress.total_bytes === null ? "" : " / " + (progress.total_bytes / (1024 * 1024)).toFixed(1) + " MiB")).join("; ") || "No durable checkpoint"}</Td><Td>{job.event_count}</Td></Tr>)}
                {!journals.length && <Tr><Td colSpan={6}>{t("No deployment jobs recorded.")}</Td></Tr>}
              </Tbody></Table></StackItem>
            </Stack>
          </Tab>

          <Tab eventKey="repositories" title={t("tabRepositories")}>
            <Stack hasGutter className="pf-v5-u-pt-lg">
              <StackItem><Title headingLevel="h2" size="xl">{t("remoteImageRepositories")}</Title>
                <p>Manage remote image repositories. SSHFS, NFS and SMB/CIFS use mounted filesystems; S3 uses an object-storage API.</p>
              </StackItem>
              <StackItem><Card><CardBody><form onSubmit={saveRemoteRepository}>
                <Field t={t} label={t("Repository ID")}><input className="pf-v5-c-form-control" value={repositoryId} onChange={(e) => setRepositoryId(e.target.value)} pattern="[a-z0-9][a-z0-9-]{0,47}" maxLength={48} readOnly={repositoryEditing} required /></Field>
                <Field t={t} label={t("Provider")}><select className="pf-v5-c-form-control" value={repositoryProvider} onChange={(e) => { setRepositoryProvider(e.target.value); setRepositoryPort(e.target.value === "sshfs" ? "22" : ""); }}>
                  <option value="sshfs">SSHFS (remote filesystem over SSH)</option><option value="nfs">NFS</option><option value="smb">SMB/CIFS</option>
                </select></Field>
                <Field t={t} label={t("Server hostname or IPv4 address")}><input className="pf-v5-c-form-control" value={repositoryHost} onChange={(e) => setRepositoryHost(e.target.value)} maxLength={253} required /></Field>
                <Field t={t} label={repositoryProvider === "smb" ? "Share and optional subdirectory" : "Remote absolute path"}><input className="pf-v5-c-form-control" value={repositoryPath} onChange={(e) => setRepositoryPath(e.target.value)} maxLength={512} required /></Field>
                {(repositoryProvider === "sshfs" || repositoryProvider === "smb") && <Field t={t} label={t("Username")}><input className="pf-v5-c-form-control" value={repositoryUsername} onChange={(e) => setRepositoryUsername(e.target.value)} maxLength={64} required /></Field>}
                {repositoryProvider === "sshfs" && <>
                  <Field t={t} label={t("Encrypted SSH private-key credential")}><select className="pf-v5-c-form-control" value={repositoryIdentity} onChange={(e) => setRepositoryIdentity(e.target.value)} required><option value="">Select imported SSH key</option>{systemdCredentials.filter((item) => item.kind === "ssh-key").map((item) => <option key={item.path} value={item.path}>{item.id}</option>)}</select></Field>
                  <Field t={t} label={t("Encrypted pinned SSH known_hosts credential")}><select className="pf-v5-c-form-control" value={repositoryKnownHosts} onChange={(e) => setRepositoryKnownHosts(e.target.value)} required><option value="">{t("Select imported known_hosts")}</option>{systemdCredentials.filter((item) => item.kind === "known-hosts").map((item) => <option key={item.path} value={item.path}>{item.id}</option>)}</select></Field>
                </>}
                {repositoryProvider === "smb" && <Field t={t} label={t("Encrypted SMB credentials")}><select className="pf-v5-c-form-control" value={repositoryCredentials} onChange={(e) => setRepositoryCredentials(e.target.value)} required><option value="">{t("Select imported SMB credential")}</option>{systemdCredentials.filter((item) => item.kind === "smb").map((item) => <option key={item.path} value={item.path}>{item.id}</option>)}</select></Field>}
                <Field t={t} label={t("Port (optional)")}><input className="pf-v5-c-form-control" type="number" min="1" max="65535" value={repositoryPort} onChange={(e) => setRepositoryPort(e.target.value)} /></Field>
                <Field t={t} label={t("Mount access")}><select className="pf-v5-c-form-control" value={repositoryReadOnly ? "ro" : "rw"} onChange={(e) => setRepositoryReadOnly(e.target.value === "ro")}>
                  <option value="ro">{t("Read-only")}</option><option value="rw">Read/write (image capture)</option>
                </select></Field>
                <Button type="submit" variant="primary" isDisabled={busy || !repositoryId || !repositoryHost || !repositoryPath}>{repositoryEditing ? "Update repository definition" : "Save repository definition"}</Button>{" "}{repositoryEditing && <Button type="button" variant="link" onClick={resetRemoteRepositoryForm} isDisabled={busy}>{t("Cancel edit")}</Button>}
              </form></CardBody></Card></StackItem>
                            <StackItem><Title headingLevel="h2" size="lg">{t("Encrypted repository credentials")}</Title>
                <p>Import a root-owned private source file (mode 0600, no symlinks or hard links). For S3, provide a JSON file with exactly access_key_id and secret_access_key. Cockpit submits only its path; the API encrypts its contents with systemd-creds and never returns secret material. The source file remains in place and must be protected or securely removed by the operator.</p>
                <Card><CardBody><form onSubmit={importSystemdCredential}>
                  <Field t={t} label={t("Credential ID")}><input className="pf-v5-c-form-control" value={credentialId} onChange={(e) => setCredentialId(e.target.value)} pattern="[a-z0-9][a-z0-9-]{0,47}" maxLength={48} required /></Field>
                  <Field t={t} label={t("Credential type")}><select className="pf-v5-c-form-control" value={credentialKind} onChange={(e) => setCredentialKind(e.target.value)}><option value="ssh-key">SSH private key</option><option value="known-hosts">{t("SSH known_hosts")}</option><option value="smb">{t("SMB credentials")}</option><option value="s3">S3 access key pair (JSON)</option></select></Field>
                  <Field t={t} label={t("Protected source file path")}><input className="pf-v5-c-form-control" value={credentialSourceFile} onChange={(e) => setCredentialSourceFile(e.target.value)} maxLength={512} required /></Field>
                  <label><input type="checkbox" checked={credentialReplace} onChange={(e) => setCredentialReplace(e.target.checked)} /> Replace an existing credential with this ID and type</label>
                  <Button type="submit" variant="primary" isDisabled={busy || !credentialId || !credentialSourceFile}>{t("Import and encrypt credential")}</Button>
                </form></CardBody></Card>
                <Table aria-label={t("Encrypted repository credentials")} variant="compact"><Thead><Tr><Th>{t("ID")}</Th><Th>{t("type")}</Th><Th>{t("Encrypted reference")}</Th><Th>{t("Action")}</Th></Tr></Thead><Tbody>
                  {systemdCredentials.map((credential) => <Tr key={credential.name}><Td>{credential.id}</Td><Td>{credential.kind}</Td><Td>{credential.path}</Td><Td><Button size="sm" variant="danger" isDisabled={busy || remoteRepositories.some((repo) => (repo.credential_refs || []).includes(credential.path)) || s3Repositories.some((repo) => (repo.credential_refs || []).includes(credential.path))} onClick={() => removeSystemdCredential(credential)}>{t("Remove")}</Button></Td></Tr>)}
                  {!systemdCredentials.length && <Tr><Td colSpan={4}>{t("No encrypted credentials imported.")}</Td></Tr>}
                </Tbody></Table>
              </StackItem>
              <StackItem><Title headingLevel="h2" size="lg">{t("S3 object repositories")}</Title>
                <p>S3 is object storage, not a filesystem mount. Local operations use private staging and verified object transfers. Distributed jobs fetch and verify S3 images on the Server before authenticated TLS delivery to Clients; Client captures are published to S3 only after the TLS transfer has been verified. Clients never receive S3 credentials.</p>
                <Card><CardBody><form onSubmit={saveS3Repository}>
                  <Field t={t} label={t("Repository ID")}><input className="pf-v5-c-form-control" value={s3RepositoryId} onChange={(e) => setS3RepositoryId(e.target.value)} pattern="[a-z0-9][a-z0-9-]{0,47}" maxLength={48} required /></Field>
                  <Field t={t} label={t("S3 endpoint URL (optional; empty for AWS S3)")}><input className="pf-v5-c-form-control" value={s3Endpoint} onChange={(e) => setS3Endpoint(e.target.value)} placeholder={t("https://s3.example.net")} /></Field>
                  <Field t={t} label={t("Region")}><input className="pf-v5-c-form-control" value={s3Region} onChange={(e) => setS3Region(e.target.value)} maxLength={64} required /></Field>
                  <Field t={t} label={t("Bucket")}><input className="pf-v5-c-form-control" value={s3Bucket} onChange={(e) => setS3Bucket(e.target.value)} maxLength={63} required /></Field>
                  <Field t={t} label={t("Object prefix")}><input className="pf-v5-c-form-control" value={s3Prefix} onChange={(e) => setS3Prefix(e.target.value)} maxLength={512} /></Field>
                  <Field t={t} label={t("Encrypted S3 credential")}><select className="pf-v5-c-form-control" value={s3CredentialId} onChange={(e) => setS3CredentialId(e.target.value)} required><option value="">Select imported S3 key pair</option>{systemdCredentials.filter((item) => item.kind === "s3").map((item) => <option key={item.id} value={item.id}>{item.id}</option>)}</select></Field>
                  <Field t={t} label={t("Access")}><select className="pf-v5-c-form-control" value={s3ReadOnly ? "ro" : "rw"} onChange={(e) => setS3ReadOnly(e.target.value === "ro")}><option value="ro">{t("Read-only")}</option><option value="rw">{t("Read/write")}</option></select></Field>
                  <Button type="submit" variant="primary" isDisabled={busy || !s3RepositoryId || !s3Bucket || !s3CredentialId}>Save S3 repository</Button>
                </form></CardBody></Card>
                <Table aria-label={t("S3 object repositories")} variant="compact"><Thead><Tr><Th>{t("ID")}</Th><Th>{t("Endpoint")}</Th><Th>{t("Bucket / prefix")}</Th><Th>{t("Access")}</Th><Th>{t("Actions")}</Th></Tr></Thead><Tbody>
                  {s3Repositories.map((repo) => <Tr key={repo.id}><Td>{repo.id}</Td><Td>{repo.endpoint_url || "AWS S3"} · {repo.region}</Td><Td>{repo.bucket}/{repo.prefix}</Td><Td>{repo.read_only ? "Read-only" : "Read/write"}</Td><Td><Button size="sm" variant="secondary" isDisabled={busy} onClick={() => runS3RepositoryAction("check_s3_repository", repo.id)}>{t("Test connection")}</Button>{" "}<Button size="sm" variant="danger" isDisabled={busy} onClick={() => runS3RepositoryAction("remove_s3_repository", repo.id)}>{t("Remove")}</Button></Td></Tr>)}
                  {!s3Repositories.length && <Tr><Td colSpan={5}>{t("No S3 object repositories configured.")}</Td></Tr>}
                </Tbody></Table>
              </StackItem>
              <StackItem><Title headingLevel="h2" size="lg">{t("Configured repositories")}</Title>
                <p>“Identity verified” confirms only that findmnt reports the expected source, filesystem type and access mode. Remote health is always unknown: this inspection does not test network connectivity or perform remote filesystem I/O. An unknown mount state is not treated as unmounted; do not mount, edit or remove the repository until its state is resolved.</p>
                <Table aria-label={t("Remote image repositories")} variant="compact"><Thead><Tr><Th>{t("ID")}</Th><Th>{t("Provider")}</Th><Th>{t("Remote location")}</Th><Th>{t("Access")}</Th><Th>{t("Mount identity")}</Th><Th>{t("Actions")}</Th></Tr></Thead><Tbody>
                  {remoteRepositories.map((repo) => <Tr key={repo.id}><Td>{repo.id}</Td><Td>{repo.provider}</Td><Td>{repo.host}:{repo.remote_path}<br />{repo.mountpoint}</Td><Td>{repo.read_only ? "Read-only" : "Read/write"}</Td><Td>{repo.mount_state === "unknown" ? <><Label color="grey">{t("State unknown")}</Label>{repo.mount_error && <div className="pf-v5-u-color-danger pf-v5-u-font-size-sm">{repo.mount_error}</div>}</> : repo.mount_state === "unmounted" ? <Label color="grey">{t("Unmounted")}</Label> : repo.verified ? <Label color="green">{t("Mounted · identity verified")}</Label> : <><Label color="red">{t("Mounted · unverified")}</Label>{repo.mount_error && <div className="pf-v5-u-color-danger pf-v5-u-font-size-sm">{repo.mount_error}</div>}</>}{repo.health_state === "unknown" && <div className="pf-v5-u-color-secondary pf-v5-u-font-size-sm">{t("Remote health unknown")}</div>}</Td><Td>
                    <Button size="sm" variant="secondary" isDisabled={busy || repo.mount_state !== "unmounted"} onClick={() => editRemoteRepository(repo)}>{t("Edit")}</Button>{" "}
                    <Button size="sm" variant="secondary" isDisabled={busy} onClick={() => runRemoteRepositoryAction("check_remote_repository", repo.id)}>{t("Check mount identity")}</Button>{" "}
                    <Button size="sm" variant="secondary" isDisabled={busy || repo.mount_state !== "unmounted"} onClick={() => runRemoteRepositoryAction("mount_remote_repository", repo.id)}>{t("Mount")}</Button>{" "}
                    <Button size="sm" variant="secondary" isDisabled={busy || repo.mount_state !== "identity_verified"} onClick={() => runRemoteRepositoryAction("unmount_remote_repository", repo.id)}>{t("Unmount")}</Button>{" "}
                    <Button size="sm" variant="danger" isDisabled={busy || repo.mount_state !== "unmounted"} onClick={() => runRemoteRepositoryAction("remove_remote_repository", repo.id)}>{t("Remove")}</Button>
                  </Td></Tr>)}
                  {!remoteRepositories.length && <Tr><Td colSpan={6}>No remote repositories configured.</Td></Tr>}
                </Tbody></Table>
              </StackItem>
            </Stack>
          </Tab>
          <Tab eventKey="operation-log" title={t("tabOperationLog")}>
            <Stack hasGutter className="pf-v5-u-pt-lg"><StackItem><Title headingLevel="h2" size="xl">{t("localOperationHistory")}</Title><p>Durable local operation definitions and state history, including worker progress and terminal diagnostics. Interrupted writes are never resumed automatically. Cancelled or interrupted restores and clones may have partially modified their destination; inspect the target before reuse. Cancellation is orderly and may take time to stop child processes.</p></StackItem>
              <StackItem><Button variant="secondary" isDisabled={!operations.length} onClick={exportLocalOperations}>{t("Export latest 100 operations as JSON")}</Button><p className="pf-v5-u-color-200 pf-v5-u-font-size-sm">The export contains the history currently loaded in Cockpit, including device paths and bounded diagnostic messages. Store it with the same care as operational logs.</p></StackItem>
              <StackItem><Table aria-label={t("Local operation history")} variant="compact"><Thead><Tr><Th>{t("Timestamp")}</Th><Th>{t("operation")}</Th><Th>{t("Target")}</Th><Th>{t("Image")}</Th><Th>{t("status")}</Th><Th>{t("Progress")}</Th><Th>{t("Operation ID")}</Th><Th>{t("Details")}</Th><Th>{t("Control")}</Th></Tr></Thead><Tbody>
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
                    <Td>{item.operation_id}</Td><Td>{details.destination_may_be_partial ? <><strong>{t("Destination may be partially written.")}</strong> {details.reason || "Inspect it before reuse."}</> : details.error ? <><strong>{details.error_type || "Operation error"}:</strong> {details.error}</> : Array.isArray(details.manifests) ? (details.manifests.length ? "Found: " + details.manifests.join(", ") : "No manifest markers found.") : details.reason || "—"}</Td>
                    <Td>{item.cancellable !== false && ["queued", "preflight", "running"].includes(item.state) ? <Button size="sm" variant="danger" isDisabled={cancellingOperationId === item.operation_id} onClick={() => cancelLocalOperation(item.operation_id)}>{cancellingOperationId === item.operation_id ? "Requesting…" : "Cancel"}</Button> : "—"}</Td>
                  </Tr>;
                })}
                {!operations.length && <Tr><Td colSpan={9}>{t("No local operations recorded.")}</Td></Tr>}
              </Tbody></Table></StackItem>
            </Stack>
          </Tab>
          <Tab eventKey="network" title={t("tabNetwork")}>
            <Stack hasGutter className="pf-v5-u-pt-lg">
              <StackItem>
                <Title headingLevel="h2" size="xl">{t("Host IPv4 configuration")}</Title>
                <p>Configure the NetworkManager profile on this machine. Use this page on the Server or on each Client independently.</p>
                <Alert variant="warning" title={t("Management connectivity protection")} isInline>
                  Changes run under a 120-second NetworkManager checkpoint. If activation or verification fails, Feclora requests rollback; if Cockpit disconnects or the process is interrupted, NetworkManager automatically restores the previous network state when the checkpoint expires. Keep local console access available.
                </Alert>
              </StackItem>
              <StackItem>
                <form onSubmit={applyNetworkProfile}>
                  <Field t={t} label={t("NetworkManager connection profile")}>
                    <select className="pf-v5-c-form-control" value={networkProfileUuid} onChange={(event) => setNetworkProfileUuid(event.target.value)} required>
                      <option value="">{t("Select profile…")}</option>
                      {networkProfiles.map((profile) => <option key={profile.uuid} value={profile.uuid} disabled={!profile.device}>{profile.name} · {profile.type} · {profile.device || "not active"}{profile.active ? " · active" : ""}</option>)}
                    </select>
                  </Field>
                  <Field t={t} label={t("IPv4 configuration")}>
                    <select className="pf-v5-c-form-control" value={networkMethod} onChange={(event) => setNetworkMethod(event.target.value)}>
                      <option value="auto">DHCP (automatic)</option>
                      <option value="manual">{t("Static IPv4")}</option>
                    </select>
                  </Field>
                  {networkMethod === "manual" && <>
                    <Field t={t} label={t("IPv4 address")}><input className="pf-v5-c-form-control" value={networkAddress} onChange={(event) => setNetworkAddress(event.target.value)} required placeholder={t("192.0.2.10")} /></Field>
                    <Field t={t} label={t("Prefix length")}><input className="pf-v5-c-form-control" type="number" min="1" max="30" value={networkPrefix} onChange={(event) => setNetworkPrefix(event.target.value)} required /></Field>
                    <Field t={t} label={t("Gateway (optional)")}><input className="pf-v5-c-form-control" value={networkGateway} onChange={(event) => setNetworkGateway(event.target.value)} placeholder={t("192.0.2.1")} /></Field>
                    <Field t={t} label={t("DNS servers (comma-separated, optional)")}><input className="pf-v5-c-form-control" value={networkDns} onChange={(event) => setNetworkDns(event.target.value)} placeholder={t("192.0.2.53, 192.0.2.54")} /></Field>
                  </>}
                  <Button type="submit" variant="primary" isLoading={busy} isDisabled={busy || !networkProfileUuid}>{t("Apply and verify network configuration")}</Button>
                </form>
                {networkApplyResult && <Alert variant="success" title={t("Network configuration verified")} isInline className="pf-v5-u-mt-md">Interface {networkApplyResult.interface}, mode {networkApplyResult.method}, address {networkApplyResult.address || "assigned by DHCP"}.</Alert>}
              </StackItem>
            </Stack>
          </Tab>
          <Tab eventKey="server" title={t("Server setup")}>
            <Stack hasGutter className="pf-v5-u-pt-lg">
              <StackItem>
                <Title headingLevel="h2" size="xl">{t("Initialize deployment Server identity")}</Title>
                <p>Select an IPv4 address currently assigned to the management interface. Feclora will initialize its managed CA and Server TLS certificate. If age-keygen is installed, it can also provision optional age encryption material.</p>
                <Alert variant="info" title={t("This is the identity bootstrap step only")} isInline>
                  It does not enable DHCP/ProxyDHCP, configure PXE boot services, open firewall ports or start a deployment. Client enrollment is a separate, explicit removable-media trust ceremony below.
                </Alert>
              </StackItem>
              <StackItem>
                <Field t={t} label={t("Server network interface and address")} help="Only active non-loopback IPv4 addresses assigned to this host are offered.">
                  <select className="pf-v5-c-form-control" value={serverBinding} onChange={(e) => { setServerBinding(e.target.value); setPxePreflight(null); setPxeProfile(null); }}>
                    <option value="">{t("Select an interface/address…")}</option>
                    {networkInterfaces.map((item) => <option key={item.binding} value={item.binding}>{item.interface} · {item.address}/{item.prefix_length}</option>)}
                  </select>
                </Field>
                {networkInterfaces.length === 0 && <Alert variant="warning" title={t("No eligible IPv4 interface found")} isInline>Connect and configure the intended management interface, then refresh this page.</Alert>}
                {networkInterfaces.find((item) => item.binding === serverBinding)?.dhcp_server && <Alert variant="warning" title={t("Existing DHCP server detected")} isInline>
                  NetworkManager reports DHCP server {networkInterfaces.find((item) => item.binding === serverBinding).dhcp_server} on this interface. This identity-only step will not change DHCP settings; review the network topology before enabling PXE or DHCP services.
                </Alert>}
                <Button variant="primary" onClick={bootstrapServer} isLoading={busy} isDisabled={busy || !serverBinding || status?.server_configured}>{t("Initialize Server identity")}</Button>
              </StackItem>
              {status?.server_configured && <StackItem><Alert variant="success" title={t("Server configuration exists")} isInline>The existing configuration is not overwritten by this wizard. Continue with the remaining Server and PXE setup once those Cockpit workflows are available.</Alert></StackItem>}
              {status?.server_configured && <StackItem><Alert variant="info" title={t("Client authentication disabled")} isInline>Clients do not have certificates or individual credentials. Deployment jobs select Clients by MAC address; HTTPS/TLS Clients verify the Server certificate.</Alert></StackItem>}
              {status?.server_configured && <StackItem><Card><CardBody>

              </CardBody></Card></StackItem>}
              {status?.server_configured && <StackItem><Card><CardBody>
                <Title headingLevel="h3" size="lg">{t("Rotate Server TLS keypair")}</Title>
                <Alert variant="warning" title={t("New Server private key; existing CA retained")} isInline>This is separate from certificate renewal. All deployment jobs must be stopped. The new key and certificate are validated before installation; configured Clients continue to trust the existing CA and Server identity. This does not rotate the CA.</Alert>
                <Field t={t} label={t("Type exactly: ROTATE SERVER TLS KEYPAIR")}>
                  <input className="pf-v5-c-form-control" value={serverRotateConfirmation} onChange={(event) => setServerRotateConfirmation(event.target.value)} />
                </Field>
                <Button variant="danger" onClick={rotateServerKeypair} isLoading={busy} isDisabled={busy || serverRotateConfirmation !== "ROTATE SERVER TLS KEYPAIR"}>{t("Rotate Server TLS keypair")}</Button>
                {serverRotateResult && <Alert variant="success" title={t("Server TLS keypair rotated")} isInline>{serverRotateResult.message} · New certificate expires in {serverRotateResult.expiry_days} days; CA expires in {serverRotateResult.ca_expiry_days} days.</Alert>}
              </CardBody></Card></StackItem>}
              {status?.server_configured && <StackItem><Card><CardBody>
                <Title headingLevel="h3" size="lg">{t("Renew Server TLS certificate")}</Title>
                <Alert variant="warning" title={t("Existing CA and private key will be retained")} isInline>Renewal is blocked while any deployment job service is active. The Server certificate is replaced atomically; existing Clients continue trusting the same CA and Server identity. This does not rotate the CA or the Server private key.</Alert>
                <Field t={t} label={t("Type exactly: RENEW SERVER CERTIFICATE")}>
                  <input className="pf-v5-c-form-control" value={serverRenewConfirmation} onChange={(event) => setServerRenewConfirmation(event.target.value)} />
                </Field>
                <Button variant="danger" onClick={renewServerCertificate} isLoading={busy} isDisabled={busy || serverRenewConfirmation !== "RENEW SERVER CERTIFICATE"}>{t("Renew Server certificate")}</Button>
                {serverRenewResult && <Alert variant="success" title={t("Server certificate renewed")} isInline>{serverRenewResult.message} · Server certificate expires in {serverRenewResult.expiry_days} days; CA expires in {serverRenewResult.ca_expiry_days} days.</Alert>}
              </CardBody></Card></StackItem>}
              <StackItem>
                <Title headingLevel="h2" size="xl">{t("PXE network profile preflight")}</Title>
                <p>Validate a proposed PXE network configuration before any service is started. Select the same management interface above.</p>
                <Field t={t} label={t("DHCP mode")}>
                  <select className="pf-v5-c-form-control" value={pxeMode} onChange={(e) => { setPxeMode(e.target.value); setPxePreflight(null); }}>
                    <option value="proxy">ProxyDHCP (existing DHCP server assigns addresses)</option>
                    <option value="isolated">Isolated authoritative DHCP (dedicated VLAN only)</option>
                  </select>
                </Field>
                {pxeMode === "isolated" && <>
                  <Alert variant="warning" title={t("Authoritative DHCP can disrupt an existing network")} isInline>Only use isolated mode on a dedicated, verified network segment where Feclora is the sole DHCP authority. Never enable it on a shared LAN.</Alert>
                  <Field t={t} label={t("DHCP pool start")}><input className="pf-v5-c-form-control" value={pxePoolStart} onChange={(e) => setPxePoolStart(e.target.value)} placeholder={t("192.0.2.100")} /></Field>
                  <Field t={t} label={t("DHCP pool end")}><input className="pf-v5-c-form-control" value={pxePoolEnd} onChange={(e) => setPxePoolEnd(e.target.value)} placeholder={t("192.0.2.180")} /></Field>
                  <Field t={t} label={t("Lease duration")}><input className="pf-v5-c-form-control" value={pxeLease} onChange={(e) => setPxeLease(e.target.value)} placeholder={t("1h")} /></Field>
                  <Field t={t} label={t("Gateway (optional)")}><input className="pf-v5-c-form-control" value={pxeGateway} onChange={(e) => setPxeGateway(e.target.value)} placeholder={t("192.0.2.254")} /></Field>
                  <Field t={t} label={t("DNS server (optional)")}><input className="pf-v5-c-form-control" value={pxeDns} onChange={(e) => setPxeDns(e.target.value)} placeholder={t("192.0.2.254")} /></Field>
                  <label><input type="checkbox" checked={pxeAuthoritative} onChange={(e) => setPxeAuthoritative(e.target.checked)} /> I confirm this is an isolated VLAN and Feclora is its only DHCP server.</label>
                </>}
                <Field t={t} label={t("HTTP boot asset port")}><input className="pf-v5-c-form-control" type="number" min="1" max="65535" value={pxePort} onChange={(e) => setPxePort(e.target.value)} /></Field>
                <Field t={t} label={t("Maximum distinct PXE clients")} help="Optional limit of unique MAC addresses. Leave empty for no client-count limit. Repeated requests from an already registered MAC do not consume another slot."><input className="pf-v5-c-form-control" type="number" min="1" max="4096" value={pxeMaxClients} onChange={(e) => setPxeMaxClients(e.target.value)} placeholder={t("No limit")} /></Field>
                <Field t={t} label={t("Maximum PXE serving time (seconds)")} help="Optional deadline from service startup. Minimum 60 seconds. Leave empty for no time limit; if both fields are empty, PXE admission has no count or time limit."><input className="pf-v5-c-form-control" type="number" min="60" max="604800" value={pxeMaxDuration} onChange={(e) => setPxeMaxDuration(e.target.value)} placeholder={t("e.g. 3600")} /></Field>
                <Button variant="primary" onClick={validatePXEProfile} isLoading={busy} isDisabled={busy || !serverBinding || (pxeMode === "isolated" && (!pxePoolStart || !pxePoolEnd || !pxeAuthoritative))}>{t("Run PXE preflight")}</Button>
              </StackItem>
              {pxeStatus.configured && <StackItem><Alert variant="warning" title={t("PXE runtime is configured")} isInline>Stop the PXE services when network boot is no longer required, or if the service state is incomplete. <Button variant="danger" onClick={stopPXE} isLoading={busy} isDisabled={busy}>{t("Stop PXE services and restore firewall")}</Button></Alert></StackItem>}
              <StackItem>
                <Card><CardBody>
                  <Title headingLevel="h3" size="lg">{t("Publish unattended PXE answer")}</Title>
                  <p>Upload the prewritten JSON answer. The repository is selected by its <code>repository_id</code> field and must already be configured in the Live client through Feclora's normal repository manager. The Server validates the JSON and publishes it through Caddy over HTTP. The answer contains no URLs, credential references or secrets.</p>
                  <Alert variant="warning" title={t("Destructive operation guard")} isInline>The PXE Live client trusts the answer delivered by this HTTP server. When a client boots the unattended iPXE entry, a matching whole disk is restored automatically. The Live client resolves the selected repository through its normal Feclora managers: SSHFS, NFS, SMB/CIFS and S3, using credentials already protected in the Live configuration. No credential handoff or per-client identity is introduced. Images may be unencrypted or age-encrypted with a symmetric passphrase entered locally in Live Cockpit. Test only with disposable target disks.</Alert>
                  <Field t={t} label={t("Prewritten answer file (JSON)")}>
                    <input className="pf-v5-c-form-control" type="file" accept=".json,application/json" onChange={(event) => { setPxeAnswerFile(event.target.files?.[0] || null); setPxeAnswerPublished(null); }} />
                    {pxeAnswerFile && <div className="pf-v5-u-color-200 pf-v5-u-font-size-sm">{pxeAnswerFile.name} · {pxeAnswerFile.size} bytes</div>}
                  </Field>
                  <Button variant="primary" onClick={publishPXEAnswer} isLoading={busy} isDisabled={busy || !pxeStatus.active || !pxeAnswerFile}>{t("Validate and publish answer")}</Button>
                  {!pxeStatus.active && <p className="pf-v5-u-color-200 pf-v5-u-font-size-sm">Start PXE services first; publication is available only while the configured Caddy service is active.</p>}
                  {pxeAnswerPublished && <Alert variant="success" title={t("Answer published")} isInline className="pf-v5-u-mt-md">
                    <p>Job: {pxeAnswerPublished.job_id}</p>
                    <p>Answer: <a href={pxeAnswerPublished.answer_url} target="_blank" rel="noreferrer">{pxeAnswerPublished.answer_url}</a></p>
                    <p>iPXE handoff: <a href={pxeAnswerPublished.boot_script_url} target="_blank" rel="noreferrer">{pxeAnswerPublished.boot_script_url}</a></p>
                    <p>{pxeAnswerPublished.message}</p>
                    <Button variant="danger" size="sm" onClick={revokePXEAnswer} isLoading={busy} isDisabled={busy}>{t("Revoke published answer")}</Button>
                  </Alert>}
                </CardBody></Card>
              </StackItem>
              {pxeAgePassphraseStatus.available && (pxeAgePassphraseStatus.waiting || pxeAgePassphraseStatus.submitted) && <StackItem>
                <Card><CardBody>
                  <Title headingLevel="h3" size="lg">{t("Unlock encrypted PXE restore")}</Title>
                  {pxeAgePassphraseStatus.waiting
                    ? <>
                        <p>The PXE Live restore worker is waiting for the symmetric age passphrase. Enter it on this Live client. Cockpit submits it once through the local privileged API; it is not added to the answer JSON, URL or kernel command line.</p>
                        <Field t={t} label={t("age symmetric passphrase")}>
                          <input className="pf-v5-c-form-control" type="password" autoComplete="off" value={pxeAgePassphrase} onChange={(event) => setPxeAgePassphrase(event.target.value)} />
                        </Field>
                        <Button variant="primary" onClick={submitPXEAgePassphrase} isLoading={busy} isDisabled={busy || !pxeAgePassphrase}>{t("Submit passphrase to this Live client")}</Button>
                      </>
                    : <Alert variant="info" title={t("Passphrase submitted")} isInline>The Live restore worker has received the one-time passphrase and is continuing the authenticated restore preflight.</Alert>}
                </CardBody></Card>
              </StackItem>}
              {pxePreflight && <StackItem><Card><CardBody>
                <Alert variant="success" title={t("PXE preflight passed")} isInline>{pxePreflight.message}</Alert>
                <p>Interface: {pxePreflight.interface} · {pxePreflight.address}/{pxePreflight.prefix_length}</p>
                <p>Subnet: {pxePreflight.subnet} · Mode: {pxePreflight.mode}</p>
                <p>Unattended PXE admission: {pxePreflight.max_clients ? `${pxePreflight.max_clients} distinct MAC addresses` : "no client-count limit"}{pxePreflight.max_duration_seconds ? ` · ${pxePreflight.max_duration_seconds} seconds` : ""}. MAC addresses identify clients operationally; they are not authentication credentials.</p>
                <p>iPXE URL: {pxePreflight.http_url}</p>
                {pxePreflight.warnings.map((warning, index) => <Alert key={index} variant="warning" title={t("Network topology warning")} isInline>{warning}</Alert>)}
                {pxeStatus.active ? <Alert variant="success" title={t("PXE services active")} isInline>Interface {pxeStatus.interface}; dnsmasq, Caddy and the loopback MAC-admission service are managed as temporary services.</Alert> : pxeStatus.configured ? <Alert variant="warning" title={t("PXE runtime needs inspection")} isInline>The profile is recorded but one or more services are not active. Stop the profile to restore firewall state before trying again.</Alert> : <Alert variant="info" title={t("Preflight only")} isInline>No services have been started yet. Activation opens a temporary firewalld zone bound only to the selected interface; it is not enabled at boot.</Alert>}{!pxeStatus.configured && <Button variant="primary" onClick={activatePXE} isLoading={busy} isDisabled={busy || !pxeProfile}>{t("Activate PXE services")}</Button>}
              </CardBody></Card></StackItem>}
            </Stack>
          </Tab>
          <Tab eventKey="client-jobs" title={t("Client jobs")}>
            <Stack hasGutter className="pf-v5-u-pt-lg">
              <StackItem><Title headingLevel="h2" size="xl">{t("Remote job on this Client")}</Title>
                <p>Inspect the Server job over TLS; the Client does not authenticate itself, choose this machine's local target, type the exact destructive/read confirmation, then connect. The Client reports READY after approval and waits for the Server operator to authorize and start the operation.</p>
              </StackItem>
              {!status?.client_configured && <StackItem><Alert variant="warning" title={t("Client enrollment required")} isInline>Configure Server trust on this Client before inspecting or joining a remote job.</Alert></StackItem>}
              {status?.client_configured && <>
                <StackItem>
                  <Field t={t} label={t("Server host override")} help="Leave blank to use the enrolled Server host. The configured Server certificate identity is still verified.">
                    <input className="pf-v5-c-form-control" value={clientRemoteHost} onChange={(event) => setClientRemoteHost(event.target.value)} placeholder={t("Use enrolled Server host")} />
                  </Field>
                  <Field t={t} label={t("Remote job UUID")}>
                    <input className="pf-v5-c-form-control" value={clientRemoteJobId} onChange={(event) => { setClientRemoteJobId(event.target.value); setClientRemoteInspection(null); setClientRemoteJobStatus(null); }} placeholder={t("xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx")} />
                  </Field>
                  <Field t={t} label={t("Local multicast receive interface (also used for the Server connection)")} help="Select the local IPv4 interface/address used for the Server connection and, for multicast jobs, the UDPcast receive interface. The address and interface are revalidated before connection or receive startup.">
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
                    <Title headingLevel="h3" size="lg">{t("Authenticated Server job")}</Title>
                    <p>Operation: {clientRemoteJob.operation}{clientRemoteJob.operation === "clone" ? " · Server source: " + clientRemoteJob.source_device : " · Image: " + clientRemoteJob.image_id}</p>
                    <p>Target type: {clientRemoteJob.target_type} · Transport: {clientRemoteJob.transport}</p>
                    <p>Server identity: {clientRemoteInspection.server_identity}</p>
                    <p>Client connection source: {clientRemoteInspection.client_network_interface} · {clientRemoteInspection.client_source_address}</p>
                    <p>Authorized Client MACs: {(clientRemoteJob.authorized_clients || []).join(", ")}</p>
                    {clientRemoteJob.transport === "multicast" && <Alert variant="warning" title={t("Multicast network requirements")} isInline>All selected Clients must be READY before the Server operator authorizes and starts the operation. Confirm UDP multicast reachability, switch IGMP snooping and an active querier on the same VLAN. UDPcast data packets are not encrypted or authenticated; TLS protects only the control channel.</Alert>}
                    {clientRemoteJob.transport === "multicast" && <label><input type="checkbox" checked={clientRemoteIgmpConfirmed} onChange={(event) => setClientRemoteIgmpConfirmed(event.target.checked)} /> I verified IGMP snooping and an active querier on this VLAN, and confirmed all Clients are on the same multicast network.</label>}
                    {(clientRemoteJob.transport === "unicast" || clientRemoteJob.transport === "multicast") && <>

                      <Field t={t} label={clientRemoteJob.target_type === "logical_volume" ? "Local destination logical volume" : clientRemoteJob.target_type === "partition" ? "Local destination partition" : "Local destination disk"} help={clientRemoteJob.target_type === "logical_volume" ? "Choose an existing healthy linear or thin LV. It must be active, unmounted and large enough; Feclora will not create or resize LVM metadata. The Client rechecks the LVM topology before READY and immediately before writing." : "The selected block device is rechecked against live inventory immediately before READY. Root, mounted or busy destinations are rejected by the storage engine."}>
                        <select className="pf-v5-c-form-control" value={clientRemoteTarget} onChange={(event) => { setClientRemoteTarget(event.target.value); setClientRemoteConfirmation(""); }}>
                          <option value="">Select local target…</option>
                          {clientRemoteDeviceOptions.map((device) => <option key={device.path} value={device.path}>{device.path} · {device.model || device.name || device.type} · {device.size_bytes || ""}</option>)}
                        </select>
                      </Field>
                      {clientRemoteJob.operation === "save" && <>
                        <Field t={t} label={t("Capture compression")}>
                          <select className="pf-v5-c-form-control" value={clientRemoteCompression} onChange={(event) => setClientRemoteCompression(event.target.value)}>
                            <option value="none">None</option><option value="gzip">gzip</option><option value="xz">xz</option>
                          </select>
                        </Field>
                        <Field t={t} label={t("Protect this image (optional)")}>
                          <label><input type="checkbox" checked={clientRemoteEncrypt} disabled={!clientRemoteInspection.image_security?.age_encryption_available} onChange={(event) => setClientRemoteEncrypt(event.target.checked)} /> Encrypt this image with age</label>
                          <br />
                          {(!clientRemoteInspection.image_security?.age_encryption_available ) && <p className="pf-v5-u-color-200 pf-v5-u-font-size-sm">Unavailable options are disabled because this Client has no usable key material or executable. Leaving encryption unchecked creates an unencrypted image with SHA-256 integrity checks.</p>}
                        </Field>
                      </>}
                      {clientRemoteConfirmationPhrase && <Alert variant="warning" title={t("Type the exact local authorization phrase")} isInline>{clientRemoteConfirmationPhrase}</Alert>}
                      <Field t={t} label={t("Local target confirmation")}>
                        <input className="pf-v5-c-form-control" value={clientRemoteConfirmation} onChange={(event) => setClientRemoteConfirmation(event.target.value)} placeholder={t("Type the phrase shown above exactly")} />
                      </Field>
                      <Button variant="primary" onClick={startClientRemoteJob} isLoading={busy} isDisabled={busy || !clientRemoteTarget || !clientRemoteConfirmationPhrase || clientRemoteConfirmation !== clientRemoteConfirmationPhrase || (!clientRemoteInterface || (clientRemoteJob.transport === "multicast" && !clientRemoteIgmpConfirmed))}>{t("Connect and wait for Server authorization")}</Button>
                    </>}
                  </CardBody></Card>
                </StackItem>}
                {clientRemoteJobStatus && <StackItem>
                  <Card><CardBody>
                    <Title headingLevel="h3" size="lg">{t("Client service status")}</Title>
                    <Label color={clientRemoteJobStatus.phase === "completed" ? "green" : clientRemoteJobStatus.phase === "failed" || clientRemoteJobStatus.phase === "interrupted" ? "red" : "blue"}>{clientRemoteJobStatus.phase}</Label>
                    <p>{clientRemoteJobStatus.detail}</p>
                    {clientRemoteJobStatus.target_description && <p>Approved target: {clientRemoteJobStatus.target_description}</p>}
                    {clientRemoteJobStatus.progress && <p>{clientRemoteJobStatus.progress.phase || "Disk operation"}: {clientRemoteJobStatus.progress.completed_bytes} / {clientRemoteJobStatus.progress.total_bytes ?? "unknown"} bytes{clientRemoteJobStatus.progress.total_bytes > 0 ? " · " + Math.min(100, Math.round(clientRemoteJobStatus.progress.completed_bytes * 100 / clientRemoteJobStatus.progress.total_bytes)) + "%" : ""}</p>}
                    {clientRemoteJobStatus.multicast_preflight?.warnings?.length > 0 && <Alert variant="warning" title={t("Multicast switch checks")} isInline>{clientRemoteJobStatus.multicast_preflight.warnings.join(" ")}</Alert>}
                    {clientRemoteJobStatus.multicast_warnings?.length > 0 && <Alert variant="warning" title={t("Multicast switch checks")} isInline>{clientRemoteJobStatus.multicast_warnings.join(" ")}</Alert>}
                    {clientRemoteJobStatus.interrupted && <Alert variant="danger" title={t("Client service interrupted")} isInline>No automatic reconnect or disk-operation resume is available. Inspect the local destination and Server journal before creating another job.</Alert>}
                    <Button variant="secondary" onClick={refreshClientRemoteJobStatus} isLoading={busy} isDisabled={busy}>{t("Refresh Client status")}</Button>
                  </CardBody></Card>
                </StackItem>}
              </>}
            </Stack>
          </Tab>
          <Tab eventKey="system" title={t("system")}>
            <Stack hasGutter className="pf-v5-u-pt-lg"><StackItem><Title headingLevel="h2" size="xl">{t("systemStatus")}</Title></StackItem>
              <StackItem><KeyboardPreferences language={language} /></StackItem>
              <StackItem><Table aria-label={t("Feclora services")} variant="compact"><Thead><Tr><Th>{t("Component")}</Th><Th>{t("status")}</Th></Tr></Thead><Tbody>
                {Object.entries(status?.services || {}).map(([name, value]) => <Tr key={name}><Td>{name}</Td><Td>{value}</Td></Tr>)}
                <Tr><Td>{t("Server deployment configuration")}</Td><Td>{status?.server_configured ? "Configured" : "Not configured"}</Td></Tr>
                <Tr><Td>{t("Client deployment configuration")}</Td><Td>{status?.client_configured ? "Configured" : "Not configured"}</Td></Tr>
              </Tbody></Table></StackItem>
              <StackItem>
                <Title headingLevel="h2" size="lg">{t("security")}</Title>
                <p>Generate a local Feclora CA and optional age identity. Private keys remain on this machine; captured images can then be encrypted when selected.</p>
                <Table aria-label={t("Image security material")} variant="compact"><Thead><Tr><Th>{t("Capability")}</Th><Th>{t("status")}</Th></Tr></Thead><Tbody>
                  {Object.entries(security).map(([name, ready]) => <Tr key={name}><Td>{name.replaceAll("_", " ")}</Td><Td><Label color={ready ? "green" : "orange"}>{ready ? "Ready" : "Not initialized"}</Label></Td></Tr>)}
                </Tbody></Table>
                <Button variant="primary" onClick={initializeSecurity} isLoading={busy} isDisabled={busy}>{t("initializeKeys")}</Button>
              </StackItem>
              <StackItem><Alert variant="info" title={t("terminal")} isInline>{t("terminalHelp")}</Alert></StackItem>
            </Stack>
          </Tab>
        </Tabs>
      </PageSection>
      <PageSection variant="default"><p className="pf-v5-u-color-200">{t("footer")}</p></PageSection>
    </Page>
  );
}
