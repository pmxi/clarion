"""Daily story digest: cluster a day's articles into stories.

The digest is built offline by `clarion digest build` and read by the
web UI. Heavy ML dependencies (torch, sentence-transformers) are only
imported inside the builder, never at package import time.
"""
