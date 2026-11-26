#!/usr/bin/env python3
"""Generate a GitHub profile dossier from public repository metadata."""
from __future__ import annotations

import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
CONFIG = ROOT / "dossier.json"
GIF = ROOT / "assets" / "signal.gif"
START = "<!-- DOSSIER:START -->"
END = "<!-- DOSSIER:END -->"
API = "https://api.github.com"


class GitHubAPIError(RuntimeError):
    """Raised when GitHub API data cannot be retrieved."""


def load_config() -> dict[str, Any]:
    with CONFIG.open(encoding="utf-8") as handle:
        config = json.load(handle)
    if not isinstance(config.get("owner"), str) or not config["owner"].strip():
        raise ValueError("dossier.json must contain a non-empty owner.")
    if not isinstance(config.get("featured"), list):
        raise ValueError("dossier.json featured must be a list.")
    if "descriptions" in config and not isinstance(config["descriptions"], dict):
        raise ValueError("dossier.json descriptions must be a dictionary.")
    return config


def github_get(path: str) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "navaneethan-profile-dossier",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(API + path, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        raise GitHubAPIError(f"GitHub API request failed for {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise GitHubAPIError(f"GitHub API returned invalid JSON for {path}") from exc


def markdown_text(value: Any, limit: int = 220) -> str:
    """Flatten and escape untrusted API text before inserting it into Markdown."""
    text = html.unescape(str(value or "").replace("\r", " ").replace("\n", " "))
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("|", "／")
    text = text.replace("`", "ˋ")
    text = text.replace("[", "［").replace("]", "］")
    text = text.replace("<", "‹").replace(">", "›")
    text = text.replace("*", "＊").replace("_", "＿")
    return text[:limit].rstrip()


def safe_repo_url(repo: dict[str, Any], owner: str) -> str:
    # Construct the canonical URL instead of trusting a URL supplied in API text.
    name = str(repo.get("name", ""))
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
        raise ValueError(f"Unexpected repository name: {name!r}")
    return f"https://github.com/{owner}/{name}"


def parse_date(value: str | None) -> str:
    if not value:
        return "Date unavailable"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.strftime("%d %b %Y")
    except ValueError:
        return "Date unavailable"


def list_public_repositories(owner: str) -> list[dict[str, Any]]:
    """Read all public repository pages, rather than silently stopping at 100."""
    collected: list[dict[str, Any]] = []
    page = 1
    while True:
        query = urllib.parse.urlencode({
            "type": "public", "sort": "updated", "per_page": 100, "page": page
        })
        result = github_get(f"/users/{urllib.parse.quote(owner)}/repos?{query}")
        if not isinstance(result, list):
            raise GitHubAPIError("Unexpected repository-list response from GitHub.")
        collected.extend(item for item in result if isinstance(item, dict))
        if len(result) < 100:
            break
        page += 1
    return collected


def get_featured(owner: str, names: list[str]) -> list[dict[str, Any]]:
    result = []
    for name in names:
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            print(f"Skipping invalid featured repository name: {name!r}", file=sys.stderr)
            continue
        try:
            repo = github_get(f"/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(name)}")
        except GitHubAPIError as exc:
            print(f"Featured repository skipped ({name}): {exc}", file=sys.stderr)
            continue
        if repo.get("private") or repo.get("archived"):
            continue
        result.append(repo)
    return result


def project_card(
    repo: dict[str, Any],
    number: int,
    owner: str,
    limit: int,
    curated_descriptions: dict[str, str] | None = None,
) -> str:
    name_raw = repo.get("name") or ""
    name = markdown_text(name_raw, 80) or "Untitled repository"
    curated = (curated_descriptions or {}).get(name_raw)
    raw_desc = curated if (curated is not None and str(curated).strip()) else repo.get("description")
    description = markdown_text(raw_desc, limit) or "No public description supplied."
    language = markdown_text(repo.get("language") or "Not specified", 45)
    stars = repo.get("stargazers_count", 0)
    if not isinstance(stars, int) or stars < 0:
        stars = 0
    pushed = parse_date(repo.get("pushed_at"))
    url = safe_repo_url(repo, owner)
    return (
        f"### CASE FILE / {number:02d} — [{name}]({url})\n\n"
        f"{description}\n\n"
        f"`{language}` · `★ {stars}` · `PUSHED {pushed.upper()}`"
    )


def build_dynamic_section(config: dict[str, Any]) -> str:
    owner = config["owner"]
    limit = int(config.get("max_description_length", 220))
    curated_descriptions = config.get("descriptions", {})
    featured = get_featured(owner, config["featured"])
    cards = [
        project_card(repo, index + 1, owner, limit, curated_descriptions)
        for index, repo in enumerate(featured)
    ]
    featured_content = "\n\n---\n\n".join(cards) if cards else "_No featured public repositories were found._"

    excluded = set(config.get("excluded", [])) | {owner}
    repositories = list_public_repositories(owner)
    eligible = [
        repo for repo in repositories
        if repo.get("name") not in excluded
        and not repo.get("private")
        and not repo.get("fork")
        and not repo.get("archived")
        and repo.get("pushed_at")
    ]
    eligible.sort(key=lambda repo: repo.get("pushed_at") or "", reverse=True)

    if eligible:
        latest = eligible[0]
        latest_name_raw = latest.get("name") or ""
        name = markdown_text(latest_name_raw, 80)
        curated_latest = curated_descriptions.get(latest_name_raw)
        raw_latest_desc = (
            curated_latest
            if (curated_latest is not None and str(curated_latest).strip())
            else latest.get("description")
        )
        description = markdown_text(raw_latest_desc, limit) or "No public description supplied."
        language = markdown_text(latest.get("language") or "Not specified", 45)
        stars = latest.get("stargazers_count", 0)
        if not isinstance(stars, int) or stars < 0:
            stars = 0
        url = safe_repo_url(latest, owner)
        latest_content = (
            f"### [{name}]({url})\n\n{description}\n\n"
            f"`{language}` · `★ {stars}` · "
            f"Last code push: **{parse_date(latest.get('pushed_at'))}**"
        )
    else:
        latest_content = "_No eligible public repository activity was found._"

    refreshed = datetime.now(timezone.utc).strftime("%d %b %Y · %H:%M UTC")
    return (
        "## 01 / FEATURED CASE FILES\n\n"
        "Curated projects selected for inspection.\n\n"
        f"{featured_content}\n\n"
        "## 02 / LATEST SIGNAL\n\n"
        "The most recently pushed eligible public repository.\n\n"
        f"{latest_content}\n\n"
        f"<sub>INDEX REFRESHED: {refreshed} · SOURCE: PUBLIC GITHUB REPOSITORY METADATA</sub>"
    )


def replace_marked_section(original: str, generated: str) -> str:
    """Replace exactly one well-formed marker pair; otherwise fail without writing."""
    if original.count(START) != 1 or original.count(END) != 1:
        raise ValueError("README must contain exactly one DOSSIER:START and DOSSIER:END marker.")
    start = original.index(START)
    end = original.index(END)
    if end <= start:
        raise ValueError("README dossier markers are malformed or out of order.")
    after_marker = end + len(END)
    return original[:start] + START + "\n" + generated + "\n" + END + original[after_marker:]


def generate_banner() -> None:
    """Create a restrained looping terminal banner using Pillow."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise RuntimeError("Pillow is required to generate assets/signal.gif.") from exc

    GIF.parent.mkdir(parents=True, exist_ok=True)
    width, height = 960, 250
    frames = []
    try:
        title_font = ImageFont.truetype("DejaVuSansMono-Bold.ttf", 43)
        body_font = ImageFont.truetype("DejaVuSansMono.ttf", 15)
        small_font = ImageFont.truetype("DejaVuSansMono.ttf", 11)
    except OSError:
        title_font = body_font = small_font = ImageFont.load_default()

    for frame in range(36):
        image = Image.new("RGB", (width, height), (9, 13, 16))
        draw = ImageDraw.Draw(image)
        for x in range(0, width, 40):
            draw.line((x, 0, x, height), fill=(18, 27, 29), width=1)
        for y in range(0, height, 40):
            draw.line((0, y, width, y), fill=(18, 27, 29), width=1)
        draw.rectangle((22, 20, width - 22, height - 20), outline=(43, 70, 65), width=1)
        draw.text((48, 39), "FIELD NOTES / ENGINEERING LOG", font=body_font, fill=(117, 153, 141))
        draw.text((48, 79), "NAVANEETHAN", font=title_font, fill=(225, 235, 229))
        draw.text((51, 143), "IDENTITY: UNCLASSIFIED", font=body_font, fill=(104, 211, 158))
        draw.text((51, 178), "NO FIXED DOMAIN // ONLY THE NEXT PROBLEM", font=small_font, fill=(135, 151, 148))
        scan_x = 48 + ((frame * 23) % 860)
        draw.line((scan_x, 29, scan_x, height - 30), fill=(69, 180, 139), width=2)
        draw.line((scan_x - 7, 29, scan_x - 7, height - 30), fill=(29, 77, 64), width=1)
        pulse = (104, 211, 158) if frame % 18 < 9 else (48, 91, 75)
        draw.ellipse((width - 77, 43, width - 65, 55), fill=pulse)
        draw.text((width - 57, 40), "LIVE", font=small_font, fill=(135, 166, 151))
        frames.append(image)

    frames[0].save(
        GIF, save_all=True, append_images=frames[1:], duration=100,
        loop=0, optimize=True, disposal=2
    )


def main() -> int:
    try:
        config = load_config()
        # Validate markers before network access or asset generation.
        original = README.read_text(encoding="utf-8")
        if original.count(START) != 1 or original.count(END) != 1:
            raise ValueError("README must contain exactly one correctly ordered marker pair.")
        if original.index(END) <= original.index(START):
            raise ValueError("README dossier markers are malformed or out of order.")
        generated = build_dynamic_section(config)
        updated = replace_marked_section(original, generated)
        generate_banner()
        README.write_text(updated, encoding="utf-8")
        print("Dossier README and banner generated successfully.")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
