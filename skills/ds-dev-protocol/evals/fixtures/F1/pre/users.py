"""User records."""


def new_user(name):
    """Create the record for a user who just signed up."""
    return {"name": name, "scores": []}


def record_score(user, score):
    user["scores"].append(score)
