import { ClerkProvider } from "@clerk/react";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { OperationsConsole } from "./OperationsConsole";

const publishableKey = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY as string | undefined;
const platformOrigin = (import.meta.env.VITE_PLATFORM_ORIGIN as string | undefined)?.replace(/\/$/, "");
const root = createRoot(document.getElementById("root")!);

if (!publishableKey || !platformOrigin) {
  root.render(
    <main className="operator-gate">
      <h1>Operations Console is disabled.</h1>
      <p>No staff identity or platform session was accepted.</p>
    </main>,
  );
} else {
  root.render(
    <StrictMode>
      <ClerkProvider publishableKey={publishableKey}>
        <OperationsConsole platformOrigin={platformOrigin} />
      </ClerkProvider>
    </StrictMode>,
  );
}
