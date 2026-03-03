import unittest
import json
from gmaps_scraper_server import extractor

class TestJsonLdExtraction(unittest.TestCase):

    def setUp(self):
        self.json_ld_sample = {
            "@context": "http://schema.org",
            "@type": "LocalBusiness",
            "name": "Test Place JSON-LD",
            "image": "https://example.com/image.jpg",
            "telephone": "+1 555-0102",
            "address": {
                "@type": "PostalAddress",
                "streetAddress": "123 Test St",
                "addressLocality": "Test City",
                "addressRegion": "Test Region",
                "postalCode": "12345",
                "addressCountry": "Test Country"
            },
            "geo": {
                "@type": "GeoCoordinates",
                "latitude": 40.7128,
                "longitude": -74.0060
            },
            "url": "https://test-place.com",
            "aggregateRating": {
                "@type": "AggregateRating",
                "ratingValue": "4.5",
                "reviewCount": "100"
            }
        }
        
        self.html_with_json_ld = f"""
        <html>
            <head>
                <script type="application/ld+json">
                {json.dumps(self.json_ld_sample)}
                </script>
                <script>
                    window.APP_INITIALIZATION_STATE = [[["0x123:0x456","Test Place Internal",["Test City"]]]];
                    window.APP_FLAGS = [];
                </script>
            </head>
            <body></body>
        </html>
        """

        self.html_no_json_ld = """
        <html>
            <script>
                window.APP_INITIALIZATION_STATE = [[["0x789:0xabc","Internal Only",[null, null, 34.05, -118.25], null, null, null, null, ["+1 555-9999"], null, null, "0x789"]]];
                window.APP_FLAGS = [];
            </script>
        </html>
        """

    def test_extract_json_ld(self):
        extracted = extractor.extract_json_ld(self.html_with_json_ld)
        self.assertIsNotNone(extracted)
        self.assertEqual(extracted["name"], "Test Place JSON-LD")
        self.assertEqual(extracted["telephone"], "+1 555-0102")
        self.assertEqual(extracted["geo"]["latitude"], 40.7128)

    def test_extract_place_data_prioritizes_json_ld(self):
        # We need to ensure we can parse the internal blob somewhat to trigger the merge
        # The mocked internal blob is very minimal, might fail parse_json_data scoring
        # Let's use a slightly better mock for internal data to pass parsing
        
        # Internal blob with DIFFERENT data to prove precedence
        internal_blob_struct = [
            ["0x888"], # 0
            "0x123456", # 1
            ["Old Address"], # 2
            None, # 3
            [None, None, "$$$", None, None, None, None, 3.0, 10], # 4 (Rating 3.0, 10 reviews)
            None, None,
            ["http://internal.com"], # 7 Website
            None, None,
            "0xInternalID", # 10 Place ID
            "Internal Name", # 11 Name
        ]
        
        # We need to wrap this in the structure expected by _find_all_blobs
        # internal_blob_struct needs to be found. 
        # _find_all_blobs looks for ")]}'" prefixed strings.
        
        json_payload = json.dumps(internal_blob_struct)
        prefix = ")]}'\n"
        full_payload_str = prefix + json_payload
        
        html = f"""
        <html>
            <script type="application/ld+json">
            {json.dumps(self.json_ld_sample)}
            </script>
            <script>
                window.APP_INITIALIZATION_STATE = {json.dumps(full_payload_str)};
                window.APP_FLAGS = [];
            </script>
        </html>
        """
        
        # Actually simplest way is to manually mock the parse_json_data return
        # But we are testing integration.
        # Let's see if our extractor can handle this mock.
        # The extract_initial_json will extraction the string.
        # parse_json_data will look for ")]}'"
        
        # Let's adjust the HTML to match what extract_initial_json expects
        html_real = f"""
        <html>
            <script type="application/ld+json">
            {json.dumps(self.json_ld_sample)}
            </script>
            <script>;window.APP_INITIALIZATION_STATE={json.dumps(full_payload_str)};window.APP_FLAGS=[];</script>
        </html>
        """
        
        data = extractor.extract_place_data(html_real)
        
        # Verify JSON-LD Precedence
        self.assertEqual(data["name"], "Test Place JSON-LD") # Should match JSON-LD
        self.assertEqual(data["rating"], "4.5")
        self.assertEqual(data["website"], "https://test-place.com")
        self.assertEqual(data["phone"], "+1 555-0102")
        
        # Verify Internal Blob Fallback (if any unique fields were there)
        # Our mock internal blob had "0xInternalID" as Place ID.
        # JSON-LD doesn't have place_id mapped usually.
        self.assertEqual(data.get("place_id"), "0xInternalID")

    def test_deduplication_logic_simulation(self):
        # Simulate the scraping loop's deduplication
        scraped_data_list = [
            {"place_id": "A", "name": "Place A"},
            {"place_id": "B", "name": "Place B"},
            {"place_id": "A", "name": "Place A Duplicate"},
            {"place_id": "C", "name": "Place C"},
        ]
        
        results = []
        seen_place_ids = set()
        
        for data in scraped_data_list:
            if data and "place_id" in data:
                pid = data["place_id"]
                if pid not in seen_place_ids:
                    seen_place_ids.add(pid)
                    results.append(data)
        
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0]["name"], "Place A")
        self.assertEqual(results[1]["name"], "Place B")
        self.assertEqual(results[2]["name"], "Place C")

if __name__ == '__main__':
    unittest.main()
