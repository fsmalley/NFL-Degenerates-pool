import os
import datetime as dt
import requests
from flask import Flask, render_template, jsonify, request

app = Flask(__name__)

SEASON = int(os.getenv("NFL_SEASON", "2026"))
API_BASE = os.getenv("NFLDATA_API_BASE", "https://api.nfldata.org")
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

TEAMS = {
    "ARI":"Arizona Cardinals","ATL":"Atlanta Falcons","BAL":"Baltimore Ravens","BUF":"Buffalo Bills",
    "CAR":"Carolina Panthers","CHI":"Chicago Bears","CIN":"Cincinnati Bengals","CLE":"Cleveland Browns",
    "DAL":"Dallas Cowboys","DEN":"Denver Broncos","DET":"Detroit Lions","GB":"Green Bay Packers",
    "HOU":"Houston Texans","IND":"Indianapolis Colts","JAX":"Jacksonville Jaguars","KC":"Kansas City Chiefs",
    "LV":"Las Vegas Raiders","LAC":"Los Angeles Chargers","LAR":"Los Angeles Rams","MIA":"Miami Dolphins",
    "MIN":"Minnesota Vikings","NE":"New England Patriots","NO":"New Orleans Saints","NYG":"New York Giants",
    "NYJ":"New York Jets","PHI":"Philadelphia Eagles","PIT":"Pittsburgh Steelers","SF":"San Francisco 49ers",
    "SEA":"Seattle Seahawks","TB":"Tampa Bay Buccaneers","TEN":"Tennessee Titans","WAS":"Washington Commanders"
}

def sb_headers(extra=None):
    h = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
    }
    if extra:
        h.update(extra)
    return h

def sb_ready():
    return bool(SUPABASE_URL and SUPABASE_SERVICE_KEY)

def sb_get(table, params=None):
    if not sb_ready():
        raise RuntimeError("Supabase is not configured.")
    r = requests.get(f"{SUPABASE_URL}/rest/v1/{table}", headers=sb_headers(), params=params or {}, timeout=20)
    r.raise_for_status()
    return r.json()

def sb_upsert(table, rows, on_conflict):
    if not rows:
        return
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/{table}",
        headers=sb_headers({"Prefer":"resolution=merge-duplicates,return=minimal"}),
        params={"on_conflict":on_conflict},
        json=rows,
        timeout=20
    )
    r.raise_for_status()

def calculate_result(away, home, away_score, home_score):
    if away_score is None or home_score is None:
        return None, None, None
    if away_score > home_score:
        return away, home, away_score-home_score
    if home_score > away_score:
        return home, away, home_score-away_score
    return "TIE", "TIE", 0

def pick(data, *keys):
    for k in keys:
        if data.get(k) is not None:
            return data[k]
    return None

def team_code(v):
    if isinstance(v, dict):
        return pick(v, "abbr", "abbreviation", "alias", "team_abbr", "team")
    return v

