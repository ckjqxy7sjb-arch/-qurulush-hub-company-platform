import { useState } from "react";
import { useNavigate } from "react-router-dom";
import toast from "react-hot-toast";
import { api, http, setAccessToken } from "../api/http.js";
import styles from "./Page.module.css";

export default function LoginPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("director@company.kg");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setLoading(true);
    try {
      const csrf = await api.csrf();
      http.defaults.headers.common["x-csrf-token"] = csrf.csrfToken;
      const session = await api.login({ email, password });
      setAccessToken(session.accessToken);
      toast.success("Вход выполнен");
      navigate("/", { replace: true });
    } catch (error) {
      toast.error(error.response?.data?.message || "Не удалось войти");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className={styles.grid} style={{ minHeight: "100vh", placeItems: "center", padding: 16 }}>
      <form className={styles.card} onSubmit={submit} style={{ width: "min(430px, 100%)" }}>
        <div className={styles.toolbar}>
          <div>
            <h2>Вход в кабинет</h2>
            <p>Рабочая платформа строительной компании</p>
          </div>
        </div>
        <div className={styles.form}>
          <label>
            Email
            <input className="field" value={email} onChange={(event) => setEmail(event.target.value)} />
          </label>
          <label>
            Пароль
            <input className="field" type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
          </label>
          <button className="btn" disabled={loading}>
            {loading ? "Проверка..." : "Войти"}
          </button>
        </div>
      </form>
    </main>
  );
}
