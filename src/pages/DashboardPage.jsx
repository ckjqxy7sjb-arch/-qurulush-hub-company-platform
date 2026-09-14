import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/http.js";
import styles from "./Page.module.css";

export default function DashboardPage() {
  const { data, isLoading } = useQuery({ queryKey: ["dashboard"], queryFn: api.dashboard });
  const metrics = data?.metrics || {};
  const urgent = data?.urgentNotifications || [];

  if (isLoading) return <div className={styles.card}>Загрузка центра...</div>;

  return (
    <section className={styles.grid}>
      <div className={styles.metrics}>
        <div className={`${styles.card} ${styles.metric}`}><span>Новые уведомления</span><strong>{metrics.newNotifications || 0}</strong></div>
        <div className={`${styles.card} ${styles.metric}`}><span>К оплате</span><strong>{metrics.unpaidAmount || 0}</strong></div>
        <div className={`${styles.card} ${styles.metric}`}><span>Документы к отправке</span><strong>{metrics.pendingDocuments || 0}</strong></div>
        <div className={`${styles.card} ${styles.metric}`}><span>Сроки сегодня</span><strong>{metrics.dueToday || 0}</strong></div>
      </div>
      <div className={styles.split}>
        <div className={styles.card}>
          <div className={styles.toolbar}>
            <div>
              <h2>Центр действий</h2>
              <p>Рабочий поток компании: принять, назначить, оплатить, отправить подтверждение.</p>
            </div>
            <Link className="btn" to="/notifications">Открыть уведомления</Link>
          </div>
          <div className={styles.feed} style={{ marginTop: 12 }}>
            {urgent.map((item) => (
              <article className={styles.message} key={item.id}>
                <b>{item.title}</b>
                <p>{item.source} · срок: {item.due_at || "без срока"} · ответственный: {item.assignee_name || "не назначен"}</p>
              </article>
            ))}
          </div>
        </div>
        <div className={styles.card}>
          <div className={styles.toolbar}>
            <div>
              <h2>Быстрые действия</h2>
              <p>Основные операции без лишних разделов.</p>
            </div>
          </div>
          <div className={styles.actions} style={{ marginTop: 12 }}>
            <Link className="btn secondary" to="/payments">Оплаты</Link>
            <Link className="btn secondary" to="/documents">Документы</Link>
            <Link className="btn secondary" to="/tasks">Поручения</Link>
            <Link className="btn secondary" to="/calendar">Календарь</Link>
          </div>
        </div>
      </div>
    </section>
  );
}
