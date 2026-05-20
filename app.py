"""
NBA Player Stats - žurnalistický generátor
Lokální Flask appka. Zadáš jméno hráče → vyplivne dva odstavce textu.
"""

from flask import Flask, render_template, jsonify, request
from nba_api.stats.static import players
from nba_api.stats.endpoints import playercareerstats, commonplayerinfo, leagueleaders
import time
import os

app = Flask(__name__)

# Delší timeout pro hostingové prostředí (NBA API občas odpovídá pomalu)
NBA_API_TIMEOUT = 30

# ---------- Pomocné funkce ----------

def find_player(name_query):
    """Najde hráče podle jména. Vrátí nejlepší match nebo None."""
    matches = players.find_players_by_full_name(name_query)
    if not matches:
        # Zkusit fuzzy - jen příjmení nebo část jména
        all_players = players.get_players()
        name_lower = name_query.lower()
        matches = [p for p in all_players if name_lower in p['full_name'].lower()]
    
    if not matches:
        return None
    
    # Preferovat aktivní hráče
    active = [m for m in matches if m.get('is_active')]
    return active[0] if active else matches[0]


def safe_call(fn, retries=3, delay=0.6):
    """nba_api občas vrátí timeout. Retry s krátkou pauzou."""
    last_err = None
    for i in range(retries):
        try:
            return fn()
        except Exception as e:
            last_err = e
            time.sleep(delay * (i + 1))
    raise last_err


def fmt_num(val, decimals=1):
    """Naformátuje číslo. Když je None nebo prázdné, vrátí pomlčku."""
    if val is None or val == "":
        return "–"
    try:
        return f"{float(val):.{decimals}f}"
    except (ValueError, TypeError):
        return "–"


def fmt_pct(val):
    """Procento z desetinného čísla (0.456 → 45.6 %)."""
    if val is None or val == "":
        return "–"
    try:
        return f"{float(val)*100:.1f} %"
    except (ValueError, TypeError):
        return "–"


def calc_ts_pct(pts, fga, fta):
    """True Shooting % = PTS / (2 * (FGA + 0.44 * FTA))."""
    try:
        denom = 2 * (float(fga) + 0.44 * float(fta))
        if denom == 0:
            return None
        return float(pts) / denom
    except (ValueError, TypeError, ZeroDivisionError):
        return None


def row_to_dict(headers, row):
    """nba_api vrací data v [headers] + [rows] formátu. Převedeme na dict."""
    return dict(zip(headers, row))


def get_position_word(pos):
    """Pozice → české slovo pro plynulý text."""
    if not pos:
        return "hráč"
    pos = pos.upper()
    mapping = {
        "G": "rozehrávač",
        "F": "křídlo",
        "C": "pivot",
        "G-F": "rozehrávač/křídlo",
        "F-G": "křídlo/rozehrávač",
        "F-C": "křídlo/pivot",
        "C-F": "pivot/křídlo",
    }
    return mapping.get(pos, "hráč")


# ---------- Generátor textu ----------

def generate_player_text(player_id, player_name):
    """Hlavní funkce - stáhne data a vygeneruje dva odstavce."""
    
    # 1. Základní info o hráči
    info_data = safe_call(lambda: commonplayerinfo.CommonPlayerInfo(player_id=player_id, timeout=NBA_API_TIMEOUT))
    info_dict = info_data.get_normalized_dict()
    common_info = info_dict.get("CommonPlayerInfo", [{}])[0]
    
    team = common_info.get("TEAM_NAME", "")
    team_city = common_info.get("TEAM_CITY", "")
    full_team = f"{team_city} {team}".strip() if team_city else team
    position = common_info.get("POSITION", "")
    height = common_info.get("HEIGHT", "")
    weight = common_info.get("WEIGHT", "")
    jersey = common_info.get("JERSEY", "")
    draft_year = common_info.get("DRAFT_YEAR", "")
    draft_round = common_info.get("DRAFT_ROUND", "")
    draft_pick = common_info.get("DRAFT_NUMBER", "")
    from_year = common_info.get("FROM_YEAR", "")
    to_year = common_info.get("TO_YEAR", "")
    is_active = (to_year == common_info.get("TO_YEAR") and 
                 (common_info.get("ROSTERSTATUS", "") == "Active"))
    
    # 2. Career stats - obsahuje sezony i kariérní totals
    career_data = safe_call(lambda: playercareerstats.PlayerCareerStats(player_id=player_id, timeout=NBA_API_TIMEOUT))
    career_dict = career_data.get_normalized_dict()
    
    # Per game season totals - aktuální sezona
    season_rows = career_dict.get("SeasonTotalsRegularSeason", [])
    career_totals = career_dict.get("CareerTotalsRegularSeason", [{}])
    career = career_totals[0] if career_totals else {}
    
    # Najdeme aktuální/poslední sezónu
    current_season = season_rows[-1] if season_rows else None
    
    # 3. Sestavení sezónního odstavce
    season_paragraph = build_season_paragraph(
        player_name, current_season, full_team, position, is_active
    )
    
    # 4. Sestavení kariérního odstavce
    career_paragraph = build_career_paragraph(
        player_name, career, season_rows, 
        draft_year, draft_round, draft_pick,
        height, weight, jersey, from_year, to_year, is_active
    )
    
    return {
        "player": player_name,
        "team": full_team,
        "position": position,
        "is_active": is_active,
        "season_paragraph": season_paragraph,
        "career_paragraph": career_paragraph,
    }


