# Project instructions

Paste the text below into Project settings > Memory > Project instructions in the Claude project.

```text
Goal: a live, working demo at the final. Working beats clean.

1. Ship the smallest version that shows the idea, push it, then improve it.
2. Reply with the result first, in five lines or fewer, plus a screenshot or preview. No long plans.
3. Cloud threads work on a branch and open a pull request. The driver squash-merges it without a review once the screenshot looks right. People who touch only their own ideas/<name>/ folder may push straight to main. Main must always run. Never force-push main.
4. Stay inside your task's folder. Ideas live in ideas/<name>/ and the product lives in app/.
5. Commit and push every 15 minutes, because a cloud VM can be lost.
6. Never commit secrets. Ask the driver before adding a paid service.
7. Use the built-in GitHub tools for pull requests. gh pr and gh issue fail with a 403 in cloud threads.

When a message says "branch idea/<name>, folder ideas/<name>", follow the hack-intake-idea skill. Before saying anything is done, follow the hack-ship-check skill.

Think about the product before the code. Name the one risk you are still guessing at (does anyone want this, can a user work it, can we build it, can we run it live) and pick the cheapest test for it. Building is the last test, not the first. Done means the demo moment works in front of a judge in the first 30 seconds, not that the feature shipped.
```
