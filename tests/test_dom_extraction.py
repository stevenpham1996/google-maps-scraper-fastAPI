
import unittest
import os
import sys

# Add parent directory to path to import extractor
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gmaps_scraper_server import extractor

class TestDOMExtraction(unittest.TestCase):
    def setUp(self):
        # Path to the artifact
        self.artifact_path = "debug_artifacts/failed_json_ld_html_1770646513345.html"
        with open(self.artifact_path, "r", encoding="utf-8") as f:
            self.html_content = f.read()

    def test_address_extraction(self):
        data = extractor.extract_from_dom(self.html_content)
        self.assertEqual(data.get("address"), "C. 17 58-Local 2, San Pedro de los Pinos, Benito Juárez, 03800 Ciudad de México, CDMX, Mexico")

    def test_phone_extraction(self):
        data = extractor.extract_from_dom(self.html_content)
        self.assertEqual(data.get("phone"), "+52 55 7112 4233")

    def test_website_extraction(self):
        data = extractor.extract_from_dom(self.html_content)
        self.assertEqual(data.get("website"), "https://www.31gatitos.com")

    def test_rating_extraction(self):
        data = extractor.extract_from_dom(self.html_content)
        self.assertEqual(data.get("rating"), 4.6)

    def test_reviews_count_extraction(self):
        data = extractor.extract_from_dom(self.html_content)
        self.assertEqual(data.get("reviews_count"), 1260)

    def test_open_hours_extraction(self):
        data = extractor.extract_from_dom(self.html_content)
        hours = data.get("open_hours")
        self.assertIsNotNone(hours)
        self.assertIn("Friday", hours)
        self.assertEqual(hours["Friday"], "2 to 9 PM")

if __name__ == '__main__':
    unittest.main()
