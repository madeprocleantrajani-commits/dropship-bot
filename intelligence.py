"""
Unified Intelligence Engine v2
-------------------------------
The brain — combines data from ALL bots into a single intelligence
layer that scores, ranks, and cross-references products.

v2 data sources:
  - Google Trends      (demand signals, rising queries)
  - Amazon BSR         (market validation, movers, BSR history)
  - Amazon Demand      (autocomplete = real buyer search intent)
  - AliExpress         (supply pricing, order counts)
  - eBay Sold          (actual transaction validation)
  - Competitors        (competitive landscape)
  - Price Monitor      (tracking active products)

v2 filters:
  - Physical products only (no digital/subscriptions)
  - Brand flagging (major brands marked non-dropshippable)
  - EUR→USD conversion for Ireland VPS

Outputs: data/analysis_YYYY-MM-DD.json
"""

import json
import glob
import re
from datetime import datetime

from config import (
    DATA_DIR, SEED_KEYWORDS, get_logger,
    is_physical_product, is_major_brand, parse_price, to_usd,
)

log = get_logger("intelligence")


# ── Utilities ──────────────────────────────────────────────


def load_latest_json(prefix: str) -> dict | None:
    """Load the most recent JSON data file with given prefix."""
    pattern = str(DATA_DIR / f"{prefix}_*.json")
    files = sorted(glob.glob(pattern), reverse=True)
    if not files:
        return None
    try:
        with open(files[0]) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        log.error(f"Failed to load {files[0]}: {e}")
        return None


def load_discovered_competitors() -> dict | None:
    """Load auto-discovered competitor stores."""
    path = DATA_DIR / "competitors_discovered.json"
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def keyword_in_title(keyword: str, title: str) -> bool:
    """Check if a keyword appears in a product title."""
    kw_lower = keyword.lower()
    title_lower = title.lower()
    if kw_lower in title_lower:
        return True
    kw_words = [w for w in kw_lower.split() if len(w) > 2]
    if len(kw_words) >= 2:
        matches = sum(1 for w in kw_words if w in title_lower)
        if matches >= len(kw_words) * 0.7:
            return True
    return False


# ── Main Engine ────────────────────────────────────────────


