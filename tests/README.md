# Tests

`tests/run.sh` checks the shipped run loop: the supervisor, the usage governor, the model guard, the worker assembler, the site generator, and the hiring-round check. It works in a throwaway copy of the repository with a stand-in `claude` (`fake_claude.py`) and a stand-in `gh` (`fake_gh.sh`), so it never contacts Anthropic or GitHub and spends no usage.

```bash
tests/run.sh
```

Run it after changing anything in `tools/`, `rules/`, or `.claude/settings.json`. A change that breaks a test either has a reason, written in `log/optimizations.md` or noted for the Investors in the next report, or gets fixed (Commandment 3).
