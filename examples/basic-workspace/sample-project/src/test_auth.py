"""
Tests for auth.py — used as the example target in the RelayKit walkthrough.
"""

import unittest

from auth import User, hash_password, login, verify_password


class AuthTests(unittest.TestCase):
    def test_password_round_trip(self) -> None:
        hashed = hash_password("hunter2")
        self.assertTrue(verify_password("hunter2", hashed))
        self.assertFalse(verify_password("wrong", hashed))

    def test_login_success(self) -> None:
        users = {"alice@example.com": User("1", "alice@example.com", hash_password("secret"))}
        result = login("alice@example.com", "secret", users)
        self.assertIsNotNone(result)
        self.assertEqual(result.email, "alice@example.com")

    def test_login_wrong_password(self) -> None:
        users = {"alice@example.com": User("1", "alice@example.com", hash_password("secret"))}
        self.assertIsNone(login("alice@example.com", "wrong", users))

    def test_login_unknown_user(self) -> None:
        self.assertIsNone(login("nobody@example.com", "secret", {}))


if __name__ == "__main__":
    unittest.main()
