import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const getToken = vi.fn();
let signedIn = false;

vi.mock("@clerk/react", () => ({
  SignInButton: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useAuth: () => ({ isLoaded: true, isSignedIn: signedIn, getToken }),
}));

import { ConnectionScreen } from "./ConnectionScreen";

describe("ConnectionScreen", () => {
  beforeEach(() => {
    signedIn = false;
    getToken.mockReset();
    window.history.replaceState({}, "", "/connect?request=mcr_req_test");
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("shows one Clerk sign-in action and no customer portal navigation", () => {
    render(<ConnectionScreen mcpOrigin="https://mcp.example.test" />);

    expect(screen.getByRole("button", { name: "Sign in to connect" })).toBeVisible();
    expect(screen.getByText("Connect your scout.")).toBeVisible();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /billing|dashboard|settings|deals/i })).not.toBeInTheDocument();
  });

  it("exchanges the Clerk token without persistence then resumes OAuth", async () => {
    signedIn = true;
    getToken.mockResolvedValue("short-lived-clerk-token");
    const storageWrite = vi.spyOn(Storage.prototype, "setItem");
    vi.mocked(fetch).mockResolvedValue(
      new Response(
        JSON.stringify({
          user: { id: 4, email: "buyer@example.test", name: "Buyer" },
          connection: { status: "ready", workspace_count: 1, workspace_id: "ws_live" },
          csrf_token: "not-persisted",
          expires_at: "2026-08-04T13:00:00Z",
        }),
        { status: 201, headers: { "Content-Type": "application/json" } },
      ),
    );
    const navigate = vi.fn();

    render(<ConnectionScreen mcpOrigin="https://mcp.example.test" navigate={navigate} />);

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        "https://mcp.example.test/v1/browser/session",
        expect.objectContaining({
          method: "POST",
          credentials: "include",
          headers: { Authorization: "Bearer short-lived-clerk-token" },
        }),
      );
    });
    expect(storageWrite).not.toHaveBeenCalled();
    expect(navigate).toHaveBeenCalledWith(
      "https://mcp.example.test/oauth/authorize?request=mcr_req_test",
    );
  });

  it("fails visibly and offers a functional retry", async () => {
    signedIn = true;
    getToken.mockResolvedValue("token");
    vi.mocked(fetch)
      .mockResolvedValueOnce(new Response("{}", { status: 503 }))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            user: { id: 4, email: "buyer@example.test", name: "Buyer" },
            connection: { status: "workspace_resolution_required", workspace_count: 2 },
            csrf_token: "csrf",
            expires_at: "2026-08-04T13:00:00Z",
          }),
          { status: 201, headers: { "Content-Type": "application/json" } },
        ),
      );

    render(<ConnectionScreen mcpOrigin="https://mcp.example.test" />);
    expect(await screen.findByText("Connection failed safely.")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Workspace access needs review.")).toBeVisible();
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("explains a server-owned account hold without issuing or resuming OAuth", async () => {
    signedIn = true;
    getToken.mockResolvedValue("token");
    vi.mocked(fetch).mockResolvedValue(
      new Response(
        JSON.stringify({
          user: { id: 4, email: "buyer@example.test", name: "Buyer" },
          connection: {
            status: "access_blocked",
            workspace_count: 1,
            workspace_id: "ws_live",
          },
          csrf_token: "csrf",
          expires_at: "2026-08-04T13:00:00Z",
        }),
        { status: 201, headers: { "Content-Type": "application/json" } },
      ),
    );
    const navigate = vi.fn();

    render(
      <ConnectionScreen
        mcpOrigin="https://mcp.example.test"
        navigate={navigate}
      />,
    );

    expect(await screen.findByText("Workspace access is paused.")).toBeVisible();
    expect(screen.getByText("No access token has been issued.")).toBeVisible();
    expect(navigate).not.toHaveBeenCalled();
  });
});
