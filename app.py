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
    "BUY": ("Buy now", "#34F0B0"),
    "WAIT": ("Wait", "#FFC24B"),
    "SKIP": ("Skip it", "#FF6B8B"),
    "UNSURE": ("Not enough data", "#9EB0FF"),
}
CONFIDENCE = {"low": 1, "medium": 2, "high": 3}
TAG_COLORS = {
    "cheaper": "#34F0B0",
    "better value": "#6FC3FF",
    "upgrade": "#D29BFF",
    "same product, better deal": "#FFC24B",
}
EXAMPLES = ["Sony WH-1000XM5", "Dyson V15 Detect", "Kindle Paperwhite"]

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');

:root{
  --serif:'Instrument Serif','Times New Roman',serif;
  --sans:'Plus Jakarta Sans',system-ui,sans-serif;
  --text:#F6F2FF; --soft:#CFC7EE; --muted:#9F95CC;
  --glass:rgba(255,255,255,.07); --edge:rgba(255,255,255,.15);
  --accent:#B79CFF;
  color-scheme:dark;
}

/* Page: violet base with a four-colour mesh */
.stApp{
  font-family:var(--sans);
  color:var(--text);
  background:
    radial-gradient(900px 620px at 6% -6%, rgba(139,92,246,.62), transparent 60%),
    radial-gradient(820px 620px at 98% 2%, rgba(244,114,182,.42), transparent 58%),
    radial-gradient(900px 700px at 78% 108%, rgba(34,211,238,.30), transparent 58%),
    radial-gradient(760px 560px at -4% 100%, rgba(251,146,60,.30), transparent 58%),
    radial-gradient(700px 420px at 50% 32%, color-mix(in srgb,var(--accent) 16%,transparent), transparent 70%),
    #150C36;
  background-attachment:fixed;
}
.stApp, .stApp p, .stApp label, .stApp input, .stApp button, .stApp textarea{font-family:var(--sans)!important}
[data-testid="stHeader"]{background:transparent!important}
[data-testid="stToolbar"],[data-testid="stDecoration"],footer{display:none!important}
.block-container,[data-testid="stMainBlockContainer"]{max-width:820px!important;padding-top:3rem!important;padding-bottom:5rem!important}
.stApp a{color:inherit;text-decoration:none}
[data-testid="stSidebarCollapseButton"] svg,[data-testid="stSidebarCollapsedControl"] svg{color:#fff!important;fill:#fff!important}

/* Sidebar */
section[data-testid="stSidebar"]{background:linear-gradient(185deg,#2A1662 0%,#1A0F45 55%,#120A30 100%)!important;border-right:1px solid var(--edge)}
section[data-testid="stSidebar"] *{color:var(--text)}
.side-title{font-family:var(--serif);font-size:32px;color:#fff;margin:6px 0 18px;letter-spacing:-.01em}

/* Hero */
.brand{display:flex;align-items:center;gap:16px;margin-bottom:12px}
.brand-mark{width:54px;height:54px;border-radius:17px;display:grid;place-items:center;flex:0 0 54px;
  background:linear-gradient(135deg,#FFC24B 0%,#FF6B8B 55%,#8B5CF6 100%);
  box-shadow:0 14px 34px -10px rgba(255,107,139,.85),inset 0 1px 0 rgba(255,255,255,.4)}
.brand-name{font-family:var(--serif);font-size:60px;line-height:1;letter-spacing:-.015em;
  background:linear-gradient(92deg,#FFFFFF 0%,#FFE3BC 38%,#FFA9D8 72%,#C9B6FF 100%);
  -webkit-background-clip:text;background-clip:text;color:transparent;-webkit-text-fill-color:transparent}
.tagline{color:var(--soft);font-size:18px;line-height:1.55;margin:8px 0 28px;max-width:560px}

/* Inputs */
[data-testid="stWidgetLabel"] p,[data-testid="stWidgetLabel"] label{color:var(--soft)!important;font-size:13.5px;font-weight:700}
[data-testid="stTextInputRootElement"],[data-testid="stNumberInputContainer"]{
  background:rgba(255,255,255,.09)!important;border:1px solid var(--edge)!important;border-radius:15px!important;
  box-shadow:none!important;transition:border-color .15s,box-shadow .15s}
[data-testid="stTextInputRootElement"]:focus-within,[data-testid="stNumberInputContainer"]:focus-within{
  border-color:#C4A8FF!important;box-shadow:0 0 0 4px rgba(196,168,255,.22)!important}
div[data-baseweb="input"],div[data-baseweb="base-input"]{background:transparent!important;border:0!important}
.stApp input{color:#fff!important;-webkit-text-fill-color:#fff!important;caret-color:#fff;font-size:16px!important;padding:14px 16px!important}
.stApp input::placeholder{color:rgba(255,255,255,.42)!important;-webkit-text-fill-color:rgba(255,255,255,.42)!important}
[data-testid="stNumberInputStepUp"],[data-testid="stNumberInputStepDown"]{background:rgba(255,255,255,.1)!important;color:#fff!important}
[data-testid="stForm"]{border:none!important;padding:0!important;background:transparent!important}
[data-testid="stFormSubmitButton"] button{
  background:linear-gradient(100deg,#FFC24B 0%,#FF6B8B 52%,#B57CFF 100%)!important;border:0!important;border-radius:15px!important;
  min-height:3.3rem;padding:.8rem 2.2rem;box-shadow:0 16px 34px -12px rgba(255,107,139,.85);transition:transform .14s,filter .14s}
[data-testid="stFormSubmitButton"] button p{color:#22103F!important;font-weight:800!important;font-size:16.5px!important}
[data-testid="stFormSubmitButton"] button:hover{transform:translateY(-2px);filter:brightness(1.08) saturate(1.1)}
[data-testid="stFormSubmitButton"] button:focus-visible{outline:3px solid #fff;outline-offset:2px}
.stButton button{background:var(--glass)!important;border:1px solid var(--edge)!important;border-radius:999px!important;
  min-height:2.3rem;padding:.25rem 1.05rem;backdrop-filter:blur(10px)}
.stButton button p{color:var(--text)!important;font-size:13.5px!important;font-weight:600!important}
.stButton button:hover{border-color:#FFC4E0!important;background:rgba(255,255,255,.13)!important}
.hint{color:var(--muted);font-size:13.5px;margin:-6px 0 14px}
.try{color:var(--muted);font-size:13.5px;font-weight:600;margin:20px 0 8px}

/* Verdict */
.verdict{margin-top:34px;padding:34px 36px 30px;border-radius:28px;
  border:1px solid color-mix(in srgb,var(--accent) 55%,transparent);
  background:
    radial-gradient(520px 260px at 100% 0%, color-mix(in srgb,var(--accent) 30%,transparent), transparent 70%),
    linear-gradient(150deg,color-mix(in srgb,var(--accent) 26%,#2A1A66) 0%,rgba(28,17,78,.86) 62%);
  box-shadow:0 46px 90px -40px color-mix(in srgb,var(--accent) 80%,transparent),inset 0 1px 0 rgba(255,255,255,.18)}
.v-top{display:flex;justify-content:space-between;align-items:center;gap:14px;color:var(--soft);font-size:14.5px;font-weight:500}
.v-conf{white-space:nowrap;color:var(--soft);font-size:13px;font-weight:600}
.meter{display:inline-flex;gap:4px;margin-left:9px;vertical-align:middle}
.meter i{width:20px;height:6px;border-radius:3px;background:rgba(255,255,255,.2)}
.meter i.on{background:var(--accent);box-shadow:0 0 12px var(--accent)}
.v-word{font-family:var(--serif);font-style:italic;font-size:92px;line-height:.95;letter-spacing:-.02em;margin:20px 0 10px;
  background:linear-gradient(95deg,var(--accent) 10%,color-mix(in srgb,var(--accent) 35%,#fff) 90%);
  -webkit-background-clip:text;background-clip:text;color:transparent;-webkit-text-fill-color:transparent;
  filter:drop-shadow(0 6px 26px color-mix(in srgb,var(--accent) 45%,transparent))}
.v-head{font-size:22px;font-weight:800;margin-bottom:6px;color:#fff}
.v-line{color:var(--soft);font-size:16.5px;line-height:1.62}
.v-stats{display:flex;flex-wrap:wrap;gap:14px 40px;margin-top:26px;padding-top:22px;border-top:1px solid rgba(255,255,255,.16)}
.v-stats .k{display:block;font-size:13px;color:var(--muted);font-weight:600;margin-bottom:3px}
.v-stats .n{font-family:var(--serif);font-size:34px;color:#fff}
.v-tip{margin-top:22px;padding:14px 18px;border-radius:16px;background:rgba(255,255,255,.09);border:1px solid rgba(255,255,255,.12);
  font-size:15px;line-height:1.55;color:#EDE8FF}

/* Sections */
.sec{font-family:var(--serif);font-size:38px;line-height:1.1;letter-spacing:-.01em;margin:52px 0 14px;color:#fff}

.why-row{display:flex;gap:16px;padding:17px 0;border-bottom:1px solid var(--edge)}
.why-row:last-child{border-bottom:0}
.dot{flex:0 0 10px;height:10px;border-radius:50%;margin-top:7px;background:var(--accent);
  box-shadow:0 0 0 5px color-mix(in srgb,var(--accent) 22%,transparent),0 0 16px var(--accent)}
.why-t{font-weight:800;font-size:17px;margin-bottom:3px;color:#fff}
.why-d{color:var(--soft);font-size:15.5px;line-height:1.62}

.opt{display:grid;grid-template-columns:minmax(130px,1.2fr) 1.2fr auto auto;gap:18px;align-items:center;
  padding:18px 20px;border:1px solid var(--edge);border-radius:18px;background:var(--glass);
  backdrop-filter:blur(14px);margin-bottom:11px}
.opt.best{border-color:color-mix(in srgb,var(--accent) 70%,transparent);
  background:linear-gradient(120deg,color-mix(in srgb,var(--accent) 20%,transparent),var(--glass))}
.seller{font-weight:800;font-size:17px;color:#fff}
.onote{color:var(--muted);font-size:13.5px;line-height:1.45;margin-top:3px}
.pill{font-size:11.5px;font-weight:800;padding:3px 10px;border-radius:999px;margin-left:10px;color:#1B0E3D;background:var(--accent)}
.bar{height:8px;border-radius:5px;background:rgba(255,255,255,.12);overflow:hidden}
.bar i{display:block;height:100%;border-radius:5px;background:linear-gradient(90deg,#FFC24B,#FF6B8B 60%,#B57CFF)}
.price{font-family:var(--serif);font-size:30px;text-align:right;min-width:86px;color:#fff}
.go{font-size:13.5px;font-weight:800;padding:9px 17px;border-radius:999px;color:#22103F;white-space:nowrap;
  background:linear-gradient(100deg,#FFE3BC,#FFC4E0);transition:transform .14s,filter .14s}
.go:hover{transform:translateY(-1px);filter:brightness(1.06)}

.alt{padding:20px 22px;border:1px solid var(--edge);border-left:4px solid var(--t);border-radius:20px;margin-bottom:13px;
  background:linear-gradient(135deg,color-mix(in srgb,var(--t) 12%,transparent),var(--glass) 55%);backdrop-filter:blur(14px)}
.tag{display:inline-block;font-size:12.5px;font-weight:800;padding:4px 12px;border-radius:999px;margin-bottom:11px;
  color:#1B0E3D;background:var(--t)}
.alt-head{display:flex;justify-content:space-between;align-items:baseline;gap:16px}
.alt-name{font-weight:800;font-size:18px;line-height:1.35;color:#fff}
.alt-price{font-family:var(--serif);font-size:30px;white-space:nowrap;color:#fff}
.alt-why{color:var(--soft);font-size:15.5px;line-height:1.62;margin:6px 0 14px}

.meta{margin-top:40px;text-align:center;color:var(--muted);font-size:13px}
.note{margin-top:24px;padding:15px 20px;border-radius:16px;font-size:15.5px;line-height:1.55;
  border:1px solid var(--edge);background:var(--glass);color:var(--soft)}
.note.err{border-color:rgba(255,107,139,.65);background:rgba(255,107,139,.14);color:#FFD3DC}

/* Loading */
.scan{margin-top:34px;padding:24px 26px;border-radius:20px;border:1px solid var(--edge);background:var(--glass);backdrop-filter:blur(14px)}
.scan-t{color:var(--text);font-size:16px;font-weight:600;margin-bottom:16px}
.scan-bar{height:6px;border-radius:4px;background:rgba(255,255,255,.12);overflow:hidden}
.scan-bar i{display:block;width:40%;height:100%;border-radius:4px;
  background:linear-gradient(90deg,transparent,#FFC24B,#FF6B8B,#B57CFF,transparent);animation:slide 1.3s ease-in-out infinite}
@keyframes slide{0%{transform:translateX(-110%)}100%{transform:translateX(270%)}}
@media (prefers-reduced-motion:reduce){.scan-bar i{animation:none;width:100%}}

@media (max-width:640px){
  .brand-name{font-size:40px}
  .brand-mark{width:44px;height:44px;flex-basis:44px}
  .verdict{padding:26px 22px}
  .v-word{font-size:64px}
  .sec{font-size:32px}
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
        tag_html = f'<span class="tag">{esc(tag)}</span>' if tag else ""
        price = a.get("price") if has_value(a.get("price")) else ""
        url = safe_url(a.get("url"))
        btn = f'<a class="go" href="{esc(url)}" target="_blank" rel="noopener noreferrer">See listing</a>' if url else ""
        cards += (
            f'<div class="alt" style="--t:{color}">{tag_html}'
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
        max_searches = int(st.number_input("Web searches per check", min_value=1, max_value=8, value=4, step=1,
                                           help="More searches find more sellers but cost more."))
        model = st.text_input("Model", value=DEFAULT_MODEL)

    st.markdown(
        compact("""
        <div class="brand">
          <div class="brand-mark">
            <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#22103F" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
              <path d="M3 12.6V4a1 1 0 0 1 1-1h8.6a1 1 0 0 1 .7.3l7.4 7.4a1 1 0 0 1 0 1.4l-8.6 8.6a1 1 0 0 1-1.4 0L3.3 13.3a1 1 0 0 1-.3-.7Z"/>
              <circle cx="8" cy="8" r="1.4" fill="#22103F" stroke="none"/>
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
