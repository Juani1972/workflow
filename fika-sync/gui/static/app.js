/**
 * Fika Sync — frontend.
 *
 * All state lives in the backend (SQLite via Flask). This file only
 * requests data, renders it, and sends changes back — it doesn't
 * store anything in localStorage or in variables that would be lost
 * on reload (that was exactly the original mockup's problem).
 */

const STATUS_LABELS = {
  green: { emoji: "🟢", label: "On track" },
  yellow: { emoji: "🟡", label: "At the limit" },
  red: { emoji: "🔴", label: "Overloaded" },
};

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `Error ${res.status} at ${path}`);
  }
  return res.json();
}

function renderStatusBadges(status) {
  const el = document.getElementById("status-badges");
  const names = { calcom: "Cal.com", google_calendar: "Google Calendar", slack: "Slack" };
  el.innerHTML = Object.entries(status.providers)
    .map(([key, info]) => {
      if (!info.credentials_configured) {
        return `<span class="badge badge--demo">${names[key]}: demo</span>`;
      }
      if (info.validated_against_real_account) {
        return `<span class="badge badge--validated">${names[key]}: connected ✓</span>`;
      }
      return `<span class="badge badge--connected">${names[key]}: connected (not validated)</span>`;
    })
    .join("");
}

function renderHero(metrics) {
  const redCount = Object.values(metrics.health_status).filter((s) => s === "red").length;
  const yellowCount = Object.values(metrics.health_status).filter((s) => s === "yellow").length;

  const headline = document.getElementById("hero-headline");
  const sub = document.getElementById("hero-sub");

  if (redCount > 0) {
    headline.textContent =
      redCount === 1
        ? "One person needs a break this week"
        : `${redCount} people need a break this week`;
  } else if (yellowCount > 0) {
    headline.textContent = "The team is close to the limit this week";
  } else {
    headline.textContent = "The team is doing well this week";
  }

  const sourceLabel = metrics.source === "demo" ? "sample data (demo)" : "Cal.com + Google Calendar";
  sub.textContent = `Week of ${metrics.week_start} · source: ${sourceLabel}`;
}

