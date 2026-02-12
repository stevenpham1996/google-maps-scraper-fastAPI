# gmaps_scraper_server/extractor.py

import json
import re
import random
import os
import time
import shutil

# --- CONSTANTS FOR REVIEW SELECTION ---
# The number of reviews to be randomly selected and stored.
REVIEW_SELECTION_COUNT = 100
# A larger pool of top-ranked reviews from which to randomly select.
# This introduces randomness while still favoring high-quality reviews.
REVIEW_CANDIDATE_POOL_SIZE = 300
# A set of placeholder usernames for efficient lookup.
PLACEHOLDER_USERNAMES = {"google user", "anonymous user", "unknown", "profile name"}


def safe_get(data, *keys):
    """
    Safely retrieves nested data from a dictionary or list using a sequence of keys/indices.
    Returns None if any key/index is not found or if the data structure is invalid.
    """
    current = data
    for key in keys:
        try:
            if isinstance(current, list):
                if isinstance(key, int) and 0 <= key < len(current):
                    current = current[key]
                else:
                    return None
            elif isinstance(current, dict):
                if key in current:
                    current = current[key]
                else:
                    return None
            else:
                return None
        except (IndexError, TypeError, KeyError) as e:
            return None
    return current

def extract_initial_json(html_content):
    """
    Extracts the JSON string assigned to window.APP_INITIALIZATION_STATE from HTML content.
    """
    try:
        # Pattern 1: Standard pattern with APP_FLAGS suffix
        match = re.search(r';window\.APP_INITIALIZATION_STATE\s*=\s*(.*?);window\.APP_FLAGS', html_content, re.DOTALL)
        if match:
             return match.group(1)
        
        # Pattern 2: Sometimes it ends with a generic semicolon or script tag end
        match = re.search(r';window\.APP_INITIALIZATION_STATE\s*=\s*(.*?);', html_content, re.DOTALL)
        if match:
             return match.group(1)

        return None
    except Exception as e:
        print(f"Error extracting JSON string: {e}")
        return None

def extract_json_ld(html_content):
    """
    Extracts and parses the JSON-LD data from the HTML.
    This provides rich data (Address, Phone, Geo) even when the internal API blob is missing it.
    """
    try:
        # Simple regex to find the script tag content. 
        # Non-greedy match until the closing tag.
        match = re.search(r'<script type="application/ld\+json">(.*?)</script>', html_content, re.DOTALL)
        if match:
            json_str = match.group(1)
            # print("JSON-LD found!")
            return json.loads(json_str)
        else:
            print("JSON-LD regex match failed.")
            # Save HTML for inspection
            save_debug_content(html_content, prefix="failed_json_ld_html", extension="html")
    except Exception as e:
        print(f"Error extracting JSON-LD: {e}")
    return None


