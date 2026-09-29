import json
import asyncio
import re
import random
from urllib.parse import quote, unquote, urlencode
import os
import base64
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

# Import the extraction functions and the browser manager
from . import extractor
from .browser_manager import browser_manager

# --- Constants ---
BASE_URL = "https://www.google.com/maps/search/"
SCROLL_PAUSE_TIME = 1.5
MAX_SCROLL_ATTEMPTS_WITHOUT_NEW_LINKS = 5

# --- Helper Functions ---
def create_search_url(query, lang="en", geo_coordinates=None, zoom=None):
    """Creates a Google Maps search URL."""
    params = {'q': query, 'hl': lang}
    return BASE_URL + "?" + urlencode(params)

def generate_random_id(length):
    """Generates a URL-safe random ID, mimicking the Go implementation."""
    num_bytes = (length * 6 + 7) // 8
    random_bytes = os.urandom(num_bytes)
    encoded = base64.urlsafe_b64encode(random_bytes).decode('utf-8')
    return encoded.replace('=', '')[:length]

def _extract_place_name(url: str) -> str:
    """
    Extract the place name from a Google Maps URL.
    Tries regex parsing first, unquotes URL characters, and strips Unicode direction marks.
    """
    if not url:
        return ""
    match = re.search(r'/maps/place/([^/@?]+)', url)
    if match:
        name = unquote(match.group(1)).replace('+', ' ').strip()
        name = re.sub(r'[\u200e\u200f\u202a-\u202e]', '', name)
        if len(name) > 1:
            return name
    return ""

def _extract_place_coords(url: str) -> tuple:
    """Extract lat/lng coordinates from a Google Maps URL."""
    if not url:
        return None, None
    match = re.search(r'@(-?[\d.]+),(-?[\d.]+)', url)
    if match:
        return match.group(1), match.group(2)
    match = re.search(r'!3d(-?[\d.]+)!4d(-?[\d.]+)', url)
    if match:
        return match.group(1), match.group(2)
    return None, None

async def navigate_to_place_bypassing_limited_view(page, url: str) -> bool:
    """
    Navigates to a Google Maps place while bypassing the 'limited view' restriction.
    1. Pre-flight session warm-up on google.com to establish cookies/consent.
    2. Search-based navigation (/maps/search/{name}/@{lat},{lng}) avoiding the limited-view blockade.
    3. Feed disambiguation: matches and clicks the top candidate if search lands on a results list.
    4. Fallback to direct URL if search doesn't land on place details, with secondary bypass if redirect resolves name.
    """
    print(f"Navigating to place with limited-view bypass: {url}")

    # Step 1: Pre-flight session warm-up to establish search cookies
    try:
        await page.goto("https://www.google.com", wait_until="domcontentloaded", timeout=15000)
        await asyncio.sleep(1.0)
        await handle_consent(page)
    except Exception as e:
        print(f"Warm-up navigation skipped/failed: {e}")

    async def _try_search_bypass(target_name: str, target_lat=None, target_lng=None) -> bool:
        if not target_name:
            return False
        encoded_query = quote(target_name)
        if target_lat and target_lng:
            search_url = f"https://www.google.com/maps/search/{encoded_query}/@{target_lat},{target_lng},17z"
        else:
            search_url = f"https://www.google.com/maps/search/{encoded_query}/"

        print(f"Navigating via search bypass: {search_url}")
        try:
            await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2.0)
            await handle_consent(page)

            # Check if search returned a multi-place feed (disambiguation list)
            feed_locator = page.locator('[role="feed"]')
            if await feed_locator.count() > 0 and await feed_locator.first.is_visible():
                print("Search returned a multi-place feed. Matching top candidate...")
                candidate_links = page.locator('[role="feed"] a[href*="/maps/place/"]')
                count = await candidate_links.count()
                matched_link = None
                for i in range(min(count, 5)):
                    link_el = candidate_links.nth(i)
                    aria_label = (await link_el.get_attribute("aria-label")) or ""
                    if target_name.lower() in aria_label.lower() or aria_label.lower() in target_name.lower():
                        print(f"Matched candidate in feed: '{aria_label}'")
                        matched_link = link_el
                        break
                if not matched_link and count > 0:
                    print("No exact title match; selecting top candidate in feed...")
                    matched_link = candidate_links.first

                if matched_link:
                    href = (await matched_link.get_attribute("href")) or ""
                    if href:
                        if href.startswith("/"):
                            href = "https://www.google.com" + href
                        print(f"Navigating directly to candidate canonical URL: {href}")
                        await page.goto(href, wait_until="domcontentloaded", timeout=35000)
                        await asyncio.sleep(2.0)
                        await handle_consent(page)
                    else:
                        await matched_link.click()
                        await asyncio.sleep(2.5)

            # Wait for place details panel or tabs to load
            try:
                await page.locator('div[role="main"], [role="tab"], div[data-review-id]').first.wait_for(state='visible', timeout=8000)
                print("Search-based navigation successful - full page loaded.")
                return True
            except Exception:
                pass
        except Exception as e:
            print(f"Search navigation encountered error: {e}")
        return False

    # Step 2: Extract place name and coordinates from initial URL
    place_name = _extract_place_name(url)
    lat, lng = _extract_place_coords(url)

    if place_name:
        if await _try_search_bypass(place_name, lat, lng):
            return True
        print("Search navigation did not directly open place, falling back to direct URL...")

    # Step 3: Direct URL Fallback
    print(f"Direct fallback navigation to: {url}")
    await page.goto(url, wait_until="domcontentloaded", timeout=40000)
    await asyncio.sleep(2.0)
    await handle_consent(page)

    # Check if shortened URL redirected to a canonical URL that we can now extract from
    resolved_url = page.url or ""
    if not place_name and "/maps/place/" in resolved_url:
        resolved_name = _extract_place_name(resolved_url)
        resolved_lat, resolved_lng = _extract_place_coords(resolved_url)
        if resolved_name and await _is_limited_view(page):
            print(f"Resolved canonical URL '{resolved_name}' in limited view. Rerouting via search bypass...")
            if await _try_search_bypass(resolved_name, resolved_lat, resolved_lng):
                return True

    if await _is_limited_view(page):
        print("  - [WARNING] Google Maps is showing a limited view — reviews may be unavailable.")

    return True

