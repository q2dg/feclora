const ACTIONS = new Set([
  "status", "inventory", "images", "journals", "operations", "initialize_security",
  "network_interfaces", "bootstrap_server", "validate_pxe_profile", "start_pxe_services", "stop_pxe_services", "pxe_service_status",
  "capture_disk", "capture_partition", "restore_disk", "restore_partition",
  "clone_disk", "clone_partition"
]);

export async function callFeclora(action, params = {}, onEvent = () => {}) {
  if (!ACTIONS.has(action)) throw new Error("Unsupported Feclora API action");
  if (!window.cockpit?.spawn) throw new Error("Open Feclora from the Cockpit web service");
  const process = window.cockpit.spawn(
    ["/usr/libexec/feclora/cockpit-api", action],
    { superuser: "require", err: "message" }
  );
  let pending = "";
  let finalResponse = null;
  process.stream((chunk) => {
    pending += chunk;
    const lines = pending.split("\n");
    pending = lines.pop() || "";
    for (const line of lines) {
      if (!line.trim()) continue;
      const message = JSON.parse(line);
      if (message.event) onEvent(message);
      else finalResponse = message;
    }
  });
  process.input(JSON.stringify({ action, params }));
  process.close("stdin");
  let output;
  try {
    output = await process;
  } catch (error) {
    if (finalResponse?.ok === false) throw new Error(finalResponse.error || error.message);
    if (pending.trim()) {
      try {
        const last = JSON.parse(pending);
        if (last.ok === false) throw new Error(last.error || error.message);
      } catch (parseError) {
        if (parseError instanceof Error && parseError.message !== "Unexpected end of JSON input") throw parseError;
      }
    }
    throw error;
  }
  const lines = [pending, ...(output || "").split("\n").reverse()];
  for (const line of lines) {
    if (!line?.trim()) continue;
    const parsed = JSON.parse(line);
    if (parsed.ok === false) throw new Error(parsed.error || "Feclora request failed");
    if (parsed.ok === true) { finalResponse = parsed; break; }
  }
  if (!finalResponse?.ok) throw new Error("Feclora did not return an operation result");
  return finalResponse.data;
}
