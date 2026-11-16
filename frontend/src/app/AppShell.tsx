// Application shell (SPEC-400 §4.2 + SPEC-408 §4.1): nav from the route
// registry (home entry first, Lab/Topologies badges) + the guide link + the
// permanent journey wayfinding bar under the header + the routed region
// outlet. WS connection status surfaces here later (features own the stream
// instance; the shell stays registry-driven).
//
// Demo session bar (SPEC-408 §4.3/§7.4, ticket #99): the shell owns the demo
// period state as plain React state (zero new dependencies, zero global
// state library — callbacks flow down via DemoContext; the bar renders
// directly under the journey bar and stays mounted for the whole demo
// period). startDemo runs the §7.4 phase machine against the REAL backend;
// landing navigates to /monitor with the pre-anchored inspect_* deep link
// (absent when the locator honestly failed to parse); 「结束演示并清理」 =
// DELETE session (204) + local demo state clear; verify is never submitted
// by the orchestration (§4.3 — the user walks PASS themselves).
import { Suspense, useCallback, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router";
import { appRoutes } from "./routes";
import { GUIDE_URL } from "./journeySteps";
import { JourneyBar } from "./JourneyBar";
import { disposeSession, isApiError, stopSession } from "../api";
import { qk } from "../query/keys";
import {
  buildDemoLandingPath,
  initialDemoPhases,
  markDemoPhase,
  orchestrateDemoSession,
  runAndWait,
  type DemoSessionState,
} from "../features/monitor/demo/demoOrchestrate";
import { DemoContext } from "../features/monitor/demo/DemoSessionContext";
import { DemoSessionBar } from "../features/monitor/demo/DemoSessionBar";
import "./shell.css";

export function AppShell() {
  const [demo, setDemo] = useState<DemoSessionState | null>(null);
  const [rerunBusy, setRerunBusy] = useState(false);
  const [cleanupBusy, setCleanupBusy] = useState(false);
  const [rerunError, setRerunError] = useState<string | null>(null);
  const [cleanupError, setCleanupError] = useState<string | null>(null);
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();

  // Re-entry guard: one orchestration at a time (a second click while in
  // flight must never start a parallel demo).
  const startDemo = useCallback(() => {
    setDemo((current) => {
      if (current !== null && current.status === "orchestrating") return current;
      return { status: "orchestrating", phases: initialDemoPhases(), sessionId: null, scenarioTitle: null, inspectLocator: null };
    });
    void (async () => {
      try {
        const result = await orchestrateDemoSession((progress) => {
          setDemo((current) =>
            current === null
              ? current
              : { ...current, phases: progress.phases, sessionId: progress.sessionId },
          );
        });
        // land: the module computed the payload; the shell navigates + hosts
        // the bar and marks the row done (the honest hand-off point).
        const landedPhases = markDemoPhase(
          result.phases,
          "land",
          "done",
          result.inspectLocator === null
            ? "已落地 Monitor(预锚定解析缺省:不带 inspect_* 参数)"
            : `已落地 Monitor(预锚定 PID ${result.inspectLocator.pid} · packet ${result.inspectLocator.packet_index})`,
        );
        setDemo({
          status: "landed",
          phases: landedPhases,
          sessionId: result.sessionId,
          scenarioTitle: result.scenarioTitle,
          inspectLocator: result.inspectLocator,
        });
        navigate(buildDemoLandingPath(result.sessionId, result.inspectLocator));
      } catch {
        // stop in place: the failed phase row already carries the explicit
        // reason; the bar switches to the failed face (no landing, no fake
        // success) and a created session stays kept + cleanable.
        setDemo((current) => (current === null ? current : { ...current, status: "failed" }));
      }
    })();
  }, [navigate]);

  // 「再跑一个 Run」: one more empty-plan run on the frozen golden geometry —
  // the journal flows in real time on the tracked demo session.
  const rerunDemoRun = useCallback(async () => {
    const sessionId = demo?.sessionId ?? null;
    if (sessionId === null || rerunBusy) return;
    setRerunBusy(true);
    setRerunError(null);
    try {
      await runAndWait(sessionId, []);
      void queryClient.invalidateQueries({ queryKey: [...qk.snapshot(sessionId)] });
      void queryClient.invalidateQueries({ queryKey: [...qk.sessionRuns(sessionId)] });
    } catch (error) {
      setRerunError(isApiError(error) ? `${error.errorCode}: ${error.message}` : error instanceof Error ? error.message : String(error));
    } finally {
      setRerunBusy(false);
    }
  }, [demo?.sessionId, queryClient, rerunBusy]);

  // 「结束演示并清理」: the SPEC-200 §5 lifecycle chain — a RUNNING demo
  // session has no direct → disposed edge, so cleanup = stop (running →
  // stopping → stopped, bounded synchronous answer) THEN DELETE
  // /sessions/{id} (204, stopped → disposed) + local demo state clear. A
  // 409 on stop means the session already sits past the stop edge (a
  // previous cleanup attempt got at least as far) — hand it to the DELETE.
  // A 404 on the DELETE means the session is already gone server-side —
  // the cleanup goal holds. If the disposed session is the tracked one,
  // leave its scope (the guide seat is the honest post-dispose view).
  const cleanupDemo = useCallback(async () => {
    const sessionId = demo?.sessionId ?? null;
    if (sessionId === null || cleanupBusy) return;
    setCleanupBusy(true);
    setCleanupError(null);
    try {
      try {
        await stopSession(sessionId);
      } catch (error) {
        if (!(isApiError(error) && error.status === 409)) throw error;
      }
      try {
        await disposeSession(sessionId);
      } catch (error) {
        if (!(isApiError(error) && error.status === 404)) throw error;
      }
      setDemo(null);
      const tracked = new URLSearchParams(location.search).get("session");
      if (location.pathname === "/monitor" && tracked === sessionId) {
        navigate("/monitor");
      }
    } catch (error) {
      setCleanupError(isApiError(error) ? `${error.errorCode}: ${error.message}` : error instanceof Error ? error.message : String(error));
    } finally {
      setCleanupBusy(false);
    }
  }, [cleanupBusy, demo?.sessionId, location.pathname, location.search, navigate]);

  const demoController = useMemo(
    () => ({ startDemo, demoBusy: demo?.status === "orchestrating" }),
    [demo?.status, startDemo],
  );

  return (
    <div className="dvb-shell">
      <header className="dvb-shell-header">
        <span className="dvb-shell-title">DVB-Nexus</span>
        <nav aria-label="路由区" className="dvb-shell-nav">
          {appRoutes.map((route) => (
            <NavLink
              key={route.path}
              to={route.path}
              className={({ isActive }) => `dvb-nav-link${isActive ? " dvb-nav-link-active" : ""}`}
              data-testid={`nav-link-${route.path === "/" ? "home" : route.path.slice(1)}`}
            >
              {route.label}
              {route.badge ? (
                <span
                  className={`dvb-badge ${route.path === "/lab" ? "dvb-badge-info" : "dvb-badge-neutral"} dvb-nav-badge`}
                  data-testid={`nav-badge-${route.path === "/" ? "home" : route.path.slice(1)}`}
                >
                  {route.badge}
                </span>
              ) : null}
            </NavLink>
          ))}
        </nav>
        <a
          className="dvb-shell-guide"
          data-testid="shell-guide-link"
          href={GUIDE_URL}
          target="_blank"
          rel="noreferrer noopener"
        >
          查看使用指南 ↗
        </a>
      </header>
      <JourneyBar />
      <DemoContext.Provider value={demoController}>
        {demo !== null && (
          <DemoSessionBar
            demo={demo}
            rerunBusy={rerunBusy}
            cleanupBusy={cleanupBusy}
            rerunError={rerunError}
            cleanupError={cleanupError}
            onRerun={() => void rerunDemoRun()}
            onCleanup={() => void cleanupDemo()}
          />
        )}
        <main className="dvb-shell-main">
          <Suspense fallback={<div className="dvb-region-loading">加载中…</div>}>
            <Outlet />
          </Suspense>
        </main>
      </DemoContext.Provider>
    </div>
  );
}
