"""
NBA Player Stats - žurnalistický generátor (verze 3, ESPN API)
Používá veřejné ESPN API (bez klíče) místo balldontlie kvůli omezením free tieru.
"""

from flask import Flask, render_template, jsonify, request
import requests
import os

app = Flask(__name__)

TIMEOUT = 20

# ESPN endpoints
SEARCH_URL = "https://site.web.api.espn.com/apis/search/v2"
OVERVIEW_URL = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{id}/overview"
STATS_URL = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{id}/stats"
GAMELOG_URL = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{id}/gamelog"
ATHLETE_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/athletes/{id}"
BIO_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/athletes/{id}/bio"

# Vypadá to slušně, když posíláme browser-like User-Agent
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/json",
}


# ---------- Pomocné funkce ----------

def fmt_num(val, decimals=1):
    if val is None or val == "":
        return "–"
    try:
        return f"{float(val):.{decimals}f}"
    except (ValueError, TypeError):
        return str(val)


def fmt_pct(val):
    """ESPN vrací procenta už jako čísla 0-100 nebo jako desetinná - heuristika."""
    if val is None or val == "":
        return "–"
    try:
        v = float(val)
        if v <= 1.0:
            v = v * 100
        return f"{v:.1f} %"
    except (ValueError, TypeError):
        return str(val)


def get_position_word(pos):
    if not pos:
        return "hráč"
    pos = pos.upper().strip()
    mapping = {
        "G": "rozehrávač", "PG": "rozehrávač", "SG": "rozehrávač",
        "POINT GUARD": "rozehrávač", "SHOOTING GUARD": "rozehrávač",
        "F": "křídlo", "SF": "křídlo", "PF": "křídlo",
        "SMALL FORWARD": "křídlo", "POWER FORWARD": "křídlo",
        "C": "pivot", "CENTER": "pivot",
        "G-F": "rozehrávač/křídlo", "F-G": "křídlo/rozehrávač",
        "F-C": "křídlo/pivot", "C-F": "pivot/křídlo",
    }
    return mapping.get(pos, pos.lower() if pos else "hráč")


def safe_get(d, *keys, default=None):
    """Bezpečný přístup do hluboko zanořeného slovníku/listu."""
    cur = d
    for k in keys:
        if cur is None:
            return default
        if isinstance(k, int):
            if isinstance(cur, list) and 0 <= k < len(cur):
                cur = cur[k]
            else:
                return default
        else:
            if isinstance(cur, dict):
                cur = cur.get(k)
            else:
                return default
    return cur if cur is not None else default


# ---------- ESPN API volání ----------