_LIMITED_VIEW_STRINGS = (
    "limited view",
    "vue limitée",                  # French
    "eingeschränkte ansicht",       # German
    "vista limitada",               # Spanish / Portuguese
    "vista limitata",               # Italian
    "תצוגה מוגבלת",                 # Hebrew
    "มุมมองที่จำกัด",                # Thai
    "ограниченный просмотр",        # Russian
    "限定ビュー",                    # Japanese
    "제한된 보기",                   # Korean
    "受限视图", "受限檢視",           # Chinese
    "عرض محدود",                     # Arabic
    "sınırlı görünüm",              # Turkish
    "ograniczony widok",            # Polish
    "beperkte weergave",            # Dutch
)

async def _is_limited_view(page) -> bool:
    """Detect limited-view restriction across languages + structure."""
    try:
        body_text = (await page.inner_text("body") or "").lower()
        for phrase in _LIMITED_VIEW_STRINGS:
            if phrase in body_text:
                return True
    except Exception:
        pass

    # Structural: the sign-in prompt is shown on limited-view pages without tabs
    try:
        sign_in_locator = page.locator('a[data-action="sign in"], a[href*="ServiceLogin"]')
        tabs_locator = page.locator('[role="tab"]')
        if await sign_in_locator.count() > 0 and await tabs_locator.count() == 0:
            return True
    except Exception:
        pass
    return False

def _score_reviews_tab(aria_label: str, tab_text: str, tab_index: str, href: str, tab_class: str) -> float:
    """Calculates weighted score for tab-is-reviews detection."""
    score = 0.0
    aria_label = (aria_label or "").lower()
    tab_text = (tab_text or "").lower()

    if any(w in aria_label for w in extractor.REVIEW_WORDS):
        score += 1.5
    if any(w in tab_text for w in extractor.REVIEW_WORDS):
        score += 1.0

    if any(w in aria_label for w in extractor.NON_REVIEW_TAB_WORDS):
        score -= 1.5
    if any(w in tab_text for w in extractor.NON_REVIEW_TAB_WORDS):
        score -= 1.0

    if tab_index in ("1", "reviews") and score > 0:
        score += 0.25

    if href and ("review" in href.lower() or "rating" in href.lower()):
        score += 1.5

    if any(c in (tab_class or "").lower() for c in ("review", "rating", "g4jrve")):
        score += 0.5

    return score

