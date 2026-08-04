import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import cssText from "./operations.css?raw";
import { OperationsConsole } from "./OperationsConsole";

const authState = vi.hoisted(() => ({
  isLoaded: true,
  isSignedIn: true,
  getToken: vi.fn(async () => "clerk-staff-token"),
  signOut: vi.fn(async () => undefined),
}));

vi.mock("@clerk/react", () => ({
  useAuth: () => ({
    isLoaded: authState.isLoaded,
    isSignedIn: authState.isSignedIn,
    getToken: authState.getToken,
  }),
  useClerk: () => ({ signOut: authState.signOut }),
  SignInButton: ({ children }: { children: React.ReactNode }) => children,
}));

const PLATFORM = "https://platform.example.test";

const admin = {
  user_id: 41,
  email: "operator@example.test",
  name: "Control Operator",
  role: "platform_admin",
};

const support = { ...admin, role: "support", name: "Support Reader" };

const summary = {
  id: 9,
  public_id: "ws_austin_buyer",
  name: "Austin Buyer",
  slug: "austin-buyer",
  plan_id: 3,
  account_state: "active",
  membership_count: 1,
  grant_count: 1,
  territory_count: 1,
};

const detail = {
  workspace: summary,
  account: { state: "active", reason: null },
  memberships: [{ id: 1, user_id: 8, role: "owner", email: "buyer@example.test", name: "Austin Buyer" }],
  grants: [{ id: 5, source: "manual", profile: "full_operator", plan_key: "operator", status: "active", scope: "subject", subject_user_id: 8 }],
  territories: [{ id: 7, name: "Austin", state: "TX", market: "Austin", asset_type: null }],
  external_accounts: [{ id: 11, provider: "stripe", external_account_id: "cus_test_123", subject_user_id: 8, metadata: {} }],
};

function response(value: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  }));
}

