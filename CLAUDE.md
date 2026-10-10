@AGENTS.md

## Claude Code–specific notes

The shared rules live in `AGENTS.md` (imported above). Put only Claude-only guidance here.

- **Use the superpowers skills workflow:**
  - `brainstorming` before building a new feature.
  - `writing-plans` for multi-step work.
  - `test-driven-development` for the deterministic core.
  - `systematic-debugging` for failures.
  - `verification-before-completion` before claiming anything is done.
- Use `frontend-design` / `ui-ux-pro-max` for workspace UI work. Use `playwright-skill` to check the end-to-end demo flow in a browser.
- The app's LLM is **OpenAI**, not Claude. Do not swap in the Anthropic SDK, and ignore Claude-API defaults when writing app code.
- The Entire hooks in `.claude/settings.json` run on every session. Leave them alone, even if they print warnings.
