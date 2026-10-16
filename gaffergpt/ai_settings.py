"""Model, reasoning effort and limits for every AI request, read from the environment.

PEP_AI_MODEL and PEP_AI_EFFORT set the default for all AI work. A single job can
be overridden with PEP_<JOB>_MODEL or PEP_<JOB>_EFFORT, where JOB is COACH (tactical
advice), RECAP (reading submitted results) or REPORTER (article writing).
"""
import logging
import os

DEFAULT_MODEL='gpt-6-luna'
DEFAULT_EFFORT='max'
EFFORTS=('minimal','low','medium','high','xhigh','max')
log=logging.getLogger(__name__)


def model(job=''):
    return os.getenv(f'PEP_{job}_MODEL') or os.getenv('PEP_AI_MODEL') or DEFAULT_MODEL


def effort(job=''):
    value=(os.getenv(f'PEP_{job}_EFFORT') or os.getenv('PEP_AI_EFFORT') or DEFAULT_EFFORT).strip().lower()
    if value not in EFFORTS:
        # A typo in Railway must not take every AI feature offline.
        log.warning('Unknown reasoning effort %r; using %s',value[:20],DEFAULT_EFFORT)
        return DEFAULT_EFFORT
    return value


def output_tokens():
    """Shared allowance for thinking plus the written answer; high effort needs the room."""
    return max(2000,int(os.getenv('PEP_AI_MAX_OUTPUT_TOKENS','32000')))


def timeout():
    return max(30,int(os.getenv('PEP_AI_TIMEOUT_SECONDS','300')))
