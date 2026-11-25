import pytest

from synaptiq.utils.exceptions import GeminiError
from synaptiq.utils.parsing import parse_json_array


def test_parses_json_array_in_markdown_fence() -> None:
    assert parse_json_array('```json\n[{"front": "Q", "back": "A"}]\n```') == [
        {"front": "Q", "back": "A"}
    ]


@pytest.mark.parametrize("reply", ["not json", '{"item": 1}'])
def test_rejects_invalid_or_non_array_reply(reply: str) -> None:
    with pytest.raises(GeminiError):
        parse_json_array(reply)
