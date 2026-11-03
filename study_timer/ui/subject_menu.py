"""Scrollable subject choices and Windows context-menu lifecycle."""

import sys
from contextlib import contextmanager
from tkinter import Toplevel

import customtkinter as ctk


class SubjectOptionMenu(ctk.CTkOptionMenu):
    """Use Tk widgets for subject rows so Windows delivers right-click events."""

    def __init__(self, *args, context_command, **kwargs):
        super().__init__(*args, **kwargs)
        self.context_command = context_command
        self.subject_popup = None
        self.subject_rows = {}
        self.context_menu = None
        self._restore_subject_popup = True

    def close_subject_popup(self):
        if self.context_menu is not None:
            menu, self.context_menu = self.context_menu, None
            menu.unpost()
            menu.grab_release()
        if self.subject_popup is not None:
            self.subject_popup.grab_release()
            self.subject_popup.destroy()
            self.subject_popup = None
            self.subject_rows = {}

    def _clicked(self, event=None):
        if self.subject_popup is not None:
            self.close_subject_popup()
        elif self.cget("state") != ctk.DISABLED:
            # CTk's global Button-1 handler focuses the clicked control. Wait for
            # that handler before moving focus into the popup, or FocusOut closes it.
            self.after_idle(self._open_dropdown_menu)

    def _open_dropdown_menu(self):
        if self.cget("state") == ctk.DISABLED:
            return
        self.close_subject_popup()
        popup = self.subject_popup = Toplevel(self)
        popup.withdraw()
        popup.overrideredirect(True)
        popup.transient(self.winfo_toplevel())
        width = max(self.winfo_width(), 220)
        height = round(self._apply_widget_scaling(min(300, len(self.cget("values")) * 36 + 12)))
        x = min(self.winfo_rootx(), self.winfo_screenwidth() - width)
        y = self.winfo_rooty() + self.winfo_height()
        if y + height > self.winfo_screenheight():
            y = max(0, self.winfo_rooty() - height)
        popup.geometry(f"{width}x{height}+{max(0, x)}+{y}")
        rows = ctk.CTkScrollableFrame(popup, corner_radius=0)
        rows.pack(fill="both", expand=True)
        for name in self.cget("values"):
            row = ctk.CTkButton(
                rows, text=name, anchor="w", height=30, fg_color="transparent",
                command=lambda name=name: self._select_subject(name),
            )
            row.pack(fill="x", pady=2)
            row.bind("<Button-3>", lambda event, name=name: self._context_subject(event, name))
            self.subject_rows[name] = row
        popup.bind("<Escape>", lambda event: self.close_subject_popup())
        popup.bind("<Button-1>", self._outside_subject_popup)
        popup.bind("<FocusOut>", lambda event: self.after_idle(self._check_popup_focus))
        popup.deiconify()
        popup.update_idletasks()
        popup.grab_set()
        popup.focus_force()

    def _outside_subject_popup(self, event):
        popup = self.subject_popup
        if popup is not None and not (
            popup.winfo_rootx() <= event.x_root < popup.winfo_rootx() + popup.winfo_width()
            and popup.winfo_rooty() <= event.y_root < popup.winfo_rooty() + popup.winfo_height()
        ):
            self.close_subject_popup()
            return "break"

    def _check_popup_focus(self):
        if self.context_menu is not None:
            return
        popup = self.subject_popup
        if popup is not None:
            focus = self.focus_get()
            if focus is None or focus.winfo_toplevel() != popup:
                self.close_subject_popup()

    def _select_subject(self, name):
        self.close_subject_popup()
        self._dropdown_callback(name)

    def _context_subject(self, event, name):
        row = self.subject_rows[name]
        x, y = row.winfo_rootx() + row.winfo_width(), row.winfo_rooty()
        self.context_command(name, x, y)
        return "break"

    def post_context_menu(self, menu, x, y):
        self.context_menu = menu
        self._restore_subject_popup = True
        self.subject_popup.grab_release()
        menu.bind("<Unmap>", lambda event: self.after_idle(lambda: self._finish_context_menu(menu)))
        menu.bind("<Escape>", self._cancel_context_menu)
        menu.bind("<ButtonPress-1>", self._context_menu_click)
        try:
            with self._native_context_dismissal():
                menu.tk_popup(x, y)
        finally:
            menu.grab_release()
            if not menu.winfo_ismapped():
                self._finish_context_menu(menu)

    @contextmanager
    def _native_context_dismissal(self):
        """Native Windows menus consume outside clicks before Tk bindings see them."""
        if sys.platform != "win32":
            yield
            return
        import ctypes
        from ctypes import wintypes

        popup = self.subject_popup
        bounds = (popup.winfo_rootx(), popup.winfo_rooty(),
                  popup.winfo_rootx() + popup.winfo_width(),
                  popup.winfo_rooty() + popup.winfo_height())
        user32 = ctypes.windll.user32
        callback_type = ctypes.WINFUNCTYPE(wintypes.LPARAM, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, callback_type, wintypes.HINSTANCE, wintypes.DWORD]
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        user32.CallNextHookEx.restype = wintypes.LPARAM
        user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]

        @callback_type
        def watch(code, wparam, lparam):
            if code == 2:  # MSGF_MENU, limited to this thread's menu modal loop.
                message = ctypes.cast(lparam, ctypes.POINTER(wintypes.MSG)).contents
                if message.message in (0x201, 0x204):  # left/right mouse down
                    point = wintypes.POINT(ctypes.c_short(message.lParam & 0xffff).value,
                                           ctypes.c_short((message.lParam >> 16) & 0xffff).value)
                    user32.ClientToScreen(message.hWnd, ctypes.byref(point))
                    rect = wintypes.RECT()
                    user32.GetWindowRect(message.hWnd, ctypes.byref(rect))
                    in_menu = rect.left <= point.x < rect.right and rect.top <= point.y < rect.bottom
                    in_list = bounds[0] <= point.x < bounds[2] and bounds[1] <= point.y < bounds[3]
                    self._restore_subject_popup = in_menu or in_list
                elif message.message == 0x100 and message.wParam == 0x1B:
                    self._restore_subject_popup = True
            return user32.CallNextHookEx(None, code, wparam, lparam)

        hook = user32.SetWindowsHookExW(-1, watch, None, ctypes.windll.kernel32.GetCurrentThreadId())
        try:
            yield
        finally:
            if hook:
                user32.UnhookWindowsHookEx(hook)

    def _cancel_context_menu(self, event):
        self._restore_subject_popup = True
        if self.context_menu is not None:
            self.context_menu.unpost()
        return "break"

    def _context_menu_click(self, event):
        menu = self.context_menu
        if menu is not None and not (
            menu.winfo_rootx() <= event.x_root < menu.winfo_rootx() + menu.winfo_width()
            and menu.winfo_rooty() <= event.y_root < menu.winfo_rooty() + menu.winfo_height()
        ):
            popup = self.subject_popup
            self._restore_subject_popup = popup is not None and (
                popup.winfo_rootx() <= event.x_root < popup.winfo_rootx() + popup.winfo_width()
                and popup.winfo_rooty() <= event.y_root < popup.winfo_rooty() + popup.winfo_height()
            )
            menu.unpost()
            return "break"

    def _finish_context_menu(self, menu):
        if self.context_menu != menu:
            return
        self.context_menu = None
        if self.subject_popup is not None:
            if self._restore_subject_popup and self.cget("state") != ctk.DISABLED:
                self.subject_popup.grab_set()
                self.subject_popup.focus_force()
            else:
                self.close_subject_popup()
