from sqldash.errors import STATUS, sentence


def test_every_kind_has_status_and_sentence():
    for kind in STATUS:
        assert sentence(kind, var="X")
    assert sentence("missing_key", var="TYPESAFE_API_KEY").startswith("TYPESAFE_API_KEY is not set")
