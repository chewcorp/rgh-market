<!-- kitchen-cook-block v1 (source: chewcorp/kitchen docs/cook-block.md; copy verbatim) -->

## Cook rules

- Post your plan, then keep building in the same session. Do not wait for a
  "go". Exception: where this repo's AGENTS.md or plan skill requires human
  sign-off for a change's tier, wait for that sign-off on that change only.
- If something blocks you, comment on the PR (or the Linear card if there is no
  PR yet). Say what blocks you, the options, and which one you recommend. Then
  carry on with every part that is not blocked. Never end a session on a
  question you only asked yourself.
- Answer every review finding on the GitHub PR, as a reply in its thread. Linear
  gets one line at most.
- Resolve a thread only when you fixed what it raised. To decline, reply with
  the reason and leave the thread unresolved.
- Bot review cap: at most 3 push rounds that answer bot findings. After round 3,
  stop pushing, and reply to any new bot finding that it is held for a human
  reviewer. Comments from a human reviewer are always acted on and don't count
  toward the cap.
- Do not merge.
- If this repo's AGENTS.md lacks the marker line above, first open a separate PR
  that adds this block verbatim, then branch the story from that PR.

<!-- /kitchen-cook-block -->
