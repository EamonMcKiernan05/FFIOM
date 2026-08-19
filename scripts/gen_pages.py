#!/usr/bin/env python3
"""Generate FFIOM static pages sharing the same nav shell.

Pre-launch checklist additions (2026-08-19): unique meta descriptions,
Open Graph tags, canonical URL, JSON-LD schema, skip-to-content link,
cookie consent banner, site footer with auto-updating year, back-to-top
button, scroll progress bar, nav search, breadcrumbs.

index.html (home) is hand-maintained — keep its shell in sync with TEMPLATE.
"""
import os

# Bump on every shell/asset change to bust caches (HTML shells are no-cache,
# but the ?v= pins on JS/CSS matter).
V = "20260819"

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
    <meta name="description" content="{description}">
    <link rel="canonical" href="https://ffiom.com{canonical}">
    <meta property="og:type" content="website">
    <meta property="og:site_name" content="Fantasy Football Isle of Man">
    <meta property="og:title" content="{title} | Fantasy Football Isle of Man">
    <meta property="og:description" content="{description}">
    <meta property="og:image" content="https://ffiom.com/static/img/clubs/PremierLeagueIOM.png">
    <meta property="og:url" content="https://ffiom.com{canonical}">
    <meta name="twitter:card" content="summary">
    <link rel="icon" href="/static/img/clubs/PremierLeagueIOM.png">
    <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@400;600;700;800&display=swap">
    <link rel="stylesheet" href="/static/css/tokens.css?v={v}">
    <link rel="stylesheet" href="/static/css/style.css?v={v}">
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
    <a class="skip-link" href="#main-content">Skip to content</a>
    <div class="scroll-progress" id="scroll-progress" aria-hidden="true"></div>
    <nav class="game-nav">
        <div class="game-nav__inner">
            <a class="game-nav__brand" href="/">
                <img class="game-nav__logo" src="/static/img/clubs/PremierLeagueIOM.png" alt="Fantasy Football Isle of Man">
            </a>
            <button class="nav-toggle" id="nav-toggle" aria-label="Menu" aria-expanded="false"><span></span><span></span><span></span></button>
            <ul class="game-nav__links" id="nav-links">
{links}
            </ul>
            <div class="game-nav__right">
                <button class="nav-search-btn" id="nav-search-btn" aria-label="Search" title="Search (Ctrl+K)">&#8981;</button>
                <button class="theme-toggle" id="theme-toggle" aria-label="Toggle theme">
                    <span class="theme-toggle__sun">&#9728;</span><span class="theme-toggle__moon">&#9790;</span>
                </button>
                <div id="nav-auth" style="display:flex;align-items:center;gap:0.8rem"></div>
            </div>
        </div>
    </nav>

    <main id="main-content">
        <div class="container">
{body}
        </div>
    </main>

    <footer class="site-footer">
        <div class="container site-footer__inner">
            <div class="site-footer__brand">
                <strong>Fantasy Football Isle of Man</strong>
                <span>FPL-style fantasy football for the Isle of Man senior leagues.</span>
            </div>
            <nav class="site-footer__links" aria-label="Footer">
                <a href="/help">Help &amp; rules</a>
                <a href="/players">Players</a>
                <a href="/fixtures">Fixtures</a>
                <a href="/leaderboard">Leaderboard</a>
                <a href="/privacy">Privacy policy</a>
                <a href="https://fulltime.thefa.com" target="_blank" rel="noopener">IOM FA FullTime</a>
            </nav>
            <div class="site-footer__copy">&copy; <span id="footer-year">2026</span> Fantasy Football IOM. Not affiliated with the Premier League or the FA.</div>
        </div>
    </footer>

    <button class="back-to-top" id="back-to-top" aria-label="Back to top">&uarr;</button>

    <div class="cookie-banner" id="cookie-banner" hidden>
        <div class="cookie-banner__inner">
            <p>FFIOM stores your login session and theme preference on this device (local storage and strictly necessary cookies). No tracking or advertising cookies are used.</p>
            <div class="cookie-banner__actions">
                <a href="/privacy">Privacy policy</a>
                <button class="button button--accent button--small" id="cookie-accept">Got it</button>
            </div>
        </div>
    </div>

    <script src="/static/js/app.js?v={v}"></script>
    <script src="/static/js/pages.js?v={v}"></script>
