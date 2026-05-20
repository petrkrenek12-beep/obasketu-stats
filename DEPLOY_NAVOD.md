# NBA Stats — návod na nasazení

Tento návod tě provede od stažení souborů až po veřejnou URL, na které appka poběží. Žádný terminál, žádný Python na tvém PC. Trvá to ~15 minut.

---

## Co budeš dělat (přehled)

1. Založíš nové GitHub repo a nahraješ tam tyhle soubory
2. Zaregistruješ se na **Render.com** (přihlášení přes GitHub)
3. Render připojíš ke svému GitHub repu
4. Render appku automaticky postaví a rozjede
5. Dostaneš URL ve tvaru `https://nba-stats-tvuj-nazev.onrender.com`

---

## Krok 1 — GitHub repo

1. Jdi na **github.com** → klikni vpravo nahoře na `+` → **New repository**
2. Pojmenuj ho třeba `nba-stats-generator`
3. Nastav **Public** (Render free tier potřebuje veřejné repo)
4. NEPŘIDÁVEJ README ani .gitignore (ty už máme v souborech)
5. Klikni **Create repository**

Pak nahraj soubory. GitHub má dvě možnosti:

**a) Drag & drop přes web (nejjednodušší):**

Na stránce repa klikni **uploading an existing file** (modrý odkaz uprostřed) → přetáhni tam **všechny soubory ze složky `nba_app_deploy`**, kterou jsem ti připravil:

- `app.py`
- `requirements.txt`
- `Procfile` (bez přípony, je to schválně)
- `runtime.txt`
- `.gitignore`
- složka `templates/` s `index.html` uvnitř

⚠️ **Důležité:** Strukturu musíš zachovat. `templates/index.html` musí být v podsložce, ne v rootu. Když to taháš přes web rozhraní, drag-and-drop celé složky `templates` funguje ve většině prohlížečů (Chrome, Edge, Firefox).

Pokud by to drag-and-drop nezvládl, nahraj soubory jeden po druhém — pro `templates/index.html` napiš do názvu souboru `templates/index.html` (s lomítkem) a GitHub složku vytvoří sám.

6. Dole na stránce napiš commit message (např. "Initial commit") → **Commit changes**

**b) GitHub Desktop:**

Pokud máš GitHub Desktop, je to ještě jednodušší — naklonuj repo, zkopíruj soubory do složky, commit & push.

---

## Krok 2 — Registrace na Render

1. Jdi na **render.com** → **Get Started**
2. Klikni **GitHub** → autorizuj přístup
3. Hotovo, jsi v dashboardu

---

## Krok 3 — Připojení repa

1. V Render dashboardu klikni **New +** (vpravo nahoře) → **Web Service**
2. **Build and deploy from a Git repository** → **Next**
3. Najdi své repo `nba-stats-generator` v seznamu → klikni **Connect**
   - Pokud ho tam nevidíš, klikni **Configure account** a Renderu povol přístup ke konkrétnímu repu

---

## Krok 4 — Nastavení služby

Render ti ukáže formulář. Vyplň/zkontroluj:

| Pole | Hodnota |
|------|---------|
| **Name** | `nba-stats` (nebo cokoliv, bude součástí URL) |
| **Region** | `Frankfurt` (nejblíže k ČR — důležité pro rychlost) |
| **Branch** | `main` |
| **Root Directory** | (nech prázdné) |
| **Runtime** | `Python 3` |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `gunicorn app:app` |
| **Instance Type** | **Free** |

Pak dole klikni **Create Web Service**.

---

## Krok 5 — Čekání na build

Render teď stahuje kód z GitHubu, instaluje závislosti a spouští appku. Trvá to **3–6 minut**.

Sleduj log ve spodní části — když uvidíš `Your service is live 🎉` a stav nahoře se přepne na **Live** (zelená tečka), je hotovo.

Klikni na URL nahoře (něco jako `https://nba-stats-xyz.onrender.com`) a appka by měla naběhnout.

---

## Důležité poznámky o free tieru Renderu

🟡 **Appka usíná po 15 minutách nečinnosti.** Když přijdeš po hodině, první načtení trvá 30–60 sekund (Render appku probouzí). Poté funguje normálně.

🟡 **750 hodin měsíčně zdarma.** Stačí na příležitostné používání. Pokud bys to chtěl mít stále aktivní, je potřeba placený plán ($7/měsíc).

🟡 **Pokud NBA API začne odmítat requesty z Render IP** (občas se stává), poznáš to podle toho, že appka bude vracet chybu "Chyba při načítání dat z NBA API". V tom případě napiš a přepneme backend na balldontlie.io API, které je s hostingem bez problémů.

---

## Update kódu později

Kdykoli pushneš změnu do GitHub repa (main branch), Render to automaticky detekuje a appku přebuilduje. Žádné další kroky.

---

## Když něco nefunguje

**Build selže:** podívej se do logu v Renderu. Nejčastěji chybí soubor nebo má špatnou strukturu (templates/ musí být složka).

**Appka naběhne, ale vrací chybu při hledání hráče:** to je nejspíš timeout NBA API. Zkus to znovu za chvíli. Pokud to dělá pořád, napiš.

**Appka padá s "Application Error":** v Renderu klikni **Logs** a podívej se na poslední řádky. Pošli mi je a vyřešíme to.

---

To je vše. Kdyby ses zasekl v kterémkoliv kroku, napiš v jakém a u čeho — pomůžu dál.
