import re

from pipecat.utils.text.base_text_filter import BaseTextFilter


class EmojiTextFilter(BaseTextFilter):
    """Strip Unicode emoji and :shortcode: tokens so TTS does not speak them."""

    _SHORTCODE = re.compile(r":[a-zA-Z0-9_+-]+:")
    _EMOJI = re.compile(
        "["
        "\U0001F1E6-\U0001F1FF"  # flags
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F680-\U0001F6FF"  # transport & map
        "\U0001F700-\U0001FAFF"  # alchemical through symbols extended-A
        "\U00002600-\U000027BF"  # misc symbols & dingbats
        "\U0000FE00-\U0000FE0F"  # variation selectors
        "\U0000200D"  # zero-width joiner
        "\U000020E3"  # combining enclosing keycap
        "]+"
    )
    _MULTI_SPACE = re.compile(r" {2,}")

    async def filter(self, text: str) -> str:
        text = self._SHORTCODE.sub("", text)
        text = self._EMOJI.sub("", text)
        return self._MULTI_SPACE.sub(" ", text)
