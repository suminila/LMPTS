"""
Admin Learners Page: View, Create, Update, and Delete learners with full CRUD functionality.
"""

import tkinter as tk
from tkinter import ttk, messagebox

from services.admin_service import LearnerAdminService
from gui import theme


class AdminLearnersPage:
    """Admin page for managing learners."""

    def __init__(self, parent):
        self.parent = parent
        self.service = LearnerAdminService()
        self.current_learner = None  # Track currently edited learner

        self.frame = ttk.Frame(parent)
        self._build_ui()

    def _build_ui(self):
        """Build the UI layout."""
        # Title
        title = ttk.Label(
            self.frame, text="Learner Management", font=("Segoe UI", 16, "bold")
        )
        title.pack(pady=10)

        # Top section: Form for create/edit
        form_frame = ttk.LabelFrame(self.frame, text="Learner Details", padding=10)
        form_frame.pack(fill="both", padx=10, pady=5)

        # ID field (read-only for new, editable for existing)
        ttk.Label(form_frame, text="Learner ID:").grid(
            row=0, column=0, sticky="w", pady=5
        )
        self.id_var = tk.StringVar()
        self.id_entry = ttk.Entry(form_frame, textvariable=self.id_var, width=20)
        self.id_entry.grid(row=0, column=1, sticky="ew", padx=5)
        self.id_readonly_label = ttk.Label(
            form_frame, text="(Auto-generated)", foreground="gray"
        )
        self.id_readonly_label.grid(row=0, column=2, padx=5)

        # Name field
        ttk.Label(form_frame, text="Name:").grid(row=1, column=0, sticky="w", pady=5)
        self.name_var = tk.StringVar()
        self.name_entry = ttk.Entry(form_frame, textvariable=self.name_var, width=40)
        self.name_entry.grid(row=1, column=1, columnspan=2, sticky="ew", padx=5)

        # Email field
        ttk.Label(form_frame, text="Email:").grid(row=2, column=0, sticky="w", pady=5)
        self.email_var = tk.StringVar()
        self.email_entry = ttk.Entry(form_frame, textvariable=self.email_var, width=40)
        self.email_entry.grid(row=2, column=1, columnspan=2, sticky="ew", padx=5)

        # Error message area
        self.error_var = tk.StringVar()
        error_label = ttk.Label(
            form_frame, textvariable=self.error_var, foreground="red"
        )
        error_label.grid(row=3, column=0, columnspan=3, sticky="ew", pady=5)

        # Buttons
        button_frame = ttk.Frame(form_frame)
        button_frame.grid(row=4, column=0, columnspan=3, sticky="ew", pady=10)

        ttk.Button(button_frame, text="Create New", command=self._create_learner).pack(
            side="left", padx=5
        )
        ttk.Button(button_frame, text="Update", command=self._update_learner).pack(
            side="left", padx=5
        )
        ttk.Button(button_frame, text="Clear", command=self._clear_form).pack(
            side="left", padx=5
        )

        form_frame.columnconfigure(1, weight=1)

        # Bottom section: Learner list
        list_frame = ttk.LabelFrame(self.frame, text="All Learners", padding=10)
        list_frame.pack(fill="both", expand=True, padx=10, pady=5)

        # Treeview columns
        columns = ("ID", "Name", "Email", "Registered")
        self.tree = ttk.Treeview(
            list_frame, columns=columns, height=15, show="headings"
        )

        self.tree.column("ID", width=80)
        self.tree.column("Name", width=150)
        self.tree.column("Email", width=200)
        self.tree.column("Registered", width=150)

        self.tree.heading("ID", text="Learner ID")
        self.tree.heading("Name", text="Name")
        self.tree.heading("Email", text="Email")
        self.tree.heading("Registered", text="Registered")

        # Scrollbar
        scrollbar = ttk.Scrollbar(
            list_frame, orient="vertical", command=self.tree.yview
        )
        self.tree.configure(yscroll=scrollbar.set)

        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Bind selection
        self.tree.bind("<<TreeviewSelect>>", self._on_select_learner)

        # Action buttons for list
        action_frame = ttk.Frame(self.frame)
        action_frame.pack(fill="x", padx=10, pady=5)

        ttk.Button(
            action_frame, text="Delete Selected", command=self._delete_learner
        ).pack(side="left", padx=5)
        ttk.Button(action_frame, text="Refresh", command=self.load_learners).pack(
            side="left", padx=5
        )

        # Load initial data
        self.load_learners()

    def load_learners(self):
        """Load and display all learners."""
        # Clear existing items
        for item in self.tree.get_children():
            self.tree.delete(item)

        # Load learners
        learners = self.service.list_all_learners()
        for learner in learners:
            self.tree.insert(
                "",
                "end",
                values=(
                    learner["learner_id"],
                    learner["name"],
                    learner["email"],
                    (
                        learner.get("date_registered", "")[:10]
                        if learner.get("date_registered")
                        else ""
                    ),
                ),
            )

    def _on_select_learner(self, event):
        """Handle learner selection in list."""
        selection = self.tree.selection()
        if not selection:
            return

        item = selection[0]
        values = self.tree.item(item)["values"]
        learner_id = values[0]

        # Load learner details
        learners = self.service.list_all_learners()
        for learner in learners:
            if learner["learner_id"] == learner_id:
                self.current_learner = learner
                self.id_var.set(learner["learner_id"])
                self.name_var.set(learner["name"])
                self.email_var.set(learner["email"])
                self.id_entry.config(state="normal")  # Allow ID editing
                self.id_readonly_label.config(text="(Click to change ID)")
                self.error_var.set("")
                break

    def _clear_form(self):
        """Clear the form for new entry."""
        self.current_learner = None
        self.id_var.set("")
        self.name_var.set("")
        self.email_var.set("")
        self.id_entry.config(state="disabled")  # Read-only for new
        self.id_readonly_label.config(text="(Auto-generated)")
        self.error_var.set("")
        self.tree.selection_remove(self.tree.selection())

    def _create_learner(self):
        """Create a new learner."""
        name = self.name_var.get().strip()
        email = self.email_var.get().strip()

        if self.current_learner:
            self.error_var.set("Clear form first to create new learner")
            return

        success, message, learner_id = self.service.create_learner(name, email)

        if success:
            self.error_var.set("")
            messagebox.showinfo("Success", f"Learner created with ID: {learner_id}")
            self._clear_form()
            self.load_learners()
        else:
            self.error_var.set(message)

    def _update_learner(self):
        """Update current learner."""
        if not self.current_learner:
            self.error_var.set("Select a learner to update")
            return

        name = self.name_var.get().strip()
        email = self.email_var.get().strip()
        new_id = self.id_var.get().strip()

        # Check if ID changed
        if new_id != self.current_learner["learner_id"]:
            # Confirm ID change
            if not messagebox.askyesno(
                "Confirm ID Change",
                f"Change ID from {self.current_learner['learner_id']} to {new_id}?\n"
                "This will update all enrollments and accounts.",
            ):
                return

            success, message = self.service.change_learner_id(
                self.current_learner["learner_id"], new_id
            )

            if not success:
                self.error_var.set(message)
                return

        # Update other fields
        success, message = self.service.update_learner(new_id, name, email)

        if success:
            self.error_var.set("")
            messagebox.showinfo("Success", "Learner updated successfully")
            self._clear_form()
            self.load_learners()
        else:
            self.error_var.set(message)

    def _delete_learner(self):
        """Delete selected learner."""
        selection = self.tree.selection()
        if not selection:
            self.error_var.set("Select a learner to delete")
            return

        item = selection[0]
        values = self.tree.item(item)["values"]
        learner_id = values[0]
        name = values[1]

        # Confirm deletion
        if not messagebox.askyesno(
            "Confirm Delete",
            f"Delete learner '{name}' ({learner_id})?\n"
            "This will also delete all enrollments and accounts.",
        ):
            return

        success, message = self.service.delete_learner(learner_id)

        if success:
            self.error_var.set("")
            messagebox.showinfo("Success", "Learner deleted successfully")
            self._clear_form()
            self.load_learners()
        else:
            messagebox.showerror("Error", message)

    def get_frame(self) -> ttk.Frame:
        """Return the page frame."""
        return self.frame