async def find_and_click_reviews_tab(page, timeout_sec=20) -> bool:
    """
    Finds and activates the Reviews tab using multi-lingual heuristic scoring.
    """
    print("Attempting to find and click Reviews tab...")
    start_time = asyncio.get_event_loop().time()
    tab_selectors = [
        '[role="tab"][aria-label*="review" i]',
        '[role="tab"][aria-label*="avis" i]',
        '[role="tab"][aria-label*="bewertung" i]',
        '[role="tab"][aria-label*="reseña" i]',
        '[role="tab"][aria-label*="recensione" i]',
        '[role="tab"]',
        'button[role="tab"]',
        'div[role="tab"]',
    ]

    while asyncio.get_event_loop().time() - start_time < timeout_sec:
        # Check if already on the active reviews tab
        active_tab = page.locator('[role="tab"][aria-selected="true"]')
        if await active_tab.count() > 0:
            active_text = (((await active_tab.first.get_attribute("aria-label")) or "") + " " + ((await active_tab.first.inner_text()) or "")).lower()
            if any(w in active_text for w in extractor.REVIEW_WORDS):
                print(f"Reviews tab already active: '{active_text.strip()}'.")
                return True
        elif await page.locator('[role="tab"]').count() == 0 and await page.locator('div[data-review-id]').count() > 0:
            # Standalone reviews page without tab bar
            print("No tab bar found, but review cards are present.")
            return True

        for selector in tab_selectors:
            tabs = page.locator(selector)
            count = await tabs.count()
            if count == 0:
                continue

            best_tab = None
            highest_score = 0.0

            for i in range(count):
                tab = tabs.nth(i)
                try:
                    aria_label = (await tab.get_attribute("aria-label")) or ""
                    tab_text = (await tab.inner_text()) or ""
                    tab_index = (await tab.get_attribute("data-tab-index")) or ""
                    href = (await tab.get_attribute("href")) or (await tab.get_attribute("data-href")) or ""
                    tab_class = (await tab.get_attribute("class")) or ""

                    score = _score_reviews_tab(aria_label, tab_text, tab_index, href, tab_class)
                    if score > highest_score and score >= 1.0:
                        highest_score = score
                        best_tab = tab
                except Exception:
                    continue

            if best_tab:
                print(f"Clicking Reviews tab (score: {highest_score})...")
                try:
                    await best_tab.click(timeout=5000)
                except Exception:
                    await best_tab.evaluate("el => el.click()")

                await asyncio.sleep(2.0)
                if await page.locator('div[data-review-id]').count() > 0 or "review" in page.url.lower():
                    print("Successfully activated Reviews tab.")
                    return True

        await asyncio.sleep(1.0)

    print("Could not find or click Reviews tab within timeout.")
    return False

