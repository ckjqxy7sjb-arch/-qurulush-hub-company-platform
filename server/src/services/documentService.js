import htmlToDocx from "html-to-docx";
import puppeteer from "puppeteer";

export async function htmlToPdfBuffer(html) {
  const browser = await puppeteer.launch({ headless: "new" });
  try {
    const page = await browser.newPage();
    await page.setContent(html, { waitUntil: "networkidle0" });
    return page.pdf({ format: "A4", printBackground: true });
  } finally {
    await browser.close();
  }
}

export async function htmlToWordBuffer(html) {
  return htmlToDocx(html, null, {
    table: { row: { cantSplit: true } },
    footer: true,
    pageNumber: true,
  });
}
