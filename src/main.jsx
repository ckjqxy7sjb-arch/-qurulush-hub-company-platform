import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "react-hot-toast";
import "dayjs/locale/ru";
import dayjs from "dayjs";
import { queryClient } from "./api/queryClient.js";
import { AppRouter } from "./router/AppRouter.jsx";
import "./styles/tokens.css";
import "./styles/base.css";

dayjs.locale("ru");

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <AppRouter />
      <Toaster position="top-right" toastOptions={{ duration: 3200 }} />
    </QueryClientProvider>
  </React.StrictMode>,
);
