BASE_DIR = $(CURDIR)

VENV = . $(BASE_DIR)/.venv/bin/activate;
RUN = $(VENV) python
SRC = $(BASE_DIR)/src

FMT = printf "\033[34m%-20s\033[0m %s\n"
RGX = /^[0-9a-zA-Z_-]+:.*?\#/

AUDIO_DIR = ./audio_log

help :: # Show this message
	@awk '{FS=": #"} $(RGX) {$(FMT),$$1,$$2}' $(MAKEFILE_LIST)

clean: # Clean project
	find . -name "*.pyc" -delete
	find . -name "*.orig" -delete

pip: # Install python dependencies
	$(VENV) pip install -r $(BASE_DIR)/requirements.txt --upgrade 

.SILENT: run
run: # Run the default application
	$(RUN) $(SRC)/rtc_server.py

.SILENT: count
count: # Count code lines with cloc
	cloc src/ --hide-rate \
		--exclude-dir=migrations,libs,plugins \
		--exclude-lang=SVG,JSON,YAML,Text,make,Markdown,TOML,INI,"PO File" \
		--not-match-f='min.js|min.css|bootstrap|icons.css' \
		--quiet

.SILENT: play
play: # Play the last n-th audio log
	@INDEX=$(or $(word 2, $(MAKECMDGOALS)), 1); \
	FILE=$$(ls -1 "$(AUDIO_DIR)" | sort | tail -n $${INDEX} | head -n 1); \
	if [ -n "$${FILE}" ]; then play "$(AUDIO_DIR)/$${FILE}"; \
	else echo "No files found in $(AUDIO_DIR)"; exit 1; fi

