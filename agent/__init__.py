"""The agent's self-modification target.

Everything the self-improvement loop is allowed to edit lives under this package:
``solutions.py`` (the code being optimised) and ``benchmarks/`` (the self-authored,
versioned benchmark suite that scores it). The loop is scope-locked to this folder.
"""
