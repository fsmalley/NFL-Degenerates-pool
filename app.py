import os
import hashlib
import hmac
import secrets
import re
import datetime as dt
import requests
from flask import Flask, render_template, jsonify, request
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

SEASON = int(os.getenv("NFL_SEASON", "2026"))
API_BASE = os.getenv("NFLDATA_API_BASE", "https://api.nfldata.org")
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
if SUPABASE_URL.endswith("/rest/v1"):
    SUPABASE_URL = SUPABASE_URL[:-8].rstrip("/")
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
        "Content-Type": "application/json",
    }
    if SUPABASE_SERVICE_KEY and not SUPABASE_SERVICE_KEY.startswith("sb_secret_"):
        h["Authorization"] = f"Bearer {SUPABASE_SERVICE_KEY}"
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
        total = 0
        count = 0
        weekly = {str(w): 0 for w in range(1, 19)}
        weekly_games = {str(w): 0 for w in range(1, 19)}

        selected = []
        for n in range(1, 9):
            team = (p.get(f"team{n}") or "").strip().upper()
            if team:
                selected.append(team)

        for g in games:
            if g.get("margin") is None:
                continue

            week = str(g.get("week") or "")
            if week not in weekly:
                continue

            for team in selected:
                score = None

                if g.get("winner") == team:
                    score = int(g["margin"])
                elif g.get("loser") == team:
                    score = -int(g["margin"])
                elif g.get("winner") == "TIE" and team in (g.get("away_team"), g.get("home_team")):
                    score = 0

                if score is not None:
                    total += score
                    count += 1
                    weekly[week] += score
                    weekly_games[week] += 1

        p["total_points"] = total
        p["games_count"] = count
        p["weekly_scores"] = weekly
        p["weekly_games"] = weekly_games

    players.sort(key=lambda p: (-p["total_points"], p["player_name"].lower()))
    for rank, p in enumerate(players, 1):
        p["rank"] = rank

    return players



def normalize_player_key(name):
    return " ".join(str(name or "").lower().split())


def parse_game_datetime(value):
    """Best-effort parse of an ISO-like kickoff timestamp."""
    value = str(value or "").strip()
    if not value or len(value) <= 10:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except Exception:
        return None


def game_has_started(game):
    status = str(game.get("status") or "").lower()
    if any(word in status for word in ("final", "complete", "closed", "in_progress", "in progress", "live", "halftime")):
        return True
    if game.get("winner") is not None:
        return True

    kickoff = parse_game_datetime(game.get("game_date"))
    if kickoff is not None and dt.datetime.now(dt.timezone.utc) >= kickoff:
        return True
    return False


def team_game(team, games):
    for g in games:
        if team in (g.get("away_team"), g.get("home_team")):
            return g
    return None


def get_survivor_player(player_key):
    rows = sb_get(
        "survivor_players",
        {
            "select": "*",
            "season": f"eq.{SEASON}",
            "player_key": f"eq.{player_key}",
            "limit": "1"
        }
    )
    return rows[0] if rows else None


def ensure_survivor_player(player_name, player_key, pin):
    player = get_survivor_player(player_key)
    now = dt.datetime.now(dt.timezone.utc).isoformat()

    if player:
        if not check_password_hash(player.get("pin_hash") or "", pin):
            raise PermissionError("Incorrect Survivor PIN for this player.")
        if player.get("player_name") != player_name:
            sb_upsert(
                "survivor_players",
                [{
                    "season": SEASON,
                    "player_key": player_key,
                    "player_name": player_name,
                    "pin_hash": player["pin_hash"],
                    "updated_at": now
                }],
                "season,player_key"
            )
        return

    if len(pin) < 4:
        raise ValueError("Choose a Survivor PIN with at least 4 characters.")

    sb_upsert(
        "survivor_players",
        [{
            "season": SEASON,
            "player_key": player_key,
            "player_name": player_name,
            "pin_hash": generate_password_hash(pin),
            "created_at": now,
            "updated_at": now
        }],
        "season,player_key"
    )


