import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { AppProviders } from "@/app/providers";
import "@/styles/index.css";

const rootElement = document.getElementById("root");

if (!rootElement) {
  throw new Error("The Anti-Gravity Hub root element is missing.");
}

createRoot(rootElement).render(
  <StrictMode>
    <AppProviders />
  </StrictMode>,
);