def extract_from_dom(html_content):
    """
    Extracts data directly from HTML using regex pattern matching on DOM elements.
    This is a fallback for when JSON-LD and internal API blobs are missing or incomplete.
    Targeting specific aria-labels and class names observed in failure artifacts.
    """
    data = {}
    try:
        # Address
        # Pattern: aria-label="Address: ..."
        address_match = re.search(r'aria-label="Address:\s*([^"]+)"', html_content)
        if address_match:
            data["address"] = address_match.group(1).strip()

        # Phone
        # Pattern: aria-label="Phone: ..."
        phone_match = re.search(r'aria-label="Phone:\s*([^"]+)"', html_content)
        if phone_match:
            data["phone"] = phone_match.group(1).strip()

        # Website
        # Pattern: Look for href in the anchor that has aria-label="Website:..."
        # We try both orders of attributes just in case
        website_match = re.search(r'aria-label="Website:[^"]*"[^>]*href="([^"]+)"', html_content)
        if not website_match:
            website_match = re.search(r'href="([^"]+)"[^>]*aria-label="Website:[^"]*"', html_content)
        
        if website_match:
            raw_url = website_match.group(1).strip()
            # Clean Google redirect if present
            if "/url?q=" in raw_url:
                # Extract the actual URL from q parameter
                # raw_url is like /url?q=https://...&opi=...
                # Simple regex or split
                q_match = re.search(r'q=([^&]+)', raw_url)
                if q_match:
                    from urllib.parse import unquote
                    data["website"] = unquote(q_match.group(1)).rstrip('/')
                else:
                    data["website"] = raw_url.rstrip('/')
            else:
                 data["website"] = raw_url.rstrip('/')
        else:
            # Fallback to just the text in aria-label if href not found
            website_text_match = re.search(r'aria-label="Website:\s*([^\"]+)"', html_content)
            if website_text_match:
                data["website"] = website_text_match.group(1).strip().rstrip('/')

        # Rating
        # Pattern: aria-label="4.6 stars"
        rating_match = re.search(r'aria-label="([\d.]+)\s*stars"', html_content)
        if rating_match:
            try:
                data["rating"] = float(rating_match.group(1))
            except ValueError:
                pass

        # Reviews Count
        # Pattern: aria-label="1,260 reviews"
        reviews_match = re.search(r'aria-label="([\d,]+)\s*reviews"', html_content)
        if reviews_match:
            try:
                count_str = reviews_match.group(1).replace(',', '')
                val = int(count_str)
                # Ignore placeholder 10112
                if val != 10112:
                    data["reviews_count"] = val
            except ValueError:
                pass

        # Price Range
        # Pattern: Handles nested spans <span><span>$100–200</span></span> and en-dashes
        price_match = re.search(r'(?:<span[^>]*>\s*)+([$€£¥]\d+(?:[–-]\d+)?)(?:\s*</span>)+', html_content)
        if not price_match:
            # Fallback to class-based matching
            price_match = re.search(r'class="[^"]*price[^"]*">[^<]*<span>([^<]+)</span>', html_content)
        
        if price_match:
            data["price_range"] = price_match.group(1).strip()
        
        # Open Hours
        # Artifact shows: <div class="kp-hours-item"><span>Friday: 2–9 PM</span></div>
        # ALSO check for aria-labels on the table rows or divs if present.
        # "Monday, 9 AM to 5 PM"
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        open_hours = {}
        
        # Strategy 1: aria-labels with "Day, Time"
        for day in days:
            # Regex to find "Monday, 9AM to 5PM" or "Monday, Closed"
            # format in aria-label often: "Monday, 9:00 AM – 5:00 PM"
            day_regex = fr'aria-label="({day}, [^"]+)"'
            match = re.search(day_regex, html_content)
            if match:
                full_text = match.group(1)
                # Remove day from text to get hours
                time_text = full_text.replace(f"{day},", "").strip()
                # Clean up "Copy open hours" and other noise
                time_text = re.sub(r',?\s*Copy open hours.*', '', time_text, flags=re.IGNORECASE)
                time_text = re.sub(r',?\s*Hide open hours.*', '', time_text, flags=re.IGNORECASE)
                
                # Replace unicode no-break space if present
                time_text = time_text.replace('\u202f', ' ')
                
                open_hours[day] = time_text.strip()
        
        if not open_hours:
            # Strategy 2: Look for class-based tables (fallback)
            hours_matches = re.findall(r'class="[^"]*hours-item[^"]*">[^<]*<span>([^<]+)</span>', html_content)
            if hours_matches:
                for item in hours_matches:
                    if ':' in item:
                        day, time_range = item.split(':', 1)
                        if day.strip() in days:
                            open_hours[day.strip()] = time_range.strip()

        if open_hours:
            data["open_hours"] = open_hours

        # Thumbnail
        # Pattern: Prioritize googleusercontent URLs, exclude maps vector tiles (vt/pb)
        thumb_patterns = [
            r'https://lh\d\.googleusercontent\.com/p/[^"&]+',
            r'src="([^"]+googleusercontent[^"]+)"[^>]*decoding="async"',
            r'decoding="async"[^>]*src="([^"]+googleusercontent[^"]+)"'
        ]
        for pattern in thumb_patterns:
            match = re.search(pattern, html_content)
            if match:
                url = match.group(0) if pattern.startswith('http') else match.group(1)
                if "vt/pb" not in url:
                    data["thumbnail"] = url
                    break

        # Images
        # Strategy 1: Find all high-res googleusercontent URLs (lh0-lh9)
        img_urls = re.findall(r'https://lh\d\.googleusercontent\.com/p/[^"&]+', html_content)
        if img_urls:
            unique_imgs = list(dict.fromkeys(img_urls))
            data["images"] = [{"image": url} for url in unique_imgs[:10]]
        else:
            # Fallback to class-based matching
            img_matches = re.findall(r'<div class="[^"]*image-item[^"]*">[^<]*<img[^>]+src="([^"]+)"', html_content)
            if img_matches:
                data["images"] = [{"image": src} for src in img_matches]

        # Categories
        # Artifact shows: <div class="kp-header-category"><button ...>Espresso bar</button>
        category_match = re.search(r'<div class="[^"]*category[^"]*">[^<]*<button[^>]*>([^<]+)</button>', html_content)
        if category_match:
             data["categories"] = [category_match.group(1).strip()]

        return data
    except Exception as e:
        print(f"Error in extract_from_dom: {e}")
        return {}


