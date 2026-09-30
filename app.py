"""Price-Check Sidekick: name a product, get a clear BUY / WAIT / SKIP verdict.

Run:  streamlit run app.py
Key:  set OPENAI_API_KEY as an environment variable, or in .streamlit/secrets.toml
"""
import json
import os
import re
from html import escape
from urllib.parse import quote

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
EXAMPLES = [
    ("Sony WH-1000XM5", "headphones"),
    ("Dyson V15 Detect", "search"),
    ("Kindle Paperwhite", "sparkle"),
]
MODELS = ["gpt-5-mini", "gpt-5.4-mini", "gpt-5-nano", "gpt-4.1-mini", "gpt-5", "gpt-5.4"]
COUNTRIES = [
    "Australia", "Bangladesh", "Brazil", "Canada", "China", "Denmark", "Egypt", "Finland", "France",
    "Germany", "Hong Kong", "India", "Indonesia", "Ireland", "Israel", "Italy", "Japan", "Kenya",
    "Malaysia", "Mexico", "Nepal", "Netherlands", "New Zealand", "Nigeria", "Norway", "Pakistan",
    "Philippines", "Poland", "Portugal", "Qatar", "Saudi Arabia", "Singapore", "South Africa",
    "South Korea", "Spain", "Sri Lanka", "Sweden", "Switzerland", "Thailand", "Turkey",
    "United Arab Emirates", "United Kingdom", "United States", "Vietnam",
]

# ------------------------------------------------------------------ icons
_ICONS = {
    "tag": "<path d='M3 12.6V4a1 1 0 0 1 1-1h8.6a1 1 0 0 1 .7.3l7.4 7.4a1 1 0 0 1 0 1.4l-8.6 8.6a1 1 0 0 1-1.4 0L3.3 13.3a1 1 0 0 1-.3-.7Z'/><circle cx='8' cy='8' r='1.4'/>",
    "headphones": "<path d='M4 15v-3a8 8 0 0 1 16 0v3'/><path d='M4 14h3a1 1 0 0 1 1 1v3a1 1 0 0 1-1 1H6a2 2 0 0 1-2-2z'/><path d='M20 14h-3a1 1 0 0 0-1 1v3a1 1 0 0 0 1 1h1a2 2 0 0 0 2-2z'/>",
    "search": "<circle cx='11' cy='11' r='6.5'/><path d='M16 16l5 5'/>",
    "sparkle": "<path d='M12 2.5l2.2 6.6 6.8 2.4-6.8 2.4L12 20.5l-2.2-6.6L3 11.5l6.8-2.4z' fill='COLOR'/>",
    "arrow": "<path d='M5 12h14M13 6l6 6-6 6'/>",
    "globe": "<circle cx='12' cy='12' r='9'/><path d='M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18'/>",
    "cube": "<path d='M12 3l8 4.5v9L12 21l-8-4.5v-9z'/><path d='M12 12l8-4.5M12 12v9M12 12L4 7.5'/>",
    "wallet": "<rect x='3' y='6' width='18' height='13' rx='3'/><path d='M3 10h18M16.5 14.5h.01'/>",
    "dollar": "<circle cx='12' cy='12' r='9'/><path d='M14.6 9.3c-.5-.8-1.4-1.3-2.6-1.3-1.4 0-2.5.7-2.5 1.9 0 2.6 5.2 1.3 5.2 4 0 1.2-1.1 2-2.7 2-1.3 0-2.3-.5-2.8-1.4M12 6.6V8m0 8v1.4'/>",
    "robot": "<rect x='5' y='8' width='14' height='10' rx='3'/><path d='M12 8V5M9.5 13h.01M14.5 13h.01M9 21h6'/>",
    "bolt": "<path d='M13 2L4 14h7l-1 8 9-12h-7z' fill='COLOR'/>",
}