def games_from(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        if isinstance(payload.get("data"), list):
            return payload["data"]
        for k in ("games","results","items"):
            if isinstance(payload.get(k), list):
                return payload[k]
    return []

def normalize_game(game, week, index):
    away = team_code(pick(game, "away_team","away","away_team_abbr","away_abbr")) or ""
    home = team_code(pick(game, "home_team","home","home_team_abbr","home_abbr")) or ""
    away_score = pick(game, "away_score","away_points","away_score_final")
    home_score = pick(game, "home_score","home_points","home_score_final")
    try: away_score = int(away_score) if away_score is not None else None
    except: away_score = None
    try: home_score = int(home_score) if home_score is not None else None
    except: home_score = None
    winner, loser, margin = calculate_result(away, home, away_score, home_score)
    return {
        "id": str(pick(game,"game_id","id") or f"{SEASON}-{week}-{index}"),
        "season": SEASON,
        "week": week,
        "game_date": str(pick(game,"game_date","gameday","date","scheduled","gametime") or ""),
        "status": str(pick(game,"status","game_status","game_state") or "scheduled").lower(),
        "away_team": away,
        "home_team": home,
        "away_score": away_score,
        "home_score": home_score,
        "winner": winner,
        "loser": loser,
        "margin": margin,
        "updated_at": dt.datetime.utcnow().isoformat()
    }

def sync_week(week):
    r = requests.get(f"{API_BASE}/v1/games", params={"season":SEASON,"week":week,"game_type":"REG","limit":100}, timeout=20)
    r.raise_for_status()
    raw = games_from(r.json())
    if not raw:
        r = requests.get(f"{API_BASE}/v1/games", params={"season":SEASON,"limit":1000}, timeout=20)
        r.raise_for_status()
        raw = [g for g in games_from(r.json()) if int(g.get("week",-1) or -1) == week]
    sb_upsert("games", [normalize_game(g,week,i) for i,g in enumerate(raw)], "id")

def get_week(week):
    rows = sb_get("games", {"select":"*","season":f"eq.{SEASON}","week":f"eq.{week}","order":"game_date.asc"})
    for g in rows:
        g["away_name"] = TEAMS.get(g["away_team"], g["away_team"])
        g["home_name"] = TEAMS.get(g["home_team"], g["home_team"])
    return rows

def ensure_players():
    rows = sb_get("draft_players", {"select":"id","limit":"1"})
    if rows:
        return
    now = dt.datetime.utcnow().isoformat()
    seed=[]
    for i in range(1,26):
        row={"id":i,"player_name":f"Player {i}","updated_at":now}
        for n in range(1,9):
            row[f"team{n}"]=""
        seed.append(row)
    sb_upsert("draft_players", seed, "id")

def draft_data():
    ensure_players()
    players = sb_get("draft_players", {"select":"*","order":"id.asc"})
    games = sb_get("games", {"select":"*","season":f"eq.{SEASON}"})
    for p in players:
        total=0
        count=0
        for n in range(1,9):
            team=(p.get(f"team{n}") or "").strip().upper()
            if not team:
                continue
            for g in games:
                if g.get("margin") is None:
                    continue
                if g.get("winner")==team:
                    total += int(g["margin"]); count += 1
                elif g.get("loser")==team:
                    total -= int(g["margin"]); count += 1
                elif g.get("winner")=="TIE" and team in (g.get("away_team"),g.get("home_team")):
                    count += 1
        p["total_points"]=total
        p["games_count"]=count
    players.sort(key=lambda p:(-p["total_points"],p["player_name"].lower()))
    for rank,p in enumerate(players,1):
        p["rank"]=rank
    return players

@app.route("/")
def index():
    week=max(1,min(18,request.args.get("week",1,type=int)))
    return render_template("index.html",season=SEASON,week=week)

@app.route("/draft")
def draft():
    return render_template("draft.html",season=SEASON)

@app.route("/health")
def health():
    try:
        sb_get("draft_players", {"select":"id","limit":"1"})
        return jsonify({"status":"ok","database":"supabase","season":SEASON}), 200
    except Exception as e:
        return jsonify({"status":"error","error":str(e)}), 500

@app.route("/api/week/<int:week>")
def api_week(week):
    week=max(1,min(18,week))
    err=None
    try: sync_week(week)
    except Exception as e: err=str(e)
    try: games=get_week(week)
    except Exception as e:
        games=[]
        err=err or str(e)
    return jsonify({"week":week,"games":games,"sync_error":err})

@app.route("/api/draft", methods=["GET","POST"])
def api_draft():
    if request.method=="GET":
        return jsonify({"players":draft_data(),"teams":TEAMS})
    payload=request.get_json(silent=True) or {}
    if not ADMIN_PASSWORD:
        return jsonify({"ok":False,"error":"ADMIN_PASSWORD is not configured on the server."}),500
    if payload.get("password","") != ADMIN_PASSWORD:
        return jsonify({"ok":False,"error":"Incorrect admin password."}),403
    now=dt.datetime.utcnow().isoformat()
    rows=[]
    for p in payload.get("players",[]):
        pid=p.get("id")
        if not pid:
            continue
        row={"id":int(pid),"player_name":str(p.get("player_name","")).strip() or f"Player {pid}","updated_at":now}
        for n in range(1,9):
            row[f"team{n}"]=str(p.get(f"team{n}","")).strip().upper()
        rows.append(row)
    sb_upsert("draft_players",rows,"id")
    return jsonify({"ok":True,"players":draft_data()})

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.getenv("PORT","5000")),debug=False)
