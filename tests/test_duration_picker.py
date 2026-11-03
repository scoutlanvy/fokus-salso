from types import SimpleNamespace

import customtkinter as ctk
import pytest

from focus_timer import config
from focus_timer.ui.duration_picker import DurationPicker


@pytest.fixture(scope="module")
def root():
    root = ctk.CTk()
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def picker(root):
    widget = DurationPicker(root)
    widget.pack()
    root.update_idletasks()
    yield widget
    widget.destroy()


def type_value(column, text):
    column.current_entry.delete(0, "end")
    column.current_entry.insert(0, text)


@pytest.mark.parametrize("name,maximum", [
    ("hours_column", 99), ("minutes_column", 59), ("seconds_column", 59),
])
def test_scroll_direction_and_wrap(picker, name, maximum):
    column = getattr(picker, name)
    column.set_value(17)
    column._on_mousewheel(SimpleNamespace(delta=-120))
    assert column.get_value() == 18
    column._on_mousewheel(SimpleNamespace(delta=120))
    assert column.get_value() == 17
    column.set_value(maximum)
    column._on_mousewheel(SimpleNamespace(delta=-120))
    assert column.get_value() == 0
    column._on_mousewheel(SimpleNamespace(delta=120))
    assert column.get_value() == maximum


def test_total_reads_pending_typing_and_formats_two_digits(picker):
    type_value(picker.hours_column, "2")
    type_value(picker.minutes_column, "3")
    type_value(picker.seconds_column, "4")
    assert picker.get_total_seconds() == 7384
    assert [column.current_entry.get() for column in (
        picker.hours_column, picker.minutes_column, picker.seconds_column
    )] == ["02", "03", "04"]


@pytest.mark.parametrize("text", ["", "60", "99"])
def test_invalid_minutes_restore_committed_value(picker, text):
    column = picker.minutes_column
    column.set_value(17)
    type_value(column, text)
    assert column.get_value() == 17
    assert column.current_entry.get() == "17"


@pytest.mark.parametrize("text", ["abc", "-1", "1.5", "123", " 5"])
def test_entry_rejects_invalid_insertions(picker, text):
    column = picker.minutes_column
    type_value(column, text)
    assert column.current_entry.get() == ""
    assert column.get_value() == config.DEFAULT_MINUTES


@pytest.mark.parametrize("event", ["<FocusOut>", "<Return>"])
def test_commit_events_format_entry_and_update_neighbors(picker, event):
    root = picker.winfo_toplevel()
    root.attributes("-alpha", 0)
    root.deiconify()
    root.update()
    column = picker.minutes_column
    column.current_entry.focus_force()
    root.update()
    type_value(column, "8")
    column.current_entry._entry.event_generate(event)
    root.update()
    assert column.current_entry.get() == "08"
    assert column.prev_label.cget("text") == "07"
    assert column.next_label.cget("text") == "09"


def test_scroll_applies_to_pending_input(picker):
    column = picker.minutes_column
    type_value(column, "40")
    column._on_mousewheel(SimpleNamespace(delta=-120))
    assert column.get_value() == 41


def test_disable_blocks_typing_scroll_and_drag_then_reenables(picker):
    column = picker.minutes_column
    type_value(column, "12")
    picker.set_enabled(False)
    type_value(column, "30")
    column._on_mousewheel(SimpleNamespace(delta=-120))
    column._on_drag_start(SimpleNamespace(y_root=100))
    column._on_drag_motion(SimpleNamespace(y_root=80))
    assert column.current_entry.cget("state") == ctk.DISABLED
    assert column.get_value() == 12
    picker.set_enabled(True)
    type_value(column, "30")
    assert column.get_value() == 30


def test_drag_and_programmatic_reset_remain_available(picker):
    column = picker.minutes_column
    column.set_value(17)
    column._on_drag_start(SimpleNamespace(y_root=100))
    column._on_drag_motion(SimpleNamespace(y_root=80))
    column._on_drag_end(None)
    assert column.get_value() == 19
    type_value(column, "45")
    picker.set_hms(config.DEFAULT_HOURS, config.DEFAULT_MINUTES, config.DEFAULT_SECONDS)
    assert picker.get_total_seconds() == (
        config.DEFAULT_HOURS * 3600 + config.DEFAULT_MINUTES * 60 + config.DEFAULT_SECONDS
    )


def test_input_has_space_for_two_digits_without_a_border(picker):
    column = picker.hours_column
    assert column.current_entry.cget("border_width") == 0
    assert column.current_entry.cget("justify") == "center"
    assert column.current_entry.cget("font")[1:] == (22, "bold")
    assert column.current_entry.cget("width") >= 60
