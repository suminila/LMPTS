"""
Main application shell after login. Sidebar navigation + header + a content
area that swaps pages. Which nav items appear depends on `user.role`
(polymorphism from the User hierarchy drives the UI, not a pile of if/else
on strings).
"""

import os
import sys
from textwrap import wrap
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.exceptions import LMPTSError
from core.models import UserRole, DifficultyLevel, CourseStatus, EnrollmentStatus
from services.lmpts_service import ProgressObserver
from gui import theme
from data.settings import get_setting, set_setting, KEY_ENROLLMENT_SORT

NAV_ITEMS = {
    "dashboard": ("🏠", "Dashboard"),
    "learners": ("👥", "Learners"),
    "courses": ("📘", "Courses"),
    "enrollments": ("📋", "Enrollments"),
    "instructors": ("🧑‍🏫", "Instructors"),
    "reports": ("📊", "Reports"),
    "analytics": ("📈", "Analytics"),
    "learner_portal": ("🎓", "Learner Portal"),
    "instructor_portal": ("🧑‍🏫", "Instructor"),
    "settings": ("⚙️", "About"),
}

# Nav keys that are shown to Administrators even though they aren't (and
# don't need to be) listed in Administrator.dashboard_permissions(). Kept
# separate so we don't have to touch core/models.py just to add an
# admin-only page.
ADMIN_ONLY_EXTRA_NAV_KEYS = {"instructors"}

# Hard override for which nav keys a role sees, applied on top of (in place
# of) whatever User.dashboard_permissions() returns. This lets us fix/lock
# down a role's sidebar entirely from this file, without needing to edit
# core/models.py. Add an entry here for any role whose permissions() method
# is returning more (or less) than it should.
ROLE_NAV_OVERRIDE = {
    UserRole.INSTRUCTOR: ["instructor_portal", "About"],
}


def _effective_nav_keys(user):
    """The nav keys a user should see: the hard override for their role if
    one is defined, otherwise whatever user.dashboard_permissions() returns."""
    override = ROLE_NAV_OVERRIDE.get(user.role)
    if override is not None:
        return override
    return user.dashboard_permissions()


def _pass_cutoff():
    return 65.0


def styled_button(parent, text, command, bg=theme.PRIMARY, fg="white", **kw):
    return tk.Button(
        parent,
        text=text,
        command=command,
        bg=bg,
        fg=fg,
        font=theme.FONT_BUTTON,
        relief="flat",
        cursor="hand2",
        activebackground=theme.PRIMARY_DARK,
        activeforeground="white",
        **kw,
    )


def card(parent, **kw):
    f = tk.Frame(
        parent,
        bg=theme.SURFACE,
        highlightbackground=theme.BORDER,
        highlightthickness=1,
        bd=0,
        **kw,
    )
    return f


def labeled_entry(parent, label_text, row, col=0, width=22, show=None):
    tk.Label(
        parent,
        text=label_text,
        font=theme.FONT_BODY_BOLD,
        bg=theme.SURFACE,
        fg=theme.TEXT_PRIMARY,
    ).grid(row=row, column=col, sticky="w", padx=(0, 8), pady=(6, 2))
    entry = tk.Entry(
        parent, font=theme.FONT_BODY, width=width, relief="solid", bd=1, show=show
    )
    entry.grid(row=row + 1, column=col, sticky="we", padx=(0, 8), pady=(0, 8), ipady=4)
    return entry


class GUIRefreshObserver(ProgressObserver):
    """Bridges service-layer events to a live UI refresh (Observer pattern)."""

    def __init__(self, refresh_callback):
        self.refresh_callback = refresh_callback

    def on_enrollment_created(self, learner_id, course_code):
        self.refresh_callback()

    def on_course_completed(self, learner_id, course_code, score):
        self.refresh_callback()


