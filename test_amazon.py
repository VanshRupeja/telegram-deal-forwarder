"""Unit tests for amazon affiliate module."""

import unittest
from amazon import is_amazon_url, extract_asin, inject_affiliate_tag


class TestAmazonModule(unittest.TestCase):
    def test_is_amazon_url(self):
        # Standard and shortened domains
        self.assertTrue(is_amazon_url("https://www.amazon.in/dp/B08N5WRWNW"))
        self.assertTrue(is_amazon_url("https://amzn.to/3xyz123"))
        self.assertTrue(is_amazon_url("https://amzn-to.co/HOcqii"))
        self.assertTrue(is_amazon_url("https://amznto.co/abc"))
        self.assertTrue(is_amazon_url("https://amzn.in/d/abc456"))
        self.assertTrue(is_amazon_url("https://a.co/d/abc"))
        self.assertTrue(is_amazon_url("https://amzn.urlgeni.us/https://www.amazon.in"))

        # Non-Amazon domains
        self.assertFalse(is_amazon_url("https://www.flipkart.com/product/xyz"))
        self.assertFalse(is_amazon_url("https://myntra.com/shoes"))
        self.assertFalse(is_amazon_url("https://www.ajio.com/s/shoes"))

    def test_extract_asin(self):
        url1 = "https://www.amazon.in/Sony-WH-1000XM4-Wireless-Cancelling-Headphones/dp/B0863TXGM3?ref=deals"
        self.assertEqual(extract_asin(url1), "B0863TXGM3")

        url2 = "https://www.amazon.com/gp/product/B07FZ8S74R/"
        self.assertEqual(extract_asin(url2), "B07FZ8S74R")

        url3 = "https://www.amazon.in/b?node=1389401031"
        self.assertIsNone(extract_asin(url3))

    def test_inject_affiliate_tag_with_asin(self):
        url = "https://www.amazon.in/Some-Product/dp/B0863TXGM3?tag=competitor-21&linkCode=ll1"
        converted = inject_affiliate_tag(url, "mydeal-21")
        self.assertEqual(converted, "https://www.amazon.in/dp/B0863TXGM3?tag=mydeal-21")

    def test_inject_affiliate_tag_category_search_page(self):
        url = "https://www.amazon.in/s?i=electronics&tag=extrape7500-21&sid=HOcqii&src=ot"
        converted = inject_affiliate_tag(url, "trendiloot-21")
        self.assertIn("tag=trendiloot-21", converted)
        self.assertNotIn("tag=extrape7500-21", converted)
        self.assertNotIn("sid=HOcqii", converted)


if __name__ == "__main__":
    unittest.main()
