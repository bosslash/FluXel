"""カンバン列・ステータス遷移の定数。"""

STATUS_ORDER = ("todo", "doing", "wait", "finish", "archive")
NEXT_STATUS = {
    "todo": "doing",
    "doing": "wait",
    "wait": "finish",
    "finish": "archive",
}
PREV_STATUS = {
    "archive": "finish",
    "finish": "wait",
    "wait": "doing",
    "doing": "todo",
}

STATUS_UI_CHOICES: tuple[tuple[str, str], ...] = (
    ("ToDo", "todo"),
    ("Doing", "doing"),
    ("Wait", "wait"),
    ("Finish", "finish"),
    ("Archive", "archive"),
)
