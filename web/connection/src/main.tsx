import { ClerkProvider } from "@clerk/react";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { ConnectionScreen } from "./ConnectionScreen";

const publishableKey = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY as string | undefined;
const mcpOrigin = (import.meta.env.VITE_MCP_ORIGIN as string | undefined)?.replace(/\/$/, "");
const root = createRoot(document.getElementById("root")!);

if (!publishableKey || !mcpOrigin) {
  root.render(
    <main className="configuration-error">
      <h1>Connection service is not configured.</h1>
      <p>No credentials were accepted and no MCP session was created.</p>
    </main>,
  );
} else {
  root.render(
    <StrictMode>
      <ClerkProvider publishableKey={publishableKey}>
        <ConnectionScreen mcpOrigin={mcpOrigin} />
      </ClerkProvider>
    </StrictMode>,
  );
}
