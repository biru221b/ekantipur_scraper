from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Locator,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

BASE_URL = "https://ekantipur.com"
ENTERTAINMENT_URL = urljoin(BASE_URL, "/entertainment")
CARTOON_URL = urljoin(BASE_URL, "/cartoon")
OUTPUT_PATH = Path(__file__).with_name("output.json")
DEFAULT_TIMEOUT_MS = 15_000

ENTERTAINMENT_LINK_SELECTOR = (
    "body > header > div > div.bottom-nav > "
    "div.bottom-nav-inside-wrapper > div > a:nth-child(5)"
)
ENTERTAINMENT_CARD_SELECTOR = ".category-main-wrapper > .category-wrapper > .category"
ENTERTAINMENT_TITLE_SELECTOR = ".category-description h2 a"
ENTERTAINMENT_AUTHOR_SELECTOR = ".category-description .author-name"
ENTERTAINMENT_IMAGE_SELECTOR = ".category-image img"
ENTERTAINMENT_CATEGORY = "मनोरञ्जन"

CARTOON_PAGE_MARKER_SELECTOR = "body > header > div > div.logo > div.category-name > p > a"
CARTOON_CARD_SELECTOR = ".cartoon-main-wrapper .cartoon-wrapper"
CARTOON_TEXT_SELECTOR = ".cartoon-description > p"
CARTOON_IMAGE_SELECTOR = ".cartoon-image img"


def launch_browser(playwright: Playwright) -> tuple[Browser, BrowserContext, Page]:
    """Launch Chromium and return a configured page for scraping."""
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
        locale="ne-NP",
        viewport={"width": 1440, "height": 960},
    )
    page = context.new_page()
    page.set_default_timeout(DEFAULT_TIMEOUT_MS)
    return browser, context, page


def safe_text(locator: Locator) -> str | None:
    """Return stripped text from the first matched element, or None."""
    if locator.count() == 0:
        return None

    text = locator.first.inner_text().strip()
    return text or None


def safe_attribute(locator: Locator, name: str) -> str | None:
    """Return a stripped attribute from the first matched element, or None."""
    if locator.count() == 0:
        return None

    value = locator.first.get_attribute(name)
    return value.strip() if value else None


def normalize_url(value: str | None) -> str | None:
    """Convert relative or protocol-relative URLs to absolute URLs."""
    if not value:
        return None

    cleaned = value.strip()
    if not cleaned:
        return None

    if cleaned.startswith("//"):
        return f"https:{cleaned}"

    return urljoin(BASE_URL, cleaned)


def extract_image_url(image_locator: Locator) -> str | None:
    """Read the most likely image source from common image attributes."""
    for attribute in ("data-src", "data-lazy-src"):
        value = safe_attribute(image_locator, attribute)
        if value:
            return normalize_url(value)

    srcset = safe_attribute(image_locator, "srcset")
    if srcset:
        first_candidate = srcset.split(",")[0].strip().split(" ")[0]
        return normalize_url(first_candidate)

    return normalize_url(safe_attribute(image_locator, "src"))


def go_to_entertainment_section(page: Page) -> None:
    """Open Ekantipur and navigate to the entertainment category page."""
    page.goto(BASE_URL, wait_until="domcontentloaded")

    # Wait for the header nav before reading its href or clicking it.
    entertainment_link = page.locator(ENTERTAINMENT_LINK_SELECTOR)
    entertainment_link.first.wait_for(state="visible")

    href = normalize_url(safe_attribute(entertainment_link, "href"))
    if href:
        page.goto(href, wait_until="domcontentloaded")
    else:
        # Fallback to a direct route if the link href is not available.
        page.goto(ENTERTAINMENT_URL, wait_until="domcontentloaded")

    # The outer card selector is broad, so wait on one concrete title element.
    page.locator(ENTERTAINMENT_CARD_SELECTOR).locator(
        ENTERTAINMENT_TITLE_SELECTOR
    ).first.wait_for(state="visible")


def extract_top_entertainment_news(page: Page, limit: int = 5) -> list[dict[str, Any]]:
    """Extract the first few entertainment article cards from the category page."""
    cards = page.locator(ENTERTAINMENT_CARD_SELECTOR)
    articles: list[dict[str, Any]] = []

    for index in range(cards.count()):
        if len(articles) >= limit:
            break

        card = cards.nth(index)
        title = safe_text(card.locator(ENTERTAINMENT_TITLE_SELECTOR))
        if not title:
            continue

        articles.append(
            {
                "title": title,
                "image_url": extract_image_url(card.locator(ENTERTAINMENT_IMAGE_SELECTOR)),
                "category": ENTERTAINMENT_CATEGORY,
                "author": safe_text(card.locator(ENTERTAINMENT_AUTHOR_SELECTOR)),
            }
        )

    return articles


def extract_cartoon_of_the_day(page: Page) -> dict[str, str | None]:
    """Open the cartoon page and extract its title, image, and author."""
    try:
        page.goto(CARTOON_URL, wait_until="domcontentloaded")

        # Wait for the page marker so we know the cartoon page header rendered.
        page.locator(CARTOON_PAGE_MARKER_SELECTOR).first.wait_for(state="visible")

        # Wait for the first cartoon card because the page contains many cartoons.
        page.locator(CARTOON_CARD_SELECTOR).first.wait_for(state="visible")
    except PlaywrightTimeoutError:
        return {
            "title": None,
            "image_url": None,
            "author": None,
        }

    cartoon_card = page.locator(CARTOON_CARD_SELECTOR).first
    title, author = split_cartoon_text(safe_text(cartoon_card.locator(CARTOON_TEXT_SELECTOR)))
    return {
        "title": title,
        "image_url": extract_image_url(cartoon_card.locator(CARTOON_IMAGE_SELECTOR)),
        "author": author,
    }


def split_cartoon_text(text: str | None) -> tuple[str | None, str | None]:
    """Split a cartoon label like 'title - author' into separate fields."""
    if not text:
        return None, None

    cleaned = text.strip()
    if not cleaned:
        return None, None

    if " - " in cleaned:
        title, author = cleaned.rsplit(" - ", 1)
        return title.strip() or None, author.strip() or None

    return cleaned, None


def write_output(payload: dict[str, Any], output_path: Path = OUTPUT_PATH) -> None:
    """Write the final JSON payload to disk using UTF-8."""
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    with sync_playwright() as playwright:
        browser, context, page = launch_browser(playwright)
        try:
            go_to_entertainment_section(page)

            payload = {
                "entertainment_news": extract_top_entertainment_news(page, limit=5),
                "cartoon_of_the_day": extract_cartoon_of_the_day(page),
            }
            write_output(payload)
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
