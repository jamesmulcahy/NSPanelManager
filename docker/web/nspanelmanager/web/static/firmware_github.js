// "Firmware from GitHub" modal (templates/modals.html): shows the staged and the available firmware per board,
// and stages a GitHub release through /rest/v2/firmware and /rest/v2/firmware/stage.
(function () {
  // [model id, label] for each model that is built, from the models in board_models.py.
  function boards() {
    const data = document.getElementById("fwgh_boards");
    return (data && JSON.parse(data.textContent)) || [];
  }

  function el(id) {
    return document.getElementById(id);
  }

  function csrfToken() {
    const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]*)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function apiBase() {
    return el("firmware_github_modal").dataset.apiBase || "";
  }

  function short(value) {
    return value ? String(value).slice(0, 8) : "";
  }

  function node(tag, className, text) {
    const created = document.createElement(tag);
    if (className) created.className = className;
    if (text !== undefined) created.textContent = text;
    return created;
  }

  function showError(error) {
    const box = el("fwgh_error");
    box.replaceChildren();
    if (!error) {
      box.classList.add("hidden");
      return;
    }
    const text = error.code ? `${error.message || "Failed."} (${error.code}${error.board ? `, ${error.board}` : ""})` : error.message || "Failed.";
    box.appendChild(node("span", "", text));
    box.classList.remove("hidden");
  }

  function setBusy(busy) {
    el("fwgh_stage_button").disabled = busy;
    el("fwgh_refresh_button").disabled = busy;
    el("fwgh_release_select").disabled = busy;
    el("fwgh_spinner").classList.toggle("hidden", !busy);
  }

  async function errorFrom(response) {
    try {
      const body = await response.json();
      if (body && body.error) return body.error;
      if (body && body.detail) return { message: body.detail };
    } catch (e) {
      // Not JSON.
    }
    return { message: `HTTP ${response.status}` };
  }

  function renderStatus(data) {
    el("fwgh_repo").textContent = data.repo || "";
    el("fwgh_release").textContent = data.release || "";
    const body = el("fwgh_table_body");
    body.replaceChildren();
    for (const [board, label] of boards()) {
      const staged = (data.staged || {})[board] || {};
      const available = data.resolved && data.resolved.boards ? data.resolved.boards[board] : null;
      const upToDate = data.up_to_date ? data.up_to_date[board] : null;
      const row = node("tr");
      row.appendChild(node("td", "", label));

      const stagedCell = node("td");
      stagedCell.appendChild(node("div", "font-mono text-xs break-all", staged.md5 || "none"));
      const origin = staged.tag || short(staged.commit);
      if (origin) stagedCell.appendChild(node("div", "text-xs opacity-60", origin));
      row.appendChild(stagedCell);

      const availableCell = node("td");
      if (available) {
        availableCell.appendChild(node("div", "font-mono text-xs break-all", available.md5));
        if (data.resolved.tag) availableCell.appendChild(node("div", "text-xs opacity-60", data.resolved.tag));
      } else {
        availableCell.appendChild(node("div", "text-xs opacity-60", "unknown"));
      }
      row.appendChild(availableCell);

      const tick = node("td", upToDate ? "text-success text-xl" : "opacity-60");
      tick.textContent = upToDate === true ? "✓" : upToDate === false ? "behind" : "–";
      tick.title = upToDate === true ? "Up to date" : upToDate === false ? "A different build is available" : "Unknown";
      row.appendChild(tick);
      body.appendChild(row);
    }
  }

  function renderReleases(releases) {
    const select = el("fwgh_release_select");
    const chosen = select.value;
    select.replaceChildren();
    const latest = node("option", "", "Latest");
    latest.value = "";
    select.appendChild(latest);
    for (const release of releases || []) {
      const option = node("option", "", release.built_at ? `${release.tag} (${release.built_at.slice(0, 10)})` : release.tag);
      option.value = release.tag;
      select.appendChild(option);
    }
    select.value = [...select.options].some((option) => option.value === chosen) ? chosen : "";
  }

  function renderResult(result) {
    const box = el("fwgh_result");
    box.replaceChildren();
    if (!result) {
      box.classList.add("hidden");
      return;
    }
    box.appendChild(node("div", "font-medium", `Staged ${result.tag || ""}${result.commit ? ` (${short(result.commit)})` : ""}`));
    for (const [board, label] of boards()) {
      const change = (result.boards || {})[board];
      if (!change) continue;
      const line = node("div", "text-xs font-mono break-all");
      line.textContent = change.changed ? `${label}: ${change.before_md5 || "none"} → ${change.after_md5}` : `${label}: already staged (${change.after_md5})`;
      box.appendChild(line);
    }
    box.classList.remove("hidden");
  }

  async function load(options) {
    const keepResult = options && options.keepResult;
    // The list of releases is fetched on open, refresh and after staging, not when only the picker changes.
    const withReleases = !(options && options.pickerOnly);
    setBusy(true);
    showError(null);
    if (!keepResult) renderResult(null);
    try {
      const params = [];
      if (withReleases) params.push("releases=1");
      const chosen = el("fwgh_release_select").value;
      if (chosen) params.push(`release=${encodeURIComponent(chosen)}`);
      const response = await fetch(`${apiBase()}${params.length ? `?${params.join("&")}` : ""}`, { headers: { Accept: "application/json" } });
      if (!response.ok) {
        showError(await errorFrom(response));
        return;
      }
      const data = await response.json();
      renderStatus(data);
      if (data.releases) renderReleases(data.releases);
      showError(data.error);
    } catch (e) {
      showError({ message: `Couldn't reach the manager: ${e.message || e}` });
    } finally {
      setBusy(false);
    }
  }

  async function stage() {
    setBusy(true);
    showError(null);
    renderResult(null);
    const release = el("fwgh_release_select").value;
    try {
      const response = await fetch(`${apiBase()}/stage`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRFToken": csrfToken() },
        body: JSON.stringify(release ? { release } : {}),
      });
      if (!response.ok) {
        showError(await errorFrom(response));
        return;
      }
      renderResult(await response.json());
      setBusy(false);
      await load({ keepResult: true });
    } catch (e) {
      showError({ message: `Couldn't reach the manager: ${e.message || e}` });
    } finally {
      setBusy(false);
    }
  }

  function pick() {
    return load({ pickerOnly: true });
  }

  function open() {
    el("firmware_github_modal").showModal();
    return load();
  }

  window.firmwareGithub = { open, load, stage, pick };
})();