def _find_app_init_blob(data):
    """
    Specifically looks for the blob at data[5][3][2] which seems to be a fallback
    schema in APP_INITIALIZATION_STATE when JSON-LD is missing.
    """
    try:
        candidate = safe_get(data, 5, 3, 2)
        if isinstance(candidate, list) and len(candidate) > 2:
            # Check for Place ID signature at index 0
            # format: 0x...:0x...
            val = candidate[0]
            if isinstance(val, str) and val.startswith("0x") and ":" in val:
                 return candidate
    except:
        pass
    return None

def _find_all_blobs(data):
    """
    Recursively searches through a nested structure (lists and dicts) 
    and collects ALL unique strings that start with the signature ")]}'".
    Returns a list of parsed JSON objects/lists.
    """
    blobs = []
    
    # Check for direct APP_INITIALIZATION_STATE blob first
    direct_blob = _find_app_init_blob(data)
    if direct_blob:
        blobs.append(direct_blob)

    def recursive_search(d):
        if isinstance(d, str):
            if d.startswith(")]}'"):
                try:
                    # Parse immediately to filter out invalid ones
                    json_str_inner = d.split(")]}'\n", 1)[1]
                    parsed = json.loads(json_str_inner)
                    # Avoid duplicates (comparing heavy objects is expensive, but necessary if structure allows)
                    # For now just append, we can score them later.
                    blobs.append(parsed)
                except:
                    pass
        elif isinstance(d, list):
             # Optimization: don't recurse into the blob we just found
            for item in d:
                recursive_search(item)
        elif isinstance(d, dict):
            for value in d.values():
                recursive_search(value)

    recursive_search(data)
    return blobs

def parse_json_data(json_str):
    """
    Parses the initial JSON, finds all potential data blobs, scores them,
    and returns the best candidate for extraction.
    """
    try:
        initial_data = json.loads(json_str)
        candidates = _find_all_blobs(initial_data)
        
        if not candidates:
            return None

        best_blob = None
        max_score = -1
        
        for i, blob in enumerate(candidates):
            score = 0
            
            # --- Scoring Logic ---
            # We check both top-level and [0][1] nested level for the common fields
            
            # Detect if this is the "Single Place/Search Result" rich blob
            # Root is usually data[0][1] for these rich embedded blobs
            root = safe_get(blob, 0, 1)
            is_rich_nested = isinstance(root, list)
            
            # 1. Place ID Check (Heavy Weight: +10)
            id_val = safe_get(blob, 10) or safe_get(blob, 0, 0)
            if not id_val and is_rich_nested:
                # In nested rich blob, ID might be at [0, 1, 14, 11] as part of a list or CID
                # but often [10] still works if we get the right root.
                # Actually, let's just check for '0x' strings anywhere in the first few levels
                id_val = safe_get(root, 10)

            if isinstance(id_val, str) and id_val.startswith("0x"):
                score += 10
            
            # 2. Coordinates Check (+5)
            lat = safe_get(blob, 9, 2) or safe_get(blob, 0, 1, 9, 2) or safe_get(blob, 7, 2)
            if isinstance(lat, (int, float)):
                score += 5
            
            # 3. Address Check (+5)
            addr = safe_get(blob, 2) or safe_get(blob, 0, 1, 2, 0)
            if addr:
                score += 5
            
            # 4. Web/Phone Check (+3)
            if safe_get(blob, 7, 0) or safe_get(blob, 0, 1, 7, 0): # Website
                score += 3
                
            if score > max_score:
                max_score = score
                best_blob = blob
        
        return best_blob

    except Exception as e:
        return None


