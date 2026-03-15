def clean_text(value: str) -> str:
    lines = [line.strip() for line in value.splitlines()]
    non_empty = [line for line in lines if line]
    return "\n\n".join(non_empty)


def clean_plaintext(value: str) -> str:
    return clean_text(value)


def clean_markdown_text(value: str) -> str:
    lines = [line.rstrip() for line in value.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)
