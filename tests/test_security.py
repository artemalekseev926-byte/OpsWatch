from cryptography.fernet import Fernet

from opswatch.security import Crypto, LoginThrottle, hash_password, new_link_code, token_hash, verify_password


def test_password_hash_roundtrip():
    stored = hash_password("s3cret!")
    assert stored.startswith("scrypt$")
    assert verify_password("s3cret!", stored)
    assert not verify_password("wrong", stored)
    assert not verify_password("s3cret!", "garbage")


def test_password_hash_is_salted():
    assert hash_password("same") != hash_password("same")


def test_crypto_roundtrip_and_bad_token():
    crypto = Crypto(Fernet.generate_key().decode())
    encrypted = crypto.encrypt("пароль базы")
    assert encrypted and "пароль" not in encrypted
    assert crypto.decrypt(encrypted) == "пароль базы"
    assert crypto.decrypt("not-a-token") == ""
    assert crypto.decrypt_json(crypto.encrypt_json({"password": "x"})) == {"password": "x"}
    assert crypto.encrypt("") == ""


def test_other_key_cannot_decrypt():
    first = Crypto(Fernet.generate_key().decode())
    second = Crypto(Fernet.generate_key().decode())
    assert second.decrypt(first.encrypt("secret")) == ""


def test_link_code_and_token_hash():
    code = new_link_code()
    assert len(code) == 8 and code.isalnum() and code == code.upper()
    assert token_hash("a") == token_hash("a") != token_hash("b")


def test_login_throttle_locks_after_failures():
    throttle = LoginThrottle(attempts=3, window=60, lock=60)
    for _ in range(3):
        assert throttle.locked_for("ip:user") == 0
        throttle.failure("ip:user")
    assert throttle.locked_for("ip:user") > 0
    throttle.success("ip:user")
    assert throttle.locked_for("ip:user") == 0
