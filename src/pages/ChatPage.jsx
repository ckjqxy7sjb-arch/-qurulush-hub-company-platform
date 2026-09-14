import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/http.js";
import { queryClient } from "../api/queryClient.js";
import styles from "./Page.module.css";

export default function ChatPage() {
  const [message, setMessage] = useState("");
  const { data = [] } = useQuery({ queryKey: ["chat"], queryFn: api.chat });
  const send = useMutation({
    mutationFn: () => api.sendChat({ message }),
    onSuccess: () => {
      setMessage("");
      queryClient.invalidateQueries({ queryKey: ["chat"] });
    },
  });

  return (
    <section className={styles.split}>
      <div className={styles.card}>
        <div className={styles.toolbar}>
          <div>
            <h2>Внутренний чат и ИИ</h2>
            <p>Обсуждение уведомлений, сроков, оплат и документов по компании.</p>
          </div>
        </div>
        <div className={styles.feed} style={{ marginTop: 12 }}>
          {data.map((item) => (
            <article className={styles.message} key={item.id}>
              <b>{item.author_name || item.author_type}</b>
              <p>{item.body}</p>
            </article>
          ))}
        </div>
      </div>
      <form className={`${styles.card} ${styles.form}`} onSubmit={(event) => { event.preventDefault(); send.mutate(); }}>
        <label>
          Сообщение
          <textarea className="field" rows="7" value={message} onChange={(event) => setMessage(event.target.value)} />
        </label>
        <button className="btn" disabled={!message.trim()}>Отправить</button>
      </form>
    </section>
  );
}
