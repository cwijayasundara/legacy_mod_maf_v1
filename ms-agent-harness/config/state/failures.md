# Raw Failure Data
#
# Append-only log of all failures across all modules.
# Used for pattern extraction → learned-rules.md.
# When the same error_category appears 2+ times, extract a learned rule.
#
# Format per entry:
# ### <module> — Attempt <N> — <date>
# - Category: <error_category>
# - Layer: <unit|integration|contract>
# - File: <path>
# - Error: <description>
# - Fix attempted: <what was tried>
# - Result: <fixed|still failing>

# ─── Failures will be logged here ───
