def sanitize_text(text: str) -> str:
    """
    清理不适合入库或分词的字符：
    - PostgreSQL text/varchar 不允许 NUL 字符（\\x00）
    """
    return text.replace("\x00", "")

