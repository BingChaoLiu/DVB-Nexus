// Shell smoke (SPEC-400 §7.3 file 1) — REAL AND GREEN AT THIS TICKET: SPA
// loads, three route regions navigable, and a session WebSocket reaches its
// ready frame through the same-origin proxy. This one test proves the full
// transport chain (uvicorn asgi entry + pump + preview proxy + WS hub).
import { expect, test } from "@playwright/test";
import { createStartedSession, subscribeAndWaitReady } from "./helpers/backend";

test("three route regions are navigable (AC-400-01)", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("link", { name: "Topologies" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Monitor" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Lab" })).toBeVisible();

  await page.getByRole("link", { name: "Topologies" }).click();
  await expect(page.getByRole("heading", { name: "Topologies" })).toBeVisible();

  await page.getByRole("link", { name: "Monitor" }).click();
  await expect(page.getByRole("heading", { name: "Monitor" })).toBeVisible();

  await page.getByRole("link", { name: "Lab" }).click();
  await expect(page.getByRole("heading", { name: "Lab" })).toBeVisible();
});

// Home foyer + journey wayfinding bar (SPEC-408 §4.1/§4.2, AC-408-01): `/` is
// a real foyer (no redirect), the bar is permanent and URL-derived, and the
// frozen §4.2 copy renders verbatim. Additive over the AC-400-01 smoke above.
test("home foyer renders the journey skeleton and the bar follows the URL (AC-408-01)", async ({ page }) => {
  await page.goto("/");

  // Nav: home entry first, module badges, guide link.
  await expect(page.getByTestId("nav-badge-lab")).toHaveText("主干");
  await expect(page.getByTestId("nav-badge-topologies")).toHaveText("进阶");
  const guide = page.getByTestId("shell-guide-link");
  await expect(guide).toHaveText("查看使用指南 ↗");
  await expect(guide).toHaveAttribute("href", /docs\/user-guide/);

  // Hero + CTA (§4.2 verbatim).
  await expect(page.getByTestId("home-hero-goal")).toHaveText(
    "目标：不看任何文档，30 分钟内独立走通八步闭环，拿到 PASS。",
  );
  const cta = page.getByTestId("home-cta-start");
  await expect(cta).toHaveText("从这里开始：选一个场景");
  await expect(cta).toHaveAttribute("href", "/lab");

  // Eight-step journey map + the Analyze gap annotation (§4.2 verbatim).
  await expect(page.getByTestId("home-journey-map")).toBeVisible();
  await expect(page.getByTestId("home-journey-step-analyze-gap")).toHaveText(
    "不可用（REST 冻结 501），旅程自动跳过",
  );

  // Three module cards + the Monitor demo placeholder (behavior is #99).
  await expect(page.getByTestId("home-card-lab")).toContainText("这是主干旅程所在：场景库列出五个场景，实验台走完八步。");
  await expect(page.getByTestId("home-card-monitor")).toContainText(
    "这是自由观测台（free observation deck），按 session 展示真实运行证据。",
  );
  await expect(page.getByTestId("home-monitor-demo-start")).toBeDisabled();
  await expect(page.getByTestId("home-card-topologies")).toContainText(
    "这是进阶工具：手工搭建与校验 MPEG-TS 拓扑。",
  );

  // Journey bar: eight nodes + position + disclaimer (§4.1 verbatim).
  for (const key of ["create", "generate", "inject", "analyze", "diagnose", "inspect", "recover", "verify"]) {
    await expect(page.getByTestId(`journey-node-${key}`)).toBeVisible();
  }
  await expect(page.getByTestId("journey-you-are")).toHaveText("你在：旅程起点");
  await expect(page.getByTestId("journey-disclaimer")).toHaveText(
    "旅程路标条只指示当前位置，不指示完成进度；通关判定只认修复后新 Run 的服务端三态判定。",
  );

  // The CTA leads into the Lab library and the bar follows the URL.
  await cta.click();
  await expect(page.getByRole("heading", { name: "Lab" })).toBeVisible();
  await expect(page.getByTestId("journey-you-are")).toHaveText("你在：Lab·场景库");
});

test("session WS subscribe reaches the ready frame through the proxy (SPEC-501 §4)", async ({ page, request }) => {
  // Navigate first: the WS URL derives from the page's location (same-origin
  // posture) — on about:blank there is no host and the URL would be malformed.
  await page.goto("/");
  const sessionId = await createStartedSession(request);
  const frame = await subscribeAndWaitReady(page, sessionId);
  expect(frame.type).toBe("ready");
  expect(typeof frame.replayed_from).toBe("number");
});
