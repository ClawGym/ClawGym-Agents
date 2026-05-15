import unittest
from app.greet import build_greeting

class TestGreet(unittest.TestCase):
    def test_neutral_default(self):
        # Default should be a neutral, inclusive greeting
        self.assertEqual(build_greeting("Alex"), "Hello, Alex!")

    def test_ignore_honorific(self):
        # Honorifics should not trigger gendered terms
        self.assertEqual(build_greeting("Pat", honorific="Mr"), "Hello, Pat!")

    def test_none_honorific_safe(self):
        # None must be handled safely and remain neutral
        self.assertEqual(build_greeting("Riley", honorific=None), "Hello, Riley!")

if __name__ == "__main__":
    unittest.main()
