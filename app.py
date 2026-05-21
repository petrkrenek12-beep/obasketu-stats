"""
NBA Player Stats - žurnalistický generátor (verze 5, FINAL)
Postaveno na základě ověřené struktury ESPN overview JSON.
"""

from flask import Flask, render_template, jsonify, request
import requests
import os
import re

app = Flask(__name__)

TIMEOUT = 20

SEARCH_URL = "https://site.web.api.espn.com/apis/search/v2"
OVERVIEW_URL = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{id}/overview"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/json",
}

# Mapování názvů týmů na české skloňování (volitelné - v dresu X)
# Pro zjednodušení necháme anglické názvy


def fmt_num(val, decimals=1):
    if val is None or val == "":
        return "–"
    try:
        return f"{float(val):.{decimals}f}"
    except (ValueError, TypeError):
        return str(val)


def fmt_pct(val):
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
        return ""
    p = str(pos).upper().strip()
    if "GUARD" in p or p in ("G", "PG", "SG"):
        return "rozehrávač"
    if "FORWARD" in p or p in ("F", "SF", "PF"):
        return "křídlo"
    if "CENTER" in p or p == "C":
        return "pivot"
    return ""


def safe_get(d, *keys, default=None):
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


def http_get(url, params=None):
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code == 200:
            return r.json()
    except (requests.exceptions.RequestException, ValueError):
        pass
    return None


def extract_numeric_id(player_item):
    """Z search výsledku vytáhne numerické ESPN ID z link.web URL.
    Příklad: https://www.espn.com/nba/player/_/id/3112335/nikola-jokic → 3112335"""
    # Hledáme nejprve v link.web
    web_link = safe_get(player_item, "link", "web")
    if isinstance(web_link, str):
        m = re.search(r"/id/(\d+)/", web_link)
        if m:
            return m.group(1)
    
    # Fallback: links pole
    links = player_item.get("links", []) or []
    for link in links:
        if isinstance(link, dict):
            href = link.get("href", "")
            m = re.search(r"/id/(\d+)/", href)
            if m:
                return m.group(1)
    
    # Posledni možnost: image URL obsahuje ID
    image = player_item.get("image") or {}
    if isinstance(image, dict):
        for k in ("default", "dark", "light"):
            url = image.get(k, "")
            if isinstance(url, str):
                m = re.search(r"/players/full/(\d+)\.png", url)
                if m:
                    return m.group(1)
    
    return None


def search_player(name_query):
    """Hledá hráče. Vrací (numeric_id, display_name, error)."""
    data = http_get(SEARCH_URL, params={
        "query": name_query, "sport": "basketball", "limit": 15
    })
    if not data:
        return None, None, "ESPN search nedostupný"
    
    results = data.get("results", [])
    candidates = []
    
    for category in results:
        items = category.get("contents", []) or category.get("results", []) or []
        for item in items:
            if not isinstance(item, dict):
                continue
            
            item_type = (item.get("type") or "").lower()
            sport = (item.get("sport") or "").lower()
            league = (item.get("league") or "").lower()
            default_league_slug = (safe_get(item, "defaultLeagueSlug") or "").lower()
            
            is_player = (item_type == "player")
            
            if not is_player:
                continue
            
            display = (item.get("displayName") or item.get("name") 
                       or item.get("title", ""))
            if not display:
                continue
            
            # Vytáhneme numerické ID z URL
            num_id = extract_numeric_id(item)
            if not num_id:
                continue
            
            # Priorita: NBA > basketball > ostatní
            priority = 2
            if "nba" in default_league_slug or "nba" in league:
                priority = 0
            elif sport == "basketball":
                priority = 1
            
            candidates.append((priority, num_id, display))
    
    if not candidates:
        return None, None, None
    
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1], candidates[0][2], None


# ---------- Extrakce dat z overview ----------

