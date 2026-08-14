import React from "react";
import ReactDOM from "react-dom/client";
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import App from "./App";
import "./index.css";
import "./engine"; // движки в бандле + window-хуки для headless-страниц/тестов
import * as ctl from "./editor/controller";
import { installDesktopFetchBridge } from "./desktop/bridge";

installDesktopFetchBridge();

// read-only хук сессии DNA-редактора для UI-тестов (вместо legacy window.Editor)
(window as any).DNAEditor = {
  getIR: () => {
    const s = ctl.getSession();
    return s ? s.activeIR || s.ir : null;
  },
  isOpen: () => ctl.isActive(),
};

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
