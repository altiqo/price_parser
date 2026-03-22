from __future__ import annotations

import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from .models import Offer

TRACKED_QUERY_URLS: dict[str, dict[str, str]] = {}

_STOP_WORDS = {
    "роутер", "router", "маршрутизатор", "wi", "fi", "wifi", "гигабитный", "двухдиапазонный"
}


def normalize_text(value: str) -> str:
    lowered = value.casefold().replace("ё", "е")
    lowered = re.sub(r"[^a-z0-9а-я]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def build_page_url(base_url: str, page: int, page_param: str = "page") -> str:
    parsed = urlparse(base_url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query[page_param] = [str(page)]
    encoded = urlencode(query, doseq=True)
    return urlunparse(parsed._replace(query=encoded))


def get_overridden_url(query: str, marketplace: str) -> str | None:
    return TRACKED_QUERY_URLS.get(normalize_text(query), {}).get(marketplace)


def query_tokens(query: str) -> list[str]:
    tokens = [token for token in normalize_text(query).split() if token and token not in _STOP_WORDS]
    compact = []
    for token in tokens:
        if token not in compact:
            compact.append(token)
    return compact


def query_model_tokens(query: str) -> list[str]:
    return [token for token in query_tokens(query) if any(char.isdigit() for char in token)]


def title_matches_query(title: str, query: str) -> bool:
    normalized_title = normalize_text(title)
    tokens = query_tokens(query)
    if not tokens:
        return False
    return all(token in normalized_title for token in tokens)


def url_matches_query_model(url: str, query: str) -> bool:
    normalized_url = normalize_text(url)
    model_tokens = query_model_tokens(query)
    if not model_tokens:
        return True
    return all(token in normalized_url for token in model_tokens)


def deduplicate_offers(offers: list[Offer]) -> list[Offer]:
    seen: set[tuple[str, str]] = set()
    unique: list[Offer] = []
    for offer in sorted(offers, key=lambda item: item.price):
        key = (offer.marketplace.value, offer.url)
        if key in seen:
            continue
        seen.add(key)
        unique.append(offer)
    return unique



def clean_marketplace_url(url: str, marketplace: str) -> str:
    parsed = urlparse(url)
    if marketplace == "ozon":
        return urlunparse(parsed._replace(query="", fragment=""))
    if marketplace == "yandex_market":
        allowed = {"hid", "nid"}
        query = parse_qs(parsed.query, keep_blank_values=True)
        cleaned = {key: value for key, value in query.items() if key in allowed}
        encoded = urlencode(cleaned, doseq=True)
        return urlunparse(parsed._replace(query=encoded, fragment=""))
    if marketplace == "wb":
        return urlunparse(parsed._replace(query="", fragment=""))
    return url
