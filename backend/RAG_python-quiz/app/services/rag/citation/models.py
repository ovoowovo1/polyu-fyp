from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class Evidence(StrictModel):
    chunk_id: str = Field(min_length=1)
    quote: str = Field(min_length=1)


class DraftBlock(StrictModel):
    id: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9_-]+$")
    markdown: str = Field(min_length=1)
    kind: Literal["factual", "structural"]
    evidence: list[Evidence] = Field(default_factory=list)


class AnswerDraft(StrictModel):
    blocks: list[DraftBlock]
    limitations: list[str]

    @model_validator(mode="after")
    def unique_ids(self):
        if len({b.id for b in self.blocks}) != len(self.blocks):
            raise ValueError("Duplicate block IDs")
        if any(not value for value in self.limitations):
            raise ValueError("Limitations must be non-empty")
        return self


class BlockVerdict(StrictModel):
    id: str = Field(min_length=1)
    supported: bool
    reason: str = Field(min_length=1)


class Verification(StrictModel):
    blocks: list[BlockVerdict]
    missing_topics: list[str]

    @model_validator(mode="after")
    def unique_ids(self):
        if len({b.id for b in self.blocks}) != len(self.blocks):
            raise ValueError("Duplicate verdict IDs")
        if any(not value for value in self.missing_topics):
            raise ValueError("Missing topics must be non-empty")
        return self
