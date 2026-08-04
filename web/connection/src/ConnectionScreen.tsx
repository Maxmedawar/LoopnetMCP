import { SignInButton, useAuth } from "@clerk/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "./connection.css";

type ScreenState =
  | "signed-out"
  | "connecting"
  | "confirm"
  | "failed"
  | "review"
  | "blocked"
  | "cancelled";

type AuthorizationSummary = {
  client_name: string;
  redirect_origin: string;
  scopes: string[];
  workspace_id?: string;
};

type ConnectionResponse = {
  connection: {
    status: "ready" | "workspace_resolution_required" | "access_blocked";
    workspace_count: number;
    workspace_id?: string;
  };
  authorization?: AuthorizationSummary | null;
  csrf_token: string;
};

type AuthorizationResponse = { redirect_to: string };

type ConnectionScreenProps = {
  mcpOrigin: string;
  navigate?: (url: string) => void;
};

const browserNavigate = (url: string) => window.location.assign(url);

function SurveyMark({ active }: { active: boolean }) {
  return (
    <svg
      className={active ? "survey-mark survey-mark--active" : "survey-mark"}
      viewBox="0 0 720 430"
      aria-hidden="true"
    >
      <path className="parcel parcel--outer" d="M72 59 562 34l91 119-62 218-459 22-60-334Z" />
      <path className="parcel" d="m72 59 173 82 317-107M245 141l-27 239M245 141l346 230M392 129l-19 249M522 82l-31 295" />
      <path className="measure" d="m112 94 398-20M104 346l432-18" />
      <path className="route" d="M144 290c83-83 148-103 226-91 76 12 117 1 185-78" />
      <circle className="station" cx="144" cy="290" r="8" />
      <circle className="station" cx="370" cy="199" r="8" />
      <circle className="station station--finish" cx="555" cy="121" r="8" />
      <text x="112" y="319">IDENTITY</text>
      <text x="333" y="232">AUTHORITY</text>
      <text x="530" y="100">MCP</text>
      <text className="bearing" x="78" y="48">N 31° 12′ E</text>
      <text className="bearing" x="579" y="399">CONNECTION PLAT 01</text>
    </svg>
  );
}

