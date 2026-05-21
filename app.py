"""
NBA Player Stats - žurnalistický generátor (verze 4, ESPN API)
Postaveno na základě reálné struktury ESPN overview odpovědi.
"""

from flask import Flask, render_template, jsonify, request
import requests
import os

app = Flask(__name__)

TIMEOUT = 20

SEARCH_URL = "https://site.web.api.espn.com/apis/search/v2"
OVERVIEW_URL = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{id}/overview"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/json",
}


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
        return "hráč"
    pos = str(pos).upper().strip()
    if "GUARD" in pos or pos in ("G", "PG", "SG"):
        return "rozehrávač"
    if "FORWARD" in pos or pos in ("F", "SF", "PF"):
        return "křídlo"
    if "CENTER" in pos or pos == "C":
        return "pivot"
    return pos.lower()


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


def search_player(name_query):
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
            item_type = (item.get("type") or "").lower()
            sport = (item.get("sport") or "").lower()
            league = (item.get("league") or "").lower()
            default_league = (item.get("defaultLeague") or "").lower()
            
            is_player = (item_type == "player" or "player" in item_type)
            is_basketball = sport == "basketball" or "basketball" in sport
            
            if is_player or is_basketball:
                pid = item.get("id") or (item.get("uid", "").split(":")[-1] if item.get("uid") else None)
                display = (item.get("displayName") or item.get("display_name") 
                           or item.get("name") or item.get("title", ""))
                
                if not pid or not display:
                    continue
                
                priority = 2
                if "nba" in league or "nba" in default_league:
                    priority = 0
                elif is_basketball:
                    priority = 1
                
                candidates.append((priority, str(pid), display))
    
    if not candidates:
        return None, None, None
    
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1], candidates[0][2], None


def extract_awards_summary(overview):
    awards = safe_get(overview, "awards", default=[])
    if not awards or not isinstance(awards, list):
        return []
    
    summary = []
    for award in awards:
        if not isinstance(award, dict):
            continue
        count = award.get("displayCount") or ""
        name = award.get("name", "")
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
    
    return summary


def extract_team_name(overview):
    for path in [("team",), ("gameLog", "team"), ("athlete", "team"), ("statistics", "team")]:
        t = safe_get(overview, *path)
        if isinstance(t, dict):
            name = t.get("displayName") or t.get("name")
            if name:
                return name
        elif isinstance(t, str) and t:
            return t
    
    # Pokus přes opponent z posledního zápasu
    events = safe_get(overview, "gameLog", "events")
    last_ev = None
    if isinstance(events, dict):
        keys = sorted(events.keys(), reverse=True)
        if keys:
            last_ev = events[keys[0]]
    elif isinstance(events, list) and events:
        last_ev = events[0]
    
    if last_ev and isinstance(last_ev, dict):
        # Tým hráče může být v "team" objektu
        for k in ["team", "athleteTeam", "homeTeam", "awayTeam"]:
            t = last_ev.get(k)
            if isinstance(t, dict):
                name = t.get("displayName") or t.get("name") or t.get("location")
                if name:
                    return name
    
    return None


def calc_averages_from_gamelog(overview):
    labels = safe_get(overview, "gameLog", "labels") \
             or safe_get(overview, "gameLog", "names") \
             or []
    
    season_types = safe_get(overview, "gameLog", "seasonTypes")
    if season_types and isinstance(season_types, list):
        for st in season_types:
            if not isinstance(st, dict):
                continue
            categories = st.get("categories", []) or []
            for cat in categories:
                if not isinstance(cat, dict):
                    continue
                totals = cat.get("totals") or cat.get("statistics")
                events = cat.get("events", []) or []
                if totals and labels and isinstance(totals, list):
                    stat_dict = {}
                    for i, label in enumerate(labels):
                        if i < len(totals):
                            stat_dict[label] = totals[i]
                    stat_dict["GP"] = len(events) if events else None
                    return stat_dict
    
    # Fallback - spočítat z events
    events = safe_get(overview, "gameLog", "events")
    events_list = []
    if isinstance(events, dict):
        events_list = list(events.values())
    elif isinstance(events, list):
        events_list = events
    
    if not events_list or not labels:
        return None
    
    sum_stats = {}
    count = 0
    for ev in events_list:
        if not isinstance(ev, dict):
            continue
        stats = ev.get("stats", []) or []
        if not stats:
            continue
        count += 1
        for i, label in enumerate(labels):
            if i < len(stats):
                val = stats[i]
                try:
                    if val in (None, "", "-"):
                        continue
                    num = float(val)
                    sum_stats[label] = sum_stats.get(label, 0) + num
                except (ValueError, TypeError):
                    pass
    
    if count == 0:
        return None
    
    avg = {k: v / count for k, v in sum_stats.items()}
    avg["GP"] = count
    return avg


