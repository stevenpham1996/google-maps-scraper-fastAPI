# gmaps_scraper_server/extractor.py

import json
import re
import random # <--- ADDED: For random selection of reviews

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
        match = re.search(r';window\.APP_INITIALIZATION_STATE\s*=\s*(.*?);window\.APP_FLAGS', html_content, re.DOTALL)
        if match:
            json_str = match.group(1)
            if json_str.strip().startswith(('[', '{')):
                return json_str
            else:
                print("Extracted content doesn't look like valid JSON start.")
                return None
        else:
            print("APP_INITIALIZATION_STATE pattern not found.")
            return None
    except Exception as e:
        print(f"Error extracting JSON string: {e}")
        return None

def parse_json_data(json_str):
    """
    Parses the initial JSON, finds the dynamic key, and extracts the main data blob.
    This mimics the logic from the Go project's JS extractor.
    """
    if not json_str:
        return None
    try:
        initial_data = json.loads(json_str)
        
        # DEBUG - save the initial data to a file for inspection
        # with open('initial_data.json', 'w') as f:
        #     json.dump(initial_data, f, indent=2)

        app_state = safe_get(initial_data, 3)
        if not isinstance(app_state, dict):
            if isinstance(app_state, list) and len(app_state) > 6:
                data_blob_str = safe_get(app_state, 6)
                if isinstance(data_blob_str, str) and data_blob_str.startswith(")]}'"):
                    json_str_inner = data_blob_str.split(")]}'\n", 1)[1]
                    actual_data = json.loads(json_str_inner)
                    return safe_get(actual_data, 6)
            return None

        for i in range(65, 91):  # ASCII for 'A' through 'Z'
            key = chr(i) + "f"
            if key in app_state:
                data_blob_str = safe_get(app_state, key, 6)
                if isinstance(data_blob_str, str) and data_blob_str.startswith(")]}'"):
                    print(f"Found data blob under dynamic key: '{key}'")
                    json_str_inner = data_blob_str.split(")]}'\n", 1)[1]
                    actual_data = json.loads(json_str_inner)
                    final_blob = safe_get(actual_data, 6)
                    if isinstance(final_blob, list):
                        return final_blob
        
        print("Could not find the data blob using dynamic key search.")
        return None

    except (json.JSONDecodeError, IndexError, TypeError) as e:
        print(f"Error parsing JSON data: {e}")
        return None


# --- Field Extraction Functions ---
def get_main_name(data):
    return safe_get(data, 11)


def get_place_id(data):
    return safe_get(data, 10)


def get_gps_coordinates(data):
    lat = safe_get(data, 9, 2)
    lon = safe_get(data, 9, 3)
    if lat is not None and lon is not None:
        return {"latitude": lat, "longitude": lon}
    return None


def get_complete_address(data):
    address_parts = safe_get(data, 2)
    if isinstance(address_parts, list):
        formatted = ", ".join(filter(None, address_parts))
        return formatted if formatted else None
    return None


def get_rating(data):
    return safe_get(data, 4, 7)


def get_reviews_count(data):
    return safe_get(data, 4, 8)


def get_website(data):
    return safe_get(data, 7, 0)


def _find_phone_recursively(data_structure):
    if isinstance(data_structure, list):
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
    return safe_get(data, 13)


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
    return safe_get(data, 4, 2)


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


def extract_place_data(html_content, all_reviews=None):
    """
    High-level function to orchestrate extraction from HTML content.
    """
    json_str = extract_initial_json(html_content)
    if not json_str:
        print("Failed to extract JSON string from HTML.")
        return None

    data_blob = parse_json_data(json_str)
    if not data_blob:
        print("Failed to parse JSON data or find expected structure.")
        return None
    
    # DEBUG - save the data_blob to a file for inspection
    # with open('data_blob.json', 'w') as f:
    #     json.dump(data_blob, f, indent=2)
        
    # ===== handle Business Status =====
    close_statuses = ['permanently closed', 'temporarily closed', 'closed permanently', 'closed temporarily']
    raw_status = get_status(data_blob)
    
    # Determine final status value ('open' or 'close')
    final_status = 'open'  # Default to 'open'
    if raw_status:
        # Use case-insensitive check for robustness
        raw_status_lower = raw_status.lower()
        if any(s in raw_status_lower for s in close_statuses):
            final_status = 'close'
    
    place_details = {
        "name": get_main_name(data_blob),
        "place_id": get_place_id(data_blob),
        "coordinates": get_gps_coordinates(data_blob),
        "address": get_complete_address(data_blob),
        "rating": get_rating(data_blob),
        "reviews_count": get_reviews_count(data_blob),
        "categories": get_categories(data_blob),
        "website": get_website(data_blob),
        "phone": get_phone_number(data_blob),
        "price_range": get_price_range(data_blob),
        "thumbnail": get_thumbnail(data_blob),
        "open_hours": get_open_hours(data_blob),
        "images": get_images(data_blob),
        "about": get_description(data_blob), # the beginning description text in 'About' tab
        "attributes": get_about(data_blob), # the listed attributes in 'About' tab
        "user_reviews": process_and_select_reviews(all_reviews) if all_reviews else [],
        "status": final_status,
    }

    return {k: v for k, v in place_details.items() if v is not None}

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