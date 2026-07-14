from pathlib import Path

path = Path(r"c:/Users/sumithra.m/Documents/learn_graph_project/gui/main.py")
text = path.read_text(encoding="utf-8")
start_marker = (
    "    def _open_mark_completed_dialog(self, learner_id: str, course_code: str):"
)
end_marker = "    def _next_level_courses(self, learner_id: str, course_code: str):"
start = text.index(start_marker)
end = text.index(end_marker)
new_block = """    def _open_mark_completed_dialog(self, learner_id: str, course_code: str):
        assignment_service = self.services.get("assignment")
        if assignment_service is None:
            self._error("Level grading is unavailable right now")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title(f"Submit Level Score - {learner_id} / {course_code}")
        dialog.configure(bg=theme.SURFACE)
        dialog.geometry("360x280")
        dialog.transient(self.root)
        dialog.grab_set()

        form = tk.Frame(dialog, bg=theme.SURFACE)
        form.pack(fill="both", expand=True, padx=20, pady=20)
        tk.Label(
            form,
            text=f"{learner_id} — {course_code}",
            font=theme.FONT_HEADING,
            bg=theme.SURFACE,
            fg=theme.TEXT_PRIMARY,
        ).pack(anchor="w", pady=(0, 10))

        try:
            progress = assignment_service.get_progress(learner_id, course_code)
            assignment_title = progress.get("current_assignment") or "Current level"
            level_label = f"Level {progress['current_level']}/{progress['total_levels']}"
            cutoff_label = f"Passing cutoff: {progress['cutoff']}%"
        except LMPTSError:
            assignment_title = "Current level"
            level_label = "Level 1/1"
            cutoff_label = "Passing cutoff: 65%"

        tk.Label(
            form,
            text=assignment_title,
            font=theme.FONT_BODY_BOLD,
            bg=theme.SURFACE,
        ).pack(anchor="w")
        tk.Label(
            form,
            text=level_label,
            font=theme.FONT_SMALL,
            bg=theme.SURFACE,
            fg=theme.TEXT_SECONDARY,
        ).pack(anchor="w", pady=(0, 4))
        tk.Label(
            form,
            text=cutoff_label,
            font=theme.FONT_SMALL,
            bg=theme.SURFACE,
            fg=theme.TEXT_SECONDARY,
        ).pack(anchor="w", pady=(0, 4))

        score_var = tk.StringVar(value="")
        entry = tk.Entry(
            form,
            textvariable=score_var,
            font=("Helvetica", 16),
            relief="solid",
            bd=1,
            width=12,
        )
        entry.pack(anchor="w", pady=(8, 6), ipady=4)
        tk.Label(
            form,
            text="Enter a percentage from 0 to 100",
            font=theme.FONT_SMALL,
            bg=theme.SURFACE,
            fg=theme.TEXT_SECONDARY,
        ).pack(anchor="w")

        error_label = tk.Label(
            form, text="", font=theme.FONT_SMALL, bg=theme.SURFACE, fg=theme.DANGER
        )
        error_label.pack(anchor="w", pady=(6, 0))

        def do_save():
            raw_value = score_var.get().strip()
            try:
                score = float(raw_value)
            except ValueError:
                error_label.config(text="Enter a valid number")
                return
            if not 0 <= score <= 100:
                error_label.config(text="Score must be between 0 and 100")
                return
            try:
                result = assignment_service.submit_grade(learner_id, course_code, score)
                dialog.destroy()
                if result["status"] == "Completed":
                    self._info(f"{learner_id} completed {course_code} with {score}%")
                else:
                    self._info(
                        f"Score saved for {course_code}: {score}%. Current level "
                        f"{result['current_level']}/{result['total_levels']}"
                    )
                self._refresh_current_page()
                self._open_progression_dialog(
                    learner_id, course_code, score, result["status"] == "Completed"
                )
            except LMPTSError as e:
                error_label.config(text=str(e))

        btn_row = tk.Frame(form, bg=theme.SURFACE)
        btn_row.pack(fill="x", pady=(12, 0))
        styled_button(btn_row, "Save", do_save).pack(
            side="left", expand=True, fill="x", ipady=6, padx=(0, 6)
        )
        styled_button(
            btn_row, "Cancel", dialog.destroy, bg=theme.SURFACE, fg=theme.TEXT_PRIMARY
        ).pack(side="left", expand=True, fill="x", ipady=6)

"""
path.write_text(text[:start] + new_block + text[end:], encoding="utf-8")
print("updated", path)
