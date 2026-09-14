import { lazy, Suspense } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { AppShell } from "../components/layout/AppShell.jsx";
import { ProtectedRoute } from "./ProtectedRoute.jsx";
import { RoleRoute } from "./RoleRoute.jsx";

const DashboardPage = lazy(() => import("../pages/DashboardPage.jsx"));
const NotificationsPage = lazy(() => import("../pages/NotificationsPage.jsx"));
const PaymentsPage = lazy(() => import("../pages/PaymentsPage.jsx"));
const DocumentsPage = lazy(() => import("../pages/DocumentsPage.jsx"));
const TasksPage = lazy(() => import("../pages/TasksPage.jsx"));
const CalendarPage = lazy(() => import("../pages/CalendarPage.jsx"));
const ChatPage = lazy(() => import("../pages/ChatPage.jsx"));
const AccessPage = lazy(() => import("../pages/AccessPage.jsx"));
const LoginPage = lazy(() => import("../pages/LoginPage.jsx"));

function Loading() {
  return <div className="page-loading">Загрузка...</div>;
}

export function AppRouter() {
  return (
    <BrowserRouter>
      <Suspense fallback={<Loading />}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<ProtectedRoute />}>
            <Route element={<AppShell />}>
              <Route index element={<DashboardPage />} />
              <Route path="notifications" element={<NotificationsPage />} />
              <Route path="payments" element={<RoleRoute roles={["company"]}><PaymentsPage /></RoleRoute>} />
              <Route path="documents" element={<DocumentsPage />} />
              <Route path="tasks" element={<RoleRoute roles={["company"]}><TasksPage /></RoleRoute>} />
              <Route path="calendar" element={<CalendarPage />} />
              <Route path="chat" element={<ChatPage />} />
              <Route path="access" element={<RoleRoute roles={["company"]}><AccessPage /></RoleRoute>} />
            </Route>
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
