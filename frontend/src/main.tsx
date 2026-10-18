import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import PinGate from "./PinGate";
import "./styles.css";
import "./trends.css";
import "./editorial.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <PinGate>
      <App />
    </PinGate>
  </React.StrictMode>,
);
