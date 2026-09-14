import { useMutation, useQuery } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { api } from "../api/http.js";
import { queryClient } from "../api/queryClient.js";
import styles from "./Page.module.css";

export default function PaymentsPage() {
  const { data = [] } = useQuery({ queryKey: ["payments"], queryFn: () => api.payments() });
  const pay = useMutation({
    mutationFn: (id) => api.pay(id, { provider: "manual", paymentNumber: `PAY-${Date.now()}`, receiptFileName: "receipt.pdf" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["payments"] });
      toast.success("Оплата зафиксирована");
    },
  });

  async function exportExcel() {
    const ExcelJS = await import("exceljs");
    const Workbook = ExcelJS.Workbook || ExcelJS.default?.Workbook;
    const workbook = new Workbook();
    const sheet = workbook.addWorksheet("Платежи");
    sheet.columns = [
      { header: "Начисление", key: "title", width: 36 },
      { header: "Основание", key: "basis", width: 34 },
      { header: "Сумма", key: "amount", width: 14 },
      { header: "Валюта", key: "currency", width: 10 },
      { header: "Статус", key: "status", width: 16 },
      { header: "Срок", key: "due_at", width: 14 },
    ];
    data.forEach((row) => sheet.addRow(row));
    const buffer = await workbook.xlsx.writeBuffer();
    const blob = new Blob([buffer], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `dgask-payments-${Date.now()}.xlsx`;
    link.click();
    URL.revokeObjectURL(link.href);
  }

  return (
    <section className={styles.grid}>
      <div className={styles.toolbar}>
        <div>
          <h2>Платежи и начисления</h2>
          <p>Штрафы, госпошлины и другие начисления с подтверждением оплаты.</p>
        </div>
        <button className="btn secondary" onClick={exportExcel}>Экспорт Excel</button>
      </div>
      <div className={`${styles.card} ${styles.tableWrap}`}>
        <table className={styles.table}>
          <thead><tr><th>Начисление</th><th>Сумма</th><th>Срок</th><th>Статус</th><th></th></tr></thead>
          <tbody>
            {data.map((item) => (
              <tr key={item.id}>
                <td className={styles.title}><strong>{item.title}</strong><span>{item.basis}</span></td>
                <td>{Number(item.amount || 0).toLocaleString("ru-RU")} сом</td>
                <td>{item.due_at || "-"}</td>
                <td><span className={`pill ${item.status === "paid" ? "green" : "amber"}`}>{item.status}</span></td>
                <td><button className="btn" disabled={item.status === "paid"} onClick={() => pay.mutate(item.id)}>Оплатить</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
