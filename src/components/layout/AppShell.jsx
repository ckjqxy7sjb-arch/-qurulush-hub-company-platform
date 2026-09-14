import { useQuery } from "@tanstack/react-query";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import toast from "react-hot-toast";
import { api, setAccessToken } from "../../api/http.js";
import { visibleNavigation } from "../../data/navigation.js";
import { useUiStore } from "../../store/uiStore.js";
import styles from "./AppShell.module.css";

export function AppShell() {
  const navigate = useNavigate();
  const { theme, setTheme } = useUiStore();
  const { data: user } = useQuery({ queryKey: ["me"], queryFn: api.me });
  const nav = visibleNavigation(user);

  async function logout() {
    await api.logout().catch(() => null);
    setAccessToken(null);
    toast.success("Сессия завершена");
    navigate("/login", { replace: true });
  }

  return (
    <div className={styles.shell} data-theme={theme}>
      <aside className={styles.sidebar}>
        <div className={styles.brand}>
          <div className={styles.mark}>ДК</div>
          <div className={styles.brandText}>
            <strong>ДГАСК КР</strong>
            <span>Кабинет компании</span>
          </div>
        </div>
        <nav className={styles.nav} aria-label="Разделы платформы">
          {nav.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.path === "/"}
              className={({ isActive }) => `${styles.navLink} ${isActive ? styles.active : ""}`}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className={styles.sidebarNote}>
          Основной контур: получить уведомление, назначить ответственного, оплатить или загрузить документ, отправить подтверждение.
        </div>
      </aside>
      <main className={styles.main}>
        <header className={styles.topbar}>
          <div className={styles.title}>
            <strong>Операционный центр строительной компании</strong>
            <span>Уведомления, оплаты, документы и сроки без лишних министерских модулей</span>
          </div>
          <div className={styles.actions}>
            <span className="pill">{user?.companyRole || user?.role || "company"}</span>
            <button className="btn secondary" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
              Тема
            </button>
            <button className="btn secondary" onClick={logout}>
              Выйти
            </button>
          </div>
        </header>
        <Outlet context={{ user }} />
      </main>
    </div>
  );
}