def generate_player_text(player_id, display_name):
    overview = http_get(OVERVIEW_URL.format(id=player_id))
    
    if not overview:
        return {
            "player": display_name, "team": "", "position": "",
            "is_active": True,
            "season_paragraph": f"ESPN momentálně nevrací data pro hráče {display_name}.",
            "career_paragraph": "Data nedostupná.",
        }
    
    team = extract_team_name(overview) or ""
    position = overview.get("position", "") or ""
    if isinstance(position, dict):
        position = position.get("abbreviation") or position.get("displayName", "")
    
    awards = extract_awards_summary(overview)
    season_stats = calc_averages_from_gamelog(overview)
    
    season_year = safe_get(overview, "gameLog", "season", "year") \
                  or safe_get(overview, "season", "year") \
                  or ""
    
    has_gamelog = bool(safe_get(overview, "gameLog", "events"))
    is_active = has_gamelog
    
    season_paragraph = build_season_paragraph(
        display_name, season_stats, team, position, is_active, season_year
    )
    career_paragraph = build_career_paragraph(
        display_name, awards, team, position, is_active
    )
    
    return {
        "player": display_name, "team": team, "position": position,
        "is_active": is_active,
        "season_paragraph": season_paragraph,
        "career_paragraph": career_paragraph,
    }


def build_season_paragraph(name, stats, team, position, is_active, season_year):
    pos_word = get_position_word(position)
    team_phrase = f"v dresu {team}" if team else ""
    
    season_label = ""
    if season_year:
        try:
            yr = int(season_year)
            season_label = f"{yr-1}/{str(yr)[-2:]}"
        except (ValueError, TypeError):
            season_label = str(season_year)
    
    if not stats:
        if is_active:
            return (
                f"{name} aktuálně působí v NBA"
                + (f" {team_phrase}" if team_phrase else "")
                + ". Detailní sezónní statistiky nejsou momentálně v očekávaném "
                "formátu k dispozici, ale podle ESPN gamelog je hráč aktivní v probíhající sezóně."
            )
        else:
            return (
                f"{name} momentálně nepatří k aktivním hráčům NBA. "
                f"Aktuální sezónní statistiky nejsou k dispozici."
            )
    
    def gs(*keys):
        for k in keys:
            for variant in [k, k.upper(), k.lower(), k.title()]:
                if variant in stats and stats[variant] not in (None, "", "-"):
                    return stats[variant]
        return None
    
    gp = gs("GP", "G", "Games")
    pts = gs("PTS", "Points")
    reb = gs("REB", "TR", "Rebounds")
    ast = gs("AST", "Assists")
    stl = gs("STL", "Steals")
    blk = gs("BLK", "Blocks")
    fg_pct = gs("FG%", "FGP")
    fg3_pct = gs("3P%", "3PT%", "3PTPCT")
    ft_pct = gs("FT%", "FTP")
    minutes = gs("MIN", "Minutes", "MPG")
    
    intro_parts = [name]
    if season_label:
        intro_parts.append(f"v sezóně {season_label}")
    elif is_active:
        intro_parts.append("v aktuální sezóně")
    if team_phrase:
        intro_parts.append(team_phrase)
    
    intro = " ".join(intro_parts)
    
    if gp:
        intro += f" odehrál {fmt_num(gp, 0)} zápasů"
        if minutes:
            intro += f" s průměrem {fmt_num(minutes)} minuty na utkání"
    intro += "."
    
    pgs = []
    if pts is not None: pgs.append(f"{fmt_num(pts)} bodu")
    if reb is not None: pgs.append(f"{fmt_num(reb)} doskoku")
    if ast is not None: pgs.append(f"{fmt_num(ast)} asistence")
    
    sentence2 = ""
    if pgs:
        prefix = f" Jako {pos_word}" if pos_word != "hráč" else ""
        sentence2 = f"{prefix} zaznamenává {', '.join(pgs)} na zápas"
        extras = []
        if stl is not None: extras.append(f"{fmt_num(stl)} zisku")
        if blk is not None: extras.append(f"{fmt_num(blk)} bloku")
        if extras:
            sentence2 += f" a k tomu přidává {' a '.join(extras)}"
        sentence2 += "."
    
    pcts = []
    if fg_pct is not None: pcts.append(f"ze hry {fmt_pct(fg_pct)}")
    if fg3_pct is not None: pcts.append(f"za tři {fmt_pct(fg3_pct)}")
    if ft_pct is not None: pcts.append(f"z trestného hodu {fmt_pct(ft_pct)}")
    
    sentence3 = ""
    if pcts:
        joined = ", ".join(pcts)
        sentence3 = f" Střelecky vykazuje {joined}."
    
    return intro + sentence2 + sentence3