async def set_reviews_sort_newest(page, timeout_sec=10) -> bool:
    """
    Sets the review sort order to 'Newest' via UI dropdown interaction.
    1. Finds and clicks the Sort button (button.HQzyZ, aria-label*="Sort", etc.)
    2. Waits for menu items [role="menuitemradio"] to appear.
    3. Matches text against multilingual 'Newest' options (from extractor.SORT_OPTIONS['newest']).
    4. Falls back to index 1 (Google standard for 'Newest') if text matching doesn't match.
    5. Awaits feed re-render.
    """
    print("Attempting to set review sort order to 'Newest'...")
    sort_button_selectors = [
        'button[data-value="Sort"]',
        'button[aria-label*="Sort" i]',
        'button[aria-label*="sort" i]',
        'button[aria-label*="Trier" i]',
        'button[aria-label*="Ordenar" i]',
        'button[aria-label*="Sortieren" i]',
        'button.HQzyZ[aria-haspopup="true"][aria-label*="sort" i]',
        'button.HQzyZ[aria-haspopup="true"]',
        'button[jsaction*="sort" i]',
        'button[jsaction*="pane.wfvdle84"]',
    ]

    sort_button = None
    for sel in sort_button_selectors:
        loc = page.locator(sel)
        if await loc.count() > 0 and await loc.first.is_visible():
            sort_button = loc.first
            break

    if not sort_button:
        # Fallback XPath
        for kw in ["sort", "Sort", "Trier", "Ordenar", "Sortieren"]:
            loc = page.locator(f"//button[contains(@aria-label, '{kw}') or contains(., '{kw}')]")
            if await loc.count() > 0 and await loc.first.is_visible():
                sort_button = loc.first
                break

    if not sort_button:
        print("  - Sort button not found, continuing with default sort order.")
        return False

    btn_label = (await sort_button.get_attribute("aria-label")) or (await sort_button.inner_text()) or ""
    print(f"  - Found sort button: '{btn_label.strip()}'. Clicking...")

    menu_items_loc = page.locator('[role="menuitemradio"], div[role="menu"] div[data-index], div[role="menuitem"]')
    menu_opened = False
    for attempt in range(2):
        try:
            await sort_button.scroll_into_view_if_needed(timeout=2000)
            await sort_button.click(timeout=3000, force=True)
        except Exception:
            try:
                await sort_button.evaluate("el => el.click()")
            except Exception:
                pass

        try:
            await menu_items_loc.first.wait_for(state="visible", timeout=4000)
            menu_opened = True
            break
        except Exception:
            if attempt == 0:
                await asyncio.sleep(1.5)

    if not menu_opened:
        print("  - Sort dropdown menu did not open, keeping current sort.")
        return False

    count = await menu_items_loc.count()
    if count == 0:
        return False

    newest_keywords = extractor.SORT_OPTIONS.get("newest", ["newest"])
    clicked = False

    # First attempt: match by text
    for i in range(count):
        item = menu_items_loc.nth(i)
        try:
            text = (await item.inner_text() or "").strip().lower()
            if any(kw in text for kw in newest_keywords):
                print(f"  - Found 'Newest' menu item: '{text}'. Clicking...")
                await item.click()
                clicked = True
                break
        except Exception:
            continue

    # Second attempt: fallback to index 1 (Google standard for 'Newest')
    if not clicked and count >= 2:
        print("  - Keyword match failed; selecting index 1 as 'Newest' fallback...")
        try:
            await menu_items_loc.nth(1).click()
            clicked = True
        except Exception as e:
            print(f"  - Failed to click index 1 menu item: {e}")

    if clicked:
        await asyncio.sleep(2.5)  # Wait for reviews feed to refresh
        print("  - Successfully applied 'Newest' sort order.")
        return True

    return False

class LayoutStallException(Exception):
    """Raised when the DOM review scroll container freezes or collapses due to asset blocking."""
    pass