function sparklinePoints(history, maxHours) {
  if (history.length === 0) return "";
  const w = 200, h = 32, pad = 3;
  const max = Math.max(maxHours, ...history.map((h) => h.hours), 1);
  const stepX = history.length > 1 ? (w - pad * 2) / (history.length - 1) : 0;
  return history
    .map((point, i) => {
      const x = pad + stepX * i;
      const y = h - pad - (point.hours / max) * (h - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

async function renderTicket(person, metrics, deck) {
  const template = document.getElementById("ticket-template");
  const node = template.content.cloneNode(true);
  const article = node.querySelector(".ticket");

  const status = metrics.health_status[person] || "green";
  article.classList.add(`ticket--${status}`);

  node.querySelector(".ticket__stamp-label").textContent = STATUS_LABELS[status].label;
  node.querySelector(".ticket__name").textContent = person;

  const weekNumber = metrics.week_start.replace(/-/g, "").slice(2);
  node.querySelector(".ticket__number").textContent = `#F-${weekNumber}`;

  const hours = metrics.hours_by_person[person] ?? 0;
  node.querySelector(".ticket__hours-value").textContent = hours.toFixed(1);

  const thresholds = metrics.thresholds_by_person[person] || {};
  const yellowInput = node.querySelector('[data-field="yellow_hours"]');
  const redInput = node.querySelector('[data-field="red_hours"]');
  yellowInput.value = thresholds.yellow_hours ?? "";
  redInput.value = thresholds.red_hours ?? "";

  const saveBtn = node.querySelector('[data-action="save-threshold"]');
  const savedMsg = node.querySelector(".ticket__saved");
  saveBtn.addEventListener("click", async () => {
    saveBtn.disabled = true;
    try {
      await api("/api/thresholds", {
        method: "POST",
        body: JSON.stringify({ person, field: "yellow_hours", value: yellowInput.value }),
      });
      await api("/api/thresholds", {
        method: "POST",
        body: JSON.stringify({ person, field: "red_hours", value: redInput.value }),
      });
      savedMsg.textContent = "Saved.";
      setTimeout(() => (savedMsg.textContent = ""), 2500);
    } catch (err) {
      savedMsg.textContent = `Error: ${err.message}`;
    } finally {
      saveBtn.disabled = false;
    }
  });

  deck.appendChild(node);

  try {
    const history = await api(`/api/history/${encodeURIComponent(person)}`);
    const svg = article.querySelector(".ticket__sparkline");
    if (history.length > 0) {
      const points = sparklinePoints(history, thresholds.red_hours || 20);
      svg.innerHTML = `<polyline points="${points}" fill="none" stroke="currentColor" stroke-width="2" style="color: var(--color-ink-soft)" />`;
    }
  } catch {
    // The history is a visual nice-to-have; if it fails, the card is
    // still useful without the sparkline.
  }
}

async function renderDeck(metrics) {
  const deck = document.getElementById("ticket-deck");
  deck.innerHTML = "";
  const people = Object.keys(metrics.hours_by_person).sort();
  for (const person of people) {
    await renderTicket(person, metrics, deck);
  }
}

function renderSyncLog(entries) {
  const list = document.getElementById("sync-log");
  if (entries.length === 0) {
    list.innerHTML = "<li>No syncs yet.</li>";
    return;
  }
  list.innerHTML = entries
    .map((entry) => {
      const cls = entry.status === "ok" ? "receipt__status--ok" : "receipt__status--error";
      const when = new Date(entry.timestamp).toLocaleString();
      return `<li><span>${when} · ${entry.source}</span><span class="${cls}">${entry.status}</span></li>`;
    })
    .join("");
}

async function loadEverything() {
  const [status, metrics, log, team, workflowSettings, notifSettings, appCredentials] = await Promise.all([
    api("/api/status"),
    api("/api/metrics"),
    api("/api/sync-log"),
    api("/api/team"),
    api("/api/workflow-settings"),
    api("/api/notification-settings"),
    api("/api/admin/app-credentials"),
  ]);
  renderStatusBadges(status);
  renderAppConfig(appCredentials);
  renderConnections(status);
  renderHero(metrics);
  await renderDeck(metrics);
  renderSyncLog(log);
  renderTeamManager(team);
  renderWorkflowSettings(workflowSettings);
  renderNotificationSettings(notifSettings);
}

document.getElementById("sync-btn").addEventListener("click", async () => {
  const btn = document.getElementById("sync-btn");
  const hint = document.getElementById("sync-hint");
  btn.disabled = true;
  hint.textContent = "Syncing…";
  try {
    const result = await api("/api/sync", { method: "POST" });
    hint.textContent = result.fallback_reason
      ? `Real sync failed, demo data was used: ${result.fallback_reason}`
      : `Done — source: ${result.source}`;
    await loadEverything();
  } catch (err) {
    hint.textContent = `Error: ${err.message}`;
  } finally {
    btn.disabled = false;
  }
});

document.getElementById("reset-btn").addEventListener("click", async () => {
  if (!confirm("This deletes all saved sample data. Continue?")) return;
  try {
    await api("/api/reset-demo", { method: "POST", body: JSON.stringify({ confirm: true }) });
    await loadEverything();
  } catch (err) {
    alert(`Could not reset: ${err.message}`);
  }
});

const PROVIDER_LABELS = {
  calcom: "Cal.com",
  google: "Google (Calendar + Sheets)",
  slack: "Slack",
};

const CALCOM_API_KEYS_URL = "https://app.cal.com/settings/developer/api-keys";

// ---------------------------------------------------------------
// App configuration (Client ID/Secret) — done once by whoever
// administers the installation, not by each user. Replaces having
// to edit .env and restart the server.
// ---------------------------------------------------------------

const APP_CONFIG_LABELS = { google: "Google (Calendar + Sheets)", slack: "Slack" };
const APP_CONFIG_SETUP_LINKS = {
  google: { url: "https://console.cloud.google.com/apis/credentials", label: "Google Cloud Console ↗" },
  slack: { url: "https://api.slack.com/apps", label: "api.slack.com/apps ↗" },
};
const APP_CONFIG_SOURCE_LABELS = {
  guided: "configured from here",
  env_manual: "configured via environment variable (.env)",
};

function renderAppConfig(appCredentials) {
  const container = document.getElementById("app-config-list");

  container.innerHTML = Object.entries(appCredentials).map(([provider, info]) => {
    const label = APP_CONFIG_LABELS[provider];
    const setupLink = APP_CONFIG_SETUP_LINKS[provider];

    if (info.configured) {
      const sourceLabel = APP_CONFIG_SOURCE_LABELS[info.source] || info.source;
      const resetButton = info.source === "guided"
        ? `<button class="btn btn--ghost" data-action="reset-app-config" data-provider="${provider}" type="button">Remove</button>`
        : "";
      return `
        <div class="app-config-row">
          <span class="app-config-row__name">${label}</span>
          <span class="app-config-row__status app-config-row__status--connected">
            ✓ ${sourceLabel} (client_id: ${info.client_id_preview})
          </span>
          ${resetButton}
        </div>
      `;
    }

    return `
      <div class="app-config-row app-config-row--form">
        <span class="app-config-row__name">${label}</span>
        <span class="app-config-row__status">Not configured</span>
        <div class="app-config-row__form">
          <a class="btn btn--ghost" href="${setupLink.url}" target="_blank" rel="noopener">
            1. Create the Client ID/Secret at ${setupLink.label}
          </a>
          <div class="app-config-row__paste">
            <input type="text" data-field="app-config-client-id" data-provider="${provider}" placeholder="2. Client ID" autocomplete="off">
            <input type="text" data-field="app-config-client-secret" data-provider="${provider}" placeholder="3. Client Secret" autocomplete="off">
            <button class="btn btn--primary" data-action="save-app-config" data-provider="${provider}" type="button">Save</button>
          </div>
        </div>
      </div>
    `;
  }).join("");

  container.querySelectorAll('[data-action="save-app-config"]').forEach((btn) => {
    btn.addEventListener("click", async () => {
      const provider = btn.dataset.provider;
      const row = btn.closest(".app-config-row");
      const clientId = row.querySelector('[data-field="app-config-client-id"]').value.trim();
      const clientSecret = row.querySelector('[data-field="app-config-client-secret"]').value.trim();
      if (!clientId || !clientSecret) {
        alert("The Client ID and Client Secret are required.");
        return;
      }
      try {
        await api(`/api/admin/app-credentials/${provider}`, {
          method: "POST",
          body: JSON.stringify({ client_id: clientId, client_secret: clientSecret }),
        });
        await loadEverything();
      } catch (err) {
        alert(`Could not save: ${err.message}`);
      }
    });
  });

  container.querySelectorAll('[data-action="reset-app-config"]').forEach((btn) => {
    btn.addEventListener("click", async () => {
      const provider = btn.dataset.provider;
      if (!confirm(`Remove the ${APP_CONFIG_LABELS[provider]} configuration? Any connection already made with this app stays as is — this only affects NEW connections from now on.`)) return;
      try {
        await api(`/api/admin/app-credentials/${provider}/reset`, { method: "POST" });
        await loadEverything();
      } catch (err) {
        alert(`Could not remove: ${err.message}`);
      }
    });
  });
}

function renderCalcomRow(status) {
  const connected = status.oauth.connected.calcom;
  const info = status.providers.calcom;


  if (connected) {
    return `
      <div class="connection-row">
        <span class="connection-row__name">${PROVIDER_LABELS.calcom}</span>
        <span class="connection-row__status connection-row__status--connected">Connected ✓</span>
        <span class="connection-row__action">
          <button class="btn btn--ghost" data-disconnect="calcom" type="button">Disconnect</button>
        </span>
      </div>
    `;
  }

  const envNote = info.connection_method === "env_manual"
    ? '<p class="connection-row__hint">A CALCOM_API_KEY is already configured via environment variable — pasting one here replaces it.</p>'
    : "";

  // Cal.com doesn't offer OAuth for personal/free accounts (see
  // README) — this is a GUIDED flow, not a single click: the real
  // Cal.com key-generation page opens, and it gets pasted here.
  return `
    <div class="connection-row connection-row--form">
      <span class="connection-row__name">${PROVIDER_LABELS.calcom}</span>
      <span class="connection-row__status">Not connected</span>
      <div class="connection-row__form">
        <a class="btn btn--ghost" href="${CALCOM_API_KEYS_URL}" target="_blank" rel="noopener">
          1. Open the API keys page ↗
        </a>
        <div class="connection-row__paste">
          <input type="text" id="calcom-api-key-input" placeholder="2. Paste the key here (cal_...)" autocomplete="off">
          <button class="btn btn--primary" id="calcom-connect-btn" type="button">Save</button>
        </div>
        ${envNote}
      </div>
    </div>
  `;
}

function renderConnections(status) {
  const container = document.getElementById("connections-list");

  const oauthRows = ["google", "slack"].map((key) => {
    const providerKey = key === "google" ? "google_calendar" : "slack";
    const info = status.providers[providerKey];
    const appConfigured = status.oauth.app_configured[key];
    const connected = status.oauth.connected[key];

    let statusHtml, actionHtml;
    if (connected) {
      statusHtml = `<span class="connection-row__status connection-row__status--connected">Connected ✓</span>`;
      actionHtml = `<button class="btn btn--ghost" data-disconnect="${key}" type="button">Disconnect</button>`;
    } else if (info.connection_method === "env_manual") {
      statusHtml = `<span class="connection-row__status">Configured via environment variable (developer mode)</span>`;
      actionHtml = `<a class="btn btn--ghost" href="/oauth/${key}/start">Connect with one click</a>`;
    } else if (appConfigured && key === "slack") {
      // Slack has a second path besides the browser redirect: paste a
      // Bot User OAuth Token generated from "Install to workspace" at
      // api.slack.com/apps — useful when the redirect_uri can't be
      // HTTPS (Slack requires PKCE for 127.0.0.1/localhost without
      // HTTPS, see README).
      statusHtml = `<span class="connection-row__status">Not connected</span>`;
      actionHtml = `
        <div class="connection-row__form">
          <a class="btn btn--primary" href="/oauth/${key}/start">Connect with one click</a>
          <div class="connection-row__paste">
            <input type="text" id="slack-bot-token-input" placeholder="or paste Bot Token (xoxb-...)" autocomplete="off">
            <button class="btn btn--ghost" id="slack-connect-token-btn" type="button">Save token</button>
          </div>
        </div>
      `;
    } else if (appConfigured) {
      statusHtml = `<span class="connection-row__status">Not connected</span>`;
      actionHtml = `<a class="btn btn--primary" href="/oauth/${key}/start">Connect</a>`;
    } else {
      statusHtml = `<span class="connection-row__status connection-row__status--unavailable">The app doesn't have OAuth credentials configured</span>`;
      actionHtml = "";
    }

    return `
      <div class="connection-row">
        <span class="connection-row__name">${PROVIDER_LABELS[key]}</span>
        ${statusHtml}
        <span class="connection-row__action">${actionHtml}</span>
      </div>
    `;
  });

  container.innerHTML = [renderCalcomRow(status), ...oauthRows].join("");

  container.querySelectorAll("[data-disconnect]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const provider = btn.dataset.disconnect;
      if (!confirm(`Disconnect ${PROVIDER_LABELS[provider]}? You'll go back to demo mode (or to the environment variable, if set) until you connect again.`)) {
        return;
      }
      try {
        const endpoint = provider === "calcom" ? "/api/calcom/disconnect" : `/oauth/${provider}/disconnect`;
        await api(endpoint, { method: "POST" });
        await loadEverything();
      } catch (err) {
        alert(`Could not disconnect: ${err.message}`);
      }
    });
  });

  const slackConnectTokenBtn = document.getElementById("slack-connect-token-btn");
  if (slackConnectTokenBtn) {
    slackConnectTokenBtn.addEventListener("click", async () => {
      const input = document.getElementById("slack-bot-token-input");
      const botToken = input.value.trim();
      if (!botToken) {
        alert("Paste the Bot Token before saving.");
        return;
      }
      slackConnectTokenBtn.disabled = true;
      try {
        await api("/api/slack/connect-token", {
          method: "POST",
          body: JSON.stringify({ bot_token: botToken }),
        });
        await loadEverything();
      } catch (err) {
        alert(`Could not save the token: ${err.message}`);
      } finally {
        slackConnectTokenBtn.disabled = false;
      }
    });
  }

  const calcomConnectBtn = document.getElementById("calcom-connect-btn");
  if (calcomConnectBtn) {
    calcomConnectBtn.addEventListener("click", async () => {
      const input = document.getElementById("calcom-api-key-input");
      const apiKey = input.value.trim();
      if (!apiKey) {
        alert("Paste the API key before saving.");
        return;
      }
      calcomConnectBtn.disabled = true;
      try {
        await api("/api/calcom/connect", {
          method: "POST",
          body: JSON.stringify({ api_key: apiKey }),
        });
        await loadEverything();
      } catch (err) {
        alert(`Could not save the key: ${err.message}`);
      } finally {
        calcomConnectBtn.disabled = false;
      }
    });
  }
}

// ---------------------------------------------------------------
// Team: add / edit / remove people
// ---------------------------------------------------------------

function renderTeamManager(team) {
  const container = document.getElementById("team-manager-list");

  if (!team.length) {
    container.innerHTML = '<p class="team-manager__loading">Nobody on the team yet — use "+ Add person".</p>';
    return;
  }

  container.innerHTML = team.map((member) => `
    <div class="team-row" data-person="${member.person}">
      <span class="team-row__name">${member.person}</span>
      <input type="text" data-field="calcom_username" placeholder="Cal.com username" value="${member.calcom_username || ""}">
      <input type="email" data-field="gcal_email" placeholder="Google email" value="${member.gcal_email || ""}">
      <input type="text" data-field="slack_user_id" placeholder="Slack user ID" value="${member.slack_user_id || ""}">
      <div class="team-row__actions">
        <button class="btn btn--ghost" data-action="save-person" type="button">Save</button>
        <button class="btn btn--ghost" data-action="delete-person" type="button">Remove</button>
      </div>
      <div class="team-row__calendar">
        ${member.gcal_connected
          ? `<span class="team-row__calendar-status team-row__calendar-status--connected">📅 Calendar connected</span>
             <button class="btn btn--ghost" data-action="disconnect-calendar" type="button">Disconnect</button>`
          : member.calcom_connected
          ? `<span class="team-row__calendar-status team-row__calendar-status--muted">📅 Already connected via Cal.com — disconnect it to use Google instead</span>`
          : `<span class="team-row__calendar-status">📅 Calendar not connected</span>
             <a class="btn btn--ghost" href="/oauth/google/start/${encodeURIComponent(member.person)}">Connect my calendar</a>`
        }
      </div>
      <div class="team-row__calcom">
        ${member.calcom_connected
          ? `<span class="team-row__calcom-status team-row__calcom-status--connected">📆 Cal.com connected</span>
             <button class="btn btn--ghost" data-action="disconnect-calcom" type="button">Disconnect</button>`
          : member.gcal_connected
          ? `<span class="team-row__calcom-status team-row__calcom-status--muted">📆 Already connected via Google Calendar — disconnect it to use Cal.com instead</span>`
          : `<span class="team-row__calcom-status">📆 Cal.com not connected</span>
             <a class="btn btn--ghost" href="${CALCOM_API_KEYS_URL}" target="_blank" rel="noopener">Generate key ↗</a>
             <input type="text" data-field="calcom-api-key-personal" placeholder="Paste key (cal_...)" autocomplete="off">
             <button class="btn btn--ghost" data-action="connect-calcom" type="button">Connect</button>`
        }
      </div>
      <p class="team-row__saved" aria-live="polite"></p>
    </div>
  `).join("");

  container.querySelectorAll('[data-action="disconnect-calendar"]').forEach((btn) => {
    btn.addEventListener("click", async () => {
      const row = btn.closest(".team-row");
      const person = row.dataset.person;
      if (!confirm(`Disconnect ${person}'s calendar?`)) return;
      try {
        await api(`/oauth/google/disconnect/${encodeURIComponent(person)}`, { method: "POST" });
        await loadEverything();
      } catch (err) {
        alert(`Could not disconnect: ${err.message}`);
      }
    });
  });

  container.querySelectorAll('[data-action="connect-calcom"]').forEach((btn) => {
    btn.addEventListener("click", async () => {
      const row = btn.closest(".team-row");
      const person = row.dataset.person;
      const input = row.querySelector('[data-field="calcom-api-key-personal"]');
      const apiKey = input.value.trim();
      if (!apiKey) {
        alert("Paste the API key before connecting.");
        return;
      }
      try {
        await api(`/api/calcom/connect/${encodeURIComponent(person)}`, {
          method: "POST",
          body: JSON.stringify({ api_key: apiKey }),
        });
        await loadEverything();
      } catch (err) {
        alert(`Could not connect Cal.com: ${err.message}`);
      }
    });
  });

  container.querySelectorAll('[data-action="disconnect-calcom"]').forEach((btn) => {
    btn.addEventListener("click", async () => {
      const row = btn.closest(".team-row");
      const person = row.dataset.person;
      if (!confirm(`Disconnect Cal.com from ${person}?`)) return;
      try {
        await api(`/api/calcom/disconnect/${encodeURIComponent(person)}`, { method: "POST" });
        await loadEverything();
      } catch (err) {
        alert(`Could not disconnect: ${err.message}`);
      }
    });
  });

  container.querySelectorAll('[data-action="save-person"]').forEach((btn) => {
    btn.addEventListener("click", async () => {
      const row = btn.closest(".team-row");
      const person = row.dataset.person;
      const body = {};
      row.querySelectorAll("input[data-field]").forEach((input) => {
        body[input.dataset.field] = input.value.trim();
      });
      try {
        await api(`/api/team/${encodeURIComponent(person)}`, { method: "PUT", body: JSON.stringify(body) });
        row.querySelector(".team-row__saved").textContent = "Saved ✓";
      } catch (err) {
        alert(`Could not save: ${err.message}`);
      }
    });
  });

  container.querySelectorAll('[data-action="delete-person"]').forEach((btn) => {
    btn.addEventListener("click", async () => {
      const row = btn.closest(".team-row");
      const person = row.dataset.person;
      if (!confirm(`Remove ${person} from the team? Their hours history will also be deleted.`)) return;
      try {
        await api(`/api/team/${encodeURIComponent(person)}`, { method: "DELETE" });
        await loadEverything();
      } catch (err) {
        alert(`Could not remove: ${err.message}`);
      }
    });
  });
}

const addPersonBtn = document.getElementById("add-person-btn");
const addPersonForm = document.getElementById("add-person-form");

addPersonBtn.addEventListener("click", () => {
  addPersonForm.hidden = !addPersonForm.hidden;
});

document.getElementById("cancel-add-person").addEventListener("click", () => {
  addPersonForm.hidden = true;
  addPersonForm.reset();
  document.getElementById("add-person-error").textContent = "";
});

addPersonForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const errorEl = document.getElementById("add-person-error");
  errorEl.textContent = "";

  const body = {
    person: document.getElementById("new-person-name").value.trim(),
    calcom_username: document.getElementById("new-person-calcom").value.trim(),
    gcal_email: document.getElementById("new-person-gcal").value.trim(),
    slack_user_id: document.getElementById("new-person-slack").value.trim(),
    yellow_hours: parseFloat(document.getElementById("new-person-yellow").value),
    red_hours: parseFloat(document.getElementById("new-person-red").value),
  };

  try {
    await api("/api/team", { method: "POST", body: JSON.stringify(body) });
    addPersonForm.hidden = true;
    addPersonForm.reset();
    // Without this, the new person stays in "Team" but doesn't show
    // up as a card until the next sync — because their hours for the
    // current week were never calculated (the auto-sync in
    // /api/metrics only triggers when the week is ENTIRELY empty,
    // and there's already data for the other people).
    await api("/api/sync", { method: "POST" });
    await loadEverything();
  } catch (err) {
    errorEl.textContent = err.message;
  }
});