def build_career_paragraph(name, awards, team, position, is_active):
    pos_word = get_position_word(position)
    
    def parse_count(c):
        """Parse '5x' nebo '3X' nebo '1' na int."""
        if c is None:
            return 1
        s = str(c).strip().lower().replace("x", "").strip()
        try:
            return int(s) if s else 1
        except (ValueError, TypeError):
            return 1
    
    if not awards:
        intro = f"{name}"
        if pos_word != "hráč":
            intro += f", {pos_word}"
        if team:
            intro += f" v dresu {team}"
        intro += ", patří mezi hráče NBA."
        intro += (
            " Detailní kariérní statistiky a historické highs jsou dostupné "
            "na specializovaných databázích jako Basketball-Reference nebo "
            "oficiálních stránkách NBA."
        )
        return intro
    
    by_type = {}
    for typ, n, c, s in awards:
        by_type.setdefault(typ, []).append((n, c, s))
    
    parts = []
    
    def cnt_phrase(count, singular, plural):
        n = parse_count(count)
        if n > 1:
            return f"{n}× {plural}"
        return singular
    
    if "mvp" in by_type:
        n, c, s = by_type["mvp"][0]
        parts.append(cnt_phrase(c, "MVP základní části", "MVP základní části"))
    
    if "finals_mvp" in by_type:
        n, c, s = by_type["finals_mvp"][0]
        seasons_str = ""
        if s and isinstance(s, list) and parse_count(c) <= 1:
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
        parts.append(cnt_phrase(c, f"MVP finále NBA{seasons_str}", "MVP finále NBA"))
    
    if "all_nba" in by_type:
        total = sum(parse_count(c) for _, c, _ in by_type["all_nba"])
        if total > 0:
            parts.append(f"{total}× nominace do All-NBA Teams")
    
    if "dpoy" in by_type:
        n, c, s = by_type["dpoy"][0]
        parts.append(cnt_phrase(c, "Defensive Player of the Year", "Defensive Player of the Year"))
    
    if "all_defense" in by_type:
        total = sum(parse_count(c) for _, c, _ in by_type["all_defense"])
        if total > 0:
            parts.append(f"{total}× All-Defensive Team")
    
    if "all_star" in by_type:
        n, c, s = by_type["all_star"][0]
        parts.append(cnt_phrase(c, "účastník All-Star Game", "účastník All-Star Game"))
    
    if "roy" in by_type:
        parts.append("Rookie of the Year")
    
    if "sixth" in by_type:
        n, c, s = by_type["sixth"][0]
        parts.append(cnt_phrase(c, "Sixth Man of the Year", "Sixth Man of the Year"))
    
    leader_parts = []
    if "leader_scoring" in by_type:
        n, c, s = by_type["leader_scoring"][0]
        leader_parts.append(cnt_phrase(c, "král střelců", "král střelců"))
    if "leader_ast" in by_type:
        n, c, s = by_type["leader_ast"][0]
        leader_parts.append(cnt_phrase(c, "lídr v asistencích", "lídr v asistencích"))
    if "leader_reb" in by_type:
        n, c, s = by_type["leader_reb"][0]
        leader_parts.append(cnt_phrase(c, "lídr v doskocích", "lídr v doskocích"))
    parts.extend(leader_parts)
    
    if not parts:
        intro = f"{name} patří mezi hráče NBA s několika kariérními úspěchy."
    else:
        intro = f"{name}"
        if pos_word != "hráč":
            intro += f", {pos_word}"
        if team:
            intro += f" v dresu {team}"
        intro += ", patří mezi nejvýraznější jména NBA — je "
        
        if len(parts) == 1:
            intro += parts[0] + "."
        elif len(parts) == 2:
            intro += parts[0] + " a " + parts[1] + "."
        else:
            intro += ", ".join(parts[:-1]) + " a " + parts[-1] + "."
    
    if not is_active:
        intro += " V současnosti není veden jako aktivní hráč NBA."
    
    intro += (
        " Pro úplné kariérní průměry a sezónní rozpis lze nahlédnout "
        "na Basketball-Reference nebo na oficiální stránky NBA."
    )
    
    return intro


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
    
    return jsonify({
        "overview_top_keys": list(overview.keys()),
        "gameLog_keys": list(safe_get(overview, "gameLog", default={}).keys()) if isinstance(overview.get("gameLog"), dict) else None,
        "gameLog_labels": safe_get(overview, "gameLog", "labels") or safe_get(overview, "gameLog", "names"),
        "awards_count": len(overview.get("awards", []) or []),
        "first_award": (overview.get("awards") or [{}])[0] if overview.get("awards") else None,
        "extracted_team": extract_team_name(overview),
        "extracted_awards_count": len(extract_awards_summary(overview)),
        "extracted_stats": calc_averages_from_gamelog(overview),
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"NBA Stats running on http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
