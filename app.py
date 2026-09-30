"""Price-Check Sidekick: paste a product name or link, get a BUY / WAIT / SKIP verdict.

Run:  streamlit run app.py
"""
import json
import os

import streamlit as st
from openai import OpenAI

DEFAULT_MODEL = "gpt-5-mini"

SYSTEM_PROMPT = """You are Price-Check Sidekick, a sharp, honest shopping assistant.

Given a product name or link, use web search to:
1. Identify the exact product.
2. Find the current price at 2-4 different sellers (prefer trusted retailers).
3. Find 1-2 good alternatives (cheaper or better value).
4. Judge whether to BUY now, WAIT (a better deal or newer model is likely soon), or SKIP.

Rules:
- If the input is a link or an ASIN/SKU, first identify the product NAME, then search by name. Do not rely on one page: Amazon often hides prices from scrapers.
- Search at least 3 different retailers (for example Walmart, Target, Ulta, Best Buy, the brand's own site) before giving up on a price.
- Every "url" must be a specific product page. Never use a homepage like https://www.amazon.com/.
- If you verified fewer than 2 real prices, set verdict to "UNSURE" instead of guessing BUY/WAIT/SKIP.
- Only report prices you actually found in search results. Never invent prices or URLs.
- If you cannot find a price, say so in the note and leave price as "unknown".
- Be brief and concrete. No marketing language.
- Respect the user's budget if given.

Reply with ONLY a JSON object (no markdown fences, no extra text) in this shape:
{
  "product": "exact product name",
  "verdict": "BUY" | "WAIT" | "SKIP" | "UNSURE",
  "confidence": "low" | "medium" | "high",
  "one_line": "one sentence verdict summary",
  "price_range": "e.g. $299 - $349",
  "options": [
    {"seller": "...", "price": "...", "note": "...", "url": "https://..."}
  ],
  "alternatives": [
    {"name": "...", "price": "...", "why": "...", "url": "https://..."}
  ],
  "reasons": ["short reason 1", "short reason 2", "short reason 3"]
}"""

VERDICT_STYLE = {
    "BUY": ("#1b8a3d", "Buy now"),
    "WAIT": ("#c98a00", "Wait"),
    "SKIP": ("#c0392b", "Skip it"),
    "UNSURE": ("#6c757d", "Not enough data"),
}


def parse_json(text: str) -> dict:
    """Pull the JSON object out of the model reply, even if it added extra text."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON found in model reply")
    return json.loads(text[start : end + 1])


def check_price(client, query, country, budget, model, max_searches):
    user_msg = f"Product: {query}"
    if budget:
        user_msg += f"\nMy budget: {budget}"
    if country:
        user_msg += f"\nI am shopping in: {country}. Prefer sellers and currency there."

    tool = {"type": "web_search"}
    kwargs = dict(
        model=model,
        instructions=SYSTEM_PROMPT,
        input=user_msg,
        tools=[tool],
        max_tool_calls=max_searches,
    )
    # Reasoning models accept an effort setting; keep it low for speed and cost.
    if model.startswith(("gpt-5", "o")):
        kwargs["reasoning"] = {"effort": "low"}

    resp = client.responses.create(**kwargs)
    searches = sum(1 for item in resp.output if item.type == "web_search_call")
    return parse_json(resp.output_text), resp.usage, searches


def render(result, usage, searches):
    verdict = str(result.get("verdict", "WAIT")).upper()
    color, label = VERDICT_STYLE.get(verdict, VERDICT_STYLE["WAIT"])

    st.markdown(
        f"""
        <div style="border-left:8px solid {color};padding:12px 18px;
                    background:rgba(128,128,128,0.08);border-radius:8px;">
          <div style="font-size:14px;opacity:.7">{result.get('product', '')}</div>
          <div style="font-size:34px;font-weight:700;color:{color}">{label}</div>
          <div style="font-size:16px">{result.get('one_line', '')}</div>
          <div style="font-size:13px;opacity:.7;margin-top:6px">
            Confidence: {result.get('confidence', '?')} &nbsp;|&nbsp;
            Price range: {result.get('price_range', '?')}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.subheader("Why")
    for r in result.get("reasons", []):
        st.markdown(f"- {r}")

    options = result.get("options", [])
    if options:
        st.subheader("Where to buy")
        for o in options:
            link = f" [link]({o['url']})" if o.get("url") else ""
            st.markdown(f"**{o.get('seller', '?')}**: {o.get('price', '?')}: {o.get('note', '')}{link}")

    alts = result.get("alternatives", [])
    if alts:
        st.subheader("Alternatives")
        for a in alts:
            link = f" [link]({a['url']})" if a.get("url") else ""
            st.markdown(f"**{a.get('name', '?')}** ({a.get('price', '?')}): {a.get('why', '')}{link}")

    st.caption(
        f"{searches} web searches | {usage.input_tokens} tokens in, "
        f"{usage.output_tokens} tokens out"
    )


def main():
    st.set_page_config(page_title="Price-Check Sidekick", page_icon="🛒")
    st.title("🛒 Price-Check Sidekick")
    st.write("Paste a product name or link. I'll search the web and tell you: **buy, wait, or skip**.")

    with st.sidebar:
        st.header("Settings")
        api_key = st.text_input("OpenAI API key", type="password",
                                value=os.getenv("OPENAI_API_KEY", ""))
        model = st.text_input("Model", value=DEFAULT_MODEL)
        country = st.text_input("Your country (optional)", placeholder="e.g. Bangladesh")
        max_searches = st.slider("Max web searches per check", 1, 8, 5,
                                 help="Each search costs money. Lower = cheaper.")

    query = st.text_input("Product name or link",
                          placeholder="Sony WH-1000XM5 or https://...")
    budget = st.text_input("Budget (optional)", placeholder="e.g. under $250")

    if st.button("Check price", type="primary", disabled=not query):
        if not api_key:
            st.error("Add your OpenAI API key in the sidebar or set OPENAI_API_KEY.")
            return
        client = OpenAI(api_key=api_key)
        with st.spinner("Searching prices..."):
            try:
                result, usage, searches = check_price(
                    client, query, country, budget, model, max_searches
                )
            except Exception as e:
                st.error(f"Something went wrong: {e}")
                return
        render(result, usage, searches)


if __name__ == "__main__":
    main()
