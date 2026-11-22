"""Error kinds, their HTTP statuses and the sentence shown for each."""

STATUS: dict[str, int] = {
    "empty": 400,
    "too_long": 400,
    "bad_request": 400,
    "forbidden": 403,
    "not_found": 404,
    "too_big": 413,
    "missing_key": 503,
    "bad_key": 502,
    "rate_limit": 429,
    "timeout": 504,
    "network": 502,
    "refusal": 422,
    "cut_off": 502,
    "upstream": 502,
    "internal": 500,
}

_SENTENCES: dict[str, str] = {
    "empty": "Nothing to send: the box is empty.",
    "too_long": "This SQL is over 50,000 characters, which is the limit for the AI calls.",
    "bad_request": "The request was not understood.",
    "forbidden": "sqldash does not answer to this address. Add its name to SQLDASH_ALLOWED_HOSTS.",
    "not_found": "There is nothing at that address.",
    "too_big": "The request is larger than sqldash accepts.",
    "missing_key": "{var} is not set, so this button is off.",
    "bad_key": "The service rejected the key in {var}.",
    "rate_limit": "The service is rate-limiting this key. Try again shortly.",
    "timeout": "The service did not answer in time.",
    "network": "The service could not be reached.",
    "refusal": "The model declined to answer for this text.",
    "cut_off": "The answer was cut off before it finished.",
    "upstream": "The service returned an answer sqldash could not use.",
    "internal": "sqldash hit an error of its own.",
}


class ServiceError(Exception):
    """A failure with a kind; detail is the variable name for key errors."""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(kind, detail)
        self.kind = kind
        self.detail = detail


def sentence(kind: str, var: str = "") -> str:
    """Return the plain-text sentence for an error kind."""
    return _SENTENCES[kind].format(var=var)