class DropshipIntelligence:
    """Scores, ranks, and cross-references products from all sources."""

    def __init__(self):
        self.trends = None
        self.amazon = None
        self.aliexpress = None
        self.competitors = None
        self.discovered_competitors = None
        self.prices = None
        self.demand = None
        self.ebay = None

    def load_all(self):
        """Load latest data from every source."""
        self.trends = load_latest_json("trends")
        self.amazon = load_latest_json("amazon")
        self.aliexpress = load_latest_json("aliexpress")
        self.competitors = load_latest_json("competitors")
        self.discovered_competitors = load_discovered_competitors()
        self.prices = load_latest_json("prices")
        self.demand = load_latest_json("demand")
        self.ebay = load_latest_json("ebay")

        sources = [self.trends, self.amazon, self.aliexpress,
                    self.competitors, self.prices, self.demand, self.ebay]
        active = sum(1 for d in sources if d)
        log.info(
            f"Data loaded — {active}/7 sources | "
            f"Trends:{'Y' if self.trends else 'N'} "
            f"Amazon:{'Y' if self.amazon else 'N'} "
            f"AliEx:{'Y' if self.aliexpress else 'N'} "
            f"Demand:{'Y' if self.demand else 'N'} "
            f"eBay:{'Y' if self.ebay else 'N'} "
            f"Comp:{'Y' if self.competitors or self.discovered_competitors else 'N'} "
            f"Price:{'Y' if self.prices else 'N'}"
        )

    # ── Data Source Status ────────────────────────────────

    def data_sources_status(self) -> dict:
        has_trend_data = bool(
            self.trends and (
                self.trends.get("hot_products") or
                any(n.get("keywords") for n in self.trends.get("niches", {}).values())
            )
        )
        has_demand = bool(
            self.demand and self.demand.get("stats", {}).get("total_unique_suggestions", 0) > 0
        )
        has_ebay = bool(
            self.ebay and self.ebay.get("stats", {}).get("total_sold_found", 0) > 0
        )
        has_competitors = bool(
            (self.competitors and self.competitors.get("stores")) or
            (self.discovered_competitors and self.discovered_competitors.get("stores"))
        )

        return {
            "trends": {
                "active": has_trend_data,
                "hot_products": len(self.trends.get("hot_products", [])) if self.trends else 0,
                "discoveries": len(self.trends.get("discoveries", [])) if self.trends else 0,
            },
            "amazon": {
                "active": bool(self.amazon and self.amazon.get("total_products_scanned", 0) > 0),
                "products": self.amazon.get("total_products_scanned", 0) if self.amazon else 0,
                "movers": self.amazon.get("total_movers_found", 0) if self.amazon else 0,
                "has_bsr_history": self.amazon.get("has_bsr_history", False) if self.amazon else False,
            },
            "demand": {
                "active": has_demand,
                "suggestions": self.demand.get("stats", {}).get("total_unique_suggestions", 0) if self.demand else 0,
                "discoveries": self.demand.get("stats", {}).get("new_discoveries", 0) if self.demand else 0,
            },
            "ebay": {
                "active": has_ebay,
                "total_sold": self.ebay.get("stats", {}).get("total_sold_found", 0) if self.ebay else 0,
                "keywords_with_sales": self.ebay.get("stats", {}).get("keywords_with_sales", 0) if self.ebay else 0,
            },
            "aliexpress": {
                "active": bool(self.aliexpress and self.aliexpress.get("total_products_found", 0) > 0),
                "products": self.aliexpress.get("total_products_found", 0) if self.aliexpress else 0,
            },
            "competitors": {
                "active": has_competitors,
                "stores": (
                    len(self.discovered_competitors.get("stores", {}))
                    if self.discovered_competitors
                    else len(self.competitors.get("stores", {})) if self.competitors else 0
                ),
            },
            "prices": {
                "active": bool(self.prices and self.prices.get("current_prices")),
                "tracked": len(self.prices.get("current_prices", {})) if self.prices else 0,
            },
        }

    # ── Amazon Analysis ───────────────────────────────────

    def analyze_amazon(self) -> dict:
        if not self.amazon:
            return {"status": "no_data"}

        analysis = {
            "categories": {},
            "movers": [],
            "dropship_candidates": [],
            "price_distribution": {},
            "rising_products": [],
        }

        all_prices = []

        for cat_name, products in self.amazon.get("best_sellers", {}).items():
            cat = {
                "total": len(products), "products": [], "top_5": [],
                "avg_price": 0, "price_range": {"min": None, "max": None},
                "avg_rating": 0,
            }
            prices, ratings = [], []

            for i, p in enumerate(products):
                price_eur = p.get("price_eur") or parse_price(p.get("price_raw", ""))
                price_usd = p.get("price_usd") or to_usd(price_eur)
                rating = p.get("rating")
                if rating is None and p.get("rating_raw"):
                    try:
                        rating = float(str(p["rating_raw"]).split()[0])
                    except (ValueError, IndexError):
                        pass

                info = {
                    "rank": p.get("rank", i + 1),
                    "title": p.get("title", "Unknown"),
                    "price_eur": price_eur,
                    "price_usd": price_usd,
                    "rating": rating,
                    "review_count": p.get("review_count"),
                    "asin": p.get("asin", ""),
                    "url": p.get("url", ""),
                    "category": cat_name,
                    "is_brand": p.get("is_brand", False),
                    "rank_direction": p.get("rank_direction"),
                    "rank_change": p.get("rank_change"),
                    "rank_yesterday": p.get("rank_yesterday"),
                }
                cat["products"].append(info)
                if i < 5:
                    cat["top_5"].append(info)
                if price_usd:
                    prices.append(price_usd)
                    all_prices.append(price_usd)
                if rating:
                    ratings.append(rating)

                # Dropship candidates: $10-$60, physical, not a major brand
                if (price_usd and 10 <= price_usd <= 60
                        and not p.get("is_brand", False)
                        and (rating is None or rating >= 4.0)):
                    info["dropship_score"] = self._score_candidate(info)
                    analysis["dropship_candidates"].append(info)

                # Rising products (BSR improved)
                if p.get("rank_direction") == "up" and p.get("rank_change", 0) >= 3:
                    analysis["rising_products"].append(info)

            if prices:
                cat["avg_price"] = round(sum(prices) / len(prices), 2)
                cat["price_range"] = {
                    "min": round(min(prices), 2),
                    "max": round(max(prices), 2),
                }
            if ratings:
                cat["avg_rating"] = round(sum(ratings) / len(ratings), 1)

            analysis["categories"][cat_name] = cat

        # Movers
        for cat_name, movers in self.amazon.get("movers_and_shakers", {}).items():
            for m in movers:
                price_eur = m.get("price_eur") or parse_price(m.get("price_raw", ""))
                analysis["movers"].append({
                    "title": m.get("title", "Unknown"),
                    "price_usd": m.get("price_usd") or to_usd(price_eur),
                    "category": cat_name,
                    "asin": m.get("asin", ""),
                    "is_brand": m.get("is_brand", False),
                    "rank_change": m.get("rank_change", ""),
                })

        analysis["dropship_candidates"].sort(
            key=lambda x: x.get("dropship_score", 0), reverse=True
        )

        if all_prices:
            analysis["price_distribution"] = {
                "under_10": sum(1 for p in all_prices if p < 10),
                "10_to_25": sum(1 for p in all_prices if 10 <= p < 25),
                "25_to_50": sum(1 for p in all_prices if 25 <= p < 50),
                "50_to_100": sum(1 for p in all_prices if 50 <= p < 100),
                "over_100": sum(1 for p in all_prices if p >= 100),
                "total": len(all_prices),
                "avg": round(sum(all_prices) / len(all_prices), 2),
                "median": round(sorted(all_prices)[len(all_prices) // 2], 2),
            }

        return analysis

    def _score_candidate(self, product: dict) -> int:
        """Score a product 0-100 for dropshipping potential."""
        score = 40

        price = product.get("price_usd") or 0
        rating = product.get("rating") or 0
        rank = product.get("rank", 999)
        reviews = product.get("review_count") or 0

        # Price sweet spot ($15-$40 ideal for dropshipping)
        if 15 <= price <= 40:
            score += 12
        elif 10 <= price <= 60:
            score += 6

        # Rank (lower = better)
        if rank <= 5:
            score += 15
        elif rank <= 10:
            score += 12
        elif rank <= 20:
            score += 8
        elif rank <= 30:
            score += 4

        # Rating
        if rating >= 4.5:
            score += 10
        elif rating >= 4.0:
            score += 6

        # Review count (social proof)
        if reviews >= 10000:
            score += 8
        elif reviews >= 1000:
            score += 5
        elif reviews >= 100:
            score += 2

        # BSR rising
        if product.get("rank_direction") == "up":
            change = product.get("rank_change", 0)
            if change >= 10:
                score += 10
            elif change >= 5:
                score += 6
            elif change >= 1:
                score += 3

        # Cross-source bonuses
        title_lower = product.get("title", "").lower()

        # Seed keyword match
        for keywords in SEED_KEYWORDS.values():
            for kw in keywords:
                if keyword_in_title(kw, title_lower):
                    score += 5
                    break

        # eBay sold validation
        if self.ebay:
            for kw, data in self.ebay.get("results", {}).items():
                if keyword_in_title(kw, title_lower):
                    sold = data.get("sold_count", 0)
                    if sold >= 100:
                        score += 10
                    elif sold >= 20:
                        score += 5
                    break

        # Amazon demand (autocomplete) validation
        if self.demand:
            for kw, data in self.demand.get("keywords", {}).items():
                if keyword_in_title(kw, title_lower):
                    score += 5  # Confirmed search demand
                    break

        # Google trending
        if self.trends:
            for hp in self.trends.get("hot_products", []):
                if keyword_in_title(hp["keyword"], title_lower):
                    score += 8
                    break

        # AliExpress source available
        if self.aliexpress:
            for kw, ali_prods in self.aliexpress.get("results", {}).items():
                if keyword_in_title(kw, title_lower) and ali_prods:
                    cheapest = min(
                        (p["price_usd"] for p in ali_prods if p.get("price_usd")),
                        default=0,
                    )
                    if cheapest and price and cheapest < price * 0.35:
                        score += 10  # Great margin
                    elif cheapest and price and cheapest < price * 0.5:
                        score += 5  # Decent margin
                    break

        return min(score, 100)

    # ── Demand Analysis ───────────────────────────────────

    def analyze_demand(self) -> dict:
        if not self.demand:
            return {"status": "no_data"}

        return {
            "keywords_scanned": self.demand.get("stats", {}).get("keywords_scanned", 0),
            "total_suggestions": self.demand.get("stats", {}).get("total_unique_suggestions", 0),
            "new_discoveries": self.demand.get("stats", {}).get("new_discoveries", 0),
            "top_discoveries": self.demand.get("top_discoveries", [])[:20],
            "keywords": {
                kw: {
                    "base_count": len(data.get("base_suggestions", [])),
                    "expanded_count": len(data.get("expanded_suggestions", [])),
                    "total_ideas": data.get("total_ideas", 0),
                    "top_suggestions": data.get("base_suggestions", [])[:5],
                }
                for kw, data in self.demand.get("keywords", {}).items()
            },
        }

    # ── eBay Analysis ─────────────────────────────────────

    def analyze_ebay(self) -> dict:
        if not self.ebay:
            return {"status": "no_data"}

        return {
            "keywords_scanned": self.ebay.get("keywords_scanned", 0),
            "total_sold": self.ebay.get("stats", {}).get("total_sold_found", 0),
            "keywords_with_sales": self.ebay.get("stats", {}).get("keywords_with_sales", 0),
            "top_sellers": self.ebay.get("top_sellers", [])[:15],
            "price_insights": self.ebay.get("price_insights", [])[:10],
            "results": {
                kw: {
                    "sold_count": data.get("sold_count", 0),
                    "avg_price": data.get("price_analysis", {}).get("avg", 0),
                    "median_price": data.get("price_analysis", {}).get("median", 0),
                    "price_range": (
                        f"${data.get('price_analysis', {}).get('min', 0):.2f}–"
                        f"${data.get('price_analysis', {}).get('max', 0):.2f}"
                        if data.get("price_analysis", {}).get("min") else "N/A"
                    ),
                }
                for kw, data in self.ebay.get("results", {}).items()
            },
        }

    # ── Trends / AliExpress / Competitors / Prices ────────

    def analyze_trends(self) -> dict:
        if not self.trends:
            return {"status": "no_data"}
        analysis = {
            "hot_products": self.trends.get("hot_products", []),
            "discoveries": self.trends.get("discoveries", []),
            "niches": {},
        }
        for niche_name, niche_data in self.trends.get("niches", {}).items():
            keywords = niche_data.get("keywords", {})
            if not keywords:
                analysis["niches"][niche_name] = {"status": "no_data", "keywords": {}}
                continue
            niche_analysis = {
                "keywords": {}, "rising_count": 0, "avg_interest": 0,
                "best_keyword": None, "best_interest": 0,
            }
            interests = []
            for kw, data in keywords.items():
                kw_info = {
                    "current": data.get("current", 0),
                    "avg": data.get("avg", 0),
                    "trend": data.get("trend", "unknown"),
                    "momentum": data.get("current", 0) - data.get("avg", 0),
                }
                niche_analysis["keywords"][kw] = kw_info
                interests.append(data.get("current", 0))
                if data.get("trend") == "rising":
                    niche_analysis["rising_count"] += 1
                if data.get("current", 0) > niche_analysis["best_interest"]:
                    niche_analysis["best_interest"] = data["current"]
                    niche_analysis["best_keyword"] = kw
            if interests:
                niche_analysis["avg_interest"] = round(sum(interests) / len(interests), 1)
            analysis["niches"][niche_name] = niche_analysis
        return analysis

    def analyze_aliexpress(self) -> dict:
        if not self.aliexpress:
            return {"status": "no_data"}
        total = self.aliexpress.get("total_products_found", 0)
        return {
            "keywords_scanned": self.aliexpress.get("keywords_scanned", 0),
            "total_products": total,
            "best_deals": self.aliexpress.get("best_deals", []),
            "by_keyword": {
                kw: {
                    "total": len(prods),
                    "avg_price": round(
                        sum(p["price_usd"] for p in prods if p.get("price_usd"))
                        / max(1, sum(1 for p in prods if p.get("price_usd"))), 2
                    ) if prods else 0,
                    "top_3": prods[:3],
                }
                for kw, prods in self.aliexpress.get("results", {}).items()
                if prods
            },
        }

    def analyze_competitors(self) -> dict:
        # Combine tracked + discovered competitors
        stores = {}
        if self.competitors and self.competitors.get("stores"):
            stores.update(self.competitors["stores"])
        if self.discovered_competitors and self.discovered_competitors.get("stores"):
            stores.update(self.discovered_competitors["stores"])
        if not stores:
            return {"status": "no_data"}
        return {"stores": stores, "total": len(stores)}

    def analyze_prices(self) -> dict:
        if not self.prices:
            return {"status": "no_data"}
        return {
            "alerts": self.prices.get("alerts", []),
            "current_prices": self.prices.get("current_prices", {}),
        }

    # ── Cross-Reference Engine ────────────────────────────

    def cross_reference(self) -> list[dict]:
        """Find products validated across multiple data sources."""
        cross_refs = []
        if not self.amazon:
            return cross_refs

        for cat_name, products in self.amazon.get("best_sellers", {}).items():
            for product in products:
                title = product.get("title", "")
                price_usd = product.get("price_usd") or to_usd(
                    product.get("price_eur") or parse_price(product.get("price_raw", ""))
                )

                ref = {
                    "title": title,
                    "amazon_rank": product.get("rank"),
                    "amazon_price_usd": price_usd,
                    "amazon_category": cat_name,
                    "amazon_rating": product.get("rating"),
                    "review_count": product.get("review_count"),
                    "is_brand": product.get("is_brand", False),
                    "rank_direction": product.get("rank_direction"),
                    "signals": ["amazon_bestseller"],
                    "signal_count": 1,
                }

                # Amazon mover?
                for movers in self.amazon.get("movers_and_shakers", {}).values():
                    for m in movers:
                        if m.get("asin") == product.get("asin"):
                            ref["signals"].append("amazon_mover")
                            ref["signal_count"] += 1
                            break

                # Seed keyword match?
                for niche, keywords in SEED_KEYWORDS.items():
                    for kw in keywords:
                        if keyword_in_title(kw, title):
                            ref["matched_niche"] = niche
                            ref["matched_keyword"] = kw
                            ref["signals"].append("seed_keyword")
                            ref["signal_count"] += 1
                            break
                    if ref.get("matched_niche"):
                        break

                # eBay sold validation?
                if self.ebay:
                    for kw, data in self.ebay.get("results", {}).items():
                        if keyword_in_title(kw, title) and data.get("sold_count", 0) > 0:
                            ref["signals"].append("ebay_validated")
                            ref["ebay_sold"] = data["sold_count"]
                            ref["ebay_avg_price"] = data.get("price_analysis", {}).get("avg", 0)
                            ref["signal_count"] += 1
                            break

                # Amazon demand (autocomplete)?
                if self.demand:
                    for kw in self.demand.get("keywords", {}):
                        if keyword_in_title(kw, title):
                            ref["signals"].append("search_demand")
                            ref["signal_count"] += 1
                            break

                # Google trending?
                if self.trends:
                    for hp in self.trends.get("hot_products", []):
                        if keyword_in_title(hp["keyword"], title):
                            ref["signals"].append("google_trending")
                            ref["trend_interest"] = hp.get("current_interest", 0)
                            ref["signal_count"] += 1
                            break

                # AliExpress source?
                if self.aliexpress:
                    for kw, ali_prods in self.aliexpress.get("results", {}).items():
                        if keyword_in_title(kw, title) and ali_prods:
                            cheapest = min(
                                (p["price_usd"] for p in ali_prods if p.get("price_usd")),
                                default=0,
                            )
                            if cheapest:
                                ref["signals"].append("aliexpress_sourced")
                                ref["source_price"] = cheapest
                                ref["signal_count"] += 1
                                if price_usd and cheapest > 0:
                                    ref["margin_pct"] = round(
                                        (price_usd - cheapest) / price_usd * 100, 1
                                    )
                            break

                if ref["signal_count"] >= 2:
                    cross_refs.append(ref)

        cross_refs.sort(key=lambda x: (-x["signal_count"], x.get("amazon_rank", 999)))
        return cross_refs

    # ── Niche Scoring ─────────────────────────────────────

    def score_niches(self) -> dict:
        niche_scores = {}

        for niche_name, keywords in SEED_KEYWORDS.items():
            ns = {
                "name": niche_name,
                "trend_score": 0,
                "demand_score": 0,
                "source_score": 0,
                "validation_score": 0,
                "total": 0,
                "grade": "?",
            }

            # Trend (0-25)
            if self.trends:
                for kw in keywords:
                    for hp in self.trends.get("hot_products", []):
                        if hp["keyword"] == kw:
                            ns["trend_score"] += 5
                    for nd in self.trends.get("niches", {}).values():
                        kd = nd.get("keywords", {}).get(kw)
                        if kd and kd.get("trend") == "rising":
                            ns["trend_score"] += 3
            ns["trend_score"] = min(ns["trend_score"], 25)

            # Demand — Amazon BSR + autocomplete + eBay (0-25)
            if self.amazon:
                for prods in self.amazon.get("best_sellers", {}).values():
                    for p in prods:
                        for kw in keywords:
                            if keyword_in_title(kw, p.get("title", "")):
                                rank = p.get("rank", 30)
                                ns["demand_score"] += max(0, 6 - rank // 5)
                                break
            if self.demand:
                for kw in keywords:
                    kd = self.demand.get("keywords", {}).get(kw)
                    if kd and kd.get("total_ideas", 0) > 10:
                        ns["demand_score"] += 3
            ns["demand_score"] = min(ns["demand_score"], 25)

            # Source (0-25) — AliExpress
            if self.aliexpress:
                for kw in keywords:
                    prods = self.aliexpress.get("results", {}).get(kw, [])
                    if prods:
                        ns["source_score"] += 5
                        cheapest = min(
                            (p["price_usd"] for p in prods if p.get("price_usd")),
                            default=99,
                        )
                        if cheapest < 10:
                            ns["source_score"] += 5
            ns["source_score"] = min(ns["source_score"], 25)

            # Validation (0-25) — eBay sold
            if self.ebay:
                for kw in keywords:
                    ed = self.ebay.get("results", {}).get(kw, {})
                    sold = ed.get("sold_count", 0)
                    if sold >= 100:
                        ns["validation_score"] += 8
                    elif sold >= 20:
                        ns["validation_score"] += 4
                    elif sold > 0:
                        ns["validation_score"] += 2
            ns["validation_score"] = min(ns["validation_score"], 25)

            ns["total"] = (ns["trend_score"] + ns["demand_score"] +
                           ns["source_score"] + ns["validation_score"])

            if ns["total"] >= 75:
                ns["grade"] = "A"
            elif ns["total"] >= 60:
                ns["grade"] = "B"
            elif ns["total"] >= 40:
                ns["grade"] = "C"
            elif ns["total"] >= 20:
                ns["grade"] = "D"
            else:
                ns["grade"] = "F"

            niche_scores[niche_name] = ns

        return niche_scores

    # ── Master Analysis ───────────────────────────────────

    def run_full_analysis(self) -> dict:
        self.load_all()

        analysis = {
            "timestamp": datetime.now().isoformat(),
            "sources": self.data_sources_status(),
            "amazon": self.analyze_amazon(),
            "trends": self.analyze_trends(),
            "demand": self.analyze_demand(),
            "ebay": self.analyze_ebay(),
            "aliexpress": self.analyze_aliexpress(),
            "competitors": self.analyze_competitors(),
            "prices": self.analyze_prices(),
            "cross_references": self.cross_reference(),
            "niche_scores": self.score_niches(),
        }

        analysis["summary"] = {
            "active_sources": sum(
                1 for s in analysis["sources"].values() if s.get("active")
            ),
            "total_sources": 7,
            "dropship_candidates": len(analysis["amazon"].get("dropship_candidates", [])),
            "cross_matches": len(analysis["cross_references"]),
            "rising_products": len(analysis["amazon"].get("rising_products", [])),
        }

        log.info(
            f"Analysis complete — "
            f"sources: {analysis['summary']['active_sources']}/7, "
            f"candidates: {analysis['summary']['dropship_candidates']}, "
            f"cross-matches: {analysis['summary']['cross_matches']}, "
            f"rising: {analysis['summary']['rising_products']}"
        )

        return analysis


if __name__ == "__main__":
    intel = DropshipIntelligence()
    result = intel.run_full_analysis()
    today = datetime.now().strftime("%Y-%m-%d")
    out = DATA_DIR / f"analysis_{today}.json"
    with open(out, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"Analysis saved: {out}")
    print(f"Candidates: {result['summary']['dropship_candidates']}")
    print(f"Cross-matches: {result['summary']['cross_matches']}")