// ---------------------------------------------------------------
// Workflows: declarative toggles (see the note in the HTML)
// ---------------------------------------------------------------

function renderWorkflowSettings(workflows) {
  const container = document.getElementById("workflow-settings-list");

  container.innerHTML = workflows.map((wf) => `
    <div class="workflow-row">
      <span class="workflow-row__name">${wf.display_name}</span>
      <span class="workflow-row__badge ${wf.live_controlled ? "workflow-row__badge--live" : ""}">
        ${wf.live_controlled ? "runs here" : "declarative"}
      </span>
      <label class="switch">
        <input type="checkbox" data-workflow-id="${wf.workflow_id}" ${wf.enabled ? "checked" : ""} ${wf.live_controlled ? "disabled" : ""}>
        <span class="switch__track"></span>
      </label>
    </div>
  `).join("");

  container.querySelectorAll("input[data-workflow-id]").forEach((input) => {
    input.addEventListener("change", async () => {
      const workflowId = input.dataset.workflowId;
      try {
        await api(`/api/workflow-settings/${encodeURIComponent(workflowId)}`, {
          method: "POST",
          body: JSON.stringify({ enabled: input.checked }),
        });
      } catch (err) {
        input.checked = !input.checked; // revert on failure
        alert(`Could not save: ${err.message}`);
      }
    });
  });
}

