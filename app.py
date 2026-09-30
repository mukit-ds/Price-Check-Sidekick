"""Price-Check Sidekick: name a product, get a clear BUY / WAIT / SKIP verdict.

Run:  streamlit run app.py
Key:  set OPENAI_API_KEY as an environment variable, or in .streamlit/secrets.toml
"""
import json
import os
import re
from html import escape

import streamlit as st
from openai import OpenAI

DEFAULT_MODEL = "gpt-5-mini"

SYSTEM_PROMPT = """You are Price-Check Sidekick, a sharp, honest shopping assistant.

Given a product name or link, use web search to:
1. Identify the exact product (brand, model, size or variant).
2. Find the current price at 2-4 different sellers.
3. Find 2-3 specific alternatives worth considering.
4. Decide: BUY now, WAIT (a better deal or newer model is likely soon), or SKIP.

Rules:
- If the input is a link or an ASIN/SKU, first identify the product NAME, then search by name. Amazon often hides prices from scrapers, so never rely on one page.
- Search at least 3 different retailers (for example Walmart, Target, Best Buy, Ulta, the brand's own site) before giving up on a price.
- Every "url" must be a specific product page. Never use a homepage.
- If you verified fewer than 2 real prices, set verdict to "UNSURE" instead of guessing.
- Only report prices you actually found. Never invent prices or URLs. Write "unknown" if missing.
- Alternatives must be exact products (brand + model + size), never categories like "other brands". Each needs a price and one concrete reason it beats or matches the original (cheaper by how much, better feature, newer model).
- Reasons need a short title (2-4 words) and one concrete sentence with numbers where possible.
- Be brief. No marketing language. Respect the user's budget if given.

Reply with ONLY a JSON object (no markdown fences, no extra text):
{
  "product": "exact product name",
  "verdict": "BUY" | "WAIT" | "SKIP" | "UNSURE",
  "confidence": "low" | "medium" | "high",
  "headline": "punchy 4-9 word summary, e.g. Fair price, but a sale is likely soon",
  "one_line": "one sentence explaining the verdict",
  "price_range": "e.g. $299 - $349",
  "best_price": "lowest verified price, e.g. $299",
  "target_price": "price at which this becomes a clear buy, or empty",
  "timing_tip": "one sentence on when to buy (sale events, new model rumors), or empty",
  "reasons": [{"title": "2-4 words", "detail": "one concrete sentence"}],
  "options": [
    {"seller": "...", "price": "...", "stock": "In stock | Out of stock | Unknown", "note": "short note", "url": "https://..."}
  ],
  "alternatives": [
    {"name": "exact product name", "price": "...", "tag": "Cheaper | Better value | Upgrade | Same product, better deal", "why": "one concrete sentence", "url": "https://..."}
  ]
}"""

VERDICTS = {
    "BUY": ("Buy now", "#3FD0A0"),
    "WAIT": ("Wait", "#F0B44C"),
    "SKIP": ("Skip it", "#F26D6D"),
    "UNSURE": ("Not enough data", "#8FA3B8"),
}
CONFIDENCE = {"low": 1, "medium": 2, "high": 3}
TAG_COLORS = {
    "cheaper": "#3FD0A0",
    "better value": "#7DB7F0",
    "upgrade": "#C39BF2",
    "same product, better deal": "#F0B44C",
}
EXAMPLES = ["Sony WH-1000XM5", "Dyson V15 Detect", "Kindle Paperwhite"]

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&family=Manrope:wght@400;500;600;700&display=swap');

:root{
  --ink:#0C1116; --panel:#131A21; --line:#24303A;
  --ivory:#F1EDE4; --muted:#8C98A3; --soft:#B4BEC6;
  --accent:#9DB4C8;
}
.stApp{
  font-family:'Manrope',system-ui,sans-serif;
  color:var(--ivory);
  background:
    radial-gradient(1100px 560px at 10% -12%, color-mix(in srgb,var(--accent) 17%,transparent), transparent 62%),
    radial-gradient(900px 520px at 105% 0%, rgba(96,124,170,.12), transparent 58%),
    var(--ink);
}
[data-testid="stHeader"]{background:transparent}
[data-testid="stToolbar"],[data-testid="stDecoration"],footer{display:none!important}
.block-container{max-width:760px;padding-top:2.6rem;padding-bottom:4rem}
.stApp a{color:inherit;text-decoration:none}

