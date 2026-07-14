"""
Login / Registration window.

Two modes toggle inside the same right-hand panel:
  - "login"    : email + password -> AuthService.login()
  - "register" : full name + email + password + confirm + role
                 -> AuthService.register()  (Learner / Instructor / Analyst only)

The Administrator account is fixed and never goes through registration, and
is never listed as an option anywhere on this screen - the admin simply
types the fixed email/password into the same Sign In form as everyone else.

On success, LoginWindow calls on_success(user); MainApp then shows the
dashboard that matches user.role (polymorphism drives which pages appear).
"""

import tkinter as tk
from tkinter import ttk, messagebox

from core.exceptions import AuthenticationError, LMPTSError, UserNotFoundError
from core.models import UserRole
from data.settings import (
    delete_setting,
    get_setting,
    KEY_REMEMBERED_EMAIL,
    set_setting,
)
from services.lmpts_service import (
    AccountService,
    AuthService,
    FIXED_ADMIN_EMAIL,
    FIXED_ADMIN_PASSWORD,
)
from gui import theme
from gui.main import card, labeled_entry, styled_button

REGISTERABLE_ROLES = [UserRole.LEARNER, UserRole.INSTRUCTOR, UserRole.ANALYST]


class LoginWindow:
    def __init__(
        self,
        root: tk.Tk,
        auth_service: AuthService,
        account_service: AccountService = None,
        on_success=None,
    ):
        self.root = root
        self.auth_service = auth_service
        self.account_service = account_service or AccountService(auth_service.user_repo)
        self.on_success = on_success
        self.mode = "login"  # or "register"
        self.remember_var = tk.BooleanVar(value=False)

        self.root.title("LearnGraph - Sign In")
        self.root.geometry("1000x700")
        self.root.configure(bg=theme.BG)
        self.root.minsize(900, 640)

        self._container = tk.Frame(self.root, bg=theme.BG)
        self._container.pack(fill="both", expand=True)
        self._render()

    # ------------------------------------------------------------------ #
    # Shell
    # ------------------------------------------------------------------ #
    def _render(self):
        for w in self._container.winfo_children():
            w.destroy()

        left = tk.Frame(self._container, bg=theme.PRIMARY, width=420)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        tk.Label(
            left, text="🎓", font=("Helvetica", 40), bg=theme.PRIMARY, fg="white"
        ).pack(pady=(90, 10))
        tk.Label(
            left,
            text="LearnGraph",
            font=("Helvetica", 26, "bold"),
            bg=theme.PRIMARY,
            fg="white",
        ).pack()
        tk.Label(
            left,
            text="Learning Management &\nPrerequisite Tracking Platform",
            font=theme.FONT_SUBTITLE,
            bg=theme.PRIMARY,
            fg="#E4E2FF",
            justify="center",
        ).pack(pady=(10, 30))
        tk.Label(
            left,
            text="Course catalogs, prerequisite graphs,\nlearning-path recommendations and\nlive analytics — in one place.",
            font=theme.FONT_BODY,
            bg=theme.PRIMARY,
            fg="#D9D6FF",
            justify="center",
        ).pack()

        right = tk.Frame(self._container, bg=theme.SURFACE)
        right.pack(side="left", fill="both", expand=True)

        canvas_holder = tk.Frame(right, bg=theme.SURFACE)
        canvas_holder.place(relx=0.5, rely=0.5, anchor="center")
        self.form = tk.Frame(canvas_holder, bg=theme.SURFACE)
        self.form.pack()

        if self.mode == "login":
            self._build_login_form()
        else:
            self._build_register_form()

        self.root.bind(
            "<Return>",
            lambda e: (
                self._handle_login()
                if self.mode == "login"
                else self._handle_register()
            ),
        )

    def _switch_mode(self, mode, prefill_email=""):
        self.mode = mode
        self._render()
        if mode == "login" and prefill_email:
            self.email_entry.insert(0, prefill_email)

    def _load_remembered_email(self):
        email = get_setting(KEY_REMEMBERED_EMAIL)
        if email:
            self.email_entry.delete(0, tk.END)
            self.email_entry.insert(0, email)
            self.remember_var.set(True)
        else:
            self.remember_var.set(False)

    def _open_forgot_password_dialog(self):
        ForgotPasswordDialog(self.root, self.account_service)

    # ------------------------------------------------------------------ #
    # Login form
    # ------------------------------------------------------------------ #
    def _build_login_form(self):
        form = self.form
        tk.Label(
            form,
            text="Welcome back",
            font=theme.FONT_TITLE,
            bg=theme.SURFACE,
            fg=theme.TEXT_PRIMARY,
        ).grid(row=0, column=0, sticky="w", pady=(0, 4))
        tk.Label(
            form,
            text="Sign in to continue to your dashboard",
            font=theme.FONT_SUBTITLE,
            bg=theme.SURFACE,
            fg=theme.TEXT_SECONDARY,
        ).grid(row=1, column=0, sticky="w", pady=(0, 24))

        tk.Label(
            form,
            text="Email",
            font=theme.FONT_BODY_BOLD,
            bg=theme.SURFACE,
            fg=theme.TEXT_PRIMARY,
        ).grid(row=2, column=0, sticky="w")
        self.email_entry = tk.Entry(
            form,
            font=theme.FONT_BODY,
            width=34,
            relief="solid",
            bd=1,
            highlightthickness=0,
        )
        self.email_entry.grid(row=3, column=0, sticky="we", pady=(4, 16), ipady=6)
        self._load_remembered_email()

        tk.Label(
            form,
            text="Password",
            font=theme.FONT_BODY_BOLD,
            bg=theme.SURFACE,
            fg=theme.TEXT_PRIMARY,
        ).grid(row=4, column=0, sticky="w")
        self.password_entry = tk.Entry(
            form,
            font=theme.FONT_BODY,
            width=34,
            show="•",
            relief="solid",
            bd=1,
            highlightthickness=0,
        )
        self.password_entry.grid(row=5, column=0, sticky="we", pady=(4, 6), ipady=6)

        remember_row = tk.Frame(form, bg=theme.SURFACE)
        remember_row.grid(row=6, column=0, sticky="w", pady=(0, 16))
        tk.Checkbutton(
            remember_row,
            text="Remember Me",
            variable=self.remember_var,
            bg=theme.SURFACE,
            fg=theme.TEXT_PRIMARY,
            selectcolor=theme.PRIMARY_LIGHT,
            font=theme.FONT_SMALL,
            activebackground=theme.SURFACE,
            borderwidth=0,
            highlightthickness=0,
            anchor="w",
        ).pack(side="left")

        self.error_label = tk.Label(
            form,
            text="",
            font=theme.FONT_SMALL,
            bg=theme.SURFACE,
            fg=theme.DANGER,
            wraplength=340,
            justify="left",
        )
        self.error_label.grid(row=7, column=0, sticky="w", pady=(0, 6))

        tk.Button(
            form,
            text="Sign In",
            font=theme.FONT_BUTTON,
            bg=theme.PRIMARY,
            fg="white",
            activebackground=theme.PRIMARY_DARK,
            activeforeground="white",
            relief="flat",
            cursor="hand2",
            command=self._handle_login,
        ).grid(row=8, column=0, sticky="we", ipady=8, pady=(8, 14))

        forgot_password = tk.Button(
            form,
            text="Forgot Password?",
            font=theme.FONT_SMALL,
            bg=theme.SURFACE,
            fg=theme.PRIMARY,
            relief="flat",
            cursor="hand2",
            bd=0,
            highlightthickness=0,
            activeforeground=theme.PRIMARY_DARK,
            activebackground=theme.SURFACE,
            command=self._open_forgot_password_dialog,
        )
        forgot_password.grid(row=9, column=0, sticky="w", pady=(0, 14))

        link_row = tk.Frame(form, bg=theme.SURFACE)
        link_row.grid(row=10, column=0, pady=(0, 14))
        tk.Label(
            link_row,
            text="New here?",
            font=theme.FONT_SMALL,
            bg=theme.SURFACE,
            fg=theme.TEXT_SECONDARY,
        ).pack(side="left", padx=(0, 6))
        tk.Button(
            link_row,
            text="Create an account  →",
            font=theme.FONT_SMALL,
            bg=theme.SURFACE,
            fg=theme.PRIMARY,
            relief="flat",
            cursor="hand2",
            bd=0,
            highlightthickness=0,
            activeforeground=theme.PRIMARY_DARK,
            activebackground=theme.SURFACE,
            command=lambda: self._switch_mode("register"),
        ).pack(side="left")

    def _handle_login(self):
        if self.mode != "login":
            return
        email = self.email_entry.get().strip()
        password = self.password_entry.get()
        if not email or not password:
            self.error_label.config(text="Enter both email and password")
            return
        try:
            user = self.auth_service.login(email, password)
        except AuthenticationError as e:
            self.error_label.config(text=str(e))
            return

        if self.remember_var.get():
            set_setting(KEY_REMEMBERED_EMAIL, email.lower())
        else:
            delete_setting(KEY_REMEMBERED_EMAIL)

        self.on_success(user)

    # ------------------------------------------------------------------ #
    # Register form
    # ------------------------------------------------------------------ #
    def _build_register_form(self):
        form = self.form
        tk.Button(
            form,
            text="←  Back to Sign In",
            font=theme.FONT_SMALL,
            bg=theme.SURFACE,
            fg=theme.PRIMARY,
            relief="flat",
            cursor="hand2",
            bd=0,
            highlightthickness=0,
            activeforeground=theme.PRIMARY_DARK,
            activebackground=theme.SURFACE,
            command=lambda: self._switch_mode("login"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))
        tk.Label(
            form,
            text="Create your account",
            font=theme.FONT_TITLE,
            bg=theme.SURFACE,
            fg=theme.TEXT_PRIMARY,
        ).grid(row=1, column=0, sticky="w", pady=(0, 4))
        tk.Label(
            form,
            text="Sign up as a Learner, Instructor, or Analyst",
            font=theme.FONT_SUBTITLE,
            bg=theme.SURFACE,
            fg=theme.TEXT_SECONDARY,
        ).grid(row=2, column=0, sticky="w", pady=(0, 18))

        tk.Label(
            form,
            text="Full Name",
            font=theme.FONT_BODY_BOLD,
            bg=theme.SURFACE,
            fg=theme.TEXT_PRIMARY,
        ).grid(row=3, column=0, sticky="w")
        self.reg_name = tk.Entry(
            form, font=theme.FONT_BODY, width=34, relief="solid", bd=1
        )
        self.reg_name.grid(row=4, column=0, sticky="we", pady=(4, 12), ipady=6)

        tk.Label(
            form,
            text="Email",
            font=theme.FONT_BODY_BOLD,
            bg=theme.SURFACE,
            fg=theme.TEXT_PRIMARY,
        ).grid(row=5, column=0, sticky="w")
        self.reg_email = tk.Entry(
            form, font=theme.FONT_BODY, width=34, relief="solid", bd=1
        )
        self.reg_email.grid(row=6, column=0, sticky="we", pady=(4, 12), ipady=6)

        tk.Label(
            form,
            text="Password",
            font=theme.FONT_BODY_BOLD,
            bg=theme.SURFACE,
            fg=theme.TEXT_PRIMARY,
        ).grid(row=7, column=0, sticky="w")
        self.reg_password = tk.Entry(
            form, font=theme.FONT_BODY, width=34, show="•", relief="solid", bd=1
        )
        self.reg_password.grid(row=8, column=0, sticky="we", pady=(4, 12), ipady=6)

        tk.Label(
            form,
            text="Confirm Password",
            font=theme.FONT_BODY_BOLD,
            bg=theme.SURFACE,
            fg=theme.TEXT_PRIMARY,
        ).grid(row=9, column=0, sticky="w")
        self.reg_confirm = tk.Entry(
            form, font=theme.FONT_BODY, width=34, show="•", relief="solid", bd=1
        )
        self.reg_confirm.grid(row=10, column=0, sticky="we", pady=(4, 12), ipady=6)

        tk.Label(
            form,
            text="Role",
            font=theme.FONT_BODY_BOLD,
            bg=theme.SURFACE,
            fg=theme.TEXT_PRIMARY,
        ).grid(row=11, column=0, sticky="w")
        self.reg_role = tk.StringVar(value=UserRole.LEARNER.value)
        role_row = tk.Frame(form, bg=theme.SURFACE)
        role_row.grid(row=12, column=0, sticky="w", pady=(4, 8))
        for role in REGISTERABLE_ROLES:
            tk.Radiobutton(
                role_row,
                text=role.value,
                variable=self.reg_role,
                value=role.value,
                bg=theme.SURFACE,
                fg=theme.TEXT_PRIMARY,
                selectcolor=theme.PRIMARY_LIGHT,
                font=theme.FONT_BODY,
                activebackground=theme.SURFACE,
            ).pack(side="left", padx=(0, 14))

        self.reg_error = tk.Label(
            form,
            text="",
            font=theme.FONT_SMALL,
            bg=theme.SURFACE,
            fg=theme.DANGER,
            wraplength=340,
            justify="left",
        )
        self.reg_error.grid(row=13, column=0, sticky="w", pady=(0, 6))

        tk.Button(
            form,
            text="Register",
            font=theme.FONT_BUTTON,
            bg=theme.PRIMARY,
            fg="white",
            activebackground=theme.PRIMARY_DARK,
            activeforeground="white",
            relief="flat",
            cursor="hand2",
            command=self._handle_register,
        ).grid(row=14, column=0, sticky="we", ipady=8, pady=(8, 14))

        link_row = tk.Frame(form, bg=theme.SURFACE)
        link_row.grid(row=15, column=0, pady=(0, 6))
        tk.Label(
            link_row,
            text="Already have an account?",
            font=theme.FONT_SMALL,
            bg=theme.SURFACE,
            fg=theme.TEXT_SECONDARY,
        ).pack(side="left", padx=(0, 6))
        tk.Button(
            link_row,
            text="Sign In",
            font=theme.FONT_SMALL,
            bg=theme.SURFACE,
            fg=theme.PRIMARY,
            relief="flat",
            cursor="hand2",
            bd=0,
            highlightthickness=0,
            activeforeground=theme.PRIMARY_DARK,
            activebackground=theme.SURFACE,
            command=lambda: self._switch_mode("login"),
        ).pack(side="left")

    def _handle_register(self):
        if self.mode != "register":
            return
        name = self.reg_name.get().strip()
        email = self.reg_email.get().strip()
        password = self.reg_password.get()
        confirm = self.reg_confirm.get()
        role_value = self.reg_role.get()

        if not name:
            self.reg_error.config(text="Full name is required")
            return
        if not email or "@" not in email:
            self.reg_error.config(text="Enter a valid email address")
            return
        if email.strip().lower() == FIXED_ADMIN_EMAIL:
            self.reg_error.config(
                text="This email is reserved for the administrator account"
            )
            return
        if not password or len(password) < 4:
            self.reg_error.config(text="Password must be at least 4 characters")
            return
        if password != confirm:
            self.reg_error.config(text="Passwords do not match")
            return

        try:
            role = UserRole(role_value)
            self.auth_service.register(name, email, password, role)
        except LMPTSError as e:
            self.reg_error.config(text=str(e))
            return

        messagebox.showinfo(
            "Account created", "Your account was created. Please sign in."
        )
        self._switch_mode("login", prefill_email=email.strip().lower())


