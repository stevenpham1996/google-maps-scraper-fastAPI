# Refactoring Plan: Google Maps Reviews Scraper — "Limited View" Bypass & DOM Extraction Engine

## Checklist

- [x] **Parent Task 1: Stealth Hardening, Context Provisioning & Concurrency Calibration**
    - [x] Sub-task 1.1: Update BrowserManager._start_browser launch arguments in browser_manager.py with anti-automation flags (--disable-blink-features=AutomationControlled).
    - [x] Sub-task 1.2: Update BrowserManager.get_context in browser_manager.py to inject CDP stealth init scripts masking navigator.webdriver, plugins, and languages.
    - [x] Sub-task 1.3: Calibrate concurrency and task dispatching jitter in main_api.py with REVIEW_SCRAPE_CONCURRENCY env override (default 16 for 48 threads) and 150-350ms launch stagger.
- [x] **Parent Task 2: Search Navigation & Feed Disambiguation Engine**
    - [x] Sub-task 2.1: Implement _extract_place_name and _extract_place_coords in scraper.py.
    - [x] Sub-task 2.2: Implement navigate_to_place_bypassing_limited_view in scraper.py with google.com warm-up, /maps/search/ translation, feed disambiguation matching, and direct URL fallback.
    - [x] Sub-task 2.3: Implement _is_limited_view validator in scraper.py checking multilingual strings and structural sign-in signals.
- [x] **Parent Task 3: Tab Activation, "Newest" Sorting & Virtual DOM Scroll Engine**
    - [x] Sub-task 3.1: Define multilingual keywords and selector constants in extractor.py (REVIEW_WORDS, NON_REVIEW_TAB_WORDS, SORT_OPTIONS, MORE_BTN, TEXT_SELECTORS, RATING_SELECTORS, DATE_SELECTORS).
    - [x] Sub-task 3.2: Implement find_and_click_reviews_tab in scraper.py with weighted heuristic scoring.
    - [x] Sub-task 3.3: Implement set_reviews_sort_newest in scraper.py with dropdown opening, keyword matching, and nth(1) fallback.
    - [x] Sub-task 3.4: Implement the in-browser batch expansion and DOM review card extractor with scrolling loop in scraper.py.
    - [x] Sub-task 3.5: Refactor fetch_all_reviews in scraper.py to route through the DOM extraction engine instead of Protobuf RPC.
- [x] **Parent Task 4: Adaptive Image De-Blocking Watchdog & Rate-Limit Interception**
    - [x] Sub-task 4.1: Implement container metrics probe and LayoutStallException in scraper.py for layout stall and zero-height card detection.
    - [x] Sub-task 4.2: Implement single-retry fallback in scraper.py (scrape_reviews_only) to re-execute stalled URLs in a fresh context with block_resources=False.
    - [x] Sub-task 4.3: Implement rate-limit and CAPTCHA detection for /sorry/ URLs returning structured failure objects.
- [x] **Parent Task 5: Pipeline Normalization, Request Models & End-to-End Verification**
    - [x] Sub-task 5.1: Update ReviewsRequest and API endpoints in main_api.py with optional max_reviews parameter (default 100, capped at REVIEW_CANDIDATE_POOL_SIZE = 300).
    - [x] Sub-task 5.2: Update extractor.py to return harvested reviews in strict chronological "Newest" order up to max_reviews without random sampling.
    - [x] Sub-task 5.3: Validate end-to-end review scraping with test script and verify that review descriptions are populated and non-empty.

## Relevant Files

### Files to be Modified:
- `gmaps_scraper_server/browser_manager.py`
- `gmaps_scraper_server/scraper.py`
- `gmaps_scraper_server/extractor.py`
- `gmaps_scraper_server/main_api.py`

### Progress Tracking:
- `dev-docs/task-completion-update.txt`