/* Sidebar */
section[data-testid="stSidebar"]{background:#0A0E12;border-right:1px solid var(--line)}
section[data-testid="stSidebar"] label p{color:var(--muted);font-size:13px;font-weight:600}
.side-title{font-family:'Fraunces',serif;font-size:22px;margin:4px 0 14px}

/* Hero */
.brand{display:flex;align-items:center;gap:14px;margin-bottom:10px}
.brand-mark{width:44px;height:44px;border-radius:13px;display:grid;place-items:center;
  border:1px solid color-mix(in srgb,var(--accent) 45%,var(--line));
  background:color-mix(in srgb,var(--accent) 12%,var(--panel))}
.brand-name{font-family:'Fraunces',serif;font-size:40px;font-weight:600;letter-spacing:-.025em;line-height:1}
.tagline{color:var(--soft);font-size:17px;line-height:1.5;margin:6px 0 22px;max-width:520px}

/* Inputs */
[data-testid="stWidgetLabel"] p{color:var(--muted);font-size:13px;font-weight:600}
div[data-baseweb="input"]{background:var(--panel)!important;border:1px solid var(--line)!important;border-radius:14px!important;transition:border-color .15s}
div[data-baseweb="input"]:focus-within{border-color:color-mix(in srgb,var(--accent) 70%,var(--line))!important}
div[data-baseweb="base-input"]{background:transparent!important}
div[data-baseweb="input"] input{color:var(--ivory)!important;font-family:'Manrope',sans-serif;padding:14px 16px!important;font-size:15.5px}
div[data-baseweb="input"] input::placeholder{color:#5F6B76}
[data-testid="stForm"]{border:none!important;padding:0!important;background:transparent!important}
[data-testid="stFormSubmitButton"] button{
  background:var(--ivory);color:#0C1116;border:0;border-radius:13px;
  font-weight:700;font-size:15.5px;padding:.75rem 1.7rem;min-height:3rem;transition:transform .12s,background .12s}
[data-testid="stFormSubmitButton"] button:hover{background:#fff;color:#0C1116;transform:translateY(-1px)}
[data-testid="stFormSubmitButton"] button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.stButton button{background:transparent;border:1px solid var(--line);color:var(--soft);
  border-radius:999px;font-size:13px;font-weight:600;padding:.2rem .9rem;min-height:2rem}
.stButton button:hover{border-color:var(--ivory);color:var(--ivory);background:transparent}
.hint{color:#6E7A85;font-size:13px;margin:-4px 0 12px}
.try{color:var(--muted);font-size:13px;margin:16px 0 6px}

/* Verdict */
.verdict{margin-top:30px;padding:30px 32px 26px;border-radius:24px;
  border:1px solid color-mix(in srgb,var(--accent) 38%,var(--line));
  background:linear-gradient(158deg,color-mix(in srgb,var(--accent) 15%,var(--panel)) 0%,var(--panel) 58%);
  box-shadow:0 40px 70px -38px color-mix(in srgb,var(--accent) 55%,transparent)}
.v-top{display:flex;justify-content:space-between;align-items:center;gap:14px;color:var(--soft);font-size:14px}
.v-conf{white-space:nowrap;color:var(--muted);font-size:13px}
.meter{display:inline-flex;gap:4px;margin-left:8px;vertical-align:middle}
.meter i{width:18px;height:5px;border-radius:3px;background:rgba(255,255,255,.14)}
.meter i.on{background:var(--accent)}
.v-word{font-family:'Fraunces',serif;font-size:68px;line-height:1;font-weight:600;letter-spacing:-.035em;
  color:var(--accent);margin:18px 0 8px}
.v-head{font-size:21px;font-weight:700;margin-bottom:6px}
.v-line{color:var(--soft);font-size:16px;line-height:1.6}
.v-stats{display:flex;flex-wrap:wrap;gap:12px 34px;margin-top:24px;padding-top:20px;border-top:1px solid rgba(255,255,255,.09)}
.v-stats .k{display:block;font-size:12.5px;color:var(--muted);margin-bottom:2px}
.v-stats .n{font-family:'Fraunces',serif;font-size:27px;font-weight:500}
.v-tip{margin-top:20px;padding:13px 16px;border-radius:14px;background:rgba(255,255,255,.045);
  font-size:14.5px;line-height:1.55;color:#D5DBE0}

/* Sections */
.sec{font-family:'Fraunces',serif;font-size:25px;font-weight:600;letter-spacing:-.015em;margin:42px 0 12px}
.sec small{font-family:'Manrope',sans-serif;font-size:13px;font-weight:500;color:var(--muted);margin-left:10px;letter-spacing:0}

.why-row{display:flex;gap:14px;padding:15px 0;border-bottom:1px solid var(--line)}
.why-row:last-child{border-bottom:0}
.dot{flex:0 0 9px;height:9px;border-radius:50%;background:var(--accent);margin-top:8px;
  box-shadow:0 0 0 5px color-mix(in srgb,var(--accent) 16%,transparent)}
.why-t{font-weight:700;font-size:16px;margin-bottom:2px}
.why-d{color:var(--soft);font-size:15px;line-height:1.6}

.opt{display:grid;grid-template-columns:minmax(130px,1.2fr) 1.2fr auto auto;gap:18px;align-items:center;
  padding:16px 18px;border:1px solid var(--line);border-radius:16px;background:var(--panel);margin-bottom:10px}
.opt.best{border-color:color-mix(in srgb,var(--accent) 55%,var(--line));
  background:linear-gradient(120deg,color-mix(in srgb,var(--accent) 9%,var(--panel)),var(--panel))}
.seller{font-weight:700;font-size:16px}
.onote{color:var(--muted);font-size:13px;line-height:1.45;margin-top:2px}
.pill{font-size:11.5px;font-weight:700;padding:2px 9px;border-radius:999px;margin-left:9px;
  color:var(--accent);background:color-mix(in srgb,var(--accent) 18%,transparent)}
.bar{height:6px;border-radius:4px;background:rgba(255,255,255,.07);overflow:hidden}
.bar i{display:block;height:100%;border-radius:4px;background:linear-gradient(90deg,var(--accent),color-mix(in srgb,var(--accent) 35%,var(--ivory)))}
.price{font-family:'Fraunces',serif;font-size:23px;font-weight:500;text-align:right;min-width:78px}
.go{font-size:13px;font-weight:700;padding:8px 15px;border-radius:999px;border:1px solid var(--line);color:var(--ivory);
  transition:border-color .15s,background .15s;white-space:nowrap}
.go:hover{border-color:var(--ivory);background:rgba(255,255,255,.06)}

.alt{padding:18px 20px;border:1px solid var(--line);border-radius:18px;margin-bottom:12px;
  background:linear-gradient(180deg,rgba(255,255,255,.035),rgba(255,255,255,0))}
.tag{display:inline-block;font-size:12px;font-weight:700;padding:3px 11px;border-radius:999px;margin-bottom:10px;
  color:var(--t);background:color-mix(in srgb,var(--t) 16%,transparent)}
.alt-head{display:flex;justify-content:space-between;align-items:baseline;gap:16px}
.alt-name{font-weight:700;font-size:17px;line-height:1.35}
.alt-price{font-family:'Fraunces',serif;font-size:22px;font-weight:500;white-space:nowrap}
.alt-why{color:var(--soft);font-size:15px;line-height:1.6;margin:6px 0 12px}

.meta{margin-top:34px;text-align:center;color:#66727D;font-size:12.5px}
.note{margin-top:22px;padding:14px 18px;border-radius:14px;font-size:15px;line-height:1.55;
  border:1px solid var(--line);background:var(--panel);color:var(--soft)}
.note.err{border-color:rgba(242,109,109,.5);background:rgba(242,109,109,.08);color:#F5B5B5}

/* Loading */
.scan{margin-top:30px;padding:22px 24px;border-radius:18px;border:1px solid var(--line);background:var(--panel)}
.scan-t{color:var(--soft);font-size:15px;margin-bottom:14px}
.scan-bar{height:5px;border-radius:3px;background:rgba(255,255,255,.07);overflow:hidden}
.scan-bar i{display:block;width:38%;height:100%;background:linear-gradient(90deg,transparent,var(--accent),transparent);
  animation:slide 1.3s ease-in-out infinite}
@keyframes slide{0%{transform:translateX(-110%)}100%{transform:translateX(280%)}}
@media (prefers-reduced-motion:reduce){.scan-bar i{animation:none;width:100%}}

@media (max-width:640px){
  .brand-name{font-size:32px}
  .verdict{padding:24px 20px}
  .v-word{font-size:52px}
  .opt{grid-template-columns:1fr auto;gap:10px 14px}
  .opt .bar{grid-column:1 / -1;order:3}
  .opt .go{grid-column:1 / -1;order:4;text-align:center}
  .alt-head{flex-direction:column;gap:4px}
}
"""


# ------------------------------------------------------------------ helpers
def esc(value) -> str:
    """HTML-escape model text. Also neutralise $ so Streamlit doesn't treat it as math."""
    return escape("" if value is None else str(value), quote=True).replace("$", "&#36;")


def compact(markup: str) -> str:
    """Collapse to one line so Markdown never turns indented HTML into a code block."""
    return "".join(line.strip() for line in markup.splitlines())


def safe_url(url) -> str:
    return url if isinstance(url, str) and url.startswith(("http://", "https://")) else ""


def price_num(price):
    m = re.search(r"\d[\d,]*\.?\d*", str(price or ""))
    if not m:
        return None
    try:
        return float(m.group().replace(",", ""))
    except ValueError:
        return None


def has_value(v) -> bool:
    return bool(v) and str(v).strip().lower() not in ("unknown", "n/a", "none", "null")


def link_btn(url, label):
    url = safe_url(url)
    if not url:
        return "<span></span>"
    return f'<a class="go" href="{esc(url)}" target="_blank" rel="noopener noreferrer">{esc(label)}</a>'


def parse_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON found in model reply")
    return json.loads(text[start : end + 1])


def get_api_key() -> str:
    key = os.getenv("OPENAI_API_KEY", "")
    if key:
        return key
    try:
        return st.secrets["OPENAI_API_KEY"]
    except Exception:
        return ""


# ------------------------------------------------------------------ agent
def check_price(client, query, country, budget, model, max_searches):
    user_msg = f"Product: {query}"
    if budget:
        user_msg += f"\nMy budget: {budget}"
    if country:
        user_msg += f"\nI am shopping in: {country}. Prefer sellers and currency there."

    kwargs = dict(
        model=model,
        instructions=SYSTEM_PROMPT,
        input=user_msg,
        tools=[{"type": "web_search"}],
        max_tool_calls=max_searches,
    )
    if model.startswith(("gpt-5", "o")):
        kwargs["reasoning"] = {"effort": "low"}

    resp = client.responses.create(**kwargs)
    searches = sum(1 for item in resp.output if item.type == "web_search_call")
    return parse_json(resp.output_text), resp.usage, searches


# ------------------------------------------------------------------ views
def verdict_view(r):
    key = str(r.get("verdict", "UNSURE")).upper()
    word, color = VERDICTS.get(key, VERDICTS["UNSURE"])
    conf = str(r.get("confidence", "low")).lower()
    level = CONFIDENCE.get(conf, 1)
    meter = "".join(f'<i class="{"on" if i < level else ""}"></i>' for i in range(3))

    stats = ""
    for label, field in (("Typical price", "price_range"), ("Lowest found", "best_price"), ("A good price", "target_price")):
        if has_value(r.get(field)):
            stats += f'<div><span class="k">{label}</span><span class="n">{esc(r[field])}</span></div>'
    stats = f'<div class="v-stats">{stats}</div>' if stats else ""

    tip = f'<div class="v-tip">{esc(r["timing_tip"])}</div>' if has_value(r.get("timing_tip")) else ""
    headline = r.get("headline") or ""
    head = f'<div class="v-head">{esc(headline)}</div>' if headline else ""

    markup = f"""
    <section class="verdict">
      <div class="v-top">
        <span>{esc(r.get("product", ""))}</span>
        <span class="v-conf">{esc(conf.capitalize())} confidence<span class="meter">{meter}</span></span>
      </div>
      <div class="v-word">{esc(word)}</div>
      {head}
      <div class="v-line">{esc(r.get("one_line", ""))}</div>
      {stats}
      {tip}
    </section>
    """
    return color, compact(markup)


def reasons_view(r):
    rows = ""
    for item in r.get("reasons", []) or []:
        if isinstance(item, dict):
            title, detail = item.get("title", ""), item.get("detail", "")
        else:
            title, detail = "", str(item)
        title_html = f'<div class="why-t">{esc(title)}</div>' if title else ""
        rows += f'<div class="why-row"><span class="dot"></span><div>{title_html}<div class="why-d">{esc(detail)}</div></div></div>'
    if not rows:
        return ""
    return compact(f'<div class="sec">Why this verdict</div>{rows}')


def options_view(r):
    options = r.get("options", []) or []
    if not options:
        return ""
    nums = [price_num(o.get("price")) for o in options]
    valid = [n for n in nums if n is not None]
    ladder = len(valid) >= 2
    lowest, highest = (min(valid), max(valid)) if valid else (None, None)

    rows = ""
    for o, n in zip(options, nums):
        is_best = ladder and n is not None and n == lowest
        pill = '<span class="pill">Lowest</span>' if is_best else ""
        bar = ""
        if ladder and n is not None:
            width = max(14, round(n / highest * 100))
            bar = f'<div class="bar"><i style="width:{width}%"></i></div>'
        else:
            bar = "<div></div>"
        note = " ".join(x for x in (o.get("stock") if has_value(o.get("stock")) else "", o.get("note", "")) if x)
        price = o.get("price") if has_value(o.get("price")) else "Unknown"
        rows += (
            f'<div class="opt{" best" if is_best else ""}">'
            f'<div><div class="seller">{esc(o.get("seller", "Seller"))}{pill}</div>'
            f'<div class="onote">{esc(note)}</div></div>'
            f"{bar}"
            f'<div class="price">{esc(price)}</div>'
            f'{link_btn(o.get("url"), "View")}'
            f"</div>"
        )
    return compact(f'<div class="sec">Where to buy</div>{rows}')


def alternatives_view(r):
    alts = r.get("alternatives", []) or []
    if not alts:
        return ""
    cards = ""
    for a in alts:
        tag = str(a.get("tag", "")).strip()
        color = TAG_COLORS.get(tag.lower(), "#8FA3B8")
        tag_html = f'<span class="tag" style="--t:{color}">{esc(tag)}</span>' if tag else ""
        price = a.get("price") if has_value(a.get("price")) else ""
        url = safe_url(a.get("url"))
        btn = f'<a class="go" href="{esc(url)}" target="_blank" rel="noopener noreferrer">See listing</a>' if url else ""
        cards += (
            f'<div class="alt">{tag_html}'
            f'<div class="alt-head"><div class="alt-name">{esc(a.get("name", ""))}</div>'
            f'<div class="alt-price">{esc(price)}</div></div>'
            f'<div class="alt-why">{esc(a.get("why", ""))}</div>{btn}</div>'
        )
    return compact(f'<div class="sec">Worth considering instead</div>{cards}')


def notice(message, error=False):
    st.markdown(compact(f'<div class="note{" err" if error else ""}">{esc(message)}</div>'), unsafe_allow_html=True)


def show_result(last):
    color, verdict_html = verdict_view(last["result"])
    st.markdown(f"<style>:root{{--accent:{color}}}</style>", unsafe_allow_html=True)
    st.markdown(verdict_html, unsafe_allow_html=True)
    for section in (reasons_view, options_view, alternatives_view):
        markup = section(last["result"])
        if markup:
            st.markdown(markup, unsafe_allow_html=True)
    u = last["usage"]
    st.markdown(
        compact(f'<div class="meta">Compared using {last["searches"]} web searches and '
                f'{u.input_tokens + u.output_tokens:,} tokens</div>'),
        unsafe_allow_html=True,
    )


# ------------------------------------------------------------------ app
def use_example(name):
    st.session_state["query"] = name
    st.session_state["autorun"] = True


def main():
    st.set_page_config(page_title="Price-Check Sidekick", page_icon="🏷️", layout="centered")
    st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)

    with st.sidebar:
        st.markdown('<div class="side-title">Preferences</div>', unsafe_allow_html=True)
        country = st.text_input("Your country", placeholder="For local sellers and currency")
        max_searches = st.slider("Web searches per check", 1, 8, 4,
                                 help="More searches find more sellers but cost more.")
        model = st.text_input("Model", value=DEFAULT_MODEL)

    st.markdown(
        compact("""
        <div class="brand">
          <div class="brand-mark">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#F1EDE4" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
              <path d="M3 12.6V4a1 1 0 0 1 1-1h8.6a1 1 0 0 1 .7.3l7.4 7.4a1 1 0 0 1 0 1.4l-8.6 8.6a1 1 0 0 1-1.4 0L3.3 13.3a1 1 0 0 1-.3-.7Z"/>
              <circle cx="8" cy="8" r="1.4" fill="#F1EDE4" stroke="none"/>
            </svg>
          </div>
          <div class="brand-name">Price-Check Sidekick</div>
        </div>
        <div class="tagline">Name a product and get a straight answer: buy it now, wait for a better deal, or skip it.</div>
        """),
        unsafe_allow_html=True,
    )

    with st.form("check"):
        st.text_input("Product", key="query", placeholder="Sony WH-1000XM5, or paste a product link")
        st.markdown('<div class="hint">Product names work best. Store links often hide their prices.</div>', unsafe_allow_html=True)
        st.text_input("Budget", key="budget", placeholder="Optional, for example under $250")
        submitted = st.form_submit_button("Check price")

    st.markdown('<div class="try">Not sure what to try?</div>', unsafe_allow_html=True)
    cols = st.columns(len(EXAMPLES))
    for col, name in zip(cols, EXAMPLES):
        col.button(name, key=f"ex_{name}", on_click=use_example, args=(name,))

    run = submitted or st.session_state.pop("autorun", False)
    query = st.session_state.get("query", "").strip()

    if run:
        api_key = get_api_key()
        if not query:
            notice("Enter a product name or link to get started.")
        elif not api_key:
            notice("No OpenAI API key found. Set the OPENAI_API_KEY environment variable "
                   "(or add it to .streamlit/secrets.toml), then restart the app.", error=True)
        else:
            slot = st.empty()
            slot.markdown(
                compact('<div class="scan"><div class="scan-t">Comparing sellers and hunting for better deals</div>'
                        '<div class="scan-bar"><i></i></div></div>'),
                unsafe_allow_html=True,
            )
            try:
                result, usage, searches = check_price(
                    OpenAI(api_key=api_key), query, country.strip(),
                    st.session_state.get("budget", "").strip(), model.strip() or DEFAULT_MODEL, max_searches,
                )
                st.session_state["last"] = {"result": result, "usage": usage, "searches": searches}
            except ValueError:
                st.session_state["last"] = None
                slot.empty()
                notice("The answer came back in an unreadable format. Try again.", error=True)
            except Exception as e:
                st.session_state["last"] = None
                slot.empty()
                notice(f"OpenAI returned an error: {e}", error=True)
            slot.empty()

    last = st.session_state.get("last")
    if last:
        show_result(last)


if __name__ == "__main__":
    main()
