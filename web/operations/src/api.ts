export type Operator = {
  user_id: number;
  email: string;
  name: string;
  role: "platform_admin" | "support";
};

export type OperatorSession = {
  operator: Operator;
  csrf_token?: string;
  expires_at?: string;
};

export type WorkspaceSummary = {
  id: number;
  public_id: string;
  name: string;
  slug: string | null;
  plan_id: number | null;
  account_state: string | null;
  membership_count: number;
  grant_count: number;
  territory_count: number;
};

export type Membership = {
  id: number;
  user_id: number;
  role: string;
  email?: string;
  name?: string;
};

export type Grant = {
  id: number;
  source: string;
  profile: string;
  plan_key: string;
  status: string;
  scope: string;
  subject_user_id: number | null;
};

export type Territory = {
  id: number;
  name: string;
  state: string | null;
  market: string | null;
  asset_type: string | null;
};

export type ExternalAccount = {
  id: number;
  provider: string;
  external_account_id: string;
  subject_user_id: number | null;
  metadata: Record<string, unknown>;
};

export type WorkspaceDetail = {
  workspace: WorkspaceSummary;
  account: { state: string; reason: string | null } | null;
  memberships: Membership[];
  grants: Grant[];
  territories: Territory[];
  external_accounts: ExternalAccount[];
};

export type ProviderEvent = {
  id: number;
  provider: string;
  event_type: string;
  outcome: string;
  reason_code: string | null;
  occurred_at: string;
  duplicate_count: number;
  replayed_at: string | null;
};

export type AuditEvent = {
  id: number;
  actor_email: string;
  actor_name: string;
  action: string;
  workspace_public_id: string | null;
  target_type: string;
  target_id: string;
  reason_code: string;
  reason: string;
  before: unknown;
  after: unknown;
  created_at: string;
};

export type SourceRight = {
  source_id: string;
  owner: string;
  dataset: string;
  rights_state: string;
  hosted_cloud_allowed: boolean;
  evidence_status: string;
  enabled: boolean;
  required_proofs: string[];
};

export type StripeReconciliationReport = {
  provider: "stripe";
  mode: "test";
  complete: true;
  observed_at: string;
  discrepancy_count: number;
  results: Array<{
    subscription_id: string;
    action: string;
    outcome: string;
    reason_code: string | null;
  }>;
};

export class OperationsApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

type Json = Record<string, unknown>;

export class OperationsApi {
  private csrfToken: string | null = null;

  constructor(private readonly origin: string) {}

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await fetch(`${this.origin}${path}`, {
      ...init,
      credentials: "include",
      headers: {
        Accept: "application/json",
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...init.headers,
      },
    });
    const value = (await response.json().catch(() => ({}))) as Json;
    if (!response.ok) {
      const error = value.error as Json | undefined;
      throw new OperationsApiError(
        response.status,
        String(error?.code ?? "request_failed"),
        String(error?.message ?? "The operations request failed safely."),
      );
    }
    return value as T;
  }

  async exchange(clerkToken: string): Promise<OperatorSession> {
    const session = await this.request<OperatorSession>("/v1/operations/session", {
      method: "POST",
      headers: { Authorization: `Bearer ${clerkToken}` },
    });
    if (!session.csrf_token) throw new Error("Operator session omitted CSRF state");
    this.csrfToken = session.csrf_token;
    return session;
  }

  current(): Promise<OperatorSession> {
    return this.request<OperatorSession>("/v1/operations/session");
  }

  async logout(): Promise<void> {
    await this.mutate<{ revoked: boolean }>("/v1/operations/session", "DELETE");
    this.csrfToken = null;
  }

  searchWorkspaces(q: string): Promise<{ workspaces: WorkspaceSummary[] }> {
    return this.request(`/v1/operations/workspaces?${new URLSearchParams({ q, limit: "25" })}`);
  }

  getWorkspace(publicId: string): Promise<WorkspaceDetail> {
    return this.request(`/v1/operations/workspaces/${encodeURIComponent(publicId)}`);
  }

  setAccountState(
    publicId: string,
    state: string,
    reasonCode: string,
    reason: string,
  ): Promise<{ account: { state: string } }> {
    return this.mutate(
      `/v1/operations/workspaces/${encodeURIComponent(publicId)}/account-state`,
      "POST",
      { state, reason_code: reasonCode, reason },
    );
  }

  revokeGrant(
    publicId: string,
    grantId: number,
    reasonCode: string,
    reason: string,
  ): Promise<{ grant: Grant }> {
    return this.mutate(
      `/v1/operations/workspaces/${encodeURIComponent(publicId)}/grants/${grantId}`,
      "DELETE",
      { reason_code: reasonCode, reason },
    );
  }

  deleteTerritory(
    publicId: string,
    territoryId: number,
    reasonCode: string,
    reason: string,
  ): Promise<{ deleted: boolean }> {
    return this.mutate(
      `/v1/operations/workspaces/${encodeURIComponent(publicId)}/territories/${territoryId}`,
      "DELETE",
      { reason_code: reasonCode, reason },
    );
  }

  deleteExternalAccount(
    publicId: string,
    mappingId: number,
    reasonCode: string,
    reason: string,
  ): Promise<{ deleted: boolean }> {
    return this.mutate(
      `/v1/operations/workspaces/${encodeURIComponent(publicId)}/external-accounts/${mappingId}`,
      "DELETE",
      { reason_code: reasonCode, reason },
    );
  }

  quarantine(provider: string): Promise<{ events: ProviderEvent[] }> {
    return this.request(
      `/v1/operations/provider-events/quarantine?${new URLSearchParams({ provider, limit: "50" })}`,
    );
  }

  replay(
    id: number,
    reasonCode: string,
    reason: string,
  ): Promise<Record<string, unknown>> {
    return this.mutate(`/v1/operations/provider-events/${id}/replay`, "POST", {
      reason_code: reasonCode,
      reason,
    });
  }

  reconcileStripe(
    publicId: string,
    reasonCode: string,
    reason: string,
  ): Promise<StripeReconciliationReport> {
    return this.mutate(
      `/v1/operations/workspaces/${encodeURIComponent(publicId)}/stripe-reconcile`,
      "POST",
      { reason_code: reasonCode, reason },
    );
  }

  audit(workspaceId?: string): Promise<{ events: AuditEvent[] }> {
    const query = new URLSearchParams({ limit: "50" });
    if (workspaceId) query.set("workspace_id", workspaceId);
    return this.request(`/v1/operations/audit?${query}`);
  }

  sourceRights(): Promise<{ summary: Record<string, number>; sources: SourceRight[] }> {
    return this.request("/v1/operations/source-rights");
  }

  health(): Promise<Record<string, string | number>> {
    return this.request("/v1/operations/health");
  }

  private mutate<T>(
    path: string,
    method: "POST" | "PATCH" | "DELETE",
    body?: Json,
  ): Promise<T> {
    if (!this.csrfToken) {
      throw new OperationsApiError(403, "csrf_missing", "Operator session is not ready.");
    }
    return this.request(path, {
      method,
      headers: { "X-CSRF-Token": this.csrfToken },
      body: body ? JSON.stringify(body) : undefined,
    });
  }
}