def icon(name, color="#D9D4FF", size=22, stroke=1.8):
    body = _ICONS[name].replace("COLOR", color)
    return (f"<svg xmlns='http://www.w3.org/2000/svg' width='{size}' height='{size}' viewBox='0 0 24 24' "
            f"fill='none' stroke='{color}' stroke-width='{stroke}' stroke-linecap='round' stroke-linejoin='round'>{body}</svg>")


def icon_url(name, color="#D9D4FF"):
    return 'url("data:image/svg+xml,' + quote(icon(name, color, 24), safe="") + '")'


def field_label(name, text):
    return compact(f'<div class="field"><span class="ico">{icon(name, "#B9B2FF", 18)}</span>{esc(text)}</div>')


def setting_label(name, text):
    return compact(f'<div class="setlabel"><span class="ico">{icon(name, "#B9B2FF", 18)}</span>{esc(text)}</div>')


# ------------------------------------------------------------------ hero art
HERO_SVG = """
<svg viewBox="0 0 320 250" width="300" height="234" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
<defs>
<linearGradient id="pcRing" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#FFB13B"/><stop offset=".5" stop-color="#FF4D8D"/><stop offset="1" stop-color="#7C5CFF"/></linearGradient>
<linearGradient id="pcEdge" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#FFB13B"/><stop offset=".5" stop-color="#FF4D8D"/><stop offset="1" stop-color="#7C5CFF"/></linearGradient>
<linearGradient id="pcBody" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#4045B5"/><stop offset="1" stop-color="#12154F"/></linearGradient>
<filter id="pcGlow" x="-30%" y="-60%" width="160%" height="220%"><feGaussianBlur stdDeviation="7"/></filter>
</defs>
<g transform="rotate(-16 160 140)">
<ellipse cx="160" cy="140" rx="138" ry="40" fill="none" stroke="url(#pcRing)" stroke-width="12" opacity=".5" filter="url(#pcGlow)"/>
<ellipse cx="160" cy="140" rx="138" ry="40" fill="none" stroke="url(#pcRing)" stroke-width="4"/>
</g>
<g transform="rotate(24 160 120)">
<path d="M116 30H204A16 16 0 0 1 220 46V150L160 212L100 150V46A16 16 0 0 1 116 30Z" fill="url(#pcBody)" stroke="url(#pcEdge)" stroke-width="5" stroke-linejoin="round"/>
<path d="M116 30H204A16 16 0 0 1 220 46V82C190 62 130 62 100 92V46A16 16 0 0 1 116 30Z" fill="#fff" opacity=".12"/>
<circle cx="160" cy="58" r="10" fill="#0A0D30" stroke="url(#pcEdge)" stroke-width="3"/>
<g transform="translate(121 92) scale(1.6)" fill="none" stroke="#C4B5FF" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
<path d="M3 12.6V4a1 1 0 0 1 1-1h8.6a1 1 0 0 1 .7.3l7.4 7.4a1 1 0 0 1 0 1.4l-8.6 8.6a1 1 0 0 1-1.4 0L3.3 13.3a1 1 0 0 1-.3-.7Z"/><circle cx="8" cy="8" r="1.4"/>
</g>
</g>
<g transform="rotate(-16 160 140)">
<path d="M22 140A138 40 0 0 0 298 140" fill="none" stroke="url(#pcRing)" stroke-width="4"/>
</g>
<path transform="translate(38 62) scale(.9)" d="M0-10L2.6-2.6L10 0L2.6 2.6L0 10L-2.6 2.6L-10 0L-2.6-2.6Z" fill="#FF7AB8"/>
<path transform="translate(292 196) scale(.8)" d="M0-10L2.6-2.6L10 0L2.6 2.6L0 10L-2.6 2.6L-10 0L-2.6-2.6Z" fill="#FF7AB8"/>
<path transform="translate(254 34) scale(.55)" d="M0-10L2.6-2.6L10 0L2.6 2.6L0 10L-2.6 2.6L-10 0L-2.6-2.6Z" fill="#FFFFFF"/>
<path transform="translate(70 214) scale(.5)" d="M0-10L2.6-2.6L10 0L2.6 2.6L0 10L-2.6 2.6L-10 0L-2.6-2.6Z" fill="#9C86FF"/>
</svg>
"""