def build_season_paragraph(name, season, team, position, is_active):
    """Žurnalistický odstavec o aktuální sezóně."""
    if not season:
        return f"{name} v této sezóně zatím neodehrál žádný zápas v základní části NBA."
    
    season_id = season.get("SEASON_ID", "")
    gp = season.get("GP", 0)
    gs = season.get("GS", 0)
    mpg = season.get("MIN", 0)
    pts = season.get("PTS", 0)
    reb = season.get("REB", 0)
    ast = season.get("AST", 0)
    stl = season.get("STL", 0)
    blk = season.get("BLK", 0)
    fg_pct = season.get("FG_PCT", 0)
    fg3_pct = season.get("FG3_PCT", 0)
    ft_pct = season.get("FT_PCT", 0)
    fga = season.get("FGA", 0)
    fta = season.get("FTA", 0)
    tov = season.get("TOV", 0)
    
    # Přepočet na per-game (totals → průměry)
    try:
        gp_int = int(gp) if gp else 1
        if gp_int == 0:
            gp_int = 1
        ppg = float(pts) / gp_int
        rpg = float(reb) / gp_int
        apg = float(ast) / gp_int
        spg = float(stl) / gp_int
        bpg = float(blk) / gp_int
        mpg_avg = float(mpg) / gp_int
        topg = float(tov) / gp_int
    except (ValueError, TypeError, ZeroDivisionError):
        ppg = rpg = apg = spg = bpg = mpg_avg = topg = 0
    
    ts_pct = calc_ts_pct(pts, fga, fta)
    
    pos_word = get_position_word(position)
    tense = "" if is_active else "v sezóně " + season_id
    
    team_phrase = f"v dresu {team}" if team else ""
    
    para = (
        f"{name} v aktuální sezóně {season_id} {team_phrase} odehrál {gp} zápasů "
        f"(z toho {gs} v základní sestavě) s průměrem {mpg_avg:.1f} minuty na utkání. "
        f"Jako {pos_word} zaznamenává {ppg:.1f} bodu, {rpg:.1f} doskoku a {apg:.1f} asistence na zápas, "
        f"k tomu přidává {spg:.1f} zisku a {bpg:.1f} bloku. "
        f"Ze hry střílí {fmt_pct(fg_pct)}, za tři {fmt_pct(fg3_pct)} a z trestného hodu {fmt_pct(ft_pct)}. "
    )
    
    if ts_pct is not None:
        para += f"Jeho True Shooting Percentage dosahuje {ts_pct*100:.1f} %"
        # Kontext k TS%
        if ts_pct >= 0.60:
            para += " – což je elitní hodnota svědčící o vysoké efektivitě útoku. "
        elif ts_pct >= 0.55:
            para += ", tedy nadprůměrná efektivita v rámci ligy. "
        elif ts_pct >= 0.50:
            para += ", což odpovídá ligovému průměru. "
        else:
            para += ", což je pod ligovým průměrem a naznačuje problémy se zakončováním. "
    
    para += f"Na zápas ztrácí míč {topg:.1f}krát."
    
    return para