def extract_stats_splits(overview):
    """Vrátí dict: {'Regular Season': {labels: stats}, 'Career': {...}, 'Postseason': {...}}"""
    statistics = overview.get("statistics") or {}
    if not isinstance(statistics, dict):
        return {}
    
    labels = statistics.get("labels", []) or []
    names = statistics.get("names", []) or []
    splits = statistics.get("splits", []) or []
    
    # Použijeme 'names' (technické klíče) protože jsou stabilnější
    keys = names if names else labels
    
    result = {}
    for split in splits:
        if not isinstance(split, dict):
            continue
        display = split.get("displayName", "")
        stats = split.get("stats", []) or []
        if not display or not stats:
            continue
        stat_dict = {}
        for i, key in enumerate(keys):
            if i < len(stats):
                stat_dict[key] = stats[i]
        result[display] = stat_dict
    
    return result


def extract_team_from_overview(overview, player_id):
    """Z nextGame vytáhne tým hráče.
    nextGame má 'shortName' jako 'DEN @ MIN' nebo 'DEN vs MIN' 
    a 'links' s URL na týmy. Náš hráč hraje za jeden z nich."""
    
    next_game = overview.get("nextGame") or {}
    if not isinstance(next_game, dict):
        return None
    
    # nextGame.name může být něco jako "Denver Nuggets at Minnesota Timberwolves"
    name = next_game.get("name", "")
    short_name = next_game.get("shortName", "")
    
    # Hledáme v events pole zápasů
    events = next_game.get("events", []) or []
    if events and isinstance(events, list):
        for ev in events:
            if not isinstance(ev, dict):
                continue
            # competitions
            comps = ev.get("competitions", []) or []
            for comp in comps:
                if not isinstance(comp, dict):
                    continue
                competitors = comp.get("competitors", []) or []
                for c in competitors:
                    if not isinstance(c, dict):
                        continue
                    # athletes
                    athletes = c.get("athletes", []) or []
                    for a in athletes:
                        if isinstance(a, dict) and str(a.get("id", "")) == str(player_id):
                            team = c.get("team") or {}
                            return team.get("displayName") or team.get("name")
    
    # Fallback: z links nextGame - tým je obvykle v home_team nebo first link
    # nextGame.links často obsahuje "/nba/team/_/name/{abbr}/{slug}" URLs
    links = next_game.get("links", []) or []
    home_team_id = next_game.get("homeTeamId")
    away_team_id = next_game.get("awayTeamId")
    
    # Pokud nextGame.name má formát "Team A at Team B" → home je B
    # A pokud athleteId hraje za home (homeTeamId)... ale to nevíme bez dalšího lookupu
    
    # Tip: použijeme jméno z `name` pole rozdělené na " at "
    if name and " at " in name:
        # name: "Denver Nuggets at Minnesota Timberwolves" - nemůžu poznat kde hraje hráč
        # Ale můžeme to říct v generickém tvaru
        teams = name.split(" at ")
        if len(teams) == 2:
            # Vrátíme oba - upravíme to v generate_player_text
            return None  # raději nic než špatně
    
    return None


def extract_team_from_search(player_id):
    """Alternativní cesta - znovu zavoláme search a vytáhneme tým ze subtitle."""
    # Tohle by bylo neefektivní - vynecháme
    return None


def extract_awards_summary(overview):
    awards = overview.get("awards") or []
    if not isinstance(awards, list):
        return []
    
    summary = []
    for award in awards:
        if not isinstance(award, dict):
            continue
        count = award.get("displayCount") or "1x"
        name = award.get("name", "") or ""
        seasons = award.get("seasons", []) or []
        if not name:
            continue
        
        nl = name.lower()
        if "finals" in nl and "mvp" in nl:
            summary.append(("finals_mvp", name, count, seasons))
        elif nl == "mvp" or nl.endswith(" mvp"):
            summary.append(("mvp", name, count, seasons))
        elif "all-nba" in nl:
            summary.append(("all_nba", name, count, seasons))
        elif "all-defensive" in nl:
            summary.append(("all_defense", name, count, seasons))
        elif "all-star mvp" in nl:
            summary.append(("asg_mvp", name, count, seasons))
        elif "all-star" in nl:
            summary.append(("all_star", name, count, seasons))
        elif "rookie of the year" in nl:
            summary.append(("roy", name, count, seasons))
        elif "defensive player" in nl:
            summary.append(("dpoy", name, count, seasons))
        elif "sixth man" in nl:
            summary.append(("sixth", name, count, seasons))
        elif "scoring" in nl:
            summary.append(("leader_scoring", name, count, seasons))
        elif "assists" in nl:
            summary.append(("leader_ast", name, count, seasons))
        elif "rebounds" in nl:
            summary.append(("leader_reb", name, count, seasons))
        elif "cup mvp" in nl:
            summary.append(("cup_mvp", name, count, seasons))
    
    return summary


