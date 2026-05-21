"""
NBA Player Stats - žurnalistický generátor (verze 2)
Používá balldontlie.io API místo nba_api (kvůli blokaci Render IP).
API klíč se načítá z prostředí přes proměnnou BALLDONTLIE_API_KEY.
"""

from flask import Flask, render_template, jsonify, request
import requests
import os

app = Flask(__name__)

API_KEY = os.environ.get("BALLDONTLIE_API_KEY", "")
BASE_URL = "https://api.balldontlie.io/nba/v1"
HEADERS = {"Authorization": API_KEY}
TIMEOUT = 15


# ---------- Pomocné funkce ----------

def fmt_pct(val):
    """Procento z desetinného čísla."""
    if val is None or val == "":
        return "–"
    try:
        return f"{float(val) * 100:.1f} %"
    except (ValueError, TypeError):
        return "–"


def fmt_num(val, decimals=1):
    if val is None or val == "":
        return "–"
    try:
        return f"{float(val):.{decimals}f}"
    except (ValueError, TypeError):
        return "–"


def calc_ts_pct(pts, fga, fta):
    """True Shooting % = PTS / (2 * (FGA + 0.44 * FTA))."""
    try:
        pts, fga, fta = float(pts), float(fga), float(fta)
        denom = 2 * (fga + 0.44 * fta)
        if denom == 0:
            return None
        return pts / denom
    except (ValueError, TypeError, ZeroDivisionError):
        return None


def get_position_word(pos):
    """Pozice → české slovo."""
    if not pos:
        return "hráč"
    pos = pos.upper().strip()
    mapping = {
        "G": "rozehrávač", "PG": "rozehrávač", "SG": "rozehrávač",
        "F": "křídlo", "SF": "křídlo", "PF": "křídlo",
        "C": "pivot",
        "G-F": "rozehrávač/křídlo", "F-G": "křídlo/rozehrávač",
        "F-C": "křídlo/pivot", "C-F": "pivot/křídlo",
    }
    return mapping.get(pos, "hráč")


# ---------- API volání ----------