def build_career_paragraph(name, career, all_seasons, draft_year, draft_round, draft_pick,
                            height, weight, jersey, from_year, to_year, is_active):
    """Žurnalistický odstavec o kariéře."""
    
    gp = career.get("GP", 0)
    pts = career.get("PTS", 0)
    reb = career.get("REB", 0)
    ast = career.get("AST", 0)
    stl = career.get("STL", 0)
    blk = career.get("BLK", 0)
    fg_pct = career.get("FG_PCT", 0)
    fg3_pct = career.get("FG3_PCT", 0)
    ft_pct = career.get("FT_PCT", 0)
    fga = career.get("FGA", 0)
    fta = career.get("FTA", 0)
    
    try:
        gp_int = int(gp) if gp else 1
        if gp_int == 0:
            gp_int = 1
        ppg = float(pts) / gp_int
        rpg = float(reb) / gp_int
        apg = float(ast) / gp_int
        spg = float(stl) / gp_int
        bpg = float(blk) / gp_int
    except (ValueError, TypeError, ZeroDivisionError):
        ppg = rpg = apg = spg = bpg = 0
    
    ts_career = calc_ts_pct(pts, fga, fta)
    
    # Kariérní highs - projdeme všechny sezóny
    best_pts_season = None
    best_reb_season = None
    best_ast_season = None
    seasons_played = len(all_seasons) if all_seasons else 0
    
    if all_seasons:
        for s in all_seasons:
            s_gp = s.get("GP", 0)
            if not s_gp or int(s_gp) == 0:
                continue
            s_gp = int(s_gp)
            s_ppg = float(s.get("PTS", 0)) / s_gp
            s_rpg = float(s.get("REB", 0)) / s_gp
            s_apg = float(s.get("AST", 0)) / s_gp
            
            if not best_pts_season or s_ppg > best_pts_season[1]:
                best_pts_season = (s.get("SEASON_ID", ""), s_ppg, s.get("TEAM_ABBREVIATION", ""))
            if not best_reb_season or s_rpg > best_reb_season[1]:
                best_reb_season = (s.get("SEASON_ID", ""), s_rpg, s.get("TEAM_ABBREVIATION", ""))
            if not best_ast_season or s_apg > best_ast_season[1]:
                best_ast_season = (s.get("SEASON_ID", ""), s_apg, s.get("TEAM_ABBREVIATION", ""))
    
    # Sestavení textu
    # Draft info
    draft_phrase = ""
    if draft_year and draft_year != "Undrafted":
        if draft_round and draft_pick:
            draft_phrase = f"Do ligy vstoupil draftem v roce {draft_year} v {draft_round}. kole jako {draft_pick}. celkově. "
        else:
            draft_phrase = f"Do ligy vstoupil draftem v roce {draft_year}. "
    elif draft_year == "Undrafted":
        draft_phrase = "V draftu nebyl vybrán a do ligy se prosadil cestou nedraftovaného hráče. "
    
    # Délka kariéry
    career_span = ""
    if from_year and to_year:
        if is_active:
            career_span = f"V NBA působí od sezóny {from_year}, dohromady už {seasons_played} sezón. "
        else:
            career_span = f"V NBA působil v letech {from_year}–{to_year}, celkem {seasons_played} sezón. "
    
    para = draft_phrase + career_span
    
    para += (
        f"V základní části kariéry odehrál {gp} zápasů s průměry {ppg:.1f} bodu, "
        f"{rpg:.1f} doskoku a {apg:.1f} asistence, k tomu {spg:.1f} zisku a {bpg:.1f} bloku na utkání. "
        f"Z dlouhodobého hlediska střílí {fmt_pct(fg_pct)} ze hry, {fmt_pct(fg3_pct)} za tříbodovou čárou "
        f"a {fmt_pct(ft_pct)} z trestných hodů"
    )
    
    if ts_career is not None:
        para += f", jeho kariérní TS% dosahuje {ts_career*100:.1f} %. "
    else:
        para += ". "
    
    # Sezónní highs
    if best_pts_season:
        para += (
            f"Bodově nejvydařenější sezónu prožil v ročníku {best_pts_season[0]} "
            f"({best_pts_season[2]}) s průměrem {best_pts_season[1]:.1f} bodu na zápas"
        )
        if best_ast_season and best_ast_season[0] != best_pts_season[0]:
            para += (
                f", asistenčně pak v sezóně {best_ast_season[0]} "
                f"s {best_ast_season[1]:.1f} přihrávky na utkání"
            )
        if best_reb_season:
            para += f", doskočil nejvíce v ročníku {best_reb_season[0]} ({best_reb_season[1]:.1f} rb/g)"
        para += "."
    
    return para


# ---------- Routes ----------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/player")
def api_player():
    name = request.args.get("name", "").strip()
    if not name:
        return jsonify({"error": "Zadej jméno hráče."}), 400
    
    player = find_player(name)
    if not player:
        return jsonify({"error": f"Hráč '{name}' nenalezen. Zkus zadat jméno v angličtině (např. 'Nikola Jokic' místo 'Jokič')."}), 404
    
    try:
        result = generate_player_text(player["id"], player["full_name"])
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": f"Chyba při načítání dat z NBA API: {str(e)}. Zkus to za chvíli znovu."}), 500


if __name__ == "__main__":
    print("\n" + "="*60)
    print("  NBA Player Stats - žurnalistický generátor")
    print("="*60)
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  Otevři v prohlížeči: http://127.0.0.1:{port}")
    print("\n  Zastavit: Ctrl+C\n")
    app.run(host="0.0.0.0", port=port, debug=False)
