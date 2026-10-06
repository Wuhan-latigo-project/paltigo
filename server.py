# =====================================================================
# Paltigo Survey — All-in-one FastAPI server
# =====================================================================
# Contains:
#   • In-RAM storage (no database)
#   • /              → Survey page (bilingual EN/ZH)
#   • /dashboard     → Live dashboard with ALL answer details
#   • /api/survey    → receive a submission
#   • /api/survey/list, /count, /export, /clear
#   • /ws/live       → WebSocket for live dashboard updates
# =====================================================================

from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime
from typing import Any, Optional

from fastapi import (
    FastAPI, Request, HTTPException, WebSocket, WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel, Field

# =====================================================================
# CONFIG
# =====================================================================
HOST = "0.0.0.0"
PORT = 8080
MAX_SUBMISSIONS = 500

# =====================================================================
# IN-MEMORY STORE
# =====================================================================
_SUBMISSIONS: list[dict] = []
_LOCK = threading.Lock()
_NEXT_ID = [1]

# =====================================================================
# LIVE HUB (WebSocket broadcast)
# =====================================================================
class LiveHub:
    def __init__(self):
        self.sockets: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def register(self, ws: WebSocket) -> None:
        async with self._lock:
            self.sockets.add(ws)

    async def unregister(self, ws: WebSocket) -> None:
        async with self._lock:
            self.sockets.discard(ws)

    async def broadcast(self, item: dict) -> None:
        async with self._lock:
            dead = []
            for ws in self.sockets:
                try:
                    await ws.send_json(item)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self.sockets.discard(ws)


HUB = LiveHub()

# =====================================================================
# MODELS
# =====================================================================
class SurveySubmission(BaseModel):
    answers: dict[str, Any] = Field(...)
    language: Optional[str] = "en"
    user_agent: Optional[str] = None
    screen: Optional[str] = None
    referrer: Optional[str] = None

# =====================================================================
# APP
# =====================================================================
app = FastAPI(title="Paltigo Survey", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    real = request.headers.get("x-real-ip")
    if fwd:
        return fwd.split(",")[0].strip() or "unknown"
    if real:
        return real.strip()
    if request.client:
        return request.client.host
    return "unknown"


# =====================================================================
# POST /api/survey
# =====================================================================
@app.post("/api/survey")
async def receive_survey(payload: SurveySubmission, request: Request):
    if not isinstance(payload.answers, dict) or len(payload.answers) == 0:
        raise HTTPException(status_code=400, detail="answers is required")

    ip = _client_ip(request)
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    with _LOCK:
        item = {
            "id": _NEXT_ID[0],
            "created_at": now,
            "ip": ip,
            "language": payload.language or "en",
            "screen": payload.screen,
            "answers": payload.answers,
        }
        _NEXT_ID[0] += 1
        _SUBMISSIONS.append(item)
        if len(_SUBMISSIONS) > MAX_SUBMISSIONS:
            del _SUBMISSIONS[: len(_SUBMISSIONS) - MAX_SUBMISSIONS]

    try:
        await HUB.broadcast(item)
    except Exception as e:
        print(f"[hub] broadcast failed: {e}")

    print(f"[survey] #{item['id']} from {ip} "
          f"age={payload.answers.get('age')} "
          f"total={len(_SUBMISSIONS)}")

    return JSONResponse(
        status_code=200,
        content={"ok": True, "id": item["id"], "received_at": now},
    )


# =====================================================================
# GET /api/survey/count
# =====================================================================
@app.get("/api/survey/count")
def count_submissions():
    with _LOCK:
        total = len(_SUBMISSIONS)
    return {"total": total, "max": MAX_SUBMISSIONS}


# =====================================================================
# GET /api/survey/list
# =====================================================================
@app.get("/api/survey/list")
def list_submissions(limit: int = 500):
    limit = max(1, min(limit, MAX_SUBMISSIONS))
    with _LOCK:
        items = list(reversed(_SUBMISSIONS))[:limit]
    return {"count": len(items), "submissions": items}


# =====================================================================
# GET /api/survey/export
# =====================================================================
@app.get("/api/survey/export")
def export_submissions():
    with _LOCK:
        items = list(_SUBMISSIONS)
    return JSONResponse(
        status_code=200,
        content={
            "exported_at": datetime.utcnow().isoformat() + "Z",
            "total": len(items),
            "submissions": items,
        },
        headers={
            "Content-Disposition":
                'attachment; filename="paltigo_survey_export.json"',
        },
    )


# =====================================================================
# POST /api/survey/clear
# =====================================================================
@app.post("/api/survey/clear")
def clear_submissions():
    with _LOCK:
        n = len(_SUBMISSIONS)
        _SUBMISSIONS.clear()
    return {"ok": True, "cleared": n}


# =====================================================================
# WebSocket /ws/live
# =====================================================================
@app.websocket("/ws/live")
async def ws_live(ws: WebSocket):
    await ws.accept()
    await HUB.register(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[ws] error: {e}")
    finally:
        await HUB.unregister(ws)


# =====================================================================
# HTML — Survey page
# =====================================================================
SURVEY_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Paltigo · Dance Survey</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
    <link href="https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,400;14..32,500;14..32,600;14..32,700&display=swap" rel="stylesheet">
    <style>
        * { font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
        body {
            background: linear-gradient(145deg, #f8faff 0%, #eef3fe 100%);
            min-height: 100vh;
            display: flex; align-items: center; justify-content: center;
            padding: 2rem 1rem;
        }
        .survey-card {
            max-width: 780px; width: 100%;
            background: #ffffff;
            border-radius: 40px;
            box-shadow: 0 25px 50px -12px rgba(0, 27, 75, 0.25), 0 4px 18px 0 rgba(0, 0, 0, 0.05);
            padding: 3rem 2.8rem;
            border: 1px solid rgba(255, 255, 255, 0.6);
        }
        @media (max-width: 576px) { .survey-card { padding: 2rem 1.5rem; border-radius: 28px; } }
        .survey-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 2rem; }
        .logo-badge { display: flex; align-items: center; gap: 10px; }
        .logo-icon {
            background: #1e4bd2; color: white;
            width: 44px; height: 44px; border-radius: 16px;
            display: flex; align-items: center; justify-content: center;
            font-size: 1.6rem;
            box-shadow: 0 8px 16px -4px rgba(30, 75, 210, 0.3);
        }
        .logo-text { font-weight: 700; font-size: 1.5rem; letter-spacing: -0.02em; color: #0b1e4e; }
        .logo-text span { color: #1e4bd2; }
        .lang-switch { display: flex; gap: 6px; background: #f0f4fe; padding: 4px; border-radius: 40px; border: 1px solid #d9e2f2; }
        .lang-btn {
            border: none; background: transparent;
            padding: 8px 18px; border-radius: 30px;
            font-weight: 600; font-size: 0.9rem;
            color: #3a4e6b; cursor: pointer; transition: all 0.2s;
        }
        .lang-btn.active { background: #1e4bd2; color: white; box-shadow: 0 6px 14px -4px rgba(30, 75, 210, 0.4); }
        .lang-btn:hover:not(.active) { background: #e1e9fa; }
        .hero-image {
            border-radius: 28px; overflow: hidden; margin-bottom: 2.4rem;
            background: #d9e6ff; display: flex; align-items: center; justify-content: center;
            max-height: 180px;
        }
        .hero-image img { width: 100%; height: 180px; object-fit: cover; display: block; }
        .hero-fallback {
            width: 100%; height: 180px;
            background: linear-gradient(135deg, #1e4bd2 0%, #6a8cff 100%);
            display: flex; align-items: center; justify-content: center;
            color: white; font-size: 2rem; font-weight: 300;
            letter-spacing: 2px; gap: 12px;
        }
        .question-item { margin-bottom: 2.2rem; padding-bottom: 0.5rem; border-bottom: 1px solid #ecf1fa; }
        .question-item:last-child { border-bottom: none; }
        .q-label {
            font-weight: 600; font-size: 1.05rem; color: #0b1e4e;
            margin-bottom: 0.9rem; display: flex; align-items: center; gap: 10px; line-height: 1.4;
        }
        .q-badge {
            background: #1e4bd2; color: white;
            font-size: 0.7rem; font-weight: 700;
            padding: 3px 10px; border-radius: 30px;
            letter-spacing: 0.3px; white-space: nowrap;
        }
        .q-star { color: #f5b342; font-size: 1.1rem; margin-left: 4px; }
        .options-grid { display: flex; flex-wrap: wrap; gap: 10px 14px; margin-top: 8px; }
        .form-check { margin-right: 1.2rem; margin-bottom: 0.4rem; min-width: 130px; }
        .form-check-input { border-color: #cbd8ee; cursor: pointer; }
        .form-check-input:checked { background-color: #1e4bd2; border-color: #1e4bd2; }
        .form-check-label { color: #25415c; font-size: 0.95rem; cursor: pointer; }
        .form-select, .form-control {
            border-radius: 16px; border: 1.5px solid #dde6f5;
            padding: 12px 18px; font-size: 0.95rem;
            background: #fbfdff; color: #0b1e4e; transition: 0.15s;
        }
        .form-select:focus, .form-control:focus {
            border-color: #1e4bd2;
            box-shadow: 0 0 0 4px rgba(30, 75, 210, 0.12);
            background: #ffffff;
        }
        textarea.form-control { min-height: 130px; resize: vertical; line-height: 1.6; }
        .hint-text { font-size: 0.85rem; color: #6b7f9c; margin-bottom: 10px; margin-top: 4px; line-height: 1.5; font-style: italic; }
        .submit-area { margin-top: 2.8rem; display: flex; justify-content: center; }
        .btn-submit {
            background: #1e4bd2; border: none; color: white;
            padding: 16px 44px; border-radius: 60px;
            font-weight: 700; font-size: 1.1rem; letter-spacing: 0.3px;
            box-shadow: 0 16px 30px -10px rgba(30, 75, 210, 0.5);
            transition: all 0.2s; display: flex; align-items: center; gap: 10px;
        }
        .btn-submit:hover { background: #1239b0; transform: translateY(-2px); box-shadow: 0 22px 35px -12px rgba(30, 75, 210, 0.6); }
        .btn-submit i { font-size: 1.3rem; }
        .btn-submit:disabled { background: #a0b4e0; transform: none; cursor: not-allowed; }
        .thankyou-msg {
            display: none; background: #e7f0ff; padding: 2rem;
            border-radius: 30px; text-align: center;
            color: #0b1e4e; font-weight: 500; font-size: 1.2rem;
            border: 1px solid #b7cdf5; margin-top: 1.5rem;
        }
        .thankyou-msg i { font-size: 3rem; color: #1e4bd2; display: block; margin-bottom: 12px; }
        .lang-en, .lang-zh { display: none; }
        .lang-en.active, .lang-zh.active { display: block; }
        .lang-en-inline, .lang-zh-inline { display: none; }
        .lang-en-inline.active, .lang-zh-inline.active { display: inline; }
        .error-msg {
            display: none; background: #ffe9e9; color: #b91c1c;
            padding: 14px 20px; border-radius: 16px; margin-top: 1.5rem;
            border: 1px solid #fbcaca; text-align: center; font-weight: 500;
        }
    </style>
</head>
<body>
<div class="survey-card" id="surveyCard">
    <div class="survey-header">
        <div class="logo-badge">
            <div class="logo-icon"><i class="bi bi-person-arms-up"></i></div>
            <div class="logo-text">Pal<span>tigo</span></div>
        </div>
        <div class="lang-switch">
            <button class="lang-btn active" id="btnEn" onclick="setLanguage('en')">EN</button>
            <button class="lang-btn" id="btnZh" onclick="setLanguage('zh')">中文</button>
        </div>
    </div>
    <div class="hero-image">
        <img src="https://images.unsplash.com/photo-1547153760-18fc86324498?q=80&w=1200&auto=format&fit=crop"
             alt="Dancers" onerror="this.style.display='none'; this.parentElement.innerHTML='<div class=\'hero-fallback\'><i class=\'bi bi-music-note-beamed\'></i> DANCE · SURVEY</div>';">
    </div>
    <form id="surveyForm" onsubmit="submitSurvey(event);">

        <div class="question-item">
            <div class="q-label"><span class="q-badge">1</span>
                <span class="lang-en active">How old are you?</span>
                <span class="lang-zh">你多大了？</span>
            </div>
            <div class="lang-en active">
                <select class="form-select" id="q_age_en" data-q="age">
                    <option value="">Select an option</option>
                    <option value="under_16">Under 16</option>
                    <option value="16_18">16 – 18</option>
                    <option value="19_22">19 – 22</option>
                    <option value="23_26">23 – 26</option>
                    <option value="27_30">27 – 30</option>
                    <option value="31_40">31 – 40</option>
                    <option value="over_40">Over 40</option>
                </select>
            </div>
            <div class="lang-zh">
                <select class="form-select" id="q_age_zh" data-q="age">
                    <option value="">请选择</option>
                    <option value="under_16">16岁以下</option>
                    <option value="16_18">16 – 18岁</option>
                    <option value="19_22">19 – 22岁</option>
                    <option value="23_26">23 – 26岁</option>
                    <option value="27_30">27 – 30岁</option>
                    <option value="31_40">31 – 40岁</option>
                    <option value="over_40">40岁以上</option>
                </select>
            </div>
        </div>

        <div class="question-item">
            <div class="q-label"><span class="q-badge">2</span>
                <span class="lang-en active">How long have you been dancing? How often per week?</span>
                <span class="lang-zh">你跳舞多久了？每周几次？</span>
            </div>
            <div class="lang-en active">
                <select class="form-select" id="q1_en" data-q="q1">
                    <option value="">Select an option</option>
                    <option value="beginner_low">Under 6 months · 1-2/wk</option>
                    <option value="beginner_high">Under 6 months · 3+/wk</option>
                    <option value="intermediate_low">6mo-2y · 1-2/wk</option>
                    <option value="intermediate_high">6mo-2y · 3+/wk</option>
                    <option value="advanced_low">2y+ · 1-2/wk</option>
                    <option value="advanced_high">2y+ · 3+/wk</option>
                </select>
            </div>
            <div class="lang-zh">
                <select class="form-select" id="q1_zh" data-q="q1">
                    <option value="">请选择</option>
                    <option value="beginner_low">不到6个月 · 每周1-2次</option>
                    <option value="beginner_high">不到6个月 · 每周3次以上</option>
                    <option value="intermediate_low">6个月–2年 · 每周1-2次</option>
                    <option value="intermediate_high">6个月–2年 · 每周3次以上</option>
                    <option value="advanced_low">2年以上 · 每周1-2次</option>
                    <option value="advanced_high">2年以上 · 每周3次以上</option>
                </select>
            </div>
        </div>

        <div class="question-item">
            <div class="q-label"><span class="q-badge">3</span>
                <span class="lang-en active">How did you learn your last new dance?</span>
                <span class="lang-zh">你最近一次学新舞是怎么学的？</span>
            </div>
            <div class="options-grid lang-en active">
                <div class="form-check"><input class="form-check-input" type="radio" name="q2" id="q2a_en" value="douyin"><label class="form-check-label" for="q2a_en">Douyin</label></div>
                <div class="form-check"><input class="form-check-input" type="radio" name="q2" id="q2b_en" value="bilibili"><label class="form-check-label" for="q2b_en">Bilibili</label></div>
                <div class="form-check"><input class="form-check-input" type="radio" name="q2" id="q2c_en" value="studio"><label class="form-check-label" for="q2c_en">Studio class</label></div>
                <div class="form-check"><input class="form-check-input" type="radio" name="q2" id="q2d_en" value="friend"><label class="form-check-label" for="q2d_en">Friend</label></div>
                <div class="form-check"><input class="form-check-input" type="radio" name="q2" id="q2e_en" value="youtube"><label class="form-check-label" for="q2e_en">YouTube</label></div>
            </div>
            <div class="options-grid lang-zh">
                <div class="form-check"><input class="form-check-input" type="radio" name="q2" id="q2a_zh" value="douyin"><label class="form-check-label" for="q2a_zh">抖音</label></div>
                <div class="form-check"><input class="form-check-input" type="radio" name="q2" id="q2b_zh" value="bilibili"><label class="form-check-label" for="q2b_zh">哔哩哔哩</label></div>
                <div class="form-check"><input class="form-check-input" type="radio" name="q2" id="q2c_zh" value="studio"><label class="form-check-label" for="q2c_zh">舞蹈教室</label></div>
                <div class="form-check"><input class="form-check-input" type="radio" name="q2" id="q2d_zh" value="friend"><label class="form-check-label" for="q2d_zh">朋友</label></div>
                <div class="form-check"><input class="form-check-input" type="radio" name="q2" id="q2e_zh" value="youtube"><label class="form-check-label" for="q2e_zh">YouTube</label></div>
            </div>
        </div>

        <div class="question-item">
            <div class="q-label"><span class="q-badge">4</span>
                <span class="lang-en active">Biggest challenge when learning a new dance? <i class="bi bi-star-fill q-star"></i></span>
                <span class="lang-zh">学新舞时，你最大的挑战是什么？ <i class="bi bi-star-fill q-star"></i></span>
            </div>
            <div class="lang-en active">
                <select class="form-select" id="q3_en" data-q="q3">
                    <option value="">Select an option</option>
                    <option value="not_sure_correct">I don't know if I'm doing it correctly</option>
                    <option value="dont_see_myself">I can't see myself clearly</option>
                    <option value="dont_know_mistakes">I don't know where I went wrong</option>
                    <option value="no_feedback">No one gives me feedback</option>
                    <option value="too_fast">The moves are too fast</option>
                    <option value="no_time">I don't have time</option>
                    <option value="other">Other</option>
                </select>
            </div>
            <div class="lang-zh">
                <select class="form-select" id="q3_zh" data-q="q3">
                    <option value="">请选择</option>
                    <option value="not_sure_correct">我不知道自己跳得对不对</option>
                    <option value="dont_see_myself">我看不清自己的动作</option>
                    <option value="dont_know_mistakes">我不知道哪里做错了</option>
                    <option value="no_feedback">没有人给我反馈</option>
                    <option value="too_fast">动作太快了</option>
                    <option value="no_time">我没有时间</option>
                    <option value="other">其他</option>
                </select>
            </div>
        </div>

        <div class="question-item">
            <div class="q-label"><span class="q-badge">5</span>
                <span class="lang-en active">Do you post dance videos on social media?</span>
                <span class="lang-zh">你会把舞蹈视频发到社交平台吗？</span>
            </div>
            <div class="lang-en active">
                <select class="form-select" id="q5_en" data-q="q5">
                    <option value="">Select an option</option>
                    <option value="yes_douyin">Yes – Douyin / Xiaohongshu</option>
                    <option value="yes_other">Yes – other</option>
                    <option value="sometimes">Sometimes</option>
                    <option value="no">No, I don't post</option>
                </select>
            </div>
            <div class="lang-zh">
                <select class="form-select" id="q5_zh" data-q="q5">
                    <option value="">请选择</option>
                    <option value="yes_douyin">会 – 抖音/小红书</option>
                    <option value="yes_other">会 – 其他</option>
                    <option value="sometimes">偶尔发</option>
                    <option value="no">不发</option>
                </select>
            </div>
        </div>

        <div class="question-item">
            <div class="q-label"><span class="q-badge">6</span>
                <span class="lang-en active">Monthly spending on dance learning? <i class="bi bi-star-fill q-star"></i></span>
                <span class="lang-zh">每月在学舞上花多少钱？ <i class="bi bi-star-fill q-star"></i></span>
            </div>
            <div class="lang-en active">
                <select class="form-select" id="q6_en" data-q="q6">
                    <option value="">Select an option</option>
                    <option value="0">I don't spend money</option>
                    <option value="under100">Under ¥100</option>
                    <option value="100-300">¥100 – ¥300</option>
                    <option value="300-500">¥300 – ¥500</option>
                    <option value="500-1000">¥500 – ¥1,000</option>
                    <option value="over1000">Over ¥1,000</option>
                </select>
            </div>
            <div class="lang-zh">
                <select class="form-select" id="q6_zh" data-q="q6">
                    <option value="">请选择</option>
                    <option value="0">不花钱</option>
                    <option value="under100">100元以下</option>
                    <option value="100-300">100–300元</option>
                    <option value="300-500">300–500元</option>
                    <option value="500-1000">500–1000元</option>
                    <option value="over1000">1000元以上</option>
                </select>
            </div>
        </div>

        <div class="question-item">
            <div class="q-label"><span class="q-badge">7</span>
                <span class="lang-en active">Have you tried apps/tools to improve your dance?</span>
                <span class="lang-zh">你试过用应用或工具来提升舞蹈吗？</span>
            </div>
            <div class="lang-en active">
                <select class="form-select" id="q7_en" data-q="q7">
                    <option value="">Select an option</option>
                    <option value="yes_too_complex">Yes – too complex</option>
                    <option value="yes_too_expensive">Yes – too expensive</option>
                    <option value="yes_not_accurate">Yes – not accurate</option>
                    <option value="yes_english">Yes – only English</option>
                    <option value="no_want">No, but I want to</option>
                    <option value="no_never">No, never</option>
                </select>
            </div>
            <div class="lang-zh">
                <select class="form-select" id="q7_zh" data-q="q7">
                    <option value="">请选择</option>
                    <option value="yes_too_complex">试过 – 太复杂</option>
                    <option value="yes_too_expensive">试过 – 太贵</option>
                    <option value="yes_not_accurate">试过 – 不够准确</option>
                    <option value="yes_english">试过 – 只有英文</option>
                    <option value="no_want">没试过，但想试</option>
                    <option value="no_never">没试过</option>
                </select>
            </div>
        </div>

        <div class="question-item">
            <div class="q-label"><span class="q-badge">8</span>
                <span class="lang-en active">Top 3 features you'd want in a dance analysis app?</span>
                <span class="lang-zh">你最想要哪3个功能？</span>
            </div>
            <div class="lang-en active">
                <div class="options-grid">
                    <div class="form-check"><input class="form-check-input q8-check" type="checkbox" id="feat1_en" value="accurate_scoring"><label class="form-check-label" for="feat1_en">Accurate scoring</label></div>
                    <div class="form-check"><input class="form-check-input q8-check" type="checkbox" id="feat2_en" value="show_mistakes"><label class="form-check-label" for="feat2_en">Show my mistakes</label></div>
                    <div class="form-check"><input class="form-check-input q8-check" type="checkbox" id="feat3_en" value="compare_reference"><label class="form-check-label" for="feat3_en">Compare with reference</label></div>
                    <div class="form-check"><input class="form-check-input q8-check" type="checkbox" id="feat4_en" value="multi_angle"><label class="form-check-label" for="feat4_en">Multi-angle recording</label></div>
                    <div class="form-check"><input class="form-check-input q8-check" type="checkbox" id="feat5_en" value="progress_tracking"><label class="form-check-label" for="feat5_en">Progress tracking</label></div>
                    <div class="form-check"><input class="form-check-input q8-check" type="checkbox" id="feat6_en" value="social_share"><label class="form-check-label" for="feat6_en">Share on social media</label></div>
                    <div class="form-check"><input class="form-check-input q8-check" type="checkbox" id="feat7_en" value="tutorials"><label class="form-check-label" for="feat7_en">Tutorials</label></div>
                </div>
            </div>
            <div class="lang-zh">
                <div class="options-grid">
                    <div class="form-check"><input class="form-check-input q8-check" type="checkbox" id="feat1_zh" value="accurate_scoring"><label class="form-check-label" for="feat1_zh">精准评分</label></div>
                    <div class="form-check"><input class="form-check-input q8-check" type="checkbox" id="feat2_zh" value="show_mistakes"><label class="form-check-label" for="feat2_zh">展示错误</label></div>
                    <div class="form-check"><input class="form-check-input q8-check" type="checkbox" id="feat3_zh" value="compare_reference"><label class="form-check-label" for="feat3_zh">与原版对比</label></div>
                    <div class="form-check"><input class="form-check-input q8-check" type="checkbox" id="feat4_zh" value="multi_angle"><label class="form-check-label" for="feat4_zh">多角度录制</label></div>
                    <div class="form-check"><input class="form-check-input q8-check" type="checkbox" id="feat5_zh" value="progress_tracking"><label class="form-check-label" for="feat5_zh">进度追踪</label></div>
                    <div class="form-check"><input class="form-check-input q8-check" type="checkbox" id="feat6_zh" value="social_share"><label class="form-check-label" for="feat6_zh">社交分享</label></div>
                    <div class="form-check"><input class="form-check-input q8-check" type="checkbox" id="feat7_zh" value="tutorials"><label class="form-check-label" for="feat7_zh">教学视频</label></div>
                </div>
            </div>
        </div>

        <div class="question-item">
            <div class="q-label"><span class="q-badge">9</span>
                <span class="lang-en active">How much would you pay per month? <i class="bi bi-star-fill q-star"></i></span>
                <span class="lang-zh">每月愿意付多少钱？ <i class="bi bi-star-fill q-star"></i></span>
            </div>
            <div class="lang-en active">
                <select class="form-select" id="q9_en" data-q="q9">
                    <option value="">Select an option</option>
                    <option value="free">Free only</option>
                    <option value="10-30">¥10 – ¥30</option>
                    <option value="30-50">¥30 – ¥50</option>
                    <option value="50-100">¥50 – ¥100</option>
                    <option value="100-200">¥100 – ¥200</option>
                    <option value="over200">Over ¥200</option>
                </select>
            </div>
            <div class="lang-zh">
                <select class="form-select" id="q9_zh" data-q="q9">
                    <option value="">请选择</option>
                    <option value="free">只接受免费</option>
                    <option value="10-30">10–30元</option>
                    <option value="30-50">30–50元</option>
                    <option value="50-100">50–100元</option>
                    <option value="100-200">100–200元</option>
                    <option value="over200">200元以上</option>
                </select>
            </div>
        </div>

        <div class="question-item">
            <div class="q-label"><span class="q-badge">10</span>
                <span class="lang-en active">What would make you use the app daily?</span>
                <span class="lang-zh">什么会让你每天使用？</span>
            </div>
            <div class="lang-en active">
                <select class="form-select" id="q10_en" data-q="q10">
                    <option value="">Select an option</option>
                    <option value="instant_feedback">Instant feedback</option>
                    <option value="compare_friends">Compare with friends</option>
                    <option value="daily_challenges">Daily challenges</option>
                    <option value="progress_tracking">Progress tracking</option>
                    <option value="new_content">New content</option>
                    <option value="community">Community</option>
                </select>
            </div>
            <div class="lang-zh">
                <select class="form-select" id="q10_zh" data-q="q10">
                    <option value="">请选择</option>
                    <option value="instant_feedback">即时反馈</option>
                    <option value="compare_friends">和朋友比较</option>
                    <option value="daily_challenges">每日挑战</option>
                    <option value="progress_tracking">进度追踪</option>
                    <option value="new_content">新内容</option>
                    <option value="community">社区</option>
                </select>
            </div>
        </div>

        <div class="question-item">
            <div class="q-label"><span class="q-badge">11</span>
                <span class="lang-en active">What is your dream dance app? <i class="bi bi-stars q-star"></i></span>
                <span class="lang-zh">你梦想中的舞蹈应用是什么样的？ <i class="bi bi-stars q-star"></i></span>
            </div>
            <div class="lang-en active">
                <div class="hint-text">
                    Close your eyes. Imagine an app built <strong>just for you</strong> — one that understands exactly what you need when you dance. It could be a feature you've always wished existed. It could be something that feels impossible today. It could be a tiny detail that would make your practice feel magical. Tell us in your own words — there is no wrong answer. <em>The more honest you are, the more likely we can build it.</em>
                </div>
                <textarea class="form-control" id="dream_en" data-q="dream_app" rows="5" maxlength="2000"
                    placeholder="Example: I wish there was an app that... it would show me... I would love it if..."></textarea>
            </div>
            <div class="lang-zh">
                <div class="hint-text">
                    闭上眼睛，想象一款<strong>专为你打造</strong>的应用 —— 它完全懂你跳舞时的需要。它可以是某个你一直希望存在的功能，可以是今天觉得不可能的东西，也可以是某个小细节，让你的练习变得特别。用你自己的话告诉我们 —— 没有错误的答案。<em>你越真诚，我们越有可能把它做出来。</em>
                </div>
                <textarea class="form-control" id="dream_zh" data-q="dream_app" rows="5" maxlength="2000"
                    placeholder="例如：我希望有一款应用……它会告诉我……如果能有……我会很喜欢"></textarea>
            </div>
        </div>

        <div class="error-msg" id="errorMsg"></div>

        <div class="submit-area">
            <button type="submit" class="btn-submit" id="submitBtn">
                <i class="bi bi-send-fill"></i>
                <span class="lang-en-inline active" id="btnTextEn">Submit survey</span>
                <span class="lang-zh-inline" id="btnTextZh">提交问卷</span>
            </button>
        </div>
    </form>

    <div class="thankyou-msg" id="thankYouMsg">
        <i class="bi bi-check-circle-fill"></i>
        <span class="lang-en-inline active" id="thankEn">Thank you! 💙</span>
        <span class="lang-zh-inline" id="thankZh">谢谢！💙</span>
    </div>
</div>

<script>
    function setLanguage(lang) {
        document.getElementById('btnEn').classList.toggle('active', lang === 'en');
        document.getElementById('btnZh').classList.toggle('active', lang === 'zh');
        document.querySelectorAll('.lang-en, .lang-zh').forEach(el => {
            el.classList.toggle('active', el.classList.contains('lang-' + lang));
        });
        document.querySelectorAll('.lang-en-inline, .lang-zh-inline').forEach(el => {
            el.classList.toggle('active', el.classList.contains('lang-' + lang + '-inline'));
        });
    }

    function collectAnswers() {
        const answers = {};
        document.querySelectorAll('select[data-q]').forEach(sel => {
            const key = sel.getAttribute('data-q');
            if (!answers[key] && sel.value) answers[key] = sel.value;
        });
        ['age','q1','q3','q5','q6','q7','q9','q10'].forEach(k => {
            if (!(k in answers)) answers[k] = null;
        });
        const q2 = document.querySelector('input[name="q2"]:checked');
        answers.q2 = q2 ? q2.value : null;
        const q8set = new Set();
        document.querySelectorAll('.q8-check:checked').forEach(cb => q8set.add(cb.value));
        answers.q8 = Array.from(q8set);
        const activeLang = document.getElementById('btnEn').classList.contains('active') ? 'en' : 'zh';
        const dreamEn = document.getElementById('dream_en').value.trim();
        const dreamZh = document.getElementById('dream_zh').value.trim();
        let dreamText = '';
        if (activeLang === 'en' && dreamEn) dreamText = dreamEn;
        else if (activeLang === 'zh' && dreamZh) dreamText = dreamZh;
        else dreamText = dreamEn || dreamZh;
        answers.dream_app = dreamText || null;
        return answers;
    }

    async function submitSurvey(event) {
        event.preventDefault();
        const btn = document.getElementById('submitBtn');
        const errBox = document.getElementById('errorMsg');
        errBox.style.display = 'none';
        const answers = collectAnswers();
        const missing = [];
        ['age','q1','q2','q3','q5','q6','q7','q9','q10'].forEach(k => {
            if (!answers[k]) missing.push(k);
        });
        if (!answers.q8 || answers.q8.length === 0) missing.push('q8');
        if (!answers.dream_app) missing.push('dream_app');
        if (missing.length) {
            errBox.textContent = "Please answer all questions. Missing: " + missing.join(", ");
            errBox.style.display = 'block';
            return;
        }
        btn.disabled = true;
        btn.querySelector('.lang-en-inline').textContent = 'Sending...';
        btn.querySelector('.lang-zh-inline').textContent = '提交中...';
        try {
            const res = await fetch('/api/survey', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    answers, language: document.getElementById('btnEn').classList.contains('active') ? 'en' : 'zh',
                    user_agent: navigator.userAgent,
                    screen: `${screen.width}x${screen.height}`,
                    referrer: document.referrer || null,
                }),
            });
            if (!res.ok) throw new Error(await res.text() || ('HTTP ' + res.status));
            document.getElementById('surveyForm').style.display = 'none';
            document.getElementById('thankYouMsg').style.display = 'block';
            document.getElementById('surveyCard').scrollIntoView({ behavior: 'smooth', block: 'start' });
        } catch (err) {
            errBox.textContent = "Error: " + err.message;
            errBox.style.display = 'block';
            btn.disabled = false;
            btn.querySelector('.lang-en-inline').textContent = 'Submit survey';
            btn.querySelector('.lang-zh-inline').textContent = '提交问卷';
        }
    }

    document.addEventListener('DOMContentLoaded', () => setLanguage('en'));
</script>
</body>
</html>
"""


# =====================================================================
# HTML — Dashboard page (with ALL answer details)
# =====================================================================
DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Paltigo · Live Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * { font-family: 'Inter', sans-serif; }
        body { background: #0f1729; color: #e2e8f0; min-height: 100vh; padding: 2rem; }
        .container { max-width: 1100px; margin: 0 auto; }
        .top-bar {
            display: flex; align-items: center; justify-content: space-between;
            margin-bottom: 1.5rem; flex-wrap: wrap; gap: 1rem;
        }
        .title { font-size: 1.6rem; font-weight: 700; color: #fff; display: flex; align-items: center; gap: 12px; }
        .title i { color: #60a5fa; }
        .status-dot {
            display: inline-block; width: 10px; height: 10px;
            border-radius: 50%; background: #ef4444; margin-right: 6px; transition: background 0.2s;
        }
        .status-dot.online { background: #22c55e; }
        .stats { display: flex; gap: 12px; flex-wrap: wrap; }
        .stat-pill {
            background: #1a2234; border: 1px solid #253046;
            padding: 8px 16px; border-radius: 30px; font-size: 0.85rem; color: #94a3b8;
        }
        .stat-pill b { color: #fff; margin-left: 6px; }
        .btn-action {
            background: #1e4bd2; border: none; color: white;
            padding: 8px 18px; border-radius: 30px;
            font-size: 0.85rem; font-weight: 600; cursor: pointer; transition: all 0.15s;
            text-decoration: none; display: inline-flex; align-items: center; gap: 6px;
        }
        .btn-action:hover { background: #1239b0; color: white; }
        .btn-clear { background: #7f1d1d; }
        .btn-clear:hover { background: #b91c1c; }

        .notif-card {
            background: #141c2e; border: 1px solid #253046;
            border-radius: 18px; padding: 22px 26px; margin-bottom: 16px;
            animation: slideIn 0.35s ease; transition: all 0.2s;
        }
        .notif-card:hover { border-color: #60a5fa; }
        .notif-card.unseen { border-left: 4px solid #60a5fa; background: #16223a; }
        @keyframes slideIn {
            from { opacity: 0; transform: translateY(-12px); }
            to { opacity: 1; transform: translateY(0); }
        }
        @keyframes pulse {
            0%, 100% { box-shadow: 0 0 0 0 rgba(96, 165, 250, 0.5); }
            50% { box-shadow: 0 0 0 12px rgba(96, 165, 250, 0); }
        }
        .notif-card.flash { animation: slideIn 0.35s ease, pulse 1.2s ease; }

        .notif-header {
            display: flex; justify-content: space-between; align-items: center;
            margin-bottom: 16px; flex-wrap: wrap; gap: 8px;
            padding-bottom: 12px; border-bottom: 1px solid #253046;
        }
        .notif-id { font-weight: 700; color: #60a5fa; font-size: 1.15rem; }
        .notif-meta-top { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
        .notif-time { color: #64748b; font-size: 0.82rem; }

        .answer-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 12px 20px;
            margin-bottom: 16px;
        }
        @media (max-width: 700px) {
            .answer-grid { grid-template-columns: 1fr; }
        }

        .answer-row {
            display: flex;
            flex-direction: column;
            gap: 4px;
        }
        .answer-label {
            font-size: 0.72rem;
            color: #64748b;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            font-weight: 600;
        }
        .answer-value {
            font-size: 0.9rem;
            color: #e2e8f0;
            font-weight: 500;
            padding: 6px 12px;
            background: #0b1220;
            border-radius: 8px;
            border: 1px solid #1e293b;
            word-break: break-word;
        }
        .answer-value.empty { color: #475569; font-style: italic; }

        .answer-row.star .answer-label { color: #fbbf24; }
        .answer-row.star .answer-value {
            border-color: #78350f;
            background: #1c1410;
            color: #fde68a;
        }

        .feature-chips {
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
        }
        .feature-chip {
            background: #1e3a8a;
            color: #bfdbfe;
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 0.78rem;
            border: 1px solid #2563eb;
            font-weight: 500;
        }

        .dream-section {
            margin-top: 16px;
            padding-top: 16px;
            border-top: 1px dashed #253046;
        }
        .dream-label {
            color: #ec4899;
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 1px;
            text-transform: uppercase;
            margin-bottom: 8px;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .dream-box {
            background: #0b1220;
            border-left: 3px solid #ec4899;
            padding: 14px 18px;
            border-radius: 10px;
            color: #e2e8f0;
            font-size: 0.95rem;
            line-height: 1.6;
            white-space: pre-wrap;
            word-break: break-word;
        }
        .dream-box.empty { color: #475569; font-style: italic; }

        .ip-chip {
            background: #1e293b;
            color: #94a3b8;
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 0.75rem;
            border: 1px solid #334155;
            font-family: monospace;
        }

        .empty {
            text-align: center;
            padding: 4rem 1rem;
            color: #475569;
        }
        .empty i { font-size: 3rem; color: #334155; display: block; margin-bottom: 12px; }
    </style>
</head>
<body>
<div class="container">
    <div class="top-bar">
        <div class="title"><i class="bi bi-bell-fill"></i> Paltigo · Live Dashboard</div>
        <div class="stats">
            <div class="stat-pill"><span class="status-dot" id="wsDot"></span><span id="wsLabel">connecting…</span></div>
            <div class="stat-pill">Total <b id="statTotal">0</b></div>
            <div class="stat-pill">Max <b id="statMax">500</b></div>
        </div>
        <div style="display: flex; gap: 8px;">
            <a class="btn-action" href="/api/survey/export"><i class="bi bi-download"></i> Export</a>
            <button class="btn-action btn-clear" onclick="clearAll()"><i class="bi bi-trash"></i> Clear</button>
        </div>
    </div>
    <div id="list"></div>
</div>

<script>
    const list = document.getElementById('list');
    let items = [];

    const LABELS = {
        "under_16": "Under 16", "16_18": "16–18", "19_22": "19–22",
        "23_26": "23–26", "27_30": "27–30", "31_40": "31–40", "over_40": "Over 40",
        "beginner_low": "Beginner · 1-2×/wk",
        "beginner_high": "Beginner · 3+×/wk",
        "intermediate_low": "Intermediate · 1-2×/wk",
        "intermediate_high": "Intermediate · 3+×/wk",
        "advanced_low": "Advanced · 1-2×/wk",
        "advanced_high": "Advanced · 3+×/wk",
        "douyin": "Douyin", "bilibili": "Bilibili", "studio": "Studio class",
        "friend": "From a friend", "youtube": "YouTube",
        "not_sure_correct": "Doesn't know if doing correctly",
        "dont_see_myself": "Can't see herself clearly",
        "dont_know_mistakes": "Doesn't know where mistakes are",
        "no_feedback": "No feedback from anyone",
        "too_fast": "Moves are too fast",
        "no_time": "No time",
        "other": "Other",
        "yes_douyin": "Yes – Douyin/Xiaohongshu",
        "yes_other": "Yes – other platforms",
        "sometimes": "Sometimes",
        "no": "No",
        "0": "Nothing", "under100": "Under ¥100",
        "100-300": "¥100–300", "300-500": "¥300–500",
        "500-1000": "¥500–1,000", "over1000": "Over ¥1,000",
        "yes_too_complex": "Tried – too complex",
        "yes_too_expensive": "Tried – too expensive",
        "yes_not_accurate": "Tried – not accurate",
        "yes_english": "Tried – only in English",
        "no_want": "Never tried, but wants to",
        "no_never": "Never tried",
        "accurate_scoring": "Accurate scoring",
        "show_mistakes": "Show mistakes",
        "compare_reference": "Compare with reference",
        "multi_angle": "Multi-angle recording",
        "progress_tracking": "Progress tracking",
        "social_share": "Share on social media",
        "tutorials": "Tutorials",
        "free": "Free only",
        "10-30": "¥10–30", "30-50": "¥30–50",
        "50-100": "¥50–100", "100-200": "¥100–200",
        "over200": "Over ¥200",
        "instant_feedback": "Instant feedback",
        "compare_friends": "Compare with friends",
        "daily_challenges": "Daily challenges",
        "new_content": "New content",
        "community": "Community",
    };

    function label(v) {
        if (v === null || v === undefined || v === "") return "—";
        return LABELS[v] || v;
    }

    function connectWS() {
        const proto = location.protocol === 'https:' ? 'wss' : 'ws';
        const ws = new WebSocket(`${proto}://${location.host}/ws/live`);
        ws.onopen = () => {
            document.getElementById('wsDot').classList.add('online');
            document.getElementById('wsLabel').textContent = 'live';
        };
        ws.onclose = () => {
            document.getElementById('wsDot').classList.remove('online');
            document.getElementById('wsLabel').textContent = 'reconnecting…';
            setTimeout(connectWS, 2000);
        };
        ws.onerror = () => ws.close();
        ws.onmessage = (ev) => {
            try {
                const item = JSON.parse(ev.data);
                items.unshift(item);
                render(true);
                refreshCount();
            } catch (e) {}
        };
    }

    function escapeHtml(s) {
        return String(s ?? '').replace(/[&<>"']/g, c => ({
            '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
        }[c]));
    }

    function fmtTime(iso) {
        if (!iso) return '—';
        try { return new Date(iso).toLocaleString(); } catch { return iso; }
    }

    function answerRow(labelText, value, isStar = false) {
        const isEmpty = value === null || value === undefined || value === "" ||
                        (Array.isArray(value) && value.length === 0);
        const cls = `answer-row${isStar ? ' star' : ''}`;

        if (Array.isArray(value) && value.length > 0) {
            const chips = value.map(v =>
                `<span class="feature-chip">${escapeHtml(label(v))}</span>`
            ).join('');
            return `
                <div class="${cls}">
                    <div class="answer-label">${escapeHtml(labelText)}</div>
                    <div class="feature-chips">${chips}</div>
                </div>`;
        }

        const valCls = `answer-value${isEmpty ? ' empty' : ''}`;
        const display = escapeHtml(label(value));
        return `
            <div class="${cls}">
                <div class="answer-label">${escapeHtml(labelText)}</div>
                <div class="${valCls}">${display}</div>
            </div>`;
    }

    function render(flashFirst = false) {
        if (!items.length) {
            list.innerHTML = `<div class="empty"><i class="bi bi-inbox"></i>Waiting for the first survey submission…</div>`;
            return;
        }
        list.innerHTML = items.map((n, idx) => {
            const a = n.answers || {};
            const flash = (flashFirst && idx === 0) ? 'flash' : '';
            const dream = (a.dream_app || '').trim();

            const dreamHtml = `
                <div class="dream-section">
                    <div class="dream-label"><i class="bi bi-stars"></i> Dream dance app</div>
                    <div class="dream-box ${dream ? '' : 'empty'}">${dream ? escapeHtml(dream) : '— no answer —'}</div>
                </div>`;

            return `
                <div class="notif-card ${flash}">
                    <div class="notif-header">
                        <div class="notif-id">#${n.id}</div>
                        <div class="notif-meta-top">
                            <span class="ip-chip"><i class="bi bi-wifi"></i> ${escapeHtml(n.ip || '—')}</span>
                            <span class="ip-chip">${escapeHtml(n.language || '—')}</span>
                            <span class="notif-time">${fmtTime(n.created_at)}</span>
                        </div>
                    </div>

                    <div class="answer-grid">
                        ${answerRow("Age", a.age)}
                        ${answerRow("Experience & practice", a.q1)}
                        ${answerRow("Learned last dance via", a.q2)}
                        ${answerRow("Biggest challenge", a.q3, true)}
                        ${answerRow("Posts videos", a.q5)}
                        ${answerRow("Monthly spending", a.q6, true)}
                        ${answerRow("Prior tools experience", a.q7)}
                        ${answerRow("Wanted features", a.q8)}
                        ${answerRow("Price willingness", a.q9, true)}
                        ${answerRow("Retention driver", a.q10)}
                    </div>

                    ${dreamHtml}
                </div>`;
        }).join('');
    }

    async function loadInitial() {
        try {
            const r = await fetch('/api/survey/list');
            const j = await r.json();
            items = j.submissions || [];
            render(false);
            refreshCount();
        } catch (e) { console.error(e); }
    }

    async function refreshCount() {
        try {
            const r = await fetch('/api/survey/count');
            const j = await r.json();
            document.getElementById('statTotal').textContent = j.total;
            document.getElementById('statMax').textContent = j.max;
        } catch {}
    }

    async function clearAll() {
        if (!confirm('Clear all submissions from RAM? This cannot be undone.')) return;
        await fetch('/api/survey/clear', { method: 'POST' });
        items = [];
        render();
        refreshCount();
    }

    connectWS();
    loadInitial();
    setInterval(refreshCount, 15000);
</script>
</body>
</html>
"""


# =====================================================================
# ROUTES — serve the embedded HTML
# =====================================================================
@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(SURVEY_HTML)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    return HTMLResponse(DASHBOARD_HTML)


# =====================================================================
# ENTRY
# =====================================================================
if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print("  Paltigo Survey — All-in-one")
    print(f"  Survey    : http://{HOST}:{PORT}/")
    print(f"  Dashboard : http://{HOST}:{PORT}/dashboard")
    print(f"  RAM max   : {MAX_SUBMISSIONS} submissions")
    print("=" * 60)
    uvicorn.run(app, host=HOST, port=PORT)