"""Admin portal API: read-only view of everything doctors do in the simulation.

All routes except /login require a Bearer token obtained with ADMIN_PASSWORD.
"""
import base64
import csv
import hmac
import hashlib
import io
import os
import re
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from db import sb

router = APIRouter(prefix="/api/admin")

# ---------------------------------------------------------------- auth ----
PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
SECRET = (os.environ.get("ADMIN_SECRET") or (PASSWORD + os.environ.get("SUPABASE_KEY", ""))).encode()
TOKEN_TTL = 12 * 3600
_fails: dict[str, list[float]] = defaultdict(list)


def _sign(body: str) -> str:
    return hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()


def make_token() -> str:
    body = str(int(time.time()) + TOKEN_TTL)
    return f"{body}.{_sign(body)}"


def valid_token(tok: str) -> bool:
    try:
        body, sig = tok.split(".", 1)
        return hmac.compare_digest(sig, _sign(body)) and int(body) > time.time()
    except Exception:
        return False


def require_admin(authorization: str = Header(default="")):
    if not PASSWORD:
        raise HTTPException(503, "Admin portal is disabled. Set ADMIN_PASSWORD in .env and restart.")
    tok = authorization.removeprefix("Bearer ").strip()
    if not valid_token(tok):
        raise HTTPException(401, "Not signed in")


class LoginIn(BaseModel):
    password: str


@router.post("/login")
def login(body: LoginIn, request: Request):
    if not PASSWORD:
        raise HTTPException(503, "Admin portal is disabled. Set ADMIN_PASSWORD in .env and restart.")
    ip = request.client.host if request.client else "?"
    now = time.time()
    _fails[ip] = [t for t in _fails[ip] if now - t < 300]
    if len(_fails[ip]) >= 5:
        raise HTTPException(429, "Too many attempts. Try again in a few minutes.")
    if not hmac.compare_digest(body.password.encode(), PASSWORD.encode()):
        _fails[ip].append(now)
        time.sleep(0.5)
        raise HTTPException(401, "Wrong password")
    return {"token": make_token(), "expires_in": TOKEN_TTL}


@router.get("/me", dependencies=[Depends(require_admin)])
def me():
    return {"ok": True}


# ---------------------------------------------------------------- data ----
def parse_ts(v) -> Optional[datetime]:
    if not v:
        return None
    s = str(v).strip().replace("Z", "+00:00")
    m = re.match(r"^(.*?T\d\d:\d\d:\d\d)(\.\d+)?(.*)$", s)
    if m:  # normalise fractional seconds to 6 digits for fromisoformat
        frac = (m.group(2) or ".0")[1:7].ljust(6, "0")
        s = f"{m.group(1)}.{frac}{m.group(3)}"
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def fetch_all(table: str, order: str) -> list[dict]:
    """Page through a table (PostgREST caps each response at 1000 rows)."""
    out, start, step = [], 0, 1000
    while True:
        rows = sb.table(table).select("*").order(order).range(start, start + step - 1).execute().data
        out += rows
        if len(rows) < step:
            return out
        start += step


_cache: dict[str, tuple[float, list]] = {}


def load(table: str, order: str) -> list[dict]:
    hit = _cache.get(table)
    if hit and time.time() - hit[0] < 3:  # 3s cache so several panels can share one read
        return hit[1]
    rows = fetch_all(table, order)
    _cache[table] = (time.time(), rows)
    return rows


def event_time(e: dict) -> datetime:
    """Device time when trustworthy, server time otherwise.

    A device clock that is ahead of the server is wrong by definition, so those fall back to
    created_at. Earlier is fine: it just means the batch was uploaded late.
    """
    server = parse_ts(e.get("created_at"))
    dev = parse_ts(e.get("client_ts"))
    if dev and server and dev <= server + timedelta(seconds=60):
        return dev
    return server or dev or datetime.now(timezone.utc)


DOCTOR_COLS = ["id", "code", "age", "gender", "degree", "degree_other", "specialty", "years_since_mbbs",
               "designation", "designation_other", "patient_setting", "patient_setting_other",
               "ai_allowed", "ai_use_any", "ai_use_clinical", "created_at"]


def dname(d: dict) -> str:
    """Participants are identified by the code the team gave them; fall back to the old name field."""
    return d.get("code") or d.get("name") or (f"Anonymous {str(d['id'])[:6]}" if d.get("id") else None)


