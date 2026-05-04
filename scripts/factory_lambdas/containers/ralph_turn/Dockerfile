FROM public.ecr.aws/lambda/python:3.12

# Tools the implementer will need: git, tar, Node 20, Claude Code CLI
RUN dnf install -y nodejs npm git tar gzip openssh-clients && \
    npm install -g @anthropic-ai/claude-code

# Lightweight Python deps the implementer's tests may need pre-installed
RUN pip install --no-cache-dir ruff mypy pytest pytest-asyncio httpx anyio alembic \
    fastapi pydantic pydantic-settings sqlalchemy asyncpg python-jose[cryptography]

# .factory artifacts (system prompts, schema)
COPY .factory/                                                      ${LAMBDA_TASK_ROOT}/.factory/

# Container code
COPY scripts/factory_lambdas/containers/ralph_turn/allowlist.py     ${LAMBDA_TASK_ROOT}/
COPY scripts/factory_lambdas/containers/ralph_turn/git_io.py        ${LAMBDA_TASK_ROOT}/
COPY scripts/factory_lambdas/containers/ralph_turn/ralph_turn.py    ${LAMBDA_TASK_ROOT}/

CMD ["ralph_turn.handler"]
