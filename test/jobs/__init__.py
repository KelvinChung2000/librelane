# This file is load-bearing, despite being empty.
#
# There are two modules named test_job.py: this package's, which tests
# librelane.jobs.Job, and test/engine/test_job.py, which tests the resolved
# job type. pytest imports a test module under a package-qualified name only
# when its directory is a package, so this __init__.py is what makes the two
# collect as test.jobs.test_job and test_job rather than colliding.
#
# test/engine/ deliberately has no __init__.py. Adding one gives both modules
# the bare name test_job and pytest aborts collection with an
# import-file-mismatch error. If you need test/engine to be a package, rename
# one of the two modules in the same change.