class World:
    """One consistent snapshot of every table, with lookups."""

    def __init__(self):
        self.doctors = load("doctors", "created_at")
        self.sessions = load("sessions", "started_at")
        self.events = load("events", "id")
        self.records = load("patient_records", "created_at")
        self.doc = {d["id"]: d for d in self.doctors}
        self.sess = {s["id"]: s for s in self.sessions}
        self.ev_by_session = defaultdict(list)
        self.ev_by_doctor = defaultdict(list)
        for e in self.events:
            e["_t"] = event_time(e)
            sid = e.get("session_id")
            did = e.get("doctor_id") or (self.sess.get(sid) or {}).get("doctor_id")
            if sid:
                self.ev_by_session[sid].append(e)
            if did:
                self.ev_by_doctor[did].append(e)
        for lst in (*self.ev_by_session.values(), *self.ev_by_doctor.values()):
            lst.sort(key=lambda e: (e["_t"], e["id"]))
        self.rec_by_session = defaultdict(list)
        self.rec_by_doctor = defaultdict(list)
        for r in self.records:
            self.rec_by_session[r.get("session_id")].append(r)
            self.rec_by_doctor[r.get("doctor_id")].append(r)

    def session_metrics(self, s: dict) -> dict:
        evs = self.ev_by_session.get(s["id"], [])
        start = parse_ts(s["started_at"])
        last = max([e["_t"] for e in evs], default=start)
        m = dict(clicks=0, page_views=0, items_added=0, video_skipped=0, video_completed=0,
                 timer_expired=0, records_saved=0, active_seconds=0.0)
        pages = []
        for e in evs:
            t, label = e.get("event_type"), e.get("label") or ""
            if t == "click":
                m["clicks"] += 1
            elif t == "page_view":
                m["page_views"] += 1
                if e.get("page") not in pages:
                    pages.append(e.get("page"))
            elif t == "page_time":
                m["active_seconds"] += (e.get("duration_ms") or 0) / 1000
            elif t == "add_to_sheet":
                m["items_added"] += 1
            elif t == "add_all_to_sheet":
                n = re.search(r"\((\d+)\)", label)
                m["items_added"] += int(n.group(1)) if n else 0
            elif t == "skip_video":
                m["video_skipped"] += 1
            elif t == "video_ended":
                m["video_completed"] += 1
            elif t == "timer_expired":
                m["timer_expired"] += 1
            elif t == "record_saved":
                m["records_saved"] += 1
        m["active_seconds"] = round(m["active_seconds"], 1)
        d = self.doc.get(s.get("doctor_id")) or {}
        return {
            "id": s["id"], "doctor_id": s.get("doctor_id"),
            "doctor_name": dname(d), "specialization": d.get("specialty"),
            "designation": d.get("designation"),
            "tab": s.get("tab"), "story": s.get("story"), "opening": s.get("opening"),
            "device": s.get("device"), "screen": s.get("screen"), "user_agent": s.get("user_agent"),
            "started_at": s["started_at"], "last_event_at": last.isoformat(),
            "duration_seconds": max(0, round((last - start).total_seconds(), 1)),
            "event_count": len(evs), "pages_visited": pages,
            "records_in_db": len(self.rec_by_session.get(s["id"], [])),
            **m,
        }

    def enrich(self, e: dict) -> dict:
        s = self.sess.get(e.get("session_id")) or {}
        d = self.doc.get(e.get("doctor_id") or s.get("doctor_id")) or {}
        start = parse_ts(s.get("started_at")) if s else None
        return {
            "id": e["id"], "time": e["_t"].isoformat(), "created_at": e.get("created_at"),
            "client_ts": e.get("client_ts"),
            "offset_seconds": max(0, round((e["_t"] - start).total_seconds(), 1)) if start else None,
            "doctor_id": d.get("id"), "doctor_name": dname(d),
            "session_id": e.get("session_id"), "tab": s.get("tab"), "story": s.get("story"),
            "opening": s.get("opening"), "page": e.get("page"), "event_type": e.get("event_type"),
            "label": e.get("label"), "duration_ms": e.get("duration_ms"),
        }


def _avg(vals):
    vals = list(vals)
    return round(sum(vals) / len(vals), 1) if vals else 0


def _group(metrics: list[dict]) -> dict:
    return {
        "sessions": len(metrics),
        "doctors": len({m["doctor_id"] for m in metrics}),
        "avg_duration_seconds": _avg(m["duration_seconds"] for m in metrics),
        "avg_active_seconds": _avg(m["active_seconds"] for m in metrics),
        "avg_clicks": _avg(m["clicks"] for m in metrics),
        "avg_items_added": _avg(m["items_added"] for m in metrics),
        "records_saved": sum(m["records_saved"] for m in metrics),
        "video_skipped": sum(m["video_skipped"] for m in metrics),
        "timer_expired": sum(m["timer_expired"] for m in metrics),
    }


