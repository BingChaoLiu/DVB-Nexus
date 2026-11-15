import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router";
import { createAppRouter } from "./app/router";
import { AppQueryProvider } from "./query/QueryProvider";
import "./styles/theme.css";

const router = createAppRouter();

const root = document.getElementById("root");
if (root === null) throw new Error("#root missing from index.html");

createRoot(root).render(
  <AppQueryProvider>
    <RouterProvider router={router} />
  </AppQueryProvider>,
);
