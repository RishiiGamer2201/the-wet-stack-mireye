"""Web search adapter for engineering standards, codes, and technical documentation.

Provides real-time search capabilities over web sources (ASHRAE, ASCE, IEEE, NFPA,
FEMA, IBC, Uptime Institute, EPA) with fallback knowledge indexing.
"""

from __future__ import annotations

import html
import logging
import re
import urllib.parse
from dataclasses import dataclass
from typing import Any

import httpx

log = logging.getLogger("websearch")


@dataclass
class WebSearchResult:
    title: str
    snippet: str
    url: str
    source: str
    published: str | None = None


# Curated engineering standards references for immediate high-accuracy answers
ENGINEERING_STANDARDS_KB = [
    {
        "keywords": ["ashrae", "tc 9.9", "thermal", "envelope", "temperature", "humidity", "chiller"],
        "title": "ASHRAE TC 9.9 Data Center Environmental Guidelines (2023 Revision)",
        "url": "https://www.ashrae.org/technical-resources/bookstore/datacom-series",
        "source": "ASHRAE Standard TC 9.9",
        "snippet": "ASHRAE TC 9.9 establishes environmental operating envelopes for mission-critical IT equipment. Recommended Class A1-A4 ranges: Dry-bulb temperature 18°C to 27°C (64.4°F to 80.6°F), Dew point 5.5°C to 15°C with max relative humidity 60%. Allowable ranges expand to 15°C-32°C for A1 and up to 45°C for A4 under adiabatic operation.",
    },
    {
        "keywords": ["asce", "7-22", "seismic", "pga", "earthquake", "anchorage", "ground acceleration"],
        "title": "ASCE 7-22 Minimum Design Loads and Associated Criteria for Buildings and Other Structures",
        "url": "https://asce7hazardtool.online",
        "source": "ASCE 7-22 Standard",
        "snippet": "ASCE 7-22 Chapter 13 & 15 defines Risk Category IV structural and non-structural seismic component anchorage. For critical facilities with Site Class D/E or PGA > 0.25g, equipment skids (transformers, chillers, UPS) require dynamic seismic snubbers, positive structural bolting, and flexible utility loops.",
    },
    {
        "keywords": ["fema", "flood", "bfe", "500-year", "100-year", "elevation", "stormwater", "drainage"],
        "title": "FEMA Flood Insurance Study & Technical Bulletin: Data Center Base Flood Elevations",
        "url": "https://msc.fema.gov/portal/search",
        "source": "FEMA Guidelines",
        "snippet": "FEMA guidelines for critical infrastructure designate that finished floor elevation (FFE) for main IT floor slabs, generator pads, and substation switchgear yards MUST be set at a minimum of 500-year BFE + 3.0 feet freeboard to prevent catastrophic submergence during extreme hydrological events.",
    },
    {
        "keywords": ["ieee", "1584", "substation", "transformer", "arc flash", "interconnection", "230kv"],
        "title": "IEEE 1584 & IEEE C37 Guide for Substation Design & Arc-Flash Hazard Calculations",
        "url": "https://standards.ieee.org/ieee/1584/7432/",
        "source": "IEEE Standards Association",
        "snippet": "IEEE standards for high-voltage substation interconnects (69kV/115kV/230kV) specify minimum clearances, dual-radial or ring-bus redundancy topologies, N-1 transformer sizing, blast deflection barrier firewalls between step-down units, and containment basins sized for 110% of oil volume.",
    },
    {
        "keywords": ["uptime", "tier iii", "tier iv", "redundancy", "concurrently maintainable", "fault tolerant"],
        "title": "Uptime Institute Tier Standard: Topology & Operational Sustainability",
        "url": "https://uptimeinstitute.com/tiers",
        "source": "Uptime Institute",
        "snippet": "Tier III requires Concurrently Maintainable power and cooling distribution paths (N+1 minimum on chillers/pumps/generators) allowing any component maintenance without IT downtime. Tier IV requires Fault Tolerant 2N active-active isolated distribution paths with automated response to failure.",
    },
    {
        "keywords": ["nfpa", "75", "76", "fire", "suppression", "vesda", "pre-action"],
        "title": "NFPA 75 Standard for the Fire Protection of Information Technology Equipment",
        "url": "https://www.nfpa.org/codes-and-standards/75",
        "source": "NFPA 75/76",
        "snippet": "NFPA 75/76 governs fire suppression in data halls. Mandates double-interlock pre-action sprinkler systems, VESDA early aspirating smoke detection, FM-200 / Novec 1230 clean agent suppression in electrical rooms, and 2-hour rated fire separation walls.",
    },
]


