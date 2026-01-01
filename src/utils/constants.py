"""Constants for job application pipeline."""

# Job evaluation status
STATUS_NOT_RELEVANT = 0  # Claude evaluated, not relevant
STATUS_PENDING = 1       # Claude evaluated, relevant, needs review
STATUS_REVIEWED = 2      # User reviewed, decided not to apply
STATUS_APPLIED = 3       # Application sent

STATUS_LABELS = {
    0: "Not Relevant",
    1: "Pending",
    2: "Reviewed",
    3: "Applied"
}