class MainApp:
    def __init__(self, root: tk.Tk, user, services: dict, on_logout):
        """
        Initialize the main application shell with tabbed navigation.

        This is the main UI after successful login. It provides:
        - A sidebar with navigation buttons filtered by user role
        - A header with Back button and user info
        - A content area that swaps pages dynamically
        - A navigation history stack for the Back button

        Args:
            root (tk.Tk): The Tkinter root window
            user: User object with .name, .role, and dashboard_permissions() method
            services (dict): Dictionary of service objects (course, learner, etc.)
            on_logout: Callback function to execute on logout

        Navigation System:
            - _page_history: Stack (list) of previously visited page keys
            - current_page_key: The page currently being displayed
            - Back button: Enabled when history is not empty, disabled on root page
            - Root pages (no Back): Dashboard (admin), Learner Portal, Instructor Portal

        Pages Available by Role:
            Admin:
                - dashboard (default root)
                - learners
                - courses
                - enrollments
                - instructors (admin-only extra)
                - reports
                - analytics
                - settings

            Learner:
                - learner_portal (default root)
                - (self-service course browsing/enrollment)

            Instructor:
                - instructor_portal (default root)
                - (instructor dashboard)
        """
        self.root = root
        self.user = user
        self.services = services
        self.on_logout = on_logout
        self.current_page_key = None
        self._page_history = []  # Stack of previously-visited page keys for Back button

        self._gui_observer = GUIRefreshObserver(self._refresh_current_page)
        self.services["learner"].register_observer(self._gui_observer)
        # Controls whether enrollment lists are shown ascending (True) or descending (False)
        # Load persisted preference from DB ("asc" / "desc"); default to asc
        stored = get_setting(KEY_ENROLLMENT_SORT)
        self._enrollment_sort_asc = stored != "desc"

        self.root.title("LearnGraph - Learning Management & Prerequisite Tracking")
        self.root.geometry("1360x820")
        self.root.minsize(1100, 700)
        self.root.configure(bg=theme.BG)

        self._build_shell()
        permitted = _effective_nav_keys(self.user)
        first_key = next(iter(permitted))
        # Prefer "dashboard" if the role has it, else the first permitted page.
        default = (
            "dashboard"
            if "dashboard" in permitted
            else (
                "analytics"
                if "analytics" in permitted
                else (
                    "learner_portal"
                    if "learner_portal" in permitted
                    else (
                        "instructor_portal"
                        if "instructor_portal" in permitted
                        else first_key
                    )
                )
            )
        )
        self._show_page(default)

    # ------------------------------------------------------------------ #
    # Shell: header + sidebar + content
    # ------------------------------------------------------------------ #
    def _build_shell(self):
        header = tk.Frame(
            self.root,
            bg=theme.SURFACE,
            height=64,
            highlightbackground=theme.BORDER,
            highlightthickness=1,
        )
        header.pack(side="top", fill="x")
        header.pack_propagate(False)

        # Only show back button if user has multiple navigation pages
        # (e.g., learners only have learner_portal, so no back needed)
        permitted = _effective_nav_keys(self.user)
        if len(permitted) > 1:
            self.back_btn = tk.Button(
                header,
                text="←  Back",
                font=theme.FONT_BODY_BOLD,
                bg=theme.SURFACE,
                fg=theme.TEXT_SECONDARY,
                relief="flat",
                cursor="hand2",
                state="normal",
                command=self._go_back,
            )
            self.back_btn.pack(side="left", padx=(16, 4))
        else:
            self.back_btn = None

        tk.Label(
            header,
            text="🎓 LearnGraph",
            font=theme.FONT_HEADING,
            bg=theme.SURFACE,
            fg=theme.PRIMARY_DARK,
        ).pack(side="left", padx=20)
        tk.Label(
            header,
            text="Learning Management & Prerequisite Tracking",
            font=theme.FONT_BODY,
            bg=theme.SURFACE,
            fg=theme.TEXT_SECONDARY,
        ).pack(side="left")

        user_box = tk.Frame(header, bg=theme.SURFACE)
        user_box.pack(side="right", padx=20)
        tk.Label(
            user_box,
            text=self.user.name,
            font=theme.FONT_BODY_BOLD,
            bg=theme.SURFACE,
            fg=theme.TEXT_PRIMARY,
        ).grid(row=0, column=0, sticky="e")
        tk.Label(
            user_box,
            text=self.user.role.value,
            font=theme.FONT_SMALL,
            bg=theme.SURFACE,
            fg=theme.TEXT_SECONDARY,
        ).grid(row=1, column=0, sticky="e")
        styled_button(
            user_box, "Logout", self._logout, bg=theme.DANGER_LIGHT, fg=theme.DANGER
        ).grid(row=0, column=1, rowspan=2, padx=(14, 0))

        body = tk.Frame(self.root, bg=theme.BG)
        body.pack(side="top", fill="both", expand=True)

        self.sidebar = tk.Frame(
            body,
            bg=theme.SURFACE,
            width=220,
            highlightbackground=theme.BORDER,
            highlightthickness=1,
        )
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        self.nav_buttons = {}
        allowed = _effective_nav_keys(self.user)
        # "dashboard" only ever appears in the Administrator's permission
        # set, so its presence is a reliable signal that this user is an
        # admin - used to unlock admin-only extra pages like "Instructors"
        # without requiring changes to core/models.py.
        is_admin = "dashboard" in allowed
        for key in NAV_ITEMS:
            if key in ADMIN_ONLY_EXTRA_NAV_KEYS:
                if not is_admin:
                    continue
            elif key not in allowed:
                continue
            icon, label = NAV_ITEMS[key]
            btn = tk.Button(
                self.sidebar,
                text=f"  {icon}   {label}",
                anchor="w",
                font=theme.FONT_BODY,
                bg=theme.SURFACE,
                fg=theme.TEXT_PRIMARY,
                relief="flat",
                cursor="hand2",
                command=lambda k=key: self._show_page(k),
            )
            btn.pack(fill="x", padx=12, pady=3, ipady=8)
            self.nav_buttons[key] = btn

        self.content = tk.Frame(body, bg=theme.BG)
        self.content.pack(side="left", fill="both", expand=True)

    def _set_active_nav(self, key):
        for k, btn in self.nav_buttons.items():
            if k == key:
                btn.configure(bg=theme.PRIMARY, fg="white")
            else:
                btn.configure(bg=theme.SURFACE, fg=theme.TEXT_PRIMARY)

    def _logout(self):
        self.services["learner"].unregister_observer(self._gui_observer)
        for widget in self.root.winfo_children():
            widget.destroy()
        self.on_logout()

    def _clear_content(self):
        for widget in self.content.winfo_children():
            widget.destroy()

    def _show_page(self, key, _record_history=True):
        """
        Navigate to a page by key and render it.

        Args:
            key (str): The page key from NAV_ITEMS (e.g., "dashboard", "learners")
            _record_history (bool): If True, records the previous page in history
                                   so Back button can return to it.
                                   If False, navigates without creating history entry.
                                   Used internally for Back and Refresh operations.

        Flow:
            1. If navigating to a DIFFERENT page, record current page in history stack
               (unless _record_history=False, which is used for Back/Refresh)
            2. Update current_page_key
            3. Highlight the selected nav button
            4. Clear the content frame
            5. Update back button enabled/disabled state
            6. Call the appropriate page builder method
            7. Handle any exceptions and display error message

        Navigation History Management:
            - Navigating between different pages: History recorded
            - Clicking same nav button twice: No duplicate history entry
            - Back button click: _record_history=False to avoid loop
            - Page refresh: _record_history=False to avoid polluting history
            - Login/logout: New MainApp instance, fresh history

        Root Pages (start with empty history):
            - "dashboard" (Admin only)
            - "learner_portal" (Learner only)
            - "instructor_portal" (Instructor only)
        """
        # Push the current page onto history stack ONLY if:
        # 1. We're recording history (_record_history=True), AND
        # 2. We have a current page (not the first page load), AND
        # 3. We're navigating to a DIFFERENT page (no duplicates)
        if _record_history and self.current_page_key and self.current_page_key != key:
            self._page_history.append(self.current_page_key)

        self.current_page_key = key
        self._set_active_nav(key)
        self._clear_content()
        self._update_back_button()

        # Map page keys to their builder methods
        page_builders = {
            "dashboard": self._page_admin_dashboard,
            "learners": self._page_learners,
            "courses": self._page_courses,
            "enrollments": self._page_enrollments,
            "instructors": self._page_instructors,
            "reports": self._page_reports,
            "analytics": self._page_analytics,
            "learner_portal": self._page_learner_portal,
            "instructor_portal": self._page_instructor_portal,
            "settings": self._page_settings,
        }

        builder = page_builders.get(key)
        if builder:
            try:
                builder()
            except Exception as exc:
                import traceback

                traceback.print_exc()
                # Display error UI instead of crashing
                tk.Label(
                    self.content,
                    text=(
                        "This page hit an error while loading, so it's showing "
                        f"blank instead of crashing:\n\n{exc}\n\n"
                        "(Full traceback printed to the terminal/console.)"
                    ),
                    font=theme.FONT_BODY,
                    bg=theme.BG,
                    fg=theme.DANGER,
                    justify="left",
                    wraplength=900,
                ).pack(anchor="w", padx=24, pady=24)

    def _go_to_dashboard(self):
        """
        Navigate directly to the Dashboard (root page).

        Behavior:
            - Immediately shows the Dashboard page
            - Does NOT navigate through history or intermediate pages
            - Does NOT record history entry for this navigation
            - Called by Back button to return to Dashboard from any page

        This centralizes all back-to-dashboard logic in one place,
        ensuring consistent behavior throughout the application.
        """
        if self.current_page_key != "dashboard":
            self._show_page("dashboard", _record_history=False)

    def _go_back(self):
        """
        Navigate back to Dashboard.

        Behavior (REDESIGNED):
            - Back button now ALWAYS returns directly to Dashboard
            - Does NOT navigate through history stack
            - Does NOT show intermediate pages
            - Ignores navigation history completely
            - Disabled only when already on Dashboard

        Example:
            User navigates: Dashboard → Learners → Courses → Add Course
            Click Back:
            - Directly navigates to Dashboard (skips intermediate pages)
            - Does NOT show Learners or Courses pages

        This provides a consistent, professional navigation experience
        where the Dashboard is always the destination for all Back buttons.
        """
        self._go_to_dashboard()

    def _update_back_button(self):
        """
        Enable or disable the Back button based on current page.

        Logic (REDESIGNED):
            - Back button is ENABLED if current page is NOT Dashboard
            - Back button is DISABLED if on Dashboard (nowhere to go back to)
            - Always navigates directly to Dashboard when enabled

        Called automatically by _show_page() after every navigation.
        """
        if self.back_btn is not None:
            # Disable back button only when on dashboard
            # Otherwise always enabled to return to dashboard
            is_on_dashboard = self.current_page_key == "dashboard"
            self.back_btn.configure(state="disabled" if is_on_dashboard else "normal")

    def _refresh_current_page(self):
        """
        Refresh the current page to show updated data.

        Behavior:
            - Re-renders the current page from fresh database/service data
            - Does NOT record history entry (use after CRUD operations)
            - Used after: create, update, delete operations
            - Preserves the user's position within the app (same page, same role)

        Example:
            User creates a learner → Page refreshes to show new learner in list
            User updates a course → Page refreshes to show updated course details
        """
        if self.current_page_key:
            # Re-render current page without recording history
            self._show_page(self.current_page_key, _record_history=False)

    def _toggle_enrollment_sort(self):
        """Toggle enrollment sort order and refresh the current page."""
        self._enrollment_sort_asc = not self._enrollment_sort_asc
        # Persist preference
        set_setting(KEY_ENROLLMENT_SORT, "asc" if self._enrollment_sort_asc else "desc")
        self._refresh_current_page()

    def _error(self, exc):
        messagebox.showerror("Action failed", str(exc))

    def _info(self, msg):
        messagebox.showinfo("Success", msg)

    # ------------------------------------------------------------------ #
    # Page: Admin Dashboard (KPIs / Actions / Charts / Progress overview)
    # ------------------------------------------------------------------ #
    def _page_admin_dashboard(self):
        outer = tk.Frame(self.content, bg=theme.BG)
        outer.pack(fill="both", expand=True)
        wrap = self._scrollable_container(outer)

        pad = tk.Frame(wrap, bg=theme.BG)
        pad.pack(fill="both", expand=True, padx=24, pady=20)

        # Pull everything once, up front, and reuse it across every card below.
        stats = self.services["analytics"].system_metrics()
        courses = self.services["course"].list_courses()
        learners = self.services["learner"].list_learners()
        enrollments = self.services["enrollment_repo"].list_all()

        # --- KPI summary row --------------------------------------------- #
        kpi_row = tk.Frame(pad, bg=theme.BG)
        kpi_row.pack(fill="x")
        kpis = [
            ("👥", "Total Learners", stats["total_learners"], theme.PRIMARY),
            ("📘", "Total Courses", stats["total_courses"], theme.SUCCESS),
            ("📋", "Total Enrollments", stats["total_enrollments"], "#f59e0b"),
            (
                "🎯",
                "Overall Completion",
                f"{stats['overall_completion_rate']}%",
                "#8b5cf6",
            ),
        ]
        for i, (icon, label, value, accent) in enumerate(kpis):
            box = self._stat_card(kpi_row, icon, label, value, accent)
            box.pack(
                side="left", expand=True, fill="both", padx=(0 if i == 0 else 8, 0)
            )

        # --- Quick actions: Register Learner / Enroll in Course ----------- #

        # --- Per-course stats used by the charts below -------------------- #
        course_stats = []
        for c in courses:
            course_enrollments = [e for e in enrollments if e.course_code == c.code]
            completed = [
                e for e in course_enrollments if e.status == EnrollmentStatus.COMPLETED
            ]
            course_stats.append(
                {
                    "code": c.code,
                    "name": c.name,
                    "enrolled": len(course_enrollments),
                    "completed": len(completed),
                }
            )
        course_stats.sort(key=lambda x: x["enrolled"], reverse=True)

        # --- Charts: enrolled-vs-completed bar chart + completion donut --- #
        chart_row = tk.Frame(pad, bg=theme.BG)
        chart_row.pack(fill="both", expand=True, pady=(16, 0))
        chart_row.columnconfigure(0, weight=2)
        chart_row.columnconfigure(1, weight=1)

        bar_card = card(chart_row)
        bar_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8), ipadx=16, ipady=14)
        tk.Label(
            bar_card,
            text="📊  Enrolled vs Completed by Course",
            font=theme.FONT_HEADING,
            bg=theme.SURFACE,
            fg=theme.TEXT_PRIMARY,
        ).pack(fill="x", anchor="w", padx=24, pady=(20, 6))
        tk.Label(
            bar_card,
            text="Top courses by enrollment — bars compare enrolled and completed learners",
            font=theme.FONT_SMALL,
            bg=theme.SURFACE,
            fg=theme.TEXT_SECONDARY,
        ).pack(fill="x", anchor="w", padx=24, pady=(0, 16))
        legend = tk.Frame(bar_card, bg=theme.SURFACE)
        legend.pack(fill="x", anchor="w", padx=24, pady=(0, 16))
        self._legend_swatch(legend, theme.PRIMARY, "Enrolled")
        self._legend_swatch(legend, theme.SUCCESS, "Completed")
        chart_frame = tk.Frame(bar_card, bg=theme.SURFACE)
        chart_frame.pack(fill="both", expand=True, padx=24, pady=(0, 24))
        self._draw_enrollment_bar_chart(bar_card, course_stats[:8])

        donut_card = card(chart_row)
        donut_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0), ipadx=16, ipady=14)
        tk.Label(
            donut_card,
            text="🎯  Completion Ratio",
            font=theme.FONT_HEADING,
            bg=theme.SURFACE,
            fg=theme.TEXT_PRIMARY,
        ).pack(padx=20, pady=(20, 8))
        tk.Label(
            donut_card,
            text="Status of all enrollments, system-wide",
            font=theme.FONT_SMALL,
            bg=theme.SURFACE,
            fg=theme.TEXT_SECONDARY,
        ).pack(padx=20, pady=(20, 8))

        status_counts = {}
        for e in enrollments:
            status_counts[e.status] = status_counts.get(e.status, 0) + 1
        known_colors = {
            EnrollmentStatus.COMPLETED: theme.SUCCESS,
            EnrollmentStatus.IN_PROGRESS: theme.PRIMARY,
        }
        palette = ["#f59e0b", "#ef4444", "#06b6d4", "#8b5cf6", "#64748b"]
        segments = []
        pi = 0
        for status, count in sorted(
            status_counts.items(), key=lambda kv: kv[1], reverse=True
        ):
            color = known_colors.get(status)
            if not color:
                color = palette[pi % len(palette)]
                pi += 1
            segments.append((status.value, count, color))
        self._draw_completion_donut(donut_card, segments)

        # --- Recent enrollments + Top courses ------------------------------ #
        bottom_row = tk.Frame(pad, bg=theme.BG)
        bottom_row.pack(fill="both", expand=True, pady=(16, 0))
        bottom_row.columnconfigure(0, weight=1)
        bottom_row.columnconfigure(1, weight=1)

        recent_card = card(bottom_row)
        recent_card.grid(
            row=0, column=0, sticky="nsew", padx=(0, 8), ipadx=16, ipady=14
        )
        recent_card.configure(height=320)
        recent_card.grid_propagate(False)
        recent_card.grid_rowconfigure(1, weight=1)
        recent_card.grid_columnconfigure(0, weight=1)

        header_frame = tk.Frame(recent_card, bg=theme.SURFACE)
        header_frame.grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 8))
        tk.Label(
            header_frame,
            text="🕒  Recent Enrollments",
            font=theme.FONT_HEADING,
            bg=theme.SURFACE,
            fg=theme.TEXT_PRIMARY,
        ).pack(side="left")
        tk.Button(
            header_frame,
            text=f"Sort: {'Asc' if self._enrollment_sort_asc else 'Desc'}",
            command=self._toggle_enrollment_sort,
            bg=theme.SURFACE,
            fg=theme.TEXT_SECONDARY,
            relief="flat",
        ).pack(side="right")

        scroll_frame = tk.Frame(recent_card, bg=theme.SURFACE)
        scroll_frame.grid(row=1, column=0, sticky="nsew")
        scroll_frame.grid_rowconfigure(0, weight=1)
        scroll_frame.grid_columnconfigure(0, weight=1)

        canvas = tk.Canvas(
            scroll_frame, bg=theme.SURFACE, highlightthickness=0, height=240
        )
        vbar = ttk.Scrollbar(scroll_frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")

        inner = tk.Frame(canvas, bg=theme.SURFACE)
        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def on_inner_configure(_event):
            canvas.configure(scrollregion=canvas.bbox("all"))
            if inner.winfo_reqheight() <= canvas.winfo_height():
                vbar.grid_remove()
            else:
                vbar.grid()

        def on_canvas_configure(event):
            canvas.itemconfig(window_id, width=event.width)
            if inner.winfo_reqheight() <= canvas.winfo_height():
                vbar.grid_remove()
            else:
                vbar.grid()

        def on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def bind_wheel(_event):
            canvas.bind_all("<MouseWheel>", on_mousewheel)

        def unbind_wheel(_event):
            canvas.unbind_all("<MouseWheel>")

        inner.bind("<Configure>", on_inner_configure)
        canvas.bind("<Configure>", on_canvas_configure)
        canvas.bind("<Enter>", bind_wheel)
        canvas.bind("<Leave>", unbind_wheel)

        recent = sorted(
            enrollments,
            key=lambda e: e.enrolled_date or "",
            reverse=not self._enrollment_sort_asc,
        )[:6]
        if recent:
            for e in recent:
                row = tk.Frame(inner, bg=theme.SURFACE)
                row.pack(fill="x", pady=3)
                tk.Label(
                    row,
                    text=f"{e.learner_id} → {e.course_code}",
                    font=theme.FONT_BODY_BOLD,
                    bg=theme.SURFACE,
                    fg=theme.TEXT_PRIMARY,
                ).pack(side="left", padx=20, pady=(20, 8))
                tk.Label(
                    row,
                    text=e.status.value,
                    font=theme.FONT_SMALL,
                    bg=theme.SURFACE,
                    fg=theme.TEXT_SECONDARY,
                ).pack(side="right", padx=20, pady=(20, 8))
        else:
            tk.Label(
                inner,
                text="No enrollments yet.",
                font=theme.FONT_BODY,
                bg=theme.SURFACE,
                fg=theme.TEXT_SECONDARY,
            ).pack(anchor="center", padx=20, pady=(20, 8))

        top_card = card(bottom_row)
        top_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0), ipadx=16, ipady=14)
        top_card.configure(height=320)
        top_card.grid_propagate(False)
        top_card.grid_rowconfigure(1, weight=1)
        top_card.grid_columnconfigure(0, weight=1)

        tk.Label(
            top_card,
            text="🏆  Top Courses by Enrollment",
            font=theme.FONT_HEADING,
            bg=theme.SURFACE,
            fg=theme.TEXT_PRIMARY,
        ).grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 8))

        scroll_frame = tk.Frame(top_card, bg=theme.SURFACE)
        scroll_frame.grid(row=1, column=0, sticky="nsew")
        scroll_frame.grid_rowconfigure(0, weight=1)
        scroll_frame.grid_columnconfigure(0, weight=1)

        canvas = tk.Canvas(
            scroll_frame, bg=theme.SURFACE, highlightthickness=0, height=240
        )
        vbar = ttk.Scrollbar(scroll_frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")

        inner = tk.Frame(canvas, bg=theme.SURFACE)
        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def on_inner_configure(_event):
            canvas.configure(scrollregion=canvas.bbox("all"))
            if inner.winfo_reqheight() <= canvas.winfo_height():
                vbar.grid_remove()
            else:
                vbar.grid()

        def on_canvas_configure(event):
            canvas.itemconfig(window_id, width=event.width)
            if inner.winfo_reqheight() <= canvas.winfo_height():
                vbar.grid_remove()
            else:
                vbar.grid()

        def on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def bind_wheel(_event):
            canvas.bind_all("<MouseWheel>", on_mousewheel)

        def unbind_wheel(_event):
            canvas.unbind_all("<MouseWheel>")

        inner.bind("<Configure>", on_inner_configure)
        canvas.bind("<Configure>", on_canvas_configure)
        canvas.bind("<Enter>", bind_wheel)
        canvas.bind("<Leave>", unbind_wheel)

        if course_stats:
            max_enrolled = max(c["enrolled"] for c in course_stats) or 1
            for c in course_stats[:6]:
                row = tk.Frame(inner, bg=theme.SURFACE)
                row.pack(fill="x", pady=4)
                tk.Label(
                    row,
                    text=f"{c['code']} — {c['name']}",
                    font=theme.FONT_BODY_BOLD,
                    bg=theme.SURFACE,
                    fg=theme.TEXT_PRIMARY,
                ).pack(anchor="center", padx=20, pady=(20, 8))
                bar_bg = tk.Frame(row, bg=theme.BORDER, height=8)
                bar_bg.pack(fill="x", pady=(4, 0))
                ratio = max(c["enrolled"] / max_enrolled, 0.03) if max_enrolled else 0
                tk.Frame(bar_bg, bg=theme.PRIMARY, height=8, width=150).place(
                    relx=0, rely=0, relwidth=ratio, relheight=1
                )
                tk.Label(
                    row,
                    text=f"{c['enrolled']} enrolled · {c['completed']} completed",
                    font=theme.FONT_SMALL,
                    bg=theme.SURFACE,
                    fg=theme.TEXT_SECONDARY,
                ).pack(anchor="center", padx=20, pady=(20, 8))
        else:
            tk.Label(
                inner,
                text="No courses yet.",
                font=theme.FONT_BODY,
                bg=theme.SURFACE,
                fg=theme.TEXT_SECONDARY,
            ).pack(anchor="center", padx=20, pady=(20, 8))

        # --- Progress Overview table ---------------------------------------#
        prog_card = card(pad)
        prog_card.pack(fill="both", expand=True, pady=(16, 0), ipadx=16, ipady=14)
        tk.Label(
            prog_card,
            text="Progress Overview",
            font=theme.FONT_HEADING,
            bg=theme.SURFACE,
            fg=theme.TEXT_PRIMARY,
        ).pack(anchor="center", padx=20, pady=(20, 8))
        tk.Label(
            prog_card,
            text="Track learner course progress and completion status",
            font=theme.FONT_SMALL,
            bg=theme.SURFACE,
            fg=theme.TEXT_SECONDARY,
        ).pack(anchor="center", padx=20, pady=(20, 8))

        columns = ("id", "learner", "total", "completed", "in_progress", "rate")

        tree = self._make_tree(
            prog_card,
            columns,
            [
                "Learner ID",
                "Learner",
                "Total Courses",
                "Completed",
                "In Progress",
                "Rate",
            ],
        )

        # Center-align headers
        for col in columns:
            tree.heading(col, anchor="center")

            # Center-align data and set widths
            tree.column("id", width=100, minwidth=80, anchor="center", stretch=True)
            tree.column(
                "learner", width=180, minwidth=150, anchor="center", stretch=True
            )
            tree.column("total", width=120, minwidth=100, anchor="center", stretch=True)
            tree.column(
                "completed", width=280, minwidth=220, anchor="center", stretch=True
            )
            tree.column(
                "in_progress", width=120, minwidth=100, anchor="center", stretch=True
            )
            tree.column("rate", width=100, minwidth=80, anchor="center", stretch=True)

        for learner in learners:
            progress = self.services["learner"].get_progress(learner["learner_id"])
            completed_codes = (
                ", ".join(
                    sorted(
                        self.services["learner"].completed_courses(
                            learner["learner_id"]
                        )
                    )
                )
                or "—"
            )
            tree.insert(
                "",
                "end",
                values=(
                    learner["learner_id"],
                    learner["name"],
                    progress["total_courses"],
                    completed_codes,
                    f"{progress['in_progress']}",
                    f"{progress['completion_rate']}%",
                ),
            )

        # footer = tk.Frame(prog_card, bg=theme.SURFACE)
        # footer.pack(fill="x", pady=(12, 0))
        # for label, value in [
        #     ("Total Learners", stats["total_learners"]),
        #     ("Total Courses", stats["total_courses"]),
        #     ("Total Enrollments", stats["total_enrollments"]),
        #     ("Overall Completion", f"{stats['overall_completion_rate']}%"),
        # ]:
        #     box = tk.Frame(footer, bg=theme.SURFACE)
        #     box.pack(side="left", padx=(0, 40))
        #     tk.Label(
        #         box,
        #         text=label,
        #         font=theme.FONT_SMALL,
        #         bg=theme.SURFACE,
        #         fg=theme.TEXT_SECONDARY,
        #     ).pack(anchor="center", padx=20, pady=(20, 8))
        #     tk.Label(
        #         box,
        #         text=str(value),
        #         font=theme.FONT_HEADING,
        #         bg=theme.SURFACE,
        #         fg=theme.TEXT_PRIMARY,
        #     ).pack(anchor="center", padx=20, pady=(20, 8))

    # ------------------------------------------------------------------ #
    # Page: Courses (Create Course / Add Prerequisite / Catalog)
    # ------------------------------------------------------------------ #
    def _page_courses(self):
        outer = tk.Frame(self.content, bg=theme.BG)
        outer.pack(fill="both", expand=True)
        scroll_area = self._scrollable_container(outer)
        wrap = tk.Frame(scroll_area, bg=theme.BG)
        wrap.pack(fill="both", expand=True, padx=24, pady=20)

        # editing_code is None while adding a brand-new course; once a row in
        # the catalog is clicked it holds that course's code and the form
        # switches into "update / delete this course" mode.
        self.editing_code = None

        create_card = card(wrap)
        create_card.pack(fill="x", ipadx=16, ipady=14)
        header_row = tk.Frame(create_card, bg=theme.SURFACE)
        header_row.pack(fill="x")
        title_lbl = tk.Label(
            header_row,
            text="📘  Add Course",
            font=theme.FONT_HEADING,
            bg=theme.SURFACE,
            fg=theme.TEXT_PRIMARY,
        )
        title_lbl.pack(side="left")
        subtitle_lbl = tk.Label(
            header_row,
            text="",
            font=theme.FONT_SMALL,
            bg=theme.SURFACE,
            fg=theme.TEXT_SECONDARY,
        )
        subtitle_lbl.pack(side="left", padx=(10, 0))

        form = tk.Frame(create_card, bg=theme.SURFACE)
        form.pack(fill="x", pady=(10, 0))
        for i in range(3):
            form.columnconfigure(i, weight=1)
        code_e = labeled_entry(form, "Code", 0, 0)
        name_e = labeled_entry(form, "Name", 0, 1)
        desc_e = labeled_entry(form, "Description", 0, 2)
        hours_e = labeled_entry(form, "Duration (hrs)", 2, 0)
        levels_e = labeled_entry(form, "Total Levels", 2, 1)

        tk.Label(
            form, text="Difficulty", font=theme.FONT_BODY_BOLD, bg=theme.SURFACE
        ).grid(row=2, column=2, sticky="w", pady=(6, 2))
        diff_combo = ttk.Combobox(
            form, values=[d.value for d in DifficultyLevel], state="readonly"
        )
        diff_combo.current(0)
        diff_combo.grid(row=3, column=2, sticky="we", padx=(0, 8), pady=(0, 8))

        instr_e = labeled_entry(form, "Instructor", 4, 0)

        tk.Label(form, text="Status", font=theme.FONT_BODY_BOLD, bg=theme.SURFACE).grid(
            row=4, column=1, sticky="w", pady=(6, 2)
        )
        status_combo = ttk.Combobox(
            form, values=[s.value for s in CourseStatus], state="readonly"
        )
        status_combo.current(list(CourseStatus).index(CourseStatus.PUBLISHED))
        status_combo.grid(row=5, column=1, sticky="we", padx=(0, 8), pady=(0, 4))

        form_error = tk.Label(
            create_card,
            text="",
            font=theme.FONT_SMALL,
            bg=theme.SURFACE,
            fg=theme.DANGER,
        )
        form_error.pack(anchor="w", pady=(4, 0))

        def clear_form():
            self.editing_code = None
            code_e.configure(state="normal")
            code_e.delete(0, tk.END)
            name_e.delete(0, tk.END)
            desc_e.delete(0, tk.END)
            hours_e.delete(0, tk.END)
            instr_e.delete(0, tk.END)
            diff_combo.current(0)
            levels_e.delete(0, tk.END)
            levels_e.insert(0, "1")
            status_combo.current(list(CourseStatus).index(CourseStatus.PUBLISHED))
            form_error.config(text="")
            title_lbl.config(text="📘  Add Course")
            subtitle_lbl.config(text="")
            add_btn.pack(side="right", padx=(6, 0), ipady=6, ipadx=10)
            update_btn.pack_forget()
            delete_btn.pack_forget()
            cancel_btn.pack_forget()
            if hasattr(self, "_courses_tree") and self._courses_tree.selection():
                self._courses_tree.selection_remove(self._courses_tree.selection())

        def load_course_into_form(course):
            self.editing_code = course.code
            code_e.configure(state="normal")
            code_e.delete(0, tk.END)
            code_e.insert(0, course.code)
            code_e.configure(state="disabled")  # course code is immutable once created
            name_e.delete(0, tk.END)
            name_e.insert(0, course.name)
            desc_e.delete(0, tk.END)
            desc_e.insert(0, course.description)
            hours_e.delete(0, tk.END)
            hours_e.insert(0, str(course.duration_hours))
            instr_e.delete(0, tk.END)
            instr_e.insert(0, course.instructor)
            diff_combo.set(course.difficulty.value)
            levels_e.delete(0, tk.END)
            levels_e.insert(0, str(getattr(course, "total_levels", 1)))
            status_combo.set(course.status.value)
            form_error.config(text="")
            title_lbl.config(text="✏️  Edit Course")
            subtitle_lbl.config(text=f"Editing {course.code} — code can't be changed")
            add_btn.pack_forget()
            update_btn.pack(side="right", padx=(6, 0), ipady=6, ipadx=10)
            delete_btn.pack(side="right", padx=(6, 0), ipady=6, ipadx=10)
            cancel_btn.pack(side="right", padx=(6, 0), ipady=6, ipadx=10)

        def _validated_fields():
            """Raises ValueError with a friendly message if a field is bad."""
            code = code_e.get().strip()
            name = name_e.get().strip()
            if not code:
                raise ValueError("Course code is required")
            if not name:
                raise ValueError("Course name is required")
            hours_raw = hours_e.get().strip() or "0"
            try:
                hours = float(hours_raw)
            except ValueError:
                raise ValueError("Duration (hrs) must be a number")
            if hours < 0:
                raise ValueError("Duration (hrs) cannot be negative")
            levels_raw = levels_e.get().strip() or "1"
            try:
                total_levels = int(levels_raw)
            except ValueError:
                raise ValueError("Total Levels must be a whole number")
            if total_levels < 1:
                raise ValueError("Total Levels must be at least 1")
            return code, name, hours, total_levels

        def do_create_course():
            try:
                code, name, hours, total_levels = _validated_fields()
                self.services["course"].create_course(
                    code,
                    name,
                    desc_e.get().strip(),
                    diff_combo.get() or "Beginner",
                    hours,
                    instr_e.get().strip(),
                    status_combo.get() or "Published",
                    total_levels,
                )
                self._info(f"Course {code} created")
                clear_form()
                self._refresh_current_page()
            except (LMPTSError, ValueError) as e:
                form_error.config(text=str(e))

        def do_update_course():
            try:
                _, name, hours, total_levels = _validated_fields()
                self.services["course"].update_course(
                    self.editing_code,
                    name=name,
                    description=desc_e.get().strip(),
                    difficulty=diff_combo.get() or None,
                    duration_hours=hours,
                    instructor=instr_e.get().strip(),
                    status=status_combo.get() or None,
                    total_levels=total_levels,
                )
                self._info(f"Course {self.editing_code} updated")
                self._refresh_current_page()
            except (LMPTSError, ValueError) as e:
                form_error.config(text=str(e))

        def do_delete_course():
            code = self.editing_code
            if not code:
                return
            if not messagebox.askyesno(
                "Delete course",
                f"Delete course {code}? This also removes its prerequisite links.",
            ):
                return
            try:
                self.services["course"].delete_course(code)
                self._info(f"Course {code} deleted")
                self._refresh_current_page()
            except LMPTSError as e:
                self._error(e)

        button_row = tk.Frame(create_card, bg=theme.SURFACE)
        button_row.pack(fill="x", pady=(10, 0))
        add_btn = styled_button(button_row, "➕ Add Course", do_create_course)
        update_btn = styled_button(
            button_row, "💾 Update Course", do_update_course, bg=theme.SUCCESS
        )
        delete_btn = styled_button(
            button_row, "🗑️ Delete Course", do_delete_course, bg=theme.DANGER
        )
        cancel_btn = styled_button(
            button_row, "Cancel", clear_form, bg=theme.BORDER, fg=theme.TEXT_PRIMARY
        )
        add_btn.pack(side="right", padx=(6, 0), ipady=6, ipadx=10)

        # --- Add prerequisite card ---
        prereq_card = card(wrap)
        prereq_card.pack(fill="x", pady=(16, 0), ipadx=16, ipady=14)
        tk.Label(
            prereq_card,
            text="🔗  Add Prerequisite",
            font=theme.FONT_HEADING,
            bg=theme.SURFACE,
            fg=theme.TEXT_PRIMARY,
        ).pack(anchor="w")
        tk.Label(
            prereq_card,
            text="Link a prerequisite to a course",
            font=theme.FONT_SMALL,
            bg=theme.SURFACE,
            fg=theme.TEXT_SECONDARY,
        ).pack(anchor="w", pady=(0, 8))

        prow = tk.Frame(prereq_card, bg=theme.SURFACE)
        prow.pack(fill="x")
        codes = [c.code for c in self.services["course"].list_courses()]
        tk.Label(
            prow, text="Prerequisite code", font=theme.FONT_BODY_BOLD, bg=theme.SURFACE
        ).grid(row=0, column=0, sticky="w")
        prereq_combo = ttk.Combobox(prow, values=codes, state="readonly", width=18)
        prereq_combo.grid(row=1, column=0, padx=(0, 10), pady=(4, 0))
        tk.Label(
            prow,
            text="is required for",
            font=theme.FONT_BODY,
            bg=theme.SURFACE,
            fg=theme.TEXT_SECONDARY,
        ).grid(row=1, column=1, padx=10)
        tk.Label(
            prow, text="Course code", font=theme.FONT_BODY_BOLD, bg=theme.SURFACE
        ).grid(row=0, column=2, sticky="w")
        dependent_combo = ttk.Combobox(prow, values=codes, state="readonly", width=18)
        dependent_combo.grid(row=1, column=2, padx=(10, 10), pady=(4, 0))

        def do_link_prereq():
            if not prereq_combo.get() or not dependent_combo.get():
                self._error("Select both courses")
                return
            try:
                self.services["course"].add_prerequisite(
                    prereq_combo.get(), dependent_combo.get()
                )
                self._info("Prerequisite linked")
                self._refresh_current_page()
            except LMPTSError as e:
                self._error(e)

        styled_button(
            prow, "🔗 Link Prerequisite", do_link_prereq, bg=theme.SUCCESS
        ).grid(row=1, column=3, padx=(10, 0), ipady=6, ipadx=8)

        # --- Course catalog table ---
        cat_card = card(wrap)
        cat_card.pack(fill="both", expand=True, pady=(16, 0), ipadx=16, ipady=14)
        tk.Label(
            cat_card,
            text="Course Catalog",
            font=theme.FONT_HEADING,
            bg=theme.SURFACE,
            fg=theme.TEXT_PRIMARY,
        ).pack(anchor="w")
        tk.Label(
            cat_card,
            text="View and manage all courses and their details",
            font=theme.FONT_SMALL,
            bg=theme.SURFACE,
            fg=theme.TEXT_SECONDARY,
        ).pack(anchor="w", pady=(0, 8))

        tk.Label(
            cat_card,
            text="Click a row to edit or delete that course",
            font=theme.FONT_SMALL,
            bg=theme.SURFACE,
            fg=theme.TEXT_SECONDARY,
        ).pack(anchor="w", pady=(0, 4))

        columns = ("code", "name", "difficulty", "hours", "status", "prereqs")
        tree = self._make_tree(
            cat_card,
            columns,
            ["Code", "Name", "Difficulty", "Hours", "Status", "Prereqs"],
        )
        self._courses_tree = tree
        for course in self.services["course"].list_courses():
            prereqs = (
                ", ".join(
                    sorted(
                        self.services["course"].get_direct_prerequisites(course.code)
                    )
                )
                or "—"
            )
            tree.insert(
                "",
                "end",
                iid=course.code,
                values=(
                    course.code,
                    course.name,
                    course.difficulty.value,
                    course.duration_hours,
                    course.status.value,
                    prereqs,
                ),
            )

        def on_row_select(event):
            selection = tree.selection()
            if not selection:
                return
            code = selection[0]
            try:
                course = self.services["course"].get_course(code)
            except LMPTSError as e:
                self._error(e)
                return
            load_course_into_form(course)

        tree.bind("<<TreeviewSelect>>", on_row_select)

    # ------------------------------------------------------------------ #
    # Page: Analytics
    # ------------------------------------------------------------------ #
    def _page_analytics(self):
        wrap = tk.Frame(self.content, bg=theme.BG)
        wrap.pack(fill="both", expand=True, padx=24, pady=20)

        metrics_card = card(wrap)
        metrics_card.pack(fill="x", ipadx=16, ipady=14)
        tk.Label(
            metrics_card,
            text="System Metrics",
            font=theme.FONT_HEADING,
            bg=theme.SURFACE,
            fg=theme.TEXT_PRIMARY,
        ).pack(anchor="w", pady=(0, 10))

        stats = self.services["analytics"].system_metrics()
        row = tk.Frame(metrics_card, bg=theme.SURFACE)
        row.pack(fill="x")
        for label, value in [
            ("Total Courses", stats["total_courses"]),
            ("Total Learners", stats["total_learners"]),
            ("Total Enrollments", stats["total_enrollments"]),
            ("Overall Completion Rate", f"{stats['overall_completion_rate']}%"),
        ]:
            box = tk.Frame(row, bg=theme.PRIMARY_LIGHT)
            box.pack(side="left", expand=True, fill="x", padx=6, ipady=12)
            tk.Label(
                box,
                text=label,
                font=theme.FONT_SMALL,
                bg=theme.PRIMARY_LIGHT,
                fg=theme.TEXT_SECONDARY,
            ).pack(anchor="w", padx=12)
            tk.Label(
                box,
                text=str(value),
                font=("Helvetica", 20, "bold"),
                bg=theme.PRIMARY_LIGHT,
                fg=theme.PRIMARY_DARK,
            ).pack(anchor="w", padx=12)

        bn_card = card(wrap)
        bn_card.pack(fill="both", expand=True, pady=(16, 0), ipadx=16, ipady=14)
        tk.Label(
            bn_card,
            text="ℹ️  Bottleneck Courses (low completion, many prereqs)",
            font=theme.FONT_HEADING,
            bg=theme.SURFACE,
            fg=theme.PRIMARY_DARK,
        ).pack(anchor="w", pady=(0, 8))

        columns = ("code", "name", "prereqs", "enrollments", "rate")
        tree = self._make_tree(
            bn_card,
            columns,
            ["Code", "Name", "Prereqs", "Enrollments", "Completion Rate"],
        )
        for s in self.services["analytics"].bottleneck_courses():
            tree.insert(
                "",
                "end",
                values=(
                    s["code"],
                    s["name"],
                    s["prereqs"],
                    s["enrollments"],
                    f"{s['completion_rate']}%",
                ),
            )

    # ------------------------------------------------------------------ #
    # Page: Learners (admin/instructor view)
    # ------------------------------------------------------------------ #
    def _page_learners(self):
        outer = tk.Frame(self.content, bg=theme.BG)
        outer.pack(fill="both", expand=True)
        scroll_area = self._scrollable_container(outer)
        wrap = tk.Frame(scroll_area, bg=theme.BG)
        wrap.pack(fill="both", expand=True, padx=24, pady=20)

        # editing_learner_id is None while the form is empty/new; once a row
        # in the table is clicked it holds that learner's current ID and the
        # form switches into "update / delete this learner" mode.
        self.editing_learner_id = None

        # --- Edit/Update card ---
        form_card = card(wrap)
        form_card.pack(fill="x", ipadx=16, ipady=14)
        header_row = tk.Frame(form_card, bg=theme.SURFACE)
        header_row.pack(fill="x")
        title_lbl = tk.Label(
            header_row,
            text="👥  Learner Details",
            font=theme.FONT_HEADING,
            bg=theme.SURFACE,
            fg=theme.TEXT_PRIMARY,
        )
        title_lbl.pack(side="left")
        subtitle_lbl = tk.Label(
            header_row,
            text="Click a row below to edit or delete that learner",
            font=theme.FONT_SMALL,
            bg=theme.SURFACE,
            fg=theme.TEXT_SECONDARY,
        )
        subtitle_lbl.pack(side="left", padx=(10, 0))

        form = tk.Frame(form_card, bg=theme.SURFACE)
        form.pack(fill="x", pady=(10, 0))
        for i in range(3):
            form.columnconfigure(i, weight=1)
        id_e = labeled_entry(form, "Learner ID", 0, 0)
        id_e.configure(state="disabled")
        name_e = labeled_entry(form, "Name", 0, 1)
        email_e = labeled_entry(form, "Email", 0, 2)

        form_error = tk.Label(
            form_card,
            text="",
            font=theme.FONT_SMALL,
            bg=theme.SURFACE,
            fg=theme.DANGER,
        )
        form_error.pack(anchor="w", pady=(4, 0))

        def clear_form():
            self.editing_learner_id = None
            id_e.configure(state="normal")
            id_e.delete(0, tk.END)
            id_e.configure(state="disabled")
            name_e.delete(0, tk.END)
            email_e.delete(0, tk.END)
            form_error.config(text="")
            title_lbl.config(text="👥  Learner Details")
            subtitle_lbl.config(text="Click a row below to edit or delete that learner")
            update_btn.pack_forget()
            delete_btn.pack_forget()
            cancel_btn.pack_forget()
            if hasattr(self, "_learners_tree") and self._learners_tree.selection():
                self._learners_tree.selection_remove(self._learners_tree.selection())

        def load_learner_into_form(learner):
            self.editing_learner_id = learner["learner_id"]
            id_e.configure(state="normal")
            id_e.delete(0, tk.END)
            id_e.insert(0, learner["learner_id"])
            name_e.delete(0, tk.END)
            name_e.insert(0, learner["name"])
            email_e.delete(0, tk.END)
            email_e.insert(0, learner["email"])
            form_error.config(text="")
            title_lbl.config(text=f"✏️  Edit Learner — {learner['learner_id']}")
            subtitle_lbl.config(
                text="Changing the ID updates every enrollment/progress record and login account"
            )
            update_btn.pack(side="right", padx=(6, 0), ipady=6, ipadx=10)
            delete_btn.pack(side="right", padx=(6, 0), ipady=6, ipadx=10)
            cancel_btn.pack(side="right", padx=(6, 0), ipady=6, ipadx=10)

        def do_update_learner():
            if not self.editing_learner_id:
                return
            new_id = id_e.get().strip()
            name = name_e.get().strip()
            email = email_e.get().strip()
            try:
                # Change the ID first (cascades to enrollments/account), then
                # update name/email under whichever ID is now current.
                if new_id and new_id != self.editing_learner_id:
                    if not messagebox.askyesno(
                        "Confirm ID change",
                        f"Change learner ID from {self.editing_learner_id} to "
                        f"{new_id}?\nThis updates all enrollments, progress "
                        "records, and the matching login account.",
                    ):
                        return
                    self.services["learner"].change_learner_id(
                        self.editing_learner_id, new_id
                    )
                    self.editing_learner_id = new_id
                self.services["learner"].update_learner(
                    self.editing_learner_id, name, email
                )
                self._info(f"Learner {self.editing_learner_id} updated")
                clear_form()
                self._refresh_current_page()
            except (LMPTSError, ValueError) as e:
                form_error.config(text=str(e))

        def do_delete_learner():
            learner_id = self.editing_learner_id
            if not learner_id:
                return
            if not messagebox.askyesno(
                "Delete learner",
                f"Delete learner {learner_id}? This also removes their "
                "enrollments, progress history, and login account.",
            ):
                return
            try:
                self.services["learner"].delete_learner(learner_id)
                self._info(f"Learner {learner_id} deleted")
                clear_form()
                self._refresh_current_page()
            except LMPTSError as e:
                self._error(e)

        button_row = tk.Frame(form_card, bg=theme.SURFACE)
        button_row.pack(fill="x", pady=(10, 0))
        update_btn = styled_button(
            button_row, "💾 Update Learner", do_update_learner, bg=theme.SUCCESS
        )
        delete_btn = styled_button(
            button_row, "🗑️ Delete Learner", do_delete_learner, bg=theme.DANGER
        )
        cancel_btn = styled_button(
            button_row, "Cancel", clear_form, bg=theme.BORDER, fg=theme.TEXT_PRIMARY
        )

        # --- Learner table ---
        list_card = card(wrap)
        list_card.pack(fill="both", expand=True, pady=(16, 0), ipadx=16, ipady=14)
        tk.Label(
            list_card,
            text="All Learners",
            font=theme.FONT_HEADING,
            bg=theme.SURFACE,
            fg=theme.TEXT_PRIMARY,
        ).pack(anchor="w", pady=(0, 10))
        columns = ("id", "name", "email", "completed", "rate")
        tree = self._make_tree(
            list_card, columns, ["Learner ID", "Name", "Email", "Completed", "Rate"]
        )
        self._learners_tree = tree
        learners_by_id = {}
        for learner in self.services["learner"].list_learners():
            progress = self.services["learner"].get_progress(learner["learner_id"])
            learners_by_id[learner["learner_id"]] = learner
            tree.insert(
                "",
                "end",
                iid=learner["learner_id"],
                values=(
                    learner["learner_id"],
                    learner["name"],
                    learner["email"],
                    progress["completed"],
                    f"{progress['completion_rate']}%",
                ),
            )

        def on_row_select(event):
            selection = tree.selection()
            if not selection:
                return
            learner = learners_by_id.get(selection[0])
            if learner:
                load_learner_into_form(learner)

        tree.bind("<<TreeviewSelect>>", on_row_select)

    # ------------------------------------------------------------------ #
    # Page: Enrollments (admin/instructor)
    # ------------------------------------------------------------------ #
    def _page_enrollments(self):
        wrap = tk.Frame(self.content, bg=theme.BG)
        wrap.pack(fill="both", expand=True, padx=24, pady=20)
        c = card(wrap)
        c.pack(fill="both", expand=True, ipadx=16, ipady=14)
        header_frame = tk.Frame(c, bg=theme.SURFACE)
        header_frame.pack(fill="x")
        tk.Label(
            header_frame,
            text="All Enrollments",
            font=theme.FONT_HEADING,
            bg=theme.SURFACE,
            fg=theme.TEXT_PRIMARY,
        ).pack(side="left", padx=(0, 6), pady=(0, 10))
        tk.Button(
            header_frame,
            text=f"Sort: {'Asc' if self._enrollment_sort_asc else 'Desc'}",
            command=self._toggle_enrollment_sort,
            bg=theme.SURFACE,
            fg=theme.TEXT_SECONDARY,
            relief="flat",
        ).pack(side="right", padx=(0, 6), pady=(0, 10))
        columns = ("learner", "course", "status", "score", "enrolled")
        tree = self._make_tree(
            c, columns, ["Learner", "Course", "Status", "Score", "Enrolled Date"]
        )
        for e in sorted(
            self.services["enrollment_repo"].list_all(),
            key=lambda e: e.enrolled_date or "",
            reverse=not self._enrollment_sort_asc,
        ):
            tree.insert(
                "",
                "end",
                values=(
                    e.learner_id,
                    e.course_code,
                    e.status.value,
                    e.score if e.score is not None else "—",
                    (e.enrolled_date or "")[:19],
                ),
            )

    # ------------------------------------------------------------------ #
    # Page: Reports
    # ------------------------------------------------------------------ #
    def _page_reports(self):
        wrap = tk.Frame(self.content, bg=theme.BG)
        wrap.pack(fill="both", expand=True, padx=24, pady=20)
        c = card(wrap)
        c.pack(fill="both", expand=True, ipadx=16, ipady=14)
        tk.Label(
            c,
            text="Course Completion Report",
            font=theme.FONT_HEADING,
            bg=theme.SURFACE,
            fg=theme.TEXT_PRIMARY,
        ).pack(anchor="w", pady=(0, 10))
        columns = ("code", "name", "prereqs", "enrollments", "rate")
        tree = self._make_tree(
            c, columns, ["Code", "Name", "Prereqs", "Enrollments", "Completion Rate"]
        )
        for s in self.services["analytics"].course_completion_stats():
            tree.insert(
                "",
                "end",
                values=(
                    s["code"],
                    s["name"],
                    s["prereqs"],
                    s["enrollments"],
                    f"{s['completion_rate']}%",
                ),
            )

    # ------------------------------------------------------------------ #
    # Page: Learner Portal (self-service)
    # ------------------------------------------------------------------ #
    def _page_learner_portal(self):
        outer = tk.Frame(self.content, bg=theme.BG)
        outer.pack(fill="both", expand=True)
        scroll_area = self._scrollable_container(outer)
        wrap = tk.Frame(scroll_area, bg=theme.BG)
        wrap.pack(fill="both", expand=True, padx=24, pady=20)

        learner_id = getattr(self.user, "user_id", None)
        learners = self.services["learner"].list_learners()
        if not any(l["learner_id"] == learner_id for l in learners):
            try:
                self.services["learner"].register_learner(
                    learner_id, self.user.name, self.user.email
                )
            except LMPTSError:
                pass

        progress = self.services["learner"].get_progress(learner_id)
        top = tk.Frame(wrap, bg=theme.BG)
        top.pack(fill="x")
        for label, value in [
            ("Enrolled", progress["total_courses"]),
            ("Completed", progress["completed"]),
            ("In Progress", progress["in_progress"]),
            ("Completion Rate", f"{progress['completion_rate']}%"),
        ]:
            box = tk.Frame(top, bg=theme.PRIMARY_LIGHT)
            box.pack(side="left", expand=True, fill="x", padx=6, ipady=12)
            tk.Label(
                box,
                text=label,
                font=theme.FONT_SMALL,
                bg=theme.PRIMARY_LIGHT,
                fg=theme.TEXT_SECONDARY,
            ).pack(anchor="w", padx=12)
            tk.Label(
                box,
                text=str(value),
                font=("Helvetica", 18, "bold"),
                bg=theme.PRIMARY_LIGHT,
                fg=theme.PRIMARY_DARK,
            ).pack(anchor="w", padx=12)

        progress_card = card(wrap)
        progress_card.pack(fill="x", pady=(16, 0), ipadx=16, ipady=14)
        tk.Label(
            progress_card,
            text="▶  My Learning Progress",
            font=theme.FONT_HEADING,
            bg=theme.SURFACE,
            fg=theme.TEXT_PRIMARY,
        ).pack(anchor="w", pady=(0, 8))

        for enrollment in progress["enrollments"]:
            row = tk.Frame(progress_card, bg=theme.PRIMARY_LIGHT)
            row.pack(fill="x", pady=6)
            text_box = tk.Frame(row, bg=theme.PRIMARY_LIGHT)
            text_box.pack(side="left", padx=14, pady=12)
            try:
                course = self.services["course"].get_course(enrollment.course_code)
                course_name = course.name
            except LMPTSError:
                course_name = enrollment.course_code
            try:
                progress_data = self.services["assignment"].get_progress(
                    learner_id, enrollment.course_code
                )
                level_text = f"Level {progress_data['current_level']}/{progress_data['total_levels']}"
                score_text = (
                    f"Latest score: {progress_data['latest_score_percent']}%"
                    if progress_data.get("latest_score_percent") is not None
                    else "Latest score: —"
                )
                status_text = progress_data["status"]
            except LMPTSError:
                level_text = "Level 1/1"
                score_text = "Latest score: —"
                status_text = enrollment.status.value
            tk.Label(
                text_box,
                text=f"{enrollment.course_code} — {course_name}",
                font=("Helvetica", 14, "bold"),
                bg=theme.PRIMARY_LIGHT,
                fg=theme.PRIMARY_DARK,
            ).pack(anchor="w")
            tk.Label(
                text_box,
                text=f"Status: {status_text} · {level_text}",
                font=theme.FONT_SMALL,
                bg=theme.PRIMARY_LIGHT,
                fg=theme.TEXT_SECONDARY,
            ).pack(anchor="w")
            tk.Label(
                text_box,
                text=score_text,
                font=theme.FONT_SMALL,
                bg=theme.PRIMARY_LIGHT,
                fg=theme.TEXT_SECONDARY,
            ).pack(anchor="w")
            if enrollment.status != EnrollmentStatus.COMPLETED:
                tk.Label(
                    text_box,
                    text="⏳ Awaiting instructor score",
                    font=theme.FONT_SMALL,
                    bg=theme.PRIMARY_LIGHT,
                    fg=theme.PRIMARY_DARK,
                ).pack(anchor="w", pady=(4, 0))

        avail_card = card(wrap)
        avail_card.pack(fill="both", expand=True, pady=(16, 0), ipadx=16, ipady=14)
        tk.Label(
            avail_card,
            text="Available Courses",
            font=theme.FONT_HEADING,
            bg=theme.SURFACE,
            fg=theme.TEXT_PRIMARY,
        ).pack(anchor="w", pady=(0, 8))

        available = self.services["learner"].available_courses(learner_id)
        for course in available:
            row = tk.Frame(
                avail_card,
                bg=theme.SURFACE,
                highlightbackground=theme.BORDER,
                highlightthickness=1,
            )
            row.pack(fill="x", pady=4)
            tk.Label(
                row,
                text=f"{course.code} — {course.name}",
                font=theme.FONT_BODY_BOLD,
                bg=theme.SURFACE,
            ).pack(side="left", padx=10, pady=8)
            tk.Label(
                row,
                text=f"{course.difficulty.value} · {course.duration_hours}h",
                font=theme.FONT_SMALL,
                bg=theme.SURFACE,
                fg=theme.TEXT_SECONDARY,
            ).pack(side="left", padx=10)

            def make_enroll(code=course.code):
                def _enroll():
                    try:
                        self.services["learner"].enroll(learner_id, code)
                        self._info(f"Learner enrolled successfully in {code}")
                        self._refresh_current_page()
                    except LMPTSError as e:
                        self._error(e)

                return _enroll

            styled_button(row, "Enroll", make_enroll()).pack(
                side="right", padx=10, pady=6, ipady=2, ipadx=8
            )
        if not available:
            tk.Label(
                avail_card,
                text="No new courses available right now.",
                font=theme.FONT_BODY,
                bg=theme.SURFACE,
                fg=theme.TEXT_SECONDARY,
            ).pack(anchor="w")

        my_card = card(wrap)
        my_card.pack(fill="both", expand=True, pady=(16, 0), ipadx=16, ipady=14)
        tk.Label(
            my_card,
            text="My Courses",
            font=theme.FONT_HEADING,
            bg=theme.SURFACE,
            fg=theme.TEXT_PRIMARY,
        ).pack(anchor="w", pady=(0, 8))
        columns = ("course", "status", "score")
        tree = self._make_tree(my_card, columns, ["Course", "Status", "Score"])
        for e in progress["enrollments"]:
            tree.insert(
                "",
                "end",
                values=(
                    e.course_code,
                    e.status.value,
                    e.score if e.score is not None else "—",
                ),
            )

    # ------------------------------------------------------------------ #
    # Page: Settings
    # ------------------------------------------------------------------ #
    def _page_settings(self):
        wrap = tk.Frame(self.content, bg=theme.BG)
        wrap.pack(fill="both", expand=True, padx=24, pady=20)
        c = card(wrap)
        c.pack(fill="x", ipadx=16, ipady=14)
        tk.Label(
            c,
            text="Account",
            font=theme.FONT_HEADING,
            bg=theme.SURFACE,
            fg=theme.TEXT_PRIMARY,
        ).pack(anchor="w")
        for label, value in [
            ("Name", self.user.name),
            ("Email", self.user.email),
            ("Role", self.user.role.value),
        ]:
            row = tk.Frame(c, bg=theme.SURFACE)
            row.pack(fill="x", pady=6)
            tk.Label(
                row,
                text=label,
                font=theme.FONT_BODY_BOLD,
                bg=theme.SURFACE,
                width=12,
                anchor="w",
            ).pack(side="left")
            tk.Label(
                row,
                text=value,
                font=theme.FONT_BODY,
                bg=theme.SURFACE,
                fg=theme.TEXT_SECONDARY,
            ).pack(side="left")

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _scrollable_container(self, parent):
        """Wraps `parent` in a vertically-scrollable canvas and returns the
        inner frame that content should be packed into. Mouse-wheel scrolling
        is only bound while the pointer is over this canvas, so it never
        leaks onto other pages."""
        canvas = tk.Canvas(parent, bg=theme.BG, highlightthickness=0)
        vbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vbar.set)
        vbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(canvas, bg=theme.BG)
        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def on_inner_configure(_event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def on_canvas_configure(event):
            canvas.itemconfig(window_id, width=event.width)

        def on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def bind_wheel(_event):
            canvas.bind_all("<MouseWheel>", on_mousewheel)

        def unbind_wheel(_event):
            canvas.unbind_all("<MouseWheel>")

        inner.bind("<Configure>", on_inner_configure)
        canvas.bind("<Configure>", on_canvas_configure)
        canvas.bind("<Enter>", bind_wheel)
        canvas.bind("<Leave>", unbind_wheel)
        return inner

    def _stat_card(self, parent, icon, label, value, accent):
        """A small KPI card: colored accent strip, icon + label, big value."""
        box = tk.Frame(
            parent,
            bg=theme.SURFACE,
            highlightbackground=theme.BORDER,
            highlightthickness=1,
        )
        tk.Frame(box, bg=accent, height=4).pack(fill="x", side="top")
        inner = tk.Frame(box, bg=theme.SURFACE)
        inner.pack(fill="both", expand=True, padx=16, pady=12)
        head = tk.Frame(inner, bg=theme.SURFACE)
        head.pack(fill="x")
        tk.Label(head, text=icon, font=("Helvetica", 18), bg=theme.SURFACE).pack(
            side="left"
        )
        tk.Label(
            head,
            text=label,
            font=theme.FONT_SMALL,
            bg=theme.SURFACE,
            fg=theme.TEXT_SECONDARY,
        ).pack(side="left", padx=(8, 0))
        tk.Label(
            inner,
            text=str(value),
            font=("Helvetica", 22, "bold"),
            bg=theme.SURFACE,
            fg=theme.TEXT_PRIMARY,
        ).pack(anchor="w", pady=(6, 0))
        return box

    def _legend_swatch(self, parent, color, text):
        item = tk.Frame(parent, bg=theme.SURFACE)
        item.pack(side="left", padx=(0, 16))
        tk.Frame(item, bg=color, width=12, height=12).pack(side="left", padx=(0, 6))
        tk.Label(
            item,
            text=text,
            font=theme.FONT_SMALL,
            bg=theme.SURFACE,
            fg=theme.TEXT_SECONDARY,
        ).pack(side="left")

    def _draw_enrollment_bar_chart(self, parent, course_stats, height=240):
        """Draws grouped bars (enrolled vs completed) per course on a Canvas.
        Redraws itself on resize so the dashboard stays responsive."""
        canvas = tk.Canvas(
            parent, bg=theme.SURFACE, height=height, highlightthickness=0
        )
        canvas.pack(fill="both", expand=True)

        if not course_stats:
            canvas.create_text(
                20,
                height // 2,
                anchor="w",
                text="No enrollment data yet",
                font=theme.FONT_BODY,
                fill=theme.TEXT_SECONDARY,
            )
            return canvas

        max_val = (
            max((max(c["enrolled"], c["completed"]) for c in course_stats), default=1)
            or 1
        )
        n = len(course_stats)
        left_pad, right_pad, top_pad, bottom_pad = 16, 16, 16, 34

        def redraw(_event=None):
            canvas.delete("all")
            w = canvas.winfo_width() or 640
            h = canvas.winfo_height() or height
            chart_w = max(w - left_pad - right_pad, 10)
            chart_h = max(h - top_pad - bottom_pad, 10)
            group_w = chart_w / n
            bar_w = min(26, group_w / 3)
            for i, c in enumerate(course_stats):
                gx = left_pad + i * group_w + group_w / 2
                enrolled_h = (c["enrolled"] / max_val) * chart_h
                completed_h = (c["completed"] / max_val) * chart_h

                x0 = gx - bar_w - 3
                canvas.create_rectangle(
                    x0,
                    top_pad + chart_h - enrolled_h,
                    x0 + bar_w,
                    top_pad + chart_h,
                    fill=theme.PRIMARY,
                    outline="",
                )
                x1 = gx + 3
                canvas.create_rectangle(
                    x1,
                    top_pad + chart_h - completed_h,
                    x1 + bar_w,
                    top_pad + chart_h,
                    fill=theme.SUCCESS,
                    outline="",
                )

                canvas.create_text(
                    gx,
                    top_pad + chart_h + 6,
                    text=c["code"],
                    font=theme.FONT_SMALL,
                    fill=theme.TEXT_SECONDARY,
                    anchor="n",
                )
                if c["enrolled"]:
                    canvas.create_text(
                        x0 + bar_w / 2,
                        top_pad + chart_h - enrolled_h - 8,
                        text=str(c["enrolled"]),
                        font=theme.FONT_SMALL,
                        fill=theme.TEXT_PRIMARY,
                    )
                if c["completed"]:
                    canvas.create_text(
                        x1 + bar_w / 2,
                        top_pad + chart_h - completed_h - 8,
                        text=str(c["completed"]),
                        font=theme.FONT_SMALL,
                        fill=theme.TEXT_PRIMARY,
                    )
            canvas.create_line(
                left_pad,
                top_pad + chart_h,
                w - right_pad,
                top_pad + chart_h,
                fill=theme.BORDER,
            )

        canvas.bind("<Configure>", redraw)
        return canvas

    def _draw_completion_donut(self, parent, segments, size=180):
        """Draws a donut chart for a list of (label, value, color) segments,
        with the overall completed percentage in the middle and a legend
        alongside it."""
        row = tk.Frame(parent, bg=theme.SURFACE)
        row.pack(fill="x", pady=(4, 0))

        total = sum(v for _, v, _ in segments)
        canvas = tk.Canvas(
            row, width=size, height=size, bg=theme.SURFACE, highlightthickness=0
        )
        canvas.pack(anchor="center", padx=(0, 20))

        if total == 0:
            canvas.create_text(
                size / 2,
                size / 2,
                text="No data",
                font=theme.FONT_SMALL,
                fill=theme.TEXT_SECONDARY,
            )
        else:
            start = 90
            pad = 6
            for _, value, color in segments:
                extent = -360 * (value / total)
                canvas.create_arc(
                    pad,
                    pad,
                    size - pad,
                    size - pad,
                    start=start,
                    extent=extent,
                    fill=color,
                    outline=theme.SURFACE,
                    width=3,
                    style="pieslice",
                )
                start += extent
            hole = size * 0.55
            off = (size - hole) / 2
            canvas.create_oval(
                off,
                off,
                off + hole,
                off + hole,
                fill=theme.SURFACE,
                outline=theme.SURFACE,
            )

            completed_value = next(
                (v for label, v, _ in segments if label.lower() == "completed"), 0
            )
            pct = round(100 * completed_value / total)
            canvas.create_text(
                size / 2,
                size / 2 - 8,
                text=f"{pct}%",
                font=("Helvetica", 18, "bold"),
                fill=theme.TEXT_PRIMARY,
            )
            canvas.create_text(
                size / 2,
                size / 2 + 14,
                text="Completed",
                font=theme.FONT_SMALL,
                fill=theme.TEXT_SECONDARY,
            )

        legend = tk.Frame(row, bg=theme.SURFACE)
        legend.pack(side="left", fill="y")
        if not segments:
            tk.Label(
                legend,
                text="No enrollments yet.",
                font=theme.FONT_BODY,
                bg=theme.SURFACE,
                fg=theme.TEXT_SECONDARY,
            ).pack(anchor="center")
        for label, value, color in segments:
            item = tk.Frame(legend, bg=theme.SURFACE)
            item.pack(anchor="w", pady=3)
            tk.Frame(item, bg=color, width=12, height=12).pack(side="left", padx=(0, 6))
            pct = round(100 * value / total) if total else 0
            tk.Label(
                item,
                text=f"{label} — {value} ({pct}%)",
                font=theme.FONT_SMALL,
                bg=theme.SURFACE,
                fg=theme.TEXT_PRIMARY,
            ).pack(anchor="center")
        return row

    def _make_tree(self, parent, columns, headings):
        frame = tk.Frame(parent, bg=theme.SURFACE)
        frame.pack(fill="both", expand=True)
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Treeview",
            rowheight=30,
            font=theme.FONT_BODY,
            background="white",
            fieldbackground="white",
            borderwidth=0,
        )
        style.configure(
            "Treeview.Heading",
            font=theme.FONT_BODY_BOLD,
            background=theme.PRIMARY,
            foreground="white",
            relief="flat",
        )
        style.map("Treeview.Heading", background=[("active", theme.PRIMARY)])

        tree = ttk.Treeview(frame, columns=columns, show="headings", height=8)
        for col, head in zip(columns, headings):
            tree.heading(col, text=head)
            tree.column(col, width=140, anchor="center")
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        return tree

    # ------------------------------------------------------------------ #
    # Page: Instructors (Administrator's view of every instructor's
    # courses and student progress)
    # ------------------------------------------------------------------ #
    def _page_instructors(self):
        outer = tk.Frame(self.content, bg=theme.BG)
        outer.pack(fill="both", expand=True)
        scroll_area = self._scrollable_container(outer)
        pad = tk.Frame(scroll_area, bg=theme.BG)
        pad.pack(fill="both", expand=True, padx=24, pady=20)

        course_service = self.services["course"]
        learner_service = self.services["learner"]
        enrollment_repo = self.services["enrollment_repo"]

        courses = course_service.list_courses()
        all_enrollments = enrollment_repo.list_all()

        instructor_names = sorted(
            {
                c.instructor
                for c in courses
                if getattr(c, "instructor", None) not in (None, "")
            }
        )

        instructor_stats = []
        for name in instructor_names:
            their_courses = [c for c in courses if c.instructor == name]
            their_codes = {c.code for c in their_courses}
            their_enrollments = [
                e for e in all_enrollments if e.course_code in their_codes
            ]
            students = {e.learner_id for e in their_enrollments}
            completed = [
                e for e in their_enrollments if e.status == EnrollmentStatus.COMPLETED
            ]
            rate = (
                round((len(completed) / len(their_enrollments) * 100), 1)
                if their_enrollments
                else 0.0
            )
            instructor_stats.append(
                {
                    "name": name,
                    "courses": their_courses,
                    "enrollments": their_enrollments,
                    "students": students,
                    "rate": rate,
                }
            )

        # --- KPI summary row ---
        total_enrollments = sum(len(s["enrollments"]) for s in instructor_stats)
        total_completed = sum(
            len([e for e in s["enrollments"] if e.status == EnrollmentStatus.COMPLETED])
            for s in instructor_stats
        )
        overall_rate = (
            round((total_completed / total_enrollments * 100), 1)
            if total_enrollments
            else 0.0
        )
        top = tk.Frame(pad, bg=theme.BG)
        top.pack(fill="x")
        kpis = [
            ("🧑‍🏫", "Total Instructors", len(instructor_stats), theme.PRIMARY),
            (
                "📘",
                "Courses Taught",
                sum(len(s["courses"]) for s in instructor_stats),
                theme.SUCCESS,
            ),
            ("📋", "Total Enrollments", total_enrollments, "#f59e0b"),
            ("🎯", "Avg Completion Rate", f"{overall_rate}%", "#8b5cf6"),
        ]
        for i, (icon, label, value, accent) in enumerate(kpis):
            box = self._stat_card(top, icon, label, value, accent)
            box.pack(
                side="left", expand=True, fill="both", padx=(0 if i == 0 else 8, 0)
            )

        if not instructor_stats:
            tk.Label(
                pad,
                bg=theme.BG,
                fg=theme.TEXT_SECONDARY,
                font=theme.FONT_BODY,
                justify="left",
                text=(
                    "No instructors are currently assigned to any course.\n"
                    "Set the Instructor field when creating/editing a course "
                    "(Courses \u2192 Create/Edit Course) to see them here."
                ),
            ).pack(anchor="w", pady=(16, 0))
            return

        # --- Instructors summary table ---
        list_card = card(pad)
        list_card.pack(fill="both", pady=(16, 0), ipadx=16, ipady=14)
        tk.Label(
            list_card,
            text="Instructors",
            font=theme.FONT_HEADING,
            bg=theme.SURFACE,
            fg=theme.TEXT_PRIMARY,
        ).pack(anchor="w", pady=(0, 8))
        tk.Label(
            list_card,
            text="Select a row to view that instructor's courses and student progress",
            font=theme.FONT_SMALL,
            bg=theme.SURFACE,
            fg=theme.TEXT_SECONDARY,
        ).pack(anchor="w", pady=(0, 8))

        columns = ("name", "courses", "students", "enrollments", "rate")
        instr_tree = self._make_tree(
            list_card,
            columns,
            ["Instructor", "Courses", "Students", "Enrollments", "Completion Rate"],
        )
        for s in instructor_stats:
            instr_tree.insert(
                "",
                "end",
                iid=s["name"],
                values=(
                    s["name"],
                    len(s["courses"]),
                    len(s["students"]),
                    len(s["enrollments"]),
                    f"{s['rate']}%",
                ),
            )

        # --- Drill-down: selected instructor's courses + student progress ---
        detail_card = card(pad)
        detail_card.pack(fill="both", expand=True, pady=(16, 0), ipadx=16, ipady=14)
        detail_header = tk.Label(
            detail_card,
            text="Select an instructor above to view details",
            font=theme.FONT_HEADING,
            bg=theme.SURFACE,
            fg=theme.TEXT_PRIMARY,
        )
        detail_header.pack(anchor="w", pady=(0, 8))
        detail_body = tk.Frame(detail_card, bg=theme.SURFACE)
        detail_body.pack(fill="both", expand=True)

        def render_detail(name):
            for w in detail_body.winfo_children():
                w.destroy()
            stat = next((s for s in instructor_stats if s["name"] == name), None)
            if not stat:
                return
            detail_header.configure(
                text=f"\U0001f9d1\u200d\U0001f3eb  {name} \u2014 Courses & Student Progress"
            )

            # --- Instructor account (login credentials) management ---
            account_service = self.services.get("account")
            matches = (
                [
                    a
                    for a in account_service.list_accounts()
                    if a["role"] == "Instructor"
                    and (a["name"] or "").strip().casefold() == name.strip().casefold()
                ]
                if account_service
                else []
            )
            account = matches[0] if matches else None

            acct_card = tk.Frame(
                detail_body,
                bg=theme.SURFACE,
                highlightbackground=theme.BORDER,
                highlightthickness=1,
            )
            acct_card.pack(fill="x", pady=(0, 14), ipadx=12, ipady=10)
            tk.Label(
                acct_card,
                text="🔑 Instructor Account",
                font=theme.FONT_BODY_BOLD,
                bg=theme.SURFACE,
                fg=theme.TEXT_PRIMARY,
            ).pack(anchor="w")

            if not account:
                tk.Label(
                    acct_card,
                    text=(
                        "No login account found for this instructor name. "
                        "Account credentials can only be edited if a matching "
                        "Instructor account exists."
                    ),
                    font=theme.FONT_SMALL,
                    bg=theme.SURFACE,
                    fg=theme.TEXT_SECONDARY,
                    justify="left",
                    wraplength=560,
                ).pack(anchor="w", pady=(4, 0))
            else:
                acct_form = tk.Frame(acct_card, bg=theme.SURFACE)
                acct_form.pack(fill="x", pady=(8, 0))
                for i in range(3):
                    acct_form.columnconfigure(i, weight=1)
                acct_id_e = labeled_entry(acct_form, "Instructor ID", 0, 0)
                acct_id_e.insert(0, account["user_id"])
                acct_email_e = labeled_entry(acct_form, "Email", 0, 1)
                acct_email_e.insert(0, account["email"])
                acct_pw_e = labeled_entry(acct_form, "Password", 0, 2, show="•")
                acct_pw_e.insert(0, account["password"])

                acct_error = tk.Label(
                    acct_card,
                    text="",
                    font=theme.FONT_SMALL,
                    bg=theme.SURFACE,
                    fg=theme.DANGER,
                )
                acct_error.pack(anchor="w", pady=(4, 0))

                def do_update_account(current_id=account["user_id"]):
                    new_id = acct_id_e.get().strip()
                    email = acct_email_e.get().strip()
                    password = acct_pw_e.get()
                    try:
                        if new_id and new_id != current_id:
                            if not messagebox.askyesno(
                                "Confirm ID change",
                                f"Change instructor ID from {current_id} to "
                                f"{new_id}?",
                            ):
                                return
                            self.services["account"].change_account_id(
                                current_id, new_id
                            )
                            current_id = new_id
                        self.services["account"].update_account(
                            current_id, name, email, password, "Instructor"
                        )
                        self._info(f"Instructor account {current_id} updated")
                        self._refresh_current_page()
                    except LMPTSError as e:
                        acct_error.config(text=str(e))

                def do_delete_account(user_id=account["user_id"]):
                    if not messagebox.askyesno(
                        "Delete instructor account",
                        f"Delete the login account for {name} ({user_id})? "
                        "This removes their ability to log in but does not "
                        "delete the courses they've been assigned to.",
                    ):
                        return
                    try:
                        self.services["account"].delete_account(user_id)
                        self._info(f"Instructor account {user_id} deleted")
                        self._refresh_current_page()
                    except LMPTSError as e:
                        acct_error.config(text=str(e))

                acct_btn_row = tk.Frame(acct_card, bg=theme.SURFACE)
                acct_btn_row.pack(fill="x", pady=(8, 0))
                styled_button(
                    acct_btn_row,
                    "💾 Update Account",
                    do_update_account,
                    bg=theme.SUCCESS,
                ).pack(side="left", padx=(0, 6), ipady=6, ipadx=10)
                styled_button(
                    acct_btn_row,
                    "🗑️ Delete Account",
                    do_delete_account,
                    bg=theme.DANGER,
                ).pack(side="left", ipady=6, ipadx=10)

            tk.Label(
                detail_body,
                text="Courses",
                font=theme.FONT_BODY_BOLD,
                bg=theme.SURFACE,
                fg=theme.TEXT_PRIMARY,
            ).pack(anchor="w", pady=(4, 4))
            c_columns = ("code", "cname", "difficulty", "hours", "enrolled", "rate")
            c_tree = self._make_tree(
                detail_body,
                c_columns,
                ["Code", "Name", "Difficulty", "Hours", "Enrolled", "Completion Rate"],
            )
            for c in stat["courses"]:
                c_enrollments = [
                    e for e in stat["enrollments"] if e.course_code == c.code
                ]
                c_completed = [
                    e for e in c_enrollments if e.status == EnrollmentStatus.COMPLETED
                ]
                c_rate = (
                    round((len(c_completed) / len(c_enrollments) * 100), 1)
                    if c_enrollments
                    else 0.0
                )
                c_tree.insert(
                    "",
                    "end",
                    values=(
                        c.code,
                        c.name,
                        c.difficulty.value,
                        c.duration_hours,
                        len(c_enrollments),
                        f"{c_rate}%",
                    ),
                )

            hdr = tk.Frame(detail_body, bg=theme.SURFACE)
            hdr.pack(fill="x")
            tk.Label(
                hdr,
                text="Student Progress",
                font=theme.FONT_BODY_BOLD,
                bg=theme.SURFACE,
                fg=theme.TEXT_PRIMARY,
            ).pack(side="left", pady=(12, 4))
            tk.Button(
                hdr,
                text=f"Sort: {'Asc' if self._enrollment_sort_asc else 'Desc'}",
                command=self._toggle_enrollment_sort,
                bg=theme.SURFACE,
                fg=theme.TEXT_SECONDARY,
                relief="flat",
            ).pack(side="right", pady=(12, 4))
            p_columns = ("learner_id", "name", "course", "status", "score", "enrolled")
            p_tree = self._make_tree(
                detail_body,
                p_columns,
                ["Learner ID", "Name", "Course", "Status", "Score", "Enrolled Date"],
            )
            for e in sorted(
                stat["enrollments"],
                key=lambda e: e.enrolled_date or "",
                reverse=not self._enrollment_sort_asc,
            ):
                p_tree.insert(
                    "",
                    "end",
                    iid=f"{e.learner_id}|{e.course_code}",
                    values=(
                        e.learner_id,
                        learner_service.get_learner_name(e.learner_id),
                        e.course_code,
                        e.status.value,
                        (
                            e.score
                            if e.score is not None
                            else (
                                "⚠ Needs Score"
                                if e.status != EnrollmentStatus.COMPLETED
                                else "—"
                            )
                        ),
                        (e.enrolled_date or "")[:19],
                    ),
                )

            grade_action_row = tk.Frame(detail_body, bg=theme.SURFACE)
            grade_action_row.pack(fill="x", pady=(10, 0))

            def do_submit_score():
                sel = p_tree.selection()
                if not sel:
                    self._error("Select a student row first")
                    return
                learner_id, course_code = sel[0].split("|", 1)
                self._open_mark_completed_dialog(learner_id, course_code)

            styled_button(
                grade_action_row, "✔ Submit Level Score", do_submit_score
            ).pack(side="left", ipady=6, ipadx=10)

        def on_select(_event):
            sel = instr_tree.selection()
            if sel:
                render_detail(sel[0])

        instr_tree.bind("<<TreeviewSelect>>", on_select)
        first_name = instructor_stats[0]["name"]
        instr_tree.selection_set(first_name)
        render_detail(first_name)

        # ------------------------------------------------------------------ #

    def _page_instructor_portal(self):
        outer = tk.Frame(self.content, bg=theme.BG)
        outer.pack(fill="both", expand=True)
        scroll_area = self._scrollable_container(outer)
        wrap = tk.Frame(scroll_area, bg=theme.BG)
        wrap.pack(fill="both", expand=True, padx=24, pady=20)

        course_service = self.services["course"]
        learner_service = self.services["learner"]
        enrollment_repo = self.services["enrollment_repo"]

        my_courses = course_service.list_courses_by_instructor(self.user.name)
        if not my_courses:
            # The exact-match lookup found nothing - fall back to a
            # case/whitespace-insensitive match, in case the Instructor
            # field on a course was typed with different casing/spacing
            # than the logged-in account's name.
            target = (self.user.name or "").strip().casefold()
            my_courses = [
                c
                for c in course_service.list_courses()
                if (getattr(c, "instructor", "") or "").strip().casefold() == target
            ]
        my_codes = [c.code for c in my_courses]

        # Gather every enrollment across this instructor's own courses only.
        all_enrollments = []
        for code in my_codes:
            all_enrollments.extend(enrollment_repo.list_for_course(code))

        unique_students = {e.learner_id for e in all_enrollments}
        completed = [
            e for e in all_enrollments if e.status == EnrollmentStatus.COMPLETED
        ]
        avg_rate = (
            round((len(completed) / len(all_enrollments) * 100), 1)
            if all_enrollments
            else 0.0
        )

        if not my_courses:
            tk.Label(
                wrap,
                bg=theme.BG,
                fg=theme.TEXT_SECONDARY,
                font=theme.FONT_BODY,
                justify="left",
                text=(
                    f"No courses are currently assigned to '{self.user.name}'.\n"
                    "Ask an Administrator to set the Instructor field on a course "
                    "(Courses \u2192 Create/Edit Course) to your account name to see it here."
                ),
            ).pack(anchor="w", pady=(10, 0))
            return

        # --- Overview cards ---
        top = tk.Frame(wrap, bg=theme.BG)
        top.pack(fill="x")
        for label, value in [
            ("My Courses", len(my_courses)),
            ("Total Students", len(unique_students)),
            ("Total Enrollments", len(all_enrollments)),
            ("Avg Completion Rate", f"{avg_rate}%"),
        ]:
            box = tk.Frame(top, bg=theme.PRIMARY_LIGHT)
            box.pack(side="left", expand=True, fill="x", padx=6, ipady=12)
            tk.Label(
                box,
                text=label,
                font=theme.FONT_SMALL,
                bg=theme.PRIMARY_LIGHT,
                fg=theme.TEXT_SECONDARY,
            ).pack(anchor="w", padx=12)
            tk.Label(
                box,
                text=str(value),
                font=("Helvetica", 18, "bold"),
                bg=theme.PRIMARY_LIGHT,
                fg=theme.PRIMARY_DARK,
            ).pack(anchor="w", padx=12)

        # --- My Courses ---
        courses_card = card(wrap)
        courses_card.pack(fill="both", pady=(16, 0), ipadx=16, ipady=14)
        tk.Label(
            courses_card,
            text="My Courses",
            font=theme.FONT_HEADING,
            bg=theme.SURFACE,
            fg=theme.TEXT_PRIMARY,
        ).pack(anchor="w", pady=(0, 8))
        columns = ("code", "name", "difficulty", "hours", "enrolled", "rate")
        courses_tree = self._make_tree(
            courses_card,
            columns,
            ["Code", "Name", "Difficulty", "Hours", "Enrolled", "Completion Rate"],
        )
        for c in my_courses:
            course_enrollments = enrollment_repo.list_for_course(c.code)
            course_completed = [
                e for e in course_enrollments if e.status == EnrollmentStatus.COMPLETED
            ]
            rate = (
                round((len(course_completed) / len(course_enrollments) * 100), 1)
                if course_enrollments
                else 0.0
            )
            courses_tree.insert(
                "",
                "end",
                values=(
                    c.code,
                    c.name,
                    c.difficulty.value,
                    c.duration_hours,
                    len(course_enrollments),
                    f"{rate}%",
                ),
            )

        # --- Enroll a student in one of my courses ---
        enroll_card = card(wrap)
        enroll_card.pack(fill="x", pady=(16, 0), ipadx=16, ipady=14)
        tk.Label(
            enroll_card,
            text="Enroll a Student",
            font=theme.FONT_HEADING,
            bg=theme.SURFACE,
            fg=theme.TEXT_PRIMARY,
        ).pack(anchor="w", pady=(0, 8))
        erow = tk.Frame(enroll_card, bg=theme.SURFACE)
        erow.pack(fill="x")
        tk.Label(
            erow, text="Learner ID", font=theme.FONT_BODY_BOLD, bg=theme.SURFACE
        ).grid(row=0, column=0, sticky="w")
        learner_id_entry = tk.Entry(
            erow, font=theme.FONT_BODY, width=18, relief="solid", bd=1
        )
        learner_id_entry.grid(row=1, column=0, padx=(0, 10), pady=(4, 0), ipady=4)
        tk.Label(erow, text="Course", font=theme.FONT_BODY_BOLD, bg=theme.SURFACE).grid(
            row=0, column=1, sticky="w"
        )
        course_combo = ttk.Combobox(erow, values=my_codes, state="readonly", width=16)
        course_combo.grid(row=1, column=1, padx=(0, 10), pady=(4, 0))

        def do_enroll_student():
            lid = learner_id_entry.get().strip()
            code = course_combo.get()
            if not lid or not code:
                self._error("Enter a learner ID and select one of your courses")
                return
            try:
                self.services["learner"].enroll(lid, code)
                self._info(f"Enrolled learner {lid} in {code}")
                self._refresh_current_page()
            except LMPTSError as e:
                self._error(e)

        styled_button(erow, "✔ Enroll", do_enroll_student).grid(
            row=1, column=2, padx=(0, 0), ipady=6, ipadx=10
        )

        # --- Student progress across my courses ---
        progress_card = card(wrap)
        progress_card.pack(fill="both", expand=True, pady=(16, 0), ipadx=16, ipady=14)
        header_row = tk.Frame(progress_card, bg=theme.SURFACE)
        header_row.pack(fill="x")
        tk.Label(
            header_row,
            text="Student Progress",
            font=theme.FONT_HEADING,
            bg=theme.SURFACE,
            fg=theme.TEXT_PRIMARY,
        ).pack(side="left")

        filter_frame = tk.Frame(header_row, bg=theme.SURFACE)
        filter_frame.pack(side="right")
        tk.Label(
            filter_frame,
            text="Course:",
            font=theme.FONT_SMALL,
            bg=theme.SURFACE,
            fg=theme.TEXT_SECONDARY,
        ).pack(side="left", padx=(0, 6))
        filter_combo = ttk.Combobox(
            filter_frame, values=["All"] + my_codes, state="readonly", width=14
        )
        filter_combo.set("All")
        filter_combo.pack(side="left")

        table_holder = tk.Frame(progress_card, bg=theme.SURFACE)
        table_holder.pack(fill="both", expand=True, pady=(10, 0))

        def render_progress_table():
            for w in table_holder.winfo_children():
                w.destroy()
            chosen = filter_combo.get()
            rows = [
                e for e in all_enrollments if chosen == "All" or e.course_code == chosen
            ]

            columns = (
                "learner_id",
                "name",
                "course",
                "status",
                "level",
                "score",
                "enrolled",
            )
            ptree = ttk.Treeview(
                table_holder, columns=columns, show="headings", height=8
            )
            for col, head in zip(
                columns,
                [
                    "Learner ID",
                    "Name",
                    "Course",
                    "Status",
                    "Level",
                    "Latest Score",
                    "Enrolled Date",
                ],
            ):
                ptree.heading(col, text=head)
                ptree.column(col, width=130, anchor="w")
            for e in rows:
                progress_data = None
                try:
                    progress_data = self.services["assignment"].get_progress(
                        e.learner_id, e.course_code
                    )
                except LMPTSError:
                    progress_data = None
                level_label = "—"
                score_label = "—"
                if progress_data is not None:
                    level_label = f"{progress_data['current_level']}/{progress_data['total_levels']}"
                    if progress_data.get("latest_score_percent") is not None:
                        score_label = f"{progress_data['latest_score_percent']}%"
                    elif e.status != EnrollmentStatus.COMPLETED:
                        score_label = "⚠ Needs Score"
                ptree.insert(
                    "",
                    "end",
                    iid=f"{e.learner_id}|{e.course_code}",
                    values=(
                        e.learner_id,
                        learner_service.get_learner_name(e.learner_id),
                        e.course_code,
                        e.status.value,
                        level_label,
                        score_label,
                        (e.enrolled_date or "")[:19],
                    ),
                )
            ptree.pack(side="left", fill="both", expand=True)
            scrollbar = ttk.Scrollbar(
                table_holder, orient="vertical", command=ptree.yview
            )
            ptree.configure(yscrollcommand=scrollbar.set)
            scrollbar.pack(side="right", fill="y")

            action_row = tk.Frame(progress_card, bg=theme.SURFACE)
            action_row.pack(fill="x", pady=(10, 0))

            def get_selected():
                sel = ptree.selection()
                if not sel:
                    self._error("Select a student row first")
                    return None
                learner_id, course_code = sel[0].split("|", 1)
                return learner_id, course_code

            def do_mark_completed():
                picked = get_selected()
                if not picked:
                    return
                learner_id, course_code = picked
                self._open_mark_completed_dialog(learner_id, course_code)

            def do_remove_enrollment():
                picked = get_selected()
                if not picked:
                    return
                learner_id, course_code = picked
                if messagebox.askyesno(
                    "Remove enrollment", f"Remove {learner_id} from {course_code}?"
                ):
                    try:
                        self.services["learner"].remove_enrollment(
                            learner_id, course_code
                        )
                        self._info("Enrollment removed")
                        self._refresh_current_page()
                    except LMPTSError as e:
                        self._error(e)

            for w in action_row.winfo_children():
                w.destroy()
            styled_button(action_row, "✔ Submit Level Score", do_mark_completed).pack(
                side="left", ipady=6, ipadx=10
            )
            styled_button(
                action_row,
                "✖ Remove Enrollment",
                do_remove_enrollment,
                bg=theme.DANGER_LIGHT,
                fg=theme.DANGER,
            ).pack(side="left", padx=(10, 0), ipady=6, ipadx=10)

        filter_combo.bind("<<ComboboxSelected>>", lambda e: render_progress_table())
        render_progress_table()

    def _open_mark_completed_dialog(self, learner_id: str, course_code: str):
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Submit Score - {learner_id} / {course_code}")
        dialog.configure(bg=theme.SURFACE)
        dialog.geometry("340x300")
        dialog.transient(self.root)
        dialog.grab_set()

        form = tk.Frame(dialog, bg=theme.SURFACE)
        form.pack(fill="both", expand=True, padx=20, pady=20)
        tk.Label(
            form,
            text=f"{learner_id} \u2014 {course_code}",
            font=theme.FONT_HEADING,
            bg=theme.SURFACE,
            fg=theme.TEXT_PRIMARY,
        ).pack(anchor="w", pady=(0, 10))

        # Pull the learner's current level for this course so the instructor
        # knows which level they're grading, and use the real pass cutoff
        # (the same one AssignmentService.submit_grade checks against).
        try:
            level_progress = self.services["assignment"].get_progress(
                learner_id, course_code
            )
            level_before = level_progress["current_level"]
            total_levels = level_progress["total_levels"]
        except LMPTSError:
            level_before = 1
            total_levels = 1
        cutoff = _pass_cutoff()

        tk.Label(
            form,
            text=f"Grading Level {level_before}/{total_levels}",
            font=theme.FONT_SMALL,
            bg=theme.SURFACE,
            fg=theme.TEXT_SECONDARY,
        ).pack(anchor="w", pady=(0, 4))
        tk.Label(
            form,
            text=f"Pass cutoff: {cutoff:g}%",
            font=theme.FONT_SMALL,
            bg=theme.SURFACE,
            fg=theme.TEXT_SECONDARY,
        ).pack(anchor="w", pady=(0, 4))

        tk.Label(
            form,
            text="Score",
            font=theme.FONT_BODY_BOLD,
            bg=theme.SURFACE,
        ).pack(anchor="w")
        score_entry = tk.Entry(
            form, font=("Helvetica", 22, "bold"), relief="solid", bd=1
        )
        score_entry.pack(anchor="w", pady=(4, 10), fill="x", ipady=4)
        score_entry.focus_set()

        error_label = tk.Label(
            form, text="", font=theme.FONT_SMALL, bg=theme.SURFACE, fg=theme.DANGER
        )
        error_label.pack(anchor="w")

        def do_save():
            raw = score_entry.get().strip()
            if not raw:
                error_label.config(text="Enter a score")
                return
            try:
                score = float(raw)
            except ValueError:
                error_label.config(text="Score must be a number")
                return
            if not (0 <= score <= 100):
                error_label.config(text="Score must be between 0 and 100")
                return
            try:
                # submit_grade is the level-aware path: it records the grade,
                # and only advances current_level (or completes the course
                # at the final level) if the score clears the cutoff.
                # A below-cutoff score just leaves the learner on the same
                # level to retry - it does not complete or fail the course.
                result = self.services["assignment"].submit_grade(
                    learner_id, course_code, score
                )
                dialog.destroy()
                passed = score >= cutoff
                if result["status"] == "completed":
                    self._info(
                        f"{learner_id} completed {course_code} with a final "
                        f"score of {score}% (cutoff {cutoff:g}%)"
                    )
                elif passed:
                    self._info(
                        f"{learner_id} passed level {level_before}/{total_levels} "
                        f"of {course_code} with {score}% and moved up to "
                        f"level {result['current_level']}/{result['total_levels']}"
                    )
                else:
                    self._info(
                        f"{learner_id} scored {score}% on {course_code} "
                        f"(below the {cutoff:g}% cutoff) - staying on "
                        f"level {level_before}/{total_levels}"
                    )
                self._refresh_current_page()
                self._open_progression_dialog(learner_id, course_code, score, passed)
            except LMPTSError as e:
                error_label.config(text=str(e))

        btn_row = tk.Frame(form, bg=theme.SURFACE)
        btn_row.pack(fill="x", pady=(6, 0))
        styled_button(btn_row, "Save", do_save).pack(
            side="left", expand=True, fill="x", ipady=6, padx=(0, 6)
        )
        styled_button(
            btn_row, "Cancel", dialog.destroy, bg=theme.SURFACE, fg=theme.TEXT_PRIMARY
        ).pack(side="left", expand=True, fill="x", ipady=6)

    def _next_level_courses(self, learner_id: str, course_code: str):
        """Courses that list `course_code` as a direct prerequisite, limited
        to the ones the learner is actually eligible for right now (all of
        their other prerequisites are met and they're not already enrolled
        or completed)."""
        course_service = self.services["course"]
        try:
            eligible = {
                c.code: c
                for c in self.services["learner"].available_courses(learner_id)
            }
        except LMPTSError:
            return []
        unlocked = []
        for c in course_service.list_courses():
            try:
                prereqs = course_service.get_direct_prerequisites(c.code)
            except LMPTSError:
                continue
            if course_code in prereqs and c.code in eligible:
                unlocked.append(eligible[c.code])
        return unlocked

    def _open_progression_dialog(
        self, learner_id: str, course_code: str, score, passed: bool
    ):
        dialog = tk.Toplevel(self.root)
        dialog.title("Level Progress")
        dialog.configure(bg=theme.SURFACE)
        dialog.transient(self.root)
        dialog.grab_set()

        form = tk.Frame(dialog, bg=theme.SURFACE)
        form.pack(fill="both", expand=True, padx=20, pady=20)

        if passed:
            tk.Label(
                form,
                text=f"✔ Level score recorded for {course_code}",
                font=theme.FONT_HEADING,
                bg=theme.SURFACE,
                fg=theme.SUCCESS,
            ).pack(anchor="w", pady=(0, 10))
        else:
            tk.Label(
                form,
                text=f"• Score recorded for {course_code}",
                font=theme.FONT_HEADING,
                bg=theme.SURFACE,
                fg=theme.PRIMARY_DARK,
            ).pack(anchor="w", pady=(0, 10))

        tk.Label(
            form,
            text=f"Score entered: {score}%",
            font=theme.FONT_BODY,
            bg=theme.SURFACE,
            fg=theme.TEXT_SECONDARY,
        ).pack(anchor="w", pady=(0, 6))
        tk.Label(
            form,
            text="The learner can retake the current level anytime without being locked out.",
            font=theme.FONT_SMALL,
            bg=theme.SURFACE,
            fg=theme.TEXT_SECONDARY,
            wraplength=320,
            justify="left",
        ).pack(anchor="w", pady=(0, 6))

        styled_button(form, "Close", dialog.destroy).pack(
            fill="x", pady=(10, 0), ipady=6
        )
