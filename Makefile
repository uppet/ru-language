.PHONY: test test-emacs examples examples-js clean
EMACS ?= emacs
test:
	python3 -m unittest discover -s tests -v
examples:
	python3 ru build examples/optional_parameters.ru -o bin/optional_parameters --emit-c dist/optional_parameters.c
	python3 ru build examples/procedure_finish.ru -o bin/procedure_finish --emit-c dist/procedure_finish.c
	python3 ru build examples/anonymous.ru -o bin/anonymous --emit-c dist/anonymous.c
	python3 ru build examples/hello.ru -o bin/hello --emit-c dist/hello.c
	python3 ru build examples/add.ru -o bin/add
	python3 ru build examples/square.ru -o bin/square --emit-c dist/square.c
	python3 ru build examples/positional.ru -o bin/positional
	python3 ru build examples/ceremony.ru -o bin/ceremony
	python3 ru build examples/conversation.ru -o bin/conversation
	python3 ru build examples/factorial.ru -o bin/factorial --emit-c dist/factorial.c
	python3 ru build examples/linked_pairs.ru -o bin/linked_pairs
	python3 ru build examples/array_sort.ru -o bin/array_sort
	python3 ru build examples/objects.ru -o bin/objects
	python3 ru build examples/students.ru -o bin/students
	python3 ru build examples/unicode_slices.ru -o bin/unicode_slices
	python3 ru build examples/entry.ru -o bin/entry
	python3 ru build examples/modules/main.ru -o bin/modules --emit-c dist/modules.c
	python3 ru build examples/checked_io.ru -o bin/checked_io
	python3 ru build examples/recovery.ru -o bin/recovery --emit-c dist/recovery.c
	python3 ru build examples/closures.ru -o bin/closures --emit-c dist/closures.c
	python3 ru build examples/contest_sum_eof.ru -o bin/contest_sum_eof --emit-c dist/contest_sum_eof.c
	python3 ru build examples/contest_prefix_sum.ru -o bin/contest_prefix_sum --emit-c dist/contest_prefix_sum.c
	python3 ru build examples/contest_line_words.ru -o bin/contest_line_words --emit-c dist/contest_line_words.c
	python3 ru build examples/contest_stable_records.ru -o bin/contest_stable_records --emit-c dist/contest_stable_records.c
# Standalone CommonJS outputs; Node is needed only to syntax-check/run them.
examples-js:
	@set -e; for source in examples/*.ru; do \
		output="dist/$$(basename "$$source" .ru).js"; \
		python3 ru build "$$source" --target js -o "$$output"; \
		node --check "$$output"; \
	done
	python3 ru build examples/modules/main.ru --target js -o dist/modules.js
	node --check dist/modules.js
clean:
	python3 -c "import pathlib,shutil; [shutil.rmtree(p) for p in pathlib.Path('.').rglob('__pycache__')]"

# Optional editor checks; the language test target needs no Emacs installation.
test-emacs:
	$(EMACS) -Q --batch -L emacs --eval '(setq byte-compile-error-on-warn t)' -f batch-byte-compile emacs/ru-lang-mode.el emacs/ru-lang-mode-tests.el
	$(EMACS) -Q --batch -L emacs -l emacs/ru-lang-mode-tests.el -f ert-run-tests-batch-and-exit

# 如书: local, offline notebook UI and editor tests.
.PHONY: notebook test-notebook
notebook:
	python3 -m rushu
test-notebook:
	python3 -m unittest discover -s tests -p "test_rushu*.py" -v
	node --test rushu/tests/*.mjs