def parse_count(c):
    """Parse '5x' nebo '5X' nebo '5' na int."""
    if c is None:
        return 1
    s = str(c).strip().lower().replace("x", "").strip()
    try:
        return int(s) if s else 1
    except (ValueError, TypeError):
        return 1


# ---------- Generátor textu ----------

def generate_player_text(player_id, display_name):
    overview = http_get(OVERVIEW_URL.format(id=player_id))
    
    if not overview:
        return {
            "player": display_name, "team": "", "position": "",
            "is_active": True,
            "season_paragraph": f"ESPN momentálně nevrací data pro hráče {display_name}.",
            "career_paragraph": "Data nedostupná.",
        }
    
    # Tým - zkusíme různé cesty
    team = extract_team_from_overview(overview, player_id) or ""
    
    # Pozice - není v overview přímo, necháme prázdné nebo z awards/positions
    position = ""
    
    # Stats splits
    splits = extract_stats_splits(overview)
    regular_season = splits.get("Regular Season")
    career_stats = splits.get("Career")
    
    awards = extract_awards_summary(overview)
    
    # Aktivní = má Regular Season záznam s nějakými statistikami
    is_active = bool(regular_season and regular_season.get("gamesPlayed"))
    
    season_paragraph = build_season_paragraph(
        display_name, regular_season, team, position, is_active
    )
    career_paragraph = build_career_paragraph(
        display_name, career_stats, awards, team, position, is_active
    )
    
    return {
        "player": display_name, "team": team, "position": position,
        "is_active": is_active,
        "season_paragraph": season_paragraph,
        "career_paragraph": career_paragraph,
    }


def build_season_paragraph(name, stats, team, position, is_active):
    pos_word = get_position_word(position)
    team_phrase = f"v dresu {team}" if team else ""
    
    if not stats:
        if is_active:
            return (
                f"{name} aktuálně působí v NBA"
                + (f" {team_phrase}" if team_phrase else "")
                + ". Sezónní statistiky nejsou momentálně k dispozici v očekávaném formátu."
            )
        else:
            return (
                f"{name} momentálně nepatří k aktivním hráčům NBA. "
                f"Aktuální sezónní statistiky proto nejsou k dispozici."
            )
    
    # ESPN klíče
    gp = stats.get("gamesPlayed")
    mpg = stats.get("avgMinutes")
    ppg = stats.get("avgPoints")
    rpg = stats.get("avgRebounds")
    apg = stats.get("avgAssists")
    spg = stats.get("avgSteals")
    bpg = stats.get("avgBlocks")
    fg_pct = stats.get("fieldGoalPct")
    fg3_pct = stats.get("threePointPct")
    ft_pct = stats.get("freeThrowPct")
    topg = stats.get("avgTurnovers")
    
    # Sezónní intro
    intro_parts = [name, "v aktuální sezóně"]
    if team_phrase:
        intro_parts.append(team_phrase)
    
    intro = " ".join(intro_parts)
    
    if gp:
        intro += f" odehrál {fmt_num(gp, 0)} zápasů"
        if mpg:
            intro += f" s průměrem {fmt_num(mpg)} minuty na utkání"
    intro += "."
    
    # Per game stats
    pgs = []
    if ppg is not None: pgs.append(f"{fmt_num(ppg)} bodu")
    if rpg is not None: pgs.append(f"{fmt_num(rpg)} doskoku")
    if apg is not None: pgs.append(f"{fmt_num(apg)} asistence")
    
    sentence2 = ""
    if pgs:
        prefix = f" Jako {pos_word}" if pos_word else ""
        sentence2 = f"{prefix} zaznamenává {', '.join(pgs)} na zápas"
        extras = []
        if spg is not None: extras.append(f"{fmt_num(spg)} zisku")
        if bpg is not None: extras.append(f"{fmt_num(bpg)} bloku")
        if extras:
            sentence2 += f" a k tomu přidává {' a '.join(extras)}"
        sentence2 += "."
    
    # Procenta
    pcts = []
    if fg_pct is not None: pcts.append(f"ze hry {fmt_pct(fg_pct)}")
    if fg3_pct is not None: pcts.append(f"za tři {fmt_pct(fg3_pct)}")
    if ft_pct is not None: pcts.append(f"z trestného hodu {fmt_pct(ft_pct)}")
    
    sentence3 = ""
    if pcts:
        joined = ", ".join(pcts)
        sentence3 = f" Střelecky vykazuje {joined}."
    
    # Turnover - pokud máme
    sentence4 = ""
    if topg is not None:
        sentence4 = f" Na zápas ztrácí míč {fmt_num(topg)}krát."
    
    return intro + sentence2 + sentence3 + sentence4