// ---------------------------------------------------------------
// Notifications: Slack channel, frequency, publish now
// ---------------------------------------------------------------

function renderNotificationSettings(settings) {
  document.getElementById("notif-slack-channel").value = settings.slack_channel || "";
  document.getElementById("notif-frequency").value = String(settings.sync_frequency_minutes || 0);
  document.getElementById("notif-auto-publish").checked = !!settings.auto_publish_on_sync;
  document.getElementById("notif-personal-dms").checked = !!settings.personal_dms_enabled;
}

document.getElementById("save-notif-btn").addEventListener("click", async () => {
  const hint = document.getElementById("notif-hint");
  const body = {
    slack_channel: document.getElementById("notif-slack-channel").value.trim(),
    sync_frequency_minutes: parseInt(document.getElementById("notif-frequency").value, 10),
    auto_publish_on_sync: document.getElementById("notif-auto-publish").checked,
    personal_dms_enabled: document.getElementById("notif-personal-dms").checked,
  };
  try {
    await api("/api/notification-settings", { method: "POST", body: JSON.stringify(body) });
    hint.textContent = "Settings saved.";
    hint.className = "notif-settings__hint notif-settings__hint--ok";
  } catch (err) {
    hint.textContent = `Error: ${err.message}`;
    hint.className = "notif-settings__hint notif-settings__hint--error";
  }
});

