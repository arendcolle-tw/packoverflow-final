# Project instructions

Paste the text below into Project settings > Memory > Project instructions in the Claude project.

```text
Goal: a live, working demo at the final. Working beats clean.

1. Ship the smallest version that shows the idea, push it, then improve it.
2. Reply with the result first, in five lines or fewer, plus a screenshot or preview. No long plans.
3. Work on a branch and open a pull request. Main must always run. Never force-push main.
4. Stay inside your task's folder. Ideas live in ideas/<name>/ and the product lives in app/.
5. Commit and push every 15 minutes, because a cloud VM can be lost.
6. Never commit secrets. Ask the driver before adding a paid service.
7. Use the built-in GitHub tools for pull requests. gh pr and gh issue fail with a 403 in cloud threads.

When a message says "branch idea/<name>, folder ideas/<name>", follow the hack-intake-idea skill. Before saying anything is done, follow the hack-ship-check skill.

Think about the product first. Who is this for, what is the moment that impresses, and what does a judge see in the first 30 seconds?
```
