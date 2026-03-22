from __future__ import annotations

import re
from urllib.parse import quote_plus

from .base import MarketplaceClient, MarketplaceError
from ..models import Marketplace, Offer
from ..query_profiles import build_page_url, clean_marketplace_url, deduplicate_offers, get_overridden_url, title_matches_query

_PRICE_RE = re.compile(r'(\d[\d\s\u2009]{2,12})\s?[₽р]')


class WildberriesClient(MarketplaceClient):
    marketplace = Marketplace.WB

    async def search(self, query: str) -> list[Offer]:
        base_url = get_overridden_url(query, self.marketplace.value) or (
            f"https://www.wildberries.ru/catalog/0/search.aspx?search={quote_plus(query)}"
        )
        offers: list[Offer] = []
        for page_num in range(1, self._max_pages + 1):
            url = build_page_url(base_url, page_num)
            page, context = await self._load_page(url)
            try:
                await self._safe_scroll(page)
                cards = await page.evaluate(
                    """
                    () => Array.from(document.querySelectorAll('article, .product-card, .j-card-item'))
                      .slice(0, 120)
                      .map((card) => {
                        const anchor = card.querySelector("a[href*='/catalog/'][href*='detail.aspx']");
                        const img = card.querySelector('img');
                        return {
                          href: anchor?.href || null,
                          title: (anchor?.getAttribute('aria-label') || img?.getAttribute('alt') || '').trim(),
                          text: (card.innerText || '').trim(),
                        };
                      })
                    """
                )
            finally:
                await self._browser.close_context(context)

            page_offers = self._extract_cards(cards, query)
            if not page_offers:
                break
            offers.extend(page_offers)

        offers = deduplicate_offers(offers)
        if not offers:
            raise MarketplaceError("Wildberries returned no parsable offers")
        return offers

    def _extract_cards(self, cards: list[dict], query: str) -> list[Offer]:
        offers: list[Offer] = []
        for card in cards:
            href = self._clean_text(card.get('href'))
            title = self._clean_text(card.get('title'))
            text = self._clean_text(card.get('text'))
            if not href or not title or not title_matches_query(title, query):
                continue
            if self._looks_unavailable(text):
                continue
            price = self._extract_price(text)
            if price is None:
                continue
            offers.append(
                Offer(
                    marketplace=self.marketplace,
                    title=title,
                    price=price,
                    currency='RUB',
                    url=clean_marketplace_url(href, self.marketplace.value),
                )
            )
        return offers

    def _extract_price(self, text: str) -> float | None:
        candidates: list[float] = []
        for line in text.splitlines():
            normalized = self._clean_text(line).replace('\u2009', ' ')
            lowered = normalized.lower()
            if not normalized or '₽' not in normalized:
                continue
            if normalized.startswith('+') or 'отзыв' in lowered or 'оцен' in lowered:
                continue
            for match in _PRICE_RE.finditer(normalized):
                value = match.group(1).replace(' ', '').replace('\u2009', '')
                try:
                    price = float(value)
                except ValueError:
                    continue
                if price >= 500:
                    candidates.append(price)
        return min(candidates) if candidates else None


    def _looks_unavailable(self, text: str) -> bool:
        lowered = self._clean_text(text).lower()
        markers = (
            "\u043d\u0435\u0442 \u0432 \u043d\u0430\u043b\u0438\u0447\u0438\u0438",
            "\u0437\u0430\u043a\u043e\u043d\u0447\u0438\u043b\u0441\u044f",
            "\u0441\u043a\u043e\u0440\u043e \u0437\u0430\u043a\u043e\u043d\u0447\u0438\u0442\u0441\u044f",
            "\u0443\u0432\u0435\u0434\u043e\u043c\u0438\u0442\u044c \u043e \u043f\u043e\u0441\u0442\u0443\u043f\u043b\u0435\u043d\u0438\u0438",
            "\u043d\u0435\u0442 \u0434\u043e\u0441\u0442\u0430\u0432\u043a\u0438",
            "\u0440\u0430\u0441\u043f\u0440\u043e\u0434\u0430\u043d",
        )
        return any(marker in lowered for marker in markers)