def survivor_board_data():
    picks = sb_get(
        "survivor_picks",
        {
            "select": "*",
            "season": f"eq.{SEASON}",
            "order": "player_name.asc,week.asc"
        }
    )
    players = sb_get(
        "survivor_players",
        {
            "select": "player_key,player_name",
            "season": f"eq.{SEASON}",
            "order": "player_name.asc"
        }
    )
    games = sb_get("games", {"select": "*", "season": f"eq.{SEASON}"})

    game_by_week = {}
    for g in games:
        game_by_week.setdefault(int(g.get("week") or 0), []).append(g)

    picks_by_player = {}
    for p in picks:
        picks_by_player.setdefault(p["player_key"], {})[int(p["week"])] = p

    # Include legacy pick-only players if needed.
    known = {p["player_key"] for p in players}
    for p in picks:
        if p["player_key"] not in known:
            players.append({"player_key": p["player_key"], "player_name": p["player_name"]})
            known.add(p["player_key"])

    board = []
    for player in players:
        key = player["player_key"]
        weekly = {}
        alive = True
        eliminated_week = None

        for week in range(1, 19):
            pick = picks_by_player.get(key, {}).get(week)
            if not pick:
                weekly[str(week)] = {"team": "", "status": "NO PICK"}
                continue

            outcome = survivor_pick_result((pick.get("team") or "").upper(), game_by_week.get(week, []))
            status = outcome["status"]
            weekly[str(week)] = {
                "team": pick.get("team") or "",
                "status": status,
                "score": outcome.get("score")
            }

            if status == "ELIMINATED" and alive:
                alive = False
                eliminated_week = week

        board.append({
            "player_key": key,
            "player_name": player.get("player_name") or key,
            "status": "ALIVE" if alive else "ELIMINATED",
            "eliminated_week": eliminated_week,
            "weekly": weekly
        })

    board.sort(key=lambda x: (x["status"] != "ALIVE", x["player_name"].lower()))
    return board



def hash_survivor_pin(pin, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        pin.encode("utf-8"),
        salt.encode("utf-8"),
        150000
    ).hex()
    return f"{salt}${digest}"


def verify_survivor_pin(pin, stored):
    if not stored or "$" not in stored:
        return False
    salt, expected = stored.split("$", 1)
    actual = hash_survivor_pin(pin, salt).split("$", 1)[1]
    return hmac.compare_digest(actual, expected)


def get_survivor_player(player_key):
    rows = sb_get(
        "survivor_players",
        {"select": "*", "player_key": f"eq.{player_key}", "limit": "1"}
    )
    return rows[0] if rows else None


def parse_game_datetime(value):
    """Best-effort ISO date parser. Naive timestamps are treated as UTC."""
    if not value:
        return None
    try:
        raw = str(value).strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        parsed = dt.datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except Exception:
        return None


def team_game_for_week(team, week):
    games = get_week(week)
    for g in games:
        if team in (g.get("away_team"), g.get("home_team")):
            return g
    return None


def pick_is_locked(team, week):
    game = team_game_for_week(team, week)
    if not game:
        return False, None

    kickoff = parse_game_datetime(game.get("game_date"))
    if kickoff is None:
        # If no parseable kickoff exists but the game already has a score/result,
        # consider it locked.
        played = (
            game.get("away_score") is not None or
            game.get("home_score") is not None or
            game.get("winner") is not None
        )
        return played, None

    return dt.datetime.now(dt.timezone.utc) >= kickoff, kickoff


def survivor_all_picks():
    return sb_get(
        "survivor_picks",
        {
            "select": "*",
            "season": f"eq.{SEASON}",
            "order": "player_name.asc,week.asc"
        }
    )


def survivor_board_data():
    picks = survivor_all_picks()
    games_by_week = {}
    players = {}

    for p in picks:
        key = p.get("player_key")
        if not key:
            continue
        entry = players.setdefault(key, {
            "player_name": p.get("player_name") or key,
            "weeks": {},
            "status": "ALIVE",
            "eliminated_week": None
        })

        week = int(p.get("week") or 0)
        if week not in games_by_week:
            games_by_week[week] = get_week(week)

        outcome = survivor_pick_result((p.get("team") or "").upper(), games_by_week[week])
        entry["weeks"][str(week)] = {
            "team": p.get("team"),
            "team_name": TEAMS.get(p.get("team"), p.get("team")),
            "result": outcome["status"]
        }

        if outcome["status"] == "ELIMINATED":
            if entry["eliminated_week"] is None or week < entry["eliminated_week"]:
                entry["eliminated_week"] = week
                entry["status"] = "OUT"

    rows = list(players.values())
    rows.sort(key=lambda p: (0 if p["status"] == "ALIVE" else 1, p["player_name"].lower()))
    return rows


