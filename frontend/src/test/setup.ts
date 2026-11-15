import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// vitest globals are off → RTL cannot auto-register its cleanup hook;
// without this, renders leak across tests (two shells in document.body).
afterEach(() => {
  cleanup();
});
