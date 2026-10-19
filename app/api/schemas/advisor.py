from typing import Annotated

from pydantic import BaseModel, StringConstraints

StudentMessage = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000)
]
StudentId = Annotated[
    str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[Ss]\d{4}$")
]


class AdviseRequest(BaseModel):
    message: StudentMessage
    student_id: StudentId
