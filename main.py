from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Any
import os, json, time, datetime
import psycopg2, psycopg2.extras
import resend
from apscheduler.schedulers.background import BackgroundScheduler

app = FastAPI(title="QMS17025 API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DATABASE_URL = os.environ.get("DATABASE_URL", "")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
resend.api_key = RESEND_API_KEY

def get_conn():
    """Her istekte yeni bağlantı aç - Neon SSL kopma sorununu önler"""
    for attempt in range(3):
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require', connect_timeout=10)
            return conn
        except Exception as e:
            print(f"DB baglanti hatasi (deneme {attempt+1}): {e}")
            if attempt < 2:
                time.sleep(1)
    raise Exception("DB baglantisi kurulamadi")

def init_db():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS qms_store (
            key TEXT PRIMARY KEY, value JSONB NOT NULL);""")
        conn.commit()
        print("DB tablosu hazir")
    finally:
        conn.close()

def db_get(key):
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT value FROM qms_store WHERE key = %s", (key,))
        row = cur.fetchone()
        return row["value"] if row else None
    finally:
        conn.close()

# ==================== BİLDİRİM ====================
def days_until(date_str):
    if not date_str:
        return None
    try:
        target = datetime.datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        return (target - datetime.date.today()).days
    except:
        return None

def fmt_date(date_str):
    if not date_str:
        return "-"
    try:
        return datetime.datetime.strptime(date_str[:10], "%Y-%m-%d").strftime("%d.%m.%Y")
    except:
        return date_str

def check_and_send_notifications():
    print("Bildirim kontrolu basliyor...")
    try:
        settings = db_get("settings") or {}
        emails_raw = settings.get("notifEmails", settings.get("notifEmail", ""))
        threshold = int(settings.get("threshold", 30))
        notif_types = settings.get("notifTypes", {})
        firm_name = settings.get("firmName", "LabQMS")

        if isinstance(emails_raw, list):
            emails = [e.strip() for e in emails_raw if e.strip()]
        else:
            emails = [e.strip() for e in str(emails_raw).split(",") if e.strip()]

        if not emails:
            print("Mail adresi tanimli degil")
            return

        alerts = []

        if notif_types.get("referans", True):
            for x in (db_get("referans") or []):
                d = days_until(x.get("birSonrakiKalibrasyon"))
                if d is not None:
                    if d < 0:
                        alerts.append({"tip":"🔴 GECİKEN","modul":"Referans Cihaz","ad":x.get("cihazAdi","-"),"tarih":fmt_date(x.get("birSonrakiKalibrasyon")),"gun":f"{abs(d)} gün geçti","renk":"#dc2626"})
                    elif d <= threshold:
                        alerts.append({"tip":"🟡 YAKLAŞAN","modul":"Referans Cihaz","ad":x.get("cihazAdi","-"),"tarih":fmt_date(x.get("birSonrakiKalibrasyon")),"gun":f"{d} gün kaldı","renk":"#d97706"})

        if notif_types.get("araKontrol", True):
            for x in (db_get("araKontrol") or []):
                d = days_until(x.get("birSonrakiPlanliAra"))
                if d is not None:
                    if d < 0:
                        alerts.append({"tip":"🔴 GECİKEN","modul":"Ara Kontrol","ad":x.get("cihazAdi","-"),"tarih":fmt_date(x.get("birSonrakiPlanliAra")),"gun":f"{abs(d)} gün geçti","renk":"#dc2626"})
                    elif d <= threshold:
                        alerts.append({"tip":"🟡 YAKLAŞAN","modul":"Ara Kontrol","ad":x.get("cihazAdi","-"),"tarih":fmt_date(x.get("birSonrakiPlanliAra")),"gun":f"{d} gün kaldı","renk":"#d97706"})

        if notif_types.get("lak", True):
            for x in (db_get("lak") or []):
                d = days_until(x.get("birSonrakiPlanliLak"))
                if d is not None and d <= threshold:
                    alerts.append({"tip":"🟡 YAKLAŞAN","modul":"LAK/YT","ad":x.get("lakAdi","-"),"tarih":fmt_date(x.get("birSonrakiPlanliLak")),"gun":f"{d} gün kaldı","renk":"#d97706"})

        if notif_types.get("pak", True):
            for x in (db_get("pak") or []):
                d = days_until(x.get("birSonrakiPlanliPak"))
                if d is not None and d <= threshold:
                    alerts.append({"tip":"🟡 YAKLAŞAN","modul":"PAK","ad":x.get("pakAdi","-"),"tarih":fmt_date(x.get("birSonrakiPlanliPak")),"gun":f"{d} gün kaldı","renk":"#d97706"})

        if not alerts:
            print("Bildirim gonderilecek kayit yok")
            return

        rows = "".join([f"""<tr>
            <td style="padding:10px 12px;border-bottom:1px solid #1e293b">{a['tip']}</td>
            <td style="padding:10px 12px;border-bottom:1px solid #1e293b">{a['modul']}</td>
            <td style="padding:10px 12px;border-bottom:1px solid #1e293b;font-weight:600">{a['ad']}</td>
            <td style="padding:10px 12px;border-bottom:1px solid #1e293b">{a['tarih']}</td>
            <td style="padding:10px 12px;border-bottom:1px solid #1e293b;color:{a['renk']};font-weight:600">{a['gun']}</td>
        </tr>""" for a in alerts])

        html = f"""<div style="font-family:Arial,sans-serif;background:#0f172a;color:#e2e8f0;padding:32px;border-radius:12px;max-width:700px;margin:0 auto">
            <div style="text-align:center;margin-bottom:28px">
                <div style="font-size:28px;font-weight:800;color:#00d4aa">{firm_name}</div>
                <div style="font-size:13px;color:#64748b;margin-top:4px">LabQMS Bildirim Raporu — {datetime.date.today().strftime('%d.%m.%Y')}</div>
            </div>
            <div style="background:#1e293b;border-radius:10px;overflow:hidden;margin-bottom:24px">
                <table style="width:100%;border-collapse:collapse;font-size:13px">
                    <thead><tr style="background:#0f172a">
                        <th style="padding:12px;text-align:left;color:#64748b">Durum</th>
                        <th style="padding:12px;text-align:left;color:#64748b">Modül</th>
                        <th style="padding:12px;text-align:left;color:#64748b">Ad</th>
                        <th style="padding:12px;text-align:left;color:#64748b">Tarih</th>
                        <th style="padding:12px;text-align:left;color:#64748b">Kalan</th>
                    </tr></thead>
                    <tbody>{rows}</tbody>
                </table>
            </div>
            <div style="text-align:center;font-size:12px;color:#475569">
                Bu mail <strong style="color:#00d4aa">{firm_name}</strong> LabQMS sistemi tarafından otomatik gönderilmiştir.<br>
                Toplam <strong style="color:#00d4aa">{len(alerts)}</strong> bildirim bulunmaktadır.
            </div>
        </div>"""

        result = resend.Emails.send({
            "from": "LabQMS <onboarding@resend.dev>",
            "to": emails,
            "subject": "[{}] LabQMS — {} Bildirim ({})".format(firm_name, len(alerts), datetime.date.today().strftime('%d.%m.%Y')),
            "html": html
        })
        print(f"Mail gonderildi: {result}")

    except Exception as e:
        print(f"Bildirim hatasi: {e}")

# ==================== SCHEDULER ====================
scheduler = BackgroundScheduler()

@app.on_event("startup")
def startup():
    try:
        init_db()
    except Exception as e:
        print(f"Startup DB hatasi: {e}")
    if RESEND_API_KEY:
        scheduler.add_job(check_and_send_notifications, 'cron', hour=8, minute=0)
        scheduler.start()
        print("Scheduler baslatildi - her gun 08:00")
    else:
        print("RESEND_API_KEY yok, scheduler baslatilmadi")

@app.on_event("shutdown")
def shutdown():
    if scheduler.running:
        scheduler.shutdown()

# ==================== API ====================
@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/api/send-notifications")
def send_notifications_now():
    try:
        check_and_send_notifications()
        return {"ok": True, "message": "Bildirimler gönderildi"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

class StoreItem(BaseModel):
    value: Any

@app.get("/api/store")
def get_all():
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT key, value FROM qms_store")
        return {row["key"]: row["value"] for row in cur.fetchall()}
    finally:
        conn.close()

@app.post("/api/store")
def set_all(data: dict):
    conn = get_conn()
    try:
        cur = conn.cursor()
        for key, value in data.items():
            cur.execute("""INSERT INTO qms_store (key, value) VALUES (%s, %s::jsonb)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
                (key, json.dumps(value)))
        conn.commit()
        return {"ok": True, "count": len(data)}
    finally:
        conn.close()

@app.get("/api/store/{key}")
def get_value(key: str):
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT value FROM qms_store WHERE key = %s", (key,))
        row = cur.fetchone()
        return {"key": key, "value": row["value"] if row else None}
    finally:
        conn.close()

@app.post("/api/store/{key}")
def set_value(key: str, item: StoreItem):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""INSERT INTO qms_store (key, value) VALUES (%s, %s::jsonb)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
            (key, json.dumps(item.value)))
        conn.commit()
        return {"ok": True, "key": key}
    finally:
        conn.close()

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def root():
    return FileResponse("static/index.html")
