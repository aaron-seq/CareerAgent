"""Contact inputs are explicit facts and local guesses, never verification."""

from unittest.mock import Mock

import pytest

from core import facade
from core.models import ContactCandidate


@pytest.fixture(autouse=True)
def no_contact_network(monkeypatch):
    forbidden = Mock(
        side_effect=AssertionError("Local contact inputs must not use network")
    )
    monkeypatch.setattr("core.outreach.verification._default_resolver", forbidden)
    monkeypatch.setattr("core.contact_finder.DDGS", forbidden)
    return forbidden


def test_manual_input_is_trimmed_and_never_verified(no_contact_network):
    contact = facade.create_manual_contact(
        " Jane Smith ", " Jane@EXAMPLE.test ", " Recruiter "
    )
    assert contact.name == "Jane Smith"
    assert contact.email == "Jane@EXAMPLE.test"
    assert contact.role == "Recruiter"
    assert contact.source == "manual"
    assert contact.email_confidence == "unknown"
    assert contact.confidence_score == 0
    no_contact_network.assert_not_called()


@pytest.mark.parametrize(
    "address",
    [
        "",
        "not-an-email",
        "x@y",
        "name@bad_domain.test",
        ".name@example.test",
        "name.@example.test",
        "first..last@example.test",
    ],
)
def test_invalid_manual_email_is_rejected(address):
    with pytest.raises(ValueError, match="valid email address"):
        facade.create_manual_contact("Jane Smith", address)


def test_blank_name_has_actionable_error():
    with pytest.raises(ValueError, match="contact's name"):
        facade.create_manual_contact("  ", "jane@example.test")


def test_email_local_part_limit_is_checked_without_rejecting_the_boundary():
    assert facade.create_manual_contact("Candidate", "a" * 64 + "@example.test").email
    with pytest.raises(ValueError, match="valid email address"):
        facade.create_manual_contact("Candidate", "a" * 65 + "@example.test")


@pytest.mark.parametrize(
    "domain",
    [
        "",
        "https://company.test",
        "company.test/path",
        "user@company.test",
        "company.test:443",
        "company .test",
        "localhost",
        "127.0.0.1",
    ],
)
def test_pattern_generation_requires_an_explicit_valid_domain(domain):
    with pytest.raises(ValueError, match="known email domain"):
        facade.generate_contact_patterns("Jane", "Smith", domain)


@pytest.mark.parametrize("first,last", [("", "Smith"), ("Jane", " ")])
def test_missing_name_is_validation_error_instead_of_index_error(first, last):
    with pytest.raises(ValueError, match="both a first name and a last name"):
        facade.generate_contact_patterns(first, last, "company.test")


def test_patterns_remain_guesses_and_preserve_explicit_domain(no_contact_network):
    contacts = facade.generate_contact_patterns(" Jane ", " Smith ", " COMPANY.TEST ")
    assert [contact.email for contact in contacts] == [
        "jane.smith@company.test",
        "jane@company.test",
        "janesmith@company.test",
    ]
    assert all(
        contact.source == "email_permutation" and contact.email_confidence == "guessed"
        for contact in contacts
    )
    no_contact_network.assert_not_called()


def test_names_not_supported_in_email_patterns_have_manual_fallback():
    with pytest.raises(ValueError, match="manual contact"):
        facade.generate_contact_patterns("José", "García", "company.test")


def test_merging_contacts_deduplicates_without_overwriting_reviewed_record():
    original = ContactCandidate(
        name="Reviewed Person", email="Jane@company.test", source="manual"
    )
    duplicate = ContactCandidate(
        name="Inferred Person", email="jane@COMPANY.test", source="email_permutation"
    )
    other = ContactCandidate(name="Other Person", email="other@company.test")
    existing = [original]
    merged = facade.merge_contacts(existing, [duplicate, other, other])
    assert merged == [original, other]
    assert existing == [original]
    assert merged[0] is original