def save_survivor_pick(player_name, week, team, pin=None, admin_override=False):
    player_key = " ".join(player_name.lower().split())
    now = dt.datetime.now(dt.timezone.utc).isoformat()

    if not admin_override:
        if not pin or not pin.isdigit() or not (4 <= len(pin) <= 12):
            raise ValueError("Enter your 4–12 digit Survivor PIN.")

        player = get_survivor_player(player_key)
        if player:
            if not verify_survivor_pin(pin, player.get("pin_hash")):
                raise PermissionError("Incorrect Survivor PIN.")
        else:
            sb_upsert("survivor_players", [{
                "player_key": player_key,
                "player_name": player_name,
                "pin_hash": hash_survivor_pin(pin),
                "created_at": now,
                "updated_at": now
            }], "player_key")

    history = survivor_player_history(player_key)

    if not admin_override:
        for old in history:
            old_week = int(old.get("week") or 0)
            if old_week <= 0 or old_week >= week:
                continue
            old_team = (old.get("team") or "").upper()
            outcome = survivor_pick_result(old_team, get_week(old_week))
            if outcome["status"] == "ELIMINATED":
                raise PermissionError(
                    f"This Survivor entry was eliminated in Week {old_week} and cannot submit a later pick."
                )

    existing = next((r for r in history if int(r.get("week") or 0) == week), None)

    # Once an existing pick's selected game has started, the player cannot change it.
    if existing and not admin_override:
        existing_team = (existing.get("team") or "").upper()
        locked, _ = pick_is_locked(existing_team, week)
        if locked:
            raise PermissionError(
                f"Week {week} is locked because your selected team's game has started."
            )

    # New submissions are also blocked if the newly selected team's game has started.
    if not admin_override:
        locked, _ = pick_is_locked(team, week)
        if locked:
            raise PermissionError(
                f"{TEAMS.get(team, team)} is already locked because its Week {week} game has started."
            )

    for old in history:
        if int(old.get("week") or 0) != week and (old.get("team") or "").upper() == team:
            if not admin_override:
                raise ValueError(
                    f"You already used {TEAMS.get(team, team)} in Week {old.get('week')}. "
                    "Survivor teams cannot be reused."
                )

    row = {
        "season": SEASON,
        "week": week,
        "player_name": player_name,
        "player_key": player_key,
        "team": team,
        "submitted_at": (existing or {}).get("submitted_at") or now,
        "updated_at": now
    }
    sb_upsert("survivor_picks", [row], "season,week,player_key")
    return row

def survivor_pick_result(team, games):
    """Return survivor outcome details for one team pick."""
    for g in games:
        if team not in (g.get("away_team"), g.get("home_team")):
            continue

        opponent = g.get("home_team") if team == g.get("away_team") else g.get("away_team")
        decided = g.get("away_score") is not None and g.get("home_score") is not None and g.get("winner") is not None

        if not decided:
            return {
                "status": "PENDING",
                "opponent": opponent,
                "score": None,
                "game_date": g.get("game_date") or ""
            }

        score = f"{g.get('away_score')} - {g.get('home_score')}"
        if g.get("winner") == team:
            status = "SURVIVED"
        else:
            # A loss or a tie counts as an elimination in this Survivor pool.
            status = "ELIMINATED"

        return {
            "status": status,
            "opponent": opponent,
            "score": score,
            "game_date": g.get("game_date") or ""
        }

    return {
        "status": "PENDING",
        "opponent": "",
        "score": None,
        "game_date": ""
    }


def survivor_results_data(week):
    picks = sb_get(
        "survivor_picks",
        {
            "select": "*",
            "season": f"eq.{SEASON}",
            "week": f"eq.{week}",
            "order": "player_name.asc"
        }
    )
    games = get_week(week)

    results = []
    for p in picks:
        outcome = survivor_pick_result((p.get("team") or "").upper(), games)
        results.append({
            "id": p.get("id"),
            "player_name": p.get("player_name"),
            "team": p.get("team"),
            "team_name": TEAMS.get(p.get("team"), p.get("team")),
            "opponent": outcome["opponent"],
            "opponent_name": TEAMS.get(outcome["opponent"], outcome["opponent"]),
            "status": outcome["status"],
            "score": outcome["score"],
            "game_date": outcome["game_date"],
            "submitted_at": p.get("submitted_at")
        })
    return results


