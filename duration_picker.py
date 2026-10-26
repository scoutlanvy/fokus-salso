from typing import Optional

import customtkinter as ctk

import config

DRAG_PIXELS_PER_STEP = 10


class WheelColumn(ctk.CTkFrame):
    def __init__(
        self,
        master,
        title: str,
        minimum: int,
        maximum: int,
        initial: int,
        width: int = 72,
        height: int = 96,
    ):
        super().__init__(master, fg_color="transparent")
        self.minimum = minimum
        self.maximum = maximum
        self._value = initial
        self._enabled = True
        self._drag_y: Optional[int] = None
        self._drag_accumulator = 0

        ctk.CTkLabel(self, text=title, font=("Helvetica", 11)).pack(pady=(0, 4))

        self.wheel_frame = ctk.CTkFrame(
            self,
            width=width,
            height=height,
            corner_radius=8,
            fg_color=("gray90", "gray17"),
        )
        self.wheel_frame.pack()
        self.wheel_frame.pack_propagate(False)

        self.prev_label = ctk.CTkLabel(
            self.wheel_frame,
            text="",
            font=("Consolas", 14),
            text_color=("gray55", "gray45"),
            height=22,
        )
        self.prev_label.pack(pady=(6, 0))

        self._input_var = ctk.StringVar(value=self._format_value(initial))
        self.current_entry = ctk.CTkEntry(
            self.wheel_frame,
            textvariable=self._input_var,
            font=("Consolas", 22, "bold"),
            width=width,
            height=30,
            border_width=0,
            corner_radius=0,
            fg_color=("gray90", "gray17"),
            justify="center",
            validate="key",
            validatecommand=(self.register(self._validate_input), "%P"),
        )
        self.current_entry.pack(pady=0)
        self.current_entry.bind("<Return>", self._commit_input)
        self.current_entry.bind("<FocusOut>", self._commit_input)
        self.current_entry.bind("<MouseWheel>", self._on_mousewheel)

        self.next_label = ctk.CTkLabel(
            self.wheel_frame,
            text="",
            font=("Consolas", 14),
            text_color=("gray55", "gray45"),
            height=22,
        )
        self.next_label.pack(pady=(0, 6))

        self._bind_wheel_events(self)
        self._bind_wheel_events(self.wheel_frame)
        for widget in (self.prev_label, self.next_label):
            self._bind_wheel_events(widget)

        self._refresh_labels()

    def _bind_wheel_events(self, widget) -> None:
        widget.bind("<MouseWheel>", self._on_mousewheel)
        widget.bind("<Button-1>", self._on_drag_start)
        widget.bind("<B1-Motion>", self._on_drag_motion)
        widget.bind("<ButtonRelease-1>", self._on_drag_end)

    def _format_value(self, value: int) -> str:
        return f"{value:02d}"

    def _validate_input(self, proposed: str) -> bool:
        return len(proposed) <= 2 and all("0" <= char <= "9" for char in proposed)

    def _commit_input(self, _event=None) -> None:
        if not self._enabled:
            return
        text = self._input_var.get()
        if text and self._validate_input(text):
            value = int(text)
            if self.minimum <= value <= self.maximum:
                self._value = value
        self._refresh_labels()

    def _wrap(self, value: int) -> int:
        span = self.maximum - self.minimum + 1
        offset = (value - self.minimum) % span
        return self.minimum + offset

    def _step(self, delta: int) -> None:
        if not self._enabled or delta == 0:
            return
        self._commit_input()
        self._value = self._wrap(self._value + delta)
        self._refresh_labels()

    def _refresh_labels(self) -> None:
        self.prev_label.configure(text=self._format_value(self._wrap(self._value - 1)))
        self._input_var.set(self._format_value(self._value))
        self.next_label.configure(text=self._format_value(self._wrap(self._value + 1)))

    def _on_mousewheel(self, event) -> None:
        if not self._enabled:
            return
        if event.delta > 0:
            self._step(-1)
        elif event.delta < 0:
            self._step(1)

    def _on_drag_start(self, event) -> None:
        if not self._enabled:
            return
        self._drag_y = event.y_root
        self._drag_accumulator = 0

    def _on_drag_motion(self, event) -> None:
        if not self._enabled or self._drag_y is None:
            return
        delta_y = self._drag_y - event.y_root
        self._drag_accumulator += delta_y
        self._drag_y = event.y_root

        steps, remainder = divmod(abs(self._drag_accumulator), DRAG_PIXELS_PER_STEP)
        if steps == 0:
            return

        direction = 1 if self._drag_accumulator > 0 else -1
        self._step(direction * steps)
        self._drag_accumulator = remainder if self._drag_accumulator >= 0 else -remainder

    def _on_drag_end(self, _event) -> None:
        self._drag_y = None
        self._drag_accumulator = 0

    def get_value(self) -> int:
        self._commit_input()
        return self._value

    def set_value(self, value: int) -> None:
        self._value = self._wrap(value)
        self._refresh_labels()

    def set_enabled(self, enabled: bool) -> None:
        self._commit_input()
        self._enabled = enabled
        self._drag_y = None
        self._drag_accumulator = 0
        if enabled:
            side_color = ("gray55", "gray45")
            center_color = ("gray10", "gray90")
        else:
            side_color = ("gray45", "gray55")
            center_color = ("gray45", "gray55")
        self.prev_label.configure(text_color=side_color)
        self.next_label.configure(text_color=side_color)
        self.current_entry.configure(
            text_color=center_color,
            state=ctk.NORMAL if enabled else ctk.DISABLED,
        )


class DurationPicker(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master, fg_color="transparent")

        columns_frame = ctk.CTkFrame(self, fg_color="transparent")
        columns_frame.pack()

        self.hours_column = WheelColumn(
            columns_frame,
            "Hours",
            0,
            config.MAX_HOURS,
            config.DEFAULT_HOURS,
        )
        self.hours_column.pack(side="left", padx=6)

        self.minutes_column = WheelColumn(
            columns_frame,
            "Minutes",
            0,
            config.MAX_MINUTES,
            config.DEFAULT_MINUTES,
        )
        self.minutes_column.pack(side="left", padx=6)

        self.seconds_column = WheelColumn(
            columns_frame,
            "Seconds",
            0,
            config.MAX_SECONDS,
            config.DEFAULT_SECONDS,
        )
        self.seconds_column.pack(side="left", padx=6)

    def get_total_seconds(self) -> int:
        return (
            self.hours_column.get_value() * 3600
            + self.minutes_column.get_value() * 60
            + self.seconds_column.get_value()
        )

    def set_hms(self, hours: int, minutes: int, seconds: int) -> None:
        self.hours_column.set_value(hours)
        self.minutes_column.set_value(minutes)
        self.seconds_column.set_value(seconds)

    def set_enabled(self, enabled: bool) -> None:
        self.hours_column.set_enabled(enabled)
        self.minutes_column.set_enabled(enabled)
        self.seconds_column.set_enabled(enabled)
