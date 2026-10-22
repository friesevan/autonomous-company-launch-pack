#!/usr/bin/env python3
"""PreToolUse hook for Bash and Monitor: refuse commands that weaken the Mac's security or reach
around the company's own guards, and log every sudo command (Commandment 2).

The company has administrator rights without a password, so this guards against accidents and
confused sessions; it is not a lock. Behind it: the supervisor restores Investor-owned files
after every session (rules/file-guard.sh), checks the security settings every tick
(rules/posture.sh), and the watchdog on GitHub notices a Mac that stopped.

Exit 2 refuses the call and shows the reason to the session. Anything unexpected (unreadable
input, a command it can't parse) falls back to the plain patterns and otherwise allows the call.

Investors own this file.
"""
import datetime as dt
import json
import os
import re
import shlex
import sys

ROOT = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOME = os.path.normpath(os.environ.get("HOME") or os.path.expanduser("~"))

# Commands that weaken security, whoever runs them, with sudo or without.
RULES = [
    (r"socketfilterfw\b.*--set(globalstate|stealthmode|blockall)\s+off", "turns off the firewall"),
    (r"\bpfctl\b(.*\s)?-[a-zA-Z]*[dF]\b", "turns off or flushes the packet filter"),
    (r"\bfdesetup\s+(disable|remove|removerecovery)\b", "turns off FileVault"),
    (r"\bspctl\b.*--(master-disable|global-disable|disable)\b", "turns off Gatekeeper"),
    (r"\bcsrutil\s+(disable|clear|authenticated-root)", "changes System Integrity Protection"),
    (r"\bsoftwareupdate\b.*--schedule\s+off", "turns off automatic updates"),
    (r"\bdefaults\s+write\s+\S*(SoftwareUpdate|commerce)\S*\s+\S*(AutomaticCheckEnabled|AutomaticDownload|"
     r"CriticalUpdateInstall|ConfigDataInstall|AutoUpdate)\S*\s+(-bool\s+|-int\s+)?(false|no|0)\b",
     "turns off automatic security updates"),
    (r"\bsystemsetup\b.*-set(remotelogin|remoteappleevents|wakeonnetworkaccess)\b", "changes Remote Login or remote access"),
    (r"\blaunchctl\b.*(com\.openssh\.sshd|com\.apple\.screensharing|com\.apple\.RemoteDesktop)", "changes SSH or Screen Sharing"),
    (r"ARDAgent\.app\S*kickstart|(^|[;&|(]\s*)(sudo\s+)?kickstart\s+-", "changes Remote Management"),
    (r"\b(dscl|dseditgroup|sysadminctl|createhomedir)\b", "changes users or the admin group"),
    (r"\bvisudo\b|/etc/sudoers|/etc/pam\.d|\bsecurity\s+authorizationdb\b", "changes sudo, PAM, or the authorization database"),
    (r"(^|[;&|(]\s*)(sudo\s+)?(nvram|bless)\b|\bprofiles\s+(install|remove|-I|-R)\b",
     "changes firmware, boot, or configuration profiles"),
    (r"TCC\.db|\btccutil\b", "changes privacy permissions"),
    (r"\bxattr\b.*com\.apple\.quarantine|\bxattr\s+(-\w+\s+)*-\w*c", "removes quarantine flags (a Gatekeeper bypass)"),
    (r"\bsudo\s+(-[a-zA-Z]*[si]\b|su\b|(-u\s+root\s+)?(ba|z|c|k|tc|da|fi)?sh\b)|(^|[;&|(]\s*)su(\s+-|\s+root\b|\s*$)",
     "opens a root shell"),
    (r"\bsecurity\s+(find-generic-password|find-internet-password|dump-keychain|export|delete-generic-password|"
     r"delete-internet-password|add-generic-password|set-generic-password-partition-list)\b", "reads or changes Keychain secrets"),
    (r"(^|[;&|(`]\s*|\$\(\s*)((sudo|nohup|env|caffeinate|command|exec|time|nice|xargs)(\s+-\S+)*\s+|[A-Za-z_]\w*=\S*\s+)*"
     r"(\S*/)?claude\s+((\S+\s+)*)(-p|--print)\b", "starts another Claude session outside the governor"),
    (r"\bgit\s+clean\b[^;&|]*\s-[a-zA-Z]*[xX]", "deletes ignored files, including the supervisor's own state"),
    (r"(^|[;&|(]\s*)(\S*/)?claude\s+(setup-token|auth\s+login|auth\s+logout|config\s+set|mcp\s+add|mcp\s+add-json|"
     r"plugin\s+install|plugins\s+install)\b",
     "changes Claude Code's login, settings, MCP servers, or plugins (an MCP server or plugin runs code outside the hooks)"),
    (r"api\.anthropic\.com", "calls the Anthropic API directly"),
]
# Only in the sessions the supervisor starts (COMPANY_RUN=1), which sync through the supervisor.
COMPANY_RULES = [
    (r"(^|[;&|(]\s*)(\S+=\S*\s+)*git\s+(-C\s+\S+\s+|-\S+\s+)*(pull|merge|rebase)(\s|$)",
     "brings GitHub's changes in during a session. The supervisor syncs between sessions: commit your work, "
     "and if a push is rejected, leave it; the supervisor pushes after the session"),
]
# The Investors' files, and the Claude Code files that change how sessions behave. The rest of
# .claude/, such as the workers' memories in .claude/agent-memory/, is the company's.
PROTECTED_DIRS = ("setup", "rules", "investors", ".github", os.path.join(".claude", "agents"),
                  os.path.join(".claude", "commands"), os.path.join(".claude", "rules"), os.path.join(".claude", "hooks"),
                  os.path.join(".claude", "output-styles"))
