import { useMutation, useQuery } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { api } from "../api/http.js";
import { queryClient } from "../api/queryClient.js";
import styles from "./Page.module.css";

export default function TasksPage() {
  const { data = [] } = useQuery({ queryKey: ["tasks"], queryFn: () => api.tasks() });
  const done = useMutation({
    mutationFn: (id) => api.updateTask(id, { status: "done", evidence: "Выполнено через web-кабинет" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      toast.success("Поручение закрыто");
    },
  });

  return (
    <section className={styles.grid}>
      <div className={styles.toolbar}>
        <div>
          <h2>Поручения</h2>
          <p>Задачи по уведомлениям, оплатам, документам и устранению замечаний.</p>
        </div>
      </div>
      <div className={`${styles.card} ${styles.tableWrap}`}>
        <table className={styles.table}>
          <thead><tr><th>Задача</th><th>Исполнитель</th><th>Срок</th><th>Статус</th><th></th></tr></thead>
          <tbody>
            {data.map((item) => (
              <tr key={item.id}>
                <td className={styles.title}><strong>{item.title}</strong><span>{item.description}</span></td>
                <td>{item.assignee_name || "-"}</td>
                <td>{item.due_at || "-"}</td>
                <td><span className="pill">{item.status}</span></td>
                <td><button className="btn secondary" onClick={() => done.mutate(item.id)}>Закрыть</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
