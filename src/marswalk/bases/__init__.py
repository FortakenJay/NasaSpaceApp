"""Bases: places on Mars the crew works from. Gale is built in; others are created from the HiRISE catalog.

registry  which Bases exist, which one is in focus, deleting them (files + database rows through db.repo)
jobs      the background job that finds and downloads a new Base's data, with progress and cancel
tomlw     writes a Base's generated site config (the standard library only reads TOML)
"""
