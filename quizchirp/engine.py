import asyncio
import json
import logging
from .config import Settings
from .answers import ANSWERS
from pathlib import Path
from contextlib import suppress

from openai_codex.generated.v2_all import SkillsListResponse, GetAccountRateLimitsResponse
from openai_codex.errors import MethodNotFoundError

from openai_codex import ApprovalMode, AsyncCodex, CodexConfig, LocalImageInput, Sandbox, TextInput

ACCESS_UNVERIFIED = "Unable to verify; trigger to retry"

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["answer"],
          "properties": {"answer": {"type": "string", "enum": list(ANSWERS)}}}
PROMPT = (
    "Read the images in order, combining continuations and overlapping content. "
    "Follow these two stages in order.\n\n"
    "1. Select a question before solving. Consider questions in natural reading order. "
    "A question is eligible only if it is a single-answer question with 2 to 6 choices, "
    "and its full question, all choices, and required supporting material are available across the images. "
    "Skip incomplete questions, questions of other types like multiple-answer questions or questions outside this choice-count range; "
    "continue to later questions instead of returning FAIL because an earlier question is ineligible. "
    "Never truncate choices to make a question eligible. "
    "Select the first eligible question, regardless of its difficulty or whether you can solve it. "
    "Return FAIL at this stage only if no eligible question exists anywhere in the images.\n\n"
    "2. Solve only the selected question. Once selected, do not switch to a later question. "
    "Return FAIL if you cannot determine a unique correct choice, including when no choice is correct "
    "or more than one choice is correct. Otherwise return that one choice. "
    "Map choices in reading order to A, B, C, D, E, F regardless of labels, "
    "using only as many letters as there are choices.\n\n"
    "Examples: A complete 7-choice question followed by a complete 4-choice single-answer question: "
    "skip the first and select the second. Two complete single-answer questions with 5 and 4 choices: "
    "select the first. If the first eligible question has no correct choice but a later question is "
    "solvable, return FAIL for the selected question; do not answer the later one."
)


RUNTIME_OVERRIDES = (
    'skills.include_instructions=false',
    'skills.bundled.enabled=false',
    'features.skill_search=false',
    'features.memories=false',
    'project_doc_max_bytes=0',
    'features.shell_tool=true',
    'web_search="live"',
    'cli_auth_credentials_store="file"',
)


class Engine:
    def __init__(self, workdir, settings=None):
        self.settings = settings or Settings()
        self.workdir = str(Path(workdir).resolve())
        codex_home = Path(workdir).resolve() / "codex"
        codex_home.mkdir(parents=True, exist_ok=True)
        self.client = AsyncCodex(CodexConfig(codex_bin=self.settings.codex_bin or None,
            cwd=str(workdir), client_name="quizchirp",
            env={"CODEX_HOME": str(codex_home)},
            config_overrides=RUNTIME_OVERRIDES))

    async def check_access(self, refresh_token=False):
        account = await self.client.account(refresh_token=refresh_token)
        if account.account is None and account.requires_openai_auth:
            return "Sign-in required"
        if account.account is None or account.account.root.type != "chatgpt":
            # The ChatGPT usage endpoint cannot validate API-key/custom providers.
            return ACCESS_UNVERIFIED
        try:
            limits = await self.client._client.request(
                "account/rateLimits/read", {"excludeResetCreditDetails": True},
                response_model=GetAccountRateLimitsResponse,
            )
        except MethodNotFoundError:
            return ACCESS_UNVERIFIED
        if (limits.ordinary_usage_allowed is False
                or limits.rate_limits.rate_limit_reached_type is not None
                or limits.rate_limits.spend_control_reached is True):
            return "Usage limit reached"
        if limits.ordinary_usage_allowed is True:
            return "Ready"
        # Percentages and past reset times are not proof of recovered access.
        return ACCESS_UNVERIFIED

    async def solve(self, paths):
        if isinstance(paths, (str, Path)):
            paths = [paths]
        paths = list(paths)
        if not paths:
            return "FAIL"
        await self.client._ensure_initialized()
        skills = await self.client._client.request(
            "skills/list", {"cwds": [self.workdir], "forceReload": True},
            response_model=SkillsListResponse,
        )
        disabled = [{"name": name, "enabled": False} for name in sorted({
            skill.name for entry in skills.data for skill in entry.skills
        })]
        thread = await self.client.thread_start(
            config={"skills": {"config": disabled}},
            ephemeral=not self.settings.retain_history, model=self.settings.model or None, sandbox=Sandbox.workspace_write, approval_mode=ApprovalMode.auto_review,
            developer_instructions="Solve the image-based practice question and return the final answer in the required schema.",
        )
        turn = await thread.turn([TextInput(PROMPT), *(LocalImageInput(str(path)) for path in paths)],
                                 output_schema=SCHEMA, effort=self.settings.thinking_effort or None)
        logging.getLogger(__name__).info("Screenshots=%s thread=%s turn=%s", paths, thread.id, turn.id)
        try:
            result = await turn.run()
        except asyncio.CancelledError:
            with suppress(Exception):
                await asyncio.wait_for(turn.interrupt(), 2)
            raise
        if result.error:
            raise RuntimeError(result.error.message)
        if result.status.value != "completed":
            return "FAIL"
        try:
            value = json.loads(result.final_response or "")
        except ValueError:
            return "FAIL"
        if isinstance(value, dict) and set(value) == {"answer"} and value["answer"] in ANSWERS:
            return value["answer"]
        return "FAIL"
