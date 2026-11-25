import imaplib
import email
import os
import re
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import requests

KST = timezone(timedelta(hours=9))

def get_today_ecount_link():
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"])
    mail.select("inbox")

    today_str = datetime.now(KST).strftime("%d-%b-%Y")
    _, data = mail.search(None, f'(FROM "ecountnotice@ecount.com" SINCE "{today_str}")')
    msg_ids = data[0].split()
    if not msg_ids:
        raise RuntimeError("오늘 수신된 ECOUNT 메일이 없습니다.")

    _, msg_data = mail.fetch(msg_ids[-1], "(RFC822)")
    msg = email.message_from_bytes(msg_data[0][1])

    body = ""
    for part in msg.walk():
        if part.get_content_type() in ("text/html", "text/plain"):
            payload = part.get_payload(decode=True)
            if payload:
                body += payload.decode(errors="ignore")

    match = re.search(r"https://l\.ecount\.com/[A-Za-z0-9]+", body)
    if not match:
        raise RuntimeError("메일 본문에서 수신문서보기 링크를 찾지 못했습니다.")
    return match.group(0)

def fetch_sales_rows(url):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="networkidle")
        print("로그인 전 URL:", page.url)

        pw_input = page.locator('input[type="password"]').first
        pw_input.fill(os.environ["ECOUNT_PASSWORD"])
        login_btn = page.locator('button:has-text("로그인"), input[type="submit"], a:has-text("로그인")')
        if login_btn.count() > 0:
            login_btn.first.click()
        else:
            pw_input.press("Enter")

        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(6000)
        print("로그인 후 URL:", page.url)
        print("프레임 수:", len(page.frames))

        rows = []
        for idx, frame in enumerate(page.frames):
            try:
                html = frame.content()
                soup = BeautifulSoup(html, "html.parser")
                tables = soup.find_all("table")
                print(f"[프레임 {idx}] URL={frame.url[:80]} | 테이블 수={len(tables)}")
                for tr in soup.select("table tr"):
                    cols = [td.get_text(strip=True) for td in tr.find_all("td")]
                    if len(cols) >= 3 and any(cols):
                        rows.append(cols)
            except Exception as e:
                print(f"[프레임 {idx}] 읽기 오류:", e)

        if not rows:
            print("페이지 텍스트 미리보기:", page.inner_text("body")[:500])

        browser.close()
    return rows

def append_to_sheet(rows):
    res = requests.post(
        os.environ["SHEET_WEBHOOK_URL"],
        json={"token": os.environ["SHEET_WEBHOOK_TOKEN"], "rows": rows},
        timeout=30,
    )
    res.raise_for_status()
    print("시트 응답:", res.text)

if __name__ == "__main__":
    link = get_today_ecount_link()
    print("찾은 링크:", link)
    sales_rows = fetch_sales_rows(link)
    print(f"추출된 행 수: {len(sales_rows)}")
    if sales_rows:
        print("샘플 2행:", sales_rows[:2])
        append_to_sheet(sales_rows)
