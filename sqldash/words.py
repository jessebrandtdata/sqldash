"""Every model-facing string, copied from the spec."""

SUMMARY_SYSTEM = (
    "You explain SQL to the person who wrote it. Say in plain English what the query "
    "returns or changes: which tables it reads, how they are joined, what is filtered, "
    "how rows are grouped, and what one output row represents. Five sentences at most. "
    "Work only from the text of the query. Do not guess at what the tables contain or "
    "at a business meaning the query does not show. If the text is not valid {dialect} "
    "or its meaning is unclear, say what is unclear. Plain prose: no Markdown, no "
    "rewritten SQL."
)


def summary_user(dialect_label: str, sql: str) -> str:
    return f"Dialect: {dialect_label}\n\n{sql}"


JUDGE_QUESTION = "agreement"

JUDGE_INSTRUCTIONS = "Does the English description say what the SQL query does?"

JUDGE_CRITERIA: dict[str, str] = {
    "agrees": (
        "Everything the description says is true of the query, and it leaves out "
        "nothing that changes the result."
    ),
    "differs": (
        "The description says something the query does not do, or leaves out "
        "something that changes the result."
    ),
    "cannot_tell": (
        "The description is too vague, or the query too unclear, to decide."
    ),
}
