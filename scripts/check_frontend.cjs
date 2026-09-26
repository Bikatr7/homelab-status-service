// Run with PLAYWRIGHT_MODULE and BROWSER_PATH pointing to installed test tools.
// All requests are intercepted; no production service or data is modified.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const frontend = path.join(__dirname, "../frontend");
const html = fs.readFileSync(
  path.join(
    frontend,
    fs.existsSync(path.join(frontend, "preview.html"))
      ? "preview.html"
      : "index.html",
  ),
  "utf8",
);
const forbidden = /192\.168\.|wi-fi|same network/i;
const privateTerms = (process.env.STATUS_PRIVATE_TERMS || "")
  .split(",")
  .filter(Boolean);
for (const source of [
  html,
  ...fs
    .readdirSync(path.join(frontend, "assets"))
    .filter((f) => /\.(css|js)$/.test(f))
    .map((f) => fs.readFileSync(path.join(frontend, "assets", f), "utf8")),
]) {
  assert.equal(
    forbidden.test(source) ||
      privateTerms.some((term) =>
        source.toLowerCase().includes(term.toLowerCase()),
      ),
    false,
    "Private infrastructure information in public source",
  );
}

function fixture() {
  const now = Date.now(),
    stamp = (offset) => new Date(now + offset * 1000).toISOString();
  const items = [1, 2, 3].map((id) => ({
    service_id: id,
    service_name: `Service ${id}`,
    started_at: stamp(-43200),
    ended_at: stamp(-7200),
    duration_seconds: 36000,
    unobserved_seconds: 0,
  }));
  return {
    generated_at: stamp(0),
    window_start: stamp(-86400),
    window_end: stamp(0),
    stale_after_seconds: 180,
    minimum_outage_seconds: 60,
    history_scope: "all",
    history_started_at: "2025-10-10T13:20:35Z",
    check_interval_seconds: 60,
    services: items.map((item) => ({
      id: item.service_id,
      name: item.service_name,
      hostname: `service${item.service_id}.example.com`,
      status: "up",
      last_check: stamp(-10),
      response_time: 120,
      uptime: 58.333,
      coverage: 100,
      down_seconds: 36000,
      unknown_seconds: 0,
      timeline: Array.from({ length: 96 }, (_, i) => ({
        status: i >= 48 && i < 88 ? "down" : "up",
        down_seconds: i >= 48 && i < 88 ? 900 : 0,
        unknown_seconds: 0,
      })),
    })),
    events: [
      {
        kind: "outage",
        started_at: stamp(-43200),
        ended_at: stamp(-7200),
        duration_seconds: 36000,
        items,
      },
      {
        kind: "outage",
        started_at: stamp(-100 * 86400),
        ended_at: stamp(-98 * 86400),
        duration_seconds: 172800,
        items: items.map((item) => ({
          ...item,
          started_at: stamp(-100 * 86400),
          ended_at: stamp(-98 * 86400),
          duration_seconds: 172800,
        })),
      },
    ],
  };
}

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.BROWSER_PATH || undefined,
  });
  try {
    const context = await browser.newContext({
      viewport: { width: 1440, height: 1000 },
      timezoneId: "America/Denver",
      hasTouch: true,
    });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    let data = fixture(),
      failure = false;
    await context.route("**/*", async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname === "/api/overview") {
        if (failure) return route.fulfill({ status: 503, body: "Unavailable" });
        return route.fulfill({ json: data });
      }
      if (url.pathname.startsWith("/assets/"))
        return route.fulfill({
          path: path.join(frontend, url.pathname.slice(1)),
        });
      if (url.pathname === "/")
        return route.fulfill({ contentType: "text/html", body: html });
      return route.abort();
    });
    async function ready() {
      await page.locator(".service").first().waitFor();
    }
    async function refresh() {
      await page.locator("#refresh").click();
      await page.waitForFunction(
        () => !document.getElementById("refresh").disabled,
      );
    }
    await page.goto("http://status.example.com/");
    await ready();
    assert.equal(await page.locator("h1").textContent(), "All services online");
    assert.match(await page.locator("#notable-event").textContent(), /10h 0m/);
    assert.equal(await page.locator(".segment.down").count(), 120);
    assert.equal(
      await page.locator("[title]").count(),
      0,
      "Native browser tooltip remains",
    );
    assert.equal(await page.locator("#history-scope").inputValue(), "all");
    assert.equal(
      await page.locator('[data-hours="720"]').getAttribute("aria-pressed"),
      "true",
    );
    assert.match(await page.locator("#archive-label").textContent(), /2025/);
    assert.doesNotMatch(
      await page.locator("body").textContent(),
      /Refreshes every minute|Full coverage/,
    );
    assert.equal(await page.locator(".metric small").count(), 0);
    const colors = await page.evaluate(() => {
      const root = getComputedStyle(document.documentElement);
      const up = getComputedStyle(document.querySelector(".segment.up"));
      const down = getComputedStyle(document.querySelector(".segment.down"));
      return {
        scheme: root.colorScheme,
        upHeight: parseFloat(up.height),
        downHeight: parseFloat(down.height),
        downPattern: down.backgroundImage,
        paper: root.getPropertyValue("--paper").trim(),
        ink: root.getPropertyValue("--ink").trim(),
        muted: root.getPropertyValue("--muted").trim(),
        healthy: root.getPropertyValue("--healthy").trim(),
        outage: root.getPropertyValue("--outage").trim(),
      };
    });
    assert.equal(colors.scheme, "dark");
    assert.equal(
      colors.downHeight,
      colors.upHeight,
      "All timeline bars must have the same height",
    );
    assert.equal(
      colors.downPattern,
      "none",
      "Outage bars must be solid, not striped",
    );
    assert.equal(colors.healthy, "#59ca8a");
    assert.equal(colors.outage, "#ff777b");
    function luminance(hex) {
      return [1, 3, 5]
        .map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
        .map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
        .reduce((sum, c, i) => sum + c * [0.2126, 0.7152, 0.0722][i], 0);
    }
    for (const key of ["ink", "muted", "healthy", "outage"])
      assert.ok(
        (luminance(colors[key]) + 0.05) / (luminance(colors.paper) + 0.05) >=
          4.5,
        `${key} contrast below 4.5:1`,
      );
    const tooltip = page.locator("#status-tooltip");
    await page.locator('[data-metric="uptime"]').first().focus();
    await tooltip.waitFor();
    assert.match(
      await tooltip.textContent(),
      /Only outages longer than 60 seconds count/,
    );
    await page.keyboard.press("Escape");
    await page.locator(".segment.down").first().hover();
    await tooltip.waitFor();
    assert.match(await tooltip.textContent(), /Downtime recorded/);
    assert.match(await tooltip.textContent(), /From.*To/s);
    await tooltip.hover();
    assert.equal(
      await tooltip.isVisible(),
      true,
      "Tooltip must remain available when hovered",
    );
    await page.keyboard.press("Escape");
    assert.equal(await tooltip.isVisible(), false);
    await page.locator(".service-state").first().focus();
    assert.match(await tooltip.textContent(), /Response time: 120 ms/);
    await page.keyboard.press("Escape");
    assert.match(
      await page.locator("#window-label").textContent(),
      /America\/Denver/,
    );
    await page.locator("#timezone").selectOption("UTC");
    assert.match(await page.locator("#window-label").textContent(), /UTC/);
    await page.locator("#view-longest").click();
    assert.ok(
      (await page.locator(".event[open]").getAttribute("data-event")).includes(
        data.events[0].started_at,
      ),
      "Banner opened a different, older outage",
    );
    assert.equal(await page.locator("details[open]").count(), 1);
    await refresh();
    assert.equal(
      await page.locator("details[open]").count(),
      1,
      "Refresh collapsed an expanded outage",
    );
    const first = page.locator(".segment").first();
    await first.focus();
    await page.keyboard.press("ArrowRight");
    assert.equal(
      await page.evaluate(() => document.activeElement.dataset.index),
      "1",
    );
    assert.match(
      await page.locator("#timeline-detail").textContent(),
      /Service 1/,
    );
    assert.equal(await first.getAttribute("title"), null);
    assert.equal(
      await page.evaluate(() =>
        document.activeElement.getAttribute("aria-describedby"),
      ),
      "status-tooltip",
    );
    assert.equal(await tooltip.isVisible(), true);
    await page.locator('[data-hours="168"]').click();
    await ready();
    assert.equal(
      await page.locator('[data-hours="168"]').getAttribute("aria-pressed"),
      "true",
    );
    await page.locator('[data-hours="720"]').click();
    await ready();
    for (const width of [320, 390, 768, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      assert.equal(
        await page.evaluate(
          () => document.documentElement.scrollWidth > innerWidth,
        ),
        false,
        `Overflow at ${width}px`,
      );
      await page.locator(".segment").first().hover();
      await tooltip.waitFor();
      const bounds = await tooltip.boundingBox();
      assert.ok(
        bounds.x >= 0 &&
          bounds.x + bounds.width <= width &&
          bounds.y >= 0 &&
          bounds.y + bounds.height <= 900,
        `Tooltip outside viewport at ${width}px`,
      );
      await page.keyboard.press("Escape");
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator(".segment.down").first().tap();
    assert.equal(
      await tooltip.isVisible(),
      true,
      "Touch does not open custom tooltip",
    );
    await page.locator("h1").tap();
    assert.equal(
      await tooltip.isVisible(),
      false,
      "Outside tap does not dismiss tooltip",
    );
    data.services[0].status = "down";
    await refresh();
    assert.equal(await page.locator("h1").textContent(), "1 service offline");
    for (const service of data.services)
      service.last_check = new Date(Date.now() - 300000).toISOString();
    await refresh();
    assert.match(await page.locator("h1").textContent(), /not fully known/);
    assert.equal(await page.locator(".service-state.is-up").count(), 0);
    data = fixture();
    await refresh();
    failure = true;
    await refresh();
    assert.match(
      await page.locator("h1").textContent(),
      /could not be refreshed/,
    );
    assert.equal(
      await page.locator(".service").count(),
      3,
      "Lost last received history",
    );
    assert.equal(
      await page.locator(".service-state.is-up").count(),
      0,
      "API failure still presents current health as green",
    );
    await page.reload();
    await page.locator("#connection-notice").waitFor();
    assert.equal(
      await page.locator("h1").textContent(),
      "Current status unavailable.",
    );
    failure = false;
    data = fixture();
    data.services = [];
    data.events = [];
    await refresh();
    assert.match(await page.locator("h1").textContent(), /not fully known/);
    assert.match(await page.locator("#services").textContent(), /No services/);
    data = fixture();
    data.services[0].name = '<img src=x onerror="window.injected=true">';
    await refresh();
    assert.equal(await page.locator(".service img").count(), 0);
    assert.equal(await page.evaluate(() => window.injected), undefined);
    await page.locator("#event-sort").selectOption("recent");
    // Historical offsets must follow DST, not reuse today's local offset.
    data = fixture();
    data.events[0].started_at = "2026-11-01T07:30:00Z";
    data.events[0].ended_at = "2026-11-01T08:30:00Z";
    await refresh();
    await page.locator("#timezone").selectOption("America/Denver");
    await page.locator(".event").first().locator("summary").click();
    const banner = await page.locator(".event-range").first().textContent();
    assert.match(banner, /GMT-6/);
    assert.match(banner, /GMT-7/);
    assert.deepEqual(errors, []);
    console.log(
      "PASS: dark theme and contrast, uniform green/red bars, custom hover/focus/touch tooltips and viewport bounds, privacy, healthy/down/stale/empty/offline states, timeline keyboard controls, history persistence, 24h/7d/30d controls, local/UTC/DST, HTML escaping, 320/390/768/1440px layouts.",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
