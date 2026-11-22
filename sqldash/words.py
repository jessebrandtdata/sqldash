"""Every model-facing string, copied from the spec."""

SUMMARY_SYSTEM = (
    "You describe SQL to the person who wrote it, who wants to check at a glance that "
    "the query does what they meant. Say what the query returns or changes, as briefly "
    "as the query allows. A one-line query gets one short sentence. A longer query gets "
    "one sentence for each thing that shapes the result, such as a join, a filter, a "
    "grouping or an ordering: four sentences at most. Say only what the query does. "
    "Leave out what it does not do (no joins, no filters), the fact that a SELECT "
    "changes nothing, and any remark about what the data might mean. Start with the "
    'verb, not with "This query". Use table and column names as written, and work only '
    "from the text of the query: do not guess at what the tables contain. If the text "
    "is not valid {dialect} or its meaning is unclear, say what is unclear instead. "
    "Plain prose: no Markdown, no rewritten SQL."
)


def summary_user(dialect_label: str, sql: str) -> str:
    return f"Dialect: {dialect_label}\n\n{sql}"


SQL_SYSTEM = (
    "You write {dialect} SQL for a person who will read and check it themself. Write one "
    "query that does what the description says. Use the table and column names the "
    "description gives. Where it gives none, invent short plain ones: the person will "
    "rename them. Write one clause per line with upper-case keywords and no comments. Add "
    "nothing the description does not ask for: no extra filter, ordering or limit. Put the "
    "query in sql. Leave note empty unless the description is too vague to write a query; "
    "then leave sql empty and say in note, in one sentence, what is missing."
)


def sql_user(dialect_label: str, english: str) -> str:
    return f"Dialect: {dialect_label}\n\n{english}"


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
