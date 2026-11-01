import re

HELP_QUEUE = "help"
HELP_REPLY_QUEUE = "help.reply"

_META = re.compile(
    r"#help ticket_id=(?P<ticket_id>\d+) user_id=(?P<user_id>\d+) dialog_id=(?P<dialog_id>\d+)"
)


def format_help_message(data: dict) -> str:
    return (
        f"Обращение #{data['ticket_id']}\n"
        f"от {data['user_name']} (user {data['user_id']}, диалог {data['dialog_id']})\n\n"
        f"{data['text']}\n\n"
        f"#help ticket_id={data['ticket_id']} user_id={data['user_id']} dialog_id={data['dialog_id']}"
    )


def parse_help_meta(text: str) -> dict | None:
    match = _META.search(text or "")
    if match is None:
        return None
    return {
        "ticket_id": int(match.group("ticket_id")),
        "user_id": int(match.group("user_id")),
        "dialog_id": int(match.group("dialog_id")),
    }


def build_help_reply(source_text: str | None, answer: str | None) -> dict | None:
    meta = parse_help_meta(source_text or "")
    if meta is None or not answer or not answer.strip():
        return None
    return {**meta, "text": answer.strip()}
