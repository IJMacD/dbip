.PHONY: install run test docker-build docker-run clean

install:
	pip install -r requirements.txt
	yarn install

run:
	python main.py --api-key $${IPLOCATE_API_KEY}

test:
	python -m pytest tests/ -v

docker-build:
	docker build -t dbip .

docker-run:
	docker run -p 8000:8000 -e IPLOCATE_API_KEY=*** dbip

clean:
	rm -rf __pycache__ .pytest_cache tests/__pycache__
	find . -name '*.pyc' -delete
