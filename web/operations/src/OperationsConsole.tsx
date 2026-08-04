import { SignInButton, useAuth, useClerk } from "@clerk/react";
import Lock from "reicon/icons/Lock";
import Refresh from "reicon/icons/Refresh";
import Search from "reicon/icons/Search";
import Trash from "reicon/icons/Trash";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AuditEvent,
  OperationsApi,
  OperationsApiError,
  Operator,
  ProviderEvent,
  SkoolReconciliationReport,
  SkoolStatus,
  SourceRight,
  StripeReconciliationReport,
  WorkspaceDetail,
  WorkspaceSummary,
} from "./api";
import { Reicon } from "./Reicon";
import { SurveyLedger } from "./SurveyLedger";
import "./operations.css";

type View = "workspace" | "providers" | "rights" | "audit" | "health";
type Notice = { kind: "error" | "success"; text: string } | null;

const REASON_CODES = [
  "customer_request",
  "billing_correction",
  "entitlement_correction",
  "security_response",
  "support_resolution",
  "data_correction",
] as const;

function errorText(error: unknown): string {
  if (error instanceof OperationsApiError) return `${error.code}: ${error.message}`;
  if (error instanceof Error) return error.message;
  return "The operation failed safely.";
}

function FieldLedger({ detail }: { detail: WorkspaceDetail }) {
  return (
    <dl className="field-ledger">
      <div><dt>Workspace</dt><dd>{detail.workspace.public_id}</dd></div>
      <div><dt>Account</dt><dd>{detail.account?.state ?? "unrecorded"}</dd></div>
      <div><dt>Plan record</dt><dd>{detail.workspace.plan_id ?? "none"}</dd></div>
      <div><dt>Members</dt><dd>{detail.memberships.length}</dd></div>
      <div><dt>Grants</dt><dd>{detail.grants.length}</dd></div>
      <div><dt>Territories</dt><dd>{detail.territories.length}</dd></div>
    </dl>
  );
}

function JsonDiff({ value }: { value: unknown }) {
  if (value == null) return <span className="empty-value">none</span>;
  return <pre>{JSON.stringify(value, null, 2)}</pre>;
}

function currentStateTemplate(communityId = "community_id"): string {
  return JSON.stringify({
    community_id: communityId,
    source: "operator_members_review",
    observed_at: new Date().toISOString(),
    confidence: "unverified",
    complete: false,
    members: [],
  }, null, 2);
}