document.getElementById("publish-now-btn").addEventListener("click", async () => {
  const btn = document.getElementById("publish-now-btn");
  const hint = document.getElementById("notif-hint");
  btn.disabled = true;
  hint.textContent = "Publishing…";
  hint.className = "notif-settings__hint";
  try {
    const result = await api("/api/publish-now", { method: "POST" });
    hint.textContent = `Published to ${result.channel} ✓`;
    hint.className = "notif-settings__hint notif-settings__hint--ok";
  } catch (err) {
    hint.textContent = `Error: ${err.message}`;
    hint.className = "notif-settings__hint notif-settings__hint--error";
  } finally {
    btn.disabled = false;
  }
});

const DM_RESULT_LABELS = {
  sent: "✓ DM sent",
  skipped_green: "🟢 not needed (all good)",
  skipped_no_slack_id: "⚠️ no slack_user_id set in Team",
};

document.getElementById("send-dms-btn").addEventListener("click", async () => {
  const btn = document.getElementById("send-dms-btn");
  const hint = document.getElementById("notif-hint");
  const resultsList = document.getElementById("dm-results");
  btn.disabled = true;
  hint.textContent = "Sending DMs…";
  hint.className = "notif-settings__hint";
  resultsList.innerHTML = "";
  try {
    const { results } = await api("/api/notifications/send-personal-dms", { method: "POST" });
    const sentCount = Object.values(results).filter((r) => r === "sent").length;
    hint.textContent = `${sentCount} DM(s) sent ✓`;
    hint.className = "notif-settings__hint notif-settings__hint--ok";
    resultsList.innerHTML = Object.entries(results).map(([person, outcome]) => {
      const label = DM_RESULT_LABELS[outcome] || `⚠️ ${outcome}`;
      return `<li><strong>${person}</strong>: ${label}</li>`;
    }).join("");
  } catch (err) {
    hint.textContent = `Error: ${err.message}`;
    hint.className = "notif-settings__hint notif-settings__hint--error";
  } finally {
    btn.disabled = false;
  }
});

