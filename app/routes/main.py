"""
Main routes (homepage, etc.)
"""

from flask import Blueprint, render_template, url_for, Response, send_from_directory, send_file
from flask_login import current_user
from app.services.tournament_service import TournamentService
import os
from pathlib import Path
from flask import request

bp = Blueprint("main", __name__)

# Dioxus SPA is built to frontend/dist; serve it at /app/
_FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


@bp.route("/app/")
@bp.route("/app")
def app_spa():
    """Serve the Dioxus SPA index. SPA lives at /app/."""
    index_path = _FRONTEND_DIST / "index.html"
    if not index_path.exists():
        return "Frontend not built. Run: cd frontend && dx build", 503
    return send_file(index_path, mimetype="text/html")


@bp.route("/app/<path:path>")
def app_static(path):
    """Serve SPA assets (JS, WASM, etc.) from frontend/dist."""
    return send_from_directory(_FRONTEND_DIST, path)


@bp.route("/")
def index():
    """Homepage showing published tournaments."""
    context = TournamentService.get_homepage_context(current_user)
    return render_template("index.html", **context)


@bp.route("/teams")
def teams():
    """List all teams."""
    from models import Team

    search = request.args.get("search", "")
    if search:
        teams = Team.query.filter(
            Team.name.contains(search) | Team.id.contains(search)
        ).all()
    else:
        teams = Team.query.all()
    return render_template("teams.html", teams=teams)


@bp.route("/players")
def players():
    """List all players."""
    from models import Player

    search = request.args.get("search", "")
    page = request.args.get("page", 1, type=int)
    per_page = 50

    # Build base query
    if search:
        query = Player.query.filter(
            Player.name.contains(search) | Player.id.contains(search)
        )
    else:
        query = Player.query

    # Get total count for pagination
    total = query.count()
    total_pages = (total + per_page - 1) // per_page  # Ceiling division

    # Apply pagination
    offset = (page - 1) * per_page
    players = query.order_by(Player.name.asc()).offset(offset).limit(per_page).all()

    return render_template(
        "players.html",
        players=players,
        page=page,
        total_pages=total_pages,
        total=total,
        search=search,
    )


@bp.route("/about")
def about():
    """About page explaining Arctos."""
    return render_template("about.html")


@bp.route("/sitemap.xml")
def sitemap():
    """Generate XML sitemap for search engines."""

    # Get base URL from request
    base_url = request.url_root.rstrip("/")

    # Static pages to include
    urls = [
        {
            "loc": base_url + url_for("main.index"),
            "changefreq": "daily",
            "priority": "1.0",
        },
        {
            "loc": base_url + url_for("auth.login"),
            "changefreq": "monthly",
            "priority": "0.8",
        },
        {
            "loc": base_url + url_for("main.teams"),
            "changefreq": "daily",
            "priority": "0.9",
        },
        {
            "loc": base_url + url_for("main.players"),
            "changefreq": "daily",
            "priority": "0.9",
        },
        {
            "loc": base_url + url_for("matches.stones_player"),
            "changefreq": "monthly",
            "priority": "0.9",
        },
        {
            "loc": base_url + url_for("tournaments.new_tournament"),
            "changefreq": "monthly",
            "priority": "0.7",
        },
        {
            "loc": base_url + url_for("main.about"),
            "changefreq": "monthly",
            "priority": "0.6",
        },
    ]

    # Generate XML
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'

    for url_data in urls:
        xml += "  <url>\n"
        xml += f'    <loc>{url_data["loc"]}</loc>\n'
        xml += f'    <changefreq>{url_data["changefreq"]}</changefreq>\n'
        xml += f'    <priority>{url_data["priority"]}</priority>\n'
        xml += "  </url>\n"

    xml += "</urlset>"

    return Response(xml, mimetype="application/xml")


@bp.route("/robots.txt")
def robots():
    """Generate robots.txt file pointing to sitemap."""
    base_url = request.url_root.rstrip("/")
    sitemap_url = base_url + url_for("main.sitemap")

    robots_txt = f"""User-agent: *
Allow: /

Sitemap: {sitemap_url}
"""

    return Response(robots_txt, mimetype="text/plain")


@bp.route("/docs")
def docs():
    """User documentation page."""
    p = Path(__file__).parent.parent.parent / "docs" / "docs.md"
    with open(p, "r", encoding="utf-8") as f:
        markdown_content = f.read()
    return render_template(
        "markdown.html", markdown_content=markdown_content, title="User Docs"
    )


@bp.route("/privacy-policy")
def privacy_policy():
    """privacy policy page (just render markdown)"""
    p = Path(__file__).parent.parent.parent / "docs" / "privacy-policy.md"
    with open(p, "r", encoding="utf-8") as f:
        md_content = f.read()
    return render_template(
        "markdown.html", markdown_content=md_content, title="Privacy Policy"
    )


@bp.route("/data-accessibility-guide")
def data_accessibility_guide():
    """data accessibility guide page (just render markdown)"""
    p = Path(__file__).parent.parent.parent / "docs" / "data-accessibility-guide.md"
    with open(p, "r", encoding="utf-8") as f:
        md_content = f.read()
    return render_template(
        "markdown.html", markdown_content=md_content, title="Data Accessibility Guide"
    )


@bp.route("/thanks")
def thanks():
    """credits page"""
    p = Path(__file__).parent.parent.parent / "docs" / "thanks.md"
    with open(p, "r", encoding="utf-8") as f:
        md_content = f.read()
    return render_template(
        "markdown.html", markdown_content=md_content, title="Credits"
    )


@bp.route("/license")
def license():
    """license page"""
    p = Path(__file__).parent.parent.parent / "docs" / "license.md"
    with open(p, "r", encoding="utf-8") as f:
        md_content = f.read()
    return render_template(
        "markdown.html", markdown_content=md_content, title="License"
    )


@bp.route("/terms")
def terms_and_conditions():
    """nasty legal page"""
    p = Path(__file__).parent.parent.parent / "docs" / "terms.md"
    with open(p, "r", encoding="utf-8") as f:
        md_content = f.read()
    return render_template(
        "markdown.html", markdown_content=md_content, title="Terms and Conditions"
    )
