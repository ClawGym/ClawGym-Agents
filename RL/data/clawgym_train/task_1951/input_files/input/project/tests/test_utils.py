# TODO: add negative tests

import unittest
from app.utils import get_env, to_json

class UtilsTest(unittest.TestCase):
    def test_to_json(self):
        data = {"a": 1, "b": 2}
        s = to_json(data)
        self.assertEqual(s, '{"a":1,"b":2}')

if __name__ == "__main__":
    unittest.main()