def find_player(name_query):
    """Najde hráče podle jména přes balldontlie API."""
    try:
        r = requests.get(
            f"{BASE_URL}/players",
            params={"search": name_query, "per_page": 25},
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return None, f"API odpovědělo chybou {r.status_code}: {r.text[:200]}"
        data = r.json().get("data", [])
        if not data:
            return None, None  # nenalezeno, ale ne chyba
        # Vrátíme nejlepší match - exact match má prioritu
        name_lower = name_query.lower()
        for p in data:
            full = f"{p.get('first_name', '')} {p.get('last_name', '')}".strip().lower()
            if full == name_lower:
                return p, None
        return data[0], None
    except requests.exceptions.RequestException as e:
        return None, f"Síťová chyba: {str(e)}"


def get_season_averages(player_id, season):
    """Sezónní průměry pro daný rok (např. 2024 = sezóna 2024-2025)."""
    try:
        r = requests.get(
            f"{BASE_URL}/season_averages",
            params={"season": season, "player_ids[]": player_id},
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return None
        data = r.json().get("data", [])
        return data[0] if data else None
    except requests.exceptions.RequestException:
        return None


def get_current_season():
    """Aktuální NBA sezóna - rok začátku sezóny.
    NBA sezóna začíná v říjnu. Pokud jsme po srpnu, aktuální je tento rok,
    jinak rok předchozí (běžící sezóna)."""
    from datetime import datetime
    now = datetime.now()
    if now.month >= 9:
        return now.year
    return now.year - 1


# ---------- Generátor textu ----------

def generate_player_text(player):
    """Hlavní funkce - vezme info o hráči, stáhne aktuální sezónu a vrátí dva odstavce."""
    
    first = player.get("first_name", "")
    last = player.get("last_name", "")
    name = f"{first} {last}".strip()
    position = player.get("position", "")
    height = player.get("height", "")
    weight = player.get("weight", "")
    college = player.get("college", "")
    country = player.get("country", "")
    draft_year = player.get("draft_year")
    draft_round = player.get("draft_round")
    draft_pick = player.get("draft_number")
    jersey = player.get("jersey_number", "")
    team = player.get("team", {})
    team_name = team.get("full_name", "") if team else ""
    
    # Aktuální sezóna
    current_season = get_current_season()
    current = get_season_averages(player.get("id"), current_season)
    
    # Pokud nehrál aktuální, zkusíme předchozí
    actually_current = True
    if not current or current.get("games_played", 0) == 0:
        actually_current = False
        prev_season = current_season - 1
        current = get_season_averages(player.get("id"), prev_season)
        if current:
            current_season = prev_season
    
    season_paragraph = build_season_paragraph(name, current, team_name, position, current_season, actually_current)
    career_paragraph = build_career_paragraph(
        name, position, height, weight, college, country,
        draft_year, draft_round, draft_pick, jersey
    )
    
    return {
        "player": name,
        "team": team_name,
        "position": position,
        "is_active": actually_current,
        "season_paragraph": season_paragraph,
        "career_paragraph": career_paragraph,
    }


def build_season_paragraph(name, stats, team, position, season_year, is_current):
    """Žurnalistický odstavec o aktuální/poslední sezóně."""
    if not stats:
        return (
            f"{name} v posledních sezónách nemá v databázi žádné záznamy "
            f"o odehraných zápasech v NBA. Pravděpodobně se jedná o hráče "
            f"mimo aktivní soupisku, na minor league smlouvě nebo působí v jiné lize."
        )
    
    season_label = f"{season_year}/{str(season_year+1)[-2:]}"
    season_intro = "aktuální" if is_current else "poslední odehrané"
    
    gp = stats.get("games_played", 0)
    mpg = stats.get("min", "0")
    ppg = stats.get("pts", 0)
    rpg = stats.get("reb", 0)
    apg = stats.get("ast", 0)
    spg = stats.get("stl", 0)
    bpg = stats.get("blk", 0)
    fg_pct = stats.get("fg_pct", 0)
    fg3_pct = stats.get("fg3_pct", 0)
    ft_pct = stats.get("ft_pct", 0)
    fga = stats.get("fga", 0)
    fta = stats.get("fta", 0)
    pts_total_estimate = float(ppg) * gp if gp else 0
    fga_total = float(fga) * gp if gp else 0
    fta_total = float(fta) * gp if gp else 0
    turnover = stats.get("turnover", 0)
    
    ts_pct = calc_ts_pct(pts_total_estimate, fga_total, fta_total) if gp else None
    
    pos_word = get_position_word(position)
    team_phrase = f"v dresu {team}" if team else ""
    
    para = (
        f"{name} v {season_intro} sezóně {season_label} {team_phrase} "
        f"odehrál {gp} zápasů s průměrem {mpg} minuty na utkání. "
        f"Jako {pos_word} zaznamenává {fmt_num(ppg)} bodu, {fmt_num(rpg)} doskoku "
        f"a {fmt_num(apg)} asistence na zápas, k tomu přidává {fmt_num(spg)} zisku "
        f"a {fmt_num(bpg)} bloku. "
        f"Ze hry střílí {fmt_pct(fg_pct)}, za tři {fmt_pct(fg3_pct)} "
        f"a z trestného hodu {fmt_pct(ft_pct)}. "
    )
    
    if ts_pct is not None:
        para += f"Jeho True Shooting Percentage v této sezóně dosahuje {ts_pct*100:.1f} %"
        if ts_pct >= 0.60:
            para += " — což je elitní hodnota svědčící o vysoké útočné efektivitě. "
        elif ts_pct >= 0.55:
            para += ", tedy nadprůměrná efektivita v rámci ligy. "
        elif ts_pct >= 0.50:
            para += ", což odpovídá ligovému průměru. "
        else:
            para += ", což je pod ligovým průměrem. "
    
    if turnover:
        para += f"Na zápas ztrácí míč {fmt_num(turnover)}krát."
    
    return para


def build_career_paragraph(name, position, height, weight, college, country,
                            draft_year, draft_round, draft_pick, jersey):
    """Odstavec o profilu a kariéře hráče (draft, fyzické parametry)."""
    
    parts = []
    
    # Draft
    if draft_year:
        if draft_round and draft_pick:
            parts.append(
                f"{name} vstoupil do NBA draftem v roce {draft_year} v {draft_round}. kole "
                f"jako {draft_pick}. celkově"
            )
        else:
            parts.append(f"{name} vstoupil do NBA v roce {draft_year}")
        if college:
            parts.append(f"po angažmá na univerzitě {college}")
    else:
        if college:
            parts.append(f"{name} prošel univerzitou {college} a do ligy se prosadil bez draftování")
        else:
            parts.append(f"{name} se do NBA dostal mimo draft")
    
    # Spojení
    intro = ", ".join(parts) + "."
    
    # Fyzické parametry
    physical = []
    if height:
        physical.append(f"měří {height}")
    if weight:
        try:
            kg = round(float(weight) * 0.453592)
            physical.append(f"váží {kg} kg ({weight} liber)")
        except (ValueError, TypeError):
            physical.append(f"váží {weight} liber")
    if country and country.upper() not in ["USA", "UNITED STATES"]:
        physical.append(f"pochází z {country}")
    if jersey:
        physical.append(f"nosí číslo {jersey}")
    
    physical_sentence = ""
    if physical:
        if position:
            pos_word = get_position_word(position)
            physical_sentence = f" Jako {pos_word} " + ", ".join(physical) + "."
        else:
            physical_sentence = " " + ", ".join(physical).capitalize() + "."
    
    note = (
        " Pro detailní kariérní statistiky napříč sezónami "
        "(kariérní průměry, sezónní highs, totals) je doporučeno nahlédnout "
        "na specializované databáze jako Basketball-Reference nebo oficiální stránky NBA."
    )
    
    return intro + physical_sentence + note


# ---------- Routes ----------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/player")
def api_player():
    name = request.args.get("name", "").strip()
    if not name:
        return jsonify({"error": "Zadej jméno hráče."}), 400
    
    if not API_KEY:
        return jsonify({
            "error": "API klíč není nastaven. Administrátor musí v Renderu nastavit BALLDONTLIE_API_KEY."
        }), 500
    
    player, err = find_player(name)
    if err:
        return jsonify({"error": err}), 500
    if not player:
        return jsonify({
            "error": f"Hráč '{name}' nebyl nalezen. Zkus zadat jméno v angličtině (např. 'Nikola Jokic' místo 'Jokič')."
        }), 404
    
    try:
        result = generate_player_text(player)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": f"Chyba při zpracování dat: {str(e)}"}), 500


if __name__ == "__main__":
    print("\n" + "="*60)
    print("  NBA Player Stats - žurnalistický generátor (balldontlie)")
    print("="*60)
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  Otevři v prohlížeči: http://127.0.0.1:{port}")
    print(f"  API klíč nastaven: {'ANO' if API_KEY else 'NE (chybí BALLDONTLIE_API_KEY)'}")
    print("\n  Zastavit: Ctrl+C\n")
    app.run(host="0.0.0.0", port=port, debug=False)
