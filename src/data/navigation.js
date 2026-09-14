export const navigation = [
  { path: "/", label: "Центр", roles: ["company"] },
  { path: "/notifications", label: "Уведомления", roles: ["company"] },
  { path: "/payments", label: "Платежи", roles: ["company"] },
  { path: "/documents", label: "Документы", roles: ["company"] },
  { path: "/tasks", label: "Поручения", roles: ["company"] },
  { path: "/calendar", label: "Календарь", roles: ["company"] },
  { path: "/chat", label: "Чат ИИ", roles: ["company"] },
  { path: "/access", label: "Доступы", roles: ["company"] },
];

export function visibleNavigation(user) {
  return navigation.filter((item) => item.roles.includes(user?.role || "company"));
}
