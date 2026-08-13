#!/usr/bin/env python3
"""Generate FFIOM static pages sharing the same nav shell."""
import os

NAV = [
    ("/", "Home"),
    ("/my-team", "My Team"),
    ("/transfers", "Transfers"),
    ("/players", "Players"),
    ("/fixtures", "Fixtures"),
    ("/gameweeks", "Gameweeks"),
    ("/history", "History"),
    ("/leaderboard", "Leaderboard"),
    ("/leagues", "Leagues"),
    ("/dream-team", "Dream Team"),
    ("/rankings", "Rankings"),
    ("/help", "Help"),
]

TEMPLATE = """<!DOCTYPE html>
<html lang="en" class="light-theme">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} | Fantasy Football Isle of Man</title>
    <link rel="icon" href="/static/img/clubs/PremierLeagueIOM.png">
    <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@400;600;700;800&display=swap">
    <link rel="stylesheet" href="/static/css/tokens.css">
    <link rel="stylesheet" href="/static/css/style.css">
    <script>
        (function () {{
            var t = localStorage.getItem('theme');
            if (!t || t === 'null') {{
                t = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark-theme' : 'light-theme';
            }}
            document.documentElement.classList.remove('light-theme', 'dark-theme');
            document.documentElement.classList.add(t);
        }})();
    </script>
</head>
<body data-page="{slug}">
    <nav class="game-nav">
        <div class="game-nav__inner">
            <a class="game-nav__brand" href="/">
                <img class="game-nav__logo" src="/static/img/clubs/PremierLeagueIOM.png" alt="Fantasy Football Isle of Man">
            </a>
            <button class="nav-toggle" id="nav-toggle" aria-label="Menu"><span></span><span></span><span></span></button>
            <ul class="game-nav__links" id="nav-links">
{links}
            </ul>
            <div class="game-nav__right">
                <button class="theme-toggle" id="theme-toggle" aria-label="Toggle theme">
                    <span class="theme-toggle__sun">&#9728;</span><span class="theme-toggle__moon">&#9790;</span>
                </button>
                <div id="nav-auth" style="display:flex;align-items:center;gap:0.8rem"></div>
            </div>
        </div>
    </nav>

    <main>
        <div class="container">
{body}
        </div>
    </main>

    <script src="/static/js/app.js"></script>
    <script src="/static/js/pages.js"></script>
</body>
</html>
"""

def page_body(slug, title, lede, extra=""):
    return f"""            <div class="page-header">
                <h1>{title}</h1>
                <p class="lede">{lede}</p>
            </div>
{extra}"""

PAGES = {
    "my-team": ("My Team", "Your squad, captain picks and chips.", """            <div id="my-team-root"><div class="loading">Loading your squad&hellip;</div></div>"""),
    "transfers": ("Transfers", "Search players and make your moves.", """            <div id="transfers-root"><div class="loading">Loading transfer market&hellip;</div></div>"""),
    "players": ("Players", "Every player in the Isle of Man leagues.", """            <div id="players-root"><div class="loading">Loading players&hellip;</div></div>"""),
    "fixtures": ("Fixtures", "Upcoming and recent fixtures with difficulty ratings.", """            <div id="fixtures-root"><div class="loading">Loading fixtures&hellip;</div></div>"""),
    "gameweeks": ("Gameweeks", "Deadlines and status for every gameweek.", """            <div id="gameweeks-root"><div class="loading">Loading gameweeks&hellip;</div></div>"""),
    "history": ("History", "Your gameweek-by-gameweek record.", """            <div id="history-root"><div class="loading">Loading your history&hellip;</div></div>"""),
    "leaderboard": ("Leaderboard", "Overall standings across all managers.", """            <div id="leaderboard-root"><div class="loading">Loading leaderboard&hellip;</div></div>"""),
    "leagues": ("Leagues", "Create and join mini-leagues.", """            <div id="leagues-root"><div class="loading">Loading leagues&hellip;</div></div>"""),
    "dream-team": ("Dream Team", "The best XI of each gameweek.", """            <div id="dream-team-root"><div class="loading">Loading dream team&hellip;</div></div>"""),
    "rankings": ("Rankings", "Player rankings by points, goals, form and more.", """            <div id="rankings-root"><div class="loading">Loading rankings&hellip;</div></div>"""),
}

