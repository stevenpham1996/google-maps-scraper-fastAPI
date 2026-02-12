# Refactoring Plan: Multi-Layer Data Integrity & Extraction Stabilization

## Checklist

- [x] **Parent Task 1:** Implement Atomic Field-Level Merging in Persistence Layer
    - [x] Sub-task 1.1: Implement cross-platform file locking in `csv_writer.py` to prevent concurrent corruption.
    - [x] Sub-task 1.2: Refactor `save_to_csv` to perform field-level merging (Deep Merge) instead of full record replacement.
    - [x] Sub-task 1.3: Implement weighted completeness scoring in `csv_writer.py` (prioritize Reviews and Hours over metadata).
- [x] **Parent Task 2:** Stabilize Scraper Timing and Snapshot Accuracy
    - [x] Sub-task 2.1: Update `scraper.py` to wait for specific UI selectors (e.g., side panel title `h1.DUwDvf`) instead of generic DOM load.
    - [x] Sub-task 2.2: Implement optional click interaction for lazy-loaded sections (e.g., expanding 'Hours' to capture full week schedule).
- [x] **Parent Task 3:** Refine DOM Extraction Patterns and Fallback Logic
    - [x] Sub-task 3.1: Refine thumbnail regex to exclude map tile URLs (`vt/pb`) and prioritize `googleusercontent.com/p/` photo URLs.
    - [x] Sub-task 3.2: Generalize image regex to support all `lh\d` subdomains and high-resolution resolution parameters.
    - [x] Sub-task 3.3: Update price regex to support deep-nested `<span>` structures and handle en-dash (`–`) in price ranges.
- [x] **Parent Task 4:** Correct Data Model Extraction Paths and Placeholder Handling
    - [x] Sub-task 4.1: Remove index `18` from address extraction paths in `extractor.py` to prevent CID/FID strings from masking actual addresses.
    - [x] Sub-task 4.2: Update `reviews_count` logic to treat value `10112` as a placeholder and trigger DOM-based fallback or RPC review count.

## Relevant Files

### Files to be Modified:
- `gmaps_scraper_server/extractor.py`
- `gmaps_scraper_server/scraper.py`
- `gmaps_scraper_server/csv_writer.py`
- `gmaps_scraper_server/main_api.py`

## Notes
- **Deduplication Priority:** The system now prioritizes retaining data from older records (like reviews) if newer scrapes fail to capture them, using field-level merging.
- **Timing Regression Fix:** Navigation wait condition was changed from `networkidle` to `commit` to prevent timeouts on Google Maps. A 20s selector wait for `h1.DUwDvf` plus a 2s fixed delay ensures the UI is ready without requiring absolute network silence.
- **Concurrency:** Reduced to 10 concurrent pages to stabilize network throughput.
- **Verification:** Merging preservation, placeholder ignoring, and refined regex matching verified via test suite.
