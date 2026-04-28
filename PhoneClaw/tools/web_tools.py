"""Web tools: search and HTTP requests."""

import re
import requests
from urllib.parse import quote_plus, urlparse

from tools.registry import registry
from utils.logger import get_logger

log = get_logger("tools.web")

_REQUEST_TIMEOUT = 15
_MAX_RESPONSE_BODY = 3000

# Private/reserved IP ranges to block (SSRF protection)
_BLOCKED_HOSTS = {
    "localhost",
    "0.0.0.0",
    "127.0.0.1",
    "::1",
    "metadata.google.internal",
    "169.254.169.254",
}

_BLOCKED_IP_PREFIXES = (
    "10.",
    "172.16.", "172.17.", "172.18.", "172.19.",
    "172.20.", "172.21.", "172.22.", "172.23.",
    "172.24.", "172.25.", "172.26.", "172.27.",
    "172.28.", "172.29.", "172.30.", "172.31.",
    "192.168.",
    "169.254.",
    "127.",
    "0.",
)


def _is_url_safe(url):
    """Check that a URL doesn't point to internal/private addresses."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if host in _BLOCKED_HOSTS:
            return False
        if any(host.startswith(p) for p in _BLOCKED_IP_PREFIXES):
            return False
        if not parsed.scheme or parsed.scheme not in ("http", "https"):
            return False
        return True
    except Exception:
        return False


@registry.register(
    "web_search",
    "Search the web using DuckDuckGo. Returns top results with titles and snippets.",
    {"query": "string (search query)"},
)
def web_search(query):
    if not query or not query.strip():
        return "ERROR: Empty search query"

    try:
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()

        # Parse results from HTML
        results = _parse_ddg_results(resp.text)

        if not results:
            return f"No results found for: {query}"

        output_lines = [f"Search results for: {query}\n"]
        for i, r in enumerate(results[:7], 1):
            output_lines.append(f"{i}. {r['title']}")
            if r.get("snippet"):
                output_lines.append(f"   {r['snippet']}")
            if r.get("url"):
                output_lines.append(f"   URL: {r['url']}")
            output_lines.append("")

        return "\n".join(output_lines)

    except requests.exceptions.Timeout:
        return "ERROR: Search request timed out"
    except Exception as exc:
        log.error("Web search failed: %s", exc)
        return f"ERROR: Search failed: {exc}"


def _parse_ddg_results(html):
    """Extract search results from DuckDuckGo HTML response."""
    results = []

    # Find result blocks
    result_blocks = re.findall(
        r'<a rel="nofollow" class="result__a" href="([^"]*)"[^>]*>(.*?)</a>',
        html,
        re.DOTALL,
    )
    snippets = re.findall(
        r'<a class="result__snippet"[^>]*>(.*?)</a>',
        html,
        re.DOTALL,
    )

    for i, (url, title) in enumerate(result_blocks):
        title_clean = re.sub(r"<[^>]+>", "", title).strip()
        snippet_clean = ""
        if i < len(snippets):
            snippet_clean = re.sub(r"<[^>]+>", "", snippets[i]).strip()

        if title_clean:
            results.append({
                "title": title_clean,
                "snippet": snippet_clean,
                "url": url,
            })

    return results


@registry.register(
    "http_request",
    "Make an HTTP request to a URL. Returns status code and response body.",
    {
        "url": "string (full URL)",
        "method": "string (GET or POST, default GET)",
        "body": "string (optional, request body for POST)",
    },
)
def http_request(url, method="GET", body=None):
    if not url:
        return "ERROR: No URL provided"

    if not _is_url_safe(url):
        return "ERROR: URL blocked — cannot access private/internal addresses"

    method = method.upper()
    if method not in ("GET", "POST"):
        return "ERROR: Only GET and POST methods are supported"

    try:
        headers = {
            "User-Agent": "PhoneClaw/1.0",
            "Accept": "text/html,application/json,text/plain",
        }

        if method == "GET":
            resp = requests.get(url, headers=headers, timeout=_REQUEST_TIMEOUT)
        else:
            headers["Content-Type"] = "application/json"
            resp = requests.post(
                url, headers=headers, data=body, timeout=_REQUEST_TIMEOUT
            )

        result = f"Status: {resp.status_code}\n"

        body_text = resp.text
        if len(body_text) > _MAX_RESPONSE_BODY:
            body_text = body_text[:_MAX_RESPONSE_BODY] + "\n... (truncated)"
        result += f"Body:\n{body_text}"

        return result

    except requests.exceptions.Timeout:
        return "ERROR: Request timed out"
    except requests.exceptions.ConnectionError:
        return f"ERROR: Could not connect to {url}"
    except Exception as exc:
        return f"ERROR: Request failed: {exc}"