PROTECTED_FILES = ("CLAUDE.md", "CLAUDE.local.md", ".mcp.json", os.path.join(".claude", "settings.json"),
                   os.path.join(".claude", "settings.local.json"), os.path.join(".claude", "CLAUDE.md"))
HOME_PROTECTED = (os.path.join(HOME, ".claude", "settings.json"), os.path.join(HOME, ".claude", "settings.local.json"),
                  os.path.join(HOME, ".claude.json"), os.path.join(HOME, "Library", "LaunchAgents"))
SYSTEM_PROTECTED = ("/etc/sudoers", "/etc/pam.d", "/Library/Application Support/ClaudeCode")
ALL_ARGS = {"rm", "rmdir", "unlink", "shred", "mv", "chmod", "chown", "chflags", "chgrp", "ln", "truncate", "touch"}
LAST_ARG = {"cp", "install", "rsync", "ditto"}
GIT_WRITES = {"checkout", "restore", "rm", "mv", "apply", "am", "clean"}
WRAPPERS = {"sudo", "command", "exec", "nohup", "time", "env", "xargs", "nice", "caffeinate"}


def refuse(reason):
    print(f"Blocked by security-guard: this command {reason}. The company never weakens the Mac's security or "
          "changes the Investors' files and settings (Commandment 2). If the work truly needs it, ask the "
          "Investors in the next report's questions.", file=sys.stderr)
    sys.exit(2)


def expand(path):
    """$VARS and a leading ~, both from the same HOME the protected paths use."""
    p = os.path.expandvars(path)
    return HOME + p[1:] if p == "~" or p.startswith("~/") else p


def protected(path, cwd, deletes=False):
    """Whether the path is one the company never changes. With deletes, the company folder itself and
    every folder that holds it or a protected home file count too, so `rm -rf ~` is refused."""
    if not path or path.startswith("-") or path in (">", ">>", "|", "&", ";"):
        return False
    p = expand(path.strip("'\""))
    p = os.path.normpath(p if os.path.isabs(p) else os.path.join(cwd, p))
    root = os.path.normpath(ROOT)
    if deletes and any(h == p or h.startswith(p.rstrip(os.sep) + os.sep) for h in (root,) + HOME_PROTECTED):
        return True
    if p == root:
        return False
    if p.startswith(root + os.sep):
        rel = p[len(root) + 1:]
        return rel in PROTECTED_FILES or any(rel == d or rel.startswith(d + os.sep) for d in PROTECTED_DIRS)
    return any(p == h or p.startswith(h + os.sep) for h in HOME_PROTECTED + SYSTEM_PROTECTED)


