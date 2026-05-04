FROM public.ecr.aws/lambda/python:3.12

RUN dnf install -y unzip wget tar gzip git nodejs npm && \
    wget -q https://releases.hashicorp.com/terraform/1.7.5/terraform_1.7.5_linux_amd64.zip && \
    unzip -q terraform_1.7.5_linux_amd64.zip && \
    mkdir -p /opt/bin && mv terraform /opt/bin/terraform && \
    rm terraform_1.7.5_linux_amd64.zip && \
    npm install -g typescript@5 --prefix /opt/node && \
    ln -sf /opt/node/lib/node_modules/typescript/bin/tsc /opt/bin/tsc

RUN pip install --no-cache-dir ruff mypy pytest pytest-asyncio httpx anyio alembic \
    fastapi pydantic pydantic-settings sqlalchemy asyncpg python-jose[cryptography]

ENV PATH="/opt/bin:${PATH}"

COPY scripts/factory_lambdas/containers/validate_v2/validate_v2.py  ${LAMBDA_TASK_ROOT}/

CMD ["validate_v2.handler"]
