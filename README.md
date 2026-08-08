# claude-plugins

Claude Code plugins by CrashLoop, served as a marketplace.

## Install

From inside Claude Code:

```
/plugin marketplace add crashloop/claude-plugins
/plugin install <plugin>@crashloop-plugins
```

Or `/plugin` alone to browse and install from the menu.

From a shell:

```sh
claude plugin marketplace add crashloop/claude-plugins
claude plugin install <plugin>@crashloop-plugins
```

Restart Claude Code afterwards; hooks load at session start.

## Plugins

| Plugin | What it does |
|--------|--------------|
| [creed](creed/) | Keeps a working discipline present and enforced: injects a compressed operating core every prompt (and after context compaction), gates done/fixed/passing claims that ran no command, and blocks git commands that stage secret-shaped files. |

**hoolint** moved to its own repository: <https://gitlab.com/packetwise/hoolint>.
Install it from there with `/plugin marketplace add https://gitlab.com/packetwise/hoolint.git`.
`tools/judge-proxy` stayed here; it exercises hoolint's `local_llm` stage.

## Enable / disable

```sh
claude plugin disable <plugin>@crashloop-plugins
claude plugin enable  <plugin>@crashloop-plugins
```

## Updating

Installs are pinned to a git commit; local edits change nothing until pushed and refreshed:

```
git push
/plugin marketplace update crashloop-plugins
/reload-plugins
```
