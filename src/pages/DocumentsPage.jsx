import { useQuery } from "@tanstack/react-query";
import { api } from "../api/http.js";
import styles from "./Page.module.css";

export default function DocumentsPage() {
  const { data = [] } = useQuery({ queryKey: ["documents"], queryFn: () => api.documents() });

  return (
    <section className={styles.grid}>
      <div className={styles.toolbar}>
        <div>
          <h2>Документы к отправке</h2>
          <p>Ответы, квитанции, акты, фото и файлы устранения замечаний.</p>
        </div>
        <button className="btn secondary" onClick={() => window.print()}>Печать PDF</button>
      </div>
      <div className={`${styles.card} ${styles.tableWrap}`}>
        <table className={styles.table}>
          <thead><tr><th>Документ</th><th>Связь</th><th>Срок</th><th>Статус</th><th>Файл</th></tr></thead>
          <tbody>
            {data.map((item) => (
              <tr key={item.id}>
                <td className={styles.title}><strong>{item.title}</strong><span>{item.description}</span></td>
                <td>{item.notification_title || item.task_title || "-"}</td>
                <td>{item.due_at || "-"}</td>
                <td><span className="pill amber">{item.status}</span></td>
                <td><input className="field" type="file" /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
