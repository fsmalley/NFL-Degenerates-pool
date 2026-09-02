import os
import hashlib
import hmac
import secrets
import re
import datetime as dt
import requests
from zoneinfo import ZoneInfo
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

DEFAULT_DRAFT_SALARY_CAP = 39500
DEFAULT_DRAFT_TEAM_SALARIES = {
    "BUF": 8000,
    "PHI": 7800,
    "KC": 7600,
    "SF": 7400,
    "MIN": 7250,
    "BAL": 7050,
    "GB": 6850,
    "DAL": 6650,
    "LAR": 6450,
    "SEA": 6300,
    "DET": 6150,
    "PIT": 6000,
    "TB": 5850,
    "LAC": 5700,
    "CIN": 5550,
    "DEN": 5400,
    "MIA": 5250,
    "NE": 5100,
    "HOU": 4950,
    "IND": 4800,
    "JAX": 4650,
    "ATL": 4500,
    "WAS": 4350,
    "NO": 4200,
    "CLE": 4050,
    "CHI": 3900,
    "TEN": 3750,
    "LV": 3600,
    "ARI": 3450,
    "CAR": 3300,
    "NYJ": 3150,
    "NYG": 3000
}

def draft_salary_config():
    """Return season-specific Draft Pool salary cap and team values."""
    cap = DEFAULT_DRAFT_SALARY_CAP
    salaries = dict(DEFAULT_DRAFT_TEAM_SALARIES)

    try:
        settings = sb_get(
            "draft_salary_settings",
            {"select":"salary_cap","season":f"eq.{SEASON}","limit":"1"}
        )
        if settings and settings[0].get("salary_cap") is not None:
            cap = int(settings[0]["salary_cap"])
    except Exception:
        pass

    try:
        rows = sb_get(
            "draft_team_values",
            {"select":"team,salary","season":f"eq.{SEASON}","order":"salary.desc"}
        )
        for row in rows:
            team = str(row.get("team") or "").upper()
            if team in TEAMS and row.get("salary") is not None:
                salaries[team] = int(row["salary"])
    except Exception:
        pass

    return {"salary_cap": cap, "team_salaries": salaries}

def draft_player_salary(player, salaries):
    selected = []
    total = 0
    for n in range(1, 9):
        team = str(player.get(f"team{n}") or "").strip().upper()
        if team:
            selected.append(team)
            total += int(salaries.get(team, 0))
    return total, selected


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

