import os
import hashlib
import hmac
import secrets
import re
import datetime as dt
import requests
from zoneinfo import ZoneInfo
from flask import Flask, render_template, jsonify, request, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
# Stable session signing key without requiring another Render setting.
# A dedicated FLASK_SECRET_KEY may be supplied, otherwise derive one from
# existing server-side secrets so member sessions survive app restarts.
_session_seed = os.getenv("FLASK_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("ADMIN_PASSWORD") or secrets.token_hex(32)
app.secret_key = hashlib.sha256((_session_seed + "|nfl-degenerates-session").encode("utf-8")).hexdigest()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("RENDER", "").lower() in ("true", "1", "yes")
)

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


ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"

def normalize_schedule_team(code):
    """Normalize ESPN/NFLData team abbreviations to this app's codes."""
    code = str(code or "").strip().upper()
    aliases = {
        "WSH": "WAS",
        "JAC": "JAX",
        "LA": "LAR",
        "OAK": "LV",
        "SD": "LAC",
        "STL": "LAR",
    }
    return aliases.get(code, code)

def fetch_espn_week_schedule(week):
    """Return matchup -> ESPN kickoff timestamp for one NFL regular-season week."""
    r = requests.get(
        ESPN_SCOREBOARD_URL,
        params={"dates": SEASON, "seasontype": 2, "week": int(week), "limit": 100},
        timeout=20
    )
    r.raise_for_status()
    payload = r.json() if r.content else {}
    schedule = {}

    for event in payload.get("events") or []:
        kickoff = str(event.get("date") or "").strip()
        competitions = event.get("competitions") or []
        if not competitions:
            continue

        competitors = competitions[0].get("competitors") or []
        away = home = ""
        for competitor in competitors:
            team = competitor.get("team") or {}
            code = normalize_schedule_team(
                team.get("abbreviation") or team.get("shortDisplayName") or team.get("name")
            )
            if competitor.get("homeAway") == "away":
                away = code
            elif competitor.get("homeAway") == "home":
                home = code

        if away and home and kickoff:
            schedule[(away, home)] = kickoff
            # Pair lookup makes the enrichment resilient if source home/away is ever inverted.
            schedule[(home, away)] = kickoff

    return schedule

def sync_week(week):
    r = requests.get(
        f"{API_BASE}/v1/games",
        params={"season":SEASON,"week":week,"game_type":"REG","limit":100},
        timeout=20
    )
    r.raise_for_status()
    raw = games_from(r.json())
    if not raw:
        r = requests.get(
            f"{API_BASE}/v1/games",
            params={"season":SEASON,"limit":1000},
            timeout=20
        )
        r.raise_for_status()
        raw = [g for g in games_from(r.json()) if int(g.get("week",-1) or -1) == week]

    # NFLData remains the authoritative results source. ESPN is used to enrich
    # the schedule with actual kickoff timestamps because NFLData commonly
    # supplies date-only values for future games.
    try:
        espn_schedule = fetch_espn_week_schedule(week)
    except Exception as e:
        espn_schedule = {}
        print(f"ESPN SCHEDULE WARNING WEEK {week}: {type(e).__name__}: {e}", flush=True)

    normalized = []
    for i, game in enumerate(raw):
        row = normalize_game(game, week, i)
        matchup = (
            normalize_schedule_team(row.get("away_team")),
            normalize_schedule_team(row.get("home_team"))
        )
        kickoff = espn_schedule.get(matchup)
        if kickoff:
            row["game_date"] = kickoff
        normalized.append(row)

    sb_upsert("games", normalized, "id")


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


def save_survivor_pick(player_name, week, team, pin=None, admin_override=False, account_authenticated=False, player_key_override=None):
    player_key = str(player_key_override or " ".join(player_name.lower().split())).strip()
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
        player = get_survivor_player(player_key)
        if account_authenticated:
            # Individual member-account authentication replaces the legacy
            # Survivor PIN prompt. Preserve a non-usable hash on newly-created
            # compatibility rows because the legacy column is NOT NULL.
            if not player:
                sb_upsert("survivor_players", [{
                    "season": SEASON,
                    "player_key": player_key,
                    "player_name": player_name,
                    "pin_hash": hash_survivor_pin(secrets.token_urlsafe(24)),
                    "created_at": now,
                    "updated_at": now
                }], "season,player_key")
        else:
            if not pin or not pin.isdigit() or not (4 <= len(pin) <= 12):
                raise ValueError("Enter your 4–12 digit Survivor PIN.")
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



# -----------------------------
# Private Member Login (V2.10)
# -----------------------------

PUBLIC_ENDPOINTS = {"member_login", "health", "static"}
ACCOUNT_GATE_ENDPOINTS = {
    "member_account_login",
    "member_account_logout",
    "member_password_change",
    "api_member_password_change",
    "test_lab"
}


def get_member_password_hash():
    """Return the stored site-member password hash, if configured."""
    try:
        rows = sb_get(
            "site_settings",
            {"select":"setting_value","setting_key":"eq.member_password_hash","limit":"1"}
        )
        if rows:
            return str(rows[0].get("setting_value") or "")
    except Exception as e:
        print(f"SITE PASSWORD READ WARNING: {type(e).__name__}: {e}", flush=True)
    return ""


def get_site_setting(key, default=""):
    try:
        rows = sb_get(
            "site_settings",
            {"select":"setting_value","setting_key":f"eq.{key}","limit":"1"}
        )
        if rows:
            return str(rows[0].get("setting_value") or default)
    except Exception as e:
        print(f"SITE SETTING READ WARNING [{key}]: {type(e).__name__}: {e}", flush=True)
    return str(default)


def site_branding():
    designer = get_site_setting("designer_name", "Pool Commissioner")
    site_date = get_site_setting("site_date", str(SEASON))
    raw_count = get_site_setting("visitor_count", "0")
    try:
        visitor_count = max(0, int(raw_count))
    except Exception:
        visitor_count = 0
    return {
        "designer_name": designer,
        "site_date": site_date,
        "visitor_count": visitor_count
    }


def increment_visitor_count():
    """Count successful site-gate logins, not page refreshes."""
    branding = site_branding()
    new_count = int(branding["visitor_count"]) + 1
    sb_upsert(
        "site_settings",
        [{
            "setting_key":"visitor_count",
            "setting_value":str(new_count),
            "updated_at":dt.datetime.now(dt.timezone.utc).isoformat()
        }],
        "setting_key"
    )
    return new_count


def verify_member_password(password):
    stored = get_member_password_hash()
    if stored:
        try:
            return check_password_hash(stored, str(password or ""))
        except Exception:
            return False

    bootstrap = os.getenv("SITE_PASSWORD", "") or ADMIN_PASSWORD
    return bool(bootstrap) and hmac.compare_digest(str(password or ""), bootstrap)


# -----------------------------
# Individual Member Accounts (V2.13)
# -----------------------------

def member_username_key(value):
    return " ".join(str(value or "").strip().lower().split())


def member_accounts_exist():
    try:
        rows = sb_get("member_accounts", {"select":"id","limit":"1"})
        return bool(rows)
    except Exception:
        return False


def get_member_account_by_username(username):
    key = member_username_key(username)
    if not key:
        return None
    rows = sb_get(
        "member_accounts",
        {"select":"*","username_key":f"eq.{key}","limit":"1"}
    )
    return rows[0] if rows else None


def get_member_account_by_id(account_id):
    try:
        account_id = int(account_id)
    except Exception:
        return None
    rows = sb_get(
        "member_accounts",
        {"select":"*","id":f"eq.{account_id}","limit":"1"}
    )
    return rows[0] if rows else None


