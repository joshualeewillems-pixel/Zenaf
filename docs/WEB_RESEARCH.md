# Web Research (DuckDuckGo search)

## Is it actually searching the web?

**Yes.** The Web Research mode uses the [duckduckgo-search](https://pypi.org/project/duckduckgo-search/) Python library to run real web searches via DuckDuckGo. No API key is required.

## What you need to do

1. **Install the dependency** (if not already):
   ```bash
   pip install duckduckgo-search
   ```
   Or install all API dependencies from the repo root:
   ```bash
   pip install -r api/requirements.txt
   ```

2. **Use it in the app:**
   - In the Workspace Organizer, open the mode dropdown and select **Web Research**.
   - Enter a search query in the query box that appears.
   - Run the request (e.g. use the main “Run” action for the selected mode). The app sends `POST /run` with `mode: "web_research"` and `params: { query: "your query" }`.
   - Results appear as top findings and sources; the agent thread shows a short summary.

## If it doesn’t work

- **“Web research requires: pip install duckduckgo-search”**  
  The package isn’t installed or isn’t in the same Python environment as the API. Install it as above and restart the API server.

- **RatelimitException / timeout / other errors**  
  DuckDuckGo may rate-limit or block some programmatic traffic. The backend returns the error in the response; the UI shows it in the result area. You can retry later or use a proxy (see the library docs).

## Backend flow

- **API:** `POST /run` with `mode: "web_research"` and `params.query` → `_run_web_research(params)`.
- **Engine:** `local_ai.zenaf_tools.web_research(query)` → `DDGS().text(query, max_results=5)` → returns `query`, `findings`, `sources`, `notes`.
- **Frontend:** Displays `top_findings` and uses the result in the agent thread.