def survivor_player_history(player_key):
    rows = sb_get(
        "survivor_picks",
        {
            "select": "week,team,player_name,player_key",
            "season": f"eq.{SEASON}",
            "player_key": f"eq.{player_key}",
            "order": "week.asc"
        }
    )
    return rows

@app.route("/")
def index():
    week=max(1,min(18,request.args.get("week",1,type=int)))
    return render_template("index.html",season=SEASON,week=week)

@app.route("/draft")
def draft():
    return render_template("draft.html",season=SEASON)

@app.route("/survivor")
def survivor():
    week=max(1,min(18,request.args.get("week",1,type=int)))
    return render_template("survivor.html",season=SEASON,week=week)

@app.route("/survivor/results")
def survivor_results():
    week=max(1,min(18,request.args.get("week",1,type=int)))
    return render_template("survivor_results.html",season=SEASON,week=week)

@app.route("/survivor/board")
def survivor_board():
    return render_template("survivor_board.html",season=SEASON)

@app.route("/health")
def health():
    try:
        sb_get("draft_players", {"select":"id","limit":"1"})
        return jsonify({"status":"ok","database":"supabase","season":SEASON}), 200
    except Exception as e:
        print(f"HEALTH CHECK ERROR: {type(e).__name__}: {e}", flush=True)
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


@app.route("/api/admin/check", methods=["POST"])
def api_admin_check():
    payload = request.get_json(silent=True) or {}
    if not ADMIN_PASSWORD:
        return jsonify({"ok": False, "error": "ADMIN_PASSWORD is not configured on the server."}), 500
    if payload.get("password", "") != ADMIN_PASSWORD:
        return jsonify({"ok": False, "error": "Incorrect admin password."}), 403
    return jsonify({"ok": True})

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

        selected = []
        row={
            "id":int(pid),
            "player_name":str(p.get("player_name","")).strip() or f"Player {pid}",
            "updated_at":now
        }

        for n in range(1,9):
            team=str(p.get(f"team{n}","")).strip().upper()
            if team and team not in TEAMS:
                return jsonify({"ok":False,"error":f"Invalid team abbreviation for {row['player_name']}: {team}"}),400
            if team:
                selected.append(team)
            row[f"team{n}"]=team

        if len(selected) != len(set(selected)):
            return jsonify({"ok":False,"error":f"{row['player_name']} has the same NFL team selected more than once."}),400

        rows.append(row)

    sb_upsert("draft_players",rows,"id")
    return jsonify({"ok":True,"players":draft_data()})


@app.route("/api/survivor/pick", methods=["POST"])
def api_survivor_pick():
    payload = request.get_json(silent=True) or {}
    player_name = str(payload.get("player_name", "")).strip()
    pin = str(payload.get("pin", "")).strip()
    team = str(payload.get("team", "")).strip().upper()

    try:
        week = int(payload.get("week", 0))
    except Exception:
        week = 0

    if not player_name:
        return jsonify({"ok": False, "error": "Enter your player name."}), 400
    if len(player_name) > 80:
        return jsonify({"ok": False, "error": "Player name is too long."}), 400
    if week < 1 or week > 18:
        return jsonify({"ok": False, "error": "Choose a valid NFL week."}), 400
    if team not in TEAMS:
        return jsonify({"ok": False, "error": "Choose a valid NFL team."}), 400

    try:
        row = save_survivor_pick(player_name, week, team, pin=pin, admin_override=False)
    except PermissionError as e:
        return jsonify({"ok": False, "error": str(e)}), 403
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        print(f"SURVIVOR SAVE ERROR: {type(e).__name__}: {e}", flush=True)
        return jsonify({"ok": False, "error": "Could not save the Survivor pick."}), 500

    return jsonify({
        "ok": True,
        "message": f"Week {week} pick saved: {TEAMS.get(team, team)}",
        "pick": row
    })