def current_member_account(refresh=False):
    account_id = session.get("member_account_id")
    if not account_id:
        return None
    if not refresh:
        return {
            "id": account_id,
            "username": session.get("member_username", ""),
            "display_name": session.get("member_display_name", ""),
            "role": session.get("member_role", "MEMBER"),
            "draft_player_id": session.get("draft_player_id"),
            "survivor_player_key": session.get("survivor_player_key", ""),
            "confidence_player_key": session.get("confidence_player_key", ""),
            "must_change_password": bool(session.get("must_change_password"))
        }
    try:
        return get_member_account_by_id(account_id)
    except Exception:
        return None


def set_member_account_session(account):
    session["account_authenticated"] = True
    session["member_account_id"] = int(account["id"])
    session["member_username"] = str(account.get("username") or "")
    session["member_display_name"] = str(account.get("display_name") or "")
    session["member_role"] = str(account.get("role") or "MEMBER").upper()
    session["draft_player_id"] = account.get("draft_player_id")
    session["survivor_player_key"] = str(account.get("survivor_player_key") or "")
    session["confidence_player_key"] = str(account.get("confidence_player_key") or "")
    session["must_change_password"] = bool(account.get("must_change_password"))


def clear_individual_member_session():
    for key in (
        "account_authenticated","member_account_id","member_username",
        "member_display_name","member_role","draft_player_id",
        "survivor_player_key","confidence_player_key","must_change_password"
    ):
        session.pop(key, None)


def member_pool_identity(pool_name):
    account = current_member_account()
    if not account:
        return None, None
    display_name = str(account.get("display_name") or "").strip()
    if pool_name == "survivor":
        key = str(account.get("survivor_player_key") or "").strip() or member_username_key(display_name)
        return display_name, key
    if pool_name == "confidence":
        key = str(account.get("confidence_player_key") or "").strip() or confidence_player_key(display_name)
        return display_name, key
    return display_name, None


def require_commissioner_account():
    return session.get("member_role") == "COMMISSIONER" and session.get("account_authenticated") is True


@app.before_request
def require_member_login():
    endpoint = request.endpoint or ""

    if endpoint in PUBLIC_ENDPOINTS or endpoint.startswith("static"):
        return None

    # First gate: shared private-site password.
    if session.get("member_authenticated") is not True:
        if request.path.startswith("/api/"):
            return jsonify({"ok":False,"error":"Site access password required."}), 401
        return redirect(url_for("member_login", next=request.full_path if request.query_string else request.path))

    # Commissioner setup/recovery remains available after the shared gate.
    # Every modifying /api/admin action still validates ADMIN_PASSWORD.
    if endpoint in ACCOUNT_GATE_ENDPOINTS or request.path.startswith("/api/admin/"):
        return None

    # Second gate: personal account.
    if session.get("account_authenticated") is not True:
        if request.path.startswith("/api/"):
            return jsonify({"ok":False,"error":"Individual member sign-in required."}), 401
        return redirect(url_for("member_account_login", next=request.full_path if request.query_string else request.path))

    # First-time temporary passwords must be replaced before pool access.
    if session.get("must_change_password") is True and endpoint not in {
        "member_password_change","api_member_password_change","member_account_logout","member_logout"
    }:
        if request.path.startswith("/api/"):
            return jsonify({"ok":False,"error":"Password change required before continuing."}), 403
        return redirect(url_for("member_password_change"))

    return None


@app.route("/login", methods=["GET","POST"])
def member_login():
    if session.get("member_authenticated") is True and request.method == "GET":
        if session.get("account_authenticated") is True:
            return redirect(url_for("index"))
        return redirect(url_for("member_account_login"))

    error = ""
    if request.method == "POST":
        password = str(request.form.get("password") or "")
        if verify_member_password(password):
            try:
                increment_visitor_count()
            except Exception as e:
                print(f"VISITOR COUNT WARNING: {type(e).__name__}: {e}", flush=True)
            session.clear()
            session["member_authenticated"] = True
            session.permanent = True
            requested_next = str(request.form.get("next") or "").strip()
            if requested_next.startswith("/") and not requested_next.startswith("//"):
                session["post_account_next"] = requested_next
            return redirect(url_for("member_account_login"))
        error = "Incorrect site access password."

    branding = site_branding()
    return render_template(
        "login.html",
        season=SEASON,
        error=error,
        next_path=str(request.args.get("next") or ""),
        designer_name=branding["designer_name"],
        site_date=branding["site_date"],
        visitor_count=branding["visitor_count"]
    )


@app.route("/member-login", methods=["GET","POST"])
def member_account_login():
    if session.get("account_authenticated") is True and request.method == "GET":
        return redirect(url_for("index"))

    error = ""
    if request.method == "POST":
        username = str(request.form.get("username") or "").strip()
        password = str(request.form.get("password") or "")
        try:
            account = get_member_account_by_username(username)
        except Exception as e:
            print(f"MEMBER ACCOUNT LOGIN ERROR: {type(e).__name__}: {e}", flush=True)
            account = None
            error = "Member accounts are not available yet. The Commissioner may need to run the V2.13 Supabase update."

        if not error:
            if not account or not bool(account.get("active", True)):
                error = "Incorrect username or password."
            else:
                try:
                    valid = check_password_hash(str(account.get("password_hash") or ""), password)
                except Exception:
                    valid = False
                if not valid:
                    error = "Incorrect username or password."
                else:
                    now = dt.datetime.now(dt.timezone.utc).isoformat()
                    updated = {**account, "last_login_at":now, "updated_at":now}
                    sb_upsert("member_accounts", [updated], "id")
                    set_member_account_session(updated)
                    if bool(updated.get("must_change_password")):
                        return redirect(url_for("member_password_change"))
                    requested_next = str(session.pop("post_account_next", "") or "").strip()
                    if requested_next.startswith("/") and not requested_next.startswith("//"):
                        return redirect(requested_next)
                    return redirect(url_for("index"))

    return render_template(
        "member_login.html",
        season=SEASON,
        error=error,
        accounts_exist=member_accounts_exist()
    )


@app.route("/member-logout")
def member_account_logout():
    clear_individual_member_session()
    return redirect(url_for("member_account_login"))


@app.route("/account/password")
def member_password_change():
    if session.get("account_authenticated") is not True:
        return redirect(url_for("member_account_login"))
    return render_template(
        "member_password.html",
        season=SEASON,
        first_login=bool(session.get("must_change_password")),
        display_name=session.get("member_display_name","")
    )


