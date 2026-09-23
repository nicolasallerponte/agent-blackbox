# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Design document and architecture decision records 0001–0008.
- Project skeleton: package layout, quality tooling, CI/CD workflows,
  community files and agent tooling.
- Core recording engine: shadow git repository per project, workspace
  snapshots that never touch the user's git history, append-only session
  journals, per-project locking, and automatic recovery from processes killed
  mid-snapshot.
