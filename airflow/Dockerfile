# airflow/Dockerfile
# Custom Airflow 2.7.2 image with dbt, DuckDB, and project dependencies.
# Base: official apache/airflow:2.7.2 (Python 3.11, non-root user uid=50000)

FROM apache/airflow:2.7.2

COPY requirements.txt /tmp/airflow-requirements.txt
RUN pip install --no-cache-dir --user -r /tmp/airflow-requirements.txt

COPY ../connectors /opt/airflow/project/connectors
COPY ../scripts /opt/airflow/project/scripts
COPY ../dbt_project /opt/airflow/project/dbt_project

ENV PYTHONPATH="/opt/airflow/project:${PYTHONPATH}"
ENV DBT_PROFILES_DIR="/opt/airflow/project/dbt_project"

WORKDIR /opt/airflow/project/dbt_project