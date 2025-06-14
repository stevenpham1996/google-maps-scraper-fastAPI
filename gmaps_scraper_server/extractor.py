import json
import re

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
                    # print(f"Index {key} out of bounds or invalid for list.")
                    return None
            elif isinstance(current, dict):
                if key in current:
                    current = current[key]
                else:
                    # print(f"Key {key} not found in dict.")
                    return None
            else:
                # print(f"Cannot access key {key} on non-dict/list item: {type(current)}")
                return None
        except (IndexError, TypeError, KeyError) as e:
            # print(f"Error accessing key {key}: {e}")
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
    Parses the extracted JSON string, handling the nested JSON string if present.
    Returns the main data blob (list) or None if parsing fails or structure is unexpected.
    """
    if not json_str:
        return None
    try:
        initial_data = json.loads(json_str)

        # Check the initial heuristic path [3][6]
        if isinstance(initial_data, list) and len(initial_data) > 3 and isinstance(initial_data[3], list) and len(initial_data[3]) > 6:
             data_blob_or_str = initial_data[3][6]

             # Case 1: It's already the list we expect (older format?)
             if isinstance(data_blob_or_str, list):
                 print("Found expected list structure directly at initial_data[3][6].")
                 return data_blob_or_str

             # Case 2: It's the string containing the actual JSON
             elif isinstance(data_blob_or_str, str) and data_blob_or_str.startswith(")]}'\n"):
                 print("Found string at initial_data[3][6], attempting to parse inner JSON.")
                 try:
                     json_str_inner = data_blob_or_str.split(")]}'\n", 1)[1]
                     actual_data = json.loads(json_str_inner)

                     # Check if the parsed inner data is a list and has the expected sub-structure at index 6
                     if isinstance(actual_data, list) and len(actual_data) > 6:
                          potential_data_blob = safe_get(actual_data, 6)
                          if isinstance(potential_data_blob, list):
                              print("Returning data blob found at actual_data[6].")
                              return potential_data_blob # This is the main data structure
                          else:
                              print(f"Data at actual_data[6] is not a list, but {type(potential_data_blob)}. Saving inner data for inspection.")
                              # Save actual_data for debugging
                              try:
                                  with open("debug_inner_data.json", "w", encoding="utf-8") as f_inner:
                                      json.dump(actual_data, f_inner, indent=2)
                                  print("...Successfully saved debug_inner_data.json")
                              except Exception as dump_error_inner:
                                  print(f"Error saving inner debug file: {dump_error_inner}")
                              return None # Structure mismatch within inner data
                     else:
                         print(f"Parsed inner JSON is not a list or too short (len <= 6), type: {type(actual_data)}. Saving inner data for inspection.")
                         # Save actual_data for debugging
                         try:
                             with open("debug_inner_data.json", "w", encoding="utf-8") as f_inner:
                                 json.dump(actual_data, f_inner, indent=2)
                             print("...Successfully saved debug_inner_data.json")
                         except Exception as dump_error_inner:
                             print(f"Error saving inner debug file: {dump_error_inner}")
                         return None # Inner JSON structure not as expected

                 except json.JSONDecodeError as e_inner:
                     print(f"Error decoding inner JSON string: {e_inner}")
                     return None
                 except Exception as e_inner_general:
                     print(f"Unexpected error processing inner JSON string: {e_inner_general}")
                     return None

             # Case 3: Data at [3][6] is neither a list nor the expected string
             else:
                 print(f"Parsed JSON structure unexpected at [3][6]. Expected list or prefixed JSON string, got {type(data_blob_or_str)}.")
                 # Save initial_data for debugging
                 print("Attempting to save full structure to debug_initial_data.json...")
                 try:
                     with open("debug_initial_data.json", "w", encoding="utf-8") as f:
                         json.dump(initial_data, f, indent=2)
                     print("...Successfully saved debug_initial_data.json")
                 except Exception as dump_error:
                     print(f"Error saving debug file: {dump_error}")
                 return None # Unexpected structure at [3][6]

        # Case 4: Initial path [3][6] itself wasn't valid
        else:
            print(f"Initial JSON structure not as expected (list[3][6] path not valid). Type: {type(initial_data)}")
            # Save initial_data for debugging
            print("Attempting to save unexpected structure to debug_initial_data.json...")
            try:
                with open("debug_initial_data.json", "w", encoding="utf-8") as f:
                    json.dump(initial_data, f, indent=2)
                print("...Successfully saved debug_initial_data.json")
            except Exception as dump_error:
                print(f"Error saving debug file: {dump_error}")
            return None # Initial structure invalid

    except json.JSONDecodeError as e:
        print(f"Error decoding initial JSON: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error parsing JSON data: {e}")
        return None


# --- Field Extraction Functions (Indices relative to the data_blob returned by parse_json_data) ---

def get_main_name(data):
    """Extracts the main name of the place."""
    # Index relative to the data_blob returned by parse_json_data
    # Confirmed via debug_inner_data.json: data_blob = actual_data[6], name = data_blob[11]
    return safe_get(data, 11)

def get_place_id(data):
    """Extracts the Google Place ID."""
    return safe_get(data, 10) # Updated index

def get_gps_coordinates(data):
    """Extracts latitude and longitude."""
    lat = safe_get(data, 9, 2)
    lon = safe_get(data, 9, 3)
    if lat is not None and lon is not None:
        return {"latitude": lat, "longitude": lon}
    return None

def get_complete_address(data):
    """Extracts structured address components and joins them."""
    address_parts = safe_get(data, 2) # Updated index
    if isinstance(address_parts, list):
        formatted = ", ".join(filter(None, address_parts))
        return formatted if formatted else None
    return None

def get_rating(data):
    """Extracts the average star rating."""
    return safe_get(data, 4, 7)

def get_reviews_count(data):
    """Extracts the total number of reviews."""
    return safe_get(data, 4, 8)

def get_website(data):
    """Extracts the primary website link."""
    # Index based on debug_inner_data.json structure relative to data_blob (actual_data[6])
    return safe_get(data, 7, 0)

def _find_phone_recursively(data_structure):
    """
    Recursively searches a nested list/dict structure for a list containing
    the phone icon URL followed by the phone number string.
    """
    if isinstance(data_structure, list):
        # Check if this list matches the pattern [icon_url, phone_string, ...]
        if len(data_structure) >= 2 and \
           isinstance(data_structure[0], str) and "call_googblue" in data_structure[0] and \
           isinstance(data_structure[1], str):
            # Found the pattern, assume data_structure[1] is the phone number
            phone_number_str = data_structure[1]
            standardized_number = re.sub(r'\D', '', phone_number_str)
            if standardized_number:
                # print(f"Debug: Found phone via recursive search: {standardized_number}")
                return standardized_number

        # If not the target list, recurse into list elements
        for item in data_structure:
            found_phone = _find_phone_recursively(item)
            if found_phone:
                return found_phone

    elif isinstance(data_structure, dict):
        # Recurse into dictionary values
        for key, value in data_structure.items():
            found_phone = _find_phone_recursively(value)
            if found_phone:
                return found_phone

    # Base case: not a list/dict or pattern not found in this branch
    return None

def get_phone_number(data_blob):
    """
    Extracts and standardizes the primary phone number by recursively searching
    the data_blob for the phone icon pattern.
    """
    # data_blob is the main list structure (e.g., actual_data[6])
    found_phone = _find_phone_recursively(data_blob)
    if found_phone:
        return found_phone
    else:
        # print("Debug: Phone number pattern not found in data_blob.")
        return None

def get_categories(data):
    """Extracts the list of categories/types."""
    return safe_get(data, 13)

def get_thumbnail(data):
    """Extracts the main thumbnail image URL."""
    # This path might still be relative to the old structure, needs verification
    # If data_blob is the list starting at actual_data[6], this index is likely wrong.
    # We need to find the thumbnail within the new structure from debug_inner_data.json
    # For now, returning None until verified.
    # return safe_get(data, 72, 0, 1, 6, 0) # Placeholder index - LIKELY WRONG
    # Tentative guess based on debug_inner_data structure (might be in a sublist like [14][0][0][6][0]?)
    return safe_get(data, 14, 0, 0, 6, 0) # Tentative guess

def get_open_hours(data):
    """Extracts the opening hours for each day."""
    # Path based on Go project: darray[34][1]
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

def get_images(data):
    """Extracts a list of images with their titles."""
    # Path based on Go project: darray[171][0]
    images_list = safe_get(data, 171, 0)
    if not isinstance(images_list, list):
        return None
        
    images = []
    for item in images_list:
        # Go project logic: getLinkSource with source:[2] and link:[3,0,6,0]
        title = safe_get(item, 2)
        url = safe_get(item, 3, 0, 6, 0)
        if title and url:
            images.append({"title": title, "image": url})
            
    return images if images else None

def parse_user_reviews(reviews_data):
    """Parses a list of raw review data from the RPC response."""
    if not isinstance(reviews_data, list):
        return None

    parsed_reviews = []
    for review in reviews_data:
        # Paths based on Go project's parseReviews function
        author_name = safe_get(review, 0, 1)
        profile_picture_url = safe_get(review, 0, 2)
        review_text = safe_get(review, 3)
        rating = safe_get(review, 4)
        relative_time = safe_get(review, 1) # e.g., "a week ago"
        
        # The Go project extracts more, but this is a solid start.
        # You can expand this by inspecting the `review` object.
        # For example, to get review photos:
        photos = [safe_get(photo, 6, 0) for photo in safe_get(review, 14) or [] if safe_get(photo, 6, 0)]

        if author_name and rating is not None:
            parsed_reviews.append({
                "name": author_name,
                "profile_picture": profile_picture_url,
                "rating": rating,
                "description": review_text,
                "when": relative_time,
                "images": photos
            })
    return parsed_reviews if parsed_reviews else None

# Add more extraction functions here as needed, using the indices
# from omkarcloud/src/extract_data.py as a reference, BUT VERIFYING against debug_inner_data.json

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

    # Now extract individual fields using the helper functions
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
        "thumbnail": get_thumbnail(data_blob),
        "open_hours": get_open_hours(data_blob),
        "images": get_images(data_blob),
        "user_reviews": parse_user_reviews(all_reviews if all_reviews else safe_get(data_blob, 52)),
    }

    # Filter out None values if desired
    place_details = {k: v for k, v in place_details.items() if v is not None}

    return place_details if place_details else None

# Example usage (for testing):
if __name__ == '__main__':
    # Load sample HTML content from a file (replace 'sample_place.html' with your file)
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