function installApi(operator = admin) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const method = init?.method ?? "GET";
    if (url.pathname === "/v1/operations/session" && method === "POST") {
      return response({ operator, csrf_token: "mcr_ops_csrf_test", expires_at: "2026-08-04T12:30:00Z" }, 201);
    }
    if (url.pathname === "/v1/operations/health") {
      return response({ status: "ready", database: "reachable", workspaces: 12, quarantined_provider_events: 2 });
    }
    if (url.pathname === "/v1/operations/workspaces" && method === "GET") {
      return response({ workspaces: [summary], next_cursor: null });
    }
    if (url.pathname === `/v1/operations/workspaces/${summary.public_id}` && method === "GET") {
      return response(detail);
    }
    if (url.pathname.endsWith("/account-state") && method === "POST") {
      return response({ account: { state: "suspended" } });
    }
    if (url.pathname === "/v1/operations/source-rights") {
      return response({
        summary: { total: 1, hosted_allowed: 0, hosted_blocked: 1 },
        sources: [{ source_id: "listing.loopnet", owner: "LoopNet", dataset: "listings", rights_state: "prohibited", hosted_cloud_allowed: false, evidence_status: "certified", enabled: false, required_proofs: [] }],
      });
    }
    if (url.pathname === "/v1/operations/audit") {
      return response({ events: [{ id: 1, actor_email: admin.email, actor_name: admin.name, action: "account.state.update", workspace_public_id: summary.public_id, target_type: "account", target_id: summary.public_id, reason_code: "support_resolution", reason: "Approved runbook action.", before: { state: "active" }, after: { state: "suspended" }, created_at: "2026-08-04T12:00:00Z" }] });
    }
    if (url.pathname === "/v1/operations/provider-events/quarantine") {
      return response({ events: [], next_cursor: null });
    }
    throw new Error(`Unhandled request: ${method} ${url.pathname}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

async function ready() {
  expect(await screen.findByText("Control Operator")).toBeInTheDocument();
}

async function openWorkspace() {
  fireEvent.change(screen.getByLabelText("Workspace lookup"), { target: { value: "Austin" } });
  fireEvent.click(screen.getByRole("button", { name: "Search workspaces" }));
  fireEvent.click(await screen.findByRole("button", { name: /Austin Buyer/ }));
  expect(await screen.findByRole("heading", { name: "Austin Buyer" })).toBeInTheDocument();
}

beforeEach(() => {
  authState.isLoaded = true;
  authState.isSignedIn = true;
  authState.getToken.mockClear();
  authState.signOut.mockClear();
  vi.unstubAllGlobals();
});

afterEach(() => cleanup());

describe("OperationsConsole", () => {
  it("exchanges Clerk identity for an opaque operator session and renders live authority", async () => {
    const fetchMock = installApi();
    render(<OperationsConsole platformOrigin={PLATFORM} />);
    await ready();

    const exchange = fetchMock.mock.calls.find(([input, init]) =>
      String(input).endsWith("/v1/operations/session") && init?.method === "POST",
    );
    expect(exchange?.[1]).toMatchObject({
      credentials: "include",
      headers: expect.objectContaining({ Authorization: "Bearer clerk-staff-token" }),
    });
    expect(document.body.textContent).not.toContain("clerk-staff-token");
    expect(screen.getByText("platform administrator")).toBeInTheDocument();
  });

  it("searches bounded workspaces and renders the server-owned control record", async () => {
    installApi();
    render(<OperationsConsole platformOrigin={PLATFORM} />);
    await ready();
    await openWorkspace();

    expect(screen.getByText("full_operator / manual")).toBeInTheDocument();
    expect(screen.getByText("cus_test_123")).toBeInTheDocument();
    expect(screen.getByText("Austin, TX")).toBeInTheDocument();
  });

  it("requires a reason before mutation and sends the in-memory CSRF token", async () => {
    const fetchMock = installApi();
    render(<OperationsConsole platformOrigin={PLATFORM} />);
    await ready();
    await openWorkspace();

    const apply = screen.getByRole("button", { name: "Apply state" });
    expect(apply).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Operator reason"), {
      target: { value: "Customer requested a documented suspension." },
    });
    fireEvent.change(screen.getByLabelText("Account state"), { target: { value: "suspended" } });
    fireEvent.click(apply);

    await screen.findByText("Account state updated and audited.");
    const mutation = fetchMock.mock.calls.find(([input, init]) =>
      String(input).endsWith("/account-state") && init?.method === "POST",
    );
    expect(mutation?.[1]?.headers).toMatchObject({ "X-CSRF-Token": "mcr_ops_csrf_test" });
    expect(JSON.parse(String(mutation?.[1]?.body))).toMatchObject({
      state: "suspended",
      reason_code: "support_resolution",
    });
  });

  it("keeps support read-only while preserving approved operational views", async () => {
    installApi(support);
    render(<OperationsConsole platformOrigin={PLATFORM} />);
    expect(await screen.findByText("read-only support")).toBeInTheDocument();
    await openWorkspace();

    expect(screen.getByRole("heading", { name: "Support review only" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Apply state" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Revoke grant/ })).not.toBeInTheDocument();
  });

  it("loads source-rights and append-only audit views through native buttons", async () => {
    installApi();
    render(<OperationsConsole platformOrigin={PLATFORM} />);
    await ready();

    const rightsButton = screen.getByRole("button", { name: /Source rights/ });
    expect(rightsButton.tagName).toBe("BUTTON");
    fireEvent.click(rightsButton);
    expect(await screen.findByText("listing.loopnet")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Audit journal/ }));
    expect(await screen.findByText("account.state.update")).toBeInTheDocument();
    expect(screen.getByText(/Approved runbook action/)).toBeInTheDocument();
  });

  it("contains no customer portal, billing, or deal-management surface", async () => {
    installApi();
    render(<OperationsConsole platformOrigin={PLATFORM} />);
    await ready();
    const visible = document.body.textContent?.toLowerCase() ?? "";
    expect(visible).not.toContain("customer portal");
    expect(visible).not.toContain("pricing");
    expect(visible).not.toContain("find deals");
    expect(visible).not.toContain("billing portal");
  });

  it("keeps content visible by default and respects reduced motion", () => {
    expect(cssText).toContain("@media (prefers-reduced-motion: reduce)");
    expect(cssText).not.toMatch(/opacity:\s*0(?:[;}])/);
    expect(cssText).not.toContain("translateY(");
  });
});
