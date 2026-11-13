# 01 – Restart from main (2026-11-11)

- The professor's assessment (Team D, 47/100 provisional) graded `main`. Our earlier OS1 work
  lived on a local branch `project/os1` that was never merged, so it was not seen.
- In the meantime the team reorganised `main`: one self-contained folder per team
  (`OS1/` … `OS5/`), with the same sub-folders (`config`, `src/edge`, `tests`, `scripts`, …).
  `OS5/` is the full project; `OS1/`–`OS4/` were empty skeletons.
- Decision: drop `project/os1`, start again from `main`, follow its layout, and only do
  Estève's tasks from the Contribution Board: OS1-3, OS1-4, OS1-5.
- The old work is kept: branch `project/os1`, and the untracked `OS1/` files in
  `git stash` ("OS1 work from project/os1 …"). Ideas were reused, not the layout.
- New work branch: `feature/os1` (from `main` at `2c6954c`).