async def scrape_reviews_from_dom(page, max_reviews=100, max_scroll_attempts=40, scroll_idle_limit=5) -> list:
    """
    Scrolls the reviews pane, dynamically expands 'More' buttons, and extracts non-truncated review cards.
    Tracks scroll metrics to detect and handle layout stalls.
    """
    print(f"Beginning DOM review extraction (target: {max_reviews} reviews)...")

    # Ensure at least one review card is rendered before starting extraction
    try:
        await page.wait_for_selector('div[data-review-id]', state='visible', timeout=8000)
    except Exception:
        print("  - Notice: No review cards visible yet. Proceeding with initial scroll...")

    # Pane selectors in order of specificity
    pane_selectors = [
        'div[role="main"] div.m6QErb.DxyBCb.kA9KIf.dS8AEf',
        'div[role="main"] div.m6QErb.DxyBCb',
        'div.m6QErb.DxyBCb',
        'div[role="main"]',
    ]


    selected_pane_sel = None
    for sel in pane_selectors:
        try:
            if await page.locator(sel).count() > 0:
                selected_pane_sel = sel
                break
        except Exception:
            continue

    if not selected_pane_sel:
        print("  - [WARNING] Could not locate reviews scroll pane with known selectors. Using fallback div[role='main'].")
        selected_pane_sel = 'div[role="main"]'

    print(f"  - Using reviews pane selector: {selected_pane_sel}")

    seen_reviews = {}
    idle_count = 0
    attempts = 0
    consecutive_stall_count = 0

    extract_and_scroll_js = """
    (paneSelector) => {
        let pane = document.querySelector(paneSelector);
        if (!pane) {
            pane = document.querySelector('div[role="main"] div.m6QErb.DxyBCb') || document.querySelector('div[role="main"]') || document.body;
        }

        // 1. Expand all visible "More" buttons
        const moreButtons = pane.querySelectorAll('button.kyuRq, button[jsaction*="expandReview"], button[aria-expanded="false"][jsaction*="review" i]');
        moreButtons.forEach(btn => {
            try { btn.click(); } catch (e) {}
        });

        // 2. Extract visible cards
        const cards = pane.querySelectorAll('div[data-review-id]');
        const reviews = [];
        let zeroHeightCount = 0;

        cards.forEach(card => {
            const h = card.offsetHeight || 0;
            if (h === 0) zeroHeightCount++;

            const id = card.getAttribute('data-review-id') || '';
            if (!id) return;

            // Name
            const nameEl = card.querySelector('div[class*="d4r55"]') || card.querySelector('button[data-review-id]');
            const name = nameEl ? (nameEl.textContent || '').trim() : '';

            // Profile Picture
            const imgEl = card.querySelector('button[data-review-id] img') || card.querySelector('img[src*="googleusercontent"]');
            const profile_picture = imgEl ? (imgEl.src || '') : '';

            // Rating
            let rating = 0.0;
            const ratingEl = card.querySelector('span[role="img"][aria-label*="star" i], span[role="img"][aria-label*="etoile" i], span[role="img"][aria-label*="étoile" i], span[role="img"][aria-label], span[class*="kvMYJc"]');
            if (ratingEl) {
                const label = ratingEl.getAttribute('aria-label') || '';
                const m = label.replace(',', '.').match(/[\\d.]+/);
                if (m) {
                    const r = parseFloat(m[0]);
                    if (r > 0 && r <= 5) rating = r;
                }
            }

            // Description / Text
            let description = '';
            const textSelectors = ['span[jsname="bN97Pc"]', 'span[jsname="fbQN7e"]', 'div.MyEned span.wiI7pd', 'span.wiI7pd'];
            for (const sel of textSelectors) {
                const el = card.querySelector(sel);
                if (el && el.textContent && el.textContent.trim()) {
                    description = el.textContent.trim();
                    break;
                }
            }

            // Date / When
            let when = '';
            const dateEl = card.querySelector('span[class*="rsqaWe"], span[class*="xRkPPb"]');
            if (dateEl) {
                when = (dateEl.textContent || '').trim();
            }

            // Images
            const images = [];
            const photoBtns = card.querySelectorAll('button.Tya61d, button[aria-label*="Photo" i][style*="url"], button[data-photo-index]');
            photoBtns.forEach(pbtn => {
                const style = pbtn.getAttribute('style') || '';
                const m = style.match(/url\\(["']?([^"']+)["']?\\)/);
                if (m && m[1] && !images.includes(m[1])) {
                    images.push(m[1]);
                }
            });

            reviews.push({
                review_id: id,
                name: name,
                profile_picture: profile_picture,
                rating: rating,
                description: description,
                when: when,
                images: images
            });
        });

        // 3. Container metrics
        const metrics = {
            scrollHeight: pane.scrollHeight || 0,
            clientHeight: pane.clientHeight || 0,
            scrollTop: pane.scrollTop || 0,
            cardCount: cards.length,
            zeroHeightCount: zeroHeightCount
        };

        // 4. Scroll pane down
        pane.scrollBy(0, pane.scrollHeight || 1000);

        return { reviews, metrics };
    }
    """

    while attempts < max_scroll_attempts:
        if len(seen_reviews) >= max_reviews:
            print(f"  - Reached target max_reviews limit ({len(seen_reviews)}/{max_reviews}).")
            break

        # Check for rate-limiting
        current_url = (page.url or "").lower()
        if "/sorry/" in current_url or "recaptcha" in current_url:
            print("  - [WARNING] Rate-limit interstitial detected during scroll.")
            break

        try:
            result = await page.evaluate(extract_and_scroll_js, selected_pane_sel)
        except Exception as e:
            print(f"  - Error executing extraction JS: {e}")
            break

        extracted_cards = result.get("reviews", [])
        metrics = result.get("metrics", {})

        new_in_batch = 0
        for r in extracted_cards:
            rid = r.get("review_id")
            if rid and rid not in seen_reviews:
                seen_reviews[rid] = r
                new_in_batch += 1

        print(f"  - Harvested {len(seen_reviews)} unique reviews so far (+{new_in_batch} this scroll)...")

        # Telemetry check for layout stall
        current_scroll_height = metrics.get("scrollHeight", 0)
        client_height = metrics.get("clientHeight", 0)
        zero_height = metrics.get("zeroHeightCount", 0)

        # Detect collapsed container or zero-height card anomaly
        if zero_height > 0 or (current_scroll_height == client_height and len(extracted_cards) > 0):
            consecutive_stall_count += 1
            print(f"  - [WARN] Potential layout stall detected (zero_height={zero_height}, scrollH={current_scroll_height}, clientH={client_height}, streak={consecutive_stall_count}).")
            if consecutive_stall_count >= 3:
                raise LayoutStallException(f"Layout stalled with zero-height elements or collapsed container: {metrics}")
        else:
            consecutive_stall_count = 0

        # Idle count check
        if new_in_batch == 0:
            if len(seen_reviews) > 0:
                idle_count += 1
            else:
                # Still waiting for initial cards to render; provide brief grace period
                await asyncio.sleep(1.0)
                if attempts >= 3:
                    idle_count += 1
            # Execute nudge scroll to re-trigger virtualization
            try:
                await page.evaluate(f"""(sel) => {{
                    const p = document.querySelector(sel) || document.querySelector('div[role="main"]');
                    if (p) {{ p.scrollBy(0, -300); }}
                }}""", selected_pane_sel)
                await asyncio.sleep(0.4)
                await page.evaluate(f"""(sel) => {{
                    const p = document.querySelector(sel) || document.querySelector('div[role="main"]');
                    if (p) {{ p.scrollBy(0, 800); }}
                }}""", selected_pane_sel)
            except Exception:
                pass

            if idle_count >= scroll_idle_limit:
                print(f"  - No new reviews found after {scroll_idle_limit} consecutive attempts. Reached end of available reviews.")
                break
        else:
            idle_count = 0

        # Check end of list marker
        end_marker = page.locator("//span[contains(text(), \"reached the end of the list\") or contains(text(), \"You've reached the end\")]")
        if await end_marker.count() > 0:
            print("  - Reached Google Maps end-of-list marker.")
            break

        attempts += 1
        await asyncio.sleep(random.uniform(1.0, 1.6))

    # Return reviews in harvested chronological order (Newest first)
    return list(seen_reviews.values())[:max_reviews]

