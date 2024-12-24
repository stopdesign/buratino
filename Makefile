BASE_DIR = $(CURDIR)

VENV = . $(BASE_DIR)/.venv/bin/activate;
RUN = $(VENV) python
SRC = $(BASE_DIR)/src

FMT = printf "\033[34m%-20s\033[0m %s\n"
RGX = /^[0-9a-zA-Z_-]+:.*?\#/

help :: # Show this message
	@awk '{FS=": #"} $(RGX) {$(FMT),$$1,$$2}' $(MAKEFILE_LIST)

clean: # Clean project
	find . -name "*.pyc" -delete
	find . -name "*.orig" -delete

pip: # Install python dependencies
	$(VENV) pip install -r $(BASE_DIR)/requirements.txt \
	--upgrade --no-python-version-warning

.SILENT: run
run: # Run the default application
	$(RUN) $(SRC)/server.py

.SILENT: count
count: # Count code lines with cloc
	cloc src/ --hide-rate \
		--exclude-dir=migrations,libs,plugins \
		--exclude-lang=SVG,JSON,YAML,Text,make,Markdown,TOML,INI,"PO File" \
		--not-match-f='min.js|min.css|bootstrap|icons.css' \
		--quiet

