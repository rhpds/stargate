FROM node:22-alpine AS frontend-build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

FROM registry.access.redhat.com/ubi9/python-39:latest

USER 0
RUN curl -sL "https://mirror.openshift.com/pub/openshift-v4/clients/ocp/stable/openshift-client-linux-amd64-rhel8.tar.gz" \
    | tar xzf - -C /usr/local/bin oc kubectl && \
    chmod +x /usr/local/bin/oc /usr/local/bin/kubectl
USER 1001

WORKDIR /opt/app-root/src

COPY pyproject.toml .
RUN pip install --no-cache-dir \
    pydantic==2.13.3 pyyaml==6.0.3 jsonschema==4.25.1 \
    fastapi==0.128.8 uvicorn==0.39.0 psycopg2-binary==2.9.12 \
    sqlalchemy==2.0.49 slowapi==0.1.9 prometheus-client==0.25.0 alembic==1.16.5

COPY engine/ engine/
COPY collectors/ collectors/
COPY proposals/ proposals/
COPY api/ api/
COPY db/ db/
COPY events/ events/
COPY constraints/ constraints/
COPY rubrics/ rubrics/
COPY remediations/ remediations/
COPY prompts/ prompts/
COPY evidence-schemas/ evidence-schemas/
COPY cli/ cli/
COPY --from=frontend-build /app/dist frontend/dist/
RUN mkdir -p scan-history

EXPOSE 8090

CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8090"]
