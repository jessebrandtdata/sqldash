from sqldash import errors
from sqldash.errors import STATUS, sentence


def test_every_kind_has_status_and_sentence():
    for kind in STATUS:
        assert sentence(kind, var="X")
    assert sentence("missing_key", var="TYPESAFE_API_KEY").startswith("TYPESAFE_API_KEY is not set")


def test_too_long_sentence_covers_both_kinds_of_text():
    assert errors.sentence("too_long") == "This text is over 50,000 characters, which is the limit for the AI calls."
