export const navigation = [
  { path: "/", label: "Центр", roles: ["company", "ministry", "regional", "inspector"] },
  { path: "/notifications", label: "Уведомления", roles: ["company", "ministry", "regional", "inspector"] },
  { path: "/payments", label: "Платежи", roles: ["company"] },
  { path: "/documents", label: "Документы", roles: ["company", "ministry", "regional", "inspector"] },
  { path: "/tasks", label: "Поручения", roles: ["company"] },
  { path: "/calendar", label: "Календарь", roles: ["company", "ministry", "regional", "inspector"] },
  { path: "/chat", label: "Чат ИИ", roles: ["company", "ministry", "regional", "inspector"] },
  { path: "/access", label: "Доступы", roles: ["company"] },
];

export function visibleNavigation(user) {
  return navigation.filter((item) => item.roles.includes(user?.role || "company"));
}
