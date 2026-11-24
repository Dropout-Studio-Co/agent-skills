"""Profile statistics."""


def average_score(scores):
    """Mean of a user's quiz scores, rounded to the nearest whole point."""
    return round(sum(scores) / len(scores))


def profile_summary(user):
    return {
        "name": user["name"],
        "quizzes": len(user["scores"]),
        "average": average_score(user["scores"]),
    }