HELP_BODY = """            <div class="page-header">
                <h1>Help</h1>
                <p class="lede">How Fantasy Football Isle of Man works.</p>
            </div>
            <div class="card">
                <h2 class="card__title">Squad</h2>
                <p>Pick a squad of 13 players within the budget. Choose a starting XI each gameweek &mdash; your bench covers no-shows.</p>
            </div>
            <div class="card">
                <h2 class="card__title">Scoring</h2>
                <div class="table-wrap"><table class="data-table">
                    <thead><tr><th>Action</th><th class="num">Points</th></tr></thead>
                    <tbody>
                        <tr><td>Playing up to 60 mins</td><td class="num">1</td></tr>
                        <tr><td>Playing 60+ mins</td><td class="num">2</td></tr>
                        <tr><td>Goal scored</td><td class="num">4</td></tr>
                        <tr><td>Assist</td><td class="num">3</td></tr>
                        <tr><td>Clean sheet</td><td class="num">4</td></tr>
                        <tr><td>Every 3 saves</td><td class="num">1</td></tr>
                        <tr><td>Penalty save</td><td class="num">5</td></tr>
                        <tr><td>Every 2 goals conceded</td><td class="num">-1</td></tr>
                        <tr><td>Yellow card</td><td class="num">-1</td></tr>
                        <tr><td>Red card</td><td class="num">-3</td></tr>
                        <tr><td>Own goal</td><td class="num">-2</td></tr>
                        <tr><td>Penalty missed</td><td class="num">-2</td></tr>
                    </tbody>
                </table></div>
            </div>
            <div class="card">
                <h2 class="card__title">Captain &amp; vice-captain</h2>
                <p>Your captain scores double points. If the captain doesn't play, the vice-captain takes over.</p>
            </div>
            <div class="card">
                <h2 class="card__title">Transfers &amp; chips</h2>
                <p>You get free transfers each gameweek; extra transfers cost points. Chips (Wildcard, Bench Boost, Triple Captain) can be activated once per season from the My Team page.</p>
            </div>
            <div class="card">
                <h2 class="card__title">Mini-leagues</h2>
                <p>Create a league on the Leagues page and share the code with friends, or join one with a code.</p>
            </div>"""

LOGIN_BODY = """            <div class="form-card card">
                <h1 style="margin-bottom:2.4rem">Sign in</h1>
                <form onsubmit="handleLogin(event)">
                    <div class="form-field">
                        <label for="login-username">Username</label>
                        <input id="login-username" type="text" required autocomplete="username">
                    </div>
                    <div class="form-field">
                        <label for="login-password">Password</label>
                        <input id="login-password" type="password" required autocomplete="current-password">
                    </div>
                    <button class="button button--filled button--full-width" type="submit">Sign in</button>
                </form>
                <p class="form-alt">New to FFIOM? <a href="/register">Create an account</a></p>
            </div>"""

REGISTER_BODY = """            <div class="form-card card">
                <h1 style="margin-bottom:2.4rem">Create your team</h1>
                <form onsubmit="handleRegister(event)">
                    <div class="form-field">
                        <label for="reg-username">Username</label>
                        <input id="reg-username" type="text" required autocomplete="username">
                    </div>
                    <div class="form-field">
                        <label for="reg-email">Email</label>
                        <input id="reg-email" type="email" required autocomplete="email">
                    </div>
                    <div class="form-field">
                        <label for="reg-team-name">Team name</label>
                        <input id="reg-team-name" type="text" required maxlength="40">
                    </div>
                    <div class="form-field">
                        <label for="reg-password">Password</label>
                        <input id="reg-password" type="password" required minlength="6" autocomplete="new-password">
                    </div>
                    <button class="button button--filled button--full-width" type="submit">Register</button>
                </form>
                <p class="form-alt">Already registered? <a href="/login">Sign in</a></p>
            </div>"""


def nav_links(active_href):
    rows = []
    for href, label in NAV:
        cls = "game-nav__link is-active" if href == active_href else "game-nav__link"
        rows.append(f'                <li><a class="{cls}" href="{href}">{label}</a></li>')
    return "\n".join(rows)


def write_page(path, slug, title, body, active_href=None):
    html = TEMPLATE.format(
        slug=slug, title=title,
        links=nav_links(active_href if active_href is not None else f"/{slug}"),
        body=body,
    )
    with open(path, "w") as f:
        f.write(html)
    print("wrote", path)


base = "static/pages"
os.makedirs(base, exist_ok=True)

for slug, (title, lede, extra) in PAGES.items():
    write_page(f"{base}/{slug}.html", slug, title, page_body(slug, title, lede, extra))

write_page(f"{base}/help.html", "help", "Help", HELP_BODY)
write_page(f"{base}/login.html", "login", "Sign in", LOGIN_BODY, active_href="")
write_page(f"{base}/register.html", "register", "Register", REGISTER_BODY, active_href="")
print("done")
