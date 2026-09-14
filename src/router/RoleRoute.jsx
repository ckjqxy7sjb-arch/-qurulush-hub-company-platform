import { useQuery } from "@tanstack/react-query";
import { Navigate } from "react-router-dom";
import { api } from "../api/http.js";

export function RoleRoute({ roles, children }) {
  const { data: user, isLoading } = useQuery({ queryKey: ["me"], queryFn: api.me });

  if (isLoading) return <div className="page-loading">Проверка доступа...</div>;
  if (!roles.includes(user?.role)) return <Navigate to="/" replace />;

  return children;
}
