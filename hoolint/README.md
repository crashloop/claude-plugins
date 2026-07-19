# hoolint

A Claude Code plugin that installs hooks to check code and documentation.

Name: **hoolint** = hook + lint.

## Purpose

Ship a set of hooks that run automatically during a Claude Code session and
check what gets written:

- **Code** — lint, format, and static-analysis checks on edited files.
- **Documentation** — checks on markdown and docstrings (staleness, broken
  links, missing or out-of-date sections).

Hooks enforce the checks at the harness level, so they fire whether or not the
model remembers to run them.

## Status

Purpose only. No scaffold yet.