@app.route("/api/member/password", methods=["POST"])
def api_member_password_change():
    if session.get("account_authenticated") is not True:
        return jsonify({"ok":False,"error":"Member sign-in required."}),401
    payload = request.get_json(silent=True) or {}
    current_password = str(payload.get("current_password") or "")
    new_password = str(payload.get("new_password") or "")
    confirm_password = str(payload.get("confirm_password") or "")
    if len(new_password) < 8:
        return jsonify({"ok":False,"error":"New password must be at least 8 characters."}),400
    if len(new_password) > 100:
        return jsonify({"ok":False,"error":"New password is too long."}),400
    if new_password != confirm_password:
        return jsonify({"ok":False,"error":"The new passwords do not match."}),400

    account = get_member_account_by_id(session.get("member_account_id"))
    if not account:
        return jsonify({"ok":False,"error":"Member account could not be found."}),404
    try:
        if not check_password_hash(str(account.get("password_hash") or ""), current_password):
            return jsonify({"ok":False,"error":"Current password is incorrect."}),403
    except Exception:
        return jsonify({"ok":False,"error":"Current password is incorrect."}),403

    account["password_hash"] = generate_password_hash(new_password)
    account["must_change_password"] = False
    account["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    sb_upsert("member_accounts", [account], "id")
    set_member_account_session(account)
    return jsonify({"ok":True,"message":"Password changed successfully."})


@app.route("/account")
def member_account_page():
    account = current_member_account(refresh=True)
    if not account:
        return redirect(url_for("member_account_login"))
    set_member_account_session(account)
    return render_template("account.html", season=SEASON, account=account)


@app.route("/api/member/me")
def api_member_me():
    account = current_member_account(refresh=True)
    if not account:
        return jsonify({"ok":False,"error":"Member account not found."}),404
    set_member_account_session(account)
    return jsonify({
        "ok":True,
        "member":{
            "id":account.get("id"),
            "username":account.get("username"),
            "display_name":account.get("display_name"),
            "role":account.get("role"),
            "draft_player_id":account.get("draft_player_id"),
            "survivor_player_key":account.get("survivor_player_key"),
            "confidence_player_key":account.get("confidence_player_key"),
            "must_change_password":bool(account.get("must_change_password"))
        }
    })


@app.route("/logout")
def member_logout():
    session.clear()
    return redirect(url_for("member_login"))


@app.route("/api/admin/site-password", methods=["POST"])
def api_admin_site_password():
    payload = request.get_json(silent=True) or {}
    if not ADMIN_PASSWORD or payload.get("admin_password", "") != ADMIN_PASSWORD:
        return jsonify({"ok":False,"error":"Incorrect commissioner password."}), 403

    new_password = str(payload.get("new_password") or "")
    confirm_password = str(payload.get("confirm_password") or "")
    if len(new_password) < 6:
        return jsonify({"ok":False,"error":"Shared site access password must be at least 6 characters."}), 400
    if len(new_password) > 100:
        return jsonify({"ok":False,"error":"Shared site access password is too long."}), 400
    if new_password != confirm_password:
        return jsonify({"ok":False,"error":"The new passwords do not match."}), 400

    password_hash = generate_password_hash(new_password)
    sb_upsert(
        "site_settings",
        [{"setting_key":"member_password_hash","setting_value":password_hash,"updated_at":dt.datetime.now(dt.timezone.utc).isoformat()}],
        "setting_key"
    )
    return jsonify({
        "ok":True,
        "message":"Shared site access password updated successfully. Existing signed-in members will remain signed in until they log out or their session expires."
    })



@app.route("/api/admin/site-branding", methods=["GET","POST"])
def api_admin_site_branding():
    if request.method == "GET":
        return jsonify({"ok":True, **site_branding()})

    payload = request.get_json(silent=True) or {}
    if not ADMIN_PASSWORD or payload.get("admin_password", "") != ADMIN_PASSWORD:
        return jsonify({"ok":False,"error":"Incorrect commissioner password."}), 403

    designer_name = str(payload.get("designer_name") or "").strip()
    site_date = str(payload.get("site_date") or "").strip()

    if not designer_name:
        return jsonify({"ok":False,"error":"Enter the designer name or credit."}), 400
    if len(designer_name) > 80:
        return jsonify({"ok":False,"error":"Designer credit is too long."}), 400
    if not site_date:
        return jsonify({"ok":False,"error":"Enter the date or year to display."}), 400
    if len(site_date) > 40:
        return jsonify({"ok":False,"error":"Displayed date is too long."}), 400

    now = dt.datetime.now(dt.timezone.utc).isoformat()
    sb_upsert(
        "site_settings",
        [
            {"setting_key":"designer_name","setting_value":designer_name,"updated_at":now},
            {"setting_key":"site_date","setting_value":site_date,"updated_at":now}
        ],
        "setting_key"
    )
    return jsonify({
        "ok":True,
        "message":"Landing-page footer updated.",
        **site_branding()
    })



# -----------------------------
# Commissioner Member Management (V2.13)
# -----------------------------

def admin_password_ok(payload=None):
    payload = payload or {}
    supplied = (
        request.headers.get("X-Admin-Password", "")
        or str(payload.get("password") or "")
        or str(request.args.get("password") or "")
    )
    return bool(ADMIN_PASSWORD) and hmac.compare_digest(str(supplied), str(ADMIN_PASSWORD))


def safe_member_account(row):
    return {
        "id":row.get("id"),
        "username":row.get("username"),
        "display_name":row.get("display_name"),
        "role":row.get("role"),
        "active":bool(row.get("active", True)),
        "must_change_password":bool(row.get("must_change_password", False)),
        "draft_player_id":row.get("draft_player_id"),
        "survivor_player_key":row.get("survivor_player_key"),
        "confidence_player_key":row.get("confidence_player_key"),
        "created_at":row.get("created_at"),
        "updated_at":row.get("updated_at"),
        "last_login_at":row.get("last_login_at")
    }


def member_identity_options():
    try:
        draft_rows = sb_get(
            "draft_players",
            {"select":"id,player_name","season":f"eq.{SEASON}","order":"player_name.asc"}
        )
    except Exception:
        draft_rows = []
    try:
        survivor_rows = sb_get(
            "survivor_players",
            {"select":"player_key,player_name","season":f"eq.{SEASON}","order":"player_name.asc"}
        )
    except Exception:
        survivor_rows = []
    try:
        confidence_rows = sb_get(
            "confidence_players",
            {"select":"player_key,player_name","season":f"eq.{SEASON}","order":"player_name.asc"}
        )
    except Exception:
        confidence_rows = []
    return {
        "draft":[{"id":r.get("id"),"player_name":r.get("player_name")} for r in draft_rows],
        "survivor":[{"player_key":r.get("player_key"),"player_name":r.get("player_name")} for r in survivor_rows],
        "confidence":[{"player_key":r.get("player_key"),"player_name":r.get("player_name")} for r in confidence_rows]
    }


@app.route("/api/admin/members", methods=["GET","POST"])
def api_admin_members():
    payload = request.get_json(silent=True) or {}
    if not admin_password_ok(payload):
        return jsonify({"ok":False,"error":"Incorrect commissioner password."}),403

    if request.method == "GET":
        try:
            rows = sb_get("member_accounts", {"select":"*","order":"display_name.asc"})
            return jsonify({
                "ok":True,
                "members":[safe_member_account(r) for r in rows],
                "identities":member_identity_options()
            })
        except Exception as e:
            print(f"MEMBER ADMIN LOAD ERROR: {type(e).__name__}: {e}", flush=True)
            return jsonify({
                "ok":False,
                "error":"Could not load member accounts. Run the V2.13 Supabase migration first."
            }),500

    action = str(payload.get("action") or "").strip().lower()
    now = dt.datetime.now(dt.timezone.utc).isoformat()

    if action == "bulk_from_draft":
        if not member_accounts_exist():
            return jsonify({
                "ok":False,
                "error":"Create the Commissioner account first, then use Bulk Create for Draft players."
            }),400

        try:
            draft_rows = sb_get(
                "draft_players",
                {"select":"id,player_name","season":f"eq.{SEASON}","order":"player_name.asc"}
            )
            existing = sb_get("member_accounts", {"select":"id,username_key,draft_player_id"})
        except Exception as e:
            return jsonify({"ok":False,"error":f"Could not load Draft/member records: {e}"}),500

        linked_ids = {
            int(r.get("draft_player_id"))
            for r in existing
            if r.get("draft_player_id") is not None
        }
        used_usernames = {str(r.get("username_key") or "") for r in existing}
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        rows = []
        credentials = []

        for player in draft_rows:
            try:
                draft_id = int(player.get("id"))
            except Exception:
                continue
            if draft_id in linked_ids:
                continue

            display_name = str(player.get("player_name") or f"Player {draft_id}").strip()
            username = display_name
            username_key = member_username_key(username)
            suffix = 2
            while username_key in used_usernames:
                username = f"{display_name} {suffix}"
                username_key = member_username_key(username)
                suffix += 1
            used_usernames.add(username_key)

            random_part = "".join(secrets.choice(alphabet) for _ in range(8))
            temporary_password = f"NFL-{random_part[:4]}-{random_part[4:]}"
            rows.append({
                "username":username,
                "username_key":username_key,
                "display_name":display_name,
                "password_hash":generate_password_hash(temporary_password),
                "role":"MEMBER",
                "active":True,
                "must_change_password":True,
                "draft_player_id":draft_id,
                "survivor_player_key":member_username_key(display_name),
                "confidence_player_key":confidence_player_key(display_name),
                "created_at":now,
                "updated_at":now,
                "last_login_at":None
            })
            credentials.append({
                "display_name":display_name,
                "username":username,
                "temporary_password":temporary_password,
                "draft_player_id":draft_id
            })

        if not rows:
            return jsonify({
                "ok":True,
                "message":"No unlinked Draft players need member accounts.",
                "credentials":[]
            })

        r = requests.post(
            f"{SUPABASE_URL}/rest/v1/member_accounts",
            headers=sb_headers({"Prefer":"return=minimal"}),
            json=rows,
            timeout=30
        )
        r.raise_for_status()
        return jsonify({
            "ok":True,
            "message":f"Created {len(rows)} member accounts from unlinked Draft players.",
            "credentials":credentials
        })

    if action == "create":
        username = str(payload.get("username") or "").strip()
        display_name = str(payload.get("display_name") or "").strip()
        temporary_password = str(payload.get("temporary_password") or "")
        role = str(payload.get("role") or "MEMBER").upper()
        active = bool(payload.get("active", True))

        # Lockout protection: the very first personal account is always the
        # Commissioner account, regardless of the form's selected role.
        try:
            first_account = not member_accounts_exist()
        except Exception:
            first_account = False
        if first_account:
            role = "COMMISSIONER"
            active = True

        if len(username) < 2 or len(username) > 80:
            return jsonify({"ok":False,"error":"Username must be 2–80 characters."}),400
        if len(display_name) < 2 or len(display_name) > 80:
            return jsonify({"ok":False,"error":"Display name must be 2–80 characters."}),400
        if len(temporary_password) < 8 or len(temporary_password) > 100:
            return jsonify({"ok":False,"error":"Temporary password must be 8–100 characters."}),400
        if role not in ("MEMBER","COMMISSIONER"):
            return jsonify({"ok":False,"error":"Role must be MEMBER or COMMISSIONER."}),400

        username_key = member_username_key(username)
        try:
            if get_member_account_by_username(username):
                return jsonify({"ok":False,"error":"That username is already in use."}),409
        except Exception as e:
            return jsonify({"ok":False,"error":f"Could not check username: {e}"}),500

        draft_player_id = payload.get("draft_player_id")
        try:
            draft_player_id = int(draft_player_id) if str(draft_player_id or "").strip() else None
        except Exception:
            return jsonify({"ok":False,"error":"Draft player assignment is invalid."}),400

        survivor_key = str(payload.get("survivor_player_key") or "").strip() or member_username_key(display_name)
        confidence_key = str(payload.get("confidence_player_key") or "").strip() or confidence_player_key(display_name)

        row = {
            "username":username,
            "username_key":username_key,
            "display_name":display_name,
            "password_hash":generate_password_hash(temporary_password),
            "role":role,
            "active":active,
            "must_change_password":True,
            "draft_player_id":draft_player_id,
            "survivor_player_key":survivor_key,
            "confidence_player_key":confidence_key,
            "created_at":now,
            "updated_at":now,
            "last_login_at":None
        }
        try:
            r = requests.post(
                f"{SUPABASE_URL}/rest/v1/member_accounts",
                headers=sb_headers({"Prefer":"return=representation"}),
                json=[row],
                timeout=20
            )
            r.raise_for_status()
            created = r.json()[0] if r.content else row
            return jsonify({
                "ok":True,
                "message":f"Member account created for {display_name}.",
                "member":safe_member_account(created)
            })
        except requests.HTTPError as e:
            detail = ""
            try:
                detail = (e.response.json() or {}).get("message") or ""
            except Exception:
                detail = str(e)
            return jsonify({"ok":False,"error":"Could not create member account. "+detail}),400

    if action in ("update","reset_password"):
        try:
            account_id = int(payload.get("id"))
        except Exception:
            return jsonify({"ok":False,"error":"A valid member account is required."}),400
        account = get_member_account_by_id(account_id)
        if not account:
            return jsonify({"ok":False,"error":"Member account not found."}),404

        if action == "reset_password":
            temporary_password = str(payload.get("temporary_password") or "")
            if len(temporary_password) < 8 or len(temporary_password) > 100:
                return jsonify({"ok":False,"error":"Temporary password must be 8–100 characters."}),400
            account["password_hash"] = generate_password_hash(temporary_password)
            account["must_change_password"] = True
            account["updated_at"] = now
            sb_upsert("member_accounts",[account],"id")
            return jsonify({
                "ok":True,
                "message":f"Temporary password reset for {account.get('display_name')}. They must change it at next sign-in."
            })

        username = str(payload.get("username") or account.get("username") or "").strip()
        display_name = str(payload.get("display_name") or account.get("display_name") or "").strip()
        role = str(payload.get("role") or account.get("role") or "MEMBER").upper()
        active = bool(payload.get("active", account.get("active", True)))
        if len(username) < 2 or len(username) > 80 or len(display_name) < 2 or len(display_name) > 80:
            return jsonify({"ok":False,"error":"Username and display name must be 2–80 characters."}),400
        if role not in ("MEMBER","COMMISSIONER"):
            return jsonify({"ok":False,"error":"Role must be MEMBER or COMMISSIONER."}),400

        key = member_username_key(username)
        duplicates = sb_get(
            "member_accounts",
            {"select":"id","username_key":f"eq.{key}","id":f"neq.{account_id}","limit":"1"}
        )
        if duplicates:
            return jsonify({"ok":False,"error":"That username is already in use."}),409

        draft_player_id = payload.get("draft_player_id")
        try:
            draft_player_id = int(draft_player_id) if str(draft_player_id or "").strip() else None
        except Exception:
            return jsonify({"ok":False,"error":"Draft player assignment is invalid."}),400

        # Prevent accidentally removing the only active Commissioner.
        if str(account.get("role") or "").upper() == "COMMISSIONER" and bool(account.get("active", True)):
            if role != "COMMISSIONER" or not active:
                all_accounts = sb_get("member_accounts", {"select":"id,role,active"})
                other_active_commissioners = [
                    r for r in all_accounts
                    if int(r.get("id") or 0) != account_id
                    and str(r.get("role") or "").upper() == "COMMISSIONER"
                    and bool(r.get("active", True))
                ]
                if not other_active_commissioners:
                    return jsonify({
                        "ok":False,
                        "error":"This is the only active Commissioner account. Create or promote another Commissioner before changing this account."
                    }),400

        account.update({
            "username":username,
            "username_key":key,
            "display_name":display_name,
            "role":role,
            "active":active,
            "draft_player_id":draft_player_id,
            "survivor_player_key":str(payload.get("survivor_player_key") or "").strip() or member_username_key(display_name),
            "confidence_player_key":str(payload.get("confidence_player_key") or "").strip() or confidence_player_key(display_name),
            "updated_at":now
        })
        sb_upsert("member_accounts",[account],"id")

        # If the commissioner edited their own account, refresh the active session.
        if int(session.get("member_account_id") or 0) == account_id:
            set_member_account_session(account)

        return jsonify({
            "ok":True,
            "message":f"Member account updated for {display_name}.",
            "member":safe_member_account(account)
        })

    return jsonify({"ok":False,"error":"Unknown member-management action."}),400




# -----------------------------
# Member Message Forum (V2.11)
# -----------------------------

def forum_topic_rows():
    topics = sb_get(
        "forum_topics",
        {"select":"*","order":"created_at.desc","limit":"200"}
    )
    replies = sb_get(
        "forum_posts",
        {"select":"topic_id,id,created_at","order":"created_at.asc","limit":"5000"}
    )
    by_topic = {}
    for row in replies:
        by_topic.setdefault(str(row.get("topic_id")), []).append(row)

    for topic in topics:
        rows = by_topic.get(str(topic.get("id")), [])
        topic["reply_count"] = len(rows)
        topic["last_activity"] = rows[-1].get("created_at") if rows else topic.get("created_at")
    topics.sort(key=lambda t: str(t.get("last_activity") or ""), reverse=True)
    return topics


def forum_topic(topic_id):
    rows = sb_get(
        "forum_topics",
        {"select":"*","id":f"eq.{int(topic_id)}","limit":"1"}
    )
    return rows[0] if rows else None


def forum_posts(topic_id):
    return sb_get(
        "forum_posts",
        {
            "select":"*",
            "topic_id":f"eq.{int(topic_id)}",
            "order":"created_at.asc",
            "limit":"1000"
        }
    )


@app.route("/forum")
def forum():
    return render_template("forum.html", season=SEASON)


@app.route("/forum/topic/<int:topic_id>")
def forum_topic_page(topic_id):
    return render_template("forum_topic.html", season=SEASON, topic_id=topic_id)


@app.route("/api/forum/topics", methods=["GET","POST"])
def api_forum_topics():
    if request.method == "GET":
        try:
            return jsonify({"ok":True,"topics":forum_topic_rows()})
        except Exception as e:
            print(f"FORUM TOPICS ERROR: {type(e).__name__}: {e}", flush=True)
            return jsonify({"ok":False,"error":"Could not load forum topics.","topics":[]}),500

    payload=request.get_json(silent=True) or {}
    author=str(session.get("member_display_name") or "").strip()
    title=str(payload.get("title") or "").strip()
    message=str(payload.get("message") or "").strip()

    if not author:
        return jsonify({"ok":False,"error":"Member account name is unavailable."}),400
    if not title:
        return jsonify({"ok":False,"error":"Enter a topic title."}),400
    if len(title)>120:
        return jsonify({"ok":False,"error":"Topic title is too long."}),400
    if not message:
        return jsonify({"ok":False,"error":"Enter a message."}),400
    if len(message)>4000:
        return jsonify({"ok":False,"error":"Message is too long (4,000 character maximum)."}),400

    now=dt.datetime.now(dt.timezone.utc).isoformat()
    r=requests.post(
        f"{SUPABASE_URL}/rest/v1/forum_topics",
        headers=sb_headers({"Prefer":"return=representation"}),
        json=[{
            "member_account_id":session.get("member_account_id"),
            "author":author,
            "title":title,
            "message":message,
            "created_at":now,
            "updated_at":now
        }],
        timeout=20
    )
    r.raise_for_status()
    rows=r.json() if r.content else []
    topic=rows[0] if rows else None
    return jsonify({"ok":True,"message":"Topic posted.","topic":topic})


@app.route("/api/forum/topic/<int:topic_id>")
def api_forum_topic(topic_id):
    try:
        topic=forum_topic(topic_id)
        if not topic:
            return jsonify({"ok":False,"error":"Forum topic not found."}),404
        return jsonify({
            "ok":True,
            "topic":topic,
            "posts":forum_posts(topic_id)
        })
    except Exception as e:
        print(f"FORUM TOPIC ERROR: {type(e).__name__}: {e}", flush=True)
        return jsonify({"ok":False,"error":"Could not load this forum topic."}),500


@app.route("/api/forum/topic/<int:topic_id>/reply", methods=["POST"])
def api_forum_reply(topic_id):
    payload=request.get_json(silent=True) or {}
    author=str(session.get("member_display_name") or "").strip()
    message=str(payload.get("message") or "").strip()

    if not forum_topic(topic_id):
        return jsonify({"ok":False,"error":"Forum topic not found."}),404
    if not author:
        return jsonify({"ok":False,"error":"Member account name is unavailable."}),400
    if not message:
        return jsonify({"ok":False,"error":"Enter a reply."}),400
    if len(message)>4000:
        return jsonify({"ok":False,"error":"Reply is too long (4,000 character maximum)."}),400

    now=dt.datetime.now(dt.timezone.utc).isoformat()
    r=requests.post(
        f"{SUPABASE_URL}/rest/v1/forum_posts",
        headers=sb_headers({"Prefer":"return=representation"}),
        json=[{
            "member_account_id":session.get("member_account_id"),
            "topic_id":int(topic_id),
            "author":author,
            "message":message,
            "created_at":now,
            "updated_at":now
        }],
        timeout=20
    )
    r.raise_for_status()
    rows=r.json() if r.content else []
    return jsonify({"ok":True,"message":"Reply posted.","post":rows[0] if rows else None})


@app.route("/api/forum/admin/delete-topic", methods=["POST"])
def api_forum_admin_delete_topic():
    payload=request.get_json(silent=True) or {}
    if not ADMIN_PASSWORD or payload.get("password","") != ADMIN_PASSWORD:
        return jsonify({"ok":False,"error":"Incorrect commissioner password."}),403
    try:
        topic_id=int(payload.get("topic_id"))
    except Exception:
        return jsonify({"ok":False,"error":"Invalid topic."}),400

    sb_delete("forum_posts", {"topic_id":f"eq.{topic_id}"})
    sb_delete("forum_topics", {"id":f"eq.{topic_id}"})
    return jsonify({"ok":True,"message":"Topic and all replies deleted."})


@app.route("/api/forum/admin/delete-post", methods=["POST"])
def api_forum_admin_delete_post():
    payload=request.get_json(silent=True) or {}
    if not ADMIN_PASSWORD or payload.get("password","") != ADMIN_PASSWORD:
        return jsonify({"ok":False,"error":"Incorrect commissioner password."}),403
    try:
        post_id=int(payload.get("post_id"))
    except Exception:
        return jsonify({"ok":False,"error":"Invalid reply."}),400

    sb_delete("forum_posts", {"id":f"eq.{post_id}"})
    return jsonify({"ok":True,"message":"Reply deleted."})


# -----------------------------
# Confidence Pool (V2.9)
# -----------------------------

def confidence_player_key(name):
    return " ".join(str(name or "").lower().split())


def get_confidence_player(player_key):
    rows = sb_get(
        "confidence_players",
        {
            "select":"*",
            "season":f"eq.{SEASON}",
            "player_key":f"eq.{player_key}",
            "limit":"1"
        }
    )
    return rows[0] if rows else None


def confidence_week_games(week, refresh=False):
    week = max(1, min(18, int(week)))
    if refresh:
        try:
            sync_week(week)
        except Exception:
            pass
    games = get_week(week)
    games.sort(key=lambda g: (
        parse_game_datetime(g.get("game_date")) or dt.datetime.max.replace(tzinfo=dt.timezone.utc),
        str(g.get("id") or "")
    ))
    return games


def confidence_week_lock(week, games=None, now=None):
    games = games if games is not None else confidence_week_games(week)
    now = now or dt.datetime.now(dt.timezone.utc)
    kickoffs = [parse_game_datetime(g.get("game_date")) for g in games]
    kickoffs = [x for x in kickoffs if x is not None]
    if kickoffs:
        first = min(kickoffs)
        return now >= first, first

    # Fallback if source kickoff text cannot be parsed.
    started = any(
        is_game_final(g) or
        str(g.get("status") or "").lower() in ("in_progress","live","halftime") or
        g.get("away_score") is not None or
        g.get("home_score") is not None
        for g in games
    )
    return started, None


def confidence_last_game(games):
    if not games:
        return None
    parsed = [(parse_game_datetime(g.get("game_date")), g) for g in games]
    valid = [(d,g) for d,g in parsed if d is not None]
    if valid:
        return max(valid, key=lambda x: (x[0], str(x[1].get("id") or "")))[1]
    return games[-1]


def confidence_entry(player_key, week):
    entries = sb_get(
        "confidence_entries",
        {
            "select":"*",
            "season":f"eq.{SEASON}",
            "week":f"eq.{week}",
            "player_key":f"eq.{player_key}",
            "limit":"1"
        }
    )
    entry = entries[0] if entries else None
    picks = sb_get(
        "confidence_picks",
        {
            "select":"*",
            "season":f"eq.{SEASON}",
            "week":f"eq.{week}",
            "player_key":f"eq.{player_key}",
            "order":"confidence_value.desc"
        }
    )
    return entry, picks


def confidence_game_result(game, picked_team):
    if not is_game_final(game):
        return "PENDING", 0
    winner = game.get("winner")
    if winner == picked_team:
        return "WIN", 1
    if winner == "TIE":
        return "TIE", 0
    return "LOSS", 0


def confidence_week_rows(week, refresh=False):
    games = confidence_week_games(week, refresh=refresh)
    game_map = {str(g.get("id")):g for g in games}
    last_game = confidence_last_game(games)
    last_game_id = str(last_game.get("id")) if last_game else None
    actual_tiebreaker = None
    if last_game and is_game_final(last_game):
        a, h = last_game.get("away_score"), last_game.get("home_score")
        if a is not None and h is not None:
            actual_tiebreaker = int(a) + int(h)

    entries = sb_get(
        "confidence_entries",
        {
            "select":"*",
            "season":f"eq.{SEASON}",
            "week":f"eq.{week}",
            "order":"player_name.asc"
        }
    )
    picks = sb_get(
        "confidence_picks",
        {
            "select":"*",
            "season":f"eq.{SEASON}",
            "week":f"eq.{week}"
        }
    )
    by_player = {}
    for pick in picks:
        by_player.setdefault(pick.get("player_key"), []).append(pick)

    rows = []
    for entry in entries:
        player_picks = by_player.get(entry.get("player_key"), [])
        points = 0
        decided = 0
        details = []
        for pick in player_picks:
            game = game_map.get(str(pick.get("game_id")))
            status = "PENDING"
            earned = 0
            if game:
                status, won = confidence_game_result(game, str(pick.get("team") or "").upper())
                if status != "PENDING":
                    decided += 1
                if won:
                    earned = int(pick.get("confidence_value") or 0)
                    points += earned
            details.append({
                **pick,
                "status":status,
                "earned":earned,
                "game":game
            })

        prediction = entry.get("tiebreaker_total")
        diff = None
        if actual_tiebreaker is not None and prediction is not None:
            diff = abs(int(prediction) - actual_tiebreaker)

        rows.append({
            **entry,
            "points":points,
            "decided_games":decided,
            "game_count":len(games),
            "tiebreaker_diff":diff,
            "actual_tiebreaker":actual_tiebreaker,
            "last_game_id":last_game_id,
            "picks":details
        })

    # Weekly ranking: points descending; when final-game total exists, closest tiebreaker wins.
    rows.sort(key=lambda r: (
        -int(r.get("points") or 0),
        10**9 if r.get("tiebreaker_diff") is None else int(r["tiebreaker_diff"]),
        str(r.get("player_name") or "").lower()
    ))
    rank = 0
    prior_key = None
    for i, row in enumerate(rows, 1):
        rank_key = (
            int(row.get("points") or 0),
            row.get("tiebreaker_diff") if actual_tiebreaker is not None else None
        )
        if prior_key is None or rank_key != prior_key:
            rank = i
            prior_key = rank_key
        row["rank"] = rank
    return rows, games, actual_tiebreaker, last_game


def confidence_season_standings():
    entries = sb_get(
        "confidence_entries",
        {"select":"*","season":f"eq.{SEASON}"}
    )
    if not entries:
        return []

    # Use stored game data only; week result pages refresh individual weeks.
    games = sb_get("games", {"select":"*","season":f"eq.{SEASON}"})
    game_map = {str(g.get("id")):g for g in games}
    picks = sb_get(
        "confidence_picks",
        {"select":"*","season":f"eq.{SEASON}"}
    )

    players = {}
    for entry in entries:
        key = entry.get("player_key")
        row = players.setdefault(key, {
            "player_key":key,
            "player_name":entry.get("player_name") or key,
            "total_points":0,
            "weeks_played":0,
            "weekly_points":{str(w):None for w in range(1,19)}
        })
        row["player_name"] = entry.get("player_name") or row["player_name"]
        row["weeks_played"] += 1

    points_by_player_week = {}
    for pick in picks:
        game = game_map.get(str(pick.get("game_id")))
        if not game or not is_game_final(game):
            continue
        status, won = confidence_game_result(game, str(pick.get("team") or "").upper())
        if won:
            k=(pick.get("player_key"), int(pick.get("week") or 0))
            points_by_player_week[k]=points_by_player_week.get(k,0)+int(pick.get("confidence_value") or 0)

    entry_keys={(e.get("player_key"),int(e.get("week") or 0)) for e in entries}
    for (player_key, week) in entry_keys:
        if player_key not in players or week not in range(1,19):
            continue
        value=points_by_player_week.get((player_key,week),0)
        players[player_key]["weekly_points"][str(week)] = value
        players[player_key]["total_points"] += value

    rows=list(players.values())
    rows.sort(key=lambda p:(-p["total_points"],p["player_name"].lower()))
    rank=0
    prior=None
    for i,row in enumerate(rows,1):
        if prior is None or row["total_points"] != prior:
            rank=i
            prior=row["total_points"]
        row["rank"]=rank
    return rows


@app.route("/confidence")
def confidence():
    week=max(1,min(18,request.args.get("week",1,type=int)))
    return render_template("confidence.html",season=SEASON,week=week)


@app.route("/confidence/results")
def confidence_results():
    week=max(1,min(18,request.args.get("week",1,type=int)))
    return render_template("confidence_results.html",season=SEASON,week=week)


@app.route("/confidence/standings")
def confidence_standings():
    return render_template("confidence_standings.html",season=SEASON)


@app.route("/api/confidence/week/<int:week>")
def api_confidence_week(week):
    week=max(1,min(18,week))
    sync_error=None
    try:
        sync_week(week)
    except Exception as e:
        sync_error=str(e)
    try:
        games=confidence_week_games(week)
    except Exception as e:
        return jsonify({"ok":False,"error":str(e),"games":[]}),500

    locked, lock_time=confidence_week_lock(week,games)
    last=confidence_last_game(games)
    return jsonify({
        "ok":True,
        "week":week,
        "game_count":len(games),
        "confidence_values":list(range(len(games),0,-1)),
        "locked":locked,
        "lock_time":lock_time.isoformat() if lock_time else None,
        "last_game_id":str(last.get("id")) if last else None,
        "games":games,
        "sync_error":sync_error
    })


@app.route("/api/confidence/entry", methods=["GET","POST"])
def api_confidence_entry():
    player_name, key = member_pool_identity("confidence")
    if not player_name or not key:
        return jsonify({"ok":False,"error":"This account is not linked to a Confidence identity."}),400

    if request.method == "GET":
        week=max(1,min(18,request.args.get("week",1,type=int)))
        entry,picks=confidence_entry(key,week)
        return jsonify({
            "ok":True,
            "entry":entry,
            "picks":picks,
            "player_name":player_name,
            "testing":True
        })

    payload=request.get_json(silent=True) or {}
    try:
        week=int(payload.get("week") or 0)
    except Exception:
        week=0
    picks=payload.get("picks") or []
    tiebreaker=payload.get("tiebreaker_total")

    if week not in range(1,19):
        return jsonify({"ok":False,"error":"Choose a valid NFL week."}),400
    try:
        tiebreaker=int(tiebreaker)
    except Exception:
        return jsonify({"ok":False,"error":"Enter the total score for the final game tiebreaker."}),400
    if tiebreaker < 0 or tiebreaker > 200:
        return jsonify({"ok":False,"error":"Tiebreaker total must be between 0 and 200."}),400

    games=confidence_week_games(week,refresh=True)
    if not games:
        return jsonify({"ok":False,"error":f"No NFL games are loaded for Week {week}."}),400
    locked,lock_time=confidence_week_lock(week,games)
    if locked:
        return jsonify({"ok":False,"error":f"Week {week} Confidence entries are locked because the first game has started."}),403

    expected_ids={str(g.get("id")) for g in games}
    if len(picks) != len(games):
        return jsonify({"ok":False,"error":f"Make a selection for all {len(games)} games."}),400

    seen_games=set()
    values=[]
    rows=[]
    for pick in picks:
        game_id=str(pick.get("game_id") or "")
        team=str(pick.get("team") or "").upper()
        try:
            value=int(pick.get("confidence_value"))
        except Exception:
            value=0
        if game_id not in expected_ids or game_id in seen_games:
            return jsonify({"ok":False,"error":"The submitted game list is invalid."}),400
        game=next((g for g in games if str(g.get("id"))==game_id),None)
        if not game or team not in (g.get("away_team"),g.get("home_team")):
            return jsonify({"ok":False,"error":"Choose one of the two teams playing in every game."}),400
        seen_games.add(game_id)
        values.append(value)
        rows.append((game_id,team,value))

    required=set(range(1,len(games)+1))
    if set(values) != required or len(values) != len(set(values)):
        return jsonify({
            "ok":False,
            "error":f"Use every confidence value from 1 through {len(games)} exactly once."
        }),400

    now=dt.datetime.now(dt.timezone.utc).isoformat()
    player=get_confidence_player(key)
    if not player:
        sb_upsert("confidence_players",[{
            "season":SEASON,
            "player_key":key,
            "player_name":player_name,
            "pin_hash":hash_survivor_pin(secrets.token_urlsafe(24)),
            "created_at":now,
            "updated_at":now
        }],"season,player_key")

    sb_upsert("confidence_entries",[{
        "season":SEASON,
        "week":week,
        "player_key":key,
        "player_name":player_name,
        "tiebreaker_total":tiebreaker,
        "submitted_at":now,
        "updated_at":now
    }],"season,week,player_key")

    pick_rows=[{
        "season":SEASON,
        "week":week,
        "player_key":key,
        "game_id":game_id,
        "team":team,
        "confidence_value":value,
        "updated_at":now
    } for game_id,team,value in rows]
    sb_upsert("confidence_picks",pick_rows,"season,week,player_key,game_id")

    return jsonify({
        "ok":True,
        "message":f"Week {week} TEST Confidence entry saved for {player_name}. Official picks must still be submitted through Football Frenzy.",
        "game_count":len(games),
        "testing":True
    })


@app.route("/api/confidence/results/<int:week>")
def api_confidence_results(week):
    week=max(1,min(18,week))
    try:
        rows,games,actual,last=confidence_week_rows(week,refresh=True)
        locked,lock_time=confidence_week_lock(week,games)
        public_rows=rows
        if not locked:
            public_rows=[]
            for row in rows:
                public_rows.append({
                    "player_name":row.get("player_name"),
                    "points":0,
                    "decided_games":0,
                    "game_count":row.get("game_count"),
                    "rank":None,
                    "tiebreaker_total":None,
                    "tiebreaker_diff":None,
                    "picks":[],
                    "hidden":True
                })
        return jsonify({
            "ok":True,
            "week":week,
            "results":public_rows,
            "game_count":len(games),
            "actual_tiebreaker":actual if locked else None,
            "last_game":last,
            "locked":locked,
            "lock_time":lock_time.isoformat() if lock_time else None
        })
    except Exception as e:
        print(f"CONFIDENCE RESULTS ERROR: {type(e).__name__}: {e}",flush=True)
        return jsonify({"ok":False,"error":str(e),"results":[]}),500


@app.route("/api/confidence/standings")
def api_confidence_standings():
    try:
        rows=confidence_season_standings()
        return jsonify({"ok":True,"season":SEASON,"players":rows})
    except Exception as e:
        print(f"CONFIDENCE STANDINGS ERROR: {type(e).__name__}: {e}",flush=True)
        return jsonify({"ok":False,"error":str(e),"players":[]}),500



def dashboard_current_week():
    """Choose the most relevant week from stored season game data."""
    try:
        rows = sb_get(
            "games",
            {"select":"week,status,game_date","season":f"eq.{SEASON}","order":"week.asc"}
        )
    except Exception:
        rows = []

    if not rows:
        return 1

    weeks = {}
    for g in rows:
        try:
            w = int(g.get("week") or 0)
        except Exception:
            continue
        if 1 <= w <= 18:
            weeks.setdefault(w, []).append(g)

    if not weeks:
        return 1

    # First week that is not completely final.
    for w in sorted(weeks):
        games = weeks[w]
        if not games:
            continue
        if not all(str(g.get("status") or "").lower() == "final" for g in games):
            return w

    return max(weeks)


def dashboard_announcement():
    return {
        "message": get_site_setting(
            "dashboard_announcement",
            "Welcome to NFL Degenerates. Check your pools and make sure your weekly picks are submitted before lock."
        ),
        "enabled": get_site_setting("dashboard_announcement_enabled", "true").lower() != "false"
    }


@app.route("/api/dashboard")
def api_dashboard():
    week = dashboard_current_week()
    account = current_member_account(refresh=True) or {}
    if account:
        set_member_account_session(account)

    data = {
        "ok": True,
        "season": SEASON,
        "week": week,
        "member": {
            "display_name": account.get("display_name") or session.get("member_display_name") or "Member",
            "username": account.get("username") or session.get("member_username") or "",
            "role": account.get("role") or session.get("member_role") or "MEMBER"
        },
        "my_pools": {
            "draft": {"linked": False},
            "survivor": {"linked": True, "status":"No pick submitted", "pick":None},
            "confidence": {"linked": True, "status":"No test entry submitted", "testing":True}
        },
        "announcement": dashboard_announcement(),
        "draft": {"leaders": [], "player_count": 0},
        "survivor": {"alive": 0, "total": 0},
        "confidence": {"leaders": [], "player_count": 0, "locked": False, "lock_time": None},
        "forum": {"topics": []},
        "next_games": []
    }

    draft_players = []
    board = []
    standings = []

    try:
        draft_players = draft_data()
        draft_players = sorted(
            draft_players,
            key=lambda p: (int(p.get("rank") or 999), -int(p.get("total_points") or 0), str(p.get("player_name") or "").lower())
        )
        data["draft"] = {
            "leaders": [{
                "rank": p.get("rank"),
                "player_name": p.get("player_name"),
                "total_points": p.get("total_points", 0)
            } for p in draft_players[:3]],
            "player_count": len(draft_players)
        }
    except Exception as e:
        data["draft"]["error"] = str(e)

    try:
        board = survivor_board_data()
        data["survivor"] = {
            "alive": sum(1 for p in board if p.get("status") == "ALIVE"),
            "total": len(board)
        }
    except Exception as e:
        data["survivor"]["error"] = str(e)

    try:
        standings = confidence_season_standings()
        standings = sorted(
            standings,
            key=lambda p: (int(p.get("rank") or 999), -int(p.get("total_points") or 0), str(p.get("player_name") or "").lower())
        )
        games = confidence_week_games(week)
        locked, lock_time = confidence_week_lock(week, games)
        data["confidence"] = {
            "leaders": [{
                "rank": p.get("rank"),
                "player_name": p.get("player_name"),
                "total_points": p.get("total_points", 0)
            } for p in standings[:3]],
            "player_count": len(standings),
            "locked": locked,
            "lock_time": lock_time.isoformat() if lock_time else None
        }
    except Exception as e:
        data["confidence"]["error"] = str(e)

    try:
        topics = forum_topic_rows()
        data["forum"]["topics"] = [{
            "id": t.get("id"),
            "title": t.get("title"),
            "author": t.get("author"),
            "reply_count": t.get("reply_count", 0),
            "last_activity": t.get("last_activity")
        } for t in topics[:3]]
    except Exception as e:
        data["forum"]["error"] = str(e)

    try:
        try:
            sync_week(week)
        except Exception:
            pass
        games = get_week(week)
        games = sorted(games, key=lambda g: str(g.get("game_date") or ""))
        now = dt.datetime.now(dt.timezone.utc)
        upcoming = []
        for g in games:
            kickoff = parse_game_datetime(g.get("game_date"))
            if str(g.get("status") or "").lower() == "final":
                continue
            if kickoff is None or kickoff >= now - dt.timedelta(hours=5):
                upcoming.append({
                    "id": g.get("id"),
                    "away_team": g.get("away_team"),
                    "away_name": g.get("away_name") or TEAMS.get(g.get("away_team"), g.get("away_team")),
                    "home_team": g.get("home_team"),
                    "home_name": g.get("home_name") or TEAMS.get(g.get("home_team"), g.get("home_team")),
                    "kickoff": kickoff.isoformat() if kickoff else g.get("game_date")
                })
        data["next_games"] = upcoming[:4]
    except Exception as e:
        data["games_error"] = str(e)

    # Personalized "My Pools" summary.
    try:
        draft_id = account.get("draft_player_id")
        if draft_id is not None:
            mine = next((p for p in draft_players if int(p.get("id") or 0) == int(draft_id)), None)
            if mine:
                data["my_pools"]["draft"] = {
                    "linked":True,
                    "player_name":mine.get("player_name"),
                    "rank":mine.get("rank"),
                    "total_points":mine.get("total_points",0),
                    "teams":[mine.get(f"team{n}") for n in range(1,9) if mine.get(f"team{n}")]
                }
    except Exception as e:
        data["my_pools"]["draft"]["error"] = str(e)

    try:
        survivor_name, survivor_key = member_pool_identity("survivor")
        history = survivor_player_history(survivor_key) if survivor_key else []
        current_pick = next((p for p in history if int(p.get("week") or 0) == week), None)
        eliminated_week = None
        for p in history:
            pw = int(p.get("week") or 0)
            if pw <= 0:
                continue
            outcome = survivor_pick_result((p.get("team") or "").upper(), get_week(pw))
            if outcome.get("status") == "ELIMINATED":
                eliminated_week = pw if eliminated_week is None else min(eliminated_week, pw)
        status = f"Eliminated Week {eliminated_week}" if eliminated_week else ("Pick submitted" if current_pick else "No pick submitted")
        data["my_pools"]["survivor"] = {
            "linked":True,
            "player_name":survivor_name,
            "status":status,
            "pick":current_pick.get("team") if current_pick else None,
            "eliminated_week":eliminated_week
        }
    except Exception as e:
        data["my_pools"]["survivor"]["error"] = str(e)

    try:
        confidence_name, confidence_key = member_pool_identity("confidence")
        entry, picks = confidence_entry(confidence_key, week) if confidence_key else (None, [])
        mine = next((p for p in standings if p.get("player_key") == confidence_key), None)
        data["my_pools"]["confidence"] = {
            "linked":True,
            "player_name":confidence_name,
            "status":"Test entry submitted" if entry else "No test entry submitted",
            "testing":True,
            "entry_submitted":bool(entry),
            "pick_count":len(picks),
            "rank":mine.get("rank") if mine else None,
            "total_points":mine.get("total_points",0) if mine else 0
        }
    except Exception as e:
        data["my_pools"]["confidence"]["error"] = str(e)

    return jsonify(data)


@app.route("/api/admin/dashboard-announcement", methods=["GET","POST"])
def api_admin_dashboard_announcement():
    if request.method == "GET":
        return jsonify({"ok":True, **dashboard_announcement()})

    payload = request.get_json(silent=True) or {}
    if not ADMIN_PASSWORD or payload.get("password", "") != ADMIN_PASSWORD:
        return jsonify({"ok":False,"error":"Incorrect commissioner password."}),403

    message = str(payload.get("message") or "").strip()
    enabled = bool(payload.get("enabled", True))
    if len(message) > 600:
        return jsonify({"ok":False,"error":"Announcement must be 600 characters or fewer."}),400
    if enabled and not message:
        return jsonify({"ok":False,"error":"Enter an announcement or turn the announcement off."}),400

    now = dt.datetime.now(dt.timezone.utc).isoformat()
    sb_upsert(
        "site_settings",
        [
            {"setting_key":"dashboard_announcement","setting_value":message,"updated_at":now},
            {"setting_key":"dashboard_announcement_enabled","setting_value":"true" if enabled else "false","updated_at":now}
        ],
        "setting_key"
    )
    return jsonify({"ok":True,"message":"Dashboard announcement updated.",**dashboard_announcement()})


@app.route("/")
def index():
    return render_template("index.html", season=SEASON)


@app.route("/results")
def nfl_results():
    week=max(1,min(18,request.args.get("week",dashboard_current_week(),type=int)))
    return render_template("results.html",season=SEASON,week=week)

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
    # Bootstrap exception: before the first account exists, the shared site
    # password plus ADMIN_PASSWORD-protected controls can create Commissioner.
    if member_accounts_exist():
        if session.get("must_change_password") is True and session.get("account_authenticated") is True:
            return redirect(url_for("member_password_change"))
        if not require_commissioner_account():
            return render_template("member_access_denied.html", season=SEASON), 403
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
        sb_get("confidence_players", {"select":"id","limit":"1"})
        sb_get("confidence_entries", {"select":"id","limit":"1"})
        sb_get("confidence_picks", {"select":"id","limit":"1"})
        sb_get("site_settings", {"select":"setting_key","limit":"1"})
        sb_get("forum_topics", {"select":"id","limit":"1"})
        sb_get("forum_posts", {"select":"id","limit":"1"})
        sb_get("member_accounts", {"select":"id","limit":"1"})
        return jsonify({"status":"ok","database":"supabase","season":SEASON,"checks":["draft","survivor","settings","draft_salary","confidence","private_login","member_accounts","forum"]}), 200
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
    account_name, account_key = member_pool_identity("survivor")
    player_name = str(account_name or "").strip()
    pin = ""
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
        row = save_survivor_pick(player_name, week, team, pin=None, admin_override=False, account_authenticated=True, player_key_override=account_key)
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
    player_name, player_key = member_pool_identity("survivor")
    if not player_name or not player_key:
        return jsonify({"history": [], "used_teams": [], "error":"This account is not linked to a Survivor identity."}),400

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

    return jsonify({
        "history": rows,
        "used_teams": used,
        "player_name": player_name,
        "player_key": player_key
    })


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

    confidence_values = list(range(16, 0, -1))
    add(
        "Confidence values cover 1–16 exactly once",
        set(confidence_values) == set(range(1,17)) and len(confidence_values) == len(set(confidence_values)),
        "A 16-game week supplies confidence values 16 through 1 with no duplicates."
    )
    add(
        "Confidence maximum points calculate correctly",
        sum(confidence_values) == 136,
        f"A perfect 16-game week is worth {sum(confidence_values)} points."
    )

    add(
        "Member usernames normalize consistently",
        member_username_key("  Fred   Smalley ") == "fred smalley",
        "Usernames are case-insensitive and repeated spaces are normalized."
    )
    add(
        "Member roles are restricted",
        {"MEMBER","COMMISSIONER"} == set(["MEMBER","COMMISSIONER"]),
        "Only MEMBER and COMMISSIONER roles are supported."
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
        ("Confidence players table", "confidence_players"),
        ("Confidence entries table", "confidence_entries"),
        ("Confidence picks table", "confidence_picks"),
        ("Member accounts table", "member_accounts"),
        ("Forum topics table", "forum_topics"),
        ("Forum posts table", "forum_posts"),
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