# ------------------------------------------------------------ endpoints ----
@router.get("/overview", dependencies=[Depends(require_admin)])
def overview():
    w = World()
    metrics = [w.session_metrics(s) for s in w.sessions]
    now = datetime.now(timezone.utc)
    active_now = sum(1 for m in metrics if (now - parse_ts(m["last_event_at"])).total_seconds() < 90)

    by_tab, by_open = defaultdict(list), defaultdict(list)
    for m in metrics:
        by_tab[m["tab"]].append(m)
        by_open[m["opening"]].append(m)

    pages = defaultdict(lambda: {"views": 0, "clicks": 0, "total_seconds": 0.0, "timed_visits": 0})
    type_counts = defaultdict(int)
    for e in w.events:
        type_counts[e.get("event_type")] += 1
        p = e.get("page")
        if not p:
            continue
        if e["event_type"] == "page_view":
            pages[p]["views"] += 1
        elif e["event_type"] == "click":
            pages[p]["clicks"] += 1
        elif e["event_type"] == "page_time":
            pages[p]["total_seconds"] += (e.get("duration_ms") or 0) / 1000
            pages[p]["timed_visits"] += 1
    page_rows = [{"page": p, **v, "total_seconds": round(v["total_seconds"], 1),
                  "avg_seconds": round(v["total_seconds"] / v["timed_visits"], 1) if v["timed_visits"] else 0}
                 for p, v in pages.items()]

    latest = sorted(w.events, key=lambda e: (e["_t"], e["id"]), reverse=True)[:15]
    return {
        "totals": {"doctors": len(w.doctors), "sessions": len(w.sessions), "events": len(w.events),
                   "records": len(w.records), "active_now": active_now,
                   "avg_duration_seconds": _avg(m["duration_seconds"] for m in metrics)},
        "by_tab": sorted(({"tab": t, "story": v[0]["story"], "opening": v[0]["opening"], **_group(v)}
                          for t, v in by_tab.items()), key=lambda r: r["tab"] or ""),
        "by_opening": [{"opening": o, **_group(v)} for o, v in by_open.items()],
        "pages": page_rows,
        "event_types": dict(type_counts),
        "session_starts": [s["started_at"] for s in w.sessions],
        "latest_events": [w.enrich(e) for e in latest],
    }


@router.get("/doctors", dependencies=[Depends(require_admin)])
def doctors():
    w = World()
    rows = []
    for d in w.doctors:
        sess = [w.session_metrics(s) for s in w.sessions if s.get("doctor_id") == d["id"]]
        evs = w.ev_by_doctor.get(d["id"], [])
        rows.append({**{k: d.get(k) for k in DOCTOR_COLS}, "name": dname(d), "specialization": d.get("specialty"),
                     "sessions": len(sess), "events": len(evs),
                     "records": len(w.rec_by_doctor.get(d["id"], [])),
                     "active_seconds": round(sum(m["active_seconds"] for m in sess), 1),
                     "last_active": evs[-1]["_t"].isoformat() if evs else d.get("created_at")})
    return sorted(rows, key=lambda r: r["last_active"] or "", reverse=True)


@router.get("/doctors/{doctor_id}", dependencies=[Depends(require_admin)])
def doctor_detail(doctor_id: str):
    w = World()
    d = w.doc.get(doctor_id)
    if not d:
        raise HTTPException(404, "Doctor not found")
    sessions = [w.session_metrics(s) for s in w.sessions if s.get("doctor_id") == doctor_id]
    return {"doctor": d, "sessions": sorted(sessions, key=lambda m: m["started_at"], reverse=True),
            "events": [w.enrich(e) for e in w.ev_by_doctor.get(doctor_id, [])],
            "records": sorted(w.rec_by_doctor.get(doctor_id, []), key=lambda r: r["created_at"], reverse=True)}


@router.get("/sessions", dependencies=[Depends(require_admin)])
def sessions(doctor_id: Optional[str] = None, tab: Optional[str] = None, opening: Optional[str] = None):
    w = World()
    out = [w.session_metrics(s) for s in w.sessions
           if (not doctor_id or s.get("doctor_id") == doctor_id)
           and (not tab or s.get("tab") == tab)
           and (not opening or s.get("opening") == opening)]
    return sorted(out, key=lambda m: m["started_at"], reverse=True)


