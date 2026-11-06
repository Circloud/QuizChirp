from dataclasses import dataclass
from threading import Lock
from .config import TRIGGER_MODES


@dataclass(frozen=True)
class Request:
    number: int
    x: int
    y: int
    deadline: float
    capture_only: bool = False


class Gate:
    """Claim a click burst and its request atomically on the input thread."""

    def __init__(self, interval, tolerance, timeout=300, trigger_mode="left_triple"):
        self.interval = interval
        self.tolerance = tolerance
        self.timeout = timeout
        self.lock = Lock()
        self.ready = False
        self.closed = False
        self.current = None
        self.serial = 0
        self.last = float("-inf")
        self.anchor = (0, 0)
        self.count = 0
        self.used = False
        self.right_pressed = False
        self.set_trigger_mode(trigger_mode)

    def set_trigger_mode(self, mode):
        if mode not in TRIGGER_MODES:
            raise ValueError("Invalid trigger mode")
        with self.lock:
            self.trigger_mode = mode
            self.last = float("-inf")
            self.count = 0
            self.used = False

    def enable(self, ready):
        with self.lock:
            self.ready = ready

    def set_right_pressed(self, pressed):
        with self.lock:
            if self.right_pressed != pressed:
                self.right_pressed = pressed
                # A chord must hold right throughout all three left presses.
                # Preserve a consumed burst until its normal time/position reset.
                self.count = 0

    def click(self, x, y, now, button="left"):
        with self.lock:
            if self.closed:
                return None
            capture_only = self.right_pressed
            expected = "middle" if self.trigger_mode == "middle_single" else "left"
            if button != expected:
                return None
            if button == "middle":
                if not self.ready or self.current is not None:
                    return None
                self.serial += 1
                self.current = Request(self.serial, x, y, now + self.timeout, capture_only)
                return self.current
            dx, dy = self.tolerance
            if (now - self.last > self.interval or abs(x - self.anchor[0]) > dx
                    or abs(y - self.anchor[1]) > dy):
                self.count = 0
                self.used = False
                self.anchor = (x, y)
            self.last = now
            self.count += 1
            if not self.ready or self.current is not None:
                self.used = True
            if self.used or self.count != 3:
                return None
            self.used = True
            self.serial += 1
            self.current = Request(self.serial, x, y, now + self.timeout, capture_only)
            return self.current

    def finish(self, request, result, now):
        with self.lock:
            if self.closed or self.current != request:
                return None
            self.current = None
            return result if now < request.deadline else "FAIL"

    def close(self):
        with self.lock:
            self.closed = True
            self.current = None
