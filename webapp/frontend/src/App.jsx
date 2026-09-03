import { useEffect, useRef, useState, useCallback } from "react";
import { api } from "./api";
import "./styles.css";

const DAY_LABELS = { mon: "M", tue: "T", wed: "W", thu: "T", fri: "F" };
const DAYS = ["mon", "tue", "wed", "thu", "fri"];
const ROLE_LABEL = { ic: "IC", manager: "Manager", lead: "Lead" };
const SEV_WORD = { green: "healthy", yellow: "at the limit", red: "overloaded" };

function nowLabel() {
  return new Date().toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
}

export default function App() {
  const [people, setPeople] = useState([]);
  const [metrics, setMetrics] = useState(null);
  const [thresholds, setThresholds] = useState({});
  const [feed, setFeed] = useState([]);
  const [connError, setConnError] = useState(null);
  const [connected, setConnected] = useState(false);
  const prevSeverity = useRef({});
  const [newName, setNewName] = useState("");
  const [newRole, setNewRole] = useState("ic");
  const debounceTimers = useRef({});
  const [doneApprovals, setDoneApprovals] = useState({});
  const [editingCalcomId, setEditingCalcomId] = useState(null);
  const [calcomForm, setCalcomForm] = useState({});

  const pushFeed = useCallback((html) => {
    setFeed((f) => [{ time: nowLabel(), html, id: Math.random() }, ...f].slice(0, 20));
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [team, m, th] = await Promise.all([
        api.getTeam(),
        api.getMetrics(),
        api.getThresholds(),
      ]);
      // detects severity transitions for the feed, same as the original prototype
      team.forEach((p) => {
        const prev = prevSeverity.current[p.id];
        if (prev !== undefined && prev !== p.severity) {
          if (p.severity === "red") {
            pushFeed(
              `Focus time suggested for <b>${p.name}</b> (${p.suggested_focus_hours}h) — 🔴 ${p.pct_of_threshold}% of threshold`
            );
          } else if (p.severity === "yellow") {
            pushFeed(`<b>${p.name}</b> entered the limit zone — 🟡 ${p.pct_of_threshold}% of threshold`);
          } else {
            pushFeed(`<b>${p.name}</b> is back in the healthy zone — 🟢 ${p.pct_of_threshold}% of threshold`);
          }
        }
        prevSeverity.current[p.id] = p.severity;
      });
      setPeople(team);
      setMetrics(m);
      setThresholds(th);
      setConnected(true);
      setConnError(null);
    } catch (e) {
      setConnected(false);
      setConnError(e.message || "Could not connect to the API");
    }
  }, [pushFeed]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function handleHoursChange(personId, day, value) {
    const hours = Math.max(0, Math.min(24, Number(value) || 0));
    setPeople((ps) =>
      ps.map((p) => (p.id === personId ? { ...p, hours: { ...p.hours, [day]: hours } } : p))
    );
    const key = `${personId}-${day}`;
    clearTimeout(debounceTimers.current[key]);
    debounceTimers.current[key] = setTimeout(async () => {
      try {
        await api.updateHours(personId, day, hours);
        await refresh();
      } catch (e) {
        setConnError(e.message);
      }
    }, 350);
  }

  async function handleAddPerson() {
    if (!newName.trim()) return;
    try {
      await api.addPerson(newName.trim(), newRole);
      pushFeed(`<b>${newName.trim()}</b> was added to the team`);
      setNewName("");
      await refresh();
    } catch (e) {
      setConnError(e.message);
    }
  }

  async function handleRemovePerson(id, name) {
    try {
      await api.removePerson(id);
      delete prevSeverity.current[id];
      pushFeed(`<b>${name}</b> was removed from the team`);
      await refresh();
    } catch (e) {
      setConnError(e.message);
    }
  }

  async function handleThresholdChange(role, field, value) {
    const num = Math.max(0.5, Number(value) || 0);
    const current = thresholds[role] || { weekly_hours: 0, daily_hours: 0 };
    const updated = { ...current, [field]: num };
    setThresholds((t) => ({ ...t, [role]: updated }));
    const key = `th-${role}`;
    clearTimeout(debounceTimers.current[key]);
    debounceTimers.current[key] = setTimeout(async () => {
      try {
        await api.updateThreshold(role, updated.weekly_hours, updated.daily_hours);
        pushFeed(`<b>${ROLE_LABEL[role]}</b> threshold updated: ${updated.weekly_hours}h/week`);
        await refresh();
      } catch (e) {
        setConnError(e.message);
      }
    }, 500);
  }

  async function handleApprove(person, decision) {
    try {
      const outcome = await api.approveAction(person.id, "protect_focus_time", decision);
      setDoneApprovals((d) => ({ ...d, [person.id]: decision }));
      if (decision !== "approved") {
        const label = decision === "modified" ? "modified" : "rejected";
        pushFeed(`Action for <b>${person.name}</b> ${label} — recorded in the audit log`);
      } else if (outcome.status === "executed" || outcome.status === "executed_with_warnings") {
        const steps = outcome.result?.steps ?? {};
        const detail = Object.entries(steps)
          .map(([name, s]) => {
            const icon = s.status === "executed" ? "✅" : s.status === "skipped" ? "⊘" : "⚠";
            return `${icon} ${name}`;
          })
          .join(" · ");
        pushFeed(
          `Focus time protected for <b>${person.name}</b> (slot: ${outcome.result?.blocked_slot ?? "?"}) — ${detail}`
        );
        Object.entries(steps)
          .filter(([, s]) => s.status === "failed")
          .forEach(([name, s]) => pushFeed(`⚠ Step <b>${name}</b> failed: ${s.reason}`));
      } else {
        pushFeed(`⚠ Could not execute for <b>${person.name}</b>: ${outcome.note}`);
      }
    } catch (e) {
      setConnError(e.message);
    }
  }

  function handleEditCalcomConfig(person) {
    setEditingCalcomId(person.id);
    setCalcomForm({ ...person.calcom_config });
  }

  async function handleSaveCalcomConfig(personId) {
    try {
      await api.updateCalcomConfig(personId, calcomForm);
      setEditingCalcomId(null);
      pushFeed(`Cal.com configuration updated`);
      await refresh();
    } catch (e) {
      setConnError(e.message);
    }
  }

  const pending = people.filter((p) => p.severity !== "green" && !doneApprovals[p.id]);

  return (
    <div className="app">
      <header className="top">
        <div className="brand">
          <div className={`brand-mark ${connected ? "live" : ""}`}></div>
          <div className="brand-name">Fika Sync</div>
          <div className={`brand-sub ${connected ? "live" : ""}`}>
            {connected ? "CONNECTED TO THE API" : "NOT CONNECTED"}
          </div>
        </div>
        <div className="brand-note">
          Data persisted in the real backend (SQLite) — no longer lost on reload. Classification
          uses the same logic already validated by the repo's tests.
        </div>
        {connError && (
          <div className="conn-error">⚠ {connError} — is `uvicorn main:app` running?</div>
        )}
      </header>

      <main>
        <div className="eyebrow">Team status — live</div>
        <h1 className="screen-title">War Room</h1>

        <div className="card">
          <div className="card-label">Focus thermometer</div>
          <div className="thermo-wrap">
            <div className="thermo-num">{metrics ? `${metrics.thermo_pct}%` : "—"}</div>
            <div className="thermo-bar">
              <div className="thermo-fill" style={{ width: `${metrics?.thermo_pct ?? 0}%` }} />
            </div>
          </div>
          <div className="thermo-caption">
            {metrics && metrics.total_hours > 0
              ? `${metrics.total_focus_hours}h of focus time suggested against ${metrics.total_hours}h total in meetings this week.`
              : "Add hours to calculate the thermometer."}
          </div>
        </div>

        <div className="card">
          <div className="card-label">
            Weekly load per person
            <span className="mono" style={{ fontSize: 9 }}>
              % of threshold
            </span>
          </div>
          <div className="bars">
            {people.map((p) => (
              <div className="bar-row" key={p.id}>
                <div className="bar-name">{p.name}</div>
                <div className="bar-track">
                  <div
                    className={`bar-fill ${p.severity}`}
                    style={{ width: `${Math.min(100, p.pct_of_threshold)}%` }}
                  />
                </div>
                <div className="bar-val">{p.pct_of_threshold}%</div>
              </div>
            ))}
            {people.length === 0 && <div className="feed-empty">No one on the team.</div>}
          </div>
        </div>

        <div className="card">
          <div className="card-label">
            Load per person · Mon–Fri <span className="mono" style={{ fontSize: 9 }}>hours</span>
          </div>
          <div className="table-scroll">
            <table className="heatmap">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Role</th>
                  {DAYS.map((d) => (
                    <th key={d}>{DAY_LABELS[d]}</th>
                  ))}
                  <th>Total</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {people.map((p) => (
                  <tr key={p.id}>
                    <td className="name">
                      <span className="p-name" style={{ display: "inline-block", borderBottom: "none" }}>
                        {p.name}
                      </span>
                    </td>
                    <td>
                      <span className="mono" style={{ fontSize: 9, color: "var(--text-dim)" }}>
                        {ROLE_LABEL[p.role] || p.role}
                      </span>
                    </td>
                    {DAYS.map((d) => {
                      const dayTh = p.daily_threshold || 1;
                      const dayPct = (p.hours[d] / dayTh) * 100;
                      const cls = dayPct <= 80 ? "green" : dayPct <= 100 ? "yellow" : "red";
                      return (
                        <td key={d}>
                          <input
                            type="number"
                            min="0"
                            max="24"
                            className={`cell ${cls}`}
                            value={p.hours[d]}
                            onChange={(e) => handleHoursChange(p.id, d, e.target.value)}
                          />
                        </td>
                      );
                    })}
                    <td className="total">
                      <span className={`pill ${p.severity}`}>
                        <span className="dot"></span>
                        {p.weekly_hours}h
                      </span>
                    </td>
                    <td>
                      <button className="p-remove" onClick={() => handleRemovePerson(p.id, p.name)}>
                        ✕
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <input
              className="p-name"
              style={{ flex: 1, borderBottom: "1px solid var(--line-strong)" }}
              placeholder="New person's name"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleAddPerson()}
            />
            <select className="p-role" value={newRole} onChange={(e) => setNewRole(e.target.value)}>
              {Object.keys(ROLE_LABEL).map((r) => (
                <option key={r} value={r}>
                  {ROLE_LABEL[r]}
                </option>
              ))}
            </select>
          </div>
          <button className="add-row" onClick={handleAddPerson}>
            + Add person
          </button>
          <div className="threshold-note">
            🟢 ≤80% of threshold · 🟡 ≤100% · 🔴 &gt;100%. Thresholds editable below.
          </div>
        </div>

        <div className="card">
          <div className="card-label">Thresholds by role</div>
          <div className="thresh-grid">
            {Object.entries(thresholds).map(([role, t]) => (
              <div className="thresh-item" key={role}>
                <div className="thresh-role">{ROLE_LABEL[role] || role}</div>
                <div className="thresh-inputs">
                  <label>
                    Weekly
                    <input
                      type="number"
                      min="1"
                      value={t.weekly_hours}
                      onChange={(e) => handleThresholdChange(role, "weekly_hours", e.target.value)}
                    />
                  </label>
                  <label>
                    Daily
                    <input
                      type="number"
                      min="0.5"
                      step="0.5"
                      value={t.daily_hours}
                      onChange={(e) => handleThresholdChange(role, "daily_hours", e.target.value)}
                    />
                  </label>
                </div>
              </div>
            ))}
          </div>
          <div className="threshold-note">
            Editing here updates the whole team's classification instantly.
          </div>
        </div>

        <div className="card">
          <div className="card-label">Actions pending approval</div>
          <div className="approvals">
            {pending.length === 0 && <div className="approval-empty">Nothing pending right now.</div>}
            {pending.map((p) => (
              <div className="approval-row" key={p.id}>
                <div className="approval-text">
                  Protect <b>{p.suggested_focus_hours}h</b> of focus time for <b>{p.name}</b> —{" "}
                  {SEV_WORD[p.severity]} ({p.pct_of_threshold}%)
                </div>
                <div className="approval-actions">
                  <button className="approve" onClick={() => handleApprove(p, "approved")}>
                    Approve
                  </button>
                  <button className="modify" onClick={() => handleApprove(p, "modified")}>
                    Modify
                  </button>
                  <button className="reject" onClick={() => handleApprove(p, "rejected")}>
                    Reject
                  </button>
                </div>
              </div>
            ))}
          </div>
          <div className="threshold-note">
            Decisions are recorded in the audit log. When approved, the backend attempts to
            actually execute it against Cal.com — if configuration or credentials are missing,
            it fails with a clear reason instead of faking success.
          </div>
        </div>

        <div className="card">
          <div className="card-label">Per-person Cal.com configuration</div>
          <div className="threshold-note" style={{ marginTop: 0, marginBottom: 10 }}>
            Needed for "Approve" to actually execute. Configured once per person.
          </div>
          <div className="approvals">
            {people.map((p) => (
              <div key={`cc-${p.id}`}>
                <div className="approval-row">
                  <div className="approval-text">
                    <b>{p.name}</b>{" "}
                    {p.calcom_ready ? (
                      <span className="pill green">
                        <span className="dot"></span>ready
                      </span>
                    ) : (
                      <span className="pill red">
                        <span className="dot"></span>needs config
                      </span>
                    )}
                  </div>
                  <button
                    className="p-remove"
                    style={{ fontSize: 11, color: "var(--text-dim)" }}
                    onClick={() =>
                      editingCalcomId === p.id ? setEditingCalcomId(null) : handleEditCalcomConfig(p)
                    }
                  >
                    {editingCalcomId === p.id ? "Close" : "Edit"}
                  </button>
                </div>
                {editingCalcomId === p.id && (
                  <div className="approval-row" style={{ flexDirection: "column", alignItems: "stretch", gap: 8 }}>
                    <input
                      className="p-name"
                      style={{ borderBottom: "1px solid var(--line-strong)" }}
                      placeholder="Cal.com username (e.g. alex-ruiz)"
                      value={calcomForm.calcom_username || ""}
                      onChange={(e) => setCalcomForm((f) => ({ ...f, calcom_username: e.target.value }))}
                    />
                    <input
                      className="p-name"
                      style={{ borderBottom: "1px solid var(--line-strong)" }}
                      placeholder="Attendee email"
                      value={calcomForm.attendee_email || ""}
                      onChange={(e) => setCalcomForm((f) => ({ ...f, attendee_email: e.target.value }))}
                    />
                    <input
                      className="p-name"
                      style={{ borderBottom: "1px solid var(--line-strong)" }}
                      placeholder="IANA timezone (e.g. Europe/Madrid)"
                      value={calcomForm.attendee_timezone || ""}
                      onChange={(e) => setCalcomForm((f) => ({ ...f, attendee_timezone: e.target.value }))}
                    />
                    <input
                      className="p-name"
                      style={{ borderBottom: "1px solid var(--line-strong)" }}
                      placeholder="2h block event_type_id"
                      value={calcomForm.focus_event_type_id_short || ""}
                      onChange={(e) =>
                        setCalcomForm((f) => ({ ...f, focus_event_type_id_short: e.target.value }))
                      }
                    />
                    <input
                      className="p-name"
                      style={{ borderBottom: "1px solid var(--line-strong)" }}
                      placeholder="4h block event_type_id"
                      value={calcomForm.focus_event_type_id_long || ""}
                      onChange={(e) =>
                        setCalcomForm((f) => ({ ...f, focus_event_type_id_long: e.target.value }))
                      }
                    />
                    <input
                      className="p-name"
                      style={{ borderBottom: "1px solid var(--line-strong)" }}
                      placeholder="Google Calendar ID (optional)"
                      value={calcomForm.gcal_calendar_id || ""}
                      onChange={(e) => setCalcomForm((f) => ({ ...f, gcal_calendar_id: e.target.value }))}
                    />
                    <input
                      className="p-name"
                      style={{ borderBottom: "1px solid var(--line-strong)" }}
                      placeholder="Slack user ID, U0123 (optional)"
                      value={calcomForm.slack_user_id || ""}
                      onChange={(e) => setCalcomForm((f) => ({ ...f, slack_user_id: e.target.value }))}
                    />
                    <button className="add-row" style={{ marginTop: 0 }} onClick={() => handleSaveCalcomConfig(p.id)}>
                      Save
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        <div className="card">
          <div className="card-label">
            Live activity <span className="mono" style={{ fontSize: 9 }}>generated as you edit</span>
          </div>
          <div className="feed">
            {feed.length === 0 && (
              <div className="feed-empty">Edit a cell or threshold to generate the first event.</div>
            )}
            {feed.map((ev) => (
              <div className="feed-item" key={ev.id}>
                <div className="feed-time mono">{ev.time}</div>
                <div className="feed-text" dangerouslySetInnerHTML={{ __html: ev.html }} />
              </div>
            ))}
          </div>
        </div>
      </main>

      <p className="foot-note">
        Real backend (FastAPI + SQLite) serving this GUI. Cal.com, Google Calendar and Slack
        are still not connected — that requires the user's real credentials.
      </p>
    </div>
  );
}
