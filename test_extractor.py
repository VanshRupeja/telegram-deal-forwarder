"""Unit tests for extractor module."""

import unittest
from telethon.tl.types import Message, MessageEntityTextUrl, MessageEntityUrl
from extractor import extract_deal_urls, has_deal_urls


class DummyMessage:
    def __init__(self, text, entities=None):
        self.text = text
        self.message = text
        self.entities = entities or []


class TestExtractor(unittest.TestCase):
    def setUp(self):
        self.allowed = ["amazon", "amzn", "flipkart", "fkrt", "myntra", "ajio"]

    def test_plain_urls(self):
        msg = DummyMessage("Check out this laptop: https://www.amazon.in/dp/B09XYZ?tag=deal and https://fkrt.it/xyz!")
        urls = extract_deal_urls(msg, filter_domains=True, allowed_domains=self.allowed)
        self.assertEqual(len(urls), 2)
        self.assertIn("https://www.amazon.in/dp/B09XYZ?tag=deal", urls)
        self.assertIn("https://fkrt.it/xyz", urls)

    def test_domain_filtering_ignores_unwanted_domains(self):
        msg = DummyMessage("Watch review here: https://youtube.com/watch?v=123 or buy at https://amzn.to/3abc")
        urls = extract_deal_urls(msg, filter_domains=True, allowed_domains=self.allowed)
        self.assertEqual(urls, ["https://amzn.to/3abc"])

    def test_telegram_rich_entities_text_url(self):
        # Hyperlink hidden behind text: "[Click Here](https://amzn.to/deal123)"
        entity = MessageEntityTextUrl(offset=0, length=10, url="https://amzn.to/deal123")
        msg = DummyMessage("Click Here to buy!", entities=[entity])
        urls = extract_deal_urls(msg, filter_domains=True, allowed_domains=self.allowed)
        self.assertEqual(urls, ["https://amzn.to/deal123"])

    def test_disable_filter_accepts_any_url(self):
        msg = DummyMessage("Visit https://example.com/item")
        urls = extract_deal_urls(msg, filter_domains=False)
        self.assertEqual(urls, ["https://example.com/item"])

    def test_has_deal_urls(self):
        msg1 = DummyMessage("Just a regular chat message without links.")
        self.assertFalse(has_deal_urls(msg1, filter_domains=True, allowed_domains=self.allowed))

        msg2 = DummyMessage("Loot deal: https://myntra.com/shoes")
        self.assertTrue(has_deal_urls(msg2, filter_domains=True, allowed_domains=self.allowed))


if __name__ == "__main__":
    unittest.main()
