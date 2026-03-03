from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Any
import os, json, time
import psycopg2, psycopg2.extras, psycopg2.pool

app = FastAPI(title="QMS17025 API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DATABASE_URL = os.environ.get("DATABASE_URL", "")
_pool = None

def get_pool():
    global _pool
    if _pool is None:
        for attempt in range(5):
            try:
                # Neon SSL gerektirir
                _pool = psycopg2.pool.SimpleConnectionPool(
                    1, 10, DATABASE_URL,
                    sslmode='require'
                )
                print(f"DB baglantisi kuruldu (deneme {attempt+1})")
                break
            except Exception as e:
                print(f"DB baglanti hatasi (deneme {attempt+1}): {e}")
                if attempt < 4:
                    time.sleep(2)
    return _pool

def get_conn():
    return get_pool().getconn()

def put_conn(conn):
    get_pool().putconn(conn)

def init_db():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS qms_store (
            key TEXT PRIMARY KEY, value JSONB NOT NULL);""")
        conn.commit()
        print("DB tablosu hazir")
    finally:
        put_conn(conn)

@app.on_event("startup")
def startup():
    try:
        init_db()
    except Exception as e:
        print(f"Startup DB hatasi: {e}")

@app.get("/health")
def health():
    return {"status": "ok"}

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
        put_conn(conn)

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
        put_conn(conn)

@app.get("/api/store/{key}")
def get_value(key: str):
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT value FROM qms_store WHERE key = %s", (key,))
        row = cur.fetchone()
        return {"key": key, "value": row["value"] if row else None}
    finally:
        put_conn(conn)

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
        put_conn(conn)

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def root():
    return FileResponse("static/index.html")