async def fetch_all_reviews(page, place_link, place_id=None, max_reviews=None):
    """
    Fetches user reviews by navigating through Google Maps UI:
    1. Bypasses 'limited view' using search-based navigation if not already on the place page.
    2. Activates the Reviews tab using multi-lingual heuristic scoring.
    3. Sets review sort order to 'Newest'.
    4. Virtual-scrolls and extracts review cards from the live DOM.
    """
    if max_reviews is None:
        max_reviews = extractor.REVIEW_SELECTION_COUNT

    # Step 1: Ensure we are on the place page (and not locked in limited view)
    current_url = page.url or ""
    if "google.com/maps" not in current_url:
        await navigate_to_place_bypassing_limited_view(page, place_link)

    # Step 2: Activate Reviews Tab
    tab_clicked = await find_and_click_reviews_tab(page)
    if not tab_clicked:
        print("  - [WARNING] Could not activate reviews tab. Attempting direct DOM scrape anyway...")

    # Step 3: Set sort order to 'Newest'
    await asyncio.sleep(1.5)
    try:
        await set_reviews_sort_newest(page)
    except Exception as e:
        print(f"  - Notice: Could not set sort to newest: {e}")

    # Step 4: Harvest reviews from DOM
    reviews = await scrape_reviews_from_dom(page, max_reviews=max_reviews)
    return reviews

