.PHONY: test test-emacs examples clean
EMACS ?= emacs
test:
	python3 -m unittest discover -s tests -v
examples:
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
clean:
	python3 -c "import pathlib,shutil; [shutil.rmtree(p) for p in pathlib.Path('.').rglob('__pycache__')]"

# Optional editor checks; the language test target needs no Emacs installation.
test-emacs:
	$(EMACS) -Q --batch -L emacs --eval '(setq byte-compile-error-on-warn t)' -f batch-byte-compile emacs/ru-lang-mode.el emacs/ru-lang-mode-tests.el
	$(EMACS) -Q --batch -L emacs -l emacs/ru-lang-mode-tests.el -f ert-run-tests-batch-and-exit
