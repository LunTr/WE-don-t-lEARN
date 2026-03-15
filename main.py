import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

#使用时建议使用chrome，需要自己按F12爬取cookies获得自己的登录信息。如果允许建议使用别人的，否则爬取答案可能被监测导致网站刷新（暂无影响）
STUDY_URL = "https://welearn.sflep.com/student/StudyCourse.aspx?cid=584&classid=730891&sco=m-2-4-2"
#在这里输入你要抓取的网页，注意不要用网页版右侧那个箭头，每次进入新课程要退出重进，保证网址最后几位数字不一样。
#比如我从2-4-1进入课程读文章，那么按箭头next跳转后浏览器复制的网址还是2-4-1，退出重进可以解决。
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

    cookie_header = cookie_path.read_text(encoding="utf-8").strip()
    if not cookie_header:
        return None

    return parse_cookie_header(cookie_header)


def build_session(cookies: Optional[Dict[str, str]] = None) -> requests.Session:
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    if cookies:
        session.cookies.update(cookies)
    return session


def decode_response(resp: requests.Response) -> str:
    enc = resp.apparent_encoding or resp.encoding or "utf-8"
    return resp.content.decode(enc, errors="replace")


def fetch_html(session: requests.Session, url: str, *, headers=None, timeout=20) -> str:
    resp = session.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    return decode_response(resp)


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
        raise ValueError("Could not extract scoid from the main study page.")

    ajax_url = urljoin(page_url, f"../Ajax/SCO.aspx?uid={userid}")
    return ScoPageContext(userid=userid, courseid=courseid, scoid=scoid, ajax_url=ajax_url)


def fetch_sco_addr(session: requests.Session, context: ScoPageContext, *, referer: str, timeout=20) -> dict:
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

    resp = session.post(context.ajax_url, headers=headers, data=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def resolve_sco_content_url(sco_data: dict, page_url: str) -> str:
    if sco_data.get("ret") != 0:
        raise ValueError(f"scoAddr returned ret={sco_data.get('ret')!r} instead of 0.")

    addr = str(sco_data.get("addr", "")).strip()
    if not addr:
        raise ValueError("scoAddr response did not include addr.")

    first_addr = addr.split("|", 1)[0].strip()
    if not first_addr:
        raise ValueError("Resolved iframe addr is empty.")

    return urljoin(page_url, first_addr)


def extract_answers(html: str):
    soup = BeautifulSoup(html, "lxml")
    grouped_answers = {
        "filling": [],
        "choice": [],
    }

    for node in soup.select("input[data-solution]"):
        parent = node.find_parent(attrs={"data-controltype": "filling"})
        grouped_answers["filling"].append(
            {
                "data_id": parent.get("data-id") if parent else None,
                "index": node.get("data-index"),
                "solutions": [node.get("data-solution")],
            }
        )

    for choice in soup.select('div[data-controltype="choice"]'):
        solutions = []
        for option in choice.select('ul[data-itemtype="options"] li[data-solution]'):
            text = option.get_text(" ", strip=True)
            if text:
                solutions.append(text)

        if not solutions:
            continue

        sn = choice.find(attrs={"data-itemtype": "sn"})
        index = None
        if sn:
            qsn = sn.find_previous(attrs={"data-qsn": True})
            if qsn:
                index = qsn.get("data-qsn")

        grouped_answers["choice"].append(
            {
                "data_id": choice.get("data-id"),
                "index": index,
                "solutions": solutions,
            }
        )

    return grouped_answers


def main(url: str):
    cookies = load_cookies_from_file("CookieValue.txt")
    session = build_session(cookies=cookies)

    main_html = fetch_html(session, url)
    context = extract_sco_page_context(main_html, url)
    sco_data = fetch_sco_addr(session, context, referer=url)
    iframe_url = resolve_sco_content_url(sco_data, url)
    iframe_html = fetch_html(session, iframe_url, headers={"Referer": url})

    grouped_answers = extract_answers(iframe_html)
    total_answers = sum(len(items) for items in grouped_answers.values())

    print(f"main page:  {url}")
    print(f"ajax url:   {context.ajax_url}")
    print(f"iframe url: {iframe_url}")
    print(f"found {total_answers} answer item(s)")

    for question_type, items in grouped_answers.items():
        if not items:
            continue

        print(f"\n[{question_type}]")
        for i, item in enumerate(items, 1):
            solution_text = " / ".join(item["solutions"])
            print(
                f"{i:02d}. data-id={item['data_id']} index={item['index']} solution={solution_text}"
            )


if __name__ == "__main__":
    main(STUDY_URL)