function evidenceAge(seconds: number | null): string {
  if (seconds == null) return "not recorded";
  if (seconds < 60) return `${seconds} seconds`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} minutes`;
  return `${Math.floor(seconds / 3600)} hours`;
}

export function OperationsConsole({ platformOrigin }: { platformOrigin: string }) {
  const { isLoaded, isSignedIn, getToken } = useAuth();
  const clerk = useClerk();
  const api = useMemo(() => new OperationsApi(platformOrigin), [platformOrigin]);
  const exchangeStarted = useRef(false);
  const [operator, setOperator] = useState<Operator | null>(null);
  const [view, setView] = useState<View>("workspace");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);
  const [health, setHealth] = useState<Record<string, string | number>>({
    status: "pending",
    workspaces: 0,
    quarantined_provider_events: 0,
  });

  const [query, setQuery] = useState("");
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [detail, setDetail] = useState<WorkspaceDetail | null>(null);
  const [accountState, setAccountState] = useState("active");
  const [reasonCode, setReasonCode] = useState("support_resolution");
  const [reason, setReason] = useState("");

  const [provider, setProvider] = useState("stripe");
  const [events, setEvents] = useState<ProviderEvent[]>([]);
  const [rights, setRights] = useState<SourceRight[]>([]);
  const [audit, setAudit] = useState<AuditEvent[]>([]);
  const [stripeReport, setStripeReport] = useState<StripeReconciliationReport | null>(null);
  const [skoolStatus, setSkoolStatus] = useState<SkoolStatus | null>(null);
  const [skoolReport, setSkoolReport] = useState<SkoolReconciliationReport | null>(null);
  const [skoolSubject, setSkoolSubject] = useState("");
  const [skoolTier, setSkoolTier] = useState("");
  const [skoolTask, setSkoolTask] = useState("");
  const [skoolMemberId, setSkoolMemberId] = useState("");
  const [skoolCompletionSource, setSkoolCompletionSource] = useState<"manual_admin_invite" | "zapier_invite">("manual_admin_invite");
  const [skoolArtifact, setSkoolArtifact] = useState(currentStateTemplate());

  const loadHealth = useCallback(async () => {
    const next = await api.health();
    setHealth(next);
  }, [api]);

  useEffect(() => {
    if (!isLoaded || !isSignedIn || exchangeStarted.current) return;
    exchangeStarted.current = true;
    setBusy(true);
    void getToken()
      .then((token) => {
        if (!token) throw new Error("Clerk did not issue a staff session token.");
        return api.exchange(token);
      })
      .then(async (session) => {
        setOperator(session.operator);
        await loadHealth();
      })
      .catch((error: unknown) => {
        setNotice({ kind: "error", text: errorText(error) });
        exchangeStarted.current = false;
      })
      .finally(() => setBusy(false));
  }, [api, getToken, isLoaded, isSignedIn, loadHealth]);

  useEffect(() => {
    if (isLoaded && !isSignedIn) {
      exchangeStarted.current = false;
      setOperator(null);
    }
  }, [isLoaded, isSignedIn]);

  const run = useCallback(async (task: () => Promise<void>, success?: string) => {
    setBusy(true);
    setNotice(null);
    try {
      await task();
      if (success) setNotice({ kind: "success", text: success });
    } catch (error) {
      setNotice({ kind: "error", text: errorText(error) });
    } finally {
      setBusy(false);
    }
  }, []);

  const search = (event: FormEvent) => {
    event.preventDefault();
    void run(async () => {
      const result = await api.searchWorkspaces(query);
      setWorkspaces(result.workspaces);
      setDetail(null);
    });
  };

  const openWorkspace = (publicId: string) => {
    void run(async () => {
      const [result, skool] = await Promise.all([
        api.getWorkspace(publicId),
        api.skoolStatus(publicId),
      ]);
      setDetail(result);
      setSkoolStatus(skool);
      setAccountState(result.account?.state ?? "active");
      setSkoolSubject(String(result.memberships[0]?.user_id ?? ""));
      setSkoolTier(skool.available_tiers[0]?.tier ?? "");
      const pending = skool.join_tasks.find((task) => task.state === "pending");
      setSkoolTask(String(pending?.id ?? ""));
      setSkoolArtifact(currentStateTemplate(skool.available_tiers[0]?.community_id));
    });
  };

  const reloadWorkspace = async () => {
    if (!detail) return;
    const [workspace, skool] = await Promise.all([
      api.getWorkspace(detail.workspace.public_id),
      api.skoolStatus(detail.workspace.public_id),
    ]);
    setDetail(workspace);
    setSkoolStatus(skool);
    const pending = skool.join_tasks.find((task) => task.state === "pending");
    setSkoolTask(String(pending?.id ?? ""));
  };

  const validReason = reason.trim().length >= 8 && reasonCode.length > 0;
  const mayMutate = operator?.role === "platform_admin";

  const changeAccountState = () => {
    if (!detail || !validReason) return;
    void run(async () => {
      await api.setAccountState(detail.workspace.public_id, accountState, reasonCode, reason);
      await reloadWorkspace();
      setReason("");
    }, "Account state updated and audited.");
  };

  const removeTerritory = (id: number) => {
    if (!detail || !validReason) return;
    void run(async () => {
      await api.deleteTerritory(detail.workspace.public_id, id, reasonCode, reason);
      await reloadWorkspace();
      setReason("");
    }, "Territory removed and audited.");
  };

  const revokeGrant = (id: number) => {
    if (!detail || !validReason) return;
    void run(async () => {
      await api.revokeGrant(detail.workspace.public_id, id, reasonCode, reason);
      await reloadWorkspace();
      setReason("");
    }, "Grant revoked and audited.");
  };

  const removeMapping = (id: number) => {
    if (!detail || !validReason) return;
    void run(async () => {
      await api.deleteExternalAccount(detail.workspace.public_id, id, reasonCode, reason);
      await reloadWorkspace();
      setReason("");
    }, "Provider mapping removed and audited.");
  };

  const reconcileStripe = () => {
    if (!detail || !validReason) return;
    void run(async () => {
      const report = await api.reconcileStripe(
        detail.workspace.public_id,
        reasonCode,
        reason,
      );
      setStripeReport(report);
      await reloadWorkspace();
      setReason("");
    }, "Stripe test state reconciled and audited.");
  };

  const createSkoolJoinTask = () => {
    if (!detail || !validReason || !skoolSubject || !skoolTier) return;
    void run(async () => {
      await api.createSkoolJoinTask(
        detail.workspace.public_id,
        Number(skoolSubject),
        skoolTier,
        reasonCode,
        reason,
      );
      await reloadWorkspace();
      setReason("");
    }, "Skool join task created. Complete the supported invite outside this runtime.");
  };

  const completeSkoolJoinTask = () => {
    if (!detail || !validReason || !skoolTask || !skoolMemberId.trim()) return;
    void run(async () => {
      await api.completeSkoolJoinTask(
        detail.workspace.public_id,
        Number(skoolTask),
        skoolMemberId.trim(),
        skoolCompletionSource,
        reasonCode,
        reason,
      );
      await reloadWorkspace();
      setSkoolMemberId("");
      setReason("");
    }, "Skool member identity bound. Access still requires trusted current-state evidence.");
  };

  const reconcileSkool = () => {
    if (!detail || !validReason) return;
    void run(async () => {
      let artifact: Record<string, unknown>;
      try {
        artifact = JSON.parse(skoolArtifact) as Record<string, unknown>;
      } catch {
        throw new Error("Skool current-state evidence must be valid JSON.");
      }
      const report = await api.reconcileSkool(
        detail.workspace.public_id,
        artifact,
        reasonCode,
        reason,
      );
      setSkoolReport(report);
      await reloadWorkspace();
      setReason("");
    }, "Skool current-state evidence reconciled and audited.");
  };

  const revokeSkool = (mappingId: number) => {
    if (!detail || !validReason) return;
    void run(async () => {
      await api.revokeSkool(
        detail.workspace.public_id,
        mappingId,
        reasonCode,
        reason,
      );
      await reloadWorkspace();
      setReason("");
    }, "Skool authority and affected OAuth sessions revoked.");
  };

  const loadProviders = (selected = provider) => {
    setProvider(selected);
    void run(async () => setEvents((await api.quarantine(selected)).events));
  };

  const replay = (id: number) => {
    if (!validReason) return;
    void run(async () => {
      await api.replay(id, reasonCode, reason);
      setEvents((await api.quarantine(provider)).events);
      setReason("");
    }, "Provider event replayed and audited.");
  };

  const showView = (next: View) => {
    setView(next);
    setNotice(null);
    if (next === "providers") loadProviders();
    if (next === "rights") void run(async () => setRights((await api.sourceRights()).sources));
    if (next === "audit") void run(async () => setAudit((await api.audit(detail?.workspace.public_id)).events));
    if (next === "health") void run(loadHealth);
  };

  const logout = () => {
    void run(async () => {
      await api.logout();
      await clerk.signOut();
      setOperator(null);
      exchangeStarted.current = false;
    });
  };

  if (!isLoaded) {
    return <main className="operator-gate"><p role="status">Loading staff identity boundary.</p></main>;
  }

  if (!isSignedIn) {
    return (
      <main className="operator-gate">
        <svg className="gate-mark" viewBox="0 0 84 84" aria-hidden="true">
          <path d="M9 67V17l18-8 15 17L57 9l18 8v50L57 75 42 58 27 75 9 67Z" />
          <path d="m27 9 15 49L57 9" />
        </svg>
        <h1>Internal operations only.</h1>
        <p>Clerk identity is the first boundary. Live operator authority is checked again on every request.</p>
        <SignInButton mode="modal">
          <button className="action action--primary" type="button">Sign in as operator</button>
        </SignInButton>
      </main>
    );
  }

  if (!operator) {
    return (
      <main className="operator-gate">
        <Reicon icon={Lock} size={30} />
        <h1>{busy ? "Checking live operator authority." : "Operator access denied."}</h1>
        <p>{notice?.text ?? "No internal control-plane session has been issued."}</p>
      </main>
    );
  }

  return (
    <main className="operations-shell">
      <header className="operations-masthead">
        <div className="operations-brand">
          <svg className="operations-mark" viewBox="0 0 42 42" aria-hidden="true">
            <path d="M4 33V9l9-5 8 9 8-9 9 5v24l-9 5-8-9-8 9-9-5Z" />
            <path d="m13 4 8 25 8-25" />
          </svg>
          <div><strong>MedawarCRE</strong><span>operations control ledger</span></div>
        </div>
        <div className="operator-identity">
          <span>{operator.name}</span>
          <span>{operator.role === "support" ? "read-only support" : "platform administrator"}</span>
          <button className="text-action" type="button" onClick={logout}>Sign out</button>
        </div>
      </header>

      <nav className="ledger-index" aria-label="Operations sections">
        {([
          ["workspace", "Workspace register"],
          ["providers", "Provider quarantine"],
          ["rights", "Source rights"],
          ["audit", "Audit journal"],
          ["health", "Runtime bearing"],
        ] as [View, string][]).map(([key, label], index) => (
          <button
            key={key}
            type="button"
            aria-current={view === key ? "page" : undefined}
            onClick={() => showView(key)}
          >
            <span>{String(index + 1).padStart(2, "0")}</span>{label}
          </button>
        ))}
      </nav>

      <div className="operations-stage">
        <aside className="platform-bearing">
          <SurveyLedger
            workspaceCount={Number(health.workspaces ?? 0)}
            quarantineCount={Number(health.quarantined_provider_events ?? 0)}
            status={String(health.status ?? "unknown")}
          />
          <p>Authority is re-read from server-owned records. Every mutation requires a reason and leaves an append-only audit event.</p>
        </aside>

        <section className="ledger-sheet" aria-busy={busy}>
          {notice && <p className={`notice notice--${notice.kind}`} role={notice.kind === "error" ? "alert" : "status"}>{notice.text}</p>}
          {view === "workspace" && (
            <>
              <div className="sheet-heading">
                <h1>Workspace register</h1>
                <p>Exact public ID, name, slug, or member email. Results are bounded to 25.</p>
              </div>
              <form className="workspace-search" onSubmit={search}>
                <label htmlFor="workspace-query">Workspace lookup</label>
                <div>
                  <input id="workspace-query" value={query} minLength={2} maxLength={128} onChange={(event) => setQuery(event.target.value)} placeholder="ws_… or operator@example.com" />
                  <button className="icon-action" type="submit" aria-label="Search workspaces" disabled={busy || query.trim().length < 2}><Reicon icon={Search} /></button>
                </div>
              </form>

              {!detail && workspaces.length > 0 && (
                <div className="result-register" aria-label="Workspace search results">
                  {workspaces.map((workspace) => (
                    <button key={workspace.public_id} type="button" onClick={() => openWorkspace(workspace.public_id)}>
                      <strong>{workspace.name}</strong>
                      <span>{workspace.public_id}</span>
                      <span>{workspace.account_state ?? "unrecorded"}</span>
                    </button>
                  ))}
                </div>
              )}

              {detail && (
                <div className="workspace-record">
                  <div className="workspace-record__title">
                    <div><button className="text-action" type="button" onClick={() => setDetail(null)}>Back to register</button><h2>{detail.workspace.name}</h2></div>
                    <button className="icon-action" type="button" aria-label="Refresh workspace" onClick={() => void run(reloadWorkspace)}><Reicon icon={Refresh} /></button>
                  </div>
                  <FieldLedger detail={detail} />

                  <div className="record-grid">
                    <section><h3>Members</h3>{detail.memberships.map((item) => <p className="record-row" key={item.id}><span>{item.name ?? item.email ?? `User ${item.user_id}`}</span><strong>{item.role}</strong></p>)}</section>
                    <section><h3>Access grants</h3>{detail.grants.map((item) => <p className="record-row" key={item.id}><span>{item.profile} / {item.source}</span><strong>{item.status}</strong>{mayMutate && item.status !== "revoked" && <button type="button" aria-label={`Revoke grant ${item.id}`} disabled={!validReason || busy} onClick={() => revokeGrant(item.id)}><Reicon icon={Trash} size={15} /></button>}</p>)}</section>
                    <section><h3>Territories</h3>{detail.territories.length === 0 ? <p className="empty-value">No territory records.</p> : detail.territories.map((item) => <p className="record-row" key={item.id}><span>{item.name}{item.state ? `, ${item.state}` : ""}</span><strong>{item.asset_type ?? "all assets"}</strong>{mayMutate && <button type="button" aria-label={`Delete territory ${item.name}`} disabled={!validReason || busy} onClick={() => removeTerritory(item.id)}><Reicon icon={Trash} size={15} /></button>}</p>)}</section>
                    <section><h3>Provider mappings</h3>{detail.external_accounts.length === 0 ? <p className="empty-value">No provider mappings.</p> : detail.external_accounts.map((item) => <p className="record-row" key={item.id}><span>{item.provider}</span><strong>{item.external_account_id}</strong>{mayMutate && <button type="button" aria-label={`Delete ${item.provider} mapping`} disabled={!validReason || busy} onClick={() => removeMapping(item.id)}><Reicon icon={Trash} size={15} /></button>}</p>)}</section>
                  </div>

                  <section className="mutation-docket" aria-label="Audited control action">
                    <h3>{mayMutate ? "Audited control action" : "Support review only"}</h3>
                    <p>{mayMutate ? "The reason below applies to the next control you invoke." : "Support can inspect these records but cannot change them."}</p>
                    <div className="reason-fields">
                      <label>Reason code<select value={reasonCode} disabled={!mayMutate} onChange={(event) => setReasonCode(event.target.value)}>{REASON_CODES.map((item) => <option key={item}>{item}</option>)}</select></label>
                      <label>Operator reason<textarea value={reason} disabled={!mayMutate} minLength={8} maxLength={500} onChange={(event) => setReason(event.target.value)} placeholder="Describe the evidence and requested result." /></label>
                    </div>
                    {mayMutate && <div className="account-action"><label>Account state<select value={accountState} onChange={(event) => setAccountState(event.target.value)}><option>active</option><option>past_due</option><option>suspended</option><option>canceled</option></select></label><button className="action" type="button" disabled={!validReason || busy} onClick={changeAccountState}>Apply state</button>{detail.external_accounts.some((item) => item.provider === "stripe") && <button className="action" type="button" disabled={!validReason || busy} onClick={reconcileStripe}>Reconcile Stripe test state</button>}</div>}
                    {stripeReport && <p className="reconciliation-result" role="status">Stripe test reconciliation checked a complete subscription list at {stripeReport.observed_at}. Discrepancies observed: <strong>{stripeReport.discrepancy_count}</strong>.</p>}
                  </section>

                  {skoolStatus && (
                    <section className="skool-ledger" aria-label="Skool lifecycle">
                      <div className="skool-ledger__heading">
                        <h3>Skool evidence ledger</h3>
                        <p>{skoolStatus.official_constraint}</p>
                      </div>
                      <dl className="skool-bearing">
                        <div><dt>Current-state certainty</dt><dd>{skoolStatus.reconciliation.certainty}</dd></div>
                        <div><dt>Evidence age</dt><dd>{evidenceAge(skoolStatus.reconciliation.age_seconds)}</dd></div>
                        <div><dt>Reason</dt><dd>{skoolStatus.reconciliation.reason_code}</dd></div>
                        <div><dt>Conflicts</dt><dd>{skoolStatus.reconciliation.conflict_count ?? 0}</dd></div>
                      </dl>

                      {skoolStatus.available_tiers.length === 0 ? (
                        <p className="empty-value">No server-owned Skool tier mapping is configured. Join and reconciliation controls remain closed.</p>
                      ) : (
                        <div className="skool-controls">
                          <fieldset>
                            <legend>Create a supported join task</legend>
                            <label>Workspace member<select value={skoolSubject} disabled={!mayMutate} onChange={(event) => setSkoolSubject(event.target.value)}>{detail.memberships.map((item) => <option key={item.id} value={item.user_id}>{item.name ?? item.email ?? `User ${item.user_id}`}</option>)}</select></label>
                            <label>Mapped tier<select value={skoolTier} disabled={!mayMutate} onChange={(event) => setSkoolTier(event.target.value)}>{skoolStatus.available_tiers.map((item) => <option key={item.tier} value={item.tier}>{item.tier} / {item.profile}</option>)}</select></label>
                            {mayMutate && <button className="action" type="button" disabled={!validReason || busy || !skoolSubject || !skoolTier} onClick={createSkoolJoinTask}>Create join task</button>}
                          </fieldset>

                          <fieldset>
                            <legend>Record a completed invite</legend>
                            <label>Pending task<select value={skoolTask} disabled={!mayMutate} onChange={(event) => setSkoolTask(event.target.value)}><option value="">Select a pending task</option>{skoolStatus.join_tasks.filter((task) => task.state === "pending").map((task) => <option key={task.id} value={task.id}>#{task.id} {task.member_name} / {task.tier}</option>)}</select></label>
                            <label>Exact Skool member ID<input value={skoolMemberId} disabled={!mayMutate} onChange={(event) => setSkoolMemberId(event.target.value)} placeholder="member identifier from Skool" /></label>
                            <label>Invite path<select value={skoolCompletionSource} disabled={!mayMutate} onChange={(event) => setSkoolCompletionSource(event.target.value as "manual_admin_invite" | "zapier_invite")}><option value="manual_admin_invite">Skool Admin Invite</option><option value="zapier_invite">Zapier Invite</option></select></label>
                            {mayMutate && <button className="action" type="button" disabled={!validReason || busy || !skoolTask || !skoolMemberId.trim()} onClick={completeSkoolJoinTask}>Record joined member</button>}
                          </fieldset>

                          <fieldset className="skool-evidence">
                            <legend>Reconcile current members</legend>
                            <label>Timestamped review artifact<textarea value={skoolArtifact} disabled={!mayMutate} spellCheck={false} onChange={(event) => setSkoolArtifact(event.target.value)} /></label>
                            <p>Use a complete, confirmed review only when every current member in this community was checked. Stale, partial, or unverified evidence cannot grant access.</p>
                            {mayMutate && <button className="action" type="button" disabled={!validReason || busy} onClick={reconcileSkool}>Reconcile evidence</button>}
                          </fieldset>
                        </div>
                      )}

                      <div className="skool-mappings">
                        <h4>Bound members and manual revocation</h4>
                        {skoolStatus.mappings.length === 0 ? <p className="empty-value">No Skool member identities are bound.</p> : skoolStatus.mappings.map((mapping) => (
                          <article key={mapping.id}>
                            <div><strong>{mapping.member_name}</strong><span>{mapping.member_email}</span></div>
                            <div><span>{mapping.external_member_id}</span><strong>{mapping.grant_status}</strong></div>
                            {mayMutate && mapping.grant_status !== "revoked" && <button className="action" type="button" disabled={!validReason || busy} onClick={() => revokeSkool(mapping.id)}>Revoke Skool authority</button>}
                          </article>
                        ))}
                      </div>
                      {skoolReport && <p className="reconciliation-result" role="status">Skool evidence is {skoolReport.certainty}. Mapped members: <strong>{skoolReport.mapped_member_count}</strong>. Conflicts: <strong>{skoolReport.conflict_count}</strong>.</p>}
                    </section>
                  )}
                </div>
              )}
            </>
          )}

          {view === "providers" && (
            <>
              <div className="sheet-heading"><h1>Provider quarantine</h1><p>Payload-free event metadata. Queue reads and replays are audited.</p></div>
              <div className="provider-selector" aria-label="Provider filter">
                {['stripe', 'skool'].map((item) => <button type="button" key={item} aria-pressed={provider === item} onClick={() => loadProviders(item)}>{item}</button>)}
                <button className="icon-action" type="button" aria-label="Refresh provider queue" onClick={() => loadProviders()}><Reicon icon={Refresh} /></button>
              </div>
              <div className="reason-fields reason-fields--provider">
                <label>Reason code<select value={reasonCode} disabled={!mayMutate} onChange={(event) => setReasonCode(event.target.value)}>{REASON_CODES.map((item) => <option key={item}>{item}</option>)}</select></label>
                <label>Replay reason<textarea value={reason} disabled={!mayMutate} onChange={(event) => setReason(event.target.value)} placeholder="State the evidence for replay." /></label>
              </div>
              <div className="event-register">{events.length === 0 ? <p className="empty-value">No quarantined events for {provider}.</p> : events.map((item) => <article key={item.id}><div><strong>#{item.id} {item.event_type}</strong><span>{item.reason_code ?? "no reason code"} / {item.occurred_at}</span></div><span>{item.outcome}</span>{mayMutate && <button className="action" type="button" disabled={!validReason || busy} onClick={() => replay(item.id)}>Replay</button>}</article>)}</div>
            </>
          )}

          {view === "rights" && (
            <><div className="sheet-heading"><h1>Source rights</h1><p>Hosted access is allowed only where certified evidence and the runtime toggle agree.</p></div><div className="rights-register">{rights.map((item) => <article key={item.source_id}><strong>{item.source_id}</strong><span>{item.dataset}</span><span>{item.rights_state}</span><span className={item.hosted_cloud_allowed && item.enabled ? "status-ok" : "status-blocked"}>{item.hosted_cloud_allowed && item.enabled ? "hosted enabled" : "hosted blocked"}</span></article>)}</div></>
          )}

          {view === "audit" && (
            <><div className="sheet-heading"><h1>Audit journal</h1><p>Actor, target, reason, before, and after. Entries are append-only.</p></div><div className="audit-register">{audit.map((item) => <article key={item.id}><header><strong>{item.action}</strong><span>{item.created_at}</span></header><p>{item.actor_email} / {item.reason_code}</p><p>{item.target_type} {item.target_id}: {item.reason}</p><details><summary>Before and after</summary><div className="audit-diff"><JsonDiff value={item.before} /><JsonDiff value={item.after} /></div></details></article>)}</div></>
          )}

          {view === "health" && (
            <><div className="sheet-heading"><h1>Runtime bearing</h1><p>Private control-plane health. This is not a public service status page.</p></div><dl className="health-register">{Object.entries(health).map(([key, value]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{value}</dd></div>)}</dl></>
          )}
        </section>
      </div>
    </main>
  );
}
