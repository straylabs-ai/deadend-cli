import tiktoken


def num_tokens_from_string(string: str, encoding_name: str = "o200k_base") -> int:
    """Returns the number of tokens in a text string using tiktoken."""
    encoding = tiktoken.get_encoding(encoding_name)
    return len(encoding.encode(string))

def truncate_string(string: str | bytes | object, encoding_name: str = "o200k_base", max_tokens: int = 20000) -> str:
    """Truncate a string to a maximum number of tokens.

    Args:
        string: The input to truncate (string, bytes, or any object)
        encoding_name: The tiktoken encoding name
        max_tokens: Maximum number of tokens to keep

    Returns:
        The truncated string
    """
    # Convert to string if needed
    if isinstance(string, bytes):
        try:
            string = string.decode('utf-8', errors='replace')
        except Exception:
            string = str(string)
    elif not isinstance(string, str):
        string = str(string)

    encoding = tiktoken.get_encoding(encoding_name)
    tokens = encoding.encode(string)
    number_tokens = len(tokens)

    if number_tokens <= max_tokens:
        return string

    truncated_tokens = tokens[:max_tokens]
    truncated_string = encoding.decode(truncated_tokens)

    return truncated_string + f"...[truncated {number_tokens - max_tokens} tokens]"