class WebSearchEngine:
    """Live web search engine with DuckDuckGo fallback and engineering standards index."""

    def __init__(self, timeout_seconds: float = 8.0) -> None:
        self.timeout = timeout_seconds

    def search(
        self, query: str, domain_filter: str | None = None, max_results: int = 5
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        cleaned_query = query.strip()

        # 1. First, check curated authoritative engineering standards knowledge base
        q_lower = cleaned_query.lower()
        kb_matches = []
        for item in ENGINEERING_STANDARDS_KB:
            match_score = sum(1 for kw in item["keywords"] if kw in q_lower)
            if match_score > 0:
                kb_matches.append((match_score, item))
        kb_matches.sort(key=lambda x: -x[0])

        for _, item in kb_matches[:2]:
            results.append(
                {
                    "title": item["title"],
                    "snippet": item["snippet"],
                    "url": item["url"],
                    "source": item["source"],
                    "type": "authoritative_standard",
                }
            )

        # 2. Attempt live search via DuckDuckGo HTML / Lite API
        try:
            live_results = self._live_duckduckgo(cleaned_query, max_results=max_results)
            results.extend(live_results)
        except Exception as exc:
            log.warning("live web search encountered error, returning curated standards", extra={"error": str(exc)})

        # Deduplicate by URL
        seen = set()
        deduped = []
        for r in results:
            if r["url"] not in seen:
                seen.add(r["url"])
                deduped.append(r)
                if len(deduped) >= max_results:
                    break
        return deduped

    def _live_duckduckgo(self, query: str, max_results: int = 4) -> list[dict[str, Any]]:
        url = "https://html.duckduckgo.com/html/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            resp = client.post(url, data={"q": f"{query} data center engineering standard"}, headers=headers)
            if resp.status_code != 200:
                return []

            text = resp.text
            # Simple regex parser for DuckDuckGo HTML output
            snippets = []
            result_blocks = re.findall(
                r'<a[^>]+class="result__url"[^>]+href="([^"]+)"[^>]*>([\s\S]*?)</a>[\s\S]*?<a[^>]+class="result__snippet"[^>]*>([\s\S]*?)</a>',
                text,
                re.IGNORECASE,
            )

            if not result_blocks:
                # Fallback pattern
                result_blocks = re.findall(
                    r'<a class="result__snippet"[^>]+href="([^"]+)"[^>]*>([\s\S]*?)</a>',
                    text,
                    re.IGNORECASE,
                )
                for item in result_blocks[:max_results]:
                    raw_url = item[0]
                    clean_text = html.unescape(re.sub(r"<[^>]+>", "", item[1])).strip()
                    parsed_url = self._extract_duckduckgo_target_url(raw_url)
                    snippets.append(
                        {
                            "title": query.capitalize(),
                            "snippet": clean_text,
                            "url": parsed_url,
                            "source": urllib.parse.urlparse(parsed_url).netloc or "web",
                            "type": "web_live",
                        }
                    )
            else:
                for r_url, r_title, r_snip in result_blocks[:max_results]:
                    raw_url = r_url
                    clean_title = html.unescape(re.sub(r"<[^>]+>", "", r_title)).strip()
                    clean_snip = html.unescape(re.sub(r"<[^>]+>", "", r_snip)).strip()
                    target_url = self._extract_duckduckgo_target_url(raw_url)
                    snippets.append(
                        {
                            "title": clean_title or query,
                            "snippet": clean_snip,
                            "url": target_url,
                            "source": urllib.parse.urlparse(target_url).netloc or "web",
                            "type": "web_live",
                        }
                    )
            return snippets

    def _extract_duckduckgo_target_url(self, ddg_url: str) -> str:
        if "uddg=" in ddg_url:
            parsed = urllib.parse.parse_qs(urllib.parse.urlparse(ddg_url).query)
            target = parsed.get("uddg")
            if target and target[0]:
                return target[0]
        return ddg_url


_engine: WebSearchEngine | None = None


def get_web_search_engine() -> WebSearchEngine:
    global _engine
    if _engine is None:
        _engine = WebSearchEngine()
    return _engine