export function ConnectionScreen({
  mcpOrigin,
  navigate = browserNavigate,
}: ConnectionScreenProps) {
  const { isLoaded, isSignedIn, getToken } = useAuth();
  const requestHandle = useMemo(
    () => new URLSearchParams(window.location.search).get("request"),
    [],
  );
  const [state, setState] = useState<ScreenState>("signed-out");
  const [attempt, setAttempt] = useState(0);
  const [authorization, setAuthorization] =
    useState<AuthorizationSummary | null>(null);
  const [csrfToken, setCsrfToken] = useState("");
  const inFlight = useRef(false);

  const connect = useCallback(async () => {
    if (!isLoaded || !isSignedIn || !requestHandle || inFlight.current) return;
    inFlight.current = true;
    setState("connecting");
    try {
      const clerkToken = await getToken();
      if (!clerkToken) throw new Error("Clerk did not issue a session token");
      const response = await fetch(
        `${mcpOrigin}/v1/browser/session?${new URLSearchParams({ request: requestHandle })}`,
        {
          method: "POST",
          credentials: "include",
          headers: { Authorization: `Bearer ${clerkToken}` },
        },
      );
      if (!response.ok) throw new Error("Browser session exchange failed");
      const payload = (await response.json()) as ConnectionResponse;
      if (payload.connection.status === "access_blocked") {
        setState("blocked");
        return;
      }
      if (payload.connection.status !== "ready") {
        setState("review");
        return;
      }
      if (!payload.authorization || !payload.csrf_token) {
        throw new Error("Authorization summary is missing");
      }
      setAuthorization(payload.authorization);
      setCsrfToken(payload.csrf_token);
      setState("confirm");
    } catch {
      setState("failed");
    } finally {
      inFlight.current = false;
    }
  }, [getToken, isLoaded, isSignedIn, mcpOrigin, requestHandle]);

  useEffect(() => {
    if (isLoaded && !isSignedIn) setState("signed-out");
    void connect();
  }, [attempt, connect, isLoaded, isSignedIn]);

  const retry = () => {
    inFlight.current = false;
    setAttempt((value) => value + 1);
  };

  const confirm = async () => {
    if (!requestHandle || !authorization || !csrfToken || inFlight.current) return;
    inFlight.current = true;
    setState("connecting");
    try {
      const response = await fetch(`${mcpOrigin}/v1/browser/authorization`, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken,
        },
        body: JSON.stringify({ request: requestHandle }),
      });
      if (!response.ok) throw new Error("Authorization confirmation failed");
      const payload = (await response.json()) as AuthorizationResponse;
      const redirect = new URL(payload.redirect_to);
      if (redirect.origin !== authorization.redirect_origin) {
        throw new Error("Authorization redirect origin changed");
      }
      navigate(redirect.toString());
    } catch {
      setState("failed");
    } finally {
      inFlight.current = false;
    }
  };

  const cancel = async () => {
    if (!csrfToken || inFlight.current) return;
    inFlight.current = true;
    try {
      const response = await fetch(`${mcpOrigin}/v1/browser/session`, {
        method: "DELETE",
        credentials: "include",
        headers: { "X-CSRF-Token": csrfToken },
      });
      if (!response.ok) throw new Error("Browser session revocation failed");
      setAuthorization(null);
      setCsrfToken("");
      setState("cancelled");
    } catch {
      setState("failed");
    } finally {
      inFlight.current = false;
    }
  };

  let copy = {
    title: "Sign in. Then return to your scout.",
    body: "Clerk verifies you. MedawarCRE resolves access from live server records.",
  };
  if (!requestHandle) {
    copy = {
      title: "Open this from your MCP client.",
      body: "A signed connection request is required before sign-in.",
    };
  } else if (state === "connecting") {
    copy = {
      title: "Establishing the connection.",
      body: "Your browser identity is being exchanged for a revocable MCP session.",
    };
  } else if (state === "failed") {
    copy = {
      title: "Connection failed safely.",
      body: "No MCP token was issued. Try once more or contact support if this repeats.",
    };
  } else if (state === "review") {
    copy = {
      title: "Workspace access needs review.",
      body: "Your identity matches more than one workspace. Support must resolve it before connection.",
    };
  } else if (state === "blocked") {
    copy = {
      title: "Workspace access is paused.",
      body: "No token was issued. Contact support to resolve the account hold before reconnecting.",
    };
  } else if (state === "confirm") {
    copy = {
      title: "Review this connection.",
      body: "Approve only if you recognize the client and destination below.",
    };
  } else if (state === "cancelled") {
    copy = {
      title: "Connection cancelled.",
      body: "The temporary MedawarCRE browser session has been revoked.",
    };
  }

  return (
    <main className="connection-shell">
      <div className="topographic-field" aria-hidden="true" />
      <header className="brand-line">
        <svg className="brand-mark" viewBox="0 0 38 38" aria-hidden="true">
          <path d="M3 30V8l8-4 8 8 8-8 8 4v22l-8 4-8-8-8 8-8-4Z" />
          <path d="m11 4 8 22 8-22" />
        </svg>
        <span>MedawarCRE</span>
        <span className="brand-context">Secure MCP connection</span>
      </header>

      <section className="connection-copy" aria-live="polite">
        <p className="folio">Connection plat / 01</p>
        <h1>Connect your scout.</h1>
        <div className="status-copy">
          <h2>{copy.title}</h2>
          <p>{copy.body}</p>
        </div>

        {!requestHandle ? null : !isLoaded || state === "connecting" ? (
          <div className="working-state" role="status">
            <span>Verifying identity</span>
            <span className="working-line" />
          </div>
        ) : state === "failed" ? (
          <button className="primary-action" type="button" onClick={retry}>
            Try again
          </button>
        ) : state === "review" || state === "blocked" ? (
          <p className="support-note">No access token has been issued.</p>
        ) : state === "confirm" && authorization ? (
          <div className="consent-review">
            <dl>
              <div>
                <dt>Client</dt>
                <dd>{authorization.client_name}</dd>
              </div>
              <div>
                <dt>Destination</dt>
                <dd>{authorization.redirect_origin}</dd>
              </div>
              <div>
                <dt>Workspace</dt>
                <dd>{authorization.workspace_id}</dd>
              </div>
              <div>
                <dt>Access</dt>
                <dd>MCP tools</dd>
              </div>
            </dl>
            <div className="consent-actions">
              <button className="primary-action" type="button" onClick={confirm}>
                Authorize MCP connection
              </button>
              <button className="cancel-action" type="button" onClick={cancel}>
                Cancel connection
              </button>
            </div>
          </div>
        ) : !isSignedIn ? (
          <SignInButton mode="modal">
            <button className="primary-action" type="button">
              Sign in to connect
            </button>
          </SignInButton>
        ) : null}
      </section>

      <div className="survey-stage">
        <SurveyMark active={state === "connecting"} />
      </div>

      <aside className="trust-note">
        <strong>What crosses this boundary</strong>
        <span>Identity proof and one OAuth grant.</span>
        <span>Billing, territory, quota, and source rights stay server-owned.</span>
      </aside>
    </main>
  );
}
