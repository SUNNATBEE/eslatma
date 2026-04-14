import os
import tempfile
import unittest

os.environ.setdefault("BOT_TOKEN", "test-token")

from database import DatabaseService
from routes.student_routes import _normalize_mars_id
from utils import hash_secret, is_hashed_secret, verify_secret


class SecretUtilsTests(unittest.TestCase):
    def test_hash_secret_roundtrip(self) -> None:
        hashed = hash_secret("super-secret")
        self.assertTrue(is_hashed_secret(hashed))
        self.assertTrue(verify_secret(hashed, "super-secret"))
        self.assertFalse(verify_secret(hashed, "wrong-secret"))

    def test_verify_secret_supports_legacy_plaintext(self) -> None:
        self.assertTrue(verify_secret("12345", "12345"))
        self.assertFalse(verify_secret("12345", "54321"))

    def test_normalize_mars_id_supports_prefixed_values(self) -> None:
        self.assertEqual(_normalize_mars_id("p12345"), "P12345")
        self.assertEqual(_normalize_mars_id("  12345  "), "12345")


class DatabaseCredentialTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.db = DatabaseService(f"sqlite+aiosqlite:///{self.db_path}")
        await self.db.init_db()

    async def asyncTearDown(self) -> None:
        await self.db.engine.dispose()
        try:
            os.remove(self.db_path)
        except FileNotFoundError:
            pass

    async def test_add_student_credential_hashes_password(self) -> None:
        await self.db.add_student_credential("1001", "Ali Valiyev", "54321", "nF-2506")
        credential = await self.db.get_student_credential("1001")

        self.assertIsNotNone(credential)
        assert credential is not None
        self.assertTrue(is_hashed_secret(credential.password))
        self.assertTrue(verify_secret(credential.password, "54321"))

    async def test_upgrade_student_credential_password_hashes_legacy_value(self) -> None:
        from database import StudentCredential

        async with self.db.session_factory() as session:
            session.add(
                StudentCredential(
                    mars_id="1002",
                    name="Test User",
                    password="plain-pass",
                    group_name="nF-2506",
                )
            )
            await session.commit()

        upgraded = await self.db.upgrade_student_credential_password("1002", "plain-pass")
        credential = await self.db.get_student_credential("1002")

        self.assertTrue(upgraded)
        self.assertIsNotNone(credential)
        assert credential is not None
        self.assertTrue(is_hashed_secret(credential.password))
        self.assertTrue(verify_secret(credential.password, "plain-pass"))


if __name__ == "__main__":
    unittest.main()
