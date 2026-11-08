const ACTIONS = new Set(["status", "inventory", "images", "journals"]);

export async function callFeclora(action) {
  if (!ACTIONS.has(action)) {
    throw new Error("Unsupported Feclora API action");
  }
  if (!window.cockpit?.spawn) {
    throw new Error("This page must be opened from the Cockpit web service");
  }
  const output = await window.cockpit.spawn(
    ["/usr/libexec/feclora/cockpit-api", action],
    { superuser: "require", err: "message" }
  );
  const response = JSON.parse(output);
  if (!response.ok) {
    throw new Error(response.error || "Feclora request failed");
  }
  return response.data;
}
