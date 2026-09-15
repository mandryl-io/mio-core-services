"""WS2811/WS2812 pixel output on a Raspberry Pi 5.

The Pi 5 cannot bit-bang NeoPixels the way earlier boards did -- the old
rpi_ws281x DMA/PWM route does not exist on this silicon. Adafruit's Pi 5
library drives them from the RP1's PIO block instead, through `/dev/pio0`,
which is why that device node has to be present before any of this works.

Everything hardware-facing is imported lazily so the colour logic above can be
imported, and tested, on a machine with no LEDs attached.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_PIN = "D18"  # physical pin 12 on the header
DEFAULT_ORDER = "GRB"
DEFAULT_GAMMA = 2.2

Color = tuple[int, int, int]


def _gamma_table(gamma: float) -> tuple[int, ...]:
    """Map linear 0-255 to what the LED must be driven at to look that bright.

    Perceived brightness is roughly the 2.2 power of emitted light, so scaling
    raw channel values by a brightness fraction makes a dim LED look far
    brighter than asked. Correcting matters most at the bottom of the range,
    which is exactly where a brightness ladder spends its time.
    """
    return tuple(round(((level / 255.0) ** gamma) * 255.0) for level in range(256))


class Strip:
    """A run of pixels, addressed as one colour at a time.

    The head has a single WS2811 today, but nothing here assumes that; a
    longer strip just gets the same colour written to every pixel.
    """

    def __init__(self, buf, count: int, gamma: float, ceiling: float) -> None:
        self._buf = buf
        self._count = count
        self._gamma = _gamma_table(gamma) if gamma else None
        self._ceiling = ceiling

    def show(self, color: Color, brightness: float = 1.0) -> None:
        """Write one colour to every pixel, scaled to `brightness` (0.0-1.0)."""
        level = max(0.0, min(1.0, brightness)) * self._ceiling
        scaled = tuple(round(max(0, min(255, channel)) * level) for channel in color)
        if self._gamma is not None:
            scaled = tuple(self._gamma[channel] for channel in scaled)
        for index in range(self._count):
            self._buf[index] = scaled
        self._buf.show()

    def off(self) -> None:
        for index in range(self._count):
            self._buf[index] = (0, 0, 0)
        self._buf.show()


@dataclass(frozen=True)
class StripConfig:
    pin: str = DEFAULT_PIN
    count: int = 1
    order: str = DEFAULT_ORDER
    gamma: float = DEFAULT_GAMMA
    ceiling: float = 1.0


def open_strip(config: StripConfig) -> Strip:
    """Build a Strip, or explain precisely which part of the stack is missing."""
    try:
        import board
        import adafruit_pixelbuf
        from adafruit_raspberry_pi5_neopixel_write import neopixel_write
    except ImportError as exc:  # not the Pi, or the wrong environment
        raise SystemExit(
            f"Cannot import the LED stack ({exc}).\n"
            "These run on the Pi, in the environment holding Adafruit-Blinka and\n"
            "Adafruit-Blinka-Raspberry-Pi5-Neopixel. See docs/rgb-lighting.md."
        ) from exc

    try:
        pin = getattr(board, config.pin)
    except AttributeError as exc:
        raise SystemExit(f"No such pin as board.{config.pin}") from exc

    class Pi5Pixelbuf(adafruit_pixelbuf.PixelBuf):
        def __init__(self, pin, size, **kwargs):
            self._pin = pin
            super().__init__(size=size, **kwargs)

        def _transmit(self, buf):
            neopixel_write(self._pin, buf)

    try:
        buf = Pi5Pixelbuf(
            pin,
            config.count,
            # Brightness and gamma are applied in Strip.show, deliberately, so
            # the correction happens before the 8-bit values are quantised.
            auto_write=False,
            byteorder=config.order,
        )
    except FileNotFoundError as exc:  # /dev/pio0
        raise SystemExit(
            f"Cannot reach the PIO device ({exc}).\n"
            "Check `ls -l /dev/pio0`. If it is missing, the firmware is too old:\n"
            "  sudo apt update && sudo apt upgrade -y\n"
            "  sudo rpi-eeprom-update -a && sudo reboot"
        ) from exc
    except PermissionError as exc:
        raise SystemExit(
            f"Permission denied opening the PIO device ({exc}). Run with sudo -E, "
            "or add your user to the group owning /dev/pio0."
        ) from exc

    return Strip(buf, config.count, config.gamma, config.ceiling)
