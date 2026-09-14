import axios from "axios";

const ACCESS_TOKEN_KEY = "dgask_access_token";

export const http = axios.create({
  baseURL: "/api",
  withCredentials: true,
  timeout: 20_000,
});

export function getAccessToken() {
  return localStorage.getItem(ACCESS_TOKEN_KEY);
}

export function setAccessToken(token) {
  if (token) localStorage.setItem(ACCESS_TOKEN_KEY, token);
  else localStorage.removeItem(ACCESS_TOKEN_KEY);
}

http.interceptors.request.use((config) => {
  const token = getAccessToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

http.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config;
    if (error.response?.status !== 401 || original?._retry || original?.url?.includes("/auth/refresh")) {
      return Promise.reject(error);
    }
    original._retry = true;
    const refresh = await http.post("/auth/refresh");
    setAccessToken(refresh.data.accessToken);
    original.headers.Authorization = `Bearer ${refresh.data.accessToken}`;
    return http(original);
  },
);

export const api = {
  csrf: () => http.get("/auth/csrf").then((res) => res.data),
  login: (payload) => http.post("/auth/login", payload).then((res) => res.data),
  me: () => http.get("/auth/me").then((res) => res.data),
  logout: () => http.post("/auth/logout").then((res) => res.data),
  dashboard: () => http.get("/dashboard").then((res) => res.data),
  notifications: (params) => http.get("/notifications", { params }).then((res) => res.data),
  acceptNotification: (id) => http.post(`/notifications/${id}/accept`).then((res) => res.data),
  sendNotificationReply: (id, payload) => http.post(`/notifications/${id}/reply`, payload).then((res) => res.data),
  tasks: (params) => http.get("/tasks", { params }).then((res) => res.data),
  updateTask: (id, payload) => http.patch(`/tasks/${id}`, payload).then((res) => res.data),
  payments: (params) => http.get("/payments", { params }).then((res) => res.data),
  pay: (id, payload) => http.post(`/payments/${id}/pay`, payload).then((res) => res.data),
  documents: (params) => http.get("/documents", { params }).then((res) => res.data),
  uploadDocument: (id, formData) => http.post(`/documents/${id}/versions`, formData).then((res) => res.data),
  calendar: () => http.get("/calendar").then((res) => res.data),
  chat: () => http.get("/chat").then((res) => res.data),
  sendChat: (payload) => http.post("/chat", payload).then((res) => res.data),
  users: () => http.get("/users").then((res) => res.data),
};
