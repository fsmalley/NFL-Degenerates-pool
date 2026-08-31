import os
import sqlite3
import datetime as dt
import requests
from flask import Flask, render_template, jsonify, request

app = Flask(__name__)

DEFAULT_DB = "/var/data/nfl_results.db" if os.path.isdir("/var/data") else "nfl_results.db"
DB = os.getenv("NFL_DB", DEFAULT_DB)
SEASON = int(os.getenv("NFL_SEASON", "2026"))
API_BASE = os.getenv("NFLDATA_API_BASE", "https://api.nfldata.org")

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

def db():
    directory = os.path.dirname(DB)
    if directory:
        os.makedirs(directory, exist_ok=True)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = db()
    con.execute("""
        CREATE TABLE IF NOT EXISTS games(
            id TEXT PRIMARY KEY,
            season INTEGER,
            week INTEGER,
            game_date TEXT,
            status TEXT,
            away_team TEXT,
            home_team TEXT,
            away_score INTEGER,
            home_score INTEGER,
            winner TEXT,
            loser TEXT,
            margin INTEGER,
            updated_at TEXT
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS draft_players(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_name TEXT NOT NULL,
            team1 TEXT DEFAULT '',
            team2 TEXT DEFAULT '',
            team3 TEXT DEFAULT '',
            team4 TEXT DEFAULT '',
            team5 TEXT DEFAULT '',
            team6 TEXT DEFAULT '',
            team7 TEXT DEFAULT '',
            team8 TEXT DEFAULT '',
            updated_at TEXT
        )
    """)
    if con.execute("SELECT COUNT(*) FROM draft_players").fetchone()[0] == 0:
        now = dt.datetime.utcnow().isoformat()
        for i in range(1, 26):
            con.execute(
                "INSERT INTO draft_players(player_name, updated_at) VALUES(?, ?)",
                (f"Player {i}", now)
            )
    con.commit()
    con.close()

def calculate_result(away, home, away_score, home_score):
    if away_score is None or home_score is None:
        return None, None, None
    if away_score > home_score:
        return away, home, away_score - home_score
    if home_score > away_score:
        return home, away, home_score - away_score
    return "TIE", "TIE", 0

def pick(data, *keys):
    for key in keys:
        if data.get(key) is not None:
            return data[key]
    return None

def team_code(value):
    if isinstance(value, dict):
        return pick(value, "abbr", "abbreviation", "alias", "team_abbr", "team")
    return value

