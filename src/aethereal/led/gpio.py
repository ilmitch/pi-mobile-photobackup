"""GPIO-backed LED output for the Raspberry Pi (LED-002).

``gpiozero`` is a Pi-only dependency (the ``pi`` optional group) and is imported lazily so
this module can be imported anywhere; only constructing :class:`GpioLedOutput` requires the
hardware and the dependency.
"""

from __future__ import annotations


class GpioLedOutput:
    """Drives a status LED on a GPIO pin via gpiozero."""

    def __init__(self, pin: int) -> None:
        from gpiozero import LED  # lazy import: Pi-only dependency

        self._led = LED(pin)

    def set(self, on: bool) -> None:
        if on:
            self._led.on()
        else:
            self._led.off()