def simple_commands(tokens):
    cmd = []
    for t in tokens:
        if t and set(t) <= set(";&|()"):
            if cmd:
                yield cmd
            cmd = []
        else:
            cmd.append(t)
    if cmd:
        yield cmd


def write_targets(command, cwd):
    """(path, directories, deletes) for every path a command writes, deletes, moves, or changes, as far
    as plain shell parsing can tell. Each path is checked against every directory the command has
    been in, so `cd rules && rm x` and `(cd /tmp); rm CLAUDE.md` are both caught."""
    lex = shlex.shlex(command, posix=True, punctuation_chars=";&|<>()")
    lex.whitespace_split = True
    dirs, found = [cwd], []
    for argv in simple_commands(list(lex)):
        targets = [argv[i + 1] for i, t in enumerate(argv[:-1]) if t in (">", ">>", ">|", "&>", "&>>")]
        argv = [a for a in argv if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", a)]
        if argv and argv[0] in ("cd", "pushd"):
            dest = expand(argv[1] if len(argv) > 1 else "~")
            dirs.append(os.path.normpath(dest if os.path.isabs(dest) else os.path.join(dirs[-1], dest)))
            continue
        while argv and os.path.basename(argv[0]) in WRAPPERS:
            argv = argv[1:]
            while argv and argv[0].startswith("-"):
                argv = argv[1:]
        found += [(t, tuple(dirs), False) for t in targets]
        if not argv:
            continue
        name, args = os.path.basename(argv[0]), [a for a in argv[1:] if a not in (">", ">>", "<", "<<")]
        plain = [a for a in args if not a.startswith("-")]
        targets, deletes = [], name in ("rm", "rmdir", "unlink", "shred", "mv")
        if name in ALL_ARGS:
            targets = plain
        elif name in LAST_ARG and plain:
            targets = plain[-1:]
        elif name == "tee":
            targets = plain
        elif name in ("sed", "perl", "gsed") and any(a.startswith("-i") or a == "--in-place" or (a.startswith("-") and "i" in a[1:] and not a.startswith("--")) for a in args):
            targets = plain[1:] if name != "perl" else plain
        elif name == "git":
            i, here = 0, [""]
            while i < len(args) and args[i].startswith("-"):   # global options, such as -C <dir>
                if args[i] in ("-C", "-c") and i + 1 < len(args):
                    if args[i] == "-C":
                        here.append(args[i + 1])
                    i += 1
                i += 1
            if i < len(args) and args[i] in GIT_WRITES:
                deletes = args[i] in ("rm", "mv", "clean")
                targets = [os.path.join(h, a) if h else a for h in here for a in args[i + 1:] if not a.startswith("-")]
        elif name in ("dd",):
            targets = [a[3:] for a in args if a.startswith("of=")]
        moved_to = targets[-1] if deletes and len(targets) > 1 and "mv" in (name, args[0] if args else "") else None
        found += [(t, tuple(dirs), deletes and t is not moved_to) for t in targets]
    return found


def log_sudo(command):
    try:
        os.makedirs(os.path.join(ROOT, "log"), exist_ok=True)
        with open(os.path.join(ROOT, "log", "sudo.log"), "a", encoding="utf-8") as f:
            f.write(f"{dt.datetime.now().astimezone().isoformat(timespec='seconds')} {command[:2000]}\n")
    except OSError:
        pass


def main():
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return
    tool_input = event.get("tool_input") or {}
    command = str(tool_input.get("command") or tool_input.get("cmd") or "")
    if not command.strip():
        return
    cwd = event.get("cwd") or ROOT
    one_line = " ".join(command.split())
    if re.search(r"(^|[;&|(`]\s*|\$\(\s*)sudo\b", command):
        log_sudo(one_line)
    for pattern, reason in RULES + (COMPANY_RULES if os.environ.get("COMPANY_RUN") == "1" else []):
        if re.search(pattern, command, re.I if "TCC" not in pattern else 0):
            refuse(reason)
    try:
        targets = write_targets(command, cwd)
    except ValueError:
        targets = [(t, (cwd,), False) for t in re.findall(r">>?\s*(\S+)", command)]
    for t, dirs, deletes in targets:
        if any(protected(t, d, deletes) for d in dirs):
            refuse(f"writes, moves, or deletes {t}, which only the Investors change")


if __name__ == "__main__":
    main()
