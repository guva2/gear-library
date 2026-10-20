import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { ensureCsrfCookie } from "./api";
import App from "./App";
import "./index.css";

// Failures are retried; see ensureCsrfCookie.
ensureCsrfCookie().catch(() => {});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
