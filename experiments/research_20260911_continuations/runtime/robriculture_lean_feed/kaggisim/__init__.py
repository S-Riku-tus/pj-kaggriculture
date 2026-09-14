"""robriculture shared library.

Everything a submitted agent needs at evaluation time lives here and gets
bundled into the submission tarball. No network access is available during
evaluation, so keep this package fully self-contained (stdlib only; numpy is
allowed since it ships in Kaggle's runtime).
"""
