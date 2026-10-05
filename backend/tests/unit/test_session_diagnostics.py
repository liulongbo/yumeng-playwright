import hashlib
import hmac

from xingtu.diagnostics import profile_file_metadata, value_hmac


def test_value_hmac_is_stable_and_does_not_expose_plaintext():
    secret = b"diagnostic-key-with-at-least-32-bytes"
    token = "sensitive-cookie-value"
    digest = value_hmac(secret, token)
    assert digest == hmac.new(secret, token.encode(), hashlib.sha256).hexdigest()
    assert token not in digest
    assert len(digest) == 64


def test_profile_metadata_records_presence_without_reading_content(tmp_path):
    profile = tmp_path / "profile"
    default = profile / "Default"
    default.mkdir(parents=True)
    (default / "Cookies").write_text("not-a-real-cookie-db")
    rows = {row["path"]: row for row in profile_file_metadata(profile)}
    assert rows["Default/Cookies"]["exists"] is True
    assert rows["Default/Cookies"]["size"] > 0
    assert rows["Default/Local Storage"]["exists"] is False