# --- Field Extraction Functions ---
def get_main_name(data):
    # Try multiple standard and nested paths
    paths = [
        (11,), (0, 1, 60), (0, 1, 14, 11), (0, 1), (1,),
        (60,), (14, 11) # If data is already the root
    ]
    for p in paths:
        val = safe_get(data, *p)
        if isinstance(val, str) and val and not val.startswith("0x"): return val
    return None


def get_place_id(data):
    paths = [
        (10,), (0, 1, 10), (0, 0), (0,), (14, 11)
    ]
    for p in paths:
        val = safe_get(data, *p)
        if isinstance(val, str) and val and val.startswith("0x"): return val
    return None


def get_gps_coordinates(data):
    paths = [
        (9, 2), (0, 1, 9, 2), (0, 1, 2, 2), (7, 2), (2, 2)
    ]
    for p in paths:
        lat = safe_get(data, *p)
        # Corresponding longitude is usually at lat_idx + 1
        lon_path = list(p)
        lon_path[-1] += 1
        lon = safe_get(data, *lon_path)
        
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and lat != 0:
             return {"latitude": lat, "longitude": lon}

    return _find_coordinates_recursively(data)


def _find_coordinates_recursively(data, depth=0):
    if depth > 10: return None
    if isinstance(data, list):
        # specific check for [null, null, lat, lon] pattern seen in artifacts
        # data[2] is lat, data[3] is lon
        if len(data) >= 4:
            val1 = data[2]
            val2 = data[3]
            # print(f"DEBUG: Checking list at depth {depth}: {[str(x)[:10] for x in data]}")
            if isinstance(val1, (float, int)) and isinstance(val2, (float, int)):
                 if -90 <= val1 <= 90 and -180 <= val2 <= 180:
                     return {"latitude": float(val1), "longitude": float(val2)}
        
        # Iterate children
        for item in data:
            res = _find_coordinates_recursively(item, depth + 1)
            if res: return res
            
    elif isinstance(data, dict):
        for key, value in data.items():
            res = _find_coordinates_recursively(value, depth + 1)
            if res: return res
            
    return None



def get_complete_address(data):
    paths = [
        (2,), (0, 1, 2, 0), (2, 0)
    ]
    for p in paths:
        val = safe_get(data, *p)
        if isinstance(val, list):
            formatted = ", ".join(filter(None, val))
            if formatted: return formatted
        if isinstance(val, str) and val and not val.startswith("0x"): return val
    return None


def get_rating(data):
    # Standard
    val = safe_get(data, 4, 7)
    if val is not None: return val
    # Nested
    val = safe_get(data, 0, 1, 4, 7)
    if val is not None: return val
    # Fallback
    return safe_get(data, 12, 2, 1)


def get_reviews_count(data):
    # Standard
    val = safe_get(data, 4, 8)
    if val is not None: return val
    # Nested
    val = safe_get(data, 0, 1, 4, 8)
    if val is not None: return val
    # Fallback
    return safe_get(data, 13, 14)


def get_website(data):
    paths = [
        (7, 0), (0, 1, 7, 0)
    ]
    for p in paths:
        val = safe_get(data, *p)
        if isinstance(val, str) and val.startswith("http"): return val
    return None

def _find_phone_recursively(data_structure):
    if isinstance(data_structure, list):
        # Specific check for phone index in rich blob [178][0][3]
        # But recursion usually finds it.
        if len(data_structure) >= 2 and \
           isinstance(data_structure[0], str) and "call_googblue" in data_structure[0] and \
           isinstance(data_structure[1], str):
            phone_number_str = data_structure[1]
            standardized_number = re.sub(r'\D', '', phone_number_str)
            if standardized_number:
                return standardized_number
        for item in data_structure:
            found_phone = _find_phone_recursively(item)
            if found_phone:
                return found_phone
    elif isinstance(data_structure, dict):
        for key, value in data_structure.items():
            found_phone = _find_phone_recursively(value)
            if found_phone:
                return found_phone
    return None


def get_phone_number(data_blob):
    found_phone = _find_phone_recursively(data_blob)
    return found_phone if found_phone else None


def get_categories(data):
    # Standard
    val = safe_get(data, 13)
    if val: return val
    # Single Place: data[13] might be the list of categories in some variants.
    # But based on typical structure, checks:
    val = safe_get(data, 13)
    if isinstance(val, list) and all(isinstance(x, str) for x in val):
        return val
    
    # Another pattern: data[11] is name, data[13] is categories?
    return None