# --- Main Scraping Logic ---
async def scrape_reviews_only(context, link, semaphore, max_reviews=None, lang="en"):
    """
    Scrapes ONLY user reviews for a single place link.
    Optimized for performance by skipping full place details extraction and blocking assets.
    Implements:
    - Adaptive image de-blocking retry on LayoutStallException.
    - Rate-limit and CAPTCHA interception.
    """
    async with semaphore:
        async def _attempt_scrape(active_context, is_retry=False):
            page = None
            try:
                page = await active_context.new_page()
                print(f"Processing link for reviews only (retry={is_retry}): {link}")

                # Bypass limited view with search-based navigation
                await navigate_to_place_bypassing_limited_view(page, link)

                resolved_url = page.url or link
                print(f"  - Resolved URL: {resolved_url}")

                # Check for rate-limiting
                if "/sorry/" in resolved_url.lower() or "recaptcha" in resolved_url.lower() or "captcha" in resolved_url.lower():
                    print(f"  - [RATE LIMITED] Detected Google rate-limit/CAPTCHA page: {resolved_url}")
                    return {
                        "link": link,
                        "resolved_url": resolved_url,
                        "user_reviews": [],
                        "status": "rate_limited",
                        "error": "Google rate-limit or CAPTCHA detected."
                    }

                all_reviews = await fetch_all_reviews(page, resolved_url, max_reviews=max_reviews)

                # Process reviews
                user_reviews = await asyncio.to_thread(extractor.process_and_select_reviews, all_reviews, max_reviews)

                return {
                    "link": link,
                    "resolved_url": resolved_url,
                    "user_reviews": user_reviews or [],
                    "status": "success"
                }
            finally:
                if page:
                    await page.close()

        # Primary execution
        try:
            return await _attempt_scrape(context, is_retry=False)
        except LayoutStallException as stall_err:
            print(f"  - [FALLBACK] Layout stall detected with blocked images: {stall_err}. Retrying once with block_resources=False...")
            fallback_context = None
            try:
                fallback_context = await browser_manager.get_context(lang=lang, block_resources=False)
                return await _attempt_scrape(fallback_context, is_retry=True)
            except Exception as retry_err:
                print(f"  - [ERROR] Fallback retry failed for {link}: {retry_err}")
                return {"link": link, "status": "error", "error": f"Fallback retry failed: {retry_err}"}
            finally:
                if fallback_context:
                    await fallback_context.close()
        except PlaywrightTimeoutError:
            print(f"  - Timeout processing: {link}")
            return {"link": link, "status": "timeout", "error": "Timeout navigating to the link."}
        except Exception as e:
            print(f"  - Error processing {link}: {e}")
            return {"link": link, "status": "error", "error": str(e)}

