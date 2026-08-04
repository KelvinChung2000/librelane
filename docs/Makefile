# Minimal makefile for Sphinx documentation
#

# You can set these variables from the command line, and also
# from the environment for the first two.
SPHINXOPTS    ?=
SPHINXBUILD   ?= sphinx-build
SOURCEDIR     = source
BUILDDIR      = build

# Put it first so that "make" without argument is like "make help".
help:
	@$(SPHINXBUILD) -M help "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)

.PHONY: help Makefile

# Catch-all target: route all unknown targets to Sphinx using the new
# "make mode" option.  $(O) is meant as a shortcut for $(SPHINXOPTS).
#
# The output used to be piped through `grep -v duplicate` and an `egrep -v` for
# "local id not found in doc 'reference/*_config_vars'", which between them hid
# 184 warnings the build really was emitting. Both causes are fixed -- the
# duplicate glossary term is gone, and the generated flow pages address a step
# by its MyST target rather than by a fragment on a path -- so the build is
# warning-clean and the filters have nothing left to hide but the next real
# warning. Removing them also restores the exit status: a pipeline reports
# grep's result, so a failing sphinx-build was reported as a success.
%: Makefile
	@$(SPHINXBUILD) -M $@ "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)
