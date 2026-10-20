import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from followwork.redact import redact  # noqa: E402


class RedactTest(unittest.TestCase):
    def test_iban(self):
        out = redact("Pay to BE71 0961 2345 6769 today")
        self.assertNotIn("0961", out)
        self.assertIn("[IBAN]", out)

    def test_iban_compact(self):
        self.assertIn("[IBAN]", redact("iban NL91ABNA0417164300"))

    def test_email(self):
        out = redact("Mail jan.peeters@client-bv.be about it")
        self.assertNotIn("jan.peeters", out)
        self.assertIn("[EMAIL]", out)

    def test_token(self):
        # Built at runtime so secret scanners do not flag fake test keys.
        for secret in ["sk-" + "ant-api03-" + "AbCdEfGh1234567890XyZ_qwerty",
                       "gh" + "p_" + "16C7e42F292c6912E7710c838347Ae178B4a",
                       "AKIA" + "IOSFODNN7EXAMPLE",
                       "eyJhbGciOiJIUzI1NiJ9." + "eyJzdWIiOiIxMjM0In0.abcDEF123"]:
            out = redact("key: " + secret)
            self.assertNotIn(secret, out, secret)
            self.assertIn("[TOKEN]", out, secret)

    def test_card(self):
        self.assertIn("[CARD]", redact("card 4111 1111 1111 1111"))

    def test_national_number(self):
        self.assertIn("[NATIONAL_NUMBER]", redact("RRN 85.07.30-033.28"))

    def test_keeps_work_words(self):
        text = "Filter: Joint committee = 200  Total gross 48,213.50"
        self.assertEqual(redact(text), text)


if __name__ == "__main__":
    unittest.main()
