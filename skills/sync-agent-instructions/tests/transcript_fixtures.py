"""Committed synthetic transcript data shared by the collector and checker tests.

The strings here are the fixtures of record for the correction marker: ten
messages a person wrote to correct an agent, and ten that are questions or
ordinary requests. Held literals are never stored here; tests assemble them.
"""
import json
import re

CORRECTIONS = [
    "No, use bun here, not npm.",
    "Don't edit the generated client by hand.",
    "That's wrong, the config lives in the root folder.",
    "Stop running the full suite for a one-line change.",
    "I told you to keep the migration separate.",
    "Never push directly to the release branch.",
    "You should have run the formatter before committing.",
    "Not like that, put the helper next to its caller.",
    "Use the shared logger instead of console.log.",
    "You forgot to update the lockfile again.",
]

NON_CORRECTIONS = [
    "Should we add a retry to the upload step?",
    "No problem, thanks for the update.",
    "Why does the build never finish on CI?",
    "Add a guard so the job doesn't fail on empty input.",
    "Can you always show the total in the footer?",
    "What should the default timeout be?",
    "Please remember the last filter the user chose.",
    "Write a test that checks the stop button works.",
    "The wrong-password message needs better copy.",
    "Instead of a modal, what would a drawer look like?",
]


def encode(path):
    """Claude Code's project-directory encoding of a working directory."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def record(text, role="user", **fields):
    """A minimal Claude Code transcript record with a message body."""
    item = {"type": role, "message": {"role": role, "content": text}}
    item.update(fields)
    return item


def write_jsonl(path, records):
    with open(str(path), "w", encoding="utf-8") as handle:
        for item in records:
            handle.write(json.dumps(item) + "\n")


def opencode_user(text, **fields):
    data = {"text": text}
    data.update(fields)
    return ("user", data)


def opencode_assistant(content):
    return ("assistant", {"content": content})