def get_thumbnail(data):
    return safe_get(data, 72, 0, 1, 6, 0)


def get_status(data):
    """
    Extracts the business status (e.g., 'Open', 'Closed', 'Temporarily closed').
    The index path [34, 4, 4] is derived from analysis of the Go project.
    """
    return safe_get(data, 34, 4, 4)


def get_open_hours(data):
    hours_list = safe_get(data, 34, 1)
    if not isinstance(hours_list, list):
        return None
    open_hours = {}
    for item in hours_list:
        if isinstance(item, list) and len(item) >= 2:
            day = safe_get(item, 0)
            times = safe_get(item, 1)
            if day and isinstance(times, list):
                open_hours[day] = times
    return open_hours if open_hours else None


def get_price_range(data):
    """Extracts the price range of the business (e.g., $, $$, $$$)."""
    # Standard
    val = safe_get(data, 4, 2)
    if val: return val
    # Single Place: Not identified in artifact.
    return None


def get_images(data):
    images_list = safe_get(data, 171, 0)
    if not isinstance(images_list, list):
        return None
    images = []
    for item in images_list:
        title = safe_get(item, 2)
        url = safe_get(item, 3, 0, 6, 0)
        if title and url:
            images.append({"title": title, "image": url})
    return images if images else None


def get_about(data):
    """
    Extracts the 'About' section, which contains details like Accessibility, Offerings, etc.
    """
    # The entire "About" block is located at index path [100, 1] in the main data blob.
    about_sections_raw = safe_get(data, 100, 1)
    
    if not isinstance(about_sections_raw, list):
        return None

    parsed_about_sections = []
    for section_raw in about_sections_raw:
        # Each section contains an ID, Name, and a list of options.
        section_id = safe_get(section_raw, 0)
        section_name = safe_get(section_raw, 1)
        options_raw = safe_get(section_raw, 2)

        if not (section_id and section_name and isinstance(options_raw, list)):
            continue

        parsed_options = []
        for option_raw in options_raw:
            # The option name is at index [1].
            option_name = safe_get(option_raw, 1)
            if not option_name:
                continue

            # The enabled status is determined by a deeply nested value being 1.0.
            # Path: [2, 1, 0, 0] relative to the option item.
            is_enabled = safe_get(option_raw, 2, 1, 0, 0) == 1.0

            parsed_options.append({
                "name": option_name,
                "enabled": is_enabled
            })
        
        if parsed_options:
            parsed_about_sections.append({
                "id": section_id,
                "name": section_name,
                "options": parsed_options
            })

    return parsed_about_sections if parsed_about_sections else None


def get_description(data):
    """Extracts the brief description of the business."""
    # Path based on Go project: darray[32][1][1]
    return safe_get(data, 32, 1, 1)


# === REVIEW SORTING AND SELECTION LOGIC ==================
def process_and_select_reviews(reviews_data):
    """
    Sorts, filters, and selects a random subset of reviews based on predefined quality criteria.
    This function processes raw review data before full parsing to optimize performance.
    
    Args:
        reviews_data (list): The raw list of review data from the 'listugcposts' RPC response.

    Returns:
        list: A list of 20 (or fewer) parsed user review dictionaries.
    """
    if not reviews_data:
        return []

    ranked_reviews = []
    for review_item in reviews_data:
        review = safe_get(review_item, 0)
        if not review:
            continue

        # --- Extract only the data needed for ranking ---
        description = safe_get(review, 2, 15, 0, 0) or ""
        profile_pic_raw = safe_get(review, 1, 4, 5, 1)
        date_parts = safe_get(review, 2, 2, 0, 1, 21, 6, 8)
        author_name = (safe_get(review, 1, 4, 5, 0) or "").lower()

        # --- Calculate ranking criteria based on the hierarchy ---
        # 1. Length of review description (longer is better)
        desc_len = len(description)
        # 2. Has a profile picture
        has_pic = bool(profile_pic_raw)
        # 3. Has a specific datetime
        has_datetime = isinstance(date_parts, list) and len(date_parts) >= 3
        # 4. Has a "real" username (not a placeholder)
        is_real_name = author_name not in PLACEHOLDER_USERNAMES
        
        # Create a sort key tuple. Python sorts tuples element-by-element,
        # perfectly matching our hierarchical ranking need.
        sort_key = (desc_len, has_pic, has_datetime, is_real_name)
        
        # Store the key along with the original raw review data
        ranked_reviews.append((sort_key, review_item))

    # Sort the list of (key, review) tuples. `reverse=True` ensures that
    # higher lengths and True values are ranked first.
    ranked_reviews.sort(key=lambda x: x[0], reverse=True)

    # Extract the sorted raw review data
    sorted_raw_reviews = [item for sort_key, item in ranked_reviews]

    # Create a candidate pool from the top-ranked reviews
    candidate_pool = sorted_raw_reviews[:REVIEW_CANDIDATE_POOL_SIZE]

    # Randomly select the final set of reviews from the pool
    if len(candidate_pool) <= REVIEW_SELECTION_COUNT:
        # If the pool is smaller than our target, take all of them
        selected_reviews_raw = candidate_pool
    else:
        # Otherwise, randomly sample the desired count from the high-quality pool
        selected_reviews_raw = random.sample(candidate_pool, REVIEW_SELECTION_COUNT)
    
    # --- Final Step: Parse ONLY the selected high-quality reviews ---
    print(f"Selected {len(selected_reviews_raw)} reviews for parsing from a total of {len(reviews_data)}.")
    return parse_user_reviews(selected_reviews_raw)


