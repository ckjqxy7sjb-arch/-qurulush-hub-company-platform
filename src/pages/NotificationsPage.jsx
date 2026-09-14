import { useMutation, useQuery } from "@tanstack/react-query";
import toast from "react-hot-toast";
import DOMPurify from "dompurify";
import { api } from "../api/http.js";
import { queryClient } from "../api/queryClient.js";
import styles from "./Page.module.css";

export default function NotificationsPage() {
  const { data = [] } = useQuery({ queryKey: ["notifications"], queryFn: () => api.notifications() });
  const accept = useMutation({
    mutationFn: api.acceptNotification,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
      toast.success("Уведомление принято в работу");
    },
  });

  return (
    <section className={styles.grid}>
      <div className={styles.toolbar}>
        <div>
          <h2>Входящие уведомления</h2>
          <p>Единая очередь от sacc2, Минстроя, ДГАСК, инспектора и платежного контура.</p>
        </div>
      </div>
      <div className={`${styles.card} ${styles.tableWrap}`}>
        <table className={styles.table}>
          <thead><tr><th>Уведомление</th><th>Источник</th><th>Срок</th><th>Статус</th><th>Действие</th></tr></thead>
          <tbody>
            {data.map((item) => (
              <tr key={item.id}>
                <td className={styles.title}>
                  <strong>{item.title}</strong>
                  <span dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(item.body || "") }} />
                </td>
                <td>{item.source}</td>
                <td>{item.due_at || "-"}</td>
                <td><span className="pill amber">{item.status}</span></td>
                <td className={styles.actions}>
                  <button className="btn secondary" onClick={() => accept.mutate(item.id)}>Принять</button>
                  <button className="btn">Ответить</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