def search_player(name_query):
    """Vyhledá hráče přes ESPN search. Vrátí (player_id, display_name) nebo (None, error)."""
    try:
        r = requests.get(
            SEARCH_URL,
            params={"query": name_query, "sport": "basketball", "limit": 10},
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return None, None, f"ESPN search vrátil chybu {r.status_code}"
        
        data = r.json()
        # Search vrací results pole, hledáme typ "player"
        results = data.get("results", [])
        
        # Procházíme všechny kategorie výsledků
        player_candidates = []
        for category in results:
            items = category.get("contents", []) or category.get("results", [])
            for item in items:
                # ESPN označuje hráče různě - typ "player" nebo má sport "basketball"
                item_type = (item.get("type") or "").lower()
                sport = (item.get("sport") or "").lower()
                if item_type == "player" or "player" in item_type or sport == "basketball":
                    pid = item.get("id") or item.get("uid", "").split(":")[-1]
                    display = item.get("displayName") or item.get("display_name") or item.get("name", "")
                    league = (item.get("league") or "").lower()
                    # Preferujeme NBA
                    if pid and display:
                        priority = 0 if "nba" in league or "nba" in str(item.get("defaultLeague", "")).lower() else 1
                        player_candidates.append((priority, pid, display))
        
        if not player_candidates:
            return None, None, None
        
        # Seřadíme podle priority (NBA má 0)
        player_candidates.sort(key=lambda x: x[0])
        _, pid, display = player_candidates[0]
        return str(pid), display, None
    
    except requests.exceptions.RequestException as e:
        return None, None, f"Síťová chyba při hledání: {str(e)}"
    except (ValueError, KeyError) as e:
        return None, None, f"Chyba parsování search: {str(e)}"


def fetch_overview(player_id):
    """Stáhne overview - profil + aktuální sezónní stats + tým."""
    try:
        r = requests.get(
            OVERVIEW_URL.format(id=player_id),
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        if r.status_code == 200:
            return r.json()
    except requests.exceptions.RequestException:
        pass
    return None


def fetch_stats(player_id):
    """Stáhne detailní statistiky - kariérní + sezónní rozpis."""
    try:
        r = requests.get(
            STATS_URL.format(id=player_id),
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        if r.status_code == 200:
            return r.json()
    except requests.exceptions.RequestException:
        pass
    return None


def fetch_gamelog(player_id):
    """Stáhne gamelog - poslední zápasy."""
    try:
        r = requests.get(
            GAMELOG_URL.format(id=player_id),
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        if r.status_code == 200:
            return r.json()
    except requests.exceptions.RequestException:
        pass
    return None


def fetch_athlete_base(player_id):
    """Stáhne základní info o hráči - tým, číslo dresu, výška, váha, draft."""
    try:
        r = requests.get(
            ATHLETE_URL.format(id=player_id),
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        if r.status_code == 200:
            return r.json()
    except requests.exceptions.RequestException:
        pass
    return None


# ---------- Extrakce dat ----------

def extract_stats_dict(stats_array, labels_array):
    """ESPN vrací stats jako paralelní pole hodnot a labelů. Spojíme do dict."""
    if not stats_array or not labels_array:
        return {}
    result = {}
    for i, label in enumerate(labels_array):
        if i < len(stats_array):
            result[label] = stats_array[i]
    return result


def get_season_averages_from_overview(overview):
    """Z overview vytáhneme aktuální sezónní průměry."""
    if not overview:
        return None
    
    # Overview má strukturu se statistics
    stats = overview.get("statistics", {})
    if not stats:
        return None
    
    # ESPN má často "splits" se sezónními agregáty
    splits = stats.get("splits", []) or []
    labels = stats.get("labels", []) or stats.get("displayNames", []) or []
    names = stats.get("names", []) or []
    
    # Pokud splits má jen jeden záznam, je to obvykle season total/average
    if splits and isinstance(splits, list) and len(splits) > 0:
        first = splits[0]
        if isinstance(first, dict):
            stats_arr = first.get("stats", []) or []
            key_list = names if names else labels
            if stats_arr and key_list:
                return extract_stats_dict(stats_arr, key_list)
    
    return None


def get_season_averages_from_stats(stats_data):
    """Vytáhne aktuální (nejnovější) sezónu z stats endpointu."""
    if not stats_data:
        return None, None
    
    # stats endpoint vrací "categories" nebo přímo data
    categories = stats_data.get("categories", []) or []
    labels = stats_data.get("labels", []) or stats_data.get("names", []) or []
    
    # Snažíme se najít "stats" pole se sezónními daty
    seasons = []
    
    # Někdy je struktura: stats_data["seasons"] nebo stats_data["splits"]
    for key in ["seasons", "splits", "statistics"]:
        val = stats_data.get(key)
        if val and isinstance(val, list):
            seasons = val
            break
    
    # Pokud máme categories, projedeme je
    if not seasons and categories:
        for cat in categories:
            cat_seasons = cat.get("statistics", []) or cat.get("stats", []) or []
            if cat_seasons:
                seasons = cat_seasons
                break
            if not labels:
                labels = cat.get("labels", []) or cat.get("names", [])
    
    if not seasons:
        return None, labels
    
    # Vrátíme nejnovější sezónu (obvykle první nebo poslední)
    return seasons, labels


# ---------- Generátor textu ----------

def generate_player_text(player_id, display_name):
    """Hlavní funkce - postaví profil a vrátí dva odstavce."""
    
    overview = fetch_overview(player_id)
    athlete = fetch_athlete_base(player_id)
    
    # Profil
    name = display_name
    team = ""
    position = ""
    jersey = ""
    height = ""
    weight = ""
    age = ""
    birthplace = ""
    draft_info = ""
    experience = ""
    is_active = True
    
    # Z athlete base
    if athlete:
        ath = athlete.get("athlete") or athlete
        team_info = ath.get("team") or {}
        team = team_info.get("displayName") or team_info.get("name", "")
        
        pos = ath.get("position") or {}
        position = pos.get("abbreviation") or pos.get("displayName", "")
        
        jersey = ath.get("jersey") or ""
        
        # Height/weight - ESPN má displayHeight ("6' 8\"") a displayWeight ("250 lbs")
        height = ath.get("displayHeight") or ath.get("height", "")
        weight = ath.get("displayWeight") or ath.get("weight", "")
        
        age = ath.get("age", "")
        birth_place = ath.get("birthPlace") or {}
        if isinstance(birth_place, dict):
            city = birth_place.get("city", "")
            country = birth_place.get("country", "")
            birthplace = ", ".join(filter(None, [city, country]))
        
        draft = ath.get("draft") or {}
        if isinstance(draft, dict) and draft:
            year = draft.get("year", "")
            rnd = draft.get("round", "")
            pick = draft.get("selection") or draft.get("pick", "")
            d_team = safe_get(draft, "team", "displayName", default="")
            if year:
                parts = [f"v roce {year}"]
                if rnd and pick:
                    parts.append(f"v {rnd}. kole jako {pick}. celkově")
                if d_team:
                    parts.append(f"týmem {d_team}")
                draft_info = " ".join(parts)
        
        exp_obj = ath.get("experience") or {}
        if isinstance(exp_obj, dict):
            yrs = exp_obj.get("years", "")
            if yrs:
                experience = str(yrs)
        
        status = ath.get("status") or {}
        if isinstance(status, dict):
            status_type = (status.get("type") or "").lower()
            if status_type and status_type != "active":
                is_active = False
    
    # Z overview doplníme tým a pozici, pokud chybí
    if overview:
        if not team:
            t = overview.get("team") or {}
            team = t.get("displayName", "")
        if not position:
            position = overview.get("position", "")
    
    # Sezónní průměry
    season_stats = get_season_averages_from_overview(overview)
    
    # Sestavení odstavců
    season_paragraph = build_season_paragraph(name, season_stats, team, position, is_active)
    career_paragraph = build_career_paragraph(
        name, position, team, height, weight, jersey, age, birthplace,
        draft_info, experience, is_active
    )
    
    return {
        "player": name,
        "team": team,
        "position": position,
        "is_active": is_active,
        "season_paragraph": season_paragraph,
        "career_paragraph": career_paragraph,
    }


def build_season_paragraph(name, stats, team, position, is_active):
    """Žurnalistický odstavec o aktuální sezóně."""
    
    pos_word = get_position_word(position)
    team_phrase = f"v dresu {team}" if team else "bez aktuálního klubového zařazení"
    
    if not stats:
        if is_active:
            return (
                f"{name} aktuálně působí {team_phrase}. "
                f"Sezónní statistiky pro tohoto hráče nejsou v aktuálním "
                f"momentě dostupné v databázi ESPN — možná jde o nového hráče, "
                f"hráče na minor league smlouvě nebo o krátkodobé výpadky v datech."
            )
        else:
            return (
                f"{name} momentálně nepatří k aktivním hráčům NBA. "
                f"Aktuální sezónní statistiky proto nejsou k dispozici."
            )
    
    # Pokusíme se vytáhnout standardní statistiky - klíče se liší podle struktury
    # Zkoušíme různé varianty názvů
    def get_stat(*keys):
        for k in keys:
            for variant in [k, k.upper(), k.lower(), k.capitalize()]:
                if variant in stats and stats[variant] not in (None, ""):
                    return stats[variant]
        return None
    
    gp = get_stat("gamesPlayed", "GP", "games_played", "G")
    mpg = get_stat("avgMinutes", "MIN", "MPG", "minutes")
    ppg = get_stat("avgPoints", "PTS", "PPG", "points")
    rpg = get_stat("avgRebounds", "REB", "RPG", "rebounds")
    apg = get_stat("avgAssists", "AST", "APG", "assists")
    spg = get_stat("avgSteals", "STL", "SPG", "steals")
    bpg = get_stat("avgBlocks", "BLK", "BPG", "blocks")
    fg_pct = get_stat("fieldGoalPct", "FG%", "fgPct", "FGP")
    fg3_pct = get_stat("threePointPct", "3P%", "3PT%", "fg3Pct")
    ft_pct = get_stat("freeThrowPct", "FT%", "ftPct", "FTP")
    
    # Pokud nemáme ani body, statistiky jsou nepoužitelné
    if ppg is None and gp is None:
        return (
            f"{name} hraje za {team or 'NBA tým'} na pozici {pos_word}. "
            f"Detailní sezónní průměry pro tohoto hráče nejsou momentálně "
            f"v databázi ESPN dostupné v očekávaném formátu."
        )
    
    parts = [f"{name} v aktuální sezóně {team_phrase} odehrál {fmt_num(gp, 0)} zápasů"]
    if mpg:
        parts.append(f"s průměrem {fmt_num(mpg)} minuty na utkání")
    parts.append(".")
    
    sentence1 = " ".join(parts).replace(" .", ".")
    
    # Druhá věta - per game statistiky
    pgs = []
    if ppg is not None:
        pgs.append(f"{fmt_num(ppg)} bodu")
    if rpg is not None:
        pgs.append(f"{fmt_num(rpg)} doskoku")
    if apg is not None:
        pgs.append(f"{fmt_num(apg)} asistence")
    
    sentence2 = ""
    if pgs:
        sentence2 = f" Jako {pos_word} zaznamenává {', '.join(pgs)} na zápas"
        extras = []
        if spg is not None:
            extras.append(f"{fmt_num(spg)} zisku")
        if bpg is not None:
            extras.append(f"{fmt_num(bpg)} bloku")
        if extras:
            sentence2 += f" a k tomu přidává {' a '.join(extras)}"
        sentence2 += "."
    
    # Třetí věta - procenta
    sentence3 = ""
    pcts = []
    if fg_pct is not None:
        pcts.append(f"ze hry {fmt_pct(fg_pct)}")
    if fg3_pct is not None:
        pcts.append(f"za tři {fmt_pct(fg3_pct)}")
    if ft_pct is not None:
        pcts.append(f"z trestného hodu {fmt_pct(ft_pct)}")
    if pcts:
        joined = ", ".join(pcts)
        sentence3 = f" Střelecky vykazuje {joined}."
    
    return sentence1 + sentence2 + sentence3


def build_career_paragraph(name, position, team, height, weight, jersey, age, 
                            birthplace, draft_info, experience, is_active):
    """Profilový odstavec o kariéře a fyzických parametrech."""
    
    pos_word = get_position_word(position)
    
    # Draft + nástup do ligy
    parts = []
    if draft_info:
        parts.append(f"{name} vstoupil do NBA draftem {draft_info}")
    else:
        parts.append(f"{name} se do NBA dostal mimo draft nebo bez veřejných informací o draftu")
    
    if experience:
        parts.append(f"v lize působí už {experience}. sezónu")
    
    intro = ", ".join(parts) + "."
    
    # Fyzické parametry a profil
    physical = []
    if height:
        physical.append(f"měří {height}")
    if weight:
        # ESPN váhu může vracet jako "250 lbs" nebo číslo
        physical.append(f"váží {weight}")
    if age:
        physical.append(f"je mu {age} let")
    
    profile_sentence = ""
    if physical:
        profile_sentence = f" Jako {pos_word} " + ", ".join(physical) + "."
    
    # Birthplace
    birth_sentence = ""
    if birthplace:
        birth_sentence = f" Pochází z {birthplace}."
    
    # Jersey
    jersey_sentence = ""
    if jersey:
        if team:
            jersey_sentence = f" V {team} nosí dres s číslem {jersey}."
        else:
            jersey_sentence = f" Nosí číslo {jersey}."
    
    # Aktivní status
    status_sentence = ""
    if not is_active:
        status_sentence = f" V současnosti není veden jako aktivní hráč NBA."
    
    note = (
        " Pro úplné kariérní průměry, sezónní rozpis a historické highs "
        "doporučujeme nahlédnout na Basketball-Reference nebo oficiální stránky NBA."
    )
    
    return intro + profile_sentence + birth_sentence + jersey_sentence + status_sentence + note


# ---------- Routes ----------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/player")
def api_player():
    name = request.args.get("name", "").strip()
    if not name:
        return jsonify({"error": "Zadej jméno hráče."}), 400
    
    player_id, display_name, err = search_player(name)
    if err:
        return jsonify({"error": err}), 500
    if not player_id:
        return jsonify({
            "error": f"Hráč '{name}' nebyl nalezen v ESPN databázi. "
                     f"Zkus zadat jméno v angličtině (např. 'Nikola Jokic' místo 'Jokič')."
        }), 404
    
    try:
        result = generate_player_text(player_id, display_name)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": f"Chyba při zpracování dat: {str(e)}"}), 500


# Debug endpoint - vrátí raw data pro hráče (pro ladění)
@app.route("/api/debug/<player_id>")
def api_debug(player_id):
    """Debug endpoint - vidíme strukturu odpovědí ESPN."""
    result = {
        "overview": fetch_overview(player_id),
        "athlete": fetch_athlete_base(player_id),
    }
    return jsonify(result)


if __name__ == "__main__":
    print("\n" + "="*60)
    print("  NBA Player Stats - žurnalistický generátor (ESPN)")
    print("="*60)
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  Otevři v prohlížeči: http://127.0.0.1:{port}")
    print("\n  Zastavit: Ctrl+C\n")
    app.run(host="0.0.0.0", port=port, debug=False)