def parse_user_reviews(reviews_data):
    """
    Parses a list of raw review data from the 'listugcposts' RPC response.
    The index paths are based on the working Go implementation.
    (This function is now called with a pre-filtered list of reviews)
    """
    if not isinstance(reviews_data, list):
        return None

    parsed_reviews = []
    for review_item in reviews_data:
        review = safe_get(review_item, 0)
        if not review:
            continue

        author_name = safe_get(review, 1, 4, 5, 0)
        if not author_name:
            continue

        pic_url_raw = safe_get(review, 1, 4, 5, 1)
        profile_picture = ""
        if pic_url_raw:
            try:
                profile_picture = bytes(pic_url_raw, "utf-8").decode("unicode_escape")
            except:
                profile_picture = pic_url_raw

        description = safe_get(review, 2, 15, 0, 0)
        rating = safe_get(review, 2, 0, 0)
        
         # --- Datetime Extraction with Fallback ---
        when = "N/A"  # Set a safe default

        # Priority 1: Attempt to extract the absolute date (YYYY-MM-DD).
        # This is the most precise data and should be preferred.
        date_parts = safe_get(review, 2, 2, 0, 1, 21, 6, 8)
        if isinstance(date_parts, list) and len(date_parts) >= 3:
            try:
                year, month, day = int(date_parts[0]), int(date_parts[1]), int(date_parts[2])
                when = f"{year}-{month:02d}-{day:02d}"
            except (ValueError, TypeError):
                # The data at the path was not in the expected [Y, M, D] numeric format.
                # We will let the code proceed to the fallback.
                pass

        # Priority 2: If absolute date extraction failed, fall back to the relative time string.
        # The 'when' variable will still be "N/A" if the block above failed or was skipped.
        if when == "N/A":
            # This index path is the common location for the relative time string (e.g., "a month ago").
            relative_time_str = safe_get(review, 1, 1)
            if isinstance(relative_time_str, str) and relative_time_str:
                when = relative_time_str

        images = []
        images_list = safe_get(review, 2, 2, 0, 1, 21, 7)
        if isinstance(images_list, list):
            for img_item in images_list:
                img_url = safe_get(img_item)
                if img_url and isinstance(img_url, str):
                    images.append("https:" + img_url if img_url.startswith('//') else img_url)

        parsed_reviews.append({
            "name": author_name,
            "profile_picture": profile_picture,
            "rating": rating,
            "description": description,
            "when": when, 
            "images": images
        })

    return parsed_reviews if parsed_reviews else None


