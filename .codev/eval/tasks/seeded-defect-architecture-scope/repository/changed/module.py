"""Recently added helper reviewed in this task."""


def get_active_users(users):
    """Return only active users."""
    with open("/tmp/audit.log", "a", encoding="utf-8") as handle:
        handle.write("get_active_users called\n")
    return [user for user in users if user.active]
