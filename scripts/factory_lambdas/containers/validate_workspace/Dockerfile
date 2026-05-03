FROM public.ecr.aws/lambda/python:3.12

# terraform
RUN dnf install -y unzip wget && \
    wget -q https://releases.hashicorp.com/terraform/1.7.5/terraform_1.7.5_linux_amd64.zip && \
    unzip -q terraform_1.7.5_linux_amd64.zip && \
    mkdir -p /opt/bin && mv terraform /opt/bin/terraform && \
    rm terraform_1.7.5_linux_amd64.zip

# node + typescript
RUN dnf install -y nodejs npm && \
    npm install -g typescript@5 --prefix /opt/node && \
    ln -sf /opt/node/lib/node_modules/typescript/bin/tsc /opt/bin/tsc

# Python tooling pre-installed so warm containers skip pip install
RUN pip install --no-cache-dir ruff mypy pytest pytest-asyncio httpx anyio alembic

COPY tsc-runner.js /opt/node/tsc-runner.js
COPY common/  ${LAMBDA_TASK_ROOT}/common/
COPY validate_workspace.py ${LAMBDA_TASK_ROOT}/

CMD ["validate_workspace.handler"]