function handleOAuthRedirectParams() {
  const params = new URLSearchParams(window.location.search);
  const connected = params.get("oauth_connected");
  const error = params.get("oauth_error");

  if (connected) {
    alert(`${PROVIDER_LABELS[connected] || connected} connected successfully.`);
  } else if (error && error.startsWith("google:already_connected_calcom:")) {
    const person = error.split(":")[2] || "";
    alert(
      `${person} already has Cal.com connected — there's no need (and it's not a good idea) to also ` +
      `connect Google Calendar: the same meeting would be counted twice. ` +
      `If you'd rather use Google instead, first disconnect Cal.com in their Team row.`
    );
  } else if (error && (error.startsWith("google:not_configured:") || error.startsWith("slack:not_configured:"))) {
    const provider = error.split(":")[0];
    alert(
      `${PROVIDER_LABELS[provider] || provider} can't be connected yet: ` +
      `whoever administers this Fika Sync installation needs to first configure ` +
      `the Client ID/Secret in the Connections tab.`
    );
  } else if (error) {
    alert(`The connection could not be completed (${error}). Check VALIDATION.md if the error comes from the real API.`);
  }

  if (connected || error) {
    const url = new URL(window.location.href);
    url.searchParams.delete("oauth_connected");
    url.searchParams.delete("oauth_error");
    window.history.replaceState({}, "", url.toString());
  }
}

handleOAuthRedirectParams();

loadEverything().catch((err) => {
  document.getElementById("hero-headline").textContent = "Could not load the team status.";
  document.getElementById("hero-sub").textContent = err.message;
});
