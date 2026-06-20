from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ConversationMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str = Field(min_length=1)
    timestamp: datetime | None = None
