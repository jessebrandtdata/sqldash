# The dialects the checker and the page know about; only postgres is checked exactly.
DIALECTS = [
    {"id": "postgres", "label": "PostgreSQL", "exact": True, "engine": "pglast", "docs": "bundled"},
    {"id": "mysql", "label": "MySQL", "exact": False, "engine": "sqlglot", "docs": "links"},
    {"id": "redshift", "label": "Redshift", "exact": False, "engine": "sqlglot", "docs": "links"},
    {"id": "athena", "label": "Athena", "exact": False, "engine": "sqlglot", "docs": "links"},
]


def get(dialect_id):
    # Return the dialect row with this id, or raise ValueError if there is none.
    for row in DIALECTS:
        if row["id"] == dialect_id:
            return row
    raise ValueError(f"unknown dialect: {dialect_id}")
