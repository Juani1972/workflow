const BASE = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Error ${res.status} en ${path}`);
  }
  return res.json();
}

export const api = {
  getTeam: () => request("/api/team"),
  addPerson: (name, role) =>
    request("/api/team", { method: "POST", body: JSON.stringify({ name, role }) }),
  removePerson: (id) => request(`/api/team/${id}`, { method: "DELETE" }),
  updateHours: (id, day, hours) =>
    request(`/api/team/${id}/hours`, {
      method: "PATCH",
      body: JSON.stringify({ day, hours }),
    }),
  getMetrics: () => request("/api/metrics"),
  getThresholds: () => request("/api/thresholds"),
  updateThreshold: (role, weekly_hours, daily_hours) =>
    request(`/api/thresholds/${role}`, {
      method: "PUT",
      body: JSON.stringify({ weekly_hours, daily_hours }),
    }),
  approveAction: (person_id, action, decision) =>
    request("/api/approve-action", {
      method: "POST",
      body: JSON.stringify({ person_id, action, decision }),
    }),
  getAuditLog: () => request("/api/audit-log"),
  updateCalcomConfig: (id, config) =>
    request(`/api/team/${id}/calcom-config`, {
      method: "PATCH",
      body: JSON.stringify(config),
    }),
};