</body>
</html>
"""

def page_body(slug, title, lede, extra=""):
    crumb = f'<nav class="breadcrumb" aria-label="Breadcrumb"><a href="/">Home</a> <span aria-hidden="true">&rsaquo;</span> <span aria-current="page">{title}</span></nav>'
    return f"""            <div class="page-header">
                {crumb}
                <h1>{title}</h1>
                <p class="lede">{lede}</p>
            </div>
{extra}"""

# slug: (title, meta description, lede, body extra)
PAGES = {
    "my-team": ("My Team", "View your FFIOM squad, set your captain and vice-captain, manage your bench and activate chips.", "Your squad, captain picks and chips.", """            <div id="my-team-root"><div class="loading" role="status">Loading your squad&hellip;</div></div>"""),
    "transfers": ("Transfers", "Search every player in the Isle of Man leagues and make your FFIOM transfers in and out.", "Search players and make your moves.", """            <div id="transfers-root"><div class="loading" role="status">Loading transfer market&hellip;</div></div>"""),
    "players": ("Players", "Every player in the Isle of Man senior leagues with prices, points, goals, assists and form.", "Every player in the Isle of Man leagues.", """            <div id="players-root"><div class="loading" role="status">Loading players&hellip;</div></div>"""),
    "fixtures": ("Fixtures", "Upcoming and recent Isle of Man league fixtures with gameweek deadlines and difficulty ratings.", "Upcoming and recent fixtures with difficulty ratings.", """            <div id="fixtures-root"><div class="loading" role="status">Loading fixtures&hellip;</div></div>"""),
    "gameweeks": ("Gameweeks", "Every FFIOM gameweek with deadlines, fixture counts and scoring status.", "Deadlines and status for every gameweek.", """            <div id="gameweeks-root"><div class="loading" role="status">Loading gameweeks&hellip;</div></div>"""),
    "history": ("History", "Your gameweek-by-gameweek FFIOM record: points, bench, transfers, hits and rank.", "Your gameweek-by-gameweek record.", """            <div id="history-root"><div class="loading" role="status">Loading your history&hellip;</div></div>"""),
    "leaderboard": ("Leaderboard", "Overall FFIOM standings across all managers this season.", "Overall standings across all managers.", """            <div id="leaderboard-root"><div class="loading" role="status">Loading leaderboard&hellip;</div></div>"""),
    "leagues": ("Leagues", "Create a private FFIOM mini-league or join one with a code.", "Create and join mini-leagues.", """            <div id="leagues-root"><div class="loading" role="status">Loading leagues&hellip;</div></div>"""),
    "dream-team": ("Dream Team", "The best XI of each FFIOM gameweek, picked by points.", "The best XI of each gameweek.", """            <div id="dream-team-root"><div class="loading" role="status">Loading dream team&hellip;</div></div>"""),
    "rankings": ("Rankings", "FFIOM player rankings by points, goals, assists, form and price.", "Player rankings by points, goals, form and more.", """            <div id="rankings-root"><div class="loading" role="status">Loading rankings&hellip;</div></div>"""),
}

HELP_BODY = """            <div class="page-header">
                <nav class="breadcrumb" aria-label="Breadcrumb"><a href="/">Home</a> <span aria-hidden="true">&rsaquo;</span> <span aria-current="page">Help</span></nav>
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
            </div>
            <div class="card">
                <h2 class="card__title">FAQ</h2>
                <div class="faq">
                    <details class="faq-item"><summary>When is the transfer deadline?</summary><p>Transfers lock at 11:00 on Saturday, before each gameweek. See the <a href="/gameweeks">Gameweeks</a> page for exact deadlines.</p></details>
                    <details class="faq-item"><summary>Where do the player stats come from?</summary><p>Appearances, goals, assists and results are synced automatically from the official IOM FA FullTime system after each match.</p></details>
                    <details class="faq-item"><summary>How do I play with friends?</summary><p>Create a league on the <a href="/leagues">Leagues</a> page and share the code. Friends join with that code and you are ranked against each other.</p></details>
                    <details class="faq-item"><summary>What happens if my captain doesn't play?</summary><p>Your vice-captain takes over automatically and scores double points instead.</p></details>
                    <details class="faq-item"><summary>Is FFIOM free to play?</summary><p>Yes. FFIOM is a fan-made game for the Isle of Man football community and is free to join.</p></details>
                </div>
            </div>
            <div class="card">
                <h2 class="card__title">Related</h2>
                <ul class="related-links">
                    <li><a href="/players">Browse all players</a></li>
                    <li><a href="/fixtures">This season's fixtures</a></li>
                    <li><a href="/leaderboard">Overall leaderboard</a></li>
                    <li><a href="/privacy">Privacy policy</a></li>
                </ul>
            </div>"""

PRIVACY_BODY = """            <div class="page-header">
                <nav class="breadcrumb" aria-label="Breadcrumb"><a href="/">Home</a> <span aria-hidden="true">&rsaquo;</span> <span aria-current="page">Privacy</span></nav>
                <h1>Privacy policy</h1>
                <p class="lede">Last updated: 19 August 2026</p>
            </div>
            <div class="card">
                <h2 class="card__title">What we collect</h2>
                <p>When you register we store your username, email address, a hashed copy of your password and your team name. We also store the fantasy decisions you make (squad picks, transfers, captain choices, league membership) so the game works.</p>
            </div>
            <div class="card">
                <h2 class="card__title">What we don't do</h2>
                <ul class="privacy-list">
                    <li>We do not sell or share your data with anyone.</li>
                    <li>We do not use advertising or third-party tracking cookies.</li>
                    <li>We do not run analytics that identify you personally.</li>
                </ul>
            </div>
            <div class="card">
                <h2 class="card__title">Cookies and local storage</h2>
                <p>FFIOM uses strictly necessary storage only: your login session (a refresh cookie plus local storage tokens) and your theme preference. Everything is on your own device and can be cleared at any time from your browser settings.</p>
            </div>
            <div class="card">
                <h2 class="card__title">Data sources</h2>
                <p>Player names, match results and statistics come from the public <a href="https://fulltime.thefa.com" target="_blank" rel="noopener">FA FullTime</a> system for Isle of Man leagues. If you believe player data is incorrect, contact the league administrators via FullTime.</p>
            </div>
            <div class="card">
                <h2 class="card__title">Your rights</h2>
                <p>You can stop playing at any time. To have your account and data deleted, contact the site administrator and we will remove your account and team records.</p>
            </div>"""

LOGIN_BODY = """            <div class="form-card card">
                <h1 style="margin-bottom:2.4rem">Sign in</h1>
                <form onsubmit="handleLogin(event)" novalidate>
                    <div class="form-field">
                        <label for="login-username">Username</label>
                        <input id="login-username" type="text" required autocomplete="username">
                    </div>
                    <div class="form-field">
                        <label for="login-password">Password</label>
                        <div class="pw-wrap">
                            <input id="login-password" type="password" required autocomplete="current-password">
                            <button type="button" class="pw-toggle" data-pw-toggle="login-password" aria-label="Show password">Show</button>
                        </div>
                    </div>
                    <div class="form-error" id="login-error" role="alert" hidden></div>
                    <button class="button button--filled button--full-width" type="submit">Sign in</button>
                </form>
                <p class="form-alt">New to FFIOM? <a href="/register">Create an account</a></p>
            </div>"""

REGISTER_BODY = """            <div class="form-card card">
                <h1 style="margin-bottom:2.4rem">Create your team</h1>
                <form onsubmit="handleRegister(event)" novalidate>
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
                        <div class="pw-wrap">
                            <input id="reg-password" type="password" required minlength="10" autocomplete="new-password">
                            <button type="button" class="pw-toggle" data-pw-toggle="reg-password" aria-label="Show password">Show</button>
                        </div>
                        <p class="form-hint">At least 10 characters, with an uppercase letter, a lowercase letter and a number.</p>
                    </div>
                    <div class="form-error" id="register-error" role="alert" hidden></div>
                    <button class="button button--filled button--full-width" type="submit">Register</button>
                </form>
                <p class="form-alt">Already registered? <a href="/login">Sign in</a></p>
            </div>"""

NOTFOUND_BODY = """            <div class="empty-state" style="padding-top:6.4rem">
                <h1 style="margin-bottom:1.6rem">404 &mdash; that page is offside</h1>
                <p style="margin-bottom:2.4rem">The page you're looking for doesn't exist or has been moved.</p>
                <div style="display:flex;gap:1.2rem;justify-content:center;flex-wrap:wrap">
                    <a class="button button--filled" href="/">Back to home</a>
                    <a class="button button--outlined" href="/players">Browse players</a>
                </div>
            </div>"""


def nav_links(active_href):
    rows = []
    for href, label in NAV:
        cls = "game-nav__link is-active" if href == active_href else "game-nav__link"
        rows.append(f'                <li><a class="{cls}" href="{href}">{label}</a></li>')
    return "\n".join(rows)


def write_page(path, slug, title, body, description, canonical, active_href=None):
    html = TEMPLATE.format(
        slug=slug, title=title, description=description, canonical=canonical,
        links=nav_links(active_href if active_href is not None else f"/{slug}"),
        body=body, v=V,
    )
    with open(path, "w") as f:
        f.write(html)
    print("wrote", path)


base = "static/pages"
os.makedirs(base, exist_ok=True)

for slug, (title, desc, lede, extra) in PAGES.items():
    write_page(f"{base}/{slug}.html", slug, title, page_body(slug, title, lede, extra),
               desc, f"/{slug}")

write_page(f"{base}/help.html", "help", "Help", HELP_BODY,
           "How FFIOM works: squads, scoring, captains, transfers, chips and mini-leagues.",
           "/help", active_href="/help")
write_page(f"{base}/privacy.html", "privacy", "Privacy policy", PRIVACY_BODY,
           "What Fantasy Football Isle of Man stores about you, and what we never do with it.",
           "/privacy", active_href="")
write_page(f"{base}/login.html", "login", "Sign in", LOGIN_BODY,
           "Sign in to your Fantasy Football Isle of Man account.",
           "/login", active_href="")
write_page(f"{base}/register.html", "register", "Create your team", REGISTER_BODY,
           "Register for Fantasy Football Isle of Man, pick your 13-player squad and join mini-leagues.",
           "/register", active_href="")
write_page(f"{base}/404.html", "404", "Page not found", NOTFOUND_BODY,
           "This page does not exist.", "/404", active_href="")
print("done")
