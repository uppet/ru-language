.PHONY: test examples clean
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
clean:
	python3 -c "import pathlib,shutil; [shutil.rmtree(p) for p in pathlib.Path('.').rglob('__pycache__')]"
