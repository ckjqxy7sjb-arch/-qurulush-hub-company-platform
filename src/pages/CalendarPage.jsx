import { useQuery } from "@tanstack/react-query";
import dayjs from "dayjs";
import { api } from "../api/http.js";
import styles from "./Page.module.css";

export default function CalendarPage() {
  const { data = [] } = useQuery({ queryKey: ["calendar"], queryFn: api.calendar });

  return (
    <section className={styles.grid}>
      <div className={styles.toolbar}>
        <div>
          <h2>Календарь сроков</h2>
          <p>Все дедлайны из уведомлений, оплат, документов и поручений.</p>
        </div>
      </div>
      <div className={styles.feed}>
        {data.map((item) => (
          <article className={styles.card} key={`${item.type}-${item.id}`}>
            <div className={styles.toolbar}>
              <div className={styles.title}>
                <strong>{item.title}</strong>
                <span>{item.type} · {item.owner || "ответственный не назначен"}</span>
              </div>
              <span className="pill amber">{item.due_at ? dayjs(item.due_at).format("DD MMMM YYYY") : "без срока"}</span>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