class ForgotPasswordDialog:
    def __init__(self, parent, account_service: AccountService):
        self.account_service = account_service
        self.top = tk.Toplevel(parent)
        self.top.title("Forgot Password")
        self.top.configure(bg=theme.BG)
        self.top.transient(parent)
        self.top.grab_set()
        self.top.resizable(False, False)
        self.top.protocol("WM_DELETE_WINDOW", self._close)

        self.body = card(self.top, padx=20, pady=20)
        self.body.pack(padx=24, pady=24)

        self._build_email_step()

    def _build_email_step(self):
        for widget in self.body.winfo_children():
            widget.destroy()

        tk.Label(
            self.body,
            text="Reset your password",
            font=theme.FONT_TITLE,
            bg=theme.SURFACE,
            fg=theme.TEXT_PRIMARY,
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        tk.Label(
            self.body,
            text=(
                "Enter the email address for your Instructor, Learner, or Analyst "
                "account. If a matching account exists, you can reset the password."
            ),
            font=theme.FONT_BODY,
            bg=theme.SURFACE,
            fg=theme.TEXT_SECONDARY,
            wraplength=380,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(0, 16))

        self.email_entry = labeled_entry(self.body, "Email", row=2, width=42)

        styled_button(
            self.body,
            text="Continue",
            command=self._submit_email,
        ).grid(row=4, column=0, sticky="we", ipady=8, pady=(8, 0))

    def _build_reset_step(self, email: str):
        for widget in self.body.winfo_children():
            widget.destroy()

        tk.Label(
            self.body,
            text="Choose a new password",
            font=theme.FONT_TITLE,
            bg=theme.SURFACE,
            fg=theme.TEXT_PRIMARY,
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        tk.Label(
            self.body,
            text=f"Reset password for {email}",
            font=theme.FONT_BODY,
            bg=theme.SURFACE,
            fg=theme.TEXT_SECONDARY,
            wraplength=380,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(0, 16))

        self.new_password_entry = labeled_entry(
            self.body, "New Password", row=2, width=42, show="•"
        )
        self.confirm_password_entry = labeled_entry(
            self.body, "Confirm Password", row=4, width=42, show="•"
        )

        self.error_label = tk.Label(
            self.body,
            text="",
            font=theme.FONT_SMALL,
            bg=theme.SURFACE,
            fg=theme.DANGER,
            wraplength=380,
            justify="left",
        )
        self.error_label.grid(row=6, column=0, sticky="w", pady=(0, 8))

        styled_button(
            self.body,
            text="Reset Password",
            command=lambda: self._submit_reset(email),
        ).grid(row=7, column=0, sticky="we", ipady=8)

    def _submit_email(self):
        email = self.email_entry.get().strip()
        if not email or "@" not in email:
            messagebox.showerror("Invalid email", "Enter a valid email address")
            return

        normalized = email.lower()
        if normalized == FIXED_ADMIN_EMAIL:
            messagebox.showinfo(
                "Password reset unavailable",
                "The administrator account cannot be reset through this screen.",
            )
            return

        try:
            self.account_service.get_account_by_email(normalized)
        except UserNotFoundError:
            messagebox.showerror(
                "Password reset failed",
                "If an account exists for this email, you may reset it here.",
            )
            return

        self._build_reset_step(normalized)

    def _submit_reset(self, email: str):
        new_password = self.new_password_entry.get()
        confirm = self.confirm_password_entry.get()

        if not new_password or len(new_password) < 4:
            self.error_label.config(text="Password must be at least 4 characters")
            return
        if new_password != confirm:
            self.error_label.config(text="Passwords do not match")
            return

        try:
            self.account_service.reset_password(email, new_password)
        except (UserNotFoundError, LMPTSError) as exc:
            self.error_label.config(text=str(exc))
            return

        messagebox.showinfo(
            "Password reset",
            "Your password has been updated. Please sign in with your new password.",
        )
        self._close()

    def _close(self):
        try:
            self.top.grab_release()
        except Exception:
            pass
        self.top.destroy()
