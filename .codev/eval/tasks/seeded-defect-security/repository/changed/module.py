"""Recently added helper reviewed in this task."""


def find_user(cursor, username):
    """Return the first user row matching username."""
    query = f"SELECT * FROM users WHERE username = '{username}'"
    cursor.execute(query)
    return cursor.fetchone()