def build_career_paragraph(name, career_stats, awards, team, position, is_active):
    pos_word = get_position_word(position)
    
    # Awards souhrn
    by_type = {}
    for typ, n, c, s in awards:
        by_type.setdefault(typ, []).append((n, c, s))
    
    awards_parts = []
    
    def cnt_phrase(count, label):
        n = parse_count(count)
        if n > 1:
            return f"{n}× {label}"
        return label
    
    if "mvp" in by_type:
        n, c, s = by_type["mvp"][0]
        awards_parts.append(cnt_phrase(c, "MVP základní části"))
    
    if "finals_mvp" in by_type:
        n, c, s = by_type["finals_mvp"][0]
        seasons_str = ""
        cnt = parse_count(c)
        if s and isinstance(s, list) and cnt <= 1:
            try:
                yrs = []
                for x in s[:3]:
                    if isinstance(x, dict):
                        y = x.get("displayYear") or x.get("year")
                        if y:
                            yrs.append(str(y))
                    elif x:
                        yrs.append(str(x))
                if yrs:
                    seasons_str = f" ({', '.join(yrs)})"
            except (ValueError, TypeError):
                pass
        if cnt > 1:
            awards_parts.append(f"{cnt}× MVP finále NBA")
        else:
            awards_parts.append(f"MVP finále NBA{seasons_str}")
    
    if "all_nba" in by_type:
        total = sum(parse_count(c) for _, c, _ in by_type["all_nba"])
        if total > 0:
            awards_parts.append(f"{total}× nominace do All-NBA Teams")
    
    if "dpoy" in by_type:
        n, c, s = by_type["dpoy"][0]
        awards_parts.append(cnt_phrase(c, "Defensive Player of the Year"))
    
    if "all_defense" in by_type:
        total = sum(parse_count(c) for _, c, _ in by_type["all_defense"])
        if total > 0:
            awards_parts.append(f"{total}× All-Defensive Team")
    
    if "all_star" in by_type:
        n, c, s = by_type["all_star"][0]
        awards_parts.append(cnt_phrase(c, "účastník All-Star Game"))
    
    if "asg_mvp" in by_type:
        n, c, s = by_type["asg_mvp"][0]
        awards_parts.append(cnt_phrase(c, "MVP All-Star Game"))
    
    if "roy" in by_type:
        awards_parts.append("Rookie of the Year")
    
    if "sixth" in by_type:
        n, c, s = by_type["sixth"][0]
        awards_parts.append(cnt_phrase(c, "Sixth Man of the Year"))
    
    if "cup_mvp" in by_type:
        n, c, s = by_type["cup_mvp"][0]
        awards_parts.append(cnt_phrase(c, "MVP NBA Cupu"))
    
    if "leader_scoring" in by_type:
        n, c, s = by_type["leader_scoring"][0]
        awards_parts.append(cnt_phrase(c, "král střelců"))
    if "leader_ast" in by_type:
        n, c, s = by_type["leader_ast"][0]
        awards_parts.append(cnt_phrase(c, "lídr v asistencích"))
    if "leader_reb" in by_type:
        n, c, s = by_type["leader_reb"][0]
        awards_parts.append(cnt_phrase(c, "lídr v doskocích"))
    
    # Sestavení odstavce
    # 1. věta - úspěchy
    sentence1 = name
    if pos_word:
        sentence1 += f", {pos_word}"
    if team:
        sentence1 += f" v dresu {team}"
    
    if awards_parts:
        sentence1 += ", patří mezi nejvýraznější jména NBA — je "
        if len(awards_parts) == 1:
            sentence1 += awards_parts[0] + "."
        elif len(awards_parts) == 2:
            sentence1 += awards_parts[0] + " a " + awards_parts[1] + "."
        else:
            sentence1 += ", ".join(awards_parts[:-1]) + " a " + awards_parts[-1] + "."
    else:
        sentence1 += "."
    
    # 2. věta - kariérní průměry
    sentence2 = ""
    if career_stats:
        gp = career_stats.get("gamesPlayed")
        ppg = career_stats.get("avgPoints")
        rpg = career_stats.get("avgRebounds")
        apg = career_stats.get("avgAssists")
        fg_pct = career_stats.get("fieldGoalPct")
        fg3_pct = career_stats.get("threePointPct")
        ft_pct = career_stats.get("freeThrowPct")
        
        if gp and (ppg or rpg or apg):
            pgs = []
            if ppg is not None: pgs.append(f"{fmt_num(ppg)} bodu")
            if rpg is not None: pgs.append(f"{fmt_num(rpg)} doskoku")
            if apg is not None: pgs.append(f"{fmt_num(apg)} asistence")
            
            sentence2 = f" V základní části kariéry odehrál {fmt_num(gp, 0)} zápasů s průměry {', '.join(pgs)} na utkání"
            
            pcts = []
            if fg_pct is not None: pcts.append(f"ze hry {fmt_pct(fg_pct)}")
            if fg3_pct is not None: pcts.append(f"za tři {fmt_pct(fg3_pct)}")
            if ft_pct is not None: pcts.append(f"z trestného hodu {fmt_pct(ft_pct)}")
            if pcts:
                sentence2 += f", dlouhodobě střílí {', '.join(pcts)}"
            sentence2 += "."
    
    # 3. status
    sentence3 = ""
    if not is_active:
        sentence3 = " V současnosti není veden jako aktivní hráč NBA."
    
    return sentence1 + sentence2 + sentence3


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
            "error": f"Hráč '{name}' nebyl nalezen. "
                     f"Zkus zadat jméno v angličtině (např. 'Nikola Jokic' místo 'Jokič')."
        }), 404
    
    try:
        result = generate_player_text(player_id, display_name)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": f"Chyba při zpracování: {str(e)}"}), 500


@app.route("/api/debug/<player_id>")
def api_debug(player_id):
    overview = http_get(OVERVIEW_URL.format(id=player_id))
    if not overview:
        return jsonify({"error": "overview unavailable"}), 500
    
    splits = extract_stats_splits(overview)
    awards = extract_awards_summary(overview)
    
    return jsonify({
        "extracted_team": extract_team_from_overview(overview, player_id),
        "splits_keys": list(splits.keys()),
        "regular_season": splits.get("Regular Season"),
        "career": splits.get("Career"),
        "awards_summary": awards[:10],
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"NBA Stats running on http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
