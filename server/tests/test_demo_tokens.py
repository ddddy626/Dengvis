import pytest

from app.demo_tokens import InvalidDemoToken, issue_token, token_digest, token_from_authorization


def test_issue_token_is_opaque_unique_and_hash_only():
    first, first_hash = issue_token()
    second, second_hash = issue_token()
    assert first != second
    assert first_hash != second_hash
    assert first_hash == token_digest(first)
    assert first not in first_hash
    assert token_from_authorization(f"Bearer {first}") == first


@pytest.mark.parametrize("header", [None, "", "Basic abc", "Bearer ", "Bearer a b", "Bearer abc"])
def test_missing_or_malformed_bearer_is_rejected(header):
    with pytest.raises(InvalidDemoToken):
        token_from_authorization(header)
