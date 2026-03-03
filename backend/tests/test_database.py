"""Tests for database session factory."""

import unittest

from backend.db.session import get_engine, get_session


class TestDatabaseSessionFactory(unittest.TestCase):
    def test_get_engine_returns_same_engine(self):
        e1 = get_engine()
        e2 = get_engine()
        self.assertIs(e1, e2)

    def test_get_session_returns_new_session_each_time(self):
        s1 = get_session()
        s2 = get_session()
        try:
            self.assertIsNot(s1, s2)
            self.assertIs(s1.get_bind(), s2.get_bind())
        finally:
            s1.close()
            s2.close()
