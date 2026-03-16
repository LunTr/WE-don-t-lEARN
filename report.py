import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib.parse import parse_qs, urljoin, urlparse

import requests


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


@dataclass
class FetchReport:
    url: str
    final_url: str
    status_code: int
    redirected: bool
    history: Tuple[Tuple[int, str], ...]
    content_type: str
    encoding: str
    apparent_encoding: str
    html_len: int
    has_data_solution_literal: bool
    data_solution_div_count: int
    title: str
    login_signals: Dict[str, bool]
    snippet: str
    saved_path: str


@dataclass
class ScoPageContext:
    userid: str
    courseid: str
    scoid: str
    ajax_url: str


def parse_cookie_header(cookie_header: str) -> Dict[str, str]:
    cookies: Dict[str, str] = {}
    for part in cookie_header.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        cookies[name.strip()] = value.strip()
    return cookies


def load_cookies_from_file(path: str = "CookieValue.txt") -> Optional[Dict[str, str]]:
    cookie_path = Path(path)
    if not cookie_path.exists():
        return None

    cookie_header = cookie_path.read_text(encoding="utf-8-sig").strip()
    if not cookie_header:
        return None

    return parse_cookie_header(cookie_header)


def build_session(
    cookies: Optional[Dict[str, str]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> requests.Session:
    sess = requests.Session()
    sess.headers.update(DEFAULT_HEADERS)
    if headers:
        sess.headers.update(headers)
    if cookies:
        sess.cookies.update(cookies)
    return sess


def save_text(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def build_report(url: str, resp: requests.Response, html: str, save_path: str) -> FetchReport:
    save_text(save_path, html)

    title = ""
    title_match = re.search(r"<title>\s*(.*?)\s*</title>", html, re.IGNORECASE | re.DOTALL)
    if title_match:
        title = title_match.group(1).strip()

    lower = html.lower()
    login_signals = {
        "contains_login_word": ("login" in lower) or ("登录" in html),
        "contains_password_field": bool(re.search(r'type=["\']password["\']', lower)),
        "contains_sso": ("sso" in lower) or ("cas" in lower) or ("oauth" in lower),
        "contains_form": "<form" in lower,
    }

    snippet = html[:1200].strip().replace("\r", "")
    history = tuple((h.status_code, h.url) for h in resp.history)
    content_type = resp.headers.get("Content-Type", "")
    data_solution_div_count = len(re.findall(r"<div\b[^>]*\bdata-solution=", html, re.IGNORECASE))

    return FetchReport(
        url=url,
        final_url=str(resp.url),
        status_code=int(resp.status_code),
        redirected=bool(resp.history),
        history=history,
        content_type=content_type,
        encoding=str(resp.encoding),
        apparent_encoding=str(resp.apparent_encoding),
        html_len=len(html),
        has_data_solution_literal=("data-solution" in html),
        data_solution_div_count=data_solution_div_count,
        title=title,
        login_signals=login_signals,
        snippet=snippet,
        saved_path=save_path,
    )


def fetch_with_report(
    session: requests.Session,
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 20,
    save_path: str = "debug_response.html",
) -> Tuple[FetchReport, str]:
    resp = session.get(
        url,
        headers=headers,
        timeout=timeout,
        allow_redirects=True,
    )

    enc = resp.encoding or resp.apparent_encoding or "utf-8"
    html = resp.content.decode(enc, errors="replace")
    report = build_report(url, resp, html, save_path)
    return report, html


def extract_js_var(html: str, name: str) -> Optional[str]:
    quoted_match = re.search(rf"var\s+{re.escape(name)}\s*=\s*['\"](.*?)['\"]\s*;", html)
    if quoted_match:
        return quoted_match.group(1)

    raw_match = re.search(rf"var\s+{re.escape(name)}\s*=\s*([^;]+);", html)
    if raw_match:
        return raw_match.group(1).strip()

    return None


def extract_initial_scoid(html: str, page_url: str) -> Optional[str]:
    init_match = re.search(r"InitSco\(\s*['\"]([^'\"]+)['\"]", html)
    if init_match:
        return init_match.group(1)

    query = parse_qs(urlparse(page_url).query)
    sco_values = query.get("sco")
    if sco_values:
        return sco_values[0]

    return None


def extract_sco_page_context(html: str, page_url: str) -> ScoPageContext:
    userid = extract_js_var(html, "userid")
    courseid = extract_js_var(html, "courseid")
    scoid = extract_initial_scoid(html, page_url)

    if not userid:
        raise ValueError("Could not extract userid from the main study page.")
    if not courseid:
        raise ValueError("Could not extract courseid from the main study page.")
    if not scoid:
        raise ValueError("Could not extract the initial scoid from the main study page.")

    ajax_url = urljoin(page_url, f"../Ajax/SCO.aspx?uid={userid}")
    return ScoPageContext(userid=userid, courseid=courseid, scoid=scoid, ajax_url=ajax_url)


def fetch_sco_addr(
    session: requests.Session,
    context: ScoPageContext,
    *,
    referer: str,
    timeout: int = 20,
    save_path: str = "debug_sco_addr.json",
) -> Dict:
    parsed_referer = urlparse(referer)
    origin = f"{parsed_referer.scheme}://{parsed_referer.netloc}"
    payload = {
        "action": "scoAddr",
        "cid": context.courseid,
        "scoid": context.scoid,
        "nocache": "0.123456789",
    }
    headers = {
        "Origin": origin,
        "Referer": referer,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }

    resp = session.post(
        context.ajax_url,
        headers=headers,
        data=payload,
        timeout=timeout,
    )
    save_text(save_path, resp.text)
    resp.raise_for_status()

    try:
        return resp.json()
    except ValueError as exc:
        raise ValueError(f"scoAddr did not return JSON: {resp.text[:500]!r}") from exc


def resolve_sco_content_url(sco_data: Dict, page_url: str) -> str:
    ret = sco_data.get("ret")
    if ret != 0:
        raise ValueError(f"scoAddr returned ret={ret!r} instead of 0.")

    addr = str(sco_data.get("addr", "")).strip()
    if not addr:
        raise ValueError("scoAddr response did not include a usable addr field.")

    first_addr = addr.split("|", 1)[0].strip()
    if not first_addr:
        raise ValueError("scoAddr addr field was empty after splitting.")

    return urljoin(page_url, first_addr)


def print_report(r: FetchReport) -> None:
    print("=== Fetch Diagnostics ===")
    print(f"URL:        {r.url}")
    print(f"Final URL:  {r.final_url}")
    print(f"Status:     {r.status_code}")
    print(f"Redirected: {r.redirected}")
    if r.history:
        print("History:")
        for code, u in r.history:
            print(f"  - {code} {u}")

    print("\n=== Response Meta ===")
    print(f"Content-Type:        {r.content_type}")
    print(f"Encoding (declared): {r.encoding}")
    print(f"Encoding (apparent): {r.apparent_encoding}")
    print(f"HTML length:         {r.html_len}")
    print(f"<title>:             {r.title!r}")

    print("\n=== Extraction ===")
    print(f"Contains literal 'data-solution' in HTML: {r.has_data_solution_literal}")
    print(f"div[data-solution] count:                {r.data_solution_div_count}")

    print("\n=== Login/JS Render Clues (heuristics) ===")
    for k, v in r.login_signals.items():
        print(f"{k}: {v}")

    print("\n=== Saved HTML ===")
    print(f"Saved to: {r.saved_path}")

    print("\n=== HTML Snippet (first ~1200 chars) ===")
    print(r.snippet)


def main():
    url = "https://welearn.sflep.com/student/StudyCourse.aspx?cid=584&classid=730891&sco=m-2-3-19"
    cookies = load_cookies_from_file("CookieValue.txt")

    if cookies:
        print(f"Loaded {len(cookies)} cookies from CookieValue.txt")
    else:
        print("CookieValue.txt not found or empty; sending request without cookies.")

    session = build_session(cookies=cookies)

    try:
        main_report, main_html = fetch_with_report(
            session,
            url,
            save_path="debug_response.html",
        )
        print_report(main_report)

        if main_report.status_code in (401, 403):
            print("\nLikely blocked or requires authentication (401/403).")
            return
        if main_report.redirected and "login" in main_report.final_url.lower():
            print("\nLooks like you were redirected to a login page; pass cookies/session.")
            return

        context = extract_sco_page_context(main_html, main_report.final_url)
        print("\n=== SCO Context ===")
        print(f"userid:   {context.userid}")
        print(f"courseid: {context.courseid}")
        print(f"scoid:    {context.scoid}")
        print(f"ajaxUrl:  {context.ajax_url}")

        sco_data = fetch_sco_addr(
            session,
            context,
            referer=main_report.final_url,
            save_path="debug_sco_addr.json",
        )
        print("\n=== AJAX scoAddr ===")
        print("Saved to: debug_sco_addr.json")
        print(f"ret:      {sco_data.get('ret')}")
        print(f"addr:     {str(sco_data.get('addr', ''))[:500]}")

        iframe_url = resolve_sco_content_url(sco_data, main_report.final_url)
        print(f"iframe:   {iframe_url}")

        iframe_report, _ = fetch_with_report(
            session,
            iframe_url,
            headers={"Referer": main_report.final_url},
            save_path="debug_iframe.html",
        )
        print("\n=== iframe Content Diagnostics ===")
        print_report(iframe_report)

        if iframe_report.has_data_solution_literal or iframe_report.data_solution_div_count > 0:
            print("\nFound data-solution in the iframe content.")
        else:
            print(
                "\nStill no data-solution in the iframe HTML. The real data is likely loaded one step deeper "
                "by JS/XHR inside the iframe page. Inspect debug_iframe.html or the iframe page's network calls next."
            )
    except (requests.RequestException, ValueError) as e:
        print("=== Fetch/Parse Error ===")
        print(repr(e))
        sys.exit(2)


if __name__ == "__main__":
    main()