def save_debug_content(content, prefix="debug", extension="txt"):
    """Saves content to a file in the debug_artifacts directory for inspection."""
    debug_dir = "debug_artifacts"
    try:
        if not os.path.exists(debug_dir):
            os.makedirs(debug_dir)
        # else:
        #     try:
        #         shutil.rmtree(debug_dir)
        #     except OSError:
        #         pass
        #     if not os.path.exists(debug_dir):
        #         os.makedirs(debug_dir)
    except Exception as e:
        print(f"Warning: Could not manage debug directory: {e}")
        return # Exit if we can't write debug info
    
    # Limit to 10 debug artifacts to avoid cluttering
    try:
        existing_files = [f for f in os.listdir(debug_dir) if os.path.isfile(os.path.join(debug_dir, f))]
        if len(existing_files) >= 50:
            print(f"Debug artifact limit reached (50). Skipping: {prefix}")
            return
    except Exception as e:
        print(f"Error checking debug directory: {e}")
    
    timestamp = int(time.time() * 1000) # Use ms for unique filenames if called quickly
    filename = f"{debug_dir}/{prefix}_{timestamp}.{extension}"
    
    try:
        with open(filename, "w", encoding="utf-8") as f:
            print(f">>>> Saving debug artifact to: {filename}")
            if isinstance(content, (dict, list)):
                json.dump(content, f, indent=2)
            else:
                f.write(str(content))
    except Exception as e:
        print(f"Failed to save debug artifact: {e}")