async def scrape_google_maps(query, max_places=None, lang="en", extract_reviews=False, max_reviews=None):
    """
    Scrapes Google Maps for places based on a query using a shared browser context.
    """
    results = []
    place_links = set()
    scroll_attempts_no_new = 0
    context = None

    try:
        # Use a single page for the initial search and link gathering
        context = await browser_manager.get_context(lang=lang)
        page = await context.new_page()
        if not page:
            raise Exception("Failed to create a new browser page.")

        search_url = create_search_url(query, lang)
        print(f"Navigating to search URL: {search_url}")
        await page.goto(search_url, wait_until='domcontentloaded')
        await asyncio.sleep(2)

        await handle_consent(page)

        print("Scrolling to load places...")
        feed_selector = '[role="feed"]'
        try:
            await page.wait_for_selector(feed_selector, state='visible', timeout=25000)
        except PlaywrightTimeoutError:
            if "/maps/place/" in page.url:
                print("Detected single place page.")
                place_links.add(page.url)
            else:
                print(f"Error: Feed element '{feed_selector}' not found. Taking screenshot.")
                await page.screenshot(path='feed_not_found_screenshot.png')
                return []

        if await page.locator(feed_selector).count() > 0:
            # Scrolling logic remains the same
            last_height = await page.evaluate(f'document.querySelector(\'{feed_selector}\').scrollHeight')
            while True:
                await page.evaluate(f'document.querySelector(\'{feed_selector}\').scrollTop = document.querySelector(\'{feed_selector}\').scrollHeight')
                await asyncio.sleep(SCROLL_PAUSE_TIME)

                current_links_list = await page.locator(f'{feed_selector} a[href*="/maps/place/"]').evaluate_all('elements => elements.map(a => a.href)')
                current_links = set(current_links_list)
                new_links_found = len(current_links - place_links) > 0
                place_links.update(current_links)
                print(f"Found {len(place_links)} unique place links so far...")

                if max_places is not None and len(place_links) >= max_places:
                    print(f"Reached max_places limit ({max_places}).")
                    place_links = set(list(place_links)[:max_places])
                    break

                new_height = await page.evaluate(f'document.querySelector(\'{feed_selector}\').scrollHeight')
                if new_height == last_height:
                    end_marker_xpath = "//span[contains(text(), \"You've reached the end of the list.\")]"
                    if await page.locator(end_marker_xpath).count() > 0:
                        print("Reached the end of the results list.")
                        break
                    else:
                        if not new_links_found:
                            scroll_attempts_no_new += 1
                            if scroll_attempts_no_new >= MAX_SCROLL_ATTEMPTS_WITHOUT_NEW_LINKS:
                                print("Stopping scroll due to lack of new links.")
                                break
                        else:
                            scroll_attempts_no_new = 0
                else:
                    last_height = new_height
                    scroll_attempts_no_new = 0
        
        await page.close() # Close the initial search page

        # --- Scraping Individual Places Concurrently ---
        if place_links:
            print(f"\nScraping details for {len(place_links)} places concurrently...")
            CONCURRENCY_LIMIT = 15
            semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)

            tasks = [scrape_place_details(context, link, extract_reviews, semaphore, max_reviews=max_reviews) for link in place_links]
            scraped_data_list = await asyncio.gather(*tasks)
            results = [data for data in scraped_data_list if data is not None]

    except Exception as e:
        print(f"An error occurred during scraping: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if context:
            await context.close()

    print(f"\nScraping finished. Found details for {len(results)} places.")
    return results

async def scrape_place_details(context, link, extract_reviews, semaphore, max_reviews=None):
    """Scrapes details for a single place link."""
    async with semaphore:
        page = None
        try:
            page = await context.new_page()
            print(f"Processing link: {link}")
            await page.goto(link, wait_until='domcontentloaded')
            
            # Wait for main content to ensure semantic attributes are rendered
            try:
                await page.wait_for_selector('div[role="main"]', timeout=5000)
            except:
                pass
            
            all_reviews = None
            if extract_reviews:
                print(f"  - Extracting all user reviews for: {link}")
                all_reviews = await fetch_all_reviews(page, link, max_reviews=max_reviews)

            html_content = await page.content()
            place_data = await asyncio.to_thread(extractor.extract_place_data, html_content, all_reviews, max_reviews)

            if place_data:
                place_data['link'] = link
                return place_data
            else:
                print(f"  - Failed to extract data for: {link}")
                return None

        except PlaywrightTimeoutError:
            print(f"  - Timeout navigating to or processing: {link}")
            return None
        except Exception as e:
            print(f"  - Error processing {link}: {e}")
            return None
        finally:
            if page:
                await page.close()


async def handle_consent(page):
    """
    Handles Google consent forms if they appear.
    Does not block or fail if no consent form is present.
    """
    consent_selectors = [
        "//button[.//span[contains(text(), 'Accept all') or contains(text(), 'Reject all') or contains(text(), 'I agree')]]",
        "form[action*='consent.google.com'] button",
        "button[aria-label*='Accept' i]",
        "button[aria-label*='Agree' i]",
        "button:has-text('Accept all')",
        "button:has-text('Reject all')",
        "button:has-text('Alles akzeptieren')",
        "button:has-text('Tout accepter')",
        "button:has-text('Aceptar todo')",
    ]
    for sel in consent_selectors:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=1000):
                print(f"Consent form detected ({sel}). Clicking it...")
                await btn.click()
                await asyncio.sleep(1)
                return
        except Exception:
            continue