@router.get("/sessions/{session_id}", dependencies=[Depends(require_admin)])
def session_detail(session_id: str):
    w = World()
    s = w.sess.get(session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    evs = w.ev_by_session.get(session_id, [])
    pages = defaultdict(lambda: {"views": 0, "clicks": 0, "seconds": 0.0})
    for e in evs:
        p = e.get("page")
        if not p:
            continue
        if e["event_type"] == "page_view":
            pages[p]["views"] += 1
        elif e["event_type"] == "click":
            pages[p]["clicks"] += 1
        elif e["event_type"] == "page_time":
            pages[p]["seconds"] += (e.get("duration_ms") or 0) / 1000
    order = []
    for e in evs:
        if e["event_type"] == "page_view" and e["page"] not in order:
            order.append(e["page"])
    journey = [{"page": p, **{**pages[p], "seconds": round(pages[p]["seconds"], 1)}} for p in order]
    added = [e.get("label") for e in evs if e["event_type"] in ("add_to_sheet", "add_all_to_sheet")]
    return {"session": w.session_metrics(s), "doctor": w.doc.get(s.get("doctor_id")),
            "journey": journey, "added_items": added,
            "events": [w.enrich(e) for e in evs],
            "records": w.rec_by_session.get(session_id, [])}


@router.get("/events", dependencies=[Depends(require_admin)])
def events(session_id: Optional[str] = None, doctor_id: Optional[str] = None,
           event_type: Optional[str] = None, q: Optional[str] = None,
           limit: int = 50, offset: int = 0):
    w = World()
    rows = [w.enrich(e) for e in sorted(w.events, key=lambda e: (e["_t"], e["id"]), reverse=True)
            if (not session_id or e.get("session_id") == session_id)
            and (not doctor_id or e.get("doctor_id") == doctor_id)
            and (not event_type or e.get("event_type") == event_type)]
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in " ".join(str(r.get(k) or "") for k in
                ("label", "page", "doctor_name", "event_type", "story")).lower()]
    limit = max(1, min(limit, 500))
    return {"total": len(rows), "rows": rows[offset:offset + limit]}


@router.get("/records", dependencies=[Depends(require_admin)])
def records():
    w = World()
    out = []
    for r in sorted(w.records, key=lambda r: r["created_at"], reverse=True):
        s = w.sess.get(r.get("session_id")) or {}
        d = w.doc.get(r.get("doctor_id")) or {}
        out.append({**r, "doctor_name": dname(d), "tab": s.get("tab"), "story": s.get("story"),
                    "opening": s.get("opening")})
    return out


# ------------------------------------------------------------- exports ----
def _safe(v):
    """Stop Excel treating a cell as a formula."""
    v = "" if v is None else str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@") else v


def _csv(header: list[str], rows: list[list], name: str) -> Response:
    buf = io.StringIO()
    wr = csv.writer(buf)
    wr.writerow(header)
    for r in rows:
        wr.writerow([_safe(c) for c in r])
    return Response("\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})


@router.get("/export/{kind}", dependencies=[Depends(require_admin)])
def export(kind: str, session_id: Optional[str] = None, doctor_id: Optional[str] = None):
    w = World()
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    if kind == "events":
        evs = [w.enrich(e) for e in w.events
               if (not session_id or e.get("session_id") == session_id)
               and (not doctor_id or e.get("doctor_id") == doctor_id)]
        evs.sort(key=lambda r: (r["doctor_name"] or "", r["session_id"] or "", r["time"]))
        cols = ["time", "offset_seconds", "doctor_id", "doctor_name", "session_id", "tab", "story", "opening",
                "page", "event_type", "label", "duration_ms", "client_ts", "created_at"]
        return _csv(cols, [[r[c] for c in cols] for r in evs], f"events-{stamp}")
    if kind == "sessions":
        ms = [w.session_metrics(s) for s in w.sessions if not doctor_id or s.get("doctor_id") == doctor_id]
        cols = ["id", "doctor_id", "doctor_name", "specialization", "designation", "tab", "story", "opening",
                "device", "screen", "started_at", "last_event_at", "duration_seconds", "active_seconds",
                "event_count", "page_views", "clicks", "items_added", "video_skipped", "video_completed",
                "timer_expired", "records_saved"]
        return _csv(cols, [[m[c] for c in cols] for m in ms], f"sessions-{stamp}")
    if kind == "doctors":
        cols = [*DOCTOR_COLS, "sessions", "events", "records", "active_seconds", "last_active"]
        return _csv(cols, [[r[c] for c in cols] for r in doctors()], f"doctors-{stamp}")
    if kind == "records":
        cols = ["created_at", "doctor_name", "patient_name", "tab", "story", "opening", "items", "notes"]
        rows = []
        for r in records():
            r["items"] = " | ".join(str(i) for i in (r.get("items") or []))
            rows.append([r.get(c) for c in cols])
        return _csv(cols, rows, f"records-{stamp}")
    raise HTTPException(404, "Unknown export. Use events, sessions, doctors or records.")