def games_from(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        if isinstance(payload.get("data"), list):
            return payload["data"]
        for key in ("games", "results", "items"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return []

def normalize_game(game, week, index):
    away = team_code(pick(game, "away_team", "away", "away_team_abbr", "away_abbr"))
    home = team_code(pick(game, "home_team", "home", "home_team_abbr", "home_abbr"))

    away_score = pick(game, "away_score", "away_points", "away_score_final")
    home_score = pick(game, "home_score", "home_points", "home_score_final")

    try:
        away_score = int(away_score) if away_score is not None else None
    except (TypeError, ValueError):
        away_score = None

    try:
        home_score = int(home_score) if home_score is not None else None
    except (TypeError, ValueError):
        home_score = None

    return {
        "id": str(pick(game, "game_id", "id") or f"{SEASON}-{week}-{index}"),
        "season": SEASON,
        "week": week,
        "game_date": str(pick(game, "game_date", "gameday", "date", "scheduled", "gametime") or ""),
        "status": str(pick(game, "status", "game_status", "game_state") or "scheduled").lower(),
        "away_team": away or "",
        "home_team": home or "",
        "away_score": away_score,
        "home_score": home_score,
        "updated_at": dt.datetime.utcnow().isoformat()
    }

def sync_week(week):
    response = requests.get(
        f"{API_BASE}/v1/games",
        params={"season": SEASON, "week": week, "game_type": "REG", "limit": 100},
        timeout=20
    )
    response.raise_for_status()
    raw_games = games_from(response.json())

    if not raw_games:
        response = requests.get(
            f"{API_BASE}/v1/games",
            params={"season": SEASON, "limit": 1000},
            timeout=20
        )
        response.raise_for_status()
        raw_games = [
            g for g in games_from(response.json())
            if int(g.get("week", -1) or -1) == week
        ]

    con = db()
    for index, raw in enumerate(raw_games):
        game = normalize_game(raw, week, index)
        winner, loser, margin = calculate_result(
            game["away_team"], game["home_team"],
            game["away_score"], game["home_score"]
        )
        con.execute("""
            INSERT OR REPLACE INTO games(
                id, season, week, game_date, status, away_team, home_team,
                away_score, home_score, winner, loser, margin, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            game["id"], game["season"], game["week"], game["game_date"], game["status"],
            game["away_team"], game["home_team"], game["away_score"], game["home_score"],
            winner, loser, margin, game["updated_at"]
        ))
    con.commit()
    con.close()

def get_week(week):
    con = db()
    rows = con.execute(
        "SELECT * FROM games WHERE season=? AND week=? ORDER BY game_date",
        (SEASON, week)
    ).fetchall()
    con.close()

    games = []
    for row in rows:
        game = dict(row)
        game["away_name"] = TEAMS.get(game["away_team"], game["away_team"])
        game["home_name"] = TEAMS.get(game["home_team"], game["home_team"])
        games.append(game)
    return games

def draft_data():
    con = db()
    players = [dict(r) for r in con.execute("SELECT * FROM draft_players ORDER BY id").fetchall()]
    games = [dict(r) for r in con.execute("SELECT * FROM games WHERE season=?", (SEASON,)).fetchall()]
    con.close()

    for player in players:
        total = 0
        completed_games = 0

        for n in range(1, 9):
            team = (player[f"team{n}"] or "").strip().upper()
            if not team:
                continue

            for game in games:
                if game["margin"] is None:
                    continue

                if game["winner"] == team:
                    total += game["margin"]
                    completed_games += 1
                elif game["loser"] == team:
                    total -= game["margin"]
                    completed_games += 1
                elif game["winner"] == "TIE" and team in (game["away_team"], game["home_team"]):
                    completed_games += 1

        player["total_points"] = total
        player["games_count"] = completed_games

    players.sort(key=lambda p: (-p["total_points"], p["player_name"].lower()))
    for rank, player in enumerate(players, start=1):
        player["rank"] = rank

    return players

@app.route("/")
def index():
    week = request.args.get("week", 1, type=int)
    week = max(1, min(18, week))
    return render_template("index.html", season=SEASON, week=week)

@app.route("/draft")
def draft():
    return render_template("draft.html", season=SEASON)

@app.route("/health")
def health():
    try:
        con = db()
        con.execute("SELECT 1").fetchone()
        con.close()
        return jsonify({"status":"ok","season":SEASON}), 200
    except Exception as exc:
        return jsonify({"status":"error","error":str(exc)}), 500

@app.route("/api/week/<int:week>")
def api_week(week):
    week = max(1, min(18, week))
    error = None
    try:
        sync_week(week)
    except Exception as exc:
        error = str(exc)

    return jsonify({
        "week": week,
        "games": get_week(week),
        "sync_error": error
    })

@app.route("/api/draft", methods=["GET", "POST"])
def api_draft():
    if request.method == "GET":
        return jsonify({"players": draft_data(), "teams": TEAMS})

    payload = request.get_json(silent=True) or {}
    players = payload.get("players", [])

    con = db()
    now = dt.datetime.utcnow().isoformat()

    for player in players:
        player_id = player.get("id")
        if not player_id:
            continue

        values = {
            "player_name": str(player.get("player_name", "")).strip() or f"Player {player_id}",
        }
        for n in range(1, 9):
            values[f"team{n}"] = str(player.get(f"team{n}", "")).strip().upper()

        con.execute("""
            UPDATE draft_players SET
                player_name=?,
                team1=?, team2=?, team3=?, team4=?,
                team5=?, team6=?, team7=?, team8=?,
                updated_at=?
            WHERE id=?
        """, (
            values["player_name"],
            values["team1"], values["team2"], values["team3"], values["team4"],
            values["team5"], values["team6"], values["team7"], values["team8"],
            now, player_id
        ))

    con.commit()
    con.close()
    return jsonify({"ok": True, "players": draft_data()})

init_db()

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
