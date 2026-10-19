---
name: hack-intake-idea
description: Use when someone points to an idea in ideas/<name> or on a branch idea/<name> and wants it in the main app. Reads it, summarises it in five lines and opens the smallest pull request that merges it into app/.
---

# Bring an idea into the main app

1. Read the idea. Run `git fetch origin`, then read `ideas/<name>/` on branch `idea/<name>` without checking out another person's branch.
2. Reply in five lines or fewer: what it does, which files in `app/` it touches, what could break, and the smallest merge that shows it working.
3. Work on a new branch `merge/<name>` from the default branch. Copy in only what the demo needs.
4. Run the `hack-ship-check` skill.
5. Open a pull request. Put a before and after screenshot in the description.
6. Ask one question only when a person has to choose. Otherwise decide and state the assumption in one line.
