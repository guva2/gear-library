import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { ensureCsrfCookie } from "./api";
import App from "./App";

// Failures are retried; see ensureCsrfCookie.
ensureCsrfCookie().catch(() => {});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
