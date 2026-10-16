(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const escape = (value) =>
    String(value ?? "").replace(
      /[&<>"']/g,
      (char) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[char],
    );
  const localZone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const domain = location.hostname.replace(/^status\./, "");
  const local = ["localhost", "127.0.0.1", "[::1]"].includes(location.hostname);
  let zone = localZone,
    hours = 720,
    data = null,
    longestEvent = null,
    error = false,
    controller = null,
    visibleEvents = 20;
  try {
    const saved = localStorage.getItem("status.timezone");
    if ([localZone, "UTC"].includes(saved)) zone = saved;
  } catch (_) {}
  $("timezone").innerHTML = [...new Set([localZone, "UTC"])]
    .map(
      (tz) =>
        `<option value="${escape(tz)}">${escape(tz === "UTC" ? "UTC" : `Local · ${tz}`)}</option>`,
    )
    .join("");
  $("timezone").value = zone;
  $("domain-label").textContent = local ? "Service availability" : domain;
  document.title = local ? "Service status" : `Status · ${domain}`;

  const formatters = new Map();
  function date(value, style = "full") {
    const key = `${zone}:${style}`;
    if (formatters.has(key)) return formatters.get(key).format(new Date(value));
    const options = { timeZone: zone, month: "short", day: "numeric" };
    if (style !== "day")
      Object.assign(options, {
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
      });
    if (style === "day" || style === "event") options.year = "numeric";
    if (style === "full")
      Object.assign(options, {
        year: "numeric",
        second: "2-digit",
        timeZoneName: "shortOffset",
      });
    const formatter = new Intl.DateTimeFormat("en-GB", options);
    formatters.set(key, formatter);
    return formatter.format(new Date(value));
  }
  function duration(value) {
    let s = Math.max(0, Math.round(value || 0));
    if (s < 60) return `${s}s`;
    if (value > 60 && value < 61) return ">1m";
    if (s < 120) return `1m${s % 60 ? ` ${s % 60}s` : ""}`;
    const days = Math.floor(s / 86400);
    s %= 86400;
    const h = Math.floor(s / 3600),
      m = Math.floor((s % 3600) / 60);
    return days ? `${days}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`;
  }
  function preciseDuration(value) {
    const seconds = Math.max(0, Math.round(value || 0));
    const hours = Math.floor(seconds / 3600),
      minutes = Math.floor((seconds % 3600) / 60);
    return `${hours ? `${hours}h ` : ""}${minutes || hours ? `${minutes}m ` : ""}${seconds % 60}s`;
  }
  const name = (service) => service.name.replace(/\s*\([^)]*\)\s*$/, "");
  const stale = (service) =>
    !service.last_check || Date.now() - Date.parse(service.last_check) >=
      data.stale_after_seconds * 1000 ||
    Date.parse(service.last_check) > Date.now();
  const state = (service) =>
    error ? "unknown" : stale(service) ? "down" : service.status;
  const label = (status) =>
    ({
      up: "Online",
      down: "Offline",
      unknown: "No fresh checks",
      checking: "Checking",
    })[status];
  const tooltip = $("status-tooltip");
  const tooltipSelector = ".segment, .service-state, .metric";
  let tooltipAnchor = null,
    tooltipPinned = false,
    hideTimer;

  function hideTooltip() {
    clearTimeout(hideTimer);
    tooltipAnchor?.removeAttribute("aria-describedby");
    tooltipAnchor?.classList.remove("is-selected");
    tooltipAnchor = null;
    tooltipPinned = false;
    tooltip.hidden = true;
  }
  function positionTooltip() {
    if (!tooltipAnchor?.isConnected || tooltip.hidden) return;
    const anchor = tooltipAnchor.getBoundingClientRect();
    const box = tooltip.getBoundingClientRect();
    const left = Math.max(
      12,
      Math.min(
        anchor.left + anchor.width / 2 - box.width / 2,
        innerWidth - box.width - 12,
      ),
    );
    let top = anchor.top - box.height - 10;
    if (top < 12) top = anchor.bottom + 10;
    top = Math.max(12, Math.min(top, innerHeight - box.height - 12));
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;
  }
  function showTooltip(anchor, pinned = false) {
    if (!data) return;
    const service = data.services.find(
      (s) => s.id === Number(anchor.dataset.service),
    );
    if (!service) return;
    clearTimeout(hideTimer);
    if (tooltipAnchor !== anchor) {
      tooltipAnchor?.removeAttribute("aria-describedby");
      tooltipAnchor?.classList.remove("is-selected");
    }
    tooltipAnchor = anchor;
    tooltipPinned = pinned;
    let status, heading, body;
    if (anchor.classList.contains("segment")) {
      const index = Number(anchor.dataset.index);
      const { start, end, bucket } = bucketInfo(service, index);
      status = bucket.status;
      heading = {
        up: "No counted downtime",
        down: "Downtime recorded",
        unknown: "Observations missing",
      }[status];
      const reachable = Math.max(
        0,
        (end - start) / 1000 - bucket.down_seconds - bucket.unknown_seconds,
      );
      body = `<dl class="tooltip-times"><div><dt>From</dt><dd>${escape(date(start))}</dd></div><div><dt>To</dt><dd>${escape(date(end))}</dd></div></dl><div class="tooltip-metrics"><span><strong>${preciseDuration(reachable)}</strong>reachable</span><span><strong class="${bucket.down_seconds ? "bad" : ""}">${preciseDuration(bucket.down_seconds)}</strong>downtime</span></div>`;
      $("timeline-detail").textContent = bucketText(service, index);
    } else if (anchor.classList.contains("metric")) {
      status = service.down_seconds ? "down" : "up";
      heading = anchor.dataset.metric === "uptime" ? "Uptime" : "Downtime";
      body = `<dl class="tooltip-times"><div><dt>From</dt><dd>${escape(date(data.window_start))}</dd></div><div><dt>To</dt><dd>${escape(date(data.window_end))}</dd></div></dl><div class="tooltip-metrics"><span><strong>${service.uptime === null ? "—" : service.uptime.toFixed(2) + "%"}</strong>uptime</span><span><strong>${preciseDuration(service.down_seconds)}</strong>downtime</span><span><strong>${preciseDuration(service.unobserved_seconds)}</strong>from missing checks</span></div><p class="tooltip-help">Failed checks lasting 60 seconds or less are excluded. Missing observations count as downtime once checks become stale.</p>`;
    } else {
      status = state(service);
      heading = label(status);
      body = `<dl class="tooltip-times"><div><dt>Check</dt><dd>${service.last_check ? escape(date(service.last_check)) : "No checks recorded"}</dd></div></dl><p class="tooltip-help">${status === "unknown" ? "Current availability cannot be confirmed." : stale(service) ? "No fresh checks. Missing observations count as downtime." : "Based on the latest service check."}${service.response_time != null && status !== "unknown" && !stale(service) ? ` Response time: ${Math.round(service.response_time)} ms.` : ""}</p>`;
    }
    tooltip.dataset.status = status;
    tooltip.innerHTML = `<div class="tooltip-service">${escape(service.name)}</div><div class="tooltip-status is-${status}"><i class="state-dot ${status}" aria-hidden="true"></i>${heading}</div>${body}<p class="tooltip-help">Esc or tap outside to dismiss.</p>`;
    tooltip.hidden = false;
    anchor.setAttribute("aria-describedby", "status-tooltip");
    anchor.classList.add("is-selected");
    positionTooltip();
  }
  function scheduleHide() {
    if (tooltipPinned || document.activeElement === tooltipAnchor) return;
    clearTimeout(hideTimer);
    hideTimer = setTimeout(hideTooltip, 160);
  }
  function renderHealth() {
    if (!data) {
      $("health-title").textContent = error
        ? "Current status unavailable."
        : "Checking service health…";
      $("health-description").textContent = error
        ? "The status API could not be reached. This does not establish whether the services are down."
        : "Waiting for the latest observations.";
      $("health-dot").className = "state-dot unknown";
      return;
    }
    const down = data.services.filter((s) => state(s) === "down").length;
    const unknown = data.services.filter((s) => state(s) === "unknown").length;
    const checking = data.services.filter(
      (s) => state(s) === "checking",
    ).length;
    const total = data.services.length;
    const unverified = error || unknown || checking || !total;
    $("health-title").textContent = error
      ? "Live status could not be refreshed."
      : down
        ? `${down === total ? "All" : down} ${down === 1 ? "service" : "services"} offline`
        : unverified
          ? "Current health is not fully known."
          : "All services online";
    $("health-dot").className =
      `state-dot ${error ? "unknown" : down ? "down" : unverified ? "unknown" : "up"}`;
    $("health-description").textContent = total
      ? `${total - down - unknown - checking}/${total} online${down ? ` · ${down} offline` : ""}${checking ? ` · ${checking} checking` : ""}${unknown ? ` · ${unknown} unverified` : ""}${error ? " · Last received data" : ""}`
      : "No monitored services are configured for this domain.";
    const latest = data.services
      .map((s) => s.last_check)
      .filter(Boolean)
      .sort()
      .at(-1);
    $("last-updated").textContent = latest
      ? `Latest check ${date(latest)}`
      : "No checks recorded";
    document.querySelectorAll(".service-state").forEach((el) => {
      const service = data.services.find(
        (s) => s.id === Number(el.dataset.service),
      );
      if (!service) return;
      const status = state(service);
      el.className = `service-state is-${status}`;
      el.innerHTML = `<i class="state-dot ${status}" aria-hidden="true"></i>${label(status)}`;
      el.setAttribute(
        "aria-label",
        `${service.name}: ${label(status)}. Check details.`,
      );
    });
    if (tooltipAnchor?.matches(".service-state"))
      showTooltip(tooltipAnchor, tooltipPinned);
  }
  function bucketInfo(service, index) {
    const width =
      (Date.parse(data.window_end) - Date.parse(data.window_start)) /
      service.timeline.length;
    const start = Date.parse(data.window_start) + index * width,
      bucket = service.timeline[index];
    return { start, end: start + width, bucket };
  }
  function bucketText(service, index) {
    const { start, end, bucket } = bucketInfo(service, index);
    return `${service.name} · ${date(start)} → ${date(end)} · ${bucket.down_seconds ? `${duration(bucket.down_seconds)} unreachable` : "No counted downtime"}${bucket.unknown_seconds ? ` · ${duration(bucket.unknown_seconds)} unobserved` : ""}`;
  }
  function renderServices() {
    const active = document.activeElement?.closest(tooltipSelector);
    const focused = active
      ? [active.dataset.service, active.dataset.index, active.dataset.metric]
      : null;
    hideTooltip();
    $("services").setAttribute("aria-busy", "false");
    $("services").innerHTML = data.services.length
      ? data.services
          .map((service) => {
            const status = state(service);
            return `<article class="service"><div class="service-heading"><h3 class="service-name">${escape(name(service))}<span class="service-host">${escape(service.hostname)}</span></h3><button type="button" class="service-state is-${status}" data-service="${service.id}" aria-label="${escape(`${service.name}: ${label(status)}. Check details.`)}"><i class="state-dot ${status}" aria-hidden="true"></i>${label(status)}</button></div><div class="service-body"><div><div class="timeline" role="group" aria-label="${escape(service.name)} availability timeline">${service.timeline.map((bucket, index) => `<button type="button" class="segment ${bucket.status}" data-service="${service.id}" data-index="${index}" tabindex="${index === 0 ? 0 : -1}" aria-label="${escape(bucketText(service, index))}"></button>`).join("")}</div><div class="timeline-axis"><span>${escape(date(data.window_start, "short"))}</span><span>${escape(date(data.window_end, "short"))}</span></div></div><div class="service-numbers"><button type="button" class="metric" data-service="${service.id}" data-metric="uptime" aria-label="Uptime details"><strong>${service.uptime === null ? "—" : `${(Math.floor(service.uptime * 100) / 100).toFixed(2)}%`}</strong></button><button type="button" class="metric" data-service="${service.id}" data-metric="downtime" aria-label="Downtime details"><strong class="${service.down_seconds ? "bad" : ""}">${duration(service.down_seconds)}</strong></button></div></div></article>`;
          })
          .join("")
      : '<div class="empty">No services to display for this domain.</div>';
    if (focused) {
      const next = $("services").querySelector(
        focused[2]
          ? `.metric[data-service="${focused[0]}"][data-metric="${focused[2]}"]`
          : focused[1] === undefined
            ? `.service-state[data-service="${focused[0]}"]`
            : `.segment[data-service="${focused[0]}"][data-index="${focused[1]}"]`,
      );
      if (next) {
        if (next.classList.contains("segment")) {
          next.parentElement.firstElementChild.tabIndex = -1;
          next.tabIndex = 0;
        }
        next.focus({ preventScroll: true });
      }
    }
  }
  const eventKey = (event) =>
    `${event.kind}:${event.started_at}:${event.items.map((item) => item.service_id).join(",")}`;

  function renderEvents() {
    const expanded = new Set(
      [...$("events").querySelectorAll("details[open]")].map(
        (el) => el.dataset.event,
      ),
    );
    const events = [...data.events];
    if ($("event-sort").value === "longest")
      events.sort((a, b) => b.duration_seconds - a.duration_seconds);
    $("event-count").textContent = String(events.length);
    $("events").innerHTML = events.length
      ? events
          .slice(0, visibleEvents)
          .map((event) => {
            const outage = event.kind === "outage",
              open = !event.ended_at;
            const missing = event.items.some(
              (item) => item.unobserved_seconds > 0,
            );
            const title = missing ? "System outage" : outage
              ? event.items.length > 1
                ? "Overlapping service outages"
                : name({ name: event.items[0].service_name })
              : "No observations";
            const subtitle = `${event.items.length} ${event.items.length === 1 ? "service" : "services"}${outage ? " affected" : " without check data"}`;
            const key = eventKey(event);
            return `<details class="event" data-event="${escape(key)}"${expanded.has(key) ? " open" : ""}><summary><span class="event-date">${escape(date(event.started_at, "event"))}</span><span class="event-title">${escape(title)}<span class="event-subtitle">${subtitle}</span></span><span class="event-duration">${duration(event.duration_seconds)}${open ? "+" : ""}</span><span class="event-status ${open && outage ? "open" : ""}">${open ? "Unresolved" : "Recovered"}</span><span class="event-toggle" aria-hidden="true">+</span></summary><div class="event-body"><p class="event-range">Started: ${escape(date(event.started_at))}<br>Recovered: ${event.ended_at ? escape(date(event.ended_at)) : "Not recorded"}</p><p class="event-note">${missing ? "The system stopped recording observations. Missing checks after the freshness deadline are included in downtime." : `First failed check to first successful check${open ? " (no recovery recorded yet)" : ""}. Cause not established by HTTP checks.`} ${event.items.length > 1 ? "Duration spans the earliest outage start to the latest recovery in this group." : ""}</p>${event.items.map((item) => `<div class="event-service"><strong>${escape(item.service_name)}</strong><span>${escape(date(item.started_at))}<br>→ ${item.ended_at ? escape(date(item.ended_at)) : "No recovery recorded"} · ${duration(item.duration_seconds)}</span></div>`).join("")}</div></details>`;
          })
          .join("")
      : '<div class="empty">No recorded outages.</div>';
    $("show-more").hidden = visibleEvents >= events.length;
  }
  function render() {
    $("timezone-note").textContent = zone;
    renderHealth();
    if (!data) return;
    $("window-label").textContent =
      `${date(data.window_start, "short")} — ${date(data.window_end, "short")} · ${zone}`;
    $("archive-label").textContent =
      data.history_scope === "window"
        ? "Selected period"
        : data.history_started_at
          ? `Archive since ${date(data.history_started_at, "day")}`
          : "All retained history";
    const longest = data.events
      .filter(
        (e) =>
          e.kind === "outage" &&
          (!e.ended_at ||
            Date.parse(e.ended_at) >= Date.parse(data.window_start)),
      )
      .sort((a, b) => b.duration_seconds - a.duration_seconds)[0];
    longestEvent = longest;
    $("notable-event").hidden = !longest;
    $("notable-event").innerHTML = longest
      ? `<div class="notable"><div><strong>${longest.ended_at ? "Longest recorded outage" : "Unresolved outage"}: ${duration(longest.duration_seconds)}${longest.ended_at ? "" : "+"}</strong><p>${longest.items.length} ${longest.items.length === 1 ? "service" : "services"} · ${escape(date(longest.started_at))}${longest.ended_at ? ` → ${escape(date(longest.ended_at))}` : " · No recovery recorded"}</p></div><a href="#outages-title" id="view-longest">View history ↓</a></div>`
      : "";
    renderServices();
    renderEvents();
    $("timeline-detail").textContent =
      `Timelines run left to right. All times are ${zone}. Select a segment for exact times; use arrow keys to navigate.`;
  }
  async function refresh() {
    if (controller) controller.abort();
    const request = new AbortController();
    controller = request;
    const timeout = setTimeout(() => request.abort(), 20000);
    $("refresh").disabled = true;
    $("refresh").textContent = "Refreshing…";
    try {
      const params = new URLSearchParams({
        hours,
        history: $("history-scope").value,
      });
      if (!local) params.set("domain", domain);
      const response = await fetch(`/api/overview?${params}`, {
        signal: request.signal,
        cache: "no-store",
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const result = await response.json();
      if (
        !Array.isArray(result.services) ||
        !Array.isArray(result.events) ||
        !Number.isFinite(Date.parse(result.generated_at))
      )
        throw new Error("Invalid status response");
      if (controller !== request) return;
      data = result;
      error = false;
      $("connection-notice").hidden = true;
      render();
    } catch (_) {
      if (controller !== request) return;
      error = true;
      $("connection-notice").hidden = false;
      $("connection-notice").textContent =
        "Could not refresh status. Check your connection or retry. Any history below is the last data received; current health is unconfirmed.";
      renderHealth();
      if (!data) {
        $("services").setAttribute("aria-busy", "false");
        $("services").innerHTML =
          '<div class="empty">Service history is unavailable.</div>';
        $("events").innerHTML =
          '<div class="empty">Outage history is unavailable.</div>';
      }
    } finally {
      clearTimeout(timeout);
      if (controller === request) {
        $("refresh").disabled = false;
        $("refresh").innerHTML = 'Refresh <span aria-hidden="true">↻</span>';
      }
    }
  }
  $("timezone").addEventListener("change", (event) => {
    zone = event.target.value;
    try {
      localStorage.setItem("status.timezone", zone);
    } catch (_) {}
    render();
  });
  $("refresh").addEventListener("click", refresh);
  document.querySelectorAll("[data-hours]").forEach((button) =>
    button.addEventListener("click", () => {
      hideTooltip();
      hours = Number(button.dataset.hours);
      visibleEvents = 20;
      data = null;
      error = false;
      document
        .querySelectorAll("[data-hours]")
        .forEach((el) =>
          el.setAttribute("aria-pressed", String(el === button)),
        );
      $("services").innerHTML =
        '<div class="empty">Loading service history…</div>';
      $("services").setAttribute("aria-busy", "true");
      $("events").innerHTML =
        '<div class="empty">Loading recorded events…</div>';
      $("window-label").textContent = "Loading selected window…";
      $("notable-event").hidden = true;
      $("show-more").hidden = true;
      $("event-count").textContent = "";
      renderHealth();
      refresh();
    }),
  );
  $("event-sort").addEventListener("change", () => {
    visibleEvents = 20;
    if (data) renderEvents();
  });
  $("history-scope").addEventListener("change", () => {
    visibleEvents = 20;
    refresh();
  });
  $("show-more").addEventListener("click", () => {
    visibleEvents += 20;
    renderEvents();
  });
  $("notable-event").addEventListener("click", (event) => {
    if (event.target.closest("#view-longest")) {
      if (!longestEvent) return;
      $("event-sort").value = "longest";
      const ordered = [...data.events].sort(
        (a, b) => b.duration_seconds - a.duration_seconds,
      );
      const position = ordered.indexOf(longestEvent);
      visibleEvents = Math.max(
        visibleEvents,
        20 * Math.ceil((position + 1) / 20),
      );
      renderEvents();
      const target = [...$("events").querySelectorAll("details")].find(
        (entry) => entry.dataset.event === eventKey(longestEvent),
      );
      if (target) {
        target.open = true;
        requestAnimationFrame(() => target.scrollIntoView({ block: "center" }));
      }
    }
  });
  $("services").addEventListener("pointerover", (event) => {
    if (event.pointerType === "touch") return;
    const anchor = event.target.closest(tooltipSelector);
    if (anchor && !anchor.contains(event.relatedTarget)) showTooltip(anchor);
  });
  $("services").addEventListener("pointerout", (event) => {
    const anchor = event.target.closest(tooltipSelector);
    if (
      anchor &&
      anchor === tooltipAnchor &&
      !anchor.contains(event.relatedTarget) &&
      !tooltip.contains(event.relatedTarget)
    )
      scheduleHide();
  });
  $("services").addEventListener("focusin", (event) => {
    const anchor = event.target.closest(tooltipSelector);
    if (anchor) showTooltip(anchor);
  });
  $("services").addEventListener("focusout", (event) => {
    if (event.target === tooltipAnchor) hideTooltip();
  });
  $("services").addEventListener("click", (event) => {
    let anchor = event.target.closest(tooltipSelector);
    // Gaps and the extra height around short bars are also tappable.
    if (!anchor && event.target.classList.contains("timeline")) {
      const bounds = event.target.getBoundingClientRect();
      const buttons = event.target.children;
      const index = Math.max(
        0,
        Math.min(
          buttons.length - 1,
          Math.floor(
            ((event.clientX - bounds.left) / bounds.width) * buttons.length,
          ),
        ),
      );
      anchor = buttons[index];
    }
    if (anchor) showTooltip(anchor, true);
  });
  tooltip.addEventListener("pointerenter", () => clearTimeout(hideTimer));
  tooltip.addEventListener("pointerleave", scheduleHide);
  document.addEventListener("pointerdown", (event) => {
    if (
      tooltipAnchor &&
      !tooltipAnchor.contains(event.target) &&
      !tooltip.contains(event.target)
    )
      hideTooltip();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !tooltip.hidden) {
      hideTooltip();
      event.preventDefault();
    }
  });
  document.addEventListener(
    "scroll",
    (event) => {
      if (!tooltip.contains(event.target)) hideTooltip();
    },
    true,
  );
  window.addEventListener("resize", positionTooltip);
  $("services").addEventListener("keydown", (event) => {
    const button = event.target.closest(".segment");
    if (
      !button ||
      !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)
    )
      return;
    event.preventDefault();
    const buttons = [...button.parentElement.children];
    const index =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? buttons.length - 1
          : Math.max(
              0,
              Math.min(
                buttons.length - 1,
                buttons.indexOf(button) + (event.key === "ArrowRight" ? 1 : -1),
              ),
            );
    buttons.forEach((el) => (el.tabIndex = -1));
    buttons[index].tabIndex = 0;
    buttons[index].focus();
  });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refresh();
  });
  setInterval(() => {
    if (!document.hidden) refresh();
  }, 60000);
  setInterval(renderHealth, 10000);
  render();
  refresh();
})();
