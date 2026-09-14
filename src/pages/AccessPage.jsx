import { useQuery } from "@tanstack/react-query";
import { api } from "../api/http.js";
import styles from "./Page.module.css";

export default function AccessPage() {
  const { data = [] } = useQuery({ queryKey: ["users"], queryFn: api.users });

  return (
    <section className={styles.grid}>
      <div className={styles.toolbar}>
        <div>
          <h2>Доступы</h2>
          <p>Роли внутри строительной компании и объектные ограничения.</p>
        </div>
      </div>
      <div className={`${styles.card} ${styles.tableWrap}`}>
        <table className={styles.table}>
          <thead><tr><th>Сотрудник</th><th>Роль</th><th>Объекты</th><th>Статус</th></tr></thead>
          <tbody>
            {data.map((item) => (
              <tr key={item.id}>
                <td className={styles.title}><strong>{item.name}</strong><span>{item.email}</span></td>
                <td>{item.company_role}</td>
                <td>{item.object_scope || "Все назначенные"}</td>
                <td><span className="pill green">{item.is_active ? "active" : "disabled"}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