@app.route("/api/survivor/admin/pick", methods=["POST"])
def api_survivor_admin_pick():
    payload = request.get_json(silent=True) or {}

    if not ADMIN_PASSWORD or payload.get("password", "") != ADMIN_PASSWORD:
        return jsonify({"ok": False, "error": "Incorrect commissioner password."}), 403

    player_name = str(payload.get("player_name", "")).strip()
    team = str(payload.get("team", "")).strip().upper()
    try:
        week = int(payload.get("week", 0))
    except Exception:
        week = 0

    if not player_name or week < 1 or week > 18 or team not in TEAMS:
        return jsonify({"ok": False, "error": "Player, week, and team are required."}), 400

    try:
        row = save_survivor_pick(player_name, week, team, admin_override=True)
        return jsonify({
            "ok": True,
            "message": f"Commissioner override saved for {player_name}, Week {week}.",
            "pick": row
        })
    except Exception as e:
        print(f"SURVIVOR ADMIN SAVE ERROR: {type(e).__name__}: {e}", flush=True)
        return jsonify({"ok": False, "error": "Commissioner override could not be saved."}), 500


@app.route("/api/survivor/history")
def api_survivor_history():
    player_name = str(request.args.get("player", "")).strip()
    if not player_name:
        return jsonify({"history": [], "used_teams": []})

    player_key = " ".join(player_name.lower().split())
    rows = survivor_player_history(player_key)
    used = []

    for row in rows:
        team = (row.get("team") or "").upper()
        row["team_name"] = TEAMS.get(team, team)
        locked, kickoff = pick_is_locked(team, int(row.get("week") or 0))
        row["locked"] = locked
        row["kickoff"] = kickoff.isoformat() if kickoff else None
        if team:
            used.append(team)

    return jsonify({"history": rows, "used_teams": used})


@app.route("/api/survivor/board")
def api_survivor_board():
    try:
        picks = survivor_all_picks()
        pick_weeks = sorted({int(p.get("week") or 0) for p in picks if int(p.get("week") or 0) in range(1,19)})
        for week in pick_weeks:
            try:
                sync_week(week)
            except Exception:
                pass
        board = survivor_board_data()
        return jsonify({
            "players": board,
            "alive": sum(1 for p in board if p["status"] == "ALIVE"),
            "out": sum(1 for p in board if p["status"] == "OUT")
        })
    except Exception as e:
        print(f"SURVIVOR BOARD ERROR: {type(e).__name__}: {e}", flush=True)
        return jsonify({"players": [], "alive": 0, "out": 0, "error": str(e)}), 500



@app.route("/api/survivor/week/<int:week>")
def api_survivor_week(week):
    week=max(1,min(18,week))
    try:
        try:
            sync_week(week)
        except Exception:
            pass
        games = get_week(week)
        teams = []
        for g in games:
            kickoff = parse_game_datetime(g.get("game_date"))
            locked = False
            if kickoff:
                locked = dt.datetime.now(dt.timezone.utc) >= kickoff
            elif g.get("winner") is not None or g.get("away_score") is not None or g.get("home_score") is not None:
                locked = True

            away = g.get("away_team")
            home = g.get("home_team")
            if away:
                teams.append({
                    "team": away,
                    "team_name": TEAMS.get(away, away),
                    "opponent": home,
                    "opponent_name": TEAMS.get(home, home),
                    "kickoff": kickoff.isoformat() if kickoff else g.get("game_date"),
                    "locked": locked
                })
            if home:
                teams.append({
                    "team": home,
                    "team_name": TEAMS.get(home, home),
                    "opponent": away,
                    "opponent_name": TEAMS.get(away, away),
                    "kickoff": kickoff.isoformat() if kickoff else g.get("game_date"),
                    "locked": locked
                })

        teams.sort(key=lambda x: x["team_name"])
        return jsonify({"week": week, "teams": teams})
    except Exception as e:
        print(f"SURVIVOR WEEK ERROR: {type(e).__name__}: {e}", flush=True)
        return jsonify({"week": week, "teams": [], "error": str(e)}), 500


@app.route("/api/survivor/results/<int:week>")
def api_survivor_results(week):
    week=max(1,min(18,week))
    sync_error=None
    try:
        sync_week(week)
    except Exception as e:
        sync_error=str(e)

    try:
        results=survivor_results_data(week)
    except Exception as e:
        results=[]
        sync_error=sync_error or str(e)

    counts = {
        "total": len(results),
        "survived": sum(1 for r in results if r["status"] == "SURVIVED"),
        "eliminated": sum(1 for r in results if r["status"] == "ELIMINATED"),
        "pending": sum(1 for r in results if r["status"] == "PENDING")
    }

    return jsonify({
        "week": week,
        "results": results,
        "counts": counts,
        "sync_error": sync_error
    })



if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.getenv("PORT","5000")),debug=False)
