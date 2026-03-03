import os
import sys
import json
import unittest

# Add the project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from gmaps_scraper_server.extractor import UnifiedExtractor, extract_place_data

class TestUnifiedExtractor(unittest.TestCase):
    def setUp(self):
        self.artifact_path = 'debug_artifacts/failed_json_ld_html_1771512756830.html'
        with open(self.artifact_path, 'r', encoding='utf-8') as f:
            self.html_content = f.read()

    def test_extraction_from_artifact(self):
        print(f"\nTesting extraction from {self.artifact_path}...")
        results = extract_place_data(self.html_content)
        
        # Verify core fields
        self.assertIsNotNone(results.get('name'))
        self.assertEqual(results.get('name'), "Gato negro café")
        
        self.assertIsNotNone(results.get('address'))
        self.assertIn("Juchitán de Zaragoza", results.get('address'))
        
        self.assertIsNotNone(results.get('phone'))
        self.assertEqual(results.get('phone'), "529514649222")
        
        self.assertIsNotNone(results.get('website'))
        self.assertIn("instagram.com", results.get('website'))
        
        self.assertIsNotNone(results.get('rating'))
        self.assertEqual(results.get('rating'), 4.3)
        
        self.assertIsNotNone(results.get('open_hours'))
        self.assertIn("Thursday", results.get('open_hours'))
        
        print("Extraction successful! Metadata:")
        print(json.dumps(results.get('_source_metadata'), indent=2))
        
        # Print critical results
        print(f"Name: {results.get('name')}")
        print(f"Address: {results.get('address')}")
        print(f"Phone: {results.get('phone')}")
        print(f"Rating: {results.get('rating')}")

if __name__ == '__main__':
    unittest.main()