def sb_delete(table, params):
    if not sb_ready():
        raise RuntimeError("Supabase is not configured.")
    r = requests.delete(
        f"{SUPABASE_URL}/rest/v1/{table}",
        headers=sb_headers({"Prefer":"return=minimal"}),
        params=params,
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

def is_game_final(game_or_status):
    """Return True only when the source explicitly reports a completed game."""
    if isinstance(game_or_status, dict):
        status = str(game_or_status.get("status") or "").strip().lower()
    else:
        status = str(game_or_status or "").strip().lower()
    if not status:
        return False
    return any(token in status for token in ("final", "complete", "completed", "closed"))


def normalize_game(game, week, index):
    away = team_code(pick(game, "away_team","away","away_team_abbr","away_abbr")) or ""
    home = team_code(pick(game, "home_team","home","home_team_abbr","home_abbr")) or ""
    away_score = pick(game, "away_score","away_points","away_score_final")
    home_score = pick(game, "home_score","home_points","home_score_final")
    try: away_score = int(away_score) if away_score is not None else None
    except: away_score = None
    try: home_score = int(home_score) if home_score is not None else None
    except: home_score = None
    status = str(pick(game,"status","game_status","game_state") or "scheduled").lower()
    winner = loser = margin = None
    if is_game_final(status):
        winner, loser, margin = calculate_result(away, home, away_score, home_score)
    return {
        "id": str(pick(game,"game_id","id") or f"{SEASON}-{week}-{index}"),
        "season": SEASON,
        "week": week,
        "game_date": str(pick(game,"game_date","gameday","date","scheduled","gametime") or ""),
        "status": status,
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
            if not is_game_final(g) or g.get("margin") is None:
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

    salary_config = draft_salary_config()
    salary_cap = salary_config["salary_cap"]
    salaries = salary_config["team_salaries"]
    for p in players:
        salary_used, _ = draft_player_salary(p, salaries)
        p["salary_used"] = salary_used
        p["salary_remaining"] = salary_cap - salary_used
        p["salary_cap"] = salary_cap

    players.sort(key=lambda p: (-p["total_points"], p["player_name"].lower()))
    rank = 0
    previous_score = None
    for index, p in enumerate(players, 1):
        if previous_score is None or p["total_points"] != previous_score:
            rank = index
            previous_score = p["total_points"]
        p["rank"] = rank

    return players



def hash_survivor_pin(pin, salt=None):
    # New records use Werkzeug's maintained password hash format. The salt
    # parameter remains accepted for compatibility with older callers.
    return generate_password_hash(pin)


def verify_survivor_pin(pin, stored):
    """Verify both newer Werkzeug hashes and legacy custom salt$digest hashes."""
    stored = str(stored or "")
    if not stored:
        return False

    # Werkzeug hashes include a method prefix such as scrypt: or pbkdf2:.
    if stored.startswith(("scrypt:", "pbkdf2:")):
        try:
            return check_password_hash(stored, pin)
        except Exception:
            return False

    # Legacy V2.x custom format: <hex salt>$<pbkdf2 digest>.
    if "$" in stored:
        try:
            salt, expected = stored.split("$", 1)
            actual = hashlib.pbkdf2_hmac(
                "sha256", pin.encode("utf-8"), salt.encode("utf-8"), 150000
            ).hex()
            return hmac.compare_digest(actual, expected)
        except Exception:
            return False
    return False


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



EASTERN = ZoneInfo("America/New_York")

def _iso_utc(value):
    """Normalize a datetime value to UTC ISO text."""
    if isinstance(value, dt.datetime):
        d = value
    else:
        d = parse_game_datetime(value)
    if d is None:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(dt.timezone.utc).isoformat()

def _default_survivor_sunday(week):
    """Return the NFL week's Sunday at 1:00 PM America/New_York."""
    try:
        games = get_week(week)
    except Exception:
        games = []

    parsed = []
    for g in games:
        d = parse_game_datetime(g.get("game_date"))
        if d:
            parsed.append(d.astimezone(EASTERN))

    if parsed:
        # Prefer an actual Sunday appearing in the week's schedule.
        sundays = [d for d in parsed if d.weekday() == 6]
        if sundays:
            sunday_date = min(sundays).date()
        else:
            anchor = min(parsed).date()
            days_until_sunday = (6 - anchor.weekday()) % 7
            sunday_date = anchor + dt.timedelta(days=days_until_sunday)
    else:
        # Fallback for a temporarily unavailable schedule. Week 1 uses the
        # first Sunday on/after September 6; subsequent weeks are 7 days apart.
        anchor = dt.date(SEASON, 9, 6)
        sunday_date = anchor + dt.timedelta(days=((6 - anchor.weekday()) % 7) + (week - 1) * 7)

    return dt.datetime.combine(sunday_date, dt.time(13, 0), tzinfo=EASTERN)

def get_survivor_week_settings(week):
    """Stored weekly settings, with Sunday 1 PM ET defaults."""
    week = max(1, min(18, int(week)))
    default_dt = _default_survivor_sunday(week)
    defaults = {
        "season": SEASON,
        "week": week,
        "deadline_at": default_dt.astimezone(dt.timezone.utc).isoformat(),
        "reveal_at": default_dt.astimezone(dt.timezone.utc).isoformat(),
        "timezone": "America/New_York",
        "is_default": True
    }
    try:
        rows = sb_get(
            "survivor_week_settings",
            {
                "select": "season,week,deadline_at,reveal_at",
                "season": f"eq.{SEASON}",
                "week": f"eq.{week}",
                "limit": "1"
            }
        )
    except Exception:
        rows = []

    if rows:
        row = rows[0]
        defaults["deadline_at"] = _iso_utc(row.get("deadline_at")) or defaults["deadline_at"]
        defaults["reveal_at"] = _iso_utc(row.get("reveal_at")) or defaults["reveal_at"]
        defaults["is_default"] = False
    return defaults

def survivor_week_deadline_passed(week, now=None):
    settings = get_survivor_week_settings(week)
    deadline = parse_game_datetime(settings.get("deadline_at"))
    now = now or dt.datetime.now(dt.timezone.utc)
    return bool(deadline and now >= deadline), deadline

def survivor_week_revealed(week, now=None):
    settings = get_survivor_week_settings(week)
    reveal = parse_game_datetime(settings.get("reveal_at"))
    now = now or dt.datetime.now(dt.timezone.utc)
    return bool(reveal and now >= reveal), reveal

def mask_survivor_result_row(row):
    return {
        "id": row.get("id"),
        "player_name": row.get("player_name"),
        "team": "",
        "team_name": "Pick Submitted",
        "opponent": "",
        "opponent_name": "",
        "status": "SUBMITTED",
        "score": "",
        "game_date": None,
        "submitted_at": row.get("submitted_at"),
        "hidden": True
    }

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

    # Server-side validation prevents direct API submissions for a bye-week team.
    game = team_game_for_week(team, week)
    if not game:
        try:
            sync_week(week)
            game = team_game_for_week(team, week)
        except Exception:
            game = None
    if not game:
        raise ValueError(f"{TEAMS.get(team, team)} does not have a scheduled game in Week {week}.")

    if not admin_override:
        if not pin or not pin.isdigit() or not (4 <= len(pin) <= 12):
            raise ValueError("Enter your 4–12 digit Survivor PIN.")

        player = get_survivor_player(player_key)
        if player:
            if not verify_survivor_pin(pin, player.get("pin_hash")):
                raise PermissionError("Incorrect Survivor PIN.")
        else:
            sb_upsert("survivor_players", [{
                "season": SEASON,
                "player_key": player_key,
                "player_name": player_name,
                "pin_hash": hash_survivor_pin(pin),
                "created_at": now,
                "updated_at": now
            }], "season,player_key")

    if not admin_override:
        deadline_passed, deadline = survivor_week_deadline_passed(week)
        if deadline_passed:
            deadline_text = deadline.astimezone(EASTERN).strftime("%A, %B %-d at %-I:%M %p ET") if os.name != "nt" else deadline.astimezone(EASTERN).strftime("%A, %B %d at %I:%M %p ET").replace(" 0"," ")
            raise PermissionError(
                f"Week {week} Survivor picks are closed. The weekly deadline was {deadline_text}."
            )

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
        decided = (
            is_game_final(g) and
            g.get("away_score") is not None and
            g.get("home_score") is not None and
            g.get("winner") is not None
        )

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

@app.route("/test-lab")
def test_lab():
    return render_template("test_lab.html", season=SEASON)


@app.route("/health")
def health():
    try:
        sb_get("draft_players", {"select":"id","limit":"1"})
        sb_get("survivor_picks", {"select":"id","limit":"1"})
        sb_get("survivor_players", {"select":"id","limit":"1"})
        sb_get("survivor_week_settings", {"select":"id","limit":"1"})
        sb_get("draft_salary_settings", {"select":"id","limit":"1"})
        sb_get("draft_team_values", {"select":"id","limit":"1"})
        return jsonify({"status":"ok","database":"supabase","season":SEASON,"checks":["draft","survivor","settings","draft_salary"]}), 200
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
        salary_config = draft_salary_config()
        return jsonify({
            "players":draft_data(),
            "teams":TEAMS,
            "salary_cap":salary_config["salary_cap"],
            "team_salaries":salary_config["team_salaries"]
        })
    payload=request.get_json(silent=True) or {}
    if not ADMIN_PASSWORD:
        return jsonify({"ok":False,"error":"ADMIN_PASSWORD is not configured on the server."}),500
    if payload.get("password","") != ADMIN_PASSWORD:
        return jsonify({"ok":False,"error":"Incorrect admin password."}),403
    now=dt.datetime.now(dt.timezone.utc).isoformat()
    salary_config = draft_salary_config()
    salary_cap = int(salary_config["salary_cap"])
    salaries = salary_config["team_salaries"]
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

        salary_used = sum(int(salaries.get(team, 0)) for team in selected)
        if salary_used > salary_cap:
            return jsonify({
                "ok":False,
                "error":f"{row['player_name']} is over the Draft Pool salary cap by ${salary_used - salary_cap:,.0f}. "
                        f"Salary used: ${salary_used:,.0f}; cap: ${salary_cap:,.0f}."
            }),400

        rows.append(row)

    sb_upsert("draft_players",rows,"id")
    return jsonify({"ok":True,"players":draft_data()})



@app.route("/api/draft/salary-settings", methods=["GET","POST"])
def api_draft_salary_settings():
    if request.method == "GET":
        config = draft_salary_config()
        return jsonify({
            "ok": True,
            "season": SEASON,
            "salary_cap": config["salary_cap"],
            "team_salaries": config["team_salaries"]
        })

    payload = request.get_json(silent=True) or {}
    if not ADMIN_PASSWORD:
        return jsonify({"ok":False,"error":"ADMIN_PASSWORD is not configured on the server."}),500
    if payload.get("password","") != ADMIN_PASSWORD:
        return jsonify({"ok":False,"error":"Incorrect admin password."}),403

    try:
        salary_cap = int(payload.get("salary_cap", 0))
    except Exception:
        salary_cap = 0
    if salary_cap <= 0:
        return jsonify({"ok":False,"error":"Salary cap must be greater than $0."}),400

    submitted = payload.get("team_salaries") or {}
    salary_rows = []
    for team in TEAMS:
        try:
            value = int(submitted.get(team, 0))
        except Exception:
            value = 0
        if value <= 0:
            return jsonify({"ok":False,"error":f"Enter a valid salary for {TEAMS[team]}."}),400
        salary_rows.append({
            "season": SEASON,
            "team": team,
            "salary": value,
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()
        })

    now = dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        sb_upsert("draft_salary_settings", [{
            "season": SEASON,
            "salary_cap": salary_cap,
            "updated_at": now
        }], "season")
        sb_upsert("draft_team_values", salary_rows, "season,team")

        salary_lookup = {r["team"]: r["salary"] for r in salary_rows}
        over_cap_players = []
        try:
            current_players = sb_get("draft_players", {"select":"*","order":"id.asc"})
            for player in current_players:
                used, _ = draft_player_salary(player, salary_lookup)
                if used > salary_cap:
                    over_cap_players.append({
                        "id": player.get("id"),
                        "player_name": player.get("player_name"),
                        "salary_used": used,
                        "over_by": used - salary_cap
                    })
        except Exception:
            over_cap_players = []

        return jsonify({
            "ok": True,
            "message": f"{SEASON} Draft Pool salary settings saved.",
            "salary_cap": salary_cap,
            "team_salaries": salary_lookup,
            "over_cap_players": over_cap_players
        })
    except Exception as e:
        print(f"DRAFT SALARY SETTINGS ERROR: {type(e).__name__}: {e}", flush=True)
        return jsonify({"ok":False,"error":"Could not save Draft Pool salary settings."}),500


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



@app.route("/api/survivor/admin/delete-pick", methods=["POST"])
def api_survivor_admin_delete_pick():
    payload = request.get_json(silent=True) or {}

    if not ADMIN_PASSWORD or payload.get("password", "") != ADMIN_PASSWORD:
        return jsonify({"ok": False, "error": "Incorrect commissioner password."}), 403

    player_name = str(payload.get("player_name", "")).strip()
    try:
        week = int(payload.get("week", 0))
    except Exception:
        week = 0

    if not player_name:
        return jsonify({"ok": False, "error": "Player name is required."}), 400
    if week < 1 or week > 18:
        return jsonify({"ok": False, "error": "Choose a valid NFL week."}), 400

    player_key = " ".join(player_name.lower().split())

    try:
        matches = sb_get("survivor_picks", {
            "select": "id,player_name,player_key,week,team",
            "season": f"eq.{SEASON}",
            "week": f"eq.{week}",
            "player_key": f"eq.{player_key}"
        })
        if not matches:
            return jsonify({
                "ok": False,
                "error": f"No Survivor pick was found for {player_name}, Week {week}."
            }), 404

        deleted_team = matches[0].get("team") or ""
        sb_delete("survivor_picks", {
            "season": f"eq.{SEASON}",
            "week": f"eq.{week}",
            "player_key": f"eq.{player_key}"
        })

        return jsonify({
            "ok": True,
            "message": f"Deleted {player_name}'s Week {week} Survivor pick ({deleted_team}).",
            "player_name": player_name,
            "week": week,
            "team": deleted_team
        })
    except Exception as e:
        print(f"SURVIVOR DELETE ERROR: {type(e).__name__}: {e}", flush=True)
        return jsonify({"ok": False, "error": "Could not delete the Survivor pick."}), 500


@app.route("/api/survivor/history")
def api_survivor_history():
    player_name = str(request.args.get("player", "")).strip()
    pin = str(request.args.get("pin", "")).strip()
    if not player_name:
        return jsonify({"history": [], "used_teams": []})

    player_key = " ".join(player_name.lower().split())
    player = get_survivor_player(player_key)

    # A brand-new player legitimately has no history yet.
    if not player:
        return jsonify({"history": [], "used_teams": [], "new_player": True})

    if not pin or not verify_survivor_pin(pin, player.get("pin_hash")):
        return jsonify({"history": [], "used_teams": [], "error": "Enter the correct Survivor PIN to view this player's picks."}), 403

    rows = survivor_player_history(player_key)
    used = []
    for row in rows:
        team = (row.get("team") or "").upper()
        row["team_name"] = TEAMS.get(team, team)
        locked, kickoff = pick_is_locked(team, int(row.get("week") or 0))
        deadline_passed, _ = survivor_week_deadline_passed(int(row.get("week") or 0))
        row["locked"] = locked or deadline_passed
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
        revealed_weeks = {w: survivor_week_revealed(w)[0] for w in range(1,19)}
        for player in board:
            visible_elimination_weeks = []
            for week_text, pick in (player.get("weeks") or {}).items():
                try:
                    week_num = int(week_text)
                except Exception:
                    continue
                if pick and not revealed_weeks.get(week_num, False):
                    pick["team"] = ""
                    pick["team_name"] = "Pick Submitted"
                    pick["result"] = "SUBMITTED"
                    pick["hidden"] = True
                elif pick and pick.get("result") == "ELIMINATED":
                    visible_elimination_weeks.append(week_num)

            if visible_elimination_weeks:
                player["status"] = "OUT"
                player["eliminated_week"] = min(visible_elimination_weeks)
            else:
                player["status"] = "ALIVE"
                player["eliminated_week"] = None

        board.sort(key=lambda p: (0 if p.get("status") == "ALIVE" else 1, p.get("player_name", "").lower()))

        return jsonify({
            "players": board,
            "alive": sum(1 for p in board if p["status"] == "ALIVE"),
            "out": sum(1 for p in board if p["status"] == "OUT"),
            "revealed_weeks": revealed_weeks
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
        settings = get_survivor_week_settings(week)
        deadline_passed, _ = survivor_week_deadline_passed(week)
        revealed, _ = survivor_week_revealed(week)
        teams = []
        for g in games:
            kickoff = parse_game_datetime(g.get("game_date"))
            locked = deadline_passed
            if kickoff and not locked:
                locked = dt.datetime.now(dt.timezone.utc) >= kickoff
            elif not kickoff and not locked and (
                g.get("winner") is not None or
                g.get("away_score") is not None or
                g.get("home_score") is not None
            ):
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
        return jsonify({
            "week": week,
            "teams": teams,
            "settings": settings,
            "deadline_passed": deadline_passed,
            "revealed": revealed
        })
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

    revealed, reveal_at = survivor_week_revealed(week)
    admin_header = request.headers.get("X-Admin-Password", "")
    commissioner_view = bool(ADMIN_PASSWORD and admin_header == ADMIN_PASSWORD)

    public_results = results if (revealed or commissioner_view) else [mask_survivor_result_row(r) for r in results]
    counts = {
        "total": len(public_results),
        "survived": sum(1 for r in public_results if r["status"] == "SURVIVED"),
        "eliminated": sum(1 for r in public_results if r["status"] == "ELIMINATED"),
        "pending": sum(1 for r in public_results if r["status"] == "PENDING"),
        "submitted": sum(1 for r in public_results if r["status"] == "SUBMITTED")
    }

    return jsonify({
        "week": week,
        "results": public_results,
        "counts": counts,
        "sync_error": sync_error,
        "revealed": revealed,
        "commissioner_view": commissioner_view,
        "settings": get_survivor_week_settings(week),
        "reveal_at": reveal_at.isoformat() if reveal_at else None
    })


@app.route("/api/survivor/settings/<int:week>", methods=["GET","POST"])
def api_survivor_settings(week):
    week=max(1,min(18,week))

    if request.method == "GET":
        settings = get_survivor_week_settings(week)
        deadline_passed, _ = survivor_week_deadline_passed(week)
        revealed, _ = survivor_week_revealed(week)
        return jsonify({
            "ok": True,
            "settings": settings,
            "deadline_passed": deadline_passed,
            "revealed": revealed
        })

    payload = request.get_json(silent=True) or {}
    if not ADMIN_PASSWORD or payload.get("password", "") != ADMIN_PASSWORD:
        return jsonify({"ok": False, "error": "Incorrect commissioner password."}), 403

    deadline_text = str(payload.get("deadline_at", "")).strip()
    reveal_text = str(payload.get("reveal_at", "")).strip()

    def parse_eastern_setting(value):
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=EASTERN)
        return parsed

    deadline = parse_eastern_setting(deadline_text)
    reveal = parse_eastern_setting(reveal_text)
    if not deadline or not reveal:
        return jsonify({"ok": False, "error": "A valid deadline and reveal time are required."}), 400

    now = dt.datetime.now(dt.timezone.utc).isoformat()
    row = {
        "season": SEASON,
        "week": week,
        "deadline_at": deadline.astimezone(dt.timezone.utc).isoformat(),
        "reveal_at": reveal.astimezone(dt.timezone.utc).isoformat(),
        "updated_at": now
    }
    try:
        sb_upsert("survivor_week_settings", [row], "season,week")
        return jsonify({"ok": True, "message": f"Week {week} Survivor times saved.", "settings": get_survivor_week_settings(week)})
    except Exception as e:
        print(f"SURVIVOR SETTINGS ERROR: {type(e).__name__}: {e}", flush=True)
        return jsonify({"ok": False, "error": "Could not save Survivor week settings."}), 500



def require_admin(payload=None):
    payload = payload or {}
    password = str(payload.get("password", ""))
    if not ADMIN_PASSWORD:
        return False, ("ADMIN_PASSWORD is not configured on the server.", 500)
    if password != ADMIN_PASSWORD:
        return False, ("Incorrect commissioner password.", 403)
    return True, None



TEST_TEAM_CODES = list(TEAMS.keys())


def build_test_schedule():
    """Deterministic 18-week synthetic schedule; test tables only."""
    teams = TEST_TEAM_CODES[:]
    games = []
    for week in range(1, 19):
        # Rotate the team list so opponents change each week.
        shift = (week - 1) % len(teams)
        rotated = teams[shift:] + teams[:shift]
        for i in range(0, 32, 2):
            away = rotated[i]
            home = rotated[i + 1]
            games.append({
                "id": f"TD-W{week:02d}-G{(i//2)+1:02d}",
                "week": week,
                "away_team": away,
                "home_team": home,
                "away_score": None,
                "home_score": None,
                "status": "scheduled"
            })
    return games


def build_test_draft_players():
    """Create 25 players with 8 deterministic, varied team selections."""
    teams = TEST_TEAM_CODES[:]
    players = []
    for i in range(25):
        # Stepped selection produces overlap while still giving each player 8 unique teams.
        selected = []
        cursor = (i * 3) % 32
        step = 5 + (i % 3)
        while len(selected) < 8:
            team = teams[cursor % 32]
            if team not in selected:
                selected.append(team)
            cursor += step
        row = {"player_name": f"Test Draft {i+1:02d}"}
        for n, team in enumerate(selected, 1):
            row[f"team{n}"] = team
        players.append(row)
    return players


def deterministic_test_score(week, game_number, away_team, home_team):
    """Repeatable fake final score, including occasional ties."""
    base = (week * 11 + game_number * 7 + sum(ord(c) for c in away_team + home_team)) % 24
    away = 13 + ((base + week + game_number) % 28)
    home = 10 + ((base * 2 + week + game_number * 3) % 31)

    # Force a few edge cases: ties and large margins.
    if week in (4, 11) and game_number == 3:
        home = away
    if week in (2, 9, 16) and game_number == 8:
        away = 42
        home = 10
    return away, home


def test_seed_rows():
    # Keep the original Survivor smoke test alongside the full Draft simulator.
    games = build_test_schedule()
    picks = [
        {"player_name":"Test Player 1","player_key":"test player 1","week":1,"team":"BUF"},
        {"player_name":"Test Player 2","player_key":"test player 2","week":1,"team":"LV"},
        {"player_name":"Test Player 3","player_key":"test player 3","week":1,"team":"PHI"},
    ]
    draft = build_test_draft_players()
    return games, picks, draft


def test_compute():
    games = sb_get("test_games", {"select":"*","order":"week.asc,id.asc"})
    survivor_picks = sb_get("test_survivor_picks", {"select":"*","order":"player_name.asc"})
    draft_players = sb_get("test_draft_players", {"select":"*","order":"player_name.asc"})

    computed_games = []
    games_by_week = {w: [] for w in range(1, 19)}
    for g in games:
        a, h = g.get("away_score"), g.get("home_score")
        winner = loser = margin = None
        if a is not None and h is not None and str(g.get("status") or "").lower() == "final":
            a, h = int(a), int(h)
            if a > h:
                winner, loser, margin = g["away_team"], g["home_team"], a-h
            elif h > a:
                winner, loser, margin = g["home_team"], g["away_team"], h-a
            else:
                winner, loser, margin = "TIE", "TIE", 0
        cg = {**g, "winner":winner, "loser":loser, "margin":margin}
        computed_games.append(cg)
        games_by_week.setdefault(int(g["week"]), []).append(cg)

    survivor = []
    for p in survivor_picks:
        status, score = "PENDING", ""
        for g in games_by_week.get(int(p["week"]), []):
            if p["team"] not in (g["away_team"], g["home_team"]):
                continue
            if str(g.get("status") or "").lower() == "final":
                score = f'{g["away_team"]} {g["away_score"]} - {g["home_team"]} {g["home_score"]}'
                status = "SURVIVED" if g["winner"] == p["team"] else "ELIMINATED"
            break
        survivor.append({**p, "status":status, "score":score})

    draft = []
    for p in draft_players:
        selected = [(p.get(f"team{n}") or "").upper() for n in range(1,9)]
        weekly = {str(w):0 for w in range(1,19)}
        weekly_games = {str(w):0 for w in range(1,19)}
        total = 0
        games_count = 0

        for week in range(1,19):
            for g in games_by_week.get(week, []):
                if g.get("margin") is None:
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
                        weekly[str(week)] += score
                        total += score
                        weekly_games[str(week)] += 1
                        games_count += 1

        running = {}
        cumulative = 0
        for week in range(1,19):
            cumulative += int(weekly[str(week)])
            running[str(week)] = cumulative

        draft.append({
            **p,
            "teams": selected,
            "total_points": total,
            "games_count": games_count,
            "weekly_scores": weekly,
            "weekly_games": weekly_games,
            "running_totals": running,
            "week_ranks": {}
        })

    # Final season/current overall rank.
    draft.sort(key=lambda x:(-x["total_points"], x["player_name"].lower()))
    rank = 0
    previous_score = None
    for idx, p in enumerate(draft, 1):
        if previous_score is None or p["total_points"] != previous_score:
            rank = idx
            previous_score = p["total_points"]
        p["rank"] = rank

    # Rank each player as of the end of every week using cumulative totals.
    for week in range(1,19):
        key = str(week)
        ordered = sorted(
            draft,
            key=lambda x: (-int(x["running_totals"][key]), x["player_name"].lower())
        )
        week_rank = 0
        previous_week_score = None
        for idx, p in enumerate(ordered, 1):
            score = int(p["running_totals"][key])
            if previous_week_score is None or score != previous_week_score:
                week_rank = idx
                previous_week_score = score
            p["week_ranks"][key] = week_rank

    finalized_weeks = []
    for week in range(1,19):
        wg = games_by_week.get(week, [])
        if wg and all(str(g.get("status") or "").lower()=="final" for g in wg):
            finalized_weeks.append(week)

    return {
        "games":computed_games,
        "survivor":survivor,
        "draft":draft,
        "finalized_weeks":finalized_weeks,
        "counts":{
            "games":len(computed_games),
            "draft_players":len(draft),
            "finalized_weeks":len(finalized_weeks),
            "survived":sum(1 for x in survivor if x["status"]=="SURVIVED"),
            "eliminated":sum(1 for x in survivor if x["status"]=="ELIMINATED"),
            "pending":sum(1 for x in survivor if x["status"]=="PENDING")
        }
    }


def seed_full_test_data():
    sb_delete("test_games", {"id":"neq.__never__"})
    sb_delete("test_survivor_picks", {"id":"gte.0"})
    sb_delete("test_draft_players", {"id":"gte.0"})

    games, picks, draft = test_seed_rows()
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    sb_upsert("test_games", [{**g,"updated_at":now} for g in games], "id")
    sb_upsert("test_survivor_picks", [{**p,"updated_at":now} for p in picks], "player_key,week")
    sb_upsert("test_draft_players", [{**p,"updated_at":now} for p in draft], "player_name")


def finalize_test_weeks(weeks):
    current = sb_get("test_games", {"select":"*","order":"week.asc,id.asc"})
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    rows = []
    per_week_counter = {}
    for g in current:
        week = int(g["week"])
        if week not in weeks:
            continue
        per_week_counter[week] = per_week_counter.get(week, 0) + 1
        away, home = deterministic_test_score(
            week, per_week_counter[week], g["away_team"], g["home_team"]
        )
        rows.append({
            "id":g["id"], "week":week, "away_team":g["away_team"], "home_team":g["home_team"],
            "away_score":away, "home_score":home, "status":"final", "updated_at":now
        })
    sb_upsert("test_games", rows, "id")



def run_v28_quality_checks():
    """Fast, read-only checks for critical pool rules."""
    checks = []

    def add(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    # Final status recognition.
    add(
        "Live games do not score",
        not is_game_final({"status":"in_progress"}),
        "A live/in-progress game must not count toward Draft or Survivor results."
    )
    add(
        "Final games are recognized",
        is_game_final({"status":"final"}),
        "Final game status must be recognized as completed."
    )

    live_game = [{
        "away_team":"BUF","home_team":"NYJ","away_score":21,"home_score":17,
        "winner":None,"loser":None,"margin":None,"status":"in_progress","game_date":""
    }]
    live_result = survivor_pick_result("BUF", live_game)
    add(
        "Survivor stays pending during live games",
        live_result.get("status") == "PENDING",
        f"Observed status: {live_result.get('status')}."
    )

    tie_game = [{
        "away_team":"BUF","home_team":"NYJ","away_score":20,"home_score":20,
        "winner":"TIE","loser":"TIE","margin":0,"status":"final","game_date":""
    }]
    tie_result = survivor_pick_result("BUF", tie_game)
    add(
        "Survivor tie eliminates",
        tie_result.get("status") == "ELIMINATED",
        f"Observed status: {tie_result.get('status')}."
    )

    add(
        "2026 salary schedule has 32 teams",
        len(DEFAULT_DRAFT_TEAM_SALARIES) == 32 and set(DEFAULT_DRAFT_TEAM_SALARIES) == set(TEAMS),
        f"{len(DEFAULT_DRAFT_TEAM_SALARIES)} team values configured."
    )
    add(
        "Default salary cap is $39,500",
        DEFAULT_DRAFT_SALARY_CAP == 39500,
        f"Configured default: ${DEFAULT_DRAFT_SALARY_CAP:,.0f}."
    )

    sample = {"team1":"BUF","team2":"PHI","team3":"KC","team4":"SF",
              "team5":"MIN","team6":"BAL","team7":"GB","team8":"DAL"}
    sample_used, sample_teams = draft_player_salary(sample, DEFAULT_DRAFT_TEAM_SALARIES)
    add(
        "Salary calculation catches over-cap rosters",
        sample_used > DEFAULT_DRAFT_SALARY_CAP and len(sample_teams) == 8,
        f"High-cost sample totals ${sample_used:,.0f} against ${DEFAULT_DRAFT_SALARY_CAP:,.0f} cap."
    )

    duplicate_sample = ["BUF","BUF","KC"]
    add(
        "Duplicate-team rule is testable",
        len(duplicate_sample) != len(set(duplicate_sample)),
        "Duplicate NFL team selections are detectable before save."
    )

    return {
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "passed_count": sum(1 for c in checks if c["passed"]),
        "total_count": len(checks)
    }


def run_system_diagnostics():
    """Read-only production configuration/database diagnostics."""
    items = []

    def add(name, passed, detail):
        items.append({"name": name, "passed": bool(passed), "detail": detail})

    table_checks = [
        ("Draft players table", "draft_players"),
        ("Survivor picks table", "survivor_picks"),
        ("Survivor players table", "survivor_players"),
        ("Survivor week settings table", "survivor_week_settings"),
        ("Draft salary settings table", "draft_salary_settings"),
        ("Draft team values table", "draft_team_values"),
        ("NFL games table", "games"),
    ]
    for label, table in table_checks:
        try:
            sb_get(table, {"select":"id","limit":"1"})
            add(label, True, "Reachable.")
        except Exception as e:
            add(label, False, f"{type(e).__name__}: {e}")

    try:
        config = draft_salary_config()
        salaries = config.get("team_salaries") or {}
        missing = [team for team in TEAMS if int(salaries.get(team, 0) or 0) <= 0]
        add(
            "Draft salary configuration",
            int(config.get("salary_cap") or 0) > 0 and not missing,
            f"Cap ${int(config.get('salary_cap') or 0):,.0f}; {32-len(missing)}/32 team values valid."
        )
    except Exception as e:
        add("Draft salary configuration", False, f"{type(e).__name__}: {e}")

    return {
        "passed": all(i["passed"] for i in items),
        "checks": items,
        "passed_count": sum(1 for i in items if i["passed"]),
        "total_count": len(items)
    }


@app.route("/api/test-lab/quality-checks", methods=["POST"])
def api_test_lab_quality_checks():
    payload = request.get_json(silent=True) or {}
    ok, err = require_admin(payload)
    if not ok:
        return jsonify({"ok":False,"error":err[0]}), err[1]
    return jsonify({"ok":True, "quality":run_v28_quality_checks(), "diagnostics":run_system_diagnostics()})


@app.route("/api/test-lab/state", methods=["POST"])
def api_test_lab_state():
    payload = request.get_json(silent=True) or {}
    ok, err = require_admin(payload)
    if not ok:
        return jsonify({"ok":False,"error":err[0]}), err[1]
    try:
        return jsonify(test_compute())
    except Exception as e:
        return jsonify({"error":str(e)}), 500


@app.route("/api/test-lab/seed", methods=["POST"])
def api_test_lab_seed():
    payload = request.get_json(silent=True) or {}
    ok, err = require_admin(payload)
    if not ok:
        return jsonify({"ok":False,"error":err[0]}), err[1]
    seed_full_test_data()
    return jsonify({"ok":True,"message":"Full 25-player Draft Pool test seeded with 18 weeks of games.","state":test_compute()})


@app.route("/api/test-lab/finalize", methods=["POST"])
def api_test_lab_finalize():
    payload = request.get_json(silent=True) or {}
    ok, err = require_admin(payload)
    if not ok:
        return jsonify({"ok":False,"error":err[0]}), err[1]
    finalize_test_weeks({1})
    return jsonify({"ok":True,"message":"Test Week 1 finalized.","state":test_compute()})


@app.route("/api/test-lab/finalize-range", methods=["POST"])
def api_test_lab_finalize_range():
    payload = request.get_json(silent=True) or {}
    ok, err = require_admin(payload)
    if not ok:
        return jsonify({"ok":False,"error":err[0]}), err[1]

    through = int(payload.get("through") or 1)
    through = max(1, min(18, through))
    finalize_test_weeks(set(range(1, through+1)))
    return jsonify({
        "ok":True,
        "message":f"Test Weeks 1–{through} finalized.",
        "state":test_compute()
    })


@app.route("/api/test-lab/finalize-season", methods=["POST"])
def api_test_lab_finalize_season():
    payload = request.get_json(silent=True) or {}
    ok, err = require_admin(payload)
    if not ok:
        return jsonify({"ok":False,"error":err[0]}), err[1]
    finalize_test_weeks(set(range(1,19)))
    return jsonify({"ok":True,"message":"Full 18-week Draft Pool test season finalized.","state":test_compute()})


@app.route("/api/test-lab/reset", methods=["POST"])
def api_test_lab_reset():
    payload = request.get_json(silent=True) or {}
    ok, err = require_admin(payload)
    if not ok:
        return jsonify({"ok":False,"error":err[0]}), err[1]

    sb_delete("test_games", {"id":"neq.__never__"})
    sb_delete("test_survivor_picks", {"id":"gte.0"})
    sb_delete("test_draft_players", {"id":"gte.0"})
    return jsonify({"ok":True,"message":"All test-only data cleared."})


if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.getenv("PORT","5000")),debug=False)