# ------------------------------------------------------------------ CSS
_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');

:root{
  --sans:'Plus Jakarta Sans',system-ui,sans-serif;
  --text:#F3F1FF; --soft:#C7C3EE; --muted:#8F8CC2;
  --glass:rgba(255,255,255,.055); --edge:rgba(255,255,255,.13);
  --accent:#8B7CFF; --navy:#0F1440;
  color-scheme:dark;
}

/* Page */
.stApp{
  font-family:var(--sans);color:var(--text);
  background:
    radial-gradient(900px 600px at 12% -8%, rgba(99,70,255,.34), transparent 62%),
    radial-gradient(800px 560px at 92% 0%, rgba(50,120,255,.20), transparent 60%),
    radial-gradient(ellipse 70% 38% at 108% 108%, rgba(255,120,90,.42), rgba(200,60,190,.28) 45%, transparent 72%),
    radial-gradient(700px 420px at 50% 34%, color-mix(in srgb,var(--accent) 12%,transparent), transparent 70%),
    #060B24;
  background-attachment:fixed;
}
.stApp, .stApp p, .stApp label, .stApp input, .stApp button, .stApp textarea{font-family:var(--sans)!important}
[data-testid="stHeader"]{background:transparent!important}
[data-testid="stToolbar"],[data-testid="stDecoration"],footer{display:none!important}
.block-container,[data-testid="stMainBlockContainer"]{max-width:1040px!important;padding-top:2.6rem!important;padding-bottom:5rem!important}
.stApp a{color:inherit;text-decoration:none}
[data-testid="stSidebarCollapseButton"] svg,[data-testid="stSidebarCollapsedControl"] svg{color:#fff!important;fill:#fff!important}
[data-testid="stWidgetLabel"]{display:none}

/* Sidebar */
section[data-testid="stSidebar"]{
  background:
    radial-gradient(ellipse 150% 30% at 0% 106%, rgba(255,120,80,.60), rgba(190,60,210,.42) 48%, transparent 74%),
    linear-gradient(185deg,#0C1142 0%,#0A0E33 62%,#0A0D2C 100%)!important;
  border-right:1px solid var(--edge)}
section[data-testid="stSidebar"] > div,[data-testid="stSidebarContent"]{background:transparent!important}
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .side-foot),
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"]:has(> .element-container .side-foot){min-height:calc(100vh - 6.5rem)}
section[data-testid="stSidebar"] [data-testid="stElementContainer"]:has(.side-foot),
section[data-testid="stSidebar"] .element-container:has(.side-foot){margin-top:auto}
.side-head{display:flex;gap:16px;align-items:center;margin:4px 0 22px}
.side-tile{width:64px;height:64px;flex:0 0 64px;border-radius:20px;display:grid;place-items:center;
  background:linear-gradient(135deg,#FFB13B 0%,#FF4D8D 60%,#8B5CF6 100%);
  box-shadow:0 14px 30px -10px rgba(255,77,141,.75),inset 0 1px 0 rgba(255,255,255,.45)}
.side-title{font-size:26px;font-weight:800;color:#fff;letter-spacing:-.02em}
.side-sub{font-size:13.5px;color:var(--muted);line-height:1.45;margin-top:3px}
section[data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"]{
  background:var(--glass);border:1px solid var(--edge)!important;border-radius:22px;padding:6px 8px 10px;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.06);margin-bottom:6px}
.setlabel{display:flex;align-items:center;gap:12px;font-weight:700;font-size:15.5px;color:#EEEBFF;margin:4px 0 2px}
.ico{width:32px;height:32px;border-radius:50%;display:grid;place-items:center;background:rgba(110,100,255,.28);flex:0 0 32px}
.side-foot{display:flex;align-items:center;gap:14px;color:#F3F1FF;font-size:14px;font-weight:600;line-height:1.4;padding:6px 4px 4px}

/* Hero */
.hero{display:flex;justify-content:space-between;align-items:flex-start;gap:20px;margin-bottom:10px}
.brand{display:flex;align-items:center;gap:22px}
.brand-mark{width:92px;height:92px;flex:0 0 92px;border-radius:28px;display:grid;place-items:center;
  background:linear-gradient(135deg,#FFB13B 0%,#FF4D8D 55%,#8B5CF6 100%);
  box-shadow:0 20px 44px -14px rgba(255,77,141,.8),inset 0 1px 0 rgba(255,255,255,.5)}
.brand-name{font-size:64px;font-weight:800;line-height:1.02;letter-spacing:-.035em;color:#fff}
.grad{background:linear-gradient(95deg,#FFA53B 0%,#FF4D8D 50%,#A66BFF 100%);-webkit-background-clip:text;background-clip:text;
  color:transparent;-webkit-text-fill-color:transparent}
.tagline{color:var(--soft);font-size:19px;line-height:1.55;margin:16px 0 0 114px;max-width:640px}
.hero-art{flex:0 0 300px;margin:-14px -8px 0 0}
.hero-art svg{filter:drop-shadow(0 20px 40px rgba(124,92,255,.45))}

/* Fields */
.field{display:flex;align-items:center;gap:12px;font-weight:700;font-size:17px;color:#EEEBFF;margin:26px 0 10px}
.field .ico{width:30px;height:30px;flex-basis:30px;background:transparent}
[data-testid="stTextInputRootElement"],[data-testid="stNumberInputContainer"]{
  background:rgba(255,255,255,.06)!important;border:1px solid rgba(150,140,255,.34)!important;border-radius:999px!important;
  box-shadow:none!important;min-height:58px;transition:border-color .15s,box-shadow .15s}
[data-testid="stTextInputRootElement"]:focus-within,[data-testid="stNumberInputContainer"]:focus-within{
  border-color:#B69CFF!important;box-shadow:0 0 0 4px rgba(150,120,255,.22)!important}
div[data-baseweb="input"],div[data-baseweb="base-input"]{background:transparent!important;border:0!important}
.stApp input{color:#fff!important;-webkit-text-fill-color:#fff!important;caret-color:#fff;font-size:16.5px!important;font-weight:500}
.stApp input::placeholder{color:rgba(200,196,245,.5)!important;-webkit-text-fill-color:rgba(200,196,245,.5)!important}
.stApp .st-key-query input,.stApp .st-key-budget input{padding:16px 24px 16px 62px!important}
.st-key-query [data-testid="stTextInputRootElement"]{background:@@tag@@ 22px center/24px 24px no-repeat, rgba(255,255,255,.06)!important}
.st-key-budget [data-testid="stTextInputRootElement"]{background:@@dollar@@ 22px center/24px 24px no-repeat, rgba(255,255,255,.06)!important}
.hint{color:var(--muted);font-size:14px;margin:8px 0 0 6px}
[data-testid="stForm"]{border:none!important;padding:0!important;background:transparent!important}

/* Primary button */
[data-testid="stFormSubmitButton"]{max-width:350px;margin-top:8px}
[data-testid="stFormSubmitButton"] button{
  width:100%;display:flex;justify-content:flex-start;align-items:center;gap:14px;
  background:linear-gradient(100deg,#FFA02E 0%,#FF4D8D 48%,#7C5CFF 82%,#4F86FF 100%)!important;
  border:0!important;border-radius:999px!important;min-height:64px;padding:0 28px;
  box-shadow:0 18px 40px -14px rgba(255,77,141,.85),inset 0 1px 0 rgba(255,255,255,.4);transition:transform .14s,filter .14s}
[data-testid="stFormSubmitButton"] button::before{content:"";width:26px;height:26px;flex:0 0 26px;background:@@tag_w@@ center/contain no-repeat}
[data-testid="stFormSubmitButton"] button::after{content:"";margin-left:auto;width:26px;height:26px;flex:0 0 26px;background:@@arrow_w@@ center/contain no-repeat}
[data-testid="stFormSubmitButton"] button [data-testid="stMarkdownContainer"]{flex:1;text-align:left}
[data-testid="stFormSubmitButton"] button p{color:#fff!important;font-weight:700!important;font-size:18px!important}
[data-testid="stFormSubmitButton"] button:hover{transform:translateY(-2px);filter:brightness(1.07) saturate(1.1)}
[data-testid="stFormSubmitButton"] button:focus-visible{outline:3px solid #fff;outline-offset:3px}

/* Example chips */
.try{color:var(--soft);font-size:15px;font-weight:600;margin:34px 0 12px}
[class*="st-key-ex_"],[class*="st-key-ex_"] .stButton{width:100%}
[class*="st-key-ex_"] button{
  width:100%;display:flex;justify-content:flex-start;align-items:center;gap:14px;min-height:60px;padding:0 22px;
  border:1.5px solid transparent!important;border-radius:999px!important;
  background:linear-gradient(#0F1545,#0F1545) padding-box,linear-gradient(90deg,rgba(255,255,255,.14),rgba(255,255,255,.14)) border-box!important;
  transition:background .15s,transform .14s}
[class*="st-key-ex_"] button:hover,[class*="st-key-ex_"] button:focus-visible{
  background:linear-gradient(#12194F,#12194F) padding-box,linear-gradient(90deg,#FF7AB8,#8B5CF6,#4F7CFF) border-box!important;
  transform:translateY(-1px);outline:none}
[class*="st-key-ex_"] button::before{content:"";width:24px;height:24px;flex:0 0 24px;background-size:contain;background-repeat:no-repeat;background-position:center}
[class*="st-key-ex_"] button::after{content:"";margin-left:auto;width:22px;height:22px;flex:0 0 22px;background:@@arrow@@ center/contain no-repeat}
[class*="st-key-ex_"] button [data-testid="stMarkdownContainer"]{flex:1;text-align:left}
[class*="st-key-ex_"] button p{color:#fff!important;font-size:16px!important;font-weight:600!important}
.st-key-ex_0 button::before{background-image:@@headphones@@}
.st-key-ex_1 button::before{background-image:@@search@@}
.st-key-ex_2 button::before{background-image:@@sparkle@@}

/* Sidebar widgets */
.st-key-country [data-baseweb="select"] > div,.st-key-model [data-baseweb="select"] > div{
  background-color:rgba(255,255,255,.07)!important;border:1px solid var(--edge)!important;border-radius:16px!important;
  min-height:52px;background-repeat:no-repeat!important;background-position:16px center!important;background-size:22px 22px!important}
.st-key-country [data-baseweb="select"] > div{background-image:@@globe@@!important}
.st-key-model [data-baseweb="select"] > div{background-image:@@robot@@!important}
.st-key-country [data-baseweb="select"] > div > div:first-child,.st-key-model [data-baseweb="select"] > div > div:first-child{padding-left:42px}
[data-baseweb="select"] *{color:#fff!important}
[data-baseweb="select"] svg{fill:#C7C3EE!important}
[data-baseweb="select"] input::placeholder,[data-baseweb="select"] [class*="placeholder"]{color:rgba(200,196,245,.7)!important}
.st-key-searches [data-testid="stNumberInputContainer"]{border-radius:16px!important;min-height:52px;background:rgba(255,255,255,.07)!important;border-color:var(--edge)!important}
.stApp .st-key-searches input{padding:10px 16px!important}
[data-testid="stNumberInputStepUp"],[data-testid="stNumberInputStepDown"]{background:rgba(255,255,255,.1)!important;color:#fff!important;border-radius:50%!important;margin:4px 3px}
[data-baseweb="popover"] > div,[data-baseweb="popover"] ul,[data-baseweb="menu"]{background:#141A55!important;border-radius:14px!important}
[data-baseweb="popover"] li{color:#fff!important}
[data-baseweb="popover"] li:hover,[data-baseweb="popover"] li[aria-selected="true"]{background:rgba(139,92,246,.4)!important}

/* Verdict */
.verdict{margin-top:36px;padding:36px 40px 32px;border-radius:30px;
  border:1px solid color-mix(in srgb,var(--accent) 55%,transparent);
  background:
    radial-gradient(520px 260px at 100% 0%, color-mix(in srgb,var(--accent) 30%,transparent), transparent 70%),
    linear-gradient(150deg,color-mix(in srgb,var(--accent) 22%,#1B1E6B) 0%,rgba(13,17,62,.9) 62%);
  box-shadow:0 46px 90px -40px color-mix(in srgb,var(--accent) 80%,transparent),inset 0 1px 0 rgba(255,255,255,.18)}
.v-top{display:flex;justify-content:space-between;align-items:center;gap:14px;color:var(--soft);font-size:15px;font-weight:500}
.v-conf{white-space:nowrap;color:var(--soft);font-size:13px;font-weight:600}
.meter{display:inline-flex;gap:4px;margin-left:9px;vertical-align:middle}
.meter i{width:20px;height:6px;border-radius:3px;background:rgba(255,255,255,.2)}
.meter i.on{background:var(--accent);box-shadow:0 0 12px var(--accent)}
.v-word{font-size:92px;font-weight:800;line-height:1;letter-spacing:-.05em;margin:22px 0 12px;
  background:linear-gradient(95deg,var(--accent) 10%,color-mix(in srgb,var(--accent) 30%,#fff) 95%);
  -webkit-background-clip:text;background-clip:text;color:transparent;-webkit-text-fill-color:transparent;
  filter:drop-shadow(0 6px 26px color-mix(in srgb,var(--accent) 45%,transparent))}
.v-head{font-size:23px;font-weight:800;margin-bottom:6px;color:#fff;letter-spacing:-.01em}
.v-line{color:var(--soft);font-size:16.5px;line-height:1.62}
.v-stats{display:flex;flex-wrap:wrap;gap:14px 44px;margin-top:28px;padding-top:24px;border-top:1px solid rgba(255,255,255,.16)}
.v-stats .k{display:block;font-size:13px;color:var(--muted);font-weight:600;margin-bottom:4px}
.v-stats .n{font-size:30px;font-weight:800;color:#fff;letter-spacing:-.02em}
.v-tip{margin-top:24px;padding:15px 20px;border-radius:18px;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.12);
  font-size:15px;line-height:1.55;color:#EDE8FF}

/* Sections */
.sec{font-size:32px;font-weight:800;line-height:1.1;letter-spacing:-.03em;margin:56px 0 16px;color:#fff}
.why-row{display:flex;gap:16px;padding:18px 0;border-bottom:1px solid var(--edge)}
.why-row:last-child{border-bottom:0}
.dot{flex:0 0 10px;height:10px;border-radius:50%;margin-top:7px;background:var(--accent);
  box-shadow:0 0 0 5px color-mix(in srgb,var(--accent) 22%,transparent),0 0 16px var(--accent)}
.why-t{font-weight:800;font-size:17px;margin-bottom:3px;color:#fff}
.why-d{color:var(--soft);font-size:15.5px;line-height:1.62}

.opt{display:grid;grid-template-columns:minmax(130px,1.2fr) 1.2fr auto auto;gap:18px;align-items:center;
  padding:18px 22px;border:1px solid var(--edge);border-radius:999px;background:var(--glass);backdrop-filter:blur(14px);margin-bottom:12px}
.opt.best{border-color:color-mix(in srgb,var(--accent) 70%,transparent);
  background:linear-gradient(120deg,color-mix(in srgb,var(--accent) 20%,transparent),var(--glass))}
.seller{font-weight:800;font-size:17px;color:#fff}
.onote{color:var(--muted);font-size:13.5px;line-height:1.45;margin-top:3px}
.pill{font-size:11.5px;font-weight:800;padding:3px 10px;border-radius:999px;margin-left:10px;color:#140B3A;background:var(--accent)}
.bar{height:8px;border-radius:5px;background:rgba(255,255,255,.12);overflow:hidden}
.bar i{display:block;height:100%;border-radius:5px;background:linear-gradient(90deg,#FFA53B,#FF4D8D 60%,#8B5CF6)}
.price{font-size:24px;font-weight:800;text-align:right;min-width:86px;color:#fff;letter-spacing:-.02em}
.go{font-size:13.5px;font-weight:800;padding:10px 20px;border-radius:999px;color:#fff;white-space:nowrap;
  background:linear-gradient(100deg,#FFA02E,#FF4D8D 60%,#7C5CFF);transition:transform .14s,filter .14s}
.go:hover{transform:translateY(-1px);filter:brightness(1.08)}

.alt{padding:22px 26px;border:1px solid var(--edge);border-left:4px solid var(--t);border-radius:24px;margin-bottom:14px;
  background:linear-gradient(135deg,color-mix(in srgb,var(--t) 13%,transparent),var(--glass) 55%);backdrop-filter:blur(14px)}
.tag{display:inline-block;font-size:12.5px;font-weight:800;padding:4px 12px;border-radius:999px;margin-bottom:11px;color:#140B3A;background:var(--t)}
.alt-head{display:flex;justify-content:space-between;align-items:baseline;gap:16px}
.alt-name{font-weight:800;font-size:18px;line-height:1.35;color:#fff}
.alt-price{font-size:26px;font-weight:800;white-space:nowrap;color:#fff;letter-spacing:-.02em}
.alt-why{color:var(--soft);font-size:15.5px;line-height:1.62;margin:6px 0 14px}

.meta{margin-top:40px;text-align:center;color:var(--muted);font-size:13px}
.note{margin-top:24px;padding:15px 22px;border-radius:20px;font-size:15.5px;line-height:1.55;border:1px solid var(--edge);background:var(--glass);color:var(--soft)}
.note.err{border-color:rgba(255,107,139,.65);background:rgba(255,107,139,.14);color:#FFD3DC}

/* Loading */
.scan{margin-top:34px;padding:24px 28px;border-radius:24px;border:1px solid var(--edge);background:var(--glass);backdrop-filter:blur(14px)}
.scan-t{color:var(--text);font-size:16px;font-weight:600;margin-bottom:16px}
.scan-bar{height:6px;border-radius:4px;background:rgba(255,255,255,.12);overflow:hidden}
.scan-bar i{display:block;width:40%;height:100%;border-radius:4px;
  background:linear-gradient(90deg,transparent,#FFA53B,#FF4D8D,#8B5CF6,transparent);animation:slide 1.3s ease-in-out infinite}
@keyframes slide{0%{transform:translateX(-110%)}100%{transform:translateX(270%)}}
@media (prefers-reduced-motion:reduce){.scan-bar i{animation:none;width:100%}}

@media (max-width:900px){
  .hero-art{display:none}
  .tagline{margin-left:0}
}
@media (max-width:640px){
  .brand{gap:14px}
  .brand-mark{width:56px;height:56px;flex-basis:56px;border-radius:18px}
  .brand-name{font-size:36px}
  .verdict{padding:26px 22px}
  .v-word{font-size:62px}
  .sec{font-size:28px}
  .opt{grid-template-columns:1fr auto;gap:10px 14px;border-radius:24px}
  .opt .bar{grid-column:1 / -1;order:3}
  .opt .go{grid-column:1 / -1;order:4;text-align:center}
  .alt-head{flex-direction:column;gap:4px}
}
"""

CSS = (
    _CSS.replace("@@tag_w@@", icon_url("tag", "#FFFFFF"))
    .replace("@@arrow_w@@", icon_url("arrow", "#FFFFFF"))
    .replace("@@tag@@", icon_url("tag", "#B9B2FF"))
    .replace("@@dollar@@", icon_url("dollar", "#B9B2FF"))
    .replace("@@arrow@@", icon_url("arrow", "#C7C3EE"))
    .replace("@@headphones@@", icon_url("headphones", "#FF7AB8"))
    .replace("@@search@@", icon_url("search", "#7F9BFF"))
    .replace("@@sparkle@@", icon_url("sparkle", "#A98BFF"))
    .replace("@@globe@@", icon_url("globe", "#9F97FF"))
    .replace("@@robot@@", icon_url("robot", "#C7C3EE"))
)

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
        st.markdown(
            compact(f"""
            <div class="side-head">
              <div class="side-tile">{icon("tag", "#22103F", 32, 2)}</div>
              <div>
                <div class="side-title">Preferences</div>
                <div class="side-sub">Set your country, search depth and model.</div>
              </div>
            </div>
            """),
            unsafe_allow_html=True,
        )
        with st.container(border=True):
            st.markdown(setting_label("globe", "Your country"), unsafe_allow_html=True)
            country = st.selectbox("Your country", COUNTRIES, index=None, key="country",
                                   placeholder="For local sellers and currency", label_visibility="collapsed")
        with st.container(border=True):
            st.markdown(setting_label("search", "Web searches per check"), unsafe_allow_html=True)
            max_searches = int(st.number_input("Web searches per check", min_value=1, max_value=8, value=4, step=1,
                                               key="searches", label_visibility="collapsed",
                                               help="More searches find more sellers but cost more."))
        with st.container(border=True):
            st.markdown(setting_label("cube", "Model"), unsafe_allow_html=True)
            model = st.selectbox("Model", MODELS, index=0, key="model", label_visibility="collapsed")
        st.markdown(
            compact(f'<div class="side-foot">{icon("bolt", "#A98BFF", 22)}<div>Smarter searches.<br>Better deals.</div></div>'),
            unsafe_allow_html=True,
        )

    st.markdown(
        compact(f"""
        <div class="hero">
          <div>
            <div class="brand">
              <div class="brand-mark">{icon("tag", "#1B1049", 44, 2)}</div>
              <div class="brand-name">Price-Check <span class="grad">Sidekick</span></div>
            </div>
            <div class="tagline">Name a product and get a straight answer: buy it now, wait for a better deal, or skip it.</div>
          </div>
          <div class="hero-art">{compact(HERO_SVG)}</div>
        </div>
        """),
        unsafe_allow_html=True,
    )

    with st.form("check"):
        st.markdown(field_label("cube", "Product"), unsafe_allow_html=True)
        st.text_input("Product", key="query", placeholder="Sony WH-1000XM5, or paste a product link",
                      label_visibility="collapsed")
        st.markdown('<div class="hint">Product names work best. Store links often hide their prices.</div>', unsafe_allow_html=True)
        st.markdown(field_label("wallet", "Budget"), unsafe_allow_html=True)
        st.text_input("Budget", key="budget", placeholder="Optional, for example under $250",
                      label_visibility="collapsed")
        submitted = st.form_submit_button("Check price")

    st.markdown('<div class="try">Not sure what to try?</div>', unsafe_allow_html=True)
    cols = st.columns(len(EXAMPLES), gap="medium")
    for i, (col, (name, _)) in enumerate(zip(cols, EXAMPLES)):
        col.button(name, key=f"ex_{i}", on_click=use_example, args=(name,))

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
                    OpenAI(api_key=api_key), query, (country or "").strip(),
                    st.session_state.get("budget", "").strip(), model or DEFAULT_MODEL, max_searches,
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
