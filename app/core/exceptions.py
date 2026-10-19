class LLMOutputError(Exception):
    pass


class ToolError(Exception):
    pass


class AgentStepLimitError(Exception):
    pass


class StudentNotFoundError(Exception):
    pass
