from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI()


@app.get("/")
def root():
    return HTMLResponse("""
    <!DOCTYPE html>
    <html>
    <head><title>Test</title></head>
    <body style="font-family:sans-serif;padding:40px;">
        <h1>✅ Vercel + FastAPI works!</h1>
        <p>If you see this, routing is OK.</p>
        <p><a href="/api/health">Test /api/health</a></p>
        <p><a href="/api/test">Test /api/test</a></p>
    </body>
    </html>
    """)


@app.get("/api/health")
def health():
    return {"ok": True, "message": "hello from health"}


@app.get("/api/test")
def test():
    return {"ok": True, "message": "hello from test"}
