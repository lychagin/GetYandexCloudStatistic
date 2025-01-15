ARG PYTHON_VERSION=3.11.2
FROM python:${PYTHON_VERSION}-slim as base

ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV TZ Europe/Moscow

LABEL "app.install.path"="${APP_INSTALL_PATH}"

RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /code

RUN apt-get update \
    && apt-get -y install libpq-dev gcc

COPY requirements.txt .
RUN pip install --user -r requirements.txt

COPY . .

# Run the application.
CMD [ "python", "-u", "./main.py" ]