def extract_place_data(html_content, all_reviews=None):
    """
    Orchestrates the extraction process:
    1. Extract JSON-LD (Rich Data).
    2. Extract Internal Blob (Multi-Blob Scoring).
    3. Merge results, prioritizing JSON-LD for core fields.
    """
    final_data = {}
    
    # 1. JSON-LD Extraction
    json_ld_data = extract_json_ld(html_content)
    if json_ld_data:
        # Map JSON-LD fields to our schema
        final_data["name"] = json_ld_data.get("name")
        final_data["website"] = json_ld_data.get("url") or json_ld_data.get("sameAs")
        final_data["phone"] = json_ld_data.get("telephone")
        final_data["description"] = json_ld_data.get("description")
        
        # Address
        addr = json_ld_data.get("address")
        if isinstance(addr, dict):
            # Construct address string or keep dict? CSV expects string usually.
            # Let's try to make a readable string
            parts = [
                addr.get("streetAddress"),
                addr.get("addressLocality"),
                addr.get("addressRegion"),
                addr.get("postalCode"),
                addr.get("addressCountry")
            ]
            final_data["address"] = ", ".join([p for p in parts if p])
            
        elif isinstance(addr, str):
             final_data["address"] = addr
        
        # Geo
        geo = json_ld_data.get("geo")
        if isinstance(geo, dict):
            final_data["latitude"] = geo.get("latitude")
            final_data["longitude"] = geo.get("longitude")
            
        # Categories (usually @type is just "Restaurant" or "LocalBusiness")
        # We might want more granular ones from internal blob, so keep this weak.
        schema_type = json_ld_data.get("@type")
        if schema_type:
            if isinstance(schema_type, str):
                final_data["categories"] = [schema_type]
            elif isinstance(schema_type, list):
                final_data["categories"] = schema_type
                
        # Opening Hours
        # JSON-LD format: "Mo-Fr 09:00-17:00"
        final_data["open_hours"] = json_ld_data.get("openingHours") or json_ld_data.get("openingHoursSpecification")
        
        final_data["rating"] = safe_get(json_ld_data, "aggregateRating", "ratingValue")
        final_data["reviews_count"] = safe_get(json_ld_data, "aggregateRating", "reviewCount")
        
        # print(f"Extracted JSON-LD for: {final_data.get('name')}")

    # 2. Internal Blob Extraction
    json_str = extract_initial_json(html_content)
    # We allow extract_initial_json to fail if JSON-LD was sufficient, but good to have both.
    
    internal_data = {}
    if json_str:
        parsed_data = parse_json_data(json_str)
        if parsed_data:
            internal_data = {
                "title": get_main_name(parsed_data), # fallback for name
                "address": get_address(parsed_data) if 'get_address' in globals() else get_complete_address(parsed_data),
                "attributes": get_attributes(parsed_data) if 'get_attributes' in globals() else get_about(parsed_data),
                "website": get_website(parsed_data),
                "phone": get_phone_number(parsed_data),
                "rating": get_rating(parsed_data),
                "reviews_count": get_reviews_count(parsed_data),
                "categories": get_categories(parsed_data), # Internal categories are usually better/more numerous
                "open_hours": get_open_hours(parsed_data),
                "images": get_images(parsed_data),
                "place_id": get_place_id(parsed_data),
                "thumbnail": get_thumbnail(parsed_data),
                "about": get_description(parsed_data),
                "price_range": get_price_range(parsed_data)
            }
            
            # Coordinates from internal blob
            coords = get_gps_coordinates(parsed_data)
            if coords:
                internal_data.update(coords)
                # Ensure 'coordinates' object is available for scripts expecting it
                internal_data["coordinates"] = coords
            
            # Status
            close_statuses = ['permanently closed', 'temporarily closed', 'closed permanently', 'closed temporarily']
            raw_status = get_status(parsed_data)
            final_status = 'open'
            if raw_status:
                raw_status_lower = raw_status.lower()
                if any(s in raw_status_lower for s in close_statuses):
                    final_status = 'close'
            internal_data["status"] = final_status
    
    # 3. Merging (JSON-LD wins for "Core" Identity, Internal wins for "Rich" Details like attributes/images)
    
    # Helper to merge if empty
    def merge_if_missing(key, source_val):
        if not final_data.get(key) and source_val:
            final_data[key] = source_val

    # ID is crucial. JSON-LD usually doesn't have the google hex ID (has URL).
    # Internal blob usually has the Hex ID.
    merge_if_missing("place_id", internal_data.get("place_id"))
    
    # If JSON-LD didn't have name (unlikely), take internal
    if not final_data.get("name"):
        final_data["name"] = internal_data.get("title")

    # Address/Phone/Web: JSON-LD is usually cleaner, but merge if missing
    merge_if_missing("address", internal_data.get("address"))
    merge_if_missing("website", internal_data.get("website"))
    merge_if_missing("phone", internal_data.get("phone"))
    
    # Coordinates: JSON-LD is authoritative if present, else internal
    merge_if_missing("latitude", internal_data.get("latitude"))
    merge_if_missing("longitude", internal_data.get("longitude"))
    
    # Also create the 'coordinates' object for consistency
    if final_data.get("latitude") and final_data.get("longitude"):
        final_data["coordinates"] = {
            "latitude": final_data["latitude"],
            "longitude": final_data["longitude"]
        }
    
    # Rating/Reviews: JSON-LD aggregateRating vs Internal
    merge_if_missing("rating", internal_data.get("rating"))
    merge_if_missing("reviews_count", internal_data.get("reviews_count"))
    
    # Categories: Internal ones are usually specific ("Cat Cafe" vs "LocalBusiness")
    # If internal has categories, they might be better or supplementary. 
    # Let's prefer Internal categories if they look like a list of strings
    int_cats = internal_data.get("categories")
    if int_cats and isinstance(int_cats, list) and len(int_cats) > 0:
        # Reuse internal categories as they are Google specific classifications
        final_data["categories"] = int_cats
    elif not final_data.get("categories"):
         final_data["categories"] = []

    # Rich details only in internal usually
    merge_if_missing("attributes", internal_data.get("attributes"))
    merge_if_missing("images", internal_data.get("images"))
    merge_if_missing("open_hours", internal_data.get("open_hours"))
    merge_if_missing("thumbnail", internal_data.get("thumbnail"))
    merge_if_missing("about", internal_data.get("about"))
    merge_if_missing("price_range", internal_data.get("price_range"))
    merge_if_missing("status", internal_data.get("status"))

    # 4. DOM Fallback Extraction (Final Layer)
    # Extract only if we are missing critical fields.
    # We run this Last to avoid overwriting good data with potential debris.
    if not final_data.get("address") or not final_data.get("phone") or not final_data.get("website") or not final_data.get("open_hours"):
        dom_data = extract_from_dom(html_content)
        if dom_data:
             for key, val in dom_data.items():
                 merge_if_missing(key, val)
    
    # User Reviews are passed in separately
    final_data["user_reviews"] = process_and_select_reviews(all_reviews) if all_reviews else []
    
    # Ensure strict deduplication of inputs if needed, though usually handled by set in scraper.
    
    # Clean up None values
    return {k: v for k, v in final_data.items() if v is not None}

# Example usage (for testing):
if __name__ == '__main__':
    try:
        with open('sample_place.html', 'r', encoding='utf-8') as f:
            sample_html = f.read()

        extracted_info = extract_place_data(sample_html)

        if extracted_info:
            print("Extracted Place Data:")
            print(json.dumps(extracted_info, indent=2))
        else:
            print("Could not extract data from the sample HTML.")

    except FileNotFoundError:
        print("Sample HTML file 'sample_place.html' not found. Cannot run example.")
    except Exception as e:
        print(f"An error occurred during example execution: {e}")