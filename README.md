#Price-Check Sidekick

Paste a product name or link -> the agent searches the web -> BUY / WAIT / SKIP verdict with sellers and alternatives.

Run
pip install -r requirements.txt
export OPENAI_API_KEY=sk-...        # Windows: set OPENAI_API_KEY=sk-...
streamlit run app.py
Cost control
Default model: gpt-5-mini (change in sidebar)
"Max web searches" slider caps searches per check (each search is billed)
Set a monthly budget limit in the OpenAI dashboard
Demo tips
Try 2-3 products: one good deal, one overpriced, one with a new model coming
Record with the sidebar set to 3 searches for a